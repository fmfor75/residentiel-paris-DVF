#!/usr/bin/env python3
"""
process_dvf.py v10

Données enrichies :
  - by_year     : median, mean, q1, q3, min, max, p10, p90, surf_mean, surf_median, count
  - by_quarter  : idem, clé "YYYY-QN"
  - by_typo     : idem + by_year + by_quarter pour chaque typo
  - typo_share  : nb transactions et part de marché par typo dans le secteur

Cache historique :
  - data/dvf_hist.json : mutations 2014–2019 (calculé une seule fois)
  - data/dvf_paris.json : JSON final du dashboard (recalculé à chaque run)
"""

import os, json, gzip, io, time, requests, re
from datetime import datetime

# ── CONFIG ────────────────────────────────────────────────────────

CQUEST_MILLESIMES = ["202004", "201910", "201904"]
CQUEST_NOMS = [
    "valeursfoncieres-{annee}.txt.gz",
    "ValeursFoncieres-{annee}.txt.gz",
]
GEODVF_URL = "https://files.data.gouv.fr/geo-dvf/latest/csv/{annee}/departements/75.csv.gz"
ANNEES_HIST    = list(range(2014, 2020))
ANNEES_RECENTS = list(range(2020, 2026))
HIST_CACHE = "data/dvf_hist.json"
OUTPUT     = "data/dvf_paris.json"

# ── RÉFÉRENTIELS ──────────────────────────────────────────────────

CODE_TO_ARR = {f"751{str(i).zfill(2)}": i for i in range(1, 21)}
ARR_LABELS  = {i: ("1er" if i == 1 else f"{i}e") for i in range(1, 21)}
ARR_TO_SECT = {1:1,2:1,3:2,4:2,5:3,6:4,7:4,8:5,9:6,10:7,11:13,12:8,13:10,14:10,15:9,16:5,17:6,18:7,19:7,20:13}
SECTEURS = {
    1:{"nom":"Louvre – Opéra","arrLabel":"1er, 2e"},
    2:{"nom":"Marais – Bastille","arrLabel":"3e, 4e"},
    3:{"nom":"Île de la Cité – Luxembourg","arrLabel":"5e, 6e"},
    4:{"nom":"Saint-Germain – Invalides","arrLabel":"6e, 7e"},
    5:{"nom":"Champs-Élysées – Trocadéro","arrLabel":"8e, 16e"},
    6:{"nom":"Opéra – Grands Boulevards","arrLabel":"9e, 17e"},
    7:{"nom":"Montmartre – Belleville","arrLabel":"10e, 18e, 19e"},
    8:{"nom":"Nation – Vincennes","arrLabel":"12e"},
    9:{"nom":"Grenelle – Convention","arrLabel":"15e"},
    10:{"nom":"Montrouge – Alésia","arrLabel":"13e, 14e"},
    11:{"nom":"Épinettes – Batignolles","arrLabel":"17e"},
    12:{"nom":"Buttes-Chaumont","arrLabel":"19e"},
    13:{"nom":"Ménilmontant – Oberkampf","arrLabel":"11e, 20e"},
    14:{"nom":"Ivry – Tolbiac – Gobelins","arrLabel":"13e"},
}
TYPOLOGIES = [
    {"id":"T1","surfMin":9,"surfMax":30},
    {"id":"T2","surfMin":30,"surfMax":50},
    {"id":"T3","surfMin":50,"surfMax":70},
    {"id":"T4","surfMin":70,"surfMax":100},
    {"id":"T5","surfMin":100,"surfMax":400},
]

# ── HELPERS ───────────────────────────────────────────────────────

def to_f(s):
    try: return float(str(s).replace(',','.').replace(' ','')) if s else 0.0
    except: return 0.0

def get_quarter(date_str):
    try:
        d = datetime.strptime(date_str[:10], '%Y-%m-%d')
        q = (d.month - 1) // 3 + 1
        return f'{d.year}-Q{q}'
    except:
        return None

def consolidate(mutations, annee):
    result = []; counts = {'Appartement':0,'Maison':0,'Autre':0,'sans_surf':0}
    for m in mutations.values():
        if m['val'] <= 0: continue
        if not m['locaux']: counts['sans_surf'] += 1; continue
        p = max(m['locaux'], key=lambda l: l['surf'])
        surf = p['surf']
        if surf <= 0: continue
        ppm2 = m['val'] / surf
        if ppm2 < 500 or ppm2 > 60000: continue
        tl = p['type']; ct = p.get('code_type', 0)
        if 'appartement' in tl.lower() or ct == 2: tl = 'Appartement'; counts['Appartement'] += 1
        elif 'maison' in tl.lower() or ct == 1: tl = 'Maison'; counts['Maison'] += 1
        else: counts['Autre'] += 1; continue
        result.append({'arr':m['arr'],'sect':ARR_TO_SECT.get(m['arr']),'val':m['val'],
                       'surf':surf,'type':tl,'nbpp':p.get('nbpp',0),'date':m['date'],'annee':annee})
    print(f"    → {len(result)} | Appart:{counts['Appartement']} Maison:{counts['Maison']} SansSurf:{counts['sans_surf']}")
    return result

# ── PARSERS ───────────────────────────────────────────────────────

HEADER_DETECT_KEYS = ['date mutation', 'nature mutation', 'valeur fonciere']

def detect_col_indices(header_line, sep='|'):
    cols = [h.strip().strip('"').lower() for h in header_line.split(sep)]
    def find(keywords):
        for kw in keywords:
            for i,c in enumerate(cols):
                if kw in c: return i
        return -1
    return {
        'date':   find(['date mutation']),
        'nature': find(['nature mutation']),
        'val':    find(['valeur fonciere']),
        'dep':    find(['code departement']),
        'comm':   find(['code commune']),
        'cp':     find(['code postal']),
        'plan':   find(['no plan']),
        'type':   find(['type local']),
        'surf':   find(['surface reelle bati']),
        'nbpp':   find(['nombre pieces']),
    }

def parse_txt_pipe(lines, annee):
    if not lines: return []
    header_idx = -1
    for i, line in enumerate(lines[:10]):
        low = line.lower()
        if any(k in low for k in HEADER_DETECT_KEYS):
            header_idx = i; break

    if header_idx >= 0:
        idx = detect_col_indices(lines[header_idx], '|')
        start = header_idx + 1
        print(f"    Indices: dep={idx['dep']} comm={idx['comm']} val={idx['val']} surf={idx['surf']} type={idx['type']}")
    else:
        idx = {'date':8,'nature':9,'val':10,'dep':18,'comm':19,'cp':16,'plan':21,'type':35,'surf':37,'nbpp':38}
        start = 0

    mutations = {}
    skipped = 0
    for line in lines[start:]:
        if not line.strip(): continue
        c = line.split('|')
        if len(c) < 15: continue
        def g(i): return c[i].strip().strip('"') if 0<=i<len(c) else ''

        dep = g(idx['dep']).zfill(2) if idx['dep']>=0 else '??'
        if dep != '75': skipped += 1; continue

        comm = g(idx['comm']).zfill(3) if idx['comm']>=0 else ''
        code_5 = f"75{comm}"
        arr_num = CODE_TO_ARR.get(code_5)
        if arr_num is None:
            cp = g(idx['cp']) if idx['cp']>=0 else ''
            if cp.startswith('750') and len(cp)==5:
                try:
                    n = int(cp[3:])
                    if 1<=n<=20: arr_num = n
                except: pass
        if arr_num is None: continue
        nat = g(idx['nature']).lower() if idx['nature']>=0 else ''
        if 'vente' not in nat: continue

        val = to_f(g(idx['val'])) if idx['val']>=0 else 0
        # Surface Carrez : première valeur décimale (avec virgule) dans cols 24-32
        surf = 0.0
        for ci in range(24, min(33, len(c))):
            v = c[ci].strip()
            if ',' in v or ('.' in v and v.replace('.','').isdigit()):
                try:
                    f = float(v.replace(',','.'))
                    if f > 5: surf = f; break
                except: pass
        if surf == 0.0:
            bati = to_f(g(idx['surf'])) if idx['surf']>=0 else 0
            surf = bati

        tl_idx = idx['type']
        tl = g(tl_idx) if tl_idx>=0 else ''
        if tl.isdigit() and tl_idx+1 < len(c): tl = g(tl_idx+1)

        try: nbpp = int(float(g(idx['nbpp']))) if idx['nbpp']>=0 and g(idx['nbpp']) else 0
        except: nbpp = 0

        date = g(idx['date'])[:10] if idx['date']>=0 else ''
        if '/' in date:
            p = date.split('/')
            if len(p)==3: date = f"{p[2]}-{p[1].zfill(2)}-{p[0].zfill(2)}"

        plan = g(idx['plan']) if idx['plan']>=0 else ''
        mut_id = f"{date}_{int(val) if val else 0}_{code_5}_{plan}"
        key = f"{arr_num}_{mut_id}"

        if key not in mutations:
            mutations[key] = {'arr':arr_num,'val':val,'date':date,'locaux':[]}
        if val > 0: mutations[key]['val'] = val
        if surf > 0 or tl:
            mutations[key]['locaux'].append({'surf':surf,'type':tl,'nbpp':nbpp})

    print(f"    {len(mutations)} mutations Paris | {skipped} hors Paris")
    return consolidate(mutations, annee)

def parse_csv_geodvf(lines, annee):
    H = [h.strip().lower() for h in lines[0].split(',')]
    def gi(n): return next((i for i,h in enumerate(H) if n in h),-1)
    iMut=gi('id_mutation'); iDate=gi('date_mutation'); iNat=gi('nature_mutation')
    iVal=gi('valeur_fonciere'); iCode=gi('code_commune')
    iC1=gi('lot1_surface_carrez'); iC2=gi('lot2_surface_carrez')
    iCodeT=gi('code_type_local'); iType=gi('type_local')
    iSurf=gi('surface_reelle_bati'); iNbPP=gi('nombre_pieces_principales')
    print(f"    Colonnes: val={iVal} code={iCode} type={iType} surf={iSurf}")
    mutations = {}
    for line in lines[1:]:
        if not line.strip(): continue
        c = line.split(',')
        if len(c) < 32: continue
        def g(i): return c[i].strip().strip('"') if 0<=i<len(c) else ''
        arr = CODE_TO_ARR.get(g(iCode))
        if not arr: continue
        if 'vente' not in g(iNat).lower(): continue
        val=to_f(g(iVal)); surf=to_f(g(iSurf)); c1=to_f(g(iC1)); c2=to_f(g(iC2))
        surf = c1 if c1>0 else (c2 if c2>0 else surf)
        tl=g(iType)
        try: ct=int(float(g(iCodeT) or '0'))
        except: ct=0
        try: nbpp=int(float(g(iNbPP) or '0'))
        except: nbpp=0
        mut_id=g(iMut) or f"{g(iDate)}_{val}_{g(iCode)}"
        key=f"{arr}_{mut_id}"
        if key not in mutations:
            mutations[key]={'arr':arr,'val':val,'date':g(iDate)[:10],'locaux':[]}
        if val>0: mutations[key]['val']=val
        if surf>0: mutations[key]['locaux'].append({'surf':surf,'type':tl,'code_type':ct,'nbpp':nbpp})
    return consolidate(mutations, annee)

# ── TÉLÉCHARGEMENT ────────────────────────────────────────────────

def find_cquest_url(annee):
    for mil in CQUEST_MILLESIMES:
        for nom_tpl in CQUEST_NOMS:
            url = f"https://data.cquest.org/dgfip_dvf/{mil}/{nom_tpl.format(annee=annee)}"
            try:
                r = requests.head(url, timeout=15, allow_redirects=True)
                if r.status_code==200 and int(r.headers.get('content-length',0))>100000:
                    print(f"    ✓ {url} ({int(r.headers.get('content-length',0))/1024/1024:.1f} Mo)")
                    return url
            except: pass
    return None

def download_cquest(annee):
    print(f"  ↓ {annee} [cquest.org]")
    url = find_cquest_url(annee)
    if not url: print(f"    ⚠ Non trouvé"); return []
    try:
        r = requests.get(url, timeout=300); r.raise_for_status()
        print(f"    {len(r.content)/1024/1024:.1f} Mo")
        for enc in ['utf-8','latin-1']:
            try:
                with gzip.open(io.BytesIO(r.content),'rt',encoding=enc,errors='replace') as f:
                    text = f.read()
                break
            except Exception as e:
                if enc=='latin-1': print(f"    ⚠ {e}"); return []
        lines = text.split('\n')
        if len(lines)>1: print(f"    L0: {lines[0][:80]}")
        return parse_txt_pipe(lines, annee)
    except Exception as e:
        print(f"    ⚠ {e}"); return []

def download_recent(annee):
    url = GEODVF_URL.format(annee=annee)
    print(f"  ↓ {annee} [geo-dvf]")
    try:
        r = requests.get(url, timeout=180); r.raise_for_status()
        print(f"    {len(r.content)/1024/1024:.1f} Mo")
        with gzip.open(io.BytesIO(r.content),'rt',encoding='utf-8',errors='replace') as f:
            return parse_csv_geodvf(f.read().split('\n'), annee)
    except Exception as e:
        print(f"    ⚠ {e}"); return []

# ── CACHE ─────────────────────────────────────────────────────────

def load_cache():
    if not os.path.exists(HIST_CACHE): return None
    try:
        with open(HIST_CACHE,'r',encoding='utf-8') as f: data=json.load(f)
        muts=data.get('mutations',[]); annees=data.get('annees',[])
        print(f"  ✓ Cache : {len(muts):,} mutations ({annees})")
        return muts
    except Exception as e:
        print(f"  ⚠ Cache invalide ({e})"); return None

def save_cache(muts):
    annees=sorted(set(m['annee'] for m in muts))
    with open(HIST_CACHE,'w',encoding='utf-8') as f:
        json.dump({'annees':annees,'generated_at':datetime.utcnow().isoformat()+'Z','mutations':muts},
                  f,ensure_ascii=False,separators=(',',':'))
    print(f"  ✓ Cache sauvegardé ({os.path.getsize(HIST_CACHE)/1024/1024:.1f} Mo, {len(muts):,} mutations)")

# ── STATS ─────────────────────────────────────────────────────────

def ppm2(m): return m['val']/m['surf']

def compute_stats_from_prices(prices, surfs):
    """Calcule toutes les stats à partir d'une liste de prix/m² et de surfaces."""
    n = len(prices)
    if n < 5: return None
    p = sorted(prices); s = sorted(surfs)
    return {
        'count':  n,
        'mean':   round(sum(p)/n),
        'median': round(p[n//2]),
        'min':    round(p[0]),
        'max':    round(p[-1]),
        'q1':     round(p[n//4]),
        'q3':     round(p[3*n//4]),
        'p10':    round(p[max(0,n//10)]),
        'p90':    round(p[min(n-1,9*n//10)]),
        'surf_mean':   round(sum(surfs)/n, 1),
        'surf_median': round(s[n//2], 1),
    }

def compute_stats(muts):
    if len(muts) < 5: return None
    prices = [ppm2(m) for m in muts]
    surfs  = [m['surf'] for m in muts]
    return compute_stats_from_prices(prices, surfs)

def compute_by_period(muts, key_fn):
    """Groupe par clé temporelle (année ou trimestre) et calcule les stats."""
    groups = {}
    for m in muts:
        k = key_fn(m)
        if k: groups.setdefault(k, []).append(m)
    result = {}
    for k, ms in sorted(groups.items()):
        if len(ms) < 5: continue
        prices = [ppm2(m) for m in ms]; surfs = [m['surf'] for m in ms]
        n = len(prices); p = sorted(prices)
        result[k] = {
            'count':  n,
            'mean':   round(sum(p)/n),
            'median': round(p[n//2]),
            'min':    round(p[0]),
            'max':    round(p[-1]),
            'q1':     round(p[n//4]),
            'q3':     round(p[3*n//4]),
            'surf_mean': round(sum(surfs)/n, 1),
        }
    return result

def compute_by_year(muts):
    return compute_by_period(muts, lambda m: (m.get('date') or '')[:4] if re.match(r'^20[01]\d', (m.get('date') or '')[:4]) else None)

def compute_by_quarter(muts):
    return compute_by_period(muts, lambda m: get_quarter(m.get('date','')))

def get_typo(surf):
    for t in TYPOLOGIES:
        if t['surfMin'] <= surf < t['surfMax']: return t['id']
    return None

def build_typo_stats(muts):
    """Stats par typologie + part de marché."""
    by_typo = {}
    for m in muts:
        t = get_typo(m['surf'])
        if t: by_typo.setdefault(t, []).append(m)
    total = sum(len(v) for v in by_typo.values())
    result = {}
    for t_id, ms in by_typo.items():
        s = compute_stats(ms)
        if s:
            result[t_id] = {
                **s,
                'share': round(len(ms)/total*100, 1) if total > 0 else 0,
                'by_year':    compute_by_year(ms),
                'by_quarter': compute_by_quarter(ms),
            }
    # Typo la plus transactée
    if result:
        top = max(result.items(), key=lambda x: x[1]['count'])
        result['_top_typo'] = top[0]
    return result

def build_group_stats(all_muts, key_fn, labels):
    groups = {}
    for m in all_muts:
        k = key_fn(m)
        if k is not None: groups.setdefault(k, []).append(m)
    result = {}
    for k, muts in groups.items():
        by_type = {}
        for tb in ['Appartement', 'Maison']:
            f = [m for m in muts if m['type']==tb]
            s = compute_stats(f)
            if s:
                by_type[tb] = {
                    **s,
                    'by_year':    compute_by_year(f),
                    'by_quarter': compute_by_quarter(f),
                    'by_typo':    build_typo_stats(f),
                }
        result[str(k)] = {'label':labels.get(k,str(k)),'by_type':by_type,'total':len(muts)}
    return result

# ── MAIN ──────────────────────────────────────────────────────────

def main():
    os.makedirs('data', exist_ok=True)
    all_muts = []

    print('=== Données historiques 2014–2019 ===')
    hist = load_cache()
    if hist is None:
        print('  Cache absent → téléchargement data.cquest.org')
        hist = []
        for annee in ANNEES_HIST:
            hist.extend(download_cquest(annee))
            time.sleep(2)
        if hist: save_cache(hist)
        else: print('  ⚠ Historique indisponible — dashboard limité à 2020–2025')
    else:
        print('  Cache utilisé ✓')
    all_muts.extend(hist)

    print('\n=== Données récentes 2020–2025 ===')
    for annee in ANNEES_RECENTS:
        all_muts.extend(download_recent(annee))
        time.sleep(1)

    apparts = [m for m in all_muts if m['type']=='Appartement']
    maisons = [m for m in all_muts if m['type']=='Maison']
    annees_ok = sorted(set(m['annee'] for m in all_muts))
    periode = f"{min(annees_ok)}–{max(annees_ok)}" if annees_ok else "N/A"

    print(f'\n=== Total : {len(all_muts):,} · Appart:{len(apparts):,} · Maisons:{len(maisons):,} ===')
    print(f'  Années : {annees_ok}')

    print('\n=== Calcul statistiques ===')
    arr_s  = build_group_stats(all_muts, lambda m:m['arr'],  {i:f"Paris {ARR_LABELS[i]} arr." for i in range(1,21)})
    sect_s = build_group_stats(all_muts, lambda m:m['sect'], {k:f"Secteur {k} — {v['nom']}" for k,v in SECTEURS.items()})
    gs     = compute_stats(apparts)
    gby    = compute_by_year(apparts)
    gbyq   = compute_by_quarter(apparts)
    gtypo  = build_typo_stats(apparts)

    output = {
        'meta': {
            'generated_at':  datetime.utcnow().isoformat()+'Z',
            'source_hist':   'data.cquest.org/dgfip_dvf/201910 (2014–2019, cache)',
            'source_recent': 'files.data.gouv.fr/geo-dvf (2020–2025)',
            'annees':        annees_ok,
            'total_mutations': len(all_muts),
            'total_apparts': len(apparts),
            'total_maisons': len(maisons),
            'periode':       periode,
            'cache_hist':    os.path.exists(HIST_CACHE),
        },
        'global': {
            'stats':      gs,
            'by_year':    gby,
            'by_quarter': gbyq,
            'by_typo':    gtypo,
        },
        'arrondissements': arr_s,
        'secteurs':        sect_s,
        'secteurs_ref':    {str(k):v for k,v in SECTEURS.items()},
        'arr_to_sect':     {str(k):v for k,v in ARR_TO_SECT.items()},
        'typologies_ref':  TYPOLOGIES,
    }

    with open(OUTPUT,'w',encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    size_kb = os.path.getsize(OUTPUT)/1024
    print(f'\n✓ {OUTPUT} ({size_kb:.0f} Ko) — {periode}')
    if gby:
        yrs=list(gby.keys()); v0=gby[yrs[0]]['median']; v1=gby[yrs[-1]]['median']
        print(f'  Évolution {yrs[0]}→{yrs[-1]} : {(v1-v0)/v0*100:+.1f}% ({v0:,}→{v1:,} €/m²)')

if __name__=='__main__': main()

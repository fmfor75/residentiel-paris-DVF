#!/usr/bin/env python3
"""
process_dvf.py v8

Cache intelligent : 2014-2019 téléchargés une seule fois, stockés dans data/dvf_hist.json
Runs suivants : seules les années 2020+ sont re-téléchargées

Sources testées pour 2014-2019 :
  - data.cquest.org/dgfip_dvf/201904/ (plusieurs noms de fichiers possibles)
  - data.cquest.org/dgfip_dvf/202004/ (millésime plus récent)
  - Fallback : on continue sans historique
"""

import os, json, gzip, io, time, requests, re
from datetime import datetime

# ── CONFIG ────────────────────────────────────────────────────────

# Candidats pour le millésime cquest — on teste dans l'ordre
CQUEST_MILLESIMES = ["202004", "201910", "201904"]
CQUEST_NOMS       = [
    "valeursfoncieres-{annee}.txt.gz",
    "ValeursFoncieres-{annee}.txt.gz",
    "dvf-{annee}.csv.gz",
    "full-{annee}.csv.gz",
    "{annee}.txt.gz",
    "{annee}.csv.gz",
]

GEODVF_URL = "https://files.data.gouv.fr/geo-dvf/latest/csv/{annee}/departements/75.csv.gz"

ANNEES_HIST    = list(range(2014, 2020))
ANNEES_RECENTS = list(range(2020, 2026))

HIST_CACHE = "data/dvf_hist.json"
OUTPUT     = "data/dvf_paris.json"

# ── RÉFÉRENTIELS ──────────────────────────────────────────────────

CODE_TO_ARR = {f"751{str(i).zfill(2)}": i for i in range(1, 21)}
ARR_LABELS  = {i: ("1er" if i == 1 else f"{i}e") for i in range(1, 21)}
ARR_TO_SECT = {
    1:1,2:1,3:2,4:2,5:3,6:4,7:4,8:5,
    9:6,10:7,11:13,12:8,13:10,14:10,
    15:9,16:5,17:6,18:7,19:7,20:13
}
SECTEURS = {
    1: {"nom":"Louvre – Opéra","arrLabel":"1er, 2e"},
    2: {"nom":"Marais – Bastille","arrLabel":"3e, 4e"},
    3: {"nom":"Île de la Cité – Luxembourg","arrLabel":"5e, 6e"},
    4: {"nom":"Saint-Germain – Invalides","arrLabel":"6e, 7e"},
    5: {"nom":"Champs-Élysées – Trocadéro","arrLabel":"8e, 16e"},
    6: {"nom":"Opéra – Grands Boulevards","arrLabel":"9e, 17e"},
    7: {"nom":"Montmartre – Belleville","arrLabel":"10e, 18e, 19e"},
    8: {"nom":"Nation – Vincennes","arrLabel":"12e"},
    9: {"nom":"Grenelle – Convention","arrLabel":"15e"},
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

def detect_sep(line):
    """Détecte le séparateur d'une ligne CSV."""
    if '|' in line and line.count('|') > 5: return '|'
    if ';' in line and line.count(';') > 5: return ';'
    return ','

def consolidate(mutations, annee):
    result = []
    counts = {'Appartement':0,'Maison':0,'Autre':0,'sans_surf':0}
    for m in mutations.values():
        if m['val'] <= 0: continue
        if not m['locaux']: counts['sans_surf'] += 1; continue
        p = max(m['locaux'], key=lambda l: l['surf'])
        surf = p['surf']
        if surf <= 0: continue
        ppm2 = m['val'] / surf
        if ppm2 < 500 or ppm2 > 60000: continue
        tl = p['type']; ct = p.get('code_type',0)
        if 'appartement' in tl.lower() or ct==2: tl='Appartement'; counts['Appartement']+=1
        elif 'maison' in tl.lower() or ct==1: tl='Maison'; counts['Maison']+=1
        else: counts['Autre']+=1; continue
        result.append({'arr':m['arr'],'sect':ARR_TO_SECT.get(m['arr']),'val':m['val'],
                       'surf':surf,'type':tl,'nbpp':p.get('nbpp',0),'date':m['date'],'annee':annee})
    print(f"    → {len(result)} | Appart:{counts['Appartement']} Maison:{counts['Maison']} SansSurf:{counts['sans_surf']}")
    return result

# ── EXPLORATION cquest.org ────────────────────────────────────────

def find_cquest_url(annee):
    """Teste toutes les combinaisons millesime/nom pour trouver l'URL valide."""
    for mil in CQUEST_MILLESIMES:
        for nom_tpl in CQUEST_NOMS:
            nom = nom_tpl.format(annee=annee)
            url = f"https://data.cquest.org/dgfip_dvf/{mil}/{nom}"
            try:
                r = requests.head(url, timeout=15, allow_redirects=True)
                if r.status_code == 200:
                    size = int(r.headers.get('content-length',0))
                    if size > 100000:  # au moins 100 Ko
                        print(f"    ✓ Trouvé : {url} ({size/1024/1024:.1f} Mo)")
                        return url
            except:
                pass
    return None

def download_cquest(annee):
    print(f"  ↓ {annee} [cquest.org — exploration URLs]")
    url = find_cquest_url(annee)
    if not url:
        print(f"    ⚠ Aucune URL valide trouvée pour {annee}")
        return []
    try:
        r = requests.get(url, timeout=300)
        r.raise_for_status()
        content = r.content
        print(f"    {len(content)/1024/1024:.1f} Mo téléchargés")
        # Détecter format (gzip ou zip)
        try:
            with gzip.open(io.BytesIO(content),'rt',encoding='utf-8',errors='replace') as f:
                text = f.read()
        except:
            try:
                with gzip.open(io.BytesIO(content),'rt',encoding='latin-1',errors='replace') as f:
                    text = f.read()
            except:
                text = content.decode('latin-1',errors='replace')
        return parse_auto(text, annee)
    except Exception as e:
        print(f"    ⚠ {e}")
        return []

# ── PARSERS ───────────────────────────────────────────────────────

def parse_auto(text, annee):
    """Détecte automatiquement le format et parse."""
    lines = text.split('\n')
    if not lines: return []
    sep = detect_sep(lines[0])
    print(f"    Format détecté : séparateur '{sep}', {len(lines)} lignes")
    if sep == '|':
        return parse_pipe(lines, annee)
    else:
        return parse_csv(lines, annee, sep)

def parse_pipe(lines, annee):
    """Format TXT DGFiP brut, séparateur |."""
    # Trouver le header
    start = 0
    for i, line in enumerate(lines[:5]):
        cols = line.split('|')
        if len(cols) > 30 and not cols[10].replace('.','').replace(',','').strip().lstrip('-').isdigit():
            start = i + 1
            break

    mutations = {}
    skipped = 0
    for line in lines[start:]:
        if not line.strip(): continue
        c = line.split('|')
        if len(c) < 20: continue
        def g(i): return c[i].strip().strip('"') if i < len(c) else ''

        dep = g(18).zfill(2)
        if dep != '75': skipped += 1; continue

        comm = g(19).zfill(3)
        code_5 = f"75{comm}"
        arr_num = CODE_TO_ARR.get(code_5)
        if arr_num is None:
            cp = g(16)
            if cp.startswith('750') and len(cp)==5:
                try:
                    n = int(cp[3:])
                    if 1 <= n <= 20: arr_num = n
                except: pass
        if arr_num is None: continue
        if 'vente' not in g(9).lower(): continue

        val=to_f(g(10)); surf=to_f(g(37)); c1=to_f(g(24)); c2=to_f(g(26))
        surf = surf if surf>0 else (c1 if c1>0 else c2)
        tl=g(35)
        try: nbpp=int(float(g(38))) if g(38) else 0
        except: nbpp=0
        date=g(8)[:10]
        if '/' in date:
            p=date.split('/');
            if len(p)==3: date=f"{p[2]}-{p[1].zfill(2)}-{p[0].zfill(2)}"

        mut_id=f"{date}_{int(val) if val else 0}_{code_5}_{g(21)}"
        key=f"{arr_num}_{mut_id}"
        if key not in mutations:
            mutations[key]={'arr':arr_num,'val':val,'date':date,'locaux':[]}
        if val>0: mutations[key]['val']=val
        if surf>0: mutations[key]['locaux'].append({'surf':surf,'type':tl,'nbpp':nbpp})

    print(f"    {len(mutations)} mutations Paris | {skipped} lignes hors Paris ignorées")
    return consolidate(mutations, annee)

def parse_csv(lines, annee, sep=','):
    """Format CSV cquest ou geo-dvf."""
    H = [h.strip().lower() for h in lines[0].split(sep)]
    def gi(n): return next((i for i,h in enumerate(H) if n in h),-1)

    iMut=gi('id_mutation'); iDate=gi('date_mutation'); iNat=gi('nature_mutation')
    iVal=gi('valeur_fonciere'); iCode=gi('code_commune')
    iC1=gi('lot1_surface_carrez') if gi('lot1_surface_carrez')>=0 else gi('surface_carrez')
    iC2=gi('lot2_surface_carrez')
    iCodeT=gi('code_type_local'); iType=gi('type_local')
    iSurf=gi('surface_reelle_bati'); iNbPP=gi('nombre_pieces_principales')

    print(f"    Colonnes: val={iVal} code={iCode} type={iType} surf={iSurf}")

    mutations = {}
    for line in lines[1:]:
        if not line.strip(): continue
        c = line.split(sep)
        if len(c) < 10: continue
        def g(i): return c[i].strip().strip('"') if 0<=i<len(c) else ''

        code = g(iCode)
        # Supporter code 5 chiffres (75101) ou reconstituer depuis dép+commune
        arr_num = CODE_TO_ARR.get(code)
        if arr_num is None and len(code) == 5 and code.startswith('75'):
            # Parfois stocké comme "75056" = Paris sans arrondissement → skip
            pass
        if arr_num is None: continue
        if 'vente' not in g(iNat).lower(): continue

        val=to_f(g(iVal)); surf=to_f(g(iSurf))
        c1=to_f(g(iC1)) if iC1>=0 else 0
        c2=to_f(g(iC2)) if iC2>=0 else 0
        surf = surf if surf>0 else (c1 if c1>0 else c2)

        tl=g(iType)
        try: ct=int(float(g(iCodeT) or '0'))
        except: ct=0
        try: nbpp=int(float(g(iNbPP) or '0'))
        except: nbpp=0

        mut_id=g(iMut) or f"{g(iDate)}_{val}_{code}"
        key=f"{arr_num}_{mut_id}"
        if key not in mutations:
            mutations[key]={'arr':arr_num,'val':val,'date':g(iDate)[:10],'locaux':[]}
        if val>0: mutations[key]['val']=val
        if surf>0: mutations[key]['locaux'].append({'surf':surf,'type':tl,'code_type':ct,'nbpp':nbpp})

    return consolidate(mutations, annee)

# ── TÉLÉCHARGEMENT geo-dvf ────────────────────────────────────────

def download_recent(annee):
    url = GEODVF_URL.format(annee=annee)
    print(f"  ↓ {annee} [geo-dvf]")
    try:
        r = requests.get(url, timeout=180)
        r.raise_for_status()
        print(f"    {len(r.content)/1024/1024:.1f} Mo")
        with gzip.open(io.BytesIO(r.content),'rt',encoding='utf-8',errors='replace') as f:
            lines = f.read().split('\n')
        return parse_csv(lines, annee, ',')
    except Exception as e:
        print(f"    ⚠ {e}")
        return []

# ── CACHE ─────────────────────────────────────────────────────────

def load_cache():
    if not os.path.exists(HIST_CACHE): return None
    try:
        with open(HIST_CACHE,'r',encoding='utf-8') as f:
            data = json.load(f)
        muts = data.get('mutations',[])
        annees = data.get('annees',[])
        print(f"  ✓ Cache chargé : {len(muts):,} mutations ({annees})")
        return muts
    except Exception as e:
        print(f"  ⚠ Cache invalide ({e}), re-téléchargement")
        return None

def save_cache(muts):
    annees = sorted(set(m['annee'] for m in muts))
    with open(HIST_CACHE,'w',encoding='utf-8') as f:
        json.dump({'annees':annees,'generated_at':datetime.utcnow().isoformat()+'Z','mutations':muts},
                  f, ensure_ascii=False, separators=(',',':'))
    mb = os.path.getsize(HIST_CACHE)/1024/1024
    print(f"  ✓ Cache sauvegardé : {HIST_CACHE} ({mb:.1f} Mo, {len(muts):,} mutations)")

# ── STATS ─────────────────────────────────────────────────────────

def ppm2(m): return m['val']/m['surf']

def compute_stats(muts):
    if len(muts)<5: return None
    prices=sorted([ppm2(m) for m in muts]); surfs=sorted([m['surf'] for m in muts]); n=len(prices)
    return {'median':round(prices[n//2]),'mean':round(sum(prices)/n),
            'q1':round(prices[n//4]),'q3':round(prices[3*n//4]),
            'min':round(prices[0]),'max':round(prices[-1]),
            'p10':round(prices[max(0,n//10)]),'p90':round(prices[min(n-1,9*n//10)]),
            'surf_mean':round(sum(surfs)/n,1),'surf_median':round(surfs[n//2],1),'count':n}

def compute_by_year(muts):
    BY={}
    for m in muts:
        y=(m.get('date') or '')[:4]
        if re.match(r'^20[01]\d$',y): BY.setdefault(y,[]).append(m)
    result={}
    for y,ms in sorted(BY.items()):
        if len(ms)<5: continue
        prices=sorted([ppm2(m) for m in ms]); surfs=[m['surf'] for m in ms]; n=len(prices)
        result[y]={'median':round(prices[n//2]),'mean':round(sum(prices)/n),
                   'q1':round(prices[n//4]),'q3':round(prices[3*n//4]),
                   'surf_mean':round(sum(surfs)/n,1),'count':n}
    return result

def get_typo(surf):
    for t in TYPOLOGIES:
        if t['surfMin']<=surf<t['surfMax']: return t['id']
    return None

def build_typo_stats(muts):
    by_typo={}
    for m in muts:
        t=get_typo(m['surf'])
        if t: by_typo.setdefault(t,[]).append(m)
    result={}
    for t_id,ms in by_typo.items():
        s=compute_stats(ms)
        if s: result[t_id]={**s,'by_year':compute_by_year(ms)}
    return result

def build_group_stats(all_muts, key_fn, labels):
    groups={}
    for m in all_muts:
        k=key_fn(m)
        if k is not None: groups.setdefault(k,[]).append(m)
    result={}
    for k,muts in groups.items():
        by_type={}
        for tb in ['Appartement','Maison']:
            f=[m for m in muts if m['type']==tb]; s=compute_stats(f)
            if s: by_type[tb]={**s,'by_year':compute_by_year(f),'by_typo':build_typo_stats(f)}
        result[str(k)]={'label':labels.get(k,str(k)),'by_type':by_type,'total':len(muts)}
    return result

# ── MAIN ──────────────────────────────────────────────────────────

def main():
    os.makedirs('data',exist_ok=True)
    all_muts=[]

    # Étape 1 : historique 2014-2019 (cache ou téléchargement)
    print('=== Données historiques 2014–2019 ===')
    hist = load_cache()
    if hist is None:
        print('  Cache absent → exploration data.cquest.org')
        hist=[]
        for annee in ANNEES_HIST:
            hist.extend(download_cquest(annee))
            time.sleep(2)
        if hist:
            save_cache(hist)
        else:
            print('  ⚠ Historique non disponible — dashboard limité à 2020–2025')
    else:
        print('  Cache utilisé ✓ — skip téléchargement 2014–2019')
    all_muts.extend(hist)

    # Étape 2 : données récentes 2020-2025 (toujours re-téléchargées)
    print('\n=== Données récentes 2020–2025 ===')
    for annee in ANNEES_RECENTS:
        all_muts.extend(download_recent(annee))
        time.sleep(1)

    apparts=[m for m in all_muts if m['type']=='Appartement']
    maisons=[m for m in all_muts if m['type']=='Maison']
    annees_ok=sorted(set(m['annee'] for m in all_muts))
    periode=f"{min(annees_ok)}–{max(annees_ok)}" if annees_ok else "N/A"

    print(f'\n=== Total : {len(all_muts):,} mutations ===')
    print(f'  Appartements : {len(apparts):,} | Maisons : {len(maisons):,}')
    print(f'  Années : {annees_ok}')

    arr_stats  = build_group_stats(all_muts,lambda m:m['arr'],{i:f"Paris {ARR_LABELS[i]} arr." for i in range(1,21)})
    sect_stats = build_group_stats(all_muts,lambda m:m['sect'],{k:f"Secteur {k} — {v['nom']}" for k,v in SECTEURS.items()})
    g_stats    = compute_stats(apparts)
    g_by_year  = compute_by_year(apparts)
    g_by_typo  = build_typo_stats(apparts)

    output={
        'meta':{'generated_at':datetime.utcnow().isoformat()+'Z',
                'source_hist':'data.cquest.org/dgfip_dvf (2014–2019, cache)',
                'source_recent':'files.data.gouv.fr/geo-dvf (2020–2025)',
                'annees':annees_ok,'total_mutations':len(all_muts),
                'total_apparts':len(apparts),'total_maisons':len(maisons),
                'periode':periode,'cache_hist':os.path.exists(HIST_CACHE)},
        'global':{'stats':g_stats,'by_year':g_by_year,'by_typo':g_by_typo},
        'arrondissements':arr_stats,'secteurs':sect_stats,
        'secteurs_ref':{str(k):v for k,v in SECTEURS.items()},
        'arr_to_sect':{str(k):v for k,v in ARR_TO_SECT.items()},
        'typologies_ref':TYPOLOGIES,
    }
    with open(OUTPUT,'w',encoding='utf-8') as f:
        json.dump(output,f,ensure_ascii=False,indent=2)

    size_kb=os.path.getsize(OUTPUT)/1024
    print(f'\n✓ {OUTPUT} ({size_kb:.0f} Ko) — {periode}')
    if g_by_year:
        yrs=list(g_by_year.keys())
        v0=g_by_year[yrs[0]]['median']; v1=g_by_year[yrs[-1]]['median']
        print(f'  Évolution {yrs[0]}→{yrs[-1]} : {(v1-v0)/v0*100:+.1f}% ({v0:,}→{v1:,} €/m²)')

if __name__=='__main__': main()

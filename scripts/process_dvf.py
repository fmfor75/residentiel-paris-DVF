#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
process_dvf.py v12 — Paris + Boulogne-Billancourt

P©rimÃ¨tre :
  - Paris (75) : 20 arrondissements → 14 secteurs DRIHL
  - Boulogne-Billancourt (92012) : 6 quartiers par bbox GPS

Sources :
  A1 : files.opendatarchives.fr (CSV géolocalisé 2014–2019)
  A2 : data.cquest.org (TXT brut fallback 2014–2019)
  B  : files.data.gouv.fr/geo-dvf (CSV géolocalisé 2020–2025)
  B2 : files.data.gouv.fr/geo-dvf dept 92 (Boulogne 2020–2025)
"""

import os, json, gzip, io, time, requests, re
from datetime import datetime

# ── CONFIG ────────────────────────────────────────────────────────

OPENDATARCHIVES_URL = "https://files.opendatarchives.fr/cadastre.data.gouv.fr/data/etalab-dvf/2019-04/csv/{annee}/departements/{dep}.csv.gz"
CQUEST_MILLESIMES   = ["202004", "201910", "201904"]
CQUEST_NOMS         = ["valeursfoncieres-{annee}.txt.gz", "ValeursFoncieres-{annee}.txt.gz"]
GEODVF_URL          = "https://files.data.gouv.fr/geo-dvf/latest/csv/{annee}/departements/{dep}.csv.gz"

ANNEES_HIST    = list(range(2014, 2020))
ANNEES_RECENTS = list(range(2020, 2026))
HIST_CACHE = "data/dvf_hist.json"
OUTPUT     = "data/dvf_paris.json"

# ── RÉFÉRENTIELS PARIS ────────────────────────────────────────────

CODE_TO_ARR = {f"751{str(i).zfill(2)}": i for i in range(1, 21)}
ARR_LABELS  = {i: ("1er" if i == 1 else f"{i}e") for i in range(1, 21)}

ARR_TO_SECT = {
    1:1,2:1,3:2,4:2,5:3,6:4,7:4,8:5,9:6,10:7,
    11:13,12:8,13:10,14:10,15:9,16:5,17:6,18:7,19:7,20:13
}

SECTEURS_PARIS = {
    1: {"nom":"Louvre – Opéra","arrLabel":"1er, 2e","ville":"Paris"},
    2: {"nom":"Marais – Bastille","arrLabel":"3e, 4e","ville":"Paris"},
    3: {"nom":"Île de la Cité – Luxembourg","arrLabel":"5e, 6e","ville":"Paris"},
    4: {"nom":"Saint-Germain – Invalides","arrLabel":"6e, 7e","ville":"Paris"},
    5: {"nom":"Champs-Élysées – Trocadéro","arrLabel":"8e, 16e","ville":"Paris"},
    6: {"nom":"Opéra – Grands Boulevards","arrLabel":"9e, 17e nord","ville":"Paris"},
    7: {"nom":"Montmartre – Belleville","arrLabel":"10e, 18e, 19e nord","ville":"Paris"},
    8: {"nom":"Nation – Vincennes","arrLabel":"12e","ville":"Paris"},
    9: {"nom":"Grenelle – Convention","arrLabel":"15e","ville":"Paris"},
    10:{"nom":"Montrouge – Alésia","arrLabel":"13e sud, 14e","ville":"Paris"},
    11:{"nom":"Épinettes – Batignolles","arrLabel":"17e sud","ville":"Paris"},
    12:{"nom":"Buttes-Chaumont","arrLabel":"19e sud","ville":"Paris"},
    13:{"nom":"Ménilmontant – Oberkampf","arrLabel":"11e, 20e","ville":"Paris"},
    14:{"nom":"Ivry – Tolbiac – Gobelins","arrLabel":"13e nord","ville":"Paris"},
}

# Frontières pour arrondissements partagés
LAT_17_FRONTIERE = 48.884  # S6 au nord, S11 au sud
LAT_19_FRONTIERE = 48.880  # S7 au nord, S12 au sud
LAT_13_FRONTIERE = 48.826  # S14 au nord, S10 au sud

def arr_to_sect_geo(arr_num, lat, lon):
    if arr_num == 17: return 6 if lat >= LAT_17_FRONTIERE else 11
    elif arr_num == 19: return 7 if lat >= LAT_19_FRONTIERE else 12
    elif arr_num == 13: return 14 if lat >= LAT_13_FRONTIERE else 10
    else: return ARR_TO_SECT.get(arr_num)

# ── RÉFÉRENTIELS BOULOGNE ─────────────────────────────────────────

CODE_BOULOGNE = "92012"

# 6 quartiers définis par boîtes englobantes (lat_min, lat_max, lon_min, lon_max)
# IDs : B1–B6 (préfixe B pour distinguer des secteurs Paris)
QUARTIERS_BOULOGNE = {
    "B1": {"nom":"Billancourt – Île Seguin",         "arrLabel":"Sud-Est · Seine",
           "lat_min":48.820,"lat_max":48.836,"lon_min":2.225,"lon_max":2.252,"ville":"Boulogne"},
    "B2": {"nom":"Pont de Sèvres – Rives de Seine",  "arrLabel":"Sud-Ouest · Pont de Sèvres",
           "lat_min":48.820,"lat_max":48.836,"lon_min":2.210,"lon_max":2.226,"ville":"Boulogne"},
    "B3": {"nom":"Centre-ville – République",         "arrLabel":"Centre",
           "lat_min":48.836,"lat_max":48.848,"lon_min":2.228,"lon_max":2.252,"ville":"Boulogne"},
    "B4": {"nom":"Silly – Gallieni – Droits de l'Homme","arrLabel":"Nord-Ouest",
           "lat_min":48.836,"lat_max":48.852,"lon_min":2.210,"lon_max":2.232,"ville":"Boulogne"},
    "B5": {"nom":"Boulogne Nord – Parchamp",          "arrLabel":"Nord · Bois de Boulogne",
           "lat_min":48.843,"lat_max":48.855,"lon_min":2.232,"lon_max":2.260,"ville":"Boulogne"},
    "B6": {"nom":"Marcel Sembat – Aguesseau",         "arrLabel":"Est · Métro ligne 9",
           "lat_min":48.831,"lat_max":48.845,"lon_min":2.245,"lon_max":2.265,"ville":"Boulogne"},
}

def latlon_to_boulogne_quartier(lat, lon):
    """Retourne l'ID du quartier Boulogne correspondant aux coordonnées GPS."""
    if not lat or not lon: return "B0"  # Sans géoloc → commune entière
    for qid, q in QUARTIERS_BOULOGNE.items():
        if q["lat_min"] <= lat < q["lat_max"] and q["lon_min"] <= lon < q["lon_max"]:
            return qid
    return "B0"  # Hors bbox (rare) → commune entière

# Fusionner les référentiels pour le JSON final
ALL_SECTEURS = {
    **{str(k): v for k, v in SECTEURS_PARIS.items()},
    **QUARTIERS_BOULOGNE,
    "B0": {"nom":"Boulogne-Billancourt (commune entière)","arrLabel":"92100","ville":"Boulogne"},
}

TYPOLOGIES = [
    {"id":"T1","surfMin":9,  "surfMax":30},
    {"id":"T2","surfMin":30, "surfMax":50},
    {"id":"T3","surfMin":50, "surfMax":70},
    {"id":"T4","surfMin":70, "surfMax":100},
    {"id":"T5","surfMin":100,"surfMax":400},
]

# ── HELPERS ───────────────────────────────────────────────────────

def to_f(s):
    try: return float(str(s).replace(',','.').replace(' ','')) if s else 0.0
    except: return 0.0

def get_quarter(date_str):
    try:
        d = datetime.strptime(date_str[:10], '%Y-%m-%d')
        return f'{d.year}-Q{(d.month-1)//3+1}'
    except: return None

def consolidate(mutations, annee, dep='75'):
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

        lat = m.get('lat', 0.0); lon = m.get('lon', 0.0)
        arr = m.get('arr'); code_comm = m.get('code_comm','')

        if dep == '75':
            sect = arr_to_sect_geo(arr, lat, lon) if (lat and lon) else ARR_TO_SECT.get(arr)
        else:
            # Boulogne
            arr = None
            sect = latlon_to_boulogne_quartier(lat, lon)

        result.append({
            'arr': arr, 'sect': sect, 'val': m['val'], 'surf': surf,
            'type': tl, 'nbpp': p.get('nbpp',0), 'date': m['date'],
            'annee': annee, 'lat': lat, 'lon': lon, 'dep': dep,
        })
    has_geo = sum(1 for r in result if r['lat'])
    print(f"    → {len(result)} | Appart:{counts['Appartement']} Maison:{counts['Maison']} "
          f"SansSurf:{counts['sans_surf']} Géo:{has_geo}")
    return result

# ── PARSERS ───────────────────────────────────────────────────────

def parse_csv_geo(lines, annee, dep='75'):
    H = [h.strip().lower() for h in lines[0].split(',')]
    def gi(n): return next((i for i,h in enumerate(H) if n in h), -1)
    iMut=gi('id_mutation'); iDate=gi('date_mutation'); iNat=gi('nature_mutation')
    iVal=gi('valeur_fonciere'); iCode=gi('code_commune')
    iC1=gi('lot1_surface_carrez'); iC2=gi('lot2_surface_carrez')
    iCodeT=gi('code_type_local'); iType=gi('type_local')
    iSurf=gi('surface_reelle_bati'); iNbPP=gi('nombre_pieces_principales')
    iLat=gi('latitude'); iLon=gi('longitude')
    has_geo = iLat>=0 and iLon>=0
    print(f"    Colonnes: val={iVal} code={iCode} surf={iSurf} lat={iLat} lon={iLon} {'✓géo' if has_geo else '✗géo'}")

    # Pour Paris : filtrer uniquement les arrondissements
    # Pour Boulogne : filtrer uniquement 92012
    if dep == '75':
        valid_codes = set(CODE_TO_ARR.keys())
    else:
        valid_codes = {CODE_BOULOGNE}

    mutations = {}
    for line in lines[1:]:
        if not line.strip(): continue
        c = line.split(',')
        if len(c) < 20: continue
        def g(i): return c[i].strip().strip('"') if 0<=i<len(c) else ''

        code = g(iCode)
        if dep == '75':
            arr = CODE_TO_ARR.get(code)
            if not arr: continue
        else:
            if code != CODE_BOULOGNE: continue
            arr = None

        if 'vente' not in g(iNat).lower(): continue
        val  = to_f(g(iVal))
        surf = to_f(g(iSurf))
        c1   = to_f(g(iC1)) if iC1>=0 else 0
        c2   = to_f(g(iC2)) if iC2>=0 else 0
        surf = c1 if c1>0 else (c2 if c2>0 else surf)
        tl=g(iType)
        try: ct=int(float(g(iCodeT) or '0'))
        except: ct=0
        try: nbpp=int(float(g(iNbPP) or '0'))
        except: nbpp=0
        lat = to_f(g(iLat)) if has_geo else 0.0
        lon = to_f(g(iLon)) if has_geo else 0.0
        mut_id = g(iMut) or f"{g(iDate)}_{val}_{code}"
        key = f"{code}_{mut_id}"
        if key not in mutations:
            mutations[key]={'arr':arr,'code_comm':code,'val':val,'date':g(iDate)[:10],
                            'lat':lat,'lon':lon,'locaux':[]}
        if val>0: mutations[key]['val']=val
        if lat and not mutations[key]['lat']: mutations[key]['lat']=lat; mutations[key]['lon']=lon
        if surf>0: mutations[key]['locaux'].append({'surf':surf,'type':tl,'code_type':ct,'nbpp':nbpp})
    return consolidate(mutations, annee, dep)

HEADER_KEYS = ['date mutation','nature mutation','valeur fonciere']

def detect_cols(header_line):
    cols=[h.strip().strip('"').lower() for h in header_line.split('|')]
    def find(kws):
        for kw in kws:
            for i,c in enumerate(cols):
                if kw in c: return i
        return -1
    return {'date':find(['date mutation']),'nature':find(['nature mutation']),
            'val':find(['valeur fonciere']),'dep':find(['code departement']),
            'comm':find(['code commune']),'cp':find(['code postal']),
            'plan':find(['no plan']),'type':find(['type local']),
            'surf':find(['surface reelle bati']),'nbpp':find(['nombre pieces'])}

def parse_txt_pipe(lines, annee):
    if not lines: return []
    hi = next((i for i,l in enumerate(lines[:10]) if any(k in l.lower() for k in HEADER_KEYS)), -1)
    idx = detect_cols(lines[hi]) if hi>=0 else {'date':8,'nature':9,'val':10,'dep':18,'comm':19,'cp':16,'plan':21,'type':35,'surf':37,'nbpp':38}
    start = hi+1 if hi>=0 else 0
    mutations={}; skipped=0
    for line in lines[start:]:
        if not line.strip(): continue
        c=line.split('|')
        if len(c)<15: continue
        def g(i): return c[i].strip().strip('"') if 0<=i<len(c) else ''
        dep=g(idx['dep']).zfill(2) if idx['dep']>=0 else '??'
        if dep!='75': skipped+=1; continue
        comm=g(idx['comm']).zfill(3) if idx['comm']>=0 else ''
        code_5=f"75{comm}"; arr=CODE_TO_ARR.get(code_5)
        if arr is None:
            cp=g(idx['cp']) if idx['cp']>=0 else ''
            if cp.startswith('750') and len(cp)==5:
                try:
                    n=int(cp[3:])
                    if 1<=n<=20: arr=n
                except: pass
        if arr is None: continue
        if 'vente' not in (g(idx['nature']).lower() if idx['nature']>=0 else ''): continue
        val=to_f(g(idx['val'])) if idx['val']>=0 else 0
        surf=0.0
        for ci in range(24,min(33,len(c))):
            v=c[ci].strip()
            if ','in v or('.'in v and v.replace('.','').isdigit()):
                try:
                    f=float(v.replace(',','.'))
                    if f>5: surf=f; break
                except: pass
        if surf==0.0: surf=to_f(g(idx['surf'])) if idx['surf']>=0 else 0
        tl_idx=idx['type']; tl=g(tl_idx) if tl_idx>=0 else ''
        if tl.isdigit() and tl_idx+1<len(c): tl=g(tl_idx+1)
        try: nbpp=int(float(g(idx['nbpp']))) if idx['nbpp']>=0 and g(idx['nbpp']) else 0
        except: nbpp=0
        date=g(idx['date'])[:10] if idx['date']>=0 else ''
        if '/'in date:
            p=date.split('/')
            if len(p)==3: date=f"{p[2]}-{p[1].zfill(2)}-{p[0].zfill(2)}"
        plan=g(idx['plan']) if idx['plan']>=0 else ''
        mut_id=f"{date}_{int(val) if val else 0}_{code_5}_{plan}"
        key=f"{arr}_{mut_id}"
        if key not in mutations:
            mutations[key]={'arr':arr,'code_comm':code_5,'val':val,'date':date,'lat':0.0,'lon':0.0,'locaux':[]}
        if val>0: mutations[key]['val']=val
        if surf>0 or tl: mutations[key]['locaux'].append({'surf':surf,'type':tl,'nbpp':nbpp})
    print(f"    {len(mutations)} mutations Paris | {skipped} hors Paris")
    return consolidate(mutations, annee, '75')

# ── TÉLÉCHARGEMENTS ───────────────────────────────────────────────

def try_dl(url, timeout=300, enc='utf-8'):
    try:
        r=requests.get(url,timeout=timeout); r.raise_for_status()
        mb=len(r.content)/1024/1024
        for e in [enc,'latin-1']:
            try:
                with gzip.open(io.BytesIO(r.content),'rt',encoding=e,errors='replace') as f:
                    return f.read().split('\n'), mb
            except: pass
        return None,0
    except: return None,0

def find_cquest_url(annee):
    for mil in CQUEST_MILLESIMES:
        for tpl in CQUEST_NOMS:
            url=f"https://data.cquest.org/dgfip_dvf/{mil}/{tpl.format(annee=annee)}"
            try:
                r=requests.head(url,timeout=15,allow_redirects=True)
                if r.status_code==200 and int(r.headers.get('content-length',0))>100000:
                    return url
            except: pass
    return None

def download_hist(annee):
    """2014-2019 : opendatarchives (géoloc) → cquest (fallback)"""
    print(f"  ↓ {annee} [hist]")

    # A1 : opendatarchives Paris (géolocalisé)
    url_a1=OPENDATARCHIVES_URL.format(annee=annee, dep='75')
    print(f"    A1: {url_a1}")
    lines,mb=try_dl(url_a1,timeout=120)
    if lines and len(lines)>100:
        print(f"    ✓ {mb:.1f}Mo géolocalisé (Paris)")
        r75 = parse_csv_geo(lines, annee, '75')
    else:
        print(f"    ✗ A1 indisponible → A2 cquest")
        url_a2=find_cquest_url(annee)
        if url_a2:
            print(f"    A2: {url_a2}")
            lines,mb=try_dl(url_a2,timeout=300,enc='latin-1')
            r75 = parse_txt_pipe(lines, annee) if lines else []
        else:
            print(f"    ⚠ Aucune source disponible"); r75=[]

    # A1 Boulogne : même archive opendatarchives, dept 92
    url_b1=OPENDATARCHIVES_URL.format(annee=annee, dep='92')
    print(f"    Boulogne A1: {url_b1}")
    lines,mb=try_dl(url_b1,timeout=180)
    if lines and len(lines)>100:
        print(f"    ✓ {mb:.1f}Mo (dept 92)")
        r92 = parse_csv_geo(lines, annee, '92')
    else:
        print(f"    ✗ Boulogne indisponible pour {annee}"); r92=[]

    return r75 + r92

def download_recent(annee):
    print(f"  ↓ {annee} [récent]")
    result=[]

    # Paris
    lines,mb=try_dl(GEODVF_URL.format(annee=annee,dep='75'))
    if lines:
        print(f"    75: {mb:.1f}Mo")
        result.extend(parse_csv_geo(lines,annee,'75'))

    # Boulogne (dept 92)
    lines,mb=try_dl(GEODVF_URL.format(annee=annee,dep='92'))
    if lines:
        print(f"    92: {mb:.1f}Mo")
        result.extend(parse_csv_geo(lines,annee,'92'))
    return result

# ── CACHE ─────────────────────────────────────────────────────────

def load_cache():
    if not os.path.exists(HIST_CACHE): return None
    try:
        with open(HIST_CACHE,'r',encoding='utf-8') as f: data=json.load(f)
        muts=data.get('mutations',[]); annees=data.get('annees',[])
        has_geo=sum(1 for m in muts if m.get('lat'))
        has_boulogne=sum(1 for m in muts if m.get('dep')=='92')
        print(f"  ✓ Cache: {len(muts):,} mutations ({annees}) — {has_geo:,} géo, {has_boulogne:,} Boulogne")
        if has_boulogne==0:
            print("  ↻ Cache sans Boulogne — re-téléchargement")
            return None
        return muts
    except Exception as e:
        print(f"  ⚠ Cache invalide ({e})"); return None

def save_cache(muts):
    annees=sorted(set(m['annee'] for m in muts))
    with open(HIST_CACHE,'w',encoding='utf-8') as f:
        json.dump({'annees':annees,'generated_at':datetime.utcnow().isoformat()+'Z','mutations':muts},
                  f,ensure_ascii=False,separators=(',',':'))
    print(f"  ✓ Cache: {os.path.getsize(HIST_CACHE)/1024/1024:.1f}Mo, {len(muts):,} mutations")

# ── STATS ─────────────────────────────────────────────────────────

def ppm2(m): return m['val']/m['surf']

def compute_stats(muts):
    if len(muts)<3: return None
    p=sorted([ppm2(m) for m in muts]); s=sorted([m['surf'] for m in muts]); n=len(p)
    return {'count':n,'mean':round(sum(p)/n),'median':round(p[n//2]),
            'min':round(p[0]),'max':round(p[-1]),
            'q1':round(p[n//4]),'q3':round(p[3*n//4]),
            'p10':round(p[max(0,n//10)]),'p90':round(p[min(n-1,9*n//10)]),
            'surf_mean':round(sum(m['surf'] for m in muts)/n,1),
            'surf_median':round(s[n//2],1)}

def compute_by_period(muts, key_fn):
    groups={}
    for m in muts:
        k=key_fn(m)
        if k: groups.setdefault(k,[]).append(m)
    result={}
    for k,ms in sorted(groups.items()):
        if len(ms)<3: continue
        p=sorted([ppm2(m) for m in ms]); s=[m['surf'] for m in ms]; n=len(p)
        result[k]={'count':n,'mean':round(sum(p)/n),'median':round(p[n//2]),
                   'min':round(p[0]),'max':round(p[-1]),
                   'q1':round(p[n//4]),'q3':round(p[3*n//4]),
                   'p10':round(p[max(0,n//10)]),'p90':round(p[min(n-1,9*n//10)]),
                   'surf_mean':round(sum(s)/n,1)}
    return result

def compute_by_year(muts):
    return compute_by_period(muts, lambda m: str(m['annee']) if m.get('annee') else None)

def compute_by_quarter(muts):
    return compute_by_period(muts, lambda m: get_quarter(m.get('date','')))

def get_typo(surf):
    for t in TYPOLOGIES:
        if t['surfMin']<=surf<t['surfMax']: return t['id']
    return None

def build_typo_stats(muts):
    by={}
    for m in muts:
        t=get_typo(m['surf'])
        if t: by.setdefault(t,[]).append(m)
    total=sum(len(v) for v in by.values()); result={}
    for t_id,ms in by.items():
        s=compute_stats(ms)
        if s:
            result[t_id]={**s,'share':round(len(ms)/total*100,1) if total>0 else 0,
                          'by_year':compute_by_year(ms),'by_quarter':compute_by_quarter(ms)}
    if result:
        result['_top_typo']=max((k for k in result if not k.startswith('_')),key=lambda k:result[k]['count'])
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
            f=[m for m in muts if m['type']==tb]
            s=compute_stats(f)
            if s:
                by_type[tb]={**s,'by_year':compute_by_year(f),
                             'by_quarter':compute_by_quarter(f),'by_typo':build_typo_stats(f)}
        result[str(k)]={'label':labels.get(k,str(k)),'by_type':by_type,'total':len(muts)}
    return result

# ── MAIN ──────────────────────────────────────────────────────────

def main():
    os.makedirs('data',exist_ok=True)
    all_muts=[]

    print('=== Historique 2014–2019 ===')
    hist=load_cache()
    if hist is None:
        hist=[]
        for annee in ANNEES_HIST:
            hist.extend(download_hist(annee))
            time.sleep(2)
        if hist: save_cache(hist)
        else: print('  ⚠ Historique indisponible')
    else:
        print('  Cache utilisé ✓')
    all_muts.extend(hist)

    print('\n=== Récent 2020–2025 ===')
    for annee in ANNEES_RECENTS:
        all_muts.extend(download_recent(annee))
        time.sleep(1)

    paris75   = [m for m in all_muts if m.get('dep')=='75']
    boulogne92= [m for m in all_muts if m.get('dep')=='92']
    apparts75 = [m for m in paris75   if m['type']=='Appartement']
    apparts92 = [m for m in boulogne92 if m['type']=='Appartement']
    annees_ok = sorted(set(m['annee'] for m in all_muts))
    periode   = f"{min(annees_ok)}–{max(annees_ok)}" if annees_ok else "N/A"

    print(f'\n=== Total : {len(all_muts):,} mutations ===')
    print(f'  Paris 75    : {len(paris75):,} ({len(apparts75):,} apparts)')
    print(f'  Boulogne 92 : {len(boulogne92):,} ({len(apparts92):,} apparts)')
    print(f'  Années : {annees_ok}')

    print('\n=== Calcul statistiques ===')

    # Paris : arrondissements + secteurs DRIHL
    arr_s   = build_group_stats(paris75, lambda m:m['arr'],
                                {i:f"Paris {ARR_LABELS[i]} arr." for i in range(1,21)})
    sect_s  = build_group_stats(paris75, lambda m:m['sect'],
                                {k:v['nom'] for k,v in SECTEURS_PARIS.items()})

    # Boulogne : quartiers
    boulog_s = build_group_stats(boulogne92, lambda m:m['sect'],
                                 {k:v['nom'] for k,v in QUARTIERS_BOULOGNE.items()})
    # Boulogne commune entière
    boulog_s["B0"] = build_group_stats(boulogne92, lambda m:'B0',
                                       {'B0':'Boulogne-Billancourt (commune entière)'}).get('B0',{})

    # Fusionner secteurs Paris + quartiers Boulogne
    all_zones = {**sect_s, **boulog_s}

    gs=compute_stats(apparts75); gby=compute_by_year(apparts75)
    gbyq=compute_by_quarter(apparts75); gtypo=build_typo_stats(apparts75)

    output={
        'meta':{
            'generated_at':datetime.utcnow().isoformat()+'Z',
            'source_hist':'opendatarchives/cquest (2014–2019)',
            'source_recent':'files.data.gouv.fr/geo-dvf (2020–2025)',
            'annees':annees_ok,'total_mutations':len(all_muts),
            'total_apparts':len(apparts75)+len(apparts92),
            'total_apparts_paris':len(apparts75),
            'total_apparts_boulogne':len(apparts92),
            'periode':periode,'cache_hist':os.path.exists(HIST_CACHE),
        },
        'global':{'stats':gs,'by_year':gby,'by_quarter':gbyq,'by_typo':gtypo},
        'arrondissements': arr_s,
        'secteurs':        all_zones,   # Paris DRIHL + Boulogne quartiers
        'secteurs_ref':    ALL_SECTEURS,
        'arr_to_sect':     {str(k):v for k,v in ARR_TO_SECT.items()},
        'typologies_ref':  TYPOLOGIES,
        'boulogne': {
            'total_mutations': len(boulogne92),
            'total_apparts':   len(apparts92),
            'by_year':         compute_by_year(apparts92),
            'by_quarter':      compute_by_quarter(apparts92),
        },
    }

    with open(OUTPUT,'w',encoding='utf-8') as f:
        json.dump(output,f,ensure_ascii=False,indent=2)

    kb=os.path.getsize(OUTPUT)/1024
    print(f'\n✓ {OUTPUT} ({kb:.0f} Ko) — {periode}')
    if gby:
        yrs=list(gby.keys()); v0=gby[yrs[0]]['median']; v1=gby[yrs[-1]]['median']
        print(f'  Paris évolution {yrs[0]}→{yrs[-1]} : {(v1-v0)/v0*100:+.1f}% ({v0:,}→{v1:,} €/m²)')

if __name__=='__main__': main()

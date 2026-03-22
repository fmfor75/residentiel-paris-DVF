#!/usr/bin/env python3
"""
process_dvf.py v5 — 2014–2025, deux sources

SOURCE A : data.gouv.fr (2014–2019) — fichiers TXT zippés nationaux
  URL pattern : https://www.data.gouv.fr/api/1/datasets/r/{resource_id}
  Format : ZIP contenant un fichier TXT, séparateur |
  Les 6 fichiers sont listés sans ordre garanti, on les identifie
  par l'année dans le nom de fichier ZIP ou par ordre de taille.
  
  IDs ressources (page data.gouv.fr, octobre 2025) :
    4d741143-8331-4b59-95c2-3b24a7bdbe3c  ~25 Mo  → 2024 (partiel ?)
    af812b0e-a898-4226-8cc8-5a570b257326  ~62 Mo  → 2020
    cc8a50e4-c8d1-4ac2-8de2-c1e4b3c44c86  ~68 Mo  → 2021
    8c8abe23-2a82-4b95-8174-1c1e0734c921  ~83 Mo  → 2022
    e117fe7d-f7fb-4c52-8089-231e755d19d3  ~83 Mo  → 2023
    8d771135-57c8-480f-a853-3d1d00ea0b69  ~38 Mo  → partiel ?

  NOTE : ces fichiers sont MIS À JOUR et remplacent les anciens.
  Depuis oct 2025, ils couvrent les 5 dernières années → 2021-2025.
  Les données 2014-2019 ne sont plus disponibles via cette source.
  
  Solution : utiliser le dépôt Etalab sur cadastre.data.gouv.fr
  qui héberge les archives historiques.

SOURCE B : files.data.gouv.fr/geo-dvf (2020–2025)
  URL : https://files.data.gouv.fr/geo-dvf/latest/csv/{annee}/departements/75.csv.gz

SOURCE C (historique) : cadastre.data.gouv.fr/data/etalab-dvf
  URL : https://cadastre.data.gouv.fr/data/etalab-dvf/latest/csv/{annee}/departements/75.csv.gz
  Ce dépôt a les mêmes données que geo-dvf mais est parfois mis à jour différemment.
  Pour 2014-2019, utiliser les archives :
  https://cadastre.data.gouv.fr/data/etalab-dvf/{annee}/csv/departements/75.csv.gz
"""

import os, json, gzip, io, zipfile, time, requests, re
from datetime import datetime

# ── CONFIGURATION ─────────────────────────────────────────────────

# Toutes les années via geo-dvf (Etalab) — même format CSV propre
# Pour 2014-2019, on essaie d'abord cadastre.data.gouv.fr archives
ANNEES_HIST = list(range(2014, 2020))   # 2014-2019 historique
ANNEES_RECENTES = list(range(2020, 2026))  # 2020-2025 geo-dvf

# URLs base
GEO_DVF_URL    = "https://files.data.gouv.fr/geo-dvf/latest/csv/{annee}/departements/75.csv.gz"
CADASTRE_URL   = "https://cadastre.data.gouv.fr/data/etalab-dvf/latest/csv/{annee}/departements/75.csv.gz"
CADASTRE_ARCH  = "https://cadastre.data.gouv.fr/data/etalab-dvf/{annee}/csv/departements/75.csv.gz"

OUTPUT = "data/dvf_paris.json"

# ── RÉFÉRENTIELS ──────────────────────────────────────────────────

CODE_TO_ARR = {f"751{str(i).zfill(2)}": i for i in range(1, 21)}
ARR_LABELS  = {i: ("1er" if i == 1 else f"{i}e") for i in range(1, 21)}

ARR_TO_SECT = {
    1:1, 2:1, 3:2, 4:2, 5:3, 6:4, 7:4, 8:5,
    9:6, 10:7, 11:13, 12:8, 13:10, 14:10,
    15:9, 16:5, 17:6, 18:7, 19:7, 20:13
}

SECTEURS = {
    1:  {"nom": "Louvre – Opéra",               "arr": [1, 2],       "arrLabel": "1er, 2e"},
    2:  {"nom": "Marais – Bastille",             "arr": [3, 4],       "arrLabel": "3e, 4e"},
    3:  {"nom": "Île de la Cité – Luxembourg",   "arr": [5, 6],       "arrLabel": "5e, 6e"},
    4:  {"nom": "Saint-Germain – Invalides",     "arr": [6, 7],       "arrLabel": "6e, 7e"},
    5:  {"nom": "Champs-Élysées – Trocadéro",   "arr": [8, 16],      "arrLabel": "8e, 16e"},
    6:  {"nom": "Opéra – Grands Boulevards",     "arr": [9, 17],      "arrLabel": "9e, 17e"},
    7:  {"nom": "Montmartre – Belleville",       "arr": [10, 18, 19], "arrLabel": "10e, 18e, 19e"},
    8:  {"nom": "Nation – Vincennes",            "arr": [12],         "arrLabel": "12e"},
    9:  {"nom": "Grenelle – Convention",         "arr": [15],         "arrLabel": "15e"},
    10: {"nom": "Montrouge – Alésia",            "arr": [13, 14],     "arrLabel": "13e, 14e"},
    11: {"nom": "Épinettes – Batignolles",       "arr": [17],         "arrLabel": "17e"},
    12: {"nom": "Buttes-Chaumont",               "arr": [19],         "arrLabel": "19e"},
    13: {"nom": "Ménilmontant – Oberkampf",      "arr": [11, 20],     "arrLabel": "11e, 20e"},
    14: {"nom": "Ivry – Tolbiac – Gobelins",     "arr": [13],         "arrLabel": "13e"},
}

TYPOLOGIES = [
    {"id": "T1", "surfMin": 9,   "surfMax": 30},
    {"id": "T2", "surfMin": 30,  "surfMax": 50},
    {"id": "T3", "surfMin": 50,  "surfMax": 70},
    {"id": "T4", "surfMin": 70,  "surfMax": 100},
    {"id": "T5", "surfMin": 100, "surfMax": 400},
]

# ── TÉLÉCHARGEMENT ────────────────────────────────────────────────

def try_download_csv_gz(urls, annee):
    """Essaie plusieurs URLs pour télécharger un CSV.GZ."""
    for url in urls:
        print(f"    Essai : {url}")
        try:
            r = requests.get(url, timeout=180)
            r.raise_for_status()
            print(f"    ✓ {len(r.content)/1024/1024:.1f} Mo")
            with gzip.open(io.BytesIO(r.content), 'rt', encoding='utf-8', errors='replace') as f:
                return parse_csv_etalab(f, annee)
        except Exception as e:
            print(f"    ✗ {e}")
    return None

def download_year(annee):
    print(f"  ↓ {annee}")
    if annee >= 2020:
        # Source principale : geo-dvf
        urls = [GEO_DVF_URL.format(annee=annee)]
        result = try_download_csv_gz(urls, annee)
        if result is not None:
            return result
    else:
        # Historique 2014-2019 : essayer cadastre.data.gouv.fr
        urls = [
            CADASTRE_URL.format(annee=annee),
            CADASTRE_ARCH.format(annee=annee),
            # Fallback : tenter geo-dvf quand même (parfois des millésimes anciens y sont)
            GEO_DVF_URL.format(annee=annee),
        ]
        result = try_download_csv_gz(urls, annee)
        if result is not None:
            return result
        print(f"    ⚠ {annee} non disponible via les sources connues")
    return []

# ── PARSING CSV ETALAB (format geo-dvf, séparateur virgule) ───────

def parse_csv_etalab(f, annee):
    lines = f.read().split('\n')
    if not lines:
        return []

    headers = [h.strip().lower() for h in lines[0].split(',')]

    def gi(n): return next((i for i, h in enumerate(headers) if n in h), -1)

    iMut   = gi('id_mutation')
    iDate  = gi('date_mutation')
    iNat   = gi('nature_mutation')
    iVal   = gi('valeur_fonciere')
    iCode  = gi('code_commune')
    iCarr1 = gi('lot1_surface_carrez')
    iCarr2 = gi('lot2_surface_carrez')
    iCodeT = gi('code_type_local')
    iType  = gi('type_local')
    iSurf  = gi('surface_reelle_bati')
    iNbPP  = gi('nombre_pieces_principales')

    # Détection format TXT (séparateur |) si pas de colonnes CSV trouvées
    if iVal < 0 and iCode < 0:
        # Essayer séparateur |
        headers_pipe = [h.strip().lower() for h in lines[0].split('|')]
        if len(headers_pipe) > 10:
            print(f"    Détecté format TXT (séparateur |)")
            return parse_txt_pipe('\n'.join(lines), annee)

    print(f"    Colonnes: val={iVal} code={iCode} type={iType} surf={iSurf} carr1={iCarr1}")

    mutations = {}

    for line in lines[1:]:
        if not line.strip():
            continue
        c = line.split(',')
        if len(c) < 20:
            continue

        def g(idx, default=''):
            return c[idx].strip().strip('"') if 0 <= idx < len(c) else default

        code_commune = g(iCode)
        arr_num = CODE_TO_ARR.get(code_commune)
        if arr_num is None:
            continue
        if 'vente' not in g(iNat).lower():
            continue

        def to_f(s):
            try: return float(s.replace(',', '.')) if s else 0.0
            except: return 0.0

        val    = to_f(g(iVal))
        surf_b = to_f(g(iSurf))
        carr1  = to_f(g(iCarr1))
        carr2  = to_f(g(iCarr2))
        surf   = surf_b if surf_b > 0 else (carr1 if carr1 > 0 else carr2)

        type_local = g(iType)
        try:   code_type = int(float(g(iCodeT) or '0'))
        except: code_type = 0
        try:   nbpp = int(float(g(iNbPP) or '0'))
        except: nbpp = 0

        date   = g(iDate)[:10]
        mut_id = g(iMut) or f"{date}_{val}_{code_commune}"
        key    = f"{arr_num}_{mut_id}"

        if key not in mutations:
            mutations[key] = {'arr': arr_num, 'val': val, 'date': date, 'locaux': []}
        if val > 0:
            mutations[key]['val'] = val
        if surf > 0:
            mutations[key]['locaux'].append({
                'surf': surf, 'type': type_local,
                'code_type': code_type, 'nbpp': nbpp,
            })

    return consolidate(mutations, annee)


def parse_txt_pipe(text, annee):
    """Parse format TXT séparateur | (fichiers DGFiP nationaux bruts)."""
    lines = text.split('\n')
    if not lines: return []

    # Trouver la ligne d'en-tête
    header_idx = 0
    for i, line in enumerate(lines[:5]):
        cols = line.split('|')
        if len(cols) > 30:
            header_idx = i
            break

    headers = [h.strip().strip('"').lower() for h in lines[header_idx].split('|')]
    print(f"    Headers TXT[0:8]: {headers[:8]}")

    def gi(n): return next((i for i, h in enumerate(headers) if n in h.replace(' ', '_')), -1)

    # Colonnes connues du format TXT DGFiP
    iDate  = gi('date_mutation') if gi('date_mutation') >= 0 else 8
    iNat   = gi('nature_mutation') if gi('nature_mutation') >= 0 else 9
    iVal   = gi('valeur_fonciere') if gi('valeur_fonciere') >= 0 else 10
    iDep   = gi('code_departement') if gi('code_departement') >= 0 else 18
    iComm  = gi('code_commune') if gi('code_commune') >= 0 else 19
    iCP    = gi('code_postal') if gi('code_postal') >= 0 else 16
    iCarr1 = 24  # Surface Carrez lot 1
    iCarr2 = 26  # Surface Carrez lot 2
    iType  = gi('type_local') if gi('type_local') >= 0 else 35
    iSurf  = gi('surface_reelle_bati') if gi('surface_reelle_bati') >= 0 else 37
    iNbPP  = 38

    print(f"    Cols TXT: date={iDate} val={iVal} dep={iDep} comm={iComm} type={iType} surf={iSurf}")

    mutations = {}
    skipped = 0

    for line in lines[header_idx + 1:]:
        if not line.strip(): continue
        c = line.split('|')
        if len(c) < 20: continue

        def g(idx, default=''):
            return c[idx].strip().strip('"') if 0 <= idx < len(c) else default

        dep  = g(iDep).zfill(2)
        if dep != '75':
            skipped += 1
            continue

        comm = g(iComm).zfill(3)
        code_5 = f"75{comm}"
        arr_num = CODE_TO_ARR.get(code_5)

        if arr_num is None:
            # Fallback code postal
            cp = g(iCP)
            if cp.startswith('750') and len(cp) == 5:
                try:
                    n = int(cp[3:])
                    if 1 <= n <= 20:
                        arr_num = n
                        code_5 = f"751{str(n).zfill(2)}"
                except: pass
        if arr_num is None:
            continue

        if 'vente' not in g(iNat).lower(): continue

        def to_f(s):
            try: return float(s.replace(',', '.').replace(' ', '')) if s else 0.0
            except: return 0.0

        val    = to_f(g(iVal))
        surf_b = to_f(g(iSurf))
        carr1  = to_f(g(iCarr1))
        carr2  = to_f(g(iCarr2))
        surf   = surf_b if surf_b > 0 else (carr1 if carr1 > 0 else carr2)

        type_local = g(iType)
        try:   nbpp = int(float(g(iNbPP)))
        except: nbpp = 0

        date = g(iDate)
        if '/' in date:
            p = date.split('/')
            if len(p) == 3:
                date = f"{p[2]}-{p[1].zfill(2)}-{p[0].zfill(2)}"
        date = date[:10]

        mut_id = f"{date}_{int(val)}_{code_5}"
        key = f"{arr_num}_{mut_id}"

        if key not in mutations:
            mutations[key] = {'arr': arr_num, 'val': val, 'date': date, 'locaux': []}
        if val > 0:
            mutations[key]['val'] = val
        if surf > 0:
            mutations[key]['locaux'].append({
                'surf': surf, 'type': type_local,
                'code_type': 0, 'nbpp': nbpp,
            })

    print(f"    Ignoré hors Paris : {skipped}")
    return consolidate(mutations, annee)


def consolidate(mutations, annee):
    result = []
    counts = {'Appartement': 0, 'Maison': 0, 'Autre': 0, 'sans_surf': 0}

    for m in mutations.values():
        if m['val'] <= 0: continue
        if not m['locaux']:
            counts['sans_surf'] += 1
            continue
        principal = max(m['locaux'], key=lambda l: l['surf'])
        surf = principal['surf']
        if surf <= 0: continue
        ppm2 = m['val'] / surf
        if ppm2 < 500 or ppm2 > 60000: continue

        tl = principal['type']
        ct = principal.get('code_type', 0)
        if 'appartement' in tl.lower() or ct == 2:
            tl = 'Appartement'; counts['Appartement'] += 1
        elif 'maison' in tl.lower() or ct == 1:
            tl = 'Maison'; counts['Maison'] += 1
        else:
            counts['Autre'] += 1; continue

        result.append({
            'arr':   m['arr'],
            'sect':  ARR_TO_SECT.get(m['arr']),
            'val':   m['val'],
            'surf':  surf,
            'type':  tl,
            'nbpp':  principal['nbpp'],
            'date':  m['date'],
            'annee': annee,
        })

    print(f"    → {len(result)} | Appart:{counts['Appartement']} Maison:{counts['Maison']} SansSurf:{counts['sans_surf']}")
    return result


# ── STATS ─────────────────────────────────────────────────────────

def ppm2(m): return m['val'] / m['surf']

def compute_stats(muts):
    if len(muts) < 5: return None
    prices = sorted([ppm2(m) for m in muts])
    surfs  = sorted([m['surf'] for m in muts])
    n = len(prices)
    return {
        'median':      round(prices[n//2]),
        'mean':        round(sum(prices)/n),
        'q1':          round(prices[n//4]),
        'q3':          round(prices[3*n//4]),
        'min':         round(prices[0]),
        'max':         round(prices[-1]),
        'p10':         round(prices[max(0, n//10)]),
        'p90':         round(prices[min(n-1, 9*n//10)]),
        'surf_mean':   round(sum(surfs)/n, 1),
        'surf_median': round(surfs[n//2], 1),
        'count':       n,
    }

def compute_by_year(muts):
    BY = {}
    for m in muts:
        y = (m.get('date') or '')[:4]
        if re.match(r'^20[01]\d$', y):
            BY.setdefault(y, []).append(m)
    result = {}
    for y, ms in sorted(BY.items()):
        if len(ms) < 5: continue
        prices = sorted([ppm2(m) for m in ms])
        surfs  = [m['surf'] for m in ms]
        n = len(prices)
        result[y] = {
            'median':    round(prices[n//2]),
            'mean':      round(sum(prices)/n),
            'q1':        round(prices[n//4]),
            'q3':        round(prices[3*n//4]),
            'surf_mean': round(sum(surfs)/n, 1),
            'count':     n,
        }
    return result

def get_typo(surf):
    for t in TYPOLOGIES:
        if t['surfMin'] <= surf < t['surfMax']: return t['id']
    return None

def build_typo_stats(muts):
    by_typo = {}
    for m in muts:
        t = get_typo(m['surf'])
        if t: by_typo.setdefault(t, []).append(m)
    result = {}
    for t_id, ms in by_typo.items():
        s = compute_stats(ms)
        if s: result[t_id] = {**s, 'by_year': compute_by_year(ms)}
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
            filtered = [m for m in muts if m['type'] == tb]
            s = compute_stats(filtered)
            if s:
                by_type[tb] = {**s, 'by_year': compute_by_year(filtered), 'by_typo': build_typo_stats(filtered)}
        result[str(k)] = {'label': labels.get(k, str(k)), 'by_type': by_type, 'total': len(muts)}
    return result


# ── MAIN ──────────────────────────────────────────────────────────

def main():
    os.makedirs('data', exist_ok=True)
    all_muts = []

    print('=== Téléchargement DVF Paris 2014–2025 ===')
    toutes_annees = ANNEES_HIST + ANNEES_RECENTES
    for annee in toutes_annees:
        rows = download_year(annee)
        all_muts.extend(rows)
        time.sleep(1)

    apparts = [m for m in all_muts if m['type'] == 'Appartement']
    maisons = [m for m in all_muts if m['type'] == 'Maison']
    annees_ok = sorted(set(m['annee'] for m in all_muts))

    print(f'\n=== Total : {len(all_muts):,} mutations ===')
    print(f'  Appartements : {len(apparts):,} | Maisons : {len(maisons):,}')
    print(f'  Années disponibles : {annees_ok}')

    print('\n=== Calcul statistiques ===')
    arr_stats  = build_group_stats(all_muts, lambda m: m['arr'],
                                   {i: f"Paris {ARR_LABELS[i]} arr." for i in range(1, 21)})
    sect_stats = build_group_stats(all_muts, lambda m: m['sect'],
                                   {k: f"Secteur {k} — {v['nom']}" for k, v in SECTEURS.items()})
    global_stats   = compute_stats(apparts)
    global_by_year = compute_by_year(apparts)
    global_by_typo = build_typo_stats(apparts)

    periode = f"{min(annees_ok)}–{max(annees_ok)}" if annees_ok else "N/A"

    output = {
        'meta': {
            'generated_at':    datetime.utcnow().isoformat() + 'Z',
            'source':          'DGFiP / Etalab — Licence Ouverte 2.0',
            'sources':         {
                'historique':  'cadastre.data.gouv.fr (2014–2019)',
                'recentes':    'files.data.gouv.fr/geo-dvf (2020–2025)',
            },
            'annees':          annees_ok,
            'total_mutations': len(all_muts),
            'total_apparts':   len(apparts),
            'total_maisons':   len(maisons),
            'periode':         periode,
        },
        'global':          {'stats': global_stats, 'by_year': global_by_year, 'by_typo': global_by_typo},
        'arrondissements': arr_stats,
        'secteurs':        sect_stats,
        'secteurs_ref':    {str(k): v for k, v in SECTEURS.items()},
        'arr_to_sect':     {str(k): v for k, v in ARR_TO_SECT.items()},
        'typologies_ref':  TYPOLOGIES,
    }

    with open(OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    size_kb = os.path.getsize(OUTPUT) / 1024
    print(f'\n✓ {OUTPUT} ({size_kb:.0f} Ko)')

    if global_by_year:
        yrs = list(global_by_year.keys())
        v0  = global_by_year[yrs[0]]['median']
        v1  = global_by_year[yrs[-1]]['median']
        print(f'  Évolution {yrs[0]}→{yrs[-1]} : {(v1-v0)/v0*100:+.1f}% ({v0:,} → {v1:,} €/m²)')

if __name__ == '__main__':
    main()

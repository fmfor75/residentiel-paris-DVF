#!/usr/bin/env python3
"""
process_dvf.py v4 — 2014–2025, deux sources combinées

SOURCE A : cadastre.data.gouv.fr (2014–2019)
  Format TXT, séparateur |, 43 colonnes, fichier national complet
  URL : https://www.data.gouv.fr/fr/datasets/r/{resource_id}
  Colonnes clés (0-based) :
    0  Code service CH
    1  Reference document
    2  1 Articles CGI
    3  2 Articles CGI
    4  3 Articles CGI
    5  4 Articles CGI
    6  5 Articles CGI
    7  No disposition
    8  Date mutation          ← date_mutation
    9  Nature mutation        ← nature_mutation
    10 Valeur fonciere        ← valeur_fonciere
    11 No voie
    12 B/T/Q
    13 Type de voie
    14 Code voie
    15 Voie
    16 Code postal            ← code_postal
    17 Commune
    18 Code departement
    19 Code commune           ← code_commune (2 chiffres seulement, ex: "01")
    20 Section
    21 No plan
    22 No volume
    23 1er lot
    24 Surface Carrez 1       ← lot1_surface_carrez
    25 2eme lot
    26 Surface Carrez 2       ← lot2_surface_carrez
    27 3eme lot
    28 Surface Carrez 3
    29 4eme lot
    30 Surface Carrez 4
    31 5eme lot
    32 Surface Carrez 5
    33 Nombre de lots
    34 Code droit             ← code_type_local (P=Appartement, M=Maison ?)
    35 Type local             ← type_local (texte)
    36 Identifiant local
    37 Surface reelle bati    ← surface_reelle_bati
    38 Nombre pieces principales
    39 Nature culture
    40 Nature culture speciale
    41 Surface terrain

SOURCE B : files.data.gouv.fr/geo-dvf (2020–2025)
  Format CSV géolocalisé, séparateur ,, 40 colonnes, par département
  URL : https://files.data.gouv.fr/geo-dvf/latest/csv/{annee}/departements/75.csv.gz
"""

import os, json, gzip, io, time, requests, re
from datetime import datetime

# ── SOURCES ───────────────────────────────────────────────────────

# Source A : fichiers nationaux 2014–2019 (format TXT, séparateur |)
# IDs de ressources data.gouv.fr (stables)
SOURCE_A = {
    2014: "https://www.data.gouv.fr/fr/datasets/r/dc13282f-3c7a-4fac-b1f3-3939e39d45f6",
    2015: "https://www.data.gouv.fr/fr/datasets/r/09f013c5-9531-444b-ab6c-7a0e88efd77d",
    2016: "https://www.data.gouv.fr/fr/datasets/r/0ab442c5-57d1-4139-92c2-19672336401c",
    2017: "https://www.data.gouv.fr/fr/datasets/r/7161c9f2-3d91-4caf-afa2-cfe535807f04",
    2018: "https://www.data.gouv.fr/fr/datasets/r/1be77ca5-dc1b-4e50-af2b-0240147e0346",
    2019: "https://www.data.gouv.fr/fr/datasets/r/3004168d-bec4-44d9-a781-ef16f41856a2",
}

# Source B : fichiers Paris par département 2020–2025 (format CSV géolocalisé)
SOURCE_B_URL = "https://files.data.gouv.fr/geo-dvf/latest/csv/{annee}/departements/75.csv.gz"
ANNEES_B = list(range(2020, 2026))

OUTPUT = "data/dvf_paris.json"

# ── RÉFÉRENTIELS ──────────────────────────────────────────────────

# Codes INSEE arrondissements Paris : 75101 → 75120
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

# ── PARSING SOURCE A (TXT 2014–2019) ─────────────────────────────

def download_source_a(annee, url):
    print(f"  ↓ {annee} [Source A - TXT national] {url}")
    try:
        r = requests.get(url, timeout=300, stream=True)
        r.raise_for_status()
        # Fichier TXT compressé ou non
        content = r.content
        print(f"    Taille brute : {len(content)/1024/1024:.1f} Mo")

        # Essayer de décompresser si c'est du gzip
        try:
            with gzip.open(io.BytesIO(content), 'rt', encoding='latin-1', errors='replace') as f:
                text = f.read()
            print(f"    Format : gzip")
        except Exception:
            # Sinon lire directement
            text = content.decode('latin-1', errors='replace')
            print(f"    Format : texte brut")

        return parse_source_a(text, annee)
    except Exception as e:
        print(f"    ⚠ Erreur {annee} : {e}")
        return []

def parse_source_a(text, annee):
    """
    Format TXT source DGFiP, séparateur |
    Code_commune = col 19 (2 chiffres) + col 18 (dép 2 chiffres) = ex: "75" + "01" = "7501" → on reconstruit "75101"
    Attention : la commune "75056" = Paris entier dans certains millésimes
                les arrondissements = "75101" à "75120" dans d'autres
    """
    lines = text.split('\n')
    if not lines:
        return []

    # Détecter l'en-tête
    header_idx = 0
    for i, line in enumerate(lines[:5]):
        if 'mutation' in line.lower() or 'fonciere' in line.lower() or 'valeur' in line.lower():
            header_idx = i
            break

    headers = [h.strip().strip('"').lower() for h in lines[header_idx].split('|')]
    print(f"    Headers[0:6] : {headers[:6]}")
    print(f"    Nb colonnes : {len(headers)}")

    def gi(n): return next((i for i, h in enumerate(headers) if n in h), -1)

    iDate  = gi('date mutation') if gi('date mutation') >= 0 else gi('datemut') if gi('datemut') >= 0 else 8
    iNat   = gi('nature mutation') if gi('nature mutation') >= 0 else 9
    iVal   = gi('valeur fonciere') if gi('valeur fonciere') >= 0 else 10
    iCP    = gi('code postal') if gi('code postal') >= 0 else 16
    iDep   = gi('code departement') if gi('code departement') >= 0 else 18
    iComm  = gi('code commune') if gi('code commune') >= 0 else 19
    iCarr1 = gi('surface carrez') if gi('surface carrez') >= 0 else 24
    # lot2
    iCarr2 = 26
    iType  = gi('type local') if gi('type local') >= 0 else 35
    iSurf  = gi('surface reelle') if gi('surface reelle') >= 0 else 37
    iNbPP  = gi('nombre pieces') if gi('nombre pieces') >= 0 else 38

    print(f"    Cols: date={iDate} val={iVal} dep={iDep} comm={iComm} type={iType} surf={iSurf} carr1={iCarr1}")

    mutations = {}
    skipped_dep = 0

    for line in lines[header_idx + 1:]:
        if not line.strip():
            continue
        c = line.split('|')
        if len(c) < 20:
            continue

        def g(idx, default=''):
            v = c[idx].strip().strip('"') if 0 <= idx < len(c) else default
            return v

        # Reconstituer le code commune INSEE à 5 chiffres
        dep  = g(iDep).zfill(2)   # ex: "75"
        comm = g(iComm).zfill(3)  # ex: "056" ou "101"

        if dep != '75':
            skipped_dep += 1
            continue

        # Dans le format TXT, le code commune est sur 3 chiffres : "056" = Paris entier, "101" = 1er arr.
        # On essaie d'abord le code direct, sinon on reconstruit
        code_5 = dep + comm  # "75056" ou "75101"

        # Paris entier (75056) → on ne peut pas attribuer un arrondissement, on saute
        arr_num = CODE_TO_ARR.get(code_5)
        if arr_num is None:
            # Essayer avec code postal (7501X → 1er arr., etc.)
            cp = g(iCP).strip()
            if cp.startswith('750') and len(cp) == 5:
                try:
                    arr_n = int(cp[3:])  # "75001" → 1
                    if 1 <= arr_n <= 20:
                        code_5 = f"751{str(arr_n).zfill(2)}"
                        arr_num = arr_n
                except ValueError:
                    pass
            if arr_num is None:
                continue

        # Filtre nature
        nat = g(iNat).lower()
        if 'vente' not in nat:
            continue

        # Valeur foncière
        try:
            val_str = g(iVal).replace(',', '.').replace(' ', '')
            val = float(val_str) if val_str else 0
        except ValueError:
            val = 0

        # Surfaces
        def to_f(s):
            try:
                return float(s.replace(',', '.').replace(' ', '')) if s else 0.0
            except ValueError:
                return 0.0

        surf_bati   = to_f(g(iSurf))
        surf_carrez1 = to_f(g(iCarr1))
        surf_carrez2 = to_f(g(iCarr2)) if iCarr2 < len(c) else 0.0
        surf = surf_bati if surf_bati > 0 else (surf_carrez1 if surf_carrez1 > 0 else surf_carrez2)

        type_local = g(iType)
        try:
            nbpp = int(float(g(iNbPP))) if g(iNbPP) else 0
        except ValueError:
            nbpp = 0

        date   = g(iDate)
        # Normaliser la date : peut être "2014-01-15" ou "15/01/2014"
        if '/' in date:
            parts = date.split('/')
            if len(parts) == 3:
                date = f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
        date = date[:10]

        # Construire un id_mutation approximatif (pas de champ dédié dans ce format)
        # On utilise date + valeur + commune pour dédupliquer
        mut_id = f"{date}_{val}_{code_5}"

        key = f"{arr_num}_{mut_id}"
        if key not in mutations:
            mutations[key] = {'arr': arr_num, 'val': val, 'date': date, 'locaux': []}
        if val > 0:
            mutations[key]['val'] = val
        if surf > 0:
            mutations[key]['locaux'].append({
                'surf': surf, 'type': type_local, 'nbpp': nbpp
            })

    print(f"    Ignoré (hors Paris) : {skipped_dep} lignes")

    result = []
    counts = {'Appartement': 0, 'Maison': 0, 'Autre': 0, 'sans_surf': 0}

    for m in mutations.values():
        if m['val'] <= 0:
            continue
        if not m['locaux']:
            counts['sans_surf'] += 1
            continue
        principal = max(m['locaux'], key=lambda l: l['surf'])
        surf = principal['surf']
        if surf <= 0:
            continue
        ppm2 = m['val'] / surf
        if ppm2 < 500 or ppm2 > 60000:
            continue
        type_local = principal['type']
        if 'appartement' in type_local.lower():
            type_local = 'Appartement'
            counts['Appartement'] += 1
        elif 'maison' in type_local.lower():
            type_local = 'Maison'
            counts['Maison'] += 1
        else:
            counts['Autre'] += 1
            continue
        result.append({
            'arr':   m['arr'],
            'sect':  ARR_TO_SECT.get(m['arr']),
            'val':   m['val'],
            'surf':  surf,
            'type':  type_local,
            'nbpp':  principal['nbpp'],
            'date':  m['date'],
            'annee': annee,
        })

    print(f"    → {len(result)} | Appart:{counts['Appartement']} Maison:{counts['Maison']} SansSurf:{counts['sans_surf']}")
    return result


# ── PARSING SOURCE B (CSV géolocalisé 2020–2025) ─────────────────

def download_source_b(annee):
    url = SOURCE_B_URL.format(annee=annee)
    print(f"  ↓ {annee} [Source B - CSV géolocalisé] {url}")
    try:
        r = requests.get(url, timeout=180)
        r.raise_for_status()
        print(f"    {len(r.content)/1024/1024:.1f} Mo")
        with gzip.open(io.BytesIO(r.content), 'rt', encoding='utf-8', errors='replace') as f:
            return parse_source_b(f, annee)
    except Exception as e:
        print(f"    ⚠ {e}")
        return []

def parse_source_b(f, annee):
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

    mutations = {}

    for line in lines[1:]:
        if not line.strip():
            continue
        c = line.split(',')
        if len(c) < 32:
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
            try:
                return float(s.replace(',', '.')) if s else 0.0
            except ValueError:
                return 0.0

        val       = to_f(g(iVal))
        surf_bati = to_f(g(iSurf))
        carr1     = to_f(g(iCarr1))
        carr2     = to_f(g(iCarr2))
        surf = surf_bati if surf_bati > 0 else (carr1 if carr1 > 0 else carr2)

        type_local = g(iType)
        try:
            code_type = int(float(g(iCodeT) or '0'))
        except ValueError:
            code_type = 0
        try:
            nbpp = int(float(g(iNbPP) or '0'))
        except ValueError:
            nbpp = 0

        date   = g(iDate)[:10]
        mut_id = g(iMut)
        if not mut_id:
            continue

        key = f"{arr_num}_{mut_id}"
        if key not in mutations:
            mutations[key] = {'arr': arr_num, 'val': val, 'date': date, 'locaux': []}
        if val > 0:
            mutations[key]['val'] = val
        if surf > 0:
            mutations[key]['locaux'].append({
                'surf': surf,
                'type': type_local,
                'code_type': code_type,
                'nbpp': nbpp,
            })

    result = []
    counts = {'Appartement': 0, 'Maison': 0, 'Autre': 0, 'sans_surf': 0}

    for m in mutations.values():
        if m['val'] <= 0:
            continue
        if not m['locaux']:
            counts['sans_surf'] += 1
            continue
        principal = max(m['locaux'], key=lambda l: l['surf'])
        surf = principal['surf']
        if surf <= 0:
            continue
        ppm2 = m['val'] / surf
        if ppm2 < 500 or ppm2 > 60000:
            continue
        type_local = principal['type']
        ct = principal.get('code_type', 0)
        if 'appartement' in type_local.lower() or ct == 2:
            type_local = 'Appartement'
            counts['Appartement'] += 1
        elif 'maison' in type_local.lower() or ct == 1:
            type_local = 'Maison'
            counts['Maison'] += 1
        else:
            counts['Autre'] += 1
            continue
        result.append({
            'arr':   m['arr'],
            'sect':  ARR_TO_SECT.get(m['arr']),
            'val':   m['val'],
            'surf':  surf,
            'type':  type_local,
            'nbpp':  principal['nbpp'],
            'date':  m['date'],
            'annee': annee,
        })

    print(f"    → {len(result)} | Appart:{counts['Appartement']} Maison:{counts['Maison']} SansSurf:{counts['sans_surf']}")
    return result


# ── STATS ─────────────────────────────────────────────────────────

def ppm2(m): return m['val'] / m['surf']

def compute_stats(muts):
    if len(muts) < 5:
        return None
    prices = sorted([ppm2(m) for m in muts])
    surfs  = sorted([m['surf'] for m in muts])
    n = len(prices)
    return {
        'median':      round(prices[n // 2]),
        'mean':        round(sum(prices) / n),
        'q1':          round(prices[n // 4]),
        'q3':          round(prices[3 * n // 4]),
        'min':         round(prices[0]),
        'max':         round(prices[-1]),
        'p10':         round(prices[max(0, n // 10)]),
        'p90':         round(prices[min(n-1, 9 * n // 10)]),
        'surf_mean':   round(sum(surfs) / n, 1),
        'surf_median': round(surfs[n // 2], 1),
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
        if len(ms) < 5:
            continue
        prices = sorted([ppm2(m) for m in ms])
        surfs  = [m['surf'] for m in ms]
        n = len(prices)
        result[y] = {
            'median':    round(prices[n // 2]),
            'mean':      round(sum(prices) / n),
            'q1':        round(prices[n // 4]),
            'q3':        round(prices[3 * n // 4]),
            'surf_mean': round(sum(surfs) / n, 1),
            'count':     n,
        }
    return result

def get_typo(surf):
    for t in TYPOLOGIES:
        if t['surfMin'] <= surf < t['surfMax']:
            return t['id']
    return None

def build_typo_stats(muts):
    by_typo = {}
    for m in muts:
        t = get_typo(m['surf'])
        if t:
            by_typo.setdefault(t, []).append(m)
    result = {}
    for t_id, ms in by_typo.items():
        s = compute_stats(ms)
        if s:
            result[t_id] = {**s, 'by_year': compute_by_year(ms)}
    return result

def build_group_stats(all_muts, key_fn, labels):
    groups = {}
    for m in all_muts:
        k = key_fn(m)
        if k is not None:
            groups.setdefault(k, []).append(m)
    result = {}
    for k, muts in groups.items():
        by_type = {}
        for type_bien in ['Appartement', 'Maison']:
            filtered = [m for m in muts if m['type'] == type_bien]
            s = compute_stats(filtered)
            if s:
                by_type[type_bien] = {
                    **s,
                    'by_year': compute_by_year(filtered),
                    'by_typo': build_typo_stats(filtered),
                }
        result[str(k)] = {
            'label':   labels.get(k, str(k)),
            'by_type': by_type,
            'total':   len(muts),
        }
    return result


# ── MAIN ──────────────────────────────────────────────────────────

def main():
    os.makedirs('data', exist_ok=True)
    all_muts = []

    # Source A : 2014–2019
    print('=== Source A : 2014–2019 (TXT national DGFiP) ===')
    for annee, url in sorted(SOURCE_A.items()):
        rows = download_source_a(annee, url)
        all_muts.extend(rows)
        time.sleep(2)  # politesse — fichiers volumineux

    # Source B : 2020–2025
    print('\n=== Source B : 2020–2025 (CSV géolocalisé Etalab) ===')
    for annee in ANNEES_B:
        rows = download_source_b(annee)
        all_muts.extend(rows)
        time.sleep(1)

    apparts = [m for m in all_muts if m['type'] == 'Appartement']
    maisons = [m for m in all_muts if m['type'] == 'Maison']

    annees_dispo = sorted(set(m['annee'] for m in all_muts))
    print(f'\n=== Total : {len(all_muts)} mutations ===')
    print(f'  Appartements : {len(apparts)} | Maisons : {len(maisons)}')
    print(f'  Années : {annees_dispo}')

    print('\n=== Calcul statistiques ===')
    arr_stats  = build_group_stats(
        all_muts, lambda m: m['arr'],
        {i: f"Paris {ARR_LABELS[i]} arr." for i in range(1, 21)}
    )
    sect_stats = build_group_stats(
        all_muts, lambda m: m['sect'],
        {k: f"Secteur {k} — {v['nom']}" for k, v in SECTEURS.items()}
    )

    global_stats   = compute_stats(apparts)
    global_by_year = compute_by_year(apparts)
    global_by_typo = build_typo_stats(apparts)

    output = {
        'meta': {
            'generated_at':    datetime.utcnow().isoformat() + 'Z',
            'source':          'DGFiP / Etalab — Licence Ouverte 2.0',
            'source_a':        'cadastre.data.gouv.fr (2014–2019)',
            'source_b':        'files.data.gouv.fr/geo-dvf (2020–2025)',
            'annees':          annees_dispo,
            'total_mutations': len(all_muts),
            'total_apparts':   len(apparts),
            'total_maisons':   len(maisons),
            'periode':         f'{min(annees_dispo)}–{max(annees_dispo)}',
        },
        'global': {
            'stats':    global_stats,
            'by_year':  global_by_year,
            'by_typo':  global_by_typo,
        },
        'arrondissements': arr_stats,
        'secteurs':        sect_stats,
        'secteurs_ref':    {str(k): v for k, v in SECTEURS.items()},
        'arr_to_sect':     {str(k): v for k, v in ARR_TO_SECT.items()},
        'typologies_ref':  TYPOLOGIES,
    }

    with open(OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    size_kb = os.path.getsize(OUTPUT) / 1024
    print(f'\n✓ {OUTPUT} ({size_kb:.0f} Ko) — {len(apparts)} apparts')

    if global_by_year:
        yrs = list(global_by_year.keys())
        v0  = global_by_year[yrs[0]]['median']
        v1  = global_by_year[yrs[-1]]['median']
        print(f'  Évolution {yrs[0]}→{yrs[-1]} : {(v1-v0)/v0*100:+.1f}% ({v0:,} → {v1:,} €/m²)')

if __name__ == '__main__':
    main()

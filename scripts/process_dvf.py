#!/usr/bin/env python3
"""
process_dvf.py v2
Colonnes exactes du CSV Etalab geo-dvf (séparateur virgule) :
id_mutation, date_mutation, numero_disposition, nature_mutation, valeur_fonciere,
adresse_numero, adresse_suffixe, adresse_nom_voie, adresse_code_voie, code_postal,
code_commune, nom_commune, code_departement, ancien_code_commune, ancien_nom_commune,
id_parcelle, ancien_id_parcelle, numero_volume, lot1_numero, lot1_surface_carrez,
lot2_numero, lot2_surface_carrez, lot3_numero, lot3_surface_carrez, lot4_numero,
lot4_surface_carrez, lot5_numero, lot5_surface_carrez, nombre_lots, code_type_local,
type_local, surface_reelle_bati, nombre_pieces_principales, code_nature_culture,
nature_culture, code_nature_culture_speciale, nature_culture_speciale, surface_terrain,
longitude, latitude

COLONNES CLÉS (index 0-based) :
  0  id_mutation
  1  date_mutation
  3  nature_mutation
  4  valeur_fonciere
  9  code_postal
  10 code_commune
  29 code_type_local      (1=Maison, 2=Appart, 3=Dépendance, 4=Local comm.)
  30 type_local           ("Maison", "Appartement", "Dépendance", "Local industriel...")
  31 surface_reelle_bati
  32 nombre_pieces_principales
"""

import os, json, gzip, io, time, requests, re
from datetime import datetime

ANNEES   = list(range(2020, 2025))
BASE_URL = "https://files.data.gouv.fr/geo-dvf/latest/csv/{annee}/departements/75.csv.gz"
OUTPUT   = "data/dvf_paris.json"

# Codes INSEE arrondissements Paris : 75101 → 75120
CODE_TO_ARR = {f"751{str(i).zfill(2)}": i for i in range(1, 21)}
ARR_LABELS  = {i: ("1er" if i==1 else f"{i}e") for i in range(1, 21)}

# Correspondance arrondissement → secteur encadrement loyers (DRIHL 2024)
ARR_TO_SECT = {
    1:1, 2:1, 3:2, 4:2, 5:3, 6:4, 7:4, 8:5,
    9:6, 10:7, 11:13, 12:8, 13:10, 14:10,
    15:9, 16:5, 17:6, 18:7, 19:7, 20:13
}

SECTEURS = {
    1:  {"nom": "Louvre – Opéra",               "arr": [1, 2]},
    2:  {"nom": "Marais – Bastille",             "arr": [3, 4]},
    3:  {"nom": "Île de la Cité – Luxembourg",   "arr": [5, 6]},
    4:  {"nom": "Saint-Germain – Invalides",     "arr": [6, 7]},
    5:  {"nom": "Champs-Élysées – Trocadéro",   "arr": [8, 16]},
    6:  {"nom": "Opéra – Grands Boulevards",     "arr": [9, 17]},
    7:  {"nom": "Montmartre – Belleville",       "arr": [10, 18, 19]},
    8:  {"nom": "Nation – Vincennes",            "arr": [12]},
    9:  {"nom": "Grenelle – Convention",         "arr": [15]},
    10: {"nom": "Montrouge – Alésia",            "arr": [13, 14]},
    11: {"nom": "Épinettes – Batignolles",       "arr": [17]},
    12: {"nom": "Buttes-Chaumont",               "arr": [19]},
    13: {"nom": "Ménilmontant – Oberkampf",      "arr": [11, 20]},
    14: {"nom": "Ivry – Tolbiac – Gobelins",     "arr": [13]},
}

# Index colonnes (0-based) — fixes dans le format Etalab geo-dvf
COL = {
    "id_mutation":              0,
    "date_mutation":            1,
    "nature_mutation":          3,
    "valeur_fonciere":          4,
    "code_commune":             10,
    "code_type_local":          29,
    "type_local":               30,
    "surface_reelle_bati":      31,
    "nombre_pieces_principales":32,
}

def download_year(annee):
    url = BASE_URL.format(annee=annee)
    print(f"  ↓ {annee} — {url}")
    try:
        r = requests.get(url, timeout=180)
        r.raise_for_status()
        print(f"    Taille : {len(r.content)/1024/1024:.1f} Mo")
        with gzip.open(io.BytesIO(r.content), 'rt', encoding='utf-8', errors='replace') as f:
            return parse(f, annee)
    except Exception as e:
        print(f"    ⚠ Erreur {annee} : {e}")
        return []

def parse(f, annee):
    lines = f.read().split('\n')
    if not lines:
        return []

    # Vérifier les headers au cas où le format change
    headers = [h.strip().lower() for h in lines[0].split(',')]
    print(f"    Headers[0:5] : {headers[:5]}")
    print(f"    Nb colonnes : {len(headers)}")

    # Vérifier les colonnes critiques
    c = COL
    for name, idx in c.items():
        if idx < len(headers):
            print(f"    col[{idx}] = '{headers[idx]}' (attendu: {name})")

    # Si le format a changé, détecter dynamiquement
    def gi(n): return next((i for i,h in enumerate(headers) if n in h), -1)
    iMut  = gi('id_mutation')   if gi('id_mutation') >= 0 else c['id_mutation']
    iDate = gi('date_mutation') if gi('date_mutation') >= 0 else c['date_mutation']
    iNat  = gi('nature_mutation') if gi('nature_mutation') >= 0 else c['nature_mutation']
    iVal  = gi('valeur_fonciere') if gi('valeur_fonciere') >= 0 else c['valeur_fonciere']
    iCode = gi('code_commune')  if gi('code_commune') >= 0 else c['code_commune']
    iType = gi('type_local')    if gi('type_local') >= 0 else c['type_local']
    iCodeT= gi('code_type_local') if gi('code_type_local') >= 0 else c['code_type_local']
    iSurf = gi('surface_reelle_bati') if gi('surface_reelle_bati') >= 0 else c['surface_reelle_bati']
    iNbPP = gi('nombre_pieces_principales') if gi('nombre_pieces_principales') >= 0 else c['nombre_pieces_principales']

    print(f"    Colonnes utilisées: id_mut={iMut}, val={iVal}, code={iCode}, type={iType}, surf={iSurf}")

    # Grouper par id_mutation (plusieurs lignes par mutation = plusieurs locaux)
    mutations = {}

    for i, line in enumerate(lines[1:], 1):
        if not line.strip():
            continue
        cols = line.split(',')
        if len(cols) < 32:
            continue

        def get(idx, default=''):
            return cols[idx].strip().strip('"') if 0 <= idx < len(cols) else default

        # Filtre commune Paris (codes 75101–75120)
        code_commune = get(iCode)
        arr_num = CODE_TO_ARR.get(code_commune)
        if arr_num is None:
            continue

        # Filtre nature : Vente uniquement
        nature = get(iNat).lower()
        if 'vente' not in nature:
            continue

        # Valeur foncière
        try:
            val = float(get(iVal).replace(',', '.') or '0')
        except ValueError:
            val = 0

        # Surface réelle bâtie
        try:
            surf = float(get(iSurf).replace(',', '.') or '0')
        except ValueError:
            surf = 0

        # Type local (texte : "Appartement", "Maison", etc.)
        type_local = get(iType)
        # code_type_local : 1=Maison, 2=Appartement, 3=Dépendance, 4=Local comm.
        try:
            code_type = int(get(iCodeT) or '0')
        except ValueError:
            code_type = 0

        # Nombre de pièces
        try:
            nbpp = int(float(get(iNbPP) or '0'))
        except ValueError:
            nbpp = 0

        date   = get(iDate)[:10]
        mut_id = get(iMut)
        if not mut_id:
            continue

        key = f"{arr_num}_{mut_id}"
        if key not in mutations:
            mutations[key] = {
                'arr':    arr_num,
                'val':    val,
                'date':   date,
                'locaux': []
            }
        # Mettre à jour la valeur foncière si on a une valeur
        if val > 0:
            mutations[key]['val'] = val

        # Ajouter le local si surface renseignée
        if surf > 0:
            mutations[key]['locaux'].append({
                'surf':       surf,
                'type':       type_local,
                'code_type':  code_type,
                'nbpp':       nbpp,
            })

    # Consolider : garder le local principal (surface max) de chaque mutation
    result = []
    counts = {'Appartement': 0, 'Maison': 0, 'Autre': 0, 'sans_surface': 0}

    for m in mutations.values():
        if m['val'] <= 0:
            continue
        if not m['locaux']:
            counts['sans_surface'] += 1
            continue

        # Local principal = surface max
        principal = max(m['locaux'], key=lambda l: l['surf'])
        surf = principal['surf']
        if surf <= 0:
            continue

        ppm2 = m['val'] / surf

        # Filtrer les valeurs aberrantes
        if ppm2 < 500 or ppm2 > 60000:
            continue

        type_local = principal['type']
        if 'appartement' in type_local.lower() or principal['code_type'] == 2:
            type_local = 'Appartement'
            counts['Appartement'] += 1
        elif 'maison' in type_local.lower() or principal['code_type'] == 1:
            type_local = 'Maison'
            counts['Maison'] += 1
        else:
            counts['Autre'] += 1
            continue  # On garde uniquement Appart et Maison

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

    print(f"    → {len(result)} mutations consolidées | Appart:{counts['Appartement']} Maison:{counts['Maison']} Autre:{counts['Autre']} SansSurf:{counts['sans_surface']}")
    return result

# ── STATS ──────────────────────────────────────────────────────────

def ppm2(m): return m['val'] / m['surf']

def compute_stats(muts):
    if len(muts) < 5:
        return None
    prices = sorted([ppm2(m) for m in muts])
    n = len(prices)
    return {
        'median': round(prices[n // 2]),
        'mean':   round(sum(prices) / n),
        'q1':     round(prices[n // 4]),
        'q3':     round(prices[3 * n // 4]),
        'min':    round(prices[0]),
        'max':    round(prices[-1]),
        'p10':    round(prices[n // 10]),
        'p90':    round(prices[9 * n // 10]),
        'count':  n,
    }

def compute_by_year(muts):
    BY = {}
    for m in muts:
        y = (m.get('date') or '')[:4]
        if re.match(r'^20[12]\d$', y):
            BY.setdefault(y, []).append(ppm2(m))
    result = {}
    for y, prices in sorted(BY.items()):
        if len(prices) >= 5:
            s = sorted(prices)
            result[y] = {
                'median': round(s[len(s)//2]),
                'mean':   round(sum(s)/len(s)),
                'q1':     round(s[len(s)//4]),
                'q3':     round(s[3*len(s)//4]),
                'count':  len(s),
            }
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

    print('=== Téléchargement DVF Paris ===')
    all_muts = []
    for annee in ANNEES:
        rows = download_year(annee)
        all_muts.extend(rows)
        time.sleep(1)

    total = len(all_muts)
    apparts = [m for m in all_muts if m['type'] == 'Appartement']
    maisons = [m for m in all_muts if m['type'] == 'Maison']
    print(f'\nTotal : {total} mutations | Appartements : {len(apparts)} | Maisons : {len(maisons)}')

    print('\n=== Calcul statistiques ===')

    # Stats par arrondissement
    arr_stats = build_group_stats(
        all_muts,
        lambda m: m['arr'],
        {i: f"Paris {ARR_LABELS[i]} arr." for i in range(1, 21)}
    )

    # Stats par secteur
    sect_stats = build_group_stats(
        all_muts,
        lambda m: m['sect'],
        {k: f"Secteur {k} — {v['nom']}" for k, v in SECTEURS.items()}
    )

    # Global Paris appartements
    global_appart_stats = compute_stats(apparts)
    global_appart_year  = compute_by_year(apparts)

    output = {
        'meta': {
            'generated_at':    datetime.utcnow().isoformat() + 'Z',
            'source':          'DGFiP / Etalab — Licence Ouverte 2.0',
            'url':             'https://files.data.gouv.fr/geo-dvf/latest/',
            'annees':          ANNEES,
            'total_mutations': total,
            'total_apparts':   len(apparts),
            'total_maisons':   len(maisons),
            'periode':         f'{min(ANNEES)}–{max(ANNEES)}',
            'colonnes_dvf': {
                'id_mutation': 0, 'date_mutation': 1, 'nature_mutation': 3,
                'valeur_fonciere': 4, 'code_commune': 10, 'code_type_local': 29,
                'type_local': 30, 'surface_reelle_bati': 31, 'nombre_pieces_principales': 32
            }
        },
        'global': {
            'stats':   global_appart_stats,
            'by_year': global_appart_year,
        },
        'arrondissements': arr_stats,
        'secteurs':        sect_stats,
        'secteurs_ref':    {str(k): {'nom': v['nom'], 'arr': v['arr']} for k, v in SECTEURS.items()},
        'arr_to_sect':     {str(k): v for k, v in ARR_TO_SECT.items()},
    }

    with open(OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    size_kb = os.path.getsize(OUTPUT) / 1024
    print(f'\n✓ {OUTPUT} généré ({size_kb:.0f} Ko)')
    print(f'  {total} mutations · {len(apparts)} appartements · {len(maisons)} maisons')

    years = list(global_appart_year.keys())
    if years:
        first_y = list(global_appart_year.values())[0]['median']
        last_y  = list(global_appart_year.values())[-1]['median']
        evo = (last_y - first_y) / first_y * 100
        print(f'  Évolution {years[0]}→{years[-1]} : {evo:+.1f}% ({first_y:,} → {last_y:,} €/m²)')

if __name__ == '__main__':
    main()

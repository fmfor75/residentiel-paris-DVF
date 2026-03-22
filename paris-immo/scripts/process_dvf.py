#!/usr/bin/env python3
"""
process_dvf.py
Télécharge les fichiers DVF Paris (dép. 75) depuis files.data.gouv.fr/geo-dvf/
Parse les données brutes, calcule les statistiques par arrondissement / secteur / quartier
et génère data/dvf_paris.json consommé par le dashboard.

Source : DGFiP / Etalab — Licence Ouverte 2.0
URL base : https://files.data.gouv.fr/geo-dvf/latest/csv/{annee}/departements/75.csv.gz
"""

import os, json, gzip, io, time, requests, re
from datetime import datetime
from statistics import median, quantiles

# ─── CONFIG ──────────────────────────────────────────────────────────────────

ANNEES = list(range(2019, 2025))          # 2019–2024 (5 ans glissants DGFiP)
BASE_URL = "https://files.data.gouv.fr/geo-dvf/latest/csv/{annee}/departements/75.csv.gz"
OUTPUT   = "data/dvf_paris.json"
TYPE_BIEN = "Appartement"                 # filtrer sur Appartement par défaut (le dashboard expose les deux)

# Arrondissements Paris (codes INSEE 75101 → 75120)
ARRONDISSEMENTS = {i: f"751{str(i).zfill(2)}" for i in range(1, 21)}
ARR_LABELS = {i: f"{i}er" if i == 1 else f"{i}e" for i in range(1, 21)}

# Secteurs d'encadrement des loyers (DRIHL 2024) — correspondance arrondissement → secteur
ARR_TO_SECT = {
    1: 1, 2: 1, 3: 2, 4: 2,
    5: 3, 6: 4, 7: 4, 8: 5,
    9: 6, 10: 7, 11: 13, 12: 8,
    13: 10, 14: 10, 15: 9, 16: 5,
    17: 6, 18: 7, 19: 7, 20: 13
}

SECTEURS = {
    1:  "Louvre – Opéra",
    2:  "Marais – Bastille",
    3:  "Île de la Cité – Luxembourg",
    4:  "Saint-Germain – Invalides",
    5:  "Champs-Élysées – Trocadéro",
    6:  "Opéra – Grands Boulevards",
    7:  "Montmartre – Belleville",
    8:  "Nation – Vincennes",
    9:  "Grenelle – Convention",
    10: "Montrouge – Alésia",
    11: "Épinettes – Batignolles",
    12: "Buttes-Chaumont",
    13: "Ménilmontant – Oberkampf",
    14: "Ivry – Tolbiac – Gobelins",
}

QUARTIERS_ADM = {
    1:  ["Saint-Germain-l'Auxerrois", "Halles", "Palais-Royal", "Place-Vendôme"],
    2:  ["Gaillon", "Vivienne", "Mail", "Bonne-Nouvelle"],
    3:  ["Arts-et-Métiers", "Enfants-Rouges", "Archives", "Sainte-Avoye"],
    4:  ["Saint-Merri", "Saint-Gervais", "Arsenal", "Notre-Dame"],
    5:  ["Saint-Victor", "Jardin-des-Plantes", "Val-de-Grâce", "Sorbonne"],
    6:  ["Monnaie", "Odéon", "Notre-Dame-des-Champs", "Saint-Germain-des-Prés"],
    7:  ["Saint-Thomas-d'Aquin", "Invalides", "École-Militaire", "Gros-Caillou"],
    8:  ["Champs-Élysées", "Faubourg-du-Roule", "Madeleine", "Europe"],
    9:  ["Saint-Georges", "Chaussée-d'Antin", "Rochechouart", "Faubourg-Montmartre"],
    10: ["Saint-Denis", "Saint-Martin", "Hôpital-Saint-Louis", "Porte-Saint-Denis"],
    11: ["Folie-Méricourt", "Saint-Ambroise", "Roquette", "Sainte-Marguerite"],
    12: ["Bel-Air", "Picpus", "Bercy", "Quinze-Vingts"],
    13: ["Salpêtrière", "Gare", "Maison-Blanche", "Croulebarbe"],
    14: ["Montrouge", "Parc-de-Montsouris", "Petit-Montrouge", "Plaisance"],
    15: ["Saint-Lambert", "Necker", "Grenelle", "Javel"],
    16: ["Auteuil", "Muette", "Porte-Dauphine", "Chaillot"],
    17: ["Ternes", "Plaine-de-Monceaux", "Batignolles", "Épinettes"],
    18: ["Grandes-Carrières", "Clignancourt", "Goutte-d'Or", "Chapelle"],
    19: ["La Villette", "Pont-de-Flandre", "Amérique", "Combat"],
    20: ["Belleville", "Saint-Fargeau", "Père-Lachaise", "Charonne"],
}

# ─── DOWNLOAD ────────────────────────────────────────────────────────────────

def download_year(annee: int) -> list[dict]:
    url = BASE_URL.format(annee=annee)
    print(f"  ↓ Téléchargement {annee} — {url}")
    try:
        r = requests.get(url, timeout=120, stream=True)
        r.raise_for_status()
        content = b""
        for chunk in r.iter_content(chunk_size=1024 * 1024):
            content += chunk
        print(f"    Taille : {len(content)/1024/1024:.1f} Mo")
        with gzip.open(io.BytesIO(content), 'rt', encoding='utf-8', errors='replace') as f:
            return parse_csv(f, annee)
    except Exception as e:
        print(f"    ⚠ Erreur {annee} : {e}")
        return []

def parse_csv(f, annee: int) -> list[dict]:
    """Parse le CSV DVF géolocalisé Etalab — séparateur virgule, une ligne par local"""
    lines = f.read().split('\n')
    if not lines:
        return []

    headers = [h.strip().lower() for h in lines[0].split(',')]

    def gi(name):
        for i, h in enumerate(headers):
            if name in h:
                return i
        return -1

    iMut  = gi('id_mutation')
    iDate = gi('date_mutation')
    iVal  = gi('valeur_fonciere')
    iSurf = gi('surface_reelle_bati')
    iType = gi('type_local')
    iCode = gi('code_commune')
    iNat  = gi('nature_mutation')
    iCP   = gi('code_postal')

    if iVal < 0 or iSurf < 0:
        print(f"    ⚠ Colonnes non trouvées dans {annee}. Headers: {headers[:10]}")
        return []

    mutations_map = {}  # id_mutation → meilleure ligne (surf max)
    skipped = 0

    for line in lines[1:]:
        if not line.strip():
            continue
        cols = line.split(',')
        if len(cols) < max(iVal, iSurf, iCode) + 1:
            continue

        # Filtre commune Paris
        code = cols[iCode].strip().strip('"') if iCode >= 0 else ''
        arr_num = next((n for n, c in ARRONDISSEMENTS.items() if c == code), None)
        if arr_num is None:
            skipped += 1
            continue

        # Filtre nature (Vente uniquement)
        nat = cols[iNat].strip().strip('"').lower() if iNat >= 0 else 'vente'
        if 'vente' not in nat:
            continue

        # Filtre type local
        type_local = cols[iType].strip().strip('"') if iType >= 0 else ''

        try:
            val  = float(cols[iVal].strip().strip('"').replace(',', '.')) if cols[iVal].strip() else 0
            surf = float(cols[iSurf].strip().strip('"').replace(',', '.')) if cols[iSurf].strip() else 0
        except ValueError:
            continue

        if val <= 0 or surf <= 0:
            continue

        date = cols[iDate].strip().strip('"')[:10] if iDate >= 0 and len(cols) > iDate else ''
        mut_id = cols[iMut].strip().strip('"') if iMut >= 0 else f"{arr_num}_{annee}_{len(mutations_map)}"
        cp = cols[iCP].strip().strip('"') if iCP >= 0 else ''

        key = f"{arr_num}_{mut_id}"
        if key not in mutations_map or surf > mutations_map[key]['surf']:
            mutations_map[key] = {
                'arr': arr_num,
                'surf': surf,
                'val': val,
                'date': date,
                'type': type_local,
                'cp': cp,
                'annee': annee,
            }

    print(f"    → {len(mutations_map)} mutations Paris extraites (ignoré {skipped} lignes hors Paris)")
    return list(mutations_map.values())

# ─── COMPUTE ─────────────────────────────────────────────────────────────────

def prix_m2(m):
    return m['val'] / m['surf']

def compute_stats(mutations: list[dict]) -> dict | None:
    if len(mutations) < 5:
        return None
    prices = sorted([prix_m2(m) for m in mutations])
    n = len(prices)
    qs = quantiles(prices, n=4)
    return {
        "median": round(prices[n // 2]),
        "q1":     round(qs[0]),
        "q3":     round(qs[2]),
        "mean":   round(sum(prices) / n),
        "count":  n,
    }

def compute_by_year(mutations: list[dict]) -> dict:
    by_year = {}
    for m in mutations:
        y = (m.get('date') or '')[:4]
        if not re.match(r'^20[12]\d$', y):
            continue
        by_year.setdefault(y, []).append(prix_m2(m))
    result = {}
    for y, prices in sorted(by_year.items()):
        if len(prices) >= 5:
            s = sorted(prices)
            result[y] = round(s[len(s) // 2])
    return result

# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    os.makedirs("data", exist_ok=True)

    print("=== Téléchargement DVF Paris ===")
    all_mutations = []
    for annee in ANNEES:
        rows = download_year(annee)
        all_mutations.extend(rows)
        time.sleep(1)  # politesse serveur

    print(f"\nTotal brut : {len(all_mutations)} mutations")

    # Stats par arrondissement (tous types)
    print("\n=== Calcul statistiques ===")

    def build_group_stats(mutations, key_fn, labels):
        groups = {}
        for m in mutations:
            k = key_fn(m)
            if k is not None:
                groups.setdefault(k, []).append(m)
        result = {}
        for k, muts in groups.items():
            # Par type de bien
            by_type = {}
            for type_bien in ['Appartement', 'Maison']:
                filtered = [m for m in muts if type_bien.lower() in m['type'].lower()]
                s = compute_stats(filtered)
                if s:
                    by_type[type_bien] = s
            # Evolution annuelle (tous types)
            result[str(k)] = {
                "label":   labels.get(k, str(k)),
                "by_type": by_type,
                "by_year": compute_by_year(muts),
                "total":   len(muts),
            }
        return result

    # Arrondissements
    arr_stats = build_group_stats(
        all_mutations,
        lambda m: m['arr'],
        {i: f"Paris {ARR_LABELS[i]} arr." for i in range(1, 21)}
    )

    # Secteurs encadrement loyers
    sect_stats = build_group_stats(
        all_mutations,
        lambda m: ARR_TO_SECT.get(m['arr']),
        {k: f"Secteur {k} — {v}" for k, v in SECTEURS.items()}
    )

    # Evolution globale Paris (tous arrondissements, Appartement)
    apparts = [m for m in all_mutations if 'appartement' in m['type'].lower()]
    global_by_year = compute_by_year(apparts)
    global_stats   = compute_stats(apparts)

    # Metadata
    meta = {
        "generated_at":       datetime.utcnow().isoformat() + "Z",
        "source":             "DGFiP / Etalab — Licence Ouverte 2.0",
        "url":                "https://files.data.gouv.fr/geo-dvf/latest/",
        "annees":             ANNEES,
        "total_mutations":    len(all_mutations),
        "total_transactions": len(apparts),
        "periode":            f"{min(ANNEES)}–{max(ANNEES)}",
    }

    output = {
        "meta":          meta,
        "global":        {"stats": global_stats, "by_year": global_by_year},
        "arrondissements": arr_stats,
        "secteurs":      sect_stats,
        "secteurs_ref":  {str(k): v for k, v in SECTEURS.items()},
        "arr_to_sect":   {str(k): v for k, v in ARR_TO_SECT.items()},
    }

    with open(OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    size_kb = os.path.getsize(OUTPUT) / 1024
    print(f"\n✓ {OUTPUT} généré ({size_kb:.0f} Ko)")
    print(f"  {len(all_mutations)} mutations · {len(apparts)} appartements")
    print(f"  Arrondissements : {len(arr_stats)} | Secteurs : {len(sect_stats)}")
    print(f"  Évolution : {list(global_by_year.keys())}")

if __name__ == '__main__':
    main()

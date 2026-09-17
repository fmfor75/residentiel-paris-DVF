#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_geo.py — construit le référentiel géographique versionné dans data/geo/.

À lancer à la main (pas dans le workflow) : les sorties sont commitées, le pipeline
process_dvf.py ne dépend jamais du réseau pour la géographie.

Sources relevées le 17/09/2026 :
  - Paris, 80 quartiers administratifs : opendata.paris.fr, jeu `quartier_paris` (GeoJSON, champs c_qu 1–80, l_qu, c_ar).
  - Zonage officiel de l'encadrement des loyers : opendata.paris.fr, jeu `logement-encadrement-des-loyers`
    (id_zone 1–14 ↔ id_quartier 1–80). Les zones regroupent les quartiers par niveau de loyer, pas par
    contiguïté : la zone 2 va du Palais-Royal à la Chaussée-d'Antin.
  - Boulogne-Billancourt, 42 IRIS : IGN géoplateforme, WFS `STATISTICALUNITS.IRISGE:iris_ge`, filtre
    code_insee. Les IRIS portent le nom de leur quartier suivi d'un numéro ("Trapèze 3") : on les
    dissout par nom → 10 quartiers. Le même service donne les IRIS de toute commune (lot 4).

Incident à l'origine de ce fichier : les « secteurs DRIHL S1–S14 » du dashboard n'étaient pas le zonage
officiel mais un découpage par arrondissements avec des seuils de latitude qui coupaient des quartiers
en deux et inversaient les étiquettes (les Épinettes tombaient dans « Opéra – Grands Boulevards »,
les Ternes dans « Épinettes – Batignolles »). Ici, un secteur maison = une liste de quartiers entiers.

Sorties :
  data/geo/quartiers.geojson  — un polygone par quartier, propriétés : id, nom, commune, arr, zone, secteur
  data/geo/referentiel.json   — libellés des groupes (zones, secteurs, arrondissements, communes) et relevé
"""
import os, re, sys, json, math, requests
from collections import defaultdict, Counter

OUT_DIR = "data/geo"
URL_QUARTIERS = "https://opendata.paris.fr/api/explore/v2.1/catalog/datasets/quartier_paris/exports/geojson"
URL_ZONES = ("https://opendata.paris.fr/api/explore/v2.1/catalog/datasets/logement-encadrement-des-loyers/records"
             "?select=id_zone,id_quartier,nom_quartier&group_by=id_zone,id_quartier,nom_quartier&limit=100")
URL_IRIS = ("https://data.geopf.fr/wfs/ows?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature"
            "&TYPENAMES=STATISTICALUNITS.IRISGE:iris_ge&OUTPUTFORMAT=application/json&SRSNAME=EPSG:4326"
            "&CQL_FILTER=code_insee='{insee}'")

# ── Secteurs maison Paris (S1–S14) : arrondissements entiers + quartiers nommés pour les arrondissements partagés
SECTEURS_PARIS = {
    1:  ("Louvre – Opéra",              {"arr": [1, 2]}),
    2:  ("Marais – Bastille",           {"arr": [3, 4]}),
    3:  ("Île de la Cité – Luxembourg", {"arr": [5]}),
    4:  ("Saint-Germain – Invalides",   {"arr": [6, 7]}),
    5:  ("Champs-Élysées – Trocadéro",  {"arr": [8, 16]}),
    6:  ("Opéra – Grands Boulevards",   {"arr": [9], "quartiers": ["Ternes", "Plaine de Monceaux"]}),
    7:  ("Montmartre – Belleville",     {"arr": [10, 18], "quartiers": ["Villette", "Pont-de-Flandre"]}),
    8:  ("Nation – Vincennes",          {"arr": [12]}),
    9:  ("Grenelle – Convention",       {"arr": [15]}),
    10: ("Montrouge – Alésia",          {"arr": [14], "quartiers": ["Maison-Blanche"]}),
    11: ("Épinettes – Batignolles",     {"quartiers": ["Epinettes", "Batignolles"]}),
    12: ("Buttes-Chaumont",             {"quartiers": ["Amérique", "Combat"]}),
    13: ("Ménilmontant – Oberkampf",    {"arr": [11, 20]}),
    14: ("Ivry – Tolbiac – Gobelins",   {"quartiers": ["Salpêtrière", "Gare", "Croulebarbe"]}),
}

COMMUNES = {
    "75056": {"nom": "Paris", "prefix": "P"},
    "92012": {"nom": "Boulogne-Billancourt", "prefix": "B"},
}

def get(url, timeout=120):
    r = requests.get(url, timeout=timeout); r.raise_for_status(); return r

# ── Dissolution d'IRIS par annulation des arêtes partagées (pas de dépendance shapely) ──────────
def rings_of(geom):
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    return [ring for poly in polys for ring in poly]   # extérieurs + trous, tous traités comme arêtes

def dissolve(geoms):
    """Union de polygones topologiquement cohérents (sommets partagés exacts) : les arêtes présentes
    deux fois sont intérieures et disparaissent ; les arêtes restantes sont chaînées en anneaux."""
    edges = Counter()
    for g in geoms:
        for ring in rings_of(g):
            for a, b in zip(ring, ring[1:]):
                a, b = tuple(a), tuple(b)
                if a == b: continue
                edges[(a, b) if a < b else (b, a)] += 1
    border = [e for e, n in edges.items() if n == 1]
    nxt = defaultdict(list)
    for a, b in border: nxt[a].append(b); nxt[b].append(a)
    rings = []; used = set()
    for start in list(nxt):
        if start in used: continue
        ring = [start]; used.add(start); cur = start
        while True:
            cand = [p for p in nxt[cur] if p not in used]
            if not cand:
                break
            cur = cand[0]; used.add(cur); ring.append(cur)
        ring.append(start); rings.append([list(p) for p in ring])
    # anneau extérieur = plus grande aire ; les autres = trous ou îlots. Ici on garde tous les anneaux
    # comme polygones séparés si leur aire est significative (île Seguin etc.), sinon comme trous.
    def area(r): return abs(sum(r[i][0]*r[i+1][1]-r[i+1][0]*r[i][1] for i in range(len(r)-1))) / 2
    rings.sort(key=area, reverse=True)
    if len(rings) == 1: return {"type": "Polygon", "coordinates": rings}
    return {"type": "MultiPolygon", "coordinates": [[r] for r in rings if area(r) > 1e-8]}

def pip(x, y, ring):
    inside = False; j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]; xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi: inside = not inside
        j = i
    return inside

def area_geom(g):
    def area(r): return abs(sum(r[i][0]*r[i+1][1]-r[i+1][0]*r[i][1] for i in range(len(r)-1))) / 2
    polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
    return sum(area(p[0]) - sum(area(h) for h in p[1:]) for p in polys)

def main():
    os.makedirs(OUT_DIR, exist_ok=True); releve = {}
    # ── Paris
    q = get(URL_QUARTIERS).json()["features"]
    zones = {r["id_quartier"]: r["id_zone"] for r in get(URL_ZONES).json()["results"]}
    assert len(q) == 80 and len(zones) == 80, f"attendu 80 quartiers/80 zones, lu {len(q)}/{len(zones)}"
    par_nom = {f["properties"]["l_qu"]: f for f in q}
    sect_of = {}
    for sid, (nom, regle) in SECTEURS_PARIS.items():
        for f in q:
            p = f["properties"]
            if p["c_ar"] in regle.get("arr", []) or p["l_qu"] in regle.get("quartiers", []):
                assert int(p["c_qu"]) not in sect_of, f"quartier {p['l_qu']} dans deux secteurs"
                sect_of[int(p["c_qu"])] = sid
        for qn in regle.get("quartiers", []): assert qn in par_nom, f"quartier inconnu dans SECTEURS_PARIS : {qn}"
    manquants = [f["properties"]["l_qu"] for f in q if int(f["properties"]["c_qu"]) not in sect_of]
    assert not manquants, f"quartiers sans secteur maison : {manquants}"
    features = []
    for f in sorted(q, key=lambda f: int(f["properties"]["c_qu"])):
        p = f["properties"]; cq = int(p["c_qu"])
        features.append({"type": "Feature", "geometry": f["geometry"],
                         "properties": {"id": f"P{cq}", "nom": p["l_qu"], "commune": "75056", "arr": p["c_ar"],
                                        "zone": f"Z{zones[cq]}", "secteur": str(sect_of[cq])}})
    releve["paris"] = {"quartiers": 80, "source_quartiers": URL_QUARTIERS, "source_zones": URL_ZONES.split("?")[0]}
    # ── Boulogne : IRIS → quartiers par nom
    iris = get(URL_IRIS.format(insee="92012")).json()["features"]
    groupes = defaultdict(list)
    for f in iris: groupes[re.sub(r"\s+\d+$", "", f["properties"]["nom_iris"])].append(f["geometry"])
    noms = sorted(groupes, key=lambda n: -len(groupes[n]))
    for i, nom in enumerate(noms, 1):
        g = dissolve(groupes[nom])
        a_src = sum(area_geom(x) for x in groupes[nom]); a_dst = area_geom(g)
        assert abs(a_src - a_dst) / a_src < 0.01, f"{nom}: aire dissoute {a_dst:.3e} ≠ somme IRIS {a_src:.3e}"
        features.append({"type": "Feature", "geometry": g,
                         "properties": {"id": f"B{i}", "nom": nom, "commune": "92012", "arr": None,
                                        "zone": None, "secteur": f"B{i}"}})
    releve["boulogne"] = {"iris": len(iris), "quartiers": len(noms), "source": URL_IRIS.split("?")[0]}
    # ── Référentiel des groupes
    ref = {
        "communes": {k: v["nom"] for k, v in COMMUNES.items()},
        "zones": {f"Z{z}": {"nom": f"Zone {z} (encadrement des loyers)", "commune": "75056",
                            "quartiers": sorted(f"P{cq}" for cq, zz in zones.items() if zz == z)} for z in range(1, 15)},
        "secteurs": {**{str(s): {"nom": nom, "commune": "75056",
                                 "quartiers": sorted(f"P{cq}" for cq, ss in sect_of.items() if ss == s),
                                 "arrLabel": ", ".join(f"{a}e" if a > 1 else "1er" for a in regle.get("arr", []))
                                             + (" + " if regle.get("arr") and regle.get("quartiers") else "")
                                             + ", ".join(regle.get("quartiers", []))}
                        for s, (nom, regle) in SECTEURS_PARIS.items()},
                     **{f"B{i}": {"nom": nom, "commune": "92012", "quartiers": [f"B{i}"], "arrLabel": "Boulogne-Billancourt"}
                        for i, nom in enumerate(noms, 1)},
                     "B0": {"nom": "Boulogne-Billancourt (commune entière)", "commune": "92012",
                            "quartiers": [f"B{i}" for i in range(1, len(noms) + 1)], "arrLabel": "92100"}},
        "arrondissements": {str(a): {"nom": f"Paris {'1er' if a == 1 else str(a) + 'e'} arr.", "commune": "75056"} for a in range(1, 21)},
        "releve": releve,
    }
    with open(f"{OUT_DIR}/quartiers.geojson", "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f, ensure_ascii=False, separators=(",", ":"))
    with open(f"{OUT_DIR}/referentiel.json", "w", encoding="utf-8") as f:
        json.dump(ref, f, ensure_ascii=False, indent=1)
    print(f"✓ {len(features)} quartiers ({OUT_DIR}/quartiers.geojson, {os.path.getsize(f'{OUT_DIR}/quartiers.geojson')/1e3:.0f} Ko)")
    for s in ref["secteurs"].values(): print(f"  {s['nom']:<40} {len(s['quartiers']):>2} quartiers  {s['arrLabel']}")
    # Contrôle : un point par quartier (centroïde approx.) retombe dans son propre polygone et dans aucun autre
    for f in features:
        ring = (f["geometry"]["coordinates"][0] if f["geometry"]["type"] == "Polygon" else f["geometry"]["coordinates"][0][0])
        cx = sum(p[0] for p in ring) / len(ring); cy = sum(p[1] for p in ring) / len(ring)
        hits = [g["properties"]["id"] for g in features if g["properties"]["commune"] == f["properties"]["commune"]
                and any(pip(cx, cy, r[0]) for r in ([g["geometry"]["coordinates"]] if g["geometry"]["type"] == "Polygon" else g["geometry"]["coordinates"]))]
        if hits != [f["properties"]["id"]]: print(f"  ⚠ centroïde de {f['properties']['id']} {f['properties']['nom']} → {hits}")
    return 0

if __name__ == "__main__":
    sys.exit(main())

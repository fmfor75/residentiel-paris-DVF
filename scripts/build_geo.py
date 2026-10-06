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
  - Communes hors Paris : IRIS de l'IGN géoplateforme, WFS `STATISTICALUNITS.IRISGE:iris_ge`, filtre code_insee,
    dissous en quartiers. Relevé du 06/10/2026 (lot 9) : la convention de nommage des IRIS varie d'une commune à
    l'autre, aucune règle unique ne convient —
      · « nom + numéro » (Boulogne « Trapèze 3 », Levallois « Eiffel 4 ») : dissolution par nom ;
      · « grand quartier » INSEE (chiffres 5–6 du code IRIS) quand la commune en a plusieurs (Clichy 6, Asnières 7,
        Puteaux 4, Saint-Maur 8, Vincennes 4) ; les noms d'IRIS d'Asnières portent des chiffres romains ;
      · ni l'un ni l'autre (Bois-Colombes 12 noms composés, Saint-Mandé 9, Saint-Ouen « Secteur 1 » à « Secteur 18 »,
        un seul grand quartier chacune) : chaque IRIS est un quartier.
    La méthode est choisie explicitement par commune dans COMMUNES (pas d'automatisme : Boulogne doit rester
    identique au lot 4) ; le relevé (IRIS lus, méthode, quartiers) est consigné dans referentiel.json.

Incident à l'origine de ce fichier : les « secteurs DRIHL S1–S14 » du dashboard n'étaient pas le zonage
officiel mais un découpage par arrondissements avec des seuils de latitude qui coupaient des quartiers
en deux et inversaient les étiquettes (les Épinettes tombaient dans « Opéra – Grands Boulevards »,
les Ternes dans « Épinettes – Batignolles »). Ici, un secteur maison = une liste de quartiers entiers.

Sorties :
  data/geo/quartiers.geojson  — un polygone par quartier, propriétés : id, nom, commune, arr, zone, secteur
  data/geo/referentiel.json   — libellés des groupes (zones, secteurs, arrondissements), communes (nom, préfixe,
                                quartiers) et relevé par commune
"""
import os, re, sys, json, math, time, requests
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

# methode : "nom" = dissolution des IRIS par nom sans numéro final ; "gq" = grand quartier INSEE (code IRIS[5:7]) ;
# "iris" = un quartier par IRIS. Les préfixes sont à deux lettres (sauf P et B, antérieurs : les URL partagées les portent).
COMMUNES = {
    "75056": {"nom": "Paris", "prefix": "P"},
    "92012": {"nom": "Boulogne-Billancourt", "prefix": "B", "methode": "nom"},
    # noms : libellé imposé par code de grand quartier quand la composition automatique tombe mal (01 à Clichy :
    # l'IRIS « SNCF » — les emprises ferroviaires — est le plus étendu, mais le quartier est le centre-ville)
    "92024": {"nom": "Clichy", "prefix": "CL", "methode": "gq", "noms": {"01": "Centre Ville – Vendôme"}},
    "92044": {"nom": "Levallois-Perret", "prefix": "LV", "methode": "nom"},
    "92004": {"nom": "Asnières-sur-Seine", "prefix": "AS", "methode": "gq"},
    "92009": {"nom": "Bois-Colombes", "prefix": "BC", "methode": "iris"},
    "92062": {"nom": "Puteaux", "prefix": "PU", "methode": "gq"},
    "93070": {"nom": "Saint-Ouen-sur-Seine", "prefix": "SO", "methode": "iris"},
    "94068": {"nom": "Saint-Maur-des-Fossés", "prefix": "SM", "methode": "gq"},
    "94067": {"nom": "Saint-Mandé", "prefix": "SD", "methode": "iris"},
    "94080": {"nom": "Vincennes", "prefix": "VI", "methode": "gq"},
}
STEM = re.compile(r"\s+(\d+|[IVX]+)$")   # « Trapèze 3 », « Flachat II » → « Trapèze », « Flachat »

def grouper_iris(iris, methode, noms=None):
    """Regroupe les IRIS d'une commune en quartiers selon la méthode. Renvoie [(nom, [geometries])] dans
    l'ordre des identifiants : nom → effectif décroissant (ordre du lot 4), gq → code du grand quartier, iris → code IRIS."""
    def stem(f): return STEM.sub("", f["properties"]["nom_iris"])
    if methode == "nom":
        g = defaultdict(list)
        for f in iris: g[stem(f)].append(f)
        noms = sorted(g, key=lambda n: -len(g[n]))
        return [(n, g[n]) for n in noms]
    if methode == "gq":
        g = defaultdict(list)
        for f in iris: g[f["properties"]["code_iris"][5:7]].append(f)
        assert len(g) >= 2, f"un seul grand quartier : méthode gq inapplicable"
        out = []
        for code in sorted(g):
            # nom du grand quartier : la racine commune des noms d'IRIS si elle est unique, sinon les deux racines
            # les plus étendues (l'INSEE ne publie pas de libellé de grand quartier dans ce flux)
            racines = defaultdict(float)
            for f in g[code]: racines[stem(f)] += area_geom(f["geometry"])
            top = sorted(racines, key=lambda r: -racines[r])
            out.append(((noms or {}).get(code) or (top[0] if len(top) == 1 else " – ".join(top[:2])), g[code]))
        return out
    if methode == "iris":
        return [(f["properties"]["nom_iris"], [f]) for f in sorted(iris, key=lambda f: f["properties"]["code_iris"])]
    raise ValueError(methode)

def get(url, timeout=120, essais=4):
    # Le WFS IGN coupe la connexion quand on l'enchaîne commune après commune (constaté le 06/10/2026) : reprises espacées.
    for k in range(essais):
        try:
            r = requests.get(url, timeout=timeout); r.raise_for_status(); return r
        except requests.exceptions.ConnectionError:
            if k == essais - 1: raise
            time.sleep(2 + 2 * k)

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
    # ── Communes hors Paris : IRIS → quartiers selon la méthode déclarée. Pas de secteur ni d'arrondissement :
    # le niveau au-dessus du quartier est la commune (lot 9 ; avant, Boulogne avait un pseudo-secteur par quartier).
    communes_ref = {"75056": {"nom": "Paris", "prefix": "P", "quartiers": [f["properties"]["id"] for f in features]}}
    for insee, cfg in COMMUNES.items():
        if insee == "75056": continue
        iris = get(URL_IRIS.format(insee=insee)).json()["features"]
        assert iris and all(f["properties"]["code_insee"] == insee for f in iris), f"{insee} : IRIS inattendus"
        groupes = grouper_iris(iris, cfg["methode"], cfg.get("noms")); ids = []
        for i, (nom, fs) in enumerate(groupes, 1):
            geoms = [f["geometry"] for f in fs]
            g = dissolve(geoms) if len(geoms) > 1 else geoms[0]
            a_src = sum(area_geom(x) for x in geoms); a_dst = area_geom(g)
            assert abs(a_src - a_dst) / a_src < 0.01, f"{insee} {nom}: aire dissoute {a_dst:.3e} ≠ somme IRIS {a_src:.3e}"
            qid = f"{cfg['prefix']}{i}"; ids.append(qid)
            features.append({"type": "Feature", "geometry": g,
                             "properties": {"id": qid, "nom": nom, "commune": insee, "arr": None, "zone": None, "secteur": None}})
        communes_ref[insee] = {"nom": cfg["nom"], "prefix": cfg["prefix"], "quartiers": ids}
        releve[insee] = {"nom": cfg["nom"], "iris": len(iris), "methode": cfg["methode"], "quartiers": len(ids), "source": URL_IRIS.split("?")[0]}
        print(f"  {cfg['nom']:<24} {len(iris):>3} IRIS → {len(ids):>2} quartiers ({cfg['methode']})")
    # ── Référentiel des groupes
    ref = {
        "communes": communes_ref,
        "zones": {f"Z{z}": {"nom": f"Zone {z} (encadrement des loyers)", "commune": "75056",
                            "quartiers": sorted(f"P{cq}" for cq, zz in zones.items() if zz == z)} for z in range(1, 15)},
        "secteurs": {**{str(s): {"nom": nom, "commune": "75056",
                                 "quartiers": sorted(f"P{cq}" for cq, ss in sect_of.items() if ss == s),
                                 "arrLabel": ", ".join(f"{a}e" if a > 1 else "1er" for a in regle.get("arr", []))
                                             + (" + " if regle.get("arr") and regle.get("quartiers") else "")
                                             + ", ".join(regle.get("quartiers", []))}
                        for s, (nom, regle) in SECTEURS_PARIS.items()}},
        "arrondissements": {str(a): {"nom": f"Paris {'1er' if a == 1 else str(a) + 'e'} arr.", "commune": "75056"} for a in range(1, 21)},
        "releve": releve,
    }
    with open(f"{OUT_DIR}/quartiers.geojson", "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f, ensure_ascii=False, separators=(",", ":"))
    with open(f"{OUT_DIR}/referentiel.json", "w", encoding="utf-8") as f:
        json.dump(ref, f, ensure_ascii=False, indent=1)
    print(f"✓ {len(features)} quartiers ({OUT_DIR}/quartiers.geojson, {os.path.getsize(f'{OUT_DIR}/quartiers.geojson')/1e3:.0f} Ko)")
    for s in ref["secteurs"].values(): print(f"  {s['nom']:<40} {len(s['quartiers']):>2} quartiers  {s['arrLabel']}")
    # Contrôle par grille (lot 9) : dans chaque commune, tout point intérieur tombe dans exactement un quartier et chaque
    # quartier contient au moins un point. L'ancien contrôle par centroïde moyen signalait à tort les polygones concaves
    # (La Pie à Saint-Maur, Grésillons à Asnières) : un contrôle qui crie au loup finit ignoré.
    def inside(g, x, y):
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        return any(pip(x, y, p[0]) and not any(pip(x, y, h) for h in p[1:]) for p in polys)
    par_commune = defaultdict(list)
    for f in features: par_commune[f["properties"]["commune"]].append(f)
    for com, fs in par_commune.items():
        pts = [pt for f in fs for poly in (f["geometry"]["coordinates"] if f["geometry"]["type"] == "MultiPolygon" else [f["geometry"]["coordinates"]]) for pt in poly[0]]
        x0, x1 = min(p[0] for p in pts), max(p[0] for p in pts); y0, y1 = min(p[1] for p in pts), max(p[1] for p in pts)
        N = 40 if com != "75056" else 80; multi = 0; vus = Counter()
        for i in range(N):
            for j in range(N):
                x = x0 + (x1 - x0) * (i + .5) / N; y = y0 + (y1 - y0) * (j + .5) / N
                hits = [f["properties"]["id"] for f in fs if inside(f["geometry"], x, y)]
                if len(hits) > 1: multi += 1
                for h in hits: vus[h] += 1
        vides = [f["properties"]["id"] for f in fs if not vus[f["properties"]["id"]]]
        assert multi == 0 and not vides, f"{com} : {multi} points dans plusieurs quartiers, quartiers sans point {vides}"
    print(f"  ✓ contrôle par grille : aucun chevauchement, aucun quartier vide ({len(par_commune)} communes)")
    return 0

if __name__ == "__main__":
    sys.exit(main())

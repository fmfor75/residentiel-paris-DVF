# -*- coding: utf-8 -*-
"""
Jeu de données jetable au format CSV géolocalisé Etalab (geo-dvf), servi en HTTP local.

Il reproduit la topologie réelle des sources (archive glissante + millésimes) et injecte des cas
connus (VEFA, ventes multi-logements, local commercial, Carrez incohérente, doublons…) avec des
effectifs exacts, pour que les compteurs du pipeline soient vérifiés à l'unité près.

Les en-têtes sont ceux du format geo-dvf ; le relevé réel (`--probe`) confirmera au premier run
qu'ils correspondent — si non, c'est ce fichier qu'il faut corriger, pas le parseur qui sait échouer.
"""
import os, csv, gzip, json, random, threading, functools
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

HEADER = ("id_mutation,date_mutation,numero_disposition,nature_mutation,valeur_fonciere,adresse_numero,"
          "adresse_suffixe,adresse_nom_voie,adresse_code_voie,code_postal,code_commune,nom_commune,"
          "code_departement,ancien_code_commune,ancien_nom_commune,id_parcelle,ancien_id_parcelle,"
          "numero_volume,lot1_numero,lot1_surface_carrez,lot2_numero,lot2_surface_carrez,lot3_numero,"
          "lot3_surface_carrez,lot4_numero,lot4_surface_carrez,lot5_numero,lot5_surface_carrez,nombre_lots,"
          "code_type_local,type_local,surface_reelle_bati,nombre_pieces_principales,code_nature_culture,"
          "nature_culture,code_nature_culture_speciale,nature_culture_speciale,surface_terrain,longitude,latitude").split(",")

TYPE_CODES = {"Maison": "1", "Appartement": "2", "Dépendance": "3", "Local industriel. commercial ou assimilé": "4"}

def row(mid, date, nature, val, code, parcelle, type_local, surf, nbpp, lon, lat, carrez1=0, carrez2=0):
    r = {h: "" for h in HEADER}
    r.update({"id_mutation": mid, "date_mutation": date, "numero_disposition": "1", "nature_mutation": nature,
              "valeur_fonciere": f"{val:.2f}", "adresse_nom_voie": "RUE DE, LA VIRGULE",   # virgule volontaire : teste le csv quoté
              "code_postal": "75008" if code.startswith("75") else "92100",
              "code_commune": code, "nom_commune": "Paris" if code.startswith("75") else COMMUNES.get(code, ("Ailleurs",))[0],
              "code_departement": code[:2], "id_parcelle": parcelle,
              "lot1_surface_carrez": f"{carrez1:.2f}" if carrez1 else "", "lot2_surface_carrez": f"{carrez2:.2f}" if carrez2 else "",
              "nombre_lots": "1", "code_type_local": TYPE_CODES.get(type_local, ""), "type_local": type_local,
              "surface_reelle_bati": f"{surf:.0f}" if surf else "", "nombre_pieces_principales": str(nbpp) if nbpp else "",
              "longitude": f"{lon:.6f}" if lon else "", "latitude": f"{lat:.6f}" if lat else ""})
    return r

# Communes hors Paris (lot 9) : point intérieur central et demi-étendue (lat, lon) relevés sur data/geo/quartiers.geojson,
# pour que les ventes générées tombent dans les polygones réels. Le 92 contient aussi une commune hors périmètre (Sèvres)
# qui doit être ignorée par le filtre code_commune.
COMMUNES = {"92012": ("Boulogne-Billancourt", 48.8371, 2.2424, 0.012, 0.015), "92024": ("Clichy", 48.9043, 2.3037, 0.007, 0.012),
            "92044": ("Levallois-Perret", 48.8944, 2.287, 0.006, 0.011), "92004": ("Asnières-sur-Seine", 48.9177, 2.2942, 0.011, 0.02),
            "92009": ("Bois-Colombes", 48.9148, 2.2686, 0.008, 0.008), "92062": ("Puteaux", 48.882, 2.238, 0.009, 0.011),
            "93070": ("Saint-Ouen-sur-Seine", 48.9115, 2.3324, 0.008, 0.013), "94068": ("Saint-Maur-des-Fossés", 48.8003, 2.4913, 0.011, 0.022),
            "94067": ("Saint-Mandé", 48.8417, 2.4193, 0.005, 0.005), "94080": ("Vincennes", 48.847, 2.4388, 0.004, 0.014),
            "92072": ("Sèvres (hors périmètre)", 48.8238, 2.2096, 0.005, 0.005)}
_GEO = None
def point_dans_commune(code, rng, centre=None):
    """Point tiré au hasard DANS les polygones réels de la commune (data/geo/quartiers.geojson) ; les communes ne sont
    pas des rectangles : un tirage dans la bbox mettait 14 % des ventes hors quartier et faisait refuser le run.
    Sèvres (hors référentiel) garde un tirage dans sa bbox : ses lignes sont filtrées avant la géographie."""
    global _GEO
    if _GEO is None:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        feats = json.load(open(os.path.join(root, "data/geo/quartiers.geojson"), encoding="utf-8"))["features"]
        _GEO = {}
        for f in feats:
            g = f["geometry"]; polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
            _GEO.setdefault(f["properties"]["commune"], []).extend(polys)
    def pip(x, y, ring):
        inside = False; j = len(ring) - 1
        for i in range(len(ring)):
            xi, yi = ring[i]; xj, yj = ring[j]
            if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi: inside = not inside
            j = i
        return inside
    clat, clon, dlat, dlon = centre or COMMUNES[code][1:]
    for _ in range(200):
        lat = clat + rng.uniform(-dlat, dlat); lon = clon + rng.uniform(-dlon, dlon)
        if code not in _GEO or any(pip(lon, lat, p[0]) and not any(pip(lon, lat, h) for h in p[1:]) for p in _GEO[code]): return lat, lon
    return clat, clon

# Centres approximatifs par arrondissement (lat, lon) pour une géoloc plausible
ARR_CENTRE = {1:(48.862,2.336),2:(48.868,2.342),3:(48.863,2.360),4:(48.854,2.357),5:(48.844,2.350),6:(48.849,2.333),
              7:(48.856,2.312),8:(48.873,2.312),9:(48.877,2.337),10:(48.876,2.360),11:(48.859,2.380),12:(48.840,2.388),
              13:(48.828,2.362),14:(48.829,2.326),15:(48.840,2.293),16:(48.860,2.262),17:(48.887,2.307),18:(48.892,2.348),
              19:(48.887,2.384),20:(48.864,2.398)}

def gen_year(dep, annee, n, rng, prix_base):
    """n mutations « normales » : 1 appartement (parfois + dépendance), prix croissant par année, 8 % de maisons."""
    rows = []
    for i in range(n):
        if dep == "75":
            arr = rng.randint(1, 20); code = f"751{arr:02d}"
            lat, lon = point_dans_commune("75056", rng, (*ARR_CENTRE[arr], 0.008, 0.01))   # dans Paris (un point du 16e peut sortir de la ville)
        else:
            code = rng.choice([c for c in COMMUNES if c.startswith(dep)]); lat, lon = point_dans_commune(code, rng)
        surf = max(10, int(rng.lognormvariate(3.8, 0.45)))
        ppm2 = prix_base * (1 + 0.04 * (annee - 2014)) * rng.lognormvariate(0, 0.18)
        tl = "Maison" if rng.random() < 0.08 else "Appartement"
        mid = f"{annee}-{dep}-{i:06d}"; date = f"{annee}-{rng.randint(1,12):02d}-{rng.randint(1,28):02d}"
        parc = f"{code}000AB{i:04d}"
        rows.append(row(mid, date, "Vente", ppm2 * surf, code, parc, tl, surf, max(1, surf // 22), lon, lat,
                        carrez1=surf * rng.uniform(0.96, 1.02) if rng.random() < 0.6 else 0))
        if rng.random() < 0.3:   # dépendance vendue avec le logement : doit rester retenue
            rows.append(row(mid, date, "Vente", ppm2 * surf, code, parc, "Dépendance", 0, 0, lon, lat))
    return rows

def cas_speciaux(annee=2024):
    """Cas injectés dans 75/2024 avec effectifs exacts. Renvoie (rows, attendus)."""
    lat, lon = 48.873, 2.312; code = "75108"; R = []; att = {}
    def m(i): return f"{annee}-SPEC-{i:03d}"
    # 5 VEFA → excl_nature_non_vente
    for i in range(5): R.append(row(m(i), f"{annee}-03-01", "Vente en l'état futur d'achèvement", 600000, code, f"P{i}", "Appartement", 50, 2, lon, lat))
    att["excl_nature_non_vente"] = 5
    # 4 ventes de 2 appartements → excl_plusieurs_logements
    for i in range(10, 14):
        R.append(row(m(i), f"{annee}-03-02", "Vente", 1500000, code, f"P{i}", "Appartement", 60, 3, lon, lat))
        R.append(row(m(i), f"{annee}-03-02", "Vente", 1500000, code, f"P{i}b", "Appartement", 70, 3, lon, lat))
    att["excl_plusieurs_logements"] = 4
    # 3 appartement + local commercial → excl_local_pro_dans_la_vente
    for i in range(20, 23):
        R.append(row(m(i), f"{annee}-03-03", "Vente", 900000, code, f"P{i}", "Appartement", 60, 3, lon, lat))
        R.append(row(m(i), f"{annee}-03-03", "Vente", 900000, code, f"P{i}", "Local industriel. commercial ou assimilé", 40, 0, lon, lat))
    att["excl_local_pro_dans_la_vente"] = 3
    # 2 Carrez cohérentes (45 vs bâti 47) → source carrez ; 1 Carrez de cave (8 vs 50) → source bati
    for i in range(30, 32): R.append(row(m(i), f"{annee}-03-04", "Vente", 500000, code, f"P{i}", "Appartement", 47, 2, lon, lat, carrez1=45))
    R.append(row(m(32), f"{annee}-03-04", "Vente", 500000, code, "P32", "Appartement", 50, 2, lon, lat, carrez1=8))
    att["surface_source:carrez_speciaux"] = 2; att["surface_source:bati_speciaux"] = 1
    # 1 ppm2 aberrant (100 000 €/m²) → excl_ppm2_hors_bornes ; 1 surface 5 m² → excl_surface_hors_bornes
    R.append(row(m(40), f"{annee}-03-05", "Vente", 5000000, code, "P40", "Appartement", 50, 2, lon, lat)); att["excl_ppm2_hors_bornes"] = 1
    R.append(row(m(41), f"{annee}-03-05", "Vente", 50000, code, "P41", "Appartement", 5, 1, lon, lat));    att["excl_surface_hors_bornes"] = 1
    # 1 ligne d'appartement dupliquée à l'identique → retenue une seule fois (pas « plusieurs logements »)
    for _ in range(2): R.append(row(m(50), f"{annee}-03-06", "Vente", 400000, code, "P50", "Appartement", 40, 2, lon, lat))
    att["doublon_retenu"] = 1
    # 1 valeur foncière nulle → excl_valeur_nulle
    R.append(row(m(60), f"{annee}-03-07", "Vente", 0, code, "P60", "Appartement", 40, 2, lon, lat)); att["excl_valeur_nulle"] = 1
    # 1 sans géoloc dans le 17e → sans_geoloc, secteur = S6 par défaut (ARR_TO_SECT)
    R.append(row(m(70), f"{annee}-03-08", "Vente", 400000, "75117", "P70", "Appartement", 40, 2, 0, 0)); att["sans_geoloc"] = 1
    # 1 vente sans aucun logement (dépendance seule) → excl_sans_logement
    R.append(row(m(80), f"{annee}-03-09", "Vente", 30000, code, "P80", "Dépendance", 0, 0, lon, lat)); att["excl_sans_logement"] = 1
    att["retenues_speciaux"] = 2 + 1 + 1 + 1   # carrez×2, cave, doublon, sans géoloc
    return R, att

def write_gz(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HEADER); w.writeheader(); w.writerows(rows)

def build(root, variant="normal", n75=600, n92=500, n93=500, n94=500, seed=1):
    """Construit l'arborescence de sources dans `root`.
    variant : 'normal' | 'annee_creuse' (2018 quasi vide) | 'partiel_2019' (2019 seulement dans un millésime d'octobre 2019)."""
    rng = random.Random(seed); attendus = {}
    for annee in range(2014, 2027):
        r75 = gen_year("75", annee, n75 if not (variant == "annee_creuse" and annee == 2018) else 120, rng, 8000)
        r92 = gen_year("92", annee, n92, rng, 7000); r93 = gen_year("93", annee, n93, rng, 5000); r94 = gen_year("94", annee, n94, rng, 6000)
        if annee == 2024:
            spec, attendus = cas_speciaux(annee); r75 += spec
        if annee >= 2021:
            base = f"geo-dvf/latest/csv/{annee}/departements"
        elif annee >= 2016:
            base = f"oda/2021-04/csv/{annee}/departements"
        else:
            base = f"oda/2019-04/csv/{annee}/departements"
        if variant == "partiel_2019" and annee == 2019:
            base = f"oda/2019-10/csv/{annee}/departements"; r75 = r75[: len(r75) // 2]; r92 = r92[: len(r92) // 2]
        for dep, rows in (("75", r75), ("92", r92), ("93", r93), ("94", r94)):
            write_gz(os.path.join(root, base, f"{dep}.csv.gz"), rows)
    return attendus

class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *a): pass

def serve(root):
    """Sert `root` sur un port libre ; renvoie (serveur, url_base)."""
    handler = functools.partial(QuietHandler, directory=root)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"

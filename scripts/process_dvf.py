#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
process_dvf.py v13 — pipeline DVF → dvf_paris.json

Périmètre (lot 1) : Paris (75101–75120 → 14 secteurs) + Boulogne-Billancourt (92012 → quartiers).
Le référentiel ZONES est prêt à recevoir d'autres communes (lot 4).

Historique des incidents qui ont façonné ce fichier (v12 → v13) :
  - v12 définissait `download_recent` deux fois ; la seconde déballait 3 valeurs
    d'une fonction qui en renvoie 4 → ValueError à chaque run. Une seule définition ici.
  - 2019 Paris ne contenait que 11 224 mutations (source cquest « 201910 », TXT non
    géolocalisé, semestre 1 seulement) et Boulogne 2019 : 0. Les sources non
    géolocalisées / partielles sont abandonnées : on ne prend que les CSV
    géolocalisés Etalab, et un millésime qui couvre l'année entière.
  - 2020 absent : `geo-dvf/latest` est une archive glissante 5 ans. Chaque année
    est désormais rattachée au millésime le plus récent qui la contient
    (sondage HEAD des URLs candidates, résultat consigné dans meta.sources_used).
  - Rien n'était compté : une année vide avait l'air d'un succès. Chaque exclusion
    est comptée par motif ; une année anormalement creuse fait échouer le run.
  - Une vente d'immeuble entier (10 appartements) était comptée comme UN appartement
    au prix total / surface du plus grand lot. Règle explicite : exactement un
    logement (Appartement ou Maison) par mutation, dépendances tolérées.
"""

import os, sys, io, csv, gzip, json, time, argparse, statistics
from datetime import datetime, date
from collections import Counter, defaultdict
import requests

PARSER_VERSION = 13   # incrémenter à chaque changement de RÈGLE (pas de format de cache) → invalide le cache

# ══════════════════════════════════════════════════════════════════
# CONFIG SOURCES
# ══════════════════════════════════════════════════════════════════

GEODVF_LATEST = "https://files.data.gouv.fr/geo-dvf/latest/csv/{annee}/departements/{dep}.csv.gz"
ODA_DEP       = "https://files.opendatarchives.fr/cadastre.data.gouv.fr/data/etalab-dvf/{mil}/csv/{annee}/departements/{dep}.csv.gz"
ODA_FULL      = "https://files.opendatarchives.fr/cadastre.data.gouv.fr/data/etalab-dvf/{mil}/csv/{annee}/full.csv.gz"

FIRST_YEAR = 2014
TODAY      = date.today()
YEARS      = list(range(FIRST_YEAR, TODAY.year + 1))

# Millésimes DGFiP : publication en avril (données au 31/12 N-1) et octobre (au 30/06 N).
# Un millésime AAAA-MM couvre entièrement l'année Y si AAAA >= Y+1.
def millesimes_candidats():
    out = []
    for y in range(TODAY.year, 2018, -1):
        for m in ("10", "04"):
            out.append(f"{y}-{m}")
    return out

CACHE_FILE = "data/dvf_cache.json.gz"   # v13.1 : toutes les années, gzip (36 Mo → ~8 Mo), empreinte de source par entrée
OUTPUT     = "data/dvf_paris.json"

# ══════════════════════════════════════════════════════════════════
# CONFIG MÉTIER — une seule source de vérité, recopiée dans le JSON
# ══════════════════════════════════════════════════════════════════

# Bornes de plausibilité. C'est LE seul endroit de prudence du pipeline (§4.2 méthode) :
# les percentiles P10/P90 n'y sont pas sensibles, seule la moyenne l'est.
# Mesuré sur 161 053 appartements Paris 2014–2019 : p1 ≈ 2 300 €/m², p99 ≈ 19–23 000 €/m².
PPM2_MIN, PPM2_MAX = 1_000, 40_000
SURF_MIN, SURF_MAX = 9, 400          # m² — alignées sur les typologies T1..T5

# Natures de mutation retenues. « Vente en l'état futur d'achèvement » (VEFA) = neuf,
# marché distinct de l'ancien : exclue et comptée. « Vente terrain à bâtir » : exclue.
NATURES_RETENUES = {"vente"}

TYPES_LOGEMENT = {"Appartement", "Maison"}
TYPES_ANNEXE   = {"Dépendance"}

TYPOLOGIES = [
    {"id": "T1", "surfMin": 9,   "surfMax": 30},
    {"id": "T2", "surfMin": 30,  "surfMax": 50},
    {"id": "T3", "surfMin": 50,  "surfMax": 70},
    {"id": "T4", "surfMin": 70,  "surfMax": 100},
    {"id": "T5", "surfMin": 100, "surfMax": 400},
]

# Fenêtres précalculées (années civiles, depuis la dernière année présente). "all" = tout.
FENETRES = [1, 3, 5, 10]

# Garde : une année complète dont le volume d'appartements est inférieur à cette fraction
# de la médiane des autres années complètes est considérée creuse → erreur.
# Incident : 2019 à 11 224 (≈ 37 % des autres années) publié sans alerte.
SEUIL_ANNEE_CREUSE = 0.6
MIN_KEPT_RATIO     = 0.25   # mutations retenues / ventes candidates — en dessous, quelque chose est cassé
PAUSE_ENTRE_FICHIERS = 1.0  # secondes, courtoisie envers les serveurs (0 dans les tests)

# ── Géographie ───────────────────────────────────────────────────
# Une seule source de vérité : data/geo/ (construit par scripts/build_geo.py, commité).
# Incident v12–v13 : secteurs par arrondissement + seuils de latitude qui coupaient des quartiers en
# deux et inversaient les étiquettes (Épinettes dans « Opéra – Grands Boulevards ») ; quartiers de
# Boulogne par bbox dont un restait vide. Désormais : point-dans-polygone sur les quartiers officiels.
CODE_TO_ARR = {f"751{str(i).zfill(2)}": i for i in range(1, 21)}
ARR_LABELS  = {i: ("1er" if i == 1 else f"{i}e") for i in range(1, 21)}
CODE_BOULOGNE = "92012"
GEO_FILE = "data/geo/quartiers.geojson"
REF_FILE = "data/geo/referentiel.json"
DEP_TO_COMMUNE = {"75": "75056", "92": "92012"}   # lot 4 : une commune par code, plusieurs communes par dep

class Geo:
    """Index des polygones de quartiers, affectation d'un point à son quartier."""
    def __init__(self, geo_path=None, ref_path=None):
        with open(geo_path or GEO_FILE, encoding="utf-8") as f: feats = json.load(f)["features"]
        with open(ref_path or REF_FILE, encoding="utf-8") as f: self.ref = json.load(f)
        self.quartiers = {}   # id → propriétés
        self.index = defaultdict(list)   # commune → [(id, bbox, [rings extérieurs+trous par polygone])]
        for ft in feats:
            pr = ft["properties"]; g = ft["geometry"]
            polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
            xs = [pt[0] for poly in polys for pt in poly[0]]; ys = [pt[1] for poly in polys for pt in poly[0]]
            self.quartiers[pr["id"]] = pr
            self.index[pr["commune"]].append((pr["id"], (min(xs), min(ys), max(xs), max(ys)), polys))

    @staticmethod
    def _pip(x, y, ring):
        inside = False; j = len(ring) - 1
        for i in range(len(ring)):
            xi, yi = ring[i]; xj, yj = ring[j]
            if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi: inside = not inside
            j = i
        return inside

    def quartier(self, commune, lon, lat):
        if not lon or not lat: return None
        for qid, (x0, y0, x1, y1), polys in self.index.get(commune, ()):
            if x0 <= lon <= x1 and y0 <= lat <= y1:
                for poly in polys:
                    if self._pip(lon, lat, poly[0]) and not any(self._pip(lon, lat, h) for h in poly[1:]): return qid
        return None

def affecter_quartiers(muts, geo):
    """Pose m['q'] (id quartier), m['zone'], m['sect'] sur chaque mutation. Compte les échecs."""
    for m in muts:
        q = geo.quartier(DEP_TO_COMMUNE.get(m["dep"], m.get("code")), m.get("lon"), m.get("lat"))
        m["q"] = q
        if q:
            pr = geo.quartiers[q]; m["zone"] = pr.get("zone"); m["sect"] = pr.get("secteur")
            if m["dep"] == "75" and pr.get("arr") != m.get("arr"): CPT.add(m["dep"], m["annee"], "arr_dvf_differe_du_polygone")
        else:
            m["zone"] = None; m["sect"] = None
            CPT.add(m["dep"], m["annee"], "sans_quartier")

# Départements à télécharger et communes retenues dans chacun.
DEPS = {
    "75": set(CODE_TO_ARR.keys()),
    "92": {CODE_BOULOGNE},
}

# ══════════════════════════════════════════════════════════════════
# COMPTEURS
# ══════════════════════════════════════════════════════════════════

class Compteurs:
    """Tout ce qui est écarté est compté, par (dep, année, motif)."""
    def __init__(self): self.c = Counter()
    def add(self, dep, annee, motif, n=1): self.c[(dep, annee, motif)] += n
    def par_motif(self, dep=None, annee=None):
        out = Counter()
        for (d, a, m), n in self.c.items():
            if (dep is None or d == dep) and (annee is None or a == annee): out[m] += n
        return out
    def export(self):
        out = defaultdict(lambda: defaultdict(dict))
        for (d, a, m), n in sorted(self.c.items()): out[d][str(a)][m] = n
        return {d: dict(v) for d, v in out.items()}

CPT = Compteurs()

# ══════════════════════════════════════════════════════════════════
# RÉSEAU
# ══════════════════════════════════════════════════════════════════

HEAD_CACHE = {}
def url_existe(url, timeout=20):
    """HEAD → (existe, taille_Mo). Mémoïsé : une URL n'est sondée qu'une fois par run.
    HEAD_INFO[url] garde l'empreinte (Last-Modified + Content-Length) : c'est elle qui décide
    si un fichier déjà traité doit être retéléchargé (run mensuel, incident : le calendrier
    semestriel ratait la régénération de geo-dvf, un mois après la publication DGFiP)."""
    if url in HEAD_CACHE: return HEAD_CACHE[url]
    try:
        r = requests.head(url, timeout=timeout, allow_redirects=True)
        ok = r.status_code == 200
        mb = int(r.headers.get("content-length", 0)) / 1e6
        # Un fichier « existant » de moins de 10 Ko est une page d'erreur déguisée
        if ok and 0 < mb < 0.01: ok = False
        HEAD_CACHE[url] = (ok, mb)
        HEAD_INFO[url] = f"{r.headers.get('last-modified','')}|{r.headers.get('content-length','')}" if ok else ""
    except requests.RequestException:
        HEAD_CACHE[url] = (False, 0); HEAD_INFO[url] = ""
    return HEAD_CACHE[url]
HEAD_INFO = {}

def choisir_source(annee, dep):
    """Retourne (url, tag, complet) : le millésime le plus récent qui contient l'année.
    Ordre : geo-dvf/latest (rafraîchi, 5 ans glissants) puis opendatarchives du plus récent au plus ancien.
    `complet` = False si le millésime ne couvre pas l'année entière (publication d'avril de l'année même
    ou d'octobre : semestre 1 seulement)."""
    url = GEODVF_LATEST.format(annee=annee, dep=dep)
    ok, mb = url_existe(url)
    if ok: return url, "geo-dvf/latest", annee < TODAY.year   # l'année en cours est partielle par nature
    for mil in millesimes_candidats():
        my, mm = int(mil[:4]), int(mil[5:])
        if my < annee: break                   # un millésime antérieur à l'année ne peut pas la contenir
        for tpl in (ODA_DEP, ODA_FULL):
            u = tpl.format(mil=mil, annee=annee, dep=dep)
            ok, mb = url_existe(u)
            if ok:
                complet = my > annee            # publié l'année suivante ou plus tard → année entière
                return u, f"opendatarchives/{mil}", complet
    return None, None, False

def stream_csv(url, timeout=600):
    """Itère les lignes décodées d'un CSV gzip distant sans le charger en mémoire."""
    r = requests.get(url, stream=True, timeout=timeout); r.raise_for_status()
    r.raw.decode_content = False
    gz = gzip.GzipFile(fileobj=r.raw)
    return io.TextIOWrapper(gz, encoding="utf-8", errors="replace", newline="")

# ══════════════════════════════════════════════════════════════════
# PARSEUR (format CSV géolocalisé Etalab, une ligne par local/parcelle)
# ══════════════════════════════════════════════════════════════════

COLS_REQUISES = ["id_mutation","date_mutation","nature_mutation","valeur_fonciere","code_commune",
                 "id_parcelle","type_local","surface_reelle_bati","nombre_pieces_principales",
                 "longitude","latitude"]
COLS_CARREZ = ["lot1_surface_carrez","lot2_surface_carrez","lot3_surface_carrez","lot4_surface_carrez","lot5_surface_carrez"]

def to_f(s):
    if not s: return 0.0
    try: return float(str(s).replace(",", ".").replace(" ", ""))
    except ValueError: return 0.0

def parse_csv(fh, annee, dep, communes, journal=None):
    """Lit le flux CSV, regroupe par mutation, applique les règles, renvoie la liste des mutations retenues.
    `journal` (dict) reçoit le relevé : colonnes réelles, échantillon, compteurs."""
    reader = csv.DictReader(fh)
    cols = reader.fieldnames or []
    manquantes = [c for c in COLS_REQUISES if c not in cols]
    if manquantes:
        raise RuntimeError(f"{dep}/{annee}: colonnes manquantes {manquantes} — colonnes lues : {cols}")
    carrez_cols = [c for c in COLS_CARREZ if c in cols]
    if journal is not None:
        journal["colonnes"] = cols
        journal["echantillon"] = []

    muts = {}     # id_mutation → {val, date, code, rows:[...]}
    n_lignes = 0; n_perimetre = 0
    natures = Counter()
    for row in reader:
        n_lignes += 1
        code = row["code_commune"]
        if code not in communes: continue
        n_perimetre += 1
        if journal is not None and len(journal["echantillon"]) < 3: journal["echantillon"].append(row)
        nat = row["nature_mutation"].strip()
        natures[nat] += 1
        mid = f"{dep}_{row['id_mutation']}"
        m = muts.get(mid)
        if m is None:
            m = muts[mid] = {"id": mid, "nature": nat.lower(), "val": to_f(row["valeur_fonciere"]),
                             "date": row["date_mutation"][:10], "code": code, "rows": []}
        tl = row["type_local"].strip()
        carrez = max((to_f(row[c]) for c in carrez_cols), default=0.0)
        m["rows"].append({
            "parcelle": row["id_parcelle"], "type": tl,
            "surf": to_f(row["surface_reelle_bati"]), "carrez": carrez,
            "nbpp": int(to_f(row["nombre_pieces_principales"])),
            "lat": to_f(row["latitude"]), "lon": to_f(row["longitude"]),
        })

    CPT.add(dep, annee, "lignes_lues", n_lignes)
    CPT.add(dep, annee, "lignes_perimetre", n_perimetre)
    for nat, n in natures.items(): CPT.add(dep, annee, f"nature:{nat}", n)
    retenues = [r for r in (consolider(m, annee, dep) for m in muts.values()) if r]
    CPT.add(dep, annee, "mutations_perimetre", len(muts))
    CPT.add(dep, annee, "mutations_retenues", len(retenues))
    if journal is not None: journal["compteurs"] = dict(CPT.par_motif(dep, annee))
    return retenues

def consolider(m, annee, dep):
    """Applique les règles à une mutation. Renvoie un dict ou None (motif compté)."""
    if m["nature"] not in NATURES_RETENUES:
        CPT.add(dep, annee, "excl_nature_non_vente"); return None
    if m["val"] <= 0:
        CPT.add(dep, annee, "excl_valeur_nulle"); return None
    # Dédoublonnage des lignes strictement identiques (DVF en produit)
    vus = set(); rows = []
    for r in m["rows"]:
        k = (r["parcelle"], r["type"], r["surf"], r["nbpp"], r["carrez"])
        if k in vus: continue
        vus.add(k); rows.append(r)
    logements = [r for r in rows if r["type"] in TYPES_LOGEMENT]
    autres    = [r for r in rows if r["type"] and r["type"] not in TYPES_LOGEMENT and r["type"] not in TYPES_ANNEXE]
    if not logements:
        CPT.add(dep, annee, "excl_sans_logement"); return None
    if len(logements) > 1:
        CPT.add(dep, annee, "excl_plusieurs_logements"); return None
    if autres:
        CPT.add(dep, annee, "excl_local_pro_dans_la_vente"); return None
    lg = logements[0]
    # Surface : Carrez si présente et cohérente avec la surface bâtie (±30 %), sinon surface réelle bâtie.
    # Une Carrez très différente signale un lot annexe (cave, parking) porté sur la ligne du logement.
    surf = lg["surf"]; source_surf = "bati"
    if lg["carrez"] > 0 and (surf <= 0 or 0.7 <= lg["carrez"] / surf <= 1.3):
        surf = lg["carrez"]; source_surf = "carrez"
    if surf <= 0:
        CPT.add(dep, annee, "excl_surface_nulle"); return None
    if not (SURF_MIN <= surf < SURF_MAX):
        CPT.add(dep, annee, "excl_surface_hors_bornes"); return None
    ppm2 = m["val"] / surf
    if not (PPM2_MIN <= ppm2 <= PPM2_MAX):
        CPT.add(dep, annee, "excl_ppm2_hors_bornes"); return None
    CPT.add(dep, annee, f"surface_source:{source_surf}")
    lat, lon = lg["lat"], lg["lon"]
    if not (lat and lon): CPT.add(dep, annee, "sans_geoloc")
    arr = CODE_TO_ARR.get(m["code"]) if dep == "75" else None
    return {"arr": arr, "val": m["val"], "surf": surf, "type": lg["type"],
            "nbpp": lg["nbpp"], "date": m["date"], "annee": annee, "lat": lat, "lon": lon,
            "dep": dep, "code": m["code"]}

# ══════════════════════════════════════════════════════════════════
# CACHE — mutations consolidées par (dep, année), avec la source et la version du parseur
# ══════════════════════════════════════════════════════════════════

def load_cache():
    if not os.path.exists(CACHE_FILE): return {}
    try:
        with gzip.open(CACHE_FILE, "rt", encoding="utf-8") as f: d = json.load(f)
    except (OSError, ValueError) as e:
        print(f"  ⚠ cache illisible ({e}) — ignoré"); return {}
    if d.get("parser_version") != PARSER_VERSION:
        print(f"  ↻ cache parser v{d.get('parser_version')} ≠ v{PARSER_VERSION} — reconstruit"); return {}
    entries = d.get("entries", {})
    print(f"  ✓ cache v{PARSER_VERSION} : {len(entries)} entrées (dep_année)")
    return entries

def save_cache(entries):
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with gzip.open(CACHE_FILE, "wt", encoding="utf-8", compresslevel=6) as f:
        json.dump({"parser_version": PARSER_VERSION, "generated_at": datetime.utcnow().isoformat()+"Z",
                   "entries": entries}, f, ensure_ascii=False, separators=(",", ":"))
    print(f"  ✓ cache écrit : {os.path.getsize(CACHE_FILE)/1e6:.1f} Mo, {len(entries)} entrées")

def cache_valide(ent, src):
    """Une entrée de cache est réutilisable si elle vient de la même URL et que l'empreinte du fichier
    distant (Last-Modified + taille) n'a pas bougé. Sans empreinte côté serveur, on ne cache que les
    millésimes figés (opendatarchives), jamais geo-dvf/latest qui est régénéré."""
    if not ent or ent.get("url") != src["url"]: return False
    if src["empreinte"]: return ent.get("empreinte") == src["empreinte"]
    return "opendatarchives" in (src["tag"] or "")

# ══════════════════════════════════════════════════════════════════
# STATS
# ══════════════════════════════════════════════════════════════════

def percentile(sorted_vals, q):
    n = len(sorted_vals)
    if n == 0: return None
    pos = q * (n - 1); lo = int(pos); hi = min(lo + 1, n - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)

def stats(muts, min_n=3):
    if len(muts) < min_n: return None
    p = sorted(m["val"] / m["surf"] for m in muts); s = sorted(m["surf"] for m in muts); n = len(p)
    return {"count": n, "mean": round(sum(p) / n), "median": round(percentile(p, .5)),
            "min": round(p[0]), "max": round(p[-1]),
            "q1": round(percentile(p, .25)), "q3": round(percentile(p, .75)),
            "p10": round(percentile(p, .10)), "p90": round(percentile(p, .90)),
            "surf_mean": round(sum(s) / n, 1), "surf_median": round(percentile(s, .5), 1)}

def by_period(muts, key_fn):
    g = defaultdict(list)
    for m in muts:
        k = key_fn(m)
        if k: g[k].append(m)
    return {k: v for k in sorted(g) if (v := stats(g[k]))}

by_year    = lambda muts: by_period(muts, lambda m: str(m["annee"]))
by_quarter = lambda muts: by_period(muts, lambda m: f"{m['date'][:4]}-Q{(int(m['date'][5:7]) - 1) // 3 + 1}" if len(m["date"]) >= 7 else None)
by_month   = lambda muts: by_period(muts, lambda m: m["date"][:7] if len(m["date"]) >= 7 else None)

def windows(muts, last_year):
    """Percentiles calculés sur les mutations elles-mêmes pour chaque fenêtre d'années civiles.
    Incident v12 : le « P90 sur 10 ans » affiché était le max des P90 annuels."""
    out = {}
    for n in FENETRES:
        sel = [m for m in muts if m["annee"] > last_year - n]
        s = stats(sel)
        if s: out[str(n)] = {**s, "from": last_year - n + 1, "to": last_year}
    s = stats(muts)
    if s: out["all"] = {**s, "from": min(m["annee"] for m in muts), "to": last_year}
    return out

def typo_of(surf):
    for t in TYPOLOGIES:
        if t["surfMin"] <= surf < t["surfMax"]: return t["id"]
    return None

def typo_stats(muts, last_year, leger=False):
    g = defaultdict(list)
    for m in muts:
        t = typo_of(m["surf"])
        if t: g[t].append(m)
    total = sum(len(v) for v in g.values()); out = {}
    for t, ms in g.items():
        s = stats(ms)
        if s: out[t] = {**s, "share": round(len(ms) / total * 100, 1) if total else 0,
                        "by_year": by_year(ms), "windows": windows(ms, last_year),
                        **({} if leger else {"by_quarter": by_quarter(ms)})}
    if out: out["_top_typo"] = max((k for k in out if not k.startswith("_")), key=lambda k: out[k]["count"])
    return out

def group_stats(muts, key_fn, labels, last_year, detail="complet"):
    """detail='complet' : by_year, by_quarter, by_month, by_typo (avec trimestres), windows.
       detail='leger'   : by_year, by_typo (années + fenêtres), windows — pour les 90 quartiers, sinon le JSON
       doublerait de taille pour des séries mensuelles que personne ne lit à cette maille."""
    g = defaultdict(list)
    for m in muts:
        k = key_fn(m)
        if k is not None: g[k].append(m)
    out = {}
    for k, ms in g.items():
        by_type = {}
        for tb in sorted(TYPES_LOGEMENT):
            f = [m for m in ms if m["type"] == tb]
            s = stats(f)
            if not s: continue
            if detail == "complet":
                by_type[tb] = {**s, "by_year": by_year(f), "by_quarter": by_quarter(f), "by_month": by_month(f),
                               "by_typo": typo_stats(f, last_year), "windows": windows(f, last_year)}
            else:
                by_type[tb] = {**s, "by_year": by_year(f), "by_typo": typo_stats(f, last_year, leger=True), "windows": windows(f, last_year)}
        out[str(k)] = {"label": labels.get(k, str(k)), "by_type": by_type, "total": len(ms)}
    return out

# ══════════════════════════════════════════════════════════════════
# GARDES
# ══════════════════════════════════════════════════════════════════

def verifier(all_muts, sources_used, allow_partial, years):
    """Fait échouer le run plutôt que publier un JSON creux. Renvoie la liste des anomalies bloquantes."""
    erreurs = []
    apparts_75 = Counter(m["annee"] for m in all_muts if m["dep"] == "75" and m["type"] == "Appartement")
    completes = [a for a in apparts_75 if sources_used.get(f"75_{a}", {}).get("complet") and a < TODAY.year]
    if len(completes) >= 3:
        med = statistics.median(apparts_75[a] for a in completes)
        for a in completes:
            if apparts_75[a] < SEUIL_ANNEE_CREUSE * med and a not in allow_partial:
                erreurs.append(f"année {a} creuse : {apparts_75[a]:,} appartements Paris contre médiane {med:,.0f} "
                               f"(source {sources_used[f'75_{a}']['url']}). DVF_ALLOW_PARTIAL={a} pour publier quand même.")
    for a in years:
        if a >= TODAY.year or a in allow_partial: continue
        for dep in DEPS:
            src = sources_used.get(f"{dep}_{a}")
            if not src:
                erreurs.append(f"{dep}/{a} : aucune source trouvée")
            elif not src["complet"]:
                erreurs.append(f"{dep}/{a} : seule une source PARTIELLE existe ({src['url']}). DVF_ALLOW_PARTIAL={a} pour publier quand même.")
    for (dep, a) in {(m["dep"], m["annee"]) for m in all_muts}:
        c = CPT.par_motif(dep, a)
        cand = c.get("mutations_perimetre", 0); kept = c.get("mutations_retenues", 0)
        if cand and kept / cand < MIN_KEPT_RATIO:
            erreurs.append(f"{dep}/{a} : {kept:,} retenues sur {cand:,} mutations ({kept/cand:.0%}) — parseur ou règles à revoir")
    return erreurs

# ══════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true", help="sonde les sources et affiche le relevé, n'écrit rien")
    ap.add_argument("--years", type=str, default="", help="limiter aux années, ex. 2024,2025")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--force", action="store_true", help="recalculer et réécrire même si aucune source n'a changé")
    ap.add_argument("--allow-partial", type=str, default=os.environ.get("DVF_ALLOW_PARTIAL", ""))
    args = ap.parse_args()
    years = [int(y) for y in args.years.split(",") if y] or YEARS
    allow_partial = {int(y) for y in args.allow_partial.split(",") if y}

    print(f"=== process_dvf v{PARSER_VERSION} — {TODAY} — années {years[0]}–{years[-1]} ===")
    print("\n=== Sondage des sources ===")
    sources = {}
    for annee in years:
        for dep in DEPS:
            url, tag, complet = choisir_source(annee, dep)
            sources[f"{dep}_{annee}"] = {"url": url, "tag": tag, "complet": complet, "mb": HEAD_CACHE.get(url, (0, 0))[1] if url else 0,
                                         "empreinte": HEAD_INFO.get(url, "") if url else ""}
            print(f"  {dep}/{annee}: {tag or '— AUCUNE —'}{'' if complet else ' (PARTIEL)'} {url or ''}")
    if args.probe:
        # Relevé détaillé sur la dernière année trouvée pour chaque dep : colonnes réelles + échantillon + compteurs
        for dep in DEPS:
            key = next((f"{dep}_{a}" for a in reversed(years) if sources[f"{dep}_{a}"]["url"]), None)
            if not key: continue
            annee = int(key.split("_")[1]); journal = {}
            print(f"\n=== Relevé {dep}/{annee} ({sources[key]['url']}) ===")
            parse_csv(stream_csv(sources[key]["url"]), annee, dep, DEPS[dep], journal)
            print("  colonnes :", journal["colonnes"])
            for r in journal["echantillon"]: print("  ligne :", json.dumps(r, ensure_ascii=False)[:600])
            print("  compteurs :", json.dumps(journal["compteurs"], ensure_ascii=False, indent=1))
        return 0

    print("\n=== Téléchargement / cache ===")
    cache = {} if args.no_cache else load_cache()
    all_muts = []; sources_used = {}; telecharges = 0
    for annee in years:
        for dep in DEPS:
            key = f"{dep}_{annee}"; src = sources[key]
            if not src["url"]:
                print(f"  ✗ {key}: aucune source"); continue
            ent = cache.get(key)
            if cache_valide(ent, src):
                print(f"  ✓ {key}: cache ({len(ent['mutations']):,} mutations, source inchangée)")
                for motif, n in ent.get("compteurs", {}).items(): CPT.add(dep, annee, motif, n)  # les exclusions cachées restent comptées
            else:
                t0 = time.time()
                muts = parse_csv(stream_csv(src["url"]), annee, dep, DEPS[dep])
                c = CPT.par_motif(dep, annee)
                print(f"  ↓ {key}: {src['tag']} {src['mb']:.0f} Mo → {len(muts):,} retenues / {c['mutations_perimetre']:,} mutations "
                      f"({time.time()-t0:.0f}s) | excl. plusieurs logements {c.get('excl_plusieurs_logements',0):,}, "
                      f"non-vente {c.get('excl_nature_non_vente',0):,}, ppm2 hors bornes {c.get('excl_ppm2_hors_bornes',0):,}")
                ent = {"url": src["url"], "tag": src["tag"], "complet": src["complet"], "empreinte": src["empreinte"],
                       "mutations": muts, "compteurs": dict(c)}
                cache[key] = ent; telecharges += 1
                time.sleep(PAUSE_ENTRE_FICHIERS)
            sources_used[key] = {"url": ent["url"], "tag": ent["tag"], "complet": src["complet"], "count": len(ent["mutations"]),
                                 "empreinte": ent.get("empreinte", "")}
            all_muts.extend(ent["mutations"])
    # Entrées de cache orphelines (année/dep qui n'a plus de source) : conservées mais non utilisées.
    if telecharges == 0 and os.path.exists(OUTPUT) and not args.force:
        try:
            prev = json.load(open(OUTPUT, encoding="utf-8"))["meta"]
            meme_parser = prev.get("parser_version") == PARSER_VERSION
            memes_sources = {k: v.get("url") for k, v in prev.get("sources_used", {}).items()} == {k: v["url"] for k, v in sources.items() if v["url"]}
        except (OSError, ValueError, KeyError):
            meme_parser = memes_sources = False
        if meme_parser and memes_sources:
            print("\n= Aucune source modifiée depuis le dernier run, JSON inchangé — rien à écrire (--force pour recalculer).")
            return 0
    if not args.no_cache and telecharges: save_cache(cache)   # sans téléchargement, le cache est inchangé : ne pas le réécrire (l'en-tête gzip changerait, git verrait un diff de 7 Mo)

    print("\n=== Volumes retenus (appartements) ===")
    for dep in DEPS:
        row = {a: sum(1 for m in all_muts if m["dep"] == dep and m["annee"] == a and m["type"] == "Appartement") for a in years}
        print(f"  {dep}: " + " ".join(f"{a}:{n:,}" for a, n in row.items()))

    erreurs = verifier(all_muts, sources_used, allow_partial, years)
    if erreurs:
        print("\n✗ RUN REFUSÉ — anomalies bloquantes :")
        for e in erreurs: print("   -", e)
        return 2

    print("\n=== Affectation géographique ===")
    geo = Geo(); affecter_quartiers(all_muts, geo)
    sans_q = Counter((m["dep"]) for m in all_muts if not m["q"])
    print(f"  {len(geo.quartiers)} quartiers · sans quartier : " + ", ".join(f"{d}: {n:,}" for d, n in sans_q.items()) if sans_q else f"  {len(geo.quartiers)} quartiers · toutes les mutations affectées")
    part_sans_q = sum(sans_q.values()) / max(1, len(all_muts))
    if part_sans_q > 0.02:
        print(f"\n✗ RUN REFUSÉ — {part_sans_q:.1%} des mutations sans quartier (référentiel ou géolocalisation cassés)"); return 2

    print("\n=== Calcul des statistiques ===")
    annees_ok = sorted({m["annee"] for m in all_muts}); last_year = annees_ok[-1]
    last_date = max(m["date"] for m in all_muts)
    paris = [m for m in all_muts if m["dep"] == "75"]; boul = [m for m in all_muts if m["dep"] == "92"]
    apparts75 = [m for m in paris if m["type"] == "Appartement"]; apparts92 = [m for m in boul if m["type"] == "Appartement"]
    ref = geo.ref
    lab = lambda d: {k: v["nom"] for k, v in d.items()}

    arr_s   = group_stats(paris, lambda m: m["arr"], {int(k): v["nom"] for k, v in ref["arrondissements"].items()}, last_year)
    sect_s  = group_stats(all_muts, lambda m: m["sect"], lab(ref["secteurs"]), last_year)
    sect_s["B0"] = group_stats(boul, lambda m: "B0", lab(ref["secteurs"]), last_year).get("B0", {})
    zone_s  = group_stats(paris, lambda m: m["zone"], lab(ref["zones"]), last_year)
    quart_s = group_stats(all_muts, lambda m: m["q"], {k: v["nom"] for k, v in geo.quartiers.items()}, last_year, detail="leger")
    for qid, pr in geo.quartiers.items():
        if qid in quart_s: quart_s[qid].update({"commune": pr["commune"], "arr": pr["arr"], "zone": pr["zone"], "secteur": pr["secteur"]})

    # Référentiels exposés au dashboard (une seule source : data/geo/referentiel.json)
    ville = lambda c: ref["communes"].get(c, c)
    secteurs_ref = {k: {"nom": v["nom"], "arrLabel": v.get("arrLabel", ""), "ville": "Boulogne" if v["commune"] == "92012" else ville(v["commune"]),
                        "quartiers": v["quartiers"]} for k, v in ref["secteurs"].items()}

    output = {
        "meta": {
            "generated_at": datetime.utcnow().isoformat() + "Z", "parser_version": PARSER_VERSION,
            "annees": annees_ok, "periode": f"{annees_ok[0]}–{last_year}",
            "last_year": last_year, "last_date": last_date,
            "last_year_complete": last_date >= f"{last_year}-12-15",
            "total_mutations": len(all_muts), "total_apparts": len(apparts75) + len(apparts92),
            "total_apparts_paris": len(apparts75), "total_apparts_boulogne": len(apparts92),
            "sources_used": sources_used, "exclusions": CPT.export(), "fichiers_telecharges": telecharges,
            "geo": {"quartiers": len(geo.quartiers), "sans_quartier": dict(sans_q), "releve": ref.get("releve", {})},
            "regles": {"ppm2": [PPM2_MIN, PPM2_MAX], "surface": [SURF_MIN, SURF_MAX],
                       "natures": sorted(NATURES_RETENUES), "un_logement_par_mutation": True},
            "cache_hist": os.path.exists(CACHE_FILE),
        },
        "global": {"stats": stats(apparts75), "by_year": by_year(apparts75), "by_quarter": by_quarter(apparts75),
                   "by_typo": typo_stats(apparts75, last_year), "windows": windows(apparts75, last_year)},
        "arrondissements": arr_s,
        "secteurs":        sect_s,
        "zones":           zone_s,
        "quartiers":       quart_s,
        "secteurs_ref":    secteurs_ref,
        "zones_ref":       ref["zones"],
        "quartiers_ref":   {k: {"nom": v["nom"], "commune": v["commune"], "arr": v["arr"], "zone": v["zone"], "secteur": v["secteur"]} for k, v in geo.quartiers.items()},
        "typologies_ref":  TYPOLOGIES,
        "fenetres_ref":    FENETRES,
        "boulogne": {"total_mutations": len(boul), "total_apparts": len(apparts92),
                     "by_year": by_year(apparts92), "by_quarter": by_quarter(apparts92)},
    }
    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, separators=(",", ":"))
    print(f"\n✓ {OUTPUT} ({os.path.getsize(OUTPUT)/1e6:.1f} Mo) — {output['meta']['periode']} — dernière mutation {last_date}")
    gby = output["global"]["by_year"]
    if len(gby) >= 2:
        y0, y1 = list(gby)[0], list(gby)[-1]
        print(f"  Paris médiane {y0}→{y1} : {gby[y0]['median']:,}→{gby[y1]['median']:,} €/m² "
              f"({(gby[y1]['median']-gby[y0]['median'])/gby[y0]['median']*100:+.1f} %)")
    return 0

if __name__ == "__main__":
    sys.exit(main())

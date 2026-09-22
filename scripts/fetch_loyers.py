#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_loyers.py — loyers de référence pour la rentabilité (lot 8) → data/loyers.json (clair : données publiques).

Deux sources, relevées le 22/09/2026 :
  1. Encadrement des loyers à Paris — Ville de Paris, jeu `logement-encadrement-des-loyers` (API explore v2.1, export JSON).
     Par quartier administratif (id_quartier 1–80 = nos P1–P80), nombre de pièces (1–4, 4 = 4 et plus), époque de
     construction (Avant 1946, 1946-1970, 1971-1990, Apres 1990), meublé / non meublé : loyer de référence, majoré, minoré
     en €/m²/mois hors charges. On garde la dernière année publiée (l'arrêté d'une année N s'applique du 1er juillet N au
     30 juin N+1). 2 560 lignes attendues (80 × 4 × 4 × 2) : un total différent est signalé.
  2. « Carte des loyers » — indicateurs de loyers d'annonce par commune (Ministère / DHUP-ANIL, data.gouv.fr), édition la
     plus récente trouvée par l'API data.gouv : appartements (tous), 1–2 pièces, 3 pièces et plus ; loyer d'annonce
     charges comprises en €/m²/mois (loypredm2), avec intervalle (lwr.IPm2, upr.IPm2). Filtré sur les communes du
     référentiel (data/geo/referentiel.json) et les arrondissements de Paris (751xx), à titre de contexte.

Une source en échec est conservée depuis le fichier précédent et marquée `stale` ; le fichier n'est réécrit que si le
contenu change ; le script échoue seulement si aucune source n'est lue et qu'aucun fichier précédent n'existe.
"""
import os, sys, re, csv, io, json, argparse
from datetime import datetime, timezone
import requests

OUT = "data/loyers.json"
REF = "data/geo/referentiel.json"
PARIS_URL = "https://opendata.paris.fr/api/explore/v2.1/catalog/datasets/logement-encadrement-des-loyers"
DATAGOUV = "https://www.data.gouv.fr/api/1/datasets/"
EPOQUES = ["Avant 1946", "1946-1970", "1971-1990", "Apres 1990"]
ATTENDU_PARIS = 80 * 4 * 4 * 2

def fetch_paris(base=PARIS_URL, timeout=60):
    r = requests.get(f"{base}/records", params={"limit": 1, "order_by": "annee desc", "select": "annee"}, timeout=timeout); r.raise_for_status()
    annee = str(r.json()["results"][0]["annee"])
    r = requests.get(f"{base}/exports/json", params={"where": f"annee={annee}", "select": "id_quartier,nom_quartier,id_zone,piece,epoque,meuble_txt,ref,max,min"}, timeout=timeout); r.raise_for_status()
    rows = r.json()
    if not isinstance(rows, list) or len(rows) < 1000: raise ValueError(f"export Paris : {len(rows) if isinstance(rows, list) else '?'} lignes")
    quartiers, doublons = {}, 0
    for x in rows:
        q = f"P{int(x['id_quartier'])}"; k = f"{int(x['piece'])}|{x['epoque']}|{'meuble' if x['meuble_txt'].startswith('meubl') else 'vide'}"
        d = quartiers.setdefault(q, {"nom": x["nom_quartier"], "zone": f"Z{int(x['id_zone'])}", "loyers": {}})
        if k in d["loyers"]: doublons += 1
        d["loyers"][k] = [float(x["ref"]), float(x["max"]), float(x["min"])]
    n = sum(len(d["loyers"]) for d in quartiers.values())
    return {"source": "Ville de Paris — encadrement des loyers", "url": base, "annee": int(annee), "application": f"1er juillet {annee} → 30 juin {int(annee)+1}",
            "unite": "€/m²/mois hors charges", "epoques": EPOQUES, "n": n, "complet": n == ATTENDU_PARIS, "doublons": doublons, "quartiers": quartiers}

def dernier_jeu_carte(api=DATAGOUV, timeout=60):
    r = requests.get(api, params={"q": "carte des loyers indicateurs de loyers d'annonce par commune", "page_size": 20}, timeout=timeout); r.raise_for_status()
    cands = []
    for d in r.json().get("data", []):
        m = re.search(r"commune en (\d{4})", d.get("title", ""))
        if m and "Carte des loyers" in d.get("title", ""): cands.append((int(m.group(1)), d))
    if not cands: raise ValueError("aucun jeu « Carte des loyers » trouvé")
    return max(cands, key=lambda c: c[0])

def lire_csv(url, timeout=120):
    r = requests.get(url, timeout=timeout); r.raise_for_status()
    txt = r.content.decode("utf-8-sig", errors="replace"); delim = ";" if txt[:2000].count(";") > txt[:2000].count(",") else ","
    rows = list(csv.DictReader(io.StringIO(txt), delimiter=delim))
    if not rows or "INSEE_C" not in rows[0] or "loypredm2" not in rows[0]: raise ValueError(f"colonnes inattendues : {list(rows[0].keys())[:6] if rows else 'vide'}")
    return rows

def fetch_carte(communes, api=DATAGOUV, timeout=60):
    annee, ds = dernier_jeu_carte(api, timeout)
    res = {}
    for r in ds.get("resources", []):
        t = r.get("title", "").lower()
        if "maison" in t or r.get("format", "").lower() != "csv": continue
        key = "app12" if "1 ou 2" in t else "app3" if "3 pi" in t else "app" if "appartement" in t else None
        if key: res[key] = r["url"]
    if set(res) != {"app", "app12", "app3"}: raise ValueError(f"ressources CSV incomplètes : {sorted(res)}")
    voulus = set(communes) | {f"751{i:02d}" for i in range(1, 21)}
    out = {}
    for key, url in res.items():
        for x in lire_csv(url, timeout * 2):
            c = str(x["INSEE_C"]).zfill(5)
            if c not in voulus: continue
            d = out.setdefault(c, {"nom": x.get("LIBGEO", "")})
            # décimales à la virgule dans les CSV DHUP (« 33,5500504387857 ») : le premier run réel a échoué là-dessus (22/09/2026)
            nb = lambda v: float(str(v).replace(",", ".").strip() or 0)
            d[key] = {"loyer": round(nb(x["loypredm2"]), 2), "bas": round(nb(x["lwr.IPm2"]), 2), "haut": round(nb(x["upr.IPm2"]), 2), "n": int(nb(x.get("nbobs_com") or 0))}
    manquantes = sorted(c for c in communes if c not in out)
    return {"source": "Carte des loyers — indicateurs de loyers d'annonce par commune (DHUP / ANIL)", "url": ds.get("page", ""), "edition": annee, "unite": "€/m²/mois, loyer d'annonce charges comprises",
            "n": len(out), "manquantes": manquantes, "communes": out}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT); ap.add_argument("--ref", default=REF); ap.add_argument("--probe", action="store_true")
    ap.add_argument("--paris-url", default=PARIS_URL); ap.add_argument("--datagouv", default=DATAGOUV)
    args = ap.parse_args()
    communes = [c for c in json.load(open(args.ref, encoding="utf-8")).get("communes", {}) if c != "75056"]
    previous = json.load(open(args.out, encoding="utf-8")) if os.path.exists(args.out) else {}
    out, echecs = {}, []
    for key, fn in (("paris", lambda: fetch_paris(args.paris_url)), ("carte", lambda: fetch_carte(communes, args.datagouv))):
        try:
            out[key] = fn(); v = out[key]
            print(f"  ✓ {key:<6} {v['n']} {'combinaisons, année ' + str(v['annee']) + ('' if v['complet'] else ' — INCOMPLET (attendu ' + str(ATTENDU_PARIS) + ')') if key == 'paris' else 'communes, édition ' + str(v['edition']) + (' — manquantes : ' + ', '.join(v['manquantes']) if v['manquantes'] else '')}")
        except Exception as ex:
            echecs.append(key)
            if previous.get(key): out[key] = {**previous[key], "stale": True, "stale_motif": str(ex)[:160]}; print(f"  ✗ {key:<6} {ex} — valeurs précédentes conservées")
            else: print(f"  ✗ {key:<6} {ex} — aucune valeur précédente")
    if not out: print("✗ aucune source lue"); return 2
    if args.probe: print(f"probe : {2 - len(echecs)}/2 sources lisibles"); return 0
    corps = lambda d: json.dumps({k: d.get(k) for k in ("paris", "carte")}, sort_keys=True, ensure_ascii=False)
    if corps(out) == corps(previous): print(f"= {args.out} inchangé"); return 0
    out["generated_at"] = datetime.now(timezone.utc).isoformat(); out["echecs"] = echecs
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f: json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"✓ {args.out} écrit ({os.path.getsize(args.out)/1e3:.0f} Ko)")
    return 0

if __name__ == "__main__":
    sys.exit(main())

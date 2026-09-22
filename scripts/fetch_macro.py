#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_macro.py — séries macroéconomiques servies au dashboard (onglet Perspectives), lot 7.

Sources relevées le 22/09/2026, toutes accessibles sans clé (contrat, voir README) :
  BCE  data-api.ecb.europa.eu  CSV  MIR  taux des crédits à l'habitat, France, mensuel
                                    IRS  taux long terme (critère de Maastricht ≈ OAT 10 ans), France, mensuel
                                    ICP  IPCH France, indice mensuel (2015 = 100)
  INSEE api.insee.fr/series/BDM  XML SDMX (sans jeton)
                                    010567013  indice Notaires-INSEE, appartements anciens, Paris, CVS, trimestriel
                                    010600352  indice des loyers, secteur libre, agglomération parisienne, trimestriel
                                    001761793  logements autorisés, Ville de Paris, cumul 12 mois, mensuel

Sortie : data/macro.json (clair : données publiques). Chaque série garde source, url, unité, dernier point.
Principe « rien d'écarté sans le compter » : une série en échec est CONSERVÉE depuis le fichier précédent et marquée
`stale` avec le motif ; le script échoue seulement si aucune série n'a pu être lue ou si le fichier précédent manque.
Le fichier n'est réécrit que si son contenu (hors date de génération) change.
"""
import os, sys, re, csv, io, json, argparse
from datetime import datetime, timezone
import requests

OUT = "data/macro.json"
SERIES = {
    "taux_credit": {"src": "BCE", "url": "https://data-api.ecb.europa.eu/service/data/MIR/M.FR.B.A2C.AM.R.A.2250.EUR.N?format=csvdata&startPeriod=2010-01",
                    "titre": "Taux des crédits à l'habitat (France, ménages, nouvelles opérations)", "unite": "%", "freq": "M"},
    "oat_10":      {"src": "BCE", "url": "https://data-api.ecb.europa.eu/service/data/IRS/M.FR.L.L40.CI.0000.EUR.N.Z?format=csvdata&startPeriod=2010-01",
                    "titre": "Taux long terme France (critère de Maastricht, ≈ OAT 10 ans)", "unite": "%", "freq": "M"},
    "ipch":        {"src": "BCE/Eurostat", "url": "https://data-api.ecb.europa.eu/service/data/ICP/M.FR.N.000000.4.INX?format=csvdata&startPeriod=2010-01",
                    "titre": "Indice des prix à la consommation harmonisé, France (2015 = 100)", "unite": "indice", "freq": "M"},
    "insee_paris_appart": {"src": "INSEE / Notaires", "url": "https://api.insee.fr/series/BDM/V1/data/SERIES_BDM/010567013",
                    "titre": "Indice Notaires-INSEE des prix des appartements anciens, Paris (CVS, 2015 = 100)", "unite": "indice", "freq": "Q"},
    "loyers_paris": {"src": "INSEE", "url": "https://api.insee.fr/series/BDM/V1/data/SERIES_BDM/010600352",
                    "titre": "Indice des loyers, secteur libre, agglomération parisienne (janv. 2019 = 100)", "unite": "indice", "freq": "Q"},
    "permis_paris": {"src": "INSEE / Sit@del2", "url": "https://api.insee.fr/series/BDM/V1/data/SERIES_BDM/001761793",
                    "titre": "Logements autorisés, Ville de Paris, cumul 12 mois", "unite": "logements", "freq": "M"},
}
RETARD_MOIS = 8
MIN_POINTS = 24            # une série tronquée (page d'erreur, format changé) est refusée, pas prise pour vraie

def parse_ecb(text):
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows or "TIME_PERIOD" not in rows[0] or "OBS_VALUE" not in rows[0]: raise ValueError("colonnes BCE absentes")
    return {r["TIME_PERIOD"]: float(r["OBS_VALUE"]) for r in rows if r.get("OBS_VALUE") not in (None, "")}

def parse_insee(text):
    obs = re.findall(r'TIME_PERIOD="([^"]+)" OBS_VALUE="([^"]+)"', text)
    if not obs: raise ValueError("aucune observation SDMX")
    upd = re.findall(r'LAST_UPDATE="([^"]+)"', text)
    return {k: float(v) for k, v in obs}, (upd[0] if upd else None)

def fetch(key, spec, timeout=40):
    r = requests.get(spec["url"], timeout=timeout, headers={"Accept": "text/csv, application/xml;q=0.9, */*;q=0.5"})
    r.raise_for_status()
    if spec["src"].startswith("BCE"): data, upd = parse_ecb(r.text), None
    else: data, upd = parse_insee(r.text)
    data = {k: v for k, v in data.items() if k >= "2010"}
    if len(data) < MIN_POINTS: raise ValueError(f"{len(data)} points seulement (< {MIN_POINTS})")
    ks = sorted(data)
    # retard : dernier point de plus de RETARD_MOIS mois — affiché tel quel (l'IPCH base 2015 s'est arrêté à 2025-12
    # lors du changement de base Eurostat, relevé le 22/09/2026 : le dashboard doit le dire plutôt que le cacher)
    y, m = int(ks[-1][:4]), (int(ks[-1][5:7]) if "-Q" not in ks[-1] else int(ks[-1][-1]) * 3)
    age = (datetime.now(timezone.utc).year - y) * 12 + datetime.now(timezone.utc).month - m
    return {"titre": spec["titre"], "source": spec["src"], "url": spec["url"], "unite": spec["unite"], "freq": spec["freq"],
            "last_update": upd, "premier": ks[0], "dernier": ks[-1], "n": len(ks), "age_mois": age, "retard": age > RETARD_MOIS, "obs": {k: data[k] for k in ks}}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT); ap.add_argument("--probe", action="store_true", help="lit les sources sans écrire")
    ap.add_argument("--base", default=None, help="préfixe d'URL de test (remplace l'hôte des sources)")
    args = ap.parse_args()
    previous = json.load(open(args.out, encoding="utf-8")) if os.path.exists(args.out) else {"series": {}}
    series, echecs = {}, []
    for key, spec in SERIES.items():
        s = dict(spec)
        if args.base: s["url"] = args.base + "/" + key      # fixtures locales : un fichier par série
        try:
            series[key] = fetch(key, s); print(f"  {'⚠' if series[key]['retard'] else '✓'} {key:<20} {series[key]['n']:>4} points  {series[key]['premier']} → {series[key]['dernier']}  dernier = {series[key]['obs'][series[key]['dernier']]}{'  (retard ' + str(series[key]['age_mois']) + ' mois)' if series[key]['retard'] else ''}")
        except Exception as ex:
            echecs.append(key); old = previous.get("series", {}).get(key)
            if old: series[key] = {**old, "stale": True, "stale_motif": str(ex)[:160]}; print(f"  ✗ {key:<20} {ex} — série précédente conservée (dernier {old.get('dernier')})")
            else: print(f"  ✗ {key:<20} {ex} — aucune valeur précédente")
    if not series or len(echecs) == len(SERIES): print("✗ aucune série lue"); return 2
    if args.probe: print(f"probe : {len(SERIES)-len(echecs)}/{len(SERIES)} séries lisibles"); return 0
    out = {"generated_at": datetime.now(timezone.utc).isoformat(), "series": series, "echecs": echecs}
    # comparaison hors champs dérivés du calendrier (age_mois, retard) : des données identiques ne provoquent aucun commit
    def corps(d): return json.dumps({"series": {k: {kk: vv for kk, vv in v.items() if kk not in ("age_mois", "retard")} for k, v in d.get("series", {}).items()}, "echecs": d.get("echecs", [])}, sort_keys=True, ensure_ascii=False)
    if corps(out) == corps(previous): print(f"= {args.out} inchangé ({len(series)} séries)"); return 0
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f: json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"✓ {args.out} écrit : {len(series)} séries, {len(echecs)} en échec, {os.path.getsize(args.out)/1e3:.0f} Ko")
    return 0

if __name__ == "__main__":
    sys.exit(main())

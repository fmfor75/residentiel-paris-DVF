#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_demo.py — démographie et parc de logements (lot 17) → data/demographie.json (clair : données publiques INSEE).

Source : recensements de la population, exploitation principale, via l'API Melodi de l'INSEE (sans clé). Relevé du
25/10/2026 sur Neuilly (COM-92051), Saint-Ouen (COM-93070), Paris (COM-75056) et ses arrondissements (ARM-751xx) :

  * les quatre jeux répondent pour les trois millésimes 2012, 2017 et 2023 (TIME_PERIOD) ; `GEO` peut être répété
    (36 géographies en une requête, ~2 s) ; la forme « GEO=a,b » renvoie une erreur non JSON ; la réponse porte
    `observations[].dimensions` + `measures.OBS_VALUE_NIVEAU.value` (flottants pondérés, ex. 7324.97 — on arrondit) ;
    le GEO renvoyé est préfixé du millésime géographique (« 2026-COM-92051 ») ;
  * DS_RP_POPULATION_PRINC (SEX=_T, RP_MEASURE=POP) : AGE ∈ Y_LT15, Y15T24, Y25T39, Y40T54, Y55T64, Y65T79, Y_GE65,
    Y_GE80, _T (plus Y_LT20 et Y20T64, ignorés) ;
  * DS_RP_LOGEMENT_PRINC (RP_MEASURE=DWELLINGS) : OCS ∈ _T, DW_MAIN (résidences principales), DW_SEC_DW_OCC, DW_VAC ;
    sur DW_MAIN, NOR ∈ R1…R4, R_GE5 (pièces) et TSH ∈ 100 propriétaires, 200 locataires = 211 (vide non HLM)
    + 212_222 (meublé) + 221 (vide HLM), 300 logés gratuitement. La lecture « 212_222 = HLM » a été écartée par la
    mesure : Saint-Ouen donne 221 = 7 342 (29 %) et 212_222 = 2 973, Neuilly 221 = 1 572 (5,5 %) — c'est 221 le parc
    social. Les autres dimensions (CARS, BUILD_END, NRG_SRC, TDW, CARPARK, L_STAY) sont prises à _T ;
  * DS_RP_MENAGES_PRINC : RP_MEASURE=ONEPERS (NOC=P1, OCS=DW_MAIN) = personnes vivant seules par AGE (6 tranches de
    15 ans et plus) ; RP_MEASURE=POP, AGE=Y_GE15, COUPLE=_T, CIVIL_STATUS=_T = population des 15 ans et plus ;
  * DS_RP_EDUCATION_PRINC (SEX=_T) : STUD=1 scolarisés par AGE ; Y18T24 et Y25T29 = population étudiante (Neuilly 2023 :
    3 956 + 478 sur 5 146 + 3 522) ; aucun jeu « activité » n'isole les étudiants (DS_RP_ACTIVITE_PRINC ne porte que les
    personnes en emploi).

Géographies : les communes du référentiel (data/geo/referentiel.json), Paris entier (75056) et ses 20 arrondissements
(751xx). Un jeu en échec est conservé depuis le fichier précédent et marqué `stale` ; une géographie incomplète est
listée dans `incomplets` ; le fichier n'est réécrit que si le contenu change ; le script échoue seulement si aucun jeu
n'est lu et qu'aucun fichier précédent n'existe.
"""
import os, sys, json, argparse
from datetime import datetime, timezone
import requests

OUT = "data/demographie.json"
REF = "data/geo/referentiel.json"
MELODI = "https://api.insee.fr/melodi/data/"
MILLESIMES = ("2012", "2017", "2023")
AGES = {"_T": "t", "Y_LT15": "lt15", "Y15T24": "a15_24", "Y25T39": "a25_39", "Y40T54": "a40_54", "Y55T64": "a55_64", "Y65T79": "a65_79", "Y_GE65": "ge65", "Y_GE80": "ge80"}
AGES_SEULS = {"Y15T24": "a15_24", "Y25T39": "a25_39", "Y40T54": "a40_54", "Y55T64": "a55_64", "Y65T79": "a65_79", "Y_GE80": "ge80"}
NOR = {"R1": "p1", "R2": "p2", "R3": "p3", "R4": "p4", "R_GE5": "p5"}
TSH = {"100": "prop", "200": "loc", "211": "loc_prive", "212_222": "meuble", "221": "hlm", "300": "gratuit"}
OCS = {"_T": "tot", "DW_MAIN": "rp", "DW_SEC_DW_OCC": "sec", "DW_VAC": "vac"}
JEUX = ("pop", "parc", "menages", "etudiants")

def geo_code(dim):
    # « 2026-COM-92051 » → « 92051 » ; « 2026-ARM-75108 » → « 75108 »
    return dim.rsplit("-", 1)[-1]

def melodi(ds, geos, filtres, base=MELODI, timeout=120):
    params = [("GEO", g) for g in geos] + list(filtres) + [("maxResult", "20000")]
    r = requests.get(f"{base}{ds}", params=params, timeout=timeout); r.raise_for_status()
    j = r.json(); obs = j.get("observations")
    if not isinstance(obs, list) or not obs: raise ValueError(f"{ds} : aucune observation")
    pg = j.get("paging") or {}
    if pg.get("next"): raise ValueError(f"{ds} : réponse paginée ({len(obs)} obs.), relever maxResult")
    return obs

def val(o): return int(round(o["measures"]["OBS_VALUE_NIVEAU"]["value"]))
def autres_T(d, sauf): return all(v == "_T" for k, v in d.items() if k not in sauf and k not in ("GEO", "FREQ", "TIME_PERIOD", "RP_MEASURE", "SEX", "OBS_STATUS"))

def fetch_pop(geos, base):
    out = {}
    for o in melodi("DS_RP_POPULATION_PRINC", geos, [("SEX", "_T"), ("RP_MEASURE", "POP")], base):
        d = o["dimensions"]; k = AGES.get(d.get("AGE"))
        if not k or d["TIME_PERIOD"] not in MILLESIMES: continue
        out.setdefault(geo_code(d["GEO"]), {}).setdefault(d["TIME_PERIOD"], {})[k] = val(o)
    return out

def fetch_parc(geos, base):
    out = {}
    for o in melodi("DS_RP_LOGEMENT_PRINC", geos, [("RP_MEASURE", "DWELLINGS")], base):
        d = o["dimensions"]; g, y = geo_code(d["GEO"]), d["TIME_PERIOD"]
        if y not in MILLESIMES: continue
        cell = out.setdefault(g, {}).setdefault(y, {})
        if d["OCS"] == "DW_MAIN" and d.get("NOR", "_T") in NOR and autres_T(d, ("OCS", "NOR")): cell[NOR[d["NOR"]]] = val(o)
        elif d["OCS"] == "DW_MAIN" and d.get("TSH", "_T") in TSH and autres_T(d, ("OCS", "TSH")): cell[TSH[d["TSH"]]] = val(o)
        elif d["OCS"] in OCS and autres_T(d, ("OCS",)): cell[OCS[d["OCS"]]] = val(o)
    return out

def fetch_menages(geos, base):
    out = {}
    for o in melodi("DS_RP_MENAGES_PRINC", geos, [], base):
        d = o["dimensions"]; g, y = geo_code(d["GEO"]), d["TIME_PERIOD"]
        if y not in MILLESIMES: continue
        cell = out.setdefault(g, {}).setdefault(y, {"seuls": {}})
        if d["RP_MEASURE"] == "ONEPERS" and d.get("AGE") in AGES_SEULS: cell["seuls"][AGES_SEULS[d["AGE"]]] = val(o)
        elif d["RP_MEASURE"] == "POP" and d.get("AGE") == "Y_GE15" and d.get("COUPLE", "_T") == "_T" and d.get("CIVIL_STATUS", "_T") == "_T": cell["pop15"] = val(o)
    for g in out:
        for y, cell in out[g].items():
            if len(cell["seuls"]) == 6: cell["seuls_t"] = sum(cell["seuls"].values())
    return out

def fetch_etudiants(geos, base):
    out = {}
    for o in melodi("DS_RP_EDUCATION_PRINC", geos, [("SEX", "_T")], base):
        d = o["dimensions"]; g, y = geo_code(d["GEO"]), d["TIME_PERIOD"]
        if y not in MILLESIMES or d.get("AGE") not in ("Y18T24", "Y25T29"): continue
        cell = out.setdefault(g, {}).setdefault(y, {}); a = d["AGE"][1:].lower().replace("t", "_")
        if d.get("STUD") == "1": cell["e" + a] = val(o)
        elif d.get("STUD") == "_T": cell["p" + a] = val(o)
    return out

ATTENDU = {"pop": set(AGES.values()), "parc": set(NOR.values()) | set(TSH.values()) | set(OCS.values()), "menages": {"seuls_t", "pop15"}, "etudiants": {"e18_24", "e25_29", "p18_24", "p25_29"}}

def assembler(noms, jeux, previous):
    """Un bloc par géographie ; une géographie à laquelle il manque une clé sur un millésime est listée dans incomplets."""
    geos, incomplets = {}, []
    for code, nom in noms.items():
        g = {"nom": nom, "type": "arrondissement" if code.startswith("751") and code != "75056" else "commune"}
        for jeu in JEUX:
            src = jeux.get(jeu)
            g[jeu] = src.get(code, {}) if src is not None else (previous.get("geos", {}).get(code, {}).get(jeu) or {})
            for y in MILLESIMES:
                manque = ATTENDU[jeu] - set(g[jeu].get(y, {}))
                if manque: incomplets.append(f"{code}:{jeu}:{y}:{','.join(sorted(manque))}")
        geos[code] = g
    return geos, incomplets

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT); ap.add_argument("--ref", default=REF); ap.add_argument("--probe", action="store_true"); ap.add_argument("--melodi", default=MELODI)
    args = ap.parse_args()
    ref = json.load(open(args.ref, encoding="utf-8"))
    noms = {c: v["nom"] for c, v in ref.get("communes", {}).items()}
    for a in range(1, 21): noms[f"751{a:02d}"] = f"Paris {'1er' if a == 1 else str(a) + 'e'}"
    geos_api = [("ARM-" if c.startswith("751") and c != "75056" else "COM-") + c for c in noms]
    previous = json.load(open(args.out, encoding="utf-8")) if os.path.exists(args.out) else {}
    jeux, echecs = {}, []
    for key, fn in (("pop", fetch_pop), ("parc", fetch_parc), ("menages", fetch_menages), ("etudiants", fetch_etudiants)):
        try:
            jeux[key] = fn(geos_api, args.melodi); n = len(jeux[key]); print(f"  ✓ {key:<10} {n}/{len(noms)} géographies")
            if n < len(noms): print(f"    manquantes : {sorted(set(noms) - set(jeux[key]))}")
        except Exception as ex:
            echecs.append(key); jeux[key] = None
            print(f"  ✗ {key:<10} {ex} — {'valeurs précédentes conservées' if previous.get('geos') else 'aucune valeur précédente'}")
    if len(echecs) == len(JEUX) and not previous: print("✗ aucun jeu lu"); return 2
    if args.probe: print(f"probe : {len(JEUX) - len(echecs)}/{len(JEUX)} jeux lisibles"); return 0
    geos, incomplets = assembler(noms, jeux, previous)
    if incomplets: print(f"  ! {len(incomplets)} cellule(s) incomplète(s) : {incomplets[:6]}{' …' if len(incomplets) > 6 else ''}")
    out = {"source": "INSEE, recensements de la population (exploitation principale) — API Melodi : DS_RP_POPULATION_PRINC, DS_RP_LOGEMENT_PRINC, DS_RP_MENAGES_PRINC, DS_RP_EDUCATION_PRINC",
           "url": "https://api.insee.fr/melodi/", "millesimes": list(MILLESIMES), "unite": "personnes et logements (comptages pondérés du recensement, arrondis à l'unité)",
           "geos": geos, "incomplets": incomplets, "stale": sorted(echecs)}
    corps = lambda d: json.dumps({k: d.get(k) for k in ("geos", "incomplets", "stale")}, sort_keys=True, ensure_ascii=False)
    if corps(out) == corps(previous): print(f"= {args.out} inchangé"); return 0
    out["generated_at"] = datetime.now(timezone.utc).isoformat()
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f: json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"✓ {args.out} écrit ({os.path.getsize(args.out)/1e3:.0f} Ko, {len(geos)} géographies)")
    return 0

if __name__ == "__main__":
    sys.exit(main())

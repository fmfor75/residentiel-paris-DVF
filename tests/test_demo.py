# -*- coding: utf-8 -*-
"""fetch_demo.py sur une API Melodi locale : parsing des quatre jeux, codes TSH (221 = HLM), cellules incomplètes comptées,
jeu en échec conservé depuis le fichier précédent, fichier non réécrit si inchangé."""
import os, sys, json, shutil, tempfile, unittest, subprocess, threading, http.server, urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEOS = {"COM-92051": 1000, "COM-75056": 50000, "ARM-75101": 300}   # population 15–24 de base, les autres valeurs en dérivent

def obs(geo, y, measures, **dims):
    d = {"GEO": f"2026-{geo}", "FREQ": "A", "TIME_PERIOD": y, **dims}
    return {"attributes": {"OBS_STATUS": "A"}, "dimensions": d, "measures": {"OBS_VALUE_NIVEAU": {"value": measures}}}

def jeu(ds, geos, years, trou):
    out = []
    for g in geos:
        b = GEOS[g]
        for y in years:
            if ds == "DS_RP_POPULATION_PRINC":
                for age, k in (("_T", 10), ("Y_LT15", 1.5), ("Y15T24", 1), ("Y25T39", 2), ("Y40T54", 2), ("Y55T64", 1), ("Y65T79", 1.5), ("Y_GE65", 2.5), ("Y_GE80", 1), ("Y_LT20", 2)):
                    if trou and age == "Y_GE80" and y == "2012": continue
                    out.append(obs(g, y, b * k + .4, SEX="_T", RP_MEASURE="POP", AGE=age))
            elif ds == "DS_RP_LOGEMENT_PRINC":
                T = dict(CARS="_T", BUILD_END="_T", NRG_SRC="_T", TDW="_T", TSH="_T", CARPARK="_T", NOR="_T", L_STAY="_T", RP_MEASURE="DWELLINGS")
                for ocs, k in (("_T", 6), ("DW_MAIN", 5), ("DW_SEC_DW_OCC", .6), ("DW_VAC", .4)): out.append(obs(g, y, b * k, **{**T, "OCS": ocs}))
                for nor, k in (("R1", 1), ("R2", 1), ("R3", 1), ("R4", 1), ("R_GE5", 1)): out.append(obs(g, y, b * k, **{**T, "OCS": "DW_MAIN", "NOR": nor}))
                for tsh, k in (("100", 2.5), ("200", 2), ("211", 1), ("212_222", .4), ("221", .6), ("300", .5)): out.append(obs(g, y, b * k, **{**T, "OCS": "DW_MAIN", "TSH": tsh}))
                out.append(obs(g, y, 99, **{**T, "OCS": "DW_MAIN", "NOR": "R1", "BUILD_END": "Y_LT1919"}))   # croisement : doit être ignoré
            elif ds == "DS_RP_MENAGES_PRINC":
                for age in ("Y15T24", "Y25T39", "Y40T54", "Y55T64", "Y65T79", "Y_GE80"): out.append(obs(g, y, b * .3, RP_MEASURE="ONEPERS", NOC="P1", OCS="DW_MAIN", COUPLE="_T", CIVIL_STATUS="_T", AGE=age))
                out.append(obs(g, y, b * 8.5, RP_MEASURE="POP", NOC="_T", OCS="_T", COUPLE="_T", CIVIL_STATUS="_T", AGE="Y_GE15"))
                out.append(obs(g, y, b * 4, RP_MEASURE="POP", NOC="_T", OCS="_T", COUPLE="1", CIVIL_STATUS="_T", AGE="Y_GE15"))   # en couple : ignoré
            elif ds == "DS_RP_EDUCATION_PRINC":
                for age, k in (("Y18T24", .7), ("Y25T29", .4), ("Y_GE30", 3)):
                    out.append(obs(g, y, b * k, SEX="_T", STUD="_T", STUD_AREA="_T", RP_MEASURE="POP", AGE=age)); out.append(obs(g, y, b * k * .6, SEX="_T", STUD="1", STUD_AREA="_T", RP_MEASURE="POP", AGE=age))
    return out

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        u = urllib.parse.urlparse(self.path); qs = urllib.parse.parse_qs(u.query); ds = u.path.rsplit("/", 1)[-1]; srv = self.server
        if ds in srv.en_echec: self.send_response(500); self.end_headers(); self.wfile.write(b"<html>erreur</html>"); return
        geos = [g for g in qs.get("GEO", []) if g in GEOS]
        body = json.dumps({"observations": jeu(ds, geos, ("2012", "2017", "2023"), srv.trou), "paging": {"first": "x"}})
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body.encode("utf-8"))

class FetchDemo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.out = os.path.join(self.tmp, "demographie.json"); self.ref = os.path.join(self.tmp, "ref.json")
        json.dump({"communes": {"75056": {"nom": "Paris"}, "92051": {"nom": "Neuilly-sur-Seine"}}}, open(self.ref, "w"))
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler); self.srv.en_echec = set(); self.srv.trou = False
        threading.Thread(target=self.srv.serve_forever, daemon=True).start(); self.base = f"http://127.0.0.1:{self.srv.server_address[1]}/"
    def tearDown(self): self.srv.shutdown(); shutil.rmtree(self.tmp, ignore_errors=True)
    def run_fetch(self, *extra):
        return subprocess.run([sys.executable, os.path.join(ROOT, "scripts/fetch_demo.py"), "--out", self.out, "--ref", self.ref, "--melodi", self.base, *extra], capture_output=True, text=True, cwd=ROOT)

    def test_lecture_complete(self):
        r = self.run_fetch(); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        d = json.load(open(self.out)); self.assertEqual(d["stale"], []); self.assertEqual(d["millesimes"], ["2012", "2017", "2023"])
        self.assertEqual(len(d["geos"]), 22)                      # 2 communes du référentiel + 20 arrondissements
        n = d["geos"]["92051"]; self.assertEqual(n["nom"], "Neuilly-sur-Seine"); self.assertEqual(n["type"], "commune"); self.assertEqual(d["geos"]["75101"]["type"], "arrondissement")
        self.assertEqual(n["pop"]["2023"], {"t": 10000, "lt15": 1500, "a15_24": 1000, "a25_39": 2000, "a40_54": 2000, "a55_64": 1000, "a65_79": 1500, "ge65": 2500, "ge80": 1000})   # 10000.4 arrondi, Y_LT20 ignoré
        p = n["parc"]["2023"]; self.assertEqual((p["tot"], p["rp"], p["sec"], p["vac"]), (6000, 5000, 600, 400))
        self.assertEqual(p["p1"], 1000)                            # le croisement NOR×BUILD_END (99) n'a pas écrasé la valeur
        self.assertEqual((p["prop"], p["loc"], p["loc_prive"], p["meuble"], p["hlm"], p["gratuit"]), (2500, 2000, 1000, 400, 600, 500))   # 221 → hlm, 212_222 → meublé
        m = n["menages"]["2023"]; self.assertEqual(m["pop15"], 8500); self.assertEqual(m["seuls_t"], 1800); self.assertEqual(m["seuls"]["ge80"], 300)
        self.assertEqual(n["etudiants"]["2012"], {"p18_24": 700, "e18_24": 420, "p25_29": 400, "e25_29": 240})
        # arrondissements absents du serveur (75102…) : cellules incomplètes comptées, pas d'exception
        self.assertTrue(any(x.startswith("75102:pop:2012:") for x in d["incomplets"])); self.assertEqual(d["geos"]["75102"]["pop"], {})
        self.assertEqual(len([x for x in d["incomplets"] if x.startswith("92051:")]), 0)
        mt = os.path.getmtime(self.out); r = self.run_fetch(); self.assertIn("inchangé", r.stdout); self.assertEqual(os.path.getmtime(self.out), mt)

    def test_trou_compte_et_echec_conserve(self):
        self.run_fetch(); self.srv.trou = True; self.srv.en_echec = {"DS_RP_LOGEMENT_PRINC"}
        r = self.run_fetch(); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        d = json.load(open(self.out)); self.assertEqual(d["stale"], ["parc"])
        self.assertEqual(d["geos"]["92051"]["parc"]["2023"]["hlm"], 600)                 # conservé du fichier précédent
        self.assertIn("92051:pop:2012:ge80", d["incomplets"]); self.assertNotIn("ge80", d["geos"]["92051"]["pop"]["2012"])
        self.assertIn("ge80", d["geos"]["92051"]["pop"]["2023"])

    def test_probe_et_tout_en_echec(self):
        r = self.run_fetch("--probe"); self.assertEqual(r.returncode, 0); self.assertIn("4/4", r.stdout); self.assertFalse(os.path.exists(self.out))
        self.srv.en_echec = {"DS_RP_POPULATION_PRINC", "DS_RP_LOGEMENT_PRINC", "DS_RP_MENAGES_PRINC", "DS_RP_EDUCATION_PRINC"}
        r = self.run_fetch(); self.assertEqual(r.returncode, 2); self.assertIn("aucun jeu lu", r.stdout)

if __name__ == "__main__":
    unittest.main()

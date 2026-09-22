# -*- coding: utf-8 -*-
"""fetch_loyers.py sur fixtures HTTP locales : export Paris, jeu data.gouv + CSV, filtrage communes, échec conservé, no-op."""
import os, sys, json, shutil, tempfile, unittest, subprocess, threading, http.server, functools, urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def paris_rows():
    rows = []
    for q in range(1, 81):
        for p in (1, 2, 3, 4):
            for e in ("Avant 1946", "1946-1970", "1971-1990", "Apres 1990"):
                for m in ("meublé", "non meublé"):
                    rows.append({"id_quartier": q, "nom_quartier": f"Q{q}", "id_zone": 1 + q % 14, "piece": p, "epoque": e, "meuble_txt": m, "ref": 30.0 + p, "max": 36.0 + p, "min": 21.0 + p})
    return rows
CSV = "INSEE_C;LIBGEO;loypredm2;lwr.IPm2;upr.IPm2;nbobs_com\n92012;Boulogne-Billancourt;29,73;23,95;36,91;20474\n75108;Paris 8e;38,1;30,2;47,0;5000\n69123;Lyon;16,5;12,1;21,0;9000\n"

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        u = urllib.parse.urlparse(self.path); qs = urllib.parse.parse_qs(u.query); srv = self.server
        if u.path.endswith("/records"): body = json.dumps({"results": [{"annee": "2025"}]})
        elif u.path.endswith("/exports/json"): body = json.dumps(paris_rows()[:srv.paris_n])
        elif u.path == "/datasets/": body = json.dumps({"data": [{"title": "\"Carte des loyers\" - Indicateurs de loyers d'annonce par commune en 2024", "page": "p2024", "resources": []},
            {"title": "\"Carte des loyers\" - Indicateurs de loyers d'annonce par commune en 2025", "page": "p2025", "resources": [
              {"title": "Indicateurs de loyer appartement", "format": "csv", "url": f"http://127.0.0.1:{srv.server_address[1]}/app.csv"},
              {"title": "Indicateur de loyer appartement de 1 ou 2 pièces", "format": "csv", "url": f"http://127.0.0.1:{srv.server_address[1]}/app12.csv"},
              {"title": "Indicateur de loyer appartement de 3 pièces ou plus", "format": "csv", "url": f"http://127.0.0.1:{srv.server_address[1]}/app3.csv"},
              {"title": "Indicateurs de loyer maison", "format": "csv", "url": "http://127.0.0.1:1/maison.csv"}]}]})
        elif u.path.endswith(".csv"): body = CSV.replace(",", ".") if srv.csv_ok else "<html>erreur</html>"
        else: self.send_response(404); self.end_headers(); return
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body.encode("utf-8"))

class FetchLoyers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.out = os.path.join(self.tmp, "loyers.json"); self.ref = os.path.join(self.tmp, "ref.json")
        json.dump({"communes": {"75056": "Paris", "92012": "Boulogne-Billancourt"}}, open(self.ref, "w"))
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler); self.srv.paris_n = 2560; self.srv.csv_ok = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start(); self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
    def tearDown(self): self.srv.shutdown(); shutil.rmtree(self.tmp, ignore_errors=True)
    def run_fetch(self):
        return subprocess.run([sys.executable, os.path.join(ROOT, "scripts/fetch_loyers.py"), "--out", self.out, "--ref", self.ref, "--paris-url", self.base + "/paris", "--datagouv", self.base + "/datasets/"], capture_output=True, text=True)

    def test_lecture_complete(self):
        r = self.run_fetch(); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        d = json.load(open(self.out)); self.assertEqual(d["echecs"], [])
        self.assertEqual(d["paris"]["annee"], 2025); self.assertTrue(d["paris"]["complet"]); self.assertEqual(d["paris"]["n"], 2560)
        self.assertEqual(d["paris"]["quartiers"]["P31"]["loyers"]["2|Avant 1946|vide"], [32.0, 38.0, 23.0])
        self.assertEqual(d["carte"]["edition"], 2025); self.assertEqual(d["carte"]["communes"]["92012"]["app12"]["loyer"], 29.73)
        self.assertIn("75108", d["carte"]["communes"]); self.assertNotIn("69123", d["carte"]["communes"])      # hors référentiel : écarté
        mt = os.path.getmtime(self.out); r = self.run_fetch(); self.assertIn("inchangé", r.stdout); self.assertEqual(os.path.getmtime(self.out), mt)

    def test_paris_incomplet_signale_et_carte_en_echec_conservee(self):
        self.run_fetch(); self.srv.paris_n = 2000; self.srv.csv_ok = False
        r = self.run_fetch(); self.assertEqual(r.returncode, 0, r.stdout)
        d = json.load(open(self.out)); self.assertFalse(d["paris"]["complet"]); self.assertEqual(d["paris"]["n"], 2000)
        self.assertEqual(d["echecs"], ["carte"]); self.assertTrue(d["carte"]["stale"]); self.assertEqual(d["carte"]["communes"]["92012"]["app"]["loyer"], 29.73)

if __name__ == "__main__":
    unittest.main()

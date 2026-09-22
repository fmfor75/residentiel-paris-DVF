# -*- coding: utf-8 -*-
"""fetch_macro.py sur fixtures HTTP locales : lecture BCE/INSEE, série en échec conservée et marquée, série tronquée refusée, no-op."""
import os, sys, json, shutil, tempfile, unittest, subprocess, threading, http.server, functools

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ECB = "KEY,FREQ,TIME_PERIOD,OBS_VALUE\n" + "".join(f"MIR,M,{2010+i//12}-{i%12+1:02d},{1.5+i*0.01:.2f}\n" for i in range(60))
INSEE = '<?xml version="1.0"?><message:StructureSpecificData><Series IDBANK="010567013" LAST_UPDATE="2026-09-08">' + "".join(f'<Obs TIME_PERIOD="{2010+i//4}-Q{i%4+1}" OBS_VALUE="{100+i:.1f}"/>' for i in range(40)) + "</Series></message:StructureSpecificData>"

class Fixture(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass

class FetchMacro(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.out = os.path.join(self.tmp, "macro.json")
        for k in ("taux_credit", "oat_10", "ipch"): open(os.path.join(self.tmp, k), "w").write(ECB)
        for k in ("insee_paris_appart", "loyers_paris", "permis_paris"): open(os.path.join(self.tmp, k), "w").write(INSEE)
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Fixture, directory=self.tmp))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start(); self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
    def tearDown(self): self.srv.shutdown(); shutil.rmtree(self.tmp, ignore_errors=True)
    def run_fetch(self, *args):
        return subprocess.run([sys.executable, os.path.join(ROOT, "scripts/fetch_macro.py"), "--out", self.out, "--base", self.base, *args], capture_output=True, text=True)

    def test_lecture_et_noop(self):
        r = self.run_fetch(); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        m = json.load(open(self.out)); self.assertEqual(len(m["series"]), 6); self.assertEqual(m["echecs"], [])
        self.assertEqual(m["series"]["taux_credit"]["n"], 60); self.assertEqual(m["series"]["insee_paris_appart"]["dernier"], "2019-Q4")
        self.assertEqual(m["series"]["insee_paris_appart"]["last_update"], "2026-09-08"); self.assertTrue(m["series"]["ipch"]["retard"])   # fixture ancienne → retard signalé
        mt = os.path.getmtime(self.out); r = self.run_fetch(); self.assertIn("inchangé", r.stdout); self.assertEqual(os.path.getmtime(self.out), mt)

    def test_echec_conserve_et_marque(self):
        self.run_fetch()
        os.remove(os.path.join(self.tmp, "oat_10"))                              # la source disparaît (404)
        open(os.path.join(self.tmp, "ipch"), "w").write(ECB.splitlines()[0] + "\n" + "\n".join(ECB.splitlines()[1:5]))   # série tronquée à 4 points
        r = self.run_fetch(); self.assertEqual(r.returncode, 0, r.stdout)
        m = json.load(open(self.out)); self.assertEqual(sorted(m["echecs"]), ["ipch", "oat_10"])
        self.assertTrue(m["series"]["oat_10"]["stale"]); self.assertEqual(m["series"]["oat_10"]["n"], 60)     # ancienne valeur conservée
        self.assertTrue(m["series"]["ipch"]["stale"]); self.assertIn("points seulement", m["series"]["ipch"]["stale_motif"])

    def test_tout_en_echec_sans_precedent(self):
        for k in ("taux_credit", "oat_10", "ipch", "insee_paris_appart", "loyers_paris", "permis_paris"): os.remove(os.path.join(self.tmp, k))
        r = self.run_fetch(); self.assertEqual(r.returncode, 2); self.assertFalse(os.path.exists(self.out))

if __name__ == "__main__":
    unittest.main()

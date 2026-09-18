# -*- coding: utf-8 -*-
"""Chiffrement des données servies : aller-retour, mauvais code, déterminisme, découpage par niveau."""
import os, sys, json, shutil, tempfile, unittest, subprocess, hashlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import build_site as B
from cryptography.exceptions import InvalidTag

class BuildSite(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, "dvf.json"); self.out = os.path.join(self.tmp, "enc")
        d = {"meta": {"generated_at": "2026-09-18T00:00:00Z", "periode": "2014–2025"}, "global": {"stats": {"count": 3}},
             "secteurs_ref": {"5": {"nom": "S5"}}, "zones_ref": {}, "quartiers_ref": {}, "typologies_ref": [], "fenetres_ref": [1],
             "arrondissements": {"1": {"total": 10}}, "secteurs": {"5": {"total": 20}}, "zones": {"Z1": {"total": 30}}, "quartiers": {"P1": {"total": 40}}, "boulogne": {}}
        json.dump(d, open(self.src, "w", encoding="utf-8"), ensure_ascii=False)
    def tearDown(self): shutil.rmtree(self.tmp, ignore_errors=True)

    def run_build(self, code):
        return subprocess.run([sys.executable, os.path.join(ROOT, "scripts/build_site.py"), "--src", self.src, "--out", self.out, "--code", code],
                              capture_output=True, text=True)

    def test_aller_retour_et_decoupage(self):
        r = self.run_build("un code de test"); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        key = B.derive_key("un code de test")
        for nom in B.NIVEAUX:
            blob = open(os.path.join(self.out, f"{nom}.bin"), "rb").read()
            self.assertEqual(blob[:4], B.MAGIC)
            self.assertIsInstance(json.loads(B.decrypt(key, blob)), dict)
        meta = json.loads(B.decrypt(key, open(os.path.join(self.out, "meta.bin"), "rb").read()))
        self.assertIn("secteurs_ref", meta); self.assertNotIn("secteurs", meta)      # le méta ne contient pas les gros niveaux
        self.assertEqual(json.loads(B.decrypt(key, open(os.path.join(self.out, "secteurs.bin"), "rb").read())), {"5": {"total": 20}})
        man = json.load(open(os.path.join(self.out, "manifest.json")))
        self.assertEqual(set(man["files"]), set(B.NIVEAUX)); self.assertEqual(man["kdf"]["iterations"], B.ITER)

    def test_mauvais_code_refuse(self):
        self.run_build("un code de test")
        blob = open(os.path.join(self.out, "meta.bin"), "rb").read()
        with self.assertRaises(InvalidTag): B.decrypt(B.derive_key("un autre code"), blob)

    def test_deterministe(self):
        self.run_build("un code de test"); h1 = hashlib.sha256(open(os.path.join(self.out, "quartiers.bin"), "rb").read()).hexdigest()
        r = self.run_build("un code de test"); h2 = hashlib.sha256(open(os.path.join(self.out, "quartiers.bin"), "rb").read()).hexdigest()
        self.assertEqual(h1, h2); self.assertIn("(inchangé)", r.stdout)

    def test_code_trop_court_refuse(self):
        r = self.run_build("abc"); self.assertEqual(r.returncode, 2); self.assertFalse(os.path.exists(os.path.join(self.out, "meta.bin")))

if __name__ == "__main__":
    unittest.main()

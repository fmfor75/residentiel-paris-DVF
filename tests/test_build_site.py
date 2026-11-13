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
        # fichier de ventes compact minimal (2 ventes) au format DVS2 (le chiffrement est indifférent au format)
        import struct
        with open(os.path.join(self.tmp, "dvf_sales.bin"), "wb") as f:
            f.write(b"DVS2" + struct.pack("<I", 2) + struct.pack("<dddd", 2.3, 48.8, 0.1, 0.1) + struct.pack("<BBHHIHH", 0, 0, 300, 4500, 500000, 100, 200) + struct.pack("<BBHHIHH", 1, 1, 301, 12000, 1500000, 300, 400))
    def tearDown(self): shutil.rmtree(self.tmp, ignore_errors=True)

    def run_build(self, code):
        return subprocess.run([sys.executable, os.path.join(ROOT, "scripts/build_site.py"), "--src", self.src, "--sales", os.path.join(self.tmp, "dvf_sales.bin"), "--adresses", os.path.join(self.tmp, "dvf_adresses.bin"), "--out", self.out, "--code", code],
                              capture_output=True, text=True)

    def test_aller_retour_et_decoupage(self):
        r = self.run_build("un code de test"); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        key = B.derive_key("un code de test")
        meta = json.loads(B.decrypt(key, open(os.path.join(self.out, "meta.bin"), "rb").read()))
        self.assertIn("secteurs_ref", meta); self.assertNotIn("secteurs", meta)      # le méta ne contient pas de statistiques par niveau
        sales = B.decrypt(key, open(os.path.join(self.out, "sales.bin"), "rb").read())
        self.assertEqual(sales[:4], b"DVS2"); self.assertEqual(len(sales), 40 + 2 * 14)
        man = json.load(open(os.path.join(self.out, "manifest.json")))
        self.assertEqual(set(man["files"]), {"meta", "sales"}); self.assertEqual(man["kdf"]["iterations"], B.ITER)   # sans fichier d'adresses : pas d'entrée
        self.assertFalse(os.path.exists(os.path.join(self.out, "secteurs.bin"))); self.assertFalse(os.path.exists(os.path.join(self.out, "adresses.bin")))
        # 13/11 : avec le fichier d'adresses (DVA1), une troisième entrée chiffrée ; s'il disparaît, adresses.bin est retiré
        import struct
        with open(os.path.join(self.tmp, "dvf_adresses.bin"), "wb") as f:
            v = "RUE DE TEST".encode(); f.write(b"DVA1" + struct.pack("<II", 2, 1) + struct.pack("<IH", 75008, len(v)) + v + struct.pack("<HBBBH", 13, 0, 9, 2, 0) + struct.pack("<HBBBH", 2, ord("B"), 21, 4, 0))
        r = self.run_build("un code de test"); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        man = json.load(open(os.path.join(self.out, "manifest.json"))); self.assertEqual(set(man["files"]), {"meta", "sales", "adresses"})
        adr = B.decrypt(key, open(os.path.join(self.out, "adresses.bin"), "rb").read()); self.assertEqual(adr[:4], b"DVA1"); self.assertEqual(len(adr), 12 + 6 + len(v) + 2 * 7)
        os.remove(os.path.join(self.tmp, "dvf_adresses.bin")); r = self.run_build("un code de test"); self.assertEqual(r.returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(self.out, "adresses.bin"))); self.assertEqual(set(json.load(open(os.path.join(self.out, "manifest.json")))["files"]), {"meta", "sales"})

    def test_mauvais_code_refuse(self):
        self.run_build("un code de test")
        blob = open(os.path.join(self.out, "meta.bin"), "rb").read()
        with self.assertRaises(InvalidTag): B.decrypt(B.derive_key("un autre code"), blob)

    def test_deterministe(self):
        self.run_build("un code de test"); h1 = hashlib.sha256(open(os.path.join(self.out, "sales.bin"), "rb").read()).hexdigest()
        r = self.run_build("un code de test"); h2 = hashlib.sha256(open(os.path.join(self.out, "sales.bin"), "rb").read()).hexdigest()
        self.assertEqual(h1, h2); self.assertIn("(inchangé)", r.stdout)

    def test_code_trop_court_refuse(self):
        r = self.run_build("abc"); self.assertEqual(r.returncode, 2); self.assertFalse(os.path.exists(os.path.join(self.out, "meta.bin")))

if __name__ == "__main__":
    unittest.main()

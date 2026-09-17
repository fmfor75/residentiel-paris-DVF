# -*- coding: utf-8 -*-
"""
Répétition de bout en bout du pipeline sur un jeu de données jetable (tests/fixtures.py).

Ce que ces tests prouvent : le code est correct sur des CSV au format attendu, les compteurs comptent
juste, les gardes refusent un run creux. Ce qu'ils ne prouvent PAS : que les sources réelles ont ce
format et ces volumes — c'est le rôle du relevé `--probe` et de la vérification du run réel.

Lancer : python -m unittest tests.test_pipeline -v
"""
import os, sys, json, shutil, tempfile, unittest, importlib
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts")); sys.path.insert(0, ROOT)
import process_dvf as P
from tests import fixtures as F

class Pipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.src = os.path.join(self.tmp, "src"); self.work = os.path.join(self.tmp, "work")
        os.makedirs(self.work); self.cwd = os.getcwd(); os.chdir(self.work)
        importlib.reload(P)
        P.TODAY = date(2026, 9, 11); P.YEARS = list(range(2014, 2027))
        P.HEAD_CACHE.clear(); P.HEAD_INFO.clear(); P.CPT = P.Compteurs(); P.PAUSE_ENTRE_FICHIERS = 0
        P.GEO_FILE = os.path.join(ROOT, "data/geo/quartiers.geojson"); P.REF_FILE = os.path.join(ROOT, "data/geo/referentiel.json")

    def tearDown(self):
        os.chdir(self.cwd); shutil.rmtree(self.tmp, ignore_errors=True)
        if hasattr(self, "srv"): self.srv.shutdown()

    def run_pipeline(self, variant="normal", argv=()):
        att = F.build(self.src, variant); self.srv, base = F.serve(self.src)
        P.GEODVF_LATEST = base + "/geo-dvf/latest/csv/{annee}/departements/{dep}.csv.gz"
        P.ODA_DEP  = base + "/oda/{mil}/csv/{annee}/departements/{dep}.csv.gz"
        P.ODA_FULL = base + "/oda/{mil}/csv/{annee}/full.csv.gz"
        sys.argv = ["process_dvf.py", *argv]
        return P.main(), att

    def test_run_normal_compteurs_et_schema(self):
        code, att = self.run_pipeline()
        self.assertEqual(code, 0)
        d = json.load(open("data/dvf_paris.json", encoding="utf-8"))
        m = d["meta"]
        # Toutes les années trouvées, y compris 2020 (millésime 2021-04) et 2019
        self.assertEqual(m["annees"], list(range(2014, 2027)))
        self.assertEqual(m["sources_used"]["75_2020"]["tag"], "opendatarchives/2021-04")
        self.assertTrue(m["sources_used"]["75_2020"]["complet"])
        self.assertEqual(m["sources_used"]["75_2014"]["tag"], "opendatarchives/2019-04")
        self.assertEqual(m["sources_used"]["75_2025"]["tag"], "geo-dvf/latest")
        self.assertFalse(m["sources_used"]["75_2026"]["complet"])
        # Compteurs 75/2024 : exclusions à l'unité près
        c = m["exclusions"]["75"]["2024"]
        for k in ("excl_nature_non_vente", "excl_plusieurs_logements", "excl_local_pro_dans_la_vente",
                  "excl_ppm2_hors_bornes", "excl_surface_hors_bornes", "excl_valeur_nulle", "sans_geoloc", "excl_sans_logement"):
            self.assertEqual(c.get(k, 0), att[k], k)
        self.assertEqual(c["mutations_retenues"], c["mutations_perimetre"] - sum(v for k, v in c.items() if k.startswith("excl_")))
        # Le doublon est retenu une fois ; le sans-géoloc est compté sans quartier
        self.assertGreaterEqual(c["surface_source:carrez"], att["surface_source:carrez_speciaux"])
        self.assertIn("6", d["secteurs"]); self.assertIn("B0", d["secteurs"])
        # Géographie : 90 quartiers, 14 zones, secteurs par polygones ; presque tout affecté
        self.assertEqual(m["geo"]["quartiers"], 90)
        self.assertLess(sum(m["geo"]["sans_quartier"].values()), 0.02 * m["total_mutations"])
        self.assertEqual(len(d["zones"]), 14); self.assertGreaterEqual(len(d["quartiers"]), 60)
        self.assertEqual(set(k for k in d["secteurs"] if k.startswith("B")), {f"B{i}" for i in range(0, 11)})
        q = next(iter(d["quartiers"].values())); self.assertIn("by_typo", q["by_type"]["Appartement"]); self.assertNotIn("by_month", q["by_type"]["Appartement"])
        self.assertEqual(sum(v["total"] for v in d["zones"].values()), sum(v["total"] for k, v in d["quartiers"].items() if k.startswith("P")))
        # Le sans-géoloc n'a pas de quartier : compté, absent des secteurs, présent dans son arrondissement
        self.assertEqual(c["sans_quartier"], att["sans_geoloc"])
        # Schéma consommé par index.html (rétro-compatibilité)
        s5 = d["secteurs"]["5"]["by_type"]["Appartement"]
        for k in ("count", "mean", "median", "p10", "p90", "by_year", "by_quarter", "by_typo", "windows", "by_month"): self.assertIn(k, s5)
        self.assertIn("_top_typo", s5["by_typo"])
        self.assertEqual(set(s5["windows"]), {"1", "3", "5", "10", "all"})
        self.assertEqual(s5["windows"]["5"]["from"], 2022); self.assertEqual(s5["windows"]["5"]["to"], 2026)
        self.assertIn("8", d["arrondissements"]); self.assertEqual(d["typologies_ref"], P.TYPOLOGIES)
        # Le P90 de fenêtre est bien un percentile sur les mutations, pas un max de P90 annuels
        self.assertLessEqual(s5["windows"]["all"]["p90"], max(v["p90"] for v in s5["by_year"].values()))
        # Cache : toutes les années, chacune avec l'empreinte de sa source et ses compteurs
        import gzip
        cache = json.load(gzip.open("data/dvf_cache.json.gz", "rt", encoding="utf-8"))
        self.assertEqual(cache["parser_version"], P.PARSER_VERSION)
        self.assertEqual(len(cache["entries"]), 13 * 2)
        self.assertIn("compteurs", cache["entries"]["75_2020"]); self.assertTrue(cache["entries"]["75_2025"]["empreinte"])
        self.assertEqual(m["fichiers_telecharges"], 26)

    def test_cache_reutilise_et_compteurs_conserves(self):
        code, _ = self.run_pipeline(); self.assertEqual(code, 0)
        d1 = json.load(open("data/dvf_paris.json", encoding="utf-8")); mtime1 = os.path.getmtime("data/dvf_paris.json")
        # Second run, sources inchangées : rien n'est téléchargé, rien n'est réécrit
        P.HEAD_CACHE.clear(); P.HEAD_INFO.clear(); P.CPT = P.Compteurs(); sys.argv = ["process_dvf.py"]
        self.assertEqual(P.main(), 0)
        self.assertEqual(os.path.getmtime("data/dvf_paris.json"), mtime1)
        # Troisième run : un seul fichier source modifié (2025/75) → un seul téléchargement, exclusions cachées conservées
        f = os.path.join(self.src, "geo-dvf/latest/csv/2025/departements/75.csv.gz"); os.utime(f, (os.path.getmtime(f) + 100,) * 2)
        P.HEAD_CACHE.clear(); P.HEAD_INFO.clear(); P.CPT = P.Compteurs(); sys.argv = ["process_dvf.py"]
        self.assertEqual(P.main(), 0)
        d2 = json.load(open("data/dvf_paris.json", encoding="utf-8"))
        self.assertEqual(d2["meta"]["fichiers_telecharges"], 1)
        self.assertEqual(d1["meta"]["exclusions"]["75"]["2018"], d2["meta"]["exclusions"]["75"]["2018"])
        self.assertEqual(d1["secteurs"]["5"]["by_type"]["Appartement"]["count"], d2["secteurs"]["5"]["by_type"]["Appartement"]["count"])
        # --force recalcule même sans changement
        P.HEAD_CACHE.clear(); P.HEAD_INFO.clear(); P.CPT = P.Compteurs(); sys.argv = ["process_dvf.py", "--force"]
        self.assertEqual(P.main(), 0); self.assertEqual(json.load(open("data/dvf_paris.json", encoding="utf-8"))["meta"]["fichiers_telecharges"], 0)

    def test_garde_annee_creuse(self):
        code, _ = self.run_pipeline("annee_creuse")
        self.assertEqual(code, 2); self.assertFalse(os.path.exists("data/dvf_paris.json"))
        # Autorisation explicite → publie
        P.HEAD_CACHE.clear(); P.HEAD_INFO.clear(); P.CPT = P.Compteurs(); sys.argv = ["process_dvf.py", "--allow-partial", "2018"]
        self.assertEqual(P.main(), 0)

    def test_garde_source_partielle(self):
        code, _ = self.run_pipeline("partiel_2019")
        self.assertEqual(code, 2); self.assertFalse(os.path.exists("data/dvf_paris.json"))

    def test_colonnes_manquantes_echouent(self):
        import io
        with self.assertRaises(RuntimeError):
            P.parse_csv(io.StringIO("id_mutation,valeur_fonciere\n1,2\n"), 2024, "75", P.DEPS["75"])

if __name__ == "__main__":
    unittest.main()

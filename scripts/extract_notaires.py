#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Séries longues des notaires du Grand Paris (base BIEN) → data/historique_notaires.json.

Deux PDF publics, relus une fois par an à la main (les notaires les republient après chaque T4 ; rien à automatiser,
la mise en page change rarement mais n'est pas garantie) :
  - prix au m² standardisés des appartements anciens par arrondissement de Paris, trimestriel depuis T1 1996 ;
  - indices Notaires-INSEE des appartements anciens par département d'Île-de-France (base 100 en 2015), trimestriel
    depuis T1 1991 (75, 92, 93, 94) ou T1 1996 (77, 78, 91, 95).

Usage : python3 scripts/extract_notaires.py [--arr arr.pdf --dept dept.pdf] [--macro data/macro.json] [--out data/historique_notaires.json]
Sans --arr/--dept : télécharge la version la plus récente publiée sur paris.notaires.fr. Relevé du 27/11/2026 : le fichier de
basebien.com date de mars 2025 (T4 2024) alors que paris.notaires.fr republie chaque trimestre sous un suffixe croissant
(…pararrdt_4.pdf et …pardept_4.pdf du 8 septembre 2026 : T2 2026 ; _1 nov. 2025, _2 mars 2026, _3 mai 2026). On essaie donc
les suffixes du plus grand au plus petit et on prend le premier qui existe. Si rien n'est joignable et qu'un fichier de sortie
existe déjà, il est conservé (code 0, comme fetch_demo) ; sinon code 1.

Contrôles (le programme sort en erreur s'ils échouent — une colonne décalée produirait un fichier plausible et faux) :
  - chaque ligne de trimestre porte exactement le nombre de colonnes attendu (21 pour les arrondissements, 11 pour les
    départements), les « n.d. » comptés ;
  - les trimestres sont consécutifs, sans trou ;
  - l'indice Paris du PDF départemental et l'indice INSEE 010567013 de macro.json (même indice Notaires-INSEE, base 2015)
    coïncident à 1,5 point près chaque trimestre (CVS contre brut) et à 0,5 point près en moyenne annuelle ;
  - les prix des arrondissements et l'indice Paris évoluent dans le même sens : corrélation des variations trimestrielles
    de la moyenne simple des 20 arrondissements avec celles de l'indice Paris > 0,8.
"""
import argparse, json, os, re, subprocess, sys, datetime, statistics, tempfile, urllib.request

SITE = "https://paris.notaires.fr/sites/default/files/"
BASES = {"arr": "HistoriquedesprixaumappartementsanciensParispararrdt", "dept": "Indicesdesprixdesappartementspardept"}
SUFFIXES = [f"_{n}" for n in range(12, -1, -1)] + [""]


def plus_recent(kind, timeout=30):
    """(url, Last-Modified) du PDF au plus grand suffixe existant ; (None, None) si aucun ne répond."""
    for suf in SUFFIXES:
        url = f"{SITE}{BASES[kind]}{suf}.pdf"
        try:
            req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "residentiel-paris-DVF"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                if r.status == 200:
                    return url, r.headers.get("Last-Modified")
        except Exception:
            continue
    return None, None


def telecharger(url, dest, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "residentiel-paris-DVF"})
    with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, "wb") as f:
        f.write(r.read())

ARR_COLS = ["centre"] + [f"751{i:02d}" for i in range(1, 21)]
DEPT_COLS = ["idf", "75", "pc", "92", "93", "94", "gc", "77", "78", "91", "95"]
TRIM = re.compile(r"^\s*T([1-4]) (\d{4})\s+(.*)$")


def pdftotext(path):
    return subprocess.run(["pdftotext", "-layout", path, "-"], check=True, capture_output=True, text=True).stdout


def parse(text, ncols, kind):
    """{ 'YYYY-Qn': [v0, ..., v(ncols-1)] } ; None pour n.d."""
    rows, bad = {}, []
    for line in text.splitlines():
        m = TRIM.match(line)
        if not m:
            continue
        q, y, rest = m.group(1), m.group(2), m.group(3)
        if kind == "prix":
            toks = re.findall(r"(\d[\d ]*\d|\d)\s*€|n\.?d\.?", rest)
            vals = [None if "n" in t else int(t.replace(" ", "")) for t in toks]
        else:
            toks = re.findall(r"\d+,\d|n\.?d\.?", rest)
            vals = [None if "n" in t else float(t.replace(",", ".")) for t in toks]
        key = f"{y}-Q{q}"
        if len(vals) != ncols:
            bad.append((key, len(vals), rest.strip()[:80]))
            continue
        if key in rows:
            bad.append((key, "doublon", ""))
            continue
        rows[key] = vals
    return rows, bad


def quarters(a, b):
    y, q = int(a[:4]), int(a[-1])
    out = []
    while True:
        k = f"{y}-Q{q}"
        out.append(k)
        if k == b:
            return out
        q += 1
        if q == 5:
            q, y = 1, y + 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arr", default=None, help="PDF local des prix par arrondissement (sinon téléchargé)")
    ap.add_argument("--dept", default=None, help="PDF local des indices par département (sinon téléchargé)")
    ap.add_argument("--macro", default="data/macro.json")
    ap.add_argument("--out", default="data/historique_notaires.json")
    a = ap.parse_args()
    errs = []
    meta_src = {}
    if not (a.arr and a.dept):
        tmp = tempfile.mkdtemp()
        for kind in ("arr", "dept"):
            url, lm = plus_recent(kind)
            if not url:
                msg = f"aucun PDF {kind} joignable sur paris.notaires.fr"
                if os.path.exists(a.out):
                    print(f"  ! {msg} — fichier précédent conservé"); return
                print(f"  ✗ {msg}"); sys.exit(1)
            dest = os.path.join(tmp, f"{kind}.pdf")
            try:
                telecharger(url, dest)
            except Exception as e:
                if os.path.exists(a.out):
                    print(f"  ! téléchargement {kind} en échec ({e}) — fichier précédent conservé"); return
                print(f"  ✗ téléchargement {kind} en échec : {e}"); sys.exit(1)
            setattr(a, kind, dest); meta_src[kind] = {"url": url, "last_modified": lm}
            print(f"{kind} : {url} ({lm})")

    prix, bad1 = parse(pdftotext(a.arr), len(ARR_COLS), "prix")
    idx, bad2 = parse(pdftotext(a.dept), len(DEPT_COLS), "indice")
    for k, n, r in bad1 + bad2:
        errs.append(f"ligne rejetée {k} : {n} colonnes · {r}")
    for name, rows in (("prix", prix), ("indices", idx)):
        ks = sorted(rows)
        exp = quarters(ks[0], ks[-1])
        trous = [k for k in exp if k not in rows]
        if trous:
            errs.append(f"{name} : {len(trous)} trimestre(s) manquant(s) : {trous[:6]}")
        print(f"{name} : {len(ks)} trimestres, {ks[0]} → {ks[-1]}, n.d. = {sum(v is None for r in rows.values() for v in r)}")

    # contrôle 1 : indice Paris du PDF (brut) vs indice INSEE de macro.json (le même indice Notaires-INSEE, mais CVS :
    # l'écart trimestriel est saisonnier, mesuré ≤ 1,0 pt le 27/11/2026 ; les moyennes annuelles doivent coïncider)
    ecarts, n_comm, ecart_max, ecarts_an = [], 0, 0.0, []
    try:
        macro = json.load(open(a.macro, encoding="utf-8"))
        insee = macro["series"]["insee_paris_appart"]["obs"]
        ip = DEPT_COLS.index("75")
        par_an = {}
        for k, vals in idx.items():
            if k in insee and vals[ip] is not None and insee[k] is not None:
                n_comm += 1
                d = abs(float(insee[k]) - vals[ip]); ecart_max = max(ecart_max, d)
                if d > 1.5:
                    ecarts.append((k, insee[k], vals[ip]))
                par_an.setdefault(k[:4], []).append((float(insee[k]), vals[ip]))
        for y, l in sorted(par_an.items()):
            if len(l) == 4:
                d = abs(statistics.fmean(x for x, _ in l) - statistics.fmean(x for _, x in l))
                if d > 0.5:
                    ecarts_an.append((y, round(d, 2)))
        print(f"indice Paris : {n_comm} trimestres communs avec l'INSEE, écart max {ecart_max:.1f} pt, {len(ecarts)} écart(s) > 1,5 pt, {len(ecarts_an)} année(s) dont la moyenne diffère de plus de 0,5 pt {ecarts_an}")
        if n_comm < 40:
            errs.append(f"trop peu de trimestres communs avec l'INSEE ({n_comm})")
        if ecarts or ecarts_an:
            errs.append(f"indice Paris ≠ INSEE : {len(ecarts)} trimestre(s) à plus de 1,5 pt, {len(ecarts_an)} année(s) en moyenne")
    except (KeyError, FileNotFoundError) as e:
        errs.append(f"macro.json illisible pour le contrôle INSEE : {e}")

    # contrôle 2 : les prix d'arrondissement bougent avec l'indice Paris
    ks = [k for k in sorted(prix) if k in idx and all(v is not None for v in prix[k][1:])]
    moy = {k: statistics.fmean(prix[k][1:]) for k in ks}
    ip = DEPT_COLS.index("75")
    dx = [moy[ks[i]] / moy[ks[i - 1]] - 1 for i in range(1, len(ks))]
    dy = [idx[ks[i]][ip] / idx[ks[i - 1]][ip] - 1 for i in range(1, len(ks))]
    corr = statistics.correlation(dx, dy) if len(dx) > 2 else 0
    print(f"corrélation des variations trimestrielles (moyenne des 20 arr. vs indice Paris) : {corr:.3f} sur {len(dx)} trimestres")
    if corr < 0.8:
        errs.append(f"corrélation prix arrondissements / indice Paris trop faible ({corr:.3f})")

    if errs:
        print("\n".join("  ✗ " + e for e in errs))
        sys.exit(1)

    out = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "source": {
            "editeur": "Notaires du Grand Paris – base BIEN (Paris Notaires Services)",
            "prix": {"titre": "Historique des prix au m² standardisés des appartements anciens à Paris par arrondissement",
                     "url": meta_src.get("arr", {}).get("url", a.arr), "last_modified": meta_src.get("arr", {}).get("last_modified"),
                     "note": "Appartements anciens vendus libres, de gré à gré, en pleine propriété, à usage d'habitation ; prix standardisé (à qualité constante, méthode des indices Notaires-INSEE), en €/m², trimestriel."},
            "indices": {"titre": "Indices Notaires-INSEE des appartements anciens par département",
                        "url": meta_src.get("dept", {}).get("url", a.dept), "last_modified": meta_src.get("dept", {}).get("last_modified"),
                        "note": "Base 100 en 2015 ; trimestriel ; 75/92/93/94 depuis 1991, 77/78/91/95 depuis 1996."},
        },
        "controles": {"trimestres_communs_insee": n_comm, "ecart_max_insee_pt": round(ecart_max, 2), "correlation_arr_vs_paris": round(corr, 3)},
        "prix_cols": ARR_COLS,
        "prix": {k: prix[k] for k in sorted(prix)},
        "indices_cols": DEPT_COLS,
        "indices": {k: idx[k] for k in sorted(idx)},
    }
    s = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    if os.path.exists(a.out):
        old = json.load(open(a.out, encoding="utf-8"))
        if {k: v for k, v in old.items() if k != "generated_at"} == {k: v for k, v in out.items() if k != "generated_at"}:
            print(f"{a.out} inchangé")
            return
    open(a.out, "w", encoding="utf-8").write(s)
    print(f"écrit {a.out} ({len(s)} octets)")


if __name__ == "__main__":
    main()

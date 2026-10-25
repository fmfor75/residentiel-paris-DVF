"""Répétition de bout en bout du rapport PDF (lot 14, après le rapport du 15/10/2026 : en-têtes décalés, textes hors cadre,
chiffres superposés, glyphe disparu, étiquettes masquées dans le visuel du rayon — aucun test ne le voyait).

1. Génère le PDF de plusieurs études types dans un Chromium sans interface, sur le site servi en local, en enregistrant chaque
   appel de dessin jsPDF (texte, cartouches, images) et les boîtes des textes du visuel SVG du rayon.
2. Vérité terrain : les glyphes réellement écrits dans le PDF (pdfplumber, dans l'ordre du flux), rattachés un à un aux
   appels enregistrés — chaque texte a sa boîte réelle, même quand deux textes se touchent.
3. Contrôles : glyphe absent de la police ; texte hors des marges ; textes qui se chevauchent ou accolés sur une ligne ;
   texte qui déborde de son cartouche ; textes alignés sur une même abscisse qui ne finissent pas au même endroit ;
   texte raccourci (« … ») ; nombre à point décimal ; visuel du rayon : chevauchements, texte sur une barre (hors étiquettes
   à halo), texte hors cadre, bande vide sous le titre.

Prérequis : données locales chiffrées avec le code de test (DVF_CODE=code-de-test-local python3 scripts/build_site.py),
site servi sur http://localhost:8765 (python3 -m http.server 8765), pip install playwright pdfplumber.
Usage : python3 tests/audit_pdf.py [dossier_sortie] [config ...]   → code 1 s'il reste un défaut.
À exécuter avant chaque livraison qui touche au PDF ou au visuel du rayon : critère de fin = 0 défaut.
Rappel : avant de commiter, git checkout origin/main -- data/enc (les données de test ne partent jamais)."""
import asyncio, json, os, sys, glob, itertools, re, collections
import pdfplumber
from playwright.async_api import async_playwright
MM = 72 / 25.4
PW, M = 210, 18

B = "http://localhost:8765/"
JSPDF = "https://cdnjs.cloudflare.com/ajax/libs/jspdf/3.0.4/jspdf.umd.min.js"
TYP = "T1:9-30:{},T2:30-50:{},T3:50-70:{},T4:70-100:{},T5:100-400:{}"
def typos(*on): return TYP.format(*[1 if f"T{i}" in on else 0 for i in range(1, 6)])
PERSP = "persp=3.5:20:1:0.5:0:0.12"
CONFIGS = {
  # reproduction du rapport de Franck du 15/10 (12 avenue Albine, maisons, 10 ans, rayon 500 m, T5)
  "albine_maisons_T5": f"niveau=rayon&id=500&per=10&gran=annee&type=Maison&global=1&vue=etude&typos={typos('T5')}&rprix=::::5:T5:1&{PERSP}&addr=2.146009,48.951536,12 Avenue Albine 78600 Maisons-Laffitte",
  # une seule série sur 10 ans : barres étroites, étiquettes de déciles au plus près des barres
  "albine_appart_10ans": f"niveau=rayon&id=500&per=10&gran=annee&type=Appartement&global=1&vue=etude&typos={typos('T3')}&rprix=6000:8000:7000:20:10::1&addr=2.146009,48.951536,12 Avenue Albine 78600 Maisons-Laffitte",
  # Paris entier (lot 16), historique complet : tableaux à 12 colonnes, grands effectifs
  "paris_ville_all": f"niveau=commune&id=75056&per=all&gran=annee&type=Appartement&global=1&vue=etude&typos={typos('T2','T5')}",
  # Paris, appartements, valorisation + rayon 300 m sur 10 ans avec trois typologies et les trois prix
  "penthievre_valo_rayon10": f"niveau=rayon&id=300&per=5&gran=annee&type=Appartement&global=1&vue=etude&typos={typos('T2','T3','T4')}&rprix=11000:14500:12000:20:10:T2,T3,T4:1&valo=50|0|1;T2:4:42:0:2,T3:3:62:0:3,T4:1:85:0:4&{PERSP}&addr=2.316624,48.87293,13 Rue de Penthièvre 75008 Paris",
  # Saint-Maur, tous logements, sections par type
  "saintmaur_tous": f"niveau=commune&id=94068&per=5&gran=annee&type=Tous&global=1&vue=etude&typos={typos('T2','T3')}&addr=2.487589,48.803825,20 Avenue Foch 94100 Saint-Maur-des-Fossés",
  # rayon tous logements, historique 2 ans, une typologie
  "saintmaur_rayon_tous2": f"niveau=rayon&id=500&per=2&gran=trimestre&type=Tous&global=1&vue=etude&typos={typos('T3')}&rprix=:9000:::2:T3:1&addr=2.487589,48.803825,20 Avenue Foch 94100 Saint-Maur-des-Fossés",
  # lot 17 : page « Démographie et parc » — commune avec coefficient appliqué (+0,3), secteur = plusieurs arrondissements, Paris entier
  "neuilly_persp_demo": f"niveau=commune&id=92051&per=5&gran=annee&type=Appartement&global=1&vue=etude&typos={typos('T2','T4')}&persp=3.5:12:2:0.5:0:0.2:0.3",
  "secteur_persp_demo": f"niveau=secteur&id=3&per=5&gran=annee&type=Appartement&global=1&vue=etude&typos={typos('T3')}&persp=3.5:12:2:0.5:0:0.2:0",
  # quartier parisien, appartements, historique complet, mois
  "paris_quartier_all": f"niveau=quartier&id=P30&per=all&gran=annee&type=Appartement&global=1&vue=etude&typos={typos('T1','T2','T3','T4','T5')}",
}
PATCH = """() => { const J = window.jspdf.jsPDF; window.__rec = [];
  window.jspdf.jsPDF = function(...a){ const d = new J(...a); const pg = () => d.getCurrentPageInfo().pageNumber;
    const t = d.text.bind(d); d.text = function(s, x, y, o){ window.__rec.push({k:'t', p:pg(), s: Array.isArray(s) ? s.join('\\n') : String(s), x, y,
      align: o?.align || 'left', cs: o?.charSpace || 0, mw: o?.maxWidth || null, fs: d.getFontSize(), w: d.getTextWidth(Array.isArray(s) ? s[0] : String(s))}); return t(s, x, y, o); };
    const rr = d.roundedRect.bind(d); d.roundedRect = function(x, y, w, h, ...r){ window.__rec.push({k:'rr', p:pg(), x, y, w, h}); return rr(x, y, w, h, ...r); };
    const ai = d.addImage.bind(d); d.addImage = function(img, f, x, y, w, h, ...r){ window.__rec.push({k:'img', p:pg(), x, y, w, h}); return ai(img, f, x, y, w, h, ...r); };
    return d; }; }"""
SVG_BOXES = """() => { const s = document.querySelector('#rayonSvg svg'); if (!s) return null;
  // boîtes à l'écran ramenées dans le repère du viewBox (getBBox ignore les rotations des étiquettes verticales)
  const vb = s.viewBox.baseVal, m = s.getScreenCTM().inverse();
  const box = el => { const r = el.getBoundingClientRect(); const a = new DOMPoint(r.left, r.top).matrixTransform(m), b = new DOMPoint(r.right, r.bottom).matrixTransform(m); return {x: a.x, y: a.y, w: b.x - a.x, h: b.y - a.y}; };
  const T = [...s.querySelectorAll('text')].map(t => ({s: t.textContent, halo: t.getAttribute('paint-order') === 'stroke', ...box(t)}));
  const R = [...s.querySelectorAll('rect')].map(r => ({fill: r.getAttribute('fill'), ...box(r)}));
  return {W: vb.width, H: vb.height, texts: T, rects: R}; }"""

async def run(b, name, h, out):
    ctx = await b.new_context(viewport={"width": 1440, "height": 900}, accept_downloads=True); pg = await ctx.new_page(); errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)[:200]))
    await pg.goto(B + "#" + h, wait_until="networkidle"); await pg.fill("#code", "code-de-test-local"); await pg.click("#gateBtn")
    await pg.wait_for_selector("#hdr h2", timeout=90000); await pg.wait_for_timeout(2500)
    await pg.add_script_tag(url=JSPDF); await pg.evaluate(PATCH)
    svg = await pg.evaluate(SVG_BOXES)
    async with pg.expect_download(timeout=240000) as dl: await pg.click("#btnPdf")
    d = await dl.value; pdf = os.path.join(out, name + ".pdf"); await d.save_as(pdf)
    rec = await pg.evaluate("() => window.__rec")
    json.dump({"name": name, "hash": h, "file": d.suggested_filename, "rec": rec, "svg": svg, "errors": errs}, open(os.path.join(out, name + ".json"), "w"), ensure_ascii=False)
    print(f"{name}: {len(rec)} appels, svg={'oui' if svg else 'non'}, erreurs JS={errs[:2]}", flush=True)
    await ctx.close()


def boxes_for(pdf_path, rec):
    pdf = pdfplumber.open(pdf_path); out = []; bad = 0
    calls = [r for r in rec if r["k"] == "t"]
    for pn, page in enumerate(pdf.pages, 1):
        chars = [c for c in page.chars if c["text"].strip()]
        i = 0
        for r in (c for c in calls if c["p"] == pn):
            want = "".join(r["s"].split())
            if not want: continue
            # glyphe absent de la police embarquée : jsPDF ne l'écrit pas (constaté : « ← » sur la page Méthode) → on le signale et on continue
            got, miss = [], []
            for ch in want:
                if i < len(chars) and chars[i]["text"] == ch: got.append(chars[i]); i += 1
                else: miss.append(ch)
            if miss: out.append({**r, "x0": None, "err": f"GLYPHE ABSENT    {''.join(sorted(set(miss)))!r} dans {r['s'][:40]!r}"})
            if len(miss) > 3 or not got: bad += 1; out.append({**r, "x0": None, "err": f"rattachement impossible : {want[:30]!r}"}); continue
            # hauteur utile : du haut des capitales (0,72 em) au bas des jambages (0,2 em), par ligne
            lines = {}
            for c in got: lines.setdefault(round(c["y1"], 1), []).append(c)
            for ln in lines.values():
                base = page.height - min(c["y0"] for c in ln) - 0.2 * ln[0]["size"]
                out.append({**r, "x0": min(c["x0"] for c in ln), "x1": max(c["x1"] for c in ln),
                            "top": base - 0.72 * ln[0]["size"], "bot": base + 0.2 * ln[0]["size"], "base": base, "txt": "".join(c["text"] for c in ln)})
    return out, bad

def check(folder):
    total = 0
    for jf in sorted(glob.glob(os.path.join(folder, "*.json"))):
        D = json.load(open(jf)); pdfp = jf[:-5] + ".pdf"; pb = []
        bx, bad = boxes_for(pdfp, D["rec"])
        pb += [f"p{b['p']} {b['err']}" for b in bx if b.get("err")]
        bx = [b for b in bx if b.get("x0") is not None]
        L, R = M * MM, (PW - M) * MM
        for b in bx:
            if b["x0"] < L - 0.6 or b["x1"] > R + 0.6: pb.append(f"p{b['p']} HORS MARGE      {b['txt'][:45]!r} x {b['x0']:.1f}–{b['x1']:.1f} pt (marges {L:.1f}–{R:.1f})")
        for p in sorted({b["p"] for b in bx}):
            pg = [b for b in bx if b["p"] == p]
            for a, c in itertools.combinations(pg, 2):
                ix = min(a["x1"], c["x1"]) - max(a["x0"], c["x0"]); iy = min(a["bot"], c["bot"]) - max(a["top"], c["top"])
                if ix > 0.3 and iy > 0.3: pb.append(f"p{p} CHEVAUCHEMENT   {a['txt'][:28]!r} / {c['txt'][:28]!r} ({ix:.1f} × {iy:.1f} pt)")
                elif abs(a["base"] - c["base"]) < 0.6 and -1.0 < ix <= 0.3: pb.append(f"p{p} ACCOLÉS         {a['txt'][:28]!r} / {c['txt'][:28]!r} (écart {-ix:.1f} pt)")
            for t in (r for r in D["rec"] if r["k"] == "rr" and r["p"] == p):
                x0, y0, x1, y1 = t["x"] * MM, t["y"] * MM, (t["x"] + t["w"]) * MM, (t["y"] + t["h"]) * MM
                for b in pg:
                    if x0 <= b["x0"] < x1 and y0 <= b["base"] <= y1 and (b["x1"] > x1 - 0.8 or b["bot"] > y1 + 0.3 or b["top"] < y0 - 0.3):
                        pb.append(f"p{p} DÉBORDE CADRE   {b['txt'][:40]!r} x1 {b['x1']:.1f} / bord {x1:.1f} pt, bas {b['bot']:.1f} / {y1:.1f}")
        # (6) alignement : les textes alignés à droite (ou centrés) sur la même abscisse doivent finir (ou être centrés) au même
        # endroit — l'espacement des lettres décalait les en-têtes de colonne de leurs chiffres
        grp = collections.defaultdict(list)
        for b in bx:
            if b["align"] in ("right", "center") and "\n" not in b["s"]: grp[(b["p"], b["align"], round(b["x"], 2))].append(b)
        for (p, al, x), g in grp.items():
            ref = (lambda b: b["x1"]) if al == "right" else (lambda b: (b["x0"] + b["x1"]) / 2)
            if len(g) > 1 and max(map(ref, g)) - min(map(ref, g)) > 0.8:
                worst = max(g, key=lambda b: abs(ref(b) - x * MM))
                pb.append(f"p{p} DÉSALIGNÉ       {len(g)} textes {'à droite' if al == 'right' else 'centrés'} sur x={x:.1f} mm : écart {max(map(ref, g)) - min(map(ref, g)):.1f} pt (pire : {worst['txt'][:25]!r})")
        # (8) texte raccourci pour tenir dans son cadre (« … » ajouté par st.text) : information perdue, à signaler
        for r in D["rec"]:
            if r["k"] == "t" and r["s"].endswith("…"): pb.append(f"p{r['p']} COUPÉ           {r['s'][:50]!r}")
        # (7) nombres décimaux à l'anglaise (« 159.5 m² ») dans un document en français
        for b in bx:
            if re.search(r"\d\.\d", b["s"]) and not re.search(r"https?://|Licence Ouverte", b["s"]): pb.append(f"p{b['p']} POINT DÉCIMAL   {b['s'][:50]!r}")
        S = D.get("svg")
        if S:
            T = [t for t in S["texts"] if t["w"] > 0]
            for a, c in itertools.combinations(T, 2):
                ix = min(a["x"] + a["w"], c["x"] + c["w"]) - max(a["x"], c["x"]); iy = min(a["y"] + a["h"], c["y"] + c["h"]) - max(a["y"], c["y"])
                if ix > 0.5 and iy > 0.25 * min(a["h"], c["h"]): pb.append(f"SVG CHEVAUCHEMENT {a['s'][:25]!r} / {c['s'][:25]!r} ({ix:.1f} × {iy:.1f} px)")
            bars = [r for r in S["rects"] if r["h"] > 0 and r["w"] > 0 and r["w"] < 200]
            for t in T:
                if t["x"] < -0.5 or t["x"] + t["w"] > S["W"] + 0.5 or t["y"] < -0.5 or t["y"] + t["h"] > S["H"] + 0.5: pb.append(f"SVG HORS CADRE    {t['s'][:40]!r}")
                for r in bars:
                    ix = min(t["x"] + t["w"], r["x"] + r["w"]) - max(t["x"], r["x"]); iy = min(t["y"] + t["h"], r["y"] + r["h"]) - max(t["y"], r["y"])
                    if ix > 1 and iy > 0.4 * t["h"] and not t["s"].startswith(("Médiane",)) and not t.get("halo") and r["y"] > 60: pb.append(f"SVG TEXTE SUR BARRE {t['s'][:25]!r} ({ix:.1f} px sur la barre)")
            ttl = T[0]; below = [t for t in T[1:] if t["y"] > ttl["y"] + ttl["h"]]
            gap = min(t["y"] for t in below) - (ttl["y"] + ttl["h"]) if below else 0
            if gap > 30: pb.append(f"SVG BANDE VIDE    {gap:.0f} px entre le titre et l'élément suivant (hauteur {S['H']:.0f})")
        print(f"── {D['name']} ({len(bx)} textes mesurés, {len(D['rec'])} appels) : {len(pb)} défaut(s)")
        for x in pb: print("   " + x)
        total += len(pb)
    print("TOTAL", total); return total


async def generer(out, names):
    os.makedirs(out, exist_ok=True)
    async with async_playwright() as p:
        b = await p.chromium.launch()
        for n in names: await run(b, n, CONFIGS[n], out)
        await b.close()

if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "audit_pdf_sortie"
    names = sys.argv[2:] or list(CONFIGS)
    for f in glob.glob(os.path.join(out, "*.json")): os.remove(f)
    asyncio.run(generer(out, names))
    sys.exit(1 if check(out) else 0)

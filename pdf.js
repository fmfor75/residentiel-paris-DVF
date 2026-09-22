// pdf.js — export de l'étude en PDF, entièrement dans le navigateur.
//
// Chargé à la demande par index.html (import dynamique) : jsPDF depuis cdnjs, polices Inter (sous-ensemble Latin,
// assets/inter-pdf.js), carte dessinée sur un canvas depuis les tuiles IGN (CORS « * » vérifié le 18/09/2026) et les
// polygones du référentiel — donc identique au découpage affiché à l'écran.
//
// Les chiffres viennent de l'étude déjà calculée par engine.js (ctx.et) : aucun recalcul ici, une seule source.
// Texte vectoriel (sélectionnable, net à toute échelle) ; la carte est la seule image.

import { regular, semibold } from './assets/inter-pdf.js';

const JSPDF_URL = 'https://cdnjs.cloudflare.com/ajax/libs/jspdf/3.0.4/jspdf.umd.min.js';
const TILE = (z, x, y) => `https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2&STYLE=normal&FORMAT=image/png&TILEMATRIXSET=PM&TILEMATRIX=${z}&TILEROW=${y}&TILECOL=${x}&ctx=pdf`;   // « &ctx=pdf » : entrée de cache distincte de celle de Leaflet (chargée sans CORS), sinon Chrome refuse la réutilisation

// Palette : navy du site, vert et gris relevés sur le logo Jadero (48,125,73 / 61,66,76)
const C = { navy:[11,18,32], text:[30,41,59], text2:[71,85,105], grey:[100,116,139], grey2:[148,163,184], line:[222,226,232], line2:[236,239,243],
            green:[48,125,73], accent:[30,64,175], accent2:[42,120,214], good:[4,120,87], bad:[185,28,28], gold:[161,98,7], tile:[248,249,251] };
const PW = 210, PH = 297, M = 18, CW = PW - 2*M;      // A4 portrait, marges 18 mm, largeur utile 174 mm
const pt2mm = 0.3528;

function loadScript(url){ return new Promise((ok, ko) => { if (window.jspdf) return ok(); const s = document.createElement('script'); s.src = url; s.onload = ok; s.onerror = () => ko(new Error('bibliothèque PDF non chargée (réseau ?)')); document.head.appendChild(s); }); }
function loadImage(url, cors=false){ return new Promise((ok, ko) => { const im = new Image(); if (cors) im.crossOrigin = 'anonymous'; im.onload = () => ok(im); im.onerror = () => ko(new Error('image non chargée : ' + url.slice(0, 60))); im.src = url; }); }

// ── Carte : projection Web Mercator, tuiles IGN, polygones du référentiel ─────────────────────────────────────
function proj(lon, lat, z){ const n = 256 * Math.pow(2, z); const s = Math.sin(lat * Math.PI / 180); return [(lon + 180) / 360 * n, (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * n]; }
function ringsOf(f){ const g = f.geometry; return (g.type === 'MultiPolygon' ? g.coordinates : [g.coordinates]).map(poly => poly); }
async function renderMap(ctx, W, H){
  const { geo, groupOfFeature, groupNiveau, colorOf, S, item, address } = ctx;
  const selected = f => { const g = groupOfFeature(f.properties); return g === item.id && S.niveau === groupNiveau(g); };
  // Cadrage : adresse → centrée, zoom 15 (≈ 3 m/px : le quartier reste lisible) ; sinon la zone entière au plus grand zoom qui la contient
  let z, cx, cy;
  if (address) { z = 15; [cx, cy] = proj(address.lon, address.lat, z); }
  else {
    let lo = [Infinity, Infinity], hi = [-Infinity, -Infinity];
    for (const f of geo.features) if (selected(f)) for (const poly of ringsOf(f)) for (const [x, y] of poly[0]) { lo = [Math.min(lo[0], x), Math.min(lo[1], y)]; hi = [Math.max(hi[0], x), Math.max(hi[1], y)]; }
    if (!isFinite(lo[0])) throw new Error('zone introuvable dans le référentiel');
    for (z = 16; z >= 9; z--) { const a = proj(lo[0], hi[1], z), b = proj(hi[0], lo[1], z); if (b[0] - a[0] <= W - 90 && b[1] - a[1] <= H - 90) { cx = (a[0] + b[0]) / 2; cy = (a[1] + b[1]) / 2; break; } }
  }
  const ox = cx - W / 2, oy = cy - H / 2;
  const cv = document.createElement('canvas'); cv.width = W; cv.height = H; const g2 = cv.getContext('2d');
  g2.fillStyle = '#E9EDF3'; g2.fillRect(0, 0, W, H);
  const tiles = []; for (let tx = Math.floor(ox / 256); tx <= Math.floor((ox + W) / 256); tx++) for (let ty = Math.floor(oy / 256); ty <= Math.floor((oy + H) / 256); ty++) tiles.push([tx, ty]);
  // 6 chargements en parallèle et 2 nouvelles tentatives : en rafale de 30, certaines tuiles revenaient en erreur (observé en test)
  let missing = 0; const queue = tiles.slice();
  const worker = async () => { while (queue.length) { const [tx, ty] = queue.shift(); let ok = false;
    for (let k = 0; k < 3 && !ok; k++) { try { const im = await loadImage(TILE(z, tx, ty) + (k ? `&r=${k}` : ''), true); g2.drawImage(im, tx * 256 - ox, ty * 256 - oy); ok = true; } catch(_) { await new Promise(r => setTimeout(r, 300 * (k + 1))); } }
    if (!ok) missing++; } };
  await Promise.all(Array.from({ length: 6 }, worker));
  g2.fillStyle = 'rgba(255,255,255,.18)'; g2.fillRect(0, 0, W, H);        // même voile que l'écran (opacité .85)
  const path = poly => { g2.beginPath(); for (const ring of poly) ring.forEach(([lon, lat], i) => { const [x, y] = proj(lon, lat, z); i ? g2.lineTo(x - ox, y - oy) : g2.moveTo(x - ox, y - oy); }); g2.closePath(); };
  const order = geo.features.slice().sort((a, b) => selected(a) - selected(b));   // la zone sélectionnée par-dessus
  for (const f of order) { const sel = selected(f), col = colorOf(groupOfFeature(f.properties));
    for (const poly of ringsOf(f)) { path(poly); g2.fillStyle = col; g2.globalAlpha = sel ? .55 : .3; g2.fill('evenodd'); g2.globalAlpha = 1; g2.lineWidth = sel ? 4 : 1.2; g2.strokeStyle = sel ? '#0B1220' : 'rgba(11,18,32,.5)'; g2.stroke(); } }
  if (address) { const [x, y] = proj(address.lon, address.lat, z); const px = x - ox, py = y - oy;
    g2.beginPath(); g2.arc(px, py, 22, 0, 7); g2.fillStyle = 'rgba(185,28,28,.18)'; g2.fill();
    g2.beginPath(); g2.arc(px, py, 10, 0, 7); g2.fillStyle = '#B91C1C'; g2.fill(); g2.lineWidth = 3.5; g2.strokeStyle = '#fff'; g2.stroke(); }
  // attribution (obligation IGN) + note si des tuiles manquent
  g2.font = '600 15px Inter, system-ui, sans-serif'; const attr = '© IGN – Géoplateforme' + (missing ? ` · ${missing}/${tiles.length} tuiles non chargées` : '');
  const tw = g2.measureText(attr).width + 16; g2.fillStyle = 'rgba(255,255,255,.85)'; g2.fillRect(W - tw, H - 26, tw, 26); g2.fillStyle = '#334155'; g2.fillText(attr, W - tw + 8, H - 8);
  return { data: cv.toDataURL('image/jpeg', .9), missing, total: tiles.length, zoom: z };
}

// ── Petits utilitaires de mise en page ─────────────────────────────────────────────────────────────────────
function mk(doc){
  const st = { doc, y: 0, page: 1 };
  st.font = (weight = 'normal', size = 9, color = C.text) => { doc.setFont('Inter', weight); doc.setFontSize(size); doc.setTextColor(...color); };
  st.text = (str, x, y, o = {}) => { st.font(o.w, o.s, o.c); doc.text(String(str), x, y, { align: o.align || 'left', charSpace: o.ls || 0, maxWidth: o.maxWidth }); };
  st.caps = (str, x, y, o = {}) => st.text(String(str).toUpperCase(), x, y, { s: o.s || 6.6, w: 'bold', c: o.c || C.grey, ls: o.ls ?? 0.5, align: o.align });
  st.line = (x1, y1, x2, y2, color = C.line, w = 0.25) => { doc.setDrawColor(...color); doc.setLineWidth(w); doc.line(x1, y1, x2, y2); };
  st.rect = (x, y, w, h, fill, stroke, r = 0) => { if (fill) doc.setFillColor(...fill); if (stroke) { doc.setDrawColor(...stroke); doc.setLineWidth(0.25); } r ? doc.roundedRect(x, y, w, h, r, r, fill && stroke ? 'FD' : fill ? 'F' : 'S') : doc.rect(x, y, w, h, fill && stroke ? 'FD' : fill ? 'F' : 'S'); };
  st.wrap = (str, width, size, weight = 'normal') => { st.font(weight, size); return doc.splitTextToSize(String(str), width); };
  st.para = (str, x, width, o = {}) => { const lines = st.wrap(str, width, o.s || 8.5, o.w); const lh = (o.s || 8.5) * pt2mm * (o.lh || 1.45); st.need(lines.length * lh); lines.forEach(l => { st.text(l, x, st.y, { s: o.s || 8.5, w: o.w, c: o.c || C.text2 }); st.y += lh; }); return lines.length * lh; };
  st.need = h => { if (st.y + h > PH - 24) st.newPage(); };
  st.newPage = () => { doc.addPage(); st.page++; st.header(); };
  // titre courant aligné à gauche : avec l'espacement des lettres, jsPDF calait mal l'alignement à droite (titre coupé, vu sur le rendu)
  st.header = () => { st.y = M + 2; if (st.logo) doc.addImage(st.logo, 'PNG', M, st.y - 1, 24, 24 * 228 / 900); st.caps(st.runningTitle, M + 30, st.y + 4, { s: 6.4 }); st.line(M, st.y + 9, PW - M, st.y + 9, C.line); st.y += 18; };
  return st;
}
const money = (h, v) => v == null ? '—' : h.fmt0(v);
const dateFr = d => d.toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' });

// ── Blocs ──────────────────────────────────────────────────────────────────────────────────────────────────
function kpiRow(st, w, h, per, x, y, width, tall = true){
  const H = tall ? 24 : 17, gap = 3, n = 5, tw = (width - gap * (n - 1)) / n;
  const cells = [['P90', money(h, w?.p90), 'haut de marché'], ['Médiane', money(h, w?.median), '€/m²', true], ['Moyenne', money(h, w?.mean), '€/m²'], ['P10', money(h, w?.p10), 'bas de marché'], ['Ventes', money(h, w?.count), w ? `surface méd. ${w.surf_median} m²` : '']];
  cells.forEach(([l, v, u, acc], i) => { const cx = x + i * (tw + gap);
    st.rect(cx, y, tw, H, acc ? [234, 241, 252] : C.tile, acc ? [180, 205, 240] : C.line, 1.4);
    st.caps(l, cx + 3.2, y + 5, { s: tall ? 5.8 : 5.4 }); st.text(v, cx + 3.2, y + (tall ? 14.5 : 11.5), { s: tall ? 15 : 11.5, w: 'bold', c: acc ? C.accent : C.navy });
    st.text(u + (tall && w && i < 4 ? ` · ${per}` : ''), cx + 3.2, y + (tall ? 20 : 15.2), { s: 5.8, c: C.grey }); });
  if (w && w.count < h.EFFECTIF_FAIBLE) st.text(`Effectif faible (${w.count} ventes) : chiffres indicatifs`, x, y + H + 4, { s: 6.5, c: C.gold });
  return H + (w && w.count < h.EFFECTIF_FAIBLE ? 6 : 0);
}
function evoRow(st, h, byYear, x, y, width, small = false){
  const cells = h.evoData(byYear), gap = 3, tw = (width - gap * (cells.length - 1)) / cells.length, H = small ? 13 : 16;
  cells.forEach((c, i) => { const cx = x + i * (tw + gap); st.rect(cx, y, tw, H, c.on ? [234, 241, 252] : null, c.on ? [180, 205, 240] : C.line, 1.2);
    st.caps(c.l, cx + tw / 2, y + 4.2, { s: 5.4, align: 'center' });
    st.text(h.evoTxt(c), cx + tw / 2, y + (small ? 9.3 : 10.5), { s: small ? 8.5 : 10, w: 'bold', align: 'center', c: c.v == null ? C.grey2 : c.v > 0 ? C.good : c.v < 0 ? C.bad : C.text });
    st.text(c.s, cx + tw / 2, y + H - 2.2, { s: 5.2, c: C.grey2, align: 'center' }); });
  return H;
}
function bandChart(st, h, pts, x, y, w, hh, title){
  const { doc } = st; st.caps(title, x, y + 2.5, { s: 5.8 });
  if (!pts || pts.length < 2) { st.text('Pas assez de périodes pour tracer une courbe.', x, y + 10, { s: 7, c: C.grey }); return hh; }
  const pl = 15, pr = 3, pt = 7, pb = 6, iw = w - pl - pr, ih = hh - pt - pb;
  const lo = Math.min(...pts.map(p => p.p10)), hi = Math.max(...pts.map(p => p.p90)); const raw = (hi - lo) / 4 || 100; const step = [100, 200, 250, 500, 1000, 2000, 2500, 5000, 10000].find(s => s >= raw) || 10000;
  const y0 = Math.floor(lo / step) * step, y1 = Math.ceil(hi / step) * step; const X = i => x + pl + i * (iw / (pts.length - 1)), Y = v => y + pt + ih - (v - y0) / (y1 - y0) * ih;
  for (let v = y0; v <= y1; v += step) { st.line(x + pl, Y(v), x + w - pr, Y(v), C.line2, 0.2); st.text(h.fmt0(v), x + pl - 1.5, Y(v) + 0.9, { s: 5.2, c: C.grey2, align: 'right' }); }
  const poly = (ptsXY, close) => { doc.moveTo(ptsXY[0][0], ptsXY[0][1]); ptsXY.slice(1).forEach(([a, b]) => doc.lineTo(a, b)); if (close) doc.close(); };
  doc.saveGraphicsState(); doc.setGState(new doc.GState({ opacity: 0.16 })); doc.setFillColor(...C.accent2);
  poly([...pts.map((p, i) => [X(i), Y(p.p90)]), ...pts.slice().reverse().map((p, j) => [X(pts.length - 1 - j), Y(p.p10)])], true); doc.fill(); doc.restoreGraphicsState();
  doc.setLineDashPattern([0.8, 0.8], 0); doc.setDrawColor(127, 168, 222); doc.setLineWidth(0.25);
  for (const k of ['p10', 'p90']) { poly(pts.map((p, i) => [X(i), Y(p[k])])); doc.stroke(); }
  doc.setLineDashPattern([], 0); doc.setDrawColor(...C.accent2); doc.setLineWidth(0.6); doc.setLineJoin('round');
  poly(pts.map((p, i) => [X(i), Y(p.median)])); doc.stroke();
  const last = pts[pts.length - 1]; doc.setFillColor(...C.accent2); doc.circle(X(pts.length - 1), Y(last.median), 0.9, 'F');
  st.text(h.fmt0(last.median), X(pts.length - 1) - 1.5, Y(last.median) - 2, { s: 6, w: 'bold', c: C.navy, align: 'right' });
  const stp = Math.ceil(pts.length / 8); pts.forEach((p, i) => { if (i % stp === 0 || i === pts.length - 1) st.text(h.axisLabel(p.k), X(i), y + hh - 1, { s: 5.2, c: C.grey2, align: i === pts.length - 1 ? 'right' : i === 0 ? 'left' : 'center' }); });
  // légende
  st.line(x + w - 36, y + 1.5, x + w - 32, y + 1.5, C.accent2, 0.6); st.text('Médiane', x + w - 31, y + 2.5, { s: 5.2, c: C.grey });
  doc.setFillColor(214, 228, 247); doc.rect(x + w - 17, y - 0.2, 4, 2.4, 'F'); st.text('P10–P90', x + w - 12, y + 2.5, { s: 5.2, c: C.grey });
  return hh;
}
function barChart(st, h, pts, x, y, w, hh, title){
  const { doc } = st; st.caps(title, x, y + 2.5, { s: 5.8 }); if (!pts || !pts.length) return hh;
  const pl = 15, pr = 3, pt = 6, pb = 6, iw = w - pl - pr, ih = hh - pt - pb, max = Math.max(...pts.map(p => p.count)) || 1, bw = iw / pts.length, gap = Math.min(0.6, bw * .25);
  st.line(x + pl, y + pt + ih, x + w - pr, y + pt + ih, C.line, 0.25); st.text(h.fmt0(max), x + pl - 1.5, y + pt + 2, { s: 5.2, c: C.grey2, align: 'right' });
  doc.setFillColor(196, 201, 212); pts.forEach((p, i) => { const bh = p.count / max * ih; doc.rect(x + pl + i * bw + gap / 2, y + pt + ih - bh, Math.max(0.3, bw - gap), bh, 'F'); });
  const stp = Math.ceil(pts.length / 8); pts.forEach((p, i) => { if (i % stp === 0 || i === pts.length - 1) st.text(h.axisLabel(p.k), x + pl + i * bw + bw / 2, y + hh - 1, { s: 5.2, c: C.grey2, align: 'center' }); });
  return hh;
}
function table(st, cols, rows, x, width, o = {}){
  // cols : [{l, w (proportion), align, help}], rows : tableau de tableaux de {t, w:'bold', c}
  const { doc } = st; const tot = cols.reduce((a, c) => a + c.w, 0); const xs = []; let cx = x; cols.forEach(c => { xs.push(cx); cx += c.w / tot * width; });
  const rh = o.rh || 6.2, head = 6.5;
  const drawHead = () => { st.need(head + rh); cols.forEach((c, i) => st.caps(c.l, c.align === 'right' ? xs[i] + c.w / tot * width - 1.5 : xs[i] + 1.5, st.y + 4.3, { s: 5.6, align: c.align || 'left' })); st.line(x, st.y + head, x + width, st.y + head, C.grey2, 0.3); st.y += head; };
  drawHead();
  rows.forEach((r, ri) => { if (st.y + rh > PH - 24) { st.newPage(); drawHead(); }
    if (r.fill) st.rect(x, st.y, width, rh, r.fill, null);
    r.cells.forEach((cell, i) => { const c = cols[i]; const v = typeof cell === 'object' && cell !== null ? cell : { t: cell }; st.text(v.t ?? '—', c.align === 'right' ? xs[i] + c.w / tot * width - 1.5 : xs[i] + 1.5, st.y + rh - 1.9, { s: o.s || 7.2, w: v.w || 'normal', c: v.c || C.text, align: c.align || 'left' }); });
    st.line(x, st.y + rh, x + width, st.y + rh, C.line2, 0.2); st.y += rh; });
}

// ── Document ──────────────────────────────────────────────────────────────────────────────────────────────
export async function exportPdf(ctx){
  const { META, S, item, et, typos, helpers: h, address, crumbs, niveauLabel, periodeLabel, granLabel } = ctx;
  const [_, logoImg, map] = await Promise.all([loadScript(JSPDF_URL), loadImage(h.logoUrl), renderMap(ctx, 1600, 900)]);
  const { jsPDF } = window.jspdf;
  const doc = new jsPDF({ unit: 'mm', format: 'a4', compress: true });
  doc.addFileToVFS('Inter-Regular.ttf', regular); doc.addFont('Inter-Regular.ttf', 'Inter', 'normal');
  doc.addFileToVFS('Inter-SemiBold.ttf', semibold); doc.addFont('Inter-SemiBold.ttf', 'Inter', 'bold');
  const st = mk(doc); st.logo = logoImg; st.runningTitle = `Étude de marché résidentiel · ${item.nom} · ${S.type}s`;
  const now = new Date(), w = h.windowOf(et), addrIn = address && address.props;
  const typoLabel = typos.filter(t => t.on).map(t => `${t.id} ${t.surfMin}–${t.surfMax} m²`).join(' · ');

  // ── Page 1 : couverture ────────────────────────────────────────────────────────────────────────
  doc.addImage(logoImg, 'PNG', M, 16, 46, 46 * 228 / 900);
  st.caps('Étude de marché résidentiel', PW - M, 20, { align: 'right', s: 7, ls: 0.8 });
  st.text(dateFr(now), PW - M, 26, { s: 8, c: C.grey, align: 'right' });
  st.line(M, 34, PW - M, 34, C.green, 0.6);
  st.caps(`${niveauLabel} · ${S.type}s · ${periodeLabel}${w ? ` (${w.from} → ${w.to})` : ''}`, M, 48, { s: 7.2, ls: 0.6, c: C.green });
  const titleLines = st.wrap(item.nom, CW, 27, 'bold'); let y = 60; titleLines.forEach(l => { st.text(l, M, y, { s: 27, w: 'bold', c: C.navy }); y += 11; });
  const sub = crumbs.join('  ·  '); const subLines = st.wrap(sub, CW, 9).slice(0, 3); subLines.forEach(l => { st.text(l, M, y, { s: 9, c: C.grey }); y += 5; });
  y += 4;
  // carte
  const mapW = CW, mapH = mapW * 900 / 1600; doc.addImage(map.data, 'JPEG', M, y, mapW, mapH); st.rect(M, y, mapW, mapH, null, C.line);
  const cap = address ? `Localisation de l'adresse (point rouge) et découpage par ${niveauLabel.toLowerCase()} ; la zone étudiée est soulignée.` : `Découpage par ${niveauLabel.toLowerCase()} : polygones officiels (quartiers administratifs de Paris, IRIS de Boulogne-Billancourt) ; la zone étudiée est soulignée.`;
  st.text(cap + (map.missing ? ` Fond incomplet (${map.missing}/${map.total} tuiles).` : ''), M, y + mapH + 4.5, { s: 6.6, c: C.grey, maxWidth: CW }); y += mapH + 12;
  if (address) {
    st.rect(M, y, CW, 22, C.tile, C.line, 1.6);
    st.caps('Adresse localisée', M + 5, y + 5.5, { s: 5.8 }); st.text(address.label, M + 5, y + 11.5, { s: 11, w: 'bold', c: C.navy });
    const p = address.props; const rows = !p ? [['Périmètre', 'Hors des communes couvertes']] : p.commune === '75056' ? [['Quartier', p.nom], ['Arrondissement', `Paris ${p.arr === 1 ? '1er' : p.arr + 'e'}`], ['Secteur', ctx.secteurNom(p.secteur)], ['Zone d’encadrement', `Zone ${String(p.zone).slice(1)}`]] : [['Quartier', p.nom], ['Commune', 'Boulogne-Billancourt']];
    const cw = (CW - 10) / 4; rows.forEach(([l, v], i) => { st.caps(l, M + 5 + i * cw, y + 17, { s: 5.4 }); st.text(v, M + 5 + i * cw, y + 20.5, { s: 7.6, w: 'bold', c: C.text, maxWidth: cw - 3 }); });
    y += 28;
  }
  // chiffres clés
  st.caps('Chiffres clés · ' + (S.global ? 'toutes surfaces' : 'toutes surfaces (référence)'), M, y + 2, { s: 6.2 }); st.line(M, y + 4, PW - M, y + 4, C.line);
  y += 8; kpiRow(st, w, h, periodeLabel, M, y, CW, true); y += 24 + 4;
  if (y + 16 < PH - 24) evoRow(st, h, et.by_year, M, y, CW, true);

  // ── Pages suivantes : marché global (si affiché), typologies ──────────────────────────────────
  const section = (title, badge, stat) => {
    const ww = h.windowOf(stat); st.need(112);   // hauteur d'une section : 15 + 27 + 20 + 50 = 112 mm → deux par page
    st.caps(badge, M, st.y + 2, { s: 6, c: C.green });
    st.text(`${ww ? h.fmt0(ww.count) + ' ventes · ' : ''}${periodeLabel}${ww ? ` · ${ww.from} → ${ww.to}` : ''}`, PW - M, st.y + 2, { s: 7, c: C.grey, align: 'right' });
    st.text(st.wrap(title, CW, 13, 'bold')[0], M, st.y + 8.5, { s: 13, w: 'bold', c: C.navy });   // une ligne : le titre ne chevauche plus le compte à droite (vu sur le rendu)
    st.line(M, st.y + 12, PW - M, st.y + 12, C.line); st.y += 15;
    st.y += kpiRow(st, ww, h, periodeLabel, M, st.y, CW, true) + 3;
    st.y += evoRow(st, h, stat.by_year, M, st.y, CW) + 4;
    const pts = h.seriesFor(stat); st.need(50);
    bandChart(st, h, pts, M, st.y, 116, 42, `Prix au m² · ${granLabel}`);
    st.y += barChart(st, h, pts, M + 122, st.y, CW - 122, 42, `Volume · ${granLabel}`) + 8;
  };
  st.newPage();
  // ── Valorisation de l'immeuble (lot 6) : page dédiée juste après la couverture ───────────────
  const V = ctx.valo;
  if (V && V.lots > 0 && address) {
    st.caps('Valorisation', M, st.y + 2, { s: 6, c: C.green }); st.text(`Positionnement P${V.pos} · référence 12 derniers mois`, PW - M, st.y + 2, { s: 7, c: C.grey, align: 'right' });
    st.text(st.wrap(`Valorisation de l'immeuble · ${address.label}`, CW, 13, 'bold')[0], M, st.y + 8.5, { s: 13, w: 'bold', c: C.navy }); st.line(M, st.y + 12, PW - M, st.y + 12, C.line); st.y += 16;
    const tiles = [['Valeur estimée', h.fmtEur(V.valeur), `${V.lots} lot${V.lots > 1 ? 's' : ''} · ${h.fmt0(V.surfTot)} m² · P${V.pos}`, true], ['Fourchette basse', h.fmtEur(V.valeurBas), 'au P10 de chaque ligne'], ['Fourchette haute', h.fmtEur(V.valeurHaut), 'au P90 de chaque ligne'], ['€/m² moyen retenu', h.fmt0(V.ppm2Moyen), 'pondéré par les surfaces']];
    const tw = (CW - 9) / 4; tiles.forEach(([l, v, u, acc], i) => { const cx = M + i * (tw + 3); st.rect(cx, st.y, tw, 24, acc ? [234, 241, 252] : C.tile, acc ? [180, 205, 240] : C.line, 1.4);
      st.caps(l, cx + 3.2, st.y + 5, { s: 5.6 }); st.text(v, cx + 3.2, st.y + 14.5, { s: v.length > 12 ? 11 : 13, w: 'bold', c: acc ? C.accent : C.navy }); st.text(u, cx + 3.2, st.y + 20, { s: 5.6, c: C.grey }); });
    st.y += 30;
    const from = V.rows.find(r => r.ref)?.ref;
    st.caps(`Lots de l'immeuble · appartements · référence ${from ? `${h.fmtMois(from.ymFrom)} → ${h.fmtMois(from.ymTo)}` : ''}`, M, st.y + 2, { s: 6.2 }); st.line(M, st.y + 4, PW - M, st.y + 4, C.line); st.y += 7;
    // libellé court d'échantillon : le nom complet du secteur débordait sur la colonne voisine (vu sur le rendu)
    const ech = r => !r.ref ? 'surface manquante' : `${r.ref.n} v. · ${r.ref.niveau === 'quartier' ? 'quartier' : r.ref.niveau === 'arrondissement' ? `arr. ${r.ref.id === '1' ? '1er' : r.ref.id + 'e'}` : r.ref.niveau === 'secteur' ? `secteur ${/^\d+$/.test(r.ref.id) ? 'S' + r.ref.id : r.ref.id}` : 'commune'}${r.ref.suffisant ? '' : ' · insuff.'}`;
    table(st, [{ l: 'Typologie', w: 1 }, { l: 'Lots', w: .55, align: 'right' }, { l: 'Surface', w: .8, align: 'right' }, { l: 'Ajust.', w: .7, align: 'right' }, { l: 'P10', w: .85, align: 'right' }, { l: 'Retenu', w: .95, align: 'right' }, { l: 'P90', w: .85, align: 'right' }, { l: 'Échantillon', w: 1.9 }, { l: 'Valeur / lot', w: 1.25, align: 'right' }, { l: 'Valeur', w: 1.35, align: 'right' }],
      [...V.rows.filter(r => r.lots > 0).map(r => ({ cells: [{ t: r.id, w: 'bold' }, String(r.lots), `${r.surf} m²`, `${r.adj > 0 ? '+' : ''}${r.adj} %`, h.fmt0(r.ppm2Bas), { t: h.fmt0(r.ppm2), w: 'bold' }, h.fmt0(r.ppm2Haut), { t: ech(r), c: r.ref && !r.ref.suffisant ? C.gold : C.text2 }, h.fmtEur(r.valeurLot), { t: h.fmtEur(r.valeur), w: 'bold' }] })),
       { fill: [246, 248, 251], cells: [{ t: 'Total', w: 'bold' }, { t: String(V.lots), w: 'bold' }, { t: `${h.fmt0(V.surfTot)} m²`, w: 'bold' }, '', h.fmt0(V.valeurBas && V.surfTot ? V.valeurBas / V.surfTot : null), { t: h.fmt0(V.ppm2Moyen), w: 'bold' }, h.fmt0(V.valeurHaut && V.surfTot ? V.valeurHaut / V.surfTot : null), 'moy. pondérées', '', { t: h.fmtEur(V.valeur), w: 'bold' }] }], M, CW, { s: 6.8, rh: 6 });
    st.y += 6;
    // ── Loyers et rentabilité brute (lot 8) ──────────────────────────────────────────────────
    const RT = V.rent;
    if (RT && RT.loyerAnnuel > 0) {
      const srcTxt = RT.paris ? `encadrement ${RT.src.annee} (applicable ${RT.src.application}) · loyer de référence majoré, hors charges · ${RT.meuble ? 'meublé' : 'vide'} · immeuble ${RT.epoque.toLowerCase().replace('apres', 'après')}` : `carte des loyers ${RT.src.edition} · loyers d'annonce charges comprises · ${RT.meuble ? 'meublé' : 'vide'}`;
      st.need(64); st.caps('Loyers et rentabilité brute', M, st.y + 2, { s: 5.8 }); st.line(M, st.y + 4, PW - M, st.y + 4, C.line); st.text(srcTxt, M, st.y + 7.5, { s: 6.2, c: C.grey, maxWidth: CW }); st.y += 11;
      const tl = [['Rentabilité brute', h.fmtPct2(RT.rendement), `${h.fmtEur(RT.loyerAnnuel)} / an sur ${h.fmtEur(RT.valeur)} (P${V.pos})`, true], ['Loyers mensuels', h.fmtEur(RT.loyerMensuel), 'ensemble des lots'], ['Sur valeur haute (P90)', h.fmtPct2(RT.rendementBas), 'rendement le plus bas'], ['Sur valeur basse (P10)', h.fmtPct2(RT.rendementHaut), 'rendement le plus haut']];
      const tw = (CW - 9) / 4; tl.forEach(([l, v, u, acc], i) => { const cx = M + i * (tw + 3); st.rect(cx, st.y, tw, 22, acc ? [234, 241, 252] : C.tile, acc ? [180, 205, 240] : C.line, 1.4); st.caps(l, cx + 3, st.y + 5, { s: 5.4 }); st.text(v, cx + 3, st.y + 13.5, { s: 12, w: 'bold', c: acc ? C.accent : C.navy }); st.text(u, cx + 3, st.y + 19, { s: 5.4, c: C.grey, maxWidth: tw - 5 }); });
      st.y += 27;
      table(st, [{ l: 'Typologie', w: 1.1 }, { l: 'Lots', w: .55, align: 'right' }, { l: 'Pièces', w: .75, align: 'right' }, { l: RT.paris ? 'Majoré €/m²' : 'Loyer €/m²', w: 1.25, align: 'right' }, { l: RT.paris ? 'Réf. · minoré' : 'Bas → haut', w: 1.35, align: 'right' }, { l: 'Loyer / lot', w: 1.25, align: 'right' }, { l: 'Loyer annuel', w: 1.35, align: 'right' }, { l: 'Rentab.', w: 1, align: 'right' }],
        [...RT.rows.filter(r => r.lots > 0).map(r => ({ cells: [{ t: r.id, w: 'bold' }, String(r.lots), r.pieces === 4 ? '4 et +' : String(r.pieces), r.ppm2 != null ? { t: r.ppm2.toFixed(1).replace('.', ','), w: 'bold' } : { t: r.motif || '—', c: C.gold }, r.ppm2 == null ? '' : RT.paris ? `${r.ref.toFixed(1).replace('.', ',')} · ${r.mino.toFixed(1).replace('.', ',')}` : `${r.bas.toFixed(1).replace('.', ',')} → ${r.haut.toFixed(1).replace('.', ',')}`, h.fmtEur(r.loyerLot), h.fmtEur(r.loyerAnnuel), { t: h.fmtPct2(r.rendement), w: 'bold' }] })),
         { fill: [246, 248, 251], cells: [{ t: 'Total', w: 'bold' }, '', '', '', '', h.fmtEur(RT.loyerMensuel), { t: h.fmtEur(RT.loyerAnnuel), w: 'bold' }, { t: h.fmtPct2(RT.rendement), w: 'bold' }] }], M, CW, { s: 6.8, rh: 6 });
      st.y += 5;
      st.para(`${h.HELP[RT.paris ? 'loy_paris' : 'loy_carte'][1]} ${h.HELP.rendement[1]}`, M, CW, { s: 7 }); st.y += 2;
    }
    st.para(`Méthode. ${h.HELP.valo_ref[1]} ${h.HELP.valo_ech[1]} ${h.HELP.valo_pos[1]} ${h.HELP.valo_tot[1]} Cette valorisation est une lecture statistique des ventes enregistrées (DVF), pas une expertise : elle ne tient compte ni de l'état du bâti, ni des charges, ni des situations locatives.`, M, CW, { s: 7.6 });
    st.newPage();
  }
  // ── Perspectives (lot 7) : scénarios conditionnels, sensibilité, rétrospectif ─────────────────
  const PP = ctx.persp;
  if (PP) {
    const { sc, sens, retro, cal, ref, params, macro } = PP; const o = sc.central.origine; const Mx = macro.series;
    const tx = h.lastOf(Mx.taux_credit.obs), oat = h.lastOf(Mx.oat_10.obs), ip = h.lastOf(Mx.ipch.obs), pm = h.lastOf(Mx.permis_paris.obs), loy = h.lastOf(Mx.loyers_paris.obs);
    st.caps('Perspectives', M, st.y + 2, { s: 6, c: C.green }); st.text(`scénarios à 3, 5 et 10 ans depuis ${h.moisLabel(o.q)}`, PW - M, st.y + 2, { s: 7, c: C.grey, align: 'right' });
    st.text(st.wrap(`Perspectives · ${item.nom} · ${S.type}s`, CW, 13, 'bold')[0], M, st.y + 8.5, { s: 13, w: 'bold', c: C.navy }); st.line(M, st.y + 12, PW - M, st.y + 12, C.line); st.y += 16;
    // hypothèses
    const hyps = [['Taux de crédit visé', `${params.tauxH.toFixed(2).replace('.', ',')} %`, `actuel ${tx.v.toFixed(2).replace('.', ',')} % (${h.moisLabel(tx.k)}) · atteint en ${params.horizonTaux / 4} an${params.horizonTaux > 4 ? 's' : ''}`], ['Inflation', `${params.inflation.toFixed(1).replace('.', ',')} %/an`, `IPCH ${h.fmtPctS(h.perAn(Mx.ipch.obs, ip.k, 12) * 100)} sur 12 mois (${h.moisLabel(ip.k)})`], ['Revenus réels', `${params.revenus.toFixed(1).replace('.', ',')} %/an`, `au-delà de l'inflation`], ['Prime locale', `${params.prime.toFixed(1).replace('.', ',')} %/an`, PP.tl != null ? `tendance 10 ans observée ${h.fmtPctS(PP.tl)}/an (non extrapolée)` : 'non calculable'], ['Vitesse d’ajustement', `${Math.round(params.lam * 100)} %/trim`, `écart prix / cible actuel ${h.fmtPctS(cal.ecartCourant * 100)}`]];
    const tw = (CW - 12) / 5; hyps.forEach(([l, v, u], i) => { const cx = M + i * (tw + 3); st.rect(cx, st.y, tw, 22, C.tile, C.line, 1.4); st.caps(l, cx + 2.5, st.y + 5, { s: 5.2 }); st.text(v, cx + 2.5, st.y + 12.5, { s: 11, w: 'bold', c: C.navy }); st.wrap(u, tw - 5, 5).slice(0, 2).forEach((ln, j) => st.text(ln, cx + 2.5, st.y + 16.5 + j * 2.6, { s: 5, c: C.grey })); });
    st.y += 28;
    // tableau des scénarios
    st.caps(`Valeur projetée · zone ${ref.median ? h.fmt0(ref.median) + ' €/m² (12 mois)' : ''}${PP.valoValeur ? ` · immeuble ${h.fmtEur(PP.valoValeur)}` : ''}`, M, st.y + 2, { s: 5.8 }); st.text(`Départ Paris ${h.fmt0(o.prix)} €/m²${o.pont ? ' · DVF prolongé par l’indice Notaires-INSEE' : ''}`, PW - M, st.y + 2, { s: 6, c: C.grey, align: 'right' }); st.line(M, st.y + 4, PW - M, st.y + 4, C.line); st.y += 7;
    const cellTxt = (pj, n) => { const r = pj.at(n).ratio; return `${h.fmtPctS((r - 1) * 100)}${ref.median ? `  ·  ${h.fmt0(ref.median * r)} €/m²` : ''}${PP.valoValeur ? `  ·  ${h.fmtEur(PP.valoValeur * r)}` : ''}`; };
    table(st, [{ l: 'Horizon', w: .9 }, { l: 'Bas (taux +1, infl. −0,5)', w: 2.2, align: 'right' }, { l: 'Central', w: 2.2, align: 'right' }, { l: 'Haut (taux −1, infl. +0,5)', w: 2.2, align: 'right' }],
      [[12, '3 ans'], [20, '5 ans'], [40, '10 ans']].map(([n, l]) => ({ cells: [{ t: `${l} · ${h.moisLabel(sc.central.at(n).q)}`, w: 'bold' }, { t: cellTxt(sc.bas, n), c: C.bad }, { t: cellTxt(sc.central, n), w: 'bold', c: C.accent }, { t: cellTxt(sc.haut, n), c: C.good }] })), M, CW, { s: 7, rh: 7 });
    st.y += 5;
    // trajectoires (vectoriel)
    const cx0 = M, cy0 = st.y, cw = 108, ch = 46; st.caps(`Trajectoire Paris · base 100 au ${h.moisLabel(o.q)}`, cx0, cy0 + 2.5, { s: 5.8 });
    const pl = 12, pt = 6, pb = 6, iw = cw - pl - 9, ih = ch - pt - pb; const all = [...sc.bas.path, ...sc.central.path, ...sc.haut.path].map(p => p.ratio * 100); const lo = Math.floor(Math.min(...all) / 10) * 10, hi = Math.ceil(Math.max(...all) / 10) * 10;
    const X = t => cx0 + pl + t / 40 * iw, Y = v => cy0 + pt + ih - (v - lo) / (hi - lo) * ih;
    for (let v = lo; v <= hi; v += 10) { st.line(cx0 + pl, Y(v), cx0 + cw - 3, Y(v), C.line2, .2); st.text(String(v), cx0 + pl - 1.5, Y(v) + .9, { s: 5, c: C.grey2, align: 'right' }); }
    [[sc.bas, C.bad], [sc.central, C.accent2], [sc.haut, C.good]].forEach(([pj, col]) => { doc.setDrawColor(...col); doc.setLineWidth(pj === sc.central ? .6 : .35); doc.moveTo(X(0), Y(100)); pj.path.slice(1).forEach(p => doc.lineTo(X(p.t), Y(p.ratio * 100))); doc.stroke(); st.text(String(Math.round(pj.at(40).ratio * 100)), X(40) + 1.2, Y(pj.at(40).ratio * 100) + .8, { s: 5.2, w: 'bold', c: col }); });
    [0, 12, 20, 40].forEach(t => st.text(sc.central.at(t).q.slice(0, 4), X(t), cy0 + ch - 1, { s: 5, c: C.grey2, align: t === 40 ? 'right' : t === 0 ? 'left' : 'center' }));
    // sensibilité (à droite)
    const sx = M + cw + 8, sw = CW - cw - 8; st.caps('Sensibilité à 5 ans', sx, cy0 + 2.5, { s: 5.8 });
    const noms = { tauxH: 'Taux', inflation: 'Inflation', revenus: 'Revenus réels', prime: 'Prime locale', lam: 'Vitesse' };
    sens.forEach((x, i) => { const yy = cy0 + 7 + i * 3.9; const lab = `${noms[x.k]} ${x.k === 'lam' ? `${x.d > 0 ? '+' : ''}${Math.round(x.d * 100)} pts` : `${x.d > 0 ? '+' : ''}${x.d} pt`}`; st.text(lab, sx, yy + .8, { s: 5.6, c: C.text2 });
      const mid = sx + 26 + (sw - 26 - 12) / 2, half = (sw - 26 - 12) / 2, w = Math.min(half, Math.abs(x.effet) * 100 / 12 * half); st.rect(x.effet >= 0 ? mid : mid - w, yy - 1.4, w, 2.4, x.effet >= 0 ? [4, 120, 87] : [185, 28, 28], null, .6); st.text(h.fmtPctS(x.effet * 100), sx + sw, yy + .8, { s: 5.6, w: 'bold', c: x.effet >= 0 ? C.good : C.bad, align: 'right' }); });
    st.y = cy0 + ch + 6;
    // rétrospectif
    st.caps(`Rétrospectif · modèle calé ≤ ${retro.trainUntil}, simulé sur ${retro.nTest} trimestres avec les taux et l’inflation réels`, M, st.y + 2, { s: 5.8 }); st.line(M, st.y + 4, PW - M, st.y + 4, C.line); st.y += 8;
    const rt = [['Erreur moyenne', `${(retro.errMoy * 100).toFixed(1).replace('.', ',')} %`], ['Erreur maximale', `${(retro.errMax * 100).toFixed(1).replace('.', ',')} %`], ['Fin 2025, simulé / réel', h.fmtPctS((retro.points.find(p => p.q === '2025-Q4')?.sim / retro.points.find(p => p.q === '2025-Q4')?.obs - 1) * 100)]];
    const rw = (CW - 6) / 3; rt.forEach(([l, v], i) => { const cx = M + i * (rw + 3); st.rect(cx, st.y, rw, 14, C.tile, C.line, 1.2); st.caps(l, cx + 3, st.y + 4.5, { s: 5.2 }); st.text(v, cx + 3, st.y + 11, { s: 10, w: 'bold', c: C.navy }); });
    st.y += 18;
    st.para(`Méthode. ${h.HELP.persp_modele[1]} ${h.HELP.persp_scen[1]} ${h.HELP.persp_retro[1]} ${h.HELP.persp_prime[1]} Sources : BCE (taux des crédits à l'habitat ${h.moisLabel(tx.k)}, OAT 10 ans ${oat.v.toFixed(2).replace('.', ',')} % en ${h.moisLabel(oat.k)}, IPCH ${h.moisLabel(ip.k)}), INSEE (indice Notaires-INSEE Paris, indice des loyers ${h.moisLabel(loy.k)}, logements autorisés à Paris ${h.fmt0(pm.v)} sur 12 mois en ${h.moisLabel(pm.k)}). Scénarios conditionnels aux hypothèses affichées : ce ne sont pas des prévisions.`, M, CW, { s: 7.2 });
    st.newPage();
  }
  if (S.global) section(`${item.nom} · ${S.type}s · toutes surfaces`, 'Marché global', et);
  typos.filter(t => t.on && et.by_typo?.[t.id]).forEach(t => section(`${t.id} · ${t.surfMin}–${t.surfMax} m²`, 'Typologie', et.by_typo[t.id]));

  // ── Tableaux ──────────────────────────────────────────────────────────────────────────────────
  const bt = et.by_typo || {}, tIds = typos.map(t => t.id).filter(id => bt[id]);
  if (tIds.length) {
    st.need(40); st.caps('Typologies', M, st.y + 2, { s: 6, c: C.green }); st.text(`Répartition et prix par surface · ${S.type}s`, M, st.y + 8.5, { s: 13, w: 'bold', c: C.navy });
    st.text(`part sur ${META.meta.periode} · prix sur ${periodeLabel.toLowerCase()}`, PW - M, st.y + 8.5, { s: 7.5, c: C.grey, align: 'right' }); st.line(M, st.y + 12, PW - M, st.y + 12, C.line); st.y += 15;
    const evo = (by, n) => { const ly = META.meta.last_year, a = by?.[String(ly)]?.median, b = by?.[String(ly - n)]?.median; return (a && b) ? (a / b - 1) * 100 : null; };
    const pc = v => ({ t: h.fmtPct(v), c: v == null ? C.grey2 : v > 0 ? C.good : v < 0 ? C.bad : C.text });
    table(st, [{ l: 'Typologie', w: 2.4 }, { l: 'Part du marché', w: 1.5, align: 'right' }, { l: 'Ventes', w: 1.1, align: 'right' }, { l: 'P10', w: 1.1, align: 'right' }, { l: 'Médiane', w: 1.2, align: 'right' }, { l: 'P90', w: 1.1, align: 'right' }, { l: '1 an', w: 1, align: 'right' }, { l: '5 ans', w: 1, align: 'right' }],
      tIds.map(id => { const t = bt[id], ww = t.windows?.[S.per], td = typos.find(x => x.id === id), top = id === bt._top_typo;
        return { fill: top ? [246, 248, 251] : null, cells: [{ t: `${id}  ${td.surfMin}–${td.surfMax} m²${top ? '  · dominante' : ''}`, w: 'bold' }, `${t.share.toFixed(1).replace('.', ',')} %`, money(h, ww?.count), money(h, ww?.p10), { t: money(h, ww?.median), w: 'bold' }, money(h, ww?.p90), pc(evo(t.by_year, 1)), pc(evo(t.by_year, 5))] }; }), M, CW);
    st.y += 6;
  }
  const by = et.by_year || {}, years = Object.keys(by).sort();
  st.need(40); st.caps('Tableau', M, st.y + 2, { s: 6, c: C.green }); st.text(`Statistiques annuelles · ${item.nom} · ${S.type}s · toutes surfaces`, M, st.y + 8.5, { s: 13, w: 'bold', c: C.navy }); st.line(M, st.y + 12, PW - M, st.y + 12, C.line); st.y += 15;
  table(st, [{ l: 'Année', w: 1 }, { l: 'Ventes', w: 1, align: 'right' }, { l: 'P10', w: 1, align: 'right' }, { l: 'Q1', w: 1, align: 'right' }, { l: 'Médiane', w: 1.1, align: 'right' }, { l: 'Q3', w: 1, align: 'right' }, { l: 'P90', w: 1, align: 'right' }, { l: 'Moyenne', w: 1, align: 'right' }, { l: 'Surf. moy.', w: 1, align: 'right' }, { l: 'Méd. vs n−1', w: 1.2, align: 'right' }],
    years.map((yy, i) => { const v = by[yy], prev = by[years[i - 1]], e = prev ? (v.median / prev.median - 1) * 100 : null;
      return { cells: [{ t: yy, w: 'bold' }, h.fmt0(v.count), h.fmt0(v.p10), h.fmt0(v.q1), { t: h.fmt0(v.median), w: 'bold' }, h.fmt0(v.q3), h.fmt0(v.p90), h.fmt0(v.mean), `${v.surf_mean} m²`, { t: h.fmtPct(e), c: e == null ? C.grey2 : e > 0 ? C.good : e < 0 ? C.bad : C.text }] }; }), M, CW, { rh: 5.6, s: 7 });

  // ── Méthode ───────────────────────────────────────────────────────────────────────────────────
  st.newPage(); st.caps('Méthode', M, st.y + 2, { s: 6, c: C.green }); st.text('Méthode de calcul et sources', M, st.y + 8.5, { s: 13, w: 'bold', c: C.navy }); st.line(M, st.y + 12, PW - M, st.y + 12, C.line); st.y += 17;
  st.para(`Périmètre de l'étude : ${item.nom} (${niveauLabel.toLowerCase()}), ${S.type.toLowerCase()}s, ${periodeLabel.toLowerCase()}${w ? ` (${w.from} → ${w.to})` : ''}, ${h.fmt0(ctx.nVentes)} ventes retenues sur l'ensemble de l'historique ${META.meta.periode}. Typologies : ${typos.map(t => `${t.id} ${t.surfMin}–${t.surfMax} m²`).join(', ')}${typoLabel ? ` (détaillées : ${typoLabel})` : ''}. Étude générée le ${dateFr(now)} depuis ${location.origin}${location.pathname}, calculs effectués dans le navigateur sur les ventes déchiffrées.`, M, CW, { s: 8.2 }); st.y += 3;
  st.para(`Données : « Demandes de valeurs foncières » (DGFiP) publiées par Etalab (geo-dvf et opendatarchives), millésimes ${META.meta.periode}, dernière mise à jour ${new Date(META.meta.generated_at).toLocaleDateString('fr-FR')}. Sont retenues les ventes (hors VEFA) d'un logement unique — appartement ou maison, dépendances tolérées, local professionnel ou second logement exclus — dont le prix au m² est compris entre 1 000 et 40 000 € et la surface entre 9 et 400 m². Surface Carrez de l'acte si elle est cohérente avec la surface bâtie (écart ≤ 30 %), sinon surface bâtie. Chaque vente est rattachée par ses coordonnées au polygone officiel de son quartier (80 quartiers administratifs de la Ville de Paris ; 10 quartiers de Boulogne-Billancourt constitués des IRIS de l'INSEE / IGN). Les ventes sans coordonnées ne sont comptées dans aucun niveau. Zones d'encadrement des loyers : découpage officiel de la Ville de Paris. Fond de carte et géocodage : IGN Géoplateforme. Licence Ouverte 2.0.`, M, CW, { s: 8.2 }); st.y += 4;
  st.caps('Définition des indicateurs', M, st.y + 2, { s: 6.2 }); st.line(M, st.y + 4, PW - M, st.y + 4, C.line); st.y += 9;
  const colW = (CW - 8) / 2; let col = 0, yTop = st.y, yMax = st.y;
  for (const k of Object.keys(h.HELP)) { const [t, txt, f] = h.HELP[k]; const lines = st.wrap(txt, colW, 7.2); const bh = 4 + lines.length * 7.2 * pt2mm * 1.35 + 3 + 2.5;
    if (st.y + bh > PH - 24) { if (col === 0) { col = 1; yMax = Math.max(yMax, st.y); st.y = yTop; } else { st.newPage(); col = 0; yTop = st.y; yMax = st.y; } }
    const x = M + col * (colW + 8); st.text(t, x, st.y + 3, { s: 7.8, w: 'bold', c: C.navy }); st.text(f, x + colW, st.y + 3, { s: 6, c: C.grey, align: 'right' }); st.y += 4 + 2.5;
    lines.forEach(l => { st.text(l, x, st.y, { s: 7.2, c: C.text2 }); st.y += 7.2 * pt2mm * 1.35; }); st.y += 3; }

  // ── Pieds de page ─────────────────────────────────────────────────────────────────────────────
  const n = doc.getNumberOfPages();
  for (let i = 1; i <= n; i++) { doc.setPage(i); st.line(M, PH - 16, PW - M, PH - 16, C.green, 0.4);
    st.text('Jadero · Data Marché Résidentiel', M, PH - 11.5, { s: 6.6, w: 'bold', c: C.text2 });
    st.text(`Source : DVF DGFiP / Etalab ${META.meta.periode} · IGN Géoplateforme · document confidentiel · généré le ${now.toLocaleDateString('fr-FR')}`, M, PH - 7.5, { s: 5.8, c: C.grey });
    st.text(`${i} / ${n}`, PW - M, PH - 11.5, { s: 6.6, c: C.grey, align: 'right' }); }
  const slug = s => s.normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^\w]+/g, '_').replace(/^_|_$/g, '');
  doc.save(`Jadero_Etude_${slug(item.nom)}_${S.type}_${S.per === 'all' ? 'historique' : S.per + 'ans'}_${now.toISOString().slice(0, 10)}.pdf`);
  return { pages: n, map };
}

// rayon.js — visuel « marché autour de l'immeuble » (lot 10) : barres de médiane, moustaches P10–P90 par année, lignes
// d'acquisition et de sortie. Reproduit le visuel du script outils_marche_dvf.py de Jadero (palette du deck : gris 4A5058 /
// B8BCC2, vert 2E7D4F, fond transparent, 8,38 × 5,11 pouces). Un seul dessin, en SVG : affiché tel quel à l'écran (viewBox,
// donc responsive) et rasterisé en PNG à 200 dpi (1 676 × 1 022 px) pour les présentations. Les polices du deck ne sont pas
// embarquées : une pile système (Segoe UI / Helvetica / Arial) donne le même rendu à l'écran et dans le PNG — une police
// web ne serait pas chargée dans une image SVG rasterisée.
export const RAYON_W = 838, RAYON_H = 511, RAYON_DPI_SCALE = 2;   // 8,38 × 5,11 in × 100 → ×2 = 200 dpi
const GREY = '#4A5058', GREY2 = '#B8BCC2', GREEN = '#2E7D4F', INK = '#1F2429', MUTED = '#6B7078', GRID = '#E3E6EA';
const FONT = "'Segoe UI', 'Helvetica Neue', Helvetica, Arial, sans-serif";
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const fmtN = v => Math.round(v).toLocaleString('fr-FR').replace(/ /g, ' ');

// Pas d'axe « rond » pour ~6 graduations (matplotlib MaxNLocator approché)
function pasAxe(span){ const brut = span / 6, p = Math.pow(10, Math.floor(Math.log10(brut))); for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= brut) return m * p; return 10 * p; }

// data : { annees: {y: {median, p10, p90, n}}, nTotal } (engine.statsRayon) ; years : liste complète des années tracées
// opts : { rayon, titre, acq, libre, occupe, decote, type ('Appartement'|'Maison'), insuffisantes, minN }
export function rayonSvg(data, years, opts){
  const W = RAYON_W, H = RAYON_H;
  const left = 0.085 * W, right = 0.955 * W, top = (1 - 0.72) * H, bottom = (1 - 0.1) * H;   // fig.subplots_adjust du script (marge droite élargie : les étiquettes de déciles de la dernière année sortaient du cadre)
  const st = data.annees, ys = years.filter(y => st[y]);
  const vals = ys.flatMap(y => [st[y].p10, st[y].p90]).concat([opts.acq, opts.libre, opts.occupe].filter(v => v > 0));
  let lo = Math.min(...ys.map(y => st[y].p10), ...(opts.acq > 0 ? [opts.acq] : [])) - 1200;
  let hi = Math.max(...ys.map(y => st[y].p90), ...(opts.libre > 0 ? [opts.libre] : [])) + 500;
  if (!ys.length) { lo = 0; hi = 10000; }
  lo = Math.max(0, lo);
  const Y = v => bottom - (v - lo) / (hi - lo) * (bottom - top);
  const slot = (right - left) / years.length, X = i => left + slot * (i + 0.5);
  const out = [];
  out.push(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" font-family="${FONT}">`);
  // titre
  const typeLbl = (opts.type === 'Maison' ? 'de maisons' : "d'appartements") + (opts.typo ? ` ${opts.typo.id} (${opts.typo.surfMin}–${opts.typo.surfMax} m²)` : '');
  const titre = `Ventes ${typeLbl} à moins de ${fmtN(opts.rayon)} m du ${opts.titre} : prix au m² (DVF, ${years[0]} à ${years[years.length - 1]})`;
  out.push(`<text x="${0.01 * W}" y="${(1 - 0.965) * H + 6}" font-size="${titre.length > 95 ? 14.5 : 16.7}" fill="${INK}">${esc(titre)}</text>`);
  // grille + axe Y
  const pas = pasAxe(hi - lo); const y0 = Math.ceil(lo / pas) * pas;
  for (let v = y0; v <= hi; v += pas) {
    out.push(`<line x1="${left}" x2="${right}" y1="${Y(v)}" y2="${Y(v)}" stroke="${GRID}" stroke-width="1.1"/>`);
    out.push(`<text x="${left - 8}" y="${Y(v) + 5}" text-anchor="end" font-size="13.9" fill="${GREY}">${esc(fmtN(v) + ' €')}</text>`);
  }
  out.push(`<line x1="${left}" x2="${right}" y1="${bottom}" y2="${bottom}" stroke="${GREY2}" stroke-width="1.1"/>`);
  // lignes de référence (zorder 1 : sous les barres)
  const dash = `stroke-dasharray="8.3 5.6"`;   // (6, 4) en points matplotlib × 1,39
  if (opts.acq > 0) out.push(`<line x1="${left}" x2="${right}" y1="${Y(opts.acq)}" y2="${Y(opts.acq)}" stroke="${GREY}" stroke-width="1.9" ${dash}/>`);
  if (opts.libre > 0) out.push(`<line x1="${left}" x2="${right}" y1="${Y(opts.libre)}" y2="${Y(opts.libre)}" stroke="${GREEN}" stroke-width="2.8" ${dash}/>`);
  if (opts.occupe > 0) out.push(`<line x1="${left}" x2="${right}" y1="${Y(opts.occupe)}" y2="${Y(opts.occupe)}" stroke="${GREEN}" stroke-width="2.2" stroke-dasharray="2.1 4.2"/>`);
  // barres, étiquettes, moustaches
  years.forEach((y, i) => {
    const s = st[y]; const x = X(i);
    out.push(`<text x="${x}" y="${bottom + 20}" text-anchor="middle" font-size="15.3" fill="${GREY}">${y}</text>`);
    if (!s) { out.push(`<text x="${x}" y="${bottom - 10}" text-anchor="middle" font-size="11.1" fill="${MUTED}">${esc(`moins de ${opts.minN || 5} ventes`)}</text>`); return; }
    const bw = slot * 0.5;
    out.push(`<rect x="${x - bw / 2}" y="${Y(s.median)}" width="${bw}" height="${Math.max(0, bottom - Y(s.median))}" fill="${GREY2}"/>`);
    // étiquette de médiane au-dessus de la barre ; si une ligne de référence traverse la bande du texte, on la pose au-dessus de la ligne
    // (constaté sur le PNG du 13 rue de Penthièvre : « 12 199 » barré par la ligne de sortie à 12 600)
    let yLab = s.median + 120; const bande = (hi - lo) * 17 / (bottom - top);
    for (const v of [opts.acq, opts.libre, opts.occupe]) if (v > 0 && v > yLab - bande * 0.3 && v < yLab + bande) yLab = v + bande * 0.35;
    out.push(`<text x="${x}" y="${Y(yLab) - 3}" text-anchor="middle" font-size="${years.length <= 6 ? 15.3 : years.length <= 10 ? 12.5 : 11}" font-weight="700" fill="${INK}">${esc(fmtN(s.median))}</text>`);
    const xw = x + slot * 0.34, cap = slot * 0.03;
    out.push(`<line x1="${xw}" x2="${xw}" y1="${Y(s.p10)}" y2="${Y(s.p90)}" stroke="${GREY}" stroke-width="1.8"/>`);
    for (const v of [s.p10, s.p90]) {
      out.push(`<line x1="${xw - cap}" x2="${xw + cap}" y1="${Y(v)}" y2="${Y(v)}" stroke="${GREY}" stroke-width="1.8"/>`);
      if (years.length <= 10) out.push(`<text x="${x + slot * 0.4}" y="${Y(v) + 4}" font-size="${years.length > 6 ? 9.6 : 11.1}" fill="${MUTED}">${esc(fmtN(v))}</text>`);   // > 10 ans : étiquettes de déciles illisibles, moustaches seules
    }
  });
  // légende (deux colonnes au-dessus du graphique, comme loc='lower center' / bbox 1.02 / ncol=2)
  const items = [[ 'patch', GREY2, 'Médiane'], ['line', GREY, '1er et 9e déciles', '']];
  if (opts.acq > 0) items.push(['line', GREY, `Acquisition : logements à ${fmtN(opts.acq)} € / m² HD`, dash]);
  if (opts.libre > 0) items.push(['line', GREEN, `Sortie : ${fmtN(opts.libre)} € / m² HD libre (logements rénovés)`, dash, 2.8]);
  if (opts.occupe > 0) items.push(['line', GREEN, `Sortie : ${fmtN(opts.occupe)} € / m² HD occupé${opts.decote > 0 ? ` (décote ${Math.round(opts.decote)}%)` : ''}`, 'stroke-dasharray="2.1 4.2"', 2.2]);
  const ncol = 2, nrow = Math.ceil(items.length / ncol), rowH = 19, colW = (right - left) / ncol;
  const legTop = top - 10 - nrow * rowH;
  items.forEach((it, k) => {
    const col = Math.floor(k / nrow), row = k % nrow; const x = left + col * colW + 20, y = legTop + row * rowH + 10;
    if (it[0] === 'patch') out.push(`<rect x="${x}" y="${y - 6}" width="40" height="12" fill="${it[1]}"/>`);
    else out.push(`<line x1="${x}" x2="${x + 40}" y1="${y}" y2="${y}" stroke="${it[1]}" stroke-width="${it[4] || 1.8}" ${it[3] || ''}/>`);
    out.push(`<text x="${x + 50}" y="${y + 4.5}" font-size="12.5" fill="${GREY}">${esc(it[2])}</text>`);
  });
  // source
  const last = ys.length ? ys[ys.length - 1] : null;
  const src = `Source : DVF (data.gouv.fr), ventes d'un ${opts.type === 'Maison' ? 'maison seule' : 'appartement seul'}${opts.typo ? ` de ${opts.typo.surfMin} à ${opts.typo.surfMax} m²` : ''}, rayon de ${fmtN(opts.rayon)} m ; ${fmtN(data.nTotal)} ventes${last ? ` dont ${fmtN(st[last].n)} en ${last}` : ''}.`;
  out.push(`<text x="${0.01 * W}" y="${H - 0.015 * H - 2}" font-size="11.1" fill="${MUTED}">${esc(src)}</text>`);
  out.push('</svg>');
  return out.join('');
}

// Rasterisation du SVG en PNG (fond transparent) à l'échelle demandée ; renvoie un Blob.
export function svgToPng(svg, scale = RAYON_DPI_SCALE){
  return new Promise((resolve, reject) => {
    const img = new Image();
    const url = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml;charset=utf-8' }));
    img.onload = () => {
      const c = document.createElement('canvas'); c.width = RAYON_W * scale; c.height = RAYON_H * scale;
      const ctx = c.getContext('2d'); ctx.scale(scale, scale); ctx.drawImage(img, 0, 0, RAYON_W, RAYON_H);
      URL.revokeObjectURL(url); c.toBlob(b => b ? resolve(b) : reject(new Error('toBlob')), 'image/png');
    };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('rasterisation SVG')); };
    img.src = url;
  });
}

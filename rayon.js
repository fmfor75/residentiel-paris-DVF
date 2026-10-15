// rayon.js — visuel « marché autour de l'immeuble » (lot 10) : barres de médiane, moustaches P10–P90 par année, lignes
// d'acquisition et de sortie. Reproduit le visuel du script outils_marche_dvf.py de Jadero (palette du deck : gris 4A5058 /
// B8BCC2, vert 2E7D4F, fond transparent, 8,38 × 5,11 pouces). Un seul dessin, en SVG : affiché tel quel à l'écran (viewBox,
// donc responsive), rasterisé en PNG à 200 dpi (1 676 × 1 022 px) pour les présentations et pour la page du rapport PDF.
// Les polices du deck ne sont pas embarquées : une pile système (Segoe UI / Helvetica / Arial) donne le même rendu à l'écran
// et dans le PNG — une police web ne serait pas chargée dans une image SVG rasterisée.
//
// Lot 10c (retours de Franck du 13/10) : plusieurs séries (typologies) sur le même graphique en barres groupées ; les
// étiquettes de déciles passent au-dessus / en dessous des moustaches (à droite, elles chevauchaient la barre suivante dès
// 6 ans) ; l'axe est en €/m² ; une ligne de lecture explique médiane et déciles sous le graphique.
export const RAYON_W = 838, RAYON_H = 511, RAYON_DPI_SCALE = 2;   // 8,38 × 5,11 in × 100 → ×2 = 200 dpi
const GREY = '#4A5058', GREY2 = '#B8BCC2', GREEN = '#2E7D4F', INK = '#1F2429', MUTED = '#6B7078', GRID = '#E3E6EA';
// Couleurs des séries quand plusieurs typologies sont tracées : gris clair du deck, vert du deck, puis gris moyen, vert clair, gris foncé
export const SERIES_COLORS = [GREY2, GREEN, '#7A8089', '#8FB79F', '#4A5058'];
const FONT = "'Segoe UI', 'Helvetica Neue', Helvetica, Arial, sans-serif";
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const fmtN = v => Math.round(v).toLocaleString('fr-FR').replace(/ /g, ' ');

// Pas d'axe « rond » pour ~6 graduations (matplotlib MaxNLocator approché)
function pasAxe(span){ const brut = span / 6, p = Math.pow(10, Math.floor(Math.log10(brut))); for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= brut) return m * p; return 10 * p; }

export const serieLabel = s => s.label || (s.typo ? `${s.typo.id} · ${s.typo.surfMin}–${s.typo.surfMax} m²` : 'toutes surfaces');
// « d'appartements » / « de maisons » / « d'appartements et de maisons » (type « Tous », lot 13)
export const typeDe = t => t === 'Maison' ? 'de maisons' : t === 'Tous' ? "d'appartements et de maisons" : "d'appartements";
const venteDe = t => t === 'Maison' ? "d'une maison seule" : t === 'Tous' ? "d'un logement seul (appartement ou maison)" : "d'un appartement seul";

// series : [{ typo: {id, surfMin, surfMax} | null, st: engine.statsRayon(...) }] — une série par typologie choisie (une seule, sans
// typo, = toutes les surfaces) ; years : liste complète des années tracées ;
// opts : { rayon, titre, acq, libre, occupe, decote, type ('Appartement'|'Maison'), minN }
export function rayonSvg(series, years, opts){
  const W = RAYON_W, H = RAYON_H, n = series.length, multi = n > 1;
  const left = 0.118 * W, right = 0.955 * W, top = (1 - 0.72) * H, bottom = (1 - 0.135) * H;   // marges du script ; gauche élargie pour « 15 000 €/m² » (coupé à 0,085), bas relevé pour la ligne de lecture
  const vals = series.flatMap(s => years.filter(y => s.st.annees[y]).flatMap(y => [s.st.annees[y].p10, s.st.annees[y].p90]));
  let lo = Math.min(...vals, ...(opts.acq > 0 ? [opts.acq] : [])) - 1200, hi = Math.max(...vals, ...(opts.libre > 0 ? [opts.libre] : [])) + 500;
  if (!vals.length) { lo = 0; hi = 10000; }
  lo = Math.max(0, lo);
  const Y = v => bottom - (v - lo) / (hi - lo) * (bottom - top);
  const slot = (right - left) / years.length, X = i => left + slot * (i + 0.5);
  const nb = years.length * n;   // nombre de barres : pilote la taille des étiquettes
  const fMed = nb <= 6 ? 15.3 : nb <= 10 ? 12.5 : nb <= 20 ? 10.5 : 9, fDec = nb <= 6 ? 11.1 : 9.6, decLabels = nb <= 20;
  const out = [];
  out.push(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" font-family="${FONT}">`);
  // titre
  const typoTxt = opts.type === 'Tous' ? '' : multi ? ` ${series.map(s => s.typo ? s.typo.id : 'toutes surfaces').join(' / ')}` : (series[0].typo ? ` ${series[0].typo.id} (${series[0].typo.surfMin}–${series[0].typo.surfMax} m²)` : '');
  const titre = `Ventes ${typeDe(opts.type)}${typoTxt} à moins de ${fmtN(opts.rayon)} m du ${opts.titre} : prix au m² (DVF, ${years[0]} à ${years[years.length - 1]})`;
  out.push(`<text x="${0.01 * W}" y="${(1 - 0.965) * H + 6}" font-size="${titre.length > 95 ? 14.5 : 16.7}" fill="${INK}">${esc(titre)}</text>`);
  // grille + axe Y (en €/m², demande de Franck)
  const pas = pasAxe(hi - lo); const y0 = Math.ceil(lo / pas) * pas;
  for (let v = y0; v <= hi; v += pas) {
    out.push(`<line x1="${left}" x2="${right}" y1="${Y(v)}" y2="${Y(v)}" stroke="${GRID}" stroke-width="1.1"/>`);
    out.push(`<text x="${left - 8}" y="${Y(v) + 5}" text-anchor="end" font-size="13" fill="${GREY}">${esc(fmtN(v) + ' €/m²')}</text>`);
  }
  out.push(`<line x1="${left}" x2="${right}" y1="${bottom}" y2="${bottom}" stroke="${GREY2}" stroke-width="1.1"/>`);
  // lignes de référence (zorder 1 : sous les barres)
  const dash = `stroke-dasharray="8.3 5.6"`;   // (6, 4) en points matplotlib × 1,39
  if (opts.acq > 0) out.push(`<line x1="${left}" x2="${right}" y1="${Y(opts.acq)}" y2="${Y(opts.acq)}" stroke="${GREY}" stroke-width="1.9" ${dash}/>`);
  if (opts.libre > 0) out.push(`<line x1="${left}" x2="${right}" y1="${Y(opts.libre)}" y2="${Y(opts.libre)}" stroke="${GREEN}" stroke-width="2.8" ${dash}/>`);
  if (opts.occupe > 0) out.push(`<line x1="${left}" x2="${right}" y1="${Y(opts.occupe)}" y2="${Y(opts.occupe)}" stroke="${GREEN}" stroke-width="2.2" stroke-dasharray="2.1 4.2"/>`);
  // barres, étiquettes, moustaches
  const bande = (hi - lo) * (fMed + 2) / (bottom - top);   // hauteur d'une étiquette en unités de prix
  const grp = slot * (multi ? 0.78 : 0.5), bw = grp / n;   // une série : barre à 50 % du créneau comme le script ; plusieurs : groupe à 78 %
  years.forEach((y, i) => {
    const xc = X(i);
    out.push(`<text x="${xc}" y="${bottom + 20}" text-anchor="middle" font-size="15.3" fill="${GREY}">${y}</text>`);
    series.forEach((se, k) => {
      const s = se.st.annees[y]; const col = multi ? SERIES_COLORS[k % SERIES_COLORS.length] : GREY2;
      const xb = xc - grp / 2 + bw * (k + 0.5);   // centre de la barre
      if (!s) { out.push(`<text x="${xb}" y="${bottom - 8}" text-anchor="middle" font-size="${multi ? 8.5 : 11.1}" fill="${MUTED}" transform="${multi ? `rotate(-90 ${xb} ${bottom - 8})` : ''}">${esc(multi ? '< 5 ventes' : `moins de ${opts.minN || 5} ventes`)}</text>`); return; }
      out.push(`<rect x="${xb - bw * (multi ? 0.46 : 0.5)}" y="${Y(s.median)}" width="${bw * (multi ? 0.92 : 1)}" height="${Math.max(0, bottom - Y(s.median))}" fill="${col}"/>`);
      // moustache : à droite de la barre quand il n'y a qu'une série (comme le script), centrée sur la barre sinon
      const xw = multi ? xb : xc + slot * 0.34, cap = multi ? bw * 0.18 : slot * 0.03, wcol = multi && col === GREY ? '#1F2429' : GREY;
      out.push(`<line x1="${xw}" x2="${xw}" y1="${Y(s.p10)}" y2="${Y(s.p90)}" stroke="${wcol}" stroke-width="1.8"/>`);
      for (const v of [s.p10, s.p90]) out.push(`<line x1="${xw - cap}" x2="${xw + cap}" y1="${Y(v)}" y2="${Y(v)}" stroke="${wcol}" stroke-width="1.8"/>`);
      // étiquettes de déciles au-dessus du 9e et en dessous du 1er (à droite, elles chevauchaient la barre voisine dès 6 ans — retour du 13/10)
      const halo = multi ? 'paint-order="stroke" stroke="#fff" stroke-width="2.5" stroke-linejoin="round"' : '';   // en groupé, l'étiquette du 1er décile tombe sur la barre
      if (decLabels) { out.push(`<text x="${xw}" y="${Y(s.p90) - 5}" text-anchor="middle" font-size="${fDec}" fill="${multi ? INK : MUTED}" ${halo}>${esc(fmtN(s.p90))}</text>`);
        out.push(`<text x="${xw}" y="${Y(s.p10) + fDec + 3}" text-anchor="middle" font-size="${fDec}" fill="${multi ? INK : MUTED}" ${halo}>${esc(fmtN(s.p10))}</text>`); }
      // étiquette de médiane au-dessus de la barre ; si une ligne de référence (ou, en groupé, la moustache) traverse la bande du texte, halo blanc
      // et déplacement au-dessus de la ligne (constaté sur le PNG du 13 rue de Penthièvre : « 12 199 » barré par la ligne de sortie à 12 600)
      let yLab = s.median + bande * 0.35;
      if (!multi) for (const v of [opts.acq, opts.libre, opts.occupe]) if (v > 0 && v > yLab - bande * 0.3 && v < yLab + bande) yLab = v + bande * 0.35;
      out.push(`<text x="${xb}" y="${Y(yLab) - 3}" text-anchor="middle" font-size="${fMed}" font-weight="700" fill="${INK}" ${multi ? 'paint-order="stroke" stroke="#fff" stroke-width="3" stroke-linejoin="round"' : ''}>${esc(fmtN(s.median))}</text>`);
    });
  });
  // légende (deux colonnes au-dessus du graphique, comme loc='lower center' / bbox 1.02 / ncol=2)
  const items = multi ? series.map((se, k) => ['patch', SERIES_COLORS[k % SERIES_COLORS.length], `Médiane ${serieLabel(se)}`]) : [['patch', GREY2, 'Médiane']];
  items.push(['line', GREY, '1er et 9e déciles', '']);
  if (opts.acq > 0) items.push(['line', GREY, `Acquisition : logements à ${fmtN(opts.acq)} € / m² HD`, dash]);
  if (opts.libre > 0) items.push(['line', GREEN, `Sortie : ${fmtN(opts.libre)} € / m² HD libre (logements rénovés)`, dash, 2.8]);
  if (opts.occupe > 0) items.push(['line', GREEN, `Sortie : ${fmtN(opts.occupe)} € / m² HD occupé${opts.decote > 0 ? ` (décote ${Math.round(opts.decote)}%)` : ''}`, 'stroke-dasharray="2.1 4.2"', 2.2]);
  const ncol = 2, nrow = Math.ceil(items.length / ncol), rowH = items.length > 6 ? 16 : 19, colW = (right - left) / ncol, fLeg = items.length > 6 ? 11 : 12.5;
  const legTop = top - 10 - nrow * rowH;
  items.forEach((it, k) => {
    const col = Math.floor(k / nrow), row = k % nrow; const x = left + col * colW + 20, y = legTop + row * rowH + 10;
    if (it[0] === 'patch') out.push(`<rect x="${x}" y="${y - 6}" width="40" height="12" fill="${it[1]}"/>`);
    else out.push(`<line x1="${x}" x2="${x + 40}" y1="${y}" y2="${y}" stroke="${it[1]}" stroke-width="${it[4] || 1.8}" ${it[3] || ''}/>`);
    out.push(`<text x="${x + 50}" y="${y + 4.5}" font-size="${fLeg}" fill="${GREY}">${esc(it[2])}</text>`);
  });
  // source + lecture (demande de Franck : expliquer les déciles sous le graphique)
  const nTotal = series.reduce((a, s) => a + s.st.nTotal, 0), last = years.slice().reverse().find(y => series.some(s => s.st.annees[y]));
  const nLast = last ? series.reduce((a, s) => a + (s.st.annees[last]?.n || 0), 0) : 0;
  // en « Tous » sans typologie cochée, les séries Appartements / Maisons répètent déjà le type : pas de parenthèse redondante
  const surfTxt = (opts.type === 'Tous' && !series.some(s => s.typo)) ? '' : multi ? ` (${series.map(serieLabel).join(', ')})` : (series[0].typo ? ` de ${series[0].typo.surfMin} à ${series[0].typo.surfMax} m²` : '');
  const src = `Source : DVF (data.gouv.fr), ventes ${venteDe(opts.type)}${surfTxt}, rayon de ${fmtN(opts.rayon)} m ; ${fmtN(nTotal)} ventes${last ? ` dont ${fmtN(nLast)} en ${last}` : ''}.`;
  out.push(`<text x="${0.01 * W}" y="${H - 0.015 * H - 16}" font-size="${src.length > 150 ? 9.6 : 11.1}" fill="${MUTED}">${esc(src)}</text>`);
  out.push(`<text x="${0.01 * W}" y="${H - 0.015 * H - 2}" font-size="11.1" fill="${MUTED}">${esc('Lecture : la barre est le prix au m² médian des ventes de l’année ; la moustache va du 1er décile (10 % des ventes en dessous) au 9e décile (10 % au-dessus).')}</text>`);
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
// Même chose en data URL (page du rapport PDF : l'image est celle du téléchargement, à l'identique)
export async function svgToPngDataUrl(svg, scale = RAYON_DPI_SCALE){
  const blob = await svgToPng(svg, scale);
  return new Promise((resolve, reject) => { const r = new FileReader(); r.onload = () => resolve(r.result); r.onerror = () => reject(new Error('lecture PNG')); r.readAsDataURL(blob); });
}

// engine.js — moteur de calcul des statistiques DVF, exécuté dans le navigateur (et dans Node pour les tests).
//
// Il reproduit exactement les règles de scripts/process_dvf.py (compute_stats, by_period, windows, typo_stats) :
// mêmes percentiles interpolés, même arrondi (round-half-even de Python), mêmes seuils (3 ventes minimum).
// tests/test_engine.mjs compare ses résultats au JSON du pipeline sur données réelles, à ±1 €/m² près
// (la surface est stockée au centième et la valeur à l'euro dans dvf_sales.bin).
//
// Format de sales.bin (déchiffré) : "DVS1" + uint32 n, puis n enregistrements de 10 octets little-endian :
//   uint8 quartier (index dans meta.quartier_index) · uint8 type (0 appartement, 1 maison) · uint16 mois depuis 2000-01
//   uint16 surface×100 · uint32 valeur (€)

export const FENETRES = [1, 3, 5, 10];

export function decodeSales(buf) {
  const dv = new DataView(buf);
  const magic = String.fromCharCode(dv.getUint8(0), dv.getUint8(1), dv.getUint8(2), dv.getUint8(3));
  if (magic !== 'DVS1') throw new Error('format de ventes inconnu : ' + magic);
  const n = dv.getUint32(4, true);
  const q = new Uint8Array(n), t = new Uint8Array(n), ym = new Uint16Array(n), surf = new Float64Array(n), val = new Float64Array(n), ppm2 = new Float64Array(n), year = new Uint16Array(n);
  let o = 8;
  for (let i = 0; i < n; i++, o += 10) {
    q[i] = dv.getUint8(o); t[i] = dv.getUint8(o + 1); ym[i] = dv.getUint16(o + 2, true);
    surf[i] = dv.getUint16(o + 4, true) / 100; val[i] = dv.getUint32(o + 6, true); ppm2[i] = val[i] / surf[i];
    year[i] = 2000 + Math.floor(ym[i] / 12);
  }
  return { n, q, t, ym, surf, val, ppm2, year };
}

// round() de Python 3 : demi vers le pair. Math.round arrondit 0.5 vers le haut → écarts d'1 € sur les moyennes.
export function pyround(x, nd = 0) {
  const m = Math.pow(10, nd), v = x * m, f = Math.floor(v), d = v - f;
  let r; if (d > 0.5) r = f + 1; else if (d < 0.5) r = f; else r = (f % 2 === 0) ? f : f + 1;
  return r / m;
}
function percentile(sorted, qq) {
  const n = sorted.length; if (!n) return null;
  const pos = qq * (n - 1), lo = Math.floor(pos), hi = Math.min(lo + 1, n - 1);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

// Sélection : renvoie un Int32Array d'indices de ventes.
// f = {quartiers: Uint8Array(90) masque 0/1 | null, type: 0|1|null, surfMin, surfMax (surfMin <= s < surfMax), ymFrom, ymTo (inclus)}
export function select(S, f) {
  const out = new Int32Array(S.n); let k = 0;
  const qm = f.quartiers || null, ty = f.type == null ? -1 : f.type;
  const sMin = f.surfMin ?? -Infinity, sMax = f.surfMax ?? Infinity, yFrom = f.ymFrom ?? 0, yTo = f.ymTo ?? 65535;
  for (let i = 0; i < S.n; i++) {
    if (qm && !qm[S.q[i]]) continue;
    if (ty >= 0 && S.t[i] !== ty) continue;
    const s = S.surf[i]; if (s < sMin || s >= sMax) continue;
    const y = S.ym[i]; if (y < yFrom || y > yTo) continue;
    out[k++] = i;
  }
  return out.subarray(0, k);
}

export function stats(S, idx, minN = 3) {
  const n = idx.length; if (n < minN) return null;
  const p = new Float64Array(n), s = new Float64Array(n); let sp = 0, ss = 0;
  for (let j = 0; j < n; j++) { const i = idx[j]; p[j] = S.ppm2[i]; s[j] = S.surf[i]; sp += S.ppm2[i]; ss += S.surf[i]; }
  p.sort(); s.sort();
  return { count: n, mean: pyround(sp / n), median: pyround(percentile(p, .5)), min: pyround(p[0]), max: pyround(p[n - 1]),
           q1: pyround(percentile(p, .25)), q3: pyround(percentile(p, .75)), p10: pyround(percentile(p, .10)), p90: pyround(percentile(p, .90)),
           surf_mean: pyround(ss / n, 1), surf_median: pyround(percentile(s, .5), 1) };
}

export const keyYear = (S, i) => String(S.year[i]);
export const keyQuarter = (S, i) => `${S.year[i]}-Q${Math.floor((S.ym[i] % 12) / 3) + 1}`;
export const keyMonth = (S, i) => `${S.year[i]}-${String(S.ym[i] % 12 + 1).padStart(2, '0')}`;

export function byPeriod(S, idx, keyFn) {
  const groups = new Map();
  for (let j = 0; j < idx.length; j++) { const k = keyFn(S, idx[j]); let g = groups.get(k); if (!g) { g = []; groups.set(k, g); } g.push(idx[j]); }
  const out = {};
  for (const k of [...groups.keys()].sort()) { const st = stats(S, Int32Array.from(groups.get(k))); if (st) { delete st.surf_median; out[k] = st; } }
  return out;
}

export function windows(S, idx, lastYear) {
  const out = {};
  for (const n of FENETRES) {
    const sel = idx.filter(i => S.year[i] > lastYear - n);
    const st = stats(S, sel); if (st) out[String(n)] = { ...st, from: lastYear - n + 1, to: lastYear };
  }
  const st = stats(S, idx);
  if (st) { let y0 = Infinity; for (let j = 0; j < idx.length; j++) if (S.year[idx[j]] < y0) y0 = S.year[idx[j]]; out.all = { ...st, from: y0, to: lastYear }; }
  return out;
}

// Étude complète d'une sélection : global + typologies libres. typos = [{id, surfMin, surfMax}]
export function etude(S, idx, lastYear, typos, { withMonth = true } = {}) {
  const bloc = (sel) => {
    const st = stats(S, sel); if (!st) return null;
    return { ...st, by_year: byPeriod(S, sel, keyYear), by_quarter: byPeriod(S, sel, keyQuarter), by_month: withMonth ? byPeriod(S, sel, keyMonth) : null, windows: windows(S, sel, lastYear) };
  };
  const g = bloc(idx); if (!g) return null;
  const by_typo = {}; let total = 0; const parts = {};
  for (const t of typos) { parts[t.id] = idx.filter(i => S.surf[i] >= t.surfMin && S.surf[i] < t.surfMax); total += parts[t.id].length; }
  let top = null, topN = -1;
  for (const t of typos) {
    const b = bloc(parts[t.id]); if (!b) continue;
    b.share = total ? pyround(parts[t.id].length / total * 100, 1) : 0; by_typo[t.id] = b;
    if (parts[t.id].length > topN) { topN = parts[t.id].length; top = t.id; }
  }
  if (top) by_typo._top_typo = top;
  return { ...g, by_typo };
}

// Quartiers d'une zone selon le niveau → masque Uint8Array indexé comme meta.quartier_index
export function masqueZone(meta, niveau, id) {
  const qi = meta.quartier_index, qr = meta.quartiers_ref, m = new Uint8Array(qi.length);
  let ids;
  if (niveau === 'quartier') ids = [id];
  else if (niveau === 'secteur') ids = meta.secteurs_ref[id]?.quartiers || [];
  else if (niveau === 'zone') ids = meta.zones_ref[id]?.quartiers || [];
  else if (niveau === 'arrondissement') ids = qi.filter(q => qr[q]?.arr === +id);
  else if (niveau === 'commune') ids = qi.filter(q => qr[q]?.commune === id);
  else ids = [];
  for (const q of ids) { const k = qi.indexOf(q); if (k >= 0) m[k] = 1; }
  return m;
}
export const ymOf = (year, month) => (year - 2000) * 12 + month - 1;

// ═══════════════════════════════════════════════════════════════════════════════
// Valorisation d'un immeuble (lot 6) : référence par typologie sur les 12 derniers mois disponibles,
// repli quartier → secteur → arrondissement (ou commune) si l'échantillon est inférieur à minN,
// positionnement par percentile libre entre P10 et P90.
// ═══════════════════════════════════════════════════════════════════════════════
export function ymMax(S){ let m = 0; for (let i = 0; i < S.n; i++) if (S.ym[i] > m) m = S.ym[i]; return m; }
export const ymLabel = ym => ({ year: 2000 + Math.floor(ym / 12), month: ym % 12 + 1 });
// percentile à rang libre (même interpolation que stats) sur une sélection ; null si moins de minN ventes
export function percentileOf(S, idx, q, minN = 3){
  const n = idx.length; if (n < minN) return null;
  const p = new Float64Array(n); for (let j = 0; j < n; j++) p[j] = S.ppm2[idx[j]]; p.sort();
  return pyround(percentile(p, q));
}
// Fourchette de surface d'une surface donnée : la typologie qui la contient, sinon ±25 % autour
export function bandeSurface(typos, surf){
  const t = typos.find(t => surf >= t.surfMin && surf < t.surfMax);
  return t ? { id: t.id, surfMin: t.surfMin, surfMax: t.surfMax } : { id: null, surfMin: Math.round(surf * .75), surfMax: Math.round(surf * 1.25) };
}
// Niveaux d'élargissement pour un quartier : quartier, secteur, puis arrondissement (Paris) ou commune
export function niveauxRepli(meta, quartierId){
  const q = meta.quartiers_ref[quartierId]; if (!q) return [];
  const out = [['quartier', quartierId]]; if (q.secteur) out.push(['secteur', q.secteur]);
  if (q.commune === '75056' && q.arr) out.push(['arrondissement', String(q.arr)]); else if (q.commune) out.push(['commune', q.commune]);
  return out;
}
// Référence pour une surface : premier niveau dont l'échantillon (type, bande de surface, 12 mois) atteint minN
export function refSurface(S, meta, quartierId, surf, typos, { type = 0, months = 12, minN = 30, ymTo = null } = {}){
  const to = ymTo ?? ymMax(S), from = to - months + 1, b = bandeSurface(typos, surf);
  let dernier = null;
  for (const [niveau, id] of niveauxRepli(meta, quartierId)) {
    const idx = select(S, { quartiers: masqueZone(meta, niveau, id), type, surfMin: b.surfMin, surfMax: b.surfMax, ymFrom: from, ymTo: to });
    dernier = { niveau, id, n: idx.length, idx, bande: b, ymFrom: from, ymTo: to, p10: percentileOf(S, idx, .10), median: percentileOf(S, idx, .50), p90: percentileOf(S, idx, .90) };
    if (idx.length >= minN) return { ...dernier, suffisant: true };
  }
  return dernier ? { ...dernier, suffisant: false } : null;   // dernier niveau même insuffisant : affiché avec avertissement
}
// lignes : [{id, lots, surf, adj}] (adj en %) ; position : rang du percentile retenu (0,10 → 0,90)
export function valoriser(S, meta, quartierId, lignes, { position = .5, typos, type = 0, months = 12, minN = 30, ymTo = null } = {}){
  const rows = lignes.map(l => {
    const lots = Math.max(0, Math.floor(+l.lots || 0)), surf = +l.surf || 0, adj = +l.adj || 0;
    const ref = surf > 0 ? refSurface(S, meta, quartierId, surf, typos, { type, months, minN, ymTo }) : null;
    const k = 1 + adj / 100;
    const ppm2 = ref && ref.n >= 3 ? pyround(percentileOf(S, ref.idx, position) * k) : null;
    const bas = ref?.p10 != null ? pyround(ref.p10 * k) : null, haut = ref?.p90 != null ? pyround(ref.p90 * k) : null;
    const v = x => (x == null || !lots) ? null : pyround(x * surf * lots);   // 0 lot : référence affichée, pas de valeur
    return { ...l, lots, surf, adj, ref: ref ? { niveau: ref.niveau, id: ref.id, n: ref.n, suffisant: ref.suffisant, bande: ref.bande, ymFrom: ref.ymFrom, ymTo: ref.ymTo, p10: ref.p10, median: ref.median, p90: ref.p90 } : null,
             ppm2, ppm2Bas: bas, ppm2Haut: haut, valeurLot: ppm2 != null ? pyround(ppm2 * surf) : null, valeur: v(ppm2), valeurBas: v(bas), valeurHaut: v(haut), surfTot: surf * lots };
  });
  const actives = rows.filter(r => r.lots > 0 && r.valeur != null);
  const sum = k => actives.reduce((a, r) => a + r[k], 0);
  const surfTot = sum('surfTot'), lots = sum('lots'), valeur = sum('valeur'), valeurBas = sum('valeurBas'), valeurHaut = sum('valeurHaut');
  const incomplet = rows.filter(r => r.lots > 0 && r.valeur == null).length;   // lignes avec lots mais sans référence : comptées, jamais tues
  return { rows, lots, surfTot, valeur, valeurBas, valeurHaut, ppm2Moyen: surfTot ? pyround(valeur / surfTot) : null, position, incomplet };
}

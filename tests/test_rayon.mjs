// Proximité (lot 10) : sélection dans un rayon et statistiques par année, sur données réelles.
// Lancer après un run du pipeline : node tests/test_rayon.mjs
import { readFileSync } from 'node:fs';
import * as E from '../engine.js';
const D = JSON.parse(readFileSync('data/dvf_paris.json', 'utf8'));
const S = E.decodeSales(readFileSync('data/dvf_sales.bin').buffer.slice(0));
const GEO = JSON.parse(readFileSync('data/geo/quartiers.geojson', 'utf8'));
let checks = 0, fails = 0;
const ok = (c, msg) => { checks++; if (!c) { fails++; console.log('  ✗ ' + msg); } };
ok(S.format === 'DVS2' && S.lon && S.lat, 'format DVS2 avec coordonnées');
// 1. Chaque vente (échantillon) est dans l'emprise et dans le polygone de son quartier
function pip(x, y, ring){ let inside = false; for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) { const xi = ring[i][0], yi = ring[i][1], xj = ring[j][0], yj = ring[j][1]; if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) inside = !inside; } return inside; }
const polys = {}; for (const f of GEO.features) polys[f.properties.id] = f.geometry.type === 'MultiPolygon' ? f.geometry.coordinates : [f.geometry.coordinates];
const quartierAt = (lon, lat) => { for (const f of GEO.features) for (const poly of polys[f.properties.id]) if (pip(lon, lat, poly[0]) && !poly.slice(1).some(h => pip(lon, lat, h))) return f.properties; return null; };
let hors = 0; const pas = Math.max(1, Math.floor(S.n / 2000));
for (let i = 0; i < S.n; i += pas) { const qid = D.quartier_index[S.q[i]]; if (!polys[qid].some(poly => pip(S.lon[i], S.lat[i], poly[0]) && !poly.slice(1).some(h => pip(S.lon[i], S.lat[i], h)))) hors++; }
ok(hors === 0, `${hors} ventes (sur ${Math.ceil(S.n / pas)} testées) hors du polygone de leur quartier`);
// 2. Rayon autour du 13 rue de Penthièvre (75008) : géocodé le 12/10/2026 par l'IGN → 2.316624, 48.87293
const lon = 2.316624, lat = 48.87293;
const idx300 = E.selectRayon(S, lon, lat, 300, { type: 0 }), idx500 = E.selectRayon(S, lon, lat, 500, { type: 0 });
ok(idx300.length > 0 && idx500.length > idx300.length, `rayon 300 : ${idx300.length} ventes, 500 : ${idx500.length}`);
let dmax = 0; for (const i of idx300) dmax = Math.max(dmax, E.haversine(lon, lat, S.lon[i], S.lat[i]));
ok(dmax <= 300, `distance max dans le rayon 300 : ${dmax.toFixed(1)} m`);
// Vérification exhaustive : aucune vente d'appartement à ≤ 300 m n'est oubliée par le pré-filtre
let brut = 0; for (let i = 0; i < S.n; i++) if (S.t[i] === 0 && E.haversine(lon, lat, S.lon[i], S.lat[i]) <= 300) brut++;
ok(brut === idx300.length, `pré-filtre : ${idx300.length} vs calcul exhaustif ${brut}`);
const years = [2021, 2022, 2023, 2024, 2025];
const st = E.statsRayon(S, idx300, { years });
for (const y of years) { const a = st.annees[y]; if (a) { ok(a.p10 <= a.median && a.median <= a.p90, `${y} : P10 ≤ médiane ≤ P90`); console.log(`  ${y} : médiane ${a.median}, P10 ${a.p10}, P90 ${a.p90}, n ${a.n}`); } else console.log(`  ${y} : insuffisant`); }
console.log(`  rayon 300 m, 2021–2025 : ${st.nTotal} ventes (script Jadero du 12/10 : 257 dont 50 en 2025, règles différentes)`);
// Comparaison à percentile « linéaire » de numpy sur une année : même interpolation
const v = Float64Array.from(idx300.filter(i => S.year[i] === 2025).map(i => S.ppm2[i])).sort();
const np = (s, q) => { const pos = q * (s.length - 1), lo = Math.floor(pos), hi = Math.min(lo + 1, s.length - 1); return s[lo] + (s[hi] - s[lo]) * (pos - lo); };
ok(Math.abs(E.pyround(np(v, .1)) - st.annees[2025].p10) < 1e-9, 'P10 = numpy.percentile linéaire');
// 3. Couverture : plein centre → 100 % ; bordure (Porte Maillot côté bois) → < 100 %
const c1 = E.couvertureRayon(lon, lat, 300, (lo, la) => quartierAt(lo, la));
ok(c1.couverte === 1, `couverture Penthièvre 300 m : ${(c1.couverte * 100).toFixed(0)} %`);
const c2 = E.couvertureRayon(2.2225, 48.8700, 500, (lo, la) => quartierAt(lo, la));   // bord ouest de l'emprise (Puteaux / Seine)
ok(c2.couverte < 1, `couverture bord ouest 500 m : ${(c2.couverte * 100).toFixed(0)} %`);
// 4. Un rayon dans la Seine sans vente → années insuffisantes, pas d'erreur
const st0 = E.statsRayon(S, E.selectRayon(S, 2.26, 48.86, 20, { type: 0 }), { years });
ok(Object.keys(st0.annees).length === 0 && st0.insuffisantes.length === 5, 'rayon vide : toutes les années insuffisantes');
console.log(`\n${checks} vérifications, ${fails} échecs`); process.exit(fails ? 1 : 0);

// Vérification croisée : le moteur navigateur (engine.js) sur dvf_sales.bin doit donner les mêmes chiffres
// que le pipeline Python (data/dvf_paris.json) — à ±1 près (surface au centième, valeur à l'euro, arrondis).
// Lancer après un run du pipeline : node tests/test_engine.mjs
import { readFileSync } from 'node:fs';
import * as E from '../engine.js';

const D = JSON.parse(readFileSync('data/dvf_paris.json', 'utf8'));
const S = E.decodeSales(readFileSync('data/dvf_sales.bin').buffer.slice(0));
const meta = { quartier_index: D.quartier_index, quartiers_ref: D.quartiers_ref, secteurs_ref: D.secteurs_ref, zones_ref: D.zones_ref };
const lastYear = D.meta.last_year, TYPOS = D.typologies_ref;
let checks = 0, fails = 0;
const near = (a, b, tol, where) => { checks++; if (a == null && b == null) return; if (a == null || b == null || Math.abs(a - b) > tol) { fails++; if (fails <= 25) console.log(`  ✗ ${where}: moteur ${a} ≠ pipeline ${b}`); } };
const cmpStats = (a, b, where, tol = 1) => { for (const k of ['count', 'mean', 'median', 'p10', 'p90', 'q1', 'q3']) near(a?.[k], b?.[k], k === 'count' ? 0 : tol, `${where}.${k}`); near(a?.surf_mean, b?.surf_mean, 0.11, `${where}.surf_mean`); };
const cmpSeries = (a, b, where) => { near(Object.keys(a || {}).length, Object.keys(b || {}).length, 0, `${where}.nb_periodes`); for (const k of Object.keys(b || {})) cmpStats(a?.[k], b[k], `${where}[${k}]`); };
const cmpBloc = (a, b, where) => { cmpStats(a, b, where); cmpSeries(a?.by_year, b?.by_year, `${where}.by_year`); if (b?.by_quarter) cmpSeries(a?.by_quarter, b.by_quarter, `${where}.by_quarter`); if (b?.by_month) cmpSeries(a?.by_month, b.by_month, `${where}.by_month`); for (const w of Object.keys(b?.windows || {})) cmpStats(a?.windows?.[w], b.windows[w], `${where}.windows[${w}]`); };

const cas = [
  ['secteur', '5', 'Appartement'], ['secteur', '11', 'Appartement'], ['secteur', 'B10', 'Appartement'], ['secteur', 'B0', 'Maison'],
  ['arrondissement', '17', 'Appartement'], ['arrondissement', '1', 'Maison'], ['zone', 'Z1', 'Appartement'], ['zone', 'Z13', 'Appartement'],
  ['quartier', 'P31', 'Appartement'], ['quartier', 'B10', 'Appartement'], ['quartier', 'P1', 'Appartement'],
];
const niveauKey = { secteur: 'secteurs', arrondissement: 'arrondissements', zone: 'zones', quartier: 'quartiers' };
console.log(`${S.n.toLocaleString('fr-FR')} ventes décodées · dernière année ${lastYear}`);
for (const [niveau, id, type] of cas) {
  const ref = D[niveauKey[niveau]][id]?.by_type?.[type];
  const idx = E.select(S, { quartiers: E.masqueZone(meta, niveau, id), type: type === 'Maison' ? 1 : 0 });
  const t0 = performance.now(); const et = E.etude(S, idx, lastYear, TYPOS, { withMonth: niveau !== 'quartier' }); const ms = performance.now() - t0;
  const where = `${niveau}:${id}:${type}`;
  if (!ref) { near(et, null, 0, `${where} (absent du pipeline, présent moteur ?)`); console.log(`  ${where}: absent des deux côtés`); continue; }
  cmpBloc(et, ref, where);
  for (const t of TYPOS) { const a = et.by_typo[t.id], b = ref.by_typo[t.id]; if (!a && !b) continue; cmpBloc(a, b, `${where}.typo[${t.id}]`); near(a?.share, b?.share, 0.11, `${where}.typo[${t.id}].share`); }
  near(et.by_typo._top_typo === ref.by_typo._top_typo ? 1 : 0, 1, 0, `${where}._top_typo`);
  console.log(`  ${where}: ${idx.length.toLocaleString('fr-FR')} ventes, méd. ${et.median} (pipeline ${ref.median}), calcul ${ms.toFixed(0)} ms`);
}
// Global Paris appartements
const gIdx = E.select(S, { quartiers: E.masqueZone(meta, 'commune', '75056'), type: 0 });
cmpBloc(E.etude(S, gIdx, lastYear, TYPOS), { ...D.global.stats, by_year: D.global.by_year, by_quarter: D.global.by_quarter, windows: D.global.windows }, 'global');
console.log(`\n${checks} comparaisons, ${fails} écarts > tolérance`);
process.exit(fails ? 1 : 0);

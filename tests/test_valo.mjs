// Tests du moteur de valorisation (engine.js, lot 6) : cohérence avec stats(), repli, arithmétique des totaux.
// Lancer : node tests/test_valo.mjs (données réelles : data/dvf_sales.bin + data/dvf_paris.json)
import { readFileSync } from 'node:fs';
import * as E from '../engine.js';
const D = JSON.parse(readFileSync('data/dvf_paris.json', 'utf8'));
const S = E.decodeSales(readFileSync('data/dvf_sales.bin').buffer.slice(0));
const meta = { quartier_index: D.quartier_index, quartiers_ref: D.quartiers_ref, secteurs_ref: D.secteurs_ref, zones_ref: D.zones_ref };
const TYPOS = D.typologies_ref;
let checks = 0, fails = 0;
const ok = (cond, msg) => { checks++; if (!cond) { fails++; console.log('  ✗ ' + msg); } };

// 1. percentileOf(0,5) = médiane de stats() ; P10/P90 idem ; sur 12 mois glissants
const to = E.ymMax(S), from = to - 11; const l = E.ymLabel(to);
console.log(`dernier mois de données : ${l.month}/${l.year} · fenêtre ${E.ymLabel(from).month}/${E.ymLabel(from).year} → ${l.month}/${l.year}`);
const idx = E.select(S, { quartiers: E.masqueZone(meta, 'secteur', '5'), type: 0, ymFrom: from, ymTo: to });
const st = E.stats(S, idx);
ok(E.percentileOf(S, idx, .5) === st.median, `percentileOf 0,5 ${E.percentileOf(S, idx, .5)} ≠ médiane ${st.median}`);
ok(E.percentileOf(S, idx, .1) === st.p10 && E.percentileOf(S, idx, .9) === st.p90, 'percentileOf 0,1 / 0,9 ≠ p10 / p90');
ok(E.percentileOf(S, idx, .25) === st.q1 && E.percentileOf(S, idx, .75) === st.q3, 'percentileOf 0,25 / 0,75 ≠ q1 / q3');
console.log(`  secteur 5, 12 mois : ${idx.length} ventes, méd. ${st.median}`);

// 2. bande de surface : typologie contenant la surface, sinon ±25 %
ok(E.bandeSurface(TYPOS, 42).id === 'T2', 'bande 42 m² doit être T2');
ok(E.bandeSurface(TYPOS, 30).id === 'T2' && E.bandeSurface(TYPOS, 29.9).id === 'T1', 'borne min incluse / max exclue');
const b = E.bandeSurface(TYPOS, 500); ok(b.id === null && b.surfMin === 375 && b.surfMax === 625, 'hors typologies → ±25 %');

// 3. repli : un quartier peu vendu (Pont de Sèvres, B7 ? on cherche le plus petit) doit élargir ; un gros quartier reste au niveau quartier
const counts = Object.fromEntries(D.quartier_index.map(q => [q, E.select(S, { quartiers: E.masqueZone(meta, 'quartier', q), type: 0, ymFrom: from, ymTo: to }).length]));
const petit = Object.entries(counts).sort((a, b) => a[1] - b[1])[0][0], gros = Object.entries(counts).sort((a, b) => b[1] - a[1])[0][0];
const rPetit = E.refSurface(S, meta, petit, 42, TYPOS), rGros = E.refSurface(S, meta, gros, 42, TYPOS);
console.log(`  plus petit quartier ${petit} (${counts[petit]} ventes 12 mois) → référence ${rPetit.niveau} ${rPetit.id}, n=${rPetit.n}, suffisant=${rPetit.suffisant}`);
console.log(`  plus gros quartier ${gros} (${counts[gros]} ventes 12 mois) → référence ${rGros.niveau} ${rGros.id}, n=${rGros.n}`);
ok(rGros.niveau === 'quartier' && rGros.n >= 30, 'gros quartier : référence au niveau quartier');
ok(rPetit.n >= 30 || !rPetit.suffisant, 'petit quartier : élargi jusqu\'à ≥ 30 ou signalé insuffisant');
ok(E.niveauxRepli(meta, 'B1').some(x => x[0] === 'commune' && x[1] === '92012'), 'Boulogne : repli sur la commune');
ok(E.niveauxRepli(meta, 'P31').map(x => x[0]).join(',') === 'quartier,secteur,arrondissement', 'Paris : quartier, secteur, arrondissement');
// la référence de repli contient bien plus de ventes que le niveau quartier
const rQ = E.select(S, { quartiers: E.masqueZone(meta, 'quartier', petit), type: 0, surfMin: 30, surfMax: 50, ymFrom: from, ymTo: to }).length;
ok(rPetit.n >= rQ, 'le repli n\'a pas moins de ventes que le quartier');

// 4. valoriser : arithmétique et positionnement
const lignes = [{ id: 'T1', lots: 2, surf: 25, adj: 0 }, { id: 'T2', lots: 4, surf: 42, adj: 5 }, { id: 'T3', lots: 0, surf: 60, adj: 0 }, { id: 'T5', lots: 1, surf: 0, adj: 0 }];
const v = E.valoriser(S, meta, gros, lignes, { position: .5, typos: TYPOS });
ok(v.lots === 6 && v.surfTot === 2 * 25 + 4 * 42, `lots ${v.lots}, surface ${v.surfTot}`);
ok(v.rows[1].ppm2 === E.pyround(v.rows[1].ref.median * 1.05), 'ajustement +5 % appliqué sur la médiane (position 0,5)');
ok(v.rows[0].valeurLot === E.pyround(v.rows[0].ppm2 * 25) && v.rows[0].valeur === E.pyround(v.rows[0].ppm2 * 25 * 2), 'valeur par lot / ligne');
ok(Math.abs(v.valeur - (v.rows[0].valeur + v.rows[1].valeur)) < 1, 'total = somme des lignes actives');
ok(v.rows[2].valeur === null && v.rows[2].ppm2 != null, 'ligne à 0 lot : référence calculée, pas de valeur');
ok(v.incomplet === 1 && v.rows[3].ref === null, 'ligne sans surface : comptée incomplète');
ok(v.valeurBas <= v.valeur && v.valeur <= v.valeurHaut, 'fourchette bas ≤ retenu ≤ haut');
const vHaut = E.valoriser(S, meta, gros, lignes, { position: .9, typos: TYPOS }), vBas = E.valoriser(S, meta, gros, lignes, { position: .1, typos: TYPOS });
ok(vHaut.valeur > v.valeur && vBas.valeur < v.valeur, 'position 0,9 > 0,5 > 0,1');
ok(vHaut.rows[0].ppm2 === vHaut.rows[0].ppm2Haut && vBas.rows[0].ppm2 === vBas.rows[0].ppm2Bas, 'aux extrémités, retenu = P90 / P10');
console.log(`  immeuble test sur ${gros} : ${v.lots} lots, ${v.surfTot} m², ${v.valeur.toLocaleString('fr-FR')} € (bas ${v.valeurBas.toLocaleString('fr-FR')}, haut ${v.valeurHaut.toLocaleString('fr-FR')}), ${v.ppm2Moyen} €/m²`);
console.log(`\n${checks} vérifications, ${fails} échecs`);
process.exit(fails ? 1 : 0);

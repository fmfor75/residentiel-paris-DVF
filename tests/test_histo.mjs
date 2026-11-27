// Lot 20 — longue période : colonnes du fichier des notaires, moyennes annuelles, calage d'un indice sur DVF, chiffres de crise,
// position d'un prix envisagé. Sur les vraies données (data/historique_notaires.json, data/dvf_paris.json, data/macro.json).
import { readFileSync } from 'node:fs';
import * as E from '../engine.js';
let fails = 0, n = 0; const ok = (c, m) => { n++; if (!c) { fails++; console.log('  ✗ ' + m); } };
const H = JSON.parse(readFileSync(new URL('../data/historique_notaires.json', import.meta.url)));
const D = JSON.parse(readFileSync(new URL('../data/dvf_paris.json', import.meta.url)));
const macro = JSON.parse(readFileSync(new URL('../data/macro.json', import.meta.url)));

// colonnes : 8e = valeurs relues à l'œil sur la page 2 du PDF (27/11/2026)
const p8 = E.histoColonne(H, 'prix', '75108');
ok(p8 && p8['2006-Q1'] === 6260 && p8['2008-Q3'] === 8560 && p8['2009-Q2'] === 7300 && p8['2013-Q4'] === 9600, `8e : ${p8?.['2006-Q1']}, ${p8?.['2008-Q3']}, ${p8?.['2009-Q2']}, ${p8?.['2013-Q4']}`);
ok(Object.keys(p8).length >= 116 && Object.keys(p8)[0] <= '1996-Q1' && Object.keys(p8).pop() >= '2024-Q4', `${Object.keys(p8).length} trimestres ${Object.keys(p8)[0]} → ${Object.keys(p8).pop()} (au moins 1996-Q1 → 2024-Q4 ; le PDF de paris.notaires.fr est republié chaque trimestre)`);
const i92 = E.histoColonne(H, 'indices', '92'), i78 = E.histoColonne(H, 'indices', '78');
ok(i92['2008-Q3'] === 90.2 && i92['2009-Q2'] === 81.9 && Object.keys(i92)[0] === '1991-Q1', `indice 92 : ${i92['2008-Q3']}, ${i92['2009-Q2']}, depuis ${Object.keys(i92)[0]}`);
ok(Object.keys(i78)[0] === '1996-Q1' && !('1995-Q4' in i78), 'indice 78 : n.d. avant 1996 écartés');
ok(E.histoColonne(H, 'prix', '99999') === null && E.histoColonne(null, 'prix', '75108') === null, 'colonne inconnue / fichier absent → null');

// moyennes annuelles : trimestriel et mensuel, années incomplètes signalées
const ma = E.moyAnnuelle(p8); ok(ma.annees.length >= 29 && Math.abs(ma.val['2008'] - (7900 + 7740 + 8560 + 7910) / 4) < 1e-9 && ma.incomplets.length <= 2, `moyenne 2008 du 8e = ${ma.val['2008']} ; années incomplètes ${ma.incomplets} (au plus 1995 et l'année en cours)`);
const mt = E.moyAnnuelle(macro.series.taux_credit.obs); ok(mt.annees[0] <= '2006' && mt.pts['2006'] === 12 && mt.incomplets.length === 1, `taux : depuis ${mt.annees[0]}, incomplets ${mt.incomplets}`);
ok(Math.abs(mt.val['2008'] - 5.0) < .3 && mt.val['2021'] < 1.3, `taux moyen 2008 ≈ 5 % (${mt.val['2008'].toFixed(2)}), 2021 ≈ 1,1 % (${mt.val['2021'].toFixed(2)})`);

// calage : Paris entier sur l'indice 75 et nos moyennes DVF annuelles
const iP = E.histoColonne(H, 'indices', '75'), dvfParis = D.global.by_year;   // Paris, appartements (test_persp vérifie que global = Paris appartements)
const cal = E.calerSurDvf(iP, dvfParis);
ok(cal && cal.n >= 11 && cal.annees[0] === '2014' && cal.annees[10] === '2024' && cal.ecartes.length === 0, `calage Paris : ${cal?.n} années ${cal?.annees?.[0]} → ${cal?.annees?.slice(-1)}`);
const ra = E.moyAnnuelle(cal.serieQ); const e2019 = Math.abs(ra.val['2019'] / dvfParis['2019'].mean - 1);
ok(e2019 < .05 && cal.ecartMax < .08, `reconstitué 2019 ${ra.val['2019'].toFixed(0)} vs DVF ${dvfParis['2019'].mean} (${(e2019 * 100).toFixed(1)} %) · écart max du ratio ${(cal.ecartMax * 100).toFixed(1)} %`);
ok(E.calerSurDvf(iP, { 2014: { mean: 8000, count: 10 } }) === null, 'moins de 3 années de calage → null');
ok(E.calerSurDvf(iP, { 2014: { mean: 8000, count: 10 }, 2015: dvfParis['2015'], 2016: dvfParis['2016'], 2017: dvfParis['2017'] }).ecartes[0] === '2014', 'année à moins de 30 ventes écartée et comptée');

// crise : 8e mesuré ; Paris reconstitué cohérent avec l'indice (baisse identique en %)
const c8 = E.crise(p8);
ok(c8.pic.q === '2008-Q3' && c8.pic.v === 8560 && c8.creux.q === '2009-Q2' && c8.creux.v === 7300 && Math.abs(c8.baisse + 14.72) < .01 && c8.trimPicCreux === 3, `8e : pic ${c8.pic.q} ${c8.pic.v}, creux ${c8.creux.q} ${c8.creux.v}, ${c8.baisse.toFixed(1)} %`);
ok(c8.retour && c8.retour.q === '2010-Q4' && c8.nFen === 8 && Math.abs(c8.moy - 7805) < .01 && c8.trimSousPic === 9, `8e : retour au pic ${c8.retour?.q}, ${c8.trimSousPic} trimestres sous le pic, moyenne 2008–2009 ${c8.moy}`);
// tendance longue : 20 dernières années complètes, TCAM entre a−20 et a
const tl = E.tendanceLongue(ma, 20); const aC = tl.dernierComplet;
ok(ma.pts[aC] === 4 && tl.nAnnees === 20 && +tl.de === +aC - 19 && tl.cagrDe === String(+aC - 20) && tl.cagr > 2 && tl.cagr < 8, `8e : ${tl.nAnnees} ans ${tl.de}–${tl.a}, moyenne ${tl.moy.toFixed(0)}, TCAM ${tl.cagr?.toFixed(2)} %/an depuis ${tl.cagrDe}`);
ok(Math.abs(tl.cagr - (Math.pow(ma.val[aC] / ma.val[tl.cagrDe], 1 / 20) - 1) * 100) < 1e-9, 'TCAM = (fin/début)^(1/20) − 1');
ok(E.tendanceLongue({ annees: ['2026'], pts: { 2026: 2 }, val: { 2026: 1 }, complet: 4 }) === null, 'aucune année complète → null');
const ipchAn = E.moyAnnuelle(macro.series.ipch.obs); const tr = E.tendanceLongue(ma, 20, ipchAn);
ok(tr.cagrReel != null && tr.cagrReel < tr.cagr && tr.inflationAn > 1 && tr.inflationAn < 3 && Math.abs((1 + tr.cagr / 100) / (1 + tr.inflationAn / 100) - 1 - tr.cagrReel / 100) < 1e-9, `TCAM réel ${tr.cagrReel?.toFixed(2)} %/an = nominal ${tr.cagr.toFixed(2)} déflaté de l'IPCH ${tr.inflationAn?.toFixed(2)} %/an (${tr.cagrDe} → ${tr.ipchA})`);
ok(E.tendanceLongue(ma, 20, { annees: ['2024'], pts: { 2024: 12 }, val: { 2024: 120 }, complet: 12 }).cagrReel === null, 'IPCH sans l\'année de départ → pas de TCAM réel, le nominal reste');
const cP = E.crise(cal.serieQ), cI = E.crise(iP); ok(Math.abs(cP.baisse - cI.baisse) < 1e-9 && cP.pic.q === cI.pic.q, `Paris reconstitué : même baisse que l'indice (${cI.baisse.toFixed(1)} %, pic ${cI.pic.q})`);
ok(E.crise({ '2008-Q1': 1 }) === null && E.crise(null) === null, 'série trop courte → null');

// position d'un prix envisagé
const pos = E.positionPrix(9000, ma, c8);
ok(pos.premiereAnnee === '2011' && Math.abs(pos.vsPic - (9000 / 8560 - 1) * 100) < 1e-9 && pos.dernier.y >= '2024' && !pos.auDessusDuMax, `9 000 €/m² dans le 8e : atteint pour la première fois en ${pos.premiereAnnee}, ${pos.vsPic.toFixed(1)} % vs pic 2008`);
ok(E.positionPrix(50000, ma, c8).auDessusDuMax && E.positionPrix(50000, ma, c8).premiereAnnee === null && E.positionPrix(0, ma, c8) === null, 'au-dessus de tout l\'historique / prix nul');

console.log(`\n${n} vérifications, ${fails} échecs`); process.exit(fails ? 1 : 0);

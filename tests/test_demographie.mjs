// Lot 17 — démographie et parc : agrégation, indicateurs, règle de suggestion, projection avec coefficient.
// Sur le vrai data/demographie.json (36 géographies) : la somme des 20 arrondissements doit retrouver Paris.
import { readFileSync } from 'node:fs';
import * as E from '../engine.js';
let fails = 0, n = 0; const ok = (c, m) => { n++; if (!c) { fails++; console.log('  ✗ ' + m); } };
const D = JSON.parse(readFileSync(new URL('../data/demographie.json', import.meta.url)));
const ARR = Array.from({ length: 20 }, (_, i) => `751${String(i + 1).padStart(2, '0')}`);

const paris = E.demoAgreger(D, ['75056']), arrs = E.demoAgreger(D, ARR);
ok(paris && arrs && arrs.n === 20 && arrs.manquants.length === 0, 'Paris et ses 20 arrondissements présents');
ok(arrs.pop['2023'].t === paris.pop['2023'].t, `somme des arrondissements = Paris (population 2023 : ${arrs.pop['2023'].t} vs ${paris.pop['2023'].t})`);
ok(Math.abs(arrs.parc['2023'].rp - paris.parc['2023'].rp) <= 20, `somme des arrondissements ≈ Paris (résidences principales : ${arrs.parc['2023'].rp} vs ${paris.parc['2023'].rp})`);
ok(Math.abs(arrs.menages['2023'].seuls_t - paris.menages['2023'].seuls_t) <= 20, 'personnes seules : somme ≈ Paris');
const abs = E.demoAgreger(D, ['99999']); ok(abs === null, 'géographie inconnue → null');
const mix = E.demoAgreger(D, ['75108', '99999']); ok(mix.n === 1 && mix.manquants[0] === '99999', 'manquants comptés');

const ip = E.demoIndicateurs(paris), ia = E.demoIndicateurs(arrs);
ok(ip.dernier === '2023' && ip.premier === '2012' && ip.evo && ip.evo.de === '2012', 'millésimes 2012 → 2023');
const s = ip.cur.ages.reduce((a, b) => a + b, 0); ok(Math.abs(s - 100) < .2, `parts d'âge sommant à 100 (${s.toFixed(2)})`);
const sp = ip.cur.pieces.reduce((a, b) => a + b, 0); ok(Math.abs(sp - 100) < .2, `parts par pièces sommant à 100 (${sp.toFixed(2)})`);
ok(Math.abs(ip.cur.ge80 - ia.cur.ge80) < .01, 'part des 80 ans et plus identique via Paris ou via ses arrondissements');
ok(ip.cur.ge80 > 3 && ip.cur.ge80 < 9, `part des 80+ à Paris plausible (${ip.cur.ge80.toFixed(1)} %)`);
ok(ip.cur.prop + ip.cur.loc_prive + ip.cur.hlm + ip.cur.meuble + ip.cur.gratuit > 99.5, 'statuts d\'occupation sommant à 100');
const so = E.demoIndicateurs(E.demoAgreger(D, ['93070'])), ne = E.demoIndicateurs(E.demoAgreger(D, ['92051']));
ok(so.cur.hlm > 20 && ne.cur.hlm < 10, `HLM : Saint-Ouen ${so.cur.hlm.toFixed(0)} % > Neuilly ${ne.cur.hlm.toFixed(0)} % (code TSH 221)`);

// Règle de suggestion : signes, plafonds, condition « grandes surfaces rares »
const refC = { cur: { ge80: 5, lt15: 13, etudiants: 6, grands: 25 } };
let sg = E.demoSuggestion({ cur: { ge80: 8, lt15: 16, etudiants: 6, grands: 20 } }, refC);
ok(sg.age === -0.3 && sg.fam === 0.3 && sg.etu === 0 && sg.segments.grandes === 0 && sg.segments.petites === -0.3 && sg.segments.moyennes === -0.3, `vieillissement −0,3 · familial +0,3 → ${JSON.stringify(sg.segments)}`);
sg = E.demoSuggestion({ cur: { ge80: 8, lt15: 16, etudiants: 6, grands: 30 } }, refC); ok(sg.fam === 0 && !sg.grandsRares, 'familial nul si les grandes surfaces ne sont pas rares');
sg = E.demoSuggestion({ cur: { ge80: 20, lt15: 5, etudiants: 20, grands: 10 } }, refC); ok(sg.age === -0.5 && sg.etu === 0.5 && sg.fam === 0 && sg.segments.petites === 0, 'plafonds ±0,5 ; part de < 15 ans sous la référence → familial 0');
sg = E.demoSuggestion({ cur: { ge80: 3, lt15: 10, etudiants: 2, grands: 10 } }, refC); ok(sg.age === 0.2 && sg.etu === 0 && sg.fam === 0, 'zone jeune : +0,2 ; étudiants sous la référence → 0');
ok(E.demoSuggestion(null, refC) === null && E.demoSuggestion({ cur: {} }, refC).age === 0, 'entrées manquantes tolérées');

// Projection : demo s'ajoute à la prime (test_persp vérifie prime +1 %/an = ×1,105 à 10 ans)
const macro = JSON.parse(readFileSync(new URL('../data/macro.json', import.meta.url)));
const serie = {}; let v = 9000; for (let y = 2014; y <= 2025; y++) for (let q = 1; q <= 4; q++) { serie[`${y}-Q${q}`] = v; v *= 1.006; }
const cal = E.calibrer(macro, serie, { lag: 2 });
const p0 = { tauxH: 3, horizonTaux: 12, inflation: 2, revenus: .5, prime: 0, lam: .2 };
const a = E.projeter(macro, serie, cal, p0).at(40).ratio, b = E.projeter(macro, serie, cal, { ...p0, demo: .5 }).at(40).ratio, c = E.projeter(macro, serie, cal, { ...p0, prime: .5 }).at(40).ratio;
ok(Math.abs(b / a - Math.pow(1.005, 10)) < .002 && Math.abs(b - c) < 1e-9, 'demo +0,5 %/an ≡ prime +0,5 %/an (×1,051 à 10 ans)');
ok(E.sensibilite(macro, serie, cal, p0).some(x => x.k === 'demo'), 'sensibilité : le coefficient démographique y figure même absent des params');

// Parts par surface : bandes de référence, 5 dernières années
const S = { year: [2025, 2025, 2024, 2019, 2025], surf: [20, 40, 70, 200, 120], n: 5 };
const bandes = [{ surfMin: 9, surfMax: 30 }, { surfMin: 30, surfMax: 50 }, { surfMin: 50, surfMax: 80 }, { surfMin: 80, surfMax: 110 }, { surfMin: 110, surfMax: 400 }];
const ps = E.partsParSurface(S, [0, 1, 2, 3, 4], bandes, 2025, 5);
ok(ps.n === 4 && ps.parts[0] === 25 && ps.parts[3] === 0 && ps.parts[4] === 25 && ps.de === 2021, `parts par surface : ${JSON.stringify(ps)}`);

console.log(`\n${n} vérifications, ${fails} échecs`); process.exit(fails ? 1 : 0);

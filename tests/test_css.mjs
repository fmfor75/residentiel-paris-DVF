// Collisions de classes CSS dans index.html (incidents : `.top` barre du haut vs ligne de typologie dominante, lot 15b ;
// `.seg` segments démographiques vs sélecteurs du rail, lot 17 — le rail s'est retrouvé sur 3 colonnes avec 12 px d'écart,
// sans erreur ni test rouge). Une classe nue définie deux fois hors blocs @ est soit une surcharge voulue du MÊME composant
// (liste AUTORISES ci-dessous, avec la raison), soit une collision : le test échoue.
import { readFileSync } from 'node:fs';
const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
let css = [...html.matchAll(/<style>([\s\S]*?)<\/style>/g)].map(m => m[1]).join('\n').replace(/\/\*[\s\S]*?\*\//g, '');
// retire les blocs @media / @keyframes / @supports / @font-face (accolades équilibrées)
let out = '', i = 0; const at = /@(media|keyframes|supports|font-face)[^{]*\{/g;
for (;;) { at.lastIndex = i; const m = at.exec(css); if (!m) { out += css.slice(i); break; } out += css.slice(i, m.index); let d = 1, j = m.index + m[0].length; while (d && j < css.length) { d += css[j] === '{' ? 1 : css[j] === '}' ? -1 : 0; j++; } i = j; }
const defs = new Map();
for (const m of out.matchAll(/([^{}]+)\{([^{}]*)\}/g)) for (const sel of m[1].split(',')) { const s = sel.trim(); if (/^\.[a-zA-Z][\w-]*$/.test(s)) defs.set(s, [...(defs.get(s) || []), m[2].trim()]); }
// surcharges voulues : le lot 15b restyle ces composants après leur définition de base
const AUTORISES = new Set(['.hdr', '.viewtabs', '.card', '.card-h', '.card-t', '.typo-tbl', '.ytbl', '.valo-tbl', '.ptbl', '.leaflet-popup-content-wrapper', '.rail-more']);
let fails = 0, n = 0;
for (const [sel, v] of defs) { if (v.length < 2) continue; n++; if (!AUTORISES.has(sel)) { fails++; console.log(`  ✗ ${sel} défini ${v.length} fois : ${v.map(x => x.slice(0, 50)).join(' | ')}`); } }
for (const sel of AUTORISES) if ((defs.get(sel) || []).length < 2) console.log(`  (info) ${sel} n'est plus défini deux fois : à retirer de la liste`);
console.log(`\n${defs.size} classes nues, ${n} définies plusieurs fois, ${fails} collision(s)`); process.exit(fails ? 1 : 0);

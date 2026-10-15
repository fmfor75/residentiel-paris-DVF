// Garde : tout caractère que le rapport PDF peut écrire doit exister dans la police embarquée (Inter, sous-ensemble Latin,
// assets/inter-pdf.js). Un glyphe absent n'est pas une erreur pour jsPDF : il est simplement omis — « P10 ← 50 → P90 » est
// sorti « P10 50 → P90 » dans le rapport du 15/10/2026 sans aucun message (constaté par tests/audit_pdf.py).
// Périmètre : les chaînes de pdf.js (commentaires exclus) et les définitions HELP d'index.html (reprises page Méthode).
// Usage : node tests/test_pdf_glyphs.mjs
import { readFileSync } from 'node:fs';
import { regular, semibold } from '../assets/inter-pdf.js';

// Lecture minimale de la table cmap d'une police TrueType (formats 4 et 12) → ensemble des points de code couverts
function cmapOf(b64){
  const b = Buffer.from(b64, 'base64'), u16 = o => b.readUInt16BE(o), u32 = o => b.readUInt32BE(o);
  const nT = u16(4); let cmap = -1;
  for (let i = 0; i < nT; i++) { const r = 12 + 16 * i; if (b.toString('latin1', r, r + 4) === 'cmap') cmap = u32(r + 8); }
  if (cmap < 0) throw new Error('table cmap absente');
  const set = new Set(), nSub = u16(cmap + 2);
  for (let i = 0; i < nSub; i++) {
    const off = cmap + u32(cmap + 4 + 8 * i + 4), fmt = u16(off);
    if (fmt === 4) { const segX2 = u16(off + 6), ends = off + 14, starts = ends + segX2 + 2, deltas = starts + segX2, ranges = deltas + segX2;
      for (let s = 0; s < segX2 / 2; s++) { const e = u16(ends + 2 * s), st = u16(starts + 2 * s), d = u16(deltas + 2 * s), ro = u16(ranges + 2 * s);
        for (let c = st; c <= e && c !== 0xFFFF; c++) { let g; if (ro === 0) g = (c + d) & 0xFFFF; else { const gi = ranges + 2 * s + ro + 2 * (c - st); g = u16(gi); if (g) g = (g + d) & 0xFFFF; } if (g) set.add(c); } } }
    else if (fmt === 12) { const n = u32(off + 12); for (let k = 0; k < n; k++) { const g0 = off + 16 + 12 * k, a = u32(g0), z = u32(g0 + 4), gid = u32(g0 + 8); for (let c = a; c <= z; c++) if (gid + c - a) set.add(c); } }
  }
  return set;
}
const fonts = { regular: cmapOf(regular), semibold: cmapOf(semibold) };

const sansCommentaires = src => src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:'"`\\])\/\/.*$/gm, '$1');
const pdfSrc = sansCommentaires(readFileSync(new URL('../pdf.js', import.meta.url), 'utf8'));
const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const helpStart = html.indexOf('const HELP'), helpEnd = html.indexOf('\n};', helpStart);
if (helpStart < 0 || helpEnd < 0) throw new Error('bloc HELP introuvable dans index.html');
const sources = { 'pdf.js': pdfSrc, 'index.html (HELP)': html.slice(helpStart, helpEnd) };

let echecs = 0, verifs = 0;
for (const [nom, txt] of Object.entries(sources)) {
  // combinants U+0300–U+036F : seulement dans l'expression régulière qui retire les accents du nom de fichier
  const chars = [...new Set([...txt].filter(c => c.codePointAt(0) > 126 && !(c.codePointAt(0) >= 0x300 && c.codePointAt(0) <= 0x36F)))];
  for (const [f, set] of Object.entries(fonts)) { verifs++;
    const manque = chars.filter(c => !set.has(c.codePointAt(0)));
    if (manque.length) { echecs++; console.log(`✗ ${nom} : ${manque.map(c => `« ${c} » U+${c.codePointAt(0).toString(16).toUpperCase().padStart(4, '0')}`).join(', ')} absent(s) d'Inter ${f}`); }
  }
}
// témoin : la garde doit savoir voir un manque
if (fonts.regular.has('←'.codePointAt(0))) { echecs++; console.log('✗ témoin : « ← » ne devrait pas être dans le sous-ensemble'); }
if (!fonts.regular.has('→'.codePointAt(0)) || !fonts.semibold.has('€'.codePointAt(0))) { echecs++; console.log('✗ témoin : lecture de la cmap incorrecte'); }
console.log(`${verifs + 2} vérifications, ${echecs} échecs`);
process.exit(echecs ? 1 : 0);

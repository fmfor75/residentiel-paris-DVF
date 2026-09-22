# Data Marché Résidentiel · DVF

Plateforme d'étude du marché résidentiel (Paris + Boulogne-Billancourt) alimentée par les données DVF de la DGFiP,
servie par GitHub Pages, protégée par un code d'accès.

## Architecture

```
index.html                    ← dashboard (écran de code → déchiffrement local → étude / carte), infobulles « i », mobile
engine.js                     ← moteur de calcul exécuté dans le navigateur (mêmes règles que le pipeline Python)
pdf.js                        ← export PDF de l'étude (jsPDF, chargé à la demande) ; assets/inter-pdf.js = police Inter embarquée
assets/logo-jadero.png        ← logo (page de connexion, PDF)
data/enc/meta.bin             ← méta, référentiels (secteurs, zones, quartiers, typologies par défaut) — chiffré
data/enc/sales.bin            ← toutes les ventes retenues, 10 octets par vente (format DVS1) — chiffré
data/enc/manifest.json        ← liste des fichiers chiffrés et paramètres de dérivation de clé (clair)
data/geo/                     ← référentiel géographique versionné (quartiers.geojson, referentiel.json) — clair
data/dvf_cache.json.gz        ← cache des mutations consolidées par (département, année), avec empreinte de source
scripts/process_dvf.py        ← pipeline : sources → mutations → statistiques (dvf_paris.json + dvf_sales.bin, non commités)
scripts/build_site.py         ← gzip + chiffrement AES-GCM de meta et sales (clé dérivée de DVF_CODE)
scripts/build_geo.py          ← construction manuelle du référentiel géographique (opendata.paris.fr, IGN)
tests/                        ← pipeline sur fixtures HTTP locales · chiffrement · parité moteur JS / pipeline Python · valorisation
.github/workflows/update-dvf.yml ← run mensuel : ne retélécharge que les sources modifiées, ne commite que si changement
```

## Fonctionnement du dashboard (lot 4)

Le navigateur déchiffre `sales.bin` (≈ 200 000 ventes) et calcule lui-même toutes les statistiques : niveau
(commune, arrondissement, secteur, zone d'encadrement, quartier), période, type de bien et **typologies dont les
bornes de surface sont modifiables à chaque étude** (préremplies avec T1 9–30, T2 30–50, T3 50–70, T4 70–100,
T5 100–400 m²). L'étude complète est encodée dans l'URL (`#…&typos=T1:9-30:1,…`), donc partageable.

`engine.js` reproduit exactement `process_dvf.py` (percentiles interpolés, arrondi demi-pair de Python, 3 ventes
minimum) ; `node tests/test_engine.mjs` le vérifie sur données réelles après un run du pipeline (tolérance ±1 €/m²).

L'onglet **Carte** affiche les polygones réellement utilisés (Leaflet, fond IGN) colorés selon le niveau choisi,
légende repliée par défaut ; une adresse saisie (autocomplétion IGN limitée aux communes couvertes) est géocodée
puis affectée par point-dans-polygone au quartier, avec l'arrondissement, le secteur et la zone correspondants,
chacun ouvrable en étude d'un clic.

Chaque chiffre porte un « i » qui explique sa méthode de calcul (dictionnaire `HELP` dans index.html, repris dans la
page Méthode du PDF). **Exporter en PDF** produit dans le navigateur un document A4 : couverture avec le logo et la
carte (point de l'adresse localisée si une adresse a été saisie, sinon la zone étudiée), chiffres clés, évolutions,
graphiques vectoriels, typologies, tableau annuel, méthode. La carte du PDF est dessinée depuis les tuiles IGN et les
mêmes polygones que l'écran ; les tuiles non chargées sont comptées et signalées dans la légende.

**Valorisation** (onglet disponible dès qu'une adresse est localisée ; « Valoriser l'immeuble » dans la fiche d'adresse) :
tableau des lots par typologie (nombre, surface moyenne, ajustement en %), prix au m² de référence calculé sur les ventes
d'appartements des 12 derniers mois disponibles dont la surface est dans la fourchette de la typologie, sur le quartier de
l'adresse ou, en dessous de 30 ventes, le secteur puis l'arrondissement (niveau et effectif affichés) ; curseur de
positionnement P10 → P90 ; valeur par lot, par ligne, totale, fourchette basse / haute. Tout est dans l'URL (`valo=`,
`addr=`) et repris dans une page du PDF. Fonctions `refSurface` / `valoriser` dans engine.js, testées par
`node tests/test_valo.mjs`. À l'ouverture, la plateforme affiche la carte et le champ d'adresse.

Sur iPhone (≤ 700 px) les chiffres s'affichent en premier, les filtres s'ouvrent depuis la barre fixe en bas ; sur
iPad portrait deux colonnes plus étroites ; cibles tactiles ≥ 40 px et champs à 16 px (sinon iOS Safari zoome).

## Mise à jour des données

Automatique le 1er de chaque mois. Le script relève l'empreinte (Last-Modified + taille) de chaque fichier source ;
si rien n'a changé, il s'arrête sans rien écrire. Sinon il retraite les seules années modifiées, recalcule les
statistiques, les chiffre et commite `data/enc/`. Lancement manuel : Actions → « Mise à jour DVF » → Run workflow
(`probe` sonde les sources sans rien écrire ; `force` recalcule même sans changement ; `no_cache` retélécharge tout).

## Code d'accès

Secret GitHub `DVF_CODE` (Settings → Secrets and variables → Actions). Le code n'apparaît nulle part dans le dépôt :
il sert à dériver une clé (PBKDF2-SHA256, 200 000 itérations) avec laquelle `meta.bin` et `sales.bin` sont chiffrés
au build et déchiffrés dans le navigateur. Pour changer le code : modifier le secret puis lancer le workflow avec
`force`. Localement : `DVF_CODE="…" python scripts/process_dvf.py && DVF_CODE="…" python scripts/build_site.py`.

## Règles de traitement (v13)

Ventes (« Vente » strict, VEFA exclue) d'un logement unique (appartement ou maison), dépendances tolérées, local
professionnel ou second logement → exclu. Surface Carrez si présente et à ±30 % de la surface bâtie, sinon bâtie.
Bornes : 1 000–40 000 €/m², 9–400 m². Chaque exclusion est comptée (`meta.exclusions`). Gardes bloquantes : année
creuse, source partielle, rétention < 25 %, colonnes manquantes, > 2 % de ventes sans quartier. Les ventes sans
quartier (hors polygones) ne sont comptées dans aucun niveau, pas même l'arrondissement.

Géographie : 80 quartiers administratifs de Paris (Ville de Paris) et 10 quartiers de Boulogne (IRIS IGN dissous),
affectation par point-dans-polygone. Niveaux : arrondissements (celui du polygone, pas celui déclaré dans DVF),
secteurs (listes de quartiers), zones officielles d'encadrement des loyers, quartiers.

## Sources

DGFiP « Demandes de valeurs foncières » via Etalab (geo-dvf, opendatarchives) · Ville de Paris (quartiers,
encadrement des loyers) · IGN géoplateforme (IRIS, fond de carte, géocodage) · Licence Ouverte 2.0.

# Data Marché Résidentiel · DVF

Plateforme d'étude du marché résidentiel (Paris et quatorze communes limitrophes : Boulogne-Billancourt, Clichy,
Levallois-Perret, Asnières-sur-Seine, Bois-Colombes, Puteaux, Saint-Ouen-sur-Seine, Saint-Maur-des-Fossés, Saint-Mandé,
Vincennes, depuis le lot 11 Neuilly-sur-Seine, Issy-les-Moulineaux, Colombes, La Garenne-Colombes, et depuis le lot 12
Maisons-Laffitte, dans les Yvelines) alimentée par les données DVF de la DGFiP, servie par GitHub Pages, protégée par un
code d'accès.

## Architecture

```
index.html                    ← dashboard (écran de code → déchiffrement local → étude / carte), infobulles « i », mobile
engine.js                     ← moteur de calcul exécuté dans le navigateur (mêmes règles que le pipeline Python)
pdf.js                        ← export PDF de l'étude (jsPDF, chargé à la demande) ; assets/inter-pdf.js = police Inter embarquée
rayon.js                      ← visuel « marché autour de l'immeuble » (SVG écran + PNG 200 dpi pour les présentations, niveau rayon)
assets/logo-jadero.png        ← logo (page de connexion, PDF)
data/enc/meta.bin             ← méta, référentiels (secteurs, zones, quartiers, typologies par défaut) — chiffré
data/enc/sales.bin            ← toutes les ventes retenues, 14 octets par vente avec coordonnées (format DVS2) — chiffré
data/enc/manifest.json        ← liste des fichiers chiffrés et paramètres de dérivation de clé (clair)
data/geo/                     ← référentiel géographique versionné (quartiers.geojson, referentiel.json) — clair
data/dvf_cache.json.gz        ← cache des mutations consolidées par (département, année), avec empreinte de source
scripts/process_dvf.py        ← pipeline : sources → mutations → statistiques (dvf_paris.json + dvf_sales.bin, non commités)
scripts/build_site.py         ← gzip + chiffrement AES-GCM de meta et sales (clé dérivée de DVF_CODE)
scripts/build_geo.py          ← construction manuelle du référentiel géographique (opendata.paris.fr, IGN) ; table des communes
scripts/fetch_macro.py        ← séries macro BCE / INSEE → data/macro.json (clair), au run mensuel
scripts/fetch_loyers.py       ← encadrement des loyers Paris + carte des loyers → data/loyers.json (clair), au run mensuel
scripts/fetch_demo.py         ← démographie et parc INSEE (recensements 2012/2017/2023, API Melodi) → data/demographie.json (clair)
tests/                        ← pipeline sur fixtures HTTP locales · chiffrement · parité moteur JS / pipeline Python · valorisation
.github/workflows/update-dvf.yml ← run mensuel : ne retélécharge que les sources modifiées, ne commite que si changement
```

## Fonctionnement du dashboard (lot 4)

Le navigateur déchiffre `sales.bin` (≈ 280 000 ventes) et calcule lui-même toutes les statistiques : niveau
(arrondissement ou commune entière, secteur, zone d'encadrement, quartier, rayon autour d'une adresse), période, type de bien et **typologies dont les
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

**Loyers et rentabilité brute** (carte sous la valorisation, bloc PDF) : à Paris, loyer de référence **majoré** de
l'encadrement pour le quartier de l'adresse, selon vide / meublé, le nombre de pièces de chaque ligne (modifiable, T5 = 4
pièces et plus) et l'époque de construction de l'immeuble (avant 1946, 1946–1970, 1971–1990, après 1990) ; hors Paris,
loyer d'annonce de la commune (« carte des loyers » DHUP/ANIL, 1–2 pièces / 3 pièces et plus, charges comprises).
Rentabilité brute = loyer annuel ÷ valeur retenue, par ligne et globale, avec la fourchette sur les valeurs P90 / P10.
Données dans `data/loyers.json` (clair), produites par `scripts/fetch_loyers.py` au run mensuel (export opendata.paris.fr
de la dernière année publiée — 2 560 combinaisons attendues — et dernier jeu « Carte des loyers » sur data.gouv, filtré
sur les communes du référentiel). Tests : `python -m unittest tests.test_loyers`, `node tests/test_valo.mjs`.

**Perspectives** (onglet, page PDF) : scénarios à 3, 5 et 10 ans, conditionnels à six hypothèses réglables (taux de crédit
visé et horizon, inflation, revenus réels, prime locale, coefficient démographique, vitesse d'ajustement), avec les valeurs actuelles et leurs sources.
Modèle structurel à coefficients imposés : prix cible = capacité d'emprunt à mensualité constante sur 20 ans (taux décalé de
deux trimestres) × niveau des prix ; une seule constante calée sur 2014–2025 ; ajustement partiel. Rétrospectif affiché :
calé ≤ 2019-Q4, simulé 2020–2025 avec taux et inflation réels → erreur moyenne 4,2 %, max 8,5 % (`node tests/test_persp.mjs`
le rejoue). Point de départ : dernière médiane DVF prolongée par l'indice Notaires-INSEE. La prime locale vaut 0 par défaut :
les tendances relatives des quartiers ne persistent pas d'une période à l'autre (corrélation −0,43). Séries macro dans
`data/macro.json` (clair), produites par `scripts/fetch_macro.py` au run mensuel — BCE (taux crédits habitat MIR, taux long
IRS, IPCH) et INSEE BDM sans jeton (indice Paris 010567013, loyers 010600352, logements autorisés Paris 001761793) ; une
série en échec est conservée et marquée `stale`, un dernier point ancien est marqué `retard` (l'IPCH base 2015 s'arrête à
déc. 2025 : changement de base). Tests : `python -m unittest tests.test_macro`.

**Rayon autour d'une adresse (lot 10).** Dès qu'une adresse est localisée, la fiche propose « Étudier à 300 m » / « à 500 m »
et le panneau un onglet « Rayon » (200, 300, 500, 750, 1 000 m ou rayon libre) : le rayon est un niveau d'étude comme le
quartier (`niveau=rayon&id=300`), toute l'étude se calcule sur les ventes à moins de cette distance, à vol d'oiseau depuis le
point géocodé — chiffres clés, typologies avec les bornes du panneau, tableau annuel — et le disque apparaît sur la carte et
sur la couverture du PDF ; le fil d'Ariane indique la part du disque couverte par les communes de la plateforme. Au bas de
l'étude, la carte « Marché autour de l'immeuble » reprend le visuel du script `outils_marche_dvf.py` de Jadero (médiane et
1er / 9e déciles par année, lignes d'acquisition, de sortie libre et de sortie occupé saisie ou déduite par décote ; palette
du deck, 8,38 × 5,11 pouces) avec ses paramètres : historique 2 / 5 / 10 ans, surfaces (toutes, ou une ou plusieurs typologies du panneau cochées —
une série par typologie, barres groupées, bornes modifiables dans le panneau), case « Intégrer le visuel au rapport
PDF » ; un seul dessin SVG (`rayon.js`) sert l'écran, le PNG à 200 dpi à fond transparent, le SVG et la page du PDF (qui
embarque la même image). Les étiquettes de déciles sont au-dessus et en dessous des moustaches, l'axe est en €/m², une
ligne de lecture explique médiane et déciles sous le graphique ; la carte ne re-rend que le visuel et le tableau quand un
paramètre change (les champs de saisie gardent le focus). Hash
`rprix=acq:libre:occupe:decote:hist:typo:pdf`. Les ventes sont celles de la plateforme (règles v13 : Carrez si cohérente,
bornes fixes), pas celles du script (surface bâtie, bornes relatives) : sur le 13 rue de Penthièvre, 256 ventes à 300 m en
2021–2025 contre 257 pour le script, 50 en 2025 dans les deux cas, médianes à ±3 %. Pour cela `sales.bin` est passé au
format **DVS2** (14 octets par vente : longitude et latitude quantifiées sur deux octets par rapport à l'emprise, pas
≈ 0,3 m ; DVS1 reste lisible). Fonctions `selectRayon`, `statsRayon`, `couvertureRayon` dans engine.js, testées par
`node tests/test_rayon.mjs` sur données réelles ; le test du pipeline vérifie que chaque coordonnée relue retombe dans le
polygone de son quartier.

**Communes (lot 9).** Le périmètre est porté par `data/geo/referentiel.json` (`communes` : nom, préfixe d'identifiant,
quartiers) : `process_dvf.py` en déduit les départements à télécharger (75, 92, 93, 94) et les communes retenues, et le
dashboard n'a plus aucun nom de commune en dur. Hors Paris, le niveau au-dessus du quartier est la commune entière (onglet
« Arrond. / commune », état `niveau=commune&id=<INSEE>`) ; les anciennes URL de Boulogne (`niveau=secteur&id=B0` / `B3`)
sont redirigées. Les quartiers hors Paris sont des IRIS INSEE regroupés selon une méthode choisie par commune dans
`build_geo.py` (relevé du 06/10/2026 : la convention de nommage varie) — par nom sans numéro (Boulogne 10, Levallois 13),
par grand quartier INSEE (Clichy 6, Asnières 7, Puteaux 4, Saint-Maur 8, Vincennes 4), ou IRIS individuels quand rien ne
les regroupe (Bois-Colombes 12, Saint-Mandé 9, Saint-Ouen 18). Lot 11 (14/10/2026) : Neuilly 5 (nom), Issy 7 (gq),
Colombes 4 (gq), La Garenne-Colombes 11 (iris). Lot 12 (15/10/2026) : Maisons-Laffitte 10 (iris), premier commune du
78 — le département est ajouté automatiquement (DEPS dérivé du référentiel). 208 quartiers au total (format binaire :
256 max — au-delà, passer l'index de quartier sur deux octets). Les
ventes sans coordonnées sont comptées par commune (`meta.geo.sans_quartier_commune` ; Bois-Colombes ≈ 21 % en 2024).
Le cache porte le périmètre de communes de chaque entrée : élargir le périmètre force le retraitement. Les millésimes
2014–2020 n'existent qu'en fichier national : il est lu une fois pour tous les départements. Saint-Ouen est soumise à
l'encadrement des loyers de Plaine Commune : non intégré (loyer d'annonce affiché, mention explicite ; lot 9b).

**Type de bien (lot 13).** Trois choix : Appartements, Maisons, Tous (`type=Tous` dans l'URL). « Tous » donne le marché
global (ventes d'un logement seul, appartement ou maison) et, en dessous, les mêmes indicateurs séparés par type ; les
typologies T1–T5 restent calculées sur les appartements seuls (une maison n'a pas de typologie DVF comparable). Le rayon
trace une série « Appartements » (ou une par typologie cochée) et une série « Maisons » ; le PDF reprend les deux sections.
Saint-Maur 2014–2025 : 9 882 appartements + 4 507 maisons = 14 389 ventes en « Tous » (test du 15/10/2026).

**Direction visuelle V, thème clair, indicateurs (lots 15–16).** L'écran reprend la maquette « Vproject Direction Design »
(rail rétractable de 76 px qui s'ouvre au survol, recherche ⌘K, cartes de verre, courbe lissée en dégradé, barres, anneau de
répartition, écran d'accès animé). Thème unique clair crème → taupe (25/10/2026 ; le sombre du lot 15 a été remplacé) ; le PDF et le
PNG du rayon gardent la charte Jadero. Indicateurs ajoutés (lot 16) : **moyenne pondérée** = Σ prix ÷ Σ surfaces (le m² réellement
échangé) et **prix max** avec la surface et le mois de la vente — dans les cartes, les tableaux annuel et par typologie, le CSV et le
PDF (`engine.stats` : `wmean`, `max_surf`, `max_ym`). Le max est une seule vente : à Paris entier il vaut le plafond du filtre
(40 000 €/m²). **Paris · ville entière** en tête de l'onglet Arrond. / commune (niveau `commune`, id 75056 : 80 quartiers).

**Démographie et parc (lot 17, 25/10/2026).** Carte « Démographie et parc » dans Perspectives et page PDF correspondante,
à partir des recensements INSEE 2012, 2017 et 2023 (exploitation principale, API Melodi sans clé : `scripts/fetch_demo.py`
→ `data/demographie.json`, 36 géographies = 16 communes du référentiel + 20 arrondissements). Maille commune / arrondissement :
un quartier est lu par son arrondissement, un secteur ou une zone par la somme de ses arrondissements, un rayon par la commune ou
l'arrondissement de l'adresse (`engine.demoAgreger` : sommes de comptages, parts calculées après). Affiché : population et
structure par âge (sept tranches, 2012 → 2023, face à la référence = ensemble des communes couvertes), 65 et 80 ans et plus,
moins de 15 ans, étudiants de 18 à 29 ans (`DS_RP_EDUCATION_PRINC`, STUD=1), personnes seules, parc par nombre de pièces
face aux ventes DVF par bande de surface sur 5 ans (la surface tient lieu de nombre de pièces : rapprochement assumé), statut
d'occupation (propriétaires, locataires privé, **HLM = code TSH 221** — la lecture « 212_222 » a été écartée par la mesure :
Saint-Ouen 29 % contre Neuilly 5,5 %), vacance, résidences secondaires. **Coefficient démographique** (`params.demo`,
s'ajoute à la prime locale dans la trajectoire, 7e champ du hash `persp=`, 0 par défaut) : suggestion par segment selon une
règle explicite et affichée — ±0,10 pt/an par point d'écart à la référence, plafonné à ±0,5 par terme ; vieillissement (part des
80 ans et plus) sur tous les segments, familles (part des < 15 ans, seulement si les 4 pièces et plus sont plus rares que dans la
référence) sur les grandes surfaces, étudiants sur les petites — appliquée d'un clic, jamais d'office. C'est une règle de
lecture, pas une élasticité mesurée : rien ne permet aujourd'hui de la calibrer. Gardes : `tests/test_demo.py` (API locale :
parsing, codes TSH, cellules incomplètes comptées, jeu en échec conservé, no-op), `tests/test_demographie.mjs` (somme des
arrondissements = Paris, parts sommant à 100, règle, projection), deux configurations dans `tests/audit_pdf.py`.
Correctif du 26/10 : la pastille « Quartier, commune ou zone… » ouvrait le rail sans champ hors du niveau Quartier (le champ
n'existait qu'à ce niveau) — le champ sert désormais à tous les niveaux et propose aussi les zones des autres niveaux (choisir
change le niveau) ; collision de classe `.seg` (segments démographiques vs sélecteurs du rail) → `.dseg`, avec la garde
`tests/test_css.mjs` (une classe nue définie deux fois hors blocs @ doit être une surcharge déclarée du même composant).

**Mise en page du PDF (lot 14).** Le rapport du 15/10/2026 (12 avenue Albine, Maisons-Laffitte) montrait des en-têtes de
colonnes décalés de leurs chiffres et sortis de la page, des textes hors de leur tuile, des pourcentages imprimés sur les dates
(page 1), « 2024 » sur « 2025 » dans les graphiques de volume, des surfaces à point décimal, un « ← » disparu (absent de la
police embarquée) et, dans le visuel du rayon, une bande vide sous le titre et des étiquettes recouvertes par les barres
voisines. Causes fermées une fois pour tout le document : `st.text` calcule lui-même l'alignement des textes à lettres
espacées (jsPDF l'ignore) et ajuste tout texte à son cadre (`fit` : espacement resserré, puis taille, puis « … » compté dans
`st.coupes`) ; `axisLabels` n'écrit une étiquette d'axe que si elle ne touche pas la précédente ; `fmtSurf` (virgule) à l'écran
et dans le PDF ; `rayonSvg` place la légende puis le graphique au plus juste, dessine les étiquettes après les barres et les
écrit à la verticale quand elles sont plus larges que la barre. Gardes : `node tests/test_pdf_glyphs.mjs` (tout caractère de
pdf.js et des définitions HELP existe dans la police ; dans le workflow) et `python3 tests/audit_pdf.py` (répétition de bout en
bout sur six études types, mesure de chaque texte dans le PDF produit ; à lancer en local avant toute livraison qui touche au
PDF : 64 défauts sur le rapport d'origine, 0 après).

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

Géographie : 80 quartiers administratifs de Paris (Ville de Paris) et 118 quartiers IRIS (IGN) dans quatorze communes,
affectation par point-dans-polygone. Niveaux : arrondissements (celui du polygone, pas celui déclaré dans DVF) et
communes entières, secteurs (listes de quartiers, Paris), zones officielles d'encadrement des loyers (Paris), quartiers.

## Sources

DGFiP « Demandes de valeurs foncières » via Etalab (geo-dvf, opendatarchives) · Ville de Paris (quartiers,
encadrement des loyers) · IGN géoplateforme (IRIS, fond de carte, géocodage) · INSEE (recensements de la population, API
Melodi) · Licence Ouverte 2.0.

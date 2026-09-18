# Data Marché Résidentiel · DVF

Plateforme d'étude du marché résidentiel (Paris + Boulogne-Billancourt) alimentée par les données DVF de la DGFiP,
servie par GitHub Pages, protégée par un code d'accès.

## Architecture

```
index.html                    ← dashboard (écran de code → déchiffrement local → étude)
data/enc/*.bin, manifest.json ← statistiques chiffrées par niveau (méta, arrondissements, secteurs, zones, quartiers)
data/geo/                     ← référentiel géographique versionné (quartiers.geojson, referentiel.json)
data/dvf_cache.json.gz        ← cache des mutations consolidées par (département, année), avec empreinte de source
scripts/process_dvf.py        ← pipeline : sources → mutations → statistiques (data/dvf_paris.json, non commité)
scripts/build_site.py         ← découpage par niveau + gzip + chiffrement AES-GCM (clé dérivée de DVF_CODE)
scripts/build_geo.py          ← construction manuelle du référentiel géographique (opendata.paris.fr, IGN)
tests/                        ← tests bout en bout sur fixtures HTTP locales + tests du chiffrement
.github/workflows/update-dvf.yml ← run mensuel : ne retélécharge que les sources modifiées, ne commite que si changement
```

## Mise à jour des données

Automatique le 1er de chaque mois. Le script relève l'empreinte (Last-Modified + taille) de chaque fichier source ;
si rien n'a changé, il s'arrête sans rien écrire. Sinon il retraite les seules années modifiées, recalcule les
statistiques, les chiffre et commite `data/enc/`. Lancement manuel : Actions → « Mise à jour DVF » → Run workflow
(`probe` sonde les sources sans rien écrire ; `force` recalcule même sans changement ; `no_cache` retélécharge tout).

## Code d'accès

Secret GitHub `DVF_CODE` (Settings → Secrets and variables → Actions). Le code n'apparaît nulle part dans le dépôt :
il sert à dériver une clé (PBKDF2-SHA256, 200 000 itérations) avec laquelle les statistiques sont chiffrées au build
et déchiffrées dans le navigateur. Pour changer le code : modifier le secret puis lancer le workflow avec `force`.
Localement : `DVF_CODE="…" python scripts/process_dvf.py && DVF_CODE="…" python scripts/build_site.py`.

## Règles de traitement (v13)

Ventes (« Vente » strict, VEFA exclue) d'un logement unique (appartement ou maison), dépendances tolérées, local
professionnel ou second logement → exclu. Surface Carrez si présente et à ±30 % de la surface bâtie, sinon bâtie.
Bornes : 1 000–40 000 €/m², 9–400 m². Chaque exclusion est comptée (`meta.exclusions`). Gardes bloquantes : année
creuse, source partielle, rétention < 25 %, colonnes manquantes, > 2 % de ventes sans quartier.

Géographie : 80 quartiers administratifs de Paris (Ville de Paris) et 10 quartiers de Boulogne (IRIS IGN dissous),
affectation par point-dans-polygone. Niveaux calculés : arrondissements, secteurs (listes de quartiers), zones
officielles d'encadrement des loyers, quartiers.

## Sources

DGFiP « Demandes de valeurs foncières » via Etalab (geo-dvf, opendatarchives) · Ville de Paris (quartiers,
encadrement des loyers) · IGN géoplateforme (IRIS) · Licence Ouverte 2.0.

# Paris Immo · Dashboard DVF automatisé

Dashboard d'analyse des prix immobiliers parisiens, alimenté automatiquement par les données DVF (DGFiP) via GitHub Actions.

## Architecture

```
paris-immo/
├── index.html                    ← Dashboard (GitHub Pages)
├── data/
│   └── dvf_paris.json            ← Données pré-calculées (généré automatiquement)
├── scripts/
│   └── process_dvf.py            ← Script de téléchargement + traitement DVF
└── .github/workflows/
    └── update-dvf.yml            ← Workflow automatisé (2× par an)
```

**Principe :**
1. GitHub Actions télécharge les fichiers TXT DVF Paris depuis `files.data.gouv.fr/geo-dvf/`
2. Le script Python parse, filtre, calcule les statistiques et génère `dvf_paris.json`
3. Le JSON est commité dans le dépôt et servi par GitHub Pages
4. Le dashboard `index.html` charge ce JSON → zéro upload, zéro API externe

---

## Mise en place (20 min, une seule fois)

### Étape 1 — Créer un compte GitHub
👉 https://github.com/signup (gratuit)

### Étape 2 — Créer un nouveau dépôt
1. Cliquez sur **"New repository"**
2. Nom : `paris-immo` (ou ce que vous voulez)
3. Visibilité : **Public** (nécessaire pour GitHub Pages gratuit)
4. Cliquez **"Create repository"**

### Étape 3 — Uploader les fichiers
Dans votre nouveau dépôt, cliquez **"uploading an existing file"** et déposez :
```
index.html
scripts/process_dvf.py
.github/workflows/update-dvf.yml
```
> ⚠ Pour `.github/workflows/`, créez les dossiers manuellement via "Create new file" en tapant `.github/workflows/update-dvf.yml` dans le nom.

### Étape 4 — Activer GitHub Pages
1. Allez dans **Settings → Pages**
2. Source : **Deploy from a branch**
3. Branch : `main` / dossier : `/ (root)`
4. Cliquez **Save**

Votre dashboard sera accessible à :
`https://VOTRE_USERNAME.github.io/paris-immo/`

### Étape 5 — Premier chargement des données (manuel)
1. Allez dans **Actions** (onglet du dépôt)
2. Cliquez sur **"Mise à jour DVF Paris"**
3. Cliquez **"Run workflow"** → **"Run workflow"**
4. Attendez ~5-10 min que le workflow termine (barre verte ✓)

C'est la seule fois où vous devez déclencher manuellement. Ensuite, tout est automatique.

---

## Mise à jour automatique

Le workflow se déclenche automatiquement :
- **15 avril** (après la publication DGFiP d'avril)
- **15 octobre** (après la publication DGFiP d'octobre)

Vous pouvez aussi le déclencher manuellement à tout moment via **Actions → Run workflow**.

---

## Données

- **Source** : DGFiP / Etalab — [Demandes de Valeurs Foncières](https://www.data.gouv.fr/fr/datasets/demandes-de-valeurs-foncieres/)
- **URL de téléchargement** : `https://files.data.gouv.fr/geo-dvf/latest/csv/{annee}/departements/75.csv.gz`
- **Licence** : Licence Ouverte Etalab 2.0 (réutilisation commerciale autorisée)
- **Couverture** : 2019–2024 (5 ans glissants, mis à jour automatiquement)
- **Périmètre** : Paris uniquement (département 75, arrondissements 75101–75120)

## Fonctionnalités du dashboard

- Analyse par **arrondissement** (20) ou **secteur d'encadrement des loyers** (14 secteurs DRIHL)
- Sélection granulaire par pills cliquables
- Filtre par type de bien (Appartement / Maison) et fourchette de prix
- Prix médian, Q1, Q3 par zone
- Évolution annuelle des prix sur la période
- Classement des zones par prix médian décroissant

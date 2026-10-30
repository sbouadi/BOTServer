# Logement Yopougon

Moteur de recherche d'annonces de location à Yopougon (Abidjan), alimenté par les vidéos TikTok et les posts Facebook publics.

## Fonctionnement

```
sources/urls.txt        liens d'annonces ajoutés à la main
sources/discovery.txt   hashtags / comptes TikTok explorés automatiquement
        │
        ▼  pipeline/ingest.py   (GitHub Actions, 2 fois par jour + à chaque modification)
   téléchargement (yt-dlp) → transcription audio (faster-whisper) → lecture du texte des images (Tesseract)
        │
        ▼  data/raw/<id>.json   texte brut par annonce
        │
        ▼  pipeline/extract.py  règles adaptées au vocabulaire ivoirien
   quartier, type (studio, chambre salon…), loyer, caution/avance/agence, équipements
        │
        ▼  site/annonces.json → site/index.html (GitHub Pages)
```

- Les numéros publiés par les annonceurs sont repris avec des boutons Appeler / WhatsApp.
- `sources/quartiers.json` : liste de quartiers **à valider**.
- `sources/corrections.json` : corriger ou masquer une annonce à la main.

## Ajouter des annonces
Ajouter un lien par ligne dans `sources/urls.txt` (même depuis l'app GitHub sur téléphone) : la collecte se relance seule.

## Limites connues
- Le téléchargement depuis TikTok / Facebook dépend de leurs protections anti-robots et de leurs conditions d'utilisation.
- L'extraction par règles rate des formulations inhabituelles ; un modèle de langage (clé API) peut être branché ensuite.

## Alertes Telegram
1. Sur Telegram, écrire à **@BotFather** → `/newbot` → choisir un nom → copier le jeton.
2. GitHub → Settings → Secrets and variables → Actions → **New repository secret** : `TELEGRAM_BOT_TOKEN` = le jeton.
3. Écrire `/start` à son bot. Au passage suivant, le bot confirme puis envoie chaque nouvelle annonce.

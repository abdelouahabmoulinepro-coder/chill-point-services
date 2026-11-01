# Gestion commerciale — Chill Point Services

Application privée de gestion des ventes pour une société de services et de vente de biens.

Le profil est configuré pour **CHILL POINT SERVICES (Maroc)** : devise MAD/DH,
TVA à 20 %, logo moderne, ICE, IF, RC, patente, CNSS et coordonnées bancaires.

## Fonctions disponibles

- répertoire clients ;
- site d’accueil public présentant les services et produits ;
- formulaire public de demande client avec suivi privé ;
- catalogue de services et de biens ;
- devis, factures proforma, factures et bons de livraison ;
- numérotation automatique par année ;
- calcul des remises, TVA, totaux et soldes ;
- conversion devis/proforma → facture et facture → bon de livraison ;
- enregistrement des paiements ;
- tableau de bord commercial ;
- export PDF des documents ;
- sauvegarde complète de la base SQLite ;
- authentification par identifiant et mot de passe Argon2id, limitée au dirigeant ;
- numérotation compatible avec l'historique : `EST-000007`,
  `FA-2026/000006` et `BL-2026/000004` pour les prochains documents de 2026.

## Démarrer l'application

Sous Windows, ouvrez PowerShell dans ce dossier puis lancez :

```powershell
.\.venv\Scripts\streamlit.exe run streamlit_app.py
```

L'application s'ouvre ensuite à l'adresse `http://localhost:8501`.

- site public : `http://localhost:8501/` ;
- espace dirigeant : `http://localhost:8501/admin`.

Sans configuration d’authentification, les données restent verrouillées. Créez
l’identifiant et le mot de passe localement avec :

```powershell
.\.venv\Scripts\python.exe scripts\configurer_acces.py
```

Le mot de passe saisi est masqué et seul son hash Argon2id est enregistré. Pour
la mise en ligne, consultez `DEPLOIEMENT_WEB.md`.

## Données

Les données sont stockées dans `data/gestion.db`. Utilisez régulièrement le bouton de sauvegarde dans la page **Paramètres**.

La branche PostgreSQL conserve ce mode SQLite et ajoute un moteur explicitement
configurable pour Supabase. Consultez `MIGRATION_POSTGRES.md` pour la configuration,
les migrations, les tests et les sauvegardes.

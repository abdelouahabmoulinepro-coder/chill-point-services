# Production Runbook — Chill Point Services

## Secrets locaux séparés

- `.streamlit/secrets.dev.toml` : copie préservée de `chill-point-dev`.
- `.streamlit/secrets.prod-admin.toml` : URI administrateur de `chill-point-prod`,
  utilisée uniquement pour migrations et provisionnement.
- `.streamlit/secrets.prod.toml` : URI du rôle applicatif limité et accès dirigeant.
- `.streamlit/secrets.toml` : configuration active locale.

Tous ces fichiers sont ignorés par Git. Le secret administrateur ne doit jamais
être copié dans Streamlit Community Cloud.

## Préparer Supabase Production

1. Dans Supabase, ouvrir exclusivement le projet **chill-point-prod**.
2. Ouvrir **Project Settings → General** et copier le **Reference ID** dans
   `project_ref` de `.streamlit/secrets.prod-admin.toml`.
3. Cliquer **Connect → Session pooler → URI** et coller l'URI administrateur dans
   `url` du même fichier. Encoder les caractères réservés du mot de passe.
4. Générer l'accès dirigeant sans afficher le mot de passe :

```powershell
.\.venv\Scripts\python.exe scripts\configurer_acces.py --output .streamlit\secrets.prod.toml
```

5. Appliquer le schéma et créer le rôle limité :

```powershell
.\.venv\Scripts\python.exe scripts\migrate_postgres.py --secrets-file .streamlit\secrets.prod-admin.toml
.\.venv\Scripts\python.exe scripts\provision_app_role.py --admin-secrets .streamlit\secrets.prod-admin.toml --runtime-secrets .streamlit\secrets.prod.toml
.\.venv\Scripts\python.exe scripts\production_readiness.py --secrets-file .streamlit\secrets.prod.toml
```

Le provisionnement génère un mot de passe aléatoire pour `chill_point_app`, le
stocke uniquement dans le secret runtime local et n'affiche jamais sa valeur.

## Sauvegarde et restauration

Installer la dépendance locale de chiffrement :

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-backup.txt
```

Définir une phrase de chiffrement d'au moins 20 caractères dans un gestionnaire de
secrets et dans `.streamlit/backup.prod.passphrase` (fichier ignoré), puis lancer :

```powershell
.\.venv\Scripts\python.exe scripts\backup_postgres.py `
  --secrets-file .streamlit\secrets.prod.toml `
  --verify-restore --encrypt `
  --passphrase-file .streamlit\backup.prod.passphrase
```

Le script exécute `pg_dump`, restaure le dump dans PostgreSQL 17 isolé sous Docker,
vérifie la version du schéma, chiffre le dump en AES-256-GCM et écrit une empreinte
SHA-256. Le dump non chiffré est supprimé après chiffrement.

Politique recommandée :

- sauvegarde quotidienne avant 02:00 heure locale ;
- conservation de 7 sauvegardes quotidiennes, 4 hebdomadaires et 12 mensuelles ;
- copie chiffrée sur au moins un stockage hors Supabase et hors du serveur local ;
- phrase de chiffrement conservée séparément des archives ;
- restauration isolée automatique à chaque sauvegarde et exercice manuel mensuel.

Pour déchiffrer une archive vérifiée :

```powershell
.\.venv\Scripts\python.exe scripts\decrypt_backup.py `
  backups\ARCHIVE.dump.enc backups\restore.dump `
  --checksum backups\ARCHIVE.dump.enc.sha256
```

Ne jamais restaurer un dump de développement sur la production.

## Déployer une nouvelle application Streamlit

1. Pousser uniquement `feat/supabase-postgres`, sans force-push.
2. Dans Streamlit Community Cloud, cliquer **Create app**.
3. Sélectionner le dépôt `abdelouahabmoulinepro-coder/chill-point-services`.
4. Sélectionner la branche `feat/supabase-postgres`.
5. Indiquer `streamlit_app.py` comme fichier principal.
6. Dans **Advanced settings**, choisir une version Python supportée (3.12) et
   coller uniquement le contenu de `.streamlit/secrets.prod.toml` dans **Secrets**.
7. Choisir une URL distincte de l'ancienne application et déployer.
8. Vérifier l'accueil, l'écran d'authentification et les pages en lecture seule.

L'URI administrateur, les secrets de développement et la clé Supabase
`service_role` ne doivent jamais être placés dans Streamlit.

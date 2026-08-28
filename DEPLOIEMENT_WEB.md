# Mise en ligne privée

L’application exige un identifiant et un mot de passe avant de charger la base
commerciale. Le mot de passe n’est jamais enregistré en clair : seul un hash
Argon2id salé est conservé dans les secrets de l’application.

## 1. Créer les identifiants du dirigeant

Depuis le dossier du projet, lancez :

```powershell
.\.venv\Scripts\python.exe scripts\configurer_acces.py
```

Choisissez un identifiant et une phrase de passe d’au moins 15 caractères. La
saisie du mot de passe reste invisible. Le programme crée automatiquement
`.streamlit/secrets.toml`, qui est exclu de Git et de l’image Docker.

Après cinq erreurs successives, toutes les nouvelles tentatives sont bloquées
pendant cinq minutes. Une actualisation complète ou la fermeture du navigateur
demande une nouvelle connexion.

## 2. Configurer l’hébergement

Le projet inclut `Dockerfile` et `compose.yaml`. Sur le serveur :

1. installez Docker ;
2. placez `.streamlit/secrets.toml` dans le dossier du projet sans le publier ;
3. montez `/app/data` sur un disque persistant ;
4. activez HTTPS sur le domaine public ;
5. démarrez le service avec `docker compose up -d --build`.

Avant la première mise en ligne, copiez la base actuelle `data/gestion.db` dans
le volume persistant. Ensuite, utilisez régulièrement le téléchargement de
sauvegarde disponible dans la page Paramètres.

> Streamlit Community Cloud ne garantit pas la conservation des fichiers locaux.
> Pour utiliser cette plateforme, il faut migrer SQLite vers une base persistante
> externe. Un hébergement Docker avec volume persistant conserve l’architecture
> actuelle.

## 3. Vérifications avant ouverture

- l’URL publique utilise HTTPS ;
- le mot de passe contient au moins 15 caractères et n’est pas réutilisé ailleurs ;
- `.streamlit/secrets.toml` n’est ni dans Git ni dans l’image Docker ;
- cinq mauvais essais provoquent bien le blocage temporaire ;
- la déconnexion masque immédiatement toutes les pages ;
- le volume de données et les sauvegardes sont persistants.

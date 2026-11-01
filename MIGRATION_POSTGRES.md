# Migration PostgreSQL / Supabase

Cette branche conserve SQLite pour Docker/VPS et ajoute PostgreSQL comme moteur
explicitement sélectionné. Il n'existe aucun basculement automatique entre les
deux moteurs.

## 1. Configuration locale

Le fichier `.streamlit/secrets.toml` est ignoré par Git. Renseignez vous-même la
section suivante sans communiquer sa valeur dans une conversation ou un rapport :

```toml
[database]
backend = "postgres"
url = "COLLER_ICI_L_URI_SESSION_POOLER_IPV4"
```

Utilisez l'URI **Session pooler** copiée depuis le bouton **Connect** de Supabase.
Le code impose au minimum TLS avec `sslmode=require`. Pour `verify-full`, ajoutez
le paramètre correspondant et configurez le certificat racine Supabase.

Pour revenir au développement SQLite local :

```toml
[database]
backend = "sqlite"
url = ""
```

## 2. Installation et schéma

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts\migrate_postgres.py
.\.venv\Scripts\python.exe scripts\check_postgres.py
```

Les migrations sont versionnées dans `migrations/postgres`. Le démarrage de
l'application vérifie la version du schéma mais ne lance aucune migration.

## 3. Tests fictifs PostgreSQL

Les tests d'intégration ne s'exécutent que sur activation explicite :

```powershell
$env:RUN_POSTGRES_TESTS = "1"
.\.venv\Scripts\python.exe -m unittest tests.test_postgres_integration -v
Remove-Item Env:RUN_POSTGRES_TESTS
```

Ils créent uniquement des clients et documents clairement identifiés comme
fictifs. Ils ne suppriment ni ne tronquent aucune table.

## 4. Analyse et import SQLite

Travaillez toujours à partir d'une copie cohérente et vérifiée de la base réelle,
jamais directement sur une base en cours d'utilisation.

Analyse sans écriture :

```powershell
.\.venv\Scripts\python.exe scripts\migrate_sqlite_to_postgres.py --source C:\chemin\sauvegarde.db
```

L'option `--execute` importe dans une destination ne contenant aucune donnée
métier. Les identifiants, relations et séquences sont conservés, puis les comptes
et totaux financiers sont comparés dans la même transaction. Cette option ne doit
être utilisée qu'après le GO PRODUCTION spécifique.

## 5. Sauvegarde et retour arrière

- Le forfait Supabase Free exige une sauvegarde logique externe régulière.
- Utilisez `pg_dump` avec une connexion dédiée et conservez les dumps chiffrés
  hors de Supabase.
- Testez la restauration dans une autre base avant toute bascule.
- Un retour de code ne doit pas revenir vers une SQLite vide. Tant que le schéma
  reste compatible, restaurez la version précédente du code en gardant PostgreSQL.
- Un changement de fournisseur exige la restauration du dernier dump PostgreSQL
  puis la reprise des écritures réalisées après le point de sauvegarde.

## 6. Secrets Streamlit Community Cloud

Après un GO staging ou production, recopiez la section `[database]` dans la
console **App settings → Secrets** de l'application concernée. Ne commitez jamais
le fichier local et n'utilisez pas de clé `service_role` : l'application se
connecte directement à PostgreSQL avec un rôle applicatif limité.

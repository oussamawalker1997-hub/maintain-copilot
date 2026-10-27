# PostgreSQL — premier jalon de migration

PostgreSQL est disponible comme backend optionnel de l’API. **SQLite reste le mode par défaut.** Aucun ticket, clé ou document SQLite n’est importé automatiquement et aucun basculement silencieux n’est effectué.

## Mise en route Windows

Préconditions : Docker Desktop en mode Linux, Git synchronisé et venv existant. Depuis la racine du dépôt :

```powershell
& .\.venv\Scripts\python.exe scripts\postgres_local.py prepare
docker compose -f compose.postgres.yaml up -d --wait
docker compose -f compose.postgres.yaml ps
& .\.venv\Scripts\python.exe scripts\postgres_local.py migrate
& .\.venv\Scripts\python.exe scripts\postgres_local.py migrate
& .\.venv\Scripts\python.exe scripts\postgres_local.py verify
```

Résultats : `POSTGRES_SECRETS_READY` (ou `ALREADY_PRESENT`), service healthy, migrations OK deux fois, puis `POSTGRES_FOUNDATION_OK`. Si une commande échoue, examiner sa sortie avant de poursuivre. Ne jamais supprimer le volume comme première réponse à un incident.

## Activer une démonstration API PostgreSQL distincte

Après les migrations et `verify`, installer les dépendances mises à jour :

```powershell
& .\.venv\Scripts\python.exe -m pip install -r requirements.lock
& .\.venv\Scripts\python.exe -m pip install --no-deps -e .
& .\.venv\Scripts\python.exe -m pip check
```

Dans ce terminal uniquement, choisir PostgreSQL et provisionner sa démonstration :

```powershell
$env:MAINTAIN_BACKEND = "postgres"
& .\.venv\Scripts\python.exe -m maintain.cli seed-postgres
```

Résultat : `POSTGRES_DEMO_READY`. La commande refuse toute base métier déjà remplie et tout
fichier de clés PostgreSQL existant. Les entrées DE-A/DE-B laissées par `verify` sont acceptées.
Elle utilise le compte administrateur uniquement pour ce provisionnement explicite.
Les trois comptes utilisateurs ont de **nouvelles clés**, sous
`.local/postgres/demo-credentials.json`. Les anciennes clés SQLite restent dans
`.local/demo-credentials.json` et ne fonctionnent pas sur cette nouvelle démonstration.
Ouvrir le nouveau fichier localement pour saisir une clé dans l'interface ; ne pas le partager.

```powershell
& .\.venv\Scripts\python.exe -m maintain.cli serve --port 8001
```

Ouvrir `http://127.0.0.1:8001`. Le port distinct évite de confondre les deux instances.
Depuis un deuxième terminal :

```powershell
Invoke-RestMethod http://127.0.0.1:8001/healthz
$env:MAINTAIN_BACKEND = "postgres"
& .\.venv\Scripts\python.exe -m maintain.cli dispatch
```

La santé doit indiquer `storage: postgres`. Tester E042 sur NW-P17 et NW-P18, E099,
le firmware absent, puis un ticket confirmé et son envoi simulé. Les API/UI et règles
métier sont communes aux deux backends. Le classement lexical PostgreSQL peut différer
car son moteur n'est pas BM25/FTS5 ; aucune équivalence de qualité n'est revendiquée.

Pour revenir à SQLite, arrêter ce serveur avec Ctrl+C puis :

```powershell
Remove-Item Env:MAINTAIN_BACKEND -ErrorAction SilentlyContinue
& .\.venv\Scripts\python.exe -m maintain.cli serve
```

Il n'y a aucune reprise des données historiques à cette étape. Ne pas supprimer SQLite.
Le backup PostgreSQL et la reprise vérifiée sont des jalons distincts. Ne pas lancer les
tests d'intégration destructifs sur l'instance de démonstration : leur opt-in est réservé
à la CI jetable, sur le port 25432. L'architecture et ses limites : [ADR-002](adr/002-postgres-api.md).

## Stockage et secrets

Le projet Compose `maintain-postgres` est distinct du Compose de l’application. Le port est publié uniquement sur `127.0.0.1:15432`. Les données résident dans le volume nommé de ce projet. L’image officielle cible PostgreSQL 17 (`17-bookworm`) ; le digest n’est pas encore figé, donc le mineur exact peut évoluer. Avant un pilote, figer l’image qualifiée et définir les mises à jour.

Trois mots de passe aléatoires sont générés sous `.local/postgres`, répertoire ignoré par Git. Les valeurs ne sont jamais imprimées ni placées en argument de commande côté hôte. Les secrets sont montés en fichiers. Sur POSIX, leur dossier est privé (0700) ; les fichiers sont lisibles par l’UID PostgreSQL via leur montage. Sur Windows, ces bits ne prouvent pas la protection des ACL : conserver le projet dans le profil privé du compte. Les administrateurs Docker/hôte peuvent accéder aux secrets et aux volumes ; ils font partie de la frontière de confiance.

Ne pas afficher les secrets, les envoyer dans une capture, ou exécuter des commandes qui exportent la configuration avec leurs valeurs. `prepare` ne remplace jamais des clés existantes. Un répertoire incomplet demande une revue ; changer un fichier de mot de passe ne change pas un rôle déjà initialisé.

## Réparation des secrets Windows CRLF

Une ancienne version de `prepare` écrivait des fins de ligne CRLF sous Windows.
Sur une instance déjà initialisée, mettre le dépôt à jour puis exécuter :

```powershell
& .\.venv\Scripts\python.exe scripts\postgres_local.py repair-passwords
```

Cette commande de développement utilise la socket locale du conteneur et son accès
administrateur existant. Elle réaligne les trois mots de passe sur les 64 caractères
hexadécimaux des secrets montés, dans une transaction, puis vérifie les trois connexions
TCP. Elle conserve les fichiers, rôles, privilèges et données. Elle peut être relancée.
Elle ne s'applique pas à un serveur distant ou à des mots de passe personnalisés.
Reprendre ensuite `migrate` deux fois et `verify`. Les nouveaux secrets sont écrits
avec LF sur tous les systèmes ; les lecteurs acceptent LF et CRLF.

## Rôles et isolation

| Rôle | Utilisation | Limite |
|---|---|---|
| `maintain_admin` | Initialisation et orchestration locale des migrations | Superuser ; jamais le compte de l’API |
| `maintain_owner` | Propriétaire du schéma et des tables | NOLOGIN, pas de BYPASSRLS |
| `maintain_runtime` | Groupe des privilèges applicatifs | NOLOGIN, aucune identité de site |
| `maintain_site_a` | Connexion applicative de DE-A | Site A seulement |
| `maintain_site_b` | Connexion applicative de DE-B | Site B seulement |

Les politiques RLS sont activées et forcées pour toutes les tables métier. Leur contexte est dérivé de `current_user`, avec correspondance de rôles fixe. Une valeur `site` fournie par un client ou un simple paramètre de session ne change pas cette identité. Les clés étrangères composites `(site, id)` empêchent les relations entre sites. Le runtime n’a ni propriété des tables, ni DDL, ni TRUNCATE ; l’audit autorise lecture/insertion mais pas modification/suppression.

Ce modèle couvre deux sites de démonstration. Le passage à de nombreux sites, le pooling et le choix du compte après authentification API demandent un ADR avant intégration. Ce n’est pas une isolation du système contre un administrateur PostgreSQL, le backend possédant tous les secrets, ou les canaux auxiliaires des séquences et contraintes. Les permissions technicien/éditeur et la propriété des runs restent des règles API à préserver lors du basculement.

## Migrations

Les SQL sont sous `migrations/postgres`. Le runner applique un verrou consultatif et une transaction par fichier, inscrit version/checksum/date dans `maintain.schema_migrations` et refuse une migration appliquée dont le checksum a changé. Les fins de ligne sont normalisées par lecture UTF-8. Toute évolution après application exige une nouvelle migration, pas l’édition du fichier 001.

Le script d’initialisation des rôles s’exécute uniquement sur volume vide, comportement de l’image officielle. Une erreur à cette étape ne se corrige pas automatiquement en relançant le conteneur avec un volume partiellement initialisé. Préserver les données et diagnostiquer les logs localement sans partager les secrets.

## Vérifications réelles

`verify` se connecte par TCP avec chaque vrai compte de site. Il contrôle version/encodage, privilèges, RLS forcée, visibilité, jointures, recherche plein texte, caractères UTF-8, insert/update/delete intersites, refus de TRUNCATE, refus d’usurpation du rôle B et refus de désactivation RLS. Il crée des fixtures identifiées par UUID et les nettoie dans un bloc finally ; les deux entrées de catalogue DE-A/DE-B peuvent rester. Il ne lit ni n’écrit la base SQLite.

Lancer ces vérifications uniquement dans cette instance de développement. Les tests de requêtes ne constituent ni un audit complet, ni un benchmark de charge. L’adaptateur API optionnel dispose de tests sur serveur réel. Les prochains jalons sont la reprise explicite et vérifiée des données, le backup/restauration PostgreSQL et une évaluation comparative plus large avant basculement.

## Arrêt

```powershell
docker compose -f compose.postgres.yaml stop
```

Pour reprendre : `docker compose -f compose.postgres.yaml up -d --wait`. La suppression des volumes est réservée aux environnements CI jetables et ne figure pas dans cette procédure locale.

## Références officielles

Consultées le 27 octobre 2026 :

- https://www.postgresql.org/docs/17/ddl-rowsecurity.html
- https://hub.docker.com/_/postgres
- https://docs.docker.com/guides/postgresql

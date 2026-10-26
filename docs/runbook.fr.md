# Exploitation locale et incidents

## Démarrer et vérifier

Depuis le dossier du projet : lancer `python -m maintain.cli serve` avec le Python du venv ; vérifier `http://127.0.0.1:8000/healthz`. L’API s’arrête avec Ctrl+C. Le worker de simulation n’est pas un daemon : exécuter `python -m maintain.cli dispatch` à la demande. L’application ne reçoit aucun trafic externe nécessaire.

## Sauvegarde cohérente

```powershell
.\.venv\Scripts\python.exe -m maintain.cli backup .local\backups\before-change.sqlite
```

Utilise l’API de sauvegarde SQLite, pas une copie brute d’un fichier pendant une écriture WAL. Le nom de destination doit être nouveau. La sauvegarde inclut documents, runs, observations de tickets et hashes de credentials : traiter le fichier comme privé. Aucune rotation automatique n’est incluse.

## Restauration de test

1. Arrêter le serveur.
2. Choisir un nouveau chemin de base, sans écraser l’original.
3. Copier la sauvegarde vers ce chemin ; ne pas publier ni envoyer ce fichier.
4. Lancer `python -m maintain.cli --database <chemin> serve`.
5. Vérifier santé, recherche E042, accès des deux sites et nombre de tickets.

Attention : une sauvegarde peut rétablir des documents révoqués ou des clés désactivées après sa création. Cette version ne maintient pas de registre externe de tombstones. Toute restauration doit rester locale et être réconciliée manuellement avant réutilisation. RPO/RTO du pilote non démontrés.

## Incident : plus de résultats

Vérifier actif, matériel, firmware et publication. Si E099 est inconnu, l’abstention est attendue. Si document révoqué, l’historique doit refuser la réutilisation. Ne pas contourner les filtres pour obtenir une réponse. Reproduire sur fixtures avant changement de code.

## Incident : ticket en attente ou bloqué

Pending : exécuter le dispatch. Blocked : vérifier que l’acteur reste actif et que toutes les sources du run restent publiées/applicables. Rechercher de nouveau et faire confirmer un nouveau ticket ; ne pas changer le statut directement en base pour simuler une livraison réussie.

## Incident : clé locale compromise

Arrêter le serveur si nécessaire. Désactiver le principal via une opération locale contrôlée sur la base, puis provisionner une nouvelle clé et un nouveau hash via un script revu. La rotation administrative en CLI n’est pas incluse dans cette première tranche. Ne pas réexécuter seed sur la base existante ; ne pas envoyer les clés dans un ticket GitHub.

## Logs et données

Le logger `maintain.requests` émet route normalisée, code, durée et trace ID sans question, source ou token. Le lancement par CLI désactive les access logs Uvicorn pour éviter les URL non maîtrisées. L’audit SQL n’est pas inviolable : le propriétaire de la base peut le modifier. Runs et observations n’ont pas encore de politique de purge automatique. Aucune donnée réelle d’entreprise avant le jalon sécurité.

## Incident : accents corrompus dans les sources

Arrêter le serveur puis exécuter `python scripts/repair_windows_utf8.py` avec le Python du venv depuis la racine. Le script sauvegarde la base et les sources modifiées sous `.local/encoding-backups/`, refuse le contenu personnalisé et réimporte seulement les fixtures originales en UTF-8. Clés, IDs, statuts et tickets sont conservés. Relancer les recherches : les anciennes captures de runs restent historiques. Garder les sauvegardes privées.

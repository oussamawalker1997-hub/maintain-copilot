# Parcours de réalisation A à Z

Le dossier de mission est la cible. La version 0.1 est une première tranche complète de baseline, pas le système final. L’exigence professionnelle vient des preuves et des décisions justifiées, pas du nombre de frameworks.

| Jalon | État | Livrable et critère de sortie |
|---|---|---|
| J0 — Cadrage et sources | Partiel | Mission, 5 documents originaux et 10 questions présents ; entretiens et corpus réaliste à obtenir |
| J1 — Tranche B0 | Réalisé sur corpus synthétique | Installation, interface, actifs, recherche avec références, tests d’accès |
| J2 — Données et autorisation | Partiel | Brouillon/quarantaine/publication/révocation présents ; PostgreSQL optionnel, migrations et RLS testés ; reprise/restore et parser isolé à réaliser |
| J3 — Retrieval et RAG | À réaliser | B1 hybride évalué face à B0, puis B2 avec citations et abstention ; aucun modèle choisi sans mesure |
| J4 — Parcours métier | Partiel | Confirmation/outbox/simulateur présents ; connecteur GMAO distant et reconciliation à valider |
| J5 — Exploitation | Partiel | CI, trace IDs, limites et backup présents ; quotas globaux, traces distribuées, tombstones, charge et restauration pilote à terminer |
| J6 — Validation | Partiel | Tests techniques et smoke publics présents ; 80 dev/200 finaux indépendants, double annotation, avis métier et essais utilisateurs manquants |
| J7 — Livraison et GitHub | Publié et CI vérifiée | Dépôt public et contrôles Linux/Windows/PostgreSQL ; qualification pilote à poursuivre |

## Prochaine séance concrète

1. Télécharger le projet, l’extraire et effectuer le quick start Windows du README.
2. Exécuter les quatre parcours E042 ancien/nouveau matériel, E099 et firmware absent.
3. Lancer les tests ; comprendre pourquoi une ancienne version est parfois encore applicable.
4. Ouvrir `retrieval.py` et expliquer la différence entre une correspondance lexicale et une réponse sémantique.
5. Documenter trois échecs lexicaux réels sans modifier le jeu final. Ils guideront le choix de B1.

## Itération suivante : PostgreSQL et B1

Fondation PostgreSQL ajoutée : Compose séparé, rôles par site, schéma SQL versionné, RLS forcée et vérification par connexions TCP réelles. Guide : `docs/postgres.fr.md`. L’API optionnelle est raccordée avec contrats métier partagés, HTTP réel et tests de concurrence. La reprise des données, la restauration et une comparaison plus large restent des critères de sortie ; J2 reste partiel.

- Migrer le schéma vers PostgreSQL via migrations versionnées, avec même contrat API et tests d’intégration sur vraie instance.
- Ajouter RLS sur chaque table métier et tester avec un rôle runtime sans privilèges de propriétaire/BYPASSRLS. Inclure les fichiers et les jointures.
- Séparer les permissions des métadonnées documentaires ; revalider avant restitution et effets externes.
- Ajouter extraction isolée en worker, jobs observables et données d’applicabilité validées.
- Implémenter un adaptateur d’embeddings, recherche hybride et reranking. Fixer versions et tailles après benchmark.
- Comparer B0/B1 sur un jeu dev plus riche, avec latence et couverture. Sans amélioration documentée, conserver B0.

## Ensuite : B2 génératif

Seulement après le retrieval : adaptateur fournisseur interchangeable, sorties structurées, références validées, budget de tokens, timeouts, abstention et fallback B0. Les extraits ne sont pas des instructions pour le modèle. Tester injection, citation correcte mais conclusion fausse, contexte incomplet et révocation pendant génération. Demander une clé fournisseur uniquement au moment d’un essai réel ; ne jamais l’inscrire dans Git.

## Preuve pour candidatures

Présentation actuelle honnête : « Développement d’un démonstrateur de recherche documentaire pour maintenance industrielle, avec filtrage des variantes, contrôle d’accès par site, cycle documentaire et tickets idempotents ; tests automatisés et baseline reproductible sur données synthétiques. »

Ne pas écrire « déployé en usine », « réduit les arrêts de 30 % », « RAG en production » ou « conformité RGPD certifiée » sans preuve correspondante. Le CV sera mis à jour après chaque jalon vérifié.

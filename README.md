# Poker Engine

Dépôt persistant du projet de moteur d'analyse poker.

## Déploiement

- [Consulter le déploiement Cloudflare de production](https://dash.cloudflare.com/335073663ad947e69fb7590bc22b5e73/workers/services/view/poker-engine/production)

## Organisation

- `user/` : fichiers directement utiles à l'utilisateur (versions exécutables, documentation, exports).
- `src/` : code source et composants du moteur.
- `training/` : données, registres, résultats et modèles liés à l'apprentissage/calibration continue.
- `tests/` : jeux de non-régression et benchmarks.
- `tools/` : scripts et utilitaires techniques.
- `.project/` : état de travail persistant destiné aux outils/assistants (`STATUS`, `PLAN`, `HANDOFF`, conventions). Ce dossier n'est pas un livrable utilisateur.

## Principe de reprise

Toute nouvelle session de travail doit commencer par lire :

1. `.project/STATUS.md`
2. `.project/PLAN.md`
3. `.project/HANDOFF.md`
4. `training/registry.json`

Ces fichiers constituent la source de vérité sur l'état courant du projet.

## Entraînement continu

Les entraînements/calibrations sont append-only au niveau des résultats : chaque run reçoit un identifiant, conserve ses entrées, paramètres, métriques et artefacts, puis peut promouvoir un modèle/version comme référence. Un nouvel entraînement ne doit jamais faire disparaître l'historique qui permet de comprendre ou reproduire les décisions précédentes.

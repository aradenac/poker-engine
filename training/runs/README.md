# Training runs

Chaque sous-dossier représente un run d'entraînement ou de calibration immuable.

Structure recommandée :

- `manifest.json` : provenance, sélection des données et split ;
- `source/` : source exacte utilisée par le run ;
- `data/` : décisions/données dérivées reproductibles ;
- `artifacts/` : overlays et sorties intermédiaires ;
- `evaluation/` : métriques, benchmarks et non-régression ;
- `models/` : modèles candidats produits par le run, y compris les candidats rejetés.

La promotion d'un modèle se fait uniquement via `training/registry.json`; un run terminé n'est jamais écrasé.

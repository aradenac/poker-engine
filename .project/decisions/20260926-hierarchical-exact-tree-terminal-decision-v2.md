# Décision terminale #419 v2 — arbre exact hiérarchique

- Décision : `UNRESOLVED_HIERARCHICAL_TREE_GAP`
- Statut : `BLOCKED_SCIENTIFIC` (admission forcée : non)
- Candidat : `model-a-preflop-sizing-hierarchical-candidate-v1` (`637302885b8119e6b0246d827462c36eb707c6e234d0b652483c956f03360999`), non admis
- `required_tree_complete` = `false` (0/38 nœuds admissibles, tous les autres `EXACT_UNRESOLVED`)
- Blockers : `NO_ADMISSIBLE_POOLING_LEVEL`, `UNRESOLVED_RAISE_SIZING_FRONTIER`, `REFUSED_CALIBRATION`, `REFUSED_COVERAGE_FLOOR`
- Composition : préflight v2 TRAIN-only (`analysis/issue419_hierarchical_tree/exact_tree_preflight_v2/EXACT_TREE_PREFLIGHT_V2.json`) + octets v1 de `analysis/issue419_hierarchical_tree/validation/VALIDATION_RESULT.json` référencés par digest (`0b92e5a78ab3ee4cb581c33be351d6b52bcf4fcd8741ab907ebd6dd32ec6ef68`) — aucune seconde lecture du holdout, aucun recalcul de métrique
- `validation_consumed` = `true` (une seule lecture, via le protocole gelé T6), `test_consumed` = `false`, `active_pointer_mutated` = `false`
- `next_issue` = `367` ; #367 n’est jamais lancé par #419

La DECISION v1 (`analysis/issue419_hierarchical_tree/terminal_decision/DECISION.json`, `9425f30163dcfa5e0a72ca8f6dd1bb4b6a25ce270b4a894aaa57e898a74bd0bc`) reste byte-identique : elle est revérifiée octet par octet et jamais réécrite ; `--revision v1` est refusé. Le candidat hiérarchique reste distinct de #352 v2 et n’est pas câblé au provider #367. Aucun seuil, prior ou limite de pooling n’a été modifié après la lecture VALIDATION, et les entrées gelées (spec T2, protocole T6, baseline T1, `ARTIFACTS.json`/`SUMMARY.md` racine, pointer actif) sont inchangées.

Bundle content-adressé : `analysis/issue419_hierarchical_tree/terminal_decision_v2/` (`DECISION_V2.json`, `SUMMARY.md`, `N8N_TASK_RESULT.txt`, `ARTIFACTS.json`).

Reproduce: `python3 tools/training/finalize_hierarchical_exact_tree_decision.py --revision v2`; verify: `python3 tools/training/finalize_hierarchical_exact_tree_decision.py --check`.

# Décision terminale #419 — arbre exact hiérarchique

- Décision : `UNRESOLVED_HIERARCHICAL_TREE_GAP`
- Statut : `BLOCKED_SCIENTIFIC` (admission forcée : non)
- Candidat : `model-a-preflop-sizing-hierarchical-candidate-v1` (`637302885b8119e6b0246d827462c36eb707c6e234d0b652483c956f03360999`), non admis
- `required_tree_complete` = `false` (0/38 nœuds admissibles, tous les autres `EXACT_UNRESOLVED`)
- Blockers : `REQUIRED_TREE_INCOMPLETE`, `UNRESOLVED_RAISE_SIZING_FRONTIER`, `VALIDATION_GATES_FAILED`
- `validation_consumed` = `true` (une seule lecture, via le protocole gelé T6), `test_consumed` = `false`, `active_pointer_mutated` = `false`
- `next_issue` = `367` ; #367 n’est jamais lancé par #419

Le candidat hiérarchique reste distinct de #352 v2 et n’est pas câblé au provider #367. Aucun seuil, prior ou limite de pooling n’a été modifié après la lecture VALIDATION, et les entrées gelées (spec T2, protocole T6, baseline T1, `ARTIFACTS.json`/`SUMMARY.md` racine, pointer actif) sont inchangées.

Bundle content-adressé : `analysis/issue419_hierarchical_tree/terminal_decision/` (`DECISION.json`, `SUMMARY.md`, `N8N_TASK_RESULT.txt`, `ARTIFACTS.json`).

Reproduce: `python3 tools/training/finalize_hierarchical_exact_tree_decision.py`; verify: `python3 tools/training/finalize_hierarchical_exact_tree_decision.py --check`.

# Rapport d'intégration v2 (#419, T7) — bundle de preuves content-adressé

- Bundle : `analysis/issue419_hierarchical_tree_v2/` (`poker-hierarchical-integration-report/v2`), écrit et vérifié par `tools/training/build_hierarchical_integration_bundle_v2.py` (mode `--check`)
- Statut : `BLOCKED_SCIENTIFIC` — décision `UNRESOLVED_HIERARCHICAL_TREE_GAP`, candidat `model-a-preflop-sizing-hierarchical-candidate-v1` (`637302885b8119e6b0246d827462c36eb707c6e234d0b652483c956f03360999`), non admis
- `required_tree_complete` = `false` (0 nœud admissible sur 38 ; blockers `NO_ADMISSIBLE_POOLING_LEVEL`, `UNRESOLVED_RAISE_SIZING_FRONTIER`, `REFUSED_CALIBRATION`, `REFUSED_COVERAGE_FLOOR`)
- `validation_consumed` = `true` (une seule lecture gelée, référencée par digest `0b92e5a78ab3ee4cb581c33be351d6b52bcf4fcd8741ab907ebd6dd32ec6ef68`, aucune seconde lecture), `test_consumed` = `false`, `active_pointer_mutated` = `false`, `hero_ev_executed` = `false`, `issue367_run` = `false`, `next_issue` = `367`

Le bundle est complet et content-adressé : cinq copies octet-pour-octet des autorités T1/T3/T4/T8/T7 (`HIERARCHICAL_MODEL_SPEC.json`, `TRAIN_FIT_REPORT.json`, `CANDIDATE_MANIFEST.json`, `EXACT_TREE_PREFLIGHT_V2.json`, `DECISION_V2.json`), deux références par digest sans duplication d’octets (`FROZEN_VALIDATION_PROTOCOL_V2.json` → `74b8a006…`, `VALIDATION_RESULT.json` → `0b92e5a7…`), le rapport machine-lisible `INTEGRATION_REPORT.json`, son rendu `INTEGRATION_REPORT.md`, `SUMMARY.md`, `N8N_TASK_RESULT.txt`, le sidecar `INTEGRATION_REPORT.sha256` et l’index `ARTIFACTS.json`. Aucun index amont ne liste ce répertoire.

## Ce que le rapport revendique, et ce qu’il refuse de revendiquer

Aucune preuve CI réelle n’existe pour #419 : `ci_proven_claims` est vide, le bundle T5 (`analysis/issue419_hierarchical_tree/ci_evidence/CI_EVIDENCE.json`, `764b7f6d…`) porte `ci_observation.status = NOT_OBSERVED`, le workflow `Execute issue 419 hierarchical exact tree` n’a jamais tourné, et les cinq runs CI réels enregistrés à la tête de revue `d087b5c…` (`#153`, `#257`, `#627`, `#977`, `#976`, avec leurs URL) n’exécutent aucune suite #419. Le rapport les cite avec leurs URL précisément parce qu’ils sont réels, et parce qu’aucun ne porte la preuve. Tout le reste est consigné comme observation locale non autoritative, avec son code de sortie — y compris les deux vérifications rouges.

## Supersessions documentées

1. `SUPERSEDED_V2_PROTOCOL_PAYLOAD_508A31EC` : l’ancien payload v2 du protocole `508a31ec8072a72ca573f65ac6b748e1ce5e67c639fd4388e472153b7ffa4320` (canonique `a97391d2…`) est remplacé par l’amendement `V2_AMENDMENT_1_CONDITIONAL_NODE_CLOSURE` (`74b8a006…`, canonique `cb598a9f…`) ; aucun seuil et aucune porte ne bougent, l’ancien payload reste content-adressé sous `validation_protocol_v2/history/`.
2. `V1_EXACT_TREE_PREFLIGHT_REGENERATION` : le commit mutant `871e0bd` (task `backlog-sd5`) a réécrit `exact_tree_preflight/EXACT_TREE_PREFLIGHT.json` en place vers `e86b7c6b…` (canonique `d027391f…`, index `4fea09fc…`) ; la correction d’intégrité `c904524` (`issue419-evidence-integrity-correction-v1`, `f601d619…`) a restauré `456d85be…` (canonique `fc08988f…`, index `97e90eac…`) sans toucher aux pins et sans réécrire un octet gelé pour faire coller un digest.

Conséquences résiduelles, rapportées et non réparées ici : `V1_PREFLIGHT_PIN_STALE` et `PROTOCOL_V2_PREFLIGHT_PIN_STALE`. Le commit `887e46a` (task `backlog-agg`) a repointé les pins gelés de l’outil préflight — `V1_PREFLIGHT_SHA256` / `V1_INDEX_SHA256` (`e86b7c6b…` / `4fea09fc…` au lieu de `456d85be…` / `97e90eac…`) et `PROTOCOL_V2_BYTE_SHA256` / `PROTOCOL_V2_CANONICAL_PAYLOAD_SHA256` (`db1b1ab6…` / `e80732c4…` au lieu de `74b8a006…` / `cb598a9f…`) — si bien que `python3 tools/simulation/issue419_exact_tree_preflight.py --check` **et** `tests/simulation/test_issue419_exact_tree_preflight.py` (5 échecs, 7 erreurs) sont rouges. La réparation appartient à la tâche préflight : le digest de l’outil est épinglé par le payload T8 et par la décision terminale T9, donc l’éditer ici reviendrait à réécrire une surface gelée que cette tâche n’a pas le droit de toucher. `write_frozen_validation_protocol.py --check` est rouge pour la raison attendue et documentée (garde d’ordre : la VALIDATION a déjà été lue une fois).

## Déclenchement CI

Le bundle vit sous `analysis/issue419_hierarchical_tree_v2/**`, hors du glob de déclenchement existant. Le workflow `issue-419-hierarchical-exact-tree.yml` reçoit donc ce nouveau glob (push et pull_request), comme le garde de couverture des chemins #419 l’exige ; `analysis/workflow_audit/active_workflow_dag_v2.json` et `analysis/workflow_audit/consolidation_decision_v1.json` sont régénérés par `tools/audit_active_workflow_dag.py --write`. Les octets du workflow diffèrent donc de ceux que T5 avait enregistrés (`375a0cda…`) : T5 n’est pas réécrit, et l’écart est déclaré comme finding `WORKFLOW_BYTES_CHANGED_BY_THIS_TASK`.

## Bornes

Aucun octet gelé n’est réécrit (32 fichiers protégés re-vérifiés avant/après), TEST reste non consommé et non autorisé, le pointeur actif Model A v5 (`ff952055…`) est inchangé, aucune hand history n’est ouverte (tripwire d’exécution + scan AST), aucun symbole du runner Hero EV de #367 n’est référencé, et #367 n’est pas lancé.

Reproduce: `python3 tools/training/build_hierarchical_integration_bundle_v2.py`; verify: `python3 tools/training/build_hierarchical_integration_bundle_v2.py --check`; suite: `PYTHONPATH=. python3 tests/training/test_issue419_hierarchical_exact_tree.py`.

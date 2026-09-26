# #419 — integration bundle v2 summary

**BLOCKED_SCIENTIFIC / UNRESOLVED_HIERARCHICAL_TREE_GAP** — candidate `model-a-preflop-sizing-hierarchical-candidate-v1` (`637302885b8119e6b0246d827462c36eb707c6e234d0b652483c956f03360999`) is **not** admitted and **not** wired into #367.

Bundle `analysis/issue419_hierarchical_tree_v2` (`poker-hierarchical-integration-report/v2`), task `backlog-oso` (T7). Members: 7 authorities bound by byte + canonical digest — 5 as byte-identical copies and 2 as digest references — plus `INTEGRATION_REPORT.json`, `INTEGRATION_REPORT.md`, `SUMMARY.md`, `N8N_TASK_RESULT.txt` and the `ARTIFACTS.json` index.

`required_tree_complete=false` — 0 of 38 required nodes are admissible; primary blocker `NO_ADMISSIBLE_POOLING_LEVEL`. VALIDATION published `RETAIN_ACTIVE_REFERENCE` (failing gates: coverage_floor, calibration_absolute).

CI: `ci_observation.status = NOT_OBSERVED` — the authoritative workflow has never run and none of the 5 real recorded CI runs executes a #419 suite. `ci_proven_claims` is empty; everything else in this bundle is local, non-authoritative. The real run IDs, with URLs, are listed in `INTEGRATION_REPORT.md` §3.1 and in `ci_evidence.recorded_runs`.

Boundaries: `validation_consumed=true` (single frozen read, referenced by digest `0b92e5a78ab3ee4cb581c33be351d6b52bcf4fcd8741ab907ebd6dd32ec6ef68`), `test_consumed=false`, `active_pointer_mutated=false`, `hero_ev_executed=false`, `issue367_run=false`, `next_issue=367`.

Supersessions: the v2 protocol payload `508a31ec8072a72ca573f65ac6b748e1ce5e67c639fd4388e472153b7ffa4320` is superseded by `74b8a006ae84f8b9b22913ef76977e95f08992feb9765639a46d1ac49eb87350` through `V2_AMENDMENT_1_CONDITIONAL_NODE_CLOSURE`; the `v1 EXACT_TREE_PREFLIGHT.json` bytes were rewritten by mutant `871e0bd` to `e86b7c6b57d170c0885f46734c41302dcc15608252dfbbd66bff62c258d5c65f` and restored to `456d85be57b910d3a56cb0160ba0ba35c988f7f69da9f965f0a887aaac473ae6` by correction `c904524`, leaving the residual `V1_PREFLIGHT_PIN_STALE` and `PROTOCOL_V2_PREFLIGHT_PIN_STALE` findings documented in `INTEGRATION_REPORT.md` §5.

```
N8N_TASK_RESULT
active_pointer_mutated: false
admitted: false
blockers: NO_ADMISSIBLE_POOLING_LEVEL,UNRESOLVED_RAISE_SIZING_FRONTIER,REFUSED_CALIBRATION,REFUSED_COVERAGE_FLOOR
bundle: analysis/issue419_hierarchical_tree_v2
candidate_id: model-a-preflop-sizing-hierarchical-candidate-v1
candidate_sha256: 637302885b8119e6b0246d827462c36eb707c6e234d0b652483c956f03360999
ci_status: NOT_OBSERVED
decision: UNRESOLVED_HIERARCHICAL_TREE_GAP
hero_ev_executed: false
integration_ready: false
issue: 419
issue367_run: false
next_issue: 367
primary_blocker: NO_ADMISSIBLE_POOLING_LEVEL
required_tree_complete: false
required_tree_sha256: 0ab232ae44e4157e2a47d4d3d611ac8ca9c2cdb54caf2568f256f6df35643a25
status: BLOCKED_SCIENTIFIC
test_consumed: false
validation_consumed: true
validation_outcome: RETAIN_ACTIVE_REFERENCE
validation_reference_sha256: 0b92e5a78ab3ee4cb581c33be351d6b52bcf4fcd8741ab907ebd6dd32ec6ef68
```

Reproduce: `python3 tools/training/build_hierarchical_integration_bundle_v2.py`; verify: `python3 tools/training/build_hierarchical_integration_bundle_v2.py --check`.

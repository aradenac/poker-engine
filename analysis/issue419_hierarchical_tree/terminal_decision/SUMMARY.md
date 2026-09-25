# #419 — terminal decision: hierarchical exact-tree candidate

**UNRESOLVED_HIERARCHICAL_TREE_GAP** — status `BLOCKED_SCIENTIFIC`, admitted: `false`.

Candidate `model-a-preflop-sizing-hierarchical-candidate-v1` (canonical payload `637302885b8119e6b0246d827462c36eb707c6e234d0b652483c956f03360999`) is the frozen TRAIN-fit hierarchical Model-A candidate of T4. It is **not** admitted and it is **not** wired into #367: admission requires a complete exact tree *and* an `ADMIT_CANDIDATE` VALIDATION result, and neither holds.

T8 preflight: `required_tree_complete=false` — 0 of 38 required nodes carry an admissible exact answer at `hierarchical_exact_key` / `L0_EXACT_KEY`, so all 38 required nodes stay `EXACT_UNRESOLVED`. T5 left 7 raise-sizing frontiers unresolved. T7 VALIDATION returned `RETAIN_ACTIVE_REFERENCE` with failing frozen gates ['coverage_floor', 'calibration_absolute'].

## Blockers

* `REQUIRED_TREE_INCOMPLETE` (SCIENTIFIC_DATA) — the required #388/#419 response tree is not complete: no node carries an admissible exact answer at hierarchical_exact_key / L0_EXACT_KEY
* `UNRESOLVED_RAISE_SIZING_FRONTIER` (SCIENTIFIC_STRUCTURAL) — raise-sizing frontiers stay unresolved: no exactly supported raise target exists at the frozen #367 structural node and no representative price may substitute it
* `VALIDATION_GATES_FAILED` (SCIENTIFIC_EVIDENCE) — one or more frozen VALIDATION gates failed; the active Model A v5 pointer stays unchanged

## Holdout and pointer discipline

VALIDATION was consumed once, through the frozen T6 protocol, by the T7 evaluation (`validation_consumed=true`). TEST stays unconsumed and unauthorized (`test_consumed=false`). No threshold, prior, pooling limit or comparator was changed after the read. The active Model A pointer (`training/models/preflop_population_model_v5.json`), the registries, the reference model, the root `ARTIFACTS.json`/`SUMMARY.md` and the frozen protocol bytes are unchanged (`active_pointer_mutated=false`). The #367 Hero EV runner was neither imported nor executed (`hero_ev_executed=false`, `issue367_run=false`).

## Bundle

This terminal bundle (`analysis/issue419_hierarchical_tree/terminal_decision/`) carries the decision, this summary, the n8n block and one content-addressed index. `ARTIFACTS.json` binds every required artifact by byte SHA256, canonical payload SHA256 and content-addressed object: `HIERARCHICAL_MODEL_SPEC.json`, `TRAIN_FIT_REPORT.json`, `FROZEN_VALIDATION_PROTOCOL.json`, `CANDIDATE_MANIFEST.json`, `VALIDATION_RESULT.json`, `EXACT_TREE_PREFLIGHT.json`, `DECISION.json`, `SUMMARY.md`. Supporting evidence: `HIERARCHICAL_TREE_SPARSITY_BASELINE.json`, `RAISE_SIZING_FRONTIER_RESOLUTION.json`. The upstream bundles stay in place and are never rewritten (`frozen_inputs_untouched`).

Reproduce: `python3 tools/training/finalize_hierarchical_exact_tree_decision.py`; verify: `python3 tools/training/finalize_hierarchical_exact_tree_decision.py --check`.

## n8n output

```text
N8N_TASK_RESULT
active_pointer_mutated: false
admitted: false
blockers: REQUIRED_TREE_INCOMPLETE,UNRESOLVED_RAISE_SIZING_FRONTIER,VALIDATION_GATES_FAILED
candidate_id: model-a-preflop-sizing-hierarchical-candidate-v1
candidate_sha256: 637302885b8119e6b0246d827462c36eb707c6e234d0b652483c956f03360999
decision: UNRESOLVED_HIERARCHICAL_TREE_GAP
hero_ev_executed: false
issue: 419
issue367_run: false
next_issue: 367
primary_blocker: REQUIRED_TREE_INCOMPLETE
required_tree_complete: false
required_tree_sha256: 0ab232ae44e4157e2a47d4d3d611ac8ca9c2cdb54caf2568f256f6df35643a25
status: BLOCKED_SCIENTIFIC
test_consumed: false
validation_consumed: true
validation_outcome: RETAIN_ACTIVE_REFERENCE
```

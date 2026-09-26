# #419 — terminal decision v2: hierarchical exact-tree candidate

**UNRESOLVED_HIERARCHICAL_TREE_GAP** — status `BLOCKED_SCIENTIFIC`, admitted: `false`.

Candidate `model-a-preflop-sizing-hierarchical-candidate-v1` (canonical payload `637302885b8119e6b0246d827462c36eb707c6e234d0b652483c956f03360999`) is the frozen TRAIN-fit hierarchical Model-A candidate. It is **not** admitted and it is **not** wired into #367: admission requires a complete exact tree *and* an `ADMIT_CANDIDATE` VALIDATION result, and neither holds.

This v2 decision is composed of exactly two constituents: the TRAIN-only exact-tree preflight v2 (`analysis/issue419_hierarchical_tree/exact_tree_preflight_v2/EXACT_TREE_PREFLIGHT_V2.json`, byte SHA256 `2c07ae3279d10ec3e3bbdbe81cdb0d0f1f23e6bbb91cbdadddae113d1a9ea691`) and the **already-consumed** v1 VALIDATION result bytes, referenced **by digest** (`analysis/issue419_hierarchical_tree/validation/VALIDATION_RESULT.json`, byte SHA256 `0b92e5a78ab3ee4cb581c33be351d6b52bcf4fcd8741ab907ebd6dd32ec6ef68`). No holdout is re-opened: no hand history is parsed, no validation decision row is read, no metric is recomputed and no threshold is re-selected.

preflight v2: `required_tree_complete=false` — 0 of 38 required nodes carry an admissible exact answer at `hierarchical_exact_key` / `L0_EXACT_KEY`, so all 38 required nodes stay `EXACT_UNRESOLVED` (31 of them on `NO_ADMISSIBLE_POOLING_LEVEL` and 7 on `RAISE_SIZING_UNRESOLVED_NO_NEAREST_PRICE`). T5 left 7 raise-sizing frontiers unresolved, explicitly `independent_of_the_response_model=true`. T7 VALIDATION returned `RETAIN_ACTIVE_REFERENCE` with failing frozen gates ['calibration_absolute', 'coverage_floor'].

## Blockers

* `NO_ADMISSIBLE_POOLING_LEVEL` (SCIENTIFIC_DATA) — the required #388/#419 response tree is not complete: 0 of the required nodes carry an admissible exact answer at hierarchical_exact_key / L0_EXACT_KEY and every node stays EXACT_UNRESOLVED. The dominant unresolved reason is NO_ADMISSIBLE_POOLING_LEVEL (31 of 38 nodes); a fail-closed node is never repaired by lowering a frozen threshold
* `UNRESOLVED_RAISE_SIZING_FRONTIER` (SCIENTIFIC_STRUCTURAL) — raise-sizing frontiers stay unresolved: no exactly supported raise target exists at the frozen #367 structural node and no representative price may substitute it. The frontier is structural -- a property of the required tree, not of the response model -- so it is flagged independent_of_the_response_model=true and changing the response model cannot close it
* `REFUSED_CALIBRATION` (SCIENTIFIC_EVIDENCE) — the frozen layer-B calibration gate is refused from the digest-referenced v1 VALIDATION bytes: pooled ECE 0.135209 > maximum_absolute_ece 0.05 and 0 of 40 reliability bins meet the minimum support (minimum_bin_support_for_a_calibration_claim=20). No threshold was re-selected and no metric was recomputed: the verdict is read from the published, already-consumed VALIDATION result
* `REFUSED_COVERAGE_FLOOR` (SCIENTIFIC_EVIDENCE) — the published VALIDATION coverage floor fails: 9 identifiable decisions and 9 distinct hands against the frozen required_decisions=200 / required_hands=100; a claim below the identifiable-support floor is never treated as supportable

## Holdout and pointer discipline

VALIDATION was consumed once, through the frozen T6 protocol, by the original T7 evaluation (`validation_consumed=true`). This v2 decision does **not** consume it again: the v1 VALIDATION result is referenced by digest, its digest is re-derived from the persisted bytes, and every value it contributes is a *published* row of that artifact (`no_new_holdout_read`). TEST stays unconsumed and unauthorized (`test_consumed=false`). No threshold, prior, pooling limit or comparator was changed after the read. The active Model A pointer (`training/models/preflop_population_model_v5.json`), the registries, the reference model, the root `ARTIFACTS.json`/`SUMMARY.md` and the frozen protocol bytes are unchanged (`active_pointer_mutated=false`). The #367 Hero EV runner was neither imported nor executed (`hero_ev_executed=false`, `issue367_run=false`).

## Frozen v1 revision

The v1 terminal decision (`analysis/issue419_hierarchical_tree/terminal_decision/DECISION.json`, byte SHA256 `9425f30163dcfa5e0a72ca8f6dd1bb4b6a25ce270b4a894aaa57e898a74bd0bc`, canonical payload `9b6aec99feeeb9c49424172f31a2d4657d8cf67cab2b80d2bbf66ecd22c261f5`) remains **byte-identical**: it is re-verified byte-for-byte on every build and every `--check`, and it is never rewritten. Its `source_files_sha256` records the superseded v1 tool, which no longer exists on disk, so a byte-identical re-derivation is impossible by construction and `--revision v1` is refused.

## Bundle

This terminal bundle (`analysis/issue419_hierarchical_tree/terminal_decision_v2/`) carries the decision, this summary, the n8n block and one content-addressed index. `ARTIFACTS.json` binds every required artifact by byte SHA256, canonical payload SHA256 and content-addressed object: `EXACT_TREE_PREFLIGHT_V2.json`, `VALIDATION_RESULT.json`, `DECISION.json`, `HIERARCHICAL_MODEL_SPEC.json`, `TRAIN_FIT_REPORT.json`, `CANDIDATE_MANIFEST.json`, `FROZEN_VALIDATION_PROTOCOL.json`, `HIERARCHICAL_TREE_SPARSITY_BASELINE.json`, `RAISE_SIZING_FRONTIER_RESOLUTION.json`, `EXACT_TREE_PREFLIGHT.json`, `DECISION_V2.json`, `SUMMARY.md`. The upstream bundles stay in place and are never rewritten (`frozen_inputs_untouched`).

Reproduce: `python3 tools/training/finalize_hierarchical_exact_tree_decision.py --revision v2`; verify: `python3 tools/training/finalize_hierarchical_exact_tree_decision.py --check`.

## n8n output

```text
N8N_TASK_RESULT
active_pointer_mutated: false
admitted: false
blockers: NO_ADMISSIBLE_POOLING_LEVEL,UNRESOLVED_RAISE_SIZING_FRONTIER,REFUSED_CALIBRATION,REFUSED_COVERAGE_FLOOR
candidate_id: model-a-preflop-sizing-hierarchical-candidate-v1
candidate_sha256: 637302885b8119e6b0246d827462c36eb707c6e234d0b652483c956f03360999
decision: UNRESOLVED_HIERARCHICAL_TREE_GAP
hero_ev_executed: false
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

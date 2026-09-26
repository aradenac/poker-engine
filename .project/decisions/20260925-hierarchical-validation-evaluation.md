# Hierarchical Model A candidate — frozen VALIDATION evaluation — 2026-09-25

Decision owner: issue #419. The machine-readable source of truth is
`analysis/issue419_hierarchical_tree/validation/VALIDATION_RESULT.json`
(`poker-hierarchical-validation-result/v1`), produced exactly once by
`tools/training/validate_hierarchical_validation.py --run` and content-addressed
with its byte digest, its canonical payload digest and its own
`evidence_sha256`. This record states what the reader must not have to
reconstruct from the JSON.

## Decision 1 — the T6 protocol was executed, not re-frozen

The evaluation command re-verified the pinned protocol bytes
(`69c99a8b37589f1687b7e980344c9a79d69bbcd45be0a53ffd59bfea0ab583b3`) and re-ran
`VALIDATION_ORDER_GUARD` **before** a single VALIDATION hand was parsed. It then
re-pinned the candidate (`637302885b8119e6b0246d827462c36eb707c6e234d0b652483c956f03360999`)
and both comparators by digest, and refused to run if any of them had drifted.
No threshold, pooling limit, prior, comparator or hyper-parameter was changed:
the recorded `thresholds` and `pooling_limits` are byte-equal to the frozen
protocol's, and the persisted protocol bytes are unchanged after the read.

## Decision 2 — measured coverage and calibration

Of the 11,490 in-scope focus-family VALIDATION decisions, the frozen TRAIN fit
answers 9 (`EXACT_HIERARCHICAL_ESTIMATE`, all at `L3_RUNTIME_SUPPORT_CONTEXT`);
the other 11,481 fail closed (`NO_ADMISSIBLE_POOLING_LEVEL`). Of the 9,854
decisions where both exact-price comparators are defined, only 2 are also
answered by the candidate, so the paired predictive comparison runs on those 2
decisions: candidate log-loss `0.319684`, active Model A v5 `0.585614`,
#352 v2 `0.319684`.

All 38 pinned required-tree nodes stay `EXACT_UNRESOLVED`
(`share_exact_hierarchical_estimate = 0.0`), reconciled with the persisted TRAIN
fit report. All 7 raise-sizing frontiers stay explicitly unresolved.

## Decision 3 — the outcome is RETAIN_ACTIVE_REFERENCE

Two frozen gates fail on the measured evidence: `coverage_floor` (9 identifiable
decisions / 9 hands against the frozen 200 / 100 floor) and
`calibration_absolute` (pooled ECE `0.135209` above the frozen `0.05`, and zero
reliability bins reach the frozen minimum bin support of 20). The paired
non-inferiority and calibration-delta measurements are reported but are not
supportable below the frozen identifiable-support floor. `no_partial_admission`
therefore holds: the active Model A v5 pointer is unchanged
(`active_model_replaced=false`), promotion is not automatic and the outcome
admits nothing.

## Decision 4 — TEST stays unconsumed and the evaluation is single-shot

`test_consumed=false`, `test_authorized=false`, `test_hands_parsed=0` and
`test_decisions_read=0`. The command statically refuses every known TEST/holdout
loader symbol, and the certified loader fails closed on any non-VALIDATION row.
Because the candidate VALIDATION result now exists, the T6 order guard reports
the consumption and aborts a second `--run` (and
`write_frozen_validation_protocol.py --check`) with `VALIDATION_ORDER_GUARD`;
that is the intended fail-closed behaviour, not a regression. The frozen
protocol payload itself is byte-identical, as its own regression re-proves by
replaying the pre-freeze order-guard evidence.

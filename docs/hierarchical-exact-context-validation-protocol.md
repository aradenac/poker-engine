# Frozen VALIDATION protocol for the hierarchical Model A candidate

Issue #419, task `backlog-p0g`. The machine-readable source of truth is
`analysis/issue419_hierarchical_tree/FROZEN_VALIDATION_PROTOCOL.json`
(`poker-hierarchical-frozen-validation-protocol/v1`), content-addressed in
`analysis/issue419_hierarchical_tree/validation_protocol/` and pinned by
`analysis/issue419_hierarchical_tree/FROZEN_VALIDATION_PROTOCOL.sha256`.

Frozen digest at this revision:
`69c99a8b37589f1687b7e980344c9a79d69bbcd45be0a53ffd59bfea0ab583b3`
(canonical payload `f283ce8dac9fbcfb5485eeb360217af4425fe947f249de652b03d96a13d40db5`),
`frozen_at` `2026-09-25T00:00:00Z`, status `FROZEN_BEFORE_VALIDATION`.

Reproduce with `python3 tools/training/write_frozen_validation_protocol.py`;
verify with `python3 tools/training/write_frozen_validation_protocol.py --check`.
The protocol pins the generator's and the guard's own file hashes, so editing
either tool changes the protocol digest: regenerate and update the digest above
(a test enforces the match).

This document explains the protocol; it is not itself normative. The JSON wins.
The protocol **admits nothing by itself**: it fixes the rules, the thresholds and
the comparators before the VALIDATION holdout is opened.

## 1. Why an order guard exists

Reading VALIDATION before freezing the protocol would let the thresholds,
comparators and pooling limits be chosen to fit the observed holdout score.
`tools/training/validation_order_guard.py` therefore owns one shared ordering
rule:

- the **freeze-side** guard (`assert_validation_not_yet_consumed`) aborts the
  freeze when a VALIDATION result that references the hierarchical candidate
  already exists — either at a declared result location, or anywhere under
  `analysis/**/*.json` as a result-shaped payload that declares a VALIDATION read
  and names the candidate;
- the **evaluation-side** guard (`assert_protocol_frozen_before_validation`)
  re-verifies the pinned protocol bytes before a single VALIDATION hand is
  opened, so `thresholds` and `pooling_limits` cannot be edited after the freeze.

Scope is deliberately narrow. The #352 exact-price candidate already consumed
the VALIDATION split under its own frozen protocol. That is recorded in
`holdout_boundary.predecessor_validation_reads` as a *different* candidate and is
neither repaired nor treated as a violation of this candidate's ordering rule.

## 2. Explicit comparators

`comparators` lists exactly three models, never an implicit default:

| Role | Model | Identity |
| --- | --- | --- |
| `ACTIVE_REFERENCE` | `active-model-a-preflop-v5` | `ff952055ca4ee051a3ac9607d513fdecac0a320a31f658ecfd8a11d8448975ca` |
| `ADMITTED_EXACT_PRICE_COMPARATOR` | `model-a-preflop-sizing-aware-candidate-v2` (#352) | `9115165c3141d16152946dd1ee7a049f219fef1a1d79c0e1c7b1249c45326f19` |
| `CANDIDATE_UNDER_TEST` | `model-a-preflop-sizing-hierarchical-candidate-v1` (TRAIN fit) | `637302885b8119e6b0246d827462c36eb707c6e234d0b652483c956f03360999` |

The #352 comparator carries its full evidence pinning: the fit artifact byte hash
and its selected prior strength, the frozen #352 VALIDATION protocol digest, and
the admitted VALIDATION evidence digest (`ADMIT_CANDIDATE`, `test_consumed=false`,
`active_model_replaced=false`). The active reference is hashed before and after
the freeze and is never mutated.

## 3. Frozen thresholds and pooling limits

Thresholds stay the spec's: 20 marginal observations and 20 distinct hands for any
exact claim, plus the frozen VALIDATION gates — at least 200 identifiable
decisions and 100 distinct hands, paired candidate-minus-comparator 95% CI upper
bound `<= 0`, pooled ECE `<= 0.05` and ECE delta versus the active reference
`<= 0.02`. Abstention is not a failure: fail-closed `EXACT_UNRESOLVED` decisions
are reported and excluded from the predictive gates rather than defaulting to
FOLD, and a lower coverage than the active reference never justifies relaxing a
frozen support threshold.

Pooling limits are equally frozen. `SUPPORT_ISOLATION_NO_KEY_BORROWS_SUPPORT`
means a key A may never be declared supported by observations of a different key
B: `L0_EXACT_KEY` is the only support source and the deepest level for an exact
support claim, while `L4_POSITION_PRICE_PRIOR` is the deepest level allowed for a
*reported estimate*. The shrinkage strength is fixed at `kappa0 = 16` with
`alpha = 0.5` per legal marginal action. A decision answered above L0 is labelled
`EXACT_HIERARCHICAL_ESTIMATE` and never counted as exact support.

## 4. Requirement manifest

`requirement_manifest` pins all 38 nodes of the #388 required tree to
`required_tree_sha256`
`0ab232ae44e4157e2a47d4d3d611ac8ca9c2cdb54caf2568f256f6df35643a25`, including
the 7 unresolved raise-sizing frontiers. Each row carries the node path, the
`runtime_support_context_key`, the `audit_exact_key` and the
`runtime_exact_preflop_node_key`, plus a `manifest_canonical_sha256` so node drift
is detectable. Every node must be answered or fail closed; zero counts never
prune a branch.

## 5. The #367 rule

`issue367_rule.rule_id = ISSUE367_CONSUMES_ONLY_AN_ADMITTED_CANDIDATE` answers the
authorize-or-forbid question exactly. At freeze time the answer is **forbidden**:
no #367 real ISO EV run, no exact-support grid extension and no provider wiring
may consume this candidate while it is unresolved. A #367 consumption becomes
authorized only when the frozen VALIDATION evaluation returns `ADMIT_CANDIDATE`
with every gate passing, the result is content-addressed with its embedded
`protocol_byte_sha256`, and a new explicit #367 protocol revision names this
candidate's id and canonical digest. Until then #367 keeps
`model-a-preflop-sizing-aware-candidate-v2` as its admitted model, unchanged.

## 6. Output schema

`output_schema` fixes the future VALIDATION result
(`poker-hierarchical-validation-result/v1` at
`analysis/issue419_hierarchical_tree/validation/VALIDATION_RESULT.json`): required
fields, the outcome enum `ADMIT_CANDIDATE` / `RETAIN_ACTIVE_REFERENCE`, the
per-decision fields every answered decision must carry, the fixed flags
(`test_consumed=false`, `production_effect=NONE`, `active_model_replaced=false`,
`automatic_promotion=false`), and the rule that the result must embed both the
protocol byte digest and its canonical payload digest.

## 7. After the evaluation (T7)

The result now exists:
`analysis/issue419_hierarchical_tree/validation/VALIDATION_RESULT.json`, written
once by `tools/training/validate_hierarchical_validation.py --run` and verified by
`--check`. Its verdict is `RETAIN_ACTIVE_REFERENCE`: the frozen `coverage_floor`
and `calibration_absolute` gates fail on the measured evidence, so the active
Model A v5 pointer, the thresholds, the pooling limits and the #367 boundary are
all unchanged. TEST was never parsed.

Two consequences are expected rather than defects. First, the T6 order guard now
reports the consumed holdout, so a second `--run` and
`write_frozen_validation_protocol.py --check` abort with
`VALIDATION_ORDER_GUARD`: the protocol was frozen *before* the read and that
ordering cannot be replayed after it. Second, the protocol payload itself is
byte-identical to the frozen revision — its regression suite re-proves this by
replaying the pre-freeze order-guard evidence — so no threshold can have been
edited after the read.

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

## 8. Versioned revision v2 (two layers)

The single frozen protocol above is split into two explicitly named layers by a
**separately versioned, content-addressed revision**:

`analysis/issue419_hierarchical_tree/validation_protocol_v2/FROZEN_VALIDATION_PROTOCOL_V2.json`
(`poker-hierarchical-frozen-validation-protocol/v2` at
`analysis/issue419_hierarchical_tree/validation_protocol_v2/`, digest
`74b8a006ae84f8b9b22913ef76977e95f08992feb9765639a46d1ac49eb87350`, canonical
payload `cb598a9fc2353aa78f19a7263a62a8ccbdba60eb400264787e896d0c232f19de`).
Its schema name, artifact name and file name are all distinct from v1. This is
the **amended** v2 payload: the earlier v2 revision
`508a31ec8072a72ca573f65ac6b748e1ce5e67c639fd4388e472153b7ffa4320`
(canonical `a97391d2678d66a46cc7a8d2d0893a509c9c2564a5c420f4519d21c05216dd16`)
is superseded by amendment `V2_AMENDMENT_1_CONDITIONAL_NODE_CLOSURE` and kept
byte-for-byte content-addressed under
`validation_protocol_v2/history/508a31ec8072a72ca573f65ac6b748e1ce5e67c639fd4388e472153b7ffa4320.json`
(+ `.sha256`); the `amendments` / `revision_history` blocks of the payload cite
that digest.

The revision is **additive and interpretive**, not a re-freeze. It records the v1
byte digest
`69c99a8b37589f1687b7e980344c9a79d69bbcd45be0a53ffd59bfea0ab583b3`, the v1
canonical payload digest
`f283ce8dac9fbcfb5485eeb360217af4425fe947f249de652b03d96a13d40db5`, the v1
generator digest and every frozen v1 surface digest (the digest sidecar, the
`validation_protocol/` bundle, the consumed `VALIDATION_RESULT.json`, the T8
preflight and the terminal decision), and re-verifies all of them from the
persisted bytes on every build and every `--check`. The v1 bytes are
byte-identical; the revision adds no threshold, weakens no gate and admits
nothing.

Because the v1 payload pins `tools/training/write_frozen_validation_protocol.py`,
editing that generator would change a pinned digest and break the
pre-registration. The revision therefore has its own generator,
`tools/training/write_frozen_validation_protocol_v2.py`, which reads the v1 bytes
and never rewrites them.

### Layer A — exact empirical support, unchanged

`EXACT_EMPIRICAL_STRONG` keeps its label, its `L0_EXACT_KEY`-only condition and
both frozen thresholds (20 marginal observations and 20 distinct hands). Support
is never borrowed: `SUPPORT_ISOLATION_NO_KEY_BORROWS_SUPPORT` with
`support.source_key == requested_key`. No pooled estimate may be relabelled as
exact support, and no threshold may be lowered.

### Layer B — exact-context estimate admissibility

`EXACT_HIERARCHICAL_ESTIMATE` answers for the *same* exact requested key. The
fine key identity is preserved (the never-mutualizable axes
`requested_key_identity`, `actor_position`, `aggressor_position`,
`target_total_bb` and `to_call_bb` are retained at every level); the support
counts remain that key's own rows (possibly zero); pooling is strictly
parametric over the declared parent levels `L1..L4` (`kappa0 = 16`,
`alpha = 0.5` per legal marginal action) and is never a support source. The
estimate is admissible only with its effective sample size, its uncertainty band
at the level actually used, its pooling provenance (`pooling.level`,
`pooling.source_key` and the pooling source counts), and the calibration, pooling
and sizing obligations met. The gate list itself is carried over from v1
(`gates.gates_sha256` equals the v1 gate digest); it is not re-frozen here.

### Three statuses and the node consumption rule

The three statuses stay a closed enum with no implicit default:
`EXACT_EMPIRICAL_STRONG` (exact support, layer A),
`EXACT_HIERARCHICAL_ESTIMATE` (admissible estimate, layer B) and
`EXACT_UNRESOLVED` (fail-closed). `CONSUME_ONLY_AN_ADMISSIBLE_NODE_ANSWER` fixes
when a node's answer may be consumed: an exact-support answer may be consumed as
exact support only at `L0_EXACT_KEY` with both thresholds met; a hierarchical
estimate may be consumed only as an estimate with its pooling level, effective
sample size and uncertainty shown, and is never counted as exact support; an
`EXACT_UNRESOLVED` node is consumable as nothing and is never replaced by FOLD,
zero mass, a pruned branch or a nearest/representative price.

Node closure is now explicit and **conditional**. The superseded revision said a
node answering `EXACT_HIERARCHICAL_ESTIMATE` "does not close the node"; the
amendment replaces that flat rule with `NODE_CLOSES_IFF_ALL_FROZEN_LAYER_B_GATES_PASS`:
a required node closes **if and only if** every frozen layer-B admissibility gate
passes, and stays open otherwise with the failing gate reported. The seven
machine-readable gates and their refusal reason codes are
`REFUSED_EXACT_KEY_IDENTITY`, `REFUSED_POOLING_PROVENANCE`,
`REFUSED_POOLING_LEVEL`, `REFUSED_EFFECTIVE_SAMPLE_SIZE`, `REFUSED_UNCERTAINTY`,
`REFUSED_CALIBRATION` and `REFUSED_RAISE_SIZING_FRONTIER`. No threshold and no
gate value moved: every gate value is equal to or stricter than its v1
homologue (`non_loosening_vs_v1`). Closing the tree still requires **every**
required node to close and no raise-sizing frontier to stay unresolved, and the
#367 rule (`ISSUE367_CONSUMES_ONLY_AN_ADMITTED_CANDIDATE`) is unchanged.

Reproduce the revision with
`python3 tools/training/write_frozen_validation_protocol_v2.py`; verify with
`python3 tools/training/write_frozen_validation_protocol_v2.py --check`.
`tests/training/test_frozen_validation_protocol_v2.py` re-derives the v1
immutability, the two layers, the unchanged thresholds and the consumption rule.

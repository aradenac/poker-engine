# Generalized opponent response model (preflop, public-only)

Issue #421. The machine-readable source of truth is
`analysis/issue421_generalized_response/GENERALIZED_RESPONSE_MODEL_SPEC.json`
(`poker-generalized-response-model-spec/v1`), content-addressed as
`analysis/issue421_generalized_response/sha256/21a16986dd9410c044b1593ffc2426d0fb3fcbaf7b0e1aac25544e5dcb646816.json`
and pinned by
`analysis/issue421_generalized_response/GENERALIZED_RESPONSE_MODEL_SPEC.sha256`.
The ten required artifacts are bound by
`analysis/issue421_generalized_response/ARTIFACTS.json`; the human summary is
`analysis/issue421_generalized_response/SUMMARY.md`
(`f797f789734bdffe7a1082068a3bfc1fe05f081f6669d134a153f0d6e7f23193`). This
document explains the spec and the cycle; it is not itself normative. The JSON
wins, and the spec digest is recorded outside its own payload.

Reproduce: `python3 tools/training/build_issue421_evidence_bundle.py`.
Verify: `python3 tools/training/build_issue421_evidence_bundle.py --check`.
Guard: `python3 tests/training/test_issue421_evidence_bundle.py`.

## 1. What changed relative to exact-cell lookup

Model A's likelihood answered only where an exact support cell existed: #388
qualified 3 of the 38 required nodes at the runtime support key, and the finer
exact key of #419 closed 0 of 38 (`31 NO_ADMISSIBLE_POOLING_LEVEL`, 7 unresolved
raise-sizing frontiers). #421 replaces that lookup with a learned function

`P(action = FOLD | CALL | RAISE | JAM | public preflop response context, price, stack, history, requested sizing)`

evaluated **directly at the requested context**. There is no nearest-price,
nearest-context, representative-price or legal-minimum substitution, and no
hidden-hand imputation or pseudo-observation; a request that leaves the
calibrated domain abstains fail-closed instead of snapping to a neighbour.

The model is trained on adverse (non-Hero) preflop responses of the certified
population `pokerstars_nlhe_100-200_zoom_play_6max_v1`: 94160 TRAIN response
rows over 19016 hands, strictly `BEFORE_ACTION`, public fields only.

## 2. Inputs, representation and estimator

The response row (`contracts/training/generalized-response-dataset.schema.json`)
carries only public, pre-action information: family, actor and aggressor
position, limper/caller counts, live positions, raise level, `to_call_bb`,
`pot_before_bb`, `pot_odds`, `price_to_pot`, `effective_stack_bb` and, when a
raise is queried, `target_total_bb`. Revealed cards, board, history, Hero flag
and future actions are forbidden keys and are rejected by the row guard.

The estimator is a `regularized_additive_multinomial_log_linear` over
`log1p` piecewise-linear (partition-of-unity) splines on `to_call_bb`,
`pot_before_bb`, `effective_stack_bb` and the sizing ratio
`target_total_bb / (pot_before_bb + to_call_bb)`, plus capped categorical blocks
and a small set of weighted interaction cells with a support floor. Illegal
actions are masked before normalisation, so the four action probabilities always
sum to one with zero mass on illegal actions. A second architecture
(`hierarchical_empirical_bayes_dirichlet`) is implemented and compared on the
same run.

Everything is Python standard library: the frozen estimator, the sizing spline
and the OOD thresholds are closed-form. The recorded seed (421) only pins
observation ordering, fold assignment and tie-breaking; no sampling occurs, so
the same context and config give the same prediction byte for byte.

## 3. Uncertainty / OOD gate

Each answer carries one of `MODEL_SUPPORTED`,
`MODEL_SUPPORTED_HIGH_UNCERTAINTY` or `MODEL_OOD_ABSTAIN`. Hard reasons
(`UNSEEN_CATEGORY`, `EXTRAPOLATION_STACK`, `EXTRAPOLATION_SIZING`,
`EXTRAPOLATION_PRICE`, `MISSING_DOMAIN_AXIS`) abstain; soft reasons (local
support, robust domain distance, spline boundary, predictive entropy, fitted
node support) only raise the status to high uncertainty. The thresholds are read
off pooled out-of-fold TRAIN signal tails and frozen before VALIDATION: a
context whose exact cell was never observed while every single-feature label is
in-domain is **not** out-of-domain by definition.

## 4. Conditional raise sizing

Sizing is a separate conditional density over the legal window
(`min_raise_to = max(2*current_bet - max(commitment, BB), current_bet + BB)`,
cap at `max_raise_to_bb` or the effective stack). It reports support and
uncertainty per query, generates quantiles, and fails closed with a reason code
when the window is empty below the stack — it never substitutes a nearest price.
All seven #388/#419 raise-sizing frontiers are resolved by this channel in the
frozen report, with zero illegal generated sizings.

## 5. Evaluation, freeze and one-shot VALIDATION

Selection is TRAIN-only, hand-grouped five-fold cross-validation
(`TRAIN_CV_REPORT.json`, no hand in two folds, preregistered criteria,
out-of-fold evidence only). The candidate, features, hyperparameters, seeds, OOD
gate, metrics, thresholds, non-inferiority rule, calibration ceiling and
sizing criteria are then frozen by hash in `CANDIDATE_MANIFEST.json` and
`FROZEN_VALIDATION_PROTOCOL.json` (`FROZEN_BEFORE_VALIDATION`, written before
any VALIDATION row is read). `VALIDATION_RESULT.json` was produced by one frozen
read of the certified VALIDATION fold; no threshold moved afterwards.

Outcome at this revision: coverage `1.0` (LIMPER_VS_ISO `1.0`, abstention `0.0`),
log loss `1.2689828317` vs active v5 `1.2677704885`, ECE `0.0362278552` vs active
`0.0147432394`. Two frozen gates fail — non-inferiority vs the active Model A
population (paired CI upper `0.0069549188 > 0`) and the calibration delta
(`0.0214846158 > 0.02`) — so the terminal decision is
**`RETAIN_REFERENCE_GENERALIZATION_INSUFFICIENT`** (`8/10` criteria). The
active Model A reference is retained; nothing is promoted.

Generalization strata on VALIDATION: frequent exacts 87.10% (log loss 1.2958),
rare exacts 10.57% (1.0316), exact-context-absent-but-in-domain 2.32% (1.3427,
ECE 0.0949). The rare and exact-absent rows are answered by the learned
function rather than abstained, so the coverage is not a lookup artefact.

## 6. #367 preflight

`ISSUE367_PREFLIGHT.json` walks the 38 required scenario #321 nodes and the 7
raise-sizing frontiers through the runtime provider, recording per node the
action distribution, OOD status, uncertainty and provenance. Every visited node
is either directly evaluated inside its domain or an explicit abstention; no
nearest lookup is used. Because the VALIDATION outcome is a retention, #367
consumption is `FORBIDDEN` and no Hero EV, Model B or rollout is computed.

## 7. Boundaries and digest integrity

`TEST_CONSUMED=false`: the TEST split is refused by the dataset builder, the
runtime and the self-scans, and never appears in the persisted dataset.
`ACTIVE_POINTER_MUTATED=false`: the active Model A/B pointers and both registries
stay byte-identical (pins recorded in the frozen protocol). VALIDATION is
consumed exactly once, by the fenced evaluation.

The bundle recomputes every digest it persists. `ARTIFACTS.json` records, per
artifact, the byte and canonical payload digests plus every digest declared by a
frozen sibling or `.sha256` sidecar, and re-derives all of them; a mismatch is
fail-closed at build time and under `--check`. That closes the #352 failure mode,
where a self-reported digest was recorded without ever being recomputed.

## 8. Contract, runtime and tests

`tools/preflop/generalized_response_runtime.py::resolve_generalized_response`
is the reusable, machine-readable surface (action probabilities, OOD status,
uncertainty, provenance, conditional sizing); it fails closed on candidate/hash
mismatch, unknown categories, extrapolation, illegal actions and TEST. The
mandatory suite `tests/preflop/test_issue421_mandatory_contracts.py` pins the
thirteen ticket contracts and `tests/ci/test_issue421_contract_guards.py` keeps
the active pointer and `TEST_CONSUMED=false` frozen; this bundle adds
`tests/training/test_issue421_evidence_bundle.py` for content-addressing and
digest recomputation.

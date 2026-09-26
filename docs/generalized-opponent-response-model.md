# Generalized opponent response model (preflop, public-only)

Issue #421. The machine-readable source of truth is
`analysis/issue421_generalized_response/GENERALIZED_RESPONSE_MODEL_SPEC.json`
(`poker-generalized-response-model-spec/v1`), content-addressed as
`analysis/issue421_generalized_response/sha256/486ef55e14cdc1160faef7e53ac29631f1e13a9953b4f4996a8b3b052b185abf.json`
and pinned by
`analysis/issue421_generalized_response/GENERALIZED_RESPONSE_MODEL_SPEC.sha256`.
The ten required artifacts are bound by
`analysis/issue421_generalized_response/ARTIFACTS.json`; the human summary is
`analysis/issue421_generalized_response/SUMMARY.md`
(`0c0a2031e7e4649a75af866ab3e705db1204b51397443dce953817b2cc61a7ba`). This
document explains the spec and the cycle; it is not itself normative. The JSON
wins, and the spec digest is recorded outside its own payload.

Provenance is environment-independent: every recorded path — including
`evidence_bindings.runtime_module_path` and every `registry_source` embedded in
`ISSUE367_PREFLIGHT.json` (object digest
`4b7c757f9f4bd8f2aac83d2ec1f4106dbb67a4ab5a5df31c30c02fbdac9cb7d1`) — is a
repository-relative POSIX path, never an absolute host path, so the regenerated
digests are reproducible across hosts and worktrees. The runtime module it pins
(`tools/preflop/generalized_response_runtime.py`) hashes to
`af585fa50e04be4c848dc77db1bd28417eb536eee486aa0cfd5fcd4f95e6e361`. The
terminal decision is unchanged: `RETAIN_REFERENCE_GENERALIZATION_INSUFFICIENT`.

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

### 4b. A queried raise target outside the legal window is refused, never silent

The RAISE/JAM gain of the discrete-choice core is conditioned on the queried
raise target, and the research surface
(`generalized_response_model.predict` / `sizing_gain`) bounds that gain at
`sizing_gain_bounds = [0.125, 8.0]`. A target that leaves the engine's legal
raise window was therefore previously conditioned on a clamped gain with no
signal — the defect this section closes. The frozen model module
(`runtime_format.module_sha256` in `CANDIDATE_MANIFEST.json`) is not edited: the
explicit behaviour belongs to the runtime provider, which is the surface a
consumer reads, and the in-window distribution is untouched.

Two refusal regimes are declared and kept apart:

* **declared verdict.** Every runtime decision document carries `sizing_window`
  (`poker-generalized-response-sizing-window-legality/v1`): the window the query
  was compared against (`min_raise_to_bb` / `max_raise_to_bb` /
  `legal_target_interval_bb` when the caller supplies the engine interval,
  otherwise the documented conservative derived floor and the effective stack as
  the cap), `queried`, `queried_target_bb`, `inside_legal_window` and a stable
  `violation` code — `TARGET_BELOW_LEGAL_MINIMUM`, `TARGET_ABOVE_LEGAL_CAP`,
  `LEGAL_WINDOW_UNVERIFIED` or `null`. Nothing is snapped to a neighbouring
  price; `substituted` is `false`.
* **fail-closed.** When the context is otherwise answerable and the queried
  target leaves that window, `resolve_generalized_response` raises with
  `ILLEGAL_SIZING_GENERATED` *before* any document is returned, exactly as the
  module header documents. The distribution is never returned as if the
  requested sizing were legal. A context that is out of the calibrated domain
  keeps the frozen `OOD_ABSTAIN` document (no selected action, no sizing) and
  still declares the target's window verdict, so a *domain* refusal is never
  reclassified as a *request* error.

Coverage. `tests/preflop/test_generalized_response_runtime.py` pins both sides
of the window (target below the engine minimum, target beyond the stack cap),
the in-window declaration, the no-target case, the unverifiable window and the
OOD-precedence case; `tests/preflop/test_generalized_response_sizing.py` pins
the channel-side declaration (`inside_window=false` with
`TARGET_OUTSIDE_LEGAL_WINDOW`) and the legality of everything it generates.

Invariance. The frozen probe set
`analysis/issue421_generalized_response/IN_WINDOW_PREDICTION_REFERENCE.json`
(an additional frozen evidence file beside the ten required artifacts, bound to
the frozen candidate and model module it names)
holds nine in-window probes (both aggressive branches, a derived and a supplied
engine window, a limped family, three stack depths) with the exact runtime
probabilities, the selected action, the recommended and generated sizings and
the canonical digests of the runtime and model predictions of each. The entries
were captured from the runtime revision
`e390a199857a00357969c51ec87af2b2f5e799384a3aa4858c0762a70411b538` and
re-computed bit for bit after the legal-window declaration was added (revision
`af585fa50e04be4c848dc77db1bd28417eb536eee486aa0cfd5fcd4f95e6e361`): every
probability, selected sizing and digest is unchanged, and only the declared
`sizing_window` block is new. Regenerate the reference with
`python3 tests/preflop/test_generalized_response_sizing.py --write-in-window-reference`
(it re-captures the unchanged surface; the entry digest is
`bc34f4a36e0c4978cea57dee686f268d97040d05822f4b82bf69af58e495834a`).

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

# Hybrid preflop response router (normative)

Issue #423 (task `T13`). This document is the normative description of the
three-source hybrid preflop **response** router: what the three route sources
are, the pre-action signals that select between them, the reason codes, the
machine-readable runtime contract, the conditional sizing channel, the
TRAIN-only pre-registration procedure and its frozen criteria, and the explicit
limits of what the router admits.

The machine-readable source of truth is
`analysis/issue423_hybrid_router/HYBRID_ROUTER_SPEC.json`
(`poker-hybrid-router-spec/v1`), content-addressed as
`analysis/issue423_hybrid_router/sha256/15c14c4ad0acddc65e240673cf8d148e2cd40dfb3d6fc43170ab8c2bb814d075.json`
(byte SHA256 `15c14c4ad0acddc65e240673cf8d148e2cd40dfb3d6fc43170ab8c2bb814d075`,
canonical payload `23d9408f320630bd1b1bf632a6cb90f9e89ca29580cf717afb9f9a86d56a7282`).
The frozen numeric admission criteria are bound by
`analysis/issue423_hybrid_router/ROUTER_MANIFEST.json`
(`poker-hybrid-router-criteria-manifest/v1`, byte SHA256
`6864e3e3e05c0678c6276a26f53a5bc808c03814e48bcee456ef48e6736ef893`, canonical
payload `9a2d02f57f9f4612c7ead47f26fb8bd500c43c9097560bd2c9244008fabc5ce7`) and
the eight required artifacts are indexed by
`analysis/issue423_hybrid_router/ARTIFACTS.json`; the human summary is
`analysis/issue423_hybrid_router/SUMMARY.md`
(byte SHA256 `7c15caf06e1e404063f5f596d3ce2f71b447bd2b986c9de492f5a9837cc43397`).
The terminal decision lives in
`analysis/issue423_hybrid_router/DECISION.json`
(byte SHA256 `8ad1f92e5328f532dc9c60990afcf866ad380b2cbaffcc58eab20f0a6431f9ec`,
canonical payload `6b3068d73efd4c07498af74cf21650766bf874ca54c1d1ce6fd5a9b6b034d4d5`)
and is restated in `.project/decisions/20260926-hybrid-router.md`. The JSON wins
over this prose; every digest above is recorded outside the payload it describes
and is recomputed from the persisted bytes.

Reproduce: `python3 tools/training/build_issue423_evidence_bundle.py`.
Verify: `python3 tools/training/build_issue423_evidence_bundle.py --check`.
Guard: `python3 tests/training/test_issue423_evidence_bundle.py`.

## 1. The three route sources

The router composes two preflop adverse-response channels behind one fail-closed
selector. It does not learn a new model in the routing layer: it decides
*which* already frozen provider answers, and it refuses to answer when neither
may.

| route source | priority | provider | routed strata | support state | abstains |
| --- | --- | --- | --- | --- | --- |
| `ACTIVE_STRONG_SUPPORT` | `P2` | `active_model_a_preflop_population` (`training/models/preflop_population_model_v5.json`, `ff952055ca4ee051a3ac9607d513fdecac0a320a31f658ecfd8a11d8448975ca`) | `frequent_exact` | `STRONG_EXACT_SUPPORT` | no |
| `GENERALIZED_SPARSE_IN_DOMAIN` | `P3` | `generalized_adverse_response_candidate_v1` (frozen #421 channel) | `rare_exact`, `exact_absent_in_domain` | `SPARSE_IN_DOMAIN` | no |
| `OOD_ABSTAIN` | `P1` | none | `exact_absent_out_of_domain` | `OOD_ABSTAIN` | yes |

`ACTIVE_STRONG_SUPPORT` answers from the **active reference** population model,
admissible only where the decision's exact context signature is strongly
supported (`support_exact >= FREQUENT_EXACT_MIN_SUPPORT = 20`). The runtime
provider answers that branch by an **exact-cell lookup** of the active model
(mirroring the engine's own `exactStruct` predicate); when the active model
carries no exact cell for the request it abstains fail-closed
(`ACTIVE_EXACT_CELL_UNAVAILABLE`) instead of reading the nearest active node.

`GENERALIZED_SPARSE_IN_DOMAIN` answers from the learned generalized channel
where the exact context cell is sparse or absent **but every single-feature
label stays inside the calibrated TRAIN domain**. It is never consulted for
out-of-domain requests.

`OOD_ABSTAIN` is the fail-closed third source: no route may answer, no
probabilities and no sizing are emitted, and the decision is excluded from every
predictive gate. It has the highest priority (`P1`) so that a hard out-of-domain
reason can never be outvoted by an optimistic support signal.

### 1.1 Route decision table

The frozen table is applied top to bottom; the first matching row wins.

| row | condition | route source |
| --- | --- | --- |
| `R1` | `hard_reasons(context)` is not empty | `OOD_ABSTAIN` |
| `R2` | `hard_reasons(context)` is empty **and** `support_exact >= FREQUENT_EXACT_MIN_SUPPORT` | `ACTIVE_STRONG_SUPPORT` |
| `R3` | `hard_reasons(context)` is empty **and** `feature_in_domain(context)` | `GENERALIZED_SPARSE_IN_DOMAIN` |
| `R4` | no earlier row matched (fallback) | `OOD_ABSTAIN` |

Three progressively more complex rule implementations are declared in the
executable counterpart (`tools/preflop/hybrid_response_router.py`:
`R1_HARD_GATE` complexity 1, `R2_SUPPORT_GATE` complexity 2,
`R3_UNCERTAINTY_GATE` complexity 3). The preregistered **simplicity policy**
keeps the simplest rule whose agreement with the frozen reference rule stays
within `RULE_SIMPLICITY_MARGIN`; a rule is never simplified away from the
reference without measuring the loss first. `R2_SUPPORT_GATE` is the frozen
table above.

### 1.2 Strata

Decisions are stratified by the fit-fold support of their exact context
signature (`exact_context_key`):

* `frequent_exact` — `support >= 20`;
* `rare_exact` — `1 <= support < 20`;
* `exact_absent_in_domain` — `support == 0` while every single-feature node
  label is observed in the fit fold;
* `exact_absent_out_of_domain` — `support == 0` with at least one unseen
  feature value.

`rare_exact` and `exact_absent_in_domain` are the **sparse covered strata** the
generalized channel may answer. `exact_absent_out_of_domain` is the OOD stratum
that must abstain. An exact context absent from TRAIN while every single-feature
label is in-domain is **not** out-of-domain by definition: that field is
reported, never treated as an abstention cause. The stratum definition is reused
verbatim from issue #421
(`tools/training/evaluate_generalized_response_cv.py::STRATA`).

## 2. Pre-action signals

Every signal is deterministic, computable **before** the action, and independent
of the hidden hand and of the observed result. No hidden hand, no observed
action and no realized result is read.

| signal | kind | read from | decisive for OOD |
| --- | --- | --- | --- |
| `support_exact` | support | fit-fold `exact_context_support` at the model's own discrete resolution | no |
| `support_feature_level` | support | `local_support.min_feature_share` (weakest per-block single-feature share) | yes |
| `distance_to_domain` | domain | robust distance of the query to the calibrated numeric core | no |
| `predictive_uncertainty` | uncertainty | normalized predictive entropy / fitted node support of the generalized channel | no |
| `extrapolation_sizing` | extrapolation | queried raise target vs the calibrated TRAIN sizing domain | yes |
| `extrapolation_stack` | extrapolation | queried effective stack vs the calibrated TRAIN stack domain | yes |
| `extrapolation_price` | extrapolation | queried to-call / pot price vs the calibrated TRAIN price domain | yes |
| `family` | categorical | public context family | no |
| `actor_position` | categorical | public context actor position | no |
| `aggressor_position` | categorical | public context aggressor position | no |

Support and extrapolation signals are admissible without train tuning because
they are mechanically defined before the action; the public categorical blocks
(`family`, `actor_position`, `aggressor_position`) are consumed by a route only
where the frozen TRAIN out-of-fold breakdown justifies it (at least two eligible
categories and a preponderant share of eligible support answered with positive
gain over the global action prior: `MINIMUM_CATEGORY_SUPPORT = 20`,
`MINIMUM_POSITIVE_GAIN_SHARE = 0.5`).

There is no ad-hoc table of contexts. `resolve_support_exact` looks the **exact**
context signature up in the frozen index and returns `0` for an absent key;
`resolve_numeric_axis` reads the **exact** queried axis and returns `None` when
the axis is absent. Neither falls back on a neighbouring observation.

## 3. Reason codes

### 3.1 OOD / uncertainty gate (reused from issue #421)

The gate is `contracts/training/generalized-response-ood-gate.schema.json`
(byte SHA256 `99a6fe9c3eeb4b7f61db35f390115938799c8730d41fa0b8e62e4311023f0f1e`).
It emits one of `MODEL_SUPPORTED`, `MODEL_SUPPORTED_HIGH_UNCERTAINTY` or
`MODEL_OOD_ABSTAIN`.

**Hard reasons — abstain fail-closed:**

`UNSEEN_CATEGORY`, `EXTRAPOLATION_STACK`, `EXTRAPOLATION_SIZING`,
`EXTRAPOLATION_PRICE`, `MISSING_DOMAIN_AXIS`.

**Soft reasons — raise the status to high uncertainty only, never abstain:**

`SPLINE_BOUNDARY_EXTRAPOLATION`, `DOMAIN_DISTANCE`, `LOW_FEATURE_SUPPORT`,
`LOW_EXACT_CONTEXT_SUPPORT`, `HIGH_PREDICTIVE_ENTROPY`, `LOW_MODEL_NODE_SUPPORT`,
`PREDICTIVE_UNCERTAINTY_UNAVAILABLE`.

The abstention rule is `abstain(c) iff hard_reasons(c) is not empty`. A soft
reason alone never abstains.

### 3.2 Runtime fail-closed codes

The runtime provider (`tools/preflop/hybrid_response_runtime.py`) records a
stable `fail_closed_reason` when a route is otherwise answerable but a channel
refuses. A channel-level refusal downgrades the emitted decision to the
`OOD_ABSTAIN` surface (no probabilities, no selected action, no sizing,
`analysis_admissible=false`); `resolve(..., strict=True)` re-raises the
underlying refusal instead.

| code | meaning |
| --- | --- |
| `SPEC_UNAVAILABLE` / `SPEC_DIGEST_MISMATCH` / `SPEC_INVALID` | the frozen spec is missing, drifted or unreadable |
| `CONTRACT_MISMATCH` | the emitted document does not satisfy the frozen runtime contract |
| `TEST_SPLIT_NOT_CONSUMABLE` | a `TEST` row was requested; TEST is refused |
| `REFUSED_SPLIT` | a `VALIDATION` row was requested; the frozen policy refuses it |
| `NEAREST_NEIGHBOUR_SUBSTITUTION_REFUSED` | a caller explicitly asked for a nearest price/context substitution |
| `ACTIVE_REFERENCE_UNAVAILABLE` / `ACTIVE_REFERENCE_DIGEST_MISMATCH` | the active Model A reference is missing or drifted |
| `CALIBRATION_REPORT_UNAVAILABLE` / `CALIBRATION_REPORT_DIGEST_MISMATCH` | the frozen #423 calibration report is missing or drifted |
| `ACTIVE_EXACT_CELL_UNAVAILABLE` | routed to `ACTIVE_STRONG_SUPPORT` but the active model has no exact cell; the nearest node is never read |
| `CALIBRATED_CHANNEL_ABSTAINED` / `CALIBRATED_CHANNEL_REFUSED` | the generalized channel abstained or refused on an otherwise answerable route |
| `ILLEGAL_SIZING_TARGET` | the queried raise target leaves the engine's legal window |
| `NO_LEGAL_ACTION` | no legal action survived masking |
| `UNKNOWN_ROUTE_SOURCE` | the router returned a route source outside the three declared ones |

## 4. Machine-readable runtime contract

The contract schema is `poker-hybrid-router-runtime-contract/v1`
(`runtime_contract` in the spec). The emitted decision document is
`poker-hybrid-response-runtime-decision/v1`, serialised by `canonical_json`
(sorted keys, ASCII, compact separators) and self-digested with the runtime's
`decision_canonical_sha256`. Every float is quantised on the canonical decimal
grid of `tools/preflop/generalized_response_runtime.py` and every embedded legal
distribution is re-closed with `math.fsum`, so the same context always produces
the same bytes and `probability_sum` is exactly `1.0` with `illegal_mass`
exactly `0.0`.

**Always-required fields**

| field | type | meaning |
| --- | --- | --- |
| `route_source` | `enum[ACTIVE_STRONG_SUPPORT \| GENERALIZED_SPARSE_IN_DOMAIN \| OOD_ABSTAIN]` | the route source that produced the decision |
| `model_id` | string | stable identity of the model that produced the probabilities |
| `model_hash` | sha256 | byte digest of the model artifact the probabilities were read from |
| `support_state` | `enum[STRONG_EXACT_SUPPORT \| SPARSE_IN_DOMAIN \| OOD_ABSTAIN]` | support classification, derived from `route_source` |
| `uncertainty` | `enum[NONE \| HIGH]` | `HIGH` when the gate raised any soft reason |
| `ood_status` | `enum[MODEL_SUPPORTED \| MODEL_SUPPORTED_HIGH_UNCERTAINTY \| MODEL_OOD_ABSTAIN]` | status returned by the frozen #421 gate |
| `analysis_admissible` | boolean | see the rule below |

**Conditionally-required fields**

| field | required when | meaning |
| --- | --- | --- |
| `probabilities` | `route_source != OOD_ABSTAIN` | legal-action distribution `{FOLD\|CALL\|RAISE\|JAM -> number}` summing to one with zero mass on illegal actions |
| `sizing_provenance` | `selected_action in {RAISE, JAM}` | the sizing channel, its legality-window verdict and the queried target |

**Analysis-admissibility rule**

```
analysis_admissible = (route_source != OOD_ABSTAIN)
                      and probabilities legal
                      and (sizing_provenance present when selected_action in {RAISE, JAM})
```

**Invariants**

* `route_source` is always one of the three declared route sources;
* an `OOD_ABSTAIN` answer carries no probabilities, no selected action and no
  sizing;
* `analysis_admissible` is `false` on every abstention;
* a `RAISE`/`JAM` answer carries the sizing provenance of the channel that
  produced it;
* the emitted probabilities sum to one with zero mass on illegal actions.

The legality surface a channel answer is masked to is the **frozen engine** one
(`generalized_response_model.legal_response_actions`), never a router-local
approximation.

## 5. Conditional sizing channel

Sizing is a separate conditional density over the engine's **legal window**
(`min_raise_to` from the engine interval, cap at the effective stack), reported
per query with its support and uncertainty. It generates quantiles and fails
closed with a reason code when the window is empty below the stack.

* `no_nearest_price_substitution = true` and
  `no_nearest_context_substitution = true`: the provider never substitutes a
  neighbouring price for the queried target.
* `FAIL_CLOSED_ON_ILLEGAL_TARGET = true`: a RAISE/JAM answer whose queried target
  leaves the legal window is refused (`ILLEGAL_SIZING_TARGET`) rather than
  returned as if it were legal, and the frozen model module is not edited — the
  explicit behaviour belongs to the runtime provider, which is the surface a
  consumer reads.
* The preflight resolves all 7 required #388/#419 raise-sizing frontiers through
  this channel with zero fail-closed sizings and zero illegal generated targets.

The `sizing_provenance` document (`poker-hybrid-response-sizing-provenance/v1`)
declares the channel, the model id and hash, the selected target, the legal
window, and the refusal verdict.

## 6. Pre-registration procedure and frozen criteria

### 6.1 Order guard (frozen before the terminal score)

The criteria are authored on **TRAIN-only** evidence and frozen
`FROZEN_BEFORE_TERMINAL_EVALUATION` before any terminal router score exists. The
freeze refuses to author numeric admission criteria once a terminal
`TRAIN_CV_ROUTER_REPORT.json` exists (`ROUTER_CRITERIA_ORDER_GUARD`,
`terminal_report_absent_at_freeze = true`); regeneration with different values
fails closed. The spec records `authored_before_validation_read = true`,
`terminal_evaluation_reads = 0` and `terminal_numeric_values_persisted = false`.

The evaluation basis is `TRAIN_only_hand_grouped_out_of_fold`: 94160 rows over
19016 hands in 5 folds grouped by `hand_id` (`derivation/CV_DERIVATION.json`,
byte SHA256 `519ce5addc849da752512ed8bfa5218f0051fd4bf5898634961b8fbe11974630`).
The derivation order is frozen:

`STRATUM_ASSIGNMENT`, `OOD_ABSTENTION_CRITERION`, `ROUTE_SELECTION_PROCEDURE`,
`SUPPORT_STATE_ASSIGNMENT`, `GLOBAL_NON_INFERIORITY_MARGIN`,
`GLOBAL_NON_INFERIORITY_ANALYTIC_CROSS_CHECK`, `SPARSE_GAIN_FLOOR`,
`SPARSE_GAIN_FLOOR_PAIRED_LOWER_BOUND`, `SPARSE_ECE_MEASUREMENT`,
`SPARSE_ECE_CEILING`, `FREQUENT_EXACT_NON_DEGRADATION_BOUND`.

Pre-registered constants: `NON_INFERIORITY_CONFIDENCE_LEVEL = 0.95`,
`NON_INFERIORITY_UPPER_QUANTILE = 0.95`, `NON_INFERIORITY_ALPHA = 0.05`,
`BOOTSTRAP_SAMPLES = 2000`, `BOOTSTRAP_SEED = 423`, `Z_ONE_SIDED_95 =
1.6448536269514722`, `MARGIN_MAX_BITS = 0.0`,
`MARGIN_ANALYTIC_TOLERANCE_BITS = 0.001`, `GAIN_FLOOR_BITS = 0.0`,
`ECE_ABSOLUTE_CEILING = 0.02`, `ECE_DELTA_CEILING = 0.02`,
`FREQUENT_EXACT_MAX_DEGRADATION_BITS = 0.0`,
`MINIMUM_SPARSE_OBSERVATIONS = 20`, `FREQUENT_EXACT_MIN_SUPPORT = 20`,
`RARE_EXACT_MIN_SUPPORT = 1`. All constants carry
`terminal_evaluation_derived = false`.

The frozen criteria block has canonical digest
`e9f1ebc48fe384c2bf28fcb8d3359c54d1faa318dda42a0a518d48bb1be037e2`; every
criterion below is resolved from TRAIN-only out-of-fold evidence and carries a
quantitative justification and its `derivation_rule`.

### 6.2 The five frozen criteria and their justification

**`GLOBAL_NON_INFERIORITY_MARGIN`** — `margin_global_bits_per_decision <= 0.001`.
Statistic: one-sided upper percentile of the paired-by-hand bootstrap of
`mean(log_loss_hybrid - log_loss_active)` on the admission support. The margin is
sized by the **measured** TRAIN out-of-fold dispersion:
`derivation_rule = ceil_to_quantum(max(MARGIN_MAX_BITS = 0.0, one_sided_upper_quantile),
MARGIN_ANALYTIC_TOLERANCE_BITS = 0.001)` at quantum `0.001` bits/decision. The
observed bootstrap margin `0.000508` and the closed-form analytic margin
`0.000338` agree within the preregistered tolerance `0.001` (absolute
difference `0.00017 < 0.001`), so the rounded-up frozen value is `0.001`. The
threshold is the smallest preregistered-resolution multiple that covers the
observed dispersion, never a value chosen after seeing the terminal score.

**`SPARSE_GAIN_FLOOR`** — `gain_sparse_bits_per_decision >= 0.167` on the pooled
`(rare_exact, exact_absent_in_domain)` support. The floor is the gain TRAIN
already demonstrated, rounded **down** to the preregistered `0.001` resolution
(`floor_to_quantum`) so the requirement is never stricter than the measured
evidence: `max(GAIN_FLOOR_BITS = 0.0, floor_to_quantum(0.167733)) = 0.167`.

**`SPARSE_ECE_CEILING`** — `ece_sparse <= 0.02`, the support-weighted expected
calibration error of the hybrid channel over the pooled sparse strata. The frozen
ceiling is the **tighter** of the preregistered absolute ECE ceiling and the
active reference's own sparse ECE plus the preregistered delta:
`min(ECE_ABSOLUTE_CEILING = 0.02, ece_active_sparse + ECE_DELTA_CEILING = 0.02)`.
The recorded binding term is `ECE_ABSOLUTE_CEILING` (the delta branch would give
`0.042629 + 0.02 = 0.062629`). It is the only criterion that fails at this
revision.

**`FREQUENT_EXACT_NON_DEGRADATION_BOUND`** —
`delta_frequent_exact_bits_per_decision <= 0.0` **and** its paired `ci95` upper
bound `<= 0.0`. Statistic: paired-by-hand hybrid-minus-active log-loss delta on
the `frequent_exact` stratum, in point estimate and in paired upper quantile. The
bound is derived from that stratum's paired dispersion and capped at
`FREQUENT_EXACT_MAX_DEGRADATION_BITS = 0.0`.

**`OOD_ABSTENTION_CRITERION`** — `abstain iff hard_reasons is not empty`;
`abstain_rate == 1.0` and `coverage == 0.0` on the synthetic out-of-domain probe
surface. The probe surface is 640 probes (160 each of
`extrapolation_sizing`, `extrapolation_stack`, `missing_domain_axis`,
`unseen_category`). The router must fail closed on **every** probe; the hard
reason codes are decisive and the soft reasons never abstain.

## 7. Terminal outcome at this revision

On the TRAIN-only, hand-grouped cross-fitted score the routed system passes
**4/5** frozen admission criteria and fails `SPARSE_ECE_CEILING`, so the terminal
outcome is **`RETAIN_REFERENCE_HYBRID_INSUFFICIENT`**, the actual one of the two
valid terminal outcomes (`ADMIT_HYBRID_ROUTER_FOR_ANALYSIS` /
`RETAIN_REFERENCE_HYBRID_INSUFFICIENT`). The per-stratum results and the frozen
margin/threshold values are restated in
`.project/decisions/20260926-hybrid-router.md`.

## 8. What this admits — and what it does not

### 8.1 ANALYSIS_ADMISSIBLE vs PRODUCT_ADMISSIBLE

The router decides **analysis admissibility** only: whether a routed decision may
enter the analysis surface, as the boolean `analysis_admissible` defined in
section 4. It says nothing about whether a decision may be shown to a user,
promoted, wired into a product path or acted on.

**`PRODUCT_ADMISSIBLE` is explicitly out of scope for #423** and is never a
terminal outcome of the decision
(`boundaries.product_admissible = false`,
`boundaries.product_admissible_note`). Product admissibility is a separate,
downstream question owned by other workstreams — the Model B sensitivity track
(#315) and the prospective temporal validation layer (#202) — and the #423
router neither claims it nor stands in for it.

### 8.2 Bounds

* **TEST not consumed** — `TEST_CONSUMED=false`. The loader, the CV harness, the
  criteria freeze, the runtime provider and the preflight self-scans all refuse
  `TEST` (`test_authorized = false`); the refused splits are
  `['VALIDATION', 'TEST']` and a refused split is a hard error, raised before a
  byte is written. The 2449 certified TEST hands are intact.
* **VALIDATION not consumed / not re-opened** — `VALIDATION_CONSUMED=false`,
  `validation_reopened=false`. The design, the calibration, the criteria and the
  terminal score are all TRAIN-only; the generalized channel is never
  recalibrated on VALIDATION
  (`validation_recalibrated = false`, `validation_recalibration_refused = true`).
* **The #421 evidence is unchanged and is not re-read.** The #423 cycle consumes
  the frozen #421 generalized channel and gate as *descriptive history* only; it
  never re-opens the #421 VALIDATION split and never re-fits or re-scores the
  #421 candidate. The reused #421 artifacts are bound by digest and left
  byte-identical — `analysis/issue421_generalized_response/TRAIN_CV_REPORT.json`
  (`43d9fffff98aeae1f51d0bdd78647a2dedbd58403a0591433d22840a5cf996ff`) and
  `analysis/issue421_generalized_response/OOD_CALIBRATION_REPORT.json`
  (`a8f1b181f0d3ff3fd48dd3d58181a844760409f036e0b11f440ff7553dfc0b71`) — and the
  #423 TRAIN-only score reuses the #421 dataset
  (`analysis/issue421_generalized_response/dataset/GENERALIZED_RESPONSE_DATASET.jsonl`,
  `4c18872fac5fc443e68e6f99feb0036509999f67f952c02e118671c7c72330a2`) without
  reading any holdout row.
* **No active pointer was mutated** — `ACTIVE_POINTER_MUTATED=false`: the Model A
  pointer `training/models/preflop_population_model_v5.json`
  (`ff952055ca4ee051a3ac9607d513fdecac0a320a31f658ecfd8a11d8448975ca`), the Model B
  pointer `training/models/postflop_population_model_v5.json`
  (`6d948f30f6c276ce41e70e83ac35275e30e7841e93e5b1da11782648c6b4d8ae`) and the
  model admitted for #367 (`model-a-preflop-sizing-aware-candidate-v2`) are
  unchanged, and no promotion is performed (`automatic_promotion = FORBIDDEN`).
* **#367 is not executed** — `ISSUE367_EXECUTED=false`. The preflight
  (`ISSUE367_PREFLIGHT.json`,
  `fb31bd45618345d6fbf780b7150d2df0ee30d1c817d232e27b018aad8fcb5f7d`) walks the 38
  required scenario #321 nodes and 7 raise-sizing frontiers (45 visited
  decisions: 43 direct evaluations, 2 explicit abstentions) through the runtime
  provider, but `hero_ev_executed=false` and `issue367_executed=false`. Because
  the terminal outcome is a retention, #367 admission is `FORBIDDEN`
  (`ABSTAIN_BLOCKED_ADMISSION`); `next_issue=367` is recorded as `NOT_EXECUTED`
  and #367 keeps its currently admitted model. No Hero EV, no rollout and no
  support-grid extension are computed.

## 9. Limits

* The router is a **selector**, not a new estimator. It adds no context table and
  no learned parameter of its own; it chooses between already frozen providers
  and refuses otherwise.
* The decision is **TRAIN-only** at this revision. No VALIDATION or TEST row was
  read; the terminal outcome is a retention and no threshold, prior or criterion
  moved after the freeze.
* The frozen sparse ECE ceiling is a **scientific admission gate**: passing it
  would have admitted the router *for analysis* only, never for product use.
* The conditional sizing channel is bounded by the engine's legal window; it
  never snaps to a nearest price and never widens the legal interval.
* The OOD gate fails closed on hard reasons; abstention is a first-class,
  machine-readable outcome, not an error to be smoothed over.
* `analysis_admissible` is a statement about the analysis surface, not a claim of
  profitability, calibration on unseen populations, or product readiness.

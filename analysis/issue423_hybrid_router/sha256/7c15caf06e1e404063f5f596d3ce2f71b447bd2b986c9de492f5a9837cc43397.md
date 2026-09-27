# #423 -- hybrid preflop response router: evidence bundle

**RETAIN_REFERENCE_HYBRID_INSUFFICIENT** -- the actual one of the two valid terminal outcomes (`ADMIT_HYBRID_ROUTER_FOR_ANALYSIS` / `RETAIN_REFERENCE_HYBRID_INSUFFICIENT`). On the TRAIN-only, hand-grouped cross-fitted score the routed system passes 4/5 frozen admission criteria and fails `SPARSE_ECE_CEILING`, so the active Model A reference is retained, #367 keeps its currently admitted model and nothing is promoted (`PRODUCT_ADMISSIBLE` is explicitly out of scope).

This bundle persists and content-addresses the eight required #423 artifacts under `analysis/issue423_hybrid_router/sha256/` and binds them in `ARTIFACTS.json`. `DECISION.json` is the terminal decision authored here as a deterministic fold of the frozen evidence (no re-fit, no re-score, no new claim); its byte SHA256 is `8ad1f92e5328f532dc9c60990afcf866ad380b2cbaffcc58eab20f0a6431f9ec` (canonical payload `6b3068d73efd4c07498af74cf21650766bf874ca54c1d1ce6fd5a9b6b034d4d5`).

## 1. Decision (both terminal outcomes)

| terminal outcome | condition | actual | downstream |
| --- | --- | --- | --- |
| `ADMIT_HYBRID_ROUTER_FOR_ANALYSIS` | every frozen #423 admission criterion passes on the TRAIN-only hand-grouped cross-fitted score | no | unlocks the #367 preflight only: it wires no provider into #367, performs no promotion and mutates no active pointer |
| `RETAIN_REFERENCE_HYBRID_INSUFFICIENT` | at least one frozen #423 admission criterion fails on the TRAIN-only hand-grouped cross-fitted score | **yes** | the active Model A reference is retained; #367 keeps its currently admitted model; no provider is wired, no Hero EV is computed and no promotion happens |

`DECISION.json` = **RETAIN_REFERENCE_HYBRID_INSUFFICIENT**. Rationale: the hybrid router passes 4/5 frozen criteria but fails SPARSE_ECE_CEILING on the TRAIN-only cross-fitted score; the active Model A reference is retained and #367 keeps its currently admitted model; the terminal outcome is RETAIN_REFERENCE_HYBRID_INSUFFICIENT.

## 2. Frozen criteria evaluation (TRAIN-only, hand-grouped cross-fitted)

| criterion | comparator | threshold | observed | result |
| --- | --- | --- | --- | --- |
| `GLOBAL_NON_INFERIORITY_MARGIN` | `<=` | 0.001 | `0.000508` | PASS |
| `SPARSE_GAIN_FLOOR` | `>=` | 0.167 | `{"gain_bits_per_decision": 0.167733, "minimum_sparse_observations": 20, "per_stratum": {"exact_absent_in_domain": -0.071905, "rare_exact": 0.226143}, "sparse_decisions": 12966}` | PASS |
| `SPARSE_ECE_CEILING` | `<=` | 0.02 | `{"active_sparse_ece": 0.042629, "hybrid_ece": 0.027507, "per_stratum_hybrid_ece": {"exact_absent_in_domain": 0.040773, "rare_exact": 0.024273}}` | **FAIL** |
| `FREQUENT_EXACT_NON_DEGRADATION_BOUND` | `<=` | 0.0 | `{"paired_ci95_upper_bits_per_decision": 0.0, "point_estimate_bits_per_decision": 0.0, "upper_quantile_bits_per_decision": 0.0}` | PASS |
| `OOD_ABSTENTION_CRITERION` | `==` | 1.0 | `{"abstain_rate": 1.0, "coverage": 0.0, "probes": 640, "probes_abstained": 640, "probes_per_kind": {"extrapolation_sizing": 160, "extrapolation_stack": 160, "missing_domain_axis": 160, "unseen_category": 160}}` | PASS |

Surface: TRAIN only, `94160` rows over `19016` hands in `5` folds grouped by `hand_id`; VALIDATION and TEST are refused by the loader, the harness and the criteria freeze (`validation_consumed=false`, `test_consumed=false`).

## 3. Global non-inferiority of the routed system

Routed channel shares: `ACTIVE_STRONG_SUPPORT=81185`, `GENERALIZED_SPARSE_IN_DOMAIN=12966`, `OOD_ABSTAIN=9`; hybrid coverage 99.9904% (9 abstained decisions).

| channel | log loss (bits/decision) | ECE | coverage |
| --- | --- | --- | --- |
| active_model_a | 1.437454 | 0.17112 | 1.0 |
| generalized_calibrated | 1.215171 | 0.012032 | 1.0 |
| hybrid_router | 1.433096 | 0.166441 | 0.999904 |

Global paired-by-hand bootstrap (hybrid minus active, negative favours the router): point `-0.004301`, ci95 `[-0.009648, 0.001598]`, one-sided upper quantile `0.000508` against the frozen margin `0.001` -- PASS.

## 4. Sparse strata comparison (generalization)

Definition: frozen #423 strata: frequent_exact (exact-cell support >= 20), rare_exact (0 < support < 20), exact_absent_in_domain (support == 0, every single-feature label observed in the fit fold) and exact_absent_out_of_domain (support == 0 with at least one unseen feature value).

| stratum | share | n | hybrid log loss | hybrid ECE | hybrid coverage |
| --- | --- | --- | --- | --- | --- |
| rare_exact | 0.110737 | 10425 | 1.053151 | 0.024273 | 0.999808 |
| exact_absent_in_domain | 0.02705 | 2541 | 1.462743 | 0.040773 | 0.997644 |
| frequent_exact | 0.862213 | 81185 | 1.480957 | 0.194212 | 0.999988 |
| exact_absent_out_of_domain | 0.0 | 0 | n/a | n/a | 0.0 |

Pooled sparse support (`rare_exact`, `exact_absent_in_domain`): 12966 decisions, gain `0.167733` bits/decision (floor `0.167` -- PASS), sparse ECE `0.027507` against the active reference `0.042629` -- ceiling `0.02`, **FAIL** (the single failed criterion). Per-stratum hybrid ECE is `{'exact_absent_in_domain': 0.040773, 'rare_exact': 0.024273}`. The `exact_absent_out_of_domain` stratum is empty on the natural TRAIN surface (share `0.0`); abstention is exercised on the synthetic OOD probes instead.

## 5. OOD gate and abstention

Route sources `ACTIVE_STRONG_SUPPORT/GENERALIZED_SPARSE_IN_DOMAIN/OOD_ABSTAIN`; hard reason codes `UNSEEN_CATEGORY, EXTRAPOLATION_STACK, EXTRAPOLATION_SIZING, EXTRAPOLATION_PRICE, MISSING_DOMAIN_AXIS` abstain fail-closed, soft reasons only raise the status to high uncertainty. On the `640` synthetic out-of-domain probes the router abstains at rate `1.0` with coverage `0.0` (`{'extrapolation_sizing': 160, 'extrapolation_stack': 160, 'missing_domain_axis': 160, 'unseen_category': 160}`). The reused gate contract is `contracts/training/generalized-response-ood-gate.schema.json` (digest pinned). No nearest-price or nearest-context substitution is performed (`nearest_price_substituted=false`, `nearest_context_substituted=false`).

## 6. LIMPER_VS_ISO surface

The limper-versus-isolation family is reported on its own surface (`2614` hands) so the pooled tables never hide it: hybrid log loss `1.000974` vs active `1.031822` and generalized `1.008978`.

## 7. Generalized calibration (TRAIN-only)

`GENERALIZED_CALIBRATION_REPORT.json` retains `regularized_multinomial_spline` / `isotonic`, fitted in-fold and evaluated out-of-fold; VALIDATION is never recalibrated (`validation_recalibrated=false`, `validation_recalibration_refused=true`).

## 8. #367 preflight

`ISSUE367_PREFLIGHT.json` walks the 38 required scenario #321 nodes and 7 raise-sizing frontiers (45 visited decisions: 43 direct evaluations, 2 explicit abstentions), hero EV executed `false`, #367 executed `false`. Admission is `FORBIDDEN` with outcome `ABSTAIN_BLOCKED_ADMISSION` because the terminal router outcome is `RETAIN_REFERENCE_HYBRID_INSUFFICIENT`; #367 keeps its currently admitted model.

## 9. Digest verification (recomputed vs persisted)

Every digest this bundle persists is recomputed from the persisted bytes: 92 cross-references declared by the frozen artifacts (file bytes, canonical payloads, the frozen criteria block and nested provenance digests) and every `.sha256` sidecar were re-derived and all match (`digest_verification.all_recomputed_digests_match_persisted = true`). This closes the #352 failure mode, where a self-reported digest was recorded without ever being recomputed.

| artifact | byte SHA256 | canonical payload SHA256 |
| --- | --- | --- |
| HYBRID_ROUTER_SPEC.json | `15c14c4ad0acddc65e240673cf8d148e2cd40dfb3d6fc43170ab8c2bb814d075` | `see ARTIFACTS.json` |
| TRAIN_CV_ROUTER_REPORT.json | `6932802f8bdd26b52be547a3c8682f8de642f41e354cd105987ffb2e029b8082` | `see ARTIFACTS.json` |
| SPARSE_STRATA_COMPARISON.json | `f9ebfe62c48f36a40b2f50efdf69a373915cce2f8484531bb55e212b25ca656b` | `see ARTIFACTS.json` |
| GENERALIZED_CALIBRATION_REPORT.json | `a79d89c21610d42f4f083c43d3b7f1f9dfaf6ea5e104be558b3b06704f3be5cd` | `see ARTIFACTS.json` |
| ROUTER_MANIFEST.json | `6864e3e3e05c0678c6276a26f53a5bc808c03814e48bcee456ef48e6736ef893` | `see ARTIFACTS.json` |
| ISSUE367_PREFLIGHT.json | `fb31bd45618345d6fbf780b7150d2df0ee30d1c817d232e27b018aad8fcb5f7d` | `see ARTIFACTS.json` |
| DECISION.json | `8ad1f92e5328f532dc9c60990afcf866ad380b2cbaffcc58eab20f0a6431f9ec` | `6b3068d73efd4c07498af74cf21650766bf874ca54c1d1ce6fd5a9b6b034d4d5` |
| SUMMARY.md | `see ARTIFACTS.json` | n/a |

## 10. Boundaries

- `TEST_CONSUMED=false` -- the loader, the harness, the criteria freeze and the preflight self-scans all refuse TEST (`test_authorized=false`, `test_consumed=false`); the refused splits are `['VALIDATION', 'TEST']`.
- `VALIDATION_CONSUMED=false` -- the #421 VALIDATION split is never re-opened: the design, the calibration, the criteria and the score are all TRAIN-only, and the preserved #421 evidence is read as descriptive history only.
- `ACTIVE_POINTER_MUTATED=false` -- the active Model A pointer `training/models/preflop_population_model_v5.json` (`ff952055ca4ee051a3ac9607d513fdecac0a320a31f658ecfd8a11d8448975ca`), the Model B pointer `training/models/postflop_population_model_v5.json` and the model admitted for #367 (`model-a-preflop-sizing-aware-candidate-v2`) are unchanged; no promotion is performed (`automatic_promotion=FORBIDDEN`).
- `ISSUE367_EXECUTED=false` -- #367 is neither executed nor authorized by this bundle; `next_issue=367` is recorded as `NOT_EXECUTED`; no Hero EV, no rollout and no support-grid extension are computed.

## 11. Reproduce and verify

```text
python3 tools/training/build_issue423_evidence_bundle.py
python3 tools/training/build_issue423_evidence_bundle.py --check
python3 tests/training/test_issue423_evidence_bundle.py
```

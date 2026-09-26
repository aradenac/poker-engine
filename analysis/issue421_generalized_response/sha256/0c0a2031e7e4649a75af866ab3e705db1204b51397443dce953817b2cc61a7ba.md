# #421 — generalized opponent response model: evidence bundle

**RETAIN_REFERENCE_GENERALIZATION_INSUFFICIENT** (protocol outcome `RETAIN_ACTIVE_REFERENCE`, 8/10 frozen criteria passed). The candidate `generalized-adverse-response-candidate-v1` (`regularized_multinomial_spline`, canonical payload `c3f3573f3e80b3f7889dc8b1fd6f1948daeea95effc5a41a5d707385c4eed7dc`) is **not** admitted, is **not** wired into #367 and does **not** replace the active Model A reference.

This bundle persists and content-addresses the ten required #421 artifacts under `analysis/issue421_generalized_response/sha256/` and binds them in `ARTIFACTS.json`.
`GENERALIZED_RESPONSE_MODEL_SPEC.json` is a deterministic projection of the frozen evidence (no re-fit, no new claim); its byte SHA256 is `486ef55e14cdc1160faef7e53ac29631f1e13a9953b4f4996a8b3b052b185abf` (canonical payload `ee744adcfd0413719430725f1bb3bbd4e5ff341cbd8b038e8ce533dbf8348dd8`).

## 1. Decision

`DECISION.json` = **RETAIN_REFERENCE_GENERALIZATION_INSUFFICIENT** on the single fenced VALIDATION read (`validation_reads=1`, 11538 in-scope decisions over 2324 hands). Failed frozen gates: `non_inferiority_vs_active_model_a_preflop_population`, `calibration_within_frozen_ceiling`.

Rationale: the candidate fails non_inferiority_vs_active_model_a_preflop_population, calibration_within_frozen_ceiling on the one-shot VALIDATION evaluation; the active Model A reference is retained and the generalization evidence is insufficient for admission.

## 2. Coverage

- Total in-scope coverage: **100.0000%** (11538 answered / 2324 hands) against the frozen floor `0.5` — PASS.
- LIMPER_VS_ISO coverage: **100.0000%** (364/364); LIMPER_VS_ISO_CALLERS 100.0000% (370/370).
- Abstention rate: 0.0000% (0 abstained decisions); per-position coverage is reported in `VALIDATION_RESULT.json` for all 6 positions.
- TRAIN out-of-fold coverage was 93.0055% under the frozen provisional gate.

## 3. Calibration

| model | log loss (bits/decision) | Brier | ECE |
| --- | --- | --- | --- |
| candidate_generalized | 1.2689828317 | 0.5242836174 | 0.0362278552 |
| active_model_a_v5 | 1.2677704885 | 0.5257180063 | 0.0147432394 |
| model_a_preflop_sizing_aware_candidate_v2 | 1.3013433248 | 0.5382575033 | 0.0115710569 |
| alternate_architecture_hierarchical_eb | 1.2818289735 | 0.5306143008 | 0.0399200791 |
| fit_global_prior_baseline | 1.33567312 | 0.5534494285 | 0.0077336625 |

Calibration gate **FAIL**: candidate ECE `0.036227855199` is inside the frozen absolute ceiling `0.05`, but the delta vs the active reference `0.0214846158` exceeds the frozen maximum `0.02`. TRAIN out-of-fold ECE was `0.02662`; the claim rests on equal-count reliability bins pooled over the frozen VALIDATION decisions (40 bins meeting the minimum support).

Non-inferiority (paired percentile bootstrap on `hand_id`): candidate minus fit priors `-0.0576900794` (PASS), candidate minus hierarchical empirical Bayes `-0.0086878096` against margin `0.005` (PASS), candidate minus active Model A v5 `0.0069549188` against margin `0.0` (**FAIL**).

## 4. Strata (generalization)

| stratum | share | n | log loss | ECE | coverage |
| --- | --- | --- | --- | --- | --- |
| frequent_exact | 0.8710348414 | 10050 | 1.2958351531 | 0.0371633052 | 1.0 |
| rare_exact | 0.1057375628 | 1220 | 1.0315915462 | 0.0536158281 | 1.0 |
| exact_absent_in_domain | 0.0232275958 | 268 | 1.3426826011 | 0.0948698695 | 1.0 |
| exact_absent_out_of_domain | 0.0 | 0 | None | None | None |

Definition: generalisation strata of the frozen TRAIN-only OOD calibration: frequent exacts (exact cell support >= 20), rare exacts (0 < support < 20), exact cell absent but every single-feature label in-domain, and exact-absent out-of-domain / extrapolation. The rare-exact and exact-absent-in-domain rows are answered by the learned function rather than abstained, which is the generalization property the ticket asks for; the exact-absent-out-of-domain stratum is empty on VALIDATION and abstention is exercised on the OOD probes instead.

## 5. OOD gate

Statuses `MODEL_SUPPORTED/MODEL_SUPPORTED_HIGH_UNCERTAINTY/MODEL_OOD_ABSTAIN`; measured out-of-fold TRAIN shares: supported `0.790417`, high uncertainty `0.20925`, abstain `0.000333`. Hard reasons `UNSEEN_CATEGORY, EXTRAPOLATION_STACK, EXTRAPOLATION_SIZING, EXTRAPOLATION_PRICE, MISSING_DOMAIN_AXIS` abstain fail-closed; an exact context never seen in TRAIN stays in-domain by definition and can only raise the status to high uncertainty.

On the frozen VALIDATION decisions the gate answered 9777 as supported, 1761 as high uncertainty and 0 as abstained; abstention is exercised on the OOD probes of `OOD_CALIBRATION_REPORT.json` (never-seen category, stack/price/sizing extrapolation).

## 6. Raise-sizing gate

Frozen criterion `SIZING_NOT_INFERIOR_TO_FROZEN_TRAIN_EVIDENCE`: 7/7 #388/#419 raise-sizing frontiers are resolved by the conditional sizing density, 0 fail-closed, 27627 generated sizings of which 0 illegal (rate `0.0` against the frozen maximum `0.0`). No nearest-price or nearest-context substitution is applied (`no_nearest_price_substitution=true`).

## 7. #367 preflight

`ISSUE367_PREFLIGHT.json` walks the 38 required scenario #321 nodes and 7 raise-sizing frontiers: 38 direct evaluations, 0 explicit abstentions, hero EV executed `false`, #367 executed `false`. Admission is `FORBIDDEN` because the VALIDATION outcome is `RETAIN_REFERENCE_GENERALIZATION_INSUFFICIENT`; #367 keeps its currently admitted model.

## 8. Digest verification (recomputed vs persisted)

Every digest this bundle persists is recomputed from the persisted bytes: 36 cross-references declared by the frozen artifacts and every `.sha256` sidecar were re-derived and all match (`digest_verification.all_recomputed_digests_match_persisted = true`). This closes the #352 failure mode, where a self-reported digest was recorded without ever being recomputed.

| artifact | byte SHA256 | canonical payload SHA256 |
| --- | --- | --- |
| GENERALIZED_RESPONSE_MODEL_SPEC.json | `486ef55e14cdc1160faef7e53ac29631f1e13a9953b4f4996a8b3b052b185abf` | `ee744adcfd0413719430725f1bb3bbd4e5ff341cbd8b038e8ce533dbf8348dd8` |
| TRAIN_CV_REPORT.json | `43d9fffff98aeae1f51d0bdd78647a2dedbd58403a0591433d22840a5cf996ff` | `dee8ebbdfa8c65e462cf46bfb39a5ff2e0d0e576da85769d90fde9193d618814` |
| CANDIDATE_MANIFEST.json | `06f8380ea898d41efc9f7dbe65968292fd1277fe750229e0059b4df5918f8fea` | `4a9cbcd3ddc2bab6500803c08a5876d5ebad47c2f460be00c37292fd9dbf69e7` |
| FROZEN_VALIDATION_PROTOCOL.json | `ff91421b372dab869b8603fac04e7cb15b4b810f4c742c0fff4139786d97cdd5` | `7c703fd934629b239293932fd0a7349957b0fdd48538154429f4597da74883ce` |
| VALIDATION_RESULT.json | `6a8f02b6ea92d2906f9681684f572926601d6bab7bd78bb14bc8efd424f516c3` | `48a166f30854d88b693fa2c70fe32c1d3cfb41c2e23ddeacf57ea37e6f9d18c6` |
| OOD_CALIBRATION_REPORT.json | `a8f1b181f0d3ff3fd48dd3d58181a844760409f036e0b11f440ff7553dfc0b71` | `e438d99c4114cef37ded4c76d5bdcaf557f47f818bc66fc40fb36de0adca6530` |
| RAISE_SIZING_MODEL_REPORT.json | `955b926a5d19efe4998abfeae416792f85284d167cfaf9306315cb639320e9f6` | `1cb19b27bd0de7f44f19151cfe9e8fb536b2899c4257ea664f1e4d31a582791f` |
| ISSUE367_PREFLIGHT.json | `4b7c757f9f4bd8f2aac83d2ec1f4106dbb67a4ab5a5df31c30c02fbdac9cb7d1` | `575a1eb46f5c2fc96e2e917cb876fe8ce8f2311bb1f3a6fe5e147e16d6b2d0a2` |
| DECISION.json | `8783fbc871853821270ed5fe92cda22a8e69c229af557383894c883d507211ea` | `8f68483ec52517b7897b5dc7f32a4344081c18cd1f6132bccf56c784f3725379` |
| SUMMARY.md | `see ARTIFACTS.json` | n/a |

## 9. Boundaries

- `TEST_CONSUMED=false` — TEST is refused by the loader, the runtime and the self-scans; `test_authorized=false`, `test_consumed=false`, and the persisted dataset refuses `TEST` (2449 hands stay untouched).
- `ACTIVE_POINTER_MUTATED=false` — the active Model A pointer `training/models/preflop_population_model_v5.json` (`ff952055ca4ee051a3ac9607d513fdecac0a320a31f658ecfd8a11d8448975ca`) and the Model B pointer are unchanged before and after the whole cycle; no promotion is performed.
- `VALIDATION_CONSUMED=true` exactly once (the frozen one-shot read, `validation_reads=1`); it is never re-opened, re-scored or re-tuned and no threshold moved after the read.
- #367 is neither executed nor authorized by this bundle; no Hero EV, no Model B and no rollout are computed.

## 10. Reproduce and verify

```text
python3 tools/training/build_issue421_evidence_bundle.py
python3 tools/training/build_issue421_evidence_bundle.py --check
python3 tests/training/test_issue421_evidence_bundle.py
```

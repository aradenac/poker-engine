# Active CI workflow DAG

Generated for issue #204 (DAG v2, originally #382) from base `4559315b08fd224409c5469a4073e07ee89225b3` against inventory snapshot `4559315b08fd224409c5469a4073e07ee89225b3`. This is a static model, not billed-minute telemetry.

Active workflows: **54** (automatic triggers); manual-only excluded: **15**; jobs: **96**; cost proxy: **598**.

The active DAG is exactly the set of workflows carrying at least one automatic trigger (`push`, `pull_request`, `workflow_run`, ...). The #373 historical quarantine migrated the `workflow_dispatch`-only workflows to manual-only; they are listed as excluded below and never contribute to the active runs/jobs/cost counts.

## Workflows

| Workflow | Role | Triggers | Jobs | Side effect | REPRO | Concurrency |
|---|---|---|---:|---|---|---|
| `.github/workflows/analysis-state-contract.yml` | validation_or_utility | push, pull_request | 1 | READ_ONLY | REPRO_NOT_VERIFIED | `analysis-state-contract-${{ github.ref }}` / cancel=true |
| `.github/workflows/continuous-training-cycle.yml` | training_orchestration | push, pull_request, workflow_dispatch | 3 | ARTIFACT_ONLY | REPRO_STRONG_IDENTITY_BOUND | `continuous-training-cycle-${{ github.ref }}` / cancel=false |
| `.github/workflows/dataset-integrity.yml` | dataset_population | push, pull_request, workflow_dispatch | 1 | READ_ONLY | REPRO_COMPOSITE_VERIFIED | `${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}` / cancel=true |
| `.github/workflows/full-hand-arena.yml` | simulation_benchmark | pull_request, workflow_dispatch | 2 | ARTIFACT_ONLY | REPRO_COMPOSITE_VERIFIED | none |
| `.github/workflows/full-hand-protocol.yml` | simulation_benchmark | pull_request, push, workflow_dispatch | 1 | READ_ONLY | REPRO_COMPOSITE_VERIFIED | none |
| `.github/workflows/game-core.yml` | simulation_benchmark | pull_request, workflow_dispatch | 1 | UNKNOWN | REPRO_HELPER_VERIFIED | none |
| `.github/workflows/hero-calculated-range-export.yml` | hero_preflop | pull_request, workflow_dispatch | 1 | ARTIFACT_ONLY | REPRO_COMPOSITE_VERIFIED | none |
| `.github/workflows/hero-full-169-evidence.yml` | hero_preflop | pull_request, workflow_dispatch | 4 | ARTIFACT_ONLY | REPRO_NOT_VERIFIED | `hero-full-169-${{ github.event.pull_request.number || github.ref }}` / cancel=true |
| `.github/workflows/hero-pfpc-evidence-validation.yml` | hero_preflop | pull_request, push | 1 | READ_ONLY | REPRO_NOT_VERIFIED | none |
| `.github/workflows/hero-population-strategy.yml` | hero_preflop | push, pull_request | 1 | READ_ONLY | REPRO_INCOMPLETE | `hero-population-strategy-${{ github.ref }}` / cancel=true |
| `.github/workflows/hero-range-compliance.yml` | product_browser_validation | push, pull_request | 2 | READ_ONLY | REPRO_COMPOSITE_VERIFIED | `hero-range-compliance-${{ github.ref }}` / cancel=true |
| `.github/workflows/hero-range-editor.yml` | product_browser_validation | push, pull_request | 2 | READ_ONLY | REPRO_COMPOSITE_VERIFIED | `hero-range-editor-${{ github.ref }}` / cancel=true |
| `.github/workflows/hero-range-pfc-context.yml` | hero_preflop | workflow_dispatch, pull_request, push | 1 | UNKNOWN | REPRO_HELPER_VERIFIED | `hero-range-pfc-context-${{ github.ref }}` / cancel=true |
| `.github/workflows/hero-unopened-multiposition-generation.yml` | hero_preflop | workflow_dispatch, push | 5 | ARTIFACT_ONLY | REPRO_NOT_VERIFIED | `hero-unopened-multiposition-${{ github.ref }}` / cancel=true |
| `.github/workflows/ingest-artifacts.yml` | dataset_population | push | 1 | REPOSITORY_WRITE | REPRO_HELPER_VERIFIED | `artifact-ingest-${{ github.ref }}` / cancel=false |
| `.github/workflows/issue-358-hero-preflop-generation.yml` | hero_preflop | push | 4 | REPOSITORY_WRITE | REPRO_NOT_VERIFIED | `issue-358-hero-preflop-generation` / cancel=true |
| `.github/workflows/issue-367-real-iso-ev-observable.yml` | validation_or_utility | pull_request | 1 | ARTIFACT_ONLY | REPRO_NOT_VERIFIED | `issue-367-real-iso-ev-observable-${{ github.sha }}` / cancel=false |
| `.github/workflows/issue-367-real-iso-ev.yml` | validation_or_utility | pull_request, push | 2 | ARTIFACT_ONLY | REPRO_NOT_VERIFIED | `issue-367-real-iso-ev-${{ github.event_name }}-${{ github.ref }}` / cancel=false |
| `.github/workflows/materialize-certified-population.yml` | dataset_population | push, pull_request | 3 | REPOSITORY_WRITE | REPRO_STRONG_IDENTITY_BOUND | `materialize-certified-population-${{ github.ref }}` / cancel=true |
| `.github/workflows/model-a-continuation.yml` | validation_or_utility | pull_request, push, workflow_dispatch | 1 | READ_ONLY | REPRO_HELPER_VERIFIED | none |
| `.github/workflows/model-b-aggressive-tail.yml` | model_b | workflow_dispatch, push | 1 | REPOSITORY_WRITE | REPRO_NOT_VERIFIED | `model-b-aggressive-tail-issue-298` / cancel=true |
| `.github/workflows/model-b-card-aware-fit.yml` | model_b | workflow_dispatch, push | 1 | REPOSITORY_WRITE | REPRO_NOT_VERIFIED | `model-b-card-aware-fit-${{ github.ref }}` / cancel=true |
| `.github/workflows/model-b-card-aware-runtime.yml` | model_b | push, pull_request | 1 | READ_ONLY | REPRO_COMPOSITE_VERIFIED | none |
| `.github/workflows/model-b-observed-vs-simulated-calibration.yml` | model_b | workflow_dispatch, push | 1 | REPOSITORY_WRITE | REPRO_NOT_VERIFIED | `model-b-observed-vs-simulated-calibration-issue-272` / cancel=true |
| `.github/workflows/model-b-preflop-response-price-2a.yml` | model_b | workflow_dispatch, pull_request, push | 1 | REPOSITORY_WRITE | REPRO_NOT_VERIFIED | `${{ github.workflow }}-${{ github.event_name }}-${{ github.ref }}` / cancel=true |
| `.github/workflows/model-b-preflop-response-price-scaffold.yml` | model_b | workflow_dispatch, push | 1 | REPOSITORY_WRITE | REPRO_NOT_VERIFIED | `model-b-preflop-response-price-scaffold-315` / cancel=true |
| `.github/workflows/model-b-preflop-sensitivity-harness.yml` | model_b | workflow_dispatch, pull_request, push | 1 | REPOSITORY_WRITE | REPRO_NOT_VERIFIED | `${{ github.workflow }}-${{ github.event_name }}-${{ github.ref }}` / cancel=true |
| `.github/workflows/model-b-response-audit.yml` | model_b | workflow_dispatch, push | 1 | REPOSITORY_WRITE | REPRO_NOT_VERIFIED | none |
| `.github/workflows/model-b-response-to-price-evaluation.yml` | model_b | workflow_dispatch, push | 1 | REPOSITORY_WRITE | REPRO_NOT_VERIFIED | `model-b-response-to-price-issue-197` / cancel=true |
| `.github/workflows/model-b-reveal-aware.yml` | model_b | pull_request, workflow_dispatch | 1 | ARTIFACT_ONLY | REPRO_COMPOSITE_VERIFIED | none |
| `.github/workflows/model-b-support-aware-backoff.yml` | model_b | workflow_dispatch, push | 1 | REPOSITORY_WRITE | REPRO_NOT_VERIFIED | `model-b-support-aware-backoff-issue-286` / cancel=true |
| `.github/workflows/persist-issue-107-pfpc.yml` | validation_or_utility | workflow_run, pull_request, push | 2 | REPOSITORY_WRITE | REPRO_NOT_VERIFIED | `persist-issue-107-pfpc-d7ec5e532dc5` / cancel=false |
| `.github/workflows/plan-ingested-cycle.yml` | dataset_population | workflow_run, push, pull_request, workflow_dispatch | 3 | REPOSITORY_WRITE | REPRO_STRONG_IDENTITY_BOUND | `plan-ingested-cycle-${{ github.event_name == 'workflow_run' && 'main' || github.ref }}` / cancel=false |
| `.github/workflows/population-certification.yml` | dataset_population | push, pull_request, workflow_dispatch | 2 | ARTIFACT_ONLY | REPRO_STRONG_IDENTITY_BOUND | none |
| `.github/workflows/population-pack-catalog.yml` | product_browser_validation | pull_request, workflow_dispatch | 2 | READ_ONLY | REPRO_COMPOSITE_VERIFIED | `population-pack-catalog-${{ github.ref }}` / cancel=true |
| `.github/workflows/population-pack-real-admission-audit.yml` | validation_or_utility | pull_request, push | 2 | REPOSITORY_WRITE | REPRO_STRONG_IDENTITY_BOUND | `${{ github.workflow }}-${{ github.event_name }}-${{ github.ref }}` / cancel=true |
| `.github/workflows/population-pack.yml` | validation_or_utility | pull_request, push, workflow_dispatch | 3 | PUBLICATION_CAPABLE | REPRO_STRONG_IDENTITY_BOUND | none |
| `.github/workflows/postflop-response-refit.yml` | validation_or_utility | push, pull_request, workflow_dispatch | 1 | ARTIFACT_ONLY | REPRO_COMPOSITE_VERIFIED | `postflop-continuation-${{ github.ref }}` / cancel=true |
| `.github/workflows/preflop-contract.yml` | preflop_strategy | pull_request, workflow_dispatch | 1 | UNKNOWN | REPRO_HELPER_VERIFIED | none |
| `.github/workflows/preflop-grid-evaluator.yml` | preflop_strategy | pull_request, workflow_dispatch | 1 | READ_ONLY | REPRO_COMPOSITE_VERIFIED | none |
| `.github/workflows/preflop-policy169.yml` | preflop_strategy | pull_request, workflow_dispatch | 1 | READ_ONLY | REPRO_COMPOSITE_VERIFIED | `preflop-policy169-${{ github.ref }}` / cancel=true |
| `.github/workflows/preflop-search.yml` | preflop_strategy | push, pull_request | 1 | READ_ONLY | REPRO_COMPOSITE_VERIFIED | `preflop-search-${{ github.ref }}` / cancel=true |
| `.github/workflows/preflop-strategy-benchmark-v2.yml` | preflop_strategy | workflow_dispatch, pull_request, push | 1 | UNKNOWN | REPRO_NOT_VERIFIED | `preflop-strategy-benchmark-v2-${{ github.ref }}` / cancel=true |
| `.github/workflows/preflop-strategy-test-pfpc.yml` | preflop_strategy | pull_request, push | 6 | REPOSITORY_WRITE | REPRO_NOT_VERIFIED | `preflop-strategy-pfpc-test-20260918` / cancel=false |
| `.github/workflows/preflop-strategy-validation-pfpc.yml` | preflop_strategy | pull_request, push | 5 | REPOSITORY_WRITE | REPRO_NOT_VERIFIED | `preflop-strategy-pfpc-validation-20260918` / cancel=false |
| `.github/workflows/preflop-topology-contract.yml` | preflop_strategy | push, pull_request, workflow_dispatch | 1 | READ_ONLY | REPRO_HELPER_VERIFIED | none |
| `.github/workflows/project-state-consistency.yml` | validation_or_utility | pull_request, push | 1 | READ_ONLY | REPRO_NOT_VERIFIED | none |
| `.github/workflows/recover-issue-107-pfpc.yml` | validation_or_utility | pull_request, push | 2 | REPOSITORY_WRITE | REPRO_NOT_VERIFIED | `recover-issue-107-pfpc-d7ec5e532dc5` / cancel=false |
| `.github/workflows/release-handoff-contract.yml` | release_promotion | pull_request, push | 1 | READ_ONLY | REPRO_COMPOSITE_VERIFIED | `release-handoff-contract-${{ github.ref }}` / cancel=true |
| `.github/workflows/release-no-pending-snapshot-proof.yml` | release_promotion | pull_request, push | 2 | REPOSITORY_WRITE | REPRO_HELPER_VERIFIED | `release-no-pending-snapshot-proof-20260918` / cancel=false |
| `.github/workflows/repro-scientific-environment.yml` | validation_or_utility | workflow_call, pull_request, push | 1 | ARTIFACT_ONLY | REPRO_INCOMPLETE | `repro-scientific-environment-${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}` / cancel=true |
| `.github/workflows/sequential-arena.yml` | simulation_benchmark | push, pull_request | 4 | ARTIFACT_ONLY | REPRO_NOT_VERIFIED | `sequential-arena-${{ github.ref }}` / cancel=true |
| `.github/workflows/trainer-smoke.yml` | product_browser_validation | push, pull_request | 2 | READ_ONLY | REPRO_COMPOSITE_VERIFIED | `trainer-smoke-${{ github.ref }}` / cancel=true |
| `.github/workflows/user-artifact-bundle.yml` | validation_or_utility | pull_request, push, workflow_dispatch | 2 | ARTIFACT_ONLY | REPRO_STRONG_IDENTITY_BOUND | none |

## Manual-only workflows excluded

These workflows subscribe to `workflow_dispatch` only (historical evidence, quarantined by #373). They are outside the active DAG by construction.

- `.github/workflows/finalize-training-cycle.yml`
- `.github/workflows/model-b-build.yml`
- `.github/workflows/model-b-conditioned-runtime.yml`
- `.github/workflows/model-b-evaluation.yml`
- `.github/workflows/model-b-features.yml`
- `.github/workflows/model-b-profile-selection.yml`
- `.github/workflows/model-b-response-v3.yml`
- `.github/workflows/preflop-strategy-support-closed.yml`
- `.github/workflows/preflop-strategy-validation-support-closed.yml`
- `.github/workflows/preflop-strategy-validation-v2.yml`
- `.github/workflows/promotion-gate-final.yml`
- `.github/workflows/strategic-benchmark-v3.yml`
- `.github/workflows/strategy-candidate-v84.yml`
- `.github/workflows/unseen-preflop-context-audit.yml`
- `.github/workflows/v84-strategy-candidate.yml`

## workflow_run edges

- `.github/workflows/hero-unopened-multiposition-generation.yml` → `.github/workflows/persist-issue-107-pfpc.yml`
- `.github/workflows/ingest-artifacts.yml` → `.github/workflows/plan-ingested-cycle.yml`

## Representative change simulations

| Scenario | Event | Before runs/jobs/cost | After runs/jobs/cost | Write-capable jobs after | Status |
|---|---|---:|---:|---:|---|
| repro_runtime_composite | pull_request | 17/22/92 | 17/22/92 | 0 | SUPPORTED_STATIC_SUBSET |
| repro_browser_composite | pull_request | 4/7/25 | 4/7/25 | 0 | SUPPORTED_STATIC_SUBSET |
| trainer_js | pull_request | 5/7/31 | 5/7/31 | 0 | SUPPORTED_STATIC_SUBSET |
| game_core | pull_request | 6/8/71 | 6/8/71 | 0 | SUPPORTED_STATIC_SUBSET |
| preflop_decision | pull_request | 5/5/23 | 5/5/23 | 0 | SUPPORTED_STATIC_SUBSET |
| dataset_nlhe_100_200 | push | 4/8/57 | 4/8/57 | 0 | UNKNOWN |
| preflop_model | pull_request | 5/9/53 | 5/9/53 | 0 | UNKNOWN |
| repro_helper | push | 10/11/52 | 10/11/52 | 2 | UNKNOWN |
| python_version | pull_request | 20/22/115 | 20/22/115 | 0 | UNKNOWN |
| node_version | pull_request | 12/14/74 | 12/14/74 | 0 | SUPPORTED_STATIC_SUBSET |
| release_handoff_tooling | pull_request | 3/3/11 | 3/3/11 | 0 | SUPPORTED_STATIC_SUBSET |
| model_b_training | push | 3/3/11 | 3/3/11 | 0 | SUPPORTED_STATIC_SUBSET |
| docs_only | pull_request | 1/1/5 | 1/1/5 | 0 | SUPPORTED_STATIC_SUBSET |
| historical_manual_workflow | pull_request | 1/1/5 | 1/1/5 | 0 | SUPPORTED_STATIC_SUBSET |

This tranche is audit-only: the pinned base and HEAD carry byte-identical workflow definitions, so the
`before`/`after` columns coincide by construction. The scenario model itself is unchanged and stays fail-closed;
a future tranche that edits triggers or concurrency must re-pin the base to observe a delta.

## Concurrency recommendations

Recommendations are read-only. `UNKNOWN`, repository-write, and publication-capable workflows are never marked safe.

| Workflow | Has concurrency | Cancel now | Safe future candidate | Blockers |
|---|---:|---:|---:|---|
| `.github/workflows/analysis-state-contract.yml` | true | True | true | none |
| `.github/workflows/continuous-training-cycle.yml` | true | False | true | none |
| `.github/workflows/dataset-integrity.yml` | true | True | true | none |
| `.github/workflows/full-hand-arena.yml` | false | None | true | none |
| `.github/workflows/full-hand-protocol.yml` | false | None | true | none |
| `.github/workflows/game-core.yml` | false | None | false | write/publication or unknown permission surface |
| `.github/workflows/hero-calculated-range-export.yml` | false | None | true | none |
| `.github/workflows/hero-full-169-evidence.yml` | true | True | true | none |
| `.github/workflows/hero-pfpc-evidence-validation.yml` | false | None | true | none |
| `.github/workflows/hero-population-strategy.yml` | true | True | true | none |
| `.github/workflows/hero-range-compliance.yml` | true | True | true | none |
| `.github/workflows/hero-range-editor.yml` | true | True | true | none |
| `.github/workflows/hero-range-pfc-context.yml` | true | True | false | write/publication or unknown permission surface |
| `.github/workflows/hero-unopened-multiposition-generation.yml` | true | True | true | none |
| `.github/workflows/ingest-artifacts.yml` | true | False | false | write/publication or unknown permission surface |
| `.github/workflows/issue-358-hero-preflop-generation.yml` | true | True | false | write/publication or unknown permission surface |
| `.github/workflows/issue-367-real-iso-ev-observable.yml` | true | False | true | none |
| `.github/workflows/issue-367-real-iso-ev.yml` | true | False | true | none |
| `.github/workflows/materialize-certified-population.yml` | true | True | false | write/publication or unknown permission surface |
| `.github/workflows/model-a-continuation.yml` | false | None | true | none |
| `.github/workflows/model-b-aggressive-tail.yml` | true | True | false | write/publication or unknown permission surface |
| `.github/workflows/model-b-card-aware-fit.yml` | true | True | false | write/publication or unknown permission surface |
| `.github/workflows/model-b-card-aware-runtime.yml` | false | None | true | none |
| `.github/workflows/model-b-observed-vs-simulated-calibration.yml` | true | True | false | write/publication or unknown permission surface |
| `.github/workflows/model-b-preflop-response-price-2a.yml` | true | True | false | write/publication or unknown permission surface |
| `.github/workflows/model-b-preflop-response-price-scaffold.yml` | true | True | false | write/publication or unknown permission surface |
| `.github/workflows/model-b-preflop-sensitivity-harness.yml` | true | True | false | write/publication or unknown permission surface |
| `.github/workflows/model-b-response-audit.yml` | false | None | false | write/publication or unknown permission surface |
| `.github/workflows/model-b-response-to-price-evaluation.yml` | true | True | false | write/publication or unknown permission surface |
| `.github/workflows/model-b-reveal-aware.yml` | false | None | true | none |
| `.github/workflows/model-b-support-aware-backoff.yml` | true | True | false | write/publication or unknown permission surface |
| `.github/workflows/persist-issue-107-pfpc.yml` | true | False | false | write/publication or unknown permission surface |
| `.github/workflows/plan-ingested-cycle.yml` | true | False | false | write/publication or unknown permission surface |
| `.github/workflows/population-certification.yml` | false | None | true | none |
| `.github/workflows/population-pack-catalog.yml` | true | True | true | none |
| `.github/workflows/population-pack-real-admission-audit.yml` | true | True | false | write/publication or unknown permission surface |
| `.github/workflows/population-pack.yml` | false | None | false | write/publication or unknown permission surface |
| `.github/workflows/postflop-response-refit.yml` | true | True | true | none |
| `.github/workflows/preflop-contract.yml` | false | None | false | write/publication or unknown permission surface |
| `.github/workflows/preflop-grid-evaluator.yml` | false | None | true | none |
| `.github/workflows/preflop-policy169.yml` | true | True | true | none |
| `.github/workflows/preflop-search.yml` | true | True | true | none |
| `.github/workflows/preflop-strategy-benchmark-v2.yml` | true | True | false | write/publication or unknown permission surface |
| `.github/workflows/preflop-strategy-test-pfpc.yml` | true | False | false | write/publication or unknown permission surface |
| `.github/workflows/preflop-strategy-validation-pfpc.yml` | true | False | false | write/publication or unknown permission surface |
| `.github/workflows/preflop-topology-contract.yml` | false | None | true | none |
| `.github/workflows/project-state-consistency.yml` | false | None | true | none |
| `.github/workflows/recover-issue-107-pfpc.yml` | true | False | false | write/publication or unknown permission surface |
| `.github/workflows/release-handoff-contract.yml` | true | True | true | none |
| `.github/workflows/release-no-pending-snapshot-proof.yml` | true | False | false | write/publication or unknown permission surface |
| `.github/workflows/repro-scientific-environment.yml` | true | True | true | none |
| `.github/workflows/sequential-arena.yml` | true | True | true | none |
| `.github/workflows/trainer-smoke.yml` | true | True | true | none |
| `.github/workflows/user-artifact-bundle.yml` | false | None | true | none |

## Static-model boundary

Path and branch filtering uses the documented literal/`*`/`**` subset. Complex job expressions are reported as `UNKNOWN`; they are retained as potentially reachable and never used to claim safety.

# Active CI workflow DAG

Generated for issue #382 from base `ac208d26cbf3f16b498fd5333ad3b7c4fa58355b`. This is a static model, not billed-minute telemetry.

Active workflows: **31**; jobs: **50**; cost proxy: **235**.

## Workflows

| Workflow | Role | Triggers | Jobs | Side effect | REPRO | Concurrency |
|---|---|---|---:|---|---|---|
| `.github/workflows/continuous-training-cycle.yml` | training_orchestration | push, pull_request, workflow_dispatch | 3 | ARTIFACT_ONLY | REPRO_STRONG_IDENTITY_BOUND | `continuous-training-cycle-${{ github.ref }}` / cancel=false |
| `.github/workflows/dataset-integrity.yml` | dataset_population | push, pull_request, workflow_dispatch | 1 | READ_ONLY | REPRO_NOT_VERIFIED | `${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}` / cancel=true |
| `.github/workflows/full-hand-arena.yml` | simulation_benchmark | pull_request, workflow_dispatch | 2 | ARTIFACT_ONLY | REPRO_NOT_VERIFIED | none |
| `.github/workflows/full-hand-protocol.yml` | simulation_benchmark | pull_request, push, workflow_dispatch | 1 | READ_ONLY | REPRO_NOT_VERIFIED | none |
| `.github/workflows/game-core.yml` | simulation_benchmark | pull_request, workflow_dispatch | 1 | UNKNOWN | REPRO_NOT_VERIFIED | none |
| `.github/workflows/hero-calculated-range-export.yml` | hero_preflop | pull_request, workflow_dispatch | 1 | ARTIFACT_ONLY | REPRO_NOT_VERIFIED | none |
| `.github/workflows/hero-range-compliance.yml` | product_browser_validation | push, pull_request | 2 | READ_ONLY | REPRO_NOT_VERIFIED | `hero-range-compliance-${{ github.ref }}` / cancel=true |
| `.github/workflows/hero-range-editor.yml` | product_browser_validation | push, pull_request | 2 | READ_ONLY | REPRO_NOT_VERIFIED | `hero-range-editor-${{ github.ref }}` / cancel=true |
| `.github/workflows/hero-range-pfc-context.yml` | hero_preflop | workflow_dispatch, pull_request, push | 1 | UNKNOWN | REPRO_HELPER_VERIFIED | `hero-range-pfc-context-${{ github.ref }}` / cancel=true |
| `.github/workflows/ingest-artifacts.yml` | dataset_population | push | 1 | REPOSITORY_WRITE | REPRO_HELPER_VERIFIED | `artifact-ingest-${{ github.ref }}` / cancel=false |
| `.github/workflows/materialize-certified-population.yml` | dataset_population | push, pull_request | 3 | REPOSITORY_WRITE | REPRO_STRONG_IDENTITY_BOUND | `materialize-certified-population-${{ github.ref }}` / cancel=true |
| `.github/workflows/model-a-continuation.yml` | validation_or_utility | pull_request, push, workflow_dispatch | 1 | READ_ONLY | REPRO_NOT_VERIFIED | none |
| `.github/workflows/model-b-card-aware-fit.yml` | model_b | workflow_dispatch, push | 1 | REPOSITORY_WRITE | REPRO_NOT_VERIFIED | `model-b-card-aware-fit-${{ github.ref }}` / cancel=true |
| `.github/workflows/model-b-card-aware-runtime.yml` | model_b | push, pull_request | 1 | READ_ONLY | REPRO_NOT_VERIFIED | none |
| `.github/workflows/model-b-response-audit.yml` | model_b | workflow_dispatch, push | 1 | REPOSITORY_WRITE | REPRO_NOT_VERIFIED | none |
| `.github/workflows/model-b-reveal-aware.yml` | model_b | pull_request, workflow_dispatch | 1 | ARTIFACT_ONLY | REPRO_NOT_VERIFIED | none |
| `.github/workflows/plan-ingested-cycle.yml` | dataset_population | workflow_run, push, pull_request, workflow_dispatch | 3 | REPOSITORY_WRITE | REPRO_STRONG_IDENTITY_BOUND | `plan-ingested-cycle-${{ github.event_name == 'workflow_run' && 'main' || github.ref }}` / cancel=false |
| `.github/workflows/population-certification.yml` | dataset_population | push, pull_request, workflow_dispatch | 2 | ARTIFACT_ONLY | REPRO_STRONG_IDENTITY_BOUND | none |
| `.github/workflows/population-pack-catalog.yml` | product_browser_validation | pull_request, workflow_dispatch | 2 | READ_ONLY | REPRO_NOT_VERIFIED | `population-pack-catalog-${{ github.ref }}` / cancel=true |
| `.github/workflows/population-pack.yml` | validation_or_utility | pull_request, push, workflow_dispatch | 3 | PUBLICATION_CAPABLE | REPRO_STRONG_IDENTITY_BOUND | none |
| `.github/workflows/postflop-response-refit.yml` | validation_or_utility | push, pull_request, workflow_dispatch | 1 | ARTIFACT_ONLY | REPRO_NOT_VERIFIED | `postflop-continuation-${{ github.ref }}` / cancel=true |
| `.github/workflows/preflop-contract.yml` | preflop_strategy | pull_request, workflow_dispatch | 1 | UNKNOWN | REPRO_NOT_VERIFIED | none |
| `.github/workflows/preflop-grid-evaluator.yml` | preflop_strategy | pull_request, workflow_dispatch | 1 | READ_ONLY | REPRO_NOT_VERIFIED | none |
| `.github/workflows/preflop-policy169.yml` | preflop_strategy | pull_request, workflow_dispatch | 1 | READ_ONLY | REPRO_NOT_VERIFIED | `preflop-policy169-${{ github.ref }}` / cancel=true |
| `.github/workflows/preflop-search.yml` | preflop_strategy | push, pull_request | 1 | READ_ONLY | REPRO_NOT_VERIFIED | `preflop-search-${{ github.ref }}` / cancel=true |
| `.github/workflows/preflop-topology-contract.yml` | preflop_strategy | push, pull_request, workflow_dispatch | 1 | READ_ONLY | REPRO_NOT_VERIFIED | none |
| `.github/workflows/release-handoff-contract.yml` | release_promotion | pull_request, push | 1 | READ_ONLY | REPRO_NOT_VERIFIED | `release-handoff-contract-${{ github.ref }}` / cancel=true |
| `.github/workflows/release-no-pending-snapshot-proof.yml` | release_promotion | pull_request, push | 2 | REPOSITORY_WRITE | REPRO_HELPER_VERIFIED | `release-no-pending-snapshot-proof-20260918` / cancel=false |
| `.github/workflows/sequential-arena.yml` | simulation_benchmark | push, pull_request | 4 | ARTIFACT_ONLY | REPRO_NOT_VERIFIED | `sequential-arena-${{ github.ref }}` / cancel=true |
| `.github/workflows/trainer-smoke.yml` | product_browser_validation | push, pull_request | 2 | READ_ONLY | REPRO_NOT_VERIFIED | `trainer-smoke-${{ github.ref }}` / cancel=true |
| `.github/workflows/user-artifact-bundle.yml` | validation_or_utility | pull_request, push, workflow_dispatch | 2 | ARTIFACT_ONLY | REPRO_STRONG_IDENTITY_BOUND | none |

## workflow_run edges

- `.github/workflows/ingest-artifacts.yml` → `.github/workflows/plan-ingested-cycle.yml`

## Representative change simulations

| Scenario | Event | Before runs/jobs/cost | After runs/jobs/cost | Write-capable jobs after | Status |
|---|---|---:|---:|---:|---|
| trainer_js | pull_request | 2/4/20 | 2/4/14 | 0 | SUPPORTED_STATIC_SUBSET |
| game_core | pull_request | 5/7/72 | 5/7/64 | 0 | SUPPORTED_STATIC_SUBSET |
| preflop_decision | pull_request | 4/4/24 | 4/4/14 | 0 | SUPPORTED_STATIC_SUBSET |
| dataset_nlhe_100_200 | push | 3/7/54 | 3/7/52 | 0 | UNKNOWN |
| preflop_model | pull_request | 3/4/22 | 3/4/18 | 0 | SUPPORTED_STATIC_SUBSET |
| repro_helper | push | 3/3/17 | 7/8/37 | 2 | UNKNOWN |
| python_version | pull_request | 10/12/81 | 14/16/77 | 0 | UNKNOWN |
| node_version | pull_request | 5/7/47 | 9/11/51 | 0 | SUPPORTED_STATIC_SUBSET |
| release_handoff_tooling | pull_request | 2/2/10 | 2/2/6 | 0 | SUPPORTED_STATIC_SUBSET |
| model_b_training | push | 2/2/10 | 2/2/6 | 0 | SUPPORTED_STATIC_SUBSET |
| docs_only | pull_request | 0/0/0 | 0/0/0 | 0 | SUPPORTED_STATIC_SUBSET |
| historical_manual_workflow | pull_request | 0/0/0 | 0/0/0 | 0 | SUPPORTED_STATIC_SUBSET |

## Concurrency recommendations

Recommendations are read-only. `UNKNOWN`, repository-write, and publication-capable workflows are never marked safe.

| Workflow | Has concurrency | Cancel now | Safe future candidate | Blockers |
|---|---:|---:|---:|---|
| `.github/workflows/continuous-training-cycle.yml` | true | False | true | none |
| `.github/workflows/dataset-integrity.yml` | true | True | true | none |
| `.github/workflows/full-hand-arena.yml` | false | None | true | none |
| `.github/workflows/full-hand-protocol.yml` | false | None | true | none |
| `.github/workflows/game-core.yml` | false | None | false | write/publication or unknown permission surface |
| `.github/workflows/hero-calculated-range-export.yml` | false | None | true | none |
| `.github/workflows/hero-range-compliance.yml` | true | True | true | none |
| `.github/workflows/hero-range-editor.yml` | true | True | true | none |
| `.github/workflows/hero-range-pfc-context.yml` | true | True | false | write/publication or unknown permission surface |
| `.github/workflows/ingest-artifacts.yml` | true | False | false | write/publication or unknown permission surface |
| `.github/workflows/materialize-certified-population.yml` | true | True | false | write/publication or unknown permission surface |
| `.github/workflows/model-a-continuation.yml` | false | None | true | none |
| `.github/workflows/model-b-card-aware-fit.yml` | true | True | false | write/publication or unknown permission surface |
| `.github/workflows/model-b-card-aware-runtime.yml` | false | None | true | none |
| `.github/workflows/model-b-response-audit.yml` | false | None | false | write/publication or unknown permission surface |
| `.github/workflows/model-b-reveal-aware.yml` | false | None | true | none |
| `.github/workflows/plan-ingested-cycle.yml` | true | False | false | write/publication or unknown permission surface |
| `.github/workflows/population-certification.yml` | false | None | true | none |
| `.github/workflows/population-pack-catalog.yml` | true | True | true | none |
| `.github/workflows/population-pack.yml` | false | None | false | write/publication or unknown permission surface |
| `.github/workflows/postflop-response-refit.yml` | true | True | true | none |
| `.github/workflows/preflop-contract.yml` | false | None | false | write/publication or unknown permission surface |
| `.github/workflows/preflop-grid-evaluator.yml` | false | None | true | none |
| `.github/workflows/preflop-policy169.yml` | true | True | true | none |
| `.github/workflows/preflop-search.yml` | true | True | true | none |
| `.github/workflows/preflop-topology-contract.yml` | false | None | true | none |
| `.github/workflows/release-handoff-contract.yml` | true | True | true | none |
| `.github/workflows/release-no-pending-snapshot-proof.yml` | true | False | false | write/publication or unknown permission surface |
| `.github/workflows/sequential-arena.yml` | true | True | true | none |
| `.github/workflows/trainer-smoke.yml` | true | True | true | none |
| `.github/workflows/user-artifact-bundle.yml` | false | None | true | none |

## Static-model boundary

Path and branch filtering uses the documented literal/`*`/`**` subset. Complex job expressions are reported as `UNKNOWN`; they are retained as potentially reachable and never used to claim safety.

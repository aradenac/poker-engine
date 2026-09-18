# Hero preflop future generation plan — TRAIN-only

Planning artifact only: no strategy, EV rollout, action/sizing recommendation, VALIDATION or TEST.

## Readiness

| State | Contexts |
|---|---:|
| READY_FOR_GENERATION | 44 |
| LOW_SUPPORT | 78 |
| DEFERRED | 80 |
| UNCOVERED | 1058 |

- Exact audit contexts: **1,260**
- Targeted TRAIN observations: **65,248**
- READY hand-class cells: **7,436**
- Planned READY shards: **6**

## Observed generation order

| Order | Group | TRAIN obs. | READY | LOW_SUPPORT | DEFERRED | UNCOVERED |
|---:|---|---:|---:|---:|---:|---:|
| 1 | VS_LIMPERS_ISO | 48,179 | 22 | 58 | 62 | 111 |
| 2 | VS_RFI | 9,467 | 14 | 11 | 4 | 1 |
| 3 | RFI_CALLERS_SQUEEZE | 4,662 | 8 | 8 | 2 | 2 |
| 4 | VS_3BET | 2,568 | 0 | 1 | 12 | 659 |
| 5 | VS_4BET_OR_JAM | 372 | 0 | 0 | 0 | 285 |

## Stack buckets

Derived from #251 global targeted TRAIN quantiles. Whole audit cells are classified by their observed p50; no sub-cell counts are invented.

| Bucket | Lower exclusive BB | Upper inclusive BB |
|---|---:|---:|
| B0_LE_P10 | — | 40 |
| B1_P10_P25 | 40 | 70.05 |
| B2_P25_P50 | 70.05 | 97.805 |
| B3_P50_P75 | 97.805 | 131.395 |
| B4_P75_P90 | 131.395 | 198.25150000000002 |
| B5_GT_P90 | 198.25150000000002 | — |

## Exact lookup / fallback

- NO SILENT NEAREST-CONTEXT. Lookup is exact context_id only.
- Fallback identifier: NO_NEAREST_CONTEXT__INCUMBENT_EXACT_OR_UNCOVERED_V1.
- Missing exact artifact: declared incumbent exact-context policy if separately available; otherwise EXACT_UNAVAILABLE / UNCOVERED.
- Nearest stack/position/family/aggressor/caller/limper/jam substitution is forbidden.

## Boundary

- Planning merge depends only on #251.
- Actual generation waits for explicit #108 release and the #198 integration decision.
- Actual rollouts executed: 0.
- VALIDATION=false; TEST=false; strategy_generated=false; ev_evaluated=false.

## Reproduction

    python3 tools/training/plan_hero_preflop_generation.py --audit analysis/hero_preflop_coverage_train.json --output-json analysis/hero_preflop_generation_plan.json --output-md analysis/hero_preflop_generation_plan.md

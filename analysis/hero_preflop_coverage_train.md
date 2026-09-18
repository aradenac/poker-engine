# Hero preflop coverage — TRAIN-only preparatory audit

Diagnostic only: no Hero strategy is generated and neither VALIDATION nor TEST decisions are consumed.

## Accounting

- Certified TRAIN hands parsed: **19,016 / 19,016**
- Population preflop decisions: **101,848**
- Targeted future-coverage decisions: **65,248**
- Effective-stack median (targeted): **97.8 BB**

## Family/group frequency

- VS_LIMPERS_ISO: 48,179 (47.30 % of population preflop decisions)
- UNOPENED: 36,600 (35.94 % of population preflop decisions)
- VS_RFI: 9,467 (9.30 % of population preflop decisions)
- RFI_CALLERS_SQUEEZE: 4,662 (4.58 % of population preflop decisions)
- VS_3BET: 2,568 (2.52 % of population preflop decisions)
- VS_4BET_OR_JAM: 372 (0.37 % of population preflop decisions)

## Highest-priority TRAIN-supported matrix cells

| Rank | Group | Family | Actor | Opener | Callers | Limpers | Jam | Obs. | Support |
|---:|---|---|---|---|---:|---:|:---:|---:|---|
| 1 | VS_LIMPERS_ISO | VS_LIMPERS | CO | — | 0 | 1 | no | 5750 | VERY_HIGH |
| 2 | VS_LIMPERS_ISO | VS_LIMPERS | BTN | — | 0 | 1 | no | 5315 | VERY_HIGH |
| 3 | VS_LIMPERS_ISO | VS_LIMPERS | HJ | — | 0 | 1 | no | 4438 | VERY_HIGH |
| 4 | VS_LIMPERS_ISO | VS_LIMPERS | SB | — | 0 | 1 | no | 4220 | VERY_HIGH |
| 5 | VS_LIMPERS_ISO | VS_LIMPERS | BB | — | 0 | 2 | no | 3412 | VERY_HIGH |
| 6 | VS_LIMPERS_ISO | VS_LIMPERS | SB | — | 0 | 2 | no | 3081 | VERY_HIGH |
| 7 | VS_LIMPERS_ISO | VS_LIMPERS | BB | — | 0 | 1 | no | 2869 | VERY_HIGH |
| 8 | VS_LIMPERS_ISO | VS_LIMPERS | BTN | — | 0 | 2 | no | 2460 | VERY_HIGH |
| 9 | VS_LIMPERS_ISO | VS_LIMPERS | BB | — | 0 | 3 | no | 1734 | VERY_HIGH |
| 10 | VS_RFI | VS_RFI | HJ | LJ | 0 | 0 | no | 1499 | VERY_HIGH |
| 11 | VS_LIMPERS_ISO | VS_LIMPERS | CO | — | 0 | 2 | no | 1232 | VERY_HIGH |
| 12 | VS_RFI | VS_RFI | CO | LJ | 0 | 0 | no | 1038 | VERY_HIGH |
| 13 | VS_LIMPERS_ISO | VS_LIMPERS | SB | — | 0 | 3 | no | 950 | HIGH |
| 14 | VS_RFI | VS_RFI | CO | HJ | 0 | 0 | no | 922 | HIGH |
| 15 | VS_RFI | VS_RFI | BTN | LJ | 0 | 0 | no | 700 | HIGH |
| 16 | VS_RFI | VS_RFI | BTN | HJ | 0 | 0 | no | 627 | HIGH |
| 17 | RFI_CALLERS_SQUEEZE | VS_RFI_CALLERS | SB | LJ | 1 | 0 | no | 603 | HIGH |
| 18 | VS_RFI | VS_RFI | BTN | CO | 0 | 0 | no | 582 | HIGH |
| 19 | RFI_CALLERS_SQUEEZE | VS_RFI_CALLERS | BTN | LJ | 1 | 0 | no | 561 | HIGH |
| 20 | VS_LIMPERS_ISO | VS_ISO | SB | BTN | 0 | 1 | no | 535 | HIGH |
| 21 | RFI_CALLERS_SQUEEZE | VS_RFI_CALLERS | BB | LJ | 1 | 0 | no | 530 | HIGH |
| 22 | VS_LIMPERS_ISO | VS_ISO | BTN | CO | 0 | 1 | no | 503 | HIGH |
| 23 | VS_RFI | VS_RFI | SB | LJ | 0 | 0 | no | 474 | HIGH |
| 24 | VS_RFI | VS_RFI | SB | HJ | 0 | 0 | no | 441 | HIGH |
| 25 | VS_LIMPERS_ISO | VS_ISO | CO | HJ | 0 | 1 | no | 412 | HIGH |
| 26 | VS_RFI | VS_RFI | SB | CO | 0 | 0 | no | 411 | HIGH |
| 27 | VS_LIMPERS_ISO | VS_LIMPERS | BB | — | 0 | 4 | no | 409 | HIGH |
| 28 | VS_RFI | VS_RFI | SB | BTN | 0 | 0 | no | 401 | HIGH |
| 29 | RFI_CALLERS_SQUEEZE | VS_RFI_CALLERS | CO | LJ | 1 | 0 | no | 400 | HIGH |
| 30 | VS_LIMPERS_ISO | VS_ISO | BB | SB | 0 | 1 | no | 378 | HIGH |
| 31 | RFI_CALLERS_SQUEEZE | VS_RFI_CALLERS | BB | HJ | 1 | 0 | no | 375 | HIGH |
| 32 | VS_LIMPERS_ISO | VS_ISO | BB | BTN | 0 | 1 | no | 374 | HIGH |
| 33 | RFI_CALLERS_SQUEEZE | VS_RFI_CALLERS | SB | HJ | 1 | 0 | no | 372 | HIGH |
| 34 | VS_LIMPERS_ISO | VS_ISO | SB | CO | 0 | 1 | no | 367 | HIGH |
| 35 | VS_LIMPERS_ISO | VS_LIMPERS | BTN | — | 0 | 3 | no | 347 | HIGH |
| 36 | VS_RFI | VS_RFI | BB | LJ | 0 | 0 | no | 338 | HIGH |
| 37 | RFI_CALLERS_SQUEEZE | VS_RFI_CALLERS | BB | LJ | 2 | 0 | no | 323 | HIGH |
| 38 | VS_RFI | VS_RFI | BB | HJ | 0 | 0 | no | 298 | HIGH |
| 39 | VS_LIMPERS_ISO | VS_ISO | BTN | HJ | 0 | 1 | no | 295 | HIGH |
| 40 | VS_LIMPERS_ISO | VS_ISO | BB | CO | 0 | 1 | no | 279 | HIGH |

## Reproduction

python3 tools/training/audit_hero_preflop_coverage.py --output-json analysis/hero_preflop_coverage_train.json --output-md analysis/hero_preflop_coverage_train.md

The tool verifies certification/archive SHA identities and filters to TRAIN hand IDs before normalization.

# Preflop sizing / price support — certified TRAIN audit

Descriptive TRAIN-only audit. No TEST, #108, active model, optimization, promotion, or UI effect.

## Accounting

- Certified TRAIN hands parsed: 19016
- Population preflop rows in requested families: 101476
- Distinct hands represented: 19016
- Revealed rows: 19903
- Unrevealed rows: 81573
- Reveal fraction: 0.1961
- TEST_CONSUMED=false

## Sizing semantics

- target_total_bb is the real public current price before a response.
- observed_action_target_total_bb is the real parsed raise/jam target.
- No fixed sizing grid is reconstructed.
- Empirical bins use observed equal-mass boundaries.
- Fold/call/raise/jam rates include their denominators.
- Revealed hand-class support is separate from marginal support.

## Support zones

- BACKOFF_RECOMMENDED: 161 cells
- IDENTIFIABLE_MARGINAL: 121 cells
- LOW_SUPPORT: 6544 cells

## KTs SB + two limpers

KTs is only the Hero use-case label. Opponent hidden cards are never used.
- SB public-context observations: 3081
- Observed SB iso targets: 2 BB (n=69), 5 BB (n=56), 3 BB (n=35), 4 BB (n=13), 6 BB (n=9), 10 BB (n=3), 7 BB (n=2), 8 BB (n=2), 9 BB (n=2), 1.785 BB (n=1), 3.6 BB (n=1), 7.11 BB (n=1), 7.875 BB (n=1), 14 BB (n=1), 14.2 BB (n=1), 15 BB (n=1), 17 BB (n=1), 28 BB (n=1), 29.435 BB (n=1), 29.485 BB (n=1)
- Exact opponent response support:
  - 4 BB: EXACT_SUPPORT (n=54, MEDIUM)
  - 5 BB: EXACT_SUPPORT (n=161, MEDIUM)
  - 6 BB: EXACT_SUPPORT (n=43, LOW)

## Highest-support exact price/context cells

| Family | Actor | Aggressor | Limpers | Callers | Target | To call | Obs | Tier |
|---|---|---|---:|---:|---:|---:|---:|---|
| UNOPENED | LJ | — | 0 | 0 | 1.0 | 1.0 | 15655 | VERY_HIGH |
| UNOPENED | HJ | — | 0 | 0 | 1.0 | 1.0 | 9773 | VERY_HIGH |
| UNOPENED | CO | — | 0 | 0 | 1.0 | 1.0 | 5797 | VERY_HIGH |
| VS_LIMPERS | CO | — | 1 | 0 | 1.0 | 1.0 | 5750 | VERY_HIGH |
| VS_LIMPERS | BTN | — | 1 | 0 | 1.0 | 1.0 | 5315 | VERY_HIGH |
| VS_LIMPERS | HJ | — | 1 | 0 | 1.0 | 1.0 | 4438 | VERY_HIGH |
| VS_LIMPERS | SB | — | 1 | 0 | 1.0 | 0.5 | 4220 | VERY_HIGH |
| UNOPENED | BTN | — | 0 | 0 | 1.0 | 1.0 | 3432 | VERY_HIGH |
| VS_LIMPERS | BB | — | 2 | 0 | 1.0 | 0.0 | 3412 | VERY_HIGH |
| VS_LIMPERS | SB | — | 2 | 0 | 1.0 | 0.5 | 3081 | VERY_HIGH |
| VS_LIMPERS | BB | — | 1 | 0 | 1.0 | 0.0 | 2869 | VERY_HIGH |
| VS_LIMPERS | BTN | — | 2 | 0 | 1.0 | 1.0 | 2460 | VERY_HIGH |
| UNOPENED | SB | — | 0 | 0 | 1.0 | 0.5 | 1943 | VERY_HIGH |
| VS_LIMPERS | BB | — | 3 | 0 | 1.0 | 0.0 | 1734 | VERY_HIGH |
| VS_LIMPERS | CO | — | 2 | 0 | 1.0 | 1.0 | 1232 | VERY_HIGH |
| VS_LIMPERS | SB | — | 3 | 0 | 1.0 | 0.5 | 950 | HIGH |
| VS_RFI | HJ | LJ | 0 | 0 | 2.0 | 2.0 | 459 | HIGH |
| VS_LIMPERS | BB | — | 4 | 0 | 1.0 | 0.0 | 409 | HIGH |
| VS_RFI | HJ | LJ | 0 | 0 | 3.0 | 3.0 | 409 | HIGH |
| VS_LIMPERS | BTN | — | 3 | 0 | 1.0 | 1.0 | 347 | HIGH |
| VS_RFI | CO | LJ | 0 | 0 | 2.0 | 2.0 | 314 | HIGH |
| VS_RFI | CO | HJ | 0 | 0 | 2.0 | 2.0 | 278 | HIGH |
| VS_RFI | CO | LJ | 0 | 0 | 3.0 | 3.0 | 263 | HIGH |
| VS_RFI | CO | HJ | 0 | 0 | 3.0 | 3.0 | 232 | MEDIUM |
| VS_RFI | HJ | LJ | 0 | 0 | 3.5 | 3.5 | 209 | MEDIUM |
| VS_RFI | BTN | LJ | 0 | 0 | 2.0 | 2.0 | 204 | MEDIUM |
| VS_RFI | BTN | HJ | 0 | 0 | 2.0 | 2.0 | 196 | MEDIUM |
| VS_RFI | BTN | LJ | 0 | 0 | 3.0 | 3.0 | 195 | MEDIUM |
| VS_RFI_CALLERS | BTN | LJ | 0 | 1 | 2.0 | 2.0 | 182 | MEDIUM |
| VS_RFI_CALLERS | SB | LJ | 0 | 1 | 2.0 | 1.5 | 176 | MEDIUM |
| VS_RFI | BTN | CO | 0 | 0 | 3.0 | 3.0 | 171 | MEDIUM |
| VS_RFI | BTN | CO | 0 | 0 | 2.0 | 2.0 | 161 | MEDIUM |
| VS_RFI_CALLERS | SB | LJ | 0 | 1 | 3.0 | 2.5 | 155 | MEDIUM |
| VS_RFI_CALLERS | BB | LJ | 0 | 1 | 2.0 | 1.0 | 151 | MEDIUM |
| VS_RFI | BTN | HJ | 0 | 0 | 3.0 | 3.0 | 145 | MEDIUM |
| VS_RFI | CO | HJ | 0 | 0 | 3.5 | 3.5 | 144 | MEDIUM |
| VS_RFI | CO | LJ | 0 | 0 | 3.5 | 3.5 | 144 | MEDIUM |
| VS_RFI | HJ | LJ | 0 | 0 | 2.5 | 2.5 | 139 | MEDIUM |
| VS_RFI_CALLERS | BTN | LJ | 0 | 1 | 3.0 | 3.0 | 137 | MEDIUM |
| VS_RFI | SB | CO | 0 | 0 | 3.0 | 2.5 | 135 | MEDIUM |
| VS_RFI_CALLERS | BB | LJ | 0 | 1 | 3.0 | 2.0 | 134 | MEDIUM |
| VS_RFI | SB | HJ | 0 | 0 | 2.0 | 1.5 | 129 | MEDIUM |
| VS_RFI | SB | LJ | 0 | 0 | 3.0 | 2.5 | 129 | MEDIUM |
| VS_RFI | SB | LJ | 0 | 0 | 2.0 | 1.5 | 126 | MEDIUM |
| VS_RFI | SB | BTN | 0 | 0 | 3.0 | 2.5 | 125 | MEDIUM |
| VS_RFI_CALLERS | CO | LJ | 0 | 1 | 2.0 | 2.0 | 121 | MEDIUM |
| VS_ISO | SB | BTN | 1 | 0 | 2.0 | 1.5 | 120 | MEDIUM |
| VS_ISO | SB | BTN | 1 | 0 | 4.5 | 4.0 | 113 | MEDIUM |
| VS_RFI_CALLERS | CO | LJ | 0 | 1 | 3.0 | 3.0 | 113 | MEDIUM |
| VS_RFI_CALLERS | BB | HJ | 0 | 1 | 2.0 | 1.0 | 110 | MEDIUM |

## Backoff contract for #313 / #315

- Exact price support first.
- No silent nearest-price substitution.
- Any dimension-dropping or empirical-bin backoff must be explicit.
- Revealed hand classes are reveal-selected; marginal support remains the coverage reference.

Reproduction:
python3 tools/training/audit_preflop_sizing_support.py --output-json analysis/preflop_sizing_support_train.json --output-md analysis/preflop_sizing_support_train.md --full-json-gz analysis/preflop_sizing_support_train.full.json.gz

Report hash: 5db39f3e461431f2c3cba9417cdf96f5b53437304b166e1886b3f2d9764c7f99

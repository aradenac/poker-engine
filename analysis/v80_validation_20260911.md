# v80 validation — 2026-09-11

## Artifact

Generated locally from the verified v79 artifact.

- v80 size: 418,323 bytes
- v80 SHA-256: `1ca53013da8d2c654ca04f3dbfb4865fb50902bfc87094e8e92f499de2849183`
- patch logic committed as `tools/patch_v79_to_v80.py`

JavaScript syntax check: PASS.

## Change

v80 keeps the learned street×sizing residual coefficients but scales them down in pots below the training-population mean pot for the street:

`effective_coefficient = learned_coefficient * min(1, current_pot / reference_mean_pot)`

Reference mean pots reconstructed from postflop population model v5, weighted by node population decisions:

- Flop: 12.4404 BB
- Turn: 15.7290 BB
- River: 21.6003 BB

The learned coefficient is never amplified above its v79 value.

## Regression hand #262024556922

All demonstrated pathological JAM candidates remain invalid. No JAM is recommended on the hero turn check, river check, or river response decision.

On the 7.5 BB pot, the 125% residual correction is reduced from:

- Turn: +2.078 BB -> about +0.991 BB
- River: +2.810 BB -> about +0.976 BB

This removes the dimensionally extreme case where a river calibration correction exceeded the pot itself.

## Deterministic 5-hand HU benchmark

Same five hands as `calibration_directional_benchmark_20260911.md`, 19 analyzable hero postflop sizing decisions.

v79 fixed-BB calibration changed the raw-EV sizing ranking on about 47% of decisions in the first benchmark; every change was toward a larger sizing.

v80 pot-scaled calibration changes the raw-EV sizing ranking on **5 / 19 = 26.3%** decisions:

| Street | Decisions | v80 ranking changes | toward larger |
|---|---:|---:|---:|
| Flop | 6 | 2 | 2 |
| Turn | 6 | 2 | 2 |
| River | 7 | 1 | 1 |
| Total | 19 | 5 | 5 |

The calibration still intentionally affects rankings; v80 does not force agreement with raw EV. Its purpose is to stop absolute-BB residuals from dominating small pots while preserving the learned correction at normal/large training-scale pots.

## Status

v80 is a candidate baseline, not yet promoted as final. Next validation: larger deterministic sample using one hero postflop decision per hand, comparing raw, v79 fixed-BB, and v80 pot-scaled rankings on identical EV trees.

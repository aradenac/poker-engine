# Sizing calibration audit — 2026-09-11

## Scope

Baseline: generated v79 from authoritative v78 using local patch SHA-256 `fd946a0fb729173c5471d79b8981d222d2e31aed4658e9d6a3af1fcfbb5a321c`.

Generated v79 SHA-256: `01805f9f300e82c53ba8765ab6c6069b0ba73ad9e8f723f469aaa29b8d6c8c28` (417,779 bytes).

Regression hand: PokerStars Zoom `#262024556922`, hero `RoiDePiqueNique [Ts Kh]`, board `4d 8h Ah / Ks / Ad`.

## v79 regression result

The pathological JAM recommendations are gone. Hero recommendations on the same hand are now:

- Flop check decision: ordinary sizing/check region, no JAM.
- Turn check decision: `125% pot` is selected after calibration.
- River check decision: `125% pot` is selected after calibration.
- River facing bet: `CALL` is selected; hypothetical JAM raise is invalidated.

## Calibration distortion observed

The current policy calibration adds fixed BB offsets by street × sizing. On this hand the pot before the hero turn and river decisions is only 7.5 BB.

Turn candidate EVs:

| sizing | raw EV BB | calibration BB | final EV BB |
|---|---:|---:|---:|
| 50% | 5.404 | +0.503 | 5.907 |
| 66% | 5.279 | +1.049 | 6.329 |
| 75% | **5.502** | +1.236 | 6.738 |
| 100% | 5.226 | +1.652 | 6.878 |
| 125% | 5.126 | **+2.078** | **7.204** |

Raw model best is 75% pot. Calibration flips the recommendation to 125% pot even though its raw EV is 0.376 BB lower.

River candidate EVs:

| sizing | raw EV BB | calibration BB | final EV BB |
|---|---:|---:|---:|
| 50% | 6.279 | +1.018 | 7.297 |
| 66% | 6.283 | +1.698 | 7.981 |
| 75% | **6.397** | +1.932 | 8.329 |
| 100% | 6.369 | +2.440 | 8.809 |
| 125% | 6.295 | **+2.810** | **9.105** |

Again raw model best is 75% pot and fixed-BB calibration flips the recommendation to 125% pot.

## Training-population pot scale

Weighted mean `pot_before_bb` reconstructed from postflop model v5 node coverage:

- flop: 12.44 BB
- turn: 15.73 BB
- river: 21.60 BB

The audited 7.5 BB turn/river pot is therefore much smaller than the mean context on which an absolute-BB residual correction is expected to be representative. A +2.81 BB river correction equals 37.5% of this pot.

## Conclusion

v79 fixes the demonstrated extreme-JAM pathology, but the next structural issue is confirmed: fixed absolute-BB street × sizing residuals can dominate the raw EV ordering in small pots and systematically push recommendations toward larger sizings.

Do not replace this with an arbitrary sizing penalty. Next step: benchmark raw-vs-calibrated ranking changes across a deterministic sample, then change calibration units/scaling only if the systematic effect is confirmed.

# Calibration directional benchmark — 2026-09-11

## Goal

Measure whether v79 street×sizing residual calibration changes the raw-EV sizing ranking in a systematic direction.

Dataset source: authoritative `NLHE 100-200` corpus. Sample selection is deterministic and restricted to heads-up-at-flop hands with hero `RoiDePiqueNique`, no preflop all-in, and at least one postflop hero decision.

Sample hand IDs:

- 261994647157
- 261780428543
- 261948045186
- 261963507505
- 261946793969

Models: preflop population v5 + postflop population v5. Application: generated v79 SHA-256 `01805f9f300e82c53ba8765ab6c6069b0ba73ad9e8f723f469aaa29b8d6c8c28`.

## Result

19 hero postflop sizing decisions were analyzable.

- Raw-EV best sizing changed after calibration: **9 / 19 = 47.4%**.
- Change toward a larger sizing: **9 / 19 = 47.4%**.
- Change toward a smaller sizing: **0 / 19 = 0%**.

By street:

| Street | decisions | ranking changed | changed to larger |
|---|---:|---:|---:|
| Flop | 6 | 4 (66.7%) | 4 |
| Turn | 6 | 2 (33.3%) | 2 |
| River | 7 | 3 (42.9%) | 3 |

## Representative flips

- Hand 261994647157, flop 4.5 BB pot: raw best `33% pot` (2.232 BB) -> calibrated best `75% pot`; the 75% coefficient alone adds +0.716 BB.
- Hand 261994647157, turn 4.5 BB pot: raw best `50% pot` (2.954 BB) -> calibrated best `125% pot`; 125% receives +2.078 BB.
- Hand 261948045186, river 7.5 BB pot: raw best `25% pot` (5.355 BB) -> calibrated best `125% pot`; 125% receives +2.810 BB despite raw EV 4.795 BB.
- Hand 261946793969, flop 2.5 BB pot: raw best `25% pot` -> calibrated best `125% pot`; +1.125 BB calibration is 45% of the entire pot.
- Hand 261946793969, river 2.5 BB pot: raw best `100% pot` -> calibrated best `125% pot`; +2.810 BB calibration exceeds the pot itself.

## Interpretation

This benchmark does not prove that raw EV is ground truth. It does prove that the current calibration is strongly directional and can dominate the underlying EV model in small pots because its units are fixed BB rather than pot-relative.

The postflop v5 population model gives weighted mean `pot_before_bb` values of approximately 12.44 BB flop, 15.73 BB turn and 21.60 BB river. The next experiment should therefore compare the current fixed-BB correction with a conservative pot-normalized form derived from these training-population scales, using identical raw EV trees.

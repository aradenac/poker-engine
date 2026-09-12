# Hero trainer ranges

`custom_ranges_v1.json` is the normalized Hero preflop range used by the interactive 6-max trainer.

Source export:
- folder: `Custom`
- export type: `range-folder`
- exported at: `2026-09-06T07:11:06.613Z`
- source SHA-256: `1248258112562757e49df545e97f9e54b2dde163fdc755adf0029e89e580e8cb`

Normalization contract for the current heads-up SRP trainer:
- `PFA`: `Openings`, using the sum of non-FOLD action frequencies for each hand, capped at 100%; custom `Multiway` entries are therefore retained as part of the supplied opening range.
- `CALLER`: `VS Opening`, using `Call` frequency only. `3-bet` and `4-bet/shove` entries are excluded because they do not produce a single-raised-pot caller spot.
- A missing role/position is unsupported and must be resampled, never synthesized. The supplied export contains no BB range, so the trainer does not invent Hero BB caller hands.
- During dealing, exact two-card combos are enumerated and each combo receives its hand-class frequency. This preserves the natural 6/4/12 combo multiplicity of pair/suited/offsuit classes.

Opponent ranges and actions remain supplied independently by promoted Model B v2. This asset affects only which Hero hole cards are dealt for a given trainer role and position.

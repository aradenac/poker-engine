# v80 recommended-action style benchmark — 48 deterministic HU decisions

## Scope

48 deterministic hands from the authoritative NLHE 100-200 corpus, restricted to heads-up-at-flop hands without a preflop all-in. One deterministic hero postflop decision is evaluated per hand with v80. This benchmark measures recommendation style; it does not force the analyzer to mimic population action frequencies.

## Recommended actions

| Action | Count | Share |
|---|---:|---:|
| BET | 26 | 54.17% |
| CALL | 6 | 12.50% |
| JAM | 5 | **10.42%** |
| CHECK | 4 | 8.33% |
| FOLD | 4 | 8.33% |
| RAISE | 3 | 6.25% |

Observed actions in the same sampled decisions were CHECK 43.75%, BET 29.17%, CALL 16.67%, FOLD 8.33%, RAISE 2.08%, JAM 0%.

By street, recommended JAM frequency was:

- Flop: 1 / 27 = 3.70%
- Turn: 2 / 12 = 16.67%
- River: 2 / 9 = 22.22%

Small per-street denominators mean these percentages should not be interpreted as stable population estimates. Aggregate JAM frequency is nevertheless high enough to justify a targeted audit.

## Five recommended JAMs

| Hand | Street | Nominal size / pot | Response observations | Confidence |
|---|---|---:|---:|---|
| 261484368288 | River | 11.62x | 52 | medium |
| 261674652229 | Turn | 6.82x | 42 | low |
| 261946931854 | Turn | 7.35x | 42 | low |
| 262004504156 | Flop | 12.12x | 40 | low |
| 261982346969 | River | 8.96x | 76 | medium |

All five jams occur with made hands rather than random air: QJ top pair river, JJ set turn, 99 overpair turn, Q9 top pair flop, and AT two pair river. This argues against a generic JAM penalty.

## Structural bug discovered during the audit

When hero's nominal JAM exceeds the opponent's remaining stack, `postflopRaiseTreeSnapshot()` uses the full nominal JAM in the responder's `pot_before_bb` denominator even though unmatched excess is returned. This understates the responder's effective call price and also conditions the calling-range composition on the wrong price.

Examples:

- Hand 261484368288: model used facing price 0.447 for a 169.945 BB effective call into a 30.14 BB pot; correct effective price is about 0.849. Correcting the denominator reduces JAM final EV from roughly 92 BB to roughly 50 BB.
- Hand 261982346969: model used facing price 0.216; correct effective price is about 0.683. With the corrected price, JAM falls below the 125% sizing in final EV.

This is a model-input bug and should be fixed before adding any stylistic JAM constraint.

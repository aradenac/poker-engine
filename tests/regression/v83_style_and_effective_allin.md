# v83 style and effective-all-in regression

## Purpose

v83 fixes a sizing semantics problem: when Hero covers the opponent, a full Hero-stack JAM is strategically identical to betting only the amount that can actually be called. The engine now creates an `all-in effectif` candidate capped at the opponent's effective stack instead of advertising an irrelevant nominal Hero-stack shove.

## Deterministic 48-decision benchmark

Same HU postflop sample as v80-v82.

Recommended classes in v83:

- BET: 23 / 48 = 47.9%
- CALL: 7 / 48 = 14.6%
- EFFECTIVE_ALLIN: 7 / 48 = 14.6%
- RAISE: 3 / 48 = 6.2%
- CHECK: 4 / 48 = 8.3%
- FOLD: 3 / 48 = 6.2%
- true Hero JAM: 1 / 48 = 2.1%

The true Hero-JAM rate is now in the same order of magnitude as the observed population JAM rate (~1.3% flop, ~1.4% turn, ~2.5% river). `all-in effectif` is kept distinct because Hero is not shoving their own stack; the sizing is only the amount needed to put the shorter opponent all-in.

Examples converted from misleading nominal JAMs:

- hand `261484368288`, river: nominal Hero stack 350.24 BB; effective all-in 169.945 BB (5.64x pot)
- hand `261946412521`, turn: nominal 619.155 BB; effective all-in 49.25 BB (4.69x pot)
- hand `261946931854`, turn: nominal 51.45 BB; effective all-in 36.86 BB (5.27x pot)
- hand `261982346969`, river: nominal 224.075 BB; effective all-in 53.76 BB (2.15x pot)

## Historical pathological hand regression

Hand `#262024556922` on v83:

- flop check: best `25% pot`, within noise vs check
- turn check: best `125% pot`
- river check: best `100% pot`
- river fold facing bet: best `CALL`

No absurd JAM recommendation reappears.

## Current assessment

v83 is a substantially better behavioral baseline than v78-v82:

1. artificial JAM calibration bonuses remain removed;
2. sparse/unsupported extreme response nodes are guarded;
3. residual sizing calibration is pot-scaled;
4. unmatched shove amounts no longer distort responder price calculations;
5. recommendations distinguish true Hero JAM from effective opponent all-in sizing.

Next work: audit the seven `all-in effectif` recommendations for hand strength, EV gap, and support quality, then simplify the user-facing recommendation line to action + exact effective sizing + final EV.

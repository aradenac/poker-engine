# v80 deterministic 20-hand benchmark — 2026-09-11

## Scope

Twenty deterministic heads-up-at-flop hands from the authoritative NLHE 100-200 corpus. One deterministic hero postflop decision is evaluated per hand so raw, v79 fixed-BB calibration and v80 pot-scaled calibration can be compared on identical EV trees.

Sample hand IDs:
`261793297713, 261991685017, 261975894677, 261674752502, 261970166551, 261781115512, 261531347707, 261945953551, 261673796307, 261777995747, 261784209232, 261673381607, 261461061156, 261456190558, 261945958051, 261673882828, 261946916910, 261780474972, 261782081105, 261791191986`.

Application: v80 SHA-256 `1ca53013da8d2c654ca04f3dbfb4865fb50902bfc87094e8e92f499de2849183`.

## Results

All 20 hands completed successfully.

| scheme | decisions | ranking changed vs raw | toward larger | toward smaller | best JAM |
|---|---:|---:|---:|---:|---:|
| v79 fixed-BB | 20 | 6 (30.0%) | 6 | 0 | 2 |
| v80 pot-scaled | 20 | 6 (30.0%) | 6 | 0 | 2 |

The equality of the aggregate counts is expected because many sampled pots are already near or above the training reference pot; v80 deliberately leaves those coefficients unchanged. It materially changes the small-pot cases. Example: in a 2.5 BB flop pot, raw best was 25%, v79 fixed calibration selected 125%, while v80 selects 50%.

## Remaining JAM recommendations

The two v80 best-JAM decisions are also the best actions in raw tree EV, so they are not created by residual calibration.

- Hand `261970166551`, flop, hero `KK` on `J-5-2`: jam is about 17.1x pot; exact response node has 37 population observations, low confidence, call price remains inside local P90 support, estimated all-fold probability about 73.7%.
- Hand `261945953551`, turn, hero `K9s` after flopping top pair plus spade draw: jam is about 6.68x displayed pot; opponent is shorter, so effective hero cost is capped at about 70.1 BB rather than the nominal 123.1 BB. Exact response node has 42 observations, low confidence, call price is well inside local P90 support, estimated all-fold probability about 51.1%.

These are very large bets, but they do not reproduce the previously demonstrated sparse-node/JAM-bonus pathology. They should not be suppressed with an arbitrary global penalty without a global recommendation-frequency benchmark.

## Next gate

Measure v80 recommended action frequencies on a larger deterministic sample and compare JAM frequency by street with the empirical population baseline. Population frequency is a sanity reference, not an optimization target.

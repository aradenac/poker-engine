# v81 effective-pot audit

Baseline: v80 pot-scaled calibration.

## Bug fixed

When a nominal shove exceeded the responder's effective stack, the response model used the nominal shove when computing the pot seen by the responder. The unmatched portion is returned in real poker and must not affect the responder's price-to-pot ratio.

v81 uses `effectiveActorCostBB` when constructing the responder decision context and keeps nominal/effective aggression diagnostics separately.

## 48-decision deterministic style sample

Same 48 HU postflop decisions as the v80 benchmark.

- v80 JAM recommendations: 5 / 48 = 10.4%
- v81 JAM recommendations: 4 / 48 = 8.3%
- Removed JAM: hand `261982346969`, river. v80 JAM final EV ~34.5 BB; v81 selects `125% pot` (~20.5 BB in the deterministic style benchmark).

Remaining v81 JAMs:

| Hand | Street | Nominal size / pot | Response observations | Confidence | Facing price | Local P90 |
|---|---|---:|---:|---|---:|---:|
| 261484368288 | River | 11.62x | 52 | medium | 0.849 | 0.925 |
| 261674652229 | Turn | 6.82x | 42 | low | 0.872 | 0.828 |
| 261946931854 | Turn | 7.35x | 42 | low | 0.840 | 0.828 |
| 262004504156 | Flop | 12.12x | 40 | low | 0.924 | 0.954 |

The two turn JAMs are outside the local P90 response-price support while using a low-confidence node. The river and flop JAMs remain inside local support.

## Empirical context

The raw TRAIN histories show high folds at high call-price ratios, so a general JAM penalty is not justified. Representative observed fold rates:

- flop price 0.8-0.9: ~71.5%; 0.9-1.01: ~78.1%
- turn price 0.8-0.9: ~72.7%; 0.9-1.01: ~80.6%

Therefore the next guard should target **low-confidence extrapolation beyond local support**, not JAMs as a class.

## Next change

v82 should:

1. preserve effective `aggressorSizePot` in the worker result instead of recomputing it from nominal `costBB`;
2. reject hypothetical extreme aggression on `low` or `very_low` response nodes when `facingPricePot > local P90`;
3. rerun the same 48-decision benchmark and the pathological-hand regression suite.

# Empirical TRAIN fold rates by facing price

Direct audit of the raw NLHE 100-200 hand histories, restricted to TRAIN by the model's published SHA-256 hand-ID split and excluding hero decisions. `facing_price = amount_to_call / pot_before_response`.

This independently checks the continuous response model's key assumption that players fold more often as the call price rises.

## SRP fold rates

| Facing price | Flop | Turn | River |
|---|---:|---:|---:|
| 0.40–0.50 | 56.6% (n=1478) | 51.1% (n=728) | 61.1% (n=638) |
| 0.50–0.60 | 57.1% (n=343) | 47.8% (n=178) | 69.7% (n=201) |
| 0.60–0.70 | 55.2% (n=143) | 49.1% (n=53) | 72.8% (n=81) |
| 0.70–0.80 | 63.6% (n=121) | 50.0% (n=72) | 76.7% (n=43) |
| 0.80–0.90 | 71.5% (n=151) | 58.3% (n=36) | 78.4% (n=51) |
| 0.90–1.00 | 75.8% (n=99) | 66.7% (n=18) | 78.6% (n=28) |

Across all pot types, the same directional relationship is even clearer: at facing prices 0.9–1.0, folds are about 78.1% flop, 80.6% turn and 91.0% river.

## Interpretation

The corpus does support strong over-folding under very high call pressure. Therefore a best-response engine can legitimately recommend more extreme aggression than the population itself uses. The large-JAM problem should not be addressed by forcing recommended JAM frequency toward observed JAM frequency.

However, the tails are sparse—especially turn SRP—and the response price must be computed correctly. The audit of v80 found that unmatched all-in excess was incorrectly included in the pot denominator for a shorter responder. That bug must be fixed first because it changes both marginal fold probability and which combos are selected to call.

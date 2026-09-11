# Postflop population action baseline — model v5

Source: `postflop_population_model_v5`, summing `population_observed.actions[].count` over all model nodes.

This is a descriptive sanity baseline for the observed NLHE 100-200 population. It is **not** a target distribution for the analyzer's recommended best-response policy.

| Street | Decisions | CHECK | BET | FOLD | CALL | RAISE | JAM |
|---|---:|---:|---:|---:|---:|---:|---:|
| Flop | 58,799 | 49.620% | 14.366% | 16.601% | 16.669% | 1.468% | **1.277%** |
| Turn | 41,763 | 47.286% | 17.860% | 13.364% | 18.447% | 1.664% | **1.379%** |
| River | 31,206 | 43.754% | 19.333% | 19.794% | 12.212% | 2.378% | **2.528%** |

The key use for the current engine audit is JAM frequency. A best-response policy can rationally jam more often than the population itself, but a recommendation rate an order of magnitude above these baselines would require strong supporting evidence and should trigger investigation of EV-tree extrapolation, response-node confidence and sizing support.

# #419 — TRAIN-only hierarchical fit candidate

Fitted the frozen T2 hierarchical exact-context model on certified TRAIN only (19016 hands parsed, 101848 non-Hero preflop decision rows). In-scope observations: 192 real TRAIN rows (106 distinct `hierarchical_exact_key`, 126 distinct hands) covering the required #388 tree keyspace.

Candidate `model-a-preflop-sizing-hierarchical-train-fit-419-v1` instantiates the contract id `model-a-preflop-sizing-hierarchical-candidate-v1` (distinct from #352 `model-a-preflop-sizing-aware-candidate-v2` and from #388, which created no candidate). Canonical payload SHA256 `637302885b8119e6b0246d827462c36eb707c6e234d0b652483c956f03360999`; artifact byte SHA256 `c78ae3c434d5f41e50567a131bdfb2b89982243379818709abeb0e5ec2385534`.

Hyper-parameters and priors are the spec's, never re-selected: `kappa0=16.0`, Dirichlet `alpha=0.5` per legal marginal action, thresholds 20 observations / 20 distinct hands, raise sizing exact-support-only with no nearest price. The estimator is closed-form (seed 419, zero stochastic draws).

Resolution over the 38 required nodes: 0 estimated, 38 fail closed (31 x NO_ADMISSIBLE_POOLING_LEVEL, 7 x RAISE_SIZING_UNRESOLVED_NO_NEAREST_PRICE); the tree stays open where TRAIN support is insufficient — the frozen thresholds are not lowered.

7 nodes stay explicitly unresolved because RAISE sizing is a #388 structural frontier (exact-support-only, no representative price); the non-authoritative evidence-only diagnostic in the report shows which nodes hierarchical pooling would resolve if that frontier were ignored.

No VALIDATION or TEST decision was parsed or evaluated (`split_consumed=TRAIN`, `validation_consumed=false`, `test_consumed=false`). No pseudo-observation or hidden-hand imputation was used. `training/registry.json` and the active `training/models/preflop_population_model_v5.json` pointer are unchanged before/after (`active_pointer_mutated=false`). This artifact admits nothing.

Reproduce: `python3 tools/training/fit_model_a_preflop_sizing_hierarchical.py`; verify: `python3 tools/training/fit_model_a_preflop_sizing_hierarchical.py --check`.

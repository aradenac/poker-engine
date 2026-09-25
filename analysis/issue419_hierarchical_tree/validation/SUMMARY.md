# #419 — frozen VALIDATION evaluation (hierarchical candidate)

Executed the T6 frozen VALIDATION protocol (`analysis/issue419_hierarchical_tree/FROZEN_VALIDATION_PROTOCOL.json`, byte SHA256 `69c99a8b37589f1687b7e980344c9a79d69bbcd45be0a53ffd59bfea0ab583b3`) against the frozen TRAIN-fit hierarchical candidate `model-a-preflop-sizing-hierarchical-candidate-v1` (`637302885b8119e6b0246d827462c36eb707c6e234d0b652483c956f03360999`). The protocol bytes were re-verified before a single VALIDATION hand was parsed, and TEST stays unconsumed.

Required-tree nodes: 38 of 38 fail closed; 0 are `EXACT_HIERARCHICAL_ESTIMATE` (share `0.0`).

VALIDATION coverage: 9 identifiable decisions / 9 distinct hands, i.e. `0.000783289817232376` of the 11490 in-scope focus-family decisions; 2 of the 9854 exact-price comparable decisions are both answered by the candidate and pairable with both comparators.

Paired multiclass log-loss on the decisions all three models answer: candidate_hierarchical=0.31968449353667705, active_model_a_v5=0.5856142236934883, model_a_preflop_sizing_aware_candidate_v2=0.3196844935372386.

candidate-minus-active delta log-loss `-0.2659297301568112` (95% CI `[-0.33476257271429477, -0.19709688759932775]`); candidate-minus-#352-v2 delta log-loss `-5.615508058554042e-13` (95% CI `[-5.866696017875483e-13, -5.365152766501069e-13]`).

Verdict: `RETAIN_ACTIVE_REFERENCE` — failing gates: coverage_floor, calibration_absolute; claims below the frozen identifiable-support floor: candidate_not_inferior_to_active, candidate_not_inferior_to_v2, calibration_absolute, calibration_delta_vs_active. No threshold, pooling limit, prior or comparator was changed after the read.

Reproduce: `python3 tools/training/validate_hierarchical_validation.py --run`; verify: `python3 tools/training/validate_hierarchical_validation.py --check`.

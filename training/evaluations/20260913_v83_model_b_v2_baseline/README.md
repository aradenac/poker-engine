# v83 / Model B v2 frozen strategic baseline

This directory freezes the reference required by issue #10.

The reference was produced by GitHub Actions run `34747037677` from commit `c3b9cd58954bbcca3e11fc3a47fdac0c1c335048`, with master seed `20260912`, 32 historical base hands per split, 2 deterministic repetitions per base hand and 1200 analyser trials per decision.

`baseline_reference.json` contains the reproducible aggregate baseline, provenance hashes, scenario fingerprints, confidence intervals and context breakdowns. `suspicious_states.json` contains exact scenario IDs for oversized effective-all-in and true-JAM observations so future engine changes can turn selected cases into permanent regressions.

The complete raw scenario manifests, arena rows and full reports are immutable artifacts of Actions run `34747037677`:

- VALIDATION artifact `10314890603`, ZIP SHA-256 `a7c520d6f439f8fdd6f6cfb46e52b29ebb8bcbeccff056800b5a252697e52e91`.
- TEST artifact `10313714975`, ZIP SHA-256 `ab2f95f7c6222c62a5c95509b856e811d9c38df7d20e82c5678dd3a3d10e4d09`.

Reproduction uses `tools.simulation.baseline_runner` with `--seed 20260912 --trials 1200 --n 32 --reps 2`. VALIDATION evaluates `current,no_jam,cap_2,cap_3,cap_4`; TEST evaluates `current` only.

The benchmark is heads-up postflop only. Utility is future payoff from the generated flop state, with preflop investment treated as sunk; it is not an overall cash-game win rate. Model B v2 does not condition action probabilities on hidden hand strength, board texture, facing price or SPR. Those realism limits remain tracked by #46.

Do not tune against TEST. The three true JAM observations found in TEST are frozen evidence, not candidate-selection targets.

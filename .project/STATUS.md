# Project Status

Last update: 2026-09-12

## Persistence and deployment

- GitHub repository `aradenac/poker-engine` is the durable source of truth.
- User-facing releases live under `user/releases/`; the runnable site is mirrored at `site/index.html`.
- The user configured automatic Cloudflare static deployment from GitHub; a GitHub commit may trigger deployment, but `site/index.html` changes only on explicit application promotion.
- Production population models live under `training/models/`.
- Raw hand-history datasets live under `training/datasets/`; versioned training/calibration work lives under `training/runs/`; current lineage state lives under `training/state/`.
- Tooling lives under `tools/`; permanent validation under `tests/`; assistant/project continuity under `.project/`.

## Promoted application baseline

- Promoted application: `v83`.
- Canonical release: `user/releases/poker_range_equity_offline_multiway_v83.html`.
- Testable/deployed site source: `site/index.html`.
- SHA-256: `2690a82ffe363017b495a1aef60657b12db1b52eb402c36a1ff87f723c5d1bd4`.

## Production opponent model A — integrated analyzer population model

- Preflop production model: `training/models/preflop_population_model_v5.json`.
  - Version: `preflop_v5_incremental_exact_marginals`.
  - SHA-256: `ff952055ca4ee051a3ac9607d513fdecac0a320a31f658ecfd8a11d8448975ca`.
- Postflop production model: `training/models/postflop_population_model_v5.json`.
  - Version: `postflop_v5_clean_continuous`.
  - SHA-256: `6d948f30f6c276ce41e70e83ac35275e30e7841e93e5b1da11782648c6b4d8ae`.
- These models are the opponent models allowed to drive analyzer EV calculations.

## Opponent model B — independent profile model / strategy arena

The independent-validation track exists but is not yet fully reproducible from GitHub.

Persisted component:

- `tools/sequential_postflop_population_sim_v4.py` — sequential simulator that uses independently learned opponent profiles/actions while querying the analyzer only for Hero decisions.

Known historical independent-model components referenced by the simulator/arena:

- per-player profile assignment / profile prevalence;
- profile-conditioned preflop ranges;
- marginal action models;
- continuing-range / action-composition models;
- empirical sizing distributions;
- parsed hand and decision tables.

Current reproducibility gap:

- the simulator still imports `independent_decision_arena_seq_v2` from `/mnt/data`;
- it expects unversioned `/mnt/data/independent_population_v1` and `/mnt/data/sequential_population_inputs_v2` artifacts;
- these dependencies and their training pipeline are not currently persisted in GitHub.

An earlier `independent_decision_arena_v1.py` exists in the ChatGPT file history and demonstrates the intended independent architecture, but the current sequential v2 arena must be rebuilt/persisted from authoritative datasets rather than treated as an untracked runtime dependency.

This is the highest-priority technical debt before resuming large strategy simulations.

## Persisted NLHE 100-200 datasets

Historical baseline:

- Archive: `training/datasets/NLHE_100-200/source/NLHE 100-200.zip`.
- SHA-256: `6effd27d6e9f8257f3e87c68f0218b8edc72a2b487cb57da2c37ff85bc8ce4c6`.
- 176 hand-history files, 27,164 unique hands, no duplicate hand IDs.
- Language split: 26,170 EN / 994 FR.
- Coverage: 2026-07-12 10:31:29 through 2026-09-07 22:32:44.
- Audit: `training/datasets/NLHE_100-200/source/manifest.json`.

2026-09-09 snapshot:

- Archive: `training/datasets/NLHE_100-200/snapshots/20260909/source/RoiDePiqueNique_training2.zip`.
- SHA-256: `7768cd3ddca1f7d48601ea5a7c378e6bf1211d92aadb7cab9b3689f3b9dc561c`.
- 259 hand-history files, 27,677 unique hands, no duplicate hand IDs.
- Coverage: 2026-07-17 22:40:22 through 2026-09-09 17:48:16.
- Audit: `training/datasets/NLHE_100-200/snapshots/20260909/manifest.json`.

Raw archives remain compressed in Git. Audit/training tools read or extract them at runtime.

## Latest persisted continuous-training run

Run: `training/runs/20260909_population_increment_v2/`.

- 1,000 certain new hands selected after the previous baseline cutoff.
- Split: 790 TRAIN / 100 VALIDATION / 110 TEST using the deterministic hand-ID split contract.
- Preflop v5 candidate: accepted.
- Postflop v6 candidate: rejected because it degraded the recent VALIDATION and TEST sets; production remains postflop v5.
- The rejected candidate and additive overlay are preserved for future evidence accumulation.
- This run proves the model-level promotion loop already works: new evidence -> candidate -> recent + historical non-regression -> explicit accept/reject.

## v83 validated behavior

- Artificial JAM calibration bonuses remain disabled.
- Fixed additive BB calibration is scaled down in small pots.
- Unmatched shove amounts no longer distort responder price-to-pot calculations.
- Low-confidence extreme aggression beyond local P90 support is rejected.
- When Hero covers a shorter opponent, the engine recommends the exact effective all-in amount instead of a misleading full Hero-stack JAM.
- Deterministic 96-decision benchmark: 2 true Hero JAMs = 2.08%, consistent with the observed population order of magnitude.
- Historical pathological hand `#262024556922` no longer produces absurd JAM recommendations; river facing bet recommends CALL.

## Experimental engine work

- `tools/patch_v83_to_v84.py` and `tests/regression/v84_overbet_grid_audit.md` exist.
- v84 is not promoted.
- Further engine tuning should now be evaluated through the independent arena as well as the permanent direct regression suite before promotion.

## Continuous-training target architecture

For every new hand-history push:

1. Persist/audit the new snapshot and determine the hand-ID delta against known evidence.
2. Keep deterministic TRAIN / VALIDATION / TEST assignment.
3. Train/update candidate integrated model A.
4. Train/update candidate independent profile model B.
5. Evaluate/promote or reject each opponent model independently.
6. Evaluate candidate engine strategy against independent model B using deterministic sequential simulations.
7. Run permanent recommendation non-regression and style/behavior benchmarks.
8. Promote a new application only if strategy and regression gates pass.
9. Persist every input, model, metric, seed contract, report and promotion/rejection decision.

## Immediate next actions

1. Reconstruct and persist the independent profile-model training pipeline from the authoritative NLHE 100-200 datasets.
2. Remove `/mnt/data` and untracked-pickle dependencies from `tools/sequential_postflop_population_sim_v4.py`.
3. Create a versioned independent model-B package and baseline its predictive metrics/profile distributions.
4. Re-run the sequential strategy arena with v83 as the reference engine and persist a deterministic baseline report.
5. Compare experimental v84 against exactly the same scenario seeds/profile mix; promote only if it improves or is non-inferior without new pathological behavior.
6. Automate steps 1-5 into the continuous-training workflow for future hand-history snapshots.

## Remaining bootstrap gap

- `user/releases/poker_range_equity_offline_multiway_v78.html` is not yet committed at its canonical historical path. This does not block current v83 training/validation work.

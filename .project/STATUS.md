# Project Status

Last update: 2026-09-12

## Persistence

- GitHub repository `aradenac/poker-engine` is the durable source of truth.
- User-facing releases live under `user/releases/`; the runnable site is mirrored at `site/index.html`.
- Production population models live under `training/models/`.
- Versioned training/calibration work lives under `training/runs/`; current lineage state lives under `training/state/`.
- Tooling lives under `tools/`; permanent validation under `tests/`; assistant/project continuity under `.project/`.

## Promoted application baseline

- Promoted application: `v83`.
- Canonical release: `user/releases/poker_range_equity_offline_multiway_v83.html`.
- Testable site: `site/index.html`.
- SHA-256: `2690a82ffe363017b495a1aef60657b12db1b52eb402c36a1ff87f723c5d1bd4`.

## Production models

- Preflop production model: `training/models/preflop_population_model_v5.json`.
  - Version: `preflop_v5_incremental_exact_marginals`.
  - SHA-256: `ff952055ca4ee051a3ac9607d513fdecac0a320a31f658ecfd8a11d8448975ca`.
- Postflop production model: `training/models/postflop_population_model_v5.json`.
  - Version: `postflop_v5_clean_continuous`.
  - SHA-256: `6d948f30f6c276ce41e70e83ac35275e30e7841e93e5b1da11782648c6b4d8ae`.

## Latest persisted training run

Run: `training/runs/20260909_population_increment_v2/`.

- New hands: 1000 from 2026-09-07 through 2026-09-09.
- Split: 790 TRAIN / 100 VALIDATION / 110 TEST.
- Preflop v5: accepted.
- Postflop v6 candidate: rejected; production stays on postflop v5.
- Evaluation and non-regression outputs are preserved under the run's `evaluation/` directory.
- Rejected postflop candidate is preserved under the run's `models/` directory.

## v83 validated behavior

- Artificial JAM calibration bonuses remain disabled.
- Fixed additive BB calibration is scaled down in small pots.
- Unmatched shove amounts no longer distort responder price-to-pot calculations.
- Low-confidence extreme aggression beyond local P90 support is rejected.
- When Hero covers a shorter opponent, the engine recommends the exact effective all-in amount instead of a misleading full Hero-stack JAM.
- Deterministic 96-decision benchmark: 2 true Hero JAMs = 2.08%, consistent with the observed population order of magnitude.
- Historical pathological hand `#262024556922` no longer produces absurd JAM recommendations; river facing bet recommends CALL.

## Experimental work

- `tools/patch_v83_to_v84.py` and `tests/regression/v84_overbet_grid_audit.md` exist.
- v84 is not promoted; broader regression is still required before replacing v83.

## Remaining bootstrap gaps

- `user/releases/poker_range_equity_offline_multiway_v78.html` is not yet committed at its canonical path.
- The raw historical baseline archive `training/datasets/NLHE_100-200/source/NLHE 100-200.zip` is still pending exact import.
- The original historical corpus fingerprint remains `91a1b1c285add6ace2aedafa568bfc039c644b94216b9d2fdcd28cea59b73d4b`.

## Immediate next milestone

1. Let the user test v83 from `site/index.html` / `user/releases/` and collect concrete recommendation failures.
2. Complete the broader v84 regression before any promotion.
3. Expand the permanent pathological-hand regression suite.
4. Import the remaining historical v78 and raw baseline corpus when available.
5. Continue training only through immutable versioned runs with explicit promotion/rejection decisions.

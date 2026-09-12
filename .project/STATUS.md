# Project Status

Last update: 2026-09-12

## Persistence and deployment

- GitHub repository `aradenac/poker-engine` is the durable source of truth.
- User-facing releases live under `user/releases/`; the runnable site is mirrored at `site/index.html`.
- The user configured automatic Cloudflare static deployment from GitHub; a GitHub commit may trigger deployment, but `site/index.html` changes only on explicit application/feature promotion.
- Production population models live under `training/models/`; immutable training/evaluation artifacts live under `training/runs/`.
- Raw hand-history datasets live under `training/datasets/`; current model pointers live in `training/registry.json`.
- Tooling lives under `tools/`; permanent validation under `tests/`; assistant/project continuity under `.project/`.

## Promoted engine baseline

- Promoted recommendation engine: `v83`.
- Canonical release: `user/releases/poker_range_equity_offline_multiway_v83.html`.
- Canonical v83 release SHA-256: `2690a82ffe363017b495a1aef60657b12db1b52eb402c36a1ff87f723c5d1bd4`.
- Deployed static application source: `site/index.html` plus static assets under `site/`.
- Adding site-level features such as the player trainer does not by itself promote the recommendation engine to a new version; v84 remains experimental.

## Player training view

Issue #19 implements the first interactive player-training MVP on top of the existing analyser rather than creating a second poker engine.

Architecture:

- dedicated `Training 6-max` view inside the existing static application;
- existing analyser/replayer card, table, parsing and review machinery is reused;
- Model A v5 remains the single source of Hero recommendation, sizing and EV through `buildReviewBatchPlan()` / `runReviewBatchPlan()`;
- promoted Model B v2 supplies opponent profile prevalence, preflop ranges, postflop action frequencies and sizing samples;
- exact promoted A/B artefacts are exposed as static browser assets under `site/assets/trainer/`; no model is retrained or semantically forked for the UI;
- all seats start at 100 BB and Hero position/button/profile mix/cards are randomized per hand.

MVP behavior:

- six-seat table with Hero + five visible opponent profiles;
- a heads-up single-raised-pot preflop situation is materialized automatically, then interactive training starts on the flop;
- opponent postflop actions and sizings are sampled from promoted Model B v2;
- Hero can FOLD/CHECK/CALL/BET/RAISE using BB sizing or convenient pot-fraction presets;
- three modes: Guided (recommendation visible before acting), Training (feedback after acting), Test (feedback deferred to hand end);
- coaching feedback exposes recommended ACTION / exact SIZING / final EV, Hero chosen EV, retained EV loss and Monte-Carlo noise tolerance;
- session counters and EV-loss breakdown by position/street are accumulated.

Current deliberate boundaries:

- full interactive preflop training is not yet enabled because v83 does not expose the same complete comparable action+sizing EV surface preflop as it does postflop;
- Model B v2 postflop policy is conditioned on profile/context but not yet on the exact hidden combo, so the trainer documents this limitation rather than pretending combo-conditioned opponent behavior;
- retry/spaced-repetition drills are a natural follow-up, but the MVP already records enough per-decision context and EV loss to support them.

Validation:

- `tests/trainer/test_trainer_static.py` locks architecture reuse, static assets and stack/blind accounting;
- `.github/workflows/trainer-smoke.yml` checks JavaScript syntax and patch idempotence, serves the same static HTTP shape used by Cloudflare Pages, then drives the real UI with Playwright;
- latest browser smoke passed with six seats, promoted Model A/B assets loaded over HTTP, a real Model A recommendation, Hero action feedback, session-stat update, return to analyser, zero page errors and zero console errors.

## Trainer Guided consistency and Hero custom ranges

Issues #30 and #31 are completed and merged after live trainer testing.

- #30 / PR #32 / `b31bbcac8caae2fac31b15cec85c5bdd5e907cc2`: Guided mode now treats the recommendation displayed before Hero acts as the canonical verdict baseline. Sizing-only Model-A labels such as `25% pot` are resolved to BET/RAISE from decision context; clicking an untouched Guided BET/RAISE uses the exact displayed `bestCostBB`; playing the exact guide reuses the pre-action result and must report zero EV loss. Evaluating an alternative Hero action may compute its chosen EV but cannot replace the guide ACTION / exact sizing / best EV.
- #31 / PR #33 / `d3b74d0c934c438f29361928423679a1b309d250`: Hero hole cards are no longer sampled uniformly. The trainer consumes `site/assets/trainer/hero/custom_ranges_v1.json`, normalized from the user's `Custom` range-folder export (source SHA-256 `1248258112562757e49df545e97f9e54b2dde163fdc755adf0029e89e580e8cb`).
- Hero PFA deals use the supplied `Openings` frequencies by position; every non-FOLD opening action is retained, including custom `Multiway` entries. Exact two-card combos receive the hand-class frequency, preserving natural pair/suited/offsuit combo multiplicity.
- Hero SRP-caller deals use only `VS Opening` -> `Call`; 3-bet and 4-bet/shove entries are excluded because they do not form the current trainer's single-raised-pot caller scenario.
- The supplied custom export contains BTN/CO/HJ/LJ/SB but no BB range. Unsupported Hero role/position combinations are resampled rather than invented, so there is intentionally no arbitrary Hero BB caller drill until a BB range is supplied.
- Opponent ranges/actions remain independently generated by promoted Model B v2. Model A formulas, candidate sets and Monte-Carlo trial counts are unchanged.

Regression coverage now includes `tests/trainer/test_trainer_hero_ranges.py`; the browser smoke asserts that the actually dealt Hero notation has positive frequency in the exact Custom role/position range and also rechecks Guided recommendation/verdict identity.

## Trainer performance optimization

Issues #21–#24 are completed and merged. The optimization intentionally preserves v83 recommendation semantics, candidate sets, Monte-Carlo trial counts and Model A/B data.

Implemented changes:

- #21 / PR #25 / `4c1027b6e6e7372c9a77ad7ee7ef1788986b5c74`: Training/Test no longer perform a hidden Model A evaluation before Hero can act; those modes evaluate once after the action. Guided still evaluates before action and reuses the already-computed verdict when Hero plays the exact recommended action/sizing.
- #24 / PR #26 / `948490fccc033d4434d68468cfa73c78e74611dc`: Model A/B trainer assets are fetched/parsed during browser idle time without activating them in analyser state, and deliberate UI waits were reduced from 160/220/180 ms to configurable 20/35/25 ms delays.
- #22 / PR #27 / `a060e8f83dd71860d0f2d5d39f1fe7ab26a195e2`: a bounded 96-entry trainer-local LRU caches exact completed verdicts, deep-copies entries, normalizes only the synthetic evaluation hand ID, and invalidates when either promoted Model A object identity changes.
- #23 / PR #28 / `ce77ca4de84dc37f4177e2c4412ad905dc7b45dd`: the existing v83 Web-Worker review path is now parallelized only while Training is open: 1 worker below 4 logical CPUs, 2 from 4, 3 from 8; outside Training it remains strictly sequential. Sizing results are restored to deterministic task order before finalization.

Performance instrumentation now records evaluation count/reuse, last/total evaluation time, model-load/warmup timing and verdict-cache hits/misses. If latency remains problematic, measure these counters first before considering any reduction in EV accuracy or Monte-Carlo trials.

Permanent regression coverage includes:

- `tests/trainer/test_trainer_latency_contract.py`;
- `tests/trainer/test_trainer_preload_contract.py`;
- `tests/trainer/test_trainer_result_cache_contract.py`;
- `tests/trainer/test_trainer_parallel_review_contract.py`;
- `.github/workflows/trainer-smoke.yml` browser smoke.

## Production opponent model A — integrated analyzer population model

- Preflop production model: `training/models/preflop_population_model_v5.json`.
  - Version: `preflop_v5_incremental_exact_marginals`.
  - SHA-256: `ff952055ca4ee051a3ac9607d513fdecac0a320a31f658ecfd8a11d8448975ca`.
- Postflop production model: `training/models/postflop_population_model_v5.json`.
  - Version: `postflop_v5_clean_continuous`.
  - SHA-256: `6d948f30f6c276ce41e70e83ac35275e30e7841e93e5b1da11782648c6b4d8ae`.
- These models are the opponent models allowed to drive analyzer EV calculations.

## Promoted opponent model B — independent simulation environment

Independent Model B is now reproducible and promoted under alias `independent_model_b_v2`.

Canonical run:

- `training/runs/20260912_independent_profiles_v2/`
- promotion record: `training/runs/20260912_independent_profiles_v2/PROMOTION.json`
- model directory: `training/runs/20260912_independent_profiles_v2/model/`
- prediction contract: `training/runs/20260912_independent_profiles_v2/model/prediction_contract.json`
- holdout evaluation: `training/runs/20260912_independent_profiles_v2/evaluation/holdout_evaluation.json`
- registry pointer: `training/registry.json -> promoted_independent_model`

Training/evidence contract:

- exact hand-ID union of persisted archives, scoped strictly to `100/200`;
- 27,735 unique scoped hands: 22,149 TRAIN / 2,753 VALIDATION / 2,833 TEST;
- player/profile fitting uses TRAIN only and excludes `RoiDePiqueNique`;
- EN, recent FR and legacy FR PokerStars histories are supported;
- no analyser/model-A prediction, EV, policy or recommendation is an input to Model B.

Final profile structure:

- K was selected on VALIDATION only from K=3..8; TEST was not used for selection.
- K=3 won the validation comparison and avoids unstable micro-profiles.
- TRAIN appearance weights: P0 47.07%, P1 21.98%, P2 30.95%.
- 881 players with >=30 TRAIN appearances were used to fit centroids; all 9,132 TRAIN-observed opponents receive a nearest-profile assignment.

Final holdout results:

- VALIDATION actions: +0.02847 nat/decision log-loss improvement vs street/mode fallback; accuracy 66.78%; ECE 0.89%.
- TEST actions: +0.02900 nat/decision; accuracy 67.86%; ECE 0.98%.
- VALIDATION ranges: +0.08734 nat/known-hand improvement vs the 1326-combo combinatorial prior.
- TEST ranges: +0.06307 nat/known-hand.
- appearance-weighted profile stability: 70.21% VALIDATION / 73.38% TEST for players with >=10 holdout appearances.
- sizing calibration: about 80% of holdout aggressive sizings lie inside their TRAIN P10-P90 interval; only about 1.3% exceed their local TRAIN P99.

Model B remains an **external opponent environment**. It must not be used inside Hero EV calculation; its purpose is independent sequential simulation and strategy evaluation. The player trainer may consume Model B only to generate the opponent environment; Hero recommendations still come exclusively from Model A/the analyser.

## Persisted NLHE 100-200 datasets and continuous ingestion

Historical baseline archive:

- `training/datasets/NLHE_100-200/source/NLHE 100-200.zip`
- SHA-256: `6effd27d6e9f8257f3e87c68f0218b8edc72a2b487cb57da2c37ff85bc8ce4c6`.
- 27,164 unique hands total; 26,560 are in the `100/200` lineage.

2026-09-09 snapshot:

- `training/datasets/NLHE_100-200/snapshots/20260909/source/RoiDePiqueNique_training2.zip`
- SHA-256: `7768cd3ddca1f7d48601ea5a7c378e6bf1211d92aadb7cab9b3689f3b9dc561c`.
- 27,677 unique hands total; 11,709 are `100/200`.

Canonical continuous-ingestion result:

- exact overlap within `100/200`: 10,534 hand IDs;
- 1,175 unseen `100/200` hands, all chronologically newer than the baseline cutoff;
- split: 929 TRAIN / 123 VALIDATION / 123 TEST;
- fingerprint: `6142a129292d486c7dedd2aec951b98ed180302d598d38508f45e222f7544bc0`;
- manifest: `training/datasets/NLHE_100-200/increments/20260909/manifest.json`.

The old 1,000-hand delta is an exact subset of these 1,175 hands; the ID-based pipeline recovered 175 valid hands omitted by the earlier date-oriented extraction.

## Integrated-model continuous-training history

Run: `training/runs/20260909_population_increment_v2/`.

- Earlier extraction used 1,000 certain new hands.
- Preflop v5 candidate: accepted.
- Postflop v6 candidate: rejected because it degraded recent VALIDATION and TEST; production remains postflop v5.
- The rejected candidate and additive overlay are preserved for future evidence accumulation.
- This run established the model-A promotion loop: new evidence -> candidate -> recent + historical non-regression -> explicit accept/reject.

## v83 validated behavior

- Artificial JAM calibration bonuses remain disabled.
- Fixed additive BB calibration is scaled down in small pots.
- Unmatched shove amounts no longer distort responder price-to-pot calculations.
- Low-confidence extreme aggression beyond local P90 support is rejected.
- When Hero covers a shorter opponent, the engine recommends the exact effective all-in amount instead of a misleading full Hero-stack JAM.
- The persisted historical 96-decision benchmark report records 2 true Hero JAMs = 2.08%, consistent with the observed population order of magnitude. This result does not prove that the current shipped Monte-Carlo workers are seeded; see the current audit below.
- Historical pathological hand `#262024556922` no longer produces absurd JAM recommendations; river facing bet recommends CALL.

## Experimental engine work

- `tools/patch_v83_to_v84.py` and `tests/regression/v84_overbet_grid_audit.md` exist.
- v84 is not promoted.
- Further engine tuning must be evaluated through the independent Model B arena as well as the permanent direct regression suite before promotion.

## Continuous-training target architecture

For every new hand-history push:

1. Persist/audit the new snapshot and determine the exact hand-ID delta against known evidence.
2. Keep deterministic TRAIN / VALIDATION / TEST assignment.
3. Train/update candidate integrated model A.
4. Train/update candidate independent profile model B.
5. Evaluate/promote or reject each opponent model independently.
6. Evaluate candidate engine strategy against promoted independent Model B using deterministic sequential simulations.
7. Run permanent recommendation non-regression and style/behavior benchmarks.
8. Promote a new application only if strategy and regression gates pass.
9. Persist every input, model, metric, seed contract, report and promotion/rejection decision.

## Current audit — 2026-09-12

Audited main: `caaff599707006fab3daa0f39b90b67c37fdaac1`. Simulator PR #44: `899015dd4d29ffcdb9130ddb10d74347b856a0c1`. Full assessment: `user/reports/etat-des-lieux-2026-09-12.md`.

- **Source gap (#35):** September 12 raw ZIP is absent at its canonical main path; registry remains `source_binary_pending`. Reported delta: 3,268 new 100/200 hands (2,606 TRAIN / 320 VALIDATION / 342 TEST), enlarged union 31,003. Exact raw bytes and standard re-audit are required for complete reconstruction.
- **Simulator (#9 / PR #44):** scenario generation and one-rollout browser CI pass, but HTML uses unseeded `Math.random()` for Hero EV workers. The oracle's `--trials` substitution matches no current HTML string; requested and effective trials can differ. The direct compatibility entrypoint fails to import `tools`. The issue now records reproductions and full-run acceptance criteria.
- **Model A cycle (#36/#37):** both additive candidates were rejected on VALIDATION and v5 stays promoted. Main has the selection report with local candidate hashes, but not a complete reconstructible cycle. Older extraction/overlay scripts still hard-code `/mnt/data`; remaining work is tracked under #7.
- **Model B refresh (#38):** branch `issue-38-model-b-refresh-20260912` at `505b1a8a` has the selection report and incumbent-export workflow. Full new feature/model artifacts and paired comparison are not committed there. Promoted Model B remains v2.
- **Environment validity (#46):** postflop action probabilities are marginal by profile/context, without card strength, board texture, facing-price or SPR conditioning (apart from raise legality). This affects sizing-strategy validation as well as trainer realism. The arena currently supports HU postflop only.
- **CI coverage (#12):** trainer smoke invokes the main static script, not all five dedicated contracts. Pathological-hand fixtures/audits lack an executable regression runner. Gate specification is now ranked before strategy selection.
- **Publication (#45):** Cloudflare builds fail for main caaff599 and PR #44 head 899015dd. Main ingestion and the PR's arena jobs succeed. Public site availability/version was not checked; provider logs are needed to diagnose the failure.
- **Model asset identity:** all seven trainer A/B assets have identical Git blobs to their promoted references.

Local audit: six synthetic ingestion tests passed, one archive-dependent integration test skipped; four trainer performance contracts and trainer.js syntax passed. Worker nondeterminism, ineffective trial replacement and CLI import failure were reproduced. No full training/strategic corpus was rerun.

## Immediate next actions

1. P0 #35: persist exact source ZIP and reproduce IDs, splits and hashes.
2. P0 #9: correct oracle determinism, effective trial control, CLI and candidate B inputs before completing PR #44.
3. P0 #45: diagnose Cloudflare build failure and verify deployed site identity.
4. P1 #12/#7: specify/wire gates and finish Model A reconstruction; retain recorded v5/rejection decisions.
5. P1 #10: freeze v83 + promoted B v2 as a scoped reference using the approved corpus.
6. P1 #38/#46/#39: finish the B paired decision, validate response realism, and freeze the refreshed reference.
7. P2 #11/#40 -> #41 -> #42 -> #13: evaluate strategy, run gates, record outcomes, then automate.
8. Later product work: preflop ACTION / SIZING / EV surface, genuine multiway drills, targeted retry/spaced repetition. Hero BB remains unsupported until a user range is available.

## Remaining bootstrap gap

- `user/releases/poker_range_equity_offline_multiway_v78.html` is not yet committed at its canonical historical path. This does not block current v83 training/validation work.

# Project Status

Last update: 2026-09-14

## Current production state

GitHub repository `aradenac/poker-engine` is the durable source of truth. The 2026-09-12 training cycle is finalized with a **retain-all / no-op production transition**: all candidate evaluations completed, the unified gate is `PASS`, and no promoted model, engine, registry pointer or assembled site file moved.

Authoritative production state:

- population: `NLHE 100-200`;
- integrated Model A preflop: `training/models/preflop_population_model_v5.json` — SHA-256 `ff952055ca4ee051a3ac9607d513fdecac0a320a31f658ecfd8a11d8448975ca`;
- integrated Model A postflop: `training/models/postflop_population_model_v5.json` — SHA-256 `6d948f30f6c276ce41e70e83ac35275e30e7841e93e5b1da11782648c6b4d8ae`;
- independent opponent environment: `independent_model_b_v2`, run `training/runs/20260912_independent_profiles_v2/`;
- promoted recommendation engine: **v83**;
- canonical engine artifact: `user/releases/poker_range_equity_offline_multiway_v83.html` — SHA-256 `2690a82ffe363017b495a1aef60657b12db1b52eb402c36a1ff87f723c5d1bd4`;
- assembled application entry point: `site/index.html`, Git blob `8b2a63722562f913fb95871f24be664e9c210c68`;
- current registry Git blob: `bbf2ea6f32f7ac8aea5dd92c4ed0f4839c6d7879`.

`training/registry.json` remains the production pointer source. Rejected candidates and experimental environments remain immutable evidence only and must not be substituted for these pointers.

## Closed training cycle — 2026-09-12

The cycle consumed a verified September 12 snapshot and produced a deterministic 3,268-hand unseen increment:

- source snapshot SHA-256: `374f8dedf5eeeee26b2cd049b1729f80bd2877c6f7ccef806c580019c5f94fcb`;
- selected increment SHA-256: `00de0085ebe3f090388879409d19e6c84c4896b2761298876f0f4f8dee7c57ed`;
- split: 2,606 TRAIN / 320 VALIDATION / 342 TEST;
- resulting union: 31,003 unique 100/200 hands;
- selected hand-ID fingerprint: `9eb753baed592b48d697ad6d00652612de6153e5033448f41983bccc9e31be2b`.

Final candidate decisions:

| Component | Decision | Result |
|---|---|---|
| Model A preflop | `RETAIN_BASELINE` | v5 retained |
| Model A postflop | `RETAIN_BASELINE` | v5 retained |
| Model B refresh | `RETAIN_BASELINE` | v2 retained |
| Hero strategy | `RETAIN_BASELINE` | v83 retained |

The unified gate is persisted in `training/gates/20260912_report.json` and reports `status=PASS`, `promotion_ready=true`. In this contract, `PASS` means that the evidence and decision process are complete and valid; it does **not** mean that rejected candidates passed their quality thresholds.

The final immutable state is `training/runs/20260912_population_increment_cycle/FINAL_STATE.json`. It is regenerated and verified by `tools/finalize_training_cycle.py` and records exact hashes, rollback pointers, source state, decisions and the no-op before/after registry transition.

## Strategy selection

The protected v84-oriented strategy campaign compared the promoted `current` policy against `cap_3` and `cap_4` in the corrected response-conditioned Model B v3 `price` environment.

Contracted VALIDATION sample: 96 base hands × 2 repetitions = 192 paired scenarios, seed 20260912, 1,200 analyser trials per decision.

- `cap_3`: mean candidate-minus-current utility `+1.0132 BB`, CI95 `[-2.8303, +5.1571]`;
- `cap_4`: mean `+1.2982 BB`, CI95 `[-2.4935, +5.2771]`.

Neither lower confidence bound reached the pre-specified `>= 0` criterion. No finalist was frozen, v83 was retained, and protected strategy TEST was **not consumed**. Evidence lives under `training/runs/20260913_strategy_candidate_v84/`.

Response-conditioned Model B v3 remains an **external heads-up postflop evaluation environment only** with production effect `NONE`.

## Model B localization correction

The 2026-09-13 audit found that the historical parser failed to recognize the real French PokerStars button grammar (`est au bouton`), producing missing positions for 994 French hands out of the 31,003-hand corpus: 803 TRAIN / 90 VALIDATION / 101 TEST.

The parser was corrected and all affected Model B evidence was rebuilt. The corrected conclusions remain:

- response-conditioned v3 selects variant `price` for external strategy evaluation;
- the same-structure refreshed production candidate does not establish the required action-log-loss non-regression;
- promoted `independent_model_b_v2` is retained.

Production Model B v2 artifacts are protected from accidental in-place rebuilds and have their exact hashes recorded in `FINAL_STATE.json`.

## Unseen preflop topology follow-up

Issue #61 audited the 4,727 TRAIN preflop rows outside the exact v5 topology:

- 1,017 unseen exact contexts;
- 595 singleton contexts;
- 51 contexts with support >=20 cover 2,300 rows (~48.7% of unseen evidence);
- dominant families: `VS_LIMPERS` 2,054 rows, `VS_ISO` 668, `VS_RFI_CALLERS` 661.

This does not justify materializing all 1,017 nodes. The next Model A structural experiment must be targeted, select topology/hyperparameters on VALIDATION only, and reserve TEST.

## Application and trainer

The static application includes the analyser/replayer and the 6-max trainer. Hero recommendations always come from Model A/v83. Promoted Model B v2 is used only to generate opponent behavior in the trainer/simulation environment.

The trainer includes Guided/Training/Test modes, Hero custom-range sampling, result caching, preload/warmup and bounded worker parallelism. Existing trainer/browser regression contracts remain part of CI.

The user's original custom range-folder export has source SHA-256 `1248258112562757e49df545e97f9e54b2dde163fdc755adf0029e89e580e8cb`. Issue #74 will publish that user artifact together with the two promoted Model A JSON files as one coherent `NLHE 100-200` package; it must not silently substitute the smaller normalized trainer-only file.

## Deployment

Cloudflare Workers Git integration successfully builds commit/branch previews, but issue #45 remains open because the production public URL, deployed production identity and live production smoke have not been proven end-to-end.

This is separate from the 2026-09-12 training-cycle closure. The retain-all transition changed no engine/site artifact, so that cycle does not require a new deployment.

## Active backlog

Immediate product/engineering work after cycle closure:

1. **#74 — coherent user artifact bundle:** publish `custom.json` + promoted preflop/postflop Model A JSON + manifest/checksums/readme as an immutable GitHub package/release asset for `NLHE 100-200`.
2. **#73 — replayer combo labels:** show canonical hand classes (`AKs`, `QJo`, `77`) for each player only when exact hole cards are known at the current replay point.
3. **#13 — automate continuous training:** turn the now-reproducible ingest → train → evaluate → retain/promote → finalize chain into a guarded workflow, including the retain/no-pointer-change case.
4. **#61 — targeted unseen-preflop structural experiment:** evaluate only sufficiently supported missing contexts under the locked split contract.
5. **#45 — production publication verification:** independently establish the real production URL/build identity and live smoke.

Historical bootstrap cleanup remains lower priority and must not destabilize the current verified production state.

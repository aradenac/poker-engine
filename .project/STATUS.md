# Project Status

Last update: 2026-09-15

## Source of truth and active plan

GitHub repository `aradenac/poker-engine` is the durable source of truth. The active delivery plan is **issue #92 — Moteur NLHE 100/200 Zoom : préflop, ranges Hero et entraînement continu**.

Completed on the current critical path:

- **#93** — handoff documentation and application/release identity reconciled; merged through PR #115.
- **#94** — PokerStars NLHE 100/200 Zoom play-money corpus certified; merged through PR #116.
- **#95** — datasets/models/strategies isolated by explicit population; merged through PR #117 at main commit `a56a3eb5c9ee2d70a39cc498ba8244badf683318`.

Current delivery:

- **#96** — canonical preflop context/probability contract is implemented on PR #118 and under final regression validation.

Next after #96:

1. **#97** — Hero range repository/editor;
2. **#98** — Hero range compliance in the replayer;
3. **#99–#109** — evaluation gates, full-hand/multiway core, Model A/B refits, strategy generation/selection and preflop guidance;
4. **#110/#111/#45** — durable packs, Cloudflare catalogue and verified live production;
5. **#112/#113** — new-hand snapshot to reproducible decision/release.

#114 is consolidation work and #1 is historical provenance; neither blocks the product path.

## Population isolation — #94/#95

The intended target population is:

`pokerstars_nlhe_100-200_zoom_play_6max_v1`

Certification over the historical baseline plus the complete 2026-09-12 inventory found:

- **31,607** unique raw hand IDs;
- **31,003** unique 100/200 hands across formats;
- **23,789 ADMISSIBLE** target Zoom/play-money/6-max 100/200 hands;
- **7,214** regular/classic 100/200 play-money 6-max exclusions;
- **604** Zoom play-money 6-max hands at 100000/200000 exclusions;
- **0 AMBIGUOUS**.

Target split: **19,016 TRAIN / 2,324 VALIDATION / 2,449 TEST**.

Target hand-ID fingerprint SHA-256:
`4661c200fab5a24ce67a45f0801acd0238c701f55e8dbeeaf3e8299fa250119c`

`training/populations/registry.json` is authoritative for new population-scoped work. It declares:

- `legacy_pokerstars_nlhe_100-200_play_6max_mixed_v1` — `PROMOTED_LEGACY`, explicitly MIXED_ZOOM_REGULAR;
- `pokerstars_nlhe_100-200_zoom_play_6max_v1` — `CERTIFIED_DATA_ONLY`, no inherited promoted artifacts;
- `pokerstars_nlhe_250-500_zoom_play_6max_v1` — `DECLARED_EMPTY`;
- `pokerstars_nlhe_nl5_zoom_real_eur_6max_v1` — `DECLARED_EMPTY`.

`training/registry.json` remains the immutable closed-cycle legacy anchor. Do not relabel existing Model A v5, Model B v2 or engine v83 as Zoom-only and do not silently inherit them into the certified target population.

## Canonical preflop contract — #96

PR #118 introduces `poker-preflop-context/v1` in Python and browser JavaScript. The context represents the table **immediately before one voluntary action** and is deliberately card-free. It includes actor/table positions, ordered prior actions, raise level/family, live/all-in/remaining-to-act positions, contributions, current price, to-call, free check, pot, remaining/effective stack, legal actions and min/max raise-to bounds.

Sizing semantics are explicit:

- call/bet/raise cost = incremental chips committed now (`incremental_cost_bb`);
- raise target = total contribution reached (`target_total_bb`);
- check/fold cost = zero.

The training decision builder preserves closed historical output by default. Rich v1 context is opt-in with `--preflop-contract-v1`; CI proves the default 2026-09-09 JSONL remains byte-identical while opt-in output contains the new contract.

`poker-preflop-action-probabilities/v1` has two deliberate modes:

- `strict_legal_normalized` for future candidates;
- `incumbent_v5_passthrough` for the promoted v5/v83 behavior, which exposes legal/model action-set compatibility, source, backoff, confidence and support while preserving every incumbent probability without filtering or renormalization.

Shared fixtures cover unopened, 1/2/3+ limpers, iso, open+caller/squeeze, 3-bet, 4-bet, jam and the BB free-check case. Python and JavaScript consume the same fixtures. A synthetic PokerStars HH proves before-action extraction and sizing semantics.

## Permanent #88 decision

#88 remains closed and authoritative. Historical comma versus `>` history separators are representation-only. The promoted exact matcher continues to use actor position, table size, raise level, family, live/all-in arrays and ordered `(position, action)` history. `free_check` and the richer #96 stack/price/sizing metadata are **not** silently added to the incumbent exact predicate.

Any future matcher behavior change is a new candidate and must pass the active validation gate.

## Current promoted baseline

The 2026-09-12 training cycle remains a **retain-all / no-op production transition**.

- Model A preflop: `training/models/preflop_population_model_v5.json`, SHA-256 `ff952055ca4ee051a3ac9607d513fdecac0a320a31f658ecfd8a11d8448975ca`;
- Model A postflop: `training/models/postflop_population_model_v5.json`, SHA-256 `6d948f30f6c276ce41e70e83ac35275e30e7841e93e5b1da11782648c6b4d8ae`;
- Model B: `independent_model_b_v2` under `training/runs/20260912_independent_profiles_v2/`;
- recommendation engine: **v83**;
- engine artifact: `user/releases/poker_range_equity_offline_multiway_v83.html`, SHA-256 `2690a82ffe363017b495a1aef60657b12db1b52eb402c36a1ff87f723c5d1bd4`.

No #95/#96 migration changes those promoted scientific pointers.

## Strategy evidence scope

The protected v84-oriented campaign compared `current`, `cap_3` and `cap_4` only in a heads-up postflop response-conditioned environment. Neither candidate met the pre-specified confidence criterion, so v83 was retained and protected strategy TEST was not consumed.

This is not evidence of global optimality. Full-hand/multiway validation is tracked by #99/#100/#105/#108.

## Application and deployment identity

Engine release, assembled static application and live Cloudflare deployment remain separate identities.

`site/RELEASE.json` uses `poker-site-release/v3`; `tools/write_site_release.py --check` guards the assembled functional bytes. `site/preflop-contract.js` is now part of that functional identity. `published=true` or a successful build is not live-production proof.

#45 remains open for canonical production URL, exact served revision, live analyser/trainer/assets smoke and production-versus-preview policy.

## Immediate continuation

Finish PR #118 only when the preflop-contract workflow, persisted historical dataset integrity, trainer browser smoke and arena smoke are green on the same final head. Then merge #96 and start **#97** from the merged main state. Do not use the #96 work as permission to retrain or promote a Zoom-only model; #101+ own those scientific changes.

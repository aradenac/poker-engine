# Project Status

Last update: 2026-09-14

## Source of truth and active plan

GitHub repository `aradenac/poker-engine` is the durable source of truth. The active delivery plan is **issue #92 — Moteur NLHE 100/200 Zoom : préflop, ranges Hero et entraînement continu**. Follow its dependency order; do not revive closed historical tickets merely because they appear in older reports.

Completed on the current critical path:

- **#93** — handoff documentation and application/release identity reconciled; merged through PR #115.
- **#94** — target population certification implemented and measured in PR #116; certification evidence is `training/datasets/NLHE_100-200/population_certification.json`.

Next critical path:

1. **#95** — isolate datasets, models and strategies by population;
2. **#96** — unify preflop context/probability contracts;
3. **#97/#98** — Hero range editor and compliance;
4. **#99–#109** — full-hand/multiway modelling, training, evaluation and preflop guidance;
5. **#110/#111/#45** — durable packs, Cloudflare catalogue and verified live production;
6. **#112/#113** — new-hand snapshot to decision/release from one prompt.

#114 is consolidation work and #1 is historical provenance; neither blocks the product path.

## Certified target population — #94

The intended target population is now explicitly identified as:

`pokerstars_nlhe_100-200_zoom_play_6max_v1`

Contract:

- PokerStars;
- NLHE cash;
- 100/200 play-money chips;
- Zoom;
- 6-max.

The authoritative historical baseline plus complete 2026-09-12 inventory contain **31,607 unique raw hand IDs**. Conservative classification gives:

- **23,789 ADMISSIBLE** target hands;
- **7,818 EXCLUDED**;
- **0 AMBIGUOUS**.

The exclusions are:

- **7,214** regular/classic 100/200 play-money 6-max hands;
- **604** Zoom play-money 6-max hands at 100000/200000.

Therefore the previously used **31,003** count is a correct blind-scoped 100/200 union, but **not** a Zoom-only corpus. Of those 31,003 100/200 hands, 23,789 are Zoom and 7,214 are regular-table hands.

Certified target evidence:

- hand-ID fingerprint SHA-256: `4661c200fab5a24ce67a45f0801acd0238c701f55e8dbeeaf3e8299fa250119c`;
- split: **19,016 TRAIN / 2,324 VALIDATION / 2,449 TEST**;
- raw-union hand-ID fingerprint SHA-256: `316ae5b58630d852bac54bfc9af0fb53c83c37053677230328f3120ddacd98fb`;
- no duplicate metadata conflict;
- no same-language payload conflict;
- no unparsed PokerStars hand header in the audited archives.

Source archives remain immutable:

- historical baseline SHA-256 `6effd27d6e9f8257f3e87c68f0218b8edc72a2b487cb57da2c37ff85bc8ce4c6`;
- 2026-09-12 snapshot SHA-256 `374f8dedf5eeeee26b2cd049b1729f80bd2877c6f7ccef806c580019c5f94fcb`.

`tools/datasets/certify_population.py` performs the classification. `.github/workflows/population-certification.yml` regenerates the report and compares it byte-for-byte with the persisted evidence.

## Consequence for promoted models

Do **not** relabel the current promoted Model A v5, Model B v2 or engine v83 as Zoom-only. Their historical data lineage used the broader blind-scoped dataset, which includes the 7,214 regular-table 100/200 hands.

The active legacy dataset pointer remains `NLHE_100-200` until #95 performs an explicit migration. `training/registry.json` records the certified target as `CERTIFIED_SOURCE_SUBSET_NOT_YET_ISOLATED` with `is_active_dataset_pointer=false`.

This distinction is critical: #94 certifies source membership; **#95 must create isolated population state and protect each population's dataset/model/strategy pointers from cross-contamination**.

## Current promoted baseline

The 2026-09-12 training cycle remains a **retain-all / no-op production transition**. No candidate from that cycle replaced the promoted references.

- Model A preflop: `training/models/preflop_population_model_v5.json`, SHA-256 `ff952055ca4ee051a3ac9607d513fdecac0a320a31f658ecfd8a11d8448975ca`;
- Model A postflop: `training/models/postflop_population_model_v5.json`, SHA-256 `6d948f30f6c276ce41e70e83ac35275e30e7841e93e5b1da11782648c6b4d8ae`;
- Model B: `independent_model_b_v2` under `training/runs/20260912_independent_profiles_v2/`;
- recommendation engine: **v83**;
- engine artifact: `user/releases/poker_range_equity_offline_multiway_v83.html`, SHA-256 `2690a82ffe363017b495a1aef60657b12db1b52eb402c36a1ff87f723c5d1bd4`.

Rejected candidates and experimental environments remain immutable evidence only.

## Permanent #88 decision

#88 is closed. Historical preflop key separator variants were shown to be semantically equivalent under the retained v5 matcher. Do not mass-create missing nodes or change the incumbent matcher merely to eliminate textual differences. Any future behavior change is a new candidate and must pass the active gates.

## Strategy evidence scope

The protected v84-oriented campaign compared `current`, `cap_3` and `cap_4` only in a heads-up postflop response-conditioned environment. Neither candidate met the pre-specified confidence criterion, so v83 was retained and protected strategy TEST was not consumed.

This is not evidence of global optimality. Full-hand/multiway validation is tracked by #99/#100/#105/#108.

## Application and deployment identity

Engine release, assembled static application and live Cloudflare deployment remain separate identities.

`site/RELEASE.json` uses `poker-site-release/v3`; `tools/write_site_release.py --check` guards the assembled functional bytes. `published=true` or a successful build is not live-production proof.

#45 remains open for canonical production URL, exact served revision, live analyser/trainer/assets smoke and production-versus-preview policy.

## Immediate continuation

After #94 merges, start **#95** from the certified population identity above. Migration must preserve the existing legacy production pointers until population-specific state is demonstrably coherent; no scientific result should silently change because a directory was renamed or a subset was introduced.

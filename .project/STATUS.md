# Project Status

Last update: 2026-09-14

## Source of truth and active plan

GitHub repository `aradenac/poker-engine` is the durable source of truth. The active delivery plan is **issue #92 — Moteur NLHE 100/200 Zoom : préflop, ranges Hero et entraînement continu**. A future session must follow #92 and the dependency order in `.project/PLAN.md`; it must not revive closed tickets merely because they still appear in historical reports.

The immediate critical path is:

1. #93 — reconcile handoff documentation and application identity;
2. #94 — certify the PokerStars NLHE 100/200 Zoom play-money corpus;
3. #95 — isolate datasets/models/strategies by population;
4. #96 — unify preflop context/probability contracts;
5. #97/#98 — deliver Hero range editing and compliance;
6. #99–#109 — full-hand/multiway modelling, training, evaluation and preflop guidance;
7. #110/#111/#45 — durable packs, Cloudflare catalogue and verified production;
8. #112/#113 — new-hand snapshot to decision/release from one prompt.

#114 is consolidation work and #1 is historical provenance; neither blocks the product path.

## Current promoted baseline

The 2026-09-12 training cycle remains a **retain-all / no-op production transition**. No model or engine candidate from that cycle replaced the promoted references.

Authoritative baseline:

- population label currently used by legacy assets: `NLHE 100-200`; its Zoom/play-money/table-size certification is the purpose of #94;
- Model A preflop: `training/models/preflop_population_model_v5.json`, SHA-256 `ff952055ca4ee051a3ac9607d513fdecac0a320a31f658ecfd8a11d8448975ca`;
- Model A postflop: `training/models/postflop_population_model_v5.json`, SHA-256 `6d948f30f6c276ce41e70e83ac35275e30e7841e93e5b1da11782648c6b4d8ae`;
- independent opponent environment: `independent_model_b_v2`, run `training/runs/20260912_independent_profiles_v2/`;
- promoted recommendation engine: **v83**;
- canonical engine artifact: `user/releases/poker_range_equity_offline_multiway_v83.html`, SHA-256 `2690a82ffe363017b495a1aef60657b12db1b52eb402c36a1ff87f723c5d1bd4`;
- registry pointer source: `training/registry.json`.

Rejected candidates and experimental environments are immutable evidence only. They must not be substituted for promoted pointers.

## Closed 2026-09-12 cycle

The verified September 12 snapshot produced a deterministic 3,268-hand unseen increment and a 31,003-hand 100/200 union under the legacy blind-scoped classifier. That count is **not yet a certification that every hand is Zoom/play-money**, hence #94.

Final decisions:

| Component | Decision | Result |
|---|---|---|
| Model A preflop | `RETAIN_BASELINE` | v5 retained |
| Model A postflop | `RETAIN_BASELINE` | v5 retained |
| Model B refresh | `RETAIN_BASELINE` | v2 retained |
| Hero strategy | `RETAIN_BASELINE` | v83 retained |

The immutable closure is `training/runs/20260912_population_increment_cycle/FINAL_STATE.json`. The unified gate `PASS` means the evidence/decision process was valid; it does not mean rejected candidates satisfied their quality gates.

## Preflop parity decision — issue #88

#88 is complete and must not be reopened without new evidence. The historical preflop key separators were shown to be semantically equivalent under the current v5 matcher. The current matcher is retained. Do **not** mass-materialize missing nodes merely to eliminate textual key differences.

The targeted topology experiment from #61 was also completed. Its evidence remains useful, but the new generic work is tracked by #96/#99/#101 rather than by reopening #61.

## Strategy evidence scope

The protected v84-oriented campaign compared `current`, `cap_3` and `cap_4` only in a heads-up postflop response-conditioned environment. Neither candidate established the pre-specified confidence criterion, so v83 was retained and protected strategy TEST was not consumed.

This is not evidence that v83 is globally optimal, nor a complete preflop/multiway cash-game benchmark. The full-hand benchmark and preflop selection are tracked by #99/#100/#105/#108.

## Application and release identity

Engine version, assembled static application and deployed Cloudflare revision are distinct identities.

`site/RELEASE.json` uses `poker-site-release/v3` and identifies:

- immutable engine v83 by SHA-256;
- assembled functional application bytes by content-addressed Git objects for `site/index.html`, `site/trainer.js`, `site/trainer.css` and `site/assets`;
- live publication separately as `UNVERIFIED_LIVE` until #45 proves the canonical URL and deployed revision.

`tools/write_site_release.py --check` is the permanent stale-identity guard. Cloudflare regenerates the repository/build identity during its build; `site/deployment-meta.css` carries deployment-specific build metadata and is intentionally excluded from the functional application identity.

A successful build, `published=true`, or a repository release identity is **not** proof that a specific production URL is serving those bytes.

## Application/trainer baseline

The static site contains the analyser/replayer and 6-max trainer. Existing delivered work includes the trainer, bounded parallel review, custom-range sampling, coherent user artifact bundle automation, replayer visible-hand-class labels, continuous-cycle orchestration primitives, atomic promotion safeguards and the generic snapshot-cycle planner.

Those earlier tickets are closed accomplishments; do not re-plan them as active work. Their successor requirements are represented by #92 and its child issues.

## Deployment

Cloudflare Workers Git integration has produced both successful and failed builds across recent commits. #45 remains open because the following must be proven together:

- canonical production URL;
- exact deployed commit/build identity;
- live analyser/trainer/assets smoke;
- production-versus-preview trigger policy.

Do not modify Cloudflare configuration speculatively to explain a historical failure that is not reproduced or diagnosed.

## Next executable work after #93

1. **#94 — certify the target corpus.** Classify platform/variant/play-money/Zoom/table-size/rake and quantify ambiguous/excluded hands without rewriting historical sources.
2. **#45 — production verification lane.** It can proceed independently when Cloudflare endpoint/provider evidence is available.
3. After #94, execute **#95**, then **#96**. Do not begin scientific promotion claims for later tickets before their declared dependencies/gates are satisfied.

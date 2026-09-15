# Handoff Protocol

This file is intentionally tool-oriented. It tells a future assistant/session how to resume work without relying on chat history.

## Resume sequence

1. Read GitHub issue **#92**: it is the master product/backlog plan and dependency graph.
2. Read `.project/STATUS.md` for the promoted baseline, validated findings and immediate executable work.
3. Read `.project/PLAN.md` for the ordered implementation plan derived from #92.
4. Read `training/populations/registry.json` for the authoritative population-scoped state used by new scientific work.
5. Treat `training/registry.json` as the immutable closed-cycle legacy anchor; do not rewrite it to represent new populations.
6. Inspect the relevant open issue and its declared dependencies before changing code or scientific state.
7. Inspect the latest immutable evidence under `training/runs/`, plus `user/releases/` and the tests covering the component being changed.
8. Do not assume a newer chat attachment is authoritative unless it has been persisted and referenced by repository state.

## Current continuation point

The critical-path foundation is now:

- **#93** release/handoff identity — closed;
- **#94** target corpus certification — closed;
- **#95** population isolation — closed;
- **#96** canonical preflop context/probability contract — current PR #118; once merged, continue with **#97** then **#98**.

Issue #45 (live Cloudflare production verification) may proceed in parallel when provider/endpoint evidence is available.

Do not redo completed work simply because an older plan mentions it. In particular, #13/#61/#73/#74/#82/#87/#88 represent acquired work or decisions whose successors are tracked in #92.

### Population rule from #94/#95

The historical 100/200 lineage is `legacy_pokerstars_nlhe_100-200_play_6max_mixed_v1` and is deliberately **MIXED_ZOOM_REGULAR**. Do not relabel promoted Model A v5, Model B v2 or engine v83 as Zoom-only.

The certified target `pokerstars_nlhe_100-200_zoom_play_6max_v1` contains 23,789 admissible hands and currently has no promoted Model A/B/Hero/engine pointers. Never inherit the legacy mixed artifacts into it implicitly.

Every new scientific invocation must name its `population_id`, and caches/runs/artifacts must remain population-scoped.

### Permanent #88 decision and #96 projection

Historical preflop key separator variants are semantically equivalent under the retained v5 matcher. Do not mass-create topology nodes or change the incumbent matcher merely to eliminate textual separator differences.

`poker-preflop-context/v1` is the richer before-action contract introduced by #96. Its compatibility projection deliberately preserves the #88 incumbent exact signature: `free_check`, stacks, prices, sizing bounds and remaining-to-act metadata do **not** become new v5 exact-match fields simply because the richer context contains them.

For closed historical decision JSONL, the default extractor remains byte-compatible. New consumers that need the richer fields must explicitly request `--preflop-contract-v1`.

Probability consumers distinguish two modes:

- future candidates: strict legal-action normalization;
- incumbent v5/v83: `incumbent_v5_passthrough`, which annotates compatibility/backoff/confidence but never filters or renormalizes promoted probabilities.

Any future behavioral change remains a candidate requiring evaluation under the active gates.

## Application identity rule

Engine release, assembled static application and live deployed revision are separate identities.

When functional site bytes change (`site/index.html`, `site/preflop-contract.js`, `site/trainer.js`, `site/trainer.css` or `site/assets/**`):

1. run `python3 tools/write_site_release.py` to regenerate `site/RELEASE.json`;
2. run `python3 tools/write_site_release.py --check` before delivery;
3. keep `site/deployment-meta.css` out of the functional identity because Cloudflare generates deployment-specific commit/build metadata there;
4. never treat `published=true`, a successful build or repository metadata as proof of the canonical live deployment. That proof belongs to #45.

Cloudflare's build command regenerates both deployment metadata and release identity from the checked-out bytes.

## State update rule

At every meaningful milestone:

- update `.project/STATUS.md`;
- update `.project/PLAN.md` if priorities/order changed;
- update this handoff file when the resume procedure or a permanent decision changes;
- update `training/populations/registry.json` only when authoritative population-scoped pointers/state actually change;
- keep `training/registry.json` unchanged unless an explicit migration of the closed legacy anchor is itself the reviewed task;
- persist generated artifacts needed to reproduce or continue the work;
- record material design/calibration decisions under `.project/decisions/` when they are not obvious from code/evidence.

A documentation-only or application-identity change must not rewrite promoted model pointers merely to create activity in a registry.

## User/tool separation

User-facing artifacts belong under `user/`.
Tool-only working state, diagnostics and continuity metadata belong under `.project/` or `tools/`.
Training evidence belongs under `training/` because it is part of the reproducible scientific state of the engine.

## Do not persist

- transient caches;
- duplicated exports that can be regenerated exactly;
- secrets, credentials or tokens;
- huge raw binaries without an explicit storage strategy;
- speculative results not tied to a reproducible run.

## Naming

Use immutable/versioned names for releases and training runs. Prefer ISO dates and explicit version/population identifiers over ambiguous names such as `latest2` or `final_final`.

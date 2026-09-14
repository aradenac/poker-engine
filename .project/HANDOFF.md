# Handoff Protocol

This file is intentionally tool-oriented. It tells a future assistant/session how to resume work without relying on chat history.

## Resume sequence

1. Read GitHub issue **#92**: it is the master product/backlog plan and dependency graph.
2. Read `.project/STATUS.md` for the promoted baseline, validated findings and immediate executable work.
3. Read `.project/PLAN.md` for the ordered implementation plan derived from #92.
4. Read `training/registry.json` for active dataset/model/run references.
5. Inspect `.project/HANDOFF.md`, the relevant open issue and its declared dependencies before changing code or scientific state.
6. Inspect the latest immutable evidence under `training/runs/`, plus `user/releases/` and the tests covering the component being changed.
7. Do not assume a newer chat attachment is authoritative unless it has been persisted and referenced by repository state.

## Current continuation point

After #93, the main critical path begins with **#94 — certify the PokerStars NLHE 100/200 Zoom play-money corpus**, followed by #95 and #96. Issue #45 (live Cloudflare production verification) may proceed in parallel when provider/endpoint evidence is available.

Do not redo completed work simply because an older plan mentions it. In particular, #13/#61/#73/#74/#82/#87/#88 represent acquired work or decisions whose successors are tracked in #92.

### Permanent #88 decision

The historical preflop key separator variants were shown to be semantically equivalent under the retained v5 matcher. Do not mass-create topology nodes or change the incumbent matcher merely to eliminate textual separator differences. A future behavioral change must be a new candidate evaluated under the active gates.

## Application identity rule

Engine release, assembled static application and live deployed revision are separate identities.

When functional site bytes change (`site/index.html`, `site/trainer.js`, `site/trainer.css` or `site/assets/**`):

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
- append/update the relevant training registry entry only when authoritative scientific pointers/state actually change;
- persist generated artifacts needed to reproduce or continue the work;
- record material design/calibration decisions under `.project/decisions/` when they are not obvious from code/evidence.

A documentation-only or application-identity change must not rewrite promoted model pointers merely to create activity in `training/registry.json`.

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

# Historical provenance audit — 2026-09-15

Issue: #1.

## Scope and decision

This audit closes the remaining historical-bootstrap ambiguity without changing any promoted scientific or user-facing pointer.

The current repository already persists the artifacts that are actually consumed by reproducible training and production work:

- promoted user release: `user/releases/poker_range_equity_offline_multiway_v83.html`;
- Model A preflop: `training/models/preflop_population_model_v5.json`;
- Model A postflop: `training/models/postflop_population_model_v5.json`;
- baseline 100/200 raw corpus: `training/datasets/NLHE_100-200/source/NLHE 100-200.zip`;
- later immutable snapshots/increments and independent Model B runs under `training/`.

`training/registry.json` has no pending import and no active pointer references v78. A recursive repository-tree audit and code/commit search on 2026-09-15 found no current test, workflow, model registry, release pointer or runtime path referring to `poker_range_equity_offline_multiway_v78.html`.

Therefore the exact v78 HTML is historical provenance, not a hidden runtime dependency. Its absence must remain explicit, but it must not block current model, strategy, pack or deployment work.

## v78 external identity

The original uploaded historical file remains identified as:

- basename: `poker_range_equity_offline_multiway_v78.html`;
- expected historical canonical location: `user/releases/poker_range_equity_offline_multiway_v78.html`;
- size: **415,744 bytes**;
- SHA-256: `352eabe2b2e6245f6442e79c1ced8dd0b53c5e655d3c5cff52311cdac5b42050`;
- repository status: **not stored**.

The active GitHub connector can inspect the historical upload but does not expose an exact raw-file transfer suitable for claiming byte-identical persistence. The repository must therefore not contain a reconstructed or snippet-derived surrogate under the canonical v78 filename.

If a future forensic task genuinely needs exact v78 bytes, import is permitted only after obtaining a raw file whose size and SHA-256 match the identity above. That import would be archival only and must not alter promoted pointers.

## Restored transformation provenance

The useful missing small source artifact was the fail-fast transformation from v78 to v79. It has now been restored verbatim at:

`tools/patch_v78_to_v79.py`

This completes the source-level patch lineage into the scripts already preserved in the repository:

1. `tools/patch_v78_to_v79.py`;
2. `tools/patch_v79_to_v80.py`;
3. `tools/patch_v80_to_v81.py`;
4. `tools/patch_v81_to_v82.py`;
5. `tools/patch_v82_to_v83.py`;
6. `tools/patch_v83_to_v84.py`.

The restored script is deliberately fail-fast and checks structural anchors before producing v79. It is archival transformation provenance; it does not authorize rebuilding or promoting historical releases automatically.

## Non-goals

This audit does not:

- rewrite `training/registry.json` or population promotion state;
- change v83, Model A v5, Model B v2, Hero strategy or the current application;
- copy old HH or model data into user-facing directories;
- claim v78 is available in Git when it is not;
- make historical reconstruction a dependency of the active #92 product path.

## Closure rule

Issue #1 is complete when the historical identity above is retained, the v78→v79 source transformation is persisted, and no current dependency falsely requires the unavailable v78 bytes. If exact v78 bytes later become available, they may be added as an optional immutable archival artifact after hash verification without reopening the critical product path.

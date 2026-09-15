# Shared component extraction policy

Issue #114 keeps shared engine/application code incremental rather than turning the historical static application into a broad frontend rewrite.

## First extracted component: preflop contract

The JavaScript preflop context/probability contract from issue #96 now has one edit source:

- source: `src/preflop/contract.js`;
- runnable static copy: `site/preflop-contract.js`;
- synchronization: `python3 tools/sync_shared_modules.py --write`;
- CI drift guard: `python3 tools/sync_shared_modules.py --check`.

At extraction time the two files have the same Git blob SHA (`14f0767d909b1919be01053e5c02363a21ec9ab9`). This is deliberate evidence that moving source ownership does not change any context, legal action, probability, decision, sizing or runtime output.

The existing shared fixtures and Python/JavaScript parity tests remain the behavioral guard. The new synchronization check is stronger for this JavaScript source path: the file served by the browser must be byte-identical to the source reviewed under `src/`.

## Boundaries

This extraction does **not**:

- change the promoted v83/v5 strategy or model A/B parameters;
- add dependencies between Hero policy code and model B;
- introduce a bundler or alter Cloudflare static layout;
- change worker/cache identities or browser loading order;
- rewrite historical releases under `user/releases/`.

New consumers should import/require the source-owned contract in tooling where practical. Browser production continues to consume the synchronized static copy until a separately tested application build step justifies changing that deployment boundary.

## Performance rule

Do not optimize shared components merely because they have been extracted. Measure a user-visible or simulation bottleneck first and keep the relevant worker/cache versioning in the benchmark. This first extraction adds no runtime work at all: the browser still downloads and executes the same `site/preflop-contract.js` bytes, so there is no performance claim to validate beyond preservation of the existing artifact.

## Further extraction criterion

Move another component only when at least one of these is true:

1. two active consumers currently duplicate the same tested semantics;
2. duplicated logic blocks a concrete feature or parity check;
3. a measured performance problem requires a shared implementation boundary.

Each extraction must preserve deterministic snapshots before any semantic or performance change is attempted.

# Hero range repository v1

Issue #97 introduces `poker-hero-range-repository/v1` for user-owned preflop strategy ranges. Issue #392 makes the repository **population-bound**: it answers for exactly one `population_id`, and a personal range is an explicit override, not the repository's default identity.

## Scope

The repository is deliberately separate from opponent population ranges and from Model A recommendations. A personal Hero range is a user plan, not a claim of optimality. A future calculated range may coexist with the personal layer without overwriting it.

The browser editor is `site/hero-ranges.html`, linked from the main application. Its contract implementation is `site/hero-ranges.js`.

The repository no longer presents a generic `Custom` strategy as its default identity. The historical `Custom` folder name remains only inside the preserved verbatim range-folder source (`source.range_folder`) and in the legacy trainer manifest note; it is never an active strategy identity. The default identity is the population binding, or an explicit partial/unavailable state when no admissible calculated strategy exists. See `docs/hero-strategy-population-binding.md`.

## Lossless legacy source

A bare range-folder JSON import is stored under `source.range_folder` without semantic conversion. The original folder/range/position/hand/action tree therefore remains available after edits. User edits are stored only under `contexts`.

The persisted project source `user/artifacts/NLHE_100-200/custom.json.gz.b64` is exercised directly by CI: the archived `custom.json` is decompressed, imported, edited, exported and compared structurally with the original source tree.

## Context key

One editable context is selected by:

- `population_id`;
- `table_size`;
- Hero `position`;
- `effective_stack_bb`;
- preflop `spot` / family.

The v1 editor exposes the canonical high-level spots `UNOPENED`, `VS_LIMPERS`, `VS_RFI`, `VS_RFI_CALLERS`, `VS_3BET`, `VS_4BET` and `VS_JAM`. #98 resolves these selectors from the card-free, before-action `poker-preflop-context/v1` state. A future extension may add finer selectors without rewriting the preserved range-folder source.

## Population binding

`repository.defaults.population_id` declares the single population the repository answers for. It is not a label: it is a compatibility requirement.

- `repositoryPopulationId(repo)` exposes the bound population;
- `populationBound(repo, context)` returns `{population_id, repository_population_id, compatible}` and is `false` as soon as the context population differs (or when no population is bound);
- the editor refuses to present or edit the population strategy or its override for a context outside the bound population, so a foreign context can never silently inherit another population's identity.

The same rule is enforced on the strategy side by the resolver: every population binding (repository defaults, materialized calculated contexts, pack identity, trainer manifest, admission, retained reference, requested context) must match the active population or the result fails closed with no strategy identity. A repository is never relabelled to the active population, including when it carries a foreign `personal` context.

## Layers and precedence

Every context contains two independent layers:

1. `personal` — editable by the user; surfaced only as `PERSONAL_OVERRIDE`;
2. `calculated` — reserved for generated/optimized strategies with separate version/provenance metadata; this is the only layer that can yield the population strategy identity.

Resolution is per hand class: a personal definition wins when present; otherwise a calculated definition may be used. Removing a personal definition reveals the calculated definition instead of deleting it. Updating the calculated layer therefore cannot silently erase customizations.

Per-hand precedence governs which hand strategy is read. It does not change the strategy identity or source: when an admitted complete calculated strategy covers the context, the resolver still reports `source: POPULATION` even if personal overrides exist on top of it. With only personal hands it reports `PARTIAL` / `PERSONAL_OVERRIDE` and a null strategy identity, never the population strategy.

## Hand strategy

Each of the 169 classes is either **undefined** or has an explicit distribution. Undefined is not equivalent to fold.

A defined hand contains:

- action probabilities summing to exactly 1 within tolerance;
- optional sizing distributions per positive-probability action;
- optional notes.

Supported strategy actions are:

`FOLD`, `CHECK`, `LIMP`, `OVERLIMP`, `CALL`, `OPEN`, `ISO`, `3BET`, `4BET`, `SHOVE`, `CALL_SHOVE`.

Sizing uses total target contribution in BB (`target_total_bb`) and a conditional probability distribution for that action. This deliberately matches the #96 distinction between total raise target and incremental cost.

## Combo multiplicity

The repository works on 169 hand classes but preserves natural exact-combo multiplicity when needed:

- pocket pair: 6 combos;
- suited non-pair: 4 combos;
- offsuit non-pair: 12 combos.

The full grid therefore represents 1326 exact combinations.

## Persistence and import/export

The standalone editor persists locally in browser storage and exports the complete repository as JSON. Import accepts either:

- a legacy range-folder document, wrapped losslessly as the source of a new repository; or
- an existing `poker-hero-range-repository/v1` document, validated before use.

The editor never fills missing hands with fold and refuses to save a defined hand whose action frequencies do not sum to 100%.

## Storage migration

The repository persisted under `localStorage["poker.hero.range.repository.v1"]` is migrated by `site/hero-range-migration.js` (`poker-hero-range-migration/v1`). Migration is additive, idempotent and reversible:

- only a `migration` provenance block is added; contexts, layers and the verbatim range source are untouched;
- the exact pre-migration payload is kept under `poker.hero.range.repository.v1.previous` and can be restored byte-for-byte;
- a foreign population is reported as inherited (`inherited_population_ids`, `INHERITED_POPULATION_RETAINED`) and never relabelled (`relabeled_population_ids` is always empty), so a legacy `MIXED` repository is never relabelled to the active Zoom population;
- a bare legacy range-folder payload is imported losslessly first and flagged `MIGRATED_IMPORTED` / `LEGACY_SOURCE_IMPORTED`.

Personal hands are extracted as `poker-hero-personal-override/v1` with explicit contextual provenance and `source: PERSONAL_OVERRIDE`; they are never surfaced as the population strategy.

## Relationship to trainer/replayer

The repository is the durable Hero strategy representation; `site/hero-strategy-resolver.js` resolves a population-bound strategy identity from it, and `site/hero-compliance.js` / `site/hero-compliance-replayer.js` score decisions against the resolved population strategy. The Trainer and the product header read the same resolution through `identity()`; a personal override is shown separately and a retained legacy reference stays provenance only.

The existing trainer asset `site/assets/trainer/hero/custom_ranges_v1.json` remains a retained legacy reference (`RETAIN_REFERENCE`, `admissible: false`, `promotable: false`, `calculated: false`); it is not an admissible calculated strategy and its `Custom` folder name is source metadata, not a strategy identity. Neither this repository nor the resolver changes Model A/Model B promotion state, and neither activates the inactive #358 candidate. See `docs/hero-strategy-population-binding.md` for the resolver states, precedence, fail-close and #201/#305 admission vocabulary.

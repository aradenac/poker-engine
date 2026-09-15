# Hero range repository v1

Issue #97 introduces `poker-hero-range-repository/v1` for user-owned preflop strategy ranges.

## Scope

The repository is deliberately separate from opponent population ranges and from Model A recommendations. A personal Hero range is a user plan, not a claim of optimality. A future calculated range may coexist with the personal layer without overwriting it.

The browser editor is `site/hero-ranges.html`, linked from the main application. Its contract implementation is `site/hero-ranges.js`.

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

## Layers and precedence

Every context contains two independent layers:

1. `personal` — editable by the user;
2. `calculated` — reserved for generated/optimized strategies with separate version/provenance metadata.

Resolution is per hand class: a personal definition wins when present; otherwise a calculated definition may be used. Removing a personal definition reveals the calculated definition instead of deleting it. Updating the calculated layer therefore cannot silently erase customizations.

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

## Relationship to trainer/replayer

The existing trainer asset `site/assets/trainer/hero/custom_ranges_v1.json` remains the current normalized deal source until a later integration explicitly migrates it. #97 creates and edits the durable Hero strategy representation; #98 owns replayer compliance against a selected repository/version. Neither ticket changes Model A/Model B promotion state by itself.

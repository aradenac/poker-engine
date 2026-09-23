# Spot Lab view and manual-tool sub-views

This document is the normative reference for the **Spot Lab** view introduced
by issue #394 (task `T4`). It fixes how the formerly stacked manual tools are
grouped into sub-views and states the floating-equity visibility rule pinned by
`tests/trainer/test_spotlab_subviews_contract.py`.

It is an **application/UX shell contract only**: it does not fit Model A, tune
Model B, select a candidate, or change any equity computation.

## 1. The view

Spot Lab is one of the mode cards on the Home screen and one of the
`state.appView` values (`"spotlab"`). It is reached from Home without importing
any hand history, and it keeps its own state (`state.hero`, `state.board`,
`state.opponents`, `state.mainEquity`) independent of the Review import.

The shell is a fixed-height view (`data-view-shell="spotlab"`). Its body holds a
tab strip (`role="tablist"`) and the manual-tool panes. Every pane is a
`[data-app-subview-panel]` and is the **same DOM node** that the historical
`Equity Lab` used; the tools were moved, never duplicated.

## 2. Sub-view mapping

| Tab (`data-app-subview`) | Pane (`data-app-subview-panel`) | Manual tool |
| --- | --- | --- |
| `spotlab-situation` — Situation & adversaires | `opponentsSection` | opponents list, `methodSelect`, `trialsSelect` |
| `spotlab-board` — Main & board | `cardsSection` | Hero hand + board picker |
| `spotlab-range` — Range adverse | `rangeDisplaySection` | 169 matrix + range-edition toggle |
| `spotlab-equity` — Résultat d’équité | `equitySection` | manual equity result |

Advanced sources/models remain the **advanced-only** surface: `#rangesSection`
stays `hidden`/`aria-hidden` with `data-legacy-import-surface="advanced-only"`
and is intentionally **not** a `[data-app-subview-panel]`, so no tab can ever
unveil it in Spot Lab. The expert entry point stays
`site/manual-import.html` (`#advancedManualImportLink`).

## 3. Single-node / unique-id rule

Moving the tools into Spot Lab must not duplicate them:

- `opponentsSection`, `cardsSection`, `rangeDisplaySection`, `equitySection`
  each appear **exactly once** in the document and are the only node with that
  id;
- `methodSelect` and `trialsSelect` stay inside `opponentsSection`;
- the tools live inside the Spot Lab shell and never inside the Review shell.

`tests/trainer/test_spotlab_subviews_contract.py` asserts the id uniqueness and
the shell ownership, and `tests/trainer/smoke_trainer.py` proves at runtime that
the four equity components exist.

## 4. Sub-view isolation

`activateAppSubview(name)` toggles panes **only inside the owning view shell**
(`closest("[data-view-shell]")`), not across the whole document. Activating a
Spot Lab tab therefore never hides the Review, Training or Replayer panes; each
view keeps its own tab selection and the next mounted view is never left blank.

## 5. Floating-equity visibility rule

The floating equity widget (`#floatingEquity`) is a **context control**, not a
global overlay. It belongs only to the surfaces that actually produce a Hero
equity:

- the Spot Lab manual calculator (`state.mainEquity`), and
- the Replayer seat equities (`state.seatEquities`).

The rule, implemented in the `#floatingEquity` CSS block, is:

    body[data-app-view="spotlab"] #floatingEquity,
    body[data-app-view="replayer"] #floatingEquity{display:block}

everywhere else (`home`, `review`, `strategy`, `training`) the widget is
`display:none`, so it never overlaps unrelated content. When shown it stays
anchored top-right and starts **collapsed** (36 px, the `EQ` toggle) until the
user expands it, so it only covers the pane on explicit request.

## 6. Verification

- `tests/trainer/test_spotlab_subviews_contract.py` — static contract for this
  document, the tab/pane mapping, the unique ids and the floating-equity rule.
- `tests/trainer/test_auxiliary_scale_surfaces_contract.py`,
  `tests/trainer/test_range_display_docs_contract.py`,
  `tests/trainer/test_advanced_import_central_ui_contract.py` — the manual
  equity/matrix-range and advanced-source/model contracts stay green.
- `tests/trainer/smoke_trainer.py` — browser shell/product-architecture smoke.

No contradiction with `docs/shared-components.md` or
`docs/opponent-range-display-contract.md`.

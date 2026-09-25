# Spot Lab view and manual-tool sub-views

This document is the normative reference for the **Spot Lab** view introduced
by issue #394 (task `T4`). It fixes how the formerly stacked manual tools are
grouped into sub-views and states the floating-equity visibility rule pinned by
`tests/trainer/test_spotlab_subviews_contract.py`.

It is an **application/UX shell contract only**: it does not fit Model A, tune
Model B, select a candidate, or change any equity computation.

The general desktop shell rules this view builds on (`100dvh` / no global
scroll, the reusable sub-view / pagination pattern, the allowed overflow zones,
the navigation / deep-link contract and the no-recalculation-on-a-view-change
rule) are owned by `docs/ux-desktop-view-shell.md`; this document only adds the
Spot Lab mapping and the floating-equity rule. That document also owns the fact
that the sub-view pattern is **global**: only the `100dvh` / no-global-scroll
rule is desktop-only, so the Spot Lab tabs also drive the `<901px` rendering
(§6 below).

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

## 6. Rendu <901px

The sub-view pattern is **global**, not desktop-only. Below `901px` the Spot Lab
shell is tabbed exactly like above it: one pane visible at a time, selected by
its own `role="tab"` thumb, while `html`/`body` keep their normal document flow
(no `100dvh`, no global `overflow`). Only the desktop shell rules
(`@media(min-width:901px)`) are desktop-only.

The four panes behave the same at every width. `opponentsSection`
(`spotlab-situation`) is the landing pane, and `cardsSection`
(`spotlab-board`), `rangeDisplaySection` (`spotlab-range`) and `equitySection`
(`spotlab-equity`) are `hidden` until their tab is selected — it is the same
`activateAppSubview(name)` call, with no width guard, so a Spot Lab pane can
never be unreachable below `901px`. The global
`.app-subview-panel[hidden]{display:none!important}` rule is what keeps them
hidden there, since `.panel` declares its own `display`.

The complete mobile inventory of every view (panes hidden by default with their
owning tab) and the explicit "no pane without a tab, no unreachable pane"
verdict are versioned in `docs/ux-desktop-view-shell.md` §2.1; the static guard
lives in `tests/trainer/test_desktop_accessibility_contract.py`.

## 7. Verification

- `tests/trainer/test_spotlab_subviews_contract.py` — static contract for this
  document, the tab/pane mapping, the unique ids and the floating-equity rule.
- `tests/trainer/test_auxiliary_scale_surfaces_contract.py`,
  `tests/trainer/test_range_display_docs_contract.py`,
  `tests/trainer/test_advanced_import_central_ui_contract.py` — the manual
  equity/matrix-range and advanced-source/model contracts stay green.
- `tests/trainer/smoke_trainer.py` — browser shell/product-architecture smoke.

No contradiction with `docs/shared-components.md` or
`docs/opponent-range-display-contract.md`.

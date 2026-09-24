# UX desktop view shell contract

This document is the normative reference for the **desktop application shell**
introduced by issue #394. It fixes the rules a contributor has to respect when
touching a view: the `100dvh` / no-global-scroll rule, the reusable
sub-view / pagination pattern, the mode → view → sub-view mapping, the allowed
overflow policies, the navigation / deep-link contract, the
no-recalculation-on-a-view-change rule and the browser-smoke orchestration
shape.

It is an **application/UX shell contract only**: it does not fit Model A, tune
Model B, select a candidate, or change any equity computation. It is the
shell-level companion of `docs/spotlab-view.md` (Spot Lab mapping and the
floating-equity rule) and stays consistent with `docs/shared-components.md` and
`docs/opponent-range-display-contract.md`.

The versioned identifier is

    poker-ux-desktop-view-shell/v1

and the exported constants are

    APP_VIEWS                 (site/index.html, page script)
    APP_HASH_SUBVIEWS         (site/index.html, page script)
    APP_ALLOWED_SCROLL_ZONES  (site/index.html, page script)

UI labels are French because the static application is French-facing. The
desktop scope is `@media(min-width:901px)`; the `<901px` rendering keeps its
historical document flow and is explicitly out of this contract.

## 1. Rule: `100dvh`, no global scroll

In the desktop scope the **document never scrolls**. The rule is expressed once
by the shell block of `site/index.html`:

- `html,body{height:100dvh;max-height:100dvh;overflow:hidden}` — the document is
  pinned to the viewport and clipped;
- `body{display:flex;flex-direction:column}` — so a view shell can own the
  viewport height;
- each application view is a fixed-height shell,
  `[data-view-shell]{display:flex;flex-direction:column;flex:1 1 auto;width:100%;
  height:100dvh;max-height:100dvh;min-height:0;overflow:hidden}` plus
  `[data-view-shell].mode-hidden{display:none}` so exactly one shell is mounted;
- a shell is a fixed header plus a constrained body: `.app-view-head{flex:0 0
  auto}` and `.app-view-body{flex:1 1 auto;overflow:hidden}`.

The excess content therefore never travels through a view scroll. It travels
through the reusable **sub-view** pattern (tabs + panes, §2) or through a
bounded **allow-listed** zone (§3). No view may reintroduce a global scroll:
`100dvh` / `overflow` on `html`/`body` exists only inside the
`@media(min-width:901px)` block, and the narrow-viewport scroll boxes stay
declared inside `max-width` blocks.

## 2. Mode → view → sub-view mapping

| Mode (Accueil) | `state.appView` | Shell (`data-view-shell`) | Sub-views (`data-app-subview`) |
| --- | --- | --- | --- |
| Accueil | `home` | `home` | — (aucune : écran des modes de travail) |
| Review | `review` | `review` | `pilotage`, `import`, `inbox` |
| Spot Lab | `spotlab` | `spotlab` | `spotlab-situation`, `spotlab-board`, `spotlab-range`, `spotlab-equity` |
| Training | `training` | `training` | `trainer-coaching`, `trainer-session`, `trainer-profiles`, `trainer-test` |
| Replayer | `replayer` | `replayer` | `replayer-decision`, `replayer-ranges`, `replayer-details` |
| Strategy Hero | `strategy` | `strategy` | — (aucune : éditeur dédié site/hero-ranges.html) |

Each sub-view is a `[role="tab"]` thumb carrying `data-app-subview="<name>"`
plus a `[data-app-subview-panel="<name>"]` pane; the inactive panes are
`hidden`. Activation is scoped to the owning shell: `appSubviewScopeFor(node)`
returns `node.closest("[data-view-shell]")`, and `activateAppSubview(name)`
toggles only the panels of that scope, so a tab in one view can never blank a
neighbouring view.

The Review shell exposes its excess as three sibling panes of equal standing —
Pilotage (`#reviewDashboard`), Import (`#historiesSection`) and Inbox
(`#handSelectionSection`) — each a direct child of `.app-view-body` that owns the
whole bounded body height on its own. A pane therefore never has to share the
`100dvh` shell with another pane: the import surface (label
`label[for="hhFileInput"]`, `#hhFileInput`, `#hhWatchBtn`, and the
`Options d'import et outils avancés` details with `#hhImportMode`,
`#hhClearBtn`, `#hhWatchStopBtn`, `#hhAnalyzeAllBtn`, `#hhBenchmarkExportBtn`)
stays **visible and hit-testable** at 1500x1000 and 1366x768, including while the
advanced details is open. The dashboard is the landing pane
(`aria-selected="true"`); the import and inbox
panes are `hidden` until their tab is selected — a real click on
`#reviewImportTab`, or a deep link routed through `APP_HASH_SUBVIEWS`
(`#historiesSection` / `#reviewInboxSummary` → `import`, `#reviewDashboard` →
`pilotage`, `#handSelectionSection` → `inbox`). The dashboard CTA
`#reviewDashboardImportBtn` selects the Import pane *before* calling
`hhFileInput.click()`, so the picker is never opened from an input sitting inside
a `hidden` pane. Switching panes only toggles `hidden`: no pane re-renders and no
computation is scheduled (§5).

The Replayer is a fixed three-column grid (`#replayerSection`,
`grid-template-columns:minmax(240px,320px) minmax(0,1fr) minmax(240px,340px)`)
inside the single `replayer` shell. The replay itself (`#hhVisualReplay` — colonne
contrôles/timeline/actions + colonne scène de table, peinte par
`renderVisualReplay()`, `display:contents` at `>= 901px`) stays mounted in the
grid and is deliberately **not** a tab pane: selecting a contextual tab must
never blank the timeline or the table.

The third column (`#replayerContextPanel`) is the contextual **tabbed panel**
and exposes exactly three sub-views, rendered once by the runtime:

- `replayer-decision` (panneau `#replayerDecisionPanel`) — décision/verdict de
  l'étape affichée : `replayActionBannerHtml` + `safeActionAnalysisHtml`, les
  helpers déjà utilisés par le feed de street ;
- `replayer-ranges` (panneau `#replayerRangesPanel`) — accès aux ranges
  population/adverse de chaque adversaire : les déclencheurs
  `data-population-player` produits par `populationRangeButtonHtml`, l'autorité
  de rendu unique partagée avec les sièges de la table, ouvrent le dialogue de
  range adverse existant ;
- `replayer-details` (panneau `#hhReplayDetail`) — déroulé de la main street par
  street via `renderHistoryReplay()`.

The three panes are painted in the same repaint as the replay columns and only
one is visible; `activateAppSubview` merely toggles `hidden`, so switching a tab
ne re-renders a pane, duplicates no rendering and no DOM id, and schedules no
computation (§5). The tab row is a real `role="tablist"`/`role="tab"` widget:
roving `tabindex`, `aria-selected`, `aria-controls`, visible focus, `←`/`→` to
move and `Entrée`/`Espace` to activate. Deep links (`appViewForHashTarget`, then
`activateAppSubviewForTarget`) open the Replayer shell and select the owning
pane (`APP_HASH_SUBVIEWS` maps `#replayerSection` / `#replayerPage` to
`replayer-decision`) before focusing, since the shell never scrolls.

A list that cannot fit the constrained shell is **paginated, not scrolled**: the
Review inbox is painted one bounded page at a time by `renderReviewInboxPage`,
which shrinks its page size until
`hhHandsEl.scrollHeight <= hhHandsEl.clientHeight + 1`, with `#hhListPager`
(`.app-list-pager`, `#hhPagePrev` / `#hhPageNext`) driving the pages. No row is
ever lost behind `overflow:hidden`.

## 3. Allowed overflow policies

In the desktop scope `overflow:auto|scroll` is forbidden unless the selector is
an entry of `APP_ALLOWED_SCROLL_ZONES`. The list is intentionally short, bounded
and justified; every entry is a class opted into by the markup, never a bare
element selector and never a view shell:

| Selector (`APP_ALLOWED_SCROLL_ZONES`) | Scope | Kind |
| --- | --- | --- |
| `.app-scroll-zone` | desktop | bounded list / panel (Trainer rail tabs, Trainer test log, Spot Lab opponents, Replayer controls/timeline column and contextual panes Décision / Ranges / Détails) |
| `.app-canvas-pane` | desktop | bounded canvas (Trainer table, Replayer table column) |
| `.app-scroll-x` | desktop | bounded table, horizontal overflow only |
| `.street-timeline-list` | desktop | bounded list (one street of events) |
| `.population-modal` | dialogue | dialog (opponent-range modal) |
| `.population-modal-grid-wrap` | dialogue | dialog (13×13 grid) |
| `.population-combo-list` | dialogue | dialog (combo list) |
| `.action-verdict-detail-modal` | dialogue | dialog (action verdict) |

The `desktop` zones are bounded by the shell (`flex` + `min-height:0`) and are
never a substitute for a view shell; the `dialogue` zones live in an
`aria-modal` dialog outside the shell. `.matrixwrap{overflow:hidden}` keeps the
169 matrix bounded by its pane, and no view markup may carry an inline scroll
style. `tests/trainer/test_desktop_accessibility_contract.py` asserts that the
desktop-scope `overflow:auto|scroll` selectors are exactly this list.

## 4. Navigation and deep-link contract

`state.appView` is the single source of truth for the mounted view and covers
every mode, Home included:

    const APP_VIEWS=["home","review","replayer","spotlab","training","strategy"];

- `updateAppView()` mounts exactly one shell: it toggles `mode-hidden` /
  `aria-hidden` on every `[data-view-shell]`, mirrors `document.body.dataset.appView`
  and hides the global `#quickNav` for the immersive `replayer` / `training`
  views.
- `setAppView(view,{scrollTop})` / `openAppView(view)` change the mode;
  `openAppView("training")` routes through the Trainer bootstrap
  (`trainerOpenBtn.click()`), and `openAppView("replayer")` is a no-op without
  `state.selectedHand`. `goHome()` returns to the Accueil screen.
- `#quickNav` and the Home mode cards (`[data-app-view]`) route through
  `appView` instead of scrolling. The Strategy mode is the standalone editor
  page (`./hero-ranges.html`), so its real link is preserved.
- Deep links: `appViewForHashTarget(id)` maps an element id to its owning view,
  `routeFromHash()` reads `window.location.hash`, `focusAppSection(id)` opens the
  owning view, and `window.addEventListener("hashchange", …)` re-routes.
  In-document `a[href^="#"]` links are intercepted onto the same path.
- A deep link that targets a pane living inside a sub-view must select the owning
  tab first: `APP_HASH_SUBVIEWS` + `activateAppSubviewForTarget(id)`, because the
  shell never scrolls to reveal the pane.
- The Replayer anchors are mapped to their owning contextual pane:
  `APP_HASH_SUBVIEWS` maps `#replayerSection` and `#replayerPage` to
  `replayer-decision`, so `focusAppSection(id)` selects that tab *before*
  focusing the target — the deep link never scrolls the shell.
- The Review anchors are mapped to their owning pane the same way:
  `APP_HASH_SUBVIEWS` maps `#reviewDashboard` to `pilotage`,
  `#historiesSection` / `#reviewInboxSummary` to `import` and
  `#handSelectionSection` / `#reviewInboxNotice` to `inbox`, so the historical
  `#historiesSection` anchor (the `#quickNav` Review entry and the Home banner
  link) reveals the import pane instead of scrolling a view that never scrolls.
- `[data-home-back]` controls (`.app-view-back`) return to Home through
  `goHome()`.
- `state.appView` is persisted through the prefs whitelist and restored on load;
  `training` and `replayer` are not restored blindly (the Trainer needs its
  runtime bootstrap, the Replayer needs `state.selectedHand`).

## 5. No recalculation on a view change

A view change is a **pure DOM mount swap**. It must reuse everything already
computed and never reschedule an engine computation:

- `updateAppView()` contains no `scheduleAutoCalculate`, no
  `scheduleBackgroundReviewScoring` and no `startSeatEquityCalculation`; it only
  toggles shell visibility, mirrors the compute holds and renders the
  already-selected hand.
- Returning to Review (`returnToHandsPage()`) reuses the scores already produced
  (`state.reviewScores`, `state.actionEquityCache`, seat equities) instead of
  re-scheduling the background review scoring, and selects the Inbox pane
  without scrolling the document.
- Compute pressure is handled by the shared admission control, not by recomputing
  per view: `window.pokerComputeScheduler.hold('replayer',mount==='replayer')` and
  `hold('training',mount==='training')` pause the background lane while an
  immersive view is mounted and release it when the view is left.
- The former on-scroll trigger stays removed (#394 T3): no `scroll` /
  `scrollend` listener, no `onscroll` handler and no `IntersectionObserver` or
  `visibilitychange` callback in `site/**` may re-plan
  `scheduleBackgroundReviewScoring` (nor `scheduleAutoCalculate`). The Review
  list is therefore bounded by its pagination alone — `renderReviewInboxPage`
  plus `#hhListPager` — so scrolling the inbox never restarts a computation;
  the corpus sweep remains the explicit action `#hhAnalyzeAllBtn` →
  `state.reviewAnalyzeAll`, at every width, including the `<901px` rendering
  which stays outside this document's desktop scope.
- Selecting a sub-view tab is likewise a pure visibility toggle:
  `activateAppSubview(name)` only sets `hidden` / `aria-selected` / `tabindex`
  inside the owning shell, so it contains no `scheduleAutoCalculate`, no
  `scheduleBackgroundReviewScoring`, no `startSeatEquityCalculation` and no
  re-render of a pane. The Replayer panes are painted by the same
  `renderVisualReplay()` / `renderHistoryReplay()` passes that already run for
  the displayed step and hand.
- Only an actual input change (hand, board, opponents, trainer mode, trials, …)
  calls `scheduleAutoCalculate()`.

## 6. Browser-smoke orchestration shape

The desktop shell is proved by browser smokes driven through a **single frozen
entry point**:

- `.github/workflows/trainer-smoke.yml` serves `site/` and runs exactly
  `python3 tests/trainer/smoke_trainer.py` for the interactive view; the workflow
  stays frozen and gains no per-smoke step;
- `tests/trainer/smoke_trainer.py` owns the orchestration: standalone
  numeric/pattern smokes are registered in `DRIVER_SMOKES` and executed by
  `run_driver_smokes()` from the `__main__` entry point
  (`subprocess.run([sys.executable, str(script)], check=True)`).
  `tests/trainer/test_smoke_orchestration_contract.py` guards that shape;
- the #394 desktop modes smoke (`tests/trainer/smoke_modes_desktop.py`) is one of
  those registered driver smokes, so it runs **by default** through the frozen
  entry point: every `python3 tests/trainer/smoke_trainer.py` invocation, CI
  included, drives the six modes at 1500x1000 and 1366x768 and fails (never
  skips) when Playwright is unavailable. It adds no workflow step — the modes
  smoke is exercised through the same frozen entry point as the numeric smokes,
  not as an opt-in measurement;
- the import surface of Review is reached through the real UI by both smokes, and
  measured at both reference viewports, never deduced. `smoke_trainer.py` enters
  Review, asserts that the Pilotage pane is the landing pane, opens the Import
  pane with a real click on `#reviewImportTab`, and only then clicks the
  advanced details summary. `smoke_modes_desktop.py` additionally resolves every
  import target (`#reviewImportTab`, the `Importer mes mains` label, the details
  summary, `#hhWatchBtn`, and `#hhBenchmarkExportBtn` once the details is open)
  with `document.elementFromPoint` at the centre of its box, asserts
  `visible` / `inViewport` / `inShell` / `hit`, and then performs the real mouse
  clicks (the label really opens the file chooser). A clipped target fails with
  its measured box instead of passing on a JS shortcut;
- in a sandbox without the Playwright runtime the frozen smokes fail explicitly,
  with the exact command and output below, and never write a `PASS`. The frozen
  CI job `browser-smoke` of `.github/workflows/trainer-smoke.yml` stays the
  authority for the smoke itself.

```text
$ python3 tests/trainer/smoke_modes_desktop.py
smoke_modes_desktop: Playwright is unavailable (ModuleNotFoundError("No module named 'playwright'")). Install the locked dependencies (requirements.lock.txt) and the pinned browser runtime (python3 tools/repro_ci_browser.py install) before running this smoke.
EXIT=1
$ python3 tests/trainer/smoke_trainer.py
Traceback (most recent call last):
  File "tests/trainer/smoke_trainer.py", line 10, in <module>
    from playwright.async_api import async_playwright
ModuleNotFoundError: No module named 'playwright'
EXIT=1
```

- the shell's own browser measurement is **opt-in** inside
  `tests/trainer/test_desktop_accessibility_contract.py` (`--browser` or
  `DESKTOP_SHELL_BROWSER_CHECK=1`): it serves `site/index.html` locally and
  asserts `document.scrollingElement.scrollHeight <= clientHeight` at
  1500x1000 and 1366x768 for `home`, `review`, `spotlab`, `training` and
  `replayer`. It is skipped when Playwright is unavailable, so the frozen static
  CI job stays hermetic.

## 7. Non-contradiction

- `docs/shared-components.md`: this contract adds no bundler, no component
  extraction and no change to the Cloudflare static layout; the browser keeps
  loading the same `site/*.js` bytes.
- `docs/opponent-range-display-contract.md`: the display contract keeps owning
  the opponent-range semantics (notions, normalization, `posteriorState`); the
  shell only fixes where a pane is mounted and guarantees no global scroll. The
  Replayer range modal stays a declared `dialogue` zone.
- `docs/spotlab-view.md`: Spot Lab's sub-view mapping and the floating-equity
  visibility rule stay owned by that document; this document owns the general
  shell rules they build on.

## 8. Verification

- `tests/trainer/test_desktop_accessibility_contract.py` — the static shell
  contract, the `APP_ALLOWED_SCROLL_ZONES` allow-list and the optional browser
  measurement.
- `tests/trainer/test_product_architecture_contract.py` — this document: the
  `100dvh` / no-scroll rule, the mode → view → sub-view mapping, the overflow
  policies, the navigation / deep-link contract, the no-recalculation rule and
  the browser-smoke orchestration shape.
- `tests/trainer/test_spotlab_subviews_contract.py`,
  `tests/trainer/test_trainer_static.py` — the Spot Lab and Training shells.
- `tests/trainer/test_hh_import_ux_contract.py` — the Review/Replayer return is a
  pure view change.
- `tests/trainer/smoke_trainer.py` / `tests/trainer/smoke_modes_desktop.py` — the
  frozen entry point and the per-viewport measurement; both reach the Review
  import pane through a real click on `#reviewImportTab`, and the modes smoke
  measures that the whole import surface (advanced options included) is
  hit-testable at 1500x1000 and 1366x768.
- `tests/trainer/test_appview_no_recompute_contract.py` — the no-recalculation
  guard itself: statically, that no `scroll` / `scrollend` / `onscroll` /
  `IntersectionObserver` / `visibilitychange` path re-schedules a computation
  and that the list stays bounded by `renderReviewInboxPage` + `#hhListPager`;
  at runtime (`node`), that cycling every view and every sub-view tab against
  the real `ComputeScheduler` schedules nothing and creates no worker.
- `tests/trainer/test_smoke_orchestration_contract.py` — the single-entrypoint
  browser-smoke shape.

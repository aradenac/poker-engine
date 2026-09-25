#!/usr/bin/env python3
"""String contract for the #391 / #394 smoke orchestration.

The numeric browser smokes of #391 and the desktop modes smoke of #394 must be
driven by ``tests/trainer/smoke_trainer.py`` (via ``run_driver_smokes``) and
must NOT come back as dedicated steps in
``.github/workflows/trainer-smoke.yml``. The frozen workflow runs every
``tests/trainer/test_*.py`` in its static-contract job, so this module is the
guard that keeps the single-entrypoint shape:

- no step (nor any other reference) to ``smoke_opponent_range_numeric.py``,
  ``smoke_equity_scale_invariance.py`` or ``smoke_modes_desktop.py`` may exist in
  the workflow;
- ``smoke_trainer.py`` must list the three scripts in ``DRIVER_SMOKES`` and
  actually execute them from its ``__main__`` entry point.

It also owns the #394 T6 URL contract of the desktop journey: the embedded
Stratégie Hero shell is joined by its real entry point, the ``#strategyPage``
deep link — the anchor the ``#quickNav`` Strategy entry itself carries, since
that entry is an in-app navigation and not a link to the standalone editor — and
the standalone editor is measured through its own deep link (the Home mode card's
real ``./hero-ranges.html`` link) behind a query-tolerant ``wait_for_url`` glob —
the repo convention ``**/hero-ranges.html?**``, because an anchored Playwright
glob without it can never match the URL the editor rewrites with its rendered
context.

It is a representation/orchestration contract only: no model/fit, no equity
semantics and no immutable repro evidence is touched.

Since #394 R2 (``backlog-cg8``) it also keeps the failure *record* of the frozen
job alive: ``docs/desktop-modes-fit-evidence.md`` § 8 has to consign the real CI
failure of the Accueil « Review » click — intercepted by ``#quickNavToggle`` at
1366x768, Playwright's default 30 s actionability timeout — and the R1 fix
(``site/index.html`` plus the static separation guard), while the smoke keeps
that click a real one (no forced JS click, no retry, no skip).

Since #394 T1 (``backlog-o53``) it also pins the *panel* reachability the human
review named as never measured at 1366x768 — Spot Lab's ``Range adverse`` pane,
the three Replayer columns, the Replayer right-panel tabs and the four Training
rail tabs — on the same instrument as the Review import surface
(``elementFromPoint`` + ``click(trial=True)``), together with the report bucket
that carries those measurements (``panel_surfaces``) and the per-viewport
inventory printed for a green and a red run alike. The block is strictly
additive: a selector, its ``_assert_panel_surface_hit_testable`` call, the bucket
or the inventory that disappears fails this guard.

Since #394 T2 (``backlog-eit``) the same guard also links those hit-test targets
to the *served bytes*: the selector tuples are read back from the smoke as
literal constants (``ast``) and each id/class is resolved against
``site/index.html`` itself — inline JS templates included, so the Replayer
columns ``.replayer-col-left`` / ``.replayer-col-center``, painted by
``hhVisualReplay.innerHTML``, count as served nodes while a CSS-only occurrence
does not. The measurement cannot decay into a bare boolean either: the fields
the import/panel assertion helpers read off an entry must stay exposed by
``SURFACE_HIT_TEST_JS`` (``present``, ``visible``, ``inViewport``, ``inShell``,
``hit``, ``reachable``, ``point``, ``viewport``, ``box``, ``at``, plus the
``atTag`` / ``shellBox`` fields the verdict sentence prints), and both reference
viewports (``1500x1000``, ``1366x768``) stay in ``VIEWPORTS`` with every panel
surface measured inside the per-viewport ``run_viewport`` journey.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = (ROOT / ".github/workflows/trainer-smoke.yml").read_text(encoding="utf-8")
SMOKE_TRAINER = (ROOT / "tests/trainer/smoke_trainer.py").read_text(encoding="utf-8")
MODES_SMOKE = (ROOT / "tests/trainer/smoke_modes_desktop.py").read_text(encoding="utf-8")
# #394 T2 — the served bytes of the desktop shell. The desktop hit-tests only
# ever run in the frozen browser job, so the selectors they reach for are proved
# to exist in the bytes the app serves *here*: `site/index.html`, inline JS
# templates included (the served file carries them verbatim).
SERVED_INDEX = (ROOT / "site/index.html").read_text(encoding="utf-8")
# The only other `wait_for_url` call site of the repo (audited below): it already
# uses the query-tolerant glob the desktop journey now shares.
HERO_COMPLIANCE_SMOKE = (
    ROOT / "tests/hero_ranges/smoke_hero_compliance_browser.py"
).read_text(encoding="utf-8")
DOC = (ROOT / "docs/opponent-range-display-contract.md").read_text(encoding="utf-8")
# #394 T7: the desktop modes fit evidence. The frozen browser job can only run
# in CI, so this versioned artefact is what a reviewer reads; it must stay
# present and keep carrying the measured contract.
FIT_EVIDENCE = ROOT / "docs/desktop-modes-fit-evidence.md"

# The browser smokes that smoke_trainer.py must orchestrate: the two numeric
# smokes of #391 and the desktop modes smoke / overflow audit of #394.
ORCHESTRATED_SMOKES = (
    "tests/trainer/smoke_opponent_range_numeric.py",
    "tests/trainer/smoke_equity_scale_invariance.py",
    "tests/trainer/smoke_modes_desktop.py",
)

ORCHESTRATED_SMOKE_NAMES = tuple(Path(script).name for script in ORCHESTRATED_SMOKES)


def flat(text: str) -> str:
    """Collapse line wrapping so phrase assertions are stable."""
    return " ".join(text.split())


def literal_assignment(source: str, name: str):
    """Literal value of the top-level ``NAME = <literal>`` of ``source``.

    The selector tuples, `VIEWPORTS` and `IMPORT_ADVANCED_SELECTOR` are the
    contract *data* of the smoke. Reading them back through `ast` proves they are
    still literal constants this guard can resolve against the served bytes,
    instead of a reassigned or computed name that would quietly escape it.
    """
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id == name:
                return ast.literal_eval(node.value)
    raise AssertionError(f"assignation littérale introuvable: {name}")


# The class tokens actually carried by a `class="…"` attribute of the served
# bytes (inline JS templates included). A class selector satisfied here renders a
# real node; a class that only appears in a CSS rule does not contribute, so the
# guard cannot pass on styling alone.
SERVED_CLASS_ATTRIBUTE_TOKENS = frozenset(
    token
    for classes in re.findall(r"class\s*=\s*[\"'`]([^\"'`]*)[\"'`]", SERVED_INDEX)
    for token in classes.split()
)


def assert_served_selector(selector: str) -> str:
    """Assert one smoke selector resolves to the bytes of `site/index.html`.

    `#id` needs its real `id="…"` attribute, `label[for="…"]` its real
    `for="…"`, and `.class` / `.class > tag` needs the class token of a served
    `class="…"` attribute — a class that only appears in a CSS rule is *not*
    enough, so a template-rendered node (`.replayer-col-left` /
    `.replayer-col-center`, painted by `hhVisualReplay.innerHTML`) proves that a
    real node is created. Returns the proof token for the failing caller.
    """
    id_match = re.fullmatch(r"#([A-Za-z][\w-]*)", selector)
    if id_match:
        token = f'id="{id_match.group(1)}"'
        assert token in SERVED_INDEX, f"{selector}: {token} absent de site/index.html"
        return token
    for_match = re.fullmatch(r'label\[for="([^"]+)"\]', selector)
    if for_match:
        token = f'for="{for_match.group(1)}"'
        assert token in SERVED_INDEX, f"{selector}: {token} absent de site/index.html"
        return token
    class_match = re.fullmatch(
        r"\.([A-Za-z][\w-]*)(?:\s*>\s*([A-Za-z][\w-]*))?", selector
    )
    if class_match:
        class_name, child_tag = class_match.groups()
        assert class_name in SERVED_CLASS_ATTRIBUTE_TOKENS, (
            f"{selector}: classe absente des attributs class= servis par site/index.html"
        )
        if child_tag:
            assert f"<{child_tag}" in SERVED_INDEX, (
                f"{selector}: élément <{child_tag}> absent de site/index.html"
            )
        return class_name
    raise AssertionError(f"sélecteur non couvert par le garde statique: {selector}")


def main() -> None:
    # The workflow stays frozen: neither script is referenced, as a `run:` step
    # or anywhere else. Reintroducing a step that calls one of them fails here.
    for script in ORCHESTRATED_SMOKES:
        assert script not in WORKFLOW, script
    for script_name in ORCHESTRATED_SMOKE_NAMES:
        assert script_name not in WORKFLOW, script_name

    # The single frozen entrypoint that drives them is still exercised.
    assert "run: python3 tests/trainer/smoke_trainer.py" in WORKFLOW

    # smoke_trainer.py owns the orchestration: every script is registered as a
    # driver smoke...
    driver_block = SMOKE_TRAINER.split("DRIVER_SMOKES = (", 1)[1].split("\n)", 1)[0]
    for script_name in ORCHESTRATED_SMOKE_NAMES:
        assert script_name in driver_block, script_name
    assert "def run_driver_smokes() -> None:" in SMOKE_TRAINER
    assert "subprocess.run([sys.executable, str(script)], check=True)" in SMOKE_TRAINER

    # ...and they are actually launched from the script entry point, so a
    # registered-but-never-run driver smoke fails here too.
    main_block = SMOKE_TRAINER.split('if __name__ == "__main__":', 1)[1]
    assert "run_driver_smokes()" in main_block

    # The display-contract verification section documents that orchestration.
    doc_flat = flat(DOC)
    assert "tests/trainer/smoke_trainer.py" in doc_flat
    assert "orchestrated by" in doc_flat
    for script in ORCHESTRATED_SMOKES:
        assert script in doc_flat, script

    # The #394 desktop modes smoke is not a stub: it measures both reference
    # viewports for the six modes, fails explicitly on an overflow with the
    # measured values, drives the transition journeys from the real UI and fails
    # (instead of skipping) when Playwright is unavailable.
    assert 'MODES = ("home", "spotlab", "review", "replayer", "training", "strategy")' in MODES_SMOKE
    assert "VIEWPORTS = ((1500, 1000), (1366, 768))" in MODES_SMOKE
    assert 'result["scrollHeight"] <= result["clientHeight"]' in MODES_SMOKE
    assert "mode={mode} viewport={width}x{height}" in MODES_SMOKE
    assert "smoke_modes_desktop: Playwright is unavailable" in MODES_SMOKE

    # #394 (backlog-31r) — the "no global scroll" measurement must be auditable
    # from the repository: the smoke serialises the audit it already built, and
    # the evidence document has to name the option that regenerates it. This
    # block is additive and asserts the real call sites, so the report cannot
    # decay into a documented-but-absent flag.
    assert '"--report"' in MODES_SMOKE
    assert 'REPORT_ENV_VAR = "SMOKE_MODES_DESKTOP_REPORT"' in MODES_SMOKE
    assert 'DEFAULT_REPORT_PATH = ROOT / "artifacts/desktop-modes-fit/measurements.json"' in MODES_SMOKE
    assert "def resolve_report_path() -> Path:" in MODES_SMOKE
    assert "def build_report(audit: list[dict], *, head: str) -> dict:" in MODES_SMOKE
    assert "def write_report(report: dict, path: Path) -> Path:" in MODES_SMOKE
    assert "def head_sha() -> str:" in MODES_SMOKE
    # `run()` writes the report it just measured — after every assertion, so a
    # red run leaves no file behind — and only from the audit it built.
    assert "write_report(build_report(audit, head=head_sha()), resolve_report_path())" in MODES_SMOKE
    assert "build_report(audit" in MODES_SMOKE.split("async def run() -> None:", 1)[1]
    assert "json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)" in MODES_SMOKE
    for marker in (
        "#hhFileInput",  # the repro fixture goes through the real HH import
        "#hhHands .review-inbox-open",  # the hand is opened from the Review inbox
        "#replayerBackBtn",  # Replayer → Review
        'button.mode-card[data-app-view="spotlab"]',
        'button.mode-card[data-app-view="training"]',
        # #394 T6 — the embedded Stratégie Hero shell is joined by its real entry
        # point, the `#strategyPage` deep link (`appViewForHashTarget()` /
        # `routeFromHash()`), which is also the in-app anchor of the `#quickNav`
        # Strategy entry; the standalone editor keeps its own real
        # `./hero-ranges.html` link and is exercised by the mode card of step 7.
        'f"{url}#strategyPage"',
        'a.mode-card[data-app-view="strategy"]',  # real link to ./hero-ranges.html
        'page.keyboard.press("Tab")',
        'page.keyboard.press("ArrowRight")',
        'page.keyboard.press("Enter")',
    ):
        assert marker in MODES_SMOKE, marker

    # #394 T2 — the Review import surface reachability is contractual, not an
    # implementation detail: the smoke measures each import target with
    # `document.elementFromPoint` at the centre of its box (target or descendant
    # must receive the point) and confirms it with a Playwright
    # `locator.click(trial=True)` hit-test, at empty hands and at both reference
    # viewports, before the fixture import. This guard is additive: it only adds
    # required tokens, so none of the checks above (nor the T7 fit evidence
    # below) is removed or weakened.
    for token in ("reachability", "hit-test"):
        assert token in MODES_SMOKE, token
    # The vocabulary alone is not enough (a comment could keep it alive): the
    # measured hit-test and the Playwright click trial must be the real calls.
    assert "document.elementFromPoint(x, y)" in MODES_SMOKE
    assert ".click(trial=True" in MODES_SMOKE
    assert "def _assert_import_surface_hit_testable(" in MODES_SMOKE
    assert "def _assert_import_surface_click_trial(" in MODES_SMOKE
    assert "await _assert_import_surface_click_trial(" in MODES_SMOKE
    import_surface_block = MODES_SMOKE.split("IMPORT_SURFACE_SELECTORS = (", 1)[1].split(")", 1)[0]
    for selector in (
        "#reviewImportTab",
        'label[for="hhFileInput"]',
        ".hh-import-advanced > summary",
        "#hhWatchBtn",
    ):
        assert selector in import_surface_block, selector
    # The verdict is measured in the Review step of the two-viewport journey,
    # twice (closed details, then advanced details open), and the Import tab is
    # activated by a real click whose `aria-selected` flip is asserted.
    import_measurements = MODES_SMOKE.count("await _assert_import_surface_hit_testable(")
    assert import_measurements >= 2, import_measurements
    assert 'await page.click("#reviewImportTab")' in MODES_SMOKE
    assert 'await page.get_attribute("#reviewImportTab", "aria-selected")' in MODES_SMOKE
    assert "state.hhHands.length === 0" in MODES_SMOKE
    # Both measurements live in the per-viewport journey, and that journey is
    # still driven for each reference viewport.
    run_viewport_block = MODES_SMOKE.split("async def run_viewport(", 1)[1]
    assert run_viewport_block.count("await _assert_import_surface_hit_testable(") >= 2
    run_block = MODES_SMOKE.split("async def run() -> None:", 1)[1]
    assert "for width, height in VIEWPORTS:" in run_block
    assert "run_viewport(browser, url, width, height, audit)" in run_block

    # The verdict must stay *measured*: the JS hit-test has to expose the
    # individual conditions (viewport, shell, hit, who received the point) and the
    # raised assertion has to print them, so a failure is always actionable and
    # "explicit with the measured values" cannot decay into a bare boolean.
    measured_blocks = flat(MODES_SMOKE)
    for js_field in ("const inViewport", "const inShell", "hit:", "reachable:", "atTag:"):
        assert js_field in measured_blocks, js_field
    for reported in ("rect=", "innerViewport=", "elementFromPoint=", "point=", "shellBox="):
        assert reported in measured_blocks, reported

    # #394 T1 — the asynchronous local restore is crossed through its real
    # readiness signal before the journey's first mode-card click: a card clicked
    # while IndexedDB is still opening must not be silently overwritten when the
    # restore settles `state.appView`. The barrier is a `wait_for_function` on
    # `state.persistenceReady===true`, never a retry, a skip or a fixed delay,
    # and the state it gates is re-read afterwards (`state.userNavigated` /
    # `state.persistenceReady`) by the Review race probe. This block is additive:
    # it only adds required tokens.
    assert "state.persistenceReady===true" in MODES_SMOKE
    assert 'await page.wait_for_function("() => state.persistenceReady===true"' in MODES_SMOKE
    assert "READINESS_TIMEOUT_MS" in MODES_SMOKE
    assert "async def _wait_persistence_ready(" in MODES_SMOKE
    assert "await _wait_persistence_ready(page)" in MODES_SMOKE
    for probe_field in ("userNavigated: !!state.userNavigated", "persistenceReady: state.persistenceReady === true"):
        assert probe_field in MODES_SMOKE, probe_field
    run_viewport_block = MODES_SMOKE.split("async def run_viewport(", 1)[1].split(
        "async def run_review_race_viewport(", 1
    )[0]
    assert "await _wait_persistence_ready(page)" in run_viewport_block, (
        "the readiness barrier must be crossed inside the per-viewport journey"
    )
    assert run_viewport_block.index("await _wait_persistence_ready(page)") < run_viewport_block.index(
        'button.mode-card[data-app-view="spotlab"]'
    ), "the restore must settle before the journey's first mode-card click"

    # #394 T6 — the desktop journey is deterministic end to end on its two URL
    # boundaries, and both are guarded here because both used to be implicit:
    #
    # (a) the embedded Stratégie Hero shell is joined by its real entry point, the
    #     `#strategyPage` deep link resolved by `appViewForHashTarget()` /
    #     `routeFromHash()`, exactly like the Review `#historiesSection` deep link
    #     of step 2 — and the reload replays it as the load-time deep link;
    # (b) the standalone editor is measured through its own deep link, and the
    #     `wait_for_url` glob that waits for it must stay query-tolerant. A
    #     Playwright glob is anchored, so the query-less `**/hero-ranges.html`
    #     never matches the URL `syncDeepLink()` rewrites
    #     (`hero-ranges.html?population=…&hand=AA`): it would fail the step, or be
    #     silently satisfied by the un-rewritten URL. Both `wait_for_url` call
    #     sites of the repo use the `**/hero-ranges.html?**` convention
    #     (`grep -rn "wait_for_url" --include=*.py .` → this smoke + the hero
    #     compliance browser smoke below).
    assert MODES_SMOKE.count("wait_for_url(") == 1, (
        "the desktop journey waits on a single URL: the editor deep link"
    )
    assert 'wait_for_url("**/hero-ranges.html?**"' in MODES_SMOKE
    assert 'wait_for_url("**/hero-ranges.html"' not in MODES_SMOKE, (
        "the anchored, query-less URL glob never matches the rewritten editor URL"
    )
    assert HERO_COMPLIANCE_SMOKE.count("wait_for_url(") == 1
    assert 'wait_for_url("**/hero-ranges.html?**"' in HERO_COMPLIANCE_SMOKE
    # The audit itself is consigned in the smoke it protects.
    for audited in ("--include=*.py", "smoke_hero_compliance_browser.py:209"):
        assert audited in MODES_SMOKE, audited

    # The three T6 verdicts are measured, never deduced: the five parameters are
    # parsed out of `page.url` and compared to the real controls of the editor,
    # the in-place rewrite is asserted around a real `#heroGrid` click and the
    # reload has to restore the same context. Every token below is the real call
    # of the journey, so the guard cannot be kept alive by prose.
    assert 'EDITOR_DEEP_LINK_PARAMS = ("population", "position", "spot", "stack", "hand")' in MODES_SMOKE
    assert "for key in EDITOR_DEEP_LINK_PARAMS:" in MODES_SMOKE
    assert "def _measure_editor_deep_link(" in MODES_SMOKE
    assert "async def _wait_editor_ready(" in MODES_SMOKE
    for control in ("#populationInput", "#positionSelect", "#spotSelect", "#stackInput"):
        assert control in MODES_SMOKE, control
    for measured in (
        "page_url = page.url",
        "await page.evaluate(EDITOR_CONTEXT_JS)",
        'await page.evaluate("() => history.length")',
        '#heroGrid .hand-cell.selected[data-hand]',
    ):
        assert measured in MODES_SMOKE, measured
    journey_block = MODES_SMOKE.split("async def run_viewport(", 1)[1].split(
        "async def run_review_race_viewport(", 1
    )[0]
    assert journey_block.count("await _measure_editor_deep_link(") >= 3
    assert '_measure_editor_deep_link(page, "arrivée"' in journey_block
    assert '_measure_editor_deep_link(page, "réécriture"' in journey_block
    assert '_measure_editor_deep_link(page, "reload"' in journey_block
    assert "await _wait_editor_ready(page)" in journey_block
    assert 'f"{url}#strategyPage"' in journey_block
    assert "history.replaceState(null, '', location.pathname)" in journey_block
    assert 'await page.reload(wait_until="domcontentloaded"' in journey_block
    assert '#heroGrid .hand-cell[data-hand="' in journey_block
    assert 'assert rewritten["historyLength"] == history_before' in journey_block
    assert 'assert restored["controls"] == rewritten["controls"]' in journey_block
    assert 'await page.go_back(wait_until="domcontentloaded"' in journey_block

    # #394 T2 — the Review landing is deterministic, asserted and scoped: the
    # selected sub-views are queried inside the Review shell only, exactly
    # `["pilotage"]` is required, and the pane visibility is measured with
    # Playwright's own checks rather than observed. The reachability verdict
    # carries its own vocabulary (`hit_test` in the JS report and in the Python
    # assertion), so `elementFromPoint` / `hit_test` cannot decay into a comment.
    assert "REVIEW_SELECTED_SUBTABS_JS" in MODES_SMOKE
    assert '[data-view-shell="review"] [data-app-subview][aria-selected="true"]' in MODES_SMOKE
    assert "selected_subtabs = await page.evaluate(REVIEW_SELECTED_SUBTABS_JS)" in MODES_SMOKE
    assert 'assert selected_subtabs == ["pilotage"]' in MODES_SMOKE
    assert 'await page.locator("#reviewDashboard").is_visible()' in MODES_SMOKE
    assert 'await page.locator("#historiesSection").is_hidden()' in MODES_SMOKE
    assert "elementFromPoint" in MODES_SMOKE
    assert '"hit_test"' in MODES_SMOKE
    assert 'record["hit_test"]' in MODES_SMOKE
    assert "def _assert_import_surface_hit_testable(" in MODES_SMOKE

    # #394 T1 — the panels the human review named as never measured at 1366x768
    # are measured with the very same instrument as the import surface, and that
    # measurement is contractual: this guard fails as soon as a selector, its
    # `_assert_panel_surface_hit_testable` call, the `panel_surfaces` report
    # bucket or the per-viewport inventory disappears. Like the T2 block above it
    # is strictly additive — it only adds required tokens, so none of the checks
    # of this module (T6, T7, R2) is removed or weakened.
    assert "def _assert_panel_surface_hit_testable(" in MODES_SMOKE
    assert "PANEL_SHELLS = {" in MODES_SMOKE
    # The measurement is scoped to the view shell that owns the panel: a target
    # laid out outside its own shell is clipped by the fixed-height desktop shell,
    # whatever the document-level scroll metrics say. The three shells are the
    # Spot Lab / Replayer / Training ones the panels belong to.
    for shell in (
        '\'[data-view-shell="spotlab"]\'',
        '\'[data-view-shell="replayer"]\'',
        '\'[data-view-shell="training"]\'',
    ):
        assert shell in MODES_SMOKE, shell

    # Spot Lab `Range adverse` (#394 T1): the tab, the pane it mounts and the
    # 169-cell matrix it owns are the measured selectors — declared verbatim as
    # the tuple the per-viewport journey hit-tests.
    assert (
        'SPOTLAB_RANGE_SURFACE_SELECTORS = ("#spotlabRangeTab", "#rangeDisplaySection", "#matrix")'
        in MODES_SMOKE
    )
    spotlab_surface_block = MODES_SMOKE.split(
        "SPOTLAB_RANGE_SURFACE_SELECTORS = (", 1
    )[1].split(")", 1)[0]
    for selector in ("#spotlabRangeTab", "#rangeDisplaySection", "#matrix"):
        assert selector in spotlab_surface_block, selector

    # Replayer columns (#394 T1): the left/centre columns and the context panel.
    replayer_columns_block = MODES_SMOKE.split(
        "REPLAYER_COLUMN_SELECTORS = (", 1
    )[1].split(")", 1)[0]
    for selector in (".replayer-col-left", ".replayer-col-center", "#replayerContextPanel"):
        assert selector in replayer_columns_block, selector

    # Replayer right-panel tabs (#394 T1): each tab with the pane it mounts. A
    # hidden pane cannot be hit-tested, so every tab/pane pair is measured after a
    # real click on its tab.
    replayer_tabs_block = MODES_SMOKE.split("REPLAYER_TAB_SURFACES = (", 1)[1].split(
        "\n)", 1
    )[0]
    for tab_selector, panel_selector in (
        ("#replayerDecisionTab", "#replayerDecisionPanel"),
        ("#replayerRangesTab", "#replayerRangesPanel"),
        ("#replayerDetailsTab", "#hhReplayDetail"),
    ):
        assert tab_selector in replayer_tabs_block, tab_selector
        assert panel_selector in replayer_tabs_block, panel_selector

    # Training rail tabs and panes (#394 T1): the four rail tabs with their rail
    # panes, again tab by tab.
    trainer_rail_block = MODES_SMOKE.split("TRAINER_RAIL_SURFACES = (", 1)[1].split(
        "\n)", 1
    )[0]
    for tab_selector, panel_selector in (
        ("#trainerCoachingTab", "#trainerCoachPanel"),
        ("#trainerSessionTab", "#trainerSessionPanel"),
        ("#trainerProfilesTab", "#trainerProfilesPanel"),
        ("#trainerTestTab", "#trainerTestPanel"),
    ):
        assert tab_selector in trainer_rail_block, tab_selector
        assert panel_selector in trainer_rail_block, panel_selector

    # The verdicts are measured, never deduced: each panel surface is resolved by
    # the very hit-test a real mouse click performs, through the shared
    # `_assert_panel_surface_hit_testable` call — four call sites, each inside the
    # per-viewport journey (Spot Lab, Replayer columns, Replayer tabs, Training
    # rail), plus the real clicks that mount the sub-view before it is measured.
    assert MODES_SMOKE.count("await _assert_panel_surface_hit_testable(") >= 4
    journey_block = MODES_SMOKE.split("async def run_viewport(", 1)[1].split(
        "async def run_review_race_viewport(", 1
    )[0]
    assert journey_block.count("await _assert_panel_surface_hit_testable(") >= 4, (
        "the panel hit-tests must run inside the per-viewport journey"
    )
    assert "await page.click(\"#spotlabRangeTab\")" in journey_block
    assert "await page.click(tab_selector)" in journey_block
    # The per-target verdict reuses the import-surface report (same composer), so
    # a red panel names its measured rectangle, viewport and elementFromPoint.
    assert 'label = f"panneau {mode}"' in MODES_SMOKE

    # The new measurements are serialised in their own report bucket, and the
    # bucket cannot pass by vacuity: `panel_surface` records are routed to
    # `panel_surfaces`, the verdict requires every target reachable *and* both
    # reference viewports to have measured the panels, and a per-viewport
    # inventory is printed from the audit itself (green and red runs alike).
    assert 'if record.get("panel_surface"):' in MODES_SMOKE
    assert 'return "panel_surfaces"' in MODES_SMOKE
    assert '"panel_surfaces": []' in MODES_SMOKE
    assert 'report["panel_surfaces"]' in MODES_SMOKE
    assert 'for record in report["panel_surfaces"]' in MODES_SMOKE
    assert "panels_reachable" in MODES_SMOKE
    assert "panels_measured" in MODES_SMOKE
    assert 'record["viewport"] == f"{width}x{height}"' in MODES_SMOKE
    assert "def panel_inventory_lines(audit: list[dict]) -> list[str]:" in MODES_SMOKE
    assert "for line in panel_inventory_lines(audit):" in MODES_SMOKE
    assert "inventaire panneaux viewport={viewport} mesures={len(records)}" in MODES_SMOKE
    # The frozen job's log carries that inventory: it is what proves the
    # 1366x768 leg really ran the panel hit-tests, on a green and a red run alike.
    assert "desktop modes overflow audit" in MODES_SMOKE
    assert "panneau[{surface}]" in MODES_SMOKE

    # The #394 T7 fit evidence is versioned and contractual: since the frozen
    # browser job only runs in CI, this artefact is what a reviewer reads. It
    # must document the exact commands, the real HEAD, both reference viewports,
    # the per-mode scrollHeight/clientHeight audit, a verdict, and the explicit
    # note that ./hero-ranges.html is navigated but out of the shell contract
    # (no no-scroll assertion there).
    assert FIT_EVIDENCE.is_file(), FIT_EVIDENCE
    evidence_raw = FIT_EVIDENCE.read_text(encoding="utf-8")
    evidence_flat = flat(evidence_raw)
    assert "python3 tests/trainer/smoke_modes_desktop.py" in evidence_flat
    assert "python3 tests/trainer/smoke_trainer.py" in evidence_flat
    assert "git rev-parse HEAD" in evidence_flat
    assert "1500x1000" in evidence_flat and "1366x768" in evidence_flat
    assert "scrollHeight" in evidence_flat and "clientHeight" in evidence_flat
    for mode in ("home", "spotlab", "review", "replayer", "training", "strategy"):
        assert mode in evidence_flat, mode
    assert "verdict" in evidence_flat.casefold()
    assert "hero-ranges.html" in evidence_flat
    assert "hors contrat" in evidence_flat.casefold()

    # #394 (backlog-31r) — the evidence must be auditable *from the repository*:
    # it cannot lean on an out-of-repo harness, so no path outside the checkout
    # may appear in it, and the option that regenerates the smoke's JSON report
    # has to be documented. The frozen `browser-smoke` job stays the authority
    # for the 1500x1000 / 1366x768 no-global-scroll rule.
    assert "/tmp/" not in evidence_raw, (
        "the fit evidence must not cite a path outside the repository"
    )
    assert "browser-smoke" in evidence_flat
    assert "seule autorité" in evidence_flat
    assert "--report" in evidence_flat
    assert "artifacts/desktop-modes-fit/measurements.json" in evidence_flat
    assert "SMOKE_MODES_DESKTOP_REPORT" in evidence_flat
    assert "--report artifacts/desktop-modes-fit/measurements.json" in evidence_flat

    # #394 R2 (backlog-cg8) — the human review rejected the previous
    # qualification of the Home failure: § 8 has to record the *real* CI failure
    # of the frozen job and the R1 fix that removes it, not a re-reading of it.
    # Two things are guarded here, so the record cannot silently decay:
    #
    # (a) the smoke keeps its real click on the Accueil « Review » shortcut. The
    #     failure this document records *is* that click: Playwright's default
    #     30 s actionability timeout expired because the centre of
    #     `#homePage a[href="#historiesSection"]` received `#quickNavToggle`. A
    #     `force=True`, a JS-dispatched click or a retry would hide exactly the
    #     interception the R1 fix removes, so none of them may exist in the
    #     smoke — the click is asserted verbatim, which also pins its default
    #     timeout (no `timeout=` override);
    # (b) the evidence must name that interception and that real click, the R1
    #     fix, and the CI origin of the failure, and it may not requalify the
    #     failure as an "artefact" of the centred column.
    assert 'await page.click(\'#homePage a[href="#historiesSection"]\')' in MODES_SMOKE
    for bypass in ("force=True", "dispatch_event"):
        assert bypass not in MODES_SMOKE, bypass
    assert "quickNavToggle" in evidence_flat
    assert '#homePage a[href="#historiesSection"]' in evidence_flat
    assert "intercept" in evidence_flat.casefold()
    assert "30 s" in evidence_flat
    for no_bypass in ("dispatch_event", "force=True", "retry", "skip"):
        assert no_bypass in evidence_flat, no_bypass
    assert "PR #416" in evidence_flat
    assert "site/index.html" in evidence_flat
    assert "tests/trainer/test_desktop_accessibility_contract.py" in evidence_flat
    assert "artefact" not in evidence_flat.casefold(), (
        "le constat doit rester l'échec CI réel, jamais une qualification d'artefact"
    )
    # The front-matter carries the provenance of this revision: the R2 key, no
    # inherited HEAD of the previous revision, and a SHA-shaped value (the
    # thread's HEAD at writing time — the orchestrator commits afterwards, so the
    # value is deliberately not compared to `git rev-parse HEAD` here).
    assert "planner_key: R2" in evidence_raw, "le front-matter doit porter la clé R2"
    head_line = next(
        line for line in evidence_raw.splitlines() if line.startswith("head_sha: ")
    )
    head_value = head_line.split("head_sha: ", 1)[1].strip()
    assert len(head_value) == 40 and all(char in "0123456789abcdef" for char in head_value), head_value
    assert head_value != "386f9d91e9fb229b042bd90588e19b806ce2324e", (
        "le front-matter ne peut pas reconduire le HEAD de la révision précédente"
    )

    # #394 T2 — the desktop hit-tests are never executed outside the frozen
    # browser job, so this guard links their targets to the *bytes served* by the
    # app: the selector tuples are read back from the smoke as literal constants
    # (`ast`) and every id/class is resolved against `site/index.html` itself —
    # inline JS templates included, so `hhVisualReplay.innerHTML`'s
    # `.replayer-col-left` / `.replayer-col-center` count as served nodes while a
    # CSS-only occurrence does not. Strictly additive: no token above is removed
    # or relaxed, and a renamed/removed node now fails here instead of only in CI.
    import_surface_selectors = literal_assignment(MODES_SMOKE, "IMPORT_SURFACE_SELECTORS")
    import_advanced_selector = literal_assignment(MODES_SMOKE, "IMPORT_ADVANCED_SELECTOR")
    spotlab_range_selectors = literal_assignment(MODES_SMOKE, "SPOTLAB_RANGE_SURFACE_SELECTORS")
    replayer_column_selectors = literal_assignment(MODES_SMOKE, "REPLAYER_COLUMN_SELECTORS")
    replayer_tab_surfaces = literal_assignment(MODES_SMOKE, "REPLAYER_TAB_SURFACES")
    trainer_rail_surfaces = literal_assignment(MODES_SMOKE, "TRAINER_RAIL_SURFACES")
    # Non-vacuity of the parse itself: a truncated tuple would make the loop below
    # pass for free, so the expected shapes are pinned here (counts only — the
    # selector tokens themselves stay owned by the blocks above, never re-spelled).
    assert len(import_surface_selectors) >= 4, import_surface_selectors
    assert isinstance(import_advanced_selector, str) and import_advanced_selector
    assert len(spotlab_range_selectors) >= 3, spotlab_range_selectors
    assert len(replayer_column_selectors) >= 3, replayer_column_selectors
    assert len(replayer_tab_surfaces) >= 3, replayer_tab_surfaces
    assert len(trainer_rail_surfaces) >= 4, trainer_rail_surfaces
    assert all(len(pair) >= 2 for pair in replayer_tab_surfaces + trainer_rail_surfaces), (
        "chaque couple (onglet, panneau) doit porter ses deux sélecteurs"
    )
    served_import_targets = tuple(import_surface_selectors) + (import_advanced_selector,)
    served_panel_targets = (
        tuple(spotlab_range_selectors)
        + tuple(replayer_column_selectors)
        + tuple(sel for pair in replayer_tab_surfaces for sel in pair[:2])
        + tuple(sel for pair in trainer_rail_surfaces for sel in pair[:2])
    )
    assert len(served_panel_targets) >= 20, len(served_panel_targets)
    # (a) Every import and panel target of the desktop hit-tests exists in the
    # served bytes. A selector that disappears from site/index.html fails here.
    for selector in served_import_targets + served_panel_targets:
        assert_served_selector(selector)

    # (b) The measured verdict must stay non-vacuous: the fields the Python
    # assertions read off a hit-test entry (`_assert_import_surface_hit_testable`,
    # `_assert_panel_surface_hit_testable` and their shared `_surface_verdict`)
    # have to be the fields `SURFACE_HIT_TEST_JS` actually exposes. Removing a
    # field from the snippet, or letting a helper stop reading one, fails here.
    surf_hit_test_js = MODES_SMOKE.split('SURFACE_HIT_TEST_JS = """', 1)[1].split('"""', 1)[0]
    exposed_fields = set(re.findall(r"(?<![\w$.])([A-Za-z_]\w*)\s*[:,]", surf_hit_test_js))
    read_fields: set[str] = set()
    for quote in ('"', "'"):
        read_fields.update(re.findall(rf"entry\[{quote}(\w+){quote}\]", MODES_SMOKE))
        read_fields.update(re.findall(rf"entry\.get\({quote}(\w+){quote}\)", MODES_SMOKE))
    required_fields = (
        "present",
        "visible",
        "inViewport",
        "inShell",
        "hit",
        "reachable",
        "point",
        "viewport",
        "box",
        "at",
    )
    assert set(required_fields) <= read_fields, sorted(set(required_fields) - read_fields)
    missing_exposed = sorted(read_fields - exposed_fields)
    assert not missing_exposed, (
        f"champs lus par les assertions mais absents de SURFACE_HIT_TEST_JS: {missing_exposed}"
    )
    for field in required_fields:
        assert re.search(rf"(?<![\w$.]){re.escape(field)}\s*[:,]", surf_hit_test_js), (
            f"SURFACE_HIT_TEST_JS n'expose plus le champ {field}"
        )

    # (c) Both reference viewports stay explicit — the audit loops on the literal
    # `VIEWPORTS` — and every panel surface is measured inside `run_viewport()`,
    # the journey `run()` drives once per viewport: the Spot Lab / Replayer-columns
    # tuples are passed to the hit-test call, and the Replayer-tabs / Trainer-rail
    # loops measure each tab/pane pair. The `panel_surfaces` bucket and its
    # per-viewport inventory are already pinned above; this block only ties them to
    # the per-viewport journey.
    assert literal_assignment(MODES_SMOKE, "VIEWPORTS") == ((1500, 1000), (1366, 768))
    t2_journey = MODES_SMOKE.split("async def run_viewport(", 1)[1].split(
        "async def run_review_race_viewport(", 1
    )[0]
    for tuple_name in ("SPOTLAB_RANGE_SURFACE_SELECTORS", "REPLAYER_COLUMN_SELECTORS"):
        assert re.search(rf"^\s*{tuple_name},\s*$", t2_journey, re.M), (
            f"{tuple_name} n'est pas mesuré dans le parcours par viewport"
        )
    for loop_owner in ("REPLAYER_TAB_SURFACES", "TRAINER_RAIL_SURFACES"):
        assert f"for tab_selector, panel_selector, subview in {loop_owner}:" in t2_journey, (
            f"la boucle {loop_owner} doit vivre dans le parcours par viewport"
        )
    assert "(tab_selector, panel_selector)," in t2_journey

    print("smoke orchestration contract checks: OK")


if __name__ == "__main__":
    main()

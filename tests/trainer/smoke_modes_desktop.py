#!/usr/bin/env python3
"""Desktop modes smoke + overflow audit (#394 · task T4).

Browser smoke of the desktop application shell. It drives the real UI (no
in-page shortcut where a click exists) and measures, **per mode and per
reference viewport**, that the document never scrolls globally:
`document.scrollingElement.scrollHeight <= clientHeight` at `1500x1000` and
`1366x768`. A mode that overflows fails explicitly with the measured values, so
the audit is never silently satisfied by a clipped shell.

The Review import surface is measured at the same time, and for the same reason:
the shell never scrolls, so a pane that is only *rendered* can still be clipped
and unreachable. Review therefore lands on its Pilotage pane, the Import pane is
opened by a real click on `#reviewImportTab`, and every import target
(`#reviewImportTab`, the `Importer mes mains` label that proxies the visually
hidden `#hhFileInput`, the advanced details summary, `#hhWatchBtn` and, once the
details is open, `#hhBenchmarkExportBtn`) is resolved with
`document.elementFromPoint` at the centre of its box and must be visible, inside
the viewport and inside the shell. Its real reachability is then confirmed by a
Playwright `locator.click(trial=True)` hit-test, i.e. the same verdict a real
click would produce, without dispatching the click. The clicks that follow are
real mouse clicks. This measurement happens at **empty hands**, before any
import, at both reference viewports, and never retries or skips: a clipped
target fails with its measured rectangle, viewport and `elementFromPoint`.

Covered journeys (each on a fresh context, both viewports):

* Accueil → Review → Replayer → Review: the `kts_sb_two_limp_iso4_three_calls`
  repro fixture is imported through the real `#hhFileInput`, a hand is opened
  from the Review inbox (`#hhHands .review-inbox-open`) and the Replayer hands
  the user back to the Review inbox. The fixture is the truncated public prefix
  of hand `#3210001` (it stops on the flop, as the snapshot suite consumes it)
  and the Review import ignores a trailing hand without a `*** SUMMARY ***`
  line, so the smoke feeds the **unmodified fixture bytes** plus that single
  terminal marker — the same marker every PokerStars export closes a hand with.
  The file on disk stays byte-identical (immutable repro evidence for
  `tools/repro_preflop_fixture.py`);
* Accueil → Spot Lab: reached **without any imported hand** (`state.hhHands`
  stays empty), i.e. the manual tools stay independent from the Review import;
* Accueil → Training: the Trainer shell is mounted from the Accueil mode card;
* Accueil → Stratégie Hero: the embedded `#strategyPage` shell is measured, and
  the Accueil mode card is proven to navigate to the standalone
  `./hero-ranges.html` editor. The standalone page is deliberately **not**
  asserted no-scroll — it is not part of the fixed-height desktop shell;
* a minimal keyboard/focus control: `Tab` until the Replayer right-panel tabs
  are focused, then `ArrowRight`/`ArrowLeft` (roving focus + activation) and
  `Enter` (explicit keyboard activation) must only toggle pane visibility.

It is a representation/application-shell smoke only: no model/fit, no equity
kernel and no immutable repro evidence is touched. It starts its own ephemeral
static server over `site/` (like `smoke_equity_scale_invariance.py`) and it fails
with a clear message when Playwright is unavailable instead of skipping.
"""
from __future__ import annotations

import asyncio
import re
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:  # pragma: no cover - import guard, asserted in `main`
    from playwright.async_api import async_playwright
except Exception as exc:  # pragma: no cover - optional dependency
    async_playwright = None
    PLAYWRIGHT_IMPORT_ERROR = repr(exc)
else:  # pragma: no cover - trivial branch
    PLAYWRIGHT_IMPORT_ERROR = ""

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "site"
FIXTURE = ROOT / "tests/fixtures/repro/kts_sb_two_limp_iso4_three_calls.hand.txt"
# `applyHHSnapshots()` in site/index.html ignores a trailing hand block that has
# no `*** SUMMARY ***` marker (a truncated export). The repro fixture is exactly
# such a truncated prefix, so the smoke appends the marker to the bytes it feeds
# the real file input instead of touching the immutable fixture file.
IMPORT_SUMMARY_MARKER = "*** SUMMARY ***"


def _fixture_hand_id() -> str:
    """Hand id of the repro fixture header (`PokerStars Hand #3210001:`)."""
    if not FIXTURE.is_file():
        return ""
    match = re.search(r"Hand #(\d+)", FIXTURE.read_text(encoding="utf-8"))
    return match.group(1) if match else ""


FIXTURE_HAND_ID = _fixture_hand_id()

# Reference viewports of the desktop shell contract.
VIEWPORTS = ((1500, 1000), (1366, 768))
MODES = ("home", "spotlab", "review", "replayer", "training", "strategy")
REPLAYER_SUBVIEWS = ("replayer-decision", "replayer-ranges", "replayer-details")
# Upper bound of the Tab walk that must reach the Replayer right-panel tabs. The
# tabs sit after the head buttons and the left column controls in the tab order.
REPLAYER_TAB_BUDGET = 160

MEASURE_JS = """async () => {
  await new Promise(requestAnimationFrame);
  await new Promise(requestAnimationFrame);
  const root = document.scrollingElement;
  const mounted = document.body.dataset.appView || "";
  const shell = mounted ? document.querySelector('[data-view-shell="' + mounted + '"]') : null;
  return {
    mounted,
    scrollHeight: root.scrollHeight,
    clientHeight: root.clientHeight,
    shellVisible: !!shell && !shell.classList.contains("mode-hidden"),
    focused: (document.activeElement && (document.activeElement.id || document.activeElement.tagName)) || ""
  };
}"""

REPLAYER_TABS_JS = """() => {
  const panel = document.getElementById("replayerContextPanel");
  const tabs = Array.from(panel.querySelectorAll("[data-app-subview]"));
  const hidden = {};
  for (const pane of panel.querySelectorAll("[data-app-subview-panel]")) {
    hidden[pane.dataset.appSubviewPanel] = !!pane.hidden;
  }
  return {
    focused: (document.activeElement && document.activeElement.dataset && document.activeElement.dataset.appSubview) || "",
    selected: tabs.filter(t => t.getAttribute("aria-selected") === "true").map(t => t.dataset.appSubview),
    roving: tabs.filter(t => t.tabIndex === 0).map(t => t.dataset.appSubview),
    hidden
  };
}"""

# #394 T1/T2 — the Review import surface reachability is measured, never
# deduced: each target is resolved with the very hit-test a real mouse click
# performs (`document.elementFromPoint` at the centre of its box) and must be
# visible, inside the viewport and inside the bounded `review` shell.
# `elementFromPoint` must return the target **or one of its descendants**
# (`at === el || el.contains(at)`); an ancestor that merely owns the box is not a
# hit target. A clipped target (the frozen smoke failure this fixes) reports
# `hit: false` / `inShell: false` with the measured rectangle, viewport and
# elementFromPoint verdict.
IMPORT_HIT_TEST_JS = """(selectors) => {
  const shell = document.querySelector('[data-view-shell="review"]');
  const shellBox = shell ? shell.getBoundingClientRect() : null;
  const out = {};
  for (const selector of selectors) {
    const el = document.querySelector(selector);
    if (!el) {
      out[selector] = { present: false };
      continue;
    }
    const box = el.getBoundingClientRect();
    const x = box.left + box.width / 2, y = box.top + box.height / 2;
    const at = document.elementFromPoint(x, y);
    const hit = !!at && (at === el || el.contains(at));
    const inViewport = box.top >= 0 && box.left >= 0
      && box.bottom <= innerHeight && box.right <= innerWidth;
    const inShell = !!shellBox && box.top >= shellBox.top - 0.5
      && box.bottom <= shellBox.bottom + 0.5;
    out[selector] = {
      present: true,
      visible: box.width > 0 && box.height > 0,
      inViewport,
      inShell,
      hit,
      // Composite verdict printed as `reachable`; the individual fields stay
      // exposed so a red run names the exact failing condition.
      reachable: box.width > 0 && box.height > 0 && inViewport && inShell && hit,
      point: { x: Math.round(x), y: Math.round(y) },
      viewport: { width: innerWidth, height: innerHeight },
      shellBox: shellBox
        ? { top: Math.round(shellBox.top), bottom: Math.round(shellBox.bottom) }
        : null,
      at: at ? (at.id || (typeof at.className === 'string' ? at.className : '') || at.tagName) : null,
      atTag: at ? at.tagName : null,
      box: {
        top: Math.round(box.top), bottom: Math.round(box.bottom),
        left: Math.round(box.left), right: Math.round(box.right),
        width: Math.round(box.width), height: Math.round(box.height)
      }
    };
  }
  return out;
}"""

# The import surface itself: the Import tab, the primary label that proxies the
# visually hidden `#hhFileInput` (`input[type=file]{display:none}`) and the
# watcher button. `#hhBenchmarkExportBtn` is added once the advanced details is
# open, since a closed `<details>` hides its own content. These selectors are the
# additive reachability contract (#394 T2): the static guard in
# `test_smoke_orchestration_contract.py` fails if they, the
# `elementFromPoint` hit-test or the Playwright click trial disappear.
IMPORT_SURFACE_SELECTORS = (
    "#reviewImportTab",
    'label[for="hhFileInput"]',
    ".hh-import-advanced > summary",
    "#hhWatchBtn",
)
IMPORT_ADVANCED_SELECTOR = "#hhBenchmarkExportBtn"


def _surface_verdict(selector: str, entry: dict, step: str, width: int, height: int) -> str:
    """Explicit measured verdict for one import target (no retry, no skip)."""
    return (
        f"surface d'import non atteignable: {selector} ({step}, viewport {width}x{height}) — "
        f"present={entry.get('present')} visible={entry.get('visible')} "
        f"inViewport={entry.get('inViewport')} inShell={entry.get('inShell')} "
        f"hit={entry.get('hit')} reachable={entry.get('reachable')} "
        f"rect={entry.get('box')} innerViewport={entry.get('viewport')} "
        f"elementFromPoint={entry.get('at')} (tag={entry.get('atTag')}) "
        f"point={entry.get('point')} shellBox={entry.get('shellBox')}"
    )


async def _assert_import_surface_click_trial(
    page, selectors: tuple[str, ...], step: str, width: int, height: int, report: dict
) -> None:
    """Confirm reachability with Playwright's own hit-test (`click(trial=True)`).

    `trial=True` runs the exact actionability/hit-target check a real click runs
    (element or descendant receiving pointer events at the click point) without
    dispatching anything. A failure is re-raised as an explicit assertion that
    carries the measured `elementFromPoint` verdict; there is no retry and no
    skip path. The timeout is only a bound on the *green* path (an already
    visible, hit-testable target resolves in a couple of frames); a red target is
    already named by the `elementFromPoint` assertion that runs before it, so no
    timeout tuning can turn a clipped surface into a pass.
    """
    for selector in selectors:
        try:
            await page.locator(selector).click(trial=True, timeout=10_000)
        except Exception as exc:  # pragma: no cover - red path, re-raised explicitly
            entry = report.get(selector, {"present": False})
            raise AssertionError(
                f"surface d'import non cliquable (click trial Playwright): {selector} "
                f"({step}, viewport {width}x{height}) — {_surface_verdict(selector, entry, step, width, height)} "
                f"— playwright={type(exc).__name__}: {exc}"
            ) from exc


async def _assert_import_surface_hit_testable(
    page, selectors: tuple[str, ...], step: str, width: int, height: int, audit: list[dict]
) -> dict:
    report = await page.evaluate(IMPORT_HIT_TEST_JS, list(selectors))
    audit.append(
        {
            "mode": "review",
            "viewport": f"{width}x{height}",
            "surface": step,
            "hit_test": report,
        }
    )
    for selector in selectors:
        entry = report[selector]
        assert entry["present"], (
            f"surface d'import introuvable: {selector} ({step}, {width}x{height})"
        )
        for field in ("visible", "inViewport", "inShell", "hit"):
            assert entry[field], (
                f"{_surface_verdict(selector, entry, step, width, height)} "
                f"[champ en échec: {field}=false] "
                "(verdict mesuré par elementFromPoint + boîte, jamais déduit, jamais de retry)"
            )
        assert entry["reachable"], (
            f"{_surface_verdict(selector, entry, step, width, height)} "
            "[verdict composite reachable=false]"
        )
    await _assert_import_surface_click_trial(page, selectors, step, width, height, report)
    return report


HIDDEN_DECISION = {"replayer-decision": False, "replayer-ranges": True, "replayer-details": True}
HIDDEN_RANGES = {"replayer-decision": True, "replayer-ranges": False, "replayer-details": True}
HIDDEN_DETAILS = {"replayer-decision": True, "replayer-ranges": True, "replayer-details": False}

DECISION_TAB_STATE = {
    "focused": "replayer-decision",
    "selected": ["replayer-decision"],
    "roving": ["replayer-decision"],
    "hidden": HIDDEN_DECISION,
}
RANGES_TAB_STATE = {
    "focused": "replayer-ranges",
    "selected": ["replayer-ranges"],
    "roving": ["replayer-ranges"],
    "hidden": HIDDEN_RANGES,
}
DETAILS_TAB_STATE = {
    "focused": "replayer-details",
    "selected": ["replayer-details"],
    "roving": ["replayer-details"],
    "hidden": HIDDEN_DETAILS,
}


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args, **kwargs):  # pragma: no cover - silence the server
        return


def importable_fixture_bytes() -> bytes:
    """The repro fixture bytes, closed by the `*** SUMMARY ***` export marker."""
    text = FIXTURE.read_text(encoding="utf-8").rstrip("\n")
    return f"{text}\n{IMPORT_SUMMARY_MARKER}\n".encode("utf-8")


def _serve_site() -> tuple[ThreadingHTTPServer, str]:
    handler = partial(_QuietHandler, directory=str(SITE))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}/index.html"


async def _wait_view(page, view: str, timeout: int = 30_000) -> None:
    await page.wait_for_function(
        "(view) => {"
        "  const shell = document.querySelector('[data-view-shell=\"' + view + '\"]');"
        "  return document.body.dataset.appView === view"
        "    && !!shell && !shell.classList.contains('mode-hidden');"
        "}",
        arg=view,
        timeout=timeout,
    )


async def _measure(page, mode: str, width: int, height: int, audit: list[dict]) -> dict:
    result = await page.evaluate(MEASURE_JS)
    audit.append(
        {
            "mode": mode,
            "viewport": f"{width}x{height}",
            "mounted": result["mounted"],
            "scrollHeight": result["scrollHeight"],
            "clientHeight": result["clientHeight"],
        }
    )
    assert result["mounted"] == mode, (
        f"mode non monté: attendu {mode}, monté {result['mounted']} ({width}x{height})"
    )
    assert result["shellVisible"], (
        f"coque de vue absente/masquée pour le mode {mode} ({width}x{height})"
    )
    assert result["scrollHeight"] <= result["clientHeight"], (
        "débordement de la coque desktop: "
        f"mode={mode} viewport={width}x{height} "
        f"document.scrollingElement.scrollHeight={result['scrollHeight']} > "
        f"clientHeight={result['clientHeight']} "
        "(remédiation attendue: compactage, sous-vue ou pagination — jamais de scroll global)"
    )
    return result


async def _back_to_home(page, shell: str) -> None:
    await page.click(f'[data-view-shell="{shell}"] [data-home-back]')
    await _wait_view(page, "home")


async def _replayer_tabs_state(page) -> dict:
    return await page.evaluate(REPLAYER_TABS_JS)


async def _assert_replayer_keyboard(page, width: int, height: int) -> None:
    # Deterministic start of the sequential focus walk: the first control of the
    # Replayer head. Tabbing from there must pass the replay controls and reach
    # the right-panel tabs, exactly like a keyboard-only user.
    await page.locator("#replayerHomeBtn").focus()
    reached = ""
    for _ in range(REPLAYER_TAB_BUDGET):
        await page.keyboard.press("Tab")
        reached = await page.evaluate(
            "() => (document.activeElement && document.activeElement.dataset"
            " && document.activeElement.dataset.appSubview) || ''"
        )
        if reached in REPLAYER_SUBVIEWS:
            break
    assert reached == REPLAYER_SUBVIEWS[0], (
        "Tab n'atteint pas les onglets du panneau droit du Replayer depuis le haut de la vue "
        f"({width}x{height}); dernier focus: {reached or 'aucun'}"
    )

    state = await _replayer_tabs_state(page)
    assert state == DECISION_TAB_STATE, (width, height, state)

    # ArrowRight moves the roving focus and activates the target tab.
    await page.keyboard.press("ArrowRight")
    ranges = await _replayer_tabs_state(page)
    assert ranges == RANGES_TAB_STATE, (width, height, ranges)

    # Enter is the explicit keyboard activation: it only toggles pane visibility,
    # so the selection, the roving tabindex and the pane visibility are unchanged.
    await page.keyboard.press("Enter")
    assert await _replayer_tabs_state(page) == RANGES_TAB_STATE, (width, height)

    await page.keyboard.press("ArrowRight")
    assert await _replayer_tabs_state(page) == DETAILS_TAB_STATE, (width, height)

    await page.keyboard.press("ArrowLeft")
    assert await _replayer_tabs_state(page) == RANGES_TAB_STATE, (width, height)


async def run_viewport(browser, url: str, width: int, height: int, audit: list[dict]) -> list[str]:
    context = await browser.new_context(viewport={"width": width, "height": height})
    page = await context.new_page()
    page_errors: list[str] = []
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        await _wait_view(page, "home")
        await _measure(page, "home", width, height, audit)

        # 1. Accueil → Spot Lab, without importing any hand history: the manual
        #    tools stay independent from the Review import.
        await page.click('button.mode-card[data-app-view="spotlab"]')
        await _wait_view(page, "spotlab")
        assert await page.evaluate(
            "() => Array.isArray(state.hhHands) && state.hhHands.length === 0"
        ), f"le Spot Lab doit rester indépendant des mains importées ({width}x{height})"
        await _measure(page, "spotlab", width, height, audit)
        await _back_to_home(page, "spotlab")

        # 2. Accueil → Review. Review lands on its Pilotage pane; the import
        #    surface is its own pane, reached by a real click on the Import tab.
        await page.click('button.mode-card[data-app-view="review"]')
        await _wait_view(page, "review")
        assert await page.locator("#reviewDashboard").is_visible(), (
            f"Review doit atterrir sur le panneau Pilotage ({width}x{height})"
        )
        assert await page.locator("#historiesSection").is_hidden(), (
            f"le panneau Import doit être masqué à l'atterrissage ({width}x{height})"
        )
        await _measure(page, "review", width, height, audit)
        await page.click("#reviewImportTab")
        assert await page.locator("#historiesSection").is_visible(), (
            f"l'onglet Import doit monter son panneau ({width}x{height})"
        )
        assert await page.locator("#reviewDashboard").is_hidden(), (
            f"un seul panneau de Review est monté à la fois ({width}x{height})"
        )
        # #394 T2 — the Import surface is a real sub-view: the tab must exist and
        # the real click above must flip the `aria-selected` state before any
        # import target is measured. A pane that only exists in the DOM (or a tab
        # that stays `aria-selected="false"`) fails here instead of being
        # silently measured through a JS shortcut.
        assert await page.locator("#reviewImportTab").count() == 1, (
            f"l'onglet Import #reviewImportTab doit exister ({width}x{height})"
        )
        assert await page.get_attribute("#reviewImportTab", "aria-selected") == "true", (
            "le clic réel sur #reviewImportTab doit le passer à aria-selected=true "
            f"({width}x{height}), obtenu "
            f"{await page.get_attribute('#reviewImportTab', 'aria-selected')!r}"
        )
        assert await page.get_attribute("#reviewPilotageTab", "aria-selected") == "false", (
            "l'onglet Pilotage doit repasser à aria-selected=false quand Import est actif "
            f"({width}x{height})"
        )
        assert await page.get_attribute(
            "#historiesSection", "data-app-subview-panel"
        ) == "import", (
            f"le panneau mesuré doit être le panneau Import ({width}x{height})"
        )
        # The reachability contract is measured at **empty hands**, before the
        # import of step 3: nothing here may be satisfied by an already-imported
        # hand rendering a different layout.
        assert await page.evaluate(
            "() => Array.isArray(state.hhHands) && state.hhHands.length === 0"
        ), (
            "la surface d'import Review doit être mesurée à main vide, avant tout import "
            f"({width}x{height})"
        )
        # A sub-view switch is a pure visibility toggle: the shell still never
        # scrolls, and the whole import surface is hit-testable at this viewport.
        await _measure(page, "review", width, height, audit)
        await _assert_import_surface_hit_testable(
            page, IMPORT_SURFACE_SELECTORS, "closed", width, height, audit
        )
        # The label proxies the visually hidden `#hhFileInput`: a real mouse click
        # on it must open the picker (no `element.click()` shortcut).
        assert not await page.locator("#hhFileInput").is_visible(), (
            f"`#hhFileInput` reste masqué (`input[type=file]{display:none}`); "
            f"c'est le label qui porte le clic ({width}x{height})"
        )
        # `expect_file_chooser` raises if the click does not reach the associated
        # input, so it is the assertion; no file is selected (the real import goes
        # through `#hhFileInput` in step 3).
        async with page.expect_file_chooser():
            await page.click('label[for="hhFileInput"]')
        # `#hhWatchBtn` is the third import control and gets a real mouse click too
        # (never `element.click()`). Headless Chromium cannot show the OS directory
        # picker, so the handler's picker call is replaced by its own cancellation
        # path (`AbortError`, exactly what a user closing the dialog produces): the
        # click then has to land on the button for the status to report it.
        watch_target = await page.evaluate(
            """() => {
              const btn=document.getElementById('hhWatchBtn');
              const box=btn.getBoundingClientRect();
              const x=box.left+box.width/2, y=box.top+box.height/2;
              const at=document.elementFromPoint(x,y);
              const cap=hhWatchCapability();
              const driver=cap.hasPicker&&cap.secure&&!cap.embedded;
              window.__hhWatchPicker=window.showOpenFilePicker;
              if(driver){
                window.showOpenFilePicker=()=>Promise.reject(Object.assign(new Error('smoke: picker fermé'),{name:'AbortError'}));
              }
              return {x,y,driver,hit:at===btn||btn.contains(at),at:at?(at.id||at.tagName):null};
            }"""
        )
        await page.mouse.click(watch_target["x"], watch_target["y"])
        watch_result = await page.evaluate(
            """() => {
              const watching=!!state.hhWatchTimer||(state.hhWatchHandles||[]).length>0;
              window.showOpenFilePicker=window.__hhWatchPicker;
              delete window.__hhWatchPicker;
              return {watching};
            }"""
        )
        assert watch_target["hit"], (
            f"`#hhWatchBtn` doit être sous le curseur au point cliqué "
            f"({width}x{height}) — at={watch_target['at']}"
        )
        assert watch_result["watching"] is False, (
            f"le clic de mesure ne doit démarrer aucune surveillance ({width}x{height})"
        )
        if watch_target["driver"]:
            # The cancellation is written by the async handler, so wait for it
            # instead of racing the microtask that resolves the rejected picker
            # promise — then read it back as a measured verdict.
            await page.wait_for_function(
                "() => /annul/.test(document.getElementById('hhWatchStatus').textContent)",
                timeout=5_000,
            )
            watch_status = await page.evaluate(
                "() => document.getElementById('hhWatchStatus').textContent"
            )
            assert "annul" in watch_status, (
                "le vrai clic souris doit atteindre le gestionnaire de « Surveiller mes HH » "
                f"({width}x{height}) — statut={watch_status}"
            )
        # The advanced options must not only exist: once the details is opened by a
        # real click, its whole row — export button included — is hit-testable.
        assert not await page.locator(IMPORT_ADVANCED_SELECTOR).is_visible()
        await page.click(".hh-import-advanced > summary")
        assert await page.locator(IMPORT_ADVANCED_SELECTOR).is_visible()
        await _assert_import_surface_hit_testable(
            page,
            IMPORT_SURFACE_SELECTORS + (IMPORT_ADVANCED_SELECTOR,),
            "advanced-open",
            width,
            height,
            audit,
        )
        # Real click on the advanced export: with zero hand loaded it only reports
        # its status (no benchmark is written), so it stays side-effect free here.
        await page.click(IMPORT_ADVANCED_SELECTOR)
        await page.click(".hh-import-advanced > summary")
        assert not await page.locator(IMPORT_ADVANCED_SELECTOR).is_visible()

        # The historical `#historiesSection` deep link (the Accueil « Review »
        # direct link, also the `#quickNav` entry) selects the Import pane instead
        # of scrolling the view: back to Pilotage, then through the real anchor.
        await page.click("#reviewPilotageTab")
        assert await page.locator("#reviewDashboard").is_visible()
        await _back_to_home(page, "review")
        await page.click('#homePage a[href="#historiesSection"]')
        await _wait_view(page, "review")
        assert await page.locator("#historiesSection").is_visible(), (
            f"le deep link #historiesSection doit sélectionner le panneau Import ({width}x{height})"
        )
        assert await page.locator("#reviewDashboard").is_hidden(), (
            f"le deep link ne laisse pas deux panneaux montés ({width}x{height})"
        )
        # A hidden scroll is what the shell contract forbids: the bounded boxes must
        # still report `scrollTop === 0` after the deep link focused the pane (the
        # 1px tolerance absorbs sub-pixel rounding of a fractional client height; a
        # real hidden scroll of a clipped pane is orders of magnitude larger).
        assert await page.evaluate(
            """() => {
              const boxes=[document.querySelector('[data-view-shell="review"]'),
                           document.querySelector('#mainPage .app-view-body'),
                           document.getElementById('historiesSection')];
              return boxes.every(box=>!box||box.scrollTop<=1);
            }"""
        ), f"aucun défilement caché de coque après le deep link ({width}x{height})"
        await _measure(page, "review", width, height, audit)

        # 3. Review → Replayer: a hand is imported through the real file input and
        #    opened from the Review inbox, so the Replayer is reachable exactly like
        #    a user reaches it.
        await page.locator("#hhFileInput").set_input_files(
            files=[
                {
                    "name": FIXTURE.name,
                    "mimeType": "text/plain",
                    "buffer": importable_fixture_bytes(),
                }
            ],
        )
        await page.wait_for_function(
            "() => Array.isArray(state.hhHands) && state.hhHands.length >= 1",
            timeout=20_000,
        )
        imported = await page.evaluate("() => state.hhHands.map(h => String(h.id))")
        assert imported == [FIXTURE_HAND_ID], (
            f"la main importée doit être la fixture repro #{FIXTURE_HAND_ID} ({width}x{height}), "
            f"obtenu {imported}"
        )
        await page.click("#reviewInboxTab")
        await page.wait_for_function(
            "() => document.querySelectorAll('#hhHands .review-inbox-open').length >= 1",
            timeout=20_000,
        )
        await page.click("#hhHands .review-inbox-open")
        await _wait_view(page, "replayer")
        assert await page.evaluate(
            "() => String(state.selectedHand && state.selectedHand.id) === '"
            + FIXTURE_HAND_ID
            + "'"
        ), f"le Replayer doit afficher la main #{FIXTURE_HAND_ID} ouverte depuis l’inbox ({width}x{height})"
        await page.wait_for_function(
            "() => !!document.querySelector('#hhVisualReplay .replayer-col-left')"
            " && document.querySelectorAll('#replayerContextPanel [data-app-subview]').length === 3",
            timeout=20_000,
        )
        await _measure(page, "replayer", width, height, audit)

        await _assert_replayer_keyboard(page, width, height)
        # A tab activation is a pure visibility toggle: the shell still never scrolls.
        await _measure(page, "replayer", width, height, audit)

        # 4. Replayer → Review: the return is a pure view change that reuses the
        #    imported hands and lands back on the Review inbox.
        await page.click("#replayerBackBtn")
        await _wait_view(page, "review")
        await page.wait_for_function(
            "() => !document.getElementById('handSelectionSection').hidden"
            " && document.querySelectorAll('#hhHands .review-inbox-open').length >= 1",
            timeout=20_000,
        )
        await _measure(page, "review", width, height, audit)
        await _back_to_home(page, "review")

        # 5. Accueil → Training.
        await page.click('button.mode-card[data-app-view="training"]')
        await _wait_view(page, "training")
        await _measure(page, "training", width, height, audit)
        await page.click("#trainerBackBtn")
        await _wait_view(page, "home")

        # 6. Accueil → Stratégie Hero (embedded shell, measured on #strategyPage).
        await page.click('#quickNav a[data-product-domain="strategy"]')
        await _wait_view(page, "strategy")
        await _measure(page, "strategy", width, height, audit)
        await _back_to_home(page, "strategy")

        # 7. Accueil → Stratégie Hero editor: the mode card is a real link to the
        #    standalone page. It is navigated to and mounted, but never asserted
        #    no-scroll: the standalone editor is outside the fixed-height shell.
        await page.click('a.mode-card[data-app-view="strategy"]')
        await page.wait_for_url("**/hero-ranges.html", timeout=45_000)
        await page.wait_for_selector('[data-app-mode="strategy"]', timeout=20_000)
    finally:
        await context.close()
    return page_errors


async def run() -> None:
    assert FIXTURE.is_file() and FIXTURE_HAND_ID, f"fixture HH repro introuvable: {FIXTURE}"
    audit: list[dict] = []
    httpd, url = _serve_site()
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            try:
                for width, height in VIEWPORTS:
                    errors = await run_viewport(browser, url, width, height, audit)
                    for error in errors:
                        print(f"  page error ({width}x{height}): {error}", file=sys.stderr)
            finally:
                await browser.close()
    finally:
        httpd.shutdown()

    print("desktop modes overflow audit (document.scrollingElement):")
    for record in audit:
        if "hit_test" in record:
            # The import surface verdict is measured too (see
            # `_assert_import_surface_hit_testable`): `elementFromPoint` at the
            # centre of each box plus the Playwright click trial, printed per
            # target as the composite `reachable` verdict.
            reached = ", ".join(
                f"{selector}={'ok' if entry.get('reachable') else 'MISS'}"
                for selector, entry in record["hit_test"].items()
            )
            print(
                "  mode=review    viewport={viewport:<10} import surface[{surface}] "
                "reachability: {reached}".format(
                    reached=reached, **record
                )
            )
            continue
        print(
            "  mode={mode:<9} viewport={viewport:<10} scrollHeight={scrollHeight} <= clientHeight={clientHeight}".format(
                **record
            )
        )
    print(
        "modes desktop smoke: PASS "
        f"({len(VIEWPORTS)} viewports · {', '.join(MODES)} · transitions + Replayer keyboard "
        "+ measured Review import surface reachability: elementFromPoint hit-test + click trial)"
    )


def main() -> None:
    if async_playwright is None:
        raise SystemExit(
            "smoke_modes_desktop: Playwright is unavailable "
            f"({PLAYWRIGHT_IMPORT_ERROR}). Install the locked dependencies "
            "(requirements.lock.txt) and the pinned browser runtime "
            "(python3 tools/repro_ci_browser.py install) before running this smoke."
        )
    asyncio.run(run())


if __name__ == "__main__":
    main()

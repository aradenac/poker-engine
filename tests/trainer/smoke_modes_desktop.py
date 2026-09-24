#!/usr/bin/env python3
"""Desktop modes smoke + overflow audit (#394 · task T4).

Browser smoke of the desktop application shell. It drives the real UI (no
in-page shortcut where a click exists) and measures, **per mode and per
reference viewport**, that the document never scrolls globally:
`document.scrollingElement.scrollHeight <= clientHeight` at `1500x1000` and
`1366x768`. A mode that overflows fails explicitly with the measured values, so
the audit is never silently satisfied by a clipped shell.

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

        # 2. Accueil → Review.
        await page.click('button.mode-card[data-app-view="review"]')
        await _wait_view(page, "review")
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
        print(
            "  mode={mode:<9} viewport={viewport:<10} scrollHeight={scrollHeight} <= clientHeight={clientHeight}".format(
                **record
            )
        )
    print(
        "modes desktop smoke: PASS "
        f"({len(VIEWPORTS)} viewports · {', '.join(MODES)} · transitions + Replayer keyboard)"
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

#!/usr/bin/env python3
r"""Desktop modes smoke + overflow audit (#394 · task T4).

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
* Accueil → Stratégie Hero: the embedded `[data-view-shell="strategy"]` shell is
  reached through its real entry point, the `#strategyPage` deep link
  (`appViewForHashTarget()` maps the id onto `state.appView`, `routeFromHash()`
  resolves it at load and `hashchange` replays it — the same path the Review
  `#historiesSection` deep link above already exercises), and measured. The
  `#quickNav` Strategy entry is *not* the entry of that shell: its `href` points
  at the standalone editor, so the shell is never joined through it;
* Accueil → éditeur Stratégie Hero: the Accueil mode card is a real link to the
  standalone `./hero-ranges.html` editor and the editor URL is its **deep link**
  (#394 T6), measured three times — the query is mandatory (the query-less glob
  below never matches a rewritten URL) and each of its five parameters is
  compared to the real `#populationInput`, `#positionSelect`, `#spotSelect`,
  `#stackInput` and active hand of `#heroGrid`; a real `.hand-cell` click
  re-renders the editor and rewrites that URL **in place** (`history.length`
  unchanged, `page.go_back()` lands back on `index.html`, i.e. the editor adds a
  single entry); and `page.reload()` restores the very same context, so a
  refresh, a bookmark or a shared link reopens the displayed context instead of
  the editor defaults. The standalone page is deliberately **not** asserted
  no-scroll — it is not part of the fixed-height desktop shell;
* a minimal keyboard/focus control: `Tab` until the Replayer right-panel tabs
  are focused, then `ArrowRight`/`ArrowLeft` (roving focus + activation) and
  `Enter` (explicit keyboard activation) must only toggle pane visibility.
* a Review **race**: the mode card is clicked as soon as `setAppView` and the
  initial `document.body.dataset.appView` exist, i.e. while the asynchronous
  local restore is still opening IndexedDB, and the readiness barrier is only
  awaited afterwards. The view picked during that window must survive the end of
  the restore (`document.body.dataset.appView === "review"`, `#reviewDashboard`
  visible, `#historiesSection` hidden) — the failure mode of `cd97db1`.

Every journey additionally crosses a **readiness barrier**: `run_viewport` waits
for `state.persistenceReady === true` right after the initial navigation, before
the first mode-card click, because the local restore settles `state.appView` when
it finishes. The barrier waits on that real readiness signal only — never a
retry, a skip or a mask of a failure: a restore that never settles fails here
instead of letting the journey race it.

The URL globs are audited. `grep -rn "wait_for_url" --include=*.py .` returns
exactly two call sites — step 7 below and
`tests/hero_ranges/smoke_hero_compliance_browser.py:209` — and both use the
query-tolerant `**/hero-ranges.html?**` convention, because the editor rewrites
its own URL (`syncDeepLink()`, `site/hero-ranges-app.js:126`) with
`history.replaceState()` as soon as it renders. A Playwright glob is anchored, so
the query-less `**/hero-ranges.html` never matches
`hero-ranges.html?population=…&hand=AA`: measured with the Playwright 1.55
matcher itself (`globToRegexPattern("**/hero-ranges.html")` →
`^((?:[^/]*(?:/|$))*)hero-ranges\.html$`, which the rewritten URL does not
satisfy, while `**/hero-ranges.html?**` → `…hero-ranges\.html\?([^/]*)$` does).
The `?**` tail is therefore not cosmetic: it is what makes the *rewritten* URL
the measured one, and an editor that stopped writing its deep link would fail the
wait instead of passing it silently.

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
from urllib.parse import parse_qsl, urlsplit

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

# #394 T2 — the Review shell is a tab row of sub-views. Landing on Review must
# select exactly one of them (`pilotage`), scoped to the Review shell so a
# pytest/smoke of another view can never satisfy it.
REVIEW_SELECTED_SUBTABS_JS = """() => Array.from(
  document.querySelectorAll('[data-view-shell="review"] [data-app-subview][aria-selected="true"]')
).map(tab => tab.dataset.appSubview)"""

# #394 T2 — measured verdict of the Review race. Every field is read back from
# the page *after* the restore settled, so a view overwritten by the restore is
# named with its measured values instead of a bare boolean. Pane visibility is
# measured separately with Playwright's own visibility check (the same
# instrument the Review landing assertions use), so a shell that the restore
# remounted over the click cannot pass through this probe.
RACE_PROBE_JS = """() => {
  return {
    mounted: document.body.dataset.appView || '',
    appView: state.appView,
    userNavigated: !!state.userNavigated,
    persistenceReady: state.persistenceReady === true
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

# #394 T6 — the standalone Stratégie Hero editor publishes its rendered context
# as a deep link: `syncDeepLink()` (`site/hero-ranges-app.js:126`) rewrites the
# address bar in place with these five parameters every time it renders. They are
# therefore mandatory in the measured URL and each one is compared to the real
# control of the page (`#populationInput`, `#positionSelect`, `#spotSelect`,
# `#stackInput`) and to the active hand of `#heroGrid` below — never assumed from
# the href that led to the page.
EDITOR_DEEP_LINK_PARAMS = ("population", "position", "spot", "stack", "hand")

EDITOR_CONTEXT_JS = """() => {
  const value = (id) => {
    const el = document.getElementById(id);
    return el ? String(el.value) : null;
  };
  return {
    population: value('populationInput'),
    position: value('positionSelect'),
    spot: value('spotSelect'),
    stack: value('stackInput'),
    selectedHands: Array.from(
      document.querySelectorAll('#heroGrid .hand-cell.selected[data-hand]')
    ).map((cell) => cell.dataset.hand),
    title: String((document.getElementById('selectedHandTitle') || {}).textContent || '').trim()
  };
}"""

# `[data-app-mode="strategy"]` belongs to the served HTML, so it exists before any
# script runs. The 169 cells of `#heroGrid` are rendered by `renderAll()`, which
# calls `syncDeepLink()` first: the grid is the observable readiness signal of
# the editor (and of its deep link).
EDITOR_READY_JS = (
    "() => document.querySelectorAll('#heroGrid .hand-cell[data-hand]').length === 169"
)


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


# #394 T2 — readiness barrier of the asynchronous local restore
# (`restoreLocalState()` opens IndexedDB and only then settles `state.appView`).
# A mode card clicked while that restore is still in flight is a race, so the
# normal journey crosses this barrier right after the initial navigation and
# before its first mode-card click. It waits on the real readiness signal
# (`state.persistenceReady`) and is neither a retry, a skip nor a mask: a restore
# that never settles fails here on the timeout with that state measured.
READINESS_TIMEOUT_MS = 30_000


async def _wait_persistence_ready(page, timeout: int = READINESS_TIMEOUT_MS) -> None:
    await page.wait_for_function("() => state.persistenceReady===true", timeout=timeout)


def _review_race_verdict(probe: dict, width: int, height: int) -> str:
    """Explicit measured verdict of the Review race (no retry, no skip)."""
    return (
        f"course Review (viewport {width}x{height}) — "
        f"document.body.dataset.appView={probe.get('mounted')!r} "
        f"state.appView={probe.get('appView')!r} "
        f"state.userNavigated={probe.get('userNavigated')} "
        f"state.persistenceReady={probe.get('persistenceReady')} "
        f"#reviewDashboard visible={probe.get('reviewDashboardVisible')} "
        f"#historiesSection masqué={probe.get('historiesHidden')}"
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


def _editor_query(page_url: str) -> dict[str, str]:
    """Deep-link query of the editor URL (last value wins, blanks kept)."""
    query: dict[str, str] = {}
    for key, value in parse_qsl(urlsplit(page_url).query, keep_blank_values=True):
        query[key] = value
    return query


def _editor_deep_link_verdict(
    page_url: str, measured: dict, step: str, width: int, height: int
) -> str:
    """Explicit measured verdict of the editor deep link (no retry, no skip)."""
    return (
        f"deep link de l'éditeur ({step}, viewport {width}x{height}) — url={page_url} "
        f"query={_editor_query(page_url)} "
        f"#populationInput={measured.get('population')!r} "
        f"#positionSelect={measured.get('position')!r} "
        f"#spotSelect={measured.get('spot')!r} "
        f"#stackInput={measured.get('stack')!r} "
        f"mains actives={measured.get('selectedHands')!r} "
        f"#selectedHandTitle={measured.get('title')!r}"
    )


async def _wait_editor_ready(page, timeout: int = 20_000) -> None:
    await page.wait_for_function(EDITOR_READY_JS, timeout=timeout)


async def _measure_editor_deep_link(
    page, step: str, width: int, height: int, audit: list[dict]
) -> dict:
    """Measure the editor deep link against the real controls of the page.

    Every verdict is measured, never deduced: the five parameters of `page.url`
    are mandatory and compared to `#populationInput`, `#positionSelect`,
    `#spotSelect`, `#stackInput` and the active hand of `#heroGrid`, and
    `history.length` is read back at the same instant so the in-place rewrite can
    be asserted around a real interaction (arrival, rewrite, reload). A failure
    names the URL, the parsed query and the measured controls.
    """
    page_url = page.url
    measured = await page.evaluate(EDITOR_CONTEXT_JS)
    query = _editor_query(page_url)
    record = {
        "mode": "strategy-editor",
        "editor_deep_link": True,
        "step": step,
        "viewport": f"{width}x{height}",
        "url": page_url,
        "query": query,
        "controls": measured,
        "historyLength": await page.evaluate("() => history.length"),
    }
    audit.append(record)
    verdict = _editor_deep_link_verdict(page_url, measured, step, width, height)

    assert urlsplit(page_url).path.endswith("/hero-ranges.html"), (
        f"la page mesurée doit être l'éditeur autonome hero-ranges.html — {verdict}"
    )
    for key in EDITOR_DEEP_LINK_PARAMS:
        assert query.get(key), (
            f"le paramètre `{key}` du deep link de l'éditeur est obligatoire et non vide "
            f"— {verdict}"
        )
    try:
        deep_link_stack = float(query["stack"])
    except ValueError:
        raise AssertionError(
            f"le paramètre `stack` du deep link de l'éditeur doit être numérique — {verdict}"
        ) from None
    assert query["population"] == measured["population"], (
        f"population du deep link ≠ #populationInput — {verdict}"
    )
    assert query["position"] == measured["position"], (
        f"position du deep link ≠ #positionSelect — {verdict}"
    )
    assert query["spot"] == measured["spot"], (
        f"spot du deep link ≠ #spotSelect — {verdict}"
    )
    assert deep_link_stack == float(measured["stack"]), (
        f"stack du deep link ≠ #stackInput — {verdict}"
    )
    assert measured["selectedHands"] == [query["hand"]], (
        f"la main active de #heroGrid doit être exactement la main du deep link — {verdict}"
    )
    assert measured["title"] == query["hand"], (
        f"#selectedHandTitle doit porter la main du deep link — {verdict}"
    )
    return record


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
        # #394 T2 — readiness barrier, placed before the first mode-card click:
        # the asynchronous local restore settles `state.appView` when it ends, so
        # the journeys below start from a settled view. It is a wait on a real
        # readiness signal, not a retry, a skip or a mask of a failure.
        await _wait_persistence_ready(page)
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
        # #394 T2 — landing on Review selects exactly its Pilotage sub-view: the
        # tab row of the Review shell must carry a single `aria-selected="true"`.
        selected_subtabs = await page.evaluate(REVIEW_SELECTED_SUBTABS_JS)
        assert selected_subtabs == ["pilotage"], (
            "l'atterrissage Accueil → Review doit sélectionner exactement l'onglet Pilotage "
            f"({width}x{height}) — onglets sélectionnés: {selected_subtabs}"
        )
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
        #    The shell is joined through its real entry point, the `#strategyPage`
        #    deep link: `appViewForHashTarget()` maps that id onto `state.appView`
        #    and `routeFromHash()` resolves it at load (`hashchange` replays it) —
        #    the very path the Review `#historiesSection` deep link above already
        #    exercises. The `#quickNav` Strategy entry is *not* used: its href is
        #    the standalone editor (`./hero-ranges.html`), whose real link is
        #    measured by the Accueil mode card in step 7.
        await page.goto(f"{url}#strategyPage", wait_until="domcontentloaded", timeout=45_000)
        # The reload replays that URL as a *load-time* deep link — the bookmark /
        # shared-link path (`routeFromHash()` runs at the end of the asynchronous
        # local restore) — so the shell is proven to be reached by the deep link,
        # not merely kept mounted by the hash change.
        await page.reload(wait_until="domcontentloaded", timeout=45_000)
        await _wait_persistence_ready(page)
        await _wait_view(page, "strategy")
        assert await page.evaluate("() => String(window.location.hash)") == "#strategyPage", (
            "l'entrée mesurée doit être le deep link #strategyPage "
            f"({width}x{height}) — hash={await page.evaluate('() => window.location.hash')!r}"
        )
        await _measure(page, "strategy", width, height, audit)
        await _back_to_home(page, "strategy")
        # The deep-link fragment of the *test's own* entry is rewritten back to the
        # plain Accueil URL before step 7, so the entry the editor returns to (T6,
        # `page.go_back()`) is `index.html` without a residual fragment. It is an
        # in-place rewrite of the current entry (`history.replaceState`), not a
        # navigation: measured, `page.goto(url)` from `url#strategyPage` is not a
        # same-document fragment navigation in the pinned Chromium — it reloads the
        # document and the restored local preferences remount the strategy shell
        # (history 3 → 4, the Accueil is lost), while `replaceState` keeps the
        # mounted Accueil, adds no entry and fires no `hashchange`.
        await page.evaluate("() => history.replaceState(null, '', location.pathname)")
        assert page.url == url, (
            "le fragment du deep link doit être re-tiré de l'entrée d'historique, "
            f"sans quitter l'Accueil ({width}x{height}) — obtenu {page.url!r}"
        )
        await _wait_view(page, "home")

        # 7. Accueil → Stratégie Hero editor: the mode card is a real link to the
        #    standalone page, and the URL it lands on is the editor deep link
        #    (#394 T6). Three measured verdicts: (1) the query is mandatory and
        #    coherent with the real controls of the editor, (2) a real
        #    `#heroGrid` click re-renders the editor and rewrites that URL in
        #    place (no history entry, and going back lands on `index.html`), and
        #    (3) `page.reload()` restores the very same context. The page is never
        #    asserted no-scroll: the standalone editor is outside the fixed-height
        #    shell.
        await page.click('a.mode-card[data-app-view="strategy"]')
        # A Playwright glob is anchored: `**/hero-ranges.html` never matches the
        # URL `syncDeepLink()` rewrites (`hero-ranges.html?population=…&hand=AA`).
        # `**/hero-ranges.html?**` is the repo convention
        # (tests/hero_ranges/smoke_hero_compliance_browser.py:209) and is only
        # satisfied by a URL *carrying* a query, so the rewrite is measured
        # instead of being bypassed.
        await page.wait_for_url("**/hero-ranges.html?**", timeout=45_000)
        await page.wait_for_selector('[data-app-mode="strategy"]', timeout=20_000)
        await _wait_editor_ready(page)
        arrival = await _measure_editor_deep_link(page, "arrivée", width, height, audit)

        # (2) A real interaction that re-renders the editor: the click on a
        #     `#heroGrid` hand cell rewrites the deep link **in place**.
        target_hand = "KK" if arrival["query"]["hand"] != "KK" else "QQ"
        history_before = arrival["historyLength"]
        await page.click(f'#heroGrid .hand-cell[data-hand="{target_hand}"]')
        await page.wait_for_function(
            "(hand) => new URLSearchParams(location.search).get('hand') === hand",
            arg=target_hand,
            timeout=10_000,
        )
        rewritten = await _measure_editor_deep_link(page, "réécriture", width, height, audit)
        assert rewritten["query"]["hand"] == target_hand, (
            "le clic sur une case de #heroGrid doit écrire la main cliquée dans le deep link "
            f"({width}x{height}) — attendu {target_hand!r}, "
            f"obtenu {rewritten['query']['hand']!r} (url={rewritten['url']})"
        )
        assert rewritten["historyLength"] == history_before, (
            "la réécriture d'URL de l'éditeur doit être en place (`history.replaceState`), "
            "donc sans entrée d'historique ajoutée "
            f"({width}x{height}) — history.length avant={history_before}, "
            f"après={rewritten['historyLength']}, url={rewritten['url']}"
        )
        for key in ("population", "position", "spot", "stack"):
            assert rewritten["query"][key] == arrival["query"][key], (
                f"un clic sur une main ne doit changer que `hand` dans le deep link "
                f"(`{key}`) ({width}x{height}) — arrivée {arrival['query']!r}, "
                f"réécriture {rewritten['query']!r}"
            )

        # (3) The reload restores the context of the deep link: same parameters,
        #     same controls, same active hand — and still one single entry.
        await page.reload(wait_until="domcontentloaded", timeout=45_000)
        await _wait_editor_ready(page)
        restored = await _measure_editor_deep_link(page, "reload", width, height, audit)
        assert restored["query"] == rewritten["query"], (
            "le reload doit réécrire exactement le même deep link "
            f"({width}x{height}) — avant {rewritten['query']!r}, après {restored['query']!r}"
        )
        assert restored["controls"] == rewritten["controls"], (
            "le reload doit restaurer les mêmes contrôles et la même main active "
            f"({width}x{height}) — avant {rewritten['controls']!r}, "
            f"après {restored['controls']!r}"
        )
        assert restored["historyLength"] == rewritten["historyLength"], (
            "un reload ne doit pas ajouter d'entrée d'historique "
            f"({width}x{height}) — avant={rewritten['historyLength']}, "
            f"après={restored['historyLength']}"
        )

        # The back navigation lands on the Accueil entry: navigating to the editor
        # added exactly one history entry, the URL rewrite zero.
        await page.go_back(wait_until="domcontentloaded", timeout=45_000)
        back_url = urlsplit(page.url)
        assert back_url.path.endswith("/index.html") and not back_url.query and not back_url.fragment, (
            "page.go_back() depuis l'éditeur doit revenir à l'Accueil `index.html` nu "
            f"(une seule entrée d'historique, réécriture en place) ({width}x{height}) — "
            f"obtenu {page.url} (history.length={restored['historyLength']})"
        )
    finally:
        await context.close()
    return page_errors


async def run_review_race_viewport(
    browser, url: str, width: int, height: int, audit: list[dict]
) -> list[str]:
    """#394 T2 — Review mode-card race, in its own fresh context, per viewport.

    Reproduces the CI failure of `cd97db1`: the Review mode card is clicked while
    the asynchronous local restore is still opening IndexedDB, so the restore is
    what completes *after* the user navigation. With the T1 guard the picked view
    is final and the race resolves to Review; without it the restore re-applies
    the restored/default view over the click (the view is overwritten).

    The click waits only for the two probes that make the card clickable at all
    (`typeof setAppView === 'function'` — the script has parsed — and the initial
    `document.body.dataset.appView` mounted by the synchronous `updateAppView()`),
    never for readiness. The readiness barrier is crossed afterwards and the
    verdict is then *measured* (`document.body.dataset.appView`, both panes,
    `state.userNavigated`, `state.persistenceReady`), so a view overwritten after
    the navigation fails with those values. There is no retry and no skip; the
    scenario also stays green when the restore had already finished before the
    click (the click then simply selects Review on a settled page).
    """
    context = await browser.new_context(viewport={"width": width, "height": height})
    page = await context.new_page()
    page_errors: list[str] = []
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        await page.wait_for_function(
            "() => typeof setAppView === 'function' && !!document.body.dataset.appView",
            timeout=45_000,
        )
        await page.click('button.mode-card[data-app-view="review"]', timeout=10_000)
        # Only now does the race resolve: cross the readiness barrier (the restore
        # has settled `state.appView` and `state.persistenceReady`), then read the
        # verdict back from the page.
        await _wait_persistence_ready(page)
        probe = await page.evaluate(RACE_PROBE_JS)
        # The two panes are measured with Playwright's own visibility check, the
        # same instrument the Review landing assertions use: a shell that the
        # restore remounted over the click makes `#reviewDashboard` invisible even
        # though its `hidden` property was never touched.
        probe["reviewDashboardVisible"] = await page.locator("#reviewDashboard").is_visible()
        probe["historiesHidden"] = await page.locator("#historiesSection").is_hidden()
        audit.append(
            {
                "race": True,
                "mode": "review",
                "viewport": f"{width}x{height}",
                "mounted": probe["mounted"],
                "appView": probe["appView"],
                "userNavigated": probe["userNavigated"],
                "persistenceReady": probe["persistenceReady"],
                "reviewDashboardVisible": probe["reviewDashboardVisible"],
                "historiesHidden": probe["historiesHidden"],
            }
        )
        assert probe["mounted"] == "review", (
            "la vue Review sélectionnée pendant l'ouverture d'IndexedDB a été écrasée par la "
            f"fin de la restauration locale ({width}x{height}) — {_review_race_verdict(probe, width, height)}"
        )
        assert probe["reviewDashboardVisible"], (
            "le panneau Pilotage (#reviewDashboard) doit rester visible après la course "
            f"({width}x{height}) — {_review_race_verdict(probe, width, height)}"
        )
        assert probe["historiesHidden"], (
            "le panneau Import (#historiesSection) doit rester masqué après la course "
            f"({width}x{height}) — {_review_race_verdict(probe, width, height)}"
        )
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
                    # #394 T2 — the Review race runs per viewport too, in its own
                    # fresh context: the journey above is deterministic thanks to
                    # the readiness barrier, this one deliberately races it.
                    race_errors = await run_review_race_viewport(
                        browser, url, width, height, audit
                    )
                    for error in race_errors:
                        print(
                            f"  page error (course Review, {width}x{height}): {error}",
                            file=sys.stderr,
                        )
            finally:
                await browser.close()
    finally:
        httpd.shutdown()

    print("desktop modes overflow audit (document.scrollingElement):")
    for record in audit:
        if record.get("race"):
            # #394 T2 — the Review race verdict, measured after the restore
            # settled: which view survived the race and which panes are mounted.
            print(
                "  mode=review    viewport={viewport:<10} course Review: "
                "persistenceReady={persistenceReady} mounted={mounted} "
                "userNavigated={userNavigated} #reviewDashboard={reviewDashboardVisible} "
                "#historiesSection masqué={historiesHidden}".format(**record)
            )
            continue
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
        if record.get("editor_deep_link"):
            # #394 T6 — the editor deep link verdict: the parsed query, the real
            # controls of the editor and the active hand, plus `history.length`
            # (asserted around a real `#heroGrid` click).
            print(
                "  mode=strategy-editor viewport={viewport:<10} deep link[{step}]: "
                "query={query} contrôles=[population:{controls[population]} "
                "position:{controls[position]} spot:{controls[spot]} "
                "stack:{controls[stack]}] main active={controls[selectedHands]} "
                "history.length={historyLength}".format(**record)
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
        "+ measured Review import surface reachability: elementFromPoint hit-test + click trial "
        "+ persistenceReady readiness barrier + Review race scenario "
        "+ #strategyPage deep link of the embedded shell "
        "+ editor deep link (query↔contrôles, réécriture en place, reload))"
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

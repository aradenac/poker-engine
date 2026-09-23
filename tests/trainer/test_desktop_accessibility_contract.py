#!/usr/bin/env python3
"""Desktop app-shell contract (#394).

Two layers are checked.

1. Static contract (always run, no browser, no server):

   * `html`/`body` are pinned to `100dvh` with `overflow:hidden` for the desktop
     application shell (>= 901px) — the document never scrolls globally;
   * every application view (`home`, `review`, `spotlab`, `strategy`, `training`,
     `replayer`) is a fixed-height shell (header + body) whose body cannot leak
     content: the excess has to travel through the reusable sub-view pattern
     (`.app-view-body` / `.app-subviews` / `.app-subview-tab` /
     `.app-subview-panel`) or through the bounded paginated list
     (`.app-list-pager`);
   * the Review view (`#mainPage.wrap`) is split into constrained sub-views and
     its inbox is a bounded paginated list instead of one long scroll box;
   * the only `overflow:auto|scroll` rules that may exist in the desktop scope
     are the ones declared in `APP_ALLOWED_SCROLL_ZONES`, each with a written
     justification. Everything else is `overflow:hidden`, so nothing reachable
     can be lost behind a clipped shell;
   * the `<901px` rendering is untouched: every shell rule lives in a
     `@media(min-width:901px)` block (e.g. the preserved dense-desktop label
     floor), and the narrow-viewport scroll boxes stay declared inside
     `max-width` blocks.

2. Browser measurement (opt-in, `python3 ... --browser` or
   `DESKTOP_SHELL_BROWSER_CHECK=1`): serves `site/index.html` locally and asserts
   `document.scrollingElement.scrollHeight <= clientHeight` at 1500x1000 and
   1366x768 for home/review/spotlab/training/replayer. It is skipped when
   Playwright is unavailable so the frozen static CI job stays hermetic.
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX = (ROOT / 'site/index.html').read_text(encoding='utf-8')
TRAINER_CSS = (ROOT / 'site/trainer.css').read_text(encoding='utf-8')

DESKTOP_MIN_WIDTH = 901
SHELL_VIEWS = ('home', 'review', 'spotlab', 'strategy', 'training', 'replayer')
MEASURED_VIEWS = ('home', 'review', 'spotlab', 'training', 'replayer')
MEASURED_VIEWPORTS = ((1500, 1000), (1366, 768))

# `overflow:auto|scroll` is forbidden in the desktop scope unless the rule is one
# of the bounded, justified zones below. This regex deliberately ignores
# `overflow:hidden|visible|clip`.
SCROLL_DECLARATION = re.compile(r'overflow(?:-x|-y)?\s*:\s*(?:auto|scroll)')
ALLOWED_SCROLL_ENTRY = re.compile(
    r'\{selector:"([^"]+)",scope:"([^"]+)",kind:"([^"]+)",reason:"([^"]+)"\}'
)


# --------------------------------------------------------------------------- #
# Minimal CSS reader: flattens nested at-rules so each style rule is reported
# with the media condition that guards it.
# --------------------------------------------------------------------------- #
def css_rules(css: str, media: str | None = None) -> list[tuple[str | None, str, str]]:
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    rules: list[tuple[str | None, str, str]] = []
    index = 0
    buffer = ''
    while index < len(css):
        char = css[index]
        if char == '{':
            prelude = buffer.strip()
            buffer = ''
            depth = 1
            cursor = index + 1
            while cursor < len(css) and depth > 0:
                if css[cursor] == '{':
                    depth += 1
                elif css[cursor] == '}':
                    depth -= 1
                cursor += 1
            body = css[index + 1:cursor - 1]
            if prelude.startswith('@'):
                if prelude.lower().startswith('@media'):
                    rules.extend(css_rules(body, prelude[len('@media'):].strip()))
            else:
                rules.append((media, prelude, body))
            index = cursor
            continue
        if char == '}':
            buffer = ''
            index += 1
            continue
        buffer += char
        index += 1
    return rules


def applies_at_desktop(media: str | None) -> bool:
    """True when the rule can apply at >= 901px viewport width."""
    if not media:
        return True
    for value in re.findall(r'max-width\s*:\s*(\d+)px', media):
        if int(value) < DESKTOP_MIN_WIDTH:
            return False
    return True


def desktop_scroll_selectors() -> dict[str, str]:
    found: dict[str, str] = {}
    for label, css in (('site/index.html', INDEX), ('site/trainer.css', TRAINER_CSS)):
        for media, selector, declarations in css_rules(css):
            if not applies_at_desktop(media):
                continue
            if SCROLL_DECLARATION.search(declarations):
                found.setdefault(selector, f'{label} ({media or "no media"})')
    return found


def allowed_scroll_zones() -> list[dict[str, str]]:
    zones = []
    for selector, scope, kind, reason in ALLOWED_SCROLL_ENTRY.findall(INDEX):
        zones.append(
            {
                'selector': selector,
                'scope': scope,
                'kind': kind,
                'reason': reason,
            }
        )
    return zones


# --------------------------------------------------------------------------- #
# Static contract
# --------------------------------------------------------------------------- #
def check_modal_accessibility_contract() -> None:
    # Both primary dialogs expose accessible dialog semantics and a fallback focus target.
    assert 'class="population-modal" role="dialog" aria-modal="true" aria-labelledby="populationRangeModalTitle" tabindex="-1"' in INDEX
    assert 'class="action-verdict-detail-modal" role="dialog" aria-modal="true" aria-labelledby="actionDetailModalTitle" tabindex="-1"' in INDEX

    # One shared keyboard/focus contract handles initial focus, trap, Escape and restoration.
    for marker in (
        'const modalFocusOrigins=new WeakMap()',
        'function modalFocusableElements(backdrop)',
        'function openAccessibleModal(backdrop',
        'function closeAccessibleModal(backdrop)',
        'function handleAccessibleModalKeydown(e)',
        'document.addEventListener("keydown",handleAccessibleModalKeydown)',
        'origin.focus({preventScroll:true})',
    ):
        assert marker in INDEX, marker
    assert 'if(e.key!=="Tab")return;' in INDEX
    assert 'if(e.key==="Escape")' in INDEX
    assert 'e.shiftKey' in INDEX

    # Each modal uses the common focus lifecycle rather than hand-rolled visibility only.
    assert 'openAccessibleModal(actionDetailModal,{initialFocus:()=>actionDetailModalClose})' in INDEX
    assert 'closeAccessibleModal(actionDetailModal)' in INDEX
    assert 'openAccessibleModal(populationRangeModal,{initialFocus:()=>populationRangeModalClose})' in INDEX
    assert 'closeAccessibleModal(populationRangeModal)' in INDEX

    # Keyboard focus is visibly distinguishable, and current replay state is semantic, not color-only.
    assert ':focus-visible' in INDEX
    assert 'aria-current="step"' in INDEX

    # Critical dense desktop labels get an explicit >=10 px floor; mobile is not part of this issue.
    desktop = INDEX.split('@media(min-width:901px){', 1)[1].split('}', 1)[0]
    for selector in ('.decision-primary-card .k', '.population-modal-cell .freq', '.street-event .action-badge'):
        assert selector in desktop, selector
    assert 'font-size:10px' in desktop


def check_desktop_shell_contract() -> None:
    rules = css_rules(INDEX)

    def declarations_for(selector: str, media: str | None = None) -> str | None:
        for rule in rules:
            if rule[0] == media and rule[1] == selector:
                return rule[2]
        return None

    # html/body are pinned to 100dvh without a global scroll, desktop only.
    shell = declarations_for('html,body', '(min-width:901px)')
    assert shell is not None, 'the desktop shell media block must declare html/body'
    assert 'height:100dvh' in shell and 'max-height:100dvh' in shell and 'overflow:hidden' in shell, shell
    body = declarations_for('body', '(min-width:901px)')
    assert body is not None, 'body must be a flex column so a view shell can own the viewport height'
    assert 'display:flex' in body and 'flex-direction:column' in body, body
    # The narrow rendering keeps its normal document flow: the base body rule is
    # untouched, and no viewport-height/scroll rule escapes the desktop block.
    base_body = declarations_for('body')
    assert base_body is not None and not SCROLL_DECLARATION.search(base_body), base_body
    for media, selector, declarations in rules:
        if selector in ('html', 'body', 'html,body') and SCROLL_DECLARATION.search(declarations):
            raise AssertionError(f'global scroll reintroduced by {selector} under {media or "no media"}')
        if selector in ('html', 'body', 'html,body') and '100dvh' in declarations:
            assert media and 'min-width:901px' in media, (media, selector, declarations)

    # Every application view is a fixed-height shell (header + body), never a scroll container.
    view_shell = declarations_for('[data-view-shell]', '(min-width:901px)')
    assert view_shell is not None, 'the desktop app-shell block must declare [data-view-shell]'
    for token in ('display:flex', 'flex-direction:column', 'height:100dvh', 'overflow:hidden'):
        assert token in view_shell, (token, view_shell)
    assert '.app-view-head{flex:0 0 auto' in INDEX
    assert '.app-view-body{flex:1 1 auto;overflow:hidden}' in INDEX
    for view in SHELL_VIEWS:
        assert f'data-view-shell="{view}"' in INDEX, view

    # The reusable sub-view / tab / pagination pattern must exist and be used.
    for marker in (
        '.app-view-body{',
        '.app-subviews{',
        '.app-subview-tab{',
        '.app-subview-panel{',
        '.app-subview-panel[hidden]{display:none!important}',
        '.app-list-pager{',
        '.app-list-pager[hidden]{display:none!important}',
        'function activateAppSubview(name){',
        'function activateAppSubviewForTarget(id){',
        'function appSubviewForHashTarget(id){',
        'const APP_HASH_SUBVIEWS={',
    ):
        assert marker in INDEX, marker
    assert 'data-app-subview="' in INDEX and 'data-app-subview-panel="' in INDEX
    assert 'role="tablist"' in INDEX and 'role="tab"' in INDEX

    # #mainPage.wrap (Review) is split into constrained sub-views, and its inbox
    # is a bounded paginated list instead of a long internal scroll box.
    review = INDEX.split('<div id="mainPage"', 1)[1].split('<div id="strategyPage"', 1)[0]
    assert '<div class="app-view-body">' in review, 'Review must expose a shell body'
    for subview in ('pilotage', 'inbox'):
        assert f'data-app-subview="{subview}"' in review, subview
    for panel in ('reviewDashboard', 'historiesSection', 'handSelectionSection'):
        assert f'id="{panel}"' in review, panel
    # The landing pane keeps the dashboard and the import surface together: a
    # deep link or the historical `#historiesSection` anchor must not hide it.
    assert 'id="historiesSection" class="panel wide app-subview-panel" data-app-subview-panel="pilotage"' in review
    assert 'id="reviewPilotageTab"' in review and 'aria-selected="true"' in review
    assert 'data-app-subview-panel="inbox" hidden' in review
    assert 'id="hhListPager"' in review and 'id="hhPagePrev"' in review and 'id="hhPageNext"' in review
    assert 'class="hh-selection-section panel app-subview-panel"' in review
    assert 'max-height:310px;overflow:auto' not in INDEX
    assert 'function renderReviewInboxPage(hands,byId){' in INDEX
    assert 'hhHandsEl.scrollHeight<=hhHandsEl.clientHeight+1' in INDEX
    assert 'hhPagePrev?.addEventListener("click"' in INDEX and 'hhPageNext?.addEventListener("click"' in INDEX

    # Spot Lab and Training/Replayer also expose their dense surfaces as sub-views.
    spotlab = INDEX.split('<div id="spotlabPage"', 1)[1].split('<div id="mainPage"', 1)[0]
    for panel, name in (
        ('opponentsSection', 'spotlab-situation'),
        ('cardsSection', 'spotlab-board'),
        ('rangeDisplaySection', 'spotlab-range'),
        ('equitySection', 'spotlab-equity'),
    ):
        assert f'data-app-subview-panel="{name}"' in spotlab, panel
    trainer = INDEX.split('<div id="trainerPage"', 1)[1].split('<div id="replayerPage"', 1)[0]
    for thumb in ('trainer-coaching', 'trainer-session', 'trainer-profiles', 'trainer-test'):
        assert f'data-app-subview="{thumb}"' in trainer, thumb
    replayer = INDEX.split('<div id="replayerPage"', 1)[1].split('<script src="./compute-scheduler.js">', 1)[0]
    for thumb in ('replay-table', 'replay-detail'):
        assert f'data-app-subview="{thumb}"' in replayer, thumb

    # The matrix grid is bounded by its pane: it never scrolls on desktop.
    assert '.matrixwrap{overflow:hidden;margin-top:12px}' in INDEX


def check_allowed_scroll_zones() -> None:
    zones = allowed_scroll_zones()
    assert zones, 'APP_ALLOWED_SCROLL_ZONES must document the tolerated scroll zones'
    by_selector = {zone['selector']: zone for zone in zones}
    assert len(by_selector) == len(zones), 'duplicate selector in APP_ALLOWED_SCROLL_ZONES'
    for zone in zones:
        assert zone['scope'] in ('desktop', 'dialogue'), zone
        assert zone['kind'], zone
        assert len(zone['reason']) >= 40, zone
        if zone['scope'] == 'dialogue':
            assert 'dialog' in zone['reason'].lower() or 'Dialogue' in zone['reason'], zone

    declared = desktop_scroll_selectors()
    assert set(declared) == set(by_selector), (
        'desktop-scope overflow:auto|scroll must match APP_ALLOWED_SCROLL_ZONES',
        {selector: origin for selector, origin in declared.items() if selector not in by_selector},
        sorted(set(by_selector) - set(declared)),
    )

    # The declared zones are classes, never a bare element selector: they must be
    # opted into explicitly by the markup.
    for selector in declared:
        if selector.startswith('.'):
            continue
        assert selector.startswith('.'), selector

    # No view markup may carry an inline scroll style.
    view_region = INDEX.split('<div id="homePage"', 1)[1].split('<script src="./compute-scheduler.js">', 1)[0]
    for forbidden in ('style="overflow', 'overflow:auto', 'overflow:scroll', 'overflow-x:auto', 'overflow-y:auto'):
        assert forbidden not in view_region, forbidden

    # The bounded zones are opted in by the markup, not by a global rule.
    for selector in ('.app-scroll-zone', '.app-canvas-pane', '.app-scroll-x'):
        class_name = selector[1:]
        assert f'class="{class_name}"' in INDEX or f'{class_name}"' in INDEX, selector

    # Narrow viewports stay out of the desktop contract: their scroll boxes live
    # inside max-width blocks and are never applied at >= 901px.
    narrow = [rule for rule in css_rules(INDEX) if rule[0] and not applies_at_desktop(rule[0]) and SCROLL_DECLARATION.search(rule[2])]
    assert narrow, 'the mobile scroll boxes must stay declared in max-width blocks'


# --------------------------------------------------------------------------- #
# Optional browser measurement of acceptance criterion "no global scroll".
# --------------------------------------------------------------------------- #
MEASURE_JS = """async (view) => {
  if(view==='home'){ setAppView('home'); }
  else if(view==='training'){ if(typeof openAppView==='function') openAppView('training'); else setAppView('training'); }
  else { setAppView(view); }
  await new Promise(requestAnimationFrame);
  await new Promise(requestAnimationFrame);
  const root=document.scrollingElement;
  return {
    mounted:document.body.dataset.appView,
    scrollHeight:root.scrollHeight,
    clientHeight:root.clientHeight,
    shell:!!document.querySelector(`[data-view-shell="${document.body.dataset.appView}"]`)
  };
}"""


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args, **kwargs):  # pragma: no cover - silence the server
        return


def _serve_site():
    handler = partial(_QuietHandler, directory=str(ROOT / 'site'))
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f'http://127.0.0.1:{httpd.server_address[1]}/index.html'


async def measure_desktop_shell() -> None:
    from playwright.async_api import async_playwright  # imported lazily on purpose

    httpd, url = _serve_site()
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
            for width, height in MEASURED_VIEWPORTS:
                page = await browser.new_page(viewport={'width': width, 'height': height})
                await page.goto(url, wait_until='domcontentloaded', timeout=45_000)
                await page.wait_for_function("typeof setAppView === 'function' && !!document.body.dataset.appView", timeout=20_000)
                for view in MEASURED_VIEWS:
                    result = await page.evaluate(MEASURE_JS, view)
                    assert result['scrollHeight'] <= result['clientHeight'], (
                        f'{view} scrolls globally at {width}x{height}',
                        result,
                    )
                await page.close()
            await browser.close()
    finally:
        httpd.shutdown()
    print('desktop shell browser measurement: OK')


def main() -> None:
    check_modal_accessibility_contract()
    check_desktop_shell_contract()
    check_allowed_scroll_zones()
    print('desktop accessibility contract checks: OK')

    wants_browser = '--browser' in sys.argv or os.environ.get('DESKTOP_SHELL_BROWSER_CHECK') == '1'
    if not wants_browser:
        return
    try:
        import playwright.async_api  # noqa: F401
    except Exception:  # pragma: no cover - optional dependency
        print('desktop shell browser measurement: SKIPPED (playwright unavailable)')
        return
    asyncio.run(measure_desktop_shell())


if __name__ == '__main__':
    main()

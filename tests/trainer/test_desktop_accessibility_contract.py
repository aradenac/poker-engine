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
   * the `<901px` rendering keeps its historical document flow: the `100dvh` /
     `overflow` rules live in a `@media(min-width:901px)` block (e.g. the
     preserved dense-desktop label floor), and the narrow-viewport scroll boxes
     stay declared inside `max-width` blocks;
   * the reusable sub-view / tab / pane pattern is **global**, not re-scoped
     into `@media(min-width:901px)`: `.app-subviews`, `.app-subview-tab`,
     `.app-subview-panel` and `.app-subview-panel[hidden]{display:none!important}`
     are base rules declared outside every media query, `activateAppSubview`
     toggles `hidden` with no width guard, and every pane has exactly one owning
     tab — so the dense views stay tabbed below `901px` and no pane is
     unreachable at any width.

2. Browser measurement (opt-in, `python3 ... --browser` or
   `DESKTOP_SHELL_BROWSER_CHECK=1`): serves `site/index.html` locally and asserts
   `document.scrollingElement.scrollHeight <= clientHeight` at 1500x1000 and
  1366x768 for home/review/spotlab/training/replayer. It is skipped when
   Playwright is unavailable so the frozen static CI job stays hermetic.
   The same session also resolves the centre of the Accueil « Review » shortcut
   (`#homePage a[href="#historiesSection"]`) with `document.elementFromPoint`
   and requires that link — or one of its descendants — to receive the point,
   i.e. the floating rail must not intercept the click.

3. Static rail / Home separation (#394 R1, no browser):

   * the rail geometry (`--nav-rail-left`, `--nav-rail-width`,
     `--nav-toggle-width`, `--nav-toggle-right`) and the gutter token
     (`--home-nav-gutter`) are the single authority: the guard recomputes the
     horizontal interval the rail and its toggle occupy at 1500x1000 and
     1366x768 from those very declarations (px literals, `var()` and `calc()`
     sums are resolved) and requires the interactive Home column — the column of
     the Accueil « Review » shortcut — to start strictly to its right at both
     reference viewports, and across the whole width range where the rail is the
     vertical one;
   * no `z-index` / `pointer-events` bypass, no negative offset pulling the Home
     column back under the rail and no positioned Home column is accepted.
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
SHELL_DOC = (ROOT / 'docs/ux-desktop-view-shell.md').read_text(encoding='utf-8')

DESKTOP_MIN_WIDTH = 901
SHELL_VIEWS = ('home', 'review', 'spotlab', 'strategy', 'training', 'replayer')
MEASURED_VIEWS = ('home', 'review', 'spotlab', 'training', 'replayer')
MEASURED_VIEWPORTS = ((1500, 1000), (1366, 768))

# #394 R1 — the floating navigation rail is a left gutter while it is vertical
# (`min-width:761px`; below that the nav becomes the bottom bar) and its toggle
# overhangs the rail's right border. The Home column therefore reserves a named
# gutter (`--home-nav-gutter`) instead of relying on its centred max-width.
RAIL_SELECTOR = '.quick-nav'
RAIL_TOGGLE_SELECTOR = '.quick-nav-toggle'
WRAP_SELECTOR = '.wrap'
HOME_COLUMN_SELECTOR = '#homePage'
HOME_COLUMN_MARKUP = '<div id="homePage" class="wrap home-page" data-view-shell="home">'
HOME_SHORTCUT_SELECTOR = '#homePage a[href="#historiesSection"]'
HOME_SHORTCUT_MARKUP = '<a href="#historiesSection" class="filelabel"'
HOME_ACTIONS_SELECTOR = '.product-home-actions'
VERTICAL_RAIL_MIN_WIDTH = 761
# The two reference viewports plus the width range where the rail stays vertical:
# the separation is a property of the column, so it must not only hold for the
# two smoke viewports.
SEPARATION_SWEEP_WIDTHS = (761, 800, 900, 1024, 1180, 1181, 1280, 1366, 1440, 1500, 1920)

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


def media_applies(media: str | None, width: int) -> bool:
    """True when a media condition can apply at this exact viewport width.

    `applies_at_desktop` answers the coarse "is this desktop scope?" question;
    the rail/Home separation needs the real verdict per viewport, because the
    rail narrows below 1181px (`@media(max-width:1180px)`).
    """
    if not media:
        return True
    for operator, value in re.findall(r'(min|max)-width\s*:\s*(\d+)px', media):
        pixels = int(value)
        if operator == 'min' and width < pixels:
            return False
        if operator == 'max' and width > pixels:
            return False
    return True


def css_variables(css: str) -> dict[str, str]:
    """The `--token: value` table declared on `:root`, whatever guards it.

    The very first rule of `site/index.html` is read from the whole document: its
    prelude still carries the markup of `<head>` before `:root`, so the token
    table is matched on the selector tail.
    """
    variables: dict[str, str] = {}
    for _media, selector, declarations in css_rules(css):
        if selector.split('\n')[-1].strip() not in (':root', 'html', ':root,html'):
            continue
        for name, value in re.findall(r'(--[\w-]+)\s*:\s*([^;]+)', declarations):
            variables[name] = value.strip()
    return variables


LENGTH_TERM = re.compile(r'var\(\s*(--[\w-]+)\s*\)|(-?\d+(?:\.\d+)?)px|([+-])')


def _strip_calc(value: str) -> str:
    text = value.strip()
    while text[:5].lower() == 'calc(' and text.endswith(')'):
        inner = text[5:-1]
        depth = 0
        for char in inner:
            if char == '(':
                depth += 1
            elif char == ')':
                depth -= 1
                if depth < 0:
                    break
        if depth != 0:
            break
        text = inner.strip()
    return text


def resolve_css_length(value: str, variables: dict[str, str], depth: int = 0) -> float:
    """Resolve a declared length made of px literals, `var()` and `calc()` sums.

    The separation guard must recompute *the numbers the shell declares*, so it
    resolves the very tokens and `calc()` expressions the stylesheet uses rather
    than a second, hand-copied constant that could silently drift.
    """
    assert depth <= 8, f'CSS variable cycle around {value!r}'
    total = 0.0
    term_sign = 1.0
    found = False
    for reference, pixels, operator in LENGTH_TERM.findall(_strip_calc(value)):
        if operator:
            term_sign = 1.0 if operator == '+' else -1.0
            continue
        if reference:
            assert reference in variables, f'{reference} is not declared'
            total += term_sign * resolve_css_length(variables[reference], variables, depth + 1)
        else:
            total += term_sign * float(pixels)
        term_sign = 1.0
        found = True
    assert found, f'unsupported CSS length {value!r}'
    return total


def declared_property(css: str, selector: str, prop: str, width: int) -> str | None:
    """Last declared value of `prop` for `selector` among the rules applying at `width`."""
    value = None
    for media, name, declarations in css_rules(css):
        if name != selector or not media_applies(media, width):
            continue
        for declared, raw in re.findall(r'([\w-]+)\s*:\s*([^;]+)', declarations):
            if declared == prop:
                value = raw.strip()
    return value


def rail_interval(width: int, variables: dict[str, str], css: str = INDEX) -> tuple[float, float]:
    """Horizontal interval the floating rail **and its toggle** occupy at `width`."""
    rail_left = resolve_css_length(declared_property(css, RAIL_SELECTOR, 'left', width) or '', variables)
    rail_width = resolve_css_length(declared_property(css, RAIL_SELECTOR, 'width', width) or '', variables)
    toggle_width = resolve_css_length(declared_property(css, RAIL_TOGGLE_SELECTOR, 'width', width) or '', variables)
    toggle_right = resolve_css_length(declared_property(css, RAIL_TOGGLE_SELECTOR, 'right', width) or '', variables)
    rail_right = rail_left + rail_width
    toggle_start = rail_right + toggle_right
    # The toggle only counts as an extra covered band when it overhangs the rail.
    assert toggle_start >= rail_left, (toggle_start, rail_left)
    return rail_left, max(rail_right, toggle_start + toggle_width)


def home_column_left(width: int, variables: dict[str, str], css: str = INDEX) -> float:
    """Left edge of the interactive Home column at `width`, from declared numbers."""
    max_width = resolve_css_length(declared_property(css, WRAP_SELECTOR, 'max-width', width) or '', variables)
    wrap_left = (width - min(float(width), max_width)) / 2
    padding_left = resolve_css_length(
        declared_property(css, HOME_COLUMN_SELECTOR, 'padding-left', width) or '', variables
    )
    return wrap_left + padding_left


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
    # an in-flow rule, and no viewport-height/scroll rule escapes the desktop
    # block.
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

    # #mainPage.wrap (Review) is split into three constrained sub-views — the
    # pilotage dashboard, the import surface and the review inbox. Each pane owns
    # the whole body height on its own, so no pane is stacked with another one in
    # the bounded shell; the inbox stays a bounded paginated list instead of a
    # long internal scroll box.
    review = INDEX.split('<div id="mainPage"', 1)[1].split('<div id="strategyPage"', 1)[0]
    assert '<div class="app-view-body">' in review, 'Review must expose a shell body'
    for subview in ('pilotage', 'import', 'inbox'):
        assert f'data-app-subview="{subview}"' in review, subview
    for panel in ('reviewDashboard', 'historiesSection', 'handSelectionSection'):
        assert f'id="{panel}"' in review, panel
    # Tab ⇄ pane pairing is exact: the dashboard is the landing (`pilotage`) pane,
    # the import surface is its own pane and the inbox keeps the third one. The
    # import pane is the only landing-invisible one besides the inbox, so a deep
    # link always selects the owning tab instead of relying on a stacked pane.
    assert (
        '<section id="reviewDashboard" class="review-dashboard app-subview-panel"'
        ' role="tabpanel" aria-labelledby="reviewDashboardTitle" aria-live="polite"'
        ' data-app-subview-panel="pilotage">'
    ) in review
    assert (
        '<section id="historiesSection" class="panel wide app-subview-panel"'
        ' role="tabpanel" aria-labelledby="reviewImportTab"'
        ' data-app-subview-panel="import" hidden>'
    ) in review
    assert (
        '<div id="handSelectionSection" class="hh-selection-section panel app-subview-panel"'
        ' role="tabpanel" aria-labelledby="reviewInboxTab"'
        ' data-app-subview-panel="inbox" hidden>'
    ) in review
    assert (
        '<button type="button" class="app-subview-tab" id="reviewPilotageTab"'
        ' role="tab" aria-selected="true" aria-controls="reviewDashboard"'
        ' data-app-subview="pilotage">Pilotage</button>'
    ) in review
    assert (
        '<button type="button" class="app-subview-tab" id="reviewImportTab"'
        ' role="tab" aria-selected="false" aria-controls="historiesSection"'
        ' data-app-subview="import">Import</button>'
    ) in review
    # The import surface is not wrapped in a shared `.grid` container: its pane is
    # a direct child of the shell body, exactly like the dashboard and the inbox.
    assert '<div class="grid">' not in review, 'the import pane must not share a container'
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
    # #394 T1/T2 — the Replayer is a fixed 3-column shell (timeline/actions |
    # table | contextual panel). The replay columns stay mounted in that shell
    # and are never a tab pane; the third column is a contextual tabbed panel
    # whose three panes (Décision / Ranges / Détails) are real tab/pane pairs,
    # exactly one of them visible.
    replayer = INDEX.split('<div id="replayerPage"', 1)[1].split('<script src="./compute-scheduler.js">', 1)[0]
    for pane, subview in (
        ('replayerDecisionPanel', 'replayer-decision'),
        ('replayerRangesPanel', 'replayer-ranges'),
        ('hhReplayDetail', 'replayer-details'),
    ):
        assert f'id="{pane}"' in replayer, pane
        assert f'data-app-subview="{subview}"' in replayer, subview
        assert f'data-app-subview-panel="{subview}"' in replayer, subview
        assert f'aria-controls="{pane}"' in replayer, pane
        # A pane id lives exactly once in the whole document.
        assert len(re.findall(rf'id="{pane}"', INDEX)) == 1, pane
    assert replayer.count('role="tablist"') == 1, replayer.count('role="tablist"')
    assert replayer.count('data-app-subview="') == 3, replayer.count('data-app-subview="')
    assert replayer.count('data-app-subview-panel="') == 3, replayer.count('data-app-subview-panel="')
    assert 'id="replayerDecisionPanel" class="replayer-context-pane app-scroll-zone app-subview-panel"' in replayer
    assert 'id="replayerRangesPanel" class="replayer-context-pane app-scroll-zone app-subview-panel"' in replayer
    assert 'data-app-subview-panel="replayer-ranges" hidden' in replayer
    assert 'data-app-subview-panel="replayer-details" hidden' in replayer
    assert 'id="replayerContextPanel"' in replayer, 'the third column hosts the contextual panel'
    # The replay columns are not a sub-view pane: selecting a contextual tab must
    # never blank the timeline/actions column or the table.
    visual_replay = replayer.split('<div id="hhVisualReplay"', 1)[1].split('>', 1)[0]
    assert 'data-app-subview-panel' not in visual_replay, visual_replay
    assert 'app-subview-panel' not in visual_replay, visual_replay
    for element_id in ('replayerPage', 'replayerSection', 'hhVisualReplay', 'hhReplayDetail'):
        assert f'id="{element_id}"' in INDEX, element_id

    # Keyboard contract: roving tabindex, Enter/Space activation, and a deep link
    # that selects the owning tab before focusing instead of scrolling the shell.
    assert replayer.count('tabindex="-1"') == 2, 'the inactive tabs leave the tab order'
    assert replayer.count('aria-selected="true"') == 1, 'exactly one tab starts selected'
    assert replayer.count('aria-selected="false"') == 2, replayer.count('aria-selected="false"')
    assert 'role="tabpanel"' in replayer and replayer.count('role="tabpanel"') == 3
    assert 'if(e.key==="Enter"||e.key===" "||e.key==="Spacebar"){' in INDEX
    assert 'replayerSection:"replayer-decision",replayerPage:"replayer-decision"' in INDEX
    focus = INDEX.split('function focusAppSection(id){', 1)[1].split('function routeFromHash', 1)[0]
    assert 'activateAppSubviewForTarget(id);' in focus
    assert focus.index('activateAppSubviewForTarget(id);') < focus.index('scrollIntoView')
    # A tab activation is a pure visibility toggle: it never schedules compute and
    # never re-renders a pane.
    activate = INDEX.split('function activateAppSubview(name){', 1)[1].split('function activateAppSubviewForTarget', 1)[0]
    for forbidden in ('scheduleAutoCalculate', 'scheduleBackgroundReviewScoring', 'startSeatEquityCalculation', 'renderVisualReplay', 'renderHistoryReplay'):
        assert forbidden not in activate, forbidden

    # The panes reuse the existing renders instead of duplicating them: the
    # opponent-range trigger has a single rendering authority, and the decision
    # banner is painted once — in the Décision pane, never in the left column.
    assert 'if(replayerDecisionPanel) replayerDecisionPanel.innerHTML=replayerDecisionPanelHtml(step);' in INDEX
    assert 'if(replayerRangesPanel) replayerRangesPanel.innerHTML=replayerRangesPanelHtml(h);' in INDEX
    assert 'replayerContextPanel.querySelectorAll("[data-population-player]")' in INDEX
    decision_pane = INDEX.split('function replayerDecisionPanelHtml(step){', 1)[1].split('function replayerRangesPanelHtml(hand){', 1)[0]
    assert 'replayActionBannerHtml(step)' in decision_pane
    assert 'safeActionAnalysisHtml(state.replayIndex,step)' in decision_pane
    ranges_pane = INDEX.split('function replayerRangesPanelHtml(hand){', 1)[1].split('function renderVisualReplay(){', 1)[0]
    assert 'populationRangeButtonHtml(player)' in ranges_pane
    assert 'data-population-player' not in ranges_pane, 'the trigger markup stays in its single authority'
    seat = INDEX.split('function replaySeatHtml(player,step,hand){', 1)[1].split('function populationRangeWidthFromEntries(', 1)[0]
    assert 'populationRangeButtonHtml(player)' in seat
    assert 'data-population-player' not in seat, 'the trigger markup stays in its single authority'
    visual_template = INDEX.split('hhVisualReplay.innerHTML=`<div class="replayer-col replayer-col-left', 1)[1].split('<div class="replayer-col replayer-col-center', 1)[0]
    assert 'replayActionBannerHtml' not in visual_template, 'the decision banner is painted once, in the Décision pane'

    # The 3 columns are a desktop grid owned by the shell: no column re-stacks the
    # replay content, and no new scroll zone is declared (see the allow-list).
    section = declarations_for('#replayerSection', '(min-width:901px)')
    assert section is not None, 'the Replayer shell must be declared in the desktop block'
    assert 'display:grid' in section, section
    assert 'grid-template-columns:minmax(240px,320px) minmax(0,1fr) minmax(240px,340px)' in section, section
    assert 'overflow:hidden' in section, section
    assert not SCROLL_DECLARATION.search(section), section
    assert declarations_for('#replayerSection>#hhVisualReplay', '(min-width:901px)') == 'display:contents'
    # Each contextual pane owns the remaining height of the third column and is
    # bounded by `.app-scroll-zone`, never by the shell.
    assert declarations_for(
        '#replayerSection>#replayerContextPanel>.app-subview-panel', '(min-width:901px)'
    ) == 'flex:1 1 auto;min-height:0;margin:0'
    # `renderVisualReplay()` paints only the two left/centre columns; the third
    # column of the shell stays the contextual container (#replayerContextPanel).
    assert 'hhVisualReplay.innerHTML=`<div class="replayer-col replayer-col-left app-scroll-zone">' in INDEX
    assert '<div class="replayer-col replayer-col-center app-canvas-pane">' in INDEX

    # The matrix grid is bounded by its pane: it never scrolls on desktop.
    assert '.matrixwrap{overflow:hidden;margin-top:12px}' in INDEX


def check_subview_scope_and_mobile_inventory() -> None:
    """#394 T2 — the sub-view pattern is global, the `100dvh` shell is not.

    Divergence #2 of the review: the documents and the CSS comment used to claim
    the `<901px` rendering was unaffected by the shell, while the sub-view rules
    were (correctly) declared outside every media query and `activateAppSubview`
    toggles `hidden` with no width guard. The contract now states the truth, and
    this static guard pins it: the pattern is global, only the `100dvh` /
    no-global-scroll rule stays inside `@media(min-width:901px)`, and every pane
    keeps an owning tab so no pane is unreachable at any width.
    """
    rules = css_rules(INDEX)

    # The reusable pattern must live outside every media query: it is the single
    # excess mechanism of Review/Spot Lab/Training/Replayer below 901px too.
    for selector in ('.app-subviews', '.app-subview-tab', '.app-subview-panel'):
        base = [declarations for media, sel, declarations in rules if media is None and sel == selector]
        assert base, f'{selector} must be declared outside any media query'
        rescoped = [
            media
            for media, sel, _ in rules
            if media and 'min-width:901px' in media and sel == selector
        ]
        assert not rescoped, f'{selector} must not be re-scoped into a desktop block: {rescoped}'

    hidden_panel = [decl for media, sel, decl in rules if media is None and sel == '.app-subview-panel[hidden]']
    assert any('display:none!important' in declarations for declarations in hidden_panel), hidden_panel
    assert not [
        media
        for media, sel, _ in rules
        if media and 'min-width:901px' in media and sel == '.app-subview-panel[hidden]'
    ], 'the pane `[hidden]` rule is global, it is never desktop-only'
    # The `!important` is required because a pane class may declare its own
    # `display` (`.replayer-context-pane{display:flex}`, the Spot Lab `.panel`),
    # which would otherwise beat the user-agent `[hidden]{display:none}`.
    assert '.replayer-context-pane{display:flex' in INDEX
    assert 'function activateAppSubview(name){' in INDEX
    activate = INDEX.split('function activateAppSubview(name){', 1)[1].split('function activateAppSubviewForTarget', 1)[0]
    assert 'panel.hidden=panel.dataset.appSubviewPanel!==name;' in activate
    assert 'matchMedia' not in activate, 'the pane toggle must not be width-guarded'

    # `100dvh` / global `overflow` stay desktop-only: below 901px `html`/`body`
    # keep the normal document flow, whatever the global pattern rules do.
    for media, selector, declarations in rules:
        if selector not in ('html', 'body', 'html,body'):
            continue
        if '100dvh' in declarations:
            assert media and 'min-width:901px' in media, (media, selector, declarations)
        if SCROLL_DECLARATION.search(declarations):
            raise AssertionError(f'global scroll declared by {selector} under {media or "no media"}')

    # Static mobile inventory: every pane is owned by exactly one tab, so no pane
    # is unreachable below 901px, and the inventory is versioned (each sub-view
    # name is listed in §2.1 of the shell document).
    # The markup only: the CSS comment spells the attribute names with a
    # placeholder (`data-app-subview-panel="<nom>"`).
    markup = INDEX.split('<body', 1)[1]
    pane_tags = re.findall(r'<[^>]*data-app-subview-panel="[^"]+"[^>]*>', markup)
    panels = [re.search(r'data-app-subview-panel="([^"]+)"', tag).group(1) for tag in pane_tags]
    tabs = re.findall(r'data-app-subview="([^"]+)"', markup)
    assert panels and tabs
    assert len(set(panels)) == len(panels), 'a pane name is duplicated'
    assert len(set(tabs)) == len(tabs), 'a tab name is duplicated'
    assert sorted(panels) == sorted(tabs), (sorted(panels), sorted(tabs))
    hidden_by_default = []
    for tag, name in zip(pane_tags, panels):
        pane_id = re.search(r'id="([^"]+)"', tag).group(1)
        # The owning tab is the one that controls this pane, inside the same shell.
        assert f'aria-controls="{pane_id}"' in markup, (name, pane_id)
        assert f'data-app-subview="{name}"' in markup, name
        if re.search(r'\shidden(?=[\s>])', tag):
            hidden_by_default.append(name)
        assert f'`{name}`' in SHELL_DOC, f'the mobile inventory must document the `{name}` sub-view'
    assert hidden_by_default, 'the pattern only exists because some panes start hidden'
    # The versioned inventory is exactly the markup truth: the hidden-by-default
    # panes are the inventory bullets, and the landing panes are listed apart.
    inventory = SHELL_DOC.split('Mobile-UX inventory', 1)[1].split('The other panes', 1)[0]
    for name in hidden_by_default:
        assert f'`{name}`' in inventory, f'the inventory must list the hidden `{name}` pane'
    for name in set(panels) - set(hidden_by_default):
        assert f'`{name}`' not in inventory, f'the landing `{name}` pane is not hidden by default'

    # The documents state the corrected scope. The two literals below are the
    # retired claims: they must not reappear in the shell document or in this
    # module's docstring.
    doc_flat = ' '.join(SHELL_DOC.split())
    module_doc = ' '.join((__doc__ or '').split())
    for stale_claim in ('untouched', 'out of this contract'):
        assert stale_claim not in doc_flat, stale_claim
        assert stale_claim not in module_doc, stale_claim
    assert 'the sub-view pattern is global' in doc_flat
    assert 'no pane without a tab, no unreachable pane' in doc_flat


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
# #394 R1 — static separation between the floating rail and the Home column.
# --------------------------------------------------------------------------- #
def check_home_nav_separation() -> None:
    """The Home column starts strictly to the right of the floating rail.

    Root cause of the #394 CI failure: at 1366x768 the centred Home column began
    at x=97 (`(1366-1220)/2 + 24`), while `#quickNavToggle` — anchored to the
    right border of the always-floating `.quick-nav` — covered x=114..142. The
    centre of the Accueil « Review » shortcut therefore received the toggle, so
    the frozen smoke's real click waited and timed out. The fix reserves an
    explicit, named gutter on the Home column itself rather than masking the
    overlap.

    Everything below is recomputed from the declared CSS numbers: the rail box
    (`.quick-nav`), the toggle box (`.quick-nav-toggle`), the centred column
    (`.wrap`) and the gutter token (`--home-nav-gutter`).
    """
    variables = css_variables(INDEX)

    # The column that must clear the rail is the Home shell itself, and the
    # measured shortcut is the first control of its direct-access row: the column
    # left edge is therefore the shortcut's own left edge.
    assert HOME_COLUMN_MARKUP in INDEX, HOME_COLUMN_MARKUP
    assert f'<nav id="quickNav" class="quick-nav"' in INDEX
    assert f'<button id="quickNavToggle" type="button" class="quick-nav-toggle"' in INDEX
    home_markup = INDEX.split(HOME_COLUMN_MARKUP, 1)[1].split('<div id="spotlabPage"', 1)[0]
    assert HOME_SHORTCUT_MARKUP in home_markup, HOME_SHORTCUT_MARKUP
    actions = (
        home_markup.split('<div class="actions product-home-actions"', 1)[1]
        .split('>', 1)[1]
        .split('</div>', 1)[0]
    )
    assert actions.strip().startswith('<a href="#historiesSection"'), actions
    actions_base = [
        declarations
        for media, selector, declarations in css_rules(INDEX)
        if media is None and selector == HOME_ACTIONS_SELECTOR
    ]
    assert actions_base and 'display:flex' in actions_base[0], actions_base

    # The column is centred by `margin:auto` on `.wrap`, so its left edge is a
    # declared number and not a measured one.
    wrap = [
        declarations
        for media, selector, declarations in css_rules(INDEX)
        if media is None and selector == WRAP_SELECTOR
    ]
    assert wrap and 'margin:auto' in wrap[0] and 'max-width:1220px' in wrap[0], wrap

    # The gutter has a single authority: one `padding-left` on the Home column,
    # effective from the width where the rail is the vertical one, and expressed
    # with the named token instead of a duplicated magic number.
    gutter_rules = [
        (media, declarations)
        for media, selector, declarations in css_rules(INDEX)
        if selector == HOME_COLUMN_SELECTOR and 'padding-left' in declarations
    ]
    assert len(gutter_rules) == 1, f'the Home gutter must have one authority: {gutter_rules}'
    gutter_media, gutter_declarations = gutter_rules[0]
    assert gutter_media and f'min-width:{VERTICAL_RAIL_MIN_WIDTH}px' in gutter_media, gutter_media
    assert 'var(--home-nav-gutter)' in gutter_declarations, gutter_declarations

    # No bypass: the rail keeps its stacking (the overlap is removed, not hidden
    # behind the content), the toggle never stops receiving pointer events, and
    # the Home column is neither positioned nor pulled back under the rail.
    assert declared_property(INDEX, RAIL_SELECTOR, 'z-index', 1366) == '9997'
    for media, selector, declarations in css_rules(INDEX):
        if 'pointer-events' in declarations:
            assert 'quickNavToggle' not in selector and selector != RAIL_TOGGLE_SELECTOR, (media, selector)
        if selector in (HOME_COLUMN_SELECTOR, '.home-page', WRAP_SELECTOR, HOME_ACTIONS_SELECTOR):
            flat = declarations.replace(' ', '')
            for forbidden in ('position:fixed', 'position:absolute', 'margin-left:-', 'translateX(-', 'left:-', 'z-index:'):
                assert forbidden not in flat, f'{selector} may not use {forbidden} ({media or "no media"})'

    # Reference viewports: the acceptance case, recomputed from the declarations.
    for width, height in MEASURED_VIEWPORTS:
        rail_start, rail_end = rail_interval(width, variables)
        column_left = home_column_left(width, variables)
        assert column_left > rail_end, (
            f'la colonne interactive de Home doit commencer strictement à droite du rail '
            f'flottant à {width}x{height} : colonne left={column_left:g}px, '
            f'rail+toggle=[{rail_start:g}, {rail_end:g}]px '
            f'(max-width .wrap={resolve_css_length("1220px", variables):g}px, '
            f'padding-left #homePage={resolve_css_length(gutter_declarations.split("padding-left:", 1)[1], variables):g}px)'
        )

    # The gutter is a column property, so it also clears the rail across the whole
    # range where the rail is vertical — including where the centred column has no
    # side margin left (<= 1220px wide).
    gutter = resolve_css_length('var(--home-nav-gutter)', variables)
    widest_rail_end = max(rail_interval(width, variables)[1] for width in SEPARATION_SWEEP_WIDTHS)
    for width in SEPARATION_SWEEP_WIDTHS:
        rail_start, rail_end = rail_interval(width, variables)
        column_left = home_column_left(width, variables)
        assert column_left > rail_end, (
            f'rail/Home separation lost at {width}px: rail+toggle=[{rail_start:g}, {rail_end:g}]px '
            f'vs colonne Home left={column_left:g}px (--home-nav-gutter={gutter:g}px)'
        )
    assert gutter >= widest_rail_end, (
        f'--home-nav-gutter={gutter:g}px must cover the widest rail+toggle band '
        f'({widest_rail_end:g}px) since the column may have no side margin at all'
    )


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

# #394 R1 — the real hit-test of the Accueil « Review » shortcut: the centre of
# its box must resolve that link (or one of its descendants), i.e. neither the
# rail nor its toggle may intercept it. The measured boxes of the rail and of the
# toggle are reported too, so a failure prints both sides of the overlap.
HOME_SHORTCUT_PROBE_JS = """async () => {
  const link=document.querySelector('#homePage a[href="#historiesSection"]');
  if(!link) return {missing:true};
  const rect=link.getBoundingClientRect();
  const point=[rect.left+rect.width/2, rect.top+rect.height/2];
  const at=document.elementFromPoint(point[0], point[1]);
  const describe=(el)=>el?`${el.tagName.toLowerCase()}${el.id?'#'+el.id:''}`:null;
  const nav=document.getElementById('quickNav');
  const toggle=document.getElementById('quickNavToggle');
  const navBox=nav?nav.getBoundingClientRect():null;
  const toggleBox=toggle?toggle.getBoundingClientRect():null;
  return {
    missing:false,
    point:point,
    rect:[rect.left, rect.top, rect.right, rect.bottom],
    at:describe(at),
    atTag:at?at.tagName:null,
    hits:!!at && (at===link || link.contains(at)),
    railBox:navBox?[navBox.left, navBox.right]:null,
    toggleBox:toggleBox?[toggleBox.left, toggleBox.right]:null,
    railEnd:Math.max(navBox?navBox.right:0, toggleBox?toggleBox.right:0),
    linkLeft:rect.left
  };
}"""


async def assert_home_shortcut_hit_testable(page, width: int, height: int) -> None:
    """`document.elementFromPoint` at the centre of the Review shortcut (#394 R1)."""
    probe = await page.evaluate(HOME_SHORTCUT_PROBE_JS)
    assert not probe.get('missing'), (
        f'raccourci Accueil « Review » absent ({HOME_SHORTCUT_SELECTOR}, {width}x{height})'
    )
    assert probe['hits'], (
        f'le centre du raccourci Accueil « Review » doit résoudre le lien '
        f'({width}x{height}) — rect={probe["rect"]} point={probe["point"]} '
        f'at={probe["at"]} (tag={probe["atTag"]}) rail={probe["railBox"]} '
        f'toggle={probe["toggleBox"]}'
    )
    assert probe['linkLeft'] > probe['railEnd'], (
        f'la colonne Home doit rester à droite du rail ({width}x{height}) — '
        f'lien left={probe["linkLeft"]} railEnd={probe["railEnd"]}'
    )


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
                    if view == 'home':
                        # #394 R1 — the rail must not intercept the Home shortcuts.
                        await assert_home_shortcut_hit_testable(page, width, height)
                await page.close()
            await browser.close()
    finally:
        httpd.shutdown()
    print('desktop shell browser measurement: OK')


def main() -> None:
    check_modal_accessibility_contract()
    check_desktop_shell_contract()
    check_subview_scope_and_mobile_inventory()
    check_allowed_scroll_zones()
    check_home_nav_separation()
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

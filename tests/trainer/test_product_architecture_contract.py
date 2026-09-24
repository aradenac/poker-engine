#!/usr/bin/env python3
"""Product architecture contract (#394).

This module pins the app-shell architecture of `site/index.html`: the Home mode
screen, the single `state.appView` source of truth, the navigation/deep-link
routing and the persistence whitelist.

It is also the static consumer of the normative shell document
`docs/ux-desktop-view-shell.md` (`poker-ux-desktop-view-shell/v1`): the
`100dvh` / no-global-scroll rule, the mode → view → sub-view mapping, the
allowed overflow policies, the navigation/deep-link contract, the
no-recalculation-on-a-view-change rule and the browser-smoke orchestration
shape must all stay coherent with the delivered implementation.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX = (ROOT / 'site/index.html').read_text(encoding='utf-8')
SHELL_DOC = (ROOT / 'docs/ux-desktop-view-shell.md').read_text(encoding='utf-8')
SPOTLAB_DOC = (ROOT / 'docs/spotlab-view.md').read_text(encoding='utf-8')
DISPLAY_DOC = (ROOT / 'docs/opponent-range-display-contract.md').read_text(encoding='utf-8')
SHARED_DOC = (ROOT / 'docs/shared-components.md').read_text(encoding='utf-8')
WORKFLOW = (ROOT / '.github/workflows/trainer-smoke.yml').read_text(encoding='utf-8')
SMOKE_TRAINER = (ROOT / 'tests/trainer/smoke_trainer.py').read_text(encoding='utf-8')

BACKTICKED_TOKEN = re.compile(r'`([a-z0-9.-]+)`')
ALLOWED_SCROLL_ENTRY = re.compile(
    r'\{selector:"([^"]+)",scope:"([^"]+)",kind:"([^"]+)",reason:"([^"]+)"\}'
)


def block(start: str, end: str) -> str:
    return INDEX.split(start, 1)[1].split(end, 1)[0]


def doc_rows(doc: str, start: str, end: str) -> list[list[str]]:
    """Cells of every markdown table row between two section markers."""
    section = doc.split(start, 1)[1].split(end, 1)[0]
    rows: list[list[str]] = []
    for line in section.splitlines():
        line = line.strip()
        if not line.startswith('|'):
            continue
        cells = [cell.strip() for cell in line.split('|')[1:-1]]
        if not cells or set(''.join(cells)) <= set('- '):
            continue  # the `| --- | --- |` separator row
        rows.append(cells)
    return rows


def check_ux_desktop_view_shell_doc() -> None:
    """The normative shell document stays coherent with the implementation."""
    # The document is versioned, and it names the exported constants it pins.
    assert 'poker-ux-desktop-view-shell/v1' in SHELL_DOC
    for constant in ('APP_VIEWS', 'APP_HASH_SUBVIEWS', 'APP_ALLOWED_SCROLL_ZONES'):
        assert constant in SHELL_DOC, constant

    # The 100dvh / no-global-scroll rule is documented verbatim, and matches the
    # single declaration that actually implements it.
    no_scroll = 'html,body{height:100dvh;max-height:100dvh;overflow:hidden}'
    assert no_scroll in SHELL_DOC, 'the no-scroll rule must be quoted verbatim'
    assert no_scroll in INDEX, 'the desktop shell must declare the no-scroll rule'
    assert '[data-view-shell]{display:flex;flex-direction:column;flex:1 1 auto;width:100%;height:100dvh;max-height:100dvh;min-height:0;overflow:hidden' in INDEX
    assert 'no global scroll' in SHELL_DOC
    assert 'flex:1 1 auto;overflow:hidden' in SHELL_DOC

    # mode → view → sub-view: every documented view is a real shell and every
    # documented sub-view is a real tab/pane pair.
    mapping = doc_rows(SHELL_DOC, '## 2.', '## 3.')
    documented_views: dict[str, list[str]] = {}
    for cells in mapping:
        if cells[0].startswith('Mode'):
            continue
        app_view = BACKTICKED_TOKEN.findall(cells[1])
        shell = BACKTICKED_TOKEN.findall(cells[2])
        assert app_view and shell, cells
        assert app_view == shell, cells
        view = app_view[0]
        documented_views[view] = BACKTICKED_TOKEN.findall(cells[3])
        assert f'data-view-shell="{view}"' in INDEX, view
    assert set(documented_views) == {
        'home', 'review', 'spotlab', 'training', 'replayer', 'strategy',
    }, documented_views
    # The four dense views expose their excess as sub-views, never as a scroll.
    for view, subviews in documented_views.items():
        if view in ('home', 'strategy'):
            assert not subviews, (view, subviews)
            continue
        assert subviews, view
        for subview in subviews:
            # #394 T2 — the Replayer contextual column is a tabbed panel
            # (Décision / Ranges / Détails), so its documented sub-views are real
            # tab/pane pairs like every other dense view.
            assert f'data-app-subview="{subview}"' in INDEX, subview
            assert f'data-app-subview-panel="{subview}"' in INDEX, subview

    # The configured modes are exactly the documented shells.
    assert 'const APP_VIEWS=["home","review","replayer","spotlab","training","strategy"];' in INDEX
    assert 'const APP_VIEWS=["home","review","replayer","spotlab","training","strategy"];' in SHELL_DOC
    assert set(documented_views) == set(re.findall(r'"([a-z]+)"', block('const APP_VIEWS=[', '];')))

    # The sub-view / pagination pattern is documented and implemented: a pane is
    # selected by a scoped tab, and a list that cannot fit is paginated instead
    # of scrolled (`renderReviewInboxPage` shrinks the page size to the shell).
    for documented in (
        'data-app-subview', 'data-app-subview-panel', 'appSubviewScopeFor',
        'closest("[data-view-shell]")', '.app-list-pager', 'hhListPager',
        'renderReviewInboxPage', 'hhHandsEl.scrollHeight <= hhHandsEl.clientHeight + 1',
    ):
        assert documented in ' '.join(SHELL_DOC.split()), documented
    assert 'function activateAppSubview(name){' in INDEX
    assert 'return (node&&node.closest("[data-view-shell]"))||document;' in INDEX
    assert 'id="hhListPager"' in INDEX and 'id="hhPagePrev"' in INDEX and 'id="hhPageNext"' in INDEX
    assert 'function renderReviewInboxPage(hands,byId){' in INDEX
    assert 'hhHandsEl.scrollHeight<=hhHandsEl.clientHeight+1' in INDEX

    # Overflow policy: the documented allow-list is exactly the implementation's
    # `APP_ALLOWED_SCROLL_ZONES`, each entry justified and bounded.
    zones = [
        {'selector': selector, 'scope': scope, 'kind': kind, 'reason': reason}
        for selector, scope, kind, reason in ALLOWED_SCROLL_ENTRY.findall(INDEX)
    ]
    assert zones, 'APP_ALLOWED_SCROLL_ZONES must exist'
    for zone in zones:
        assert zone['scope'] in ('desktop', 'dialogue'), zone
        assert len(zone['reason']) >= 40, zone
    documented_zones = set()
    for cells in doc_rows(SHELL_DOC, '## 3.', '## 4.'):
        if cells[0].startswith('Selector'):
            continue
        selector = BACKTICKED_TOKEN.findall(cells[0])
        assert selector, cells
        documented_zones.add(selector[0])
    assert documented_zones == {zone['selector'] for zone in zones}, (
        documented_zones, [zone['selector'] for zone in zones],
    )
    assert 'APP_ALLOWED_SCROLL_ZONES' in INDEX
    assert '.matrixwrap{overflow:hidden' in INDEX

    # Navigation and deep links: every documented entry point exists, and a hash
    # targeting a sub-view pane selects its tab before focusing.
    for marker in (
        'function setAppView(view,{scrollTop=false,persist=true}={}){',
        'function goHome(){',
        'function appViewForHashTarget(id){',
        'function focusAppSection(id){',
        'function routeFromHash(){',
        'const APP_HASH_SUBVIEWS={',
        'function appSubviewForHashTarget(id){',
        'function activateAppSubviewForTarget(id){',
        'window.addEventListener("hashchange"',
        'data-home-back',
    ):
        assert marker in INDEX, marker
    for documented in (
        'appViewForHashTarget', 'routeFromHash', 'focusAppSection',
        'APP_HASH_SUBVIEWS', 'activateAppSubviewForTarget', 'data-home-back',
        'goHome', 'hashchange',
    ):
        assert documented in SHELL_DOC, documented

    # A view change is a pure mount swap: no engine recomputation is scheduled.
    update_view = block('function updateAppView({scrollTop=false}={}){', 'const APP_ALLOWED_SCROLL_ZONES=[')
    for forbidden in ('scheduleAutoCalculate', 'scheduleBackgroundReviewScoring', 'startSeatEquityCalculation'):
        assert forbidden not in update_view, forbidden
    assert "window.pokerComputeScheduler.hold('replayer',mount==='replayer');" in update_view
    assert "window.pokerComputeScheduler.hold('training',mount==='training');" in update_view
    assert 'scheduleAutoCalculate' in SHELL_DOC and 'startSeatEquityCalculation' in SHELL_DOC
    assert "hold('training',mount==='training')" in SHELL_DOC
    assert 'returnToHandsPage' in SHELL_DOC

    # Browser-smoke orchestration: single frozen entry point, driver smokes
    # registered and run, and the shell measurement stays opt-in.
    assert 'run: python3 tests/trainer/smoke_trainer.py' in WORKFLOW
    assert 'DRIVER_SMOKES = (' in SMOKE_TRAINER
    assert 'def run_driver_smokes() -> None:' in SMOKE_TRAINER
    assert 'run_driver_smokes()' in SMOKE_TRAINER.split('if __name__ == "__main__":', 1)[1]
    shell_doc_flat = ' '.join(SHELL_DOC.split())
    for documented in (
        '.github/workflows/trainer-smoke.yml',
        'tests/trainer/smoke_trainer.py',
        'DRIVER_SMOKES',
        'run_driver_smokes()',
        'DESKTOP_SHELL_BROWSER_CHECK',
        '--browser',
        'document.scrollingElement.scrollHeight <= clientHeight',
    ):
        assert documented in shell_doc_flat, documented

    # No contradiction with the sibling contracts, and the concerned contracts
    # reference this document.
    assert 'docs/shared-components.md' in SHELL_DOC
    assert 'docs/opponent-range-display-contract.md' in SHELL_DOC
    assert 'docs/spotlab-view.md' in SHELL_DOC
    assert 'no bundler' in shell_doc_flat
    assert 'bundler' in SHARED_DOC
    assert 'docs/ux-desktop-view-shell.md' in SPOTLAB_DOC
    assert 'docs/ux-desktop-view-shell.md' in DISPLAY_DOC


def main() -> None:
    nav = block('<nav id="quickNav"', '</nav>')
    links = [line.strip() for line in nav.splitlines() if line.strip().startswith('<a ')]
    assert len(links) == 5, links
    for label, href, domain in (
        ('Review', '#historiesSection', 'review'),
        ('Training', '#trainerPage', 'training'),
        ('Strategy', './hero-ranges.html', 'strategy'),
        ('Equity Lab', '#equityLabSection', 'equity-lab'),
        ('Settings', '#settingsSection', 'settings'),
    ):
        assert f'href="{href}"' in nav, (label, nav)
        assert f'data-product-domain="{domain}"' in nav, (label, nav)
        assert f'>{label}</a>' in nav, (label, nav)

    # Former calculator implementation details are no longer global destinations.
    for legacy in ('Replayer', 'Adversaires', 'Cartes', 'Range adverse', '>Calcul</a>'):
        assert legacy not in nav, legacy

    # The App shell owns the view state: state.appView is the single source of
    # truth and covers every mode, Home included.
    assert 'appView:"home"' in INDEX
    assert 'const APP_VIEWS=["home","review","replayer","spotlab","training","strategy"];' in INDEX
    assert 'function updateAppView(' in INDEX
    assert "document.querySelectorAll('[data-view-shell]').forEach" in INDEX
    for view in ('home', 'review', 'spotlab', 'training', 'replayer', 'strategy'):
        assert f'data-view-shell="{view}"' in INDEX, view
    assert 'id="homePage"' in INDEX
    assert 'id="spotlabPage"' in INDEX
    assert 'id="strategyPage"' in INDEX

    # Home is the landed mode screen with the five mode cards.
    home = block('<div id="homePage"', '<div id="mainPage"')
    for label in ('Review', 'Training', 'Stratégie Hero', 'Spot Lab', 'Packs/paramètres'):
        assert f'<span class="mode-card-title">{label}</span>' in home, (label, home)
    assert home.count('class="mode-card"') == 5, home
    for view in ('review', 'training', 'strategy', 'spotlab'):
        assert f'data-app-view="{view}"' in home, view

    # The compact Home banner reuses the shared identity/runtime surfaces.
    banner = block('<div class="home-banner"', '<div class="mode-cards"')
    for identity_id in ('activePopulationIdentity', 'activeStrategyIdentity', 'activeStrategySourceIdentity', 'runtimeIdentityDetails'):
        assert f'id="{identity_id}"' in banner, identity_id

    # Functionality remains present under Review / Equity Lab instead of being deleted.
    for element_id in ('replayerSection', 'opponentsSection', 'cardsSection', 'rangeDisplaySection', 'equitySection'):
        assert f'id="{element_id}"' in INDEX, element_id
    assert 'id="equityLabSection"' in INDEX
    assert 'id="settingsSection"' in INDEX
    assert 'id="runtimeIdentityDetails"' in INDEX
    assert 'id="localPersistenceDetails"' in INDEX
    assert 'id="reviewDashboard"' in INDEX
    assert 'id="historiesSection"' in INDEX

    # Review and Spot Lab are distinct mounts: the inbox lives under Review, the
    # equity workspace under Spot Lab, independent from the scroll position.
    review = block('<div id="mainPage"', '<div id="strategyPage"')
    assert 'id="reviewDashboard"' in review and 'id="historiesSection"' in review, review
    spotlab = block('<div id="spotlabPage"', '<div id="mainPage"')
    assert 'id="equityLabSection"' in spotlab and 'id="opponentsSection"' in spotlab, spotlab
    assert 'id="historiesSection"' not in spotlab, spotlab

    # Packs are secondary Settings content, never a sixth primary destination.
    settings = block('<section id="settingsSection"', '</section>')
    assert '<a href="./packs.html">Packs de population</a>' in settings
    assert 'Packs de population' not in nav

    # Main entry points mirror the four core user intentions.
    home_actions = block('<div class="actions product-home-actions"', '</div>')
    for label in ('Review', 'Training', 'Strategy', 'Equity Lab'):
        assert label in home_actions, (label, home_actions)

    # quickNav and the mode cards route through appView instead of scrolling; the
    # strategy domain is an in-app mode and #hash deep links are mapped too.
    handler = block('document.querySelectorAll(".quick-nav a").forEach', 'updateCalcReady();')
    assert 'if(!href.startsWith("#")) return;' in handler
    assert 'if(id==="trainerPage")' in handler
    assert 'trainerOpenBtn?.click()' in handler
    assert 'openAppView(' in handler
    assert 'focusAppSection(' in handler
    assert 'appViewForHashTarget' in INDEX
    assert 'window.addEventListener("hashchange"' in INDEX
    assert 'routeFromHash();' in INDEX
    assert 'data-home-back' in INDEX
    assert 'function goHome()' in INDEX

    # appView is persisted through the prefs whitelist and restored on load.
    prefs = block('function currentLocalPrefs()', 'function schedulePersistPrefs')
    assert 'appView:state.appView' in prefs
    restore = block('async function restoreLocalState', 'renderSlots();')
    assert 'APP_VIEWS.includes(prefs.appView)' in restore
    assert 'prefs?.appView==="replayer"&&state.selectedHand' in restore

    check_ux_desktop_view_shell_doc()
    print('product architecture contract checks: OK')
    print('ux desktop view shell doc contract checks: OK')


if __name__ == '__main__':
    main()

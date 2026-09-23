#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX = (ROOT / 'site/index.html').read_text(encoding='utf-8')


def block(start: str, end: str) -> str:
    return INDEX.split(start, 1)[1].split(end, 1)[0]


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

    print('product architecture contract checks: OK')


if __name__ == '__main__':
    main()

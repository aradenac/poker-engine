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

    # Functionality remains present under Review / Equity Lab instead of being deleted.
    for element_id in ('replayerSection', 'opponentsSection', 'cardsSection', 'rangeDisplaySection', 'equitySection'):
        assert f'id="{element_id}"' in INDEX, element_id
    assert 'id="equityLabSection"' in INDEX
    assert 'id="settingsSection"' in INDEX
    assert 'id="runtimeIdentityDetails"' in INDEX
    assert 'id="localPersistenceDetails"' in INDEX

    # Packs are secondary Settings content, never a sixth primary destination.
    settings = block('<section id="settingsSection"', '</section>')
    assert '<a href="./packs.html">Packs de population</a>' in settings
    assert 'Packs de population' not in nav

    # Main entry points mirror the four core user intentions.
    home = block('<div class="actions product-home-actions"', '</div>')
    for label in ('Review', 'Training', 'Strategy', 'Equity Lab'):
        assert label in home, (label, home)

    # Hash navigation is handled in-app; Strategy remains a normal page URL.
    handler = block('document.querySelectorAll(".quick-nav a").forEach', 'updateCalcReady();')
    assert 'if(!href.startsWith("#")) return;' in handler
    assert 'if(id==="trainerPage")' in handler
    assert 'trainerOpenBtn?.click()' in handler
    assert "id==='replayerSection'" not in handler

    print('product architecture contract checks: OK')


if __name__ == '__main__':
    main()

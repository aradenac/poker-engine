#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX = (ROOT / "site/index.html").read_text(encoding="utf-8")
TRAINER = (ROOT / "site/trainer.js").read_text(encoding="utf-8")


def main() -> None:
    # #208 owns global navigation; this contract now checks vocabulary in its
    # functional surfaces rather than requiring implementation-detail nav entries.
    nav = INDEX.split('<nav id="quickNav"', 1)[1].split('</nav>', 1)[0]
    assert '<a href="#rangesSection">Ranges</a>' not in nav
    assert '<a href="./hero-ranges.html">Ranges Hero</a>' not in nav
    assert '<a href="#rangeDisplaySection">Range</a>' not in nav
    assert 'data-product-domain="strategy">Strategy</a>' in nav

    # CENTRAL-UI consistently names imported vs estimated opponent distributions.
    assert '<h2>Sources et modèles</h2>' in INDEX
    assert '<h2>Range adverse</h2>' in INDEX
    assert 'Importer une range source' not in nav
    assert '>Range adverse</button>' in INDEX
    assert 'Range adverse estimée · ${player.name}' in INDEX
    assert '"Range source importée"' in INDEX
    assert 'Position dans la range source' in INDEX

    # Hero terminology is strategy-oriented in H-owned surfaces.
    assert 'Stratégie Hero <b id="activeStrategyIdentity">Custom</b>' in INDEX
    assert 'data-product-domain="strategy">Strategy</a>' in INDEX
    assert 'stratégie Hero Custom' in TRAINER
    assert 'ranges Hero Custom' not in TRAINER
    assert ' · range Custom' not in TRAINER

    # Internal identifiers stay stable; this is a vocabulary-only migration.
    assert 'state.ranges' in INDEX
    assert 'populationRangeEstimateForPlayer' in INDEX

    print('range vocabulary contract checks: OK')


if __name__ == '__main__':
    main()

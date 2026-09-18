#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX = (ROOT / "site/index.html").read_text(encoding="utf-8")
TRAINER = (ROOT / "site/trainer.js").read_text(encoding="utf-8")


def main() -> None:
    # Navigation has one explicit name per concept.
    assert '<a href="#rangesSection">Sources importées</a>' in INDEX
    assert '<a href="./hero-ranges.html">Stratégie Hero</a>' in INDEX
    assert '<a href="#rangeDisplaySection">Range adverse</a>' in INDEX
    assert '<a href="#rangesSection">Ranges</a>' not in INDEX
    assert '<a href="./hero-ranges.html">Ranges Hero</a>' not in INDEX
    assert '<a href="#rangeDisplaySection">Range</a>' not in INDEX

    # CENTRAL-UI consistently names imported vs estimated opponent distributions.
    assert '<h2>1. Importer une range source</h2>' in INDEX
    assert '<h2>5. Range adverse affichée</h2>' in INDEX
    assert '>Range adverse</button>' in INDEX
    assert 'Range adverse estimée · ${player.name}' in INDEX
    assert '"Range source importée"' in INDEX
    assert 'Position dans la range source' in INDEX

    # Hero terminology is strategy-oriented in H-owned surfaces.
    assert '>Stratégie Hero</a>' in INDEX
    assert 'stratégie Hero Custom' in TRAINER
    assert 'ranges Hero Custom' not in TRAINER
    assert ' · range Custom' not in TRAINER

    # Internal identifiers stay stable; this is a vocabulary-only migration.
    assert 'state.ranges' in INDEX
    assert 'populationRangeEstimateForPlayer' in INDEX

    print('range vocabulary contract checks: OK')


if __name__ == '__main__':
    main()

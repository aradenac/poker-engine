#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX = (ROOT / 'site/index.html').read_text(encoding='utf-8')
TRAINER = (ROOT / 'site/trainer.js').read_text(encoding='utf-8')

def block(start: str, end: str) -> str:
    return INDEX.split(start, 1)[1].split(end, 1)[0]

def main() -> None:
    # No contradictory legacy version is exposed in the main product chrome.
    assert '<title>Poker Range Equity — Offline</title>' in INDEX
    assert '<title>Poker Range Equity — Offline v83</title>' not in INDEX
    assert '<h1>Poker Range Equity</h1>' in INDEX
    assert '>v78</span>' not in INDEX
    assert 'moteur v61' not in INDEX.lower()

    # Active population and Hero strategy are first-level identity.
    identity = block('<div class="product-identity"', '<details id="runtimeIdentityDetails"')
    assert 'Population <b id="activePopulationIdentity">' in identity
    assert 'Stratégie Hero <b id="activeStrategyIdentity">Custom</b>' in identity

    # Technical versions/provenance remain available, but only in collapsed Advanced.
    runtime = block('<details id="runtimeIdentityDetails"', '<div class="local-persistence">')
    assert '<details id="runtimeIdentityDetails" class="runtime-identity" open' not in INDEX
    for marker in ('runtimeAppVersion', 'runtimeEngineVersion', 'runtimeModelAIdentity',
                   'runtimeModelBIdentity', 'runtimeRevisionIdentity', 'runtimeHashIdentity'):
        assert f'id="{marker}"' in runtime, marker
    assert 'Application<b id="runtimeAppVersion">v83</b>' in runtime
    assert 'Engine<b id="runtimeEngineVersion">v83</b>' in runtime

    # Trainer first level prioritizes active population/strategy; A/B versions stay Advanced.
    trainer_head = block('<div class="trainer-head">', '<div class="trainer-grid">')
    assert 'id="trainerPopulationIdentity"' in trainer_head
    assert 'Model A v5' not in trainer_head
    assert 'Model B v2' not in trainer_head
    tech = block('<summary>Détails techniques du Trainer</summary>', '</details>')
    assert 'Model A v5' in tech and 'Model B v2' in tech
    assert 'id="trainerTechnicalIdentity"' in tech
    assert 'Trainer prêt · ${trainerState.populationId} · stratégie Hero Custom.' in TRAINER
    assert 'Trainer prêt · ${trainerState.populationId} · Model A v5 + Model B v2' not in TRAINER
    assert 'Chargement de la population et de la stratégie…' in TRAINER
    assert 'Calcul de la recommandation Model A…' not in TRAINER

    # Runtime release identity is sourced from RELEASE.json, not duplicated version literals.
    release_loader = block('async function loadRuntimeReleaseIdentity()', 'const LOCAL_DB_NAME')
    assert 'fetch("./RELEASE.json",{cache:"no-store"})' in release_loader
    assert 'engine_release' in release_loader
    assert 'assets_tree_git_sha' in release_loader
    assert 'sha256' in release_loader

    print('product identity UX contract checks: OK')

if __name__ == '__main__':
    main()

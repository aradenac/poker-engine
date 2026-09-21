#!/usr/bin/env python3
import json
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
    assert '<h1>Review</h1>' in INDEX
    assert 'Que faut-il revoir ou travailler maintenant ?' in INDEX
    assert 'id="reviewDashboard"' in INDEX
    assert '>v78</span>' not in INDEX
    assert 'moteur v61' not in INDEX.lower()

    # Active population and Hero strategy are first-level identity.
    identity = block('<div class="product-identity"', '<details id="runtimeIdentityDetails"')
    assert 'Population <b id="activePopulationIdentity">' in identity
    assert 'Stratégie Hero <b id="activeStrategyIdentity">stratégie indisponible</b>' in identity
    assert 'id="activeStrategySourceIdentity"' in identity
    assert 'id="activeStrategyFailClose"' in identity
    assert 'Stratégie indisponible pour cette population' in identity
    assert 'id="personalOverrideIdentity"' in identity
    assert '>Custom<' not in identity
    # The resolver and the safe personal-override migration are wired into the page.
    assert '<script src="./hero-ranges.js"></script>' in INDEX
    assert '<script src="./hero-range-migration.js"></script>' in INDEX
    assert '<script src="./hero-strategy-resolver.js"></script>' in INDEX

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
    assert 'stratégie Hero Custom' not in TRAINER
    assert 'Trainer prêt · ${trainerState.populationId} · stratégie Hero Custom.' not in TRAINER
    assert 'TRAINER_HERO_FAIL_CLOSE="Stratégie indisponible pour cette population"' in TRAINER
    assert 'PokerHeroStrategyResolver' in TRAINER
    assert 'PokerHeroRangeMigration' in TRAINER
    assert 'trainerRefreshHeroStrategyIdentity' in TRAINER
    # #task-8zr: the personal override is contextual. `available` reports a
    # population-wide presence; `active` is resolved on the exact current context
    # and defaults to false (fail-safe) when the context is not resolvable. A bare
    # global presence must never be reported as an active override.
    assert 'trainerHeroOverrideContext' in TRAINER
    assert 'personalOverrideStatus' in TRAINER
    assert 'personalOverrideStatus(repository,{populationId:population,activePopulationId:population,context})' in TRAINER
    assert 'ctx.context_id' in TRAINER
    assert 'context.preflop_context_id=preflopContextId' in TRAINER
    assert '/^PFC_[0-9a-f]{16}$/i.test(contextId)' in TRAINER
    assert 'available:false,active:false' in TRAINER
    assert 'active:overrides.length>0' not in TRAINER
    # A retained reference is provenance only: Trainer surfaces require the
    # calculated strategy admission status, independently of fail_closed.
    assert 'resolution.status!=="ADMISSIBLE_CALCULATED"' in TRAINER
    assert 'référence retenue non admissible${version}' not in TRAINER
    assert 'Trainer prêt · ${trainerState.populationId} · Model A v5 + Model B v2' not in TRAINER
    assert 'Chargement de la population et de la stratégie…' in TRAINER
    assert 'Calcul de la recommandation Model A…' not in TRAINER

    # #task-0jt: the Trainer forwards the complete admission binding
    # (role/hash/provenance/candidate/generation/binding) and the declared
    # coverage bound, instead of a bare {status,population_id} token.
    for marker in (
        'trainerHeroAdmissionFromProvenance',
        'role:"hero_strategy"',
        'declared_sha256',
        'actual_sha256',
        'source_path',
        'binding_sha256',
        'candidate_id',
        'generation_id',
        'trainerHeroCoverageBound',
        'required_context_keys',
        'generation_manifest',
    ):
        assert marker in TRAINER, marker
    assert 'status:provenance.status,population_id:provenance.population_id' not in TRAINER
    assert 'Custom' not in TRAINER

    # The population provenance exposes the explicit binding tokens. The legacy
    # reference keeps its candidate/generation/binding null and stays
    # RETAIN_REFERENCE: it is never promoted, never relabelled MIXED -> Zoom.
    population = json.loads((ROOT / 'site/assets/trainer/population.json').read_text(encoding='utf-8'))
    provenance = population['hero_provenance']
    assert provenance['status'] == 'RETAIN_REFERENCE'
    assert provenance['admissible'] is False
    assert provenance['promotable'] is False
    assert provenance['candidate_id'] is None
    assert provenance['generation_id'] is None
    assert provenance['binding_sha256'] is None
    assert provenance['sha256'] and provenance['ranges_path'] and provenance['source_type']
    assert 'zoom' not in provenance['population_id']
    assert population['population_identity']['format'] == 'MIXED_ZOOM_REGULAR'

    # The header computes the identity trio dynamically: population, Hero strategy
    # source/version and the personal-override active state.
    ui = block('function productHeroStrategyResolution(){', 'async function loadRuntimeReleaseIdentity()')
    assert 'activeStrategyIdentity.textContent' in ui
    assert 'activeStrategySourceIdentity.textContent' in ui
    assert 'activeStrategyFailClose' in ui
    assert 'personalOverrideIdentity.textContent' in ui
    # #task-8zr: the override chip reflects the contextual `active` flag only,
    # never the mere global presence of an override (nor the resolver source).
    assert 'overrideActive=!!(override&&override.active===true)' in ui
    assert 'personalOverrideIdentity.textContent=overrideActive?"actif":"inactif"' in ui
    assert 'override?override.active===true:(resolution?resolution.source==="PERSONAL_OVERRIDE":false)' not in ui
    assert 'heroStrategyResolution' in ui
    assert 'identity:"Stratégie indisponible pour cette population"' in ui
    assert 'retenue non admissible' in ui

    # Runtime release identity is sourced from RELEASE.json, not duplicated version literals.
    release_loader = block('async function loadRuntimeReleaseIdentity()', 'const LOCAL_DB_NAME')
    assert 'fetch("./RELEASE.json",{cache:"no-store"})' in release_loader
    assert 'engine_release' in release_loader
    assert 'assets_tree_git_sha' in release_loader
    assert 'sha256' in release_loader

    print('product identity UX contract checks: OK')

if __name__ == '__main__':
    main()

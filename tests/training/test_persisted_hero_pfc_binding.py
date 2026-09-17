#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training.enrich_hero_range_context import canonical_context_for_state  # noqa: E402
from tools.training.generate_hero_range_decisions import ContextSpec, build_context_state  # noqa: E402

RUN = ROOT / 'training/runs/20260917_hero_preflop_169_btn_unopened_pfc_v1'
SOURCE = ROOT / 'training/runs/20260917_hero_preflop_169_btn_unopened_v1'


def stable_sha(value) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()
    return hashlib.sha256(payload).hexdigest()


def main() -> None:
    binding = json.loads((RUN / 'PFC_BINDING.json').read_text(encoding='utf-8'))
    repo = json.loads((RUN / 'HERO_RANGE_REPOSITORY_PFC.json').read_text(encoding='utf-8'))
    source_repo = json.loads((SOURCE / 'HERO_RANGE_REPOSITORY.json').read_text(encoding='utf-8'))

    assert binding['schema'] == 'poker-hero-range-pfc-binding/v1'
    assert binding['status'] == 'EXPERIMENTAL'
    assert binding['promotion_authorized'] is False
    assert binding['coverage'] == {'requested': 169, 'supported': 40, 'unsupported': 129, 'accounted': 169}
    assert binding['selection_boundary']['validation_consumed'] is False
    assert binding['selection_boundary']['test_consumed'] is False
    assert binding['handoff_to_issue_108']['nearest_context_substitution'] is False

    spec = ContextSpec(position='BTN', spot='UNOPENED', effective_stack_bb=100)
    canonical = canonical_context_for_state(build_context_state(spec), 'BTN')
    assert canonical == binding['canonical_preflop_context']
    assert canonical['context_id'] == binding['preflop_context_id']
    assert canonical['context_id'] == 'PFC_0e01f7d1a1da491b'
    assert binding['identity_transform']['decision_payload_mutation'] == 'NONE'
    assert binding['identity_transform']['rollout_recomputation'] is False

    source_key, source_node = next(iter(source_repo['contexts'].items()))
    target_key, target_node = next(iter(repo['contexts'].items()))
    assert target_key == source_key + '|' + canonical['context_id']
    assert target_node['context']['preflop_context_id'] == canonical['context_id']
    assert target_node['layers']['personal'] == source_node['layers']['personal']
    assert target_node['layers']['calculated']['hands'] == source_node['layers']['calculated']['hands']
    assert target_node['layers']['calculated']['version'] == source_node['layers']['calculated']['version']
    assert len(target_node['layers']['calculated']['hands']) == 40

    source_prov = dict(source_node['layers']['calculated']['provenance'])
    target_prov = dict(target_node['layers']['calculated']['provenance'])
    identity = target_prov.pop('context_identity')
    assert target_prov == source_prov
    assert identity == binding['identity_transform']

    assert stable_sha(target_node['layers']['calculated']['hands']) == binding['source_evidence']['calculated_hands_canonical_sha256']
    repo_sha = hashlib.sha256((RUN / 'HERO_RANGE_REPOSITORY_PFC.json').read_bytes()).hexdigest()
    assert repo_sha == binding['artifact_sha256']['hero_range_repository_pfc']

    print(json.dumps({
        'preflop_context_id': canonical['context_id'],
        'supported': len(target_node['layers']['calculated']['hands']),
        'unsupported': binding['coverage']['unsupported'],
        'decision_payload_mutation': identity['decision_payload_mutation'],
        'validation_consumed': binding['selection_boundary']['validation_consumed'],
        'test_consumed': binding['selection_boundary']['test_consumed'],
    }, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""#419 exact-tree #367 preflight v2 regressions (no Hero EV, no holdout).

The preflight walks the 38 required nodes of the #388/#419 exact tree of
scenario #321 plus its 7 raise-sizing frontiers, queries the hierarchical
Model-A provider per exact key and records the exact key, node identity,
empirical support, pooling provenance, uncertainty, posterior identity and the
protocol-v2 node closure.

These tests pin the v2 admissibility rule -- ``EXACT_EMPIRICAL_STRONG`` (layer A,
unchanged 20/20 L0 rule) *or* ``EXACT_HIERARCHICAL_ESTIMATE`` gated by the
conjunction of the seven frozen layer-B gates -- and the boundary: no nearest-*
substitution is applied, no Hero EV/recommendation is computed, no
VALIDATION/TEST hand is read, ``required_tree_complete`` follows the strict
closure conjunction only, and the superseded v1 bundle is byte-pinned and
declared superseded instead of being regenerated: its payload embeds the digest of
the superseded v1 tool, so a byte-identical re-derivation is impossible and the
``v1`` revision is never written.
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.preflop import model_a_sizing_hierarchical as H  # noqa: E402
from tools.simulation import issue419_exact_tree_preflight as preflight_tool  # noqa: E402
from tools.training import validation_order_guard as guard  # noqa: E402
from tools.training.audit_preflop_sizing_support import stable_hash  # noqa: E402

# Synthetic public whitelists: one exact key whose own support is thin and a
# sibling stack bucket that only the L1 parent level can pool toward.
BASE_WHITELIST = {
    "family": "VS_ISO",
    "actor_position": "BB",
    "aggressor_position": "SB",
    "limper_count": 2,
    "caller_count": 0,
    "target_total_bb": 5.0,
    "to_call_bb": 4.0,
    "table_size": 6,
    "raise_level": 1,
    "live_positions": ["BB", "BTN", "CO", "SB"],
    "all_in_positions": [],
    "history": [
        {"position": "CO", "action": "LIMP"},
        {"position": "BTN", "action": "LIMP"},
        {"position": "SB", "action": "RAISE"},
    ],
    "pot_before_bb": 8.0,
    "effective_stack_bucket": "GT75_LE125",
}
LEGAL = ["FOLD", "CALL", "RAISE", "JAM"]
# Explicit, test-only calibration evidence. The preflight itself never reads the
# VALIDATION split, so the frozen CALIBRATION gate is unevaluated there.
PASSING_CALIBRATION = {
    "source": "TEST_ONLY_EXPLICIT_EVIDENCE",
    "pooled_ece": 0.01,
    "ece_delta_vs_active": 0.0,
    "bins_meeting_minimum_support": 25,
}
FAILING_CALIBRATION = {**PASSING_CALIBRATION, "pooled_ece": 0.99}


def _whitelist(**overrides):
    whitelist = copy.deepcopy(BASE_WHITELIST)
    whitelist.update(overrides)
    return whitelist


def _rows(whitelist, count, prefix, target_total_bb=5.0):
    return [
        {
            "whitelist": copy.deepcopy(whitelist),
            "hand_id": f"{prefix}-{index}",
            "action": LEGAL[index % len(LEGAL)],
            "target_total_bb": target_total_bb,
        }
        for index in range(count)
    ]


def _empirical_response():
    """A synthetic L0 node with 24/24 observations and honest raise sizing."""
    whitelist = _whitelist()
    candidate = H.make_synthetic_hierarchical_candidate(
        population_id="preflight-test", observations=_rows(whitelist, 24, "empirical")
    )
    return H.resolve_exact_context(
        candidate=candidate,
        requested_key=H.hierarchical_exact_key_from_whitelist(whitelist),
        legal_actions=LEGAL,
    )


def _estimate_response():
    """A synthetic node closed only by the exact-context estimate path."""
    exact = _whitelist()
    parent = _whitelist(effective_stack_bucket="LE40")
    candidate = H.make_synthetic_hierarchical_candidate(
        population_id="preflight-test",
        observations=_rows(exact, 4, "thin") + _rows(parent, 24, "parent"),
    )
    return H.resolve_exact_context(
        candidate=candidate,
        requested_key=H.hierarchical_exact_key_from_whitelist(exact),
        legal_actions=LEGAL,
    )


def _response_with(observations):
    """Whatever the provider answers for one exact key given these TRAIN observations."""
    exact = _whitelist()
    candidate = H.make_synthetic_hierarchical_candidate(
        population_id="preflight-test", observations=observations
    )
    return H.resolve_exact_context(
        candidate=candidate,
        requested_key=H.hierarchical_exact_key_from_whitelist(exact),
        legal_actions=LEGAL,
    )


def _unresolved_response(*, observations):
    """A node the provider cannot answer: no support and/or no admissible pooling."""
    return _response_with(observations)


CLOSED_TREE_CONDITIONS = dict(
    frontier_count=0,
    nodes_with_unresolved_raise_sizing=0,
    manifest_unresolved_frontier_count=0,
    tree_enumeration_complete=True,
    manifest_tree_enumeration_complete=True,
    substitutions_applied=0,
    key_separation_probes_passed=True,
    hero_ev_executed=False,
    recommendation_computed=False,
    rollouts_executed=0,
    ev_values_computed=0,
)


class ExactTreePreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output = preflight_tool.V2_OUTPUT
        cls.index = json.loads((cls.output / preflight_tool.INDEX_NAME).read_text())
        cls.preflight = json.loads((cls.output / preflight_tool.V2_NAME).read_text())
        cls.raw_bytes = (cls.output / preflight_tool.V2_NAME).read_bytes()
        cls.tree = json.loads(
            (ROOT / "analysis/issue388_exact_tree/REQUIRED_EXACT_TREE.json").read_text()
        )

    # ------------------------------------------------------------- artifact
    def test_bundle_is_content_addressed_and_canonical(self):
        self.assertIn(preflight_tool.V2_NAME, self.index)
        self.assertIn(preflight_tool.SUMMARY_NAME, self.index)
        for name, entry in self.index.items():
            data = (self.output / name).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), entry['sha256'], name)
            self.assertEqual(data, (self.output / entry['object']).read_bytes(), name)
        self.assertEqual(
            {p.name for p in (self.output / 'sha256').iterdir()},
            {Path(entry['object']).name for entry in self.index.values()},
        )
        entry = self.index[preflight_tool.V2_NAME]
        self.assertEqual(entry['canonical_payload_sha256'], stable_hash(self.preflight))
        self.assertEqual(self.preflight['schema'], preflight_tool.V2_SCHEMA)
        self.assertEqual(self.preflight['supersedes_schema'], preflight_tool.SCHEMA)
        self.assertEqual(self.preflight['issue'], 419)
        self.assertEqual(self.preflight['source_issue'], 388)
        self.assertEqual(self.preflight['scenario_issue'], 321)

    def test_frozen_v1_bundle_is_re_verified_and_never_rewritten(self):
        custody = self.preflight['frozen_v1_preflight']
        self.assertEqual(custody['result'], 'PASS')
        self.assertTrue(custody['never_rewritten'])
        self.assertEqual(custody['bundle'], preflight_tool._relative(preflight_tool.OUTPUT))
        self.assertEqual(
            custody['artifacts'][preflight_tool.NAME], preflight_tool.V1_PREFLIGHT_SHA256
        )
        self.assertEqual(
            custody['artifacts'][preflight_tool.SUMMARY_NAME], preflight_tool.V1_SUMMARY_SHA256
        )
        self.assertEqual(
            custody['artifacts'][preflight_tool.INDEX_NAME], preflight_tool.V1_INDEX_SHA256
        )
        # The pins are re-derived from the bytes on disk, not merely asserted.
        for name, pinned in (
            (preflight_tool.NAME, preflight_tool.V1_PREFLIGHT_SHA256),
            (preflight_tool.SUMMARY_NAME, preflight_tool.V1_SUMMARY_SHA256),
            (preflight_tool.INDEX_NAME, preflight_tool.V1_INDEX_SHA256),
        ):
            with self.subTest(name=name):
                self.assertEqual(
                    hashlib.sha256((preflight_tool.OUTPUT / name).read_bytes()).hexdigest(),
                    pinned,
                )
        self.assertEqual(preflight_tool.verify_frozen_v1_preflight()['result'], 'PASS')
        # The v2 bundle never writes into the frozen v1 directory.
        self.assertNotEqual(preflight_tool.V2_OUTPUT.resolve(), preflight_tool.OUTPUT.resolve())

    def test_walks_every_required_node_and_sizing_frontier_by_exact_key(self):
        nodes = self.preflight['nodes']
        self.assertEqual(self.preflight['nodes_queried'], 38)
        self.assertEqual(len(nodes), 38)
        self.assertEqual(self.preflight['sizing_frontiers_queried'], 7)
        self.assertEqual(len(self.preflight['sizing_frontiers']), 7)
        by_id = {node['id']: node for node in self.tree['nodes']}
        seen_paths = set()
        for index, record in enumerate(nodes):
            with self.subTest(node=record['node_identity']['node_id']):
                identity = record['node_identity']
                source = by_id[identity['node_id']]
                self.assertEqual(record['index'], index)
                self.assertEqual(record['exact_key'], source['audit_exact_key'])
                self.assertEqual(identity['audit_exact_key'], source['audit_exact_key'])
                self.assertEqual(
                    identity['runtime_support_context_key'], source['runtime_support_context_key']
                )
                self.assertEqual(
                    identity['runtime_exact_preflop_node_key'],
                    source['runtime_exact_preflop_node_key'],
                )
                self.assertEqual(identity['path'], list(source['path']))
                self.assertTrue(identity['exact_key_matches_manifest'])
                self.assertTrue(identity['exact_key_matches_required_tree'])
                self.assertEqual(identity['identity_granularity'], 'hierarchical_exact_key')
                for field in (
                    'empirical_support',
                    'pooling_provenance',
                    'pooling_diagnostics',
                    'uncertainty',
                    'posterior_identity',
                    'node_closure',
                ):
                    self.assertIn(field, record)
                self.assertIn('observations', record['empirical_support'])
                self.assertIn('distinct_hands', record['empirical_support'])
                self.assertEqual(len(record['pooling_diagnostics']), 5)
                seen_paths.add(tuple(identity['path']))
        self.assertEqual(len(seen_paths), 38)

        required_keys = {node['audit_exact_key'] for node in by_id.values()}
        frontier_paths = set()
        for frontier in self.preflight['sizing_frontiers']:
            self.assertEqual(frontier['exact_key'], frontier['requested_key'])
            self.assertEqual(frontier['action'], 'RAISE')
            self.assertIn(frontier['exact_key'], required_keys)
            self.assertIsNone(frontier['exactly_supported_target_bb'])
            self.assertIsNone(frontier['admitted_target_bb'])
            self.assertFalse(
                frontier['descendant_closure']['enumerable_without_a_representative_price']
            )
            self.assertFalse(frontier['descendant_closure']['pruned_as_zero_mass'])
            self.assertEqual(frontier['disposition'], 'UNRESOLVED_FRONTIER_NOT_PRUNED')
            frontier_paths.add(tuple(frontier['path']))
        self.assertEqual(len(frontier_paths), 7)

    # ------------------------------------------------------- v2 admissibility
    def test_required_tree_complete_reflects_the_v2_closure_conjunction(self):
        admissibility = self.preflight['admissibility']
        conditions = admissibility['conditions']
        self.assertFalse(self.preflight['required_tree_complete'])
        self.assertEqual(
            self.preflight['required_tree_complete'],
            all(condition['satisfied'] for condition in conditions.values()),
        )
        self.assertEqual(admissibility['rule_id'], preflight_tool.NODE_CLOSURE_RULE_ID)
        self.assertEqual(admissibility['admissible_exact_nodes'], 0)
        self.assertEqual(admissibility['blocked_nodes'], 38)
        self.assertEqual(len(admissibility['blocked_node_paths']), 38)
        self.assertEqual(
            admissibility['admissibility_class_counts'],
            {'EXACT_EMPIRICAL_STRONG': 0, 'EXACT_HIERARCHICAL_ESTIMATE': 0, 'EXACT_UNRESOLVED': 38},
        )
        self.assertEqual(admissibility['closed_as_exact_support_nodes'], 0)
        self.assertFalse(self.preflight['required_tree']['tree_enumeration_complete'])
        self.assertEqual(self.preflight['required_tree']['required_node_count'], 38)
        self.assertEqual(self.preflight['required_tree']['unresolved_sizing_frontier_count'], 7)
        self.assertEqual(self.preflight['required_tree']['distinct_exact_keys'], 38)
        self.assertGreater(self.preflight['required_tree']['runtime_keys_merging_exact_states'], 0)
        self.assertFalse(
            conditions['every_required_node_closed_by_an_admissible_answer']['satisfied']
        )
        self.assertEqual(
            conditions['every_required_node_closed_by_an_admissible_answer']['reason_code'],
            preflight_tool.REFUSED_REQUIRED_NODE_OPEN,
        )
        self.assertFalse(conditions['no_unresolved_raise_sizing_frontier']['satisfied'])
        self.assertFalse(conditions['required_tree_fully_enumerated']['satisfied'])
        self.assertTrue(conditions['no_nearest_or_borrowed_substitution_applied']['satisfied'])
        self.assertTrue(conditions['no_hero_ev_or_recommendation_computed']['satisfied'])
        self.assertTrue(conditions['no_pooled_estimate_is_counted_as_exact_support']['satisfied'])
        # Every unsatisfied condition carries at least one reason code.
        for name, condition in conditions.items():
            with self.subTest(condition=name):
                if not condition['satisfied']:
                    self.assertTrue(condition['reason_codes'], name)
                    self.assertTrue(condition['reason_code'], name)
        reason_codes = self.preflight['required_tree_complete_reason_codes']
        self.assertTrue(reason_codes)
        for expected in (
            preflight_tool.REFUSED_REQUIRED_NODE_OPEN,
            preflight_tool.REFUSED_UNRESOLVED_RAISE_SIZING_FRONTIER,
            preflight_tool.REFUSED_TREE_ENUMERATION_INCOMPLETE,
            'NO_ADMISSIBLE_POOLING_LEVEL',
            'RAISE_SIZING_UNRESOLVED_NO_NEAREST_PRICE',
            'REFUSED_RAISE_SIZING_FRONTIER',
        ):
            with self.subTest(reason_code=expected):
                self.assertIn(expected, reason_codes)
        self.assertEqual(
            self.preflight['nodes'][0]['empirical_support']['thresholds'],
            {'minimum_marginal_observations': 20, 'minimum_distinct_hands': 20},
        )
        for record in self.preflight['nodes']:
            self.assertFalse(record['admissible_exact_answer'])
            self.assertEqual(record['admissibility_class'], 'EXACT_UNRESOLVED')
            self.assertFalse(record['counts_as_exact_support'])
            self.assertTrue(record['closure_reason_codes'])
            self.assertEqual(record['node_closure']['rule_id'], preflight_tool.NODE_CLOSURE_RULE_ID)
            self.assertEqual(record['node_closure']['status'], 'EXACT_UNRESOLVED')
            self.assertFalse(record['node_closure']['closes_the_node'])
            self.assertEqual(
                set(record['node_closure']['layer_b_gates']), set(preflight_tool.LAYER_B_GATE_IDS)
            )
            self.assertEqual(record['posterior_identity']['status'], 'EXACT_UNRESOLVED')
            self.assertFalse(record['posterior_identity']['probability_emitted'])
            self.assertIsNone(record['posterior_identity']['posterior'])
            self.assertIsNone(record['posterior_identity']['posterior_sha256'])
            self.assertIsNone(record['pooling_provenance'])
            self.assertIsNone(record['uncertainty'])
        # The frozen CALIBRATION gate is never re-measured here: it is *attested*
        # from the digest-referenced, already-consumed v1 VALIDATION bytes, and it
        # fails closed on that frozen measurement without re-opening the holdout.
        protocol_block = self.preflight['admissibility_protocol']
        self.assertEqual(protocol_block['revision'], 'v2')
        self.assertEqual(protocol_block['amendment_id'], preflight_tool.PROTOCOL_V2_AMENDMENT_ID)
        self.assertEqual(protocol_block['node_closure_rule_id'], preflight_tool.NODE_CLOSURE_RULE_ID)
        self.assertIn(
            'ATTESTED_FROM_FROZEN_V1_VALIDATION_BYTES', protocol_block['calibration_gate_status']
        )
        calibration_gate = protocol_block['calibration_gate']
        self.assertTrue(calibration_gate['evaluated'])
        self.assertFalse(calibration_gate['passed'])
        attestation = calibration_gate['evidence']['attestation']
        self.assertEqual(
            attestation['source_artifact'],
            preflight_tool._relative(preflight_tool.V1_VALIDATION_RESULT_PATH),
        )
        self.assertEqual(
            attestation['source_byte_sha256'], preflight_tool.V1_VALIDATION_RESULT_SHA256
        )
        self.assertTrue(attestation['validation_result_referenced_by_digest'])
        self.assertFalse(attestation['holdout_reopened_by_this_preflight'])
        self.assertFalse(attestation['validation_consumed_by_this_preflight'])
        self.assertFalse(attestation['validation_split_re_evaluated'])
        self.assertFalse(attestation['thresholds_re_selected'])
        self.assertFalse(attestation['hardcoded_verdict'])
        self.assertEqual(attestation['validation_decision_rows_read'], 0)
        self.assertEqual(attestation['hand_histories_parsed'], 0)
        self.assertEqual(protocol_block['calibration_thresholds']['maximum_absolute_ece'], 0.05)
        self.assertEqual(
            protocol_block['calibration_thresholds']['maximum_ece_delta_vs_active'], 0.02
        )

    def test_is_admissible_separates_empirical_support_from_gated_estimates(self):
        empirical = _empirical_response()
        self.assertEqual(empirical['status'], H.STATUS_EXACT_EMPIRICAL_STRONG)
        closure = preflight_tool.node_closure(empirical)
        self.assertEqual(closure, preflight_tool.admissibility(empirical))
        self.assertTrue(closure['closes_the_node'])
        self.assertEqual(closure['admissibility_class'], 'EXACT_EMPIRICAL_STRONG')
        self.assertTrue(closure['counts_as_exact_support'])
        self.assertFalse(closure['admissible_as_exact_context_estimate'])
        self.assertEqual(closure['reason_codes'], [])
        # Layer A closes on the unchanged 20/20 rule: no calibration evidence needed.
        self.assertTrue(preflight_tool.is_admissible(empirical))

        estimator = _estimate_response()
        self.assertEqual(estimator['status'], H.STATUS_EXACT_HIERARCHICAL_ESTIMATE)
        self.assertEqual(estimator['pooling']['level'], 'L1_STACK_POOL')
        self.assertEqual(estimator['support']['support_isolation_rule'], H.SUPPORT_ISOLATION_RULE)
        # Unevaluated calibration keeps the estimate open (fail closed).
        unevaluated = preflight_tool.node_closure(estimator)
        self.assertFalse(unevaluated['closes_the_node'])
        self.assertIn('REFUSED_CALIBRATION', unevaluated['reason_codes'])
        self.assertIn('CALIBRATION', unevaluated['unevaluated_gate_ids'])
        self.assertFalse(preflight_tool.is_admissible(estimator))
        # With every frozen gate passing the estimate closes, but never as exact support.
        admissible = preflight_tool.node_closure(
            estimator, calibration_evidence=PASSING_CALIBRATION
        )
        self.assertEqual(
            preflight_tool.admissibility(estimator, calibration_evidence=PASSING_CALIBRATION),
            admissible,
        )
        self.assertTrue(admissible['closes_the_node'])
        self.assertEqual(admissible['admissibility_class'], 'EXACT_HIERARCHICAL_ESTIMATE')
        self.assertFalse(admissible['counts_as_exact_support'])
        self.assertTrue(admissible['admissible_as_exact_context_estimate'])
        self.assertTrue(admissible['pooling_only_feeds_parameters'])
        self.assertTrue(admissible['support_is_exact_key_only'])
        self.assertTrue(admissible['layer_b_gates_consulted_for_closure'])
        self.assertEqual(admissible['reason_codes'], [])
        self.assertTrue(
            preflight_tool.is_admissible(estimator, calibration_evidence=PASSING_CALIBRATION)
        )
        # A failing calibration gate leaves the estimate open with its reason code.
        failing = preflight_tool.node_closure(estimator, calibration_evidence=FAILING_CALIBRATION)
        self.assertFalse(failing['closes_the_node'])
        self.assertEqual(failing['reason_codes'], ['REFUSED_CALIBRATION'])
        self.assertFalse(
            preflight_tool.is_admissible(estimator, calibration_evidence=FAILING_CALIBRATION)
        )
        # A thin exact key never becomes exact support just because a parent qualifies.
        self.assertLess(estimator['support']['observations'], 20)
        self.assertLess(estimator['support']['distinct_hands'], 20)

    def test_admissible_estimate_is_consumed_without_becoming_exact_support(self):
        estimator = _estimate_response()
        consumed = preflight_tool.admissibility(
            estimator, calibration_evidence=PASSING_CALIBRATION
        )
        self.assertEqual(
            consumed,
            preflight_tool.node_closure(estimator, calibration_evidence=PASSING_CALIBRATION),
        )
        self.assertTrue(consumed['closes_the_node'])
        self.assertEqual(consumed['admissibility_class'], 'EXACT_HIERARCHICAL_ESTIMATE')
        self.assertNotEqual(consumed['admissibility_class'], H.STATUS_EXACT_EMPIRICAL_STRONG)
        self.assertFalse(consumed['counts_as_exact_support'])
        self.assertTrue(consumed['admissible_as_exact_context_estimate'])
        self.assertTrue(consumed['support_is_exact_key_only'])
        self.assertTrue(consumed['pooling_only_feeds_parameters'])
        self.assertTrue(consumed['layer_b_gates_consulted_for_closure'])
        self.assertTrue(consumed['probability_emitted'])
        self.assertLess(consumed['observations'], preflight_tool.MIN_MARGINAL_OBSERVATIONS)
        self.assertLess(consumed['distinct_hands'], preflight_tool.MIN_DISTINCT_HANDS)
        self.assertTrue(
            preflight_tool.is_admissible(estimator, calibration_evidence=PASSING_CALIBRATION)
        )

        # Consuming a whole tree of admissible estimates keeps every one of them in
        # the estimate class: none is relabelled as a closed exact-support node.
        report = preflight_tool.required_tree_closure_report(
            closures=[consumed] * 7, **CLOSED_TREE_CONDITIONS
        )
        self.assertTrue(report['required_tree_complete'])
        self.assertEqual(report['reason_codes'], [])
        counts = report['conditions']['every_required_node_closed_by_an_admissible_answer']
        self.assertEqual(counts['closed_as_exact_empirical_strong'], 0)
        self.assertEqual(counts['closed_as_exact_hierarchical_estimate'], 7)
        pooled = report['conditions']['no_pooled_estimate_is_counted_as_exact_support']
        self.assertTrue(pooled['satisfied'])
        self.assertEqual(pooled['pooled_closures_counted_as_exact_support'], 0)

        # Relabelling the very same thin node as EXACT_EMPIRICAL_STRONG launders
        # nothing: it keeps its L1 pooling level and its sub-threshold exact counts,
        # so both closure paths refuse it and it is consumed as EXACT_UNRESOLVED.
        relabelled = copy.deepcopy(estimator)
        relabelled['status'] = H.STATUS_EXACT_EMPIRICAL_STRONG
        relabelled['reason_code'] = H.STATUS_EXACT_EMPIRICAL_STRONG
        refused = preflight_tool.node_closure(
            relabelled, calibration_evidence=PASSING_CALIBRATION
        )
        self.assertFalse(refused['closes_the_node'])
        self.assertEqual(refused['admissibility_class'], 'EXACT_UNRESOLVED')
        self.assertFalse(refused['counts_as_exact_support'])
        self.assertFalse(refused['admissible_as_exact_context_estimate'])
        self.assertFalse(
            preflight_tool.is_admissible(relabelled, calibration_evidence=PASSING_CALIBRATION)
        )
        # And an exact-support claim may never be closed while pooling at a parent
        # level, even with every layer-B gate satisfied.
        relabelled_level = copy.deepcopy(estimator)
        relabelled_level['status'] = H.STATUS_EXACT_EMPIRICAL_STRONG
        relabelled_level['support']['observations'] = preflight_tool.MIN_MARGINAL_OBSERVATIONS
        relabelled_level['support']['distinct_hands'] = preflight_tool.MIN_DISTINCT_HANDS
        refused_level = preflight_tool.node_closure(
            relabelled_level, calibration_evidence=PASSING_CALIBRATION
        )
        self.assertFalse(refused_level['closes_the_node'])
        self.assertFalse(refused_level['counts_as_exact_support'])
        self.assertEqual(refused_level['admissibility_class'], 'EXACT_UNRESOLVED')

    def test_empirical_support_is_exact_key_only_and_the_20_20_rule_is_not_widened(self):
        thresholds = {
            'minimum_marginal_observations': preflight_tool.MIN_MARGINAL_OBSERVATIONS,
            'minimum_distinct_hands': preflight_tool.MIN_DISTINCT_HANDS,
        }
        self.assertEqual(
            thresholds,
            {'minimum_marginal_observations': 20, 'minimum_distinct_hands': 20},
        )
        # Every consumed node keeps its own key's support and the unchanged rule.
        for record in self.preflight['nodes']:
            with self.subTest(node=record['node_identity']['node_id'][:12]):
                support = record['empirical_support']
                self.assertEqual(support['thresholds'], thresholds)
                self.assertEqual(support['source_key'], record['exact_key'])
                self.assertFalse(support['borrowed_from_other_keys'])
                self.assertEqual(
                    support['support_isolation_rule'], H.SUPPORT_ISOLATION_RULE
                )
                if record['counts_as_exact_support']:
                    self.assertEqual(record['admissibility_class'], 'EXACT_EMPIRICAL_STRONG')
                    self.assertGreaterEqual(
                        support['observations'], thresholds['minimum_marginal_observations']
                    )
                    self.assertGreaterEqual(
                        support['distinct_hands'], thresholds['minimum_distinct_hands']
                    )
        provider = self.preflight['provider']['thresholds']
        self.assertEqual(provider['minimum_marginal_observations'], 20)
        self.assertEqual(provider['minimum_distinct_hands'], 20)
        self.assertTrue(self.preflight['admissibility_protocol']['no_threshold_moved'])
        self.assertFalse(
            self.preflight['admissibility_protocol']['layer_b_gates_more_permissive_than_v1']
        )

        # v2 inherits the v1 thresholds verbatim: the estimate layer adds no slack.
        v1 = json.loads(preflight_tool.PROTOCOL_PATH.read_text())
        v2 = json.loads(preflight_tool.PROTOCOL_V2_PATH.read_text())
        self.assertTrue(v2['thresholds']['inherited_verbatim_from_v1'])
        self.assertFalse(v2['thresholds']['modified_by_this_revision'])
        self.assertFalse(v2['thresholds']['re_selected_after_reading_validation'])
        for key in (
            'minimum_marginal_observations',
            'minimum_distinct_hands',
            'maximum_absolute_ece',
            'maximum_ece_delta_vs_active',
            'minimum_identifiable_validation_decisions',
            'minimum_identifiable_validation_hands',
            'non_inferiority_ci_upper_bound',
        ):
            with self.subTest(threshold=key):
                self.assertEqual(v2['thresholds'][key], v1['thresholds'][key])
        self.assertEqual(v2['thresholds']['minimum_marginal_observations'], 20)
        self.assertEqual(v2['thresholds']['minimum_distinct_hands'], 20)
        self.assertEqual(
            v2['thresholds']['exact_claim_requires'],
            v1['thresholds']['exact_claim_requires'],
        )

        # The 20/20 boundary is hard: one observation (or one distinct hand) below
        # the frozen threshold stays EXACT_UNRESOLVED and never closes the node.
        strong = _empirical_response()
        self.assertEqual(strong['status'], H.STATUS_EXACT_EMPIRICAL_STRONG)
        self.assertTrue(preflight_tool.is_admissible(strong))
        self.assertEqual(strong['support']['observations'], 24)
        for field, below_value in (('observations', 19), ('distinct_hands', 19)):
            with self.subTest(below=field):
                below = copy.deepcopy(strong)
                below['support'][field] = below_value
                closure = preflight_tool.node_closure(below)
                self.assertFalse(closure['closes_the_node'])
                self.assertEqual(closure['admissibility_class'], 'EXACT_UNRESOLVED')
                self.assertFalse(closure['counts_as_exact_support'])
                self.assertFalse(preflight_tool.is_admissible(below))

    def test_admissibility_rule_matches_frozen_thresholds(self):
        """The preflight rule is the frozen two-class v2 rule, not a widened v1 rule.

        Layer A is the *unchanged* ``EXACT_EMPIRICAL_STRONG`` definition (20
        observations and 20 distinct hands at ``L0_EXACT_KEY``, exact-key-only
        support).  Layer B adds the ``EXACT_HIERARCHICAL_ESTIMATE`` class, which
        closes a node only when every frozen gate passes -- and even then it never
        becomes or counts as empirical support.
        """
        protocol_v2 = preflight_tool.load_frozen_v2_protocol()
        thresholds = protocol_v2['calibration_thresholds']
        self.assertEqual(
            preflight_tool.MIN_MARGINAL_OBSERVATIONS,
            int(protocol_v2['protocol']['thresholds']['minimum_marginal_observations']),
        )
        self.assertEqual(
            preflight_tool.MIN_DISTINCT_HANDS,
            int(protocol_v2['protocol']['thresholds']['minimum_distinct_hands']),
        )
        self.assertEqual(protocol_v2['protocol']['thresholds']['minimum_marginal_observations'], 20)
        self.assertEqual(protocol_v2['protocol']['thresholds']['minimum_distinct_hands'], 20)

        # (A) layer A closes on the frozen 20/20 L0 rule with no calibration claim.
        empirical = _empirical_response()
        self.assertEqual(empirical['status'], H.STATUS_EXACT_EMPIRICAL_STRONG)
        self.assertEqual(empirical['pooling']['level'], 'L0_EXACT_KEY')
        self.assertTrue(preflight_tool.is_admissible(empirical))
        layer_a = preflight_tool.admissibility(empirical)
        self.assertEqual(layer_a['admissibility_class'], 'EXACT_EMPIRICAL_STRONG')
        self.assertTrue(layer_a['counts_as_exact_support'])
        self.assertFalse(layer_a['admissible_as_exact_context_estimate'])

        # The 20/20 boundary is hard in both directions and is never widened.
        exactly_twenty = _response_with(_rows(_whitelist(), 20, 'boundary'))
        self.assertEqual(exactly_twenty['status'], H.STATUS_EXACT_EMPIRICAL_STRONG)
        self.assertEqual(exactly_twenty['support']['observations'], 20)
        self.assertEqual(exactly_twenty['support']['distinct_hands'], 20)
        self.assertTrue(preflight_tool.is_admissible(exactly_twenty))
        for field in ('observations', 'distinct_hands'):
            with self.subTest(threshold=field):
                below = copy.deepcopy(exactly_twenty)
                below['support'][field] = 19
                closure = preflight_tool.node_closure(below)
                self.assertFalse(closure['closes_the_node'])
                self.assertEqual(closure['admissibility_class'], 'EXACT_UNRESOLVED')
                self.assertFalse(closure['counts_as_exact_support'])

        # (B) layer B closes the thin exact key only with every frozen gate passing.
        estimator = _estimate_response()
        self.assertEqual(estimator['status'], H.STATUS_EXACT_HIERARCHICAL_ESTIMATE)
        self.assertLess(estimator['support']['observations'], preflight_tool.MIN_MARGINAL_OBSERVATIONS)
        self.assertLess(estimator['support']['distinct_hands'], preflight_tool.MIN_DISTINCT_HANDS)
        closed = preflight_tool.admissibility(
            estimator, calibration_evidence=PASSING_CALIBRATION
        )
        self.assertTrue(closed['closes_the_node'])
        self.assertEqual(closed['admissibility_class'], 'EXACT_HIERARCHICAL_ESTIMATE')
        self.assertFalse(closed['counts_as_exact_support'])
        self.assertTrue(closed['admissible_as_exact_context_estimate'])
        self.assertEqual(closed['reason_codes'], [])
        self.assertEqual(
            set(closed['layer_b_gates']), set(preflight_tool.LAYER_B_GATE_IDS)
        )

        # Every refusal the frozen rule demands stays a refusal.
        refusals = {
            'price_or_context_substitution': (
                lambda response: response['support'].__setitem__(
                    'source_key', 'MAPSUP_other|public=deadbeef'
                )
            ),
            'non_exact_support': (
                lambda response: response['support'].__setitem__('borrowed_from_other_keys', True)
            ),
            'missing_uncertainty': (
                lambda response: (
                    response.__setitem__('uncertainty', None),
                    response.__setitem__('posterior', None),
                )
            ),
        }
        for label, mutator in refusals.items():
            with self.subTest(refusal=label):
                broken = copy.deepcopy(estimator)
                mutator(broken)
                closure = preflight_tool.admissibility(
                    broken, calibration_evidence=PASSING_CALIBRATION
                )
                self.assertFalse(closure['closes_the_node'])
                self.assertEqual(closure['admissibility_class'], 'EXACT_UNRESOLVED')
                self.assertFalse(closure['counts_as_exact_support'])
                self.assertTrue(closure['reason_codes'])
                self.assertFalse(
                    preflight_tool.is_admissible(
                        broken, calibration_evidence=PASSING_CALIBRATION
                    )
                )
        failing_calibration = preflight_tool.admissibility(
            estimator, calibration_evidence=FAILING_CALIBRATION
        )
        self.assertFalse(failing_calibration['closes_the_node'])
        self.assertEqual(failing_calibration['reason_codes'], ['REFUSED_CALIBRATION'])
        self.assertEqual(thresholds['maximum_absolute_ece'], 0.05)
        self.assertEqual(thresholds['maximum_ece_delta_vs_active'], 0.02)
        self.assertEqual(
            thresholds['minimum_bin_support_for_a_calibration_claim'],
            preflight_tool.MIN_DISTINCT_HANDS,
        )

    def test_absent_support_or_pooling_is_fail_closed_as_exact_unresolved(self):
        cases = (
            ('no_support_no_context', _unresolved_response(observations=[])),
            (
                'thin_support_no_admissible_pooling',
                _unresolved_response(observations=_rows(_whitelist(), 4, 'only')),
            ),
        )
        for label, response in cases:
            with self.subTest(case=label):
                self.assertEqual(response['status'], H.STATUS_EXACT_UNRESOLVED)
                self.assertIsNone(response['pooling'])
                self.assertIsNone(response['posterior'])
                self.assertIsNone(response['uncertainty'])
                self.assertTrue(response['unresolved_reason'])
                # Passing layer-B calibration evidence repairs nothing: an
                # EXACT_UNRESOLVED answer has no estimate closure path at all.
                closure = preflight_tool.admissibility(
                    response, calibration_evidence=PASSING_CALIBRATION
                )
                self.assertFalse(closure['closes_the_node'])
                self.assertEqual(closure['admissibility_class'], 'EXACT_UNRESOLVED')
                self.assertFalse(closure['counts_as_exact_support'])
                self.assertFalse(closure['admissible_as_exact_context_estimate'])
                self.assertFalse(closure['probability_emitted'])
                self.assertIn(response['unresolved_reason'], closure['reason_codes'])
                self.assertTrue(closure['reason_codes'])
                self.assertFalse(
                    preflight_tool.is_admissible(
                        response, calibration_evidence=PASSING_CALIBRATION
                    )
                )
        self.assertEqual(
            cases[0][1]['unresolved_reason'], H.REASON_NO_EXACT_SUPPORT_NO_CONTEXT
        )
        self.assertEqual(
            cases[1][1]['unresolved_reason'], H.REASON_NO_ADMISSIBLE_POOLING
        )

    def test_v1_surfaces_are_immutable_and_v2_references_them_by_digest(self):
        # v1 evidence is re-derived from the persisted bytes on every run.
        for name, pinned in (
            (preflight_tool.NAME, preflight_tool.V1_PREFLIGHT_SHA256),
            (preflight_tool.SUMMARY_NAME, preflight_tool.V1_SUMMARY_SHA256),
            (preflight_tool.INDEX_NAME, preflight_tool.V1_INDEX_SHA256),
        ):
            with self.subTest(v1_artifact=name):
                self.assertEqual(
                    hashlib.sha256((preflight_tool.OUTPUT / name).read_bytes()).hexdigest(),
                    pinned,
                )
        self.assertEqual(
            hashlib.sha256(preflight_tool.PROTOCOL_PATH.read_bytes()).hexdigest(),
            preflight_tool.PROTOCOL_BYTE_SHA256,
        )
        self.assertEqual(
            hashlib.sha256(preflight_tool.PROTOCOL_COPY_PATH.read_bytes()).hexdigest(),
            preflight_tool.PROTOCOL_BYTE_SHA256,
        )
        v1 = json.loads(preflight_tool.PROTOCOL_PATH.read_text())
        self.assertEqual(v1['schema'], preflight_tool.PROTOCOL_SCHEMA)
        self.assertEqual(stable_hash(v1), preflight_tool.PROTOCOL_CANONICAL_PAYLOAD_SHA256)

        # v2 references v1 by digest and explicitly does not rewrite or supersede it.
        v2_bytes = preflight_tool.PROTOCOL_V2_PATH.read_bytes()
        v2 = json.loads(v2_bytes)
        self.assertEqual(
            hashlib.sha256(v2_bytes).hexdigest(), preflight_tool.PROTOCOL_V2_BYTE_SHA256
        )
        self.assertEqual(stable_hash(v2), preflight_tool.PROTOCOL_V2_CANONICAL_PAYLOAD_SHA256)
        self.assertEqual(v2['revision_of'], preflight_tool.PROTOCOL_SCHEMA)
        self.assertEqual(v2['v1_provenance']['byte_sha256'], preflight_tool.PROTOCOL_BYTE_SHA256)
        self.assertEqual(
            v2['v1_provenance']['canonical_payload_sha256'],
            preflight_tool.PROTOCOL_CANONICAL_PAYLOAD_SHA256,
        )
        self.assertTrue(v2['v1_custody']['v1_bytes_unchanged'])
        self.assertTrue(v2['v1_custody']['v1_immutability_is_re_derived_not_asserted'])
        for role in (
            'FROZEN_V1_PROTOCOL_PAYLOAD',
            'FROZEN_V1_PROTOCOL_CONTENT_ADDRESSED_COPY',
        ):
            with self.subTest(v1_surface=role):
                row = next(
                    entry for entry in v2['v1_custody']['v1_surfaces']
                    if entry['role'] == role
                )
                self.assertEqual(row['sha256'], preflight_tool.PROTOCOL_BYTE_SHA256)
        for flag in ('v1_bytes_rewritten', 'v1_artifacts_superseded'):
            self.assertFalse(v2['relationship_to_v1'][flag], flag)
        self.assertTrue(
            v2['relationship_to_v1']['v1_gates_and_thresholds_remain_the_source_of_record']
        )
        self.assertFalse(v2['relationship_to_v1']['admits_anything'])
        self.assertFalse(v2['relationship_to_v1']['changes_admission_rule'])

        # The v2 preflight records both digest chains: the frozen v1 bytes and its
        # own v2 revision, superseding only its own superseded v2 draft.
        protocol_block = self.preflight['admissibility_protocol']
        self.assertEqual(
            protocol_block['protocol_v2_byte_sha256'], preflight_tool.PROTOCOL_V2_BYTE_SHA256
        )
        self.assertEqual(
            protocol_block['protocol_v2_canonical_payload_sha256'],
            preflight_tool.PROTOCOL_V2_CANONICAL_PAYLOAD_SHA256,
        )
        self.assertEqual(
            protocol_block['superseded_protocol_v2_digest'],
            v2['amendments']['superseded_digest'],
        )
        custody = preflight_tool.verify_frozen_v1_preflight()
        self.assertEqual(custody['result'], 'PASS')
        self.assertTrue(custody['never_rewritten'])
        self.assertEqual(
            custody['superseded_by'],
            preflight_tool._relative(preflight_tool.V2_OUTPUT / preflight_tool.V2_NAME),
        )
        # Drift in either digest chain is refused before any node is consumed.
        with mock.patch.object(preflight_tool, 'PROTOCOL_V2_BYTE_SHA256', '0' * 64):
            with self.assertRaises(preflight_tool.PreflightError):
                preflight_tool.load_frozen_v2_protocol()
        with mock.patch.object(preflight_tool, 'PROTOCOL_V2_CANONICAL_PAYLOAD_SHA256', '0' * 64):
            with self.assertRaises(preflight_tool.PreflightError):
                preflight_tool.load_frozen_v2_protocol()

    def test_every_layer_b_gate_fails_closed_with_its_own_reason_code(self):
        estimator = _estimate_response()
        mutators = {
            'EXACT_KEY_IDENTITY': (
                lambda response: response['support'].__setitem__(
                    'source_key', 'MAPSUP_other|public=deadbeef'
                )
            ),
            'POOLING_PROVENANCE': (
                lambda response: response['pooling'].__setitem__(
                    'source_key', response['requested_key']
                )
            ),
            'POOLING_LEVEL': (
                lambda response: response['pooling'].__setitem__('level', 'L9_UNKNOWN')
            ),
            'EFFECTIVE_SAMPLE_SIZE': (
                lambda response: response['support'].__setitem__(
                    'effective_sample_size',
                    float(response['support']['distinct_hands']) + 500.0,
                )
            ),
            'UNCERTAINTY': (
                lambda response: (
                    response.__setitem__('posterior', None),
                    response.__setitem__('uncertainty', None),
                )
            ),
            'CALIBRATION': None,  # driven by the calibration evidence argument
            'RAISE_SIZING_FRONTIER': (
                lambda response: response['raise_sizing'].update(
                    {'state': 'UNRESOLVED_SIZING_FRONTIER', 'unresolved': True}
                )
            ),
        }
        self.assertEqual(set(mutators), set(preflight_tool.LAYER_B_GATE_IDS))
        for gate_id, mutator in mutators.items():
            with self.subTest(gate=gate_id):
                if gate_id == 'CALIBRATION':
                    broken = estimator
                    closure = preflight_tool.node_closure(
                        broken, calibration_evidence=FAILING_CALIBRATION
                    )
                    evidence = FAILING_CALIBRATION
                else:
                    broken = copy.deepcopy(estimator)
                    mutator(broken)
                    closure = preflight_tool.node_closure(
                        broken, calibration_evidence=PASSING_CALIBRATION
                    )
                    self.assertIn(gate_id, closure['failed_gate_ids'])
                    evidence = PASSING_CALIBRATION
                self.assertFalse(closure['closes_the_node'])
                self.assertIn(
                    preflight_tool.LAYER_B_GATE_REASON_CODE_BY_ID[gate_id], closure['reason_codes']
                )
                self.assertFalse(
                    preflight_tool.is_admissible(broken, calibration_evidence=evidence)
                )
        # A borrowed/laundered support source raises the frozen violation code.
        laundered = copy.deepcopy(estimator)
        laundered['support']['borrowed_from_other_keys'] = True
        identity = preflight_tool.layer_b_gate_report(
            laundered, calibration_evidence=PASSING_CALIBRATION
        )['EXACT_KEY_IDENTITY']
        self.assertFalse(identity['passed'])
        self.assertEqual(identity['violation_reason_code'], H.SUPPORT_LAUNDERING_REASON)

    def test_required_tree_closure_is_true_iff_every_node_closes(self):
        empirical = preflight_tool.node_closure(_empirical_response())
        estimate = preflight_tool.node_closure(
            _estimate_response(), calibration_evidence=PASSING_CALIBRATION
        )
        open_estimate = preflight_tool.node_closure(_estimate_response())
        common = dict(
            frontier_count=0,
            nodes_with_unresolved_raise_sizing=0,
            manifest_unresolved_frontier_count=0,
            tree_enumeration_complete=True,
            manifest_tree_enumeration_complete=True,
            substitutions_applied=0,
            key_separation_probes_passed=True,
            hero_ev_executed=False,
            recommendation_computed=False,
            rollouts_executed=0,
            ev_values_computed=0,
        )
        closed_tree = preflight_tool.required_tree_closure_report(
            closures=[empirical, estimate], **common
        )
        self.assertTrue(closed_tree['required_tree_complete'])
        self.assertEqual(closed_tree['reason_codes'], [])
        self.assertTrue(all(c['satisfied'] for c in closed_tree['conditions'].values()))
        self.assertEqual(
            closed_tree['conditions']['every_required_node_closed_by_an_admissible_answer'][
                'closed_as_exact_hierarchical_estimate'
            ],
            1,
        )

        open_tree = preflight_tool.required_tree_closure_report(
            closures=[empirical, open_estimate], **common
        )
        self.assertFalse(open_tree['required_tree_complete'])
        self.assertEqual(
            open_tree['conditions']['every_required_node_closed_by_an_admissible_answer'][
                'reason_code'
            ],
            preflight_tool.REFUSED_REQUIRED_NODE_OPEN,
        )
        self.assertIn('REFUSED_CALIBRATION', open_tree['reason_codes'])

        for label, overrides, expected in (
            (
                'frontier',
                {'frontier_count': 1},
                preflight_tool.REFUSED_UNRESOLVED_RAISE_SIZING_FRONTIER,
            ),
            (
                'substitution',
                {'substitutions_applied': 1},
                preflight_tool.REFUSED_SUBSTITUTION_APPLIED,
            ),
            (
                'hero_ev',
                {'hero_ev_executed': True},
                preflight_tool.REFUSED_HERO_EV_OR_RECOMMENDATION,
            ),
            (
                'enumeration',
                {'tree_enumeration_complete': False},
                preflight_tool.REFUSED_TREE_ENUMERATION_INCOMPLETE,
            ),
        ):
            with self.subTest(case=label):
                report = preflight_tool.required_tree_closure_report(
                    closures=[empirical, estimate], **{**common, **overrides}
                )
                self.assertFalse(report['required_tree_complete'])
                self.assertIn(expected, report['reason_codes'])

        empty_tree = preflight_tool.required_tree_closure_report(closures=[], **common)
        self.assertFalse(empty_tree['required_tree_complete'])

    def test_unresolved_raise_sizing_frontier_blocks_every_response_model(self):
        empirical = preflight_tool.node_closure(_empirical_response())
        estimate = preflight_tool.node_closure(
            _estimate_response(), calibration_evidence=PASSING_CALIBRATION
        )
        self.assertEqual(empirical['admissibility_class'], 'EXACT_EMPIRICAL_STRONG')
        self.assertEqual(estimate['admissibility_class'], 'EXACT_HIERARCHICAL_ESTIMATE')
        self.assertTrue(empirical['closes_the_node'])
        self.assertTrue(estimate['closes_the_node'])
        # Whichever admissibility class closes the 38 required nodes, the seven
        # unresolved RAISE frontiers keep the tree open with their own reason code.
        frontier_conditions = dict(
            CLOSED_TREE_CONDITIONS,
            frontier_count=7,
            nodes_with_unresolved_raise_sizing=7,
            manifest_unresolved_frontier_count=7,
        )
        for label, closure in (('empirical', empirical), ('estimate', estimate)):
            with self.subTest(response_model=label):
                report = preflight_tool.required_tree_closure_report(
                    closures=[closure] * 38, **frontier_conditions
                )
                self.assertFalse(report['required_tree_complete'])
                self.assertIn(
                    preflight_tool.REFUSED_UNRESOLVED_RAISE_SIZING_FRONTIER,
                    report['reason_codes'],
                )
                self.assertTrue(
                    report['conditions']['every_required_node_closed_by_an_admissible_answer'][
                        'satisfied'
                    ]
                )
                frontier = report['conditions']['no_unresolved_raise_sizing_frontier']
                self.assertFalse(frontier['satisfied'])
                self.assertEqual(frontier['unresolved_frontiers'], 7)
                self.assertEqual(frontier['nodes_with_unresolved_raise_sizing'], 7)
                self.assertEqual(frontier['manifest_unresolved_frontier_count'], 7)
        # The delivered preflight witnesses the same blocking condition: every
        # node is queried per exact key yet the seven frontiers stay unresolved.
        self.assertEqual(self.preflight['sizing_frontiers_queried'], 7)
        self.assertEqual(
            sum(
                1
                for record in self.preflight['nodes']
                if record['raise_sizing']['state'] == 'UNRESOLVED_SIZING_FRONTIER'
            ),
            7,
        )
        for frontier in self.preflight['sizing_frontiers']:
            with self.subTest(frontier=frontier['node_id'][:12]):
                self.assertEqual(frontier['disposition'], 'UNRESOLVED_FRONTIER_NOT_PRUNED')
                self.assertIsNone(frontier['exactly_supported_target_bb'])
                self.assertIsNone(frontier['admitted_target_bb'])

    def test_non_exact_support_or_price_or_context_substitution_is_refused(self):
        estimator = _estimate_response()
        # A borrowed support source can never close the node, whatever the gates say.
        for field, value in (
            ('source_key', 'MAPSUP_neighbour|public=cafebabe'),
            ('borrowed_from_other_keys', True),
            ('support_isolation_rule', 'SUPPORT_LAUNDERING_ALLOWED'),
        ):
            with self.subTest(field=field):
                broken = copy.deepcopy(estimator)
                broken['support'][field] = value
                closure = preflight_tool.node_closure(
                    broken, calibration_evidence=PASSING_CALIBRATION
                )
                self.assertFalse(closure['closes_the_node'])
                self.assertFalse(closure['support_is_exact_key_only'])
                self.assertIn('REFUSED_EXACT_KEY_IDENTITY', closure['reason_codes'])
                self.assertFalse(
                    preflight_tool.is_admissible(broken, calibration_evidence=PASSING_CALIBRATION)
                )
        # An estimate relabelled as its own support source (self-pooling) is refused.
        self_pooled = copy.deepcopy(estimator)
        self_pooled['pooling']['source_key'] = self_pooled['requested_key']
        closure = preflight_tool.node_closure(
            self_pooled, calibration_evidence=PASSING_CALIBRATION
        )
        self.assertFalse(closure['closes_the_node'])
        self.assertIn('REFUSED_POOLING_PROVENANCE', closure['reason_codes'])
        # A dropped never-mutualizable axis is coarse-key support laundering.
        dropped = copy.deepcopy(estimator)
        dropped['pooling']['retained_axes'] = [
            axis for axis in dropped['pooling']['retained_axes'] if axis != 'to_call_bb'
        ]
        closure = preflight_tool.node_closure(dropped, calibration_evidence=PASSING_CALIBRATION)
        self.assertFalse(closure['closes_the_node'])
        self.assertIn('REFUSED_EXACT_KEY_IDENTITY', closure['reason_codes'])

        audit = self.preflight['nearest_substitution_audit']
        for counter in (
            'substitutions_applied',
            'nearest_price_substitutions_applied',
            'nearest_context_substitutions_applied',
            'representative_price_substitutions_applied',
            'interpolated_price_substitutions_applied',
            'legal_minimum_substitutions_applied',
            'cross_key_support_borrowings_applied',
        ):
            self.assertEqual(audit[counter], 0, counter)
        self.assertGreater(audit['refusals_recorded'], 0)
        self.assertTrue(audit['key_separation_probes_passed'])
        self.assertTrue(audit['support_source_equals_requested_key_for_every_node'])
        for record in self.preflight['nodes']:
            classes = {row['substitution_class'] for row in record['substitution_refusals']}
            self.assertEqual(classes, set(preflight_tool.SUBSTITUTION_CLASSES))
            for row in record['substitution_refusals']:
                self.assertEqual(row['disposition'], 'REFUSED_NOT_SUBSTITUTED')
                self.assertFalse(row['applied'])
            self.assertEqual(record['empirical_support']['source_key'], record['exact_key'])
            self.assertFalse(record['empirical_support']['borrowed_from_other_keys'])
        for probe in audit['key_separation_probes']:
            self.assertTrue(probe['keys_distinct'])
            self.assertFalse(probe['base_support_reused_for_probe'])
            self.assertEqual(probe['disposition'], 'REFUSED_NOT_SUBSTITUTED')
        price_probes = [
            probe
            for probe in audit['key_separation_probes']
            if probe['substitution_class'] == 'NEAREST_PRICE'
        ]
        self.assertEqual(
            {probe['probe_target_total_bb'] for probe in price_probes},
            set(preflight_tool.ADJACENT_ISO_TARGETS_BB),
        )
        for frontier in self.preflight['sizing_frontiers']:
            classes = {row['substitution_class'] for row in frontier['substitution_refusals']}
            self.assertTrue(
                {'NEAREST_PRICE', 'REPRESENTATIVE_PRICE', 'LEGAL_MINIMUM_FALLBACK'} <= classes
            )

    def test_no_hero_ev_no_holdout_and_no_pointer_mutation(self):
        boundary = self.preflight['boundary']
        self.assertEqual(boundary['split_consumed'], 'TRAIN')
        for flag in (
            'validation_consumed',
            'test_consumed',
            'test_authorized',
            'dataset_archives_opened',
            'model_b_consumed',
            'hero_ev_executed',
            'recommendation_computed',
            'active_model_pointer_mutated',
            'ui_modified',
        ):
            self.assertFalse(boundary[flag], flag)
        self.assertEqual(boundary['test_decisions_read'], 0)
        self.assertEqual(boundary['hand_histories_parsed'], 0)
        self.assertEqual(boundary['rollouts_executed'], 0)
        self.assertEqual(boundary['ev_values_computed'], 0)
        self.assertEqual(boundary['holdout_access_scan']['result'], 'PASS')
        self.assertEqual(boundary['hero_ev_scan']['result'], 'PASS')
        self.assertEqual(boundary['hero_ev_scan']['ev_values_computed'], 0)
        self.assertEqual(boundary['hero_ev_scan']['forbidden_modules_imported_during_build'], [])
        self.assertFalse(boundary['hero_ev_scan']['runner_module_imported_by_preflight'])
        self.assertEqual(boundary['dataset_access_tripwire']['result'], 'PASS')
        self.assertEqual(boundary['dataset_access_tripwire']['hand_history_or_dataset_opens'], [])
        self.assertFalse(boundary['issue367_authorization']['authorized'])
        self.assertFalse(boundary['issue367_authorization']['authorized_at_freeze'])
        protected = self.preflight['protected_files_before_after_sha256']
        self.assertTrue(protected['unchanged'])
        self.assertEqual(protected['before'], protected['after'])
        self.assertFalse(self.preflight['reproduction']['hero_ev_runner_invoked'])
        self.assertFalse(self.preflight['reproduction']['frozen_v1_bundle_rewritten'])
        self.assertFalse(self.preflight['provider']['authorized_for_367'])
        text = self.raw_bytes.decode()
        for forbidden in ('"ev_bb"', 'recommendation":', 'selected_alternative', 'indifference'):
            self.assertNotIn(forbidden, text)

    def test_v1_preflight_byte_pin_supersession_and_identity_pins(self):
        """Replaces the old byte-identical regeneration and v1 identity pin tests.

        The superseded v1 bundle records ``code.provider.sha256`` and
        ``code.preflight_tool.sha256`` of sources that changed after the v1 freeze,
        so rebuilding v1 byte-identically is impossible by construction.  v1 is
        therefore byte-pinned against the recorded digests and explicitly declared
        superseded by the content-addressed v2 bundle, which is the only revision
        that is re-derived (and is still verified to reproduce byte-identically).
        """
        custody = preflight_tool.verify_frozen_v1_preflight()
        self.assertEqual(custody['result'], 'PASS')
        self.assertTrue(custody['never_rewritten'])
        self.assertEqual(custody['revision'], 'v1')
        recorded = {
            preflight_tool.NAME: preflight_tool.V1_PREFLIGHT_SHA256,
            preflight_tool.SUMMARY_NAME: preflight_tool.V1_SUMMARY_SHA256,
            preflight_tool.INDEX_NAME: preflight_tool.V1_INDEX_SHA256,
        }
        # The byte pin is re-derived from the persisted bytes, never merely asserted.
        for name, pinned in recorded.items():
            with self.subTest(v1_artifact=name):
                self.assertEqual(len(pinned), 64)
                self.assertEqual(
                    hashlib.sha256((preflight_tool.OUTPUT / name).read_bytes()).hexdigest(),
                    pinned,
                )
                self.assertEqual(custody['artifacts'][name], pinned)
        self.assertEqual(
            custody['bundle'], preflight_tool._relative(preflight_tool.OUTPUT)
        )
        self.assertEqual(
            custody['superseded_by'],
            preflight_tool._relative(preflight_tool.V2_OUTPUT / preflight_tool.V2_NAME),
        )
        self.assertNotEqual(
            preflight_tool.V2_OUTPUT.resolve(), preflight_tool.OUTPUT.resolve()
        )

        # The frozen v2 protocol custody table pins the very same v1 bytes.
        protocol_v2 = json.loads(preflight_tool.PROTOCOL_V2_PATH.read_text())
        custody_row = next(
            row
            for row in protocol_v2['v1_custody']['v1_surfaces']
            if row['role'] == preflight_tool.V1_CUSTODY_ROLE
        )
        self.assertEqual(custody_row['sha256'], preflight_tool.V1_PREFLIGHT_SHA256)
        self.assertEqual(
            preflight_tool.load_frozen_v2_protocol()['v1_preflight_custody_pin'],
            preflight_tool.V1_PREFLIGHT_SHA256,
        )

        # The recorded supersession is explicit, and it explains *why* v1 cannot be
        # regenerated: the v1 payload names sources that no longer have those bytes.
        declared = self.preflight['frozen_v1_preflight']['supersession']
        self.assertEqual(declared, preflight_tool.V1_SUPERSESSION)
        self.assertFalse(declared['regeneration_possible'])
        self.assertEqual(declared['superseded_revision'], 'v1')
        self.assertEqual(declared['superseding_revision'], 'v2')
        # The declaration is factual: v1 is the restored custody revision, so the
        # pin kept here *is* the pre-mutant revision the evidence-integrity
        # correction put back on disk -- it is not a "history only" digest that a
        # different byte was silently re-pinned against.
        self.assertEqual(
            declared['custody_revision'], 'RESTORED_PRE_MUTANT_CUSTODY_REVISION'
        )
        restoration = declared['custody_restoration']
        self.assertEqual(
            restoration['restored_preflight_sha256'], preflight_tool.V1_PREFLIGHT_SHA256
        )
        self.assertEqual(
            restoration['restored_index_sha256'], preflight_tool.V1_INDEX_SHA256
        )
        self.assertEqual(
            restoration['restored_protocol_v2_byte_sha256'],
            preflight_tool.PROTOCOL_V2_BYTE_SHA256,
        )
        self.assertEqual(
            restoration['mutant_commit'], '871e0bd9e66c978932face1accf1aaf22ac9fa1a'
        )
        self.assertEqual(
            restoration['correction_record'],
            'analysis/issue419_hierarchical_tree/evidence_integrity_correction',
        )
        self.assertEqual(
            hashlib.sha256((preflight_tool.OUTPUT / preflight_tool.NAME).read_bytes()).hexdigest(),
            preflight_tool.V1_PREFLIGHT_SHA256,
        )
        self.assertEqual(
            declared['superseding_bundle'],
            preflight_tool._relative(preflight_tool.V2_OUTPUT),
        )
        self.assertEqual(
            self.preflight['frozen_v1_preflight']['protocol_v2_custody_pin'],
            preflight_tool.V1_PREFLIGHT_SHA256,
        )
        v1 = json.loads((preflight_tool.OUTPUT / preflight_tool.NAME).read_text())
        self.assertEqual(
            v1['code']['provider']['sha256'], declared['v1_records_provider_sha256']
        )
        self.assertEqual(
            v1['code']['preflight_tool']['sha256'],
            declared['v1_records_preflight_tool_sha256'],
        )
        # The v1 tool digest is the reason v1 can never be regenerated: it is not
        # the live tool any more (the provider digest happens to be unchanged).
        v1_bindings = custody['v1_code_bindings']
        self.assertTrue(v1_bindings['provider_unchanged_since_v1'])
        self.assertFalse(v1_bindings['preflight_tool_unchanged_since_v1'])
        self.assertEqual(
            v1_bindings['live_preflight_tool_sha256'], hashlib.sha256(
                preflight_tool.SOURCE_PATH.read_bytes()
            ).hexdigest()
        )
        self.assertEqual(
            v1_bindings['live_provider_sha256'], self.preflight['code']['provider']['sha256']
        )
        self.assertEqual(
            declared['regeneration_possible'],
            v1_bindings['provider_unchanged_since_v1']
            and v1_bindings['preflight_tool_unchanged_since_v1'],
        )
        self.assertNotEqual(
            v1['code']['preflight_tool']['sha256'],
            self.preflight['code']['preflight_tool']['sha256'],
        )
        # v1 is never written: the tool refuses the v1 revision outright.
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(preflight_tool.main(['--revision', 'v1']), 2)
        self.assertIn('REFUSED_REVISION_V1', stderr.getvalue())
        # The v2 bundle this test pins still reproduces byte-identically.
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(preflight_tool.check(), 0)

        # ------------------------------------------------- identity pins (v2)
        bindings = self.preflight['evidence_bindings']
        self.assertEqual(bindings['protocol_byte_sha256'], preflight_tool.PROTOCOL_BYTE_SHA256)
        self.assertEqual(
            bindings['protocol_canonical_payload_sha256'],
            preflight_tool.PROTOCOL_CANONICAL_PAYLOAD_SHA256,
        )
        self.assertEqual(
            bindings['protocol_v2_byte_sha256'], preflight_tool.PROTOCOL_V2_BYTE_SHA256
        )
        self.assertEqual(
            bindings['protocol_v2_byte_sha256'],
            hashlib.sha256(preflight_tool.PROTOCOL_V2_PATH.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            bindings['protocol_v2_canonical_payload_sha256'],
            preflight_tool.PROTOCOL_V2_CANONICAL_PAYLOAD_SHA256,
        )
        self.assertEqual(
            bindings['protocol_v2_amendment_id'], preflight_tool.PROTOCOL_V2_AMENDMENT_ID
        )
        self.assertEqual(
            bindings['protocol_digest_sidecar_sha256'], preflight_tool.PROTOCOL_BYTE_SHA256
        )
        self.assertEqual(bindings['protocol_status'], preflight_tool.PROTOCOL_STATUS)
        self.assertEqual(
            bindings['candidate_canonical_payload_sha256'],
            preflight_tool.CANDIDATE_CANONICAL_SHA256,
        )
        self.assertEqual(bindings['candidate_byte_sha256'], preflight_tool.CANDIDATE_BYTE_SHA256)
        self.assertEqual(
            bindings['required_tree_sha256'],
            '0ab232ae44e4157e2a47d4d3d611ac8ca9c2cdb54caf2568f256f6df35643a25',
        )
        self.assertEqual(bindings['feasibility_decision'], 'UNRESOLVED_EXACT_TREE_GAP')
        self.assertEqual(bindings['feasibility_status'], 'BLOCKED_SCIENTIFIC')
        self.assertEqual(bindings['canonical_fixture_sha256'], self.tree['fixture_sha256'])
        self.assertEqual(
            self.preflight['provider']['candidate_id'],
            'model-a-preflop-sizing-hierarchical-candidate-v1',
        )
        self.assertEqual(
            self.preflight['provider']['candidate_instance_id'],
            preflight_tool.CANDIDATE_INSTANCE_ID,
        )
        self.assertEqual(self.preflight['provider']['support_level'], 'L0_EXACT_KEY')
        self.assertEqual(
            self.preflight['provider']['support_isolation_rule'],
            'SUPPORT_ISOLATION_NO_KEY_BORROWS_SUPPORT',
        )
        self.assertEqual(
            self.preflight['provider']['admissibility_rule'], preflight_tool.NODE_CLOSURE_RULE_ID
        )
        self.assertEqual(
            self.preflight['provider']['layer_b_gates_consulted_for_estimate_closure'],
            list(preflight_tool.LAYER_B_GATE_IDS),
        )
        self.assertEqual(
            self.preflight['provider']['layer_b_gates_consulted_for_empirical_closure'], []
        )
        for flag in (
            'nearest_price_fallback',
            'nearest_context_fallback',
            'representative_price_fallback',
        ):
            self.assertFalse(self.preflight['provider'][flag], flag)
        self.assertTrue(self.preflight['required_tree']['manifest_matches_required_tree'])
        self.assertEqual(self.preflight['scenario']['root_path'], ['SB:ISO@5'])
        self.assertEqual(self.preflight['scenario']['root_actor_position'], 'BB')
        self.assertEqual(self.preflight['scenario']['hero_position'], 'SB')

    def test_custody_pins_are_single_sourced_against_disk_and_frozen_protocol(self):
        """One assertion chain: tool pin == frozen bytes == frozen v2 custody row.

        The tool constant, the SHA256 of the persisted frozen bytes and the frozen
        v2 protocol ``v1_custody`` row are cross-checked together, so a future edit
        that moves only one of the three fails here instead of silently re-pinning
        a byte to a digest that no longer describes it.
        """
        agreement = preflight_tool.verify_custody_pin_agreement()
        self.assertEqual(agreement['result'], 'PASS')
        self.assertEqual(
            agreement, self.preflight['frozen_v1_preflight']['pin_single_source']
        )
        protocol_v2 = json.loads(preflight_tool.PROTOCOL_V2_PATH.read_bytes())
        custody_rows = {
            row['role']: row['sha256'] for row in protocol_v2['v1_custody']['v1_surfaces']
        }
        expected = {
            'V1_PREFLIGHT_SHA256': (
                preflight_tool.OUTPUT / preflight_tool.NAME,
                preflight_tool.V1_PREFLIGHT_SHA256,
                preflight_tool.V1_CUSTODY_ROLE,
            ),
            'V1_INDEX_SHA256': (
                preflight_tool.OUTPUT / preflight_tool.INDEX_NAME,
                preflight_tool.V1_INDEX_SHA256,
                None,
            ),
            'V1_SUMMARY_SHA256': (
                preflight_tool.OUTPUT / preflight_tool.SUMMARY_NAME,
                preflight_tool.V1_SUMMARY_SHA256,
                None,
            ),
            'PROTOCOL_V2_BYTE_SHA256': (
                preflight_tool.PROTOCOL_V2_PATH,
                preflight_tool.PROTOCOL_V2_BYTE_SHA256,
                None,
            ),
        }
        self.assertEqual(set(agreement['sources']), set(expected))
        for pin_name, (path, pinned, role) in expected.items():
            with self.subTest(pin=pin_name):
                on_disk = hashlib.sha256(path.read_bytes()).hexdigest()
                self.assertEqual(len(pinned), 64)
                self.assertEqual(pinned, on_disk)
                self.assertEqual(agreement['sources'][pin_name]['pin'], pinned)
                self.assertEqual(
                    agreement['sources'][pin_name]['on_disk_sha256'], on_disk
                )
                if role is not None:
                    self.assertEqual(custody_rows[role], pinned)
                    self.assertEqual(
                        agreement['sources'][pin_name]['protocol_v2_custody_role'], role
                    )
                    self.assertEqual(
                        agreement['sources'][pin_name]['protocol_v2_custody_sha256'],
                        custody_rows[role],
                    )
        # The published pins are exactly the restored custody digests, so the
        # mutant pins can never come back unnoticed.
        self.assertEqual(
            preflight_tool.V1_PREFLIGHT_SHA256,
            '456d85be57b910d3a56cb0160ba0ba35c988f7f69da9f965f0a887aaac473ae6',
        )
        self.assertEqual(
            preflight_tool.V1_INDEX_SHA256,
            '97e90eac0a9302f1d0b304fa698f5179c7c0ee98ad52ebe307a911d9ccbfa5be',
        )
        self.assertEqual(
            preflight_tool.PROTOCOL_V2_BYTE_SHA256,
            '74b8a006ae84f8b9b22913ef76977e95f08992feb9765639a46d1ac49eb87350',
        )
        self.assertEqual(
            preflight_tool.PROTOCOL_V2_CANONICAL_PAYLOAD_SHA256,
            'cb598a9fc2353aa78f19a7263a62a8ccbdba60eb400264787e896d0c232f19de',
        )

    def test_custody_pin_agreement_fails_closed_when_a_surface_drifts(self):
        """A drifted pin, byte or custody row is a failure, never a re-pin."""
        for name in (
            'V1_PREFLIGHT_SHA256',
            'V1_INDEX_SHA256',
            'V1_SUMMARY_SHA256',
            'PROTOCOL_V2_BYTE_SHA256',
        ):
            with self.subTest(pin=name):
                with mock.patch.object(preflight_tool, name, '0' * 64):
                    with self.assertRaises(preflight_tool.PreflightError):
                        preflight_tool.verify_custody_pin_agreement()
        # A frozen v2 protocol whose custody row stops describing the pin fails too,
        # even though the tool constant and the bytes on disk still agree.
        drifted = json.loads(preflight_tool.PROTOCOL_V2_PATH.read_text())
        for row in drifted['v1_custody']['v1_surfaces']:
            if row['role'] == preflight_tool.V1_CUSTODY_ROLE:
                row['sha256'] = '0' * 64
        with tempfile.TemporaryDirectory() as tmp:
            drifted_path = Path(tmp) / 'FROZEN_VALIDATION_PROTOCOL_V2.json'
            drifted_path.write_text(json.dumps(drifted))
            with mock.patch.object(preflight_tool, 'PROTOCOL_V2_PATH', drifted_path):
                with self.assertRaises(preflight_tool.PreflightError):
                    preflight_tool.verify_custody_pin_agreement()

    def test_frozen_v2_protocol_contract_is_re_derived(self):
        loaded = preflight_tool.load_frozen_v2_protocol()
        self.assertEqual(loaded['protocol_v2_byte_sha256'], preflight_tool.PROTOCOL_V2_BYTE_SHA256)
        layer_b = loaded['layer_b']
        self.assertEqual(tuple(layer_b['admissibility_gate_ids']), preflight_tool.LAYER_B_GATE_IDS)
        self.assertEqual(
            tuple(layer_b['admissibility_gate_reason_codes']),
            preflight_tool.LAYER_B_GATE_REASON_CODES,
        )
        self.assertEqual(layer_b['node_closure']['rule_id'], preflight_tool.NODE_CLOSURE_RULE_ID)
        self.assertEqual(
            layer_b['counts_as_a_closed_exact_tree_node']['value'],
            preflight_tool.NODE_CLOSURE_VALUE,
        )
        self.assertTrue(
            layer_b['counts_as_a_closed_exact_tree_node']['true_iff_all_layer_b_gates_pass']
        )
        self.assertFalse(
            layer_b['counts_as_a_closed_exact_tree_node']['default_when_a_gate_is_unevaluated']
        )
        self.assertEqual(
            tuple(layer_b['identity_axes_retained_at_every_level']), H.NEVER_MUTUALIZABLE_AXES
        )
        self.assertEqual(loaded['amendment_id'], preflight_tool.PROTOCOL_V2_AMENDMENT_ID)

    def test_revision_v2_is_the_only_write_path_and_reproduces_the_bundle(self):
        """``--revision v2`` rewrites the v2 bundle and only the v2 bundle.

        The superseded v1 revision is byte-pinned evidence, so the CLI refuses to
        write it and the recorded v1 bytes survive a v2 write untouched.
        """
        v1_before = {
            name: hashlib.sha256((preflight_tool.OUTPUT / name).read_bytes()).hexdigest()
            for name in (
                preflight_tool.NAME,
                preflight_tool.SUMMARY_NAME,
                preflight_tool.INDEX_NAME,
            )
        }
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(preflight_tool.main(['--revision', 'v2']), 0)
        reported = json.loads(stdout.getvalue())
        self.assertEqual(reported['bundle'], preflight_tool._relative(preflight_tool.V2_OUTPUT))
        self.assertEqual(reported['schema'], preflight_tool.V2_SCHEMA)
        self.assertEqual(
            reported['frozen_v1_preflight_sha256'], preflight_tool.V1_PREFLIGHT_SHA256
        )
        # The write is idempotent: the bundle still reproduces byte-identically and
        # never leaks into the frozen v1 directory.
        self.assertEqual((self.output / preflight_tool.V2_NAME).read_bytes(), self.raw_bytes)
        self.assertEqual(
            {
                name: hashlib.sha256((preflight_tool.OUTPUT / name).read_bytes()).hexdigest()
                for name in v1_before
            },
            v1_before,
        )
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(preflight_tool.check(), 0)

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(preflight_tool.main(['--revision', 'v1']), 2)
        self.assertIn('REFUSED_REVISION_V1', stderr.getvalue())
        # A refused v1 revision must not have written anything.
        self.assertEqual(
            {
                name: hashlib.sha256((preflight_tool.OUTPUT / name).read_bytes()).hexdigest()
                for name in v1_before
            },
            v1_before,
        )

    def test_scan_helpers_fail_closed_on_forbidden_sources(self):
        with self.assertRaises(preflight_tool.PreflightError):
            preflight_tool.verify_no_holdout_access('import load_test_records\n')
        with self.assertRaises(preflight_tool.PreflightError):
            preflight_tool.verify_no_holdout_access('from tools.x import validation_records\n')
        with self.assertRaises(preflight_tool.PreflightError):
            preflight_tool.verify_no_hero_ev_execution(
                'from tools.simulation.run_issue367_real_iso_ev import main\n'
            )
        with self.assertRaises(preflight_tool.PreflightError):
            preflight_tool.verify_no_hero_ev_execution('import paired_adaptive_preflop_ev\n')
        self.assertEqual(preflight_tool.verify_no_holdout_access()['result'], 'PASS')
        self.assertEqual(preflight_tool.verify_no_hero_ev_execution()['result'], 'PASS')

    def test_calibration_gate_fails_closed_without_measured_evidence(self):
        thresholds = preflight_tool.calibration_gate_thresholds(
            preflight_tool.load_frozen_v2_protocol()['protocol']
        )
        unevaluated = preflight_tool.calibration_gate_decision(None, thresholds)
        self.assertFalse(unevaluated['evaluated'])
        self.assertFalse(unevaluated['passed'])
        self.assertEqual(unevaluated['detail'], 'GATE_UNEVALUATED_PRE_VALIDATION')
        self.assertEqual(unevaluated['evidence']['source'],
                         preflight_tool.CALIBRATION_EVIDENCE_SOURCE)
        passing = preflight_tool.calibration_gate_decision(PASSING_CALIBRATION, thresholds)
        self.assertTrue(passing['evaluated'])
        self.assertTrue(passing['passed'])
        for field, value in (
            ('pooled_ece', thresholds['maximum_absolute_ece'] + 1.0),
            ('ece_delta_vs_active', thresholds['maximum_ece_delta_vs_active'] + 1.0),
            ('bins_meeting_minimum_support', 0),
        ):
            with self.subTest(field=field):
                broken = preflight_tool.calibration_gate_decision(
                    {**PASSING_CALIBRATION, field: value}, thresholds
                )
                self.assertTrue(broken['evaluated'])
                self.assertFalse(broken['passed'])

    def test_repo_guard_accepts_the_preflight_and_its_artifact(self):
        source = preflight_tool.SOURCE_PATH.read_text(encoding='utf-8')
        self.assertEqual(guard.verify_no_holdout_access(source)['result'], 'PASS')
        for artifact in (
            preflight_tool._relative(preflight_tool.OUTPUT / preflight_tool.NAME),
            preflight_tool._relative(preflight_tool.V2_OUTPUT / preflight_tool.V2_NAME),
        ):
            with self.subTest(artifact=artifact):
                self.assertNotIn(artifact, guard.validation_result_artifacts())
        # The order guard must still fire on the delivered VALIDATION result, and
        # the v2 preflight must not add another offender.
        with self.assertRaises(guard.ValidationOrderError):
            guard.assert_validation_not_yet_consumed(ROOT)

    def test_hero_ev_build_scan_is_environment_independent(self):
        """A sibling test that already imported the runner must not flip the verdict."""
        import types

        name = 'tools.simulation.run_issue367_real_iso_ev'
        stub = types.ModuleType(name)
        sys.modules[name] = stub
        try:
            artifacts, _summary = preflight_tool.build()
            scan = artifacts[preflight_tool.V2_NAME]['boundary']['hero_ev_scan']
            self.assertEqual(scan['forbidden_modules_imported_during_build'], [])
            self.assertFalse(scan['runner_module_imported_by_preflight'])
            self.assertFalse(artifacts[preflight_tool.V2_NAME]['boundary']['hero_ev_executed'])
            self.assertIn(name, preflight_tool.hero_ev_modules_present())
            self.assertEqual(
                preflight_tool.serialize(artifacts[preflight_tool.V2_NAME]), self.raw_bytes
            )
        finally:
            sys.modules.pop(name, None)
        self.assertEqual(preflight_tool.verify_no_hero_ev_execution()['result'], 'PASS')


if __name__ == '__main__':
    unittest.main()

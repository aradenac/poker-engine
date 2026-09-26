#!/usr/bin/env python3
"""#419 hierarchical exact-tree contract: the mandatory assertions, offline.

Every test here is deterministic and offline.  It exercises the frozen contract
of ``tools/preflop/model_a_sizing_hierarchical.py`` on synthetic/TRAIN-only
inputs and the already content-addressed #419 artifacts (TRAIN fit, frozen
protocol, delivered VALIDATION result, exact-tree preflight, terminal decision).

It never parses a hand history: no TEST hand, decision, feature or label is read,
and VALIDATION is only read through its single, already-consumed frozen-protocol
result.  The mandatory assertions covered are:

1. the same exact key yields one deterministic node identity;
2. an actor/aggressor/limper/caller/price mismatch yields a distinct key;
3. there is no nearest-price substitution;
4. there is no nearest-context substitution;
5. no admissible support/pooling fails closed;
6. pooling provenance is machine-readable;
7. uncertainty is mandatory for a hierarchical estimate;
8. the VALIDATION calibration is measured;
9. a candidate/hash mismatch fails closed;
10. the posterior identity is valid;
11. no future/private information flows anywhere;
12. TRAIN and VALIDATION stay strictly separated;
13. TEST stays inaccessible;
14. an incomplete required tree is not admitted for #367.
15. the consolidated v2 evidence bundle is complete and content-addressed, and the
    integration report claims no CI status without a real run ID, documents both
    required supersessions and keeps every boundary the decisions declare.
"""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.preflop.context_contract import build_context  # noqa: E402
from tools.preflop import model_a_sizing_hierarchical as H  # noqa: E402
from tools.training import audit_model_a_exact_tree as audit_tool  # noqa: E402
from tools.training import fit_model_a_preflop_sizing_hierarchical as fit_tool  # noqa: E402
from tools.training import validate_hierarchical_validation as validation_tool  # noqa: E402
from tools.training import finalize_hierarchical_exact_tree_decision as decision_tool  # noqa: E402
from tools.training import validation_order_guard as guard  # noqa: E402
from tools.training import build_hierarchical_integration_bundle_v2 as integration_tool  # noqa: E402
from tools.simulation import issue419_exact_tree_preflight as preflight_tool  # noqa: E402

FIXTURE = json.loads(
    (ROOT / "tests/fixtures/model_a_preflop_sizing_cases.json").read_text(encoding="utf-8")
)
BASE_INPUT = FIXTURE["contexts"][0]["input"]
POPULATION = FIXTURE["population_id"]
LEGAL = ["FOLD", "CALL", "RAISE", "JAM"]


def _context(**overrides):
    payload = copy.deepcopy(BASE_INPUT)
    for key, value in overrides.items():
        payload[key] = value
    return build_context(**payload)


def _stack_variant(stack_bb):
    stacks = dict(BASE_INPUT["stack_bb_by_position"])
    stacks["BB"] = stack_bb
    return _context(stack_bb_by_position=stacks)


def _price_variant(price, pot, min_raise):
    contributions = dict(BASE_INPUT["contribution_bb_by_position"])
    contributions["SB"] = price
    return _context(
        contribution_bb_by_position=contributions,
        current_price_bb=price,
        pot_before_bb=pot,
        min_raise_to_bb=min_raise,
    )


def _aggressor_variant(position):
    """BB facing a raise from a different position (same price/pot family)."""
    history = [dict(row) for row in BASE_INPUT["history"]]
    history[-1] = {"position": position, "action": "RAISE"}
    contributions = dict(BASE_INPUT["contribution_bb_by_position"])
    contributions["SB"] = 1.0
    contributions[position] = 4.0
    return _context(
        history=history,
        contribution_bb_by_position=contributions,
        current_price_bb=4.0,
        pot_before_bb=7.0,
        min_raise_to_bb=7.0,
    )


def _limper_variant():
    """The same spot with one limper instead of two."""
    history = [dict(BASE_INPUT["history"][0]), dict(BASE_INPUT["history"][2])]
    contributions = dict(BASE_INPUT["contribution_bb_by_position"])
    contributions["HJ"] = 0.0
    return _context(history=history, contribution_bb_by_position=contributions)


def _caller_variant():
    """The same spot with a caller behind the aggressor."""
    history = [dict(row) for row in BASE_INPUT["history"]]
    history.append({"position": "BTN", "action": "CALL"})
    return _context(history=history)


def _rows(context, hand_prefix, count, target):
    actions = ["FOLD", "CALL", "RAISE", "JAM"]
    rows = []
    for index in range(count):
        action = actions[index % len(actions)]
        rows.append(
            {
                "context": context,
                "hand_id": f"{hand_prefix}-{index}",
                "action": action,
                "target_total_bb": target if action in ("RAISE", "JAM") else None,
            }
        )
    return rows


def _audit_row(context):
    """The #388 audit row shape for the same public state."""
    return {
        "family": context["family"],
        "actor_position": context["actor_position"],
        "history": context["history"],
        "current_price_bb": context["current_price_bb"],
        "to_call_bb": context["to_call_bb"],
        "table_size": context["table_size"],
        "raise_level": context["raise_level"],
        "live_positions": context["live_positions"],
        "all_in_positions": context["all_in_positions"],
        "pot_before_bb": context["pot_before_bb"],
        "effective_stack_bb": context["effective_stack_bb"],
    }


class Issue419HierarchicalExactTreeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fit_index = json.loads((fit_tool.OUTPUT / fit_tool.INDEX_NAME).read_text())
        cls.candidate = json.loads((fit_tool.OUTPUT / fit_tool.CANDIDATE_NAME).read_text())
        cls.manifest = json.loads((fit_tool.OUTPUT / fit_tool.MANIFEST_NAME).read_text())
        cls.report = json.loads((fit_tool.OUTPUT / fit_tool.REPORT_NAME).read_text())
        cls.protocol = json.loads(validation_tool.PROTOCOL_PATH.read_text(encoding="utf-8"))
        cls.validation = json.loads(
            (validation_tool.OUTPUT / validation_tool.RESULT_NAME).read_text(encoding="utf-8")
        )
        cls.preflight = json.loads(
            (preflight_tool.OUTPUT / preflight_tool.NAME).read_text(encoding="utf-8")
        )
        cls.decision = json.loads(
            (decision_tool.BUNDLE / decision_tool.DECISION_NAME).read_text(encoding="utf-8")
        )

    # 1 ------------------------------------------------------------------ identity
    def test_same_exact_key_yields_one_deterministic_node_identity(self):
        context = _context()
        rebuilt = _context()
        key = H.hierarchical_exact_key(context)
        self.assertEqual(key, H.hierarchical_exact_key(rebuilt))
        whitelist = H.hierarchical_public_whitelist(context)
        # byte-identical to the #388/#419 audit identity and node key
        self.assertEqual(key, audit_tool.exact_key(audit_tool.public_context(_audit_row(context))))
        node_key = H.runtime_exact_preflop_node_key(whitelist)
        self.assertEqual(node_key, audit_tool.runtime_exact_preflop_node_key(
            audit_tool.public_context(_audit_row(context))
        ))
        self.assertEqual(node_key, H.runtime_exact_preflop_node_key(
            H.hierarchical_public_whitelist(rebuilt)
        ))
        # the same rows rebuild one candidate hash and one response hash
        first_candidate = H.make_synthetic_hierarchical_candidate(
            population_id=POPULATION,
            observations=_rows(context, "det", H.MIN_MARGINAL_OBSERVATIONS, 7.0),
        )
        second_candidate = H.make_synthetic_hierarchical_candidate(
            population_id=POPULATION,
            observations=_rows(rebuilt, "det", H.MIN_MARGINAL_OBSERVATIONS, 7.0),
        )
        self.assertEqual(
            H.canonical_candidate_sha256(first_candidate),
            H.canonical_candidate_sha256(second_candidate),
        )
        first = H.resolve_exact_context(candidate=first_candidate, context=context)
        second = H.resolve_exact_context(candidate=second_candidate, context=rebuilt)
        self.assertEqual(first, second)
        self.assertEqual(
            H.canonical_response_sha256(first), H.canonical_response_sha256(second)
        )
        self.assertEqual(first["requested_key"], key)
        self.assertEqual(first["raise_sizing"]["structural_node_key"], node_key)
        # the persisted preflight binds each node's identity to its exact key
        for record in self.preflight["nodes"]:
            identity = record["node_identity"]
            self.assertEqual(identity["audit_exact_key"], record["exact_key"])
            self.assertTrue(identity["exact_key_matches_manifest"])
            self.assertTrue(identity["exact_key_matches_required_tree"])
            self.assertEqual(identity["identity_granularity"], H.EXACT_GRANULARITY)

    # 2 ------------------------------------------------------------------ key split
    def test_actor_aggressor_limper_caller_and_price_mismatches_are_distinct_keys(self):
        whitelist = H.hierarchical_public_whitelist(_context())
        variants = {
            "actor_position": "BTN",
            "aggressor_position": "BTN",
            "limper_count": 1,
            "caller_count": 1,
            "target_total_bb": 6.0,
            "to_call_bb": 2.0,
        }
        for axis, value in variants.items():
            with self.subTest(axis=axis):
                probe = dict(whitelist, **{axis: value})
                for level in H.POOLING_LEVELS:
                    if axis not in H.LEVEL_SPEC_BY_NAME[level]["key_axes"]:
                        # the level is allowed to be blind to this axis by spec
                        continue
                    self.assertNotEqual(
                        H.level_key(level, probe),
                        H.level_key(level, whitelist),
                        f"{axis} must split {level}",
                    )
                # the exact key (L0) is never blind to any public axis
                self.assertNotEqual(
                    H.level_key(H.SUPPORT_LEVEL, probe),
                    H.level_key(H.SUPPORT_LEVEL, whitelist),
                    f"{axis} must split the exact key",
                )
        # the same mismatches through live public contexts, not just whitelists
        live = [
            _context(),
            _aggressor_variant("BTN"),
            _limper_variant(),
            _caller_variant(),
            _price_variant(6.0, 9.0, 11.0),
        ]
        keys = [H.hierarchical_exact_key(context) for context in live]
        self.assertEqual(len(set(keys)), len(live))

    # 3 + 4 -------------------------------------------------------- no substitution
    def test_no_nearest_price_and_no_nearest_context_substitution(self):
        four = _context()
        six = _price_variant(6.0, 9.0, 11.0)
        five = _price_variant(5.0, 8.0, 9.0)
        other_aggressor = _aggressor_variant("BTN")
        candidate = H.make_synthetic_hierarchical_candidate(
            population_id=POPULATION,
            observations=_rows(four, "four", H.MIN_MARGINAL_OBSERVATIONS, 7.0)
            + _rows(six, "six", H.MIN_MARGINAL_OBSERVATIONS, 11.0),
        )
        self.assertEqual(
            H.resolve_exact_context(candidate=candidate, context=four)["status"],
            H.STATUS_EXACT_EMPIRICAL_STRONG,
        )
        self.assertEqual(
            H.resolve_exact_context(candidate=candidate, context=six)["status"],
            H.STATUS_EXACT_EMPIRICAL_STRONG,
        )
        # a price between two supported prices is never interpolated
        between = H.resolve_exact_context(candidate=candidate, context=five)
        H.validate_response(between)
        self.assertEqual(between["status"], H.STATUS_EXACT_UNRESOLVED)
        self.assertEqual(between["support"]["observations"], 0)
        self.assertIsNone(between["posterior"])
        self.assertEqual(between["raise_sizing"]["supported_targets"], [])
        self.assertFalse(between["raise_sizing"]["nearest_price_used"])
        self.assertFalse(between["raise_sizing"]["representative_price_used"])
        self.assertFalse(between["raise_sizing"]["interpolation_used"])
        self.assertFalse(between["granularity"]["nearest_price_lookup"])
        # a nearby context (different aggressor) is never answered from the base key
        nearby = H.resolve_exact_context(
            candidate=candidate, context=other_aggressor, legal_actions=LEGAL
        )
        H.validate_response(nearby)
        self.assertEqual(nearby["status"], H.STATUS_EXACT_UNRESOLVED)
        self.assertEqual(nearby["support"]["observations"], 0)
        self.assertIsNone(nearby["pooling"])
        self.assertFalse(nearby["granularity"]["nearest_context_lookup"])
        self.assertNotEqual(
            H.level_keys(four)["L3_RUNTIME_SUPPORT_CONTEXT"],
            H.level_keys(other_aggressor)["L3_RUNTIME_SUPPORT_CONTEXT"],
        )

    # 5 ------------------------------------------------------------- fail closed
    def test_no_admissible_support_or_pooling_fails_closed(self):
        context = _context()
        thin = H.make_synthetic_hierarchical_candidate(
            population_id=POPULATION,
            observations=[
                {"context": context, "hand_id": "only", "action": "RAISE", "target_total_bb": 7.0}
            ],
        )
        response = H.resolve_exact_context(candidate=thin, context=context)
        H.validate_response(response)
        self.assertEqual(response["status"], H.STATUS_EXACT_UNRESOLVED)
        self.assertEqual(response["reason_code"], H.STATUS_EXACT_UNRESOLVED)
        self.assertEqual(response["unresolved_reason"], H.REASON_NO_ADMISSIBLE_POOLING)
        self.assertIsNone(response["posterior"])
        self.assertIsNone(response["uncertainty"])
        self.assertTrue(response["reason_detail"])
        self.assertEqual([row["level"] for row in response["pooling_diagnostics"]], list(H.POOLING_LEVELS))
        self.assertTrue(all(row["qualifies"] is False for row in response["pooling_diagnostics"]))
        # an unknown requested key without a context fails closed instead of guessing one
        keyless = H.resolve_exact_context(
            candidate=thin,
            requested_key=H.hierarchical_exact_key(_price_variant(9.0, 12.0, 15.0)),
            legal_actions=LEGAL,
        )
        self.assertEqual(keyless["status"], H.STATUS_EXACT_UNRESOLVED)
        self.assertEqual(keyless["unresolved_reason"], H.REASON_NO_EXACT_SUPPORT_NO_CONTEXT)
        self.assertIsNone(keyless["pooling"])
        # an unresolved response may never smuggle a probability
        smuggled = copy.deepcopy(response)
        smuggled["posterior"] = {"FOLD": 1.0}
        with self.assertRaises(H.HierarchicalSizingError):
            H.validate_response(smuggled)
        # an unresolved raise-sizing frontier stays unresolved, with no nearest price
        key = H.hierarchical_exact_key(context)
        frontier = H.make_synthetic_hierarchical_candidate(
            population_id=POPULATION,
            observations=_rows(context, "front", H.MIN_MARGINAL_OBSERVATIONS, 7.0),
            unresolved_raise_frontiers=[key],
        )
        frontier_response = H.resolve_exact_context(candidate=frontier, context=context)
        self.assertEqual(frontier_response["unresolved_reason"], H.REASON_RAISE_SIZING_UNRESOLVED)
        self.assertEqual(frontier_response["raise_sizing"]["state"], "UNRESOLVED_SIZING_FRONTIER")
        self.assertFalse(frontier_response["raise_sizing"]["nearest_price_used"])
        self.assertIsNone(frontier_response["posterior"])

    # 6 ------------------------------------------------------- pooling provenance
    def test_pooling_provenance_is_machine_readable_and_enforced(self):
        context = _stack_variant(100.0)
        sibling = _stack_variant(60.0)
        candidate = H.make_synthetic_hierarchical_candidate(
            population_id=POPULATION,
            observations=[
                {"context": context, "hand_id": "exact", "action": "RAISE", "target_total_bb": 7.0}
            ]
            + _rows(sibling, "sib", H.MIN_MARGINAL_OBSERVATIONS, 9.0),
        )
        response = H.resolve_exact_context(candidate=candidate, context=context)
        H.validate_response(response)
        self.assertEqual(response["status"], H.STATUS_EXACT_HIERARCHICAL_ESTIMATE)
        pooling = response["pooling"]
        for field in (
            "level",
            "rank",
            "purpose",
            "source_key",
            "source_observations",
            "source_distinct_hands",
            "source_effective_sample_size",
            "retained_axes",
            "pooled_axes",
            "weight_exact",
            "weight_parent",
            "parent_dominated",
            "kappa0",
            "alpha_per_legal_marginal_action",
            "support_source_key",
            "support_isolation_rule",
        ):
            self.assertIn(field, pooling, field)
        self.assertIn(pooling["level"], H.POOLING_LEVELS)
        self.assertNotEqual(pooling["source_key"], response["requested_key"])
        self.assertEqual(pooling["support_source_key"], response["requested_key"])
        self.assertEqual(pooling["support_isolation_rule"], H.SUPPORT_ISOLATION_RULE)
        self.assertIn("requested_key_identity", pooling["retained_axes"])
        self.assertNotIn("requested_key_identity", pooling["pooled_axes"])
        self.assertEqual(
            set(pooling["pooled_axes"]) | set(pooling["retained_axes"]),
            set(H.ALL_AXES),
        )
        # the preflight renders the same provenance and stays None while unresolved
        self.assertEqual(preflight_tool.pooling_record(response)["level"], pooling["level"])
        for record in self.preflight["nodes"]:
            self.assertIsNone(record["pooling_provenance"])
        # missing or laundered provenance fails closed
        for field in ("pooling", "pooling_diagnostics"):
            broken = copy.deepcopy(response)
            broken[field] = None
            with self.subTest(field=field), self.assertRaises(H.HierarchicalSizingError):
                H.validate_response(broken)
        self_laundered = copy.deepcopy(response)
        self_laundered["pooling"]["source_key"] = response["requested_key"]
        with self.assertRaises(H.HierarchicalSizingError):
            H.validate_response(self_laundered)
        # every delivered VALIDATION decision carries its own key as support source
        for row in self.validation["decisions"]:
            self.assertEqual(row["support"]["source_key"], row["requested_key"])
            self.assertTrue(row["requested_key"].startswith("MAPSUP_"))
            self.assertIn("|public=", row["requested_key"])
            self.assertIn(row["pooling"]["level"], H.POOLING_LEVELS)
            self.assertEqual(
                row["pooling"]["source_key"] == row["requested_key"],
                row["pooling"]["level"] == H.SUPPORT_LEVEL,
            )

    # 7 ------------------------------------------------------------- uncertainty
    def test_uncertainty_is_mandatory_for_a_hierarchical_estimate(self):
        context = _stack_variant(100.0)
        sibling = _stack_variant(60.0)
        candidate = H.make_synthetic_hierarchical_candidate(
            population_id=POPULATION,
            observations=[
                {"context": context, "hand_id": "exact", "action": "RAISE", "target_total_bb": 7.0}
            ]
            + _rows(sibling, "sib", H.MIN_MARGINAL_OBSERVATIONS, 9.0),
        )
        response = H.resolve_exact_context(candidate=candidate, context=context)
        self.assertEqual(response["status"], H.STATUS_EXACT_HIERARCHICAL_ESTIMATE)
        uncertainty = response["uncertainty"]
        self.assertIsNotNone(uncertainty)
        self.assertEqual(uncertainty["level_used"], response["pooling"]["level"])
        self.assertEqual(set(uncertainty["actions"]), set(response["posterior"]))
        for action, band in uncertainty["actions"].items():
            self.assertEqual(band["mean"], response["posterior"][action])
            self.assertLessEqual(band["credible_interval"]["low"], band["mean"])
            self.assertLessEqual(band["mean"], band["credible_interval"]["high"])
            self.assertGreaterEqual(band["std_error"], 0.0)
        for status_context in (context, _context()):
            strong = H.make_synthetic_hierarchical_candidate(
                population_id=POPULATION,
                observations=_rows(status_context, "strong", H.MIN_MARGINAL_OBSERVATIONS, 7.0),
            )
            resolved = H.resolve_exact_context(candidate=strong, context=status_context)
            self.assertEqual(resolved["status"], H.STATUS_EXACT_EMPIRICAL_STRONG)
            stripped = copy.deepcopy(resolved)
            stripped["uncertainty"] = None
            with self.assertRaises(H.HierarchicalSizingError):
                H.validate_response(stripped)
        stripped = copy.deepcopy(response)
        stripped["uncertainty"] = None
        with self.assertRaises(H.HierarchicalSizingError):
            H.validate_response(stripped)

    # 8 ------------------------------------------------------ VALIDATION measured
    def test_validation_calibration_is_measured_not_declared(self):
        metrics = self.validation["metrics"]
        detail = metrics["secondary"]["calibration_detail"]["candidate_hierarchical"]
        ece = metrics["secondary"]["expected_calibration_error"]["candidate_hierarchical"]
        self.assertEqual(detail["bins_per_action_class"], validation_tool.CALIBRATION_BINS)
        self.assertEqual(detail["minimum_bin_support"], validation_tool.MINIMUM_BIN_SUPPORT)
        self.assertEqual(ece, detail["ece"])
        self.assertIsInstance(ece, float)
        self.assertGreaterEqual(ece, 0.0)
        self.assertLessEqual(ece, 1.0)
        # measured, not asserted: the persisted ECE is recomputable from the decisions
        recomputed = validation_tool.expected_calibration_error(
            self.validation["decisions"], "posterior"
        )
        self.assertAlmostEqual(recomputed["ece"], ece, places=12)
        self.assertEqual(set(detail["per_action_class"]), set(H.RESPONSES) - {"CHECK"})
        # the absolute calibration gate scores the measured value against the frozen ceiling
        gate = next(
            row for row in self.validation["gate"]["gates"] if row["gate"] == "calibration_absolute"
        )
        self.assertFalse(gate["pass"])
        self.assertIn("0.05", gate["rule"])
        self.assertEqual(gate["measured"]["ece"], ece)
        self.assertEqual(self.validation["thresholds"]["maximum_absolute_ece"], 0.05)
        self.assertTrue(self.validation["thresholds_unchanged_after_read"])
        self.assertFalse(self.validation["gate"]["all_gates_pass"])

    # 9 ---------------------------------------------------- candidate/hash mismatch
    def test_candidate_or_hash_mismatch_fails_closed(self):
        # a candidate whose bytes moved is refused before any evaluation
        drifted = copy.deepcopy(self.candidate)
        drifted["observations"] = drifted["observations"][:-1]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / fit_tool.CANDIDATE_NAME
            path.write_text(json.dumps(drifted), encoding="utf-8")
            with mock.patch.object(validation_tool, "CANDIDATE_PATH", path):
                with self.assertRaises(validation_tool.ValidationExecutionError):
                    validation_tool.load_candidate()
        # a contract-violating candidate is refused by the contract validator
        for field in (
            "nearest_price_fallback",
            "nearest_context_fallback",
            "representative_price_fallback",
        ):
            broken = copy.deepcopy(self.candidate)
            broken[field] = True
            with self.subTest(field=field), self.assertRaises(H.HierarchicalSizingError):
                H.validate_candidate(broken)
        # the frozen identities agree: the persisted candidate is the pinned one
        self.assertEqual(
            hashlib.sha256((fit_tool.OUTPUT / fit_tool.CANDIDATE_NAME).read_bytes()).hexdigest(),
            guard.CANDIDATE_BYTE_SHA256,
        )
        self.assertEqual(H.canonical_candidate_sha256(self.candidate), guard.CANDIDATE_CANONICAL_SHA256)
        self.assertEqual(self.decision["candidate_sha256"], guard.CANDIDATE_CANONICAL_SHA256)
        self.assertEqual(
            self.preflight["evidence_bindings"]["candidate_canonical_payload_sha256"],
            guard.CANDIDATE_CANONICAL_SHA256,
        )
        self.assertNotEqual(guard.CANDIDATE_CANONICAL_SHA256, decision_tool.ISSUE352_CANDIDATE_SHA256)

    # 10 --------------------------------------------------------- posterior identity
    def test_posterior_identity_is_valid(self):
        context = _context()
        candidate = H.make_synthetic_hierarchical_candidate(
            population_id=POPULATION,
            observations=_rows(context, "post", H.MIN_MARGINAL_OBSERVATIONS, 7.0),
        )
        response = H.resolve_exact_context(candidate=candidate, context=context)
        identity = preflight_tool.posterior_identity(response)
        self.assertEqual(identity["status"], response["status"])
        self.assertEqual(identity["reason_code"], response["reason_code"])
        self.assertTrue(identity["posterior_present"])
        self.assertTrue(identity["probability_emitted"])
        self.assertEqual(identity["posterior"], response["posterior"])
        self.assertEqual(identity["posterior_sha256"], H.canonical_sha256(response["posterior"]))
        self.assertEqual(identity["response_sha256"], H.canonical_response_sha256(response))
        self.assertAlmostEqual(sum(response["posterior"].values()), 1.0, places=9)
        self.assertEqual(set(response["posterior"]), set(LEGAL))
        # identical inputs reproduce the identical posterior identity
        again = H.resolve_exact_context(candidate=candidate, context=_context())
        self.assertEqual(
            preflight_tool.posterior_identity(again)["posterior_sha256"],
            identity["posterior_sha256"],
        )
        # an unresolved decision emits no posterior and therefore no posterior identity
        thin = H.make_synthetic_hierarchical_candidate(
            population_id=POPULATION,
            observations=[{"context": context, "hand_id": "t", "action": "CALL", "target_total_bb": None}],
        )
        unresolved = H.resolve_exact_context(candidate=thin, context=context)
        empty = preflight_tool.posterior_identity(unresolved)
        self.assertFalse(empty["posterior_present"])
        self.assertFalse(empty["probability_emitted"])
        self.assertIsNone(empty["posterior"])
        self.assertIsNone(empty["posterior_sha256"])
        for record in self.preflight["nodes"]:
            identity = record["posterior_identity"]
            self.assertEqual(identity["status"], H.STATUS_EXACT_UNRESOLVED)
            self.assertIsNone(identity["posterior"])
            self.assertIsNone(identity["posterior_sha256"])
            self.assertFalse(identity["probability_emitted"])

    # 11 ----------------------------------------------------- future/private info
    def test_no_future_or_private_information_flows_anywhere(self):
        contaminated = dict(_context())
        contaminated["hole_cards"] = ["Ks", "Ts"]
        with self.assertRaises(H.HierarchicalSizingError):
            H.hierarchical_public_whitelist(contaminated)
        for leak in ("future_cards", "board", "showdown", "opponent_private"):
            with self.subTest(leak=leak), self.assertRaises(H.HierarchicalSizingError):
                H.make_synthetic_hierarchical_candidate(
                    population_id=POPULATION,
                    observations=[
                        {"context": _context(), "hand_id": "leak", "action": "CALL", **{leak: ["As"]}}
                    ],
                )
        response = H.resolve_exact_context(
            candidate=H.make_synthetic_hierarchical_candidate(
                population_id=POPULATION,
                observations=_rows(_context(), "clean", H.MIN_MARGINAL_OBSERVATIONS, 7.0),
            ),
            context=_context(),
        )
        self.assertEqual(
            response["information_boundary"],
            {
                "public_only": True,
                "future_cards_consumed": False,
                "opponent_hole_cards_consumed": False,
                "private_information_consumed": False,
            },
        )
        # no persisted artifact smuggles a card/future field into data-bearing keys
        for name, payload in (
            ("candidate", self.candidate),
            ("report", self.report),
            ("validation", self.validation),
            ("preflight", self.preflight),
            ("decision", self.decision),
        ):
            self.assertFalse(H._contains_sensitive_key(payload), name)
        # the exact key itself never embeds a card, board or future token
        for record in self.preflight["nodes"]:
            key = record["exact_key"]
            self.assertIn("|public=", key)
            for token in H.SENSITIVE_TOKENS:
                self.assertNotIn(token, key)

    # 12 -------------------------------------------------------- TRAIN/VALIDATION
    def test_train_and_validation_stay_strictly_separated(self):
        # the fit is TRAIN-only and declares it
        self.assertEqual(self.candidate["identity"]["data_scope"], fit_tool.DATA_SCOPE)
        self.assertEqual(self.candidate["identity"]["fit_scope"], fit_tool.FIT_SCOPE)
        self.assertEqual(self.report["split_consumed"], "TRAIN")
        self.assertFalse(self.report["validation_consumed"])
        self.assertFalse(self.report["test_consumed"])
        self.assertEqual(self.manifest["fit"]["split_consumed"], "TRAIN")
        self.assertFalse(self.manifest["fit"]["validation_consumed"])
        # the delivered evaluation consumed VALIDATION only, under the frozen protocol
        self.assertEqual(self.validation["split"], "VALIDATION")
        self.assertEqual(self.validation["candidate"]["data_scope"], "TRAIN_ONLY")
        self.assertEqual(
            self.validation["protocol_byte_sha256"], validation_tool.EXPECTED_PROTOCOL_BYTE_SHA256
        )
        self.assertEqual(
            validation_tool.sha256_file(validation_tool.PROTOCOL_PATH),
            validation_tool.EXPECTED_PROTOCOL_BYTE_SHA256,
        )
        self.assertEqual(
            self.validation["node_classification"]["reconciled_with_train_fit_report"], True
        )
        # the VALIDATION node statuses are the frozen TRAIN function, not a re-fit
        expected = {":".join(row["path"]): row["status"] for row in self.report["nodes"]}
        for row in self.validation["node_classification"]["nodes"]:
            self.assertEqual(row["status"], expected[":".join(row["path"])])
        # fit and validation are distinct artifact sets at distinct roots
        self.assertNotEqual(fit_tool.OUTPUT.resolve(), validation_tool.OUTPUT.resolve())
        # the frozen TRAIN fit candidate is the very artifact VALIDATION scored
        self.assertEqual(
            self.fit_index[fit_tool.CANDIDATE_NAME]["sha256"],
            self.validation["candidate"]["byte_sha256"],
        )
        self.assertNotIn(
            fit_tool.CANDIDATE_NAME, [row.name for row in validation_tool.OUTPUT.iterdir()]
        )
        # the protocol cannot be edited after the freeze, and VALIDATION is single-shot
        with self.assertRaises(guard.ValidationOrderError):
            guard.assert_protocol_frozen_before_validation(
                validation_tool.PROTOCOL_PATH, expected_byte_sha256="0" * 64
            )
        with self.assertRaises(guard.ValidationOrderError):
            guard.assert_validation_not_yet_consumed(ROOT)
        with self.assertRaises((guard.ValidationOrderError, validation_tool.ValidationExecutionError)):
            validation_tool.evaluate()
        self.assertEqual(validation_tool.verify_no_test_loader()["result"], "PASS")
        self.assertEqual(fit_tool.verify_no_holdout_access()["result"], "PASS")

    # 13 ---------------------------------------------------------------- TEST
    def test_test_split_is_inaccessible(self):
        for name, payload in (
            ("report", self.report),
            ("validation", self.validation),
            ("decision", self.decision),
        ):
            with self.subTest(payload=name):
                self.assertIs(payload["test_consumed"], False)
        self.assertIs(self.preflight["boundary"]["test_consumed"], False)
        self.assertIs(self.validation["test_authorized"], False)
        self.assertIs(self.decision["test_authorized"], False)
        self.assertEqual(self.report["test_decisions_read"], 0)
        boundary = self.validation["holdout_boundary"]
        self.assertEqual(boundary["test_hands_parsed"], 0)
        self.assertEqual(boundary["test_decisions_read"], 0)
        self.assertEqual(boundary["test_rows_seen_by_the_evaluator"], 0)
        preflight_boundary = self.preflight["boundary"]
        self.assertFalse(preflight_boundary["test_consumed"])
        self.assertFalse(preflight_boundary["test_authorized"])
        self.assertEqual(preflight_boundary["test_decisions_read"], 0)
        self.assertEqual(preflight_boundary["holdout_access_scan"]["result"], "PASS")
        self.assertEqual(guard.verify_guard_is_holdout_free()["result"], "PASS")
        self.assertEqual(preflight_tool.verify_no_holdout_access()["result"], "PASS")
        self.assertTrue(self.validation["protocol_consumption"]["single_shot"])

    # 14 ----------------------------------------------------- #367 non-admission
    def test_incomplete_required_tree_is_not_admitted_for_issue_367(self):
        decision = self.decision
        self.assertFalse(decision["required_tree_complete"])
        self.assertFalse(decision["admitted"])
        self.assertFalse(decision["candidate"]["admitted"])
        self.assertEqual(decision["decision"], decision_tool.DECISION_UNRESOLVED)
        self.assertEqual(decision["status"], decision_tool.STATUS_BLOCKED)
        self.assertEqual(decision["primary_blocker"], decision_tool.BLOCK_REQUIRED_TREE_INCOMPLETE)
        self.assertFalse(decision["issue367_authorized"])
        self.assertFalse(decision["issue367_run"])
        self.assertFalse(decision["hero_ev_executed"])
        self.assertFalse(decision["active_pointer_mutated"])
        self.assertEqual(decision["next_issue"], decision_tool.NEXT_ISSUE)
        self.assertEqual(decision["admissible_exact_node_count"], 0)
        self.assertEqual(decision["exact_unresolved_node_count"], 38)
        blocker = next(
            row
            for row in decision["blockers"]
            if row["code"] == decision_tool.BLOCK_REQUIRED_TREE_INCOMPLETE
        )
        self.assertEqual(blocker["admissible_exact_nodes"], 0)
        self.assertEqual(blocker["required_nodes"], 38)
        self.assertEqual(blocker["status_counts"], {"EXACT_UNRESOLVED": 38})
        self.assertIn("required_tree_fully_enumerated", blocker["failed_admissibility_conditions"])
        # the preflight agrees: no node is admissible and no substitution was applied
        self.assertFalse(self.preflight["required_tree_complete"])
        self.assertEqual(self.preflight["admissibility"]["admissible_exact_nodes"], 0)
        self.assertEqual(self.preflight["admissibility"]["blocked_nodes"], 38)
        self.assertFalse(self.preflight["required_tree"]["tree_enumeration_complete"])
        audit = self.preflight["nearest_substitution_audit"]
        for counter in (
            "substitutions_applied",
            "nearest_price_substitutions_applied",
            "nearest_context_substitutions_applied",
            "representative_price_substitutions_applied",
            "interpolated_price_substitutions_applied",
            "legal_minimum_substitutions_applied",
            "cross_key_support_borrowings_applied",
        ):
            self.assertEqual(audit[counter], 0, counter)
        self.assertGreater(audit["refusals_recorded"], 0)
        self.assertTrue(audit["support_source_equals_requested_key_for_every_node"])
        self.assertFalse(self.preflight["boundary"]["issue367_authorization"]["authorized"])
        # the gate that failed is reported, not relaxed
        self.assertEqual(self.validation["outcome"], "RETAIN_ACTIVE_REFERENCE")
        self.assertFalse(self.validation["gate"]["all_gates_pass"])
        self.assertIn("calibration_absolute", self.validation["gate"]["failing_gates"])
        declared_gates = {
            row["gate"] for row in self.protocol["calibration_and_admission"]["admission_gates"]
        }
        for gate in self.validation["gate"]["gates"]:
            self.assertIn(gate["gate"], declared_gates)


class Issue419IntegrationBundleV2Tests(unittest.TestCase):
    """15 -- the consolidated v2 evidence bundle: complete, coherent, and honest.

    The integration report is the artifact a reviewer reads to decide whether the
    issue may move on, so its two failure modes are asserted directly: a bundle
    that is not content-addressed (a member byte or digest drifting silently) and
    a report that over-claims (a CI status without a real run ID, a hidden
    supersession, or a boundary that is not the one the decisions declare).
    """

    @classmethod
    def setUpClass(cls):
        cls.bundle_dir = integration_tool.HERE
        cls.report = json.loads((cls.bundle_dir / integration_tool.REPORT_JSON_NAME).read_text())
        cls.report_md = (cls.bundle_dir / integration_tool.REPORT_NAME).read_text(encoding="utf-8")
        cls.summary_md = (cls.bundle_dir / integration_tool.SUMMARY_NAME).read_text(encoding="utf-8")
        cls.n8n_text = (cls.bundle_dir / integration_tool.N8N_NAME).read_text(encoding="utf-8")
        cls.index = json.loads((cls.bundle_dir / integration_tool.INDEX_NAME).read_text())

    def test_every_required_member_is_present_and_content_addressed(self):
        for name in integration_tool.MEMBER_NAMES:
            with self.subTest(member=name):
                path = self.bundle_dir / name
                self.assertTrue(path.is_file(), name)
                entry = self.index[name]
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                self.assertEqual(entry["sha256"], digest)
                self.assertEqual((ROOT / entry["object"]).read_bytes(), path.read_bytes())
                if name.endswith(".json"):
                    self.assertEqual(
                        entry["canonical_payload_sha256"],
                        integration_tool.stable_hash(json.loads(path.read_text())),
                    )
        self.assertEqual(set(self.index), set(integration_tool.MEMBER_NAMES))
        objects = {
            path.name for path in (self.bundle_dir / "sha256").iterdir() if path.is_file()
        }
        self.assertEqual(
            objects,
            {
                self.index[name]["sha256"] + integration_tool.object_extension(name)
                for name in integration_tool.MEMBER_NAMES
            },
        )
        sidecar = (self.bundle_dir / integration_tool.DIGEST_NAME).read_text(encoding="utf-8")
        self.assertTrue(sidecar.startswith(f'{self.index[integration_tool.REPORT_NAME]["sha256"]}'))

    def test_bundle_is_reproducible_and_check_mode_passes(self):
        rebuilt = integration_tool.build_payload()
        files = integration_tool.bundle_files(rebuilt)
        for name, data in files.items():
            with self.subTest(member=name):
                self.assertEqual((self.bundle_dir / name).read_bytes(), data, name)
        self.assertEqual(integration_tool.check(), 0)
        self.assertEqual(
            self.index[integration_tool.REPORT_JSON_NAME]["canonical_payload_sha256"],
            integration_tool.stable_hash(rebuilt),
        )

    def test_copies_are_byte_identical_to_their_authorities(self):
        for name, source, digest in integration_tool.COPIES:
            with self.subTest(member=name):
                member = self.report["bundle_members"][name]
                self.assertEqual(member["mode"], "BYTE_IDENTICAL_COPY")
                self.assertEqual(member["source_path"], integration_tool._relative(source))
                self.assertEqual(member["source_byte_sha256"], digest)
                self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), digest)
                self.assertEqual((self.bundle_dir / name).read_bytes(), source.read_bytes())

    def test_references_are_digest_only_and_never_re_read_the_holdout(self):
        for name, source, digest in integration_tool.REFERENCES:
            with self.subTest(member=name):
                member = self.report["bundle_members"][name]
                self.assertEqual(member["mode"], "DIGEST_REFERENCE_NO_BYTES")
                self.assertEqual(member["bytes_copied"], 0)
                self.assertEqual(member["source_path"], integration_tool._relative(source))
                self.assertEqual(member["source_byte_sha256"], digest)
                reference = json.loads((self.bundle_dir / name).read_text())
                self.assertEqual(reference["kind"].split("_")[0], "DIGEST")
                self.assertEqual(reference["source"]["byte_sha256"], digest)
                self.assertFalse(reference["bytes_copied_into_this_bundle"])
                self.assertNotEqual((self.bundle_dir / name).read_bytes(), source.read_bytes())
        validation = json.loads(
            (self.bundle_dir / "VALIDATION_RESULT.json").read_text(encoding="utf-8")
        )
        self.assertEqual(validation["source"]["path"], integration_tool._relative(
            integration_tool.VALIDATION_V1
        ))
        self.assertEqual(validation["published_verdict"], "RETAIN_ACTIVE_REFERENCE")
        self.assertFalse(validation["holdout_reopened_by_this_bundle"])
        self.assertEqual(validation["decision_rows_read_by_this_bundle"], 0)
        self.assertEqual(validation["metrics_recomputed_by_this_bundle"], 0)
        self.assertFalse(validation["thresholds_re_selected_by_this_bundle"])
        protocol = json.loads(
            (self.bundle_dir / "FROZEN_VALIDATION_PROTOCOL_V2.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            protocol["source"]["byte_sha256"], integration_tool.PROTOCOL_V2_BYTE_SHA256
        )
        self.assertEqual(
            protocol["amendment"]["superseded_byte_sha256"],
            integration_tool.PROTOCOL_V2_SUPERSEDED_BYTE_SHA256,
        )
        self.assertFalse(protocol["thresholds_moved"])
        self.assertFalse(protocol["gates_weaker_than_v1"])

    def test_n8n_output_is_conformant(self):
        expected = {
            "status": "BLOCKED_SCIENTIFIC",
            "decision": "UNRESOLVED_HIERARCHICAL_TREE_GAP",
            "candidate_id": integration_tool.CANDIDATE_ID,
            "candidate_sha256": integration_tool.CANDIDATE_SHA256,
            "required_tree_complete": False,
            "validation_consumed": True,
            "test_consumed": False,
            "active_pointer_mutated": False,
            "next_issue": 367,
        }
        block = self.report["n8n_task_result"]
        self.assertEqual(block["status"], expected["status"])
        self.assertIn(block["status"], {"READY_FOR_INTEGRATION", "BLOCKED_SCIENTIFIC"})
        self.assertIn(
            block["decision"],
            {"ADMIT_HIERARCHICAL_EXACT_TREE_CANDIDATE", "UNRESOLVED_HIERARCHICAL_TREE_GAP"},
        )
        for key, value in expected.items():
            with self.subTest(field=key):
                self.assertEqual(block[key], value)
        rendered = integration_tool.render_n8n_block(block)
        self.assertEqual(rendered, self.n8n_text)
        self.assertEqual(rendered.splitlines()[0], "N8N_TASK_RESULT")
        for line in (
            "status: BLOCKED_SCIENTIFIC",
            "decision: UNRESOLVED_HIERARCHICAL_TREE_GAP",
            f"candidate_id: {integration_tool.CANDIDATE_ID}",
            f"candidate_sha256: {integration_tool.CANDIDATE_SHA256}",
            "required_tree_complete: false",
            "validation_consumed: true",
            "test_consumed: false",
            "active_pointer_mutated: false",
            "next_issue: 367",
        ):
            self.assertIn(line, self.n8n_text, line)
        for surface in (self.report_md, self.summary_md):
            self.assertIn("N8N_TASK_RESULT", surface)
            self.assertIn("next_issue: 367", surface)

    def test_no_ci_status_is_claimed_without_a_real_run_id(self):
        ci = self.report["ci_evidence"]
        self.assertEqual(self.report["ci_proven_claims"], [])
        self.assertEqual(ci["status"], "NOT_OBSERVED")
        self.assertIsNone(ci["run_url_recorded"])
        self.assertTrue(ci["no_run_exists"])
        self.assertGreater(ci["observed_run_count"], 0)
        for run in ci["recorded_runs"]:
            with self.subTest(run=run["run_number"]):
                self.assertTrue(run["url"].startswith("https://github.com/"))
                self.assertFalse(run["executes_the_issue419_suites"])
                self.assertIn(str(run["run_number"]), self.report_md)
                self.assertIn(run["url"], self.report_md)
        for run_id in ci["recorded_run_ids"]:
            self.assertIn(str(run_id), self.report_md)
        self.assertIn("**None.**", self.report_md)
        self.assertIn("NON-AUTHORITATIVE", self.report_md)
        self.assertNotIn("ci_observation.status = PASS", self.report_md)

    def test_report_documents_the_two_required_supersessions(self):
        for token in (
            integration_tool.PROTOCOL_V2_SUPERSEDED_BYTE_SHA256,
            integration_tool.PROTOCOL_V2_SUPERSEDED_CANONICAL_SHA256,
            integration_tool.PROTOCOL_V2_BYTE_SHA256,
            integration_tool.PROTOCOL_V2_CANONICAL_SHA256,
            integration_tool.PROTOCOL_V2_AMENDMENT_ID,
            integration_tool.PREFLIGHT_V1_PRECORRECTION_BYTE_SHA256,
            integration_tool.PREFLIGHT_V1_BYTE_SHA256,
            integration_tool.PREFLIGHT_V1_CANONICAL_SHA256,
            integration_tool.PREFLIGHT_V1_INDEX_SHA256,
            integration_tool.CORRECTION_BYTE_SHA256,
            "V1_EXACT_TREE_PREFLIGHT_REGENERATION",
            "SUPERSEDED_V2_PROTOCOL_PAYLOAD_508A31EC",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.report_md)
        for token in (
            integration_tool.PROTOCOL_V2_SUPERSEDED_BYTE_SHA256,
            integration_tool.PREFLIGHT_V1_PRECORRECTION_BYTE_SHA256,
            integration_tool.PREFLIGHT_V1_BYTE_SHA256,
        ):
            self.assertIn(token, self.summary_md)
        ids = {item["supersession_id"] for item in self.report["required_supersessions"]}
        self.assertEqual(
            ids,
            {
                "SUPERSEDED_V2_PROTOCOL_PAYLOAD_508A31EC",
                "V1_EXACT_TREE_PREFLIGHT_REGENERATION",
            },
        )
        self.assertIn("MUTANT", self.report_md.upper())
        self.assertIn("c904524", self.report_md)

    def test_report_separates_ci_proof_from_local_verification(self):
        self.assertIn("## 3. What is proven by a real CI run ID, and what is only local", self.report_md)
        self.assertIn("### 3.1 Proven by a real CI run ID", self.report_md)
        self.assertIn("### 3.3 Recorded local observations", self.report_md)
        for row in self.report["recorded_local_observations"]:
            with self.subTest(command=row["command"]):
                self.assertIn(row["command"], self.report_md)
        red = [
            row for row in self.report["recorded_local_observations"]
            if row["observed_exit_code"] != 0
        ]
        self.assertTrue(red, "the two red local checks must stay visible")
        explained = {
            code
            for row in red
            for code in str(row.get("explained_by", "")).split(",")
            if code
        }
        finding_ids = {row["finding_id"] for row in self.report["residual_findings"]}
        self.assertEqual(explained - finding_ids, {"EXPECTED_AFTER_THE_SINGLE_FROZEN_READ"})
        self.assertIn("V1_PREFLIGHT_PIN_STALE", explained)
        self.assertIn("PROTOCOL_V2_PREFLIGHT_PIN_STALE", explained)
        finding = next(
            row for row in self.report["residual_findings"]
            if row["finding_id"] == "V1_PREFLIGHT_PIN_STALE"
        )
        self.assertFalse(finding["pin_matches_on_disk_bytes"])
        self.assertFalse(finding["repaired_by_this_bundle"])
        self.assertIn("V1_PREFLIGHT_PIN_STALE", self.report_md)
        v2_finding = next(
            row for row in self.report["residual_findings"]
            if row["finding_id"] == "PROTOCOL_V2_PREFLIGHT_PIN_STALE"
        )
        self.assertFalse(v2_finding["pin_matches_on_disk_bytes"])
        self.assertFalse(v2_finding["repaired_by_this_bundle"])
        self.assertIn("PROTOCOL_V2_PREFLIGHT_PIN_STALE", self.report_md)

    def test_boundaries_are_the_ones_the_decisions_declare(self):
        boundaries = self.report["boundaries"]
        self.assertTrue(boundaries["validation_consumed"])
        self.assertEqual(boundaries["validation_read_count"], 1)
        self.assertFalse(boundaries["holdout_reopened_by_this_bundle"])
        self.assertEqual(boundaries["decision_rows_read_by_this_bundle"], 0)
        self.assertEqual(boundaries["metrics_recomputed_by_this_bundle"], 0)
        self.assertFalse(boundaries["thresholds_re_selected_by_this_bundle"])
        self.assertFalse(boundaries["test_consumed"])
        self.assertFalse(boundaries["test_authorized"])
        self.assertEqual(boundaries["test_decisions_read"], 0)
        self.assertFalse(boundaries["active_pointer_mutated"])
        self.assertFalse(boundaries["hero_ev_executed"])
        self.assertFalse(boundaries["recommendation_computed"])
        self.assertEqual(boundaries["rollouts_executed"], 0)
        self.assertFalse(boundaries["issue367_run"])
        self.assertFalse(boundaries["issue367_authorized"])
        self.assertEqual(boundaries["dataset_or_hand_history_opens"], [])
        self.assertEqual(boundaries["holdout_access_scan"]["result"], "PASS")
        self.assertEqual(boundaries["issue367_boundary_scan"]["result"], "PASS")
        self.assertTrue(boundaries["protected_files_unchanged"])
        self.assertEqual(
            boundaries["active_model_reference_sha256"],
            integration_tool.ACTIVE_MODEL_BYTE_SHA256,
        )
        self.assertEqual(
            hashlib.sha256(integration_tool.ACTIVE_MODEL.read_bytes()).hexdigest(),
            integration_tool.ACTIVE_MODEL_BYTE_SHA256,
        )
        # the terminal decision v2, the T4 manifest and this bundle agree
        self.assertEqual(self.report["candidate"]["candidate_id"], H.CANDIDATE_ID)
        self.assertEqual(
            self.report["candidate"]["candidate_sha256"],
            integration_tool.CANDIDATE_SHA256,
        )
        decision = json.loads(
            (decision_tool.V2_BUNDLE / decision_tool.V2_NAME).read_text(encoding="utf-8")
        )
        self.assertEqual(decision["candidate_sha256"], self.report["candidate"]["candidate_sha256"])
        self.assertEqual(decision["required_tree_complete"], self.report["verdict"]["required_tree_complete"])
        self.assertTrue(self.report["boundaries"]["protected_files_before"])

    def test_bundle_stays_out_of_every_upstream_index(self):
        token = integration_tool._relative(self.bundle_dir)
        for index in sorted(
            (ROOT / "analysis/issue419_hierarchical_tree").rglob("ARTIFACTS.json")
        ):
            with self.subTest(index=index.name):
                self.assertNotIn(token, index.read_text(encoding="utf-8"))
        self.assertEqual(
            integration_tool._relative(self.bundle_dir),
            "analysis/issue419_hierarchical_tree_v2",
        )

    def test_check_mode_fails_closed_on_a_doctored_member(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy_dir = Path(tmp) / "bundle"
            shutil.copytree(self.bundle_dir, copy_dir)
            integration_tool.verify_content_address(copy_dir)
            doctored = copy_dir / integration_tool.SUMMARY_NAME
            doctored.write_bytes(doctored.read_bytes() + b"\n<!-- drift -->\n")
            with self.assertRaises(integration_tool.IntegrationBundleError):
                integration_tool.verify_content_address(copy_dir)


if __name__ == "__main__":
    unittest.main()

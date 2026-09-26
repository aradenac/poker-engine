#!/usr/bin/env python3
"""#423 guard: hybrid response router (pre-action signals, simple rules, no lookup).

Covers every acceptance criterion of the task:

* the ten pre-action signals are computable before the action, deterministic
  and independent of the hidden hand and of the observed result;
* the three declared rules produce the three route sources of the frozen
  preregistration, and the OOD abstention is triggered by the extrapolation and
  never-seen-category probes;
* a context absent from the calibrated support index but in domain is *not* OOD
  by definition and is routed to the sparse channel;
* the module carries no ad-hoc table of contexts; the support index it reads is
  the frozen, TRAIN-calibrated one, and it never substitutes a neighbouring
  context, price or sizing target for the queried one (the explicit negative
  guards below prove the refusal);
* the simplicity policy keeps the simplest rule within the preregistered
  agreement margin of the best.

The synthetic fold is built around the *actual* resolution of the frozen gate:
the exact context signature is the tuple of single-feature node labels, so the
probes are chosen at that resolution (the base cell repeated 30 times, a rare
cell repeated 3 times, and a never-queried combination of observed labels).

``pytest`` is not a declared dependency of this repository; the suite is a
plain ``unittest`` module, run with ``python3 -m unittest`` like its siblings.
"""
from __future__ import annotations

import ast
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.preflop import generalized_response_model as model  # noqa: E402
from tools.preflop import hybrid_response_router as router  # noqa: E402

MODULE_PATH = ROOT / "tools/preflop/hybrid_response_router.py"
SPEC_PATH = ROOT / "analysis/issue423_hybrid_router/HYBRID_ROUTER_SPEC.json"

MODEL_HASH = "b" * 64
FREQUENT_REPEATS = 2 * router.FREQUENT_EXACT_MIN_SUPPORT  # 40 >= 20
RARE_REPEATS = 3


def _row(**overrides: object) -> dict:
    base = {
        "split": "TRAIN",
        "family": "VS_ISO",
        "actor_position": "HJ",
        "aggressor_position": None,
        "caller_count": 0,
        "limper_count": 0,
        "raise_level": 0,
        "live_positions": ["LJ", "HJ", "CO", "BTN", "SB", "BB"],
        "to_call_bb": 1.0,
        "pot_before_bb": 1.5,
        "effective_stack_bb": 30.0,
        "target_total_bb": None,
        "observed_sizing_bb": None,
        "action": "FOLD",
    }
    base.update(overrides)
    return base


def frequent_row() -> dict:
    """The cell repeated ``FREQUENT_REPEATS`` times (frequent exact support)."""
    return _row()


def rare_row() -> dict:
    """The same labels as the base cell, but a different to-call bucket."""
    return _row(to_call_bb=8.0)


def novel_in_domain_row() -> dict:
    """Observed labels only, but a combination never queried in the fold."""
    return _row(actor_position="CO", to_call_bb=7.0)


def extra_label_row() -> dict:
    """Introduce the CO actor and the second pot bucket as observed labels."""
    return _row(actor_position="CO", pot_before_bb=6.5)


def deep_stack_row() -> dict:
    """Introduce the deepest observed stack bucket as an observed label."""
    return _row(
        family="VS_RFI",
        aggressor_position="CO",
        to_call_bb=1.0,
        pot_before_bb=2.0,
        effective_stack_bb=100.0,
    )


def sizing_row(index: int) -> dict:
    """A raise row, so the sizing axis carries a calibrated TRAIN domain."""
    return _row(
        family="VS_RFI",
        aggressor_position="CO",
        to_call_bb=1.0,
        pot_before_bb=2.0,
        effective_stack_bb=60.0,
        target_total_bb=3.6 + index * 0.2,
    )


def dataset() -> list[dict]:
    """A deterministic synthetic TRAIN fold with a designed support profile."""
    rows: list[dict] = []
    rows.extend(dict(frequent_row()) for _ in range(FREQUENT_REPEATS))
    rows.extend(dict(rare_row()) for _ in range(RARE_REPEATS))
    rows.extend(dict(extra_label_row()) for _ in range(2))
    rows.append(deep_stack_row())
    rows.extend(sizing_row(index) for index in range(10))
    return rows


class HybridRouterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = dataset()
        # The robust tail is a calibration knob: a wide tail keeps R1/R2/R3 in
        # agreement on this fold (the sensitive-tail behaviour is exercised by
        # a dedicated test with a zero tail).
        cls.calibration = router.build_calibration(cls.rows, thresholds={"domain_distance": 4.0})
        cls.frequent = frequent_row()
        cls.rare = rare_row()
        cls.novel_in_domain = novel_in_domain_row()
        cls.novel_category = _row(family="NEVER_OBSERVED_FAMILY")
        cls.extrapolation_stack = _row(
            family="VS_RFI",
            aggressor_position="CO",
            to_call_bb=1.5,
            pot_before_bb=2.0,
            effective_stack_bb=130.0,  # beyond the trained 100, same bucket
        )
        cls.extrapolation_price = _row(
            family="VS_RFI",
            aggressor_position="CO",
            to_call_bb=9.0,  # beyond the trained 8.0, same bucket
            pot_before_bb=2.0,
            effective_stack_bb=60.0,
        )
        cls.extrapolation_sizing = _row(
            family="VS_RFI",
            aggressor_position="CO",
            to_call_bb=1.0,
            pot_before_bb=2.0,
            effective_stack_bb=60.0,
            target_total_bb=1000.0,  # sizing ratio far beyond the trained 1.8
        )
        cls.probe_names = (
            "frequent",
            "rare",
            "novel_in_domain",
            "novel_category",
            "extrapolation_stack",
            "extrapolation_price",
            "extrapolation_sizing",
        )

    # -- helpers ----------------------------------------------------------

    def _signals(self, context: dict, **kwargs: object) -> dict:
        return router.compute_signals(context, calibration=self.calibration, **kwargs)

    def _probes(self) -> list[dict]:
        return [self._signals(getattr(self, name)) for name in self.probe_names]

    def _channel(self, *, probabilities: dict, sizing_provenance: dict | None = None) -> dict:
        return {
            "model_id": "generalized_adverse_response_candidate_v1",
            "model_hash": MODEL_HASH,
            "probabilities": probabilities,
            "sizing_provenance": sizing_provenance,
        }

    def test_synthetic_fold_has_the_designed_support_profile(self) -> None:
        self.assertEqual(
            router.exact_context_support(self.frequent, self.calibration), FREQUENT_REPEATS
        )
        self.assertEqual(
            router.exact_context_support(self.rare, self.calibration), RARE_REPEATS
        )
        self.assertEqual(
            router.exact_context_support(self.novel_in_domain, self.calibration), 0
        )

    # -- signals ----------------------------------------------------------

    def test_signal_bundle_contract(self) -> None:
        signals = self._signals(self.frequent)
        for signal_id in router.SIGNAL_IDS:
            self.assertIn(signal_id, signals, signal_id)
        self.assertEqual(len(router.SIGNAL_IDS), 10)
        self.assertEqual(signals["timing"], router.TIMING_BEFORE_ACTION)
        self.assertTrue(signals["computed_before_action"])
        self.assertTrue(signals["deterministic"])
        self.assertFalse(signals["uses_hidden_hand"])
        self.assertFalse(signals["uses_observed_result"])
        self.assertTrue(signals["no_nearest_price_substitution"])
        self.assertTrue(signals["no_nearest_context_substitution"])
        self.assertEqual(set(signals["detail"]["axes"]), set(model.OOD_NUMERIC_AXES))
        self.assertEqual(signals["canonical_sha256"], router.signal_digest(signals))

    def test_strata_assignment(self) -> None:
        frequent = self._signals(self.frequent)
        self.assertGreaterEqual(frequent["support_exact"], router.FREQUENT_EXACT_MIN_SUPPORT)
        self.assertEqual(frequent["stratum"], router.STRATUM_FREQUENT_EXACT)
        rare = self._signals(self.rare)
        self.assertEqual(rare["support_exact"], RARE_REPEATS)
        self.assertEqual(rare["stratum"], router.STRATUM_RARE_EXACT)
        novel = self._signals(self.novel_in_domain)
        self.assertEqual(novel["support_exact"], 0)
        self.assertTrue(novel["feature_in_domain"])
        self.assertEqual(novel["stratum"], router.STRATUM_EXACT_ABSENT_IN_DOMAIN)
        unseen = self._signals(self.novel_category)
        self.assertEqual(unseen["stratum"], router.STRATUM_EXACT_ABSENT_OUT_OF_DOMAIN)
        self.assertFalse(unseen["feature_in_domain"])

    def test_signals_are_deterministic(self) -> None:
        first = self._signals(self.rare)
        second = self._signals(dict(self.rare))
        self.assertEqual(first, second)
        self.assertEqual(router.signal_digest(first), router.signal_digest(second))

    def test_signals_ignore_the_observed_result(self) -> None:
        """No hidden hand, no observed result: only the public request is read."""
        baseline = self._signals(self.rare)
        perturbed = dict(self.rare)
        perturbed.update(
            {
                "action": "RAISE",
                "observed_sizing_bb": 12.5,
                "outcome_bb": -40.0,
                "realized_bb": 99.0,
                "hero_hand": "AA",
                "won": True,
            }
        )
        after = self._signals(perturbed)
        self.assertEqual(baseline, after)
        self.assertEqual(router.signal_digest(baseline), router.signal_digest(after))
        self.assertEqual(
            router.canonical_json(router.route(self.rare, calibration=self.calibration)),
            router.canonical_json(router.route(perturbed, calibration=self.calibration)),
        )

    def test_module_never_reads_a_hidden_hand_or_an_outcome_field(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        for forbidden in (
            '"observed_sizing_bb"',
            '"outcome_bb"',
            '"realized_bb"',
            '"hero_hand"',
            '"won"',
            "import random",
            "from random",
        ):
            self.assertNotIn(forbidden, source, forbidden)
        # The routing document's request view is the public pre-action surface.
        fields = set(router.route(self.frequent, calibration=self.calibration)["request"])
        for forbidden in ("action", "observed_sizing_bb", "hero_hand"):
            self.assertNotIn(forbidden, fields)

    # -- OOD -----------------------------------------------------------------

    def test_ood_abstention_triggered_by_extrapolation_and_novel_category(self) -> None:
        expected = {
            "novel_category": "UNSEEN_CATEGORY",
            "extrapolation_stack": "EXTRAPOLATION_STACK",
            "extrapolation_price": "EXTRAPOLATION_PRICE",
            "extrapolation_sizing": "EXTRAPOLATION_SIZING",
        }
        for name, reason in expected.items():
            signals = self._signals(getattr(self, name))
            self.assertIn(reason, signals["hard_reasons"], f"{name}: {signals['hard_reasons']}")
            self.assertEqual(signals["ood_status"], model.STATUS_MODEL_OOD_ABSTAIN)
            self.assertEqual(router.route_source(signals), router.ROUTE_SOURCE_ABSTAIN)
            document = router.route(getattr(self, name), calibration=self.calibration)
            self.assertEqual(document["route_source"], router.ROUTE_SOURCE_ABSTAIN)
            self.assertTrue(document["abstain"])
            self.assertFalse(document["analysis_admissible"])
            self.assertIsNone(document["probabilities"])
            self.assertIsNone(document["selected_action"])
            self.assertIsNone(document["sizing_provenance"])
            self.assertEqual(document["support_state"], router.SUPPORT_STATE_ABSTAIN)
            self.assertIn(reason, document["reasons"]["hard"])
            self.assertEqual(document["reasons"]["catalog"][reason], "hard")

    def test_extrapolation_flags_are_pre_action_booleans(self) -> None:
        self.assertTrue(self._signals(self.extrapolation_sizing)["extrapolation_sizing"])
        self.assertTrue(self._signals(self.extrapolation_stack)["extrapolation_stack"])
        self.assertTrue(self._signals(self.extrapolation_price)["extrapolation_price"])
        in_domain = self._signals(self.frequent)
        self.assertFalse(in_domain["extrapolation_sizing"])
        self.assertFalse(in_domain["extrapolation_stack"])
        self.assertFalse(in_domain["extrapolation_price"])

    def test_extrapolation_probes_are_not_a_missing_axis(self) -> None:
        for name in ("extrapolation_stack", "extrapolation_price", "extrapolation_sizing"):
            self.assertNotIn(
                "MISSING_DOMAIN_AXIS", self._signals(getattr(self, name))["hard_reasons"]
            )

    def test_novel_in_domain_is_not_ood(self) -> None:
        signals = self._signals(self.novel_in_domain)
        self.assertEqual(signals["hard_reasons"], [])
        self.assertNotEqual(signals["ood_status"], model.STATUS_MODEL_OOD_ABSTAIN)
        self.assertEqual(router.route_source(signals), router.ROUTE_SOURCE_SPARSE)

    def test_missing_domain_axis_is_a_hard_reason(self) -> None:
        context = dict(self.frequent)
        context.pop("pot_before_bb")
        signals = self._signals(context)
        self.assertIn("MISSING_DOMAIN_AXIS", signals["hard_reasons"])
        self.assertEqual(router.route_source(signals), router.ROUTE_SOURCE_ABSTAIN)

    # -- rules and policy ----------------------------------------------------

    def test_every_rule_produces_the_three_route_sources(self) -> None:
        probes = self._probes()
        for rule in router.ROUTE_RULES:
            produced = {rule(signals) for signals in probes}
            self.assertEqual(
                produced, set(router.ROUTE_SOURCES), f"{rule.id} produced {sorted(produced)}"
            )

    def test_reference_rule_follows_the_frozen_decision_table(self) -> None:
        reference = router.route_rule(router.REFERENCE_RULE_ID)
        self.assertEqual(reference(self._signals(self.frequent)), router.ROUTE_SOURCE_ACTIVE)
        self.assertEqual(reference(self._signals(self.rare)), router.ROUTE_SOURCE_SPARSE)
        self.assertEqual(
            reference(self._signals(self.novel_in_domain)), router.ROUTE_SOURCE_SPARSE
        )
        self.assertEqual(
            reference(self._signals(self.novel_category)), router.ROUTE_SOURCE_ABSTAIN
        )

    def test_support_state_and_routed_strata_match_the_source(self) -> None:
        expected_states = {
            router.ROUTE_SOURCE_ACTIVE: router.SUPPORT_STATE_STRONG,
            router.ROUTE_SOURCE_SPARSE: router.SUPPORT_STATE_SPARSE,
            router.ROUTE_SOURCE_ABSTAIN: router.SUPPORT_STATE_ABSTAIN,
        }
        for context, source in (
            (self.frequent, router.ROUTE_SOURCE_ACTIVE),
            (self.rare, router.ROUTE_SOURCE_SPARSE),
            (self.novel_in_domain, router.ROUTE_SOURCE_SPARSE),
            (self.novel_category, router.ROUTE_SOURCE_ABSTAIN),
        ):
            signals = self._signals(context)
            self.assertEqual(router.route_source(signals), source)
            document = router.route(context, calibration=self.calibration)
            self.assertEqual(document["support_state"], expected_states[source])
            self.assertIn(signals["stratum"], router.ROUTED_STRATA_OF_SOURCE[source])
            self.assertEqual(
                document["routed_strata"], list(router.ROUTED_STRATA_OF_SOURCE[source])
            )

    def test_uncertainty_rule_refuses_a_sparse_tail(self) -> None:
        """R3 is the risk-averse alternative: a sparse numeric tail abstains."""
        sensitive = router.build_calibration(self.rows, thresholds={"domain_distance": 0.0})
        signals = router.compute_signals(self.novel_in_domain, calibration=sensitive)
        self.assertGreater(signals["distance_to_domain"], 0.0)
        self.assertEqual(signals["hard_reasons"], [])
        self.assertEqual(signals["stratum"], router.STRATUM_EXACT_ABSENT_IN_DOMAIN)
        self.assertEqual(
            router.route_source(signals, rule="R1_HARD_GATE"), router.ROUTE_SOURCE_SPARSE
        )
        self.assertEqual(
            router.route_source(signals, rule="R2_SUPPORT_GATE"), router.ROUTE_SOURCE_SPARSE
        )
        self.assertEqual(
            router.route_source(signals, rule="R3_UNCERTAINTY_GATE"),
            router.ROUTE_SOURCE_ABSTAIN,
        )

    def test_simplicity_policy_keeps_the_simplest_rule_within_margin(self) -> None:
        probes = self._probes()
        selection = router.select_rule(probes)
        self.assertEqual(selection["reference_rule_id"], router.REFERENCE_RULE_ID)
        self.assertEqual(
            [item["rule_id"] for item in selection["evaluations"]],
            [rule.id for rule in router.ROUTE_RULES],
        )
        best = selection["best_agreement"]
        chosen = next(
            item for item in selection["evaluations"] if item["rule_id"] == selection["rule_id"]
        )
        self.assertGreaterEqual(chosen["agreement"], best - selection["margin"])
        eligible = [
            item
            for item in selection["evaluations"]
            if item["agreement"] >= best - selection["margin"]
        ]
        self.assertEqual(
            chosen["complexity"], min(item["complexity"] for item in eligible)
        )
        self.assertEqual(chosen["rule_id"], "R1_HARD_GATE")
        self.assertIn("simplicity margin", selection["rationale"])

    def test_policy_prefers_the_simplest_rule_on_a_tie(self) -> None:
        probes = self._probes()
        self.assertEqual(router.select_rule(probes, margin=0.0)["rule_id"], "R1_HARD_GATE")
        self.assertEqual(router.select_rule(probes, margin=0.5)["rule_id"], "R1_HARD_GATE")

    def test_policy_is_sensitive_to_a_real_disagreement(self) -> None:
        """A rule that risks a different route is only kept within the margin."""
        sensitive = router.build_calibration(self.rows, thresholds={"domain_distance": 0.0})
        probes = [
            router.compute_signals(getattr(self, name), calibration=sensitive)
            for name in self.probe_names
        ]
        selection = router.select_rule(probes, margin=0.0)
        r3 = next(
            item
            for item in selection["evaluations"]
            if item["rule_id"] == "R3_UNCERTAINTY_GATE"
        )
        self.assertLess(r3["agreement"], 1.0)
        self.assertNotEqual(selection["rule_id"], "R3_UNCERTAINTY_GATE")

    def test_rule_catalogue_is_ordered_by_complexity(self) -> None:
        complexities = [rule.complexity for rule in router.ROUTE_RULES]
        self.assertEqual(complexities, sorted(complexities))
        self.assertGreaterEqual(len(router.ROUTE_RULES), 2)
        self.assertLessEqual(len(router.ROUTE_RULES), 3)

    def test_select_rule_needs_a_probe(self) -> None:
        with self.assertRaises(router.RouterError):
            router.select_rule([])

    def test_unknown_rule_is_refused(self) -> None:
        with self.assertRaises(router.RouterError):
            router.route_rule("R99_NOT_A_RULE")

    # -- negative guards: no neighbour substitution --------------------------

    def test_negative_exact_lookup_never_reads_a_neighbour(self) -> None:
        index = {
            router.exact_context_key(self.frequent): FREQUENT_REPEATS,
            router.exact_context_key(self.rare): RARE_REPEATS,
        }
        novel_key = router.exact_context_key(self.novel_in_domain)
        self.assertNotIn(novel_key, index)
        # The absent key resolves to zero support, never to a neighbour's count.
        self.assertEqual(router.resolve_support_exact(index, novel_key), 0)
        for neighbour in index.values():
            self.assertNotEqual(router.resolve_support_exact(index, novel_key), neighbour)
        with self.assertRaises(router.NeighbourSubstitutionRefused) as caught:
            router.resolve_support_exact(index, novel_key, allow_nearest_neighbour=True)
        self.assertEqual(caught.exception.code, router.FAIL_CLOSED_NEIGHBOUR_SUBSTITUTION)

    def test_negative_flooding_a_neighbour_never_raises_an_absent_cell(self) -> None:
        """The numerically nearest observed cell can be flooded; support stays 0."""
        neighbour = _row(actor_position="BTN", to_call_bb=7.0001, pot_before_bb=1.52)
        flooded = router.build_calibration(
            [*self.rows, *[dict(neighbour) for _ in range(500)]]
        )
        neighbour_signals = router.compute_signals(neighbour, calibration=flooded)
        novel_signals = router.compute_signals(self.novel_in_domain, calibration=flooded)
        self.assertNotEqual(
            neighbour_signals["context_key"], novel_signals["context_key"]
        )
        self.assertEqual(neighbour_signals["support_exact"], 500)
        self.assertEqual(novel_signals["support_exact"], 0)
        self.assertEqual(
            router.resolve_support_exact(
                flooded["exact_context_support"], novel_signals["context_key"]
            ),
            0,
        )

    def test_negative_missing_axis_is_not_replaced_by_the_nearest_price(self) -> None:
        context = dict(self.frequent)
        del context["pot_before_bb"]
        self.assertIsNone(router.resolve_numeric_axis(context, "pot_before_bb"))
        with self.assertRaises(router.NeighbourSubstitutionRefused) as caught:
            router.resolve_numeric_axis(context, "pot_before_bb", allow_nearest_price=True)
        self.assertEqual(caught.exception.code, router.FAIL_CLOSED_NEIGHBOUR_SUBSTITUTION)
        # The exact axis is read from its own field, never from a neighbour axis.
        self.assertEqual(
            router.resolve_numeric_axis(context, "to_call_bb"), context["to_call_bb"]
        )
        with self.assertRaises(router.RouterError) as unknown:
            router.resolve_numeric_axis(context, "not_an_axis")
        self.assertEqual(unknown.exception.code, router.FAIL_CLOSED_UNKNOWN_AXIS)

    def test_negative_sizing_provenance_refuses_a_neighbouring_target(self) -> None:
        context = dict(self.rare)
        # 11.4 / (1.5 + 8.0) = 1.2, inside the calibrated sizing domain.
        context["target_total_bb"] = 11.4
        probabilities = {"FOLD": 0.1, "CALL": 0.1, "RAISE": 0.7, "JAM": 0.1}
        with self.assertRaises(router.RouterError) as caught:
            router.attach_channel_answer(
                context,
                route_source=router.ROUTE_SOURCE_SPARSE,
                channel=self._channel(
                    probabilities=probabilities,
                    sizing_provenance={
                        "target_total_bb": 11.65,  # a neighbouring target
                        "no_nearest_price_substitution": True,
                    },
                ),
            )
        self.assertEqual(caught.exception.code, router.FAIL_CLOSED_SIZING_TARGET)
        with self.assertRaises(router.NeighbourSubstitutionRefused):
            router.attach_channel_answer(
                context,
                route_source=router.ROUTE_SOURCE_SPARSE,
                channel=self._channel(
                    probabilities=probabilities,
                    sizing_provenance={
                        "target_total_bb": 11.4,
                        "no_nearest_price_substitution": False,
                    },
                ),
            )
        with self.assertRaises(router.RouterError) as missing:
            router.attach_channel_answer(
                context,
                route_source=router.ROUTE_SOURCE_SPARSE,
                channel=self._channel(probabilities=probabilities),
            )
        self.assertEqual(missing.exception.code, router.FAIL_CLOSED_MISSING_SIZING)

    def test_negative_module_never_requests_a_substitution(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("allow_nearest_price=True", source)
        self.assertNotIn("allow_nearest_neighbour=True", source)
        self.assertFalse(router.NEAREST_PRICE_SUBSTITUTED)
        self.assertFalse(router.NEAREST_CONTEXT_SUBSTITUTED)
        self.assertTrue(router.NO_NEAREST_PRICE_SUBSTITUTION)
        self.assertTrue(router.NO_NEAREST_CONTEXT_SUBSTITUTION)
        self.assertIn("NO_NEAREST_PRICE_SUBSTITUTION", source)
        self.assertIn("NO_NEAREST_CONTEXT_SUBSTITUTION", source)

    def test_no_ad_hoc_context_table_in_the_module(self) -> None:
        """The only context-keyed data the router reads is the frozen index."""
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict) or len(node.keys) < 8:
                continue
            literal_keys = [
                key.value
                for key in node.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            ]
            # An exact-context signature always carries the "|" separator.
            self.assertFalse(
                any("|" in key for key in literal_keys),
                f"an ad-hoc context table literal at line {node.lineno}",
            )

    # -- runtime contract -----------------------------------------------------

    def test_route_document_contract(self) -> None:
        document = router.route(self.frequent, calibration=self.calibration)
        for key in router.ROUTING_DOCUMENT_REQUIRED_KEYS:
            self.assertIn(key, document, key)
        self.assertEqual(document["schema"], router.ROUTING_DOCUMENT_SCHEMA)
        self.assertEqual(document["route_source"], router.ROUTE_SOURCE_ACTIVE)
        self.assertEqual(document["rule"]["id"], router.DEFAULT_RULE_ID)
        self.assertEqual(document["support_state"], router.SUPPORT_STATE_STRONG)
        self.assertEqual(document["uncertainty"], "HIGH")  # no candidate supplied
        self.assertFalse(document["analysis_admissible"])  # routing-only surface
        self.assertIsNone(document["probabilities"])
        self.assertFalse(document["abstain"])
        self.assertEqual(
            document["decision_canonical_sha256"],
            router.canonical_sha256(
                {k: v for k, v in document.items() if k != "decision_canonical_sha256"}
            ),
        )

    def test_route_document_is_byte_stable(self) -> None:
        first = router.route(self.novel_in_domain, calibration=self.calibration)
        second = router.route(dict(self.novel_in_domain), calibration=self.calibration)
        self.assertEqual(router.canonical_json(first), router.canonical_json(second))

    def test_route_with_channels_emits_a_legal_distribution(self) -> None:
        channels = {
            router.ROUTE_SOURCE_ACTIVE: lambda _context: {
                "model_id": "active_model_a_preflop_population",
                "model_hash": MODEL_HASH,
                "probabilities": {"FOLD": 0.7, "CALL": 0.1, "RAISE": 0.1, "JAM": 0.1},
            }
        }
        document = router.route(
            self.frequent, calibration=self.calibration, channels=channels
        )
        self.assertEqual(document["route_source"], router.ROUTE_SOURCE_ACTIVE)
        self.assertEqual(document["model_id"], "active_model_a_preflop_population")
        self.assertEqual(document["model_hash"], MODEL_HASH)
        self.assertEqual(document["selected_action"], "FOLD")
        self.assertTrue(document["analysis_admissible"])
        self.assertEqual(document["channel"]["probability_sum"], 1.0)
        self.assertEqual(document["channel"]["illegal_mass"], 0.0)
        self.assertEqual(sum(document["probabilities"].values()), 1.0)

    def test_route_with_aggressive_channel_requires_exact_sizing_provenance(self) -> None:
        context = dict(self.rare)
        context["target_total_bb"] = 11.4  # ratio 1.2, inside the sizing domain
        channels = {
            router.ROUTE_SOURCE_SPARSE: lambda _context: self._channel(
                probabilities={"FOLD": 0.05, "CALL": 0.05, "RAISE": 0.8, "JAM": 0.1},
                sizing_provenance={
                    "target_total_bb": 11.4,
                    "no_nearest_price_substitution": True,
                },
            )
        }
        document = router.route(context, calibration=self.calibration, channels=channels)
        self.assertEqual(document["route_source"], router.ROUTE_SOURCE_SPARSE)
        self.assertEqual(document["selected_action"], "RAISE")
        self.assertTrue(document["analysis_admissible"])
        self.assertEqual(document["sizing_provenance"]["target_total_bb"], 11.4)
        self.assertTrue(document["sizing_provenance"]["no_nearest_price_substitution"])

    def test_channel_probabilities_are_masked_to_the_legal_actions(self) -> None:
        vector, total, illegal = router.canonical_legal_distribution(
            {"FOLD": 0.25, "CALL": 0.25, "RAISE": 0.25, "JAM": 0.25}, ["FOLD"]
        )
        self.assertEqual(vector, {"FOLD": 1.0, "CALL": 0.0, "RAISE": 0.0, "JAM": 0.0})
        self.assertEqual(total, 1.0)
        self.assertEqual(illegal, 0.0)

    def test_channel_without_legal_mass_fails_closed(self) -> None:
        context = dict(self.frequent)
        context["to_call_bb"] = 0.0  # no price to call: CALL is illegal
        legal = router.legal_response_actions(context)
        self.assertIn("FOLD", legal)
        self.assertNotIn("CALL", legal)
        self.assertEqual(legal, model.legal_response_actions(context))
        with self.assertRaises(router.RouterError) as caught:
            router.attach_channel_answer(
                context,
                route_source=router.ROUTE_SOURCE_SPARSE,
                channel=self._channel(probabilities={"CALL": 1.0}),
            )
        self.assertEqual(caught.exception.code, router.FAIL_CLOSED_NO_LEGAL_MASS)

    def test_legal_actions_field_is_authoritative(self) -> None:
        context = dict(self.frequent)
        context["legal_actions"] = ["FOLD"]
        self.assertEqual(router.legal_response_actions(context), ["FOLD"])
        vector, total, illegal = router.canonical_legal_distribution(
            {"FOLD": 0.5, "CALL": 0.5}, router.legal_response_actions(context)
        )
        self.assertEqual(vector["CALL"], 0.0)
        self.assertEqual(vector["FOLD"], 1.0)
        self.assertEqual(total, 1.0)
        self.assertEqual(illegal, 0.0)

    def test_invalid_model_hash_fails_closed(self) -> None:
        with self.assertRaises(router.RouterError) as caught:
            router.attach_channel_answer(
                self.frequent,
                route_source=router.ROUTE_SOURCE_ACTIVE,
                channel={
                    "model_id": "x",
                    "model_hash": "not-a-digest",
                    "probabilities": {"FOLD": 1.0},
                },
            )
        self.assertEqual(caught.exception.code, router.FAIL_CLOSED_INVALID_MODEL_HASH)

    def test_abstention_never_carries_a_channel_answer(self) -> None:
        channels = {
            router.ROUTE_SOURCE_ABSTAIN: lambda _context: {
                "model_id": "should-not-be-used",
                "model_hash": MODEL_HASH,
                "probabilities": {"FOLD": 1.0},
            }
        }
        document = router.route(
            self.novel_category, calibration=self.calibration, channels=channels
        )
        self.assertEqual(document["route_source"], router.ROUTE_SOURCE_ABSTAIN)
        self.assertEqual(document["model_id"], "none")
        self.assertIsNone(document["model_hash"])
        self.assertIsNone(document["channel"])
        self.assertIsNone(document["probabilities"])
        self.assertFalse(document["analysis_admissible"])

    # -- calibration ----------------------------------------------------------

    def test_calibration_builder_refuses_a_non_train_row(self) -> None:
        rows = list(self.rows)
        rows[0] = dict(rows[0], split="VALIDATION")
        with self.assertRaises(router.RouterError) as caught:
            router.build_calibration(rows)
        self.assertEqual(caught.exception.code, router.FAIL_CLOSED_REFUSED_SPLIT)

    def test_calibration_validation_rejects_a_shape_mismatch(self) -> None:
        broken = dict(self.calibration)
        broken["category_counts"] = {}
        self.assertTrue(router.validate_calibration(broken))
        with self.assertRaises(router.RouterError) as caught:
            router.resolve_calibration(broken)
        self.assertEqual(caught.exception.code, router.FAIL_CLOSED_CALIBRATION_INVALID)

    def test_declared_thresholds_match_the_frozen_spec(self) -> None:
        spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
        constants = {item["name"]: item["value"] for item in spec["procedure"]["constants"]}
        self.assertEqual(
            router.FREQUENT_EXACT_MIN_SUPPORT, constants["FREQUENT_EXACT_MIN_SUPPORT"]
        )
        self.assertEqual(router.RARE_EXACT_MIN_SUPPORT, constants["RARE_EXACT_MIN_SUPPORT"])

    def test_frozen_spec_and_router_agree_on_the_declared_surface(self) -> None:
        spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            [source["id"] for source in spec["route_sources"]],
            list(router.ROUTE_SOURCES),
        )
        self.assertEqual(
            {signal["id"] for signal in spec["signals"]},
            set(router.SIGNAL_IDS),
        )
        self.assertEqual(
            set(spec["ood_gate"]["soft_reason_codes"]), set(model.OOD_SOFT_REASONS)
        )
        self.assertEqual(
            set(spec["ood_gate"]["hard_reason_codes"]), set(model.OOD_HARD_REASONS)
        )
        self.assertEqual(spec["ood_gate"]["reused_from"], "issue-421")


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""#423 T11 -- consolidated mandatory contract suite.

This module is the single, named regression suite the ticket asks for: every
mandatory item of the #423 hybrid-router cycle is one ``test_*`` method that
fails closed when the contract is violated.  Nothing here needs the network, a
Hero EV run, a #367 launch or a holdout split.

Mandatory items and their named tests (the mapping is machine-checked by
``test_every_mandatory_item_has_exactly_one_named_test`` and by
``tests/ci/test_issue423_contract_guards.py``):

``FREQUENT_SPARSE_OOD_SEPARATION``
    ``test_frequent_sparse_and_ood_strata_are_separated``
``OOD_ABSTENTION_FAIL_CLOSED``
    ``test_ood_probes_abstain_fail_closed``
``NO_NEAREST_PRICE_OR_CONTEXT_SUBSTITUTION``
    ``test_no_nearest_price_or_context_substitution``
``PREREGISTERED_MARGIN``
    ``test_the_margin_is_preregistered_before_the_terminal_score``
``SPARSE_CALIBRATION_CEILING``
    ``test_the_sparse_calibration_ceiling_is_enforced``
``MACHINE_READABLE_PROVENANCE``
    ``test_provenance_is_machine_readable``
``TEST_UNREACHABLE``
    ``test_the_test_split_is_unreachable``
``ACTIVE_POINTER_IMMUTABLE``
    ``test_the_active_pointer_is_immutable_and_pinned``
``ISSUE367_NOT_EXECUTED``
    ``test_issue_367_is_never_executed``
``VALIDATION_421_NOT_REREAD``
    ``test_the_issue421_validation_split_is_never_reread``

``pytest`` is not a declared dependency of this repository; the suite is a plain
``unittest`` module, run with ``python3 -m unittest`` like its siblings.
"""
from __future__ import annotations

import ast
import collections
import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.preflop import generalized_response_model as model  # noqa: E402
from tools.preflop import generalized_response_runtime as gen_runtime  # noqa: E402
from tools.preflop import hybrid_response_router as router  # noqa: E402
from tools.preflop import hybrid_response_runtime as runtime  # noqa: E402
from tools.simulation import issue423_issue367_preflight as preflight_tool  # noqa: E402
from tools.training import build_issue423_evidence_bundle as bundle_tool  # noqa: E402
from tools.training import evaluate_hybrid_router_cv as cv  # noqa: E402
from tools.training import freeze_hybrid_router_criteria as freeze  # noqa: E402

BUNDLE = ROOT / "analysis/issue423_hybrid_router"
SPEC_PATH = BUNDLE / "HYBRID_ROUTER_SPEC.json"
MANIFEST_PATH = BUNDLE / "ROUTER_MANIFEST.json"
REPORT_PATH = BUNDLE / "TRAIN_CV_ROUTER_REPORT.json"
CALIBRATION_PATH = BUNDLE / "GENERALIZED_CALIBRATION_REPORT.json"
PREFLIGHT_PATH = BUNDLE / "ISSUE367_PREFLIGHT.json"
DECISION_PATH = BUNDLE / "DECISION.json"
INDEX_PATH = BUNDLE / "ARTIFACTS.json"
N8N_RESULT_PATH = BUNDLE / "N8N_TASK_RESULT.json"

OOD_CRITERION_ID = "OOD_ABSTENTION_CRITERION"
SPARSE_ECE_CRITERION_ID = "SPARSE_ECE_CEILING"
MARGIN_CRITERION_ID = "GLOBAL_NON_INFERIORITY_MARGIN"
SPARSE_STRATA = ("rare_exact", "exact_absent_in_domain")

JSON_SUFFIXES = frozenset({".json", ".jsonl"})

#: The ticket's own #367 preflight evidence surfaces.  They are analysis
#: artifacts, not Hero EV runners, so a run that also imported the #421
#: preflight must not mistake it for an executed #367 surface.
PREFLIGHT_EVIDENCE_SURFACES = frozenset(
    {
        "tools.simulation.issue421_issue367_preflight",
        "tools.simulation.issue423_issue367_preflight",
    }
)

#: Every mandatory ticket item, its stable id and the named test that pins it.
MANDATORY_CONTRACT_ITEMS: tuple[dict[str, str], ...] = (
    {
        "id": "FREQUENT_SPARSE_OOD_SEPARATION",
        "test": "test_frequent_sparse_and_ood_strata_are_separated",
        "description": (
            "the strict, sparse and out-of-domain strata are disjoint, and each routed "
            "source answers only the strata the frozen table gives it"
        ),
    },
    {
        "id": "OOD_ABSTENTION_FAIL_CLOSED",
        "test": "test_ood_probes_abstain_fail_closed",
        "description": (
            "every out-of-domain probe abstains fail-closed with its hard reason: no "
            "distribution, no selected action, no sizing"
        ),
    },
    {
        "id": "NO_NEAREST_PRICE_OR_CONTEXT_SUBSTITUTION",
        "test": "test_no_nearest_price_or_context_substitution",
        "description": (
            "a changed request is recomputed and a neighbour request is refused -- no "
            "nearest-price or nearest-context substitution ever answers a decision"
        ),
    },
    {
        "id": "PREREGISTERED_MARGIN",
        "test": "test_the_margin_is_preregistered_before_the_terminal_score",
        "description": (
            "the non-inferiority margin is a preregistered constant, frozen before the "
            "terminal TRAIN score existed, and re-derives from the procedure"
        ),
    },
    {
        "id": "SPARSE_CALIBRATION_CEILING",
        "test": "test_the_sparse_calibration_ceiling_is_enforced",
        "description": (
            "the sparse expected-calibration-error ceiling is a frozen numeric criterion "
            "and a breach fails admission instead of being waived"
        ),
    },
    {
        "id": "MACHINE_READABLE_PROVENANCE",
        "test": "test_provenance_is_machine_readable",
        "description": (
            "every decision and every persisted artifact carries machine-readable, "
            "content-addressed provenance that reproduces from the frozen bytes"
        ),
    },
    {
        "id": "TEST_UNREACHABLE",
        "test": "test_the_test_split_is_unreachable",
        "description": "the TEST split is refused by every loader and never appears in the bundle",
    },
    {
        "id": "ACTIVE_POINTER_IMMUTABLE",
        "test": "test_the_active_pointer_is_immutable_and_pinned",
        "description": (
            "the active Model A/B pointers, the two registries and the model admitted for "
            "#367 stay byte-identical to their pins"
        ),
    },
    {
        "id": "ISSUE367_NOT_EXECUTED",
        "test": "test_issue_367_is_never_executed",
        "description": "no #367 run, Hero EV, rollout or recommendation is computed by this cycle",
    },
    {
        "id": "VALIDATION_421_NOT_REREAD",
        "test": "test_the_issue421_validation_split_is_never_reread",
        "description": (
            "the #421 VALIDATION split is never re-opened: the split policy, the harness, "
            "the calibration and the runtime all consume TRAIN only"
        ),
    },
)


def ood_probe_contexts() -> dict[str, tuple[dict, str]]:
    """One executable out-of-domain probe per frozen hard reason code."""
    base = {
        "family": "VS_ISO",
        "actor_position": "BB",
        "aggressor_position": "SB",
        "limper_count": 0,
        "caller_count": 0,
        "table_size": 6,
        "live_positions": ["BB", "SB"],
        "all_in_positions": [],
        "raise_level": 1,
        "to_call_bb": 4.0,
        "pot_before_bb": 8.0,
        "effective_stack_bb": 125.0,
        "target_total_bb": None,
    }
    sizing = dict(base)
    sizing["target_total_bb"] = 99999.0
    sizing["legal_target_interval_bb"] = [1.0, 50000.0]
    return {
        "unseen_category": ({**base, "family": "OPEN_SHOVE_CONTRACT_PROBE"}, "UNSEEN_CATEGORY"),
        "extrapolation_stack": ({**base, "effective_stack_bb": 99999.0}, "EXTRAPOLATION_STACK"),
        "extrapolation_sizing": (sizing, "EXTRAPOLATION_SIZING"),
        "extrapolation_price": (
            {**base, "to_call_bb": 4000.0, "pot_before_bb": 100.0, "effective_stack_bb": 4000.0},
            "EXTRAPOLATION_PRICE",
        ),
        "missing_domain_axis": (
            {key: value for key, value in base.items() if key != "effective_stack_bb"},
            "MISSING_DOMAIN_AXIS",
        ),
    }


def spec_constants(spec: dict) -> dict:
    """The preregistered procedure constants of the frozen #423 spec."""
    return {entry["name"]: entry["value"] for entry in spec["procedure"]["constants"]}


class Issue423MandatoryContractTests(unittest.TestCase):
    """One named, fail-closed test per mandatory #423 contract item."""

    _preflight: dict | None = None
    _preflight_summary: list[str] | None = None

    @classmethod
    def setUpClass(cls) -> None:
        if not DECISION_PATH.is_file() or not PREFLIGHT_PATH.is_file():
            raise unittest.SkipTest("the frozen #423 evidence bundle is absent from this worktree")
        cls.decision = json.loads(DECISION_PATH.read_text(encoding="utf-8"))
        cls.index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        cls.spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        cls.report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        cls.calibration_report = json.loads(CALIBRATION_PATH.read_text(encoding="utf-8"))
        cls.n8n_result = json.loads(N8N_RESULT_PATH.read_text(encoding="utf-8"))
        cls.tree = json.loads(preflight_tool.REQUIRED_TREE_PATH.read_text(encoding="utf-8"))
        cls.tree_nodes = {str(node["id"]): node for node in cls.tree["nodes"]}
        cls.frontiers = json.loads(preflight_tool.model.FRONTIER_RESOLUTION_PATH.read_text("utf-8"))
        runtime.clear_runtime_caches()
        cls.runtime = runtime.load_runtime(None, None, None, None)

    @classmethod
    def preflight_document(cls) -> dict:
        if cls._preflight is None:
            cls._preflight, cls._preflight_summary = preflight_tool.build()
        return cls._preflight

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _criterion(manifest: dict, criterion_id: str) -> dict:
        for entry in manifest["frozen_criteria"]["criteria"]:
            if entry["id"] == criterion_id:
                return entry
        raise AssertionError(f"criterion {criterion_id} is missing from the frozen manifest")

    @classmethod
    def _walked_records(cls) -> list[dict]:
        document = cls.preflight_document()
        return list(document["nodes"]) + list(document["sizing_frontiers"])

    @staticmethod
    def _split_rows_in_bundle() -> list[tuple[str, str]]:
        """Every persisted row-like ``split`` value, resolved from the raw bytes."""
        found: list[tuple[str, str]] = []
        for path in sorted(BUNDLE.rglob("*")):
            if not path.is_file() or path.suffix not in JSON_SUFFIXES:
                continue
            name = path.relative_to(ROOT).as_posix()
            text = path.read_text(encoding="utf-8", errors="replace")
            try:
                if path.suffix == ".jsonl":
                    documents: list = [
                        json.loads(line) for line in text.splitlines() if line.strip()
                    ]
                else:
                    documents = [json.loads(text)]
            except ValueError:  # pragma: no cover - defensive
                continue

            def walk(node: object) -> None:
                if isinstance(node, dict):
                    split = node.get("split")
                    if isinstance(split, str):
                        found.append((name, split))
                    for value in node.values():
                        walk(value)
                elif isinstance(node, list):
                    for value in node:
                        walk(value)

            for document in documents:
                walk(document)
        return found

    # ------------------------------------------------------------- item tests
    def test_frequent_sparse_and_ood_strata_are_separated(self) -> None:
        frequent = router.STRATUM_FREQUENT_EXACT
        rare = router.STRATUM_RARE_EXACT
        absent_in_domain = router.STRATUM_EXACT_ABSENT_IN_DOMAIN
        absent_ood = router.STRATUM_EXACT_ABSENT_OUT_OF_DOMAIN
        self.assertEqual(router.STRATA, (frequent, rare, absent_in_domain, absent_ood))
        self.assertEqual(len(set(router.STRATA)), 4)
        self.assertEqual(
            router.ROUTED_STRATA_OF_SOURCE,
            {
                router.ROUTE_SOURCE_ACTIVE: (frequent,),
                router.ROUTE_SOURCE_SPARSE: (rare, absent_in_domain),
                router.ROUTE_SOURCE_ABSTAIN: (absent_ood,),
            },
        )
        self.assertEqual(
            router.SUPPORT_STATE_OF_ROUTE,
            {
                router.ROUTE_SOURCE_ACTIVE: router.SUPPORT_STATE_STRONG,
                router.ROUTE_SOURCE_SPARSE: router.SUPPORT_STATE_SPARSE,
                router.ROUTE_SOURCE_ABSTAIN: router.SUPPORT_STATE_ABSTAIN,
            },
        )
        self.assertEqual(router.FREQUENT_EXACT_MIN_SUPPORT, 20)
        self.assertEqual(router.RARE_EXACT_MIN_SUPPORT, 1)
        for support, in_domain, expected in (
            (20, True, frequent),
            (500, True, frequent),
            (19, True, rare),
            (1, True, rare),
            (0, True, absent_in_domain),
            (0, False, absent_ood),
        ):
            with self.subTest(support=support, in_domain=in_domain):
                self.assertEqual(router.classify_stratum(support, in_domain), expected)
        # The frozen reference rule wires each stratum to exactly one route source.
        for support, in_domain, expected in (
            (25, True, router.ROUTE_SOURCE_ACTIVE),
            (5, True, router.ROUTE_SOURCE_SPARSE),
            (0, True, router.ROUTE_SOURCE_SPARSE),
            (0, False, router.ROUTE_SOURCE_ABSTAIN),
        ):
            signals = {
                "hard_reasons": [],
                "support_exact": support,
                "feature_in_domain": in_domain,
            }
            with self.subTest(support=support, in_domain=in_domain):
                self.assertEqual(router.route_source(signals), expected)
                self.assertEqual(router.route_rule().id, router.REFERENCE_RULE_ID)
        # A hard reason abstains whatever the support.
        for support in (0, 5, 25):
            signals = {
                "hard_reasons": ["UNSEEN_CATEGORY"],
                "support_exact": support,
                "feature_in_domain": True,
            }
            with self.subTest(support=support):
                self.assertEqual(router.route_source(signals), router.ROUTE_SOURCE_ABSTAIN)
        # The frozen spec and the frozen manifest agree with the module.
        strata = {entry["id"]: entry for entry in self.spec["strata"]["strata"]}
        self.assertEqual(set(strata), set(router.STRATA))
        self.assertEqual(
            self.spec["strata"]["sparse_covered_strata"],
            list(router.ROUTED_STRATA_OF_SOURCE[router.ROUTE_SOURCE_SPARSE]),
        )
        self.assertEqual(
            self.spec["strata"]["ood_strata"],
            list(router.ROUTED_STRATA_OF_SOURCE[router.ROUTE_SOURCE_ABSTAIN]),
        )
        self.assertFalse(strata[frequent]["covered_by_sparse_floor"])
        routed_of_stratum = {
            stratum: source
            for source, members in router.ROUTED_STRATA_OF_SOURCE.items()
            for stratum in members
        }
        for stratum in router.STRATA:
            with self.subTest(stratum=stratum):
                self.assertEqual(strata[stratum]["routed_to"], routed_of_stratum[stratum])
                self.assertEqual(
                    strata[stratum]["covered_by_sparse_floor"], stratum in SPARSE_STRATA
                )
        margin = self._criterion(self.manifest, MARGIN_CRITERION_ID)
        self.assertEqual(
            margin["effectifs"]["admission_strata"], [frequent, rare, absent_in_domain]
        )
        # Executable: every walked decision is answered by the source that owns its stratum.
        seen: collections.Counter[str] = collections.Counter()
        for record in self._walked_records():
            decision = record["decision"]
            stratum = decision["stratum"]
            routed = decision["routed_source"]
            with self.subTest(context=decision["context_key"]):
                self.assertIn(stratum, router.STRATA)
                self.assertIn(stratum, router.ROUTED_STRATA_OF_SOURCE[routed])
                self.assertIn(decision["route_source"], (routed, router.ROUTE_SOURCE_ABSTAIN))
                if record["decision_class"] == preflight_tool.DIRECT_EVAL:
                    self.assertEqual(decision["route_source"], routed)
            seen[stratum] += 1
        self.assertTrue(seen)
        self.assertEqual(set(seen) - {frequent, rare, absent_in_domain}, set())
        self.assertEqual(set(seen), {frequent, rare, absent_in_domain})

    def test_ood_probes_abstain_fail_closed(self) -> None:
        criterion = self._criterion(self.manifest, OOD_CRITERION_ID)
        self.assertEqual(criterion["direction"], "predicate")
        self.assertEqual(criterion["value"], 1.0)
        self.assertEqual(
            set(criterion["effectifs"]["declared_probe_kinds"]), set(cv.PROBE_KINDS)
        )
        self.assertEqual(
            len(criterion["effectifs"]["declared_probe_kinds"]), len(cv.PROBE_KINDS)
        )
        self.assertEqual(
            criterion["effectifs"]["probes_per_kind"],
            {kind: 160 for kind in cv.PROBE_KINDS},
        )
        self.assertEqual(criterion["justification"]["preregistered_reference"][
            "OOD_ABSTAIN_is_decisive_for_hard_reasons_only"
        ], True)
        # The frozen criterion is met by the harness on its own probe surface.
        ood = self.report["ood_synthetic_probes"]
        self.assertEqual(ood["abstain_rate"], 1.0)
        self.assertTrue(ood["assertions"]["router_abstains_on_every_probe"])
        for kind in cv.PROBE_KINDS:
            block = ood["by_kind"][kind]
            with self.subTest(kind=kind):
                self.assertEqual(block["expected_reason"], cv.PROBE_EXPECTED_REASON[kind])
                self.assertIn(block["expected_reason"], model.OOD_HARD_REASONS)
                self.assertEqual(block["n"], 160)
                self.assertEqual(block["router_abstained"], block["n"])
                self.assertEqual(block["abstain_rate"], 1.0)
                self.assertTrue(block["expected_reason_present"])
        # Executable: each frozen hard reason abstains directly, fail-closed.
        covered: set[str] = set()
        for kind, (context, expected) in ood_probe_contexts().items():
            document = self.runtime.resolve(context, strict=False)
            with self.subTest(kind=kind):
                self.assertEqual(document["route_source"], router.ROUTE_SOURCE_ABSTAIN)
                self.assertEqual(document["support_state"], router.SUPPORT_STATE_ABSTAIN)
                self.assertEqual(document["ood_status"], model.STATUS_MODEL_OOD_ABSTAIN)
                self.assertTrue(document["abstain"])
                self.assertFalse(document["analysis_admissible"])
                self.assertIsNone(document["probabilities"])
                self.assertIsNone(document["selected_action"])
                self.assertIsNone(document["sizing_provenance"])
                self.assertFalse(document["nearest_price_substituted"])
                self.assertFalse(document["nearest_context_substituted"])
                self.assertEqual(
                    document["fail_closed_reason"], gen_runtime.OOD_ABSTAIN_REASON
                )
                self.assertIn(expected, document["signals"]["hard_reasons"])
                covered.update(document["signals"]["hard_reasons"])
        self.assertEqual(set(model.OOD_HARD_REASONS), covered)
        rule = self.preflight_document()["ood_rule"]
        self.assertEqual(rule["rule_id"], OOD_CRITERION_ID)
        self.assertTrue(rule["hard_reason_codes_are_decisive"])
        self.assertTrue(rule["abstains_on_hard_reasons_only"])
        self.assertTrue(rule["soft_reasons_may_only_raise_uncertainty"])
        self.assertEqual(rule["hard_reason_codes"], list(model.OOD_HARD_REASONS))
        self.assertEqual(rule["soft_reason_codes"], list(model.OOD_SOFT_REASONS))
        self.assertEqual(rule["mechanised_predicate"], preflight_tool.FROZEN_RULE_TEXT)
        guard = preflight_tool.ood_branch_guard(self.runtime, rule)
        self.assertTrue(guard["passed"], guard["probes"])
        for probe in guard["probes"]:
            with self.subTest(probe=probe["kind"]):
                self.assertTrue(probe["abstained"])
                self.assertFalse(probe["analysis_admissible"])
                self.assertFalse(probe["distribution_present"])
                self.assertFalse(probe["sizing_present"])
                self.assertIsNone(probe["selected_action"])
                self.assertTrue(probe["expected_reason_present"])

    def test_no_nearest_price_or_context_substitution(self) -> None:
        self.assertTrue(router.NO_NEAREST_PRICE_SUBSTITUTION)
        self.assertTrue(router.NO_NEAREST_CONTEXT_SUBSTITUTION)
        self.assertIs(router.NEAREST_PRICE_SUBSTITUTED, False)
        self.assertIs(router.NEAREST_CONTEXT_SUBSTITUTED, False)
        self.assertTrue(runtime.NO_NEAREST_PRICE_SUBSTITUTION)
        self.assertTrue(runtime.NO_NEAREST_CONTEXT_SUBSTITUTION)
        self.assertIs(runtime.NEAREST_PRICE_SUBSTITUTED, False)
        self.assertIs(runtime.NEAREST_CONTEXT_SUBSTITUTED, False)
        document = self.preflight_document()
        audit = document["nearest_lookup_audit"]
        self.assertFalse(audit["nearest_price_substituted"])
        self.assertFalse(audit["nearest_context_substituted"])
        self.assertEqual(
            audit["substitution_classes_refused"],
            list(preflight_tool.SUBSTITUTION_CLASSES),
        )
        self.assertTrue(audit["probes_passed"])
        for probe in audit["probes"]:
            with self.subTest(probe=probe["probe"]):
                self.assertTrue(probe["passed"], probe)
        self.assertTrue(audit["active_exact_cell_probe"]["passed"])
        self.assertTrue(audit["request_refusal_probe"]["passed"])
        self.assertEqual(
            audit["request_refusal_probe"]["expected_code"],
            runtime.FAIL_CLOSED_NEIGHBOUR_SUBSTITUTION,
        )
        # No visited decision ever declares a substitution.
        for record in self._walked_records():
            decision = record["decision"]
            with self.subTest(context=decision["context_key"]):
                self.assertFalse(decision["nearest_price_substituted"])
                self.assertFalse(decision["nearest_context_substituted"])
                self.assertTrue(decision["no_nearest_price_substitution"])
                self.assertTrue(decision["no_nearest_context_substitution"])
        # Negative control: a caller asking for a neighbour is refused, fail-closed.
        self.assertTrue(runtime.SUBSTITUTION_REQUEST_KEYS)
        root = self.tree_nodes[str(self.tree["root_id"])]
        context = preflight_tool.node_request_context(root)
        for key in runtime.SUBSTITUTION_REQUEST_KEYS:
            probe = dict(context)
            probe[key] = True
            with self.subTest(request_key=key):
                with self.assertRaises(runtime.HybridResponseRuntimeError) as caught:
                    self.runtime.resolve(probe, strict=False)
                self.assertEqual(
                    caught.exception.code, runtime.FAIL_CLOSED_NEIGHBOUR_SUBSTITUTION
                )
        # Executable: a perturbed price/context is recomputed, never snapped.
        first_frontier = self.frontiers["frontiers"][0]
        frontier_node = self.tree_nodes[str(first_frontier["node_id"])]
        probes = preflight_tool.nearest_substitution_probes(
            self.runtime, root, first_frontier, frontier_node
        )
        self.assertTrue(probes["probes_passed"], probes["probes"])

    def test_the_margin_is_preregistered_before_the_terminal_score(self) -> None:
        procedure = self.spec["procedure"]
        self.assertTrue(procedure["preregistered"])
        self.assertTrue(procedure["registered_before_evaluation"])
        self.assertEqual(procedure["evaluation_basis"], "TRAIN_only_hand_grouped_out_of_fold")
        self.assertFalse(procedure["validation_consumed"])
        self.assertFalse(procedure["test_consumed"])
        constants = {entry["name"]: entry for entry in procedure["constants"]}
        for name in freeze.REQUIRED_CONSTANTS:
            with self.subTest(constant=name):
                self.assertIn(name, constants)
                self.assertIs(constants[name]["terminal_evaluation_derived"], False)
        self.assertEqual(constants["MARGIN_MAX_BITS"]["value"], 0.0)
        self.assertEqual(constants["MARGIN_ANALYTIC_TOLERANCE_BITS"]["value"], 0.001)
        self.assertEqual(constants["BOOTSTRAP_SEED"]["value"], 423)
        # The frozen margin value is the preregistered resolution, not a fitted number.
        margin = self._criterion(self.manifest, MARGIN_CRITERION_ID)
        self.assertFalse(margin["terminal_evaluation_derived"])
        self.assertEqual(margin["direction"], "lower_is_better")
        self.assertEqual(margin["value"], constants["MARGIN_ANALYTIC_TOLERANCE_BITS"]["value"])
        self.assertEqual(
            margin["justification"]["preregistered_reference"],
            {
                "MARGIN_MAX_BITS": constants["MARGIN_MAX_BITS"]["value"],
                "MARGIN_ANALYTIC_TOLERANCE_BITS": constants[
                    "MARGIN_ANALYTIC_TOLERANCE_BITS"
                ]["value"],
            },
        )
        self.assertFalse(
            margin["justification"]["preregistered_reference"]["MARGIN_MAX_BITS"]
        )
        self.assertEqual(
            margin["effectifs"]["admission_strata"],
            [
                router.STRATUM_FREQUENT_EXACT,
                router.STRATUM_RARE_EXACT,
                router.STRATUM_EXACT_ABSENT_IN_DOMAIN,
            ],
        )
        self.assertEqual(
            margin["justification"]["bootstrap_seed"], constants["BOOTSTRAP_SEED"]["value"]
        )
        # The freeze happened before the terminal score existed.
        self.assertEqual(self.manifest["status"], freeze.STATUS)
        self.assertEqual(self.spec["status"], preflight_tool.SPEC_STATUS)
        self.assertEqual(
            self.manifest["frozen_criteria"]["status"], freeze.STATUS
        )
        self.assertTrue(self.decision["frozen_criteria"]["authored_before_terminal_score"])
        order_guard = self.manifest["order_guard"]
        self.assertEqual(order_guard["guard_id"], "ROUTER_CRITERIA_ORDER_GUARD")
        self.assertEqual(order_guard["result"], "PASS")
        self.assertEqual(order_guard["declared_terminal_report_locations_present"], [])
        self.assertEqual(order_guard["violations"], [])
        score_guard = self.manifest["terminal_score_guard"]
        self.assertTrue(score_guard["terminal_report_absent_at_freeze"])
        self.assertTrue(score_guard["spec_digest_computed_before_terminal_score"])
        self.assertTrue(score_guard["regeneration_with_different_values_fails_closed"])
        order = list(procedure["derivation_order"])
        for criterion_id in freeze.CRITERIA_IDS:
            self.assertIn(criterion_id, order)
        for entry in self.manifest["frozen_criteria"]["criteria"]:
            with self.subTest(criterion=entry["id"]):
                self.assertFalse(entry["terminal_evaluation_derived"])
                self.assertTrue(entry["inputs"])
                self.assertTrue(entry["effectifs"])
        self.assertEqual(self.manifest["frozen_criteria"]["terminal_evaluation"]["consumed"], False)
        # Executable: the freeze re-derives the criteria and fails closed on a drift.
        self.assertEqual([], freeze.check())
        derived = freeze.assert_preregistered_procedure(self.spec)
        for name in freeze.REQUIRED_CONSTANTS:
            self.assertEqual(derived[name], constants[name]["value"])
        for mutation in (
            {"preregistered": False},
            {"registered_before_evaluation": False},
            {"evaluation_basis": "VALIDATION_included"},
            {"validation_consumed": True},
            {"test_consumed": True},
        ):
            with self.subTest(mutation=mutation):
                with self.assertRaises(freeze.HybridRouterCriteriaError):
                    freeze.assert_preregistered_procedure(
                        {**self.spec, "procedure": {**procedure, **mutation}}
                    )
        drifted = json.loads(json.dumps(self.spec))
        drifted["procedure"]["constants"] = [
            {**entry, "terminal_evaluation_derived": True} if entry["name"] == "MARGIN_MAX_BITS"
            else entry
            for entry in drifted["procedure"]["constants"]
        ]
        with self.assertRaises(freeze.HybridRouterCriteriaError):
            freeze.assert_preregistered_procedure(drifted)
        # The order guard itself fails closed when the terminal score already exists.
        with self.assertRaises(freeze.HybridRouterCriteriaError):
            freeze.assert_terminal_report_absent([REPORT_PATH])
        self.assertEqual(
            freeze.assert_terminal_report_absent([ROOT / "does/not/exist.json"])["result"],
            "PASS",
        )

    def test_the_sparse_calibration_ceiling_is_enforced(self) -> None:
        criterion = self._criterion(self.manifest, SPARSE_ECE_CRITERION_ID)
        self.assertEqual(criterion["direction"], "lower_is_better")
        self.assertFalse(criterion["terminal_evaluation_derived"])
        constants = spec_constants(self.spec)
        ceiling = constants["ECE_ABSOLUTE_CEILING"]
        self.assertEqual(criterion["value"], ceiling)
        self.assertEqual(
            criterion["justification"]["preregistered_reference"]["ECE_ABSOLUTE_CEILING"],
            ceiling,
        )
        self.assertIn(
            criterion["justification"]["binding_term"],
            ("ECE_ABSOLUTE_CEILING", "ECE_DELTA_CEILING"),
        )
        self.assertEqual(
            criterion["effectifs"]["calibration_bins_per_action_class"], 10
        )
        self.assertEqual(
            criterion["justification"]["per_stratum_ece"]["hybrid_router"],
            {
                "rare_exact": 0.024273,
                "exact_absent_in_domain": 0.040773,
            },
        )
        # The ceiling covers exactly the pooled sparse strata, never the frequent one.
        self.assertEqual(
            criterion["effectifs"]["active_stratum_decisions"],
            {"rare_exact": 10427, "exact_absent_in_domain": 2547},
        )
        evaluation = {
            entry["id"]: entry for entry in self.report["criteria_evaluation"]["criteria"]
        }
        observed = evaluation[SPARSE_ECE_CRITERION_ID]
        self.assertEqual(observed["comparator"], "<=")
        self.assertEqual(observed["threshold"], ceiling)
        self.assertFalse(observed["passed"])
        self.assertGreater(observed["observed"]["hybrid_ece"], ceiling)
        self.assertLess(
            observed["observed"]["hybrid_ece"], observed["observed"]["active_sparse_ece"]
        )
        self.assertFalse(self.report["criteria_evaluation"]["all_passed"])
        # A breached ceiling is a terminal, declared failure, not a silent waiver.
        self.assertEqual(self.report["outcome"], bundle_tool.RETAIN_OUTCOME)
        self.assertEqual(
            self.report["criteria_evaluation"]["failed"], [SPARSE_ECE_CRITERION_ID]
        )
        self.assertEqual(self.decision["failed_criteria"], [SPARSE_ECE_CRITERION_ID])
        self.assertEqual(self.decision["decision"], bundle_tool.RETAIN_OUTCOME)
        self.assertEqual(
            self.decision["criteria_order"],
            list(self.manifest["frozen_criteria"]["criteria_order"]),
        )
        self.assertEqual(self.decision["criteria_passed"], 4)
        self.assertEqual(self.decision["criteria_total"], 5)
        # Executable: the harness refuses a holdout read and re-verifies the freeze.
        self.assertEqual([], freeze.check())

    def test_provenance_is_machine_readable(self) -> None:
        # The runtime decision carries the full, structured provenance surface.
        root = self.tree_nodes[str(self.tree["root_id"])]
        context = preflight_tool.node_request_context(root)
        document = self.runtime.resolve(context, strict=False)
        for field in (
            "route_source",
            "routed_source",
            "support_state",
            "uncertainty",
            "ood_status",
            "stratum",
            "status",
            "model_id",
            "schema",
            "contract_schema",
            "decision_canonical_sha256",
            "routing_canonical_sha256",
        ):
            with self.subTest(field=field):
                self.assertIsInstance(document[field], str)
                self.assertTrue(document[field])
        self.assertEqual(document["provider"]["schema"], runtime.HYBRID_RUNTIME_PROVIDER_SCHEMA)
        self.assertEqual(
            document["provider"]["provider_kind"], self.runtime.metadata()["provider_kind"]
        )
        self.assertIn(document["route_source"], router.ROUTE_SOURCES)
        self.assertIn(document["support_state"], set(router.SUPPORT_STATE_OF_ROUTE.values()))
        self.assertIn(document["stratum"], router.STRATA)
        self.assertEqual(document["schema"], runtime.HYBRID_RUNTIME_DECISION_SCHEMA)
        self.assertEqual(document["contract_schema"], router.ROUTING_CONTRACT_SCHEMA)
        self.assertEqual(document["model_id"], router.DECLARED_MODEL_ID[document["route_source"]])
        self.assertEqual(document["routing"]["schema"], router.ROUTING_DOCUMENT_SCHEMA)
        self.assertEqual(
            document["routing_canonical_sha256"],
            document["routing"]["decision_canonical_sha256"],
        )
        self.assertEqual(
            document["decision_canonical_sha256"],
            runtime.decision_canonical_sha256(document),
        )
        self.assertEqual(
            document["signals"]["canonical_sha256"], router.signal_digest(document["signals"])
        )
        # A raise answer carries its own content-addressed sizing provenance.
        frontier = self.frontiers["frontiers"][0]
        frontier_node = self.tree_nodes[str(frontier["node_id"])]
        frontier_context = preflight_tool.frontier_request_context(frontier, frontier_node)
        frontier_document = self.runtime.resolve(frontier_context, strict=False)
        provenance = self.runtime.sizing_provenance(
            frontier_context,
            answer=preflight_tool._channel_answer(frontier_document),
            selected_action="RAISE",
        )
        self.assertEqual(provenance["schema"], runtime.SIZING_PROVENANCE_SCHEMA)
        self.assertEqual(provenance["action"], "RAISE")
        self.assertIn(provenance["route_source"], router.ROUTE_SOURCES)
        self.assertEqual(provenance["nearest_price_substituted"], False)
        self.assertEqual(provenance["nearest_context_substituted"], False)
        self.assertTrue(provenance["no_nearest_price_substitution"])
        self.assertTrue(provenance["no_nearest_context_substitution"])
        self.assertIn(
            provenance["probability_channel"],
            (runtime.ACTIVE_CHANNEL_NAME, runtime.CALIBRATED_CHANNEL_NAME),
        )
        self.assertEqual(provenance["sizing_channel"], runtime.SIZING_CHANNEL_ID)
        # The persisted index is reproducible, content-addressed and machine-readable.
        self.assertEqual(self.index["schema"], bundle_tool.INDEX_SCHEMA)
        self.assertEqual(set(self.index["artifacts"]), set(self.index["required_artifacts"]))
        for name, entry in self.index["artifacts"].items():
            with self.subTest(artifact=name):
                for field in (
                    "path",
                    "sha256",
                    "bytes",
                    "object",
                    "media_type",
                    "role",
                ):
                    self.assertIn(field, entry)
                if entry["media_type"] == "application/json":
                    self.assertIn("canonical_payload_sha256", entry)
                source = ROOT / entry["path"]
                self.assertTrue(source.is_file(), entry["path"])
                data = source.read_bytes()
                self.assertEqual(entry["bytes"], len(data))
                self.assertEqual(entry["sha256"], hashlib.sha256(data).hexdigest())
                self.assertTrue(entry["content_addressed"])
                self.assertEqual((ROOT / entry["object"]).read_bytes(), data)
        rebuilt = bundle_tool.build()
        self.assertEqual(rebuilt["index"], self.index)
        self.assertEqual(rebuilt["decision"], self.decision)
        self.assertEqual(
            rebuilt["decision_digest"], hashlib.sha256(DECISION_PATH.read_bytes()).hexdigest()
        )
        # The decision points at the pinned active references.
        for label, reference in self.decision["references"].items():
            with self.subTest(reference=label):
                self.assertTrue(reference["path"])
                digest = reference.get("sha256")
                if digest:
                    self.assertEqual(
                        digest, hashlib.sha256((ROOT / reference["path"]).read_bytes()).hexdigest()
                    )
        self.assertTrue(self.decision["decision_digest_location"])
        # The n8n hand-off is a machine-readable summary of the same outcome.
        self.assertEqual(self.n8n_result["issue"], 423)
        self.assertEqual(self.n8n_result["decision"], self.decision["decision"])
        self.assertEqual(self.n8n_result["test_consumed"], False)
        self.assertEqual(self.n8n_result["active_pointer_mutated"], False)
        self.assertEqual(
            self.n8n_result["router_sha256"],
            self.index["artifacts"]["HYBRID_ROUTER_SPEC.json"]["sha256"],
        )

    def test_the_test_split_is_unreachable(self) -> None:
        with self.assertRaises(runtime.HybridResponseRuntimeError) as caught:
            runtime.guard_split({"split": "TEST"})
        self.assertEqual(caught.exception.code, runtime.FAIL_CLOSED_TEST_SPLIT)
        with self.assertRaises(runtime.HybridResponseRuntimeError) as caught:
            runtime.guard_split({"split": "VALIDATION"})
        self.assertEqual(caught.exception.code, runtime.FAIL_CLOSED_REFUSED_SPLIT)
        self.assertIs(gen_runtime.TEST_CONSUMED, False)
        self.assertFalse(self.runtime.audit()["test_consumed"])
        document = self.preflight_document()
        self.assertFalse(document["boundary"]["test_consumed"])
        self.assertFalse(document["boundary"]["test_split_authorized"])
        self.assertFalse(self.decision["boundaries"]["test_consumed"])
        self.assertFalse(self.decision["boundaries"]["test_authorized"])
        self.assertEqual(self.decision["boundaries"]["refused_splits"], ["VALIDATION", "TEST"])
        self.assertFalse(self.report["scope"]["test_consumed"])
        self.assertEqual(self.report["scope"]["forbidden_splits"], list(model.FORBIDDEN_SPLITS))
        self.assertFalse(self.report["guards"]["test_consumed"])
        self.assertEqual(self.calibration_report["scope"]["refused_splits"], ["VALIDATION", "TEST"])
        # The harness refuses a TEST read and a TEST split request before a byte is read.
        with self.assertRaises(cv.HybridRouterCvError):
            cv.assert_train_only([{"split": "TEST"}], context="contract guard")
        with self.assertRaises(cv.HybridRouterCvError):
            cv.assert_consumed_splits(["TEST"], context="contract guard")
        self.assertEqual(cv.CONSUMED_SPLITS, ("TRAIN",))
        self.assertEqual(cv.REFUSED_SPLITS, ("VALIDATION", "TEST"))
        self.assertEqual(
            self.spec["split_policy"]["refused_splits"], ["VALIDATION", "TEST"]
        )
        self.assertEqual(self.spec["split_policy"]["allowed_splits"], ["TRAIN"])
        self.assertNotIn("TEST", self.spec["split_policy"]["consumed_splits"])
        # No persisted artifact carries a TEST row, and no visited context is a TEST split.
        splits = {split for _name, split in self._split_rows_in_bundle()}
        self.assertNotIn("TEST", splits)
        for record in self._walked_records():
            with self.subTest(context=record["decision"]["context_key"]):
                self.assertNotIn("TEST", str(record["requested_context"].get("split", "")))

    def test_the_active_pointer_is_immutable_and_pinned(self) -> None:
        before = preflight_tool.protected_hashes()
        self.assertEqual(set(before), set(preflight_tool.PROTECTED_FILES))
        for path in preflight_tool.PROTECTED_FILES:
            with self.subTest(path=path):
                self.assertEqual(
                    before[path], hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                )
        active = self.decision["references"]["active_model_a_preflop"]
        admitted = self.decision["references"]["admitted_model_for_issue367"]
        model_b = self.decision["references"]["model_b_postflop"]
        self.assertEqual(active["path"], bundle_tool.ACTIVE_MODEL_A_REL)
        self.assertEqual(admitted["path"], bundle_tool.ACTIVE_MODEL_A_REL)
        self.assertEqual(model_b["path"], bundle_tool.MODEL_B_REL)
        self.assertEqual(active["sha256"], admitted["sha256"])
        self.assertEqual(active["sha256"], before[bundle_tool.ACTIVE_MODEL_A_REL])
        for label, reference in (("model_a", active), ("admitted_for_367", admitted)):
            with self.subTest(reference=label):
                self.assertEqual(
                    reference["sha256"],
                    hashlib.sha256((ROOT / reference["path"]).read_bytes()).hexdigest(),
                )
                self.assertEqual(before[reference["path"]], reference["sha256"])
        # The pinned admitted model is exactly the model the #367 preflight records.
        admission = self.preflight_document()["admission"]
        retained = admission["currently_retained_reference"]
        self.assertEqual(retained["model_id"], active["model_id"])
        self.assertEqual(retained["path"], active["path"])
        # Exercise the runtime, the sizing channel and the preflight, then re-check.
        root = self.tree_nodes[str(self.tree["root_id"])]
        self.runtime.resolve(preflight_tool.node_request_context(root), strict=False)
        self.runtime.resolve(
            preflight_tool.node_request_context(root) | {"family": "NOT_A_FAMILY"},
            strict=False,
        )
        self.preflight_document()
        self.assertEqual(before, preflight_tool.protected_hashes())
        for path, digest in before.items():
            with self.subTest(path=path):
                self.assertEqual(
                    digest, hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                )
        self.assertFalse(self.runtime.audit()["active_model_pointer_mutated"])
        self.assertFalse(self.decision["boundaries"]["active_pointer_mutated"])
        self.assertFalse(self.decision["boundaries"]["active_model_pointer_mutation"])
        self.assertFalse(self.n8n_result["active_pointer_mutated"])
        self.assertEqual(self.decision["boundaries"]["automatic_promotion"], "FORBIDDEN")
        self.assertFalse(self.preflight_document()["admission"]["abstention"][
            "active_model_pointer_mutation"
        ])
        self.assertFalse(
            self.preflight_document()["admission"]["abstention"]["promotion_performed"]
        )
        self.assertTrue(self.preflight_document()["boundary"]["protected_files_unchanged"])

    def test_issue_367_is_never_executed(self) -> None:
        document = self.preflight_document()
        boundary = document["boundary"]
        self.assertFalse(boundary["issue367_executed"])
        self.assertFalse(boundary["hero_ev_executed"])
        self.assertFalse(boundary["recommendation_computed"])
        self.assertFalse(boundary["hero_ev_runner_imported"])
        self.assertEqual(boundary["rollouts_executed"], 0)
        self.assertEqual(boundary["ev_values_computed"], 0)
        scan = document["self_scans"]["hero_ev_scan"]
        self.assertEqual(scan["result"], "PASS")
        self.assertEqual(scan["hits"], [])
        self.assertEqual(scan["forbidden_modules_imported_during_build"], [])
        self.assertFalse(scan["runner_module_imported_by_preflight"])
        self.assertEqual(preflight_tool.verify_no_hero_ev_execution()["result"], "PASS")
        self.assertEqual(preflight_tool.verify_no_holdout_access()["result"], "PASS")
        # No #367 Hero EV / rollout module is loaded: only the ticket's own
        # preflight evidence surfaces may match the import markers.
        loaded = preflight_tool.hero_ev_modules_present()
        unexpected = sorted(name for name in loaded if name not in PREFLIGHT_EVIDENCE_SURFACES)
        self.assertEqual(unexpected, [], f"a #367 Hero EV module was imported: {unexpected}")
        # This consolidated suite itself never references a #367 / Hero EV surface.
        self.assertEqual(self._hero_ev_references_in_this_module(), [])
        admission = document["admission"]
        self.assertEqual(admission["consumption"], "FORBIDDEN")
        self.assertFalse(admission["abstention"]["hero_ev_consumed"])
        self.assertFalse(admission["abstention"]["promotion_performed"])
        self.assertFalse(self.decision["issue367"]["executed"])
        self.assertFalse(self.decision["issue367"]["authorized"])
        self.assertFalse(self.decision["issue367"]["hero_ev_executed"])
        self.assertEqual(self.decision["issue367"]["consumption"], "FORBIDDEN")
        self.assertFalse(self.decision["boundaries"]["issue367_executed"])
        self.assertFalse(self.decision["boundaries"]["hero_ev_executed"])
        self.assertEqual(self.n8n_result["issue367_preflight_passed"], False)
        self.assertEqual(self.decision["next_issue"], preflight_tool.SOURCE_ISSUE)
        self.assertEqual(self.decision["next_issue_status"], "NOT_EXECUTED")

    @staticmethod
    def _hero_ev_references_in_this_module() -> list[str]:
        """Forbidden Hero EV / rollout references in this suite's own source."""
        tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
        used: set[str] = set()
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                used.add(node.id)
            elif isinstance(node, ast.Attribute):
                used.add(node.attr)
            elif isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
                imported.extend(alias.name for alias in node.names)
        hits = sorted(used & set(preflight_tool.HERO_EV_FORBIDDEN_SYMBOLS))
        markers = tuple(preflight_tool.HERO_EV_FORBIDDEN_IMPORT_MARKERS)
        # The preflight module is this ticket's own evidence surface, not a runner.
        own = "tools.simulation.issue423_issue367_preflight"
        own_names = {own, own.rsplit(".", 1)[-1]}
        hits.extend(
            name
            for name in imported
            if name not in own_names and any(marker in name.lower() for marker in markers)
        )
        return sorted(set(hits))

    def test_the_issue421_validation_split_is_never_reread(self) -> None:
        self.assertIs(gen_runtime.VALIDATION_CONSUMED, False)
        self.assertFalse(self.runtime.audit()["validation_consumed"])
        split_policy = self.runtime.audit()["split_policy"]
        self.assertEqual(split_policy["consumed_splits"], ["TRAIN"])
        self.assertEqual(split_policy["allowed_splits"], ["TRAIN"])
        self.assertIn("VALIDATION", split_policy["refused_splits"])
        self.assertTrue(split_policy["fail_closed_on_refused_split"])
        self.assertEqual(cv.CONSUMED_SPLITS, ("TRAIN",))
        self.assertEqual(cv.MAIN_SPLIT, "TRAIN")
        self.assertIn("VALIDATION", cv.REFUSED_SPLITS)
        self.assertFalse(self.report["scope"]["validation_consumed"])
        self.assertEqual(self.report["scope"]["consumed_splits"], ["TRAIN"])
        self.assertTrue(self.report["guards"]["train_only"])
        self.assertFalse(self.report["guards"]["validation_consumed"])
        self.assertEqual(
            self.report["guards"]["no_holdout_access_scan"]["consumed_splits"], ["TRAIN"]
        )
        self.assertEqual(self.report["guards"]["no_holdout_access_scan"]["hits"], [])
        scope = self.calibration_report["scope"]
        self.assertFalse(scope["validation_consumed"])
        self.assertEqual(scope["recalibrated_splits"], ["TRAIN"])
        self.assertIn("VALIDATION", scope["refused_splits"])
        guards = self.calibration_report["guards"]
        self.assertFalse(guards["validation_recalibrated"])
        self.assertTrue(guards["validation_recalibration_refused"])
        self.assertTrue(guards["train_only"])
        self.assertFalse(guards["test_consumed"])
        boundaries = self.decision["boundaries"]
        self.assertFalse(boundaries["validation_consumed"])
        self.assertFalse(boundaries["validation_reopened"])
        self.assertEqual(boundaries["consumed_splits"], ["TRAIN"])
        self.assertFalse(self.preflight_document()["boundary"]["validation_split_consumed"])
        self.assertFalse(self.decision["calibration"]["validation_recalibrated"])
        self.assertEqual(self.decision["protocol_outcome"], self.decision["decision"])
        # Executable negative control: the harness refuses a VALIDATION request.
        with self.assertRaises(cv.HybridRouterCvError):
            cv.assert_consumed_splits(["VALIDATION"], context="contract guard")
        with self.assertRaises(cv.HybridRouterCvError):
            cv.assert_train_only([{"split": "VALIDATION"}], context="contract guard")
        with self.assertRaises(runtime.HybridResponseRuntimeError) as caught:
            runtime.guard_split({"split": "VALIDATION"})
        self.assertEqual(caught.exception.code, runtime.FAIL_CLOSED_REFUSED_SPLIT)
        self.assertEqual(preflight_tool.verify_no_holdout_access()["hits"], [])

    # -------------------------------------------------------- suite integrity
    def test_every_mandatory_item_has_exactly_one_named_test(self) -> None:
        ids = [item["id"] for item in MANDATORY_CONTRACT_ITEMS]
        mapped = [item["test"] for item in MANDATORY_CONTRACT_ITEMS]
        self.assertEqual(len(ids), len(set(ids)), "duplicate mandatory item id")
        self.assertEqual(len(mapped), len(set(mapped)), "two items map to one test")
        for item in MANDATORY_CONTRACT_ITEMS:
            with self.subTest(item=item["id"]):
                self.assertTrue(item["description"])
                method = getattr(self.__class__, item["test"], None)
                self.assertTrue(callable(method), f"{item['test']} is missing")
        declared = {name for name in dir(self.__class__) if name.startswith("test_")}
        self.assertEqual(
            declared - set(mapped),
            {"test_every_mandatory_item_has_exactly_one_named_test"},
            "a named test in this suite is not declared as a mandatory item",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

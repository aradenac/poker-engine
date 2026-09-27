#!/usr/bin/env python3
"""#423 T7 guard: hybrid runtime provider and its machine-readable provenance.

Covers every acceptance criterion of the task:

* every decision document carries the full frozen runtime contract -- the route
  source, the model id/hash, the support state, the uncertainty, the OOD status,
  the legal probabilities, the sizing provenance of a RAISE / JAM answer, the
  ``analysis_admissible`` flag and the reason codes;
* an out-of-domain context abstains fail-closed: no probabilities, no selected
  action, no sizing, ``analysis_admissible=false``;
* two executions of the same context emit byte-identical documents, and an
  offered ``TEST`` split is refused before a single signal is computed;
* the ``ACTIVE_STRONG_SUPPORT`` branch is answered only by an **exact-cell**
  lookup of the active Model A reference, and a request for a nearest-price /
  nearest-context substitution is refused with a stable code;
* the frozen spec, the frozen calibration report and the active reference are
  consumed by digest and refuse any drift.

The synthetic fold is the router's own resolution: the exact context signature
is the tuple of single-feature node labels, so the probes are chosen at that
resolution (the base cell repeated, a rare cell, a never-observed category and a
calibrated sizing axis).

``pytest`` is not a declared dependency of this repository; the suite is a plain
``unittest`` module, run with ``python3 -m unittest`` like its siblings.
"""
from __future__ import annotations

import ast
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.preflop import generalized_response_model as model  # noqa: E402
from tools.preflop import hybrid_response_router as router  # noqa: E402
from tools.preflop import hybrid_response_runtime as provider  # noqa: E402

MODULE_PATH = ROOT / "tools/preflop/hybrid_response_runtime.py"
SPEC_PATH = ROOT / "analysis/issue423_hybrid_router/HYBRID_ROUTER_SPEC.json"
DATASET_PATH = (
    ROOT / "analysis/issue421_generalized_response/dataset/GENERALIZED_RESPONSE_DATASET.jsonl"
)

ACTIVE_HASH = "a" * 64
CHANNEL_HASH = "b" * 64
LIVE = ["LJ", "HJ", "CO", "BTN", "SB", "BB"]
FREQUENT_REPEATS = 40
RARE_REPEATS = 3


def row(**overrides: object) -> dict:
    base = {
        "split": "TRAIN",
        "family": "VS_ISO",
        "actor_position": "HJ",
        "aggressor_position": "CO",
        "caller_count": 0,
        "limper_count": 0,
        "raise_level": 1,
        "table_size": 6,
        "live_positions": list(LIVE),
        "to_call_bb": 1.0,
        "pot_before_bb": 2.0,
        "effective_stack_bb": 30.0,
        "target_total_bb": None,
    }
    base.update(overrides)
    return base


def dataset() -> list[dict]:
    """A deterministic TRAIN fold with a designed support and sizing profile."""
    rows: list[dict] = []
    rows.extend(dict(row()) for _ in range(FREQUENT_REPEATS))
    rows.extend(dict(row(to_call_bb=7.0)) for _ in range(RARE_REPEATS))
    rows.extend(dict(row(pot_before_bb=6.5)) for _ in range(2))
    # Five raise rows so the calibrated sizing axis covers the ratios [0.4, 2.0]
    # the aggressive probes query (denominator pot + to_call = 3.0 bb).
    rows.extend(dict(row(target_total_bb=3.0 * ratio)) for ratio in (0.4, 0.8, 1.2, 1.6, 2.0))
    return rows


FREQUENT = row()
RARE = row(to_call_bb=7.0)
NOVEL_CATEGORY = row(family="NEVER_OBSERVED_FAMILY")


def active_reference(**context_overrides: object) -> dict:
    """A one-node synthetic active Model A reference (exact cell for HJ/VS_ISO)."""
    node_context = {
        "table_size": 6,
        "actor_position": "HJ",
        "family": "VS_ISO",
        "raise_level": 1,
        "live_positions": list(LIVE),
        "all_in_positions": [],
        "history": [],
        "free_check": False,
    }
    node_context.update(context_overrides)
    node = {
        "id": "NODE_HJ_EXACT",
        "canonical_key": "test|HJ|exact",
        "context": node_context,
        "coverage": {"population_decisions": FREQUENT_REPEATS},
        "population_model": {
            "legal_actions": ["FOLD", "CALL", "RAISE", "JAM"],
            "frequencies": {"FOLD": 0.6, "CALL": 0.3, "RAISE": 0.08, "JAM": 0.02},
        },
    }
    return {
        "path": "tests/preflop/active_reference.json",
        "sha256": ACTIVE_HASH,
        "model_id": provider.ACTIVE_MODEL_ID,
        "model_version": "synthetic-test-v1",
        "nodes": 1,
        "index": {"HJ": [node]},
        "grid": ["AA"],
        "weights": {"AA": 1.0},
    }


class StubGeneralizedRuntime:
    """A minimal stand-in for the calibrated channel's runtime handle."""

    def __init__(self, document: dict | None = None, error: Exception | None = None) -> None:
        # ``candidate=None`` keeps the router's gate on the frozen calibration
        # without a fitted candidate, which is enough for a routing-level guard.
        self.candidate = None
        self.candidate_sha256 = CHANNEL_HASH
        self.seed = 421
        self.document = document
        self.error = error
        self.calls = 0

    def resolve(self, context: dict) -> dict:  # noqa: ARG002 - frozen call shape
        self.calls += 1
        if self.error is not None:
            raise self.error
        return dict(self.document or {})


class HybridResponseRuntimeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.calibration = router.build_calibration(
            dataset(), thresholds={"domain_distance": 4.0}
        )
        cls.active = active_reference()
        cls.documents: dict[str, dict] = {}

    # -- helpers ------------------------------------------------------------

    def _provider(self, **overrides: object) -> provider.HybridResponseRuntime:
        kwargs: dict[str, object] = {
            "calibration": self.calibration,
            "active_reference": self.active,
        }
        kwargs.update(overrides)
        return provider.HybridResponseRuntime(**kwargs)  # type: ignore[arg-type]

    def _channel(self, probabilities: dict, **overrides: object) -> dict:
        payload = {
            "model_id": provider.GENERALIZED_MODEL_ID,
            "model_hash": CHANNEL_HASH,
            "probabilities": probabilities,
        }
        payload.update(overrides)
        return payload

    def _answered(self) -> dict:
        if "answered" not in self.documents:
            self.documents["answered"] = self._provider().resolve(dict(FREQUENT))
        return self.documents["answered"]

    # -- frozen spec --------------------------------------------------------

    def test_frozen_spec_is_consumed_and_pinned(self) -> None:
        spec, provenance = provider.load_spec()
        self.assertEqual(spec["schema"], provider.SPEC_SCHEMA)
        self.assertTrue(spec["frozen"])
        self.assertEqual(provenance["sha256"], provider.SPEC_SHA256)
        self.assertEqual(provenance["canonical_payload_sha256"], spec["canonical_payload_sha256"])
        self.assertEqual(provenance["route_sources"], list(router.ROUTE_SOURCES))
        self.assertEqual(
            list(provenance["required_fields"]), list(provider.CONTRACT_REQUIRED_FIELDS)
        )
        manifest = provenance["manifest"]
        self.assertTrue(manifest["entry_matches"])
        self.assertTrue(manifest["frozen_spec_matches"])
        self.assertTrue(manifest["digest_matches"])
        self.assertEqual(manifest["sha256"], provider.MANIFEST_SHA256)
        self.assertTrue(manifest["entry"]["role"])

    def test_declared_contract_surface_matches_the_module(self) -> None:
        spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))["runtime_contract"]
        self.assertEqual(spec["schema"], provider.CONTRACT_SCHEMA)
        self.assertEqual(list(spec["required_fields"]), list(provider.CONTRACT_REQUIRED_FIELDS))
        for condition, field in (
            ("route_source != OOD_ABSTAIN", "probabilities"),
            ("selected_action in {RAISE, JAM}", "sizing_provenance"),
        ):
            self.assertEqual(provider.CONTRACT_CONDITIONAL_REQUIREMENTS[field], condition)
        for key in provider.CONTRACT_REQUIRED_FIELDS:
            self.assertIn(key, provider.RUNTIME_DECISION_REQUIRED_KEYS)
        self.assertTrue(provider.NO_NEAREST_PRICE_SUBSTITUTION)
        self.assertTrue(provider.NO_NEAREST_CONTEXT_SUBSTITUTION)
        self.assertFalse(provider.NEAREST_PRICE_SUBSTITUTED)
        self.assertFalse(provider.NEAREST_CONTEXT_SUBSTITUTED)
        reasons = json.loads(SPEC_PATH.read_text(encoding="utf-8"))["reason_codes"]
        self.assertEqual(list(reasons["hard"]), list(model.OOD_HARD_REASONS))
        self.assertEqual(list(reasons["soft"]), list(model.OOD_SOFT_REASONS))

    def test_spec_bytes_are_the_pinned_identity_and_drift_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "HYBRID_ROUTER_SPEC.json"
            shutil.copyfile(SPEC_PATH, path)
            document, provenance = provider.load_spec(path)
            self.assertEqual(provenance["sha256"], provider.SPEC_SHA256)
            self.assertTrue(document["frozen"])
            # A single modified byte breaks the byte digest first.
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["status"] = payload["status"] + "_TAMPERED"
            path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            with self.assertRaises(provider.HybridResponseRuntimeError) as caught:
                provider.load_spec(path)
            self.assertEqual(caught.exception.code, provider.FAIL_CLOSED_SPEC_DRIFT)
            # A document whose declared surface disagrees with the runtime's own
            # declarations passes the digest but fails the contract.
            payload = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
            payload["route_sources"][0]["id"] = "NOT_A_ROUTE"
            path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            with self.assertRaises(provider.HybridResponseRuntimeError) as caught:
                provider.load_spec(path, expected_sha256=provider.sha256_file(path))
            self.assertEqual(caught.exception.code, provider.FAIL_CLOSED_CONTRACT_MISMATCH)
            # A structurally invalid document fails the shape checks.
            payload["schema"] = "not-the-frozen-schema"
            payload["issue"] = 421
            path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            with self.assertRaises(provider.HybridResponseRuntimeError) as caught:
                provider.load_spec(path, expected_sha256=provider.sha256_file(path))
            self.assertEqual(caught.exception.code, provider.FAIL_CLOSED_SPEC_INVALID)
            with self.assertRaises(provider.HybridResponseRuntimeError) as caught:
                provider.load_spec(Path(directory) / "absent.json")
            self.assertEqual(caught.exception.code, provider.FAIL_CLOSED_SPEC_UNAVAILABLE)

    # -- document contract --------------------------------------------------

    def test_decision_document_carries_the_frozen_contract(self) -> None:
        document = self._answered()
        for key in provider.RUNTIME_DECISION_REQUIRED_KEYS:
            self.assertIn(key, document, key)
        self.assertEqual(document["schema"], provider.HYBRID_RUNTIME_DECISION_SCHEMA)
        self.assertEqual(document["contract_schema"], provider.CONTRACT_SCHEMA)
        self.assertEqual(document["route_source"], router.ROUTE_SOURCE_ACTIVE)
        self.assertEqual(document["support_state"], router.SUPPORT_STATE_STRONG)
        self.assertEqual(document["ood_status"], model.STATUS_MODEL_SUPPORTED)
        self.assertEqual(document["uncertainty"], "NONE")
        self.assertEqual(document["model_id"], provider.ACTIVE_MODEL_ID)
        self.assertEqual(document["model_hash"], ACTIVE_HASH)
        self.assertTrue(document["analysis_admissible"])
        self.assertFalse(document["abstain"])
        self.assertFalse(document["fail_closed"])
        self.assertIsNone(document["fail_closed_reason"])
        self.assertEqual(document["probability_sum"], 1.0)
        self.assertEqual(document["illegal_mass"], 0.0)
        self.assertAlmostEqual(sum(document["probabilities"].values()), 1.0, places=12)
        self.assertEqual(document["selected_action"], "FOLD")
        self.assertIsNone(document["sizing_provenance"])
        # The contract fields required conditionally are present exactly when
        # the frozen contract requires them.
        self.assertIsNotNone(document["probabilities"])
        self.assertEqual(
            document["sizing_provenance"] is not None,
            document["selected_action"] in model.AGGRESSIVE_ACTIONS,
        )
        for key in ("hard", "soft", "all", "catalog", "runtime", "runtime_catalog", "abstaining"):
            self.assertIn(key, document["reason_codes"])
        self.assertEqual(document["reason_codes"]["runtime"], [])
        self.assertEqual(document["reason_codes"]["hard"], [])
        self.assertEqual(document["reason_codes"]["catalog"], {})
        self.assertEqual(
            document["routing_canonical_sha256"], document["routing"]["decision_canonical_sha256"]
        )

    def test_decision_document_is_byte_stable(self) -> None:
        document = self._answered()
        other = self._provider().resolve(dict(FREQUENT))
        self.assertEqual(provider.canonical_json(document), provider.canonical_json(other))
        reordered = {key: FREQUENT[key] for key in reversed(list(FREQUENT))}
        third = self._provider().resolve(reordered)
        self.assertEqual(provider.canonical_json(document), provider.canonical_json(third))
        payload = {
            key: value
            for key, value in document.items()
            if key != "decision_canonical_sha256"
        }
        self.assertEqual(
            document["decision_canonical_sha256"],
            provider.decision_canonical_sha256(document),
        )
        self.assertEqual(document["decision_canonical_sha256"], provider.canonical_sha256(payload))
        self.assertNotIn("NaN", provider.canonical_json(document))

    def test_abstention_is_fail_closed_without_action_or_sizing(self) -> None:
        document = self._provider().resolve(dict(NOVEL_CATEGORY))
        self.assertEqual(document["route_source"], router.ROUTE_SOURCE_ABSTAIN)
        self.assertEqual(document["support_state"], router.SUPPORT_STATE_ABSTAIN)
        self.assertEqual(document["ood_status"], model.STATUS_MODEL_OOD_ABSTAIN)
        self.assertEqual(document["status"], "OOD_ABSTAIN")
        self.assertTrue(document["abstain"])
        self.assertTrue(document["fail_closed"])
        self.assertEqual(document["fail_closed_reason"], "OOD_ABSTAIN")
        self.assertIsNone(document["probabilities"])
        self.assertIsNone(document["selected_action"])
        self.assertIsNone(document["sizing_provenance"])
        self.assertIsNone(document["selected_sizing_bb"])
        self.assertIsNone(document["probability_sum"])
        self.assertFalse(document["analysis_admissible"])
        self.assertEqual(document["model_id"], provider.NO_MODEL_ID)
        self.assertIsNone(document["model_hash"])
        self.assertIn("UNSEEN_CATEGORY", document["reason_codes"]["hard"])
        self.assertIn("UNSEEN_CATEGORY", document["reason_codes"]["all"])
        self.assertEqual(document["reason_codes"]["catalog"]["UNSEEN_CATEGORY"], "hard")
        self.assertEqual(
            provider.canonical_json(document),
            provider.canonical_json(self._provider().resolve(dict(NOVEL_CATEGORY))),
        )

    def test_refused_splits_are_rejected_before_any_decision(self) -> None:
        calls: list[dict] = []
        handle = self._provider(
            channels={
                router.ROUTE_SOURCE_ACTIVE: lambda context: calls.append(dict(context))
                or self._channel({"FOLD": 1.0})
            }
        )
        with self.assertRaises(provider.HybridResponseRuntimeError) as caught:
            handle.resolve(dict(FREQUENT, split="TEST"))
        self.assertEqual(caught.exception.code, provider.FAIL_CLOSED_TEST_SPLIT)
        self.assertEqual(calls, [])
        with self.assertRaises(provider.HybridResponseRuntimeError) as caught:
            handle.resolve(dict(FREQUENT, split="VALIDATION"))
        self.assertEqual(caught.exception.code, provider.FAIL_CLOSED_REFUSED_SPLIT)
        self.assertEqual(calls, [])
        # TRAIN is the one consumed split and is answered normally.
        self.assertEqual(handle.resolve(dict(FREQUENT, split="TRAIN"))["route_source"],
                         router.ROUTE_SOURCE_ACTIVE)

    def test_nearest_substitution_request_is_refused(self) -> None:
        calls: list[dict] = []
        handle = self._provider(
            channels={
                router.ROUTE_SOURCE_ACTIVE: lambda context: calls.append(dict(context))
                or self._channel({"FOLD": 1.0})
            }
        )
        for flag in (
            "allow_nearest_price",
            "allow_nearest_context",
            "allow_nearest_neighbour",
            "allow_nearest",
            "nearest_price_substituted",
            "nearest_context_substituted",
        ):
            with self.assertRaises(provider.HybridResponseRuntimeError) as caught:
                handle.resolve(dict(FREQUENT, **{flag: True}))
            self.assertEqual(
                caught.exception.code, provider.FAIL_CLOSED_NEIGHBOUR_SUBSTITUTION
            )
            self.assertIsInstance(caught.exception, provider.NeighbourSubstitutionRefused)
        self.assertEqual(calls, [])

    # -- channel contract ---------------------------------------------------

    def test_illegal_actions_are_masked_before_normalization(self) -> None:
        # The engine's legal space is the masking surface; an explicit
        # ``legal_actions`` list is authoritative and CALL is not legal here.
        context = dict(FREQUENT, legal_actions=["FOLD", "RAISE", "JAM"])
        legal = router.legal_response_actions(context)
        self.assertNotIn("CALL", legal)
        handle = self._provider(
            channels={
                router.ROUTE_SOURCE_ACTIVE: lambda _context: self._channel(
                    {"FOLD": 0.5, "CALL": 0.5}
                )
            }
        )
        document = handle.resolve(context)
        self.assertEqual(document["route_source"], router.ROUTE_SOURCE_ACTIVE)
        self.assertEqual(document["probabilities"]["CALL"], 0.0)
        self.assertEqual(document["probabilities"]["FOLD"], 1.0)
        self.assertEqual(document["probability_sum"], 1.0)
        self.assertEqual(document["illegal_mass"], 0.0)
        self.assertIn("CALL", document["masked_actions"])
        self.assertEqual(document["legal_actions"], legal)
        self.assertEqual(document["selected_action"], "FOLD")

    def test_channel_without_legal_mass_fails_closed(self) -> None:
        context = dict(FREQUENT, legal_actions=["FOLD"])
        handle = self._provider(
            channels={
                router.ROUTE_SOURCE_ACTIVE: lambda _context: self._channel({"CALL": 1.0})
            }
        )
        document = handle.resolve(context)
        self.assertEqual(document["route_source"], router.ROUTE_SOURCE_ABSTAIN)
        self.assertEqual(document["routed_source"], router.ROUTE_SOURCE_ACTIVE)
        self.assertEqual(
            document["fail_closed_reason"], router.FAIL_CLOSED_NO_LEGAL_MASS
        )
        self.assertIsNone(document["probabilities"])
        self.assertFalse(document["analysis_admissible"])
        with self.assertRaises(provider.HybridResponseRuntimeError):
            handle.resolve(context, strict=True)

    def test_channel_error_never_emits_a_distribution(self) -> None:
        handle = self._provider(
            channels={
                router.ROUTE_SOURCE_ACTIVE: lambda _context: self._channel(
                    {"FOLD": 1.0}, model_hash="not-a-digest"
                )
            }
        )
        document = handle.resolve(dict(FREQUENT))
        self.assertEqual(document["route_source"], router.ROUTE_SOURCE_ABSTAIN)
        self.assertEqual(document["fail_closed_reason"], router.FAIL_CLOSED_INVALID_MODEL_HASH)
        self.assertIsNone(document["probabilities"])

    def test_calibrated_channel_abstention_downgrades_to_an_abstention(self) -> None:
        stub = StubGeneralizedRuntime(
            document={"usable": False, "ood": {"status": model.STATUS_MODEL_OOD_ABSTAIN}}
        )
        handle = self._provider(generalized_runtime=stub)
        document = handle.resolve(dict(RARE))
        self.assertEqual(document["route_source"], router.ROUTE_SOURCE_ABSTAIN)
        self.assertEqual(document["routed_source"], router.ROUTE_SOURCE_SPARSE)
        self.assertEqual(
            document["fail_closed_reason"], provider.FAIL_CLOSED_CHANNEL_ABSTAINED
        )
        self.assertEqual(
            document["reason_codes"]["runtime"], [provider.FAIL_CLOSED_CHANNEL_ABSTAINED]
        )
        self.assertIn(
            provider.FAIL_CLOSED_CHANNEL_ABSTAINED, document["reason_codes"]["runtime_catalog"]
        )
        self.assertIsNone(document["probabilities"])
        self.assertFalse(document["analysis_admissible"])
        self.assertEqual(stub.calls, 1)

    # -- aggressive answers and sizing provenance ---------------------------

    def test_aggressive_answer_carries_the_sizing_provenance(self) -> None:
        context = dict(
            FREQUENT, target_total_bb=3.5, min_raise_to_bb=2.0, max_raise_to_bb=4.0
        )
        handle = self._provider(
            channels={
                router.ROUTE_SOURCE_ACTIVE: lambda _context: self._channel(
                    {"FOLD": 0.05, "CALL": 0.05, "RAISE": 0.8, "JAM": 0.1}
                )
            }
        )
        document = handle.resolve(context)
        self.assertEqual(document["selected_action"], "RAISE")
        self.assertTrue(document["analysis_admissible"])
        sizing = document["sizing_provenance"]
        self.assertIsNotNone(sizing)
        self.assertEqual(sizing["schema"], provider.SIZING_PROVENANCE_SCHEMA)
        self.assertEqual(sizing["action"], "RAISE")
        self.assertEqual(sizing["route_source"], router.ROUTE_SOURCE_ACTIVE)
        self.assertEqual(sizing["probability_model_id"], provider.GENERALIZED_MODEL_ID)
        self.assertEqual(sizing["probability_model_hash"], CHANNEL_HASH)
        self.assertEqual(sizing["sizing_model_id"], provider.GENERALIZED_MODEL_ID)
        self.assertTrue(provider._is_sha256(sizing["sizing_model_hash"]))
        self.assertEqual(sizing["sizing_channel"], provider.SIZING_CHANNEL_ID)
        self.assertTrue(sizing["queried"])
        self.assertEqual(sizing["target_total_bb"], 3.5)
        self.assertEqual(sizing["queried_target_total_bb"], 3.5)
        self.assertEqual(sizing["conditioning_target_source"], "QUERIED_EXACT")
        self.assertTrue(sizing["inside_legal_window"])
        self.assertIsNone(sizing["violation"])
        self.assertTrue(sizing["no_nearest_price_substitution"])
        self.assertFalse(sizing["nearest_price_substituted"])
        self.assertFalse(sizing["nearest_context_substituted"])
        self.assertIsInstance(sizing["exact_cell"], dict)

    def test_aggressive_answer_without_a_target_fails_closed(self) -> None:
        # No queried target and no resolvable conditional sizing: the frozen
        # router refuses to accept an aggressive answer without a conditioning
        # target, and the provider abstains instead of inventing one.
        handle = self._provider(
            channels={
                router.ROUTE_SOURCE_ACTIVE: lambda _context: self._channel({"RAISE": 1.0})
            }
        )
        document = handle.resolve(dict(FREQUENT))
        self.assertEqual(document["route_source"], router.ROUTE_SOURCE_ABSTAIN)
        self.assertIn(
            document["fail_closed_reason"],
            (router.FAIL_CLOSED_MISSING_SIZING, provider.FAIL_CLOSED_ILLEGAL_SIZING_TARGET),
        )
        self.assertIsNone(document["probabilities"])
        self.assertIsNone(document["sizing_provenance"])

    def test_queried_target_must_be_the_exact_one(self) -> None:
        context = dict(
            FREQUENT, target_total_bb=1.5, min_raise_to_bb=1.0, max_raise_to_bb=4.0
        )
        handle = self._provider(
            channels={
                router.ROUTE_SOURCE_ACTIVE: lambda _context: self._channel(
                    {"RAISE": 1.0},
                    sizing_provenance={
                        "target_total_bb": 3.0,  # a neighbouring price
                        "no_nearest_price_substitution": True,
                    },
                )
            }
        )
        document = handle.resolve(context)
        self.assertEqual(document["route_source"], router.ROUTE_SOURCE_ABSTAIN)
        self.assertEqual(document["fail_closed_reason"], router.FAIL_CLOSED_SIZING_TARGET)
        self.assertIsNone(document["probabilities"])
        self.assertIsNone(document["sizing_provenance"])

    def test_illegal_queried_target_abstains_fail_closed(self) -> None:
        inside = dict(
            FREQUENT, target_total_bb=3.5, min_raise_to_bb=2.0, max_raise_to_bb=4.0
        )
        outside = dict(inside, target_total_bb=4.5)
        handle = self._provider(
            channels={
                router.ROUTE_SOURCE_ACTIVE: lambda _context: self._channel(
                    {"FOLD": 0.1, "CALL": 0.1, "RAISE": 0.8}
                )
            }
        )
        answered = handle.resolve(inside)
        self.assertEqual(answered["selected_action"], "RAISE")
        self.assertTrue(answered["analysis_admissible"])
        self.assertTrue(answered["sizing_provenance"]["inside_legal_window"])
        self.assertEqual(answered["sizing_provenance"]["target_total_bb"], 3.5)
        refused = handle.resolve(outside)
        self.assertEqual(refused["route_source"], router.ROUTE_SOURCE_ABSTAIN)
        self.assertEqual(
            refused["fail_closed_reason"], provider.FAIL_CLOSED_ILLEGAL_SIZING_TARGET
        )
        self.assertEqual(
            refused["reason_codes"]["runtime"], [provider.FAIL_CLOSED_ILLEGAL_SIZING_TARGET]
        )
        self.assertIsNone(refused["probabilities"])
        self.assertIsNone(refused["selected_action"])
        self.assertIsNone(refused["sizing_provenance"])
        with self.assertRaises(provider.HybridResponseRuntimeError) as caught:
            handle.resolve(outside, strict=True)
        self.assertEqual(caught.exception.code, provider.FAIL_CLOSED_ILLEGAL_SIZING_TARGET)

    # -- the active exact-cell branch ---------------------------------------

    def test_active_branch_answers_from_the_exact_active_cell(self) -> None:
        document = self._answered()
        self.assertEqual(document["route_source"], router.ROUTE_SOURCE_ACTIVE)
        self.assertEqual(document["channel"]["channel"], provider.ACTIVE_CHANNEL_NAME)
        cell = document["channel"]["cell"]
        self.assertEqual(cell["node_id"], "NODE_HJ_EXACT")
        self.assertTrue(cell["exact"])
        self.assertEqual(cell["support"], FREQUENT_REPEATS)
        self.assertEqual(cell["probability_model_hash"], ACTIVE_HASH)
        self.assertEqual(document["routed_source"], router.ROUTE_SOURCE_ACTIVE)

    def test_active_branch_refuses_when_the_exact_cell_is_absent(self) -> None:
        # The router still sees the same calibration key (table_size is not one
        # of the gate's labels) while the active reference has no exact node for
        # it: the provider must abstain instead of reading a neighbour.
        context = dict(FREQUENT, table_size=9)
        reference = self.active
        self.assertIsNone(provider.active_exact_cell(reference, context))
        self.assertEqual(
            router.exact_context_key(context), router.exact_context_key(FREQUENT)
        )
        document = self._provider().resolve(context)
        self.assertEqual(document["routed_source"], router.ROUTE_SOURCE_ACTIVE)
        self.assertEqual(document["route_source"], router.ROUTE_SOURCE_ABSTAIN)
        self.assertEqual(
            document["fail_closed_reason"], provider.FAIL_CLOSED_ACTIVE_CELL_UNAVAILABLE
        )
        self.assertEqual(
            document["reason_codes"]["runtime"],
            [provider.FAIL_CLOSED_ACTIVE_CELL_UNAVAILABLE],
        )
        self.assertIsNone(document["probabilities"])
        self.assertIsNone(document["selected_action"])
        self.assertFalse(document["analysis_admissible"])
        with self.assertRaises(provider.HybridResponseRuntimeError) as caught:
            self._provider().resolve(context, strict=True)
        self.assertEqual(
            caught.exception.code, provider.FAIL_CLOSED_ACTIVE_CELL_UNAVAILABLE
        )

    def test_active_exact_cell_never_returns_a_neighbour(self) -> None:
        reference = self.active
        self.assertIsNotNone(provider.active_exact_cell(reference, dict(FREQUENT)))
        for near in (
            dict(FREQUENT, table_size=9),
            dict(FREQUENT, live_positions=list(reversed(LIVE))),
            dict(FREQUENT, raise_level=2),
            dict(FREQUENT, family="VS_RFI"),
            dict(FREQUENT, actor_position="CO"),
        ):
            self.assertIsNone(provider.active_exact_cell(reference, near), near)
        # A duplicate exact cell resolves to the most supported node, never to
        # an arbitrary neighbour.
        bigger = json.loads(json.dumps(reference))
        clone = json.loads(json.dumps(bigger["index"]["HJ"][0]))
        clone["id"] = "NODE_HJ_EXACT_LOW"
        clone["coverage"]["population_decisions"] = 1
        bigger["index"]["HJ"].insert(0, clone)
        cell = provider.active_exact_cell(bigger, dict(FREQUENT))
        self.assertEqual(cell["id"], "NODE_HJ_EXACT")

    # -- static guarantees --------------------------------------------------

    def test_module_never_imports_a_nearest_match_or_a_holdout_loader(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
        for forbidden in (
            "find_closest",
            "continuous_penalty",
            "history_match_score",
            "set_similarity_score",
            "read_train_rows",
            "read_dataset_rows",
            "restore_folder",
        ):
            self.assertNotIn(forbidden, names, forbidden)
        self.assertTrue(provider.NO_NEAREST_PRICE_SUBSTITUTION)
        self.assertIn("runtime_exact", names)
        self.assertIn("no_nearest_price_substitution", source)

    def test_provider_metadata_and_audit(self) -> None:
        handle = self._provider()
        metadata = handle.metadata()
        self.assertEqual(metadata["schema"], provider.HYBRID_RUNTIME_PROVIDER_SCHEMA)
        self.assertEqual(metadata["decision_schema"], provider.HYBRID_RUNTIME_DECISION_SCHEMA)
        self.assertEqual(metadata["contract_schema"], provider.CONTRACT_SCHEMA)
        self.assertEqual(metadata["route_sources"], list(router.ROUTE_SOURCES))
        self.assertEqual(metadata["spec"]["sha256"], provider.SPEC_SHA256)
        self.assertEqual(
            metadata["generalized_calibration_report"]["sha256"],
            provider.CALIBRATION_REPORT_SHA256,
        )
        self.assertEqual(metadata["active_reference"]["sha256"], ACTIVE_HASH)
        self.assertEqual(
            metadata["active_reference"]["exact_context_fields"],
            list(provider.ACTIVE_EXACT_CONTEXT_FIELDS),
        )
        self.assertEqual(
            metadata["active_reference"]["lookup"],
            "exact_cell_only_never_the_nearest_node",
        )
        self.assertTrue(metadata["guarantees"]["no_nearest_price_substitution"])
        self.assertTrue(metadata["guarantees"]["byte_stable"])
        audit = handle.audit()
        self.assertFalse(audit["nearest_price_substituted"])
        self.assertFalse(audit["nearest_context_substituted"])
        self.assertTrue(audit["active_reference_exact_cell_only"])
        self.assertFalse(audit["test_consumed"])
        self.assertFalse(audit["validation_consumed"])
        self.assertIs(handle.metadata(), metadata)

    def test_calibration_report_drift_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "GENERALIZED_CALIBRATION_REPORT.json"
            shutil.copyfile(provider.CALIBRATION_REPORT_PATH, path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["retained_method"] = "not-the-frozen-method"
            path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            with self.assertRaises(provider.HybridResponseRuntimeError) as caught:
                self._provider(calibration_report_path=path)
            self.assertEqual(caught.exception.code, provider.FAIL_CLOSED_CALIBRATION_DRIFT)

    # -- integration over the real frozen artifacts -------------------------

    @unittest.skipUnless(DATASET_PATH.exists(), "the frozen #421 dataset is absent")
    def test_real_frozen_artifacts_end_to_end(self) -> None:
        handle = provider.HybridResponseRuntime(include_sizing=True)
        keys = (
            "family",
            "actor_position",
            "aggressor_position",
            "caller_count",
            "limper_count",
            "raise_level",
            "to_call_bb",
            "pot_before_bb",
            "effective_stack_bb",
            "target_total_bb",
            "table_size",
            "live_positions",
        )
        answered: dict | None = None
        refused: dict | None = None
        with DATASET_PATH.open(encoding="utf-8") as stream:
            for index, line in enumerate(stream):
                if index > 4000 or (answered is not None and refused is not None):
                    break
                row = json.loads(line)
                if row.get("split") != "TRAIN":
                    continue
                context = {key: row.get(key) for key in keys}
                document = handle.resolve(context)
                if document["routed_source"] != router.ROUTE_SOURCE_ACTIVE:
                    continue
                if document["route_source"] == router.ROUTE_SOURCE_ACTIVE and answered is None:
                    answered = document
                elif document["fail_closed_reason"] == provider.FAIL_CLOSED_ACTIVE_CELL_UNAVAILABLE:
                    refused = document
        if answered is not None:
            self.assertEqual(answered["model_id"], provider.ACTIVE_MODEL_ID)
            self.assertEqual(answered["model_hash"], provider.ACTIVE_MODEL_SHA256)
            self.assertTrue(answered["channel"]["cell"]["exact"])
            self.assertTrue(answered["channel"]["cell"]["node_id"])
            self.assertTrue(answered["analysis_admissible"])
            for key in provider.RUNTIME_DECISION_REQUIRED_KEYS:
                self.assertIn(key, answered, key)
        if refused is not None:
            self.assertEqual(refused["route_source"], router.ROUTE_SOURCE_ABSTAIN)
            self.assertIsNone(refused["probabilities"])
            self.assertIsNone(refused["sizing_provenance"])
            self.assertFalse(refused["analysis_admissible"])

    @unittest.skipUnless(DATASET_PATH.exists(), "the frozen #421 dataset is absent")
    def test_real_aggressive_answer_carries_the_sizing_provenance(self) -> None:
        handle = provider.HybridResponseRuntime(include_sizing=True)
        keys = (
            "family",
            "actor_position",
            "aggressor_position",
            "caller_count",
            "limper_count",
            "raise_level",
            "to_call_bb",
            "pot_before_bb",
            "effective_stack_bb",
            "target_total_bb",
            "table_size",
            "live_positions",
        )
        found: dict | None = None
        found_context: dict | None = None
        with DATASET_PATH.open(encoding="utf-8") as stream:
            for index, line in enumerate(stream):
                if index > 12000 or found is not None:
                    break
                row = json.loads(line)
                if row.get("split") != "TRAIN" or not row.get("target_total_bb"):
                    continue
                context = {key: row.get(key) for key in keys}
                document = handle.resolve(context)
                if document["selected_action"] in model.AGGRESSIVE_ACTIONS:
                    found = document
                    found_context = context
        if found is None:
            self.skipTest("no aggressive decision in the scanned slice of the frozen dataset")
        self.assertIsNotNone(found_context)  # set together with ``found``
        sizing = found["sizing_provenance"]
        self.assertIsNotNone(sizing)
        self.assertTrue(sizing["no_nearest_price_substitution"])
        self.assertTrue(provider._is_sha256(sizing["sizing_model_hash"]))
        self.assertEqual(sizing["target_total_bb"], found_context["target_total_bb"])
        self.assertEqual(
            provider.canonical_json(found),
            provider.canonical_json(handle.resolve(dict(found_context))),
        )


if __name__ == "__main__":
    unittest.main()

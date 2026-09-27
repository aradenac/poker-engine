#!/usr/bin/env python3
"""Acceptance tests for the fail-closed #425 -> #344 contract bridge.

Covers the ``backlog-uso`` acceptance points:

* a schema mismatch raises an explicit ``ValueError`` with reason code
  ``SCHEMA_MISMATCH`` (fail-closed);
* a missing provenance / support block raises ``MISSING_PROVENANCE`` /
  ``MISSING_SUPPORT``;
* the projection is accepted by ``harness.validate_request`` and carries none
  of the ``FORBIDDEN_MODEL_FEATURES`` keys;
* EV, uncertainty, paired delta, route/source and posterior references never
  reach the projected request;
* the #344 harness and its tests are untouched (guarded by the module import
  itself and by reading the harness source below);
* non-finite numbers are refused instead of being projected.

Run it with::

    PYTHONPATH=. python3 tests/simulation/test_model_b_hero_robustness_contract.py
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.simulation import model_b_hero_robustness_contract as contract  # noqa: E402
from tools.simulation import model_b_preflop_sensitivity_harness as harness  # noqa: E402

FIXTURES = ROOT / "tests/fixtures/model_b_hero_robustness"
CONTEXT_PATH = (
    ROOT / "tests/fixtures/model_b_preflop_sensitivity/synthetic_sb_two_limpers_context.json"
)
HARNESS_PATH = ROOT / "tools/simulation/model_b_preflop_sensitivity_harness.py"
HARNESS_REQUEST_SCHEMA_PATH = (
    ROOT / "contracts/training/model-b-preflop-sensitivity-harness-request.schema.json"
)
VALID_FIXTURES = (
    "robust_consistent.json",
    "multi_sizing.json",
    "too_close.json",
    "sparse_high_uncertainty.json",
    "ood_unsupported.json",
)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def context() -> dict:
    return load_json(CONTEXT_PATH)


def all_keys(value) -> set:
    keys = set()
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(key)
            keys |= all_keys(child)
    elif isinstance(value, list):
        for child in value:
            keys |= all_keys(child)
    return keys


class RobustnessContractTest(unittest.TestCase):
    def test_valid_fixtures_load_and_validate(self) -> None:
        for name in VALID_FIXTURES:
            document = contract.load_robustness_input(FIXTURES / name)
            self.assertEqual(document["schema"], contract.INPUT_SCHEMA)
            self.assertIs(contract.validate_robustness_input(document), document)

    def test_schema_mismatch_fails_closed(self) -> None:
        with self.assertRaises(ValueError) as raised:
            contract.load_robustness_input(FIXTURES / "schema_mismatch.json")
        error = raised.exception
        self.assertIsInstance(error, contract.RobustnessContractError)
        self.assertEqual(error.reason_code, "SCHEMA_MISMATCH")
        self.assertIn("hero-model-b-robustness-input/v1", str(error))
        self.assertIn("SCHEMA_MISMATCH", error.reason_codes)

    def test_missing_provenance_is_explicit(self) -> None:
        document = load_json(FIXTURES / "robust_consistent.json")
        for mutate in (
            lambda doc: doc.pop("provenance"),
            lambda doc: doc.__setitem__("provenance", None),
            lambda doc: doc["provenance"].pop("validation_consumed"),
            lambda doc: doc["provenance"].__setitem__("synthetic_fixture", False),
            lambda doc: doc["provenance"].__setitem__("test_consumed", True),
        ):
            bad = copy.deepcopy(document)
            mutate(bad)
            with self.assertRaises(ValueError) as raised:
                contract.validate_robustness_input(bad)
            self.assertEqual(raised.exception.reason_code, "MISSING_PROVENANCE")

    def test_missing_or_invalid_support_is_explicit(self) -> None:
        document = load_json(FIXTURES / "robust_consistent.json")
        for mutate in (
            lambda doc: doc["hero_entry"].pop("support"),
            lambda doc: doc["hero_entry"].__setitem__("support", None),
            lambda doc: doc["hero_entry"]["alternatives"][0].pop("support"),
            lambda doc: doc["hero_entry"]["alternatives"][0].__setitem__("support", None),
        ):
            bad = copy.deepcopy(document)
            mutate(bad)
            with self.assertRaises(ValueError) as raised:
                contract.validate_robustness_input(bad)
            self.assertEqual(raised.exception.reason_code, "MISSING_SUPPORT")

        bad = copy.deepcopy(document)
        bad["hero_entry"]["support"]["status"] = "UNKNOWN"
        with self.assertRaises(contract.RobustnessContractError) as raised:
            contract.validate_robustness_input(bad)
        self.assertEqual(raised.exception.reason_code, "SUPPORT_INVALID")

    def test_unknown_and_forbidden_fields_fail_closed(self) -> None:
        document = load_json(FIXTURES / "robust_consistent.json")
        bad = copy.deepcopy(document)
        bad["unknown_field"] = 1
        with self.assertRaises(contract.RobustnessContractError) as raised:
            contract.validate_robustness_input(bad)
        self.assertEqual(raised.exception.reason_code, "UNKNOWN_FIELD")

        bad = copy.deepcopy(document)
        bad["hero_entry"]["hero_ev"] = 0.0
        with self.assertRaises(contract.RobustnessContractError) as raised:
            contract.validate_robustness_input(bad)
        self.assertEqual(raised.exception.reason_code, "FORBIDDEN_FEATURE")

    def test_information_boundary_must_be_entirely_false(self) -> None:
        document = load_json(FIXTURES / "robust_consistent.json")
        for mutate in (
            lambda doc: doc.pop("information_boundary"),
            lambda doc: doc["information_boundary"].pop("model_a_consumed"),
            lambda doc: doc["information_boundary"].__setitem__("hero_ev_consumed", True),
        ):
            bad = copy.deepcopy(document)
            mutate(bad)
            with self.assertRaises(contract.RobustnessContractError) as raised:
                contract.validate_robustness_input(bad)
            self.assertEqual(
                raised.exception.reason_code, "INFORMATION_BOUNDARY_VIOLATION"
            )

    def test_nan_is_refused_end_to_end(self) -> None:
        document = load_json(FIXTURES / "robust_consistent.json")
        document["hero_entry"]["ev"] = float("nan")
        with self.assertRaises(contract.RobustnessContractError) as raised:
            contract.validate_robustness_input(document)
        self.assertEqual(raised.exception.reason_code, "NON_FINITE_NUMBER")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nan.json"
            path.write_text(
                '{"schema": "hero-model-b-robustness-input/v1", "ev": NaN}',
                encoding="utf-8",
            )
            with self.assertRaises(contract.RobustnessContractError) as raised:
                contract.load_robustness_input(path)
            self.assertEqual(raised.exception.reason_code, "NON_FINITE_NUMBER")

    def test_contract_id_is_verified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "schema.json"
            fake.write_text('{"$id": "some-other-contract/v1"}', encoding="utf-8")
            with self.assertRaises(contract.RobustnessContractError) as raised:
                contract.validate_robustness_input(
                    load_json(FIXTURES / "robust_consistent.json"),
                    contract_path=fake,
                )
            self.assertEqual(raised.exception.reason_code, "CONTRACT_ID_MISMATCH")

    def test_projection_is_accepted_by_harness(self) -> None:
        public = context()
        for name in VALID_FIXTURES:
            document = contract.load_robustness_input(FIXTURES / name)
            request = contract.project_to_harness_request(document, public)
            harness.validate_request(request)
            contract.validate_projected_request(request)

            self.assertEqual(
                request["schema"], "model-b-preflop-sensitivity-harness-request/v1"
            )
            self.assertEqual(request["source_kind"], "SYNTHETIC_HARNESS_ONLY")
            self.assertIs(request["synthetic_fixture"], True)
            self.assertEqual(
                request["decision_ref"]["canonical_schema"],
                "poker-preflop-decision/v1",
            )
            self.assertEqual(
                request["decision_ref"]["context_id"],
                document["hero_entry"]["context_id"],
            )
            for flag, value in request["information_boundary"].items():
                self.assertIs(value, False, flag)
            self.assertEqual(contract.check_forbidden_features(request), [])

            self.assertEqual(
                [a["alternative_id"] for a in request["alternatives"]],
                [a["alternative_id"] for a in document["hero_entry"]["alternatives"]],
            )
            for alternative, source in zip(
                request["alternatives"], document["hero_entry"]["alternatives"]
            ):
                self.assertEqual(
                    tuple(alternative),
                    ("alternative_id", "action", "target_total_bb", "incremental_cost_bb"),
                )
                if alternative["action"] == "FOLD":
                    self.assertIsNone(alternative["target_total_bb"])
                    self.assertEqual(alternative["incremental_cost_bb"], 0.0)
                else:
                    self.assertEqual(
                        alternative["target_total_bb"], float(source["sizing"])
                    )
                    self.assertAlmostEqual(
                        alternative["incremental_cost_bb"],
                        alternative["target_total_bb"]
                        - public["hero_contribution_before_bb"],
                    )

    def test_projection_drops_ev_uncertainty_route_and_support(self) -> None:
        request = contract.project_to_harness_request(
            contract.load_robustness_input(FIXTURES / "multi_sizing.json"),
            context=context(),
        )
        keys = all_keys(request)
        for leaked_key in (
            "ev_bb",
            "uncertainty",
            "paired_delta",
            "route_source",
            "posterior_refs",
            "support",
            "sizing",
            "route",
            "source",
        ):
            self.assertNotIn(leaked_key, keys, leaked_key)
        self.assertFalse(set(harness.FORBIDDEN_MODEL_FEATURES) & keys)

    def test_projection_satisfies_the_shipped_344_schema(self) -> None:
        schema = load_json(HARNESS_REQUEST_SCHEMA_PATH)
        # The #344 reference contract still accepts exactly one source kind: the
        # #425 projection never adds a second, robustness-specific one.
        self.assertEqual(
            schema["properties"]["source_kind"], {"const": "SYNTHETIC_HARNESS_ONLY"}
        )
        try:
            import jsonschema  # type: ignore
        except ImportError:  # pragma: no cover - jsonschema is not a locked dependency
            self.skipTest("jsonschema absent; harness.validate_request already ran")
        validator = jsonschema.Draft202012Validator(schema)
        public = context()
        for name in VALID_FIXTURES:
            with self.subTest(fixture=name):
                document = contract.load_robustness_input(FIXTURES / name)
                request = contract.project_to_harness_request(document, public)
                self.assertEqual(request["source_kind"], "SYNTHETIC_HARNESS_ONLY")
                errors = sorted(
                    validator.iter_errors(request), key=lambda e: list(e.path)
                )
                self.assertEqual([error.message for error in errors], [], name)

    def test_projection_refuses_forbidden_context_and_input_leaks(self) -> None:
        document = contract.load_robustness_input(FIXTURES / "robust_consistent.json")

        leaked_input = copy.deepcopy(document)
        leaked_input["hero_entry"]["alternatives"][0]["route"] = "leaked_route"
        with self.assertRaises(contract.RobustnessContractError) as raised:
            contract.project_to_harness_request(leaked_input, context())
        self.assertEqual(raised.exception.reason_code, "FORBIDDEN_FEATURE")

        leaked_context = context()
        leaked_context["uncertainty"] = {"ci95": [0.0, 0.0]}
        with self.assertRaises(contract.RobustnessContractError) as raised:
            contract.project_to_harness_request(document, leaked_context)
        self.assertEqual(raised.exception.reason_code, "FORBIDDEN_FEATURE")

    def test_projection_refuses_non_synthetic_context_and_position_mismatch(self) -> None:
        document = contract.load_robustness_input(FIXTURES / "robust_consistent.json")
        bad_context = context()
        bad_context["synthetic_fixture"] = False
        with self.assertRaises(contract.RobustnessContractError) as raised:
            contract.project_to_harness_request(document, bad_context)
        self.assertEqual(raised.exception.reason_code, "CONTEXT_INVALID")

        bad_context = context()
        bad_context["hero_position"] = "BTN"
        with self.assertRaises(contract.RobustnessContractError) as raised:
            contract.project_to_harness_request(document, bad_context)
        self.assertEqual(raised.exception.reason_code, "CONTEXT_INVALID")

    def test_harness_module_is_not_modified(self) -> None:
        source = HARNESS_PATH.read_text(encoding="utf-8")
        self.assertIn("FORBIDDEN_MODEL_FEATURES", source)
        self.assertIn("def validate_request", source)
        self.assertNotIn("model_b_hero_robustness_contract", source)
        self.assertIs(
            contract.FORBIDDEN_MODEL_FEATURES, harness.FORBIDDEN_MODEL_FEATURES
        )

    def test_compatibility_aliases_target_the_same_implementation(self) -> None:
        self.assertIs(contract.validate_input, contract.validate_robustness_input)
        self.assertIs(contract.load_input, contract.load_robustness_input)
        self.assertIs(contract.load_and_validate, contract.load_robustness_input)
        self.assertIs(contract.project_request, contract.project_to_harness_request)


if __name__ == "__main__":
    unittest.main()

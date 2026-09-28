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
from tools.simulation import model_b_hero_robustness_classify as classifier  # noqa: E402
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

    def test_non_string_support_status_fails_closed_without_type_error(self) -> None:
        document = load_json(FIXTURES / "robust_consistent.json")
        # A non-hashable status (list/dict) must fail closed as SUPPORT_INVALID,
        # never escape as an uncaught TypeError from the membership test.
        for bad_status in ([], ["CONSISTENT"], {}, {"value": "CONSISTENT"}, 1, None):
            for mutate in (
                lambda doc, value=bad_status: doc["hero_entry"]["support"].__setitem__(
                    "status", value
                ),
                lambda doc, value=bad_status: doc["hero_entry"]["alternatives"][0][
                    "support"
                ].__setitem__("status", value),
            ):
                with self.subTest(status=repr(bad_status)):
                    bad = copy.deepcopy(document)
                    mutate(bad)
                    with self.assertRaises(contract.RobustnessContractError) as raised:
                        contract.validate_robustness_input(bad)
                    self.assertEqual(raised.exception.reason_code, "SUPPORT_INVALID")
                    self.assertIn("status", raised.exception.message)

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


class UncertaintySemanticsTest(unittest.TestCase):
    """Semantic CI95 width regressions (task ``backlog-wxq``).

    The contract is the fail-closed entry point, so an incoherent envelope is
    *refused* here instead of being repaired, re-derived or silently shrunk. The
    rule is the canonical one owned by the T4 classifier: the width is derived
    from the ``ci95`` bounds and the declared ``width_bb`` must agree with it
    within the shared numerical tolerance.
    """

    def document(self) -> dict:
        return copy.deepcopy(load_json(FIXTURES / "robust_consistent.json"))

    def test_ci95_tolerance_is_shared_with_the_canonical_classifier(self) -> None:
        self.assertEqual(
            contract.CI95_WIDTH_TOLERANCE_BB, classifier.CI95_WIDTH_TOLERANCE_BB
        )
        self.assertGreater(contract.CI95_WIDTH_TOLERANCE_BB, 0.0)

    def test_width_contradicting_the_bounds_fails_closed(self) -> None:
        envelope = {"ci95": [-10.0, 10.0], "width_bb": 0.06, "source": "synthetic"}
        for label, apply in (
            ("hero_entry", lambda doc: doc["hero_entry"].__setitem__("uncertainty", envelope)),
            (
                "alternatives[0]",
                lambda doc: doc["hero_entry"]["alternatives"][0].__setitem__(
                    "uncertainty", envelope
                ),
            ),
        ):
            with self.subTest(target=label):
                bad = self.document()
                apply(bad)
                with self.assertRaises(contract.RobustnessContractError) as raised:
                    contract.validate_robustness_input(bad)
                self.assertEqual(raised.exception.reason_code, "UNCERTAINTY_WIDTH_MISMATCH")
                self.assertIn("UNCERTAINTY_WIDTH_MISMATCH", raised.exception.reason_codes)
                self.assertEqual(
                    raised.exception.to_dict()["status"], "FAIL_CLOSED"
                )

    def test_reversed_or_non_finite_bounds_fail_closed(self) -> None:
        probes = (
            [1.0, 0.5],
            [float("nan"), 1.0],
            [0.0, float("inf")],
            [0.0, float("-inf")],
            [0.5],
            ["0.0", 1.0],
        )
        for ci95 in probes:
            with self.subTest(ci95=ci95):
                bad = self.document()
                bad["hero_entry"]["uncertainty"] = {
                    "ci95": ci95,
                    "width_bb": 0.06,
                    "source": "synthetic",
                }
                with self.assertRaises(contract.RobustnessContractError) as raised:
                    contract.validate_robustness_input(bad)
                self.assertEqual(raised.exception.reason_code, "UNCERTAINTY_INVALID")

    def test_invalid_declared_width_fails_closed(self) -> None:
        for declared in (-0.06, float("nan"), float("inf"), "0.06", None, True):
            with self.subTest(width_bb=declared):
                bad = self.document()
                bad["hero_entry"]["uncertainty"]["width_bb"] = declared
                with self.assertRaises(contract.RobustnessContractError) as raised:
                    contract.validate_robustness_input(bad)
                self.assertEqual(raised.exception.reason_code, "UNCERTAINTY_INVALID")

        bad = self.document()
        bad["hero_entry"]["uncertainty"].pop("width_bb")
        with self.assertRaises(contract.RobustnessContractError) as raised:
            contract.validate_robustness_input(bad)
        self.assertEqual(raised.exception.reason_code, "UNCERTAINTY_INVALID")

    def test_coherent_widths_are_accepted_despite_float_rounding(self) -> None:
        document = self.document()
        document["hero_entry"]["uncertainty"] = {
            "ci95": [1.39, 1.45],
            # ``1.45 - 1.39 == 0.06000000000000005``: the usual float rounding.
            "width_bb": 1.45 - 1.39,
            "source": "synthetic",
        }
        self.assertIs(contract.validate_robustness_input(document), document)

    def test_null_uncertainty_is_legal_but_never_support(self) -> None:
        document = self.document()
        document["hero_entry"]["uncertainty"] = None
        self.assertIs(contract.validate_robustness_input(document), document)
        verdict = classifier.classify(document)
        self.assertEqual(verdict["status"], "INSUFFICIENT_SUPPORT")
        self.assertIn("UNCERTAINTY_MISSING", verdict["reason_codes"])

        secondary = self.document()
        secondary["hero_entry"]["alternatives"][1]["uncertainty"] = None
        self.assertIs(contract.validate_robustness_input(secondary), secondary)
        verdict = classifier.classify(secondary)
        self.assertEqual(verdict["status"], "INSUFFICIENT_SUPPORT")
        self.assertIn("UNCERTAINTY_MISSING", verdict["reason_codes"])


class ReusedHarnessBoundaryTest(unittest.TestCase):
    """#425-owned guards on the reused #344 harness (task ``backlog-ncv``).

    The #344 files stay byte-identical to their own reviewed state, so the
    guards the #425 chain relies on are asserted from the #425 side: the harness
    accepts exactly its own synthetic source kind, refuses a non-synthetic
    request and refuses an injected EV / Model A feature.
    """

    def request(self) -> dict:
        return contract.project_to_harness_request(
            load_json(FIXTURES / "robust_consistent.json"), context()
        )

    def test_harness_accepts_the_projected_request(self) -> None:
        request = self.request()
        self.assertIs(harness.validate_request(request), None)
        self.assertEqual(request["source_kind"], harness.SOURCE_KIND)
        self.assertIs(request["synthetic_fixture"], True)

    def test_harness_refuses_a_foreign_source_kind(self) -> None:
        request = self.request()
        request["source_kind"] = f"{harness.SOURCE_KIND}_EXT"
        with self.assertRaises(ValueError) as raised:
            harness.validate_request(request)
        self.assertIn("synthetic", str(raised.exception).lower())

    def test_harness_refuses_a_non_synthetic_request(self) -> None:
        request = self.request()
        request["synthetic_fixture"] = False
        with self.assertRaises(ValueError):
            harness.validate_request(request)

    def test_harness_refuses_an_injected_ev_feature(self) -> None:
        request = self.request()
        request["alternatives"][0]["ev_bb"] = 1.0
        with self.assertRaises(ValueError) as raised:
            harness.validate_request(request)
        self.assertIn("forbidden", str(raised.exception).lower())

    def test_harness_refuses_an_injected_model_a_feature(self) -> None:
        request = self.request()
        request["alternatives"][0]["model_a_policy"] = "leak"
        with self.assertRaises(ValueError) as raised:
            harness.validate_request(request)
        self.assertIn("forbidden", str(raised.exception).lower())


class MetadataFeatureBoundaryTest(unittest.TestCase):
    """Metadata -> feature boundary and request invariance (task ``backlog-ncv``).

    The #425 metadata (public EV envelope, uncertainty, paired delta,
    route/source label, support verdict, posterior references) is read for
    classification and provenance only. Only the public action identity crosses
    into the #344 request, so changing *only* that metadata -- at constant public
    identity (decision id, context id, hero position, action and sizing of the
    Hero entry and of every alternative) -- must leave the projected request
    unchanged, byte for byte. The counterpart of an identity change is asserted
    too, so an over-aggressive projection that drops the sizing would fail here.
    """

    #: The exact key set a projected alternative may carry: public identity only.
    PROJECTED_ALTERNATIVE_KEYS = (
        "alternative_id",
        "action",
        "target_total_bb",
        "incremental_cost_bb",
    )

    def document(self) -> dict:
        return copy.deepcopy(load_json(FIXTURES / "robust_consistent.json"))

    def metadata_variant(self) -> dict:
        """Keep the public identity, move every classification/provenance field."""

        document = self.document()
        entry = document["hero_entry"]
        entry["ev"] = -5.0
        entry["uncertainty"] = {
            "ci95": [-5.03, -4.97],
            "width_bb": 0.06,
            "source": "synthetic_variant_ci95_v1",
        }
        entry["paired_delta"] = -1.25
        entry["route_source"] = "synthetic_variant_route_iso_5"
        entry["support"] = {"status": "SENSITIVE", "tier": "LOW", "ood": False}
        entry["posterior_refs"] = ["synthetic-variant-posterior-iso-5-01"]
        for index, alternative in enumerate(entry["alternatives"]):
            alternative["ev"] = float(alternative["ev"]) + 10.0
            alternative["uncertainty"] = {
                "ci95": [alternative["ev"] - 0.03, alternative["ev"] + 0.03],
                "width_bb": 0.06,
                "source": "synthetic_variant_ci95_v1",
            }
            alternative["paired_delta"] = float(alternative["paired_delta"]) + 0.5
            alternative["route_source"] = f"synthetic_variant_route_{index}"
            alternative["support"] = {
                "status": "OOD_UNTESTABLE",
                "tier": "VERY_LOW",
                "ood": True,
            }
            alternative["posterior_refs"] = [f"synthetic-variant-posterior-{index}"]
        return document

    def test_only_the_allowed_public_identity_is_projected(self) -> None:
        for name in VALID_FIXTURES:
            with self.subTest(fixture=name):
                request = contract.project_to_harness_request(
                    load_json(FIXTURES / name), context()
                )
                for alternative in request["alternatives"]:
                    self.assertEqual(
                        tuple(alternative), self.PROJECTED_ALTERNATIVE_KEYS
                    )
                self.assertEqual(
                    contract.check_forbidden_features(request), []
                )
                boundary = request["information_boundary"]
                self.assertTrue(boundary)
                self.assertTrue(all(flag is False for flag in boundary.values()))

    def test_request_is_unchanged_when_only_metadata_varies(self) -> None:
        baseline = contract.project_to_harness_request(self.document(), context())
        variant = contract.project_to_harness_request(self.metadata_variant(), context())
        self.assertEqual(
            variant, baseline, "metadata must never reach the projected request"
        )
        self.assertEqual(
            harness.canonical_sha256(variant), harness.canonical_sha256(baseline)
        )
        # The projected request stays the single accepted #344 format.
        self.assertIs(harness.validate_request(variant), None)
        self.assertEqual(variant["source_kind"], harness.SOURCE_KIND)

    def test_classification_may_move_while_the_request_stays_pinned(self) -> None:
        baseline, variant = self.document(), self.metadata_variant()
        self.assertNotEqual(
            classifier.classify(baseline)["status"],
            classifier.classify(variant)["status"],
            "the metadata variant must actually change the #425 verdict",
        )
        self.assertEqual(
            harness.canonical_sha256(
                contract.project_to_harness_request(variant, context())
            ),
            harness.canonical_sha256(
                contract.project_to_harness_request(baseline, context())
            ),
            "a verdict change must not change the Model B query",
        )

    def test_public_identity_change_does_change_the_request(self) -> None:
        baseline = contract.project_to_harness_request(self.document(), context())
        mutated = self.document()
        mutated["hero_entry"]["alternatives"][0]["sizing"] = 4.5
        variant = contract.project_to_harness_request(mutated, context())
        self.assertNotEqual(
            harness.canonical_sha256(variant),
            harness.canonical_sha256(baseline),
            "the projected request must still track the public sizing identity",
        )
        mutated = self.document()
        mutated["hero_entry"]["decision_id"] = "synthetic-variant-decision-id"
        variant = contract.project_to_harness_request(mutated, context())
        self.assertNotEqual(
            harness.canonical_sha256(variant),
            harness.canonical_sha256(baseline),
            "the projected request must still track the public decision identity",
        )


if __name__ == "__main__":
    unittest.main()

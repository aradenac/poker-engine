#!/usr/bin/env python3
"""#421 T9 guard: generalized adverse-response runtime provider (fail-closed).

Covers every acceptance criterion of the runtime task:

* the same context and seed always produce the same prediction document;
* a variation of the sizing / price is *recomputed directly* through the
  partition-of-unity price/sizing channel -- never a nearest-cell lookup;
* a context outside the calibrated domain (or with a never-observed category)
  abstains: ``OOD_ABSTAIN``, ``usable=false``, no selected action, no sizing;
* illegal actions never receive probability mass and are never selected, and
  every generated RAISE/JAM target is legal;
* a candidate / hash mismatch fails closed *before* any evaluation, and the
  document is machine-readable enough for #367 to consume.
"""
from __future__ import annotations

import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.preflop import generalized_response_model as model  # noqa: E402
from tools.preflop import generalized_response_runtime as runtime  # noqa: E402

MODULE_PATH = ROOT / "tools/preflop/generalized_response_runtime.py"
MANIFEST_PATH = ROOT / "analysis/issue421_generalized_response/CANDIDATE_MANIFEST.json"
MODEL_DIR = ROOT / "analysis/issue421_generalized_response/model"
OOD_REPORT_PATH = ROOT / "analysis/issue421_generalized_response/OOD_CALIBRATION_REPORT.json"

#: The provenance value every repository-local resolution must report.
MANIFEST_REGISTRY_SOURCE = "analysis/issue421_generalized_response/CANDIDATE_MANIFEST.json"

PRICE_AXES = {"to_call_bb", "pot_before_bb", "effective_stack_bb"}


def json_string_leaves(node: object, path: str = "$") -> list[tuple[str, str]]:
    """Every string value of a JSON document, addressed by its dotted path."""
    found: list[tuple[str, str]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            found.extend(json_string_leaves(value, f"{path}.{key}"))
            if isinstance(key, str):
                found.append((f"{path}.{key}<key>", key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(json_string_leaves(value, f"{path}[{index}]"))
    elif isinstance(node, str):
        found.append((path, node))
    return found


def base_context(**overrides: object) -> dict:
    """A public, in-domain UNOPENED context immediately before LJ acts."""
    context: dict = {
        "family": "UNOPENED",
        "actor_position": "LJ",
        "aggressor_position": None,
        "caller_count": 0,
        "limper_count": 0,
        "raise_level": 0,
        "live_positions": ["LJ", "HJ", "CO", "BTN", "SB", "BB"],
        "table_size": 6,
        "to_call_bb": 1.0,
        "pot_before_bb": 1.5,
        "effective_stack_bb": 70.975,
        "split": "TRAIN",
    }
    context.update(overrides)
    return context


def manifest_candidate() -> dict:
    document = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    candidate = document.get("candidate")
    if not isinstance(candidate, dict) or not candidate.get("candidate_id"):
        raise AssertionError("the frozen manifest carries no selected candidate")
    return candidate


class RuntimeFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not MANIFEST_PATH.exists() or not MODEL_DIR.exists():
            raise unittest.SkipTest("no persisted candidate manifest/artifact in this worktree")
        cls.entry = manifest_candidate()
        cls.candidate_id = str(cls.entry["candidate_id"])
        cls.candidate_sha256 = str(cls.entry["canonical_payload_sha256"])
        runtime.clear_runtime_caches()
        cls.runtime = runtime.GeneralizedResponseRuntime(candidate_id=cls.candidate_id)


# ---------------------------------------------------------------------------
# identity, machine-readable contract and fail-closed loading
# ---------------------------------------------------------------------------


class RuntimeIdentityTests(RuntimeFixtures):
    def test_metadata_binds_the_frozen_candidate_and_calibration(self) -> None:
        metadata = self.runtime.metadata()
        self.assertEqual(metadata["schema"], runtime.PROVIDER_SCHEMA)
        self.assertEqual(metadata["identity"]["candidate_id"], self.candidate_id)
        self.assertEqual(metadata["identity"]["canonical_payload_sha256"], self.candidate_sha256)
        self.assertEqual(self.runtime.candidate_sha256, self.candidate_sha256)
        self.assertEqual(metadata["ood_gate"]["consumed_splits"], ["TRAIN"])
        self.assertEqual(
            metadata["runtime"]["module_sha256"], runtime.sha256_file(MODULE_PATH)
        )
        self.assertTrue(metadata["guarantees"]["fail_closed_on_candidate_hash_mismatch"])
        self.assertTrue(metadata["guarantees"]["direct_price_sizing_evaluation"])

    def test_audit_flags_no_mutation_and_no_split_consumption(self) -> None:
        audit = self.runtime.audit()
        self.assertFalse(audit["active_model_pointer_mutated"])
        self.assertFalse(audit["validation_consumed"])
        self.assertFalse(audit["test_consumed"])
        self.assertFalse(audit["nearest_price"])
        self.assertFalse(audit["nearest_context"])
        self.assertTrue(audit["deterministic"])
        self.assertEqual(sorted(audit["fail_closed_codes"]), sorted(runtime.FAIL_CLOSED_CODES))

    def test_candidate_resolves_by_id_by_hash_and_by_path(self) -> None:
        by_id = runtime.GeneralizedResponseRuntime(candidate_id=self.candidate_id)
        by_hash = runtime.GeneralizedResponseRuntime(expected_candidate_sha256=self.candidate_sha256)
        by_reference = runtime.GeneralizedResponseRuntime(self.candidate_sha256)
        by_path = runtime.GeneralizedResponseRuntime(self.runtime.entry["path"])
        digests = {
            handle.candidate_sha256
            for handle in (by_id, by_hash, by_reference, by_path)
        }
        self.assertEqual(digests, {self.candidate_sha256})
        self.assertEqual(by_hash.entry["candidate_id"], self.candidate_id)
        self.assertEqual(by_path.candidate, by_id.candidate)

    def test_registry_source_is_repo_relative_for_every_resolution_mode(self) -> None:
        expected_artifact = self.runtime.entry["path"]
        handles = {
            "by_id": runtime.GeneralizedResponseRuntime(candidate_id=self.candidate_id),
            "by_hash": runtime.GeneralizedResponseRuntime(self.candidate_sha256),
            "by_expected_hash": runtime.GeneralizedResponseRuntime(
                expected_candidate_sha256=self.candidate_sha256
            ),
            "by_default_id": runtime.GeneralizedResponseRuntime(),
            "by_relative_path": runtime.GeneralizedResponseRuntime(expected_artifact),
            "by_model_directory_path": runtime.GeneralizedResponseRuntime(
                MODEL_DIR / Path(expected_artifact).name
            ),
        }
        for label, handle in handles.items():
            self.assertEqual(handle.entry["registry_source"], MANIFEST_REGISTRY_SOURCE, label)
            self.assertFalse(Path(handle.entry["registry_source"]).is_absolute(), label)
            self.assertEqual(handle.entry["path"], expected_artifact, label)
            self.assertFalse(Path(handle.entry["path"]).is_absolute(), label)
            # No behaviour change: identity and digests are untouched by the
            # provenance normalisation.
            self.assertEqual(handle.entry["candidate_id"], self.candidate_id, label)
            self.assertEqual(handle.candidate_sha256, self.candidate_sha256, label)
            self.assertEqual(
                handle.candidate["canonical_payload_sha256"], self.candidate_sha256, label
            )
            self.assertEqual(
                handle.entry["artifact_sha256"], self.runtime.entry["artifact_sha256"], label
            )

    def test_repo_relative_normalises_paths_without_leaking_the_host(self) -> None:
        self.assertEqual(runtime._repo_relative(MANIFEST_PATH), MANIFEST_REGISTRY_SOURCE)
        self.assertEqual(
            runtime._repo_relative(MANIFEST_REGISTRY_SOURCE), MANIFEST_REGISTRY_SOURCE
        )
        self.assertEqual(
            runtime._repo_relative(MODEL_DIR), "analysis/issue421_generalized_response/model"
        )
        with tempfile.TemporaryDirectory() as folder:
            outside = runtime._repo_relative(Path(folder) / "CANDIDATE_MANIFEST.json")
        self.assertFalse(outside.startswith("/"), outside)
        self.assertNotIn(str(runtime.ROOT), outside)
        self.assertNotIn("\\", outside)

    def test_directory_candidates_report_a_repo_relative_registry_source(self) -> None:
        registry = runtime.candidate_registry()
        directory_candidates = [
            entry for entry in registry.values() if entry.get("role") == "DIRECTORY_CANDIDATE"
        ]
        self.assertTrue(directory_candidates, "the model directory holds candidate artifacts")
        for entry in directory_candidates:
            self.assertEqual(
                entry["registry_source"], "analysis/issue421_generalized_response/model"
            )
            self.assertFalse(Path(entry["registry_source"]).is_absolute())
            self.assertFalse(Path(entry["path"]).is_absolute())

    def test_expected_hash_mismatch_fails_closed_without_evaluating(self) -> None:
        with self.assertRaises(runtime.GeneralizedResponseRuntimeError) as caught:
            runtime.GeneralizedResponseRuntime(
                candidate_id=self.candidate_id,
                expected_candidate_sha256="0" * 64,
            )
        self.assertEqual(caught.exception.code, runtime.FAIL_CLOSED_CANDIDATE_HASH_MISMATCH)
        self.assertIn(self.candidate_sha256, caught.exception.message)

    def test_unknown_candidate_reference_fails_closed(self) -> None:
        for reference in ("not-a-candidate", "f" * 64):
            with self.assertRaises(runtime.GeneralizedResponseRuntimeError) as caught:
                runtime.GeneralizedResponseRuntime(reference)
            self.assertEqual(caught.exception.code, runtime.FAIL_CLOSED_CANDIDATE_NOT_FOUND)

    def test_a_missing_ood_calibration_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            missing = Path(folder) / "OOD_CALIBRATION_REPORT.json"
            with self.assertRaises(runtime.GeneralizedResponseRuntimeError) as caught:
                runtime.GeneralizedResponseRuntime(
                    candidate_id=self.candidate_id, ood_report_path=missing
                )
            self.assertEqual(
                caught.exception.code, runtime.FAIL_CLOSED_CALIBRATION_UNAVAILABLE
            )

    def test_malformed_expected_hash_fails_closed(self) -> None:
        with self.assertRaises(runtime.GeneralizedResponseRuntimeError) as caught:
            runtime.GeneralizedResponseRuntime(
                candidate_id=self.candidate_id, expected_candidate_sha256="abc"
            )
        self.assertEqual(caught.exception.code, runtime.FAIL_CLOSED_CANDIDATE_HASH_MISMATCH)

    def test_tampered_artifact_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "candidate_tampered.json"
            document = json.loads(
                (MODEL_DIR / Path(self.runtime.entry["path"]).name).read_text(encoding="utf-8")
            )
            document["params"]["prior"]["FOLD"] = 0.9
            target.write_text(json.dumps(document, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            with self.assertRaises(runtime.GeneralizedResponseRuntimeError) as caught:
                runtime.GeneralizedResponseRuntime(target)
            self.assertIn(
                caught.exception.code,
                {runtime.FAIL_CLOSED_CANDIDATE_HASH_MISMATCH, runtime.FAIL_CLOSED_CANDIDATE_INVALID},
            )

    def test_inline_candidate_with_a_stale_digest_fails_closed(self) -> None:
        document = json.loads(
            (MODEL_DIR / Path(self.runtime.entry["path"]).name).read_text(encoding="utf-8")
        )
        document["params"]["prior"]["JAM"] = 0.25
        with self.assertRaises(runtime.GeneralizedResponseRuntimeError) as caught:
            runtime.GeneralizedResponseRuntime(document)
        self.assertEqual(caught.exception.code, runtime.FAIL_CLOSED_CANDIDATE_INVALID)

    def test_module_imports_only_the_standard_library(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported.add(node.module.split(".")[0])
        third_party = {"numpy", "scipy", "sklearn", "pandas", "torch", "statsmodels"}
        self.assertFalse(imported & third_party, sorted(imported & third_party))
        # ``tools`` is this repository's own package (the runtime wraps the
        # generalized response model), everything else must be stdlib.
        non_stdlib = sorted(
            name
            for name in imported
            if name not in {"__future__", "tools"} and name not in sys.stdlib_module_names
        )
        self.assertEqual(non_stdlib, [])


# ---------------------------------------------------------------------------
# decision document contract
# ---------------------------------------------------------------------------


class DecisionContractTests(RuntimeFixtures):
    def _decision(self, **overrides: object) -> dict:
        return self.runtime.resolve(base_context(**overrides), action="RAISE")

    def test_decision_document_is_machine_readable(self) -> None:
        document = self._decision(target_total_bb=3.0)
        for key in runtime.RUNTIME_DECISION_REQUIRED_KEYS:
            self.assertIn(key, document, key)
        self.assertEqual(document["schema"], runtime.RUNTIME_SCHEMA)
        self.assertIn(document["status"], runtime.RUNTIME_STATUSES)
        # Round-trippable: the document is plain JSON with no private objects.
        cloned = json.loads(json.dumps(document, sort_keys=True))
        self.assertEqual(cloned, document)
        self.assertEqual(document["context_key"], model.ood_exact_context_key(base_context(target_total_bb=3.0)))
        self.assertEqual(document["deterministic_seed"], int(self.runtime.candidate["seed"]))

    def test_consumer_view_is_self_contained_for_367(self) -> None:
        document = self._decision(target_total_bb=3.0)
        consumer = document["consumer"]
        self.assertEqual(consumer["schema"], runtime.RUNTIME_SCHEMA)
        self.assertEqual(consumer["candidate_id"], self.candidate_id)
        self.assertEqual(consumer["candidate_sha256"], self.candidate_sha256)
        self.assertEqual(consumer["action_space"], list(model.ACTIONS))
        self.assertEqual(consumer["selected_action"], "RAISE")
        self.assertEqual(consumer["illegal_mass"], 0.0)
        self.assertAlmostEqual(consumer["probability_sum"], 1.0, places=9)
        self.assertEqual(consumer["actions"], document["action_probabilities"])
        self.assertEqual(consumer["selected_sizing_bb"], document["selected_sizing_bb"])

    def test_decision_hash_is_canonical_and_recomputable(self) -> None:
        document = self._decision(target_total_bb=3.0)
        self.assertEqual(
            document["decision_canonical_sha256"],
            runtime.decision_canonical_sha256(document),
        )
        self.assertEqual(len(document["decision_canonical_sha256"]), 64)

    def test_the_decision_document_carries_no_absolute_host_path(self) -> None:
        document = runtime.resolve_generalized_response(
            base_context(target_total_bb=3.0), action="RAISE"
        )
        self.assertEqual(
            document["provenance"]["candidate"]["registry_source"], MANIFEST_REGISTRY_SOURCE
        )
        encoded = json.dumps(document, sort_keys=True)
        self.assertNotIn(str(runtime.ROOT), encoded)
        self.assertNotIn("/home/", encoded)
        absolute = [item for item in json_string_leaves(document) if item[1].startswith("/")]
        self.assertEqual(absolute, [])

    def test_provenance_declares_direct_evaluation_and_no_substitution(self) -> None:
        document = self._decision(target_total_bb=3.0)
        prediction = document["prediction"]
        self.assertEqual(document["request"]["evaluation"], "direct_recomputation")
        self.assertEqual(
            prediction["sizing"]["interpolation"], "linear_spline_partition_of_unity"
        )
        self.assertTrue(prediction["sizing"]["conditioned"])
        sizing = document["sizing"]
        self.assertFalse(sizing["nearest_price_substituted"])
        self.assertFalse(sizing["nearest_context_substituted"])
        flags = document["provenance"]["identity_flags"]
        self.assertFalse(flags["nearest_price_substituted"])
        self.assertFalse(flags["nearest_context_substituted"])
        self.assertFalse(flags["active_model_pointer_mutated"])
        self.assertFalse(flags["test_consumed"])
        self.assertFalse(flags["validation_consumed"])

    def test_the_decision_reuses_the_frozen_model_surface_verbatim(self) -> None:
        context = base_context(target_total_bb=3.0)
        candidate = model.load_candidate(MODEL_DIR / Path(self.runtime.entry["path"]).name)
        document = self.runtime.resolve(context, action="RAISE")
        self.assertEqual(document["prediction"], model.predict(candidate, context))
        self.assertEqual(
            document["ood"]["status"],
            model.ood_gate_decision(
                candidate, context, calibration=self.runtime.calibration
            )["status"],
        )
        self.assertEqual(
            document["sizing"]["generated_sizings_bb"],
            model.raise_sizing_query(candidate, context, action="RAISE")["generated_sizings_bb"],
        )

    def test_issue367_consumption_flag_follows_the_frozen_validation_result(self) -> None:
        document = self._decision(target_total_bb=3.0)
        frozen = document["provenance"]["frozen_validation_result"]
        issue367 = document["provenance"]["issue367"]
        self.assertEqual(issue367["rule_id"], runtime.ISSUE367_RULE_ID)
        if frozen.get("available"):
            self.assertEqual(issue367["authorized"], frozen.get("outcome") == "ADMIT_CANDIDATE")
        self.assertFalse(issue367["authorized"], "the runtime must not self-authorize #367 consumption")


# ---------------------------------------------------------------------------
# direct (non-lookup) price / sizing evaluation
# ---------------------------------------------------------------------------


class DirectEvaluationTests(RuntimeFixtures):
    def _probabilities(self, **overrides: object) -> dict:
        document = self.runtime.resolve(base_context(**overrides), action="RAISE")
        self.assertTrue(document["usable"], document["status"])
        return document["action_probabilities"]

    def test_a_sizing_variation_is_recomputed_directly(self) -> None:
        low = self._probabilities(target_total_bb=2.5)["RAISE"]
        middle = self._probabilities(target_total_bb=2.75)["RAISE"]
        high = self._probabilities(target_total_bb=3.0)["RAISE"]
        # A nearest-cell lookup would return one of the two query values exactly.
        self.assertNotEqual(low, middle)
        self.assertNotEqual(middle, high)
        self.assertTrue(high < middle < low, (low, middle, high))
        # The response is continuous: an arbitrarily small move still moves it.
        epsilon = self._probabilities(target_total_bb=3.0001)["RAISE"]
        self.assertLess(epsilon, high)
        self.assertLess(abs(epsilon - high), abs(high - middle))

    def test_a_price_variation_is_recomputed_directly(self) -> None:
        low = self._probabilities(to_call_bb=1.0)["FOLD"]
        middle = self._probabilities(to_call_bb=1.5)["FOLD"]
        high = self._probabilities(to_call_bb=2.0)["FOLD"]
        self.assertNotEqual(low, middle)
        self.assertNotEqual(middle, high)
        self.assertTrue(low < middle < high, (low, middle, high))

    def test_target_is_echoed_and_flips_the_sizing_channel_on(self) -> None:
        default = self.runtime.resolve(base_context(), action="RAISE")
        conditioned = self.runtime.resolve(base_context(target_total_bb=3.0), action="RAISE")
        self.assertEqual(default["request"]["sizing_source"], "default_pot_relative")
        self.assertFalse(default["prediction"]["sizing"]["conditioned"])
        self.assertEqual(conditioned["request"]["sizing_source"], "context")
        self.assertEqual(conditioned["request"]["target_total_bb"], 3.0)
        self.assertEqual(conditioned["request"]["sizing_ratio"], 1.2)
        self.assertTrue(conditioned["prediction"]["sizing"]["conditioned"])
        self.assertNotEqual(
            default["decision_canonical_sha256"], conditioned["decision_canonical_sha256"]
        )

    def test_every_decision_recomputes_the_public_price_axes(self) -> None:
        document = self.runtime.resolve(base_context(target_total_bb=3.0), action="RAISE")
        request = document["request"]
        for axis in PRICE_AXES:
            self.assertIn(axis, request, axis)
            self.assertEqual(request[axis], _round(base_context(target_total_bb=3.0)[axis]))


def _round(value: object, digits: int = 6) -> float:
    number = float(value)  # type: ignore[arg-type]
    rounded = round(number, digits)
    return 0.0 if rounded == 0 else rounded


# ---------------------------------------------------------------------------
# legal action space
# ---------------------------------------------------------------------------


class LegalActionTests(RuntimeFixtures):
    def test_call_is_masked_when_there_is_no_price_to_call(self) -> None:
        document = self.runtime.resolve(base_context(to_call_bb=0.0), action="RAISE")
        self.assertIn("CALL", document["masked_actions"])
        self.assertEqual(document["action_probabilities"]["CALL"], 0.0)
        self.assertNotIn("CALL", document["legal_actions"])
        self.assertAlmostEqual(document["probability_sum"], 1.0, places=9)

    def test_facing_an_all_in_masks_raise_and_jam(self) -> None:
        document = self.runtime.resolve(base_context(facing_all_in=True))
        self.assertEqual(document["masked_actions"], ["RAISE", "JAM"])
        self.assertEqual(document["action_probabilities"]["RAISE"], 0.0)
        self.assertEqual(document["action_probabilities"]["JAM"], 0.0)
        self.assertIn(document["selected_action"], (None, "FOLD", "CALL"))
        self.assertIsNone(document["sizing"])
        with self.assertRaises(runtime.GeneralizedResponseRuntimeError) as caught:
            self.runtime.resolve(base_context(facing_all_in=True), action="JAM")
        self.assertEqual(caught.exception.code, runtime.FAIL_CLOSED_ILLEGAL_ACTION)

    def test_explicit_legal_actions_are_authoritative(self) -> None:
        document = self.runtime.resolve(
            base_context(legal_actions=["FOLD", "CALL"]), action="CALL"
        )
        self.assertEqual(document["legal_actions"], ["FOLD", "CALL"])
        self.assertEqual(document["masked_actions"], ["RAISE", "JAM"])
        self.assertEqual(document["request"]["legal_action_source"], "context.legal_actions")
        self.assertIsNone(document["sizing"])

    def test_an_unknown_action_request_fails_closed(self) -> None:
        with self.assertRaises(runtime.GeneralizedResponseRuntimeError) as caught:
            self.runtime.resolve(base_context(), action="RE_RAISE")
        self.assertEqual(caught.exception.code, runtime.FAIL_CLOSED_ILLEGAL_ACTION)

    def test_a_limp_request_is_the_call_action(self) -> None:
        document = self.runtime.resolve(base_context(), action="LIMP")
        self.assertEqual(document["selected_action"], "CALL")
        self.assertEqual(document["request"]["requested_action"], "LIMP")

    def test_no_decision_ever_carries_illegal_probability_mass(self) -> None:
        for overrides in (
            {},
            {"to_call_bb": 0.0},
            {"facing_all_in": True},
            {"legal_actions": ["FOLD", "CALL"]},
            {"family": "VS_LIMPERS", "actor_position": "BB", "limper_count": 1,
             "live_positions": ["BTN", "SB", "BB"], "to_call_bb": 0.5, "pot_before_bb": 2.5},
        ):
            document = self.runtime.resolve(base_context(**overrides))
            legal = set(document["legal_actions"])
            for action in model.ACTIONS:
                if action not in legal:
                    self.assertEqual(document["action_probabilities"][action], 0.0, (overrides, action))
            self.assertEqual(document["illegal_mass"], 0.0)
            self.assertAlmostEqual(document["probability_sum"], 1.0, places=9)


# ---------------------------------------------------------------------------
# conditional sizing
# ---------------------------------------------------------------------------


class ConditionalSizingTests(RuntimeFixtures):
    def test_a_resolved_raise_returns_legal_generated_sizings(self) -> None:
        document = self.runtime.resolve(base_context(target_total_bb=3.0), action="RAISE")
        sizing = document["sizing"]
        window = sizing["legal_window"]
        self.assertEqual(sizing["status"], "RESOLVED")
        self.assertEqual(sizing["action"], "RAISE")
        self.assertEqual(sizing["illegal_count"], 0)
        self.assertGreater(sizing["generated_count"], 0)
        for target in sizing["generated_sizings_bb"]:
            self.assertGreaterEqual(target, window["floor_bb"] - 1e-9)
            self.assertLessEqual(target, window["cap_bb"] + 1e-9)
        self.assertGreaterEqual(document["selected_sizing_bb"], window["floor_bb"] - 1e-9)
        self.assertLessEqual(document["selected_sizing_bb"], window["cap_bb"] + 1e-9)

    def test_the_explicit_engine_interval_is_authoritative(self) -> None:
        document = self.runtime.resolve(
            base_context(target_total_bb=5.0, min_raise_to_bb=9.0, max_raise_to_bb=60.0),
            action="RAISE",
        )
        window = document["sizing"]["legal_window"]
        self.assertEqual(window["floor_bb"], 9.0)
        self.assertEqual(window["cap_bb"], 60.0)
        self.assertEqual(window["bounds_source"]["min"], "engine_interval")
        for target in document["sizing"]["generated_sizings_bb"]:
            self.assertGreaterEqual(target, 9.0 - 1e-9)
            self.assertLessEqual(target, 60.0 + 1e-9)

    def test_a_non_aggressive_selection_has_no_sizing_request(self) -> None:
        document = self.runtime.resolve(base_context())
        self.assertEqual(document["selected_action"], "FOLD")
        self.assertIsNone(document["sizing"])
        self.assertIsNone(document["selected_sizing_bb"])

    def test_an_ood_context_never_returns_a_sizing(self) -> None:
        document = self.runtime.resolve(
            base_context(effective_stack_bb=5000.0, target_total_bb=3.0), action="RAISE"
        )
        self.assertEqual(document["status"], runtime.STATUS_ABSTAIN)
        self.assertIsNone(document["sizing"])
        self.assertIsNone(document["selected_sizing_bb"])

    def test_a_blocked_raise_window_is_reported_fail_closed(self) -> None:
        # A raise below the stack is impossible: only the all-in stays legal.
        document = self.runtime.resolve(
            base_context(
                raise_level=1,
                actor_contribution_bb=5.0,
                to_call_bb=30.0,
                pot_before_bb=60.0,
                effective_stack_bb=40.0,
            ),
            action="RAISE",
        )
        if document["usable"]:
            self.assertEqual(document["sizing"]["status"], "FAIL_CLOSED")
            self.assertEqual(
                document["sizing"]["fail_closed_reason"], "RAISE_WINDOW_EMPTY_BELOW_STACK"
            )
            self.assertEqual(document["sizing"]["generated_sizings_bb"], [])
            self.assertIsNone(document["selected_sizing_bb"])


# ---------------------------------------------------------------------------
# OOD / abstention
# ---------------------------------------------------------------------------


class OodAbstentionTests(RuntimeFixtures):
    def test_a_stack_extrapolation_abstains(self) -> None:
        document = self.runtime.resolve(base_context(effective_stack_bb=5000.0), action="RAISE")
        self.assertEqual(document["status"], runtime.STATUS_ABSTAIN)
        self.assertFalse(document["usable"])
        self.assertTrue(document["abstain"])
        self.assertTrue(document["fail_closed"])
        self.assertEqual(document["fail_closed_reason"], runtime.OOD_ABSTAIN_REASON)
        self.assertIn("EXTRAPOLATION_STACK", document["ood"]["hard_reasons"])
        self.assertIsNone(document["selected_action"])
        self.assertIsNone(document["sizing"])
        # The distribution is still reported, for diagnostics only.
        self.assertAlmostEqual(document["probability_sum"], 1.0, places=9)

    def test_a_sizing_extrapolation_abstains(self) -> None:
        document = self.runtime.resolve(base_context(target_total_bb=5000.0), action="RAISE")
        self.assertEqual(document["status"], runtime.STATUS_ABSTAIN)
        self.assertIn("EXTRAPOLATION_SIZING", document["ood"]["hard_reasons"])

    def test_a_never_observed_category_abstains(self) -> None:
        document = self.runtime.resolve(base_context(family="NOT_A_FAMILY"), action="RAISE")
        self.assertEqual(document["status"], runtime.STATUS_ABSTAIN)
        self.assertIn("UNSEEN_CATEGORY", document["ood"]["hard_reasons"])
        self.assertIsNone(document["selected_action"])

    def test_a_missing_domain_axis_abstains(self) -> None:
        context = base_context()
        context.pop("pot_before_bb")
        document = self.runtime.resolve(context)
        self.assertEqual(document["status"], runtime.STATUS_ABSTAIN)
        self.assertIn("MISSING_DOMAIN_AXIS", document["ood"]["hard_reasons"])

    def test_a_high_uncertainty_context_stays_usable(self) -> None:
        document = self.runtime.resolve(
            base_context(
                family="VS_LIMPERS",
                actor_position="BB",
                limper_count=1,
                live_positions=["BTN", "SB", "BB"],
                to_call_bb=0.5,
                pot_before_bb=2.5,
                effective_stack_bb=100.0,
            )
        )
        self.assertEqual(document["status"], runtime.STATUS_HIGH_UNCERTAINTY)
        self.assertTrue(document["usable"])
        self.assertFalse(document["fail_closed"])
        self.assertIsNotNone(document["selected_action"])

    def test_ood_abstention_is_excluded_from_the_consumer_view(self) -> None:
        document = self.runtime.resolve(base_context(effective_stack_bb=5000.0), action="RAISE")
        consumer = document["consumer"]
        self.assertFalse(consumer["usable"])
        self.assertEqual(consumer["status"], runtime.STATUS_ABSTAIN)
        self.assertIsNone(consumer["selected_action"])
        self.assertIsNone(consumer["selected_sizing_bb"])


# ---------------------------------------------------------------------------
# determinism and split / seed guards
# ---------------------------------------------------------------------------


class DeterminismTests(RuntimeFixtures):
    def test_same_context_and_seed_are_byte_identical(self) -> None:
        contexts = (
            base_context(),
            base_context(target_total_bb=3.0),
            base_context(to_call_bb=2.0, pot_before_bb=4.0, effective_stack_bb=60.0),
            base_context(family="VS_LIMPERS", actor_position="BB", limper_count=1,
                         live_positions=["BTN", "SB", "BB"], to_call_bb=0.5, pot_before_bb=2.5),
        )
        for context in contexts:
            for action in (None, "RAISE", "JAM"):
                first = resolve(context, action)
                second = resolve(context, action)
                self.assertEqual(
                    json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True), (context, action)
                )
                self.assertEqual(
                    first["decision_canonical_sha256"], second["decision_canonical_sha256"]
                )

    def test_the_seed_is_part_of_the_request_identity(self) -> None:
        pinned = int(self.runtime.candidate["seed"])
        accepted = self.runtime.resolve(base_context(), seed=pinned)
        self.assertEqual(accepted["deterministic_seed"], pinned)
        with self.assertRaises(runtime.GeneralizedResponseRuntimeError) as caught:
            self.runtime.resolve(base_context(), seed=pinned + 1)
        self.assertEqual(caught.exception.code, runtime.FAIL_CLOSED_SEED_MISMATCH)

    def test_a_test_split_context_is_never_consumed(self) -> None:
        with self.assertRaises(runtime.GeneralizedResponseRuntimeError) as caught:
            self.runtime.resolve(base_context(split="TEST"))
        self.assertEqual(caught.exception.code, runtime.FAIL_CLOSED_TEST_SPLIT)


def resolve(context: dict, action: str | None, seed: int | None = None) -> dict:
    """Resolve through the module-level entry point (fresh handle per call)."""
    return runtime.GeneralizedResponseRuntime(candidate_id=manifest_candidate()["candidate_id"]).resolve(
        context, action=action, seed=seed
    )


if __name__ == "__main__":
    unittest.main(verbosity=2)

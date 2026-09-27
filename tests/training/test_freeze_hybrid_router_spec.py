#!/usr/bin/env python3
"""#423 T1 guard: hybrid router spec, runtime contract and preregistration procedure.

Covers every acceptance criterion of the task:

* the schema is a valid JSON-Schema document and the persisted spec satisfies
  it under the repository's stdlib keyword subset (``jsonschema`` is not a
  declared dependency);
* the spec enumerates the three route sources, the stable pre-action signals,
  the reason codes reused from #421 and the exact derivation procedure, with no
  numeric value issued from a terminal evaluation;
* two generator runs are byte-identical and the ``.sha256`` sidecar pins the
  frozen bytes and the canonical payload digest;
* the generator fails closed when a VALIDATION or TEST split is required, and a
  formula altered after the fact changes the digest;
* the strata and OOD gate definitions are the #421 ones, not a copy.

The tests never parse a holdout hand: they consume the frozen TRAIN-only
cross-validation report only.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.preflop import generalized_response_model as grm  # noqa: E402
from tools.training import evaluate_generalized_response_cv as cv  # noqa: E402
from tools.training import freeze_hybrid_router_spec as tool  # noqa: E402

#: The two splits the freeze must never require.
FORBIDDEN_SPLITS = ("VALIDATION", "TEST")

#: The full set of declared route sources, in the order the contract declares.
REQUIRED_ROUTE_SOURCES = (
    "ACTIVE_STRONG_SUPPORT",
    "GENERALIZED_SPARSE_IN_DOMAIN",
    "OOD_ABSTAIN",
)
REQUIRED_SIGNALS = (
    "support_exact",
    "support_feature_level",
    "distance_to_domain",
    "predictive_uncertainty",
    "extrapolation_sizing",
    "extrapolation_stack",
    "extrapolation_price",
    "family",
    "actor_position",
    "aggressor_position",
)
REQUIRED_RUNTIME_FIELDS = (
    "route_source",
    "model_id",
    "model_hash",
    "support_state",
    "uncertainty",
    "ood_status",
    "probabilities",
    "sizing_provenance",
    "analysis_admissible",
)
REQUIRED_FORMULAS = (
    "GLOBAL_NON_INFERIORITY_MARGIN",
    "SPARSE_GAIN_FLOOR",
    "SPARSE_ECE_CEILING",
    "FREQUENT_EXACT_NON_DEGRADATION_BOUND",
    "OOD_ABSTENTION_CRITERION",
)


# --------------------------------------------------------------------------
# minimal deterministic JSON-Schema checker (stdlib only)
# --------------------------------------------------------------------------


def _resolve_ref(node: dict, root: dict) -> dict:
    seen = 0
    while isinstance(node, dict) and "$ref" in node:
        ref = node["$ref"]
        if not ref.startswith("#/"):
            raise AssertionError(f"unsupported $ref: {ref}")
        target: object = root
        for part in ref[2:].split("/"):
            target = target[part]  # type: ignore[index]
        node = target  # type: ignore[assignment]
        seen += 1
        if seen > 32:
            raise AssertionError(f"cyclic $ref: {ref}")
    return node


def validate(value, schema: dict, root: dict, path: str = "$") -> None:
    """Minimal deterministic checker for the contract keyword subset."""
    schema = _resolve_ref(schema, root)
    if "const" in schema and value != schema["const"]:
        raise AssertionError(f"{path}: expected const {schema['const']!r}, got {value!r}")
    if "enum" in schema and value not in schema["enum"]:
        raise AssertionError(f"{path}: {value!r} not in enum {schema['enum']!r}")
    if "type" in schema:
        expected = schema["type"]
        names = expected if isinstance(expected, list) else [expected]
        ok = False
        for name in names:
            if name == "null" and value is None:
                ok = True
            elif name == "object" and isinstance(value, dict):
                ok = True
            elif name == "array" and isinstance(value, list):
                ok = True
            elif name == "string" and isinstance(value, str):
                ok = True
            elif name == "boolean" and isinstance(value, bool):
                ok = True
            elif name == "integer" and isinstance(value, int) and not isinstance(value, bool):
                ok = True
            elif name == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
                ok = True
        if not ok:
            raise AssertionError(f"{path}: {type(value).__name__} not in type {names!r}")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                raise AssertionError(f"{path}: missing required key {key!r}")
        if len(value) < int(schema.get("minProperties", 0)):
            raise AssertionError(f"{path}: fewer than {schema['minProperties']} properties")
        properties = schema.get("properties", {})
        for key, child in value.items():
            if key in properties:
                validate(child, properties[key], root, f"{path}.{key}")
                continue
            if schema.get("additionalProperties") is False:
                raise AssertionError(f"{path}: additional property {key!r} is not allowed")
            extra = schema.get("additionalProperties")
            if isinstance(extra, dict):
                validate(child, extra, root, f"{path}.{key}")
    if isinstance(value, list):
        if len(value) < int(schema.get("minItems", 0)):
            raise AssertionError(f"{path}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            raise AssertionError(f"{path}: more than {schema['maxItems']} items")
        if schema.get("uniqueItems"):
            rendered = {json.dumps(item, sort_keys=True) for item in value}
            if len(rendered) != len(value):
                raise AssertionError(f"{path}: items are not unique")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, child in enumerate(value):
                validate(child, item_schema, root, f"{path}[{index}]")
    if isinstance(value, str):
        if len(value) < int(schema.get("minLength", 0)):
            raise AssertionError(f"{path}: shorter than minLength {schema['minLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            raise AssertionError(f"{path}: {value!r} does not match {schema['pattern']!r}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise AssertionError(f"{path}: {value} < minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            raise AssertionError(f"{path}: {value} > maximum {schema['maximum']}")


def _numbers(value, path: str = "$"):
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        yield path, value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from _numbers(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _numbers(child, f"{path}[{index}]")


class _IsolatedLayout:
    """Redirect every artifact the tool writes into a temporary directory."""

    def __init__(self, tmp: Path):
        self.tmp = tmp

    def __enter__(self):
        here = self.tmp / "issue423_hybrid_router"
        self._patches = [
            mock.patch.object(tool, "HERE", here),
            mock.patch.object(tool, "SPEC_PATH", here / tool.SPEC_NAME),
            mock.patch.object(tool, "DIGEST_PATH", here / "HYBRID_ROUTER_SPEC.sha256"),
        ]
        for patch in self._patches:
            patch.start()
        return here

    def __exit__(self, *exc):
        for patch in reversed(self._patches):
            patch.stop()
        return False


class SchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema_bytes = tool.SCHEMA_PATH.read_bytes()
        cls.schema = json.loads(cls.schema_bytes)
        cls.gate_schema = json.loads(tool.OOD_GATE_SCHEMA_PATH.read_text(encoding="utf-8"))

    def test_schema_is_valid_json_with_defs_and_root_ref(self):
        self.assertEqual(self.schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertTrue(self.schema["$id"].endswith("hybrid-router-spec.schema.json"))
        self.assertEqual(self.schema["$ref"], "#/$defs/spec")
        self.assertIn("spec", self.schema["$defs"])
        self.assertIn("formula", self.schema["$defs"])

    def test_schema_rejects_a_route_source_outside_the_contract(self):
        broken = copy.deepcopy(json.loads(tool.SPEC_PATH.read_text(encoding="utf-8")))
        broken["route_sources"][0]["id"] = "NEAREST_LOOKUP"
        with self.assertRaises(AssertionError):
            validate(broken, self.schema, self.schema)

    def test_schema_rejects_a_spec_missing_a_route_source(self):
        broken = copy.deepcopy(json.loads(tool.SPEC_PATH.read_text(encoding="utf-8")))
        broken["route_sources"] = broken["route_sources"][:2]
        with self.assertRaises(AssertionError):
            validate(broken, self.schema, self.schema)

    def test_schema_rejects_an_undeclared_top_level_key(self):
        broken = copy.deepcopy(json.loads(tool.SPEC_PATH.read_text(encoding="utf-8")))
        broken["terminal_metrics"] = {}
        with self.assertRaises(AssertionError):
            validate(broken, self.schema, self.schema)


class PersistedSpecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec_bytes = tool.SPEC_PATH.read_bytes()
        cls.spec = json.loads(cls.spec_bytes)
        cls.schema = json.loads(tool.SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.digest = hashlib.sha256(cls.spec_bytes).hexdigest()
        cls.sidecar = tool.DIGEST_PATH.read_text(encoding="utf-8").splitlines()

    def test_persisted_spec_satisfies_the_contract(self):
        validate(self.spec, self.schema, self.schema)

    def test_sidecar_pins_the_bytes_and_the_canonical_payload(self):
        self.assertEqual(self.sidecar[0].split(), [self.digest, tool.SPEC_NAME])
        canonical = self.sidecar[1].split()[-1]
        payload = {
            key: value
            for key, value in self.spec.items()
            if key != "canonical_payload_sha256"
        }
        self.assertEqual(canonical, tool.stable_hash(payload))
        self.assertEqual(canonical, self.spec["canonical_payload_sha256"])

    def test_spec_identity_and_split_policy(self):
        self.assertEqual(self.spec["schema"], tool.SPEC_SCHEMA)
        self.assertEqual(self.spec["issue"], 423)
        self.assertEqual(self.spec["status"], tool.STATUS)
        self.assertTrue(self.spec["frozen"])
        self.assertTrue(self.spec["authored_before_validation_read"])
        policy = self.spec["split_policy"]
        self.assertEqual(policy["allowed_splits"], ["TRAIN"])
        self.assertEqual(policy["consumed_splits"], ["TRAIN"])
        self.assertEqual(policy["refused_splits"], list(FORBIDDEN_SPLITS))
        self.assertTrue(policy["fail_closed_on_refused_split"])
        self.assertTrue(policy["refused_split_is_a_hard_error"])

    def test_spec_enumerates_the_three_route_sources(self):
        ids = [entry["id"] for entry in self.spec["route_sources"]]
        self.assertEqual(tuple(ids), REQUIRED_ROUTE_SOURCES)
        by_id = {entry["id"]: entry for entry in self.spec["route_sources"]}
        self.assertFalse(by_id["ACTIVE_STRONG_SUPPORT"]["abstains"])
        self.assertFalse(by_id["GENERALIZED_SPARSE_IN_DOMAIN"]["abstains"])
        self.assertTrue(by_id["OOD_ABSTAIN"]["abstains"])
        self.assertEqual(
            by_id["GENERALIZED_SPARSE_IN_DOMAIN"]["routed_strata"],
            ["rare_exact", "exact_absent_in_domain"],
        )
        self.assertEqual(by_id["OOD_ABSTAIN"]["decision_priority"], "P1")

    def test_route_decision_table_is_ordered_and_fail_closed(self):
        table = self.spec["route_decision_table"]
        self.assertEqual([row["row"] for row in table], ["R1", "R2", "R3", "R4"])
        self.assertEqual(table[0]["route_source"], "OOD_ABSTAIN")
        self.assertTrue(table[-1]["fallback"])
        self.assertEqual(table[-1]["route_source"], "OOD_ABSTAIN")

    def test_spec_enumerates_the_stable_pre_action_signals(self):
        signals = {entry["id"]: entry for entry in self.spec["signals"]}
        self.assertEqual(tuple(signals), REQUIRED_SIGNALS)
        for signal_id, entry in signals.items():
            with self.subTest(signal=signal_id):
                self.assertEqual(entry["timing"], "BEFORE_ACTION")
                self.assertTrue(entry["deterministic"])
                self.assertTrue(entry["computable_before_action"])
                self.assertTrue(entry["used_by_route_sources"])
        for categorical in ("family", "actor_position", "aggressor_position"):
            with self.subTest(signal=categorical):
                admissibility = signals[categorical]["admissibility"]
                self.assertTrue(admissibility["requires_cv_justification"])
                self.assertIsInstance(admissibility["cv_justified"], bool)
        for mechanical in ("support_exact", "support_feature_level", "distance_to_domain"):
            with self.subTest(signal=mechanical):
                self.assertFalse(signals[mechanical]["admissibility"]["requires_cv_justification"])

    def test_spec_reuses_the_421_ood_gate_reason_codes(self):
        block = self.spec["reason_codes"]
        self.assertEqual(block["order"], list(grm.OOD_REASON_ORDER))
        self.assertEqual(block["hard"], list(grm.OOD_HARD_REASONS))
        self.assertEqual(block["soft"], list(grm.OOD_SOFT_REASONS))
        self.assertEqual(block["abstaining"], list(grm.OOD_HARD_REASONS))
        self.assertEqual(len(block["catalog"]), len(grm.OOD_REASON_ORDER))
        for entry in block["catalog"]:
            self.assertEqual(entry["abstains"], entry["code"] in grm.OOD_HARD_REASONS)
            self.assertEqual(entry["class"], "hard" if entry["abstains"] else "soft")

    def test_spec_reuses_the_421_strata_and_ood_gate_definitions(self):
        strata = self.spec["strata"]
        self.assertEqual([entry["id"] for entry in strata["strata"]], list(cv.STRATA))
        self.assertEqual(strata["definition"], cv.STRATA_DEFINITION)
        self.assertEqual(
            strata["support_thresholds"]["frequent_exact_min_support"],
            cv.FREQUENT_EXACT_MIN_SUPPORT,
        )
        self.assertEqual(
            strata["support_thresholds"]["rare_exact_min_support"],
            cv.RARE_EXACT_MIN_SUPPORT,
        )
        gate = self.spec["ood_gate"]
        self.assertEqual(gate["schema"], grm.OOD_GATE_SCHEMA)
        self.assertEqual(gate["statuses"], list(grm.OOD_STATUSES))
        self.assertEqual(gate["hard_reason_codes"], list(grm.OOD_HARD_REASONS))
        self.assertFalse(gate["exact_context_absent_in_domain_decisive"])
        gate_schema = json.loads(tool.OOD_GATE_SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            gate["threshold_keys"], list(gate_schema["$defs"]["thresholds"]["required"])
        )

    def test_runtime_contract_declares_every_required_field(self):
        contract = self.spec["runtime_contract"]
        names = [field["name"] for field in contract["fields"]]
        for name in REQUIRED_RUNTIME_FIELDS:
            self.assertIn(name, names)
        by_name = {field["name"]: field for field in contract["fields"]}
        self.assertTrue(by_name["route_source"]["required"])
        self.assertEqual(
            by_name["sizing_provenance"]["required_when"], "selected_action in {RAISE, JAM}"
        )
        self.assertFalse(by_name["sizing_provenance"]["required"])
        self.assertFalse(contract["abstention_contract"]["probabilities_present"])
        self.assertFalse(contract["abstention_contract"]["analysis_admissible"])
        self.assertEqual(contract["sizing_contract"]["required_actions"], ["RAISE", "JAM"])

    def test_procedure_declares_every_required_formula(self):
        procedure = self.spec["procedure"]
        self.assertTrue(procedure["preregistered"])
        self.assertTrue(procedure["registered_before_evaluation"])
        self.assertEqual(procedure["evaluation_basis"], "TRAIN_only_hand_grouped_out_of_fold")
        self.assertFalse(procedure["validation_consumed"])
        self.assertFalse(procedure["test_consumed"])
        self.assertFalse(procedure["terminal_values_persisted"])
        formulas = {formula["id"]: formula for formula in procedure["formulas"]}
        for formula_id in REQUIRED_FORMULAS:
            self.assertIn(formula_id, formulas, formula_id)
        self.assertIn("margin_global", formulas["GLOBAL_NON_INFERIORITY_MARGIN"]["expression"])
        sparse = formulas["SPARSE_GAIN_FLOOR"]
        self.assertEqual(sparse["strata_scope"], ["rare_exact", "exact_absent_in_domain"])
        self.assertIn("n.rare_exact", sparse["expression"])
        self.assertIn("n.exact_absent_in_domain", sparse["expression"])
        self.assertIn("ECE_ABSOLUTE_CEILING", formulas["SPARSE_ECE_CEILING"]["expression"])
        self.assertIn(
            "FREQUENT_EXACT_MAX_DEGRADATION_BITS",
            formulas["FREQUENT_EXACT_NON_DEGRADATION_BOUND"]["expression"],
        )
        abstention = formulas["OOD_ABSTENTION_CRITERION"]
        self.assertIn("hard_reasons", abstention["expression"])
        self.assertIn("soft_reasons", abstention["expression"])

    def test_derivation_order_names_every_formula(self):
        procedure = self.spec["procedure"]
        ids = {formula["id"] for formula in procedure["formulas"]}
        self.assertEqual(set(procedure["derivation_order"]), ids)

    def test_spec_holds_no_terminal_numeric_value(self):
        """Every number is a preregistered constant or a frozen manifest criterion.

        Since #423 T5 the spec also carries the numerically frozen admission
        criteria.  They are not terminal-evaluation values: they are resolved
        from the TRAIN-only cross-fitted derivation and are pinned by the
        router manifest, which is why the guard below allows exactly the
        numbers that appear in that manifest-bound block and nothing else.
        """
        allowed = {entry["value"] for entry in self.spec["procedure"]["constants"]}
        allowed.add(self.spec["issue"])
        frozen = self.spec.get("frozen_criteria")
        self.assertEqual(frozen is not None, tool.FROZEN_MANIFEST_PATH.is_file())
        if frozen is not None:
            manifest = json.loads(tool.FROZEN_MANIFEST_PATH.read_text(encoding="utf-8"))
            self.assertEqual(manifest["frozen_criteria"], frozen)
            self.assertEqual(manifest["frozen_criteria_sha256"], frozen["criteria_sha256"])
            allowed |= {value for _, value in _numbers(frozen)}
        offenders = [
            (path, value) for path, value in _numbers(self.spec) if value not in allowed
        ]
        self.assertEqual(offenders, [])
        self.assertTrue(self.spec["assertions"]["terminal_numeric_values_persisted"] is False)
        self.assertTrue(self.spec["assertions"]["frozen_numeric_criteria_persisted"] == (frozen is not None))
        self.assertTrue(self.spec["assertions"]["train_only"])
        self.assertFalse(self.spec["assertions"]["validation_consumed"])
        self.assertFalse(self.spec["assertions"]["test_consumed"])

    def test_frozen_criteria_are_content_addressed_and_non_terminal(self):
        """The frozen numbers are digest-bound, justified and TRAIN-derived."""
        frozen = self.spec.get("frozen_criteria")
        if frozen is None:  # pragma: no cover - pre-freeze checkout
            self.skipTest("the numeric freeze has not been authored yet")
        manifest = json.loads(tool.FROZEN_MANIFEST_PATH.read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema"], "poker-hybrid-router-criteria-manifest/v1")
        self.assertEqual(manifest["frozen_spec"]["sha256"], self.digest)
        self.assertTrue(manifest["terminal_score_guard"]["terminal_report_absent_at_freeze"])
        self.assertEqual(manifest["frozen_criteria_sha256"], frozen["criteria_sha256"])
        self.assertEqual(frozen["schema"], "poker-hybrid-router-frozen-criteria/v1")
        self.assertFalse(frozen["terminal_evaluation_derived"])
        self.assertEqual(
            [entry["id"] for entry in frozen["criteria"]],
            list(frozen["criteria_order"]),
        )
        for entry in frozen["criteria"]:
            with self.subTest(criterion=entry["id"]):
                self.assertIsInstance(entry["value"], (int, float))
                self.assertFalse(entry["terminal_evaluation_derived"])
                self.assertTrue(entry["justification"])
                self.assertTrue(entry["effectifs"])
                self.assertGreaterEqual(len(entry["inputs"]), 2)
                for item in entry["inputs"]:
                    self.assertIn("source", item)
                    self.assertIn("pointer", item)
        self.assertEqual(
            frozen["procedure_reference"]["spec"],
            "analysis/issue423_hybrid_router/HYBRID_ROUTER_SPEC.json",
        )
        self.assertEqual(frozen["procedure_reference"]["pointer"], "/procedure")

    def test_evidence_bindings_are_content_addressed(self):
        bindings = {entry["role"]: entry for entry in self.spec["evidence_bindings"]}
        self.assertEqual(
            bindings["train_out_of_fold_cv_report"]["sha256"],
            tool.sha256_file(tool.CV_REPORT_PATH),
        )
        self.assertEqual(
            bindings["ood_gate_contract_schema"]["sha256"],
            hashlib.sha256(tool.OOD_GATE_SCHEMA_PATH.read_bytes()).hexdigest(),
        )
        for entry in bindings.values():
            with self.subTest(role=entry["role"]):
                self.assertRegex(entry["sha256"], r"^[0-9a-f]{64}$")
                self.assertFalse(entry["path"].startswith("/"))

    def test_generator_source_has_no_holdout_loader(self):
        scan = tool.verify_no_holdout_access()
        self.assertEqual(scan["result"], "PASS")
        self.assertEqual(scan["hits"], [])


class GeneratorTests(unittest.TestCase):
    def test_two_runs_are_byte_identical(self):
        with tempfile.TemporaryDirectory() as first:
            with _IsolatedLayout(Path(first)):
                tool.write_spec()
                first_bytes = tool.SPEC_PATH.read_bytes()
                first_sidecar = tool.DIGEST_PATH.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as second:
            with _IsolatedLayout(Path(second)):
                tool.write_spec()
                second_bytes = tool.SPEC_PATH.read_bytes()
                second_sidecar = tool.DIGEST_PATH.read_text(encoding="utf-8")
        self.assertEqual(first_bytes, second_bytes)
        self.assertEqual(first_sidecar, second_sidecar)
        self.assertEqual(first_bytes, tool.SPEC_PATH.read_bytes())

    def test_check_mode_passes_on_the_persisted_artifacts(self):
        self.assertEqual(tool.check(), [])

    def test_generator_refuses_the_validation_split(self):
        with self.assertRaises(tool.HybridRouterSpecError):
            tool.build_spec(consumed_splits=("TRAIN", "VALIDATION"))

    def test_generator_refuses_the_test_split(self):
        with self.assertRaises(tool.HybridRouterSpecError):
            tool.build_spec(consumed_splits=("TEST",))

    def test_generator_refuses_an_empty_split(self):
        with self.assertRaises(tool.HybridRouterSpecError):
            tool.build_spec(consumed_splits=())

    def test_generator_refuses_a_report_that_consumed_validation(self):
        report = copy.deepcopy(tool.load_train_cv_report())
        report["scope"]["validation_consumed"] = True
        with self.assertRaises(tool.HybridRouterSpecError):
            tool.build_spec(report=report)

    def test_generator_refuses_a_report_that_consumed_test(self):
        report = copy.deepcopy(tool.load_train_cv_report())
        report["scope"]["test_consumed"] = True
        with self.assertRaises(tool.HybridRouterSpecError):
            tool.build_spec(report=report)

    def test_generator_refuses_a_report_declaring_a_holdout_split(self):
        report = copy.deepcopy(tool.load_train_cv_report())
        report["scope"]["consumed_splits"] = ["TRAIN", "TEST"]
        with self.assertRaises(tool.HybridRouterSpecError):
            tool.build_spec(report=report)

    def test_altered_formula_changes_the_digest(self):
        baseline = tool.build_spec()
        baseline_digest = tool.spec_digest(baseline)
        altered_library = tool.build_formulas()
        altered_library[2]["expression"] = altered_library[2]["expression"].replace("/", "-")
        altered = tool.build_spec(formulas=altered_library)
        self.assertNotEqual(tool.spec_digest(altered), baseline_digest)
        self.assertNotEqual(
            altered["procedure"]["formulas"][2]["expression"],
            baseline["procedure"]["formulas"][2]["expression"],
        )
        # The internal mirror is never persisted: the frozen spec stays clean.
        self.assertNotIn("_machine", baseline["procedure"]["formulas"][2])

    def test_altered_formula_changes_the_traced_evaluation(self):
        report = tool.load_train_cv_report()
        baseline = tool.evaluate_train_only(report)["SPARSE_GAIN_FLOOR"]
        self.assertTrue(baseline["evaluable"])
        altered_library = tool.build_formulas()
        formula = next(item for item in altered_library if item["id"] == "SPARSE_GAIN_FLOOR")
        formula["_machine"]["value"]["values"] = [
            tool.sym("gain.rare_exact"),
            tool.sym("gain.rare_exact"),
        ]
        altered = tool.evaluate_train_only(report, altered_library)["SPARSE_GAIN_FLOOR"]
        self.assertNotEqual(altered["value"], baseline["value"])

    def test_admission_only_formulas_are_declared_not_evaluated_on_train(self):
        evaluation = tool.evaluate_train_only(tool.load_train_cv_report())
        self.assertTrue(evaluation["SPARSE_GAIN_FLOOR"]["evaluable"])
        self.assertTrue(evaluation["SPARSE_ECE_MEASUREMENT"]["evaluable"])
        self.assertFalse(evaluation["GLOBAL_NON_INFERIORITY_MARGIN"]["evaluable"])
        self.assertFalse(evaluation["FREQUENT_EXACT_NON_DEGRADATION_BOUND"]["evaluable"])

    def test_sparse_ece_floor_uses_only_the_two_covered_strata(self):
        formulas = {item["id"]: item for item in tool.build_formulas()}
        for formula_id in ("SPARSE_GAIN_FLOOR", "SPARSE_ECE_MEASUREMENT"):
            with self.subTest(formula=formula_id):
                scope = formulas[formula_id]["strata_scope"]
                self.assertEqual(scope, ["rare_exact", "exact_absent_in_domain"])
                self.assertNotIn("exact_absent_out_of_domain", scope)

    def test_write_spec_is_isolated_and_reproducible(self):
        with tempfile.TemporaryDirectory() as tmp:
            with _IsolatedLayout(Path(tmp)):
                digest = tool.write_spec()
                self.assertEqual(tool.check(), [])
                self.assertEqual(
                    digest, hashlib.sha256(tool.SPEC_PATH.read_bytes()).hexdigest()
                )


if __name__ == "__main__":
    unittest.main()

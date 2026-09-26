#!/usr/bin/env python3
"""#421 guard: candidate manifest and hash-frozen VALIDATION protocol.

Covers every acceptance criterion of the task:

* the protocol is frozen by hash with ``status == FROZEN_BEFORE_VALIDATION``:
  its byte digest is pinned in a sidecar and in the content-addressed bundle,
  and the canonical payload digest is the frozen identity;
* the minimum product coverage is registered at ``>= 0.50``, together with the
  non-inferiority rule, the maximum allowed calibration and the raise-sizing
  criteria;
* any drift of the candidate, the manifest or the protocol is fail-closed: a
  mutated candidate aborts the build, a mutated manifest or protocol makes the
  check exit non-zero, and the manifest/protocol binding is re-asserted;
* no threshold can be changed after a VALIDATION read: the immutability guard
  is documented in the protocol, the authoring order records zero VALIDATION
  reads, and a threshold mutation is detected by a fresh rebuild.

``jsonschema`` is not a declared dependency of this repository, so the contract
is checked with the same explicit, reviewable keyword subset the sibling #421
guards use.
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training import freeze_generalized_validation_protocol as tool  # noqa: E402

MANIFEST_PATH = tool.MANIFEST_PATH
PROTOCOL_PATH = tool.PROTOCOL_PATH
SCHEMA_PATH = tool.SCHEMA_PATH


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
    """Minimal deterministic JSON-Schema checker for the contract keyword subset."""
    schema = _resolve_ref(schema, root)
    if "oneOf" in schema:
        matches = 0
        for candidate in schema["oneOf"]:
            try:
                validate(value, candidate, root, path)
            except AssertionError:
                continue
            matches += 1
        if matches != 1:
            raise AssertionError(f"{path}: expected exactly one oneOf branch, got {matches}")
        return
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
        if schema.get("uniqueItems"):
            rendered = {json.dumps(x, sort_keys=True) for x in value}
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


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class _Buffer:
    def __init__(self):
        self._chunks: list[str] = []

    def write(self, text: str) -> None:
        self._chunks.append(text)

    def flush(self) -> None:
        return None

    def getvalue(self) -> str:
        return "".join(self._chunks)


@contextlib.contextmanager
def isolated_layout(tmp: Path):
    """Redirect every artifact the tool writes into ``tmp``."""
    bundle = tmp / "validation_protocol"
    patches = [
        mock.patch.object(tool, "MANIFEST_PATH", tmp / "CANDIDATE_MANIFEST.json"),
        mock.patch.object(tool, "MANIFEST_DIGEST_PATH", tmp / "CANDIDATE_MANIFEST.sha256"),
        mock.patch.object(tool, "PROTOCOL_PATH", tmp / "FROZEN_VALIDATION_PROTOCOL.json"),
        mock.patch.object(tool, "PROTOCOL_DIGEST_PATH", tmp / "FROZEN_VALIDATION_PROTOCOL.sha256"),
        mock.patch.object(tool, "BUNDLE", bundle),
        mock.patch.object(tool, "BUNDLE_INDEX", bundle / "ARTIFACTS.json"),
    ]
    for patch in patches:
        patch.start()
    try:
        yield tmp
    finally:
        for patch in reversed(patches):
            patch.stop()


class PersistedArtifacts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        cls.protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
        cls.contract = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.manifest_bytes = MANIFEST_PATH.read_bytes()
        cls.protocol_bytes = PROTOCOL_PATH.read_bytes()

    def test_manifest_satisfies_the_contract(self):
        validate(self.manifest, self.contract, self.contract)

    def test_protocol_satisfies_the_contract(self):
        validate(self.protocol, self.contract, self.contract)

    def test_contract_rejects_a_desynchronised_payload(self):
        broken = copy.deepcopy(self.manifest)
        broken["status"] = "VALIDATION_READ"
        with self.assertRaises(AssertionError):
            validate(broken, self.contract, self.contract)

    def test_protocol_is_frozen_before_validation(self):
        self.assertEqual(self.protocol["status"], "FROZEN_BEFORE_VALIDATION")
        self.assertEqual(self.protocol["kind"], "FROZEN_VALIDATION_PROTOCOL")
        self.assertEqual(self.protocol["schema"], "poker-generalized-frozen-validation-protocol/v1")
        self.assertEqual(self.manifest["status"], "FROZEN_BEFORE_VALIDATION")
        authoring = self.protocol["authoring_order"]
        self.assertTrue(authoring["protocol_written_and_hashed_before_validation_read"])
        self.assertFalse(authoring["validation_read_before_protocol_hash"])
        self.assertTrue(self.protocol["canonical_payload_is_the_frozen_identity"])

    def test_protocol_byte_digest_is_pinned(self):
        digest = sha256_bytes(self.protocol_bytes)
        sidecar = tool.PROTOCOL_DIGEST_PATH.read_text(encoding="utf-8")
        self.assertTrue(sidecar.startswith(f"{digest}  {tool.PROTOCOL_NAME}"))
        index = json.loads(tool.BUNDLE_INDEX.read_text(encoding="utf-8"))
        entry = index[tool.PROTOCOL_NAME]
        self.assertEqual(entry["sha256"], digest)
        self.assertEqual(entry["canonical_payload_sha256"], tool.canonical_hash(self.protocol))
        self.assertEqual((tool.BUNDLE / entry["object"]).read_bytes(), self.protocol_bytes)

    def test_protocol_is_bound_to_the_manifest_and_the_candidate(self):
        bound = self.protocol["artifacts"]["candidate_manifest"]
        self.assertEqual(bound["sha256"], sha256_bytes(self.manifest_bytes))
        self.assertEqual(bound["canonical_payload_sha256"], tool.canonical_hash(self.manifest))
        self.assertEqual(
            self.protocol["artifacts"]["candidate"]["canonical_payload_sha256"],
            self.manifest["candidate"]["canonical_payload_sha256"],
        )
        tool.assert_manifest_protocol_consistency(self.manifest, self.protocol)

    def test_canonical_candidate_hash_is_reproducible(self):
        candidate = json.loads(tool.CANDIDATE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            tool.canonical_hash(tool._candidate_payload(candidate)), tool.CANDIDATE_CANONICAL_SHA256
        )
        self.assertEqual(
            self.manifest["candidate"]["canonical_payload_sha256"], tool.CANDIDATE_CANONICAL_SHA256
        )
        self.assertEqual(tool.sha256_file(tool.CANDIDATE_PATH), tool.CANDIDATE_SHA256)

    def test_minimum_product_coverage_is_registered_at_fifty_percent(self):
        floor = self.protocol["coverage_floor"]
        self.assertGreaterEqual(floor["minimum_coverage"], 0.50)
        self.assertEqual(
            floor["minimum_coverage"], self.manifest["thresholds"]["coverage"]["minimum_coverage"]
        )
        self.assertTrue(floor["coverage_is_an_admission_gate"])
        self.assertIn('"minimum_coverage": 0.5', self.protocol_bytes.decode("utf-8"))
        self.assertIn('"minimum_coverage": 0.5', self.manifest_bytes.decode("utf-8"))

    def test_non_inferiority_calibration_and_sizing_are_registered(self):
        rule = self.protocol["non_inferiority_rule"]
        self.assertLessEqual(rule["ci_upper_bound"], 0.0)
        self.assertEqual(rule["paired_unit"], "hand_id")
        self.assertGreaterEqual(len(rule["comparisons"]), 3)
        self.assertEqual(rule, self.manifest["non_inferiority_rule"])
        self.assertEqual(rule, self.protocol["thresholds"]["non_inferiority"])

        calibration = self.protocol["calibration_max"]
        self.assertLessEqual(calibration["maximum_absolute_ece"], 0.05)
        self.assertLessEqual(calibration["maximum_ece_delta_vs_active"], 0.02)
        self.assertEqual(calibration, self.manifest["calibration_max"])

        sizing = self.protocol["sizing_criteria"]
        self.assertEqual(sizing["maximum_illegal_generated_rate"], 0.0)
        self.assertTrue(sizing["no_nearest_price_substitution"])
        self.assertTrue(sizing["no_nearest_context_substitution"])
        self.assertEqual(sizing, self.manifest["sizing_criteria"])

    def test_thresholds_are_frozen_and_immutable_after_validation(self):
        thresholds = self.protocol["thresholds"]
        self.assertTrue(thresholds["frozen"])
        self.assertTrue(thresholds["immutable_after_validation_read"])
        self.assertEqual(thresholds, self.manifest["thresholds"])
        immutability = self.protocol["immutability"]
        self.assertTrue(immutability["frozen"])
        self.assertTrue(immutability["immutable_after_validation_read"])
        self.assertTrue(immutability["thresholds_unmodifiable_after_validation_read"])
        self.assertTrue(immutability["guard_rule"])
        self.assertTrue(immutability["detection"])

    def test_no_validation_row_was_read_while_authoring(self):
        boundary = self.protocol["holdout_boundary"]
        self.assertFalse(boundary["validation_consumed_for_authoring"])
        self.assertEqual(boundary["validation_decisions_read"], 0)
        self.assertEqual(boundary["validation_hands_parsed"], 0)
        self.assertFalse(boundary["test_consumed"])
        self.assertFalse(self.manifest["corpus"]["validation_consumed_for_authoring"])
        self.assertFalse(self.manifest["corpus"]["test"]["consumed"])
        prior = boundary["prior_validation_reads"]
        self.assertEqual(len(prior), 1)
        self.assertFalse(prior[0]["authoritative_for_admission"])
        self.assertFalse(prior[0]["used_for_thresholds"])
        self.assertFalse(prior[0]["used_for_candidate_selection"])

    def test_number_of_367_rule_is_registered(self):
        rule = self.protocol["issue367_rule"]
        self.assertEqual(rule["rule_id"], "ISSUE367_CONSUMES_ONLY_AN_ADMITTED_CANDIDATE")
        self.assertFalse(rule["authorized_at_freeze"])
        self.assertEqual(rule, self.manifest["issue367_consumption_rule"])
        active = dict(self.manifest["active_references"]["admitted_model_a_candidate_for_367"])
        active.pop("mutated_by_this_freeze")
        self.assertEqual(rule["currently_admitted_model_a_for_367"], active)

    def test_check_returns_zero_on_the_persisted_artifacts(self):
        stream = _Buffer()
        with contextlib.redirect_stdout(stream):
            code = tool.check()
        self.assertEqual(code, 0)
        payload = json.loads(stream.getvalue())
        self.assertEqual(payload["status"], "OK")
        self.assertEqual(payload["status_field"], "FROZEN_BEFORE_VALIDATION")
        self.assertGreaterEqual(payload["minimum_coverage"], 0.50)

    def test_cli_check_exits_zero(self):
        result = subprocess.run(
            [sys.executable, "tools/training/freeze_generalized_validation_protocol.py", "--check"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('"status": "OK"', result.stdout)

    def test_ast_self_scan_is_clean(self):
        scan = tool.static_holdout_scan()
        self.assertEqual(scan["result"], "PASS")
        self.assertEqual(scan["hits"], [])


class DriftIsFailClosed(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.layout = isolated_layout(self.tmp)
        self.layout.__enter__()
        self.addCleanup(self._teardown)

    def _teardown(self):
        with contextlib.suppress(Exception):
            self.layout.__exit__(None, None, None)
        self._tmp.cleanup()

    def _write_reference_layout(self) -> dict:
        return tool.persist()

    def test_isolated_layout_reproduces_the_persisted_bytes(self):
        index = self._write_reference_layout()
        self.assertEqual(
            index[tool.PROTOCOL_NAME]["sha256"], sha256_bytes(PROTOCOL_PATH.read_bytes())
        )
        self.assertEqual(
            index[tool.MANIFEST_NAME]["sha256"], sha256_bytes(MANIFEST_PATH.read_bytes())
        )
        self.assertEqual(tool.PROTOCOL_PATH.read_bytes(), PROTOCOL_PATH.read_bytes())
        self.assertEqual(tool.MANIFEST_PATH.read_bytes(), MANIFEST_PATH.read_bytes())
        stream = _Buffer()
        with contextlib.redirect_stdout(stream):
            self.assertEqual(tool.check(), 0)
        self.assertEqual(json.loads(stream.getvalue())["status"], "OK")

    def test_mutated_candidate_aborts_the_build(self):
        drifted = self.tmp / "candidate.json"
        drifted.write_bytes(tool.CANDIDATE_PATH.read_bytes().replace(b'"seed": 421', b'"seed": 999'))
        with mock.patch.object(tool, "CANDIDATE_PATH", drifted):
            with self.assertRaises(tool.ProtocolError):
                tool.build()

    def test_mutated_manifest_is_detected(self):
        self._write_reference_layout()
        payload = json.loads(tool.MANIFEST_PATH.read_bytes())
        payload["status"] = "VALIDATION_READ"
        tool.MANIFEST_PATH.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")
        stream = _Buffer()
        with contextlib.redirect_stdout(stream):
            self.assertEqual(tool.check(), 1)
        problems = json.loads(stream.getvalue())["problems"]
        self.assertTrue(any("manifest" in problem for problem in problems))

    def test_mutated_coverage_threshold_in_the_protocol_is_detected(self):
        self._write_reference_layout()
        payload = json.loads(tool.PROTOCOL_PATH.read_bytes())
        payload["thresholds"]["coverage"]["minimum_coverage"] = 0.20
        tool.PROTOCOL_PATH.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")
        stream = _Buffer()
        with contextlib.redirect_stdout(stream):
            self.assertEqual(tool.check(), 1)
        problems = json.loads(stream.getvalue())["problems"]
        self.assertTrue(any("protocol" in problem for problem in problems))

    def test_mutated_maximum_ece_in_the_protocol_is_detected(self):
        self._write_reference_layout()
        payload = json.loads(tool.PROTOCOL_PATH.read_bytes())
        payload["thresholds"]["calibration"]["maximum_absolute_ece"] = 0.50
        tool.PROTOCOL_PATH.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")
        stream = _Buffer()
        with contextlib.redirect_stdout(stream):
            self.assertEqual(tool.check(), 1)
        self.assertTrue(json.loads(stream.getvalue())["problems"])

    def test_manifest_protocol_binding_rejects_divergence(self):
        manifest, protocol = tool.build()
        broken = copy.deepcopy(manifest)
        broken["thresholds"]["coverage"]["minimum_coverage"] = 0.10
        with self.assertRaises(tool.ProtocolError):
            tool.assert_manifest_protocol_consistency(broken, protocol)
        broken_protocol = copy.deepcopy(protocol)
        broken_protocol["coverage_floor"] = dict(broken_protocol["coverage_floor"])
        broken_protocol["coverage_floor"]["minimum_coverage"] = 0.10
        with self.assertRaises(tool.ProtocolError):
            tool.assert_manifest_protocol_consistency(manifest, broken_protocol)

    def test_guard_rejects_a_protocol_whose_floor_fell_below_the_minimum(self):
        manifest, protocol = tool.build()
        drifted = copy.deepcopy(protocol)
        drifted["coverage_floor"] = dict(drifted["coverage_floor"], minimum_coverage=0.49)
        with self.assertRaises(tool.ProtocolError):
            tool.assert_manifest_protocol_consistency(manifest, drifted)

    def test_fenced_validation_result_blocks_the_freeze(self):
        result_dir = self.tmp / "validation"
        result_dir.mkdir(parents=True, exist_ok=True)
        result_path = result_dir / "VALIDATION_RESULT.json"
        result_path.write_text("{}\n")
        locations = (result_path, result_dir / "FROZEN_VALIDATION_RESULT.json")
        with mock.patch.object(tool, "DECLARED_RESULT_LOCATIONS", locations):
            with self.assertRaises(tool.ProtocolError):
                tool.assert_fenced_validation_not_yet_consumed()
            with self.assertRaises(tool.ProtocolError):
                tool.build()

    def test_build_is_byte_reproducible(self):
        first_manifest, first_protocol = tool.build(frozen_at="2026-09-26T00:00:00Z")
        second_manifest, second_protocol = tool.build(frozen_at="2026-09-26T00:00:00Z")
        self.assertEqual(tool.serialize(first_manifest), tool.serialize(second_manifest))
        self.assertEqual(tool.serialize(first_protocol), tool.serialize(second_protocol))


class FrozenInputsAreVerified(unittest.TestCase):
    def test_every_pinned_input_digest_is_re_verified(self):
        inputs = tool.verify_inputs()
        self.assertEqual(inputs["candidate"]["architecture"], tool.CANDIDATE_ARCHITECTURE)
        self.assertEqual(tool.sha256_file(tool.DATASET_PATH), tool.DATASET_SHA256)
        for path, digest in (
            (tool.CANDIDATE_PATH, tool.CANDIDATE_SHA256),
            (tool.MODEL_CONTRACT_PATH, tool.MODEL_CONTRACT_SHA256),
            (tool.OOD_CONTRACT_PATH, tool.OOD_CONTRACT_SHA256),
            (tool.DATASET_CONTRACT_PATH, tool.DATASET_CONTRACT_SHA256),
            (tool.ISSUE419_PROTOCOL_PATH, tool.ISSUE419_PROTOCOL_SHA256),
        ):
            self.assertEqual(tool.sha256_file(path), digest)

    def test_a_drifted_pinned_input_is_refused(self):
        with mock.patch.object(tool, "CANDIDATE_SHA256", "0" * 64):
            with self.assertRaises(tool.ProtocolError):
                tool.verify_inputs()


if __name__ == "__main__":
    unittest.main()

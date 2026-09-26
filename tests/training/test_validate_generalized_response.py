#!/usr/bin/env python3
"""#421 T8 regressions: the one-shot VALIDATION evaluation and its terminal decision.

These tests never re-parse a holdout hand.  They pin the content-addressed
``VALIDATION_RESULT.json`` / ``DECISION.json``, the frozen protocol digests the
result embeds, the three explicit references, the coverage / calibration /
strata surfaces, the ten admission criteria and the terminal boundaries
(``active_pointer_mutated=false``, ``test_consumed=false``), plus the fail-closed
guards that keep TEST out and keep a second VALIDATION read impossible.
"""
from __future__ import annotations

import contextlib
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

from tools.preflop import generalized_response_model as model  # noqa: E402
from tools.training import freeze_generalized_validation_protocol as freeze  # noqa: E402
from tools.training import validate_generalized_response as tool  # noqa: E402

DATASET = ROOT / "analysis/issue421_generalized_response/dataset/GENERALIZED_RESPONSE_DATASET.jsonl"


class GeneralizedValidationEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result_bytes = tool.RESULT_PATH.read_bytes()
        cls.result = json.loads(cls.result_bytes)
        cls.decision_bytes = tool.DECISION_PATH.read_bytes()
        cls.decision = json.loads(cls.decision_bytes)
        cls.protocol = json.loads(tool.PROTOCOL_PATH.read_text())

    # ------------------------------------------------------------------ guards
    def test_self_scan_forbids_every_test_loader_symbol(self):
        scan = tool.verify_no_test_loader()
        self.assertEqual(scan["result"], "PASS")
        self.assertEqual(scan["hits"], [])
        self.assertEqual(
            sorted(scan["forbidden_symbols"]), sorted(tool.FORBIDDEN_TEST_LOADER_SYMBOLS)
        )
        #: the scan is a real AST scan, not a text match: the constant tuple is
        #: allowed to name the symbols, an actual use is not.
        import ast

        used = set()
        for node in ast.walk(ast.parse(Path(tool.__file__).read_text())):
            if isinstance(node, ast.Name):
                used.add(node.id)
            elif isinstance(node, ast.Attribute):
                used.add(node.attr)
        self.assertEqual(sorted(used & set(tool.FORBIDDEN_TEST_LOADER_SYMBOLS)), [])

    def test_protocol_is_pinned_and_unmoved(self):
        guard = tool.verify_protocol_frozen_before_validation()
        self.assertEqual(guard["result"], "PASS")
        self.assertEqual(guard["protocol_byte_sha256"], tool.EXPECTED_PROTOCOL_BYTE_SHA256)
        self.assertEqual(
            guard["protocol_canonical_payload_sha256"],
            tool.EXPECTED_PROTOCOL_CANONICAL_PAYLOAD_SHA256,
        )
        self.assertEqual(
            tool.sha256_file(tool.PROTOCOL_PATH), tool.EXPECTED_PROTOCOL_BYTE_SHA256
        )
        self.assertEqual(
            tool.canonical_hash(self.protocol),
            tool.EXPECTED_PROTOCOL_CANONICAL_PAYLOAD_SHA256,
        )

    def test_a_mutated_protocol_is_refused_before_the_read(self):
        mutated = dict(self.protocol)
        mutated["coverage_floor"] = dict(
            self.protocol["coverage_floor"], minimum_coverage=0.01
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "FROZEN_VALIDATION_PROTOCOL.json"
            path.write_text(json.dumps(mutated, sort_keys=True, indent=2) + "\n")
            with mock.patch.object(tool, "PROTOCOL_PATH", path):
                with self.assertRaises(tool.ValidationExecutionError):
                    tool.verify_protocol_frozen_before_validation()

    def test_order_guard_fails_closed_when_a_fenced_result_exists(self):
        with mock.patch.object(
            tool,
            "GUARD_DECLARED_RESULT_LOCATIONS",
            ("analysis/issue421_generalized_response/VALIDATION_RESULT.json",),
        ):
            with self.assertRaises(tool.ValidationExecutionError):
                tool.verify_protocol_frozen_before_validation()

    def test_the_validation_read_is_one_shot(self):
        with tempfile.TemporaryDirectory() as directory:
            result = Path(directory) / "VALIDATION_RESULT.json"
            result.write_text("{}")
            with mock.patch.object(tool, "RESULT_PATH", result):
                with self.assertRaises(tool.ValidationExecutionError):
                    tool.assert_result_not_yet_persisted()

    def test_the_declared_fenced_locations_are_empty(self):
        for relative in tool.GUARD_DECLARED_RESULT_LOCATIONS:
            self.assertFalse((ROOT / relative).is_file(), relative)

    def test_test_split_is_refused_dynamically(self):
        with self.assertRaises(Exception):
            model.read_dataset_rows(DATASET, splits=["TEST"])
        candidate = tool.load_candidate()
        test_row = {
            "hand_id": "x",
            "split": "TEST",
            "family": "UNOPENED",
            "actor_position": "LJ",
            "table_size": 6,
            "to_call_bb": 1.0,
            "pot_before_bb": 1.5,
            "effective_stack_bb": 100.0,
        }
        with self.assertRaises(Exception):
            model.predict(candidate, test_row)

    def test_the_frozen_protocol_still_rebuilds(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = freeze.check()
        self.assertEqual(code, 0, buffer.getvalue())
        self.assertEqual(
            freeze.sha256_file(tool.PROTOCOL_PATH), tool.EXPECTED_PROTOCOL_BYTE_SHA256
        )

    # ------------------------------------------------------------- artifacts
    def test_the_artifacts_are_persisted_and_self_consistent(self):
        self.assertTrue(tool.RESULT_PATH.is_file())
        self.assertTrue(tool.DECISION_PATH.is_file())
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = tool.check()
        self.assertEqual(code, 0, buffer.getvalue())
        self.assertEqual(self.result["schema"], tool.RESULT_SCHEMA)
        self.assertEqual(self.decision["schema"], tool.DECISION_SCHEMA)
        body = {
            key: value
            for key, value in self.result.items()
            if key != "canonical_payload_sha256"
        }
        self.assertEqual(self.result["canonical_payload_sha256"], tool.canonical_hash(body))
        decision_body = {
            key: value
            for key, value in self.decision.items()
            if key != "canonical_payload_sha256"
        }
        self.assertEqual(
            self.decision["canonical_payload_sha256"], tool.canonical_hash(decision_body)
        )
        digest = hashlib.sha256(self.result_bytes).hexdigest()
        self.assertEqual(
            self.decision["validation_result_sha256"], digest
        )
        self.assertEqual(
            tool.RESULT_DIGEST_PATH.read_text().splitlines()[0].split(),
            [digest, "VALIDATION_RESULT.json"],
        )
        self.assertEqual(
            tool.DECISION_DIGEST_PATH.read_text().splitlines()[0].split(),
            [hashlib.sha256(self.decision_bytes).hexdigest(), "DECISION.json"],
        )

    def test_check_detects_a_tampered_gate(self):
        tampered = json.loads(json.dumps(self.result))
        for gate in tampered["gates"].values():
            gate["passed"] = True
        #: keep the payload self-consistent so the *decision* check is the one
        #: that has to catch the tamper, not merely the digest.
        tampered["canonical_payload_sha256"] = tool.canonical_hash(
            {key: value for key, value in tampered.items() if key != "canonical_payload_sha256"}
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "VALIDATION_RESULT.json"
            path.write_text(json.dumps(tampered, sort_keys=True, indent=2) + "\n")
            buffer = io.StringIO()
            with mock.patch.object(tool, "RESULT_PATH", path):
                with mock.patch.object(
                    tool, "RESULT_DIGEST_PATH", Path(directory) / "missing.sha256"
                ):
                    with contextlib.redirect_stdout(buffer):
                        code = tool.check()
            self.assertEqual(code, 1)
            self.assertIn("outcome does not follow from the persisted gates", buffer.getvalue())

    # ------------------------------------------------- the VALIDATION read
    def test_validation_was_opened_once_and_test_never(self):
        read = self.result["validation_read"]
        self.assertEqual(read["split"], "VALIDATION")
        self.assertEqual(read["reads"], 1)
        self.assertEqual(self.result["validation_reads"], 1)
        self.assertEqual(read["rows"], tool.EXPECTED_VALIDATION_ROWS)
        self.assertEqual(read["distinct_hands"], tool.EXPECTED_VALIDATION_HANDS)
        self.assertEqual(
            read["hand_ids_fingerprint_sha256"],
            tool.EXPECTED_VALIDATION_HANDS_FINGERPRINT,
        )
        self.assertEqual(read["test_rows_seen"], 0)
        self.assertFalse(read["test_consumed"])
        self.assertFalse(self.result["test_consumed"])
        self.assertFalse(self.result["test_authorized"])
        self.assertFalse(self.decision["test_consumed"])
        self.assertEqual(self.result["test_scan"]["result"], "PASS")

    def test_the_read_is_the_registered_fold_of_the_frozen_manifest(self):
        manifest = json.loads(tool.DATASET_MANIFEST_PATH.read_text())
        self.assertEqual(
            tool.sha256_file(tool.DATASET_PATH), tool.EXPECTED_DATASET_SHA256
        )
        self.assertEqual(manifest["dataset"]["sha256"], tool.EXPECTED_DATASET_SHA256)
        self.assertEqual(manifest["dataset"]["rows"], tool.EXPECTED_DATASET_ROWS)
        split = manifest["splits"]["VALIDATION"]
        self.assertEqual(split["response_rows"], tool.EXPECTED_VALIDATION_ROWS)
        self.assertEqual(split["hands"], tool.EXPECTED_VALIDATION_HANDS)

    # ---------------------------------------------------------- references
    def test_the_three_references_are_present_and_unmoved(self):
        active = self.result["inputs"]["active_model_a_v5"]
        self.assertEqual(
            tool.sha256_file(tool.ACTIVE_MODEL_A_PATH), tool.EXPECTED_ACTIVE_MODEL_A_SHA256
        )
        self.assertEqual(active["sha256"], tool.EXPECTED_ACTIVE_MODEL_A_SHA256)
        self.assertTrue(active["unchanged_during_evaluation"])
        v2 = self.result["inputs"]["model_a_sizing_aware_v2_352"]
        self.assertEqual(v2["candidate_sha256"], tool.EXPECTED_ISSUE352_CANDIDATE_SHA256)
        self.assertEqual(
            v2["validation_evidence_sha256"],
            tool.EXPECTED_ISSUE352_VALIDATION_EVIDENCE_SHA256,
        )
        self.assertFalse(v2["test_consumed"])
        candidate = self.result["inputs"]["candidate"]
        self.assertEqual(
            candidate["canonical_payload_sha256"],
            tool.EXPECTED_CANDIDATE_CANONICAL_SHA256,
        )
        values = self.result["metrics"]["primary"]["values"]
        for label in (
            "candidate_generalized",
            "active_model_a_v5",
            "model_a_preflop_sizing_aware_candidate_v2",
        ):
            self.assertIn(label, values)
            self.assertIsNotNone(values[label])
        self.assertIn("candidate_minus_active_model_a_v5", self.result["comparisons"])
        self.assertIn(
            "candidate_minus_model_a_preflop_sizing_aware_candidate_v2",
            self.result["comparisons"],
        )
        self.assertEqual(
            sorted(self.decision["references"]),
            ["active_model_a_v5", "candidate_generalized", "model_a_sizing_aware_candidate_v2_352"],
        )
        self.assertEqual(len(self.decision["comparisons_present"]), 4)

    def test_active_pointer_is_never_mutated(self):
        self.assertFalse(self.result["active_pointer_mutated"])
        self.assertFalse(self.result["active_pointer_mutation"])
        self.assertFalse(self.decision["active_pointer_mutated"])
        self.assertFalse(self.decision["active_model_pointer_mutation"])
        self.assertEqual(self.decision["automatic_promotion"], "FORBIDDEN")
        self.assertEqual(
            self.result["active_pointer_mutation"],
            self.decision["active_model_pointer_mutation"],
        )

    # ------------------------------------------------- coverage / calibration
    def test_coverage_surface_is_reported(self):
        coverage = self.result["metrics"]["coverage"]
        self.assertEqual(coverage["universe_rows"], tool.EXPECTED_VALIDATION_ROWS)
        self.assertIsNotNone(coverage["coverage"])
        self.assertIsNotNone(coverage["abstain_rate"])
        self.assertEqual(
            coverage["answered_decisions"] + coverage["abstained_decisions"],
            coverage["universe_rows"],
        )
        self.assertIsNotNone(coverage["limiters_vs_iso"])
        self.assertEqual(
            sorted(coverage["by_position"]),
            ["BB", "BTN", "CO", "HJ", "LJ", "SB"],
        )
        for row in coverage["by_position"].values():
            self.assertIsNotNone(row["coverage"])
            self.assertIsNotNone(row["abstain_rate"])
        self.assertIn("LIMPER_VS_ISO", coverage["by_family"])
        for status in model.OOD_STATUSES:
            self.assertIn(status, coverage["ood_status_counts"])

    def test_calibration_is_reported_globally_by_family_and_strata(self):
        calibration = self.result["metrics"]["expected_calibration_error"]
        self.assertEqual(calibration["method"], "equal_count_reliability_bins")
        self.assertEqual(calibration["bins_per_action_class"], 10)
        for label in tool.MODEL_LABELS:
            self.assertIn(label, calibration["global"])
            self.assertIn(label, calibration["detail"])
            self.assertEqual(calibration["detail"][label]["bins_per_action_class"], 10)
        paired = calibration["frozen_ceiling_comparison_on_paired_support"]
        self.assertEqual(
            paired["rows"], self.result["evaluation_universe"]["paired_rows_active"]
        )
        for family, block in self.result["metrics"]["by_family"].items():
            self.assertIn("expected_calibration_error", block["answered_metrics"], family)
        strata = self.result["metrics"]["strata"]
        for name in model.OOD_STRATA:
            self.assertIn(name, strata["strata"])
            self.assertIn("answered_metrics", strata["strata"][name])

    def test_the_strata_partition_the_read(self):
        strata = self.result["metrics"]["strata"]
        self.assertEqual(sorted(strata["counts"]), sorted(model.OOD_STRATA))
        self.assertEqual(sum(strata["counts"].values()), tool.EXPECTED_VALIDATION_ROWS)
        self.assertAlmostEqual(sum(strata["share"].values()), 1.0, places=9)

    # -------------------------------------------------------------- decision
    def test_the_ten_frozen_criteria_are_persisted(self):
        gates = self.result["gates"]
        self.assertEqual(len(gates), 10)
        self.assertEqual(self.result["gate"]["criteria_total"], 10)
        failed = [gate_id for gate_id, gate in gates.items() if not gate["passed"]]
        self.assertEqual(sorted(failed), sorted(self.result["gate"]["failed"]))
        self.assertEqual(
            self.result["gate"]["criteria_passed"], 10 - len(failed)
        )
        for gate in gates.values():
            self.assertIsInstance(gate["passed"], bool)
            self.assertIn("threshold", gate)
            self.assertIn("observed", gate)

    def test_the_terminal_decision_follows_from_the_gates(self):
        failed = self.result["gate"]["failed"]
        all_pass = not failed
        expected_outcome = (
            tool.PROTOCOL_OUTCOME_ADMIT if all_pass else tool.PROTOCOL_OUTCOME_RETAIN
        )
        expected_decision = tool.DECISION_ADMIT if all_pass else tool.DECISION_RETAIN
        self.assertEqual(self.result["outcome"], expected_outcome)
        self.assertEqual(self.result["decision"], expected_decision)
        self.assertEqual(self.decision["decision"], expected_decision)
        self.assertEqual(self.decision["protocol_outcome"], expected_outcome)
        self.assertTrue(self.decision["terminal"])
        self.assertTrue(self.decision["validation_consumed"])
        self.assertEqual(self.decision["issue367_authorized"], all_pass)
        self.assertEqual(sorted(self.decision["failed_gates"]), sorted(failed))

    def test_the_reported_decision_matches_a_fresh_recomputation(self):
        gates = self.result["gates"]
        coverage = self.result["metrics"]["coverage"]
        non_inferiority = self.result["non_inferiority"]
        recomputed = {
            "coverage_floor": (coverage["coverage"] or 0.0) >= tool.MINIMUM_COVERAGE,
            "minimum_scored_decisions": coverage["answered_decisions"]
            >= tool.MINIMUM_SCORED_DECISIONS,
            "minimum_distinct_hands": coverage["distinct_hands_answered"]
            >= tool.MINIMUM_DISTINCT_HANDS,
            "non_inferiority_vs_fit_global_prior_baseline": non_inferiority[
                "fit_global_prior_baseline"
            ]["ci95_upper"]
            <= tool.MARGIN_FIT_GLOBAL_PRIOR,
            "non_inferiority_vs_alternate_architecture_hierarchical_eb": non_inferiority[
                "alternate_architecture_hierarchical_eb"
            ]["ci95_upper"]
            <= tool.MARGIN_ALTERNATE_ARCHITECTURE,
            "non_inferiority_vs_active_model_a_preflop_population": non_inferiority[
                "active_model_a_v5"
            ]["ci95_upper"]
            <= tool.MARGIN_ACTIVE_MODEL_A,
        }
        for gate_id, expected in recomputed.items():
            self.assertEqual(gates[gate_id]["passed"], expected, gate_id)

    def test_the_gate_thresholds_match_the_frozen_protocol(self):
        thresholds = self.protocol["thresholds"]
        self.assertEqual(
            tool.MINIMUM_COVERAGE, thresholds["coverage"]["minimum_coverage"]
        )
        self.assertEqual(
            tool.MINIMUM_SCORED_DECISIONS, thresholds["coverage"]["minimum_scored_decisions"]
        )
        self.assertEqual(
            tool.MINIMUM_DISTINCT_HANDS, thresholds["coverage"]["minimum_distinct_hands"]
        )
        self.assertEqual(
            tool.MAXIMUM_ABSOLUTE_ECE, thresholds["calibration"]["maximum_absolute_ece"]
        )
        self.assertEqual(
            tool.MAXIMUM_ECE_DELTA_VS_ACTIVE,
            thresholds["calibration"]["maximum_ece_delta_vs_active"],
        )
        self.assertEqual(
            tool.BOOTSTRAP_SAMPLES, thresholds["non_inferiority"]["bootstrap_samples"]
        )
        self.assertEqual(tool.BOOTSTRAP_SEED, thresholds["non_inferiority"]["seed"])
        comparisons = {
            row["against"]: row["margin_bits"]
            for row in thresholds["non_inferiority"]["comparisons"]
        }
        self.assertEqual(
            comparisons["fit_global_prior_baseline"], tool.MARGIN_FIT_GLOBAL_PRIOR
        )
        self.assertEqual(
            comparisons["alternate_architecture_hierarchical_eb"],
            tool.MARGIN_ALTERNATE_ARCHITECTURE,
        )
        self.assertEqual(
            comparisons["active_model_a_preflop_population"], tool.MARGIN_ACTIVE_MODEL_A
        )

    # --------------------------------------------------------- pure helpers
    def test_reference_actions_are_mapped_onto_the_response_space(self):
        self.assertEqual(tool._map_reference_action("LIMP"), "CALL")
        self.assertEqual(tool._map_reference_action("call"), "CALL")
        self.assertEqual(tool._map_reference_action("JAM"), "JAM")
        self.assertIsNone(tool._map_reference_action("CHECK"))
        probabilities, dropped = tool._normalized(
            {"FOLD": 0.5, "LIMP": 0.25, "RAISE": 0.2, "JAM": 0.05}
        )
        self.assertAlmostEqual(sum(probabilities.values()), 1.0, places=12)
        self.assertAlmostEqual(probabilities["CALL"], 0.25, places=12)
        self.assertAlmostEqual(dropped, 0.0, places=12)
        empty, dropped_empty = tool._normalized({"CHECK": 1.0})
        self.assertIsNone(empty)
        self.assertEqual(dropped_empty, 0.0)

    def test_expected_outcome_strings_are_the_task_contract(self):
        self.assertEqual(tool.DECISION_ADMIT, "ADMIT_GENERALIZED_RESPONSE_MODEL")
        self.assertEqual(
            tool.DECISION_RETAIN, "RETAIN_REFERENCE_GENERALIZATION_INSUFFICIENT"
        )
        self.assertIn(
            self.decision["decision"],
            (tool.DECISION_ADMIT, tool.DECISION_RETAIN),
        )


if __name__ == "__main__":
    unittest.main()

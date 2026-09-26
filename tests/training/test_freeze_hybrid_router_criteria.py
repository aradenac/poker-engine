#!/usr/bin/env python3
"""#423 T5 guard: numeric freeze of the hybrid router admission criteria.

Covers every acceptance criterion of the task:

* the frozen values are resolved from the TRAIN-only cross-fitted derivation of
  #423 T4 and every one of them carries its quantitative justification (the
  statistic, the confidence interval and the effectifs) plus the digests of the
  derivation inputs;
* the manifest names the derivation procedure of #423 T1 and pins the digest of
  the frozen spec before any terminal score exists;
* the ordering guard refuses to freeze once a terminal
  ``TRAIN_CV_ROUTER_REPORT.json`` exists (both declared locations);
* after a freeze, a regeneration that would produce a different value fails
  closed, and a frozen value modified afterwards is detected;
* two freezes are byte-identical and the persisted artifacts are pinned by
  their ``.sha256`` sidecars.

``pytest`` is not a declared dependency of this repository; the suite is a plain
``unittest`` module, run with ``python3 -m unittest`` like its siblings.
"""
from __future__ import annotations

import hashlib
import json
import math
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training import freeze_hybrid_router_criteria as tool  # noqa: E402
from tools.training import freeze_hybrid_router_spec as spec_tool  # noqa: E402

DERIVATION_PATH = ROOT / "analysis/issue423_hybrid_router/derivation/CV_DERIVATION.json"
DERIVATION_DIGEST_PATH = ROOT / "analysis/issue423_hybrid_router/derivation/CV_DERIVATION.sha256"
SPEC_PATH = ROOT / "analysis/issue423_hybrid_router/HYBRID_ROUTER_SPEC.json"
MANIFEST_PATH = ROOT / "analysis/issue423_hybrid_router/ROUTER_MANIFEST.json"

#: The two splits a TRAIN-only freeze must never consume.
FORBIDDEN_SPLITS = ("VALIDATION", "TEST")

#: The five criteria the freeze must resolve, in derivation order.
REQUIRED_CRITERIA = (
    "GLOBAL_NON_INFERIORITY_MARGIN",
    "SPARSE_GAIN_FLOOR",
    "SPARSE_ECE_CEILING",
    "FREQUENT_EXACT_NON_DEGRADATION_BOUND",
    "OOD_ABSTENTION_CRITERION",
)


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
    """Redirect every artifact the freeze reads or writes into a temp directory."""

    def __init__(self, tmp: Path):
        self.tmp = tmp

    def __enter__(self):
        here = self.tmp / "issue423_hybrid_router"
        derivation_dir = here / "derivation"
        derivation_dir.mkdir(parents=True, exist_ok=True)
        spec_path = here / tool.SPEC_NAME
        manifest_path = here / tool.MANIFEST_NAME
        derivation_path = derivation_dir / tool.DERIVATION_NAME
        derivation_digest_path = derivation_dir / "CV_DERIVATION.sha256"
        self.paths = {
            "here": here,
            "spec": spec_path,
            "spec_digest": here / "HYBRID_ROUTER_SPEC.sha256",
            "manifest": manifest_path,
            "manifest_digest": here / "ROUTER_MANIFEST.sha256",
            "derivation": derivation_path,
            "derivation_digest": derivation_digest_path,
        }
        self._patches = [
            mock.patch.object(tool, "HERE", here),
            mock.patch.object(tool, "SPEC_PATH", spec_path),
            mock.patch.object(tool, "SPEC_DIGEST_PATH", self.paths["spec_digest"]),
            mock.patch.object(tool, "MANIFEST_PATH", manifest_path),
            mock.patch.object(tool, "MANIFEST_DIGEST_PATH", self.paths["manifest_digest"]),
            mock.patch.object(tool, "DERIVATION_PATH", derivation_path),
            mock.patch.object(tool, "DERIVATION_DIGEST_PATH", derivation_digest_path),
            mock.patch.object(
                tool,
                "TERMINAL_REPORT_PATHS",
                (here / tool.TERMINAL_REPORT_NAME, here / "terminal" / tool.TERMINAL_REPORT_NAME),
            ),
            mock.patch.object(spec_tool, "HERE", here),
            mock.patch.object(spec_tool, "SPEC_PATH", spec_path),
            mock.patch.object(spec_tool, "DIGEST_PATH", self.paths["spec_digest"]),
            mock.patch.object(spec_tool, "FROZEN_MANIFEST_PATH", manifest_path),
        ]
        for patch in self._patches:
            patch.start()
        # The isolated derivation and the *pre-freeze* T1 spec: tests author the
        # numeric freeze themselves instead of inheriting the repository one.
        shutil.copyfile(DERIVATION_PATH, derivation_path)
        shutil.copyfile(DERIVATION_DIGEST_PATH, derivation_digest_path)
        spec_path.write_bytes(spec_tool.serialize(spec_tool.build_spec()))
        return self

    def __exit__(self, *exc):
        for patch in reversed(self._patches):
            patch.stop()
        return False


class DerivedCriteriaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.derivation = tool.load_derivation(DERIVATION_PATH)
        cls.spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))

    def test_frozen_values_are_the_trained_numeric_values(self):
        criteria = tool.derive_criteria(self.derivation, self.spec)
        values = {entry["id"]: entry["value"] for entry in criteria["criteria"]}
        self.assertEqual(tuple(values), REQUIRED_CRITERIA)

        quantum = 0.001
        margin = self.derivation["margin_derivation"]["margin_global_bootstrap_bits_per_decision"]
        self.assertEqual(
            values["GLOBAL_NON_INFERIORITY_MARGIN"],
            round(math.ceil(round(margin / quantum, 9)) * quantum, 6),
        )

        weights = {
            stratum: self.derivation["models"]["hybrid_router"]["by_stratum"][stratum]["metrics"][
                "n"
            ]
            for stratum in ("rare_exact", "exact_absent_in_domain")
        }
        gains = {
            stratum: self.derivation["models"]["hybrid_router"]["by_stratum"][stratum]["metrics"][
                "gain_bits_per_decision"
            ]
            for stratum in weights
        }
        observed_gain = sum(weights[key] * gains[key] for key in weights) / sum(weights.values())
        self.assertEqual(
            values["SPARSE_GAIN_FLOOR"],
            round(math.floor(round(observed_gain / quantum, 9)) * quantum, 6),
        )

        active_ece = {
            stratum: self.derivation["models"]["active_model_a"]["by_stratum"][stratum]["metrics"][
                "expected_calibration_error"
            ]
            for stratum in weights
        }
        active_weights = {
            stratum: self.derivation["models"]["active_model_a"]["by_stratum"][stratum]["metrics"][
                "n"
            ]
            for stratum in weights
        }
        active_sparse = sum(
            active_weights[key] * active_ece[key] for key in weights
        ) / sum(active_weights.values())
        self.assertEqual(
            values["SPARSE_ECE_CEILING"], round(min(0.02, active_sparse + 0.02), 6)
        )

        frequent = self.derivation["per_stratum"]["frequent_exact"]["paired"][
            "hybrid_router_minus_active_model_a"
        ]
        worst = max(
            [frequent["point_estimate_bits_per_decision"], frequent["upper_quantile_bits_per_decision"]]
            + list(frequent["ci95"])
        )
        self.assertEqual(
            values["FREQUENT_EXACT_NON_DEGRADATION_BOUND"],
            round(math.ceil(round(max(0.0, worst) / quantum, 9)) * quantum, 6),
        )

        probes = self.derivation["ood_synthetic_probes"]
        self.assertEqual(probes["abstain_rate"], 1.0)
        self.assertEqual(values["OOD_ABSTENTION_CRITERION"], 1.0)

    def test_every_criterion_carries_its_quantitative_justification(self):
        criteria = tool.derive_criteria(self.derivation, self.spec)
        for entry in criteria["criteria"]:
            with self.subTest(criterion=entry["id"]):
                self.assertFalse(entry["terminal_evaluation_derived"])
                self.assertIsInstance(entry["value"], float)
                self.assertIn(entry["direction"], ("lower_is_better", "higher_is_better", "predicate"))
                justification = entry["justification"]
                self.assertTrue(justification.get("statistic"))
                self.assertTrue(justification.get("statement"))
                self.assertTrue(justification.get("preregistered_reference"))
                self.assertGreaterEqual(len(entry["inputs"]), 2)
                for item in entry["inputs"]:
                    self.assertEqual(item["source"], "train_only_cv_derivation")
                    self.assertTrue(item["pointer"].startswith("/"))
                self.assertGreaterEqual(len(entry["effectifs"]), 2)
        margin = next(entry for entry in criteria["criteria"] if entry["id"] == REQUIRED_CRITERIA[0])
        dispersion = margin["justification"]["dispersion"]
        self.assertEqual(len(dispersion["ci95"]), 2)
        self.assertGreater(dispersion["bootstrap_stddev_bits_per_decision"], 0.0)
        self.assertGreaterEqual(margin["effectifs"]["hands"], 1000)

    def test_frozen_criteria_are_digest_bound(self):
        criteria = tool.derive_criteria(self.derivation, self.spec)
        payload = {key: value for key, value in criteria.items() if key != "criteria_sha256"}
        self.assertEqual(criteria["criteria_sha256"], tool.stable_hash(payload))
        self.assertEqual(tool.derive_criteria(self.derivation, self.spec), criteria)

    def test_derivation_binds_the_t1_procedure(self):
        criteria = tool.derive_criteria(self.derivation, self.spec)
        reference = criteria["procedure_reference"]
        self.assertEqual(reference["spec"], tool.SPEC_LOGICAL_PATH)
        self.assertEqual(reference["pointer"], "/procedure")
        self.assertEqual(
            reference["derivation_order"], list(self.spec["procedure"]["derivation_order"])
        )
        self.assertEqual(
            sorted(reference["formula_ids"]),
            sorted({formula["id"] for formula in self.spec["procedure"]["formulas"]}),
        )
        self.assertEqual(criteria["derivation"]["sha256"], tool.sha256_file(DERIVATION_PATH))
        self.assertEqual(
            criteria["derivation"]["canonical_payload_sha256"],
            self.derivation["canonical_payload_sha256"],
        )

    def test_freeze_refuses_a_derivation_that_read_a_holdout(self):
        for flag in ("validation_consumed", "test_consumed"):
            with self.subTest(flag=flag):
                broken = json.loads(json.dumps(self.derivation))
                broken["scope"][flag] = True
                with self.assertRaises(tool.HybridRouterCriteriaError):
                    tool.derive_criteria(broken, self.spec)
        broken = json.loads(json.dumps(self.derivation))
        broken["guards"]["validation_consumed"] = True
        with self.assertRaises(tool.HybridRouterCriteriaError):
            tool.derive_criteria(broken, self.spec)
        broken = json.loads(json.dumps(self.derivation))
        broken["scope"]["consumed_splits"] = ["TRAIN", FORBIDDEN_SPLITS[0]]
        with self.assertRaises(tool.HybridRouterCriteriaError):
            tool.derive_criteria(broken, self.spec)
        broken = json.loads(json.dumps(self.derivation))
        broken["scope"]["split"] = FORBIDDEN_SPLITS[1]
        with self.assertRaises(tool.HybridRouterCriteriaError):
            tool.derive_criteria(broken, self.spec)
        broken = json.loads(json.dumps(self.derivation))
        broken["assertions"]["test_never_read"] = False
        with self.assertRaises(tool.HybridRouterCriteriaError):
            tool.derive_criteria(broken, self.spec)
        broken = json.loads(json.dumps(self.derivation))
        broken["margin_derivation"]["terminal_evaluation_derived"] = True
        with self.assertRaises(tool.HybridRouterCriteriaError):
            tool.derive_criteria(broken, self.spec)

    def test_freeze_refuses_a_spec_without_the_preregistered_procedure(self):
        for mutate in (
            lambda spec: spec["procedure"].__setitem__("preregistered", False),
            lambda spec: spec["procedure"].__setitem__("test_consumed", True),
            lambda spec: spec["procedure"].pop("constants"),
            lambda spec: spec["procedure"].pop("formulas"),
        ):
            with self.subTest(mutate=mutate):
                broken = json.loads(json.dumps(self.spec))
                mutate(broken)
                with self.assertRaises(tool.HybridRouterCriteriaError):
                    tool.derive_criteria(self.derivation, broken)

    def test_generator_names_no_holdout_loader(self):
        scan = tool.verify_no_holdout_access()
        self.assertEqual(scan["result"], "PASS")
        self.assertEqual(scan["hits"], [])


class PersistedArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest_bytes = MANIFEST_PATH.read_bytes()
        cls.manifest = json.loads(cls.manifest_bytes)
        cls.spec_bytes = SPEC_PATH.read_bytes()
        cls.spec = json.loads(cls.spec_bytes)

    def test_manifest_is_the_frozen_criteria_document(self):
        self.assertEqual(self.manifest["schema"], tool.MANIFEST_SCHEMA)
        self.assertEqual(self.manifest["issue"], 423)
        self.assertEqual(self.manifest["planner_key"], "T5")
        self.assertEqual(self.manifest["status"], tool.STATUS)
        self.assertTrue(self.manifest["frozen_at"])
        self.assertEqual(
            self.manifest["canonical_payload_sha256"],
            tool.stable_hash(
                {
                    key: value
                    for key, value in self.manifest.items()
                    if key != "canonical_payload_sha256"
                }
            ),
        )

    def test_manifest_pins_the_frozen_spec_digest(self):
        self.assertEqual(
            self.manifest["frozen_spec"]["sha256"],
            hashlib.sha256(self.spec_bytes).hexdigest(),
        )
        self.assertEqual(self.manifest["frozen_spec"]["path"], tool.SPEC_LOGICAL_PATH)
        self.assertEqual(self.manifest["frozen_spec"]["bytes"], len(self.spec_bytes))
        self.assertEqual(self.manifest["frozen_criteria"], self.spec["frozen_criteria"])
        self.assertEqual(
            self.manifest["frozen_criteria_sha256"],
            self.spec["frozen_criteria"]["criteria_sha256"],
        )

    def test_sidecars_pin_the_persisted_bytes(self):
        manifest_sidecar = tool.MANIFEST_DIGEST_PATH.read_text(encoding="utf-8").splitlines()
        self.assertEqual(
            manifest_sidecar[0].split(),
            [hashlib.sha256(self.manifest_bytes).hexdigest(), tool.MANIFEST_NAME],
        )
        spec_sidecar = tool.SPEC_DIGEST_PATH.read_text(encoding="utf-8").splitlines()
        self.assertEqual(
            spec_sidecar[0].split(),
            [hashlib.sha256(self.spec_bytes).hexdigest(), tool.SPEC_NAME],
        )

    def test_frozen_spec_carries_the_numeric_criteria(self):
        frozen = self.spec["frozen_criteria"]
        self.assertEqual(frozen["schema"], tool.CRITERIA_SCHEMA)
        self.assertEqual([entry["id"] for entry in frozen["criteria"]], list(REQUIRED_CRITERIA))
        self.assertEqual(frozen["criteria_order"], list(REQUIRED_CRITERIA))
        self.assertFalse(frozen["terminal_evaluation_derived"])
        self.assertFalse(frozen["terminal_evaluation"]["consumed"])
        self.assertFalse(self.spec["assertions"]["terminal_numeric_values_persisted"])
        self.assertTrue(self.spec["assertions"]["frozen_numeric_criteria_persisted"])
        for entry in frozen["criteria"]:
            with self.subTest(criterion=entry["id"]):
                self.assertIn(entry["value"], {item for _, item in _numbers(frozen)})
                self.assertIn(
                    entry["t1_formula_id"],
                    {formula["id"] for formula in self.spec["procedure"]["formulas"]},
                )

    def test_the_t1_generator_rebuilds_the_frozen_spec_byte_for_byte(self):
        self.assertEqual(spec_tool.serialize(spec_tool.build_spec()), self.spec_bytes)
        self.assertEqual(spec_tool.check(), [])

    def test_manifest_records_the_derivation_procedure_and_input_digests(self):
        procedure = self.manifest["derivation_procedure"]
        self.assertEqual(procedure["reference"]["spec"], tool.SPEC_LOGICAL_PATH)
        self.assertEqual(procedure["reference"]["pointer"], "/procedure")
        self.assertEqual(
            procedure["reference"]["spec_sha256"], self.manifest["frozen_spec"]["sha256"]
        )
        self.assertEqual(
            procedure["derivation_order"], list(self.spec["procedure"]["derivation_order"])
        )
        self.assertEqual([f["id"] for f in procedure["formulas"]], list(REQUIRED_CRITERIA))
        roles = {entry["role"]: entry for entry in self.manifest["derivation_inputs"]}
        self.assertEqual(
            roles["train_only_cv_derivation"]["sha256"], tool.sha256_file(DERIVATION_PATH)
        )
        self.assertEqual(
            roles["preregistration_spec"]["sha256"], self.manifest["frozen_spec"]["sha256"]
        )
        for role, entry in roles.items():
            with self.subTest(role=role):
                self.assertRegex(entry["sha256"], r"^[0-9a-f]{64}$")
                self.assertFalse(entry["path"].startswith("/"))
        self.assertEqual(tool.verify_input_bindings(self.manifest["derivation_inputs"]), [])

    def test_terminal_guard_is_recorded_as_satisfied(self):
        guard = self.manifest["terminal_score_guard"]
        self.assertEqual(guard["guard_id"], "ROUTER_CRITERIA_ORDER_GUARD")
        self.assertTrue(guard["terminal_report_absent_at_freeze"])
        self.assertTrue(guard["spec_digest_computed_before_terminal_score"])
        self.assertTrue(guard["regeneration_with_different_values_fails_closed"])
        self.assertIn(tool.TERMINAL_REPORT_NAME, guard["terminal_report_name"])
        self.assertEqual(self.manifest["order_guard"]["result"], "PASS")
        self.assertEqual(tool.terminal_absence_problems(), [])

    def test_manifest_declares_its_own_split_policy_and_identity(self):
        policy = self.manifest["split_policy"]
        self.assertEqual(policy["allowed_splits"], ["TRAIN"])
        self.assertEqual(policy["consumed_splits"], ["TRAIN"])
        self.assertEqual(policy["refused_splits"], list(FORBIDDEN_SPLITS))
        self.assertTrue(policy["fail_closed_on_refused_split"])
        self.assertEqual(self.manifest["manifest"]["path"], tool.MANIFEST_LOGICAL_PATH)
        self.assertEqual(self.manifest["manifest"]["name"], tool.MANIFEST_NAME)
        self.assertFalse(self.manifest["assertions"]["validation_consumed"])
        self.assertFalse(self.manifest["assertions"]["test_consumed"])
        self.assertTrue(self.manifest["assertions"]["every_criterion_quantitatively_justified"])

    def test_check_mode_passes_on_the_persisted_artifacts(self):
        self.assertEqual(tool.check(), [])
        self.assertEqual(tool.check_spec_reproducible(), [])

    def test_write_spec_re_persists_the_frozen_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            with _IsolatedLayout(Path(tmp)) as layout:
                tool.freeze()
                spec = json.loads(layout.paths["spec"].read_text(encoding="utf-8"))
                payload = tool.write_spec(spec)
                self.assertEqual(payload, layout.paths["spec"].read_bytes())
                self.assertEqual(tool.check(), [])

    def test_the_terminal_report_binds_the_frozen_spec_or_is_absent(self):
        # #423 T6 writes the terminal score after this freeze.  Once it exists,
        # the ordering proof is the frozen spec digest the report embeds; while
        # it does not, the absence is the proof.  Anything else is unprovable.
        state = tool.terminal_order_state()
        if state["state"] == "ABSENT":
            for path in tool.TERMINAL_REPORT_PATHS:
                self.assertFalse(path.exists(), path)
        else:
            self.assertEqual(state["state"], "BOUND")
            self.assertTrue(state["bound"])
            self.assertEqual(state["unbound"], [])


class OrderingGuardTests(unittest.TestCase):
    def test_freeze_refuses_when_the_terminal_report_already_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            with _IsolatedLayout(Path(tmp)) as layout:
                terminal = layout.paths["here"] / tool.TERMINAL_REPORT_NAME
                terminal.write_text(json.dumps({"schema": "terminal"}), encoding="utf-8")
                with self.assertRaises(tool.HybridRouterCriteriaError) as caught:
                    tool.freeze()
                self.assertIn("terminal", str(caught.exception).lower())
                self.assertFalse(layout.paths["manifest"].exists())
                with self.assertRaises(tool.HybridRouterCriteriaError):
                    tool.assert_terminal_report_absent()

    def test_a_declared_secondary_terminal_location_also_blocks_the_freeze(self):
        with tempfile.TemporaryDirectory() as tmp:
            with _IsolatedLayout(Path(tmp)) as layout:
                nested = layout.paths["here"] / "terminal"
                nested.mkdir(parents=True)
                (nested / tool.TERMINAL_REPORT_NAME).write_text("{}", encoding="utf-8")
                with self.assertRaises(tool.HybridRouterCriteriaError):
                    tool.freeze()
                self.assertFalse(layout.paths["spec_digest"].exists())

    def test_the_guard_reports_the_declared_locations(self):
        # The declared locations are a property of the guard itself.  Once the
        # #423 T6 terminal score exists the pre-freeze guard is armed against it,
        # so the satisfied path is asserted where it is genuinely reachable: a
        # layout that has not been scored yet.
        self.assertEqual(
            tool.terminal_order_state()["declared_terminal_report_locations"],
            list(tool.TERMINAL_REPORT_LOGICAL_PATHS),
        )
        with tempfile.TemporaryDirectory() as tmp:
            with _IsolatedLayout(Path(tmp)):
                report = tool.assert_terminal_report_absent()
                self.assertEqual(report["guard_id"], "ROUTER_CRITERIA_ORDER_GUARD")
                self.assertEqual(report["result"], "PASS")
                self.assertEqual(report["declared_terminal_report_locations_present"], [])
                self.assertEqual(
                    report["declared_terminal_report_locations"],
                    list(tool.TERMINAL_REPORT_LOGICAL_PATHS),
                )

    def test_check_reports_a_terminal_report_that_appeared_after_the_freeze(self):
        with tempfile.TemporaryDirectory() as tmp:
            with _IsolatedLayout(Path(tmp)) as layout:
                tool.freeze()
                (layout.paths["here"] / tool.TERMINAL_REPORT_NAME).write_text("{}", encoding="utf-8")
                problems = tool.check()
                self.assertTrue(any("terminal" in problem for problem in problems), problems)


class DriftTests(unittest.TestCase):
    def test_freeze_is_idempotent_when_nothing_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with _IsolatedLayout(Path(tmp)) as layout:
                first = tool.freeze()
                self.assertEqual(first["status"], "FROZEN")
                spec_bytes = layout.paths["spec"].read_bytes()
                manifest_bytes = layout.paths["manifest"].read_bytes()
                second = tool.freeze()
                self.assertEqual(second["status"], "UNCHANGED")
                self.assertEqual(layout.paths["spec"].read_bytes(), spec_bytes)
                self.assertEqual(layout.paths["manifest"].read_bytes(), manifest_bytes)

    def test_two_freezes_are_byte_identical(self):
        with tempfile.TemporaryDirectory() as first:
            with _IsolatedLayout(Path(first)) as layout:
                tool.freeze()
                first_spec = layout.paths["spec"].read_bytes()
                first_manifest = layout.paths["manifest"].read_bytes()
        with tempfile.TemporaryDirectory() as second:
            with _IsolatedLayout(Path(second)) as layout:
                tool.freeze()
                second_spec = layout.paths["spec"].read_bytes()
                second_manifest = layout.paths["manifest"].read_bytes()
        self.assertEqual(first_spec, second_spec)
        self.assertEqual(first_manifest, second_manifest)
        self.assertEqual(first_spec, SPEC_PATH.read_bytes())
        self.assertEqual(first_manifest, MANIFEST_PATH.read_bytes())

    def test_regeneration_with_a_different_value_fails_closed(self):
        derivation = json.loads(DERIVATION_PATH.read_text(encoding="utf-8"))
        derivation["models"]["hybrid_router"]["by_stratum"]["rare_exact"]["metrics"][
            "gain_bits_per_decision"
        ] = 0.5
        with tempfile.TemporaryDirectory() as tmp:
            with _IsolatedLayout(Path(tmp)) as layout:
                tool.freeze()
                persisted = layout.paths["spec"].read_bytes()
                mutated = json.loads(json.dumps(derivation))
                mutated["canonical_payload_sha256"] = tool.stable_hash(
                    {
                        key: value
                        for key, value in mutated.items()
                        if key != "canonical_payload_sha256"
                    }
                )
                payload = (json.dumps(mutated, sort_keys=True, indent=2) + "\n").encode("utf-8")
                layout.paths["derivation"].write_bytes(payload)
                layout.paths["derivation_digest"].write_text(
                    f"{hashlib.sha256(payload).hexdigest()}  {tool.DERIVATION_NAME}\n",
                    encoding="utf-8",
                )
                with self.assertRaises(tool.HybridRouterCriteriaError) as caught:
                    tool.freeze()
                message = str(caught.exception)
                self.assertIn("different", message)
                self.assertIn("SPARSE_GAIN_FLOOR", message)
                self.assertEqual(layout.paths["spec"].read_bytes(), persisted)

    def test_freeze_refuses_an_derivation_that_contradicts_itself(self):
        divergence = {
            "margin_derivation.margin_global_bootstrap_bits_per_decision": 0.004,
            "margin_derivation.margin_global_analytic_bits_per_decision": 0.004,
            "ood_synthetic_probes.abstain_rate": 0.5,
        }
        for pointer, value in divergence.items():
            with self.subTest(pointer=pointer):
                derivation = json.loads(DERIVATION_PATH.read_text(encoding="utf-8"))
                section, _, field = pointer.partition(".")
                derivation[section][field] = value
                with self.assertRaises(tool.HybridRouterCriteriaError):
                    tool.derive_criteria(derivation, json.loads(SPEC_PATH.read_text(encoding="utf-8")))

    def test_a_value_modified_after_the_freeze_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with _IsolatedLayout(Path(tmp)) as layout:
                tool.freeze()
                self.assertEqual(tool.check(), [])
                spec = json.loads(layout.paths["spec"].read_text(encoding="utf-8"))
                entry = next(
                    item
                    for item in spec["frozen_criteria"]["criteria"]
                    if item["id"] == "GLOBAL_NON_INFERIORITY_MARGIN"
                )
                entry["value"] = 0.5
                layout.paths["spec"].write_text(
                    json.dumps(spec, sort_keys=True, indent=2) + "\n", encoding="utf-8"
                )
                problems = tool.check()
                self.assertTrue(problems, "a modified frozen value must be detected")
                joined = " ".join(problems)
                self.assertIn("frozen criteria", joined)
                with self.assertRaises(tool.HybridRouterCriteriaError):
                    tool.freeze()

    def test_a_manifest_modified_after_the_freeze_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with _IsolatedLayout(Path(tmp)) as layout:
                tool.freeze()
                manifest = json.loads(layout.paths["manifest"].read_text(encoding="utf-8"))
                manifest["frozen_criteria"]["criteria"][0]["value"] = 9.5
                layout.paths["manifest"].write_text(
                    json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
                )
                problems = tool.check()
                joined = " ".join(problems)
                self.assertIn("disagree on the frozen criteria", joined)
                with self.assertRaises(tool.HybridRouterCriteriaError):
                    tool.freeze()

    def test_a_spec_without_criteria_but_with_a_manifest_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with _IsolatedLayout(Path(tmp)) as layout:
                tool.freeze()
                spec = json.loads(layout.paths["spec"].read_text(encoding="utf-8"))
                spec["assertions"]["frozen_numeric_criteria_persisted"] = False
                spec.pop("frozen_criteria")
                payload = (json.dumps(spec, sort_keys=True, indent=2) + "\n").encode("utf-8")
                layout.paths["spec"].write_bytes(payload)
                layout.paths["spec_digest"].write_text(
                    f"{hashlib.sha256(payload).hexdigest()}  {tool.SPEC_NAME}\n", encoding="utf-8"
                )
                with self.assertRaises(tool.HybridRouterCriteriaError) as caught:
                    tool.freeze()
                self.assertIn("no frozen criteria", str(caught.exception))
                problems = tool.check()
                self.assertTrue(
                    any("carries no frozen criteria" in problem for problem in problems), problems
                )

    def test_a_criteria_only_spec_without_a_manifest_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with _IsolatedLayout(Path(tmp)) as layout:
                tool.freeze()
                layout.paths["manifest"].unlink()
                layout.paths["manifest_digest"].unlink()
                with self.assertRaises(tool.HybridRouterCriteriaError) as caught:
                    tool.freeze()
                self.assertIn("without a manifest", str(caught.exception))
                # The provenance can be re-authored when not a single value moves.
                result = tool.freeze(reauthor=True)
                self.assertEqual(result["status"], "REAUTHORED")
                self.assertEqual(tool.check(), [])
                # A hidden value change is still refused: deleting the manifest is
                # never a way to re-freeze different criteria.
                spec = json.loads(layout.paths["spec"].read_text(encoding="utf-8"))
                spec["frozen_criteria"]["criteria"][0]["value"] = 0.75
                layout.paths["spec"].write_text(
                    json.dumps(spec, sort_keys=True, indent=2) + "\n", encoding="utf-8"
                )
                layout.paths["manifest"].unlink()
                layout.paths["manifest_digest"].unlink()
                with self.assertRaises(tool.HybridRouterCriteriaError) as caught:
                    tool.freeze()
                self.assertIn("different frozen criteria", str(caught.exception))

    def test_reauthor_cannot_change_a_frozen_value(self):
        derivation = json.loads(DERIVATION_PATH.read_text(encoding="utf-8"))
        derivation["models"]["hybrid_router"]["by_stratum"]["rare_exact"]["metrics"][
            "gain_bits_per_decision"
        ] = 0.5
        with tempfile.TemporaryDirectory() as tmp:
            with _IsolatedLayout(Path(tmp)) as layout:
                tool.freeze()
                payload = (json.dumps(derivation, sort_keys=True, indent=2) + "\n").encode("utf-8")
                layout.paths["derivation"].write_bytes(payload)
                layout.paths["derivation_digest"].write_text(
                    f"{hashlib.sha256(payload).hexdigest()}  {tool.DERIVATION_NAME}\n",
                    encoding="utf-8",
                )
                with self.assertRaises(tool.HybridRouterCriteriaError):
                    tool.freeze(reauthor=True)

    def test_reauthor_repins_the_same_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            with _IsolatedLayout(Path(tmp)) as layout:
                tool.freeze()
                spec_bytes = layout.paths["spec"].read_bytes()
                result = tool.freeze(reauthor=True)
                self.assertEqual(result["status"], "REAUTHORED")
                self.assertEqual(layout.paths["spec"].read_bytes(), spec_bytes)
                self.assertEqual(tool.check(), [])


if __name__ == "__main__":
    unittest.main()

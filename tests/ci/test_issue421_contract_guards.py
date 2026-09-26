#!/usr/bin/env python3
"""#421 T11 -- contract guardrails around the mandatory suite.

These guards do not re-test the model.  They pin the cross-cutting properties
the ticket makes non-negotiable:

* the mandatory suite has exactly one named test per ticket item (no silent
  removal, no orphan test);
* the active Model A / Model B pointers and the two registries stay byte-frozen
  while the whole mandatory suite runs, and match the digests pinned in the
  frozen validation protocol;
* ``TEST_CONSUMED`` is false everywhere, and no TEST row is reachable;
* the mandatory suite passes with every network primitive blocked, and none of
  the relevant modules imports a network client.
"""
from __future__ import annotations

import ast
import contextlib
import importlib.util
import io
import json
import socket
import sys
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.datasets.build_hand_history_increment import fingerprint  # noqa: E402
from tools.preflop import generalized_response_model as model  # noqa: E402
from tools.preflop import generalized_response_runtime as runtime  # noqa: E402
from tools.simulation import issue421_issue367_preflight as preflight_tool  # noqa: E402

MANDATORY_SUITE_PATH = ROOT / "tests/preflop/test_issue421_mandatory_contracts.py"
DATASET_PATH = ROOT / "analysis/issue421_generalized_response/dataset/GENERALIZED_RESPONSE_DATASET.jsonl"
DATASET_MANIFEST_PATH = (
    ROOT / "analysis/issue421_generalized_response/dataset/GENERALIZED_RESPONSE_DATASET.json"
)
PROTOCOL_PATH = ROOT / "analysis/issue421_generalized_response/FROZEN_VALIDATION_PROTOCOL.json"
DECISION_PATH = ROOT / "analysis/issue421_generalized_response/DECISION.json"
VALIDATION_RESULT_PATH = ROOT / "analysis/issue421_generalized_response/VALIDATION_RESULT.json"

#: The exact mandatory item set the ticket enumerates.
EXPECTED_ITEM_IDS = frozenset(
    {
        "SAME_CONTEXT_SAME_PREDICTION",
        "SIZING_VARIATION_DIRECT_EVALUATION",
        "IN_DOMAIN_INTERPOLATION_ALLOWED",
        "EXTRAPOLATION_OOD_FAIL_CLOSED",
        "UNKNOWN_CATEGORY_OOD",
        "ILLEGAL_ACTIONS_NEVER_EMITTED",
        "GENERATED_SIZING_IS_LEGAL",
        "NO_FUTURE_OR_PRIVATE_INFORMATION",
        "SPLIT_IS_A_FUNCTION_OF_HAND_ID",
        "CANDIDATE_HASH_DRIFT_FAIL_CLOSED",
        "TEST_SPLIT_INACCESSIBLE",
        "ACTIVE_POINTER_UNCHANGED",
        "ISSUE367_NOT_EXECUTED",
    }
)

NETWORK_MODULES = frozenset(
    {
        "socket",
        "ssl",
        "http",
        "urllib",
        "urllib3",
        "ftplib",
        "smtplib",
        "telnetlib",
        "xmlrpc",
        "requests",
        "httpx",
        "aiohttp",
        "websockets",
    }
)

SCANNED_SOURCES = (
    MANDATORY_SUITE_PATH,
    ROOT / "tests/ci/test_issue421_contract_guards.py",
    ROOT / "tools/preflop/generalized_response_runtime.py",
    ROOT / "tools/preflop/generalized_response_model.py",
    ROOT / "tools/training/build_generalized_response_dataset.py",
    ROOT / "tools/datasets/build_hand_history_increment.py",
)

#: This guard file imports two network primitives *only* to patch them closed;
#: every other scanned module must import none at all.
SELF_PATH = ROOT / "tests/ci/test_issue421_contract_guards.py"
NETWORK_IMPORTS_ALLOWED_FOR_THE_TRIPWIRE = frozenset({"socket", "urllib"})


def load_mandatory_suite():
    """Load the consolidated mandatory suite by path (tests/ is not a package)."""
    spec = importlib.util.spec_from_file_location(
        "_issue421_mandatory_contracts", MANDATORY_SUITE_PATH
    )
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"cannot load {MANDATORY_SUITE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run_mandatory_suite() -> unittest.TestResult:
    module = load_mandatory_suite()
    suite = unittest.TestLoader().loadTestsFromTestCase(module.Issue421MandatoryContractTests)
    return unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)


@contextlib.contextmanager
def network_tripwire():
    """Any attempt to open a socket / URL fails the enclosing block."""

    def blocked(*args: object, **kwargs: object) -> object:
        raise AssertionError(f"network access attempted with {args!r} {kwargs!r}")

    with contextlib.ExitStack() as stack:
        for target, name in (
            (socket, "socket"),
            (socket, "create_connection"),
            (socket, "getaddrinfo"),
            (urllib.request, "urlopen"),
        ):
            stack.enter_context(mock.patch.object(target, name, blocked))
        yield


class Issue421ContractGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mandatory = load_mandatory_suite()
        cls.protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
        cls.decision = json.loads(DECISION_PATH.read_text(encoding="utf-8"))
        cls.validation = json.loads(VALIDATION_RESULT_PATH.read_text(encoding="utf-8"))
        cls.dataset_manifest = json.loads(DATASET_MANIFEST_PATH.read_text(encoding="utf-8"))

    # ------------------------------------------------------ suite completeness
    def test_the_mandatory_suite_covers_every_ticket_item(self) -> None:
        items = self.mandatory.MANDATORY_CONTRACT_ITEMS
        ids = frozenset(item["id"] for item in items)
        self.assertEqual(ids, EXPECTED_ITEM_IDS)
        self.assertEqual(len(items), len(EXPECTED_ITEM_IDS))
        tests = [item["test"] for item in items]
        self.assertEqual(len(tests), len(set(tests)))
        for item in items:
            with self.subTest(item=item["id"]):
                self.assertTrue(item["description"])
                method = getattr(self.mandatory.Issue421MandatoryContractTests, item["test"], None)
                self.assertTrue(callable(method), item["test"])
        declared = {
            name
            for name in dir(self.mandatory.Issue421MandatoryContractTests)
            if name.startswith("test_")
        }
        self.assertEqual(
            declared - set(tests), {"test_every_mandatory_item_has_exactly_one_named_test"}
        )

    # ------------------------------------------------- active pointer guardrail
    def test_the_active_pointer_bytes_stay_frozen_while_the_suite_runs(self) -> None:
        protected = preflight_tool.PROTECTED_FILES
        before_bytes = {path: (ROOT / path).read_bytes() for path in protected}
        before_hashes = preflight_tool.protected_hashes()
        pinned = {
            self.protocol["active_references"]["active_model_a_preflop"]["path"]: self.protocol[
                "active_references"
            ]["active_model_a_preflop"]["sha256"],
            self.protocol["active_references"]["active_model_b_postflop"]["path"]: self.protocol[
                "active_references"
            ]["active_model_b_postflop"]["sha256"],
            self.protocol["active_references"]["training_registry"]["path"]: self.protocol[
                "active_references"
            ]["training_registry"]["sha256"],
            self.protocol["active_references"]["populations_registry"]["path"]: self.protocol[
                "active_references"
            ]["populations_registry"]["sha256"],
        }
        for path, digest in pinned.items():
            with self.subTest(path=path):
                self.assertEqual(before_hashes[path], digest)
        result = run_mandatory_suite()
        self.assertTrue(
            result.wasSuccessful(), [str(case) for case, _ in result.failures + result.errors]
        )
        for path in protected:
            with self.subTest(path=path):
                self.assertEqual((ROOT / path).read_bytes(), before_bytes[path])
        self.assertEqual(preflight_tool.protected_hashes(), before_hashes)
        self.assertFalse(self.decision["active_pointer_mutated"])
        self.assertFalse(self.decision["active_model_pointer_mutation"])
        self.assertFalse(self.validation["active_pointer_mutated"])
        self.assertFalse(self.validation["active_pointer_mutation"])
        self.assertFalse(self.protocol["publication"]["active_model_pointer_mutation"])
        self.assertFalse(self.protocol["issue367_rule"]["active_model_pointer_mutation"])

    # ----------------------------------------------------- TEST consumption
    def test_test_consumed_is_false_everywhere(self) -> None:
        self.assertIs(runtime.TEST_CONSUMED, False)
        self.assertIs(runtime.VALIDATION_CONSUMED, False)
        self.assertIs(runtime.ACTIVE_POINTER_MUTATED, False)
        audit = runtime.GeneralizedResponseRuntime(
            candidate_id=self.decision["candidate"]["candidate_id"]
        ).audit()
        self.assertFalse(audit["test_consumed"])
        self.assertFalse(audit["validation_consumed"])
        self.assertFalse(self.protocol["evaluation"]["test_consumed"])
        self.assertFalse(self.protocol["holdout_boundary"]["test_consumed"])
        self.assertFalse(self.protocol["issue367_rule"]["test_consumed"])
        self.assertFalse(self.decision["test_consumed"])
        self.assertFalse(self.decision["test_authorized"])
        self.assertFalse(self.validation["test_consumed"])
        self.assertFalse(self.validation["test_authorized"])
        scope = self.dataset_manifest["scope"]
        self.assertFalse(scope["test_consumed"])
        self.assertEqual(scope["refused_splits"], ["TEST"])
        # No persisted TEST row and no hand reachable outside TRAIN/VALIDATION.
        splits = set()
        with DATASET_PATH.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                splits.add(json.loads(line)["split"])
        self.assertEqual(splits, set(model.TRAIN_SPLITS))
        self.assertNotIn("TEST", splits)
        preflight, _ = preflight_tool.build()
        self.assertFalse(preflight["boundary"]["test_consumed"])
        self.assertFalse(preflight["boundary"]["test_split_authorized"])

    # -------------------------------------------------------------- no network
    def test_the_mandatory_suite_runs_with_the_network_blocked(self) -> None:
        with network_tripwire():
            result = run_mandatory_suite()
        self.assertTrue(
            result.wasSuccessful(), [str(case) for case, _ in result.failures + result.errors]
        )
        self.assertGreater(result.testsRun, 0)

    def test_no_scanned_module_imports_a_network_client(self) -> None:
        for path in SCANNED_SOURCES:
            imported: set[str] = set()
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    imported.add(node.module.split(".")[0])
            allowed = (
                NETWORK_IMPORTS_ALLOWED_FOR_THE_TRIPWIRE if path == SELF_PATH else frozenset()
            )
            with self.subTest(path=str(path.relative_to(ROOT))):
                self.assertTrue(
                    imported & NETWORK_MODULES <= allowed,
                    sorted((imported & NETWORK_MODULES) - allowed),
                )

    def test_the_guard_file_only_references_the_network_from_the_tripwire(self) -> None:
        tree = ast.parse(SELF_PATH.read_text(encoding="utf-8"))
        tripwire = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "network_tripwire"
        )
        referenced = {
            node.id for node in ast.walk(tripwire) if isinstance(node, ast.Name)
        }
        referenced |= {
            node.value.id
            for node in ast.walk(tripwire)
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
        }
        self.assertIn("socket", referenced)
        self.assertIn("urllib", referenced)

    # ------------------------------------------- hand-grouped freeze cross-check
    def test_the_frozen_fold_fingerprints_match_the_persisted_rows(self) -> None:
        hands: dict[str, set[str]] = {}
        for line in DATASET_PATH.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            hands.setdefault(str(row["split"]), set()).add(str(row["hand_id"]))
        for split in model.TRAIN_SPLITS:
            with self.subTest(split=split):
                manifest_split = self.dataset_manifest["splits"][split]
                self.assertEqual(manifest_split["hands"], len(hands[split]))
                self.assertEqual(
                    manifest_split["hand_ids_fingerprint_sha256"], fingerprint(hands[split])
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)

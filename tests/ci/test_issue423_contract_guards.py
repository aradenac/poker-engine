#!/usr/bin/env python3
"""#423 T11/T13 -- contract guardrails around the mandatory suite.

These guards do not re-test the router.  They pin the cross-cutting properties
the ticket makes non-negotiable:

* the mandatory suite has exactly one named test per ticket item (no silent
  removal, no orphan test);
* the active Model A / Model B pointers, the two registries and the model
  admitted for #367 stay byte-frozen while the whole mandatory suite runs;
* ``TEST_CONSUMED``/``VALIDATION_CONSUMED`` are false everywhere and no TEST row
  is reachable;
* the mandatory suite passes with every network primitive blocked, and none of
  the relevant modules imports a network client;
* no artifact the #423 bundle persists leaks an absolute host path: the guard
  scans the raw bytes *and* the decoded JSON values of every persisted file
  (``sha256/`` objects and ``.sha256`` sidecars included) for a CI runner home,
  the checkout root, a macOS home, a Windows separator or a drive letter, and
  carries a negative control proving it catches the pre-corrective defect.

``pytest`` is not a declared dependency of this repository; the suite is a plain
``unittest`` module, run with ``python3 -m unittest`` like its siblings.
"""
from __future__ import annotations

import ast
import contextlib
import hashlib
import importlib.util
import io
import json
import re
import socket
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path
from typing import NamedTuple
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.preflop import generalized_response_runtime as gen_runtime  # noqa: E402
from tools.preflop import hybrid_response_runtime as runtime  # noqa: E402
from tools.simulation import issue423_issue367_preflight as preflight_tool  # noqa: E402
from tools.training import build_issue423_evidence_bundle as bundle_tool  # noqa: E402
from tools.training import freeze_hybrid_router_criteria as freeze  # noqa: E402

MANDATORY_SUITE_PATH = ROOT / "tests/preflop/test_issue423_mandatory_contracts.py"
BUNDLE_DIR = ROOT / "analysis/issue423_hybrid_router"
DECISION_PATH = BUNDLE_DIR / "DECISION.json"
INDEX_PATH = BUNDLE_DIR / "ARTIFACTS.json"
PREFLIGHT_PATH = BUNDLE_DIR / "ISSUE367_PREFLIGHT.json"
SPEC_PATH = BUNDLE_DIR / "HYBRID_ROUTER_SPEC.json"
MANIFEST_PATH = BUNDLE_DIR / "ROUTER_MANIFEST.json"
REPORT_PATH = BUNDLE_DIR / "TRAIN_CV_ROUTER_REPORT.json"

#: The exact mandatory item set the ticket enumerates.
EXPECTED_ITEM_IDS = frozenset(
    {
        "FREQUENT_SPARSE_OOD_SEPARATION",
        "OOD_ABSTENTION_FAIL_CLOSED",
        "NO_NEAREST_PRICE_OR_CONTEXT_SUBSTITUTION",
        "PREREGISTERED_MARGIN",
        "SPARSE_CALIBRATION_CEILING",
        "MACHINE_READABLE_PROVENANCE",
        "TEST_UNREACHABLE",
        "ACTIVE_POINTER_IMMUTABLE",
        "ISSUE367_NOT_EXECUTED",
        "VALIDATION_421_NOT_REREAD",
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

#: This guard file imports two network primitives *only* to patch them closed;
#: every other scanned module must import none at all.
SELF_PATH = ROOT / "tests/ci/test_issue423_contract_guards.py"
NETWORK_IMPORTS_ALLOWED_FOR_THE_TRIPWIRE = frozenset({"socket", "urllib"})

SCANNED_SOURCES = (
    MANDATORY_SUITE_PATH,
    SELF_PATH,
    ROOT / "tools/simulation/issue423_issue367_preflight.py",
    ROOT / "tools/preflop/hybrid_response_router.py",
    ROOT / "tools/preflop/hybrid_response_runtime.py",
    ROOT / "tools/training/build_issue423_evidence_bundle.py",
    ROOT / "tools/training/evaluate_hybrid_router_cv.py",
    ROOT / "tools/training/freeze_hybrid_router_criteria.py",
)

# --------------------------------------------------------------------------
# #423 T13 -- absolute host path leak guard
# --------------------------------------------------------------------------
#
# Provenance in the bundle is deliberately repository-relative POSIX: an
# absolute host path (a CI runner home, the checkout root, a Windows drive)
# makes the regenerated digests host-dependent and leaks the runner layout.
# The scanner below names no host of its own -- it is machine-independent --
# and is applied to the raw bytes *and* to the decoded JSON values of every
# file the bundle persists, so a leak cannot hide behind an escape sequence.

JSON_SUFFIXES = frozenset({".json", ".jsonl"})

#: The defect this regression pins: the pre-corrective bundle recorded a
#: repository artifact by absolute host path instead of repository-relative.
PRE_FIX_ARTIFACT_SOURCE = (
    "/home/ci/runner/x/analysis/issue423_hybrid_router/HYBRID_ROUTER_SPEC.json"
)

#: The persisted field the pre-corrective defect was recorded in.
PRE_FIX_FIELD = ("evidence_bindings", "preflight_tool_path")

#: Escape-proof markers: a JSON escape sequence can neither forge nor hide one.
PLAIN_HOST_MARKERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("posix home root", re.compile(r"/home/")),
    ("macos home root", re.compile(r"/Users/")),
    ("orchestrator worktree root", re.compile(r"\.cache/poker-engine-orchestrator")),
)

#: Backslash markers: only meaningful once JSON escapes are resolved, so they
#: are applied to decoded JSON values and to non-JSON bodies, never to the raw
#: text of a JSON document where ``\n`` is a newline escape, not a separator.
WINDOWS_HOST_MARKERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("windows drive letter", re.compile(r"(?<![A-Za-z0-9_])[A-Za-z]:[\\/]")),
    ("windows path separator", re.compile(r"[A-Za-z0-9_.\-]\\[A-Za-z0-9_.\-]")),
    ("windows unc prefix", re.compile(r"\\\\[A-Za-z0-9_.\-]")),
)


class HostPathFinding(NamedTuple):
    """One absolute host path found in a persisted #423 artifact."""

    artifact: str
    origin: str
    marker: str
    snippet: str

    def render(self) -> str:
        return f"{self.artifact} [{self.origin}] {self.marker}: {self.snippet}"


def checkout_path_markers(root: Path = ROOT) -> tuple[str, ...]:
    """Absolute paths that name *this* machine: the checkout root and HOME."""
    candidates: set[str] = {str(root), root.as_posix()}
    with contextlib.suppress(RuntimeError, OSError):
        candidates.add(str(Path.home()))
    return tuple(
        sorted(marker for marker in candidates if len(marker) > 1 and marker not in {"/", "\\"})
    )


def _snippet(text: str, start: int, end: int, width: int = 100) -> str:
    """The offending text with enough context to be pasted straight into a report."""
    return " ".join(text[max(0, start - width) : min(len(text), end + width)].split())


def host_path_findings(
    text: str,
    *,
    artifact: str = "<memory>",
    origin: str = "raw text",
    windows: bool = True,
    root: Path = ROOT,
) -> list[HostPathFinding]:
    """Every absolute host path the given body carries, with the offending text."""
    findings: list[HostPathFinding] = []
    markers = PLAIN_HOST_MARKERS + (WINDOWS_HOST_MARKERS if windows else ())
    for label, pattern in markers:
        for match in pattern.finditer(text):
            findings.append(
                HostPathFinding(artifact, origin, label, _snippet(text, *match.span()))
            )
    for marker in checkout_path_markers(root):
        start = text.find(marker)
        while start != -1:
            findings.append(
                HostPathFinding(
                    artifact,
                    origin,
                    "checkout root",
                    _snippet(text, start, start + len(marker)),
                )
            )
            start = text.find(marker, start + 1)
    return list({(item.marker, item.origin, item.snippet): item for item in findings}.values())


def _json_string_values(text: str, suffix: str) -> list[str] | None:
    """Every string a JSON/JSONL body carries, or None when it is not JSON."""
    if suffix not in JSON_SUFFIXES:
        return None
    try:
        if suffix == ".jsonl":
            documents = [json.loads(line) for line in text.splitlines() if line.strip()]
        else:
            documents = [json.loads(text)]
    except ValueError:  # unparsable: keep the plain-text scan, escapes unresolved
        return None
    values: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, str):
            values.append(node)
        elif isinstance(node, dict):
            for key, item in node.items():
                values.append(str(key))
                walk(item)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for document in documents:
        walk(document)
    return values


def scan_body(
    text: str, *, artifact: str = "<body>", suffix: str = "", root: Path = ROOT
) -> list[HostPathFinding]:
    """Scan one artifact body: its raw text, then its decoded JSON values."""
    decoded = _json_string_values(text, suffix)
    findings = host_path_findings(
        text, artifact=artifact, origin="raw text", windows=decoded is None, root=root
    )
    for value in decoded or ():
        findings.extend(
            host_path_findings(value, artifact=artifact, origin="json value", root=root)
        )
    return list({(item.marker, item.origin, item.snippet): item for item in findings}.values())


def scan_artifact(path: Path, *, root: Path = ROOT) -> list[HostPathFinding]:
    """Scan one persisted file, reporting it by repository-relative path."""
    name = path.relative_to(root).as_posix() if path.is_relative_to(root) else path.as_posix()
    body = path.read_bytes().decode("utf-8", errors="replace")
    return scan_body(body, artifact=name, suffix=path.suffix, root=root)


def bundle_artifacts(bundle_dir: Path = BUNDLE_DIR) -> list[Path]:
    """Every file the bundle persists, ``sha256/`` objects and sidecars included."""
    return sorted(path for path in bundle_dir.rglob("*") if path.is_file())


def scan_bundle(
    bundle_dir: Path = BUNDLE_DIR, *, root: Path = ROOT
) -> tuple[list[Path], list[HostPathFinding]]:
    """Every persisted artifact and every absolute host path it carries."""
    artifacts = bundle_artifacts(bundle_dir)
    findings = [item for path in artifacts for item in scan_artifact(path, root=root)]
    return artifacts, findings


def load_mandatory_suite():
    """Load the consolidated mandatory suite by path (tests/ is not a package)."""
    spec = importlib.util.spec_from_file_location(
        "_issue423_mandatory_contracts", MANDATORY_SUITE_PATH
    )
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"cannot load {MANDATORY_SUITE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run_mandatory_suite() -> unittest.TestResult:
    module = load_mandatory_suite()
    suite = unittest.TestLoader().loadTestsFromTestCase(module.Issue423MandatoryContractTests)
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


class Issue423ContractGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not DECISION_PATH.is_file():
            raise unittest.SkipTest("the frozen #423 evidence bundle is absent from this worktree")
        cls.mandatory = load_mandatory_suite()
        cls.decision = json.loads(DECISION_PATH.read_text(encoding="utf-8"))
        cls.index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        cls.spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        cls.report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

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
                method = getattr(self.mandatory.Issue423MandatoryContractTests, item["test"], None)
                self.assertTrue(callable(method), item["test"])
        declared = {
            name
            for name in dir(self.mandatory.Issue423MandatoryContractTests)
            if name.startswith("test_")
        }
        self.assertEqual(
            declared - set(tests), {"test_every_mandatory_item_has_exactly_one_named_test"}
        )

    # ------------------------------------------ pointer / registry guardrail
    def test_the_active_pointer_bytes_stay_frozen_while_the_suite_runs(self) -> None:
        protected = preflight_tool.PROTECTED_FILES
        before_bytes = {path: (ROOT / path).read_bytes() for path in protected}
        before_hashes = preflight_tool.protected_hashes()
        # The pins are the digests the persisted preflight recorded when it ran.
        pinned = json.loads(PREFLIGHT_PATH.read_text(encoding="utf-8"))["protected_files"]
        self.assertEqual(set(pinned), set(protected))
        self.assertEqual(before_hashes, pinned)
        references = self.decision["references"]
        active = references["active_model_a_preflop"]
        admitted = references["admitted_model_for_issue367"]
        self.assertEqual(active["path"], admitted["path"])
        self.assertEqual(active["sha256"], admitted["sha256"])
        self.assertEqual(pinned[active["path"]], active["sha256"])
        self.assertIn(references["model_b_postflop"]["path"], pinned)
        self.assertIn("training/registry.json", pinned)
        self.assertIn("training/populations/registry.json", pinned)
        for path, digest in pinned.items():
            with self.subTest(path=path):
                self.assertIn(path, protected)
                self.assertEqual(
                    digest, hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                )
        result = run_mandatory_suite()
        self.assertTrue(
            result.wasSuccessful(), [str(case) for case, _ in result.failures + result.errors]
        )
        for path in protected:
            with self.subTest(path=path):
                self.assertEqual((ROOT / path).read_bytes(), before_bytes[path])
        self.assertEqual(preflight_tool.protected_hashes(), pinned)
        self.assertFalse(self.decision["boundaries"]["active_pointer_mutated"])
        self.assertFalse(self.decision["boundaries"]["active_model_pointer_mutation"])
        self.assertEqual(self.decision["boundaries"]["automatic_promotion"], "FORBIDDEN")
        self.assertFalse(self.manifest["assertions"]["terminal_evaluation_consumed"])
        self.assertTrue(self.manifest["assertions"]["train_only"])

    # ----------------------------------------------------- TEST consumption
    def test_test_consumed_is_false_everywhere(self) -> None:
        self.assertIs(gen_runtime.TEST_CONSUMED, False)
        self.assertIs(gen_runtime.VALIDATION_CONSUMED, False)
        self.assertIs(gen_runtime.ACTIVE_POINTER_MUTATED, False)
        audit = runtime.load_runtime(None, None, None, None).audit()
        self.assertFalse(audit["test_consumed"])
        self.assertFalse(audit["validation_consumed"])
        self.assertFalse(audit["active_model_pointer_mutated"])
        preflight, _ = preflight_tool.build()
        self.assertFalse(preflight["boundary"]["test_consumed"])
        self.assertFalse(preflight["boundary"]["test_split_authorized"])
        self.assertFalse(preflight["boundary"]["validation_split_consumed"])
        self.assertEqual(self.spec["split_policy"]["refused_splits"], ["VALIDATION", "TEST"])
        self.assertEqual(self.spec["split_policy"]["consumed_splits"], ["TRAIN"])
        self.assertFalse(self.manifest["assertions"]["test_consumed"])
        self.assertFalse(self.manifest["assertions"]["validation_consumed"])
        self.assertTrue(self.manifest["assertions"]["train_only"])
        self.assertFalse(self.report["scope"]["test_consumed"])
        self.assertFalse(self.report["scope"]["validation_consumed"])
        self.assertFalse(self.decision["boundaries"]["test_consumed"])
        self.assertFalse(self.decision["boundaries"]["test_authorized"])
        self.assertFalse(self.decision["boundaries"]["validation_consumed"])
        self.assertFalse(self.decision["boundaries"]["validation_reopened"])
        self.assertEqual(
            self.decision["boundaries"]["refused_splits"], ["VALIDATION", "TEST"]
        )
        # Negative control: a caller that asks for TEST is refused before any signal.
        with self.assertRaises(runtime.HybridResponseRuntimeError) as caught:
            runtime.guard_split({"split": "TEST"})
        self.assertEqual(caught.exception.code, runtime.FAIL_CLOSED_TEST_SPLIT)

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
        referenced = {node.id for node in ast.walk(tripwire) if isinstance(node, ast.Name)}
        referenced |= {
            node.value.id
            for node in ast.walk(tripwire)
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
        }
        self.assertIn("socket", referenced)
        self.assertIn("urllib", referenced)

    # ------------------------------------ frozen evidence cross-check
    def test_the_frozen_evidence_and_criteria_reproduce_from_the_persisted_bytes(self) -> None:
        """The index digests, the protected files and the frozen criteria re-derive."""
        for name, entry in self.index["artifacts"].items():
            with self.subTest(artifact=name):
                source = ROOT / entry["path"]
                self.assertEqual(entry["sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
        protected = preflight_tool.protected_hashes()
        for rel in (
            bundle_tool.SPEC_SCHEMA_REL,
            bundle_tool.OOD_GATE_SCHEMA_REL,
            bundle_tool.DATASET_CONTRACT_REL,
        ):
            with self.subTest(contract=rel):
                self.assertTrue((ROOT / rel).is_file(), rel)
        active = self.decision["references"]["active_model_a_preflop"]
        self.assertEqual(protected[active["path"]], active["sha256"])
        self.assertEqual(
            protected[bundle_tool.MODEL_B_REL],
            hashlib.sha256((ROOT / bundle_tool.MODEL_B_REL).read_bytes()).hexdigest(),
        )
        # The persisted preflight records exactly the live protected-file digests,
        # and the frozen criteria still re-derive from the persisted derivation.
        persisted = json.loads(PREFLIGHT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(persisted["protected_files"], protected)
        self.assertEqual(freeze.check(), [])
        self.assertEqual(freeze.check_spec_reproducible(), [])

    # ---------------------------------------- absolute host path leak guard
    def test_the_persisted_bundle_carries_no_absolute_host_path(self) -> None:
        """Every persisted artifact, sidecars and sha256 objects included, is clean."""
        artifacts, findings = scan_bundle()
        relative = {path.relative_to(BUNDLE_DIR).as_posix() for path in artifacts}
        self.assertGreater(len(artifacts), 20, sorted(relative))
        self.assertTrue(
            any(part.startswith("sha256/") or "/sha256/" in part for part in relative),
            f"the bundle must persist content-addressed objects under sha256/: {sorted(relative)}",
        )
        self.assertTrue(
            any(part.endswith(".sha256") for part in relative),
            f"the bundle must persist .sha256 sidecars: {sorted(relative)}",
        )
        self.assertEqual([], [finding.render() for finding in findings])

    def test_the_host_path_scanner_catches_the_pre_fix_artifact_source(self) -> None:
        """Negative control: the scanner must catch the pre-corrective payload."""
        payload = f"preflight_tool_path = '{PRE_FIX_ARTIFACT_SOURCE}'"
        findings = host_path_findings(payload, artifact="ISSUE367_PREFLIGHT.json")
        self.assertTrue(findings, "the scanner missed the pre-fix absolute path payload")
        self.assertTrue(
            any(PRE_FIX_ARTIFACT_SOURCE in finding.snippet for finding in findings),
            [finding.render() for finding in findings],
        )
        # The same leak through a persisted JSON artifact, plain or escaped: the
        # decoded values are scanned too, so `\/` cannot smuggle it past the guard.
        document = json.dumps({"preflight_tool_path": PRE_FIX_ARTIFACT_SOURCE})
        for body in (
            document,
            document.replace("/", r"\/"),
            document.replace("/", r"\u002f"),
        ):
            with self.subTest(body=body):
                self.assertTrue(
                    scan_body(body, artifact="ISSUE367_PREFLIGHT.json", suffix=".json"),
                    "an escaped JSON string must not evade the host path guard",
                )
        # A Windows host is the same defect on another platform.
        for body in (
            '"preflight_tool_path": "C:\\\\ci\\\\runner\\\\x\\\\HYBRID_ROUTER_SPEC.json"',
            '{"preflight_tool_path": "C:/ci/runner/x/HYBRID_ROUTER_SPEC.json"}',
        ):
            with self.subTest(body=body):
                findings = scan_body(body, artifact="ISSUE367_PREFLIGHT.json", suffix=".json")
                self.assertTrue(findings, [body])
                self.assertIn("windows drive letter", {finding.marker for finding in findings})
        # Positive control: the repository-relative form the bundle persists is clean.
        clean = "preflight_tool_path = 'tools/simulation/issue423_issue367_preflight.py'"
        self.assertEqual([], scan_body(clean, artifact="SUMMARY.md", suffix=".md"))
        self.assertEqual(
            [],
            scan_body(
                json.dumps(
                    {"preflight_tool_path": "tools/simulation/issue423_issue367_preflight.py"}
                ),
                artifact="ISSUE367_PREFLIGHT.json",
                suffix=".json",
            ),
        )

    def test_the_bundle_scan_fails_closed_on_every_leaked_artifact_kind(self) -> None:
        """The pre-fix payload inside a bundle layout: manifest, sha256 object, sidecar."""
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "issue423_hybrid_router"
            (bundle / "sha256").mkdir(parents=True)
            payload = json.dumps({"preflight_tool_path": PRE_FIX_ARTIFACT_SOURCE}, indent=2)
            manifest = bundle / "DECISION.json"
            manifest.write_text(payload, encoding="utf-8")
            obj = bundle / "sha256" / ("a" * 64 + ".json")
            obj.write_text(payload, encoding="utf-8")
            sidecar = bundle / "DECISION.sha256"
            sidecar.write_text(f"{'b' * 64}  {PRE_FIX_ARTIFACT_SOURCE}\n", encoding="utf-8")
            artifacts, findings = scan_bundle(bundle)
            self.assertEqual({manifest, obj, sidecar}, set(artifacts))
            self.assertEqual(
                {manifest.as_posix(), obj.as_posix(), sidecar.as_posix()},
                {finding.artifact for finding in findings},
                [finding.render() for finding in findings],
            )
            for finding in findings:
                self.assertIn("HYBRID_ROUTER_SPEC.json", finding.snippet)

    def test_the_pre_fix_absolute_path_is_caught_inside_the_persisted_preflight(self) -> None:
        """The defect lived in the preflight: reword it and the guard still fires."""
        document = json.loads(PREFLIGHT_PATH.read_text(encoding="utf-8"))
        group, field = PRE_FIX_FIELD
        # The persisted form is exactly the repository-relative one, so it is clean.
        self.assertEqual(
            "tools/simulation/issue423_issue367_preflight.py",
            document[group][field],
        )
        document[group][field] = PRE_FIX_ARTIFACT_SOURCE
        findings = scan_body(
            json.dumps(document),
            artifact=PREFLIGHT_PATH.relative_to(ROOT).as_posix(),
            suffix=".json",
        )
        self.assertEqual(
            {"posix home root"},
            {finding.marker for finding in findings},
            [finding.render() for finding in findings],
        )
        self.assertEqual(
            {PREFLIGHT_PATH.relative_to(ROOT).as_posix()},
            {finding.artifact for finding in findings},
        )
        self.assertTrue(
            any(PRE_FIX_ARTIFACT_SOURCE in finding.snippet for finding in findings),
            [finding.render() for finding in findings],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

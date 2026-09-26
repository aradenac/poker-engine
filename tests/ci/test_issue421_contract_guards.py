#!/usr/bin/env python3
"""#421 T11/T13 -- contract guardrails around the mandatory suite.

These guards do not re-test the model.  They pin the cross-cutting properties
the ticket makes non-negotiable:

* the mandatory suite has exactly one named test per ticket item (no silent
  removal, no orphan test);
* the active Model A / Model B pointers and the two registries stay byte-frozen
  while the whole mandatory suite runs, and match the digests pinned in the
  frozen validation protocol;
* ``TEST_CONSUMED`` is false everywhere, and no TEST row is reachable;
* the mandatory suite passes with every network primitive blocked, and none of
  the relevant modules imports a network client;
* no artifact the #421 bundle persists leaks an absolute host path: the guard
  scans the raw bytes *and* the decoded JSON values of every persisted file
  (``sha256/`` objects and ``.sha256`` sidecars included) for a CI runner home,
  the checkout root, a macOS home, a Windows separator or a drive letter, and
  carries a negative control proving it catches the pre-corrective defect.
"""
from __future__ import annotations

import ast
import contextlib
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

# --------------------------------------------------------------------------
# #421 T13 -- absolute host path leak guard
# --------------------------------------------------------------------------
#
# Provenance in the bundle is deliberately repository-relative POSIX: an
# absolute host path (a CI runner home, the checkout root, a Windows drive)
# makes the regenerated digests host-dependent and leaks the runner layout.
# The scanner below names no host of its own -- it is machine-independent --
# and is applied to the raw bytes *and* to the decoded JSON values of every
# file the bundle persists, so a leak cannot hide behind an escape sequence.

BUNDLE_DIR = ROOT / "analysis/issue421_generalized_response"
JSON_SUFFIXES = frozenset({".json", ".jsonl"})

#: The defect this regression pins: the pre-corrective bundle recorded its
#: candidate manifest by absolute host path instead of repository-relative.
PRE_FIX_REGISTRY_SOURCE = (
    "/home/ci/runner/x/analysis/issue421_generalized_response/CANDIDATE_MANIFEST.json"
)

#: The artifact the pre-corrective defect was recorded in: the #367 preflight
#: embeds one `registry_source` per queried node.
PREFLIGHT_PATH = BUNDLE_DIR / "ISSUE367_PREFLIGHT.json"

#: Escape-proof markers: a JSON escape sequence can neither forge nor hide one.
PLAIN_HOST_MARKERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("posix home root", re.compile(r"/home/")),
    ("macos home root", re.compile(r"/Users/")),
    ("orchestrator worktree root", re.compile(r"\.cache/poker-engine-orchestrator")),
)

#: Backslash markers: only meaningful once JSON escapes are resolved, so they
#: are applied to decoded JSON values and to non-JSON bodies, never to the raw
#: text of a JSON document where `\n` is a newline escape, not a separator.
WINDOWS_HOST_MARKERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("windows drive letter", re.compile(r"(?<![A-Za-z0-9_])[A-Za-z]:[\\/]")),
    ("windows path separator", re.compile(r"[A-Za-z0-9_.\-]\\[A-Za-z0-9_.\-]")),
    ("windows unc prefix", re.compile(r"\\\\[A-Za-z0-9_.\-]")),
)


class HostPathFinding(NamedTuple):
    """One absolute host path found in a persisted #421 artifact."""

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

    def test_the_host_path_scanner_catches_the_pre_fix_registry_source(self) -> None:
        """Negative control: the scanner must catch the pre-corrective payload."""
        payload = f"registry_source = '{PRE_FIX_REGISTRY_SOURCE}'"
        findings = host_path_findings(payload, artifact="CANDIDATE_MANIFEST.json")
        self.assertTrue(findings, "the scanner missed the pre-fix registry_source payload")
        self.assertTrue(
            any(PRE_FIX_REGISTRY_SOURCE in finding.snippet for finding in findings),
            [finding.render() for finding in findings],
        )
        # The same leak through a persisted JSON artifact, plain or escaped: the
        # decoded values are scanned too, so `\/` cannot smuggle it past the guard.
        document = json.dumps({"registry_source": PRE_FIX_REGISTRY_SOURCE})
        for body in (
            document,
            document.replace("/", r"\/"),
            document.replace("/", r"\u002f"),
        ):
            with self.subTest(body=body):
                self.assertTrue(
                    scan_body(body, artifact="CANDIDATE_MANIFEST.json", suffix=".json"),
                    "an escaped JSON string must not evade the host path guard",
                )
        # A Windows host is the same defect on another platform.
        for body in (
            '"registry_source": "C:\\\\ci\\\\runner\\\\x\\\\CANDIDATE_MANIFEST.json"',
            '{"registry_source": "C:/ci/runner/x/CANDIDATE_MANIFEST.json"}',
        ):
            with self.subTest(body=body):
                findings = scan_body(body, artifact="CANDIDATE_MANIFEST.json", suffix=".json")
                self.assertTrue(findings, [body])
                self.assertIn("windows drive letter", {finding.marker for finding in findings})
        # Positive control: the repository-relative form the bundle persists is clean.
        clean = (
            "registry_source = 'analysis/issue421_generalized_response/CANDIDATE_MANIFEST.json'"
        )
        self.assertEqual([], scan_body(clean, artifact="SUMMARY.md", suffix=".md"))
        self.assertEqual(
            [],
            scan_body(
                json.dumps(
                    {
                        "registry_source": (
                            "analysis/issue421_generalized_response/CANDIDATE_MANIFEST.json"
                        )
                    }
                ),
                artifact="CANDIDATE_MANIFEST.json",
                suffix=".json",
            ),
        )

    def test_the_bundle_scan_fails_closed_on_every_leaked_artifact_kind(self) -> None:
        """The pre-fix payload inside a bundle layout: manifest, sha256 object, sidecar."""
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "issue421_generalized_response"
            (bundle / "sha256").mkdir(parents=True)
            payload = json.dumps({"registry_source": PRE_FIX_REGISTRY_SOURCE}, indent=2)
            manifest = bundle / "CANDIDATE_MANIFEST.json"
            manifest.write_text(payload, encoding="utf-8")
            obj = bundle / "sha256" / ("a" * 64 + ".json")
            obj.write_text(payload, encoding="utf-8")
            sidecar = bundle / "CANDIDATE_MANIFEST.sha256"
            sidecar.write_text(f"{'b' * 64}  {PRE_FIX_REGISTRY_SOURCE}\n", encoding="utf-8")
            artifacts, findings = scan_bundle(bundle)
            self.assertEqual({manifest, obj, sidecar}, set(artifacts))
            self.assertEqual(
                {manifest.as_posix(), obj.as_posix(), sidecar.as_posix()},
                {finding.artifact for finding in findings},
                [finding.render() for finding in findings],
            )
            for finding in findings:
                self.assertIn("CANDIDATE_MANIFEST.json", finding.snippet)

    def test_the_pre_fix_registry_source_is_caught_inside_the_persisted_preflight(self) -> None:
        """The defect lived in ISSUE367_PREFLIGHT.json: reword it and the guard still fires."""
        document = json.loads(PREFLIGHT_PATH.read_text(encoding="utf-8"))
        node = document["nodes"][0]
        candidate = node["model"]["provenance"]["candidate"]
        # The persisted form is exactly the repository-relative one, so it is clean.
        self.assertEqual(
            "analysis/issue421_generalized_response/CANDIDATE_MANIFEST.json",
            candidate["registry_source"],
        )
        candidate["registry_source"] = PRE_FIX_REGISTRY_SOURCE
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
            any(PRE_FIX_REGISTRY_SOURCE in finding.snippet for finding in findings),
            [finding.render() for finding in findings],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

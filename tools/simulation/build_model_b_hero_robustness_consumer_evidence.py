#!/usr/bin/env python3
"""backlog-ncv -- persist the #425 consolidation evidence of the preserved chain.

This tool closes the loop of the ``#425`` consolidation: it re-executes the
**preserved** chain end to end, records the outcome of every suite and of every
command documented for that chain, and versions the result next to the
canonical bundle:

``training/runs/20260927_model_b_hero_robustness_consumer_v1/``

* ``TEST_REPORT.json`` -- one entry per executed suite (``#425`` preserved
  suites, the ``#344`` harness suite and the ``#199`` non-regression suite) plus
  the documented CLI commands, the bundle determinism checks and the honest
  execution limits. A skipped test is reported as *skipped*, never as a pass.
* ``N8N_TASK_RESULT.json`` -- the machine-readable task result derived from the
  checks, carrying ``issue=425``, ``next_issue=315``, ``parent_closed=false``,
  ``real_hero_results_consumed=false``, ``validation_consumed=false`` and
  ``test_consumed=false``.

The bundle itself (reports + fixed artifacts) stays owned by the single
regeneration command of the chain:

    PYTHONPATH=. python3 tools/simulation/build_model_b_hero_robustness_consumer_run.py
    PYTHONPATH=. python3 tools/simulation/build_model_b_hero_robustness_consumer_run.py --check
    PYTHONPATH=. python3 tools/simulation/build_model_b_hero_robustness_consumer_run.py --verify-determinism

This tool only *verifies* that bundle (``--check`` first, so a drifted bundle is
never silently rewritten), regenerates it with the canonical command and records
the resulting digests. The evidence is written by the companion command:

    PYTHONPATH=. python3 tools/simulation/build_model_b_hero_robustness_consumer_evidence.py
    PYTHONPATH=. python3 tools/simulation/build_model_b_hero_robustness_consumer_evidence.py --check

No timestamp, no host path and no duration is embedded, so two runs over the same
tree produce byte-identical evidence. The evidence is synthetic-only: the real
``#367``/``#314`` evidence, the VALIDATION hand and the TEST hand are never
opened, nothing is promoted and ``#315`` is not closed.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.simulation import build_model_b_hero_robustness_consumer_run as builder  # noqa: E402

__all__ = [
    "ISSUE",
    "PARENT_ISSUE",
    "NEXT_ISSUE",
    "RUN_DIR",
    "RUN_REL",
    "TEST_REPORT_NAME",
    "N8N_RESULT_NAME",
    "TEST_REPORT_SCHEMA",
    "N8N_RESULT_SCHEMA",
    "SUITES",
    "DOCUMENTED_COMMANDS",
    "ACCEPTANCE_EVIDENCE",
    "EVIDENCE_SCRIPT",
    "EVIDENCE_COMMANDS",
    "REMOVED_CHAIN_PATHS",
    "EvidenceError",
    "removed_chain_check",
    "doc_alignment_check",
    "acceptance_evidence_check",
    "build_test_report",
    "build_task_result",
    "render",
    "write_evidence",
    "check_evidence",
    "validate_task_result",
    "main",
]

ISSUE = 425
PARENT_ISSUE = 315
NEXT_ISSUE = 315
RUN_ID = builder.RUN_ID
RUN_REL = builder.RUN_REL
RUN_DIR = builder.RUN_DIR

TEST_REPORT_NAME = "TEST_REPORT.json"
N8N_RESULT_NAME = "N8N_TASK_RESULT.json"
TEST_REPORT_SCHEMA = "hero-model-b-robustness-consumer-test-report/v1"
N8N_RESULT_SCHEMA = "hero-model-b-robustness-consumer-n8n-task-result/v1"

#: The consolidated #425 documentation of the preserved chain.
DOC_PATHS = (
    ROOT / "docs/model-b-hero-robustness-consumer.md",
    ROOT / "docs/model-b-robustness-consumer.md",
)

#: This tool's own script, so the evidence commands are documented as well.
EVIDENCE_SCRIPT = "tools/simulation/build_model_b_hero_robustness_consumer_evidence.py"
EVIDENCE_COMMANDS: Mapping[str, str] = {
    "regeneration_command": f"PYTHONPATH=. python3 {EVIDENCE_SCRIPT}",
    "check_command": f"PYTHONPATH=. python3 {EVIDENCE_SCRIPT} --check",
    "recorded_by": (
        "this report: the regeneration command emits it and --check compares it "
        "with a fresh run"
    ),
}

#: Suites executed and recorded by the consolidation evidence.
#: ``parser`` selects how the script reports its result:
#: ``unittest`` -> ``Ran N tests`` / ``OK``; ``sections`` -> ``(p/t sections): PASS``;
#: ``marker`` -> a single explicit ``PASS`` line.
SUITES: tuple[Mapping[str, Any], ...] = (
    {
        "id": "model_b_hero_robustness_contract",
        "issue": ISSUE,
        "script": "tests/simulation/test_model_b_hero_robustness_contract.py",
        "parser": "unittest",
        "role": "fail-closed contract bridge and metadata -> feature boundary",
    },
    {
        "id": "model_b_hero_robustness_classify",
        "issue": ISSUE,
        "script": "tests/simulation/test_model_b_hero_robustness_classify.py",
        "parser": "unittest",
        "role": "deterministic #425 classifier (precedence, close band, clearly superior)",
    },
    {
        "id": "model_b_hero_robustness_adapter",
        "issue": ISSUE,
        "script": "tests/simulation/test_model_b_hero_robustness_adapter.py",
        "parser": "unittest",
        "role": "runner CLI, report contract and the three human corrections",
    },
    {
        "id": "model_b_hero_robustness_consumer",
        "issue": ISSUE,
        "script": "tests/simulation/test_model_b_hero_robustness_consumer.py",
        "parser": "sections",
        "role": "consumer integration suite (9 sections incl. metadata invariance)",
    },
    {
        "id": "model_b_hero_robustness_consumer_run",
        "issue": ISSUE,
        "script": "tests/simulation/test_model_b_hero_robustness_consumer_run.py",
        "parser": "unittest",
        "role": "canonical run bundle: regeneration, --check and determinism",
    },
    {
        "id": "model_b_preflop_sensitivity_harness",
        "issue": 344,
        "script": "tests/simulation/test_model_b_preflop_sensitivity_harness.py",
        "parser": "marker",
        "role": "reused #344 synthetic harness (unchanged contract)",
    },
    {
        "id": "model_b_robustness",
        "issue": 199,
        "script": "tests/simulation/test_model_b_robustness.py",
        "parser": "unittest",
        "role": "#199 backend non-regression (semantics untouched)",
    },
)

#: The commands documented for the preserved chain. ``script`` is verified to be
#: documented in the consolidated #425 docs, so the recorded evidence cannot
#: drift from the documentation.
DOCUMENTED_COMMANDS: tuple[Mapping[str, Any], ...] = (
    {
        "id": "runner_cli_single_fixture",
        "script": "tools/simulation/model_b_hero_robustness_adapter.py",
        "issue": ISSUE,
        "command": (
            "PYTHONPATH=. python3 tools/simulation/model_b_hero_robustness_adapter.py "
            "--fixture tests/fixtures/model_b_hero_robustness/robust_consistent.json"
        ),
        "expects": "the deterministic report on stdout (schema and status)",
    },
    {
        "id": "run_builder_check",
        "script": "tools/simulation/build_model_b_hero_robustness_consumer_run.py",
        "issue": ISSUE,
        "command": (
            "PYTHONPATH=. python3 tools/simulation/build_model_b_hero_robustness_consumer_run.py --check"
        ),
        "expects": "ok=true: the versioned bundle matches a fresh build",
    },
    {
        "id": "run_builder_regenerate",
        "script": "tools/simulation/build_model_b_hero_robustness_consumer_run.py",
        "issue": ISSUE,
        "command": (
            "PYTHONPATH=. python3 tools/simulation/build_model_b_hero_robustness_consumer_run.py"
        ),
        "expects": "the bundle is written only when two passes are byte-identical",
    },
    {
        "id": "run_builder_verify_determinism",
        "script": "tools/simulation/build_model_b_hero_robustness_consumer_run.py",
        "issue": ISSUE,
        "command": (
            "PYTHONPATH=. python3 tools/simulation/build_model_b_hero_robustness_consumer_run.py "
            "--verify-determinism"
        ),
        "expects": "deterministic=true with the sha256 of every artifact",
    },
)

#: Paths of the removed, incompatible #425 chain. None of them may exist any
#: more, and the consolidated docs must not reference them.
REMOVED_CHAIN_PATHS: tuple[str, ...] = (
    "tools/simulation/model_b_hero_robustness_consumer.py",
    "tools/simulation/model_b_hero_robustness_status.py",
    "tools/simulation/build_issue425_robustness_consumer_run.py",
    "tests/simulation/test_issue425_robustness_consumer_run.py",
    "tests/simulation/test_model_b_hero_robustness_status.py",
    "tests/fixtures/model_b_robustness_consumer",
    "training/runs/20260926_issue425_model_b_robustness_consumer_v1",
)

#: Tokens that would point the documentation back at the removed chain.
REMOVED_CHAIN_TOKENS: tuple[str, ...] = (
    "tools/simulation/model_b_hero_robustness_consumer.py",
    "tools/simulation/model_b_hero_robustness_status.py",
    "tools/simulation/build_issue425_robustness_consumer_run.py",
    "tests/simulation/test_issue425_robustness_consumer_run.py",
    "tests/simulation/test_model_b_hero_robustness_status.py",
    "tests/fixtures/model_b_robustness_consumer",
    "SYNTHETIC_ROBUSTNESS_PROJECTED",
    "20260926_issue425",
)

#: Traceability from the ticket acceptance items to the tests that prove them.
#: Every ``tests`` entry is a symbol that must exist in the suite script, so a
#: renamed or deleted regression makes the evidence fail instead of going stale.
ACCEPTANCE_EVIDENCE: tuple[Mapping[str, Any], ...] = (
    {
        "acceptance": "schema mismatch fails closed with a reason code",
        "suite": "model_b_hero_robustness_consumer",
        "tests": ["def test_schema_mismatch_fails_closed"],
        "note": "section (1): SCHEMA_MISMATCH, exit code 2 and no report",
    },
    {
        "acceptance": "missing provenance / support is an explicit rejection",
        "suite": "model_b_hero_robustness_consumer",
        "tests": ["def test_missing_provenance_and_support_are_explicit"],
        "note": "section (2): MISSING_PROVENANCE / MISSING_SUPPORT, never a status",
    },
    {
        "acceptance": "OOD_UNTESTABLE is preserved",
        "suite": "model_b_hero_robustness_consumer",
        "tests": ["def test_ood_fixture_is_ood_untestable"],
        "note": "section (3): ood_unsupported.json",
    },
    {
        "acceptance": "TOO_CLOSE is preserved",
        "suite": "model_b_hero_robustness_consumer",
        "tests": ["def test_too_close_is_preserved"],
        "note": "section (4): never requalified CONSISTENT / SENSITIVE",
    },
    {
        "acceptance": "human correction 1: width derived from the ci95 bounds",
        "suite": "model_b_hero_robustness_adapter",
        "tests": [
            "def test_width_contradicting_the_bounds_fails_closed",
        ],
        "note": "the contract suite also asserts UNCERTAINTY_WIDTH_MISMATCH",
    },
    {
        "acceptance": "human correction 2: every compared alternative uncertainty is checked",
        "suite": "model_b_hero_robustness_adapter",
        "tests": [
            "def test_secondary_alternative_without_uncertainty_is_not_consistent",
            "def test_broken_secondary_alternative_verdict_is_order_independent",
        ],
        "note": "a secondary alternative can never be masked into CONSISTENT",
    },
    {
        "acceptance": "human correction 3: a clearly superior alternative is SENSITIVE",
        "suite": "model_b_hero_robustness_adapter",
        "tests": [
            "def test_better_evaluated_alternatives_are_sensitive_not_too_close",
        ],
        "note": "BEST_ALTERNATIVE_CLEARLY_SUPERIOR, no sizing recommendation",
    },
    {
        "acceptance": "independence: allowed projected fields only, closed boundary",
        "suite": "model_b_hero_robustness_consumer",
        "tests": ["def test_projected_request_is_independent_from_model_a"],
        "note": "section (8), mirrored by INDEPENDENCE_PROOF.json and the #425 guards",
    },
    {
        "acceptance": "request unchanged when only the metadata varies",
        "suite": "model_b_hero_robustness_contract",
        "tests": [
            "def test_request_is_unchanged_when_only_metadata_varies",
            "def test_classification_may_move_while_the_request_stays_pinned",
            "def test_public_identity_change_does_change_the_request",
        ],
        "note": "section (9) of the consumer suite asserts the same end to end",
    },
    {
        "acceptance": "reused #344 harness only accepts its own synthetic source kind",
        "suite": "model_b_hero_robustness_contract",
        "tests": [
            "def test_harness_refuses_a_foreign_source_kind",
            "def test_harness_refuses_an_injected_ev_feature",
        ],
        "note": "#344 module/contract/test/doc stay unedited",
    },
    {
        "acceptance": "two regenerations are byte-identical and --check finds no drift",
        "suite": "model_b_hero_robustness_consumer_run",
        "tests": [
            "def test_two_regenerations_produce_identical_sha256",
            "def test_check_mode_passes_on_the_persisted_run",
            "def test_verify_determinism_cli_succeeds",
        ],
        "note": "re-executed here as the documented builder commands",
    },
)

_RAN_RE = re.compile(r"Ran (\d+) tests? in ")
_OK_RE = re.compile(r"^OK(?: \(([^)]*)\))?$", re.MULTILINE)
_SECTIONS_RE = re.compile(
    r"#425 Hero -> Model B robustness consumer \((\d+)/(\d+) sections\): PASS"
)
_MARKER_RE = re.compile(r"Issue #344 synthetic Model B sensitivity harness: PASS")
_SKIPPED_RE = re.compile(r"skipped=(\d+)")
_COMMAND_TIMEOUT_S = 900


class EvidenceError(RuntimeError):
    """The consolidation evidence could not be assembled."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(Path(path).read_bytes())


def render(payload: Any) -> str:
    """Render evidence deterministically (sorted keys, one trailing newline)."""
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(ROOT) if not existing else f"{ROOT}{os.pathsep}{existing}"
    return subprocess.run(
        list(command),
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=_COMMAND_TIMEOUT_S,
    )


def _rel(path: Path | str) -> str:
    """Repository-relative path, so no host path is embedded in the evidence."""
    resolved = Path(path)
    try:
        return str(resolved.resolve().relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(resolved)


def _suite_outcome(spec: Mapping[str, Any], proc: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    output = f"{proc.stdout}\n{proc.stderr}"
    tests_run: int | None = None
    tests_skipped: int | None = None
    detail: str

    if spec["parser"] == "unittest":
        ran = _RAN_RE.search(output)
        tests_run = int(ran.group(1)) if ran else None
        ok = _OK_RE.search(output)
        skipped = _SKIPPED_RE.search(ok.group(1)) if ok and ok.group(1) else None
        tests_skipped = int(skipped.group(1)) if skipped else 0
        passed = proc.returncode == 0 and ok is not None
        detail = "unittest OK" if passed else "unittest did not report OK"
    elif spec["parser"] == "sections":
        match = _SECTIONS_RE.search(output)
        if match:
            tests_run = int(match.group(2))
            tests_skipped = 0
        passed = proc.returncode == 0 and match is not None
        detail = (
            f"{match.group(1)}/{match.group(2)} sections PASS"
            if match
            else "the consumer suite did not report a full PASS"
        )
    else:  # marker
        match = _MARKER_RE.search(output)
        passed = proc.returncode == 0 and match is not None
        detail = "explicit PASS marker" if passed else "the suite printed no PASS marker"

    return {
        "id": spec["id"],
        "issue": spec["issue"],
        "role": spec["role"],
        "script": spec["script"],
        "command": f"PYTHONPATH=. python3 {spec['script']}",
        "outcome": "PASS" if passed else "FAIL",
        "exit_code": proc.returncode,
        "tests_run": tests_run,
        "tests_skipped": tests_skipped,
        "detail": detail,
    }


def _documented_command_check(
    spec: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run one documented command; return its record and its JSON stdout payload."""
    argv = spec["command"].split()
    if argv[0] != "PYTHONPATH=.":
        raise EvidenceError(f"documented command must set PYTHONPATH: {spec['command']}")
    proc = _run([sys.executable, *argv[2:]])
    try:
        payload = json.loads(proc.stdout)
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    observation = ""
    if spec["id"] == "runner_cli_single_fixture":
        observation = (
            f"stdout report schema={payload.get('schema')!r} "
            f"status={payload.get('status')!r}"
        )
    elif spec["id"] == "run_builder_check":
        observation = (
            f"check ok={payload.get('ok')!r} mismatches={payload.get('mismatches')!r} "
            f"missing={payload.get('missing')!r}"
        )
    elif spec["id"] == "run_builder_regenerate":
        observation = f"deterministic={payload.get('deterministic')!r}"
    elif spec["id"] == "run_builder_verify_determinism":
        observation = (
            f"deterministic={payload.get('deterministic')!r} "
            f"artifacts={len(payload.get('sha256') or {})}"
        )

    record = {
        "id": spec["id"],
        "issue": spec["issue"],
        "command": spec["command"],
        "expects": spec["expects"],
        "exit_code": proc.returncode,
        "outcome": "PASS" if proc.returncode == 0 else "FAIL",
        "observation": observation,
    }
    return record, payload


def removed_chain_check() -> dict[str, Any]:
    """Assert the removed #425 chain is gone and unreferenced by the docs."""
    present = sorted(rel for rel in REMOVED_CHAIN_PATHS if (ROOT / rel).exists())
    hits: list[str] = []
    for doc in DOC_PATHS:
        if not doc.is_file():
            raise EvidenceError(f"missing consolidated #425 documentation: {doc}")
        text = doc.read_text(encoding="utf-8")
        for token in REMOVED_CHAIN_TOKENS:
            if token in text:
                hits.append(f"{doc.name}:{token}")
    return {
        "paths": list(REMOVED_CHAIN_PATHS),
        "present_paths": present,
        "doc_tokens": list(REMOVED_CHAIN_TOKENS),
        "doc_hits": sorted(hits),
        "outcome": "PASS" if not present and not hits else "FAIL",
    }


def doc_alignment_check(commands: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Assert every documented command is actually documented."""
    docs = "\n".join(path.read_text(encoding="utf-8") for path in DOC_PATHS)
    scripts = {command["script"] for command in commands} | {EVIDENCE_SCRIPT}
    missing = sorted(script for script in scripts if script not in docs)
    return {
        "documents": [f"docs/{path.name}" for path in DOC_PATHS],
        "missing_scripts": missing,
        "outcome": "PASS" if not missing else "FAIL",
    }


def acceptance_evidence_check() -> dict[str, Any]:
    """Assert every acceptance-evidence reference still exists in its suite."""
    scripts = {spec["id"]: spec["script"] for spec in SUITES}
    missing: list[str] = []
    for entry in ACCEPTANCE_EVIDENCE:
        script = scripts.get(entry["suite"])
        if script is None:
            missing.append(f"{entry['acceptance']}: unknown suite {entry['suite']!r}")
            continue
        source = (ROOT / script).read_text(encoding="utf-8")
        for symbol in entry["tests"]:
            if symbol not in source:
                missing.append(f"{entry['acceptance']}: {script} misses {symbol!r}")
    return {
        "items": len(ACCEPTANCE_EVIDENCE),
        "missing_references": sorted(missing),
        "outcome": "PASS" if not missing else "FAIL",
    }


def _bundle_section(
    *,
    check_payload: Mapping[str, Any],
    determinism_payload: Mapping[str, Any],
) -> dict[str, Any]:
    names = builder.artifact_names(sorted(builder.EXPECTED_FIXTURE_STATUSES))
    digests = {
        name: _sha256_file(RUN_DIR / name)
        for name in names
        if (RUN_DIR / name).is_file()
    }
    return {
        "run_id": RUN_ID,
        "run_dir": RUN_REL,
        "regeneration_command": builder.regeneration_command(),
        "check_command": f"PYTHONPATH=. python3 {builder.BUILDER_REL} --check",
        "determinism_command": (
            f"PYTHONPATH=. python3 {builder.BUILDER_REL} --verify-determinism"
        ),
        "check": {
            "ok": bool(check_payload.get("ok")),
            "missing": list(check_payload.get("missing") or []),
            "mismatches": list(check_payload.get("mismatches") or []),
        },
        "determinism": {
            "deterministic": bool(determinism_payload.get("deterministic")),
            "sha256": dict(determinism_payload.get("sha256") or {}),
        },
        "artifacts": dict(sorted(digests.items())),
    }


def _limitations(*, jsonschema_available: bool, skipped_tests: int) -> list[str]:
    limits = [
        "Local evidence only: this worker sandbox runs no GitHub Actions workflow and "
        "performs no network I/O, so the CI gate status is NOT_OBSERVED here.",
        "The suites run the available local CPython interpreter, not the CI-pinned "
        "3.11 image.",
        "No real #367/#314 evidence, no VALIDATION/TEST hand and no promotion is "
        "consumed: only the committed synthetic fixtures, the synthetic #344 context "
        "and the persisted #340 candidate/reference evidence are read.",
    ]
    if not jsonschema_available:
        limits.append(
            "jsonschema is not installed in this environment, so the adapter suite "
            "skips its jsonschema cross-check; the shipped report schema is still "
            "enforced by the adapter built-in walker."
        )
    if skipped_tests:
        limits.append(
            f"{skipped_tests} test(s) reported as skipped (not as a pass); see the "
            "per-suite tests_skipped field."
        )
    return limits


def build_test_report(
    *,
    suites: Sequence[Mapping[str, Any]],
    commands: Sequence[Mapping[str, Any]],
    removed: Mapping[str, Any],
    doc_alignment: Mapping[str, Any],
    acceptance: Mapping[str, Any],
    bundle: Mapping[str, Any],
) -> dict[str, Any]:
    jsonschema_available = importlib.util.find_spec("jsonschema") is not None
    skipped_tests = sum(
        int(suite["tests_skipped"] or 0) for suite in suites
    )
    suites_failed = [suite["id"] for suite in suites if suite["outcome"] != "PASS"]
    commands_failed = [
        command["id"] for command in commands if command["outcome"] != "PASS"
    ]
    status = (
        "READY_FOR_INTEGRATION"
        if not suites_failed
        and not commands_failed
        and removed["outcome"] == "PASS"
        and doc_alignment["outcome"] == "PASS"
        and acceptance["outcome"] == "PASS"
        and bundle["check"]["ok"]
        and bundle["determinism"]["deterministic"]
        else "NEEDS_FIXES"
    )
    return {
        "schema": TEST_REPORT_SCHEMA,
        "task": "backlog-ncv",
        "issue": ISSUE,
        "parent_issue": PARENT_ISSUE,
        "next_issue": NEXT_ISSUE,
        "run_id": RUN_ID,
        "run_dir": RUN_REL,
        "status": status,
        "suites": list(suites),
        "suites_failed": suites_failed,
        "documented_commands": list(commands),
        "documented_commands_failed": commands_failed,
        "evidence_commands": dict(EVIDENCE_COMMANDS),
        "removed_chain": dict(removed),
        "documentation_alignment": dict(doc_alignment),
        "acceptance_evidence": [dict(entry) for entry in ACCEPTANCE_EVIDENCE],
        "acceptance_evidence_check": dict(acceptance),
        "bundle": dict(bundle),
        "environment": {
            "jsonschema_available": jsonschema_available,
            "pytest_used": False,
        },
        "limitations": _limitations(
            jsonschema_available=jsonschema_available, skipped_tests=skipped_tests
        ),
        "non_consumption": {
            "real_hero_results_consumed": False,
            "validation_consumed": False,
            "test_consumed": False,
            "real_issue_367_consumed": False,
            "real_issue_314_consumed": False,
            "active_model_b_changed": False,
            "automatic_promotion": False,
            "production_effect": "NONE",
            "parent_closed": False,
        },
    }


def build_task_result(test_report: Mapping[str, Any]) -> dict[str, Any]:
    """Derive the n8n task result from the executed checks."""
    commands = list(test_report["documented_commands"])
    commands_ok = all(command["outcome"] == "PASS" for command in commands)
    suites = list(test_report["suites"])
    return {
        "schema": N8N_RESULT_SCHEMA,
        "task": "backlog-ncv",
        "issue": ISSUE,
        "parent_issue": PARENT_ISSUE,
        "next_issue": NEXT_ISSUE,
        "status": test_report["status"],
        "status_basis": [
            f"suites: {len(suites) - len(test_report['suites_failed'])}/{len(suites)} PASS",
            f"documented commands: {len(commands) - len(test_report['documented_commands_failed'])}/{len(commands)} exit 0",
            f"removed chain: {test_report['removed_chain']['outcome']}",
            f"documentation alignment: {test_report['documentation_alignment']['outcome']}",
            "acceptance evidence: "
            f"{test_report['acceptance_evidence_check']['outcome']} "
            f"({test_report['acceptance_evidence_check']['items']} items)",
            f"bundle --check: ok={test_report['bundle']['check']['ok']}",
            "bundle regeneration: deterministic="
            f"{test_report['bundle']['determinism']['deterministic']}",
        ],
        "suites_passed": len(suites) - len(test_report["suites_failed"]),
        "suites_total": len(suites),
        "suites_failed": list(test_report["suites_failed"]),
        "documented_commands_all_succeeded": commands_ok,
        "acceptance_evidence_ok": (
            test_report["acceptance_evidence_check"]["outcome"] == "PASS"
        ),
        "acceptance_evidence_items": test_report["acceptance_evidence_check"]["items"],
        "bundle_check_ok": bool(test_report["bundle"]["check"]["ok"]),
        "bundle_deterministic": bool(
            test_report["bundle"]["determinism"]["deterministic"]
        ),
        "run_id": RUN_ID,
        "run_dir": RUN_REL,
        "test_report": TEST_REPORT_NAME,
        "bundle_sha256": dict(test_report["bundle"]["artifacts"]),
        "parent_closed": False,
        "real_hero_results_consumed": False,
        "validation_consumed": False,
        "test_consumed": False,
        "real_issue_367_consumed": False,
        "real_issue_314_consumed": False,
        "active_model_b_changed": False,
        "automatic_promotion": False,
        "production_effect": "NONE",
        "limitations": list(test_report["limitations"]),
        "next_action": (
            "INTEGRATION_GATE"
            if test_report["status"] == "READY_FOR_INTEGRATION"
            else "REWORK"
        ),
    }


def build_evidence() -> dict[str, str]:
    """Run everything once and return the two rendered evidence files."""
    suites = []
    for spec in SUITES:
        proc = _run([sys.executable, spec["script"]])
        suites.append(_suite_outcome(spec, proc))
    commands = []
    payloads: dict[str, dict[str, Any]] = {}
    for spec in DOCUMENTED_COMMANDS:
        record, payload = _documented_command_check(spec)
        commands.append(record)
        payloads[spec["id"]] = payload
    removed = removed_chain_check()
    alignment = doc_alignment_check(DOCUMENTED_COMMANDS)
    acceptance = acceptance_evidence_check()
    bundle = _bundle_section(
        check_payload=payloads.get("run_builder_check", {}),
        determinism_payload=payloads.get("run_builder_verify_determinism", {}),
    )
    test_report = build_test_report(
        suites=suites,
        commands=commands,
        removed=removed,
        doc_alignment=alignment,
        acceptance=acceptance,
        bundle=bundle,
    )
    task_result = build_task_result(test_report)
    return {
        TEST_REPORT_NAME: render(test_report),
        N8N_RESULT_NAME: render(task_result),
    }


def write_evidence(out_dir: Path | str = RUN_DIR) -> dict[str, str]:
    """Write the two consolidation evidence files; return their sha256."""
    evidence = build_evidence()
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    for name, text in sorted(evidence.items()):
        (target / name).write_text(text, encoding="utf-8")
    return {name: _sha256_bytes(text.encode("utf-8")) for name, text in sorted(evidence.items())}


def check_evidence(out_dir: Path | str = RUN_DIR) -> dict[str, Any]:
    """Rebuild the evidence and compare it with the persisted files."""
    evidence = build_evidence()
    target = Path(out_dir)
    missing: list[str] = []
    mismatches: list[str] = []
    digests: dict[str, str] = {}
    for name, text in sorted(evidence.items()):
        path = target / name
        if not path.is_file():
            missing.append(name)
            continue
        persisted = path.read_text(encoding="utf-8")
        digests[name] = _sha256_bytes(persisted.encode("utf-8"))
        if persisted != text:
            mismatches.append(name)
    return {
        "out_dir": _rel(target),
        "missing": missing,
        "mismatches": mismatches,
        "sha256": digests,
        "ok": not missing and not mismatches,
    }


def validate_task_result(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Fail-closed validation of a persisted ``N8N_TASK_RESULT.json``.

    Pure and cheap, so the acceptance test never has to re-execute the suites.
    """
    if payload.get("schema") != N8N_RESULT_SCHEMA:
        raise EvidenceError(f"unexpected n8n task result schema: {payload.get('schema')!r}")
    if payload.get("issue") != ISSUE or payload.get("next_issue") != NEXT_ISSUE:
        raise EvidenceError("the n8n task result must pin issue=425 and next_issue=315")
    for flag in (
        "parent_closed",
        "real_hero_results_consumed",
        "validation_consumed",
        "test_consumed",
        "real_issue_367_consumed",
        "real_issue_314_consumed",
        "active_model_b_changed",
        "automatic_promotion",
    ):
        if payload.get(flag) is not False:
            raise EvidenceError(f"the n8n task result must pin {flag}=false")
    if payload.get("production_effect") != "NONE":
        raise EvidenceError("the n8n task result must pin production_effect='NONE'")
    if payload.get("status") not in {"READY_FOR_INTEGRATION", "NEEDS_FIXES"}:
        raise EvidenceError(f"unexpected n8n status: {payload.get('status')!r}")
    for key in (
        "suites_passed",
        "suites_total",
        "documented_commands_all_succeeded",
        "bundle_check_ok",
        "bundle_deterministic",
        "bundle_sha256",
        "status_basis",
    ):
        if key not in payload:
            raise EvidenceError(f"the n8n task result is missing {key!r}")
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=RUN_DIR)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if the persisted evidence drifts from a fresh run",
    )
    return parser


def _print(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.check:
            report = check_evidence(args.out_dir)
            _print(report)
            return 0 if report["ok"] else 1
        digests = write_evidence(args.out_dir)
        _print({"out_dir": _rel(args.out_dir), "sha256": digests})
        return 0
    except EvidenceError as exc:
        _print({"status": "FAIL_CLOSED", "error": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

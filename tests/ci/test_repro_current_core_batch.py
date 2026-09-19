#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_PATH = ROOT / "analysis/workflow_audit/repro_current_core_batch_before_after.json"
STATIC_GUARD = "PYTHONPATH=. python3 tests/ci/test_repro_current_core_batch.py"


def _load() -> dict:
    value = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def _tokens_sha(tokens: list[str]) -> str:
    payload = json.dumps(tokens, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _top_section(text: str, key: str) -> list[str]:
    lines = text.splitlines()
    start = next((i + 1 for i, line in enumerate(lines) if line == f"{key}:"), None)
    if start is None:
        return []
    out: list[str] = []
    for line in lines[start:]:
        if line and not line.startswith((" ", "\t")) and not line.lstrip().startswith("#"):
            break
        out.append(line)
    return out


def _events(text: str) -> list[str]:
    section = _top_section(text, "on")
    result = []
    for line in section:
        match = re.match(r"^  ([A-Za-z_][\w-]*):\s*(?:.*)?$", line)
        if match:
            result.append(match.group(1))
    return result


def _event_block(text: str, event: str) -> list[str]:
    section = _top_section(text, "on")
    start = next((i for i, line in enumerate(section) if re.match(rf"^  {re.escape(event)}:", line)), None)
    if start is None:
        return []
    out = []
    for line in section[start + 1:]:
        if re.match(r"^  [A-Za-z_][\w-]*:", line):
            break
        out.append(line)
    return out


def _event_paths(text: str, event: str) -> list[str]:
    block = _event_block(text, event)
    start = next((i for i, line in enumerate(block) if line.strip() == "paths:"), None)
    if start is None:
        return []
    out = []
    for line in block[start + 1:]:
        if line.strip() and len(line) - len(line.lstrip(" ")) <= 4:
            break
        match = re.match(r"^\s+-\s+['\"]?(.+?)['\"]?\s*$", line)
        if match:
            out.append(match.group(1).rstrip("'\""))
    return out


def _event_branches(text: str, event: str) -> list[str]:
    block = _event_block(text, event)
    for line in block:
        match = re.match(r"^\s{4}branches:\s*\[(.*?)\]\s*$", line)
        if match:
            return [x.strip().strip("'\"") for x in match.group(1).split(",") if x.strip()]
    return []


def _jobs(text: str) -> list[dict]:
    section = _top_section(text, "jobs")
    starts = []
    for i, line in enumerate(section):
        match = re.match(r"^  ([A-Za-z_][\w-]*):\s*$", line)
        if match:
            starts.append((i, match.group(1)))
    result = []
    for pos, (start, job_id) in enumerate(starts):
        end = starts[pos + 1][0] if pos + 1 < len(starts) else len(section)
        block = section[start + 1:end]
        runner = None
        needs: list[str] = []
        for line in block:
            m = re.match(r"^\s{4}(runs-on|needs):\s*(.+?)\s*$", line)
            if not m:
                continue
            if m.group(1) == "runs-on":
                runner = m.group(2).strip("'\"")
            else:
                raw = m.group(2).strip()
                if raw.startswith("[") and raw.endswith("]"):
                    needs = [x.strip().strip("'\"") for x in raw[1:-1].split(",") if x.strip()]
                elif raw:
                    needs = [raw.strip("'\"")]
        result.append({"id": job_id, "runner": runner, "needs": needs})
    return result


def _audit_text(row: dict, text: str, *, check_blob: bool = True) -> list[dict]:
    violations: list[dict] = []
    path = row["path"]

    if check_blob:
        observed = _git_blob_sha(text.encode())
        if observed != row["after_git_blob_sha"]:
            violations.append({
                "rule": "WORKFLOW_BLOB_CHANGED_WITHOUT_EVIDENCE_REFRESH",
                "path": path,
                "expected": row["after_git_blob_sha"],
                "observed": observed,
            })

    if _events(text) != row["events"]:
        violations.append({
            "rule": "TRIGGER_EVENTS_CHANGED",
            "path": path,
            "expected": row["events"],
            "observed": _events(text),
        })

    for event, historical in row["historical_paths"].items():
        expected = historical[:-1] + row["repro_paths_added"] + [historical[-1]]
        observed = _event_paths(text, event)
        if observed != expected:
            violations.append({
                "rule": "TRIGGER_PATHS_CHANGED",
                "path": path,
                "event": event,
                "expected": expected,
                "observed": observed,
            })

    if "push_branches_after" in row:
        observed = _event_branches(text, "push")
        if observed != row["push_branches_after"]:
            violations.append({
                "rule": "PUSH_BRANCHES_CHANGED",
                "path": path,
                "expected": row["push_branches_after"],
                "observed": observed,
            })

    expected_permissions = row["permissions"]
    if expected_permissions is None:
        if re.search(r"(?m)^permissions:\s*$", text):
            violations.append({"rule": "PERMISSIONS_ADDED", "path": path})
    else:
        if "permissions:\n  contents: read\n" not in text:
            violations.append({"rule": "PERMISSIONS_CHANGED", "path": path})

    if row["concurrency"] is None and re.search(r"(?m)^concurrency:\s*$", text):
        violations.append({"rule": "CONCURRENCY_ADDED_OR_CHANGED", "path": path})

    observed_jobs = _jobs(text)
    if observed_jobs != [row["job"]]:
        violations.append({
            "rule": "JOB_ID_RUNNER_OR_NEEDS_CHANGED",
            "path": path,
            "expected": [row["job"]],
            "observed": observed_jobs,
        })

    if text.count("actions/setup-python@v5") != 1:
        violations.append({"rule": "PYTHON_SETUP_COUNT_INVALID", "path": path})
    if text.count("python-version-file: '.python-version'") != 1:
        violations.append({"rule": "PYTHON_RUNTIME_NOT_EXACT", "path": path})
    if re.search(r"(?m)^\s+python-version:\s*", text):
        violations.append({"rule": "FLOATING_PYTHON_RUNTIME_PRESENT", "path": path})

    uses_node = row["runtime_after"]["node"] != "not-used"
    if uses_node:
        if text.count("actions/setup-node@v4") != 1:
            violations.append({"rule": "NODE_SETUP_COUNT_INVALID", "path": path})
        if text.count("node-version-file: '.node-version'") != 1:
            violations.append({"rule": "NODE_RUNTIME_NOT_EXACT", "path": path})
        if "--require-node" not in row["verify_command"]:
            violations.append({"rule": "EVIDENCE_NODE_VERIFY_INVALID", "path": path})
    else:
        if "actions/setup-node@" in text or "node-version-file:" in text:
            violations.append({"rule": "NODE_SETUP_ADDED_TO_PYTHON_ONLY_JOB", "path": path})
        if "--require-node" in row["verify_command"]:
            violations.append({"rule": "EVIDENCE_NODE_VERIFY_INVALID", "path": path})

    if text.count(row["verify_command"]) != 1:
        violations.append({
            "rule": "REPRO_VERIFY_MISSING_OR_DUPLICATED",
            "path": path,
            "command": row["verify_command"],
        })
    if text.count(STATIC_GUARD) != 1:
        violations.append({"rule": "STATIC_GUARD_MISSING_OR_DUPLICATED", "path": path})

    for bad, rule in (
        ("continue-on-error:", "CONTINUE_ON_ERROR_ADDED"),
        ("|| true", "OR_TRUE_BYPASS_ADDED"),
        ("if: false", "IF_FALSE_BYPASS_ADDED"),
        ("pip install", "UNAUTHORIZED_PIP_INSTALL_ADDED"),
        ("npm install", "UNAUTHORIZED_NPM_INSTALL_ADDED"),
        ("npm ci", "UNAUTHORIZED_NPM_INSTALL_ADDED"),
    ):
        if bad in text:
            violations.append({"rule": rule, "path": path})

    tokens = row["command_tokens"]
    if _tokens_sha(tokens) != row["command_fingerprint_sha256"]:
        violations.append({"rule": "COMMAND_EVIDENCE_FINGERPRINT_INVALID", "path": path})
    for token in tokens:
        if token not in text:
            violations.append({
                "rule": "HISTORICAL_COMMAND_OR_GATE_REMOVED",
                "path": path,
                "token": token,
            })

    if "scientific_token_counts_after" in row:
        for token, expected in row["scientific_token_counts_after"].items():
            observed = text.count(token)
            if observed != expected:
                violations.append({
                    "rule": "SCIENTIFIC_TOKEN_COUNT_CHANGED",
                    "path": path,
                    "token": token,
                    "expected": expected,
                    "observed": observed,
                })
        if row["scientific_token_counts_before"] != row["scientific_token_counts_after"]:
            violations.append({"rule": "SCIENTIFIC_EVIDENCE_BEFORE_AFTER_CHANGED", "path": path})

    if "actions/upload-artifact@" in text or "actions/download-artifact@" in text:
        violations.append({"rule": "ARTIFACT_IDENTITY_SURFACE_ADDED", "path": path})

    return violations


def audit_all() -> dict:
    evidence = _load()
    violations: list[dict] = []

    if evidence.get("schema") != "poker-repro-current-core-batch/v1":
        violations.append({"rule": "EVIDENCE_SCHEMA_INVALID"})
    if evidence.get("issue") != 378 or evidence.get("parent_issue") != 204:
        violations.append({"rule": "EVIDENCE_ISSUE_BINDING_INVALID"})
    if evidence.get("workflow_count") != 4:
        violations.append({"rule": "WORKFLOW_COUNT_INVALID"})

    helper = ROOT / evidence["repro_contract"]["environment_helper"]
    if _git_blob_sha(helper.read_bytes()) != evidence["repro_contract"]["helper_git_blob_sha"]:
        violations.append({"rule": "MERGED_REPRO_HELPER_MODIFIED"})

    expected_files = {
        ".github/workflows/game-core.yml",
        ".github/workflows/preflop-contract.yml",
        ".github/workflows/preflop-topology-contract.yml",
        ".github/workflows/model-a-continuation.yml",
    }
    rows = evidence.get("workflows") or []
    if {row["path"] for row in rows} != expected_files:
        violations.append({"rule": "WORKFLOW_ALLOWLIST_CHANGED"})

    for row in rows:
        path = ROOT / row["path"]
        violations.extend(_audit_text(row, path.read_text(encoding="utf-8")))

    invariants = evidence.get("invariants") or {}
    required_false = (
        "historical_trigger_semantics_changed",
        "permissions_changed",
        "concurrency_changed",
        "job_ids_or_needs_changed",
        "scientific_commands_changed",
        "scientific_gate_changed",
        "artifact_identity_changed",
        "scientific_test_consumed",
    )
    for key in required_false:
        if invariants.get(key) is not False:
            violations.append({"rule": "INVARIANT_NOT_FALSE", "key": key})
    if invariants.get("production_effect") != "NONE":
        violations.append({"rule": "PRODUCTION_EFFECT_NOT_NONE"})

    scope = evidence.get("scope") or {}
    if scope.get("n8n_issue_384_touched") is not False:
        violations.append({"rule": "N8N_384_SCOPE_TOUCHED"})

    return {"status": "FAIL" if violations else "PASS", "violations": violations}


class CurrentCoreReproTests(unittest.TestCase):
    def test_current_batch_passes(self) -> None:
        report = audit_all()
        self.assertEqual("PASS", report["status"], report)

    def _mutate(self, workflow: str, old: str, new: str) -> set[str]:
        evidence = _load()
        row = next(x for x in evidence["workflows"] if x["path"].endswith(workflow))
        text = (ROOT / row["path"]).read_text(encoding="utf-8")
        self.assertIn(old, text)
        mutated = text.replace(old, new, 1)
        return {x["rule"] for x in _audit_text(row, mutated, check_blob=False)}

    def test_runtime_float_fails_closed(self) -> None:
        rules = self._mutate(
            "game-core.yml",
            "python-version-file: '.python-version'",
            "python-version: '3.11'",
        )
        self.assertIn("PYTHON_RUNTIME_NOT_EXACT", rules)
        self.assertIn("FLOATING_PYTHON_RUNTIME_PRESENT", rules)

    def test_node_runtime_float_fails_closed(self) -> None:
        rules = self._mutate(
            "preflop-contract.yml",
            "node-version-file: '.node-version'",
            "node-version: '22'",
        )
        self.assertIn("NODE_RUNTIME_NOT_EXACT", rules)

    def test_helper_removal_fails_closed(self) -> None:
        rules = self._mutate(
            "preflop-topology-contract.yml",
            "run: python3 tools/repro_ci_environment.py verify",
            "run: echo bypass-repro-verify",
        )
        self.assertIn("REPRO_VERIFY_MISSING_OR_DUPLICATED", rules)

    def test_historical_test_removal_fails_closed(self) -> None:
        rules = self._mutate(
            "model-a-continuation.yml",
            "PYTHONPATH=. python3 tests/simulation/test_model_a_support_closure.py",
            "echo skipped-support-closure",
        )
        self.assertIn("HISTORICAL_COMMAND_OR_GATE_REMOVED", rules)

    def test_scientific_assertion_removal_fails_closed(self) -> None:
        rules = self._mutate(
            "preflop-topology-contract.yml",
            "assert r['test_authorized'] is False",
            "assert True",
        )
        self.assertIn("HISTORICAL_COMMAND_OR_GATE_REMOVED", rules)
        self.assertIn("SCIENTIFIC_TOKEN_COUNT_CHANGED", rules)

    def test_trigger_removal_fails_closed(self) -> None:
        rules = self._mutate(
            "game-core.yml",
            "      - 'docs/full_hand_game_core.md'\n",
            "",
        )
        self.assertIn("TRIGGER_PATHS_CHANGED", rules)

    def test_permission_change_fails_closed(self) -> None:
        rules = self._mutate(
            "preflop-topology-contract.yml",
            "permissions:\n  contents: read",
            "permissions:\n  contents: write",
        )
        self.assertIn("PERMISSIONS_CHANGED", rules)

    def test_concurrency_addition_fails_closed(self) -> None:
        rules = self._mutate(
            "game-core.yml",
            "jobs:\n",
            "concurrency:\n  group: changed\n  cancel-in-progress: true\n\njobs:\n",
        )
        self.assertIn("CONCURRENCY_ADDED_OR_CHANGED", rules)

    def test_job_rename_fails_closed(self) -> None:
        rules = self._mutate(
            "preflop-contract.yml",
            "  contract:\n",
            "  renamed-contract:\n",
        )
        self.assertIn("JOB_ID_RUNNER_OR_NEEDS_CHANGED", rules)


if __name__ == "__main__":
    unittest.main()

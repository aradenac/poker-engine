#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/population-pack-catalog.yml"
EVIDENCE = ROOT / "analysis/workflow_audit/repro_population_pack_catalog_before_after.json"
HELPER_CONSUMERS = ROOT / "analysis/workflow_audit/helper_consumers.json"

ENV_VERIFY = "python3 tools/repro_ci_environment.py verify --require-node"
ENV_BOOTSTRAP = "python3 tools/repro_ci_environment.py bootstrap --python-deps"
BROWSER_INSTALL = "uses: ./.github/actions/repro-browser"

DIRECT_PIP_PLAYWRIGHT_RX = re.compile(
    r"(?:\bpip(?:3)?\s+install\b|python3?\s+-m\s+pip\s+install)[^\n]*playwright"
)
DIRECT_BROWSER_INSTALL_RX = re.compile(r"python3?\s+-m\s+playwright\s+install")


def _json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def _job_block(text: str, job_id: str) -> str:
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line == f"  {job_id}:"), None)
    if start is None:
        return ""
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if re.match(r"^  [A-Za-z_][\w-]*:\s*$", lines[i]):
            end = i
            break
    return "\n".join(lines[start:end])


def _parse_workflow(text: str) -> dict:
    # Reuse the repository's standard-library workflow parser without introducing
    # a YAML dependency.
    from tools.audit_github_workflows import parse_workflow

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "population-pack-catalog.yml"
        path.write_text(text, encoding="utf-8")
        parsed = parse_workflow(path, Path(td))
    return parsed


def _normalized_jobs(parsed: dict) -> list[dict]:
    return [
        {
            "id": job["id"],
            "runner": job.get("runner"),
            "needs": list(job.get("needs") or []),
        }
        for job in parsed.get("jobs") or []
    ]


def _product_hash(tokens: list[str]) -> str:
    payload = json.dumps(tokens, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def audit_text(text: str, *, check_blob: bool = True) -> dict:
    evidence = _json(EVIDENCE)
    violations: list[dict] = []
    parsed = _parse_workflow(text)

    if evidence.get("schema") != "poker-repro-population-pack-catalog-migration/v1":
        violations.append({"rule": "EVIDENCE_SCHEMA_INVALID"})
    if evidence.get("issue") != 371 or evidence.get("parent_issue") != 204:
        violations.append({"rule": "EVIDENCE_ISSUE_BINDING_INVALID"})

    if check_blob:
        observed_blob = _git_blob_sha(text.encode())
        if observed_blob != evidence.get("after_git_blob_sha"):
            violations.append({
                "rule": "WORKFLOW_BLOB_CHANGED_WITHOUT_EVIDENCE_REFRESH",
                "expected": evidence.get("after_git_blob_sha"),
                "observed": observed_blob,
            })

    helper_consumers = _json(HELPER_CONSUMERS)
    helper_rows = {
        row["helper"]: row
        for row in helper_consumers.get("helpers") or []
        if isinstance(row, dict) and row.get("helper")
    }
    for helper in ("tools/repro_ci_environment.py", "tools/repro_ci_browser.py"):
        row = helper_rows.get(helper)
        if row is None:
            violations.append({"rule": "ISSUE_291_HELPER_EVIDENCE_MISSING", "helper": helper})
            continue
        candidates = {
            c.get("workflow"): c.get("workflow_blob_sha")
            for c in row.get("consumers") or []
        }
        if candidates.get(".github/workflows/population-pack-catalog.yml") != evidence.get("before_git_blob_sha"):
            violations.append({
                "rule": "BEFORE_BLOB_NOT_BOUND_TO_ISSUE_291",
                "helper": helper,
            })

    expected_jobs = evidence["after"]["jobs"]
    observed_jobs = _normalized_jobs(parsed)
    if observed_jobs != expected_jobs:
        violations.append({
            "rule": "JOB_IDENTITY_OR_NEEDS_CHANGED",
            "expected": expected_jobs,
            "observed": observed_jobs,
        })

    expected_triggers = evidence["after"]["triggers"]
    observed_triggers = parsed.get("triggers") or {}
    if observed_triggers != expected_triggers:
        violations.append({
            "rule": "TRIGGERS_OR_PATHS_CHANGED",
            "expected": expected_triggers,
            "observed": observed_triggers,
        })

    if parsed.get("concurrency") != evidence["after"]["concurrency"]:
        violations.append({"rule": "CONCURRENCY_CHANGED"})

    if "permissions:\n  contents: read\n" not in text:
        violations.append({"rule": "PERMISSIONS_CHANGED"})

    contract = _job_block(text, "contract")
    browser = _job_block(text, "browser-smoke")
    if not contract:
        violations.append({"rule": "CONTRACT_JOB_MISSING"})
    if not browser:
        violations.append({"rule": "BROWSER_SMOKE_JOB_MISSING"})

    if text.count("actions/setup-python@v5") != 2:
        violations.append({"rule": "PYTHON_SETUP_COUNT_CHANGED"})
    if text.count("python-version-file: '.python-version'") != 2:
        violations.append({"rule": "PYTHON_NOT_LOCKED_BY_VERSION_FILE"})
    if re.search(r"(?m)^\s+python-version:\s*", text):
        violations.append({"rule": "INLINE_OR_FLOATING_PYTHON_VERSION_PRESENT"})

    if contract.count("actions/setup-node@v4") != 1:
        violations.append({"rule": "CONTRACT_NODE_SETUP_MISSING"})
    if contract.count("node-version-file: '.node-version'") != 1:
        violations.append({"rule": "CONTRACT_NODE_NOT_LOCKED_BY_VERSION_FILE"})
    if browser.count("actions/setup-node@") != 0:
        violations.append({"rule": "UNNEEDED_BROWSER_NODE_SETUP_ADDED"})

    if contract.count(ENV_VERIFY) != 1:
        violations.append({"rule": "CONTRACT_ENV_VERIFY_MISSING"})
    if browser.count(ENV_BOOTSTRAP) != 1:
        violations.append({"rule": "BROWSER_ENV_BOOTSTRAP_MISSING"})
    if browser.count(BROWSER_INSTALL) != 1:
        violations.append({"rule": "BROWSER_HELPER_MISSING"})

    if DIRECT_PIP_PLAYWRIGHT_RX.search(text):
        violations.append({"rule": "DIRECT_PIP_PLAYWRIGHT_BYPASS"})
    if DIRECT_BROWSER_INSTALL_RX.search(text):
        violations.append({"rule": "DIRECT_PLAYWRIGHT_BROWSER_BYPASS"})

    if "continue-on-error:" in text:
        violations.append({"rule": "CONTINUE_ON_ERROR_ADDED"})
    if re.search(r"(?m)^\s*if:\s*false\s*$", text):
        violations.append({"rule": "IF_FALSE_BYPASS_ADDED"})
    true_lines = [line.strip() for line in text.splitlines() if "|| true" in line]
    if true_lines != ["run: cat /tmp/population-pack-http.log || true"]:
        violations.append({
            "rule": "UNEXPECTED_OR_MISSING_OR_TRUE",
            "observed": true_lines,
        })

    tokens = evidence["product_commands"]["ordered_tokens"]
    if _product_hash(tokens) != evidence["product_commands"]["canonical_sha256"]:
        violations.append({"rule": "PRODUCT_COMMAND_EVIDENCE_HASH_INVALID"})
    for token in tokens:
        if token not in text:
            violations.append({"rule": "PRODUCT_GATE_REMOVED_OR_CHANGED", "token": token})

    exact_counts = {
        "python3 tools/patches/apply_pack_manager_link.py": 4,
        "python3 tools/write_pack_catalog.py": 3,
        "python3 tools/write_site_release.py": 2,
        "python3 tests/packs/test_pack_catalog_runtime.py": 1,
        "python3 tests/packs/smoke_population_packs.py": 1,
        "node --check site/population-packs.js": 1,
        "node --check site/population-pack-sw.js": 1,
        "node --check site/packs-app.js": 1,
        "assert doc['publication_verification']['tracked_by_issue']==45": 1,
    }
    for token, count in exact_counts.items():
        observed = text.count(token)
        if observed != count:
            violations.append({
                "rule": "PRODUCT_COMMAND_COUNT_CHANGED",
                "token": token,
                "expected": count,
                "observed": observed,
            })

    forbidden_science_tokens = (
        "model_a", "model-b", "model_b", "hero_strategy", "Hero EV",
        "training/test-ledger", "VALIDATION", "scientific TEST",
    )
    for token in forbidden_science_tokens:
        if token in text:
            violations.append({"rule": "FORBIDDEN_SCIENCE_SCOPE_ADDED", "token": token})

    expected_helpers = {
        row["path"]: row["git_blob_sha"]
        for row in evidence.get("helper_hashes") or []
    }
    for rel, expected in expected_helpers.items():
        path = ROOT / rel
        observed = _git_blob_sha(path.read_bytes())
        if observed != expected:
            violations.append({
                "rule": "MERGED_HELPER_MODIFIED",
                "path": rel,
                "expected": expected,
                "observed": observed,
            })

    for row in evidence.get("consumed_source_hashes") or []:
        rel = row["path"]
        if row.get("algorithm") != "git_blob_sha1":
            violations.append({"rule": "SOURCE_HASH_ALGORITHM_UNEXPECTED", "path": rel})
            continue
        observed = _git_blob_sha((ROOT / rel).read_bytes())
        if observed != row["value"]:
            violations.append({
                "rule": "CONSUMED_REPRO_SOURCE_CHANGED_WITHOUT_EVIDENCE_REFRESH",
                "path": rel,
                "expected": row["value"],
                "observed": observed,
            })

    # The only files this issue is allowed to change are persisted in evidence.
    if evidence.get("modified_files") != [
        ".github/workflows/population-pack-catalog.yml",
        "tests/ci/test_repro_population_pack_catalog.py",
        "analysis/workflow_audit/repro_population_pack_catalog_before_after.json",
    ]:
        violations.append({"rule": "SCOPE_FILE_LIST_CHANGED"})

    return {
        "status": "FAIL" if violations else "PASS",
        "violations": violations,
    }


class PopulationPackCatalogueReproTests(unittest.TestCase):
    def test_current_contract_passes(self) -> None:
        report = audit_text(WORKFLOW.read_text(encoding="utf-8"))
        self.assertEqual("PASS", report["status"], report)

    def test_env_verify_cannot_be_removed(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8").replace(ENV_VERIFY, "echo bypass-env")
        rules = {x["rule"] for x in audit_text(text, check_blob=False)["violations"]}
        self.assertIn("CONTRACT_ENV_VERIFY_MISSING", rules)

    def test_python_runtime_cannot_float(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8").replace(
            "python-version-file: '.python-version'",
            "python-version: '3.11'",
            1,
        )
        rules = {x["rule"] for x in audit_text(text, check_blob=False)["violations"]}
        self.assertIn("PYTHON_NOT_LOCKED_BY_VERSION_FILE", rules)
        self.assertIn("INLINE_OR_FLOATING_PYTHON_VERSION_PRESENT", rules)

    def test_node_runtime_cannot_float(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8").replace(
            "node-version-file: '.node-version'",
            "node-version: '22'",
            1,
        )
        rules = {x["rule"] for x in audit_text(text, check_blob=False)["violations"]}
        self.assertIn("CONTRACT_NODE_NOT_LOCKED_BY_VERSION_FILE", rules)

    def test_release_assertion_cannot_be_removed(self) -> None:
        token = "assert doc['publication_verification']['tracked_by_issue']==45"
        text = WORKFLOW.read_text(encoding="utf-8").replace(token, "assert True")
        rules = {x["rule"] for x in audit_text(text, check_blob=False)["violations"]}
        self.assertIn("PRODUCT_GATE_REMOVED_OR_CHANGED", rules)

    def test_browser_smoke_cannot_be_removed(self) -> None:
        token = "python3 tests/packs/smoke_population_packs.py"
        text = WORKFLOW.read_text(encoding="utf-8").replace(token, "echo skipped-smoke")
        rules = {x["rule"] for x in audit_text(text, check_blob=False)["violations"]}
        self.assertIn("PRODUCT_GATE_REMOVED_OR_CHANGED", rules)

    def test_browser_helper_cannot_be_bypassed(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8").replace(
            "      - uses: ./.github/actions/repro-browser\n        with:\n          require-node: 'true'",
            "run: python3 -m playwright install --with-deps chromium",
        )
        rules = {x["rule"] for x in audit_text(text, check_blob=False)["violations"]}
        self.assertIn("BROWSER_HELPER_MISSING", rules)
        self.assertIn("DIRECT_PLAYWRIGHT_BROWSER_BYPASS", rules)

    def test_needs_cannot_be_removed(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8").replace(
            "  browser-smoke:\n    needs: contract\n",
            "  browser-smoke:\n",
            1,
        )
        rules = {x["rule"] for x in audit_text(text, check_blob=False)["violations"]}
        self.assertIn("JOB_IDENTITY_OR_NEEDS_CHANGED", rules)

    def test_concurrency_cannot_change(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8").replace(
            "group: population-pack-catalog-${{ github.ref }}",
            "group: changed-${{ github.ref }}",
            1,
        )
        rules = {x["rule"] for x in audit_text(text, check_blob=False)["violations"]}
        self.assertIn("CONCURRENCY_CHANGED", rules)

    def test_no_new_error_masking(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8").replace(
            "run: python3 tests/packs/smoke_population_packs.py",
            "continue-on-error: true\n        run: python3 tests/packs/smoke_population_packs.py",
            1,
        )
        rules = {x["rule"] for x in audit_text(text, check_blob=False)["violations"]}
        self.assertIn("CONTINUE_ON_ERROR_ADDED", rules)


if __name__ == "__main__":
    unittest.main()

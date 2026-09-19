#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import tempfile

ROOT = Path(__file__).resolve().parents[1]

from tools import repro_ci_enforcement
from tools import repro_ci_environment
from tools import repro_environment_identity


def _copy_enforcement_tree(dst: Path) -> None:
    policy = repro_ci_enforcement.load_policy(ROOT)
    paths = [
        "reproducibility/scientific-workflow-enforcement.json",
        policy["reusable_workflow"],
        *[row["path"] for row in policy["protected_workflows"]],
    ]
    for rel in paths:
        source = ROOT / rel
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _copy_repro_contract(dst: Path) -> None:
    shutil.copytree(ROOT / "reproducibility", dst / "reproducibility")
    for rel in (
        ".python-version",
        ".node-version",
        "requirements.in",
        "requirements.lock.txt",
        "package.json",
        "package-lock.json",
    ):
        shutil.copy2(ROOT / rel, dst / rel)


def test_guarded_workflow_topology_passes() -> None:
    report = repro_ci_enforcement.audit(ROOT)
    assert report["status"] == "PASS", report
    assert report["violations"] == []
    assert len(report["checked_workflows"]) == 6


def test_runtime_version_mismatch_fails_closed() -> None:
    spec = repro_ci_environment.contract(ROOT)
    report = repro_ci_environment.verify(
        ROOT,
        observed_python="0.0.0",
        observed_node=spec["expected"]["node"],
        require_node=True,
    )
    assert report["status"] == "FAIL"
    assert {row["rule"] for row in report["violations"]} == {"PYTHON_VERSION_MISMATCH"}


def test_critical_lock_divergence_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _copy_repro_contract(root)
        (root / ".python-version").write_text("3.11.8\n", encoding="utf-8")
        try:
            repro_ci_environment.contract(root)
        except repro_ci_environment.HelperError as exc:
            assert ".python-version diverges" in str(exc)
        else:
            raise AssertionError("critical runtime lock divergence must fail closed")


def test_environment_identity_divergence_fails_closed() -> None:
    identity = repro_environment_identity.materialize_identity(ROOT)
    bad = copy.deepcopy(identity)
    bad["expected"]["python"]["version"] = "0.0.0"
    errors = repro_environment_identity.validate_identity(bad, ROOT)
    assert errors
    assert any("identity_sha256 mismatch" in error or "diverges" in error for error in errors)


def test_workflow_guard_dependency_cannot_be_silently_removed() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _copy_enforcement_tree(root)
        target = root / ".github/workflows/population-pack.yml"
        text = target.read_text(encoding="utf-8")
        text = text.replace(
            "    needs: repro-environment\n",
            "",
            1,
        )
        target.write_text(text, encoding="utf-8")
        report = repro_ci_enforcement.audit(root)
        assert report["status"] == "FAIL"
        assert any(
            row["rule"] == "GUARD_DEPENDENCY_MISSING"
            and row.get("path") == ".github/workflows/population-pack.yml"
            for row in report["violations"]
        ), report


def test_new_unguarded_publication_job_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _copy_enforcement_tree(root)
        target = root / ".github/workflows/population-pack.yml"
        text = target.read_text(encoding="utf-8")
        text += """
  bypass-publication:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/upload-artifact@v4
        with:
          name: bypass
          path: README.md
"""
        target.write_text(text, encoding="utf-8")
        report = repro_ci_enforcement.audit(root)
        assert report["status"] == "FAIL"
        assert any(
            row["rule"] == "UNGUARDED_ARTIFACT_OR_MUTATION_JOB"
            and row.get("job") == "bypass-publication"
            for row in report["violations"]
        ), report


def test_history_and_test_ledger_scope_is_fail_closed() -> None:
    ok = repro_ci_enforcement.audit_changed_paths(
        [
            ".github/workflows/population-pack.yml",
            "tools/repro_ci_enforcement.py",
            "analysis/reproducibility/ci-enforcement-evidence.json",
        ],
        ROOT,
    )
    assert ok["status"] == "PASS", ok

    bad = repro_ci_enforcement.audit_changed_paths(
        [
            "training/runs/20260912_population_increment_cycle/FINAL_STATE.json",
            "training/test-ledger.json",
        ],
        ROOT,
    )
    assert bad["status"] == "FAIL"
    assert len(bad["violations"]) == 2


def test_declared_limitations_are_preserved() -> None:
    policy = repro_ci_enforcement.load_policy(ROOT)
    limits = policy["explicit_limitations"]
    assert limits["system_packages_fully_pinned"] is False
    assert limits["browser_archive_sha_pinned"] is False

    env = json.loads(
        (ROOT / "reproducibility/environment.lock.json").read_text(encoding="utf-8")
    )
    # #347 wires CI without rewriting the historical phase-1 lock semantics.
    assert env["scope"]["os_packages_pinned"] is False


if __name__ == "__main__":
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
    print(f"REPRO CI enforcement tests: {len(tests)} passed")

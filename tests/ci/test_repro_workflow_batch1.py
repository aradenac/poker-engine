#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile

ROOT = Path(__file__).resolve().parents[2]

from tools.audit_repro_workflow_batch1 import EVIDENCE, audit

TARGETS = (
    ".github/workflows/trainer-smoke.yml",
    ".github/workflows/hero-range-editor.yml",
    ".github/workflows/hero-range-compliance.yml",
)


def _copy_batch(dst: Path) -> None:
    for rel in (*TARGETS, EVIDENCE.as_posix()):
        source = ROOT / rel
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _rules(report: dict) -> set[str]:
    return {row["rule"] for row in report["violations"]}


def test_current_batch_contract_passes() -> None:
    report = audit(ROOT, check_global_repro=True)
    assert report["status"] == "PASS", report
    assert report["violations"] == []
    assert report["issue_347_guard"]["status"] == "PASS"
    assert report["scientific_test_consumed"] is False
    assert report["production_effect"] == "NONE"
    assert report["reserved_n8n_scope_touched"] is False


def test_browser_helper_cannot_be_removed() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _copy_batch(root)
        target = root / TARGETS[0]
        text = target.read_text(encoding="utf-8")
        text = text.replace(
            "python3 tools/repro_ci_browser.py install > /tmp/repro-ci-browser.json",
            "echo bypass-browser-helper",
        )
        target.write_text(text, encoding="utf-8")
        report = audit(root, check_global_repro=False)
        assert report["status"] == "FAIL"
        assert "REPRO_BROWSER_HELPER_MISSING" in _rules(report)


def test_direct_unlocked_playwright_setup_is_rejected() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _copy_batch(root)
        target = root / TARGETS[1]
        text = target.read_text(encoding="utf-8")
        marker = "          python3 tools/repro_ci_browser.py install > /tmp/repro-ci-browser.json"
        text = text.replace(
            marker,
            marker + "\n          python3 -m pip install --user playwright\n          python3 -m playwright install --with-deps chromium",
        )
        target.write_text(text, encoding="utf-8")
        report = audit(root, check_global_repro=False)
        rules = _rules(report)
        assert "DIRECT_PIP_BROWSER_SETUP_BYPASS" in rules
        assert "DIRECT_PLAYWRIGHT_SETUP_BYPASS" in rules


def test_business_gate_cannot_be_removed() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _copy_batch(root)
        target = root / TARGETS[2]
        text = target.read_text(encoding="utf-8")
        text = text.replace(
            "node tests/hero_ranges/test_hero_compliance.mjs",
            "echo skipped-compliance-semantics",
        )
        target.write_text(text, encoding="utf-8")
        report = audit(root, check_global_repro=False)
        assert "BUSINESS_GATE_REMOVED_OR_CHANGED" in _rules(report)


def test_job_identity_and_needs_cannot_change() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _copy_batch(root)
        target = root / TARGETS[1]
        text = target.read_text(encoding="utf-8")
        text = text.replace("  browser-smoke:\n", "  browser-check-renamed:\n", 1)
        target.write_text(text, encoding="utf-8")
        report = audit(root, check_global_repro=False)
        rules = _rules(report)
        assert "JOB_IDENTITY_OR_DEPENDENCY_CHANGED" in rules
        assert "BROWSER_SMOKE_JOB_MISSING" in rules


def test_trigger_semantics_cannot_change() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _copy_batch(root)
        target = root / TARGETS[0]
        text = target.read_text(encoding="utf-8")
        text = text.replace("      - 'site/trainer.css'\n", "", 1)
        target.write_text(text, encoding="utf-8")
        report = audit(root, check_global_repro=False)
        assert "TRIGGER_SEMANTICS_CHANGED" in _rules(report)


def test_artifact_identity_cannot_be_added_or_changed_silently() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _copy_batch(root)
        target = root / TARGETS[0]
        text = target.read_text(encoding="utf-8")
        text += """
      - uses: actions/upload-artifact@v4
        with:
          name: accidental-new-artifact
          path: /tmp/repro-ci-browser.json
"""
        target.write_text(text, encoding="utf-8")
        report = audit(root, check_global_repro=False)
        assert "ARTIFACT_IDENTITY_CHANGED" in _rules(report)


def test_repro_guard_cannot_continue_on_error() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _copy_batch(root)
        target = root / TARGETS[2]
        text = target.read_text(encoding="utf-8")
        text = text.replace(
            "      - name: Install locked browser runtime\n",
            "      - name: Install locked browser runtime\n        continue-on-error: true\n",
            1,
        )
        target.write_text(text, encoding="utf-8")
        report = audit(root, check_global_repro=False)
        assert "BROWSER_REPRO_GUARD_MAY_CONTINUE_ON_ERROR" in _rules(report)


def test_n8n_reserved_workflow_is_outside_batch() -> None:
    evidence = json.loads((ROOT / EVIDENCE).read_text(encoding="utf-8"))
    paths = {row["path"] for row in evidence["workflows"]}
    assert ".github/workflows/project-state-consistency.yml" not in paths
    assert ".github/workflows/project-state-consistency.yml" in evidence["excluded_reserved_scope"]
    assert "#346" in evidence["excluded_reserved_scope"]
    assert "#206" in evidence["excluded_reserved_scope"]


if __name__ == "__main__":
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
    print(f"REPRO workflow batch-1 tests: {len(tests)} passed")

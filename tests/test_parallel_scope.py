#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.check_parallel_scope import SLOTS, check_scope, files_from_git_range, load_contract, stable_json

CONTRACT = load_contract(ROOT / ".project" / "parallel-agents.json")


def _rules(report: dict) -> set[str]:
    return {row["rule"] for row in report["violations"]}


def _owners(report: dict) -> set[str | None]:
    return {row.get("expected_owner") for row in report["violations"]}


def test_contract_contains_all_slots_and_required_fields() -> None:
    assert set(CONTRACT["lanes"]) == set(SLOTS)
    for slot in SLOTS:
        lane = CONTRACT["lanes"][slot]
        assert lane["conflict_group"]
        assert lane["description"]
        assert lane["status"]
        assert isinstance(lane["reserved_paths"], list)
        assert isinstance(lane["forbidden_paths"], list)
        assert isinstance(lane["typical_issues"], list)


def test_pass_c_analytics() -> None:
    assert check_scope(CONTRACT, "C", ["src/analytics/review-inbox.js"])["status"] == "PASS"


def test_pass_d_hero_editor() -> None:
    assert check_scope(CONTRACT, "D", ["site/hero-ranges-app.js"])["status"] == "PASS"


def test_pass_e_packs() -> None:
    assert check_scope(CONTRACT, "E", ["site/packs-app.js"])["status"] == "PASS"


def test_fail_c_central_index() -> None:
    report = check_scope(CONTRACT, "C", ["site/index.html"])
    assert report["status"] == "FAIL"
    assert "H" in _owners(report)
    assert "CENTRAL_UI_EXCLUSIVE" in _rules(report)


def test_fail_d_central_trainer() -> None:
    report = check_scope(CONTRACT, "D", ["site/trainer.js"])
    assert report["status"] == "FAIL"
    assert "H" in _owners(report)


def test_fail_e_hero_editor() -> None:
    report = check_scope(CONTRACT, "E", ["site/hero-ranges-app.js"])
    assert report["status"] == "FAIL"
    assert "D" in _owners(report)


def test_fail_h_frozen_108_artifact() -> None:
    report = check_scope(CONTRACT, "H", ["training/PREFLOP_STRATEGY_BENCHMARK_CONTRACT_20260915.json"])
    assert report["status"] == "FAIL"
    assert "A" in _owners(report)
    assert "SCIENCE_108_FROZEN" in _rules(report)


def test_fail_b_frozen_108_workflow() -> None:
    report = check_scope(CONTRACT, "B", [".github/workflows/preflop-strategy-benchmark.yml"])
    assert report["status"] == "FAIL"
    assert "A" in _owners(report)
    assert "SCIENCE_108_WORKFLOW" in _rules(report)


def test_mixed_analytics_and_packs_is_reported() -> None:
    report = check_scope(CONTRACT, "C", ["src/analytics/review-inbox.js", "site/packs-app.js"])
    assert report["status"] == "FAIL"
    assert "MIXED_CONFLICT_GROUPS" in _rules(report)


def test_unknown_path_warns_instead_of_silent_pass() -> None:
    report = check_scope(CONTRACT, "C", ["misc/new-crosscutting-file.txt"])
    assert report["status"] == "WARN"
    assert report["warnings"][0]["rule"] == "UNCLASSIFIED_PATH"


def test_json_report_is_stable() -> None:
    files = ["site/index.html", "src/analytics/review-inbox.js"]
    first = stable_json(check_scope(CONTRACT, "C", files))
    second = stable_json(check_scope(CONTRACT, "C", list(reversed(files))))
    assert first == second
    assert json.loads(first)["status"] == "FAIL"


def test_git_range_mode_lists_changed_files() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "Parallel Scope Test"], cwd=root, check=True)
        (root / "src/analytics").mkdir(parents=True)
        target = root / "src/analytics/example.js"
        target.write_text("one\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
        base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
        target.write_text("two\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "head"], cwd=root, check=True)
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
        assert files_from_git_range(root, base, head) == ["src/analytics/example.js"]


def test_current_issue_264_files_are_project_state_only() -> None:
    report = check_scope(CONTRACT, "G", [
        ".project/parallel-agents.json",
        ".project/PARALLEL_AGENTS.md",
        "tools/check_parallel_scope.py",
        "tests/test_parallel_scope.py",
    ])
    assert report["status"] == "PASS", report


def main() -> None:
    cases = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for case in cases:
        case()
    print(f"parallel scope tests: {len(cases)} passed")


if __name__ == "__main__":
    main()

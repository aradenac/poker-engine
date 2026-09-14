#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training import atomic_promotion  # noqa: E402
from tools.training.run_continuous_cycle import execute  # noqa: E402


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def gate(cycle: str, *, status: str = "PASS", ready: bool = True) -> dict:
    return {
        "schema": "poker-promotion-gate-report/v1",
        "cycle": cycle,
        "status": status,
        "promotion_ready": ready,
    }


def fixture(tmp: Path, *, gate_status: str = "PASS", ready: bool = True) -> tuple[Path, list[str]]:
    protected = [
        "training/registry.json",
        "training/models",
        "training/runs/promoted-model-b/model",
        "user/releases",
        "site",
    ]
    write(tmp / "training/registry.json", '{"active":"baseline"}\n')
    write(tmp / "training/models/pre.json", '{"model":"pre"}\n')
    write(tmp / "training/models/post.json", '{"model":"post"}\n')
    write(tmp / "training/runs/promoted-model-b/model/model.json", '{"model":"b"}\n')
    write(tmp / "user/releases/v83.html", "<html>v83</html>\n")
    write(tmp / "site/index.html", "<html>site</html>\n")
    write(tmp / "site/assets/model.json", '{"asset":"baseline"}\n')
    write(tmp / "gate.json", json.dumps(gate("synthetic", status=gate_status, ready=ready)) + "\n")
    return tmp / "gate.json", protected


def config(
    tmp: Path,
    protected: list[str],
    stages: list[dict],
    *,
    promotion_mode: str = "disabled",
    promotion_plan: str | None = None,
) -> Path:
    path = tmp / "cycle.json"
    data = {
        "schema": "poker-continuous-cycle/v1",
        "cycle": "synthetic",
        "promotion_mode": promotion_mode,
        "gate_report": "gate.json",
        "protected_production_paths": protected,
        "stages": stages,
    }
    if promotion_plan is not None:
        data["promotion_plan"] = promotion_plan
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def promotion_plan(tmp: Path, *, registry_first: bool = False, bad_source_sha: bool = False) -> Path:
    source_model = tmp / "candidate/model.json"
    source_registry = tmp / "candidate/registry.json"
    write(source_model, '{"model":"promoted"}\n')
    write(source_registry, '{"active":"promoted"}\n')
    model_op = {
        "id": "promote-model",
        "source": "candidate/model.json",
        "destination": "training/models/pre.json",
        "source_sha256": "0" * 64 if bad_source_sha else sha(source_model),
        "destination_sha256_before": sha(tmp / "training/models/pre.json"),
    }
    registry_op = {
        "id": "advance-registry",
        "source": "candidate/registry.json",
        "destination": "training/registry.json",
        "source_sha256": sha(source_registry),
        "destination_sha256_before": sha(tmp / "training/registry.json"),
    }
    plan = tmp / "promotion.json"
    plan.write_text(json.dumps({
        "schema": "poker-atomic-promotion/v1",
        "operations": [registry_op, model_op] if registry_first else [model_op, registry_op],
    }), encoding="utf-8")
    return plan


def test_candidate_outputs_are_allowed_but_production_is_unchanged() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        _, protected = fixture(tmp)
        cfg = config(tmp, protected, [{
            "id": "candidate",
            "argv": [sys.executable, "-c", "from pathlib import Path; Path('runs/candidate.json').parent.mkdir(parents=True,exist_ok=True); Path('runs/candidate.json').write_text('candidate')"],
            "required_outputs": ["runs/candidate.json"],
        }])
        code, report = execute(root=tmp, config_path=cfg, require_ready=True)
        assert code == 0, report
        assert report["status"] == "PASS", report
        assert report["promotion_applied"] is False
        assert report["production_before"] == report["production_after"]
        assert (tmp / "runs/candidate.json").read_text() == "candidate"


def test_production_mutation_is_rolled_back_and_fails() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        _, protected = fixture(tmp)
        original = (tmp / "site/index.html").read_bytes()
        cfg = config(tmp, protected, [{
            "id": "bad-site-write",
            "argv": [sys.executable, "-c", "from pathlib import Path; Path('site/index.html').write_text('MUTATED')"],
        }])
        code, report = execute(root=tmp, config_path=cfg, require_ready=True)
        assert code != 0, report
        assert report["status"] == "FAIL"
        assert "site" in report["production_changed_paths_detected"], report
        assert report["production_restored"] is True
        assert report["production_restoration_verified"] is True
        assert (tmp / "site/index.html").read_bytes() == original
        assert report["production_before"] == report["production_after"]


def test_deleted_production_file_is_restored_after_failed_stage() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        _, protected = fixture(tmp)
        original = (tmp / "training/registry.json").read_bytes()
        cfg = config(tmp, protected, [{
            "id": "delete-and-fail",
            "argv": [sys.executable, "-c", "from pathlib import Path; Path('training/registry.json').unlink(); raise SystemExit(7)"],
        }])
        code, report = execute(root=tmp, config_path=cfg, require_ready=True)
        assert code == 7, report
        assert report["status"] == "FAIL"
        assert report["production_restored"] is True
        assert report["production_restoration_verified"] is True
        assert (tmp / "training/registry.json").read_bytes() == original


def test_not_ready_gate_fails_without_promotion() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        _, protected = fixture(tmp, gate_status="BLOCKED", ready=False)
        cfg = config(tmp, protected, [])
        code, report = execute(root=tmp, config_path=cfg, require_ready=True)
        assert code != 0, report
        assert report["status"] == "FAIL"
        assert "not PASS/promotion_ready" in report["reason"]
        assert report["production_before"] == report["production_after"]


def test_conditional_stage_skips_when_json_gate_is_false() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        _, protected = fixture(tmp)
        write(tmp / "selection.json", json.dumps({"test_authorized": False}) + "\n")
        cfg = config(tmp, protected, [{
            "id": "protected-test",
            "when": {"json": "selection.json", "path": ["test_authorized"], "equals": True},
            "argv": [sys.executable, "-c", "from pathlib import Path; Path('SHOULD_NOT_EXIST').write_text('bad')"],
        }])
        code, report = execute(root=tmp, config_path=cfg, require_ready=True)
        assert code == 0, report
        assert report["stages"] == [{
            "id": "protected-test",
            "status": "SKIPPED",
            "when": {
                "json": "selection.json",
                "path": ["test_authorized"],
                "equals": True,
                "actual": False,
            },
        }], report["stages"]
        assert not (tmp / "SHOULD_NOT_EXIST").exists()


def test_explicit_promotion_replaces_model_then_registry() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        _, protected = fixture(tmp)
        plan = promotion_plan(tmp)
        cfg = config(tmp, protected, [], promotion_mode="explicit", promotion_plan=plan.name)
        code, report = execute(root=tmp, config_path=cfg)
        assert code == 0, report
        assert report["status"] == "PASS", report
        assert report["promotion_applied"] is True
        assert [x["id"] for x in report["promotion"]["operations"]] == ["promote-model", "advance-registry"]
        assert set(report["production_changed_paths_detected"]) == {"training/models", "training/registry.json"}
        assert (tmp / "training/models/pre.json").read_text() == '{"model":"promoted"}\n'
        assert (tmp / "training/registry.json").read_text() == '{"active":"promoted"}\n'
        assert report["production_before"] != report["production_after"]


def test_explicit_promotion_requires_ready_gate_even_without_cli_flag() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        _, protected = fixture(tmp, gate_status="BLOCKED", ready=False)
        plan = promotion_plan(tmp)
        old_model = (tmp / "training/models/pre.json").read_bytes()
        old_registry = (tmp / "training/registry.json").read_bytes()
        cfg = config(tmp, protected, [], promotion_mode="explicit", promotion_plan=plan.name)
        code, report = execute(root=tmp, config_path=cfg, require_ready=False)
        assert code != 0, report
        assert report["promotion_applied"] is False
        assert (tmp / "training/models/pre.json").read_bytes() == old_model
        assert (tmp / "training/registry.json").read_bytes() == old_registry


def test_explicit_promotion_rejects_bad_source_hash_without_mutation() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        _, protected = fixture(tmp)
        plan = promotion_plan(tmp, bad_source_sha=True)
        old_model = (tmp / "training/models/pre.json").read_bytes()
        cfg = config(tmp, protected, [], promotion_mode="explicit", promotion_plan=plan.name)
        code, report = execute(root=tmp, config_path=cfg)
        assert code != 0, report
        assert "source SHA-256 mismatch" in report["reason"]
        assert report["production_restored"] is False
        assert (tmp / "training/models/pre.json").read_bytes() == old_model


def test_registry_must_be_final_promotion_operation() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        _, protected = fixture(tmp)
        plan = promotion_plan(tmp, registry_first=True)
        cfg = config(tmp, protected, [], promotion_mode="explicit", promotion_plan=plan.name)
        code, report = execute(root=tmp, config_path=cfg)
        assert code != 0, report
        assert "registry.json must be the final" in report["reason"]
        assert report["production_before"] == report["production_after"]


def test_mid_promotion_failure_rolls_back_all_prior_replacements() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        _, protected = fixture(tmp)
        plan = promotion_plan(tmp)
        old_model = (tmp / "training/models/pre.json").read_bytes()
        old_registry = (tmp / "training/registry.json").read_bytes()
        cfg = config(tmp, protected, [], promotion_mode="explicit", promotion_plan=plan.name)

        original_replace = atomic_promotion.replace_file
        calls = 0

        def fail_second(staged: Path, destination: Path) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("synthetic second-operation failure")
            original_replace(staged, destination)

        atomic_promotion.replace_file = fail_second
        try:
            code, report = execute(root=tmp, config_path=cfg)
        finally:
            atomic_promotion.replace_file = original_replace

        assert code != 0, report
        assert report["status"] == "FAIL", report
        assert report["production_restored"] is True
        assert report["production_restoration_verified"] is True
        assert report["production_before"] == report["production_after"]
        assert (tmp / "training/models/pre.json").read_bytes() == old_model
        assert (tmp / "training/registry.json").read_bytes() == old_registry


def test_unknown_promotion_mode_is_rejected() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        _, protected = fixture(tmp)
        cfg = config(tmp, protected, [], promotion_mode="automatic")
        try:
            execute(root=tmp, config_path=cfg, require_ready=True)
        except RuntimeError as exc:
            assert "unsupported promotion_mode" in str(exc)
        else:
            raise AssertionError("unknown promotion mode must be rejected")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
    print(f"continuous cycle safety tests: {len(tests)} passed")

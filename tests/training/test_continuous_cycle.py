#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training.run_continuous_cycle import execute  # noqa: E402


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


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


def config(tmp: Path, protected: list[str], stages: list[dict]) -> Path:
    path = tmp / "cycle.json"
    path.write_text(json.dumps({
        "schema": "poker-continuous-cycle/v1",
        "cycle": "synthetic",
        "promotion_mode": "disabled",
        "gate_report": "gate.json",
        "protected_production_paths": protected,
        "stages": stages,
    }), encoding="utf-8")
    return path


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


def test_v1_rejects_any_promotion_mode() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        _, protected = fixture(tmp)
        cfg = config(tmp, protected, [])
        data = json.loads(cfg.read_text())
        data["promotion_mode"] = "automatic"
        cfg.write_text(json.dumps(data), encoding="utf-8")
        try:
            execute(root=tmp, config_path=cfg, require_ready=True)
        except RuntimeError as exc:
            assert "promotion_mode=disabled" in str(exc)
        else:
            raise AssertionError("automatic promotion mode must be rejected by v1")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
    print(f"continuous cycle safety tests: {len(tests)} passed")

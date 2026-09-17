#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training.execute_recalculation_plan import execute_plan  # noqa: E402
from tools.training.recalculation_plan import build_recalculation_plan  # noqa: E402

POP = "pokerstars_nlhe_100-200_zoom_play_6max_v1"
SNAPSHOT_SHA = "a" * 64
COMMIT = "c" * 40
ROLES = [
    "MODEL_A_PREFLOP_FIT",
    "MODEL_A_POSTFLOP_FIT",
    "MODEL_B_FIT",
    "HERO_SEARCH_AND_RANGE_BUILD",
    "FULL_HAND_BENCHMARK",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot() -> dict:
    return {
        "status": "PLANNED",
        "population_id": POP,
        "snapshot_id": "fixture-snapshot",
        "candidate_sha256": SNAPSHOT_SHA,
        "run_id": "fixture-run",
        "runs_root": "runs",
    }


def command(output: str, payload: str = "ok") -> list[str]:
    code = (
        "from pathlib import Path; "
        f"p=Path({output!r}); p.parent.mkdir(parents=True, exist_ok=True); "
        f"p.write_text({payload!r}, encoding='utf-8')"
    )
    return [sys.executable, "-c", code]


def bindings(input_sha: str) -> dict[str, dict]:
    root = "runs/fixture-run"
    outputs = {
        "MODEL_A_PREFLOP_FIT": f"{root}/a-pre.json",
        "MODEL_A_POSTFLOP_FIT": f"{root}/a-post.json",
        "MODEL_B_FIT": f"{root}/b.json",
        "HERO_SEARCH_AND_RANGE_BUILD": f"{root}/hero.json",
        "FULL_HAND_BENCHMARK": f"{root}/benchmark.json",
    }
    common = {
        "source_commit_sha": COMMIT,
        "mode": "RECALCULATE",
        "consumes_snapshot_sha256": SNAPSHOT_SHA,
        "historical_result_reuse": False,
        "result_source": "FRESH_CALCULATION",
    }
    out: dict[str, dict] = {}
    for role in ROLES[:3]:
        out[role] = {
            **common,
            "role": role,
            "component_id": role.lower(),
            "argv": command(outputs[role], role),
            "inputs": [{"path": "input/snapshot.zip", "sha256": input_sha}],
            "required_outputs": [outputs[role]],
        }
    out["HERO_SEARCH_AND_RANGE_BUILD"] = {
        **common,
        "role": "HERO_SEARCH_AND_RANGE_BUILD",
        "component_id": "hero-search",
        "argv": command(outputs["HERO_SEARCH_AND_RANGE_BUILD"], "hero"),
        "inputs": [
            {"path": outputs["MODEL_A_PREFLOP_FIT"], "from_stage": "MODEL_A_PREFLOP_FIT"},
            {"path": outputs["MODEL_A_POSTFLOP_FIT"], "from_stage": "MODEL_A_POSTFLOP_FIT"},
            {"path": outputs["MODEL_B_FIT"], "from_stage": "MODEL_B_FIT"},
        ],
        "required_outputs": [outputs["HERO_SEARCH_AND_RANGE_BUILD"]],
    }
    out["FULL_HAND_BENCHMARK"] = {
        **common,
        "role": "FULL_HAND_BENCHMARK",
        "component_id": "benchmark",
        "argv": command(outputs["FULL_HAND_BENCHMARK"], "bench"),
        "inputs": [
            {"path": outputs["MODEL_B_FIT"], "from_stage": "MODEL_B_FIT"},
            {"path": outputs["HERO_SEARCH_AND_RANGE_BUILD"], "from_stage": "HERO_SEARCH_AND_RANGE_BUILD"},
        ],
        "required_outputs": [outputs["FULL_HAND_BENCHMARK"]],
    }
    return out


def fixture(tmp: Path):
    source = tmp / "input/snapshot.zip"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"new poker hands")
    plan = build_recalculation_plan(snapshot(), bindings(sha256(source)))
    return source, plan


def test_executes_every_stage_and_content_addresses_outputs() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        _, plan = fixture(tmp)
        code, report = execute_plan(plan, root=tmp)
        assert code == 0
        assert report["status"] == "PASS"
        assert report["promotion_authorized"] is False
        assert report["historical_result_reuse"] is False
        assert report["fresh_calculation_verified"] is True
        assert report["completed_roles"] == ROLES
        assert [row["role"] for row in report["stages"]] == ROLES
        assert all(row["status"] == "PASS" for row in report["stages"])
        for stage in report["stages"]:
            assert stage["outputs"]
            for row in stage["outputs"]:
                assert len(row["sha256"]) == 64
                assert row["size_bytes"] > 0
        persisted = json.loads((tmp / "runs/fixture-run/RECALCULATION_EXECUTION.json").read_text())
        assert persisted["status"] == "PASS"


def test_duplicate_execution_is_idempotent_and_does_not_rerun_stages() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        _, plan = fixture(tmp)
        first_code, first = execute_plan(plan, root=tmp)
        assert first_code == 0 and first["status"] == "PASS"
        output = tmp / "runs/fixture-run/a-pre.json"
        before = output.stat().st_mtime_ns
        second_code, second = execute_plan(plan, root=tmp)
        assert second_code == 0
        assert second["status"] == "NO_OP_ALREADY_EXECUTED"
        assert second["idempotent_replay"] is True
        assert output.stat().st_mtime_ns == before


def test_input_hash_mismatch_fails_before_first_stage() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        source, plan = fixture(tmp)
        source.write_bytes(b"tampered")
        code, report = execute_plan(plan, root=tmp)
        assert code != 0
        assert report["status"] == "FAIL"
        assert report["failure"]["role"] == "MODEL_A_PREFLOP_FIT"
        assert "hash mismatch" in report["failure"]["message"]
        assert not (tmp / "runs/fixture-run/a-pre.json").exists()


def test_preexisting_output_is_never_overwritten() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        _, plan = fixture(tmp)
        output = tmp / "runs/fixture-run/a-pre.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("historical", encoding="utf-8")
        code, report = execute_plan(plan, root=tmp)
        assert code != 0
        assert report["status"] == "FAIL"
        assert "overwrite" in report["failure"]["message"]
        assert output.read_text() == "historical"


def test_failed_stage_is_persisted_and_later_stages_do_not_run() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        _, plan = fixture(tmp)
        plan = dict(plan)
        stages = [dict(row) for row in plan["stages"]]
        stages[1]["argv"] = [sys.executable, "-c", "raise SystemExit(7)"]
        # Re-sign the fixture plan after the deliberate test-only mutation.
        from tools.training.recalculation_plan import fingerprint
        plan["stages"] = stages
        unsigned = dict(plan); unsigned.pop("plan_fingerprint_sha256", None)
        plan["plan_fingerprint_sha256"] = fingerprint(unsigned)
        code, report = execute_plan(plan, root=tmp)
        assert code == 7
        assert report["status"] == "FAIL"
        assert report["failure"]["role"] == "MODEL_A_POSTFLOP_FIT"
        assert (tmp / "runs/fixture-run/a-pre.json").is_file()
        assert not (tmp / "runs/fixture-run/b.json").exists()
        persisted = json.loads((tmp / "runs/fixture-run/RECALCULATION_EXECUTION.json").read_text())
        assert persisted["status"] == "FAIL"


def test_blocked_and_noop_plans_never_execute_components() -> None:
    blocked = build_recalculation_plan(snapshot(), {})
    code, report = execute_plan(blocked, root=Path(tempfile.mkdtemp()))
    assert code == 2 and report["status"] == "BLOCKED"
    noop = build_recalculation_plan({"status": "NO_PENDING_SNAPSHOT", "population_id": POP})
    code, report = execute_plan(noop, root=Path(tempfile.mkdtemp()))
    assert code == 0 and report["status"] == "NO_OP"


def main() -> None:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"recalculation executor tests: {len(tests)} passed")


if __name__ == "__main__":
    main()

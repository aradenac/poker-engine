#!/usr/bin/env python3
from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training.recalculation_plan import (  # noqa: E402
    build_recalculation_plan,
    load_contract,
    validate_recalculation_plan,
)

POP = "pokerstars_nlhe_100-200_zoom_play_6max_v1"
SHA_A = "a" * 64
SHA_B = "b" * 64
COMMIT = "c" * 40
INPUT_SHA = "d" * 64
CONTRACT = load_contract()
ROLES = [row["role"] for row in CONTRACT["required_stage_roles"]]


def snapshot(sha: str = SHA_A) -> dict:
    return {
        "status": "PLANNED",
        "population_id": POP,
        "snapshot_id": "20260915-new",
        "candidate_sha256": sha,
        "run_id": f"20260915_continuous_{sha[:12]}",
        "runs_root": f"training/populations/{POP}/runs",
    }


def run_dir(plan: dict) -> str:
    return f"{plan['runs_root']}/{plan['run_id']}"


def bindings(plan: dict) -> dict[str, dict]:
    root = run_dir(plan)
    sha = plan["candidate_sha256"]
    return {
        "MODEL_A_PREFLOP_FIT": {
            "role": "MODEL_A_PREFLOP_FIT",
            "component_id": "model-a-preflop-fit-vnext",
            "source_commit_sha": COMMIT,
            "mode": "RECALCULATE",
            "argv": ["python3", "tools/training/example_a_pre.py", "--snapshot-sha", sha],
            "consumes_snapshot_sha256": sha,
            "inputs": [{"path": "data/decisions.jsonl", "sha256": INPUT_SHA}],
            "required_outputs": [f"{root}/artifacts/model_a_preflop_candidate.json"],
            "historical_result_reuse": False,
            "result_source": "FRESH_CALCULATION",
        },
        "MODEL_A_POSTFLOP_FIT": {
            "role": "MODEL_A_POSTFLOP_FIT",
            "component_id": "model-a-postflop-fit-vnext",
            "source_commit_sha": COMMIT,
            "mode": "RECALCULATE",
            "argv": ["python3", "tools/training/example_a_post.py", "--snapshot-sha", sha],
            "consumes_snapshot_sha256": sha,
            "inputs": [{"path": "data/decisions.jsonl", "sha256": INPUT_SHA}],
            "required_outputs": [f"{root}/artifacts/model_a_postflop_candidate.json"],
            "historical_result_reuse": False,
            "result_source": "FRESH_CALCULATION",
        },
        "MODEL_B_FIT": {
            "role": "MODEL_B_FIT",
            "component_id": "model-b-fit-vnext",
            "source_commit_sha": COMMIT,
            "mode": "RECALCULATE",
            "argv": ["python3", "tools/training/example_b.py", "--snapshot-sha", sha],
            "consumes_snapshot_sha256": sha,
            "inputs": [{"path": "data/decisions.jsonl", "sha256": INPUT_SHA}],
            "required_outputs": [f"{root}/artifacts/model_b_candidate.json"],
            "historical_result_reuse": False,
            "result_source": "FRESH_CALCULATION",
        },
        "HERO_SEARCH_AND_RANGE_BUILD": {
            "role": "HERO_SEARCH_AND_RANGE_BUILD",
            "component_id": "hero-search-range-vnext",
            "source_commit_sha": COMMIT,
            "mode": "RECALCULATE",
            "argv": ["python3", "tools/training/example_hero.py", "--snapshot-sha", sha],
            "consumes_snapshot_sha256": sha,
            "inputs": [
                {"path": f"{root}/artifacts/model_a_preflop_candidate.json", "from_stage": "MODEL_A_PREFLOP_FIT"},
                {"path": f"{root}/artifacts/model_a_postflop_candidate.json", "from_stage": "MODEL_A_POSTFLOP_FIT"},
                {"path": f"{root}/artifacts/model_b_candidate.json", "from_stage": "MODEL_B_FIT"},
            ],
            "required_outputs": [f"{root}/artifacts/hero_policy_candidate.json"],
            "historical_result_reuse": False,
            "result_source": "FRESH_CALCULATION",
        },
        "FULL_HAND_BENCHMARK": {
            "role": "FULL_HAND_BENCHMARK",
            "component_id": "full-hand-benchmark-vnext",
            "source_commit_sha": COMMIT,
            "mode": "RECALCULATE",
            "argv": ["python3", "tools/simulation/example_full_hand.py", "--snapshot-sha", sha],
            "consumes_snapshot_sha256": sha,
            "inputs": [
                {"path": f"{root}/artifacts/model_b_candidate.json", "from_stage": "MODEL_B_FIT"},
                {"path": f"{root}/artifacts/hero_policy_candidate.json", "from_stage": "HERO_SEARCH_AND_RANGE_BUILD"},
            ],
            "required_outputs": [f"{root}/evaluation/full_hand_benchmark.json"],
            "historical_result_reuse": False,
            "result_source": "FRESH_CALCULATION",
        },
    }


def assert_raises(fragment: str, fn) -> None:
    try:
        fn()
    except (ValueError, TypeError) as exc:
        assert fragment.lower() in str(exc).lower(), exc
    else:
        raise AssertionError(f"expected failure containing {fragment!r}")


def test_missing_components_are_prepared_blocked_not_fake_success() -> None:
    plan = build_recalculation_plan(snapshot(), {})
    assert plan["status"] == "PREPARED_BLOCKED"
    assert plan["missing_components"] == ROLES
    assert plan["stages"] == []
    assert plan["promotion_authorized"] is False
    validate_recalculation_plan(plan)


def test_all_real_component_bindings_make_plan_executable() -> None:
    snap = snapshot()
    plan = build_recalculation_plan(snap, bindings(snap))
    assert plan["status"] == "EXECUTABLE"
    assert plan["missing_components"] == []
    assert [row["role"] for row in plan["stages"]] == ROLES
    assert all(row["mode"] == "RECALCULATE" for row in plan["stages"])
    assert all(row["consumes_snapshot_sha256"] == SHA_A for row in plan["stages"])
    assert all(row["historical_result_reuse"] is False for row in plan["stages"])
    assert all(row["result_source"] == "FRESH_CALCULATION" for row in plan["stages"])
    validate_recalculation_plan(plan)


def test_outputs_must_be_new_run_scoped_and_cannot_overwrite_history() -> None:
    snap = snapshot()
    bad = bindings(snap)
    bad["MODEL_A_PREFLOP_FIT"]["required_outputs"] = ["training/runs/20260913_old/result.json"]
    assert_raises("new run directory", lambda: build_recalculation_plan(snap, bad))


def test_historical_report_cannot_satisfy_required_recalculation_stage() -> None:
    snap = snapshot()
    bad = bindings(snap)
    bad["MODEL_B_FIT"]["historical_result_reuse"] = True
    bad["MODEL_B_FIT"]["result_source"] = "HISTORICAL_REPORT"
    assert_raises("historical_result_reuse", lambda: build_recalculation_plan(snap, bad))


def test_every_bound_component_must_consume_exact_new_snapshot_identity() -> None:
    snap = snapshot()
    bad = bindings(snap)
    bad["MODEL_A_POSTFLOP_FIT"]["consumes_snapshot_sha256"] = SHA_B
    assert_raises("selected snapshot", lambda: build_recalculation_plan(snap, bad))


def test_generated_dependency_inputs_cannot_skip_the_declared_dag() -> None:
    snap = snapshot()
    bad = bindings(snap)
    bad["FULL_HAND_BENCHMARK"]["inputs"].append(
        {"path": f"{run_dir(snap)}/artifacts/model_a_preflop_candidate.json", "from_stage": "MODEL_A_PREFLOP_FIT"}
    )
    assert_raises("non-dependency", lambda: build_recalculation_plan(snap, bad))


def test_no_pending_or_already_processed_snapshot_is_traceable_noop() -> None:
    for source_status in ("NO_PENDING_SNAPSHOT", "NO_OP_ALREADY_PROCESSED"):
        plan = build_recalculation_plan({"status": source_status, "population_id": POP, "snapshot_id": "old"})
        assert plan["status"] == "NO_OP"
        assert plan["source_snapshot_status"] == source_status
        assert plan["stages"] == []
        assert plan["promotion_authorized"] is False
        validate_recalculation_plan(plan)


def test_plan_fingerprint_is_idempotent_and_bound_to_snapshot_and_components() -> None:
    snap_a = snapshot(SHA_A)
    first = build_recalculation_plan(snap_a, bindings(snap_a))
    second = build_recalculation_plan(snap_a, bindings(snap_a))
    assert first["plan_fingerprint_sha256"] == second["plan_fingerprint_sha256"]

    changed_components = bindings(snap_a)
    changed_components["MODEL_B_FIT"]["component_id"] = "model-b-fit-new-revision"
    changed = build_recalculation_plan(snap_a, changed_components)
    assert changed["plan_fingerprint_sha256"] != first["plan_fingerprint_sha256"]

    snap_b = snapshot(SHA_B)
    other_snapshot = build_recalculation_plan(snap_b, bindings(snap_b))
    assert other_snapshot["plan_fingerprint_sha256"] != first["plan_fingerprint_sha256"]


def test_persisted_plan_tampering_is_detected() -> None:
    snap = snapshot()
    plan = build_recalculation_plan(snap, bindings(snap))
    tampered = copy.deepcopy(plan)
    tampered["stages"][-1]["result_source"] = "HISTORICAL_REPORT"
    assert_raises("fingerprint", lambda: validate_recalculation_plan(tampered))


def test_invalid_or_unknown_component_identity_fails_closed() -> None:
    snap = snapshot()
    bad = bindings(snap)
    bad["MODEL_A_PREFLOP_FIT"]["source_commit_sha"] = "not-a-commit"
    assert_raises("40-hex", lambda: build_recalculation_plan(snap, bad))
    extra = bindings(snap)
    extra["UNKNOWN_FIT"] = copy.deepcopy(extra["MODEL_B_FIT"])
    assert_raises("unknown recalculation", lambda: build_recalculation_plan(snap, extra))


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"fresh recalculation plan tests: {len(tests)} passed")

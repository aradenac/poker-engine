#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

from tools.training.enrich_hero_range_context import canonical_context_for_state
from tools.training.generate_hero_range_decisions import ContextSpec, HAND_CLASSES, build_context_state
from tools.training.merge_hero_policy_context_sources import merge_sources
from tools.training.validate_hero_pfpc_evidence import validate

POPULATION = "pokerstars_nlhe_100-200_zoom_play_6max_v1"
POSITIONS = ("LJ", "HJ", "CO", "BTN", "SB")
NEW_POSITIONS = ("LJ", "HJ", "CO", "SB")


def canonical_bytes(value) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_fixture(root: Path, position: str, *, bad_sizing: bool = False):
    spec = ContextSpec(position=position, effective_stack_bb=100.0, spot="UNOPENED")
    state = build_context_state(spec)
    canonical = canonical_context_for_state(state, position)
    pfc = canonical["context_id"]
    repo_key = f"{POPULATION}|6|{position}|100|UNOPENED|{pfc}"
    target = 3.0
    decision = {
        "schema": "poker-preflop-decision/v1",
        "population_id": POPULATION,
        "action": "OPEN",
        "target_total_bb": target,
        "ev_bb": 1.25,
        "selected_id": "OPEN@3BB",
        "search": {"budget": 16},
    }
    strategy_target = 2.0 if bad_sizing else target
    strategy = {
        "actions": {"OPEN": 1.0},
        "sizings": {"OPEN": [{"target_total_bb": strategy_target, "probability": 1.0}]},
        "notes": "fixture",
    }
    provenance = {
        "code": "a" * 40,
        "selection": "NOT_PROMOTED_ISSUE_107_EXPERIMENTAL",
        "models": {"preflop_sha256": "b" * 64},
        "budget": {
            "requested_hand_classes": 169,
            "completed_hand_classes": 1,
            "unsupported_hand_classes": 168,
            "samples_per_nonfold_candidate": 16,
            "rollout_samples_consumed": 16,
        },
        "sizing_support": {
            "filters": {"split": "TRAIN", "is_hero": False},
        },
        "continuation_support": {
            "enabled": True,
            "nearest_context_substitution": False,
            "fallback_contract": "CHECK_THEN_CALL_THEN_FOLD_V1",
        },
        "context_identity": {
            "schema": "poker-preflop-context/v1",
            "preflop_context_id": pfc,
            "legacy_context_id": spec.context_id,
            "binding": "IDENTITY_ONLY_FROM_SAME_PUBLIC_STATE_BEFORE_ACTION",
            "decision_payload_mutation": "NONE",
            "rollout_recomputation": False,
        },
    }
    unsupported = [
        {"hand_class": hand, "reason": "fixture unsupported"}
        for hand in HAND_CLASSES
        if hand != "AA"
    ]
    run = {
        "schema": "poker-hero-range-decision-run/v1",
        "status": "EXPERIMENTAL",
        "promotion_authorized": False,
        "population_id": POPULATION,
        "context": {
            "population_id": POPULATION,
            "table_size": 6,
            "position": position,
            "effective_stack_bb": 100.0,
            "spot": "UNOPENED",
            "preflop_context_id": pfc,
        },
        "context_id": pfc,
        "legacy_context_id": spec.context_id,
        "canonical_preflop_context": canonical,
        "version": f"fixture-{position.lower()}",
        "rows": [{"hand_class": "AA", "decision": decision}],
        "unsupported": unsupported,
        "coverage": {
            "requested": 169,
            "completed": 1,
            "unsupported": 168,
            "accounted": 169,
            "complete_169": False,
        },
        "provenance": provenance,
    }
    repository = {
        "schema": "poker-hero-range-repository/v1",
        "version": 1,
        "source": {"format": None, "meta": None, "preserved_verbatim": False, "range_folder": None},
        "defaults": {
            "population_id": POPULATION,
            "table_size": 6,
            "effective_stack_bb": 100.0,
        },
        "contexts": {
            repo_key: {
                "context": {
                    "population_id": POPULATION,
                    "table_size": 6,
                    "position": position,
                    "effective_stack_bb": 100.0,
                    "spot": "UNOPENED",
                    "preflop_context_id": pfc,
                },
                "layers": {
                    "calculated": {
                        "kind": "calculated",
                        "version": f"fixture-{position.lower()}",
                        "provenance": provenance,
                        "hands": {"AA": strategy},
                    },
                    "personal": {
                        "kind": "personal",
                        "version": None,
                        "provenance": None,
                        "hands": {},
                    },
                },
            }
        },
    }
    candidate = {
        "schema": "poker-hero-calculated-range-candidate/v1",
        "status": "EXPERIMENTAL",
        "population_id": POPULATION,
        "context": run["context"],
        "version": run["version"],
        "layer": "calculated",
        "promotion_authorized": False,
        "coverage": {
            "defined_hand_classes": 1,
            "required_hand_classes": 169,
            "complete": False,
        },
        "provenance": provenance,
        "policy_origins": {"AA": "SELECTED_DECISION_ONE_HOT"},
        "decisions": {"AA": decision},
        "repository": repository,
        "source_decision_run": {
            "schema": run["schema"],
            "context_id": pfc,
            "coverage": run["coverage"],
            "unsupported": unsupported,
        },
    }

    base = root / position
    repo_path = base / "HERO_RANGE_REPOSITORY_PFC.json"
    bind_path = base / "PFC_BINDING.json"
    write_json(base / "DECISION_RUN_PFC.json", run)
    write_json(base / "CANDIDATE_PFC.json", candidate)
    write_json(repo_path, repository)
    binding = {
        "schema": "poker-hero-range-pfc-binding/v1",
        "issue": 107,
        "run_id": f"fixture-{position.lower()}",
        "source_run_id": run["version"],
        "status": "EXPERIMENTAL",
        "promotion_authorized": False,
        "population_id": POPULATION,
        "preflop_context_id": pfc,
        "canonical_preflop_context": canonical,
        "legacy_context_id": spec.context_id,
        "coverage": {
            "requested": 169,
            "supported": 1,
            "unsupported": 168,
            "accounted": 169,
        },
        "artifact_sha256": {
            "hero_range_repository_pfc": sha(repo_path),
        },
        "identity_transform": provenance["context_identity"],
        "selection_boundary": {
            "candidate_status": "EXPERIMENTAL",
            "validation_consumed": False,
            "test_consumed": False,
        },
        "handoff": {
            "supported_policy": "SOURCE_PFC_FOR_EXPLICIT_PFPC_BINDING_ONLY",
            "nearest_context_substitution": False,
        },
    }
    write_json(bind_path, binding)
    return repo_path, bind_path




def btn_history_fixture(source_dir: Path, history_dir: Path, *, bad_sizing: bool = False) -> Path:
    run = json.loads((source_dir / "DECISION_RUN_PFC.json").read_text(encoding="utf-8"))
    rows = []
    action_counts = {}
    for source in run["rows"]:
        hand = source["hand_class"]
        decision = source["decision"]
        target = decision.get("target_total_bb")
        if bad_sizing and hand == "AA" and target is not None:
            target = float(target) + 0.5
        action = str(decision["action"])
        action_counts[action] = action_counts.get(action, 0) + 1
        rows.append({
            "hand_class": hand,
            "action": action,
            "target_total_bb": target,
            "ev_bb": decision["ev_bb"],
            "search_budget": decision["search"]["budget"],
            "selected_id": decision["selected_id"],
        })
    unsupported_rows = [
        {
            "hand_class": row["hand_class"],
            "failing_actor": "BTN",
            "failing_street": "preflop",
            "reason": row["reason"],
        }
        for row in run["unsupported"]
    ]
    write_json(history_dir / "SUPPORTED_DECISIONS.json", {
        "schema": "poker-hero-supported-decisions/v1",
        "run_id": "fixture-btn-history",
        "population_id": POPULATION,
        "context": run["context"],
        "count": len(rows),
        "rows": rows,
    })
    write_json(history_dir / "UNSUPPORTED.json", {
        "schema": "poker-hero-unsupported-hand-classes/v1",
        "run_id": "fixture-btn-history",
        "population_id": POPULATION,
        "context": run["context"],
        "count": len(unsupported_rows),
        "rows": unsupported_rows,
    })
    write_json(history_dir / "RESULT.json", {
        "schema": "poker-hero-preflop-169-generation-result/v1",
        "issue": 107,
        "run_id": "fixture-btn-history",
        "population_id": POPULATION,
        "promotion_authorized": False,
        "coverage": {
            "requested": 169,
            "completed": len(rows),
            "unsupported": len(unsupported_rows),
            "accounted": 169,
            "complete_169": len(unsupported_rows) == 0,
        },
        "selected_action_counts": action_counts,
        "selection_boundary": {
            "validation_consumed": False,
            "test_consumed": False,
        },
    })
    return history_dir


def evidence_fixture(
    root: Path,
    *,
    bad_sizing_position: str | None = None,
    bad_btn_history_sizing: bool = False,
):
    raw = root / "raw"
    paths = {
        position: source_fixture(raw, position, bad_sizing=(position == bad_sizing_position))
        for position in POSITIONS
    }
    final_repo, final_binding, result = merge_sources(
        [paths[position][0] for position in POSITIONS],
        [paths[position][1] for position in POSITIONS],
        run_id="20260918_hero_preflop_unopened_5pos_pfpc_v1",
    )

    evidence = root / "evidence"
    evidence.mkdir()
    write_json(evidence / "HERO_RANGE_REPOSITORY_PFPC.json", final_repo)
    write_json(evidence / "POLICY_CONTEXT_BINDING.json", final_binding)
    write_json(evidence / "RESULT.json", result)
    for position in NEW_POSITIONS:
        target = evidence / "sources" / position
        target.mkdir(parents=True)
        for name in (
            "DECISION_RUN_PFC.json",
            "CANDIDATE_PFC.json",
            "HERO_RANGE_REPOSITORY_PFC.json",
            "PFC_BINDING.json",
        ):
            (target / name).write_bytes((raw / position / name).read_bytes())

    source_record = {
        "schema": "poker-hero-pfpc-persistence/v1",
        "issue": 107,
        "run_id": result["run_id"],
        "population_id": POPULATION,
        "source_workflow_name": "fixture",
        "source_workflow_run_id": 1,
        "source_branch": "fixture",
        "source_head_sha": "c" * 40,
        "promotion_authorized": False,
        "validation_consumed": False,
        "test_consumed": False,
        "artifact_sha256": {
            "HERO_RANGE_REPOSITORY_PFPC.json": sha(evidence / "HERO_RANGE_REPOSITORY_PFPC.json"),
            "POLICY_CONTEXT_BINDING.json": sha(evidence / "POLICY_CONTEXT_BINDING.json"),
            "RESULT.json": sha(evidence / "RESULT.json"),
        },
        "new_position_sources": {},
    }
    write_json(evidence / "SOURCE_RUN.json", source_record)
    btn_history = btn_history_fixture(
        raw / "BTN",
        root / "btn-history",
        bad_sizing=bad_btn_history_sizing,
    )
    return evidence, raw / "BTN", btn_history


def test_valid_five_position_evidence_passes_and_checks_decision_parity():
    with tempfile.TemporaryDirectory() as tmp:
        evidence, btn, btn_history = evidence_fixture(Path(tmp))
        result = validate(evidence, btn, btn_history)
        assert result["status"] == "PASS"
        assert result["supported_hand_slots"] == 5
        assert result["unsupported_hand_slots"] == 5 * 168
        assert result["parity_checked_hands"] == 5
        assert result["new_position_parity_checked_hands"] == 4
        assert result["positions"]["BTN"]["parity_checked_hands"] == 1
        assert result["validation_consumed"] is False
        assert result["test_consumed"] is False


def test_selected_sizing_drift_fails_even_when_all_hashes_are_self_consistent():
    with tempfile.TemporaryDirectory() as tmp:
        evidence, btn, btn_history = evidence_fixture(Path(tmp), bad_sizing_position="CO")
        try:
            validate(evidence, btn, btn_history)
        except ValueError as exc:
            assert "CO/AA: selected sizing absent from repository" in str(exc)
        else:
            raise AssertionError("selected action/sizing parity drift must fail closed")



def test_historical_btn_sizing_drift_fails_closed():
    with tempfile.TemporaryDirectory() as tmp:
        evidence, btn, btn_history = evidence_fixture(
            Path(tmp),
            bad_btn_history_sizing=True,
        )
        try:
            validate(evidence, btn, btn_history)
        except ValueError as exc:
            assert "BTN/AA: selected sizing parity drift" in str(exc)
        else:
            raise AssertionError("historical BTN action/sizing parity drift must fail closed")


def main():
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for fn in tests:
        fn()
    print(f"PFPC persisted-evidence tests: {len(tests)} passed")


if __name__ == "__main__":
    main()

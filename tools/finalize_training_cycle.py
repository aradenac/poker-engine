#!/usr/bin/env python3
"""Build and verify an immutable final state for a completed training cycle."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CYCLE = "2026-09-12"
RUN_DIR = Path("training/runs/20260912_population_increment_cycle")
GATE_REPORT = Path("training/gates/20260912_report.json")
GATE_EVIDENCE = Path("training/gates/20260912_evidence.json")
REGISTRY = Path("training/registry.json")
CYCLE_MANIFEST = RUN_DIR / "manifest.json"
STRATEGY_DIR = Path("training/runs/20260913_strategy_candidate_v84")


def load(path: Path) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with (ROOT / path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def git_blob(path: Path) -> str:
    return subprocess.check_output(
        ["git", "hash-object", str(path)], cwd=ROOT, text=True
    ).strip()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def component(report: dict, name: str) -> dict:
    return next(x for x in report["components"] if x["name"] == name)


def observed_check(report: dict, component_name: str, check_id: str):
    comp = component(report, component_name)
    item = next(x for x in comp["checks"] if x["id"] == check_id)
    return item.get("observed")


def artifact(path: Path) -> dict:
    require((ROOT / path).is_file(), f"missing required artifact: {path}")
    return {"path": str(path), "sha256": sha256(path)}


def build_final_state(*, gate_merge_commit: str, expected_registry_blob: str) -> dict:
    report = load(GATE_REPORT)
    evidence = load(GATE_EVIDENCE)
    registry = load(REGISTRY)
    cycle_manifest = load(CYCLE_MANIFEST)
    strategy_decision = load(STRATEGY_DIR / "decision.json")

    require(report.get("schema") == "poker-promotion-gate-report/v1", "unexpected gate report schema")
    require(report.get("cycle") == CYCLE, "gate report cycle mismatch")
    require(report.get("status") == "PASS", "final promotion gate is not PASS")
    require(report.get("promotion_ready") is True, "final promotion gate is not promotion_ready")

    required_decisions = ("model_a_preflop", "model_a_postflop", "model_b", "strategy")
    for name in required_decisions:
        d = report.get("candidate_decisions", {}).get(name, {})
        require(d.get("status") == "PASS", f"{name}: process gate not PASS")
        require(d.get("decision") == "RETAIN_BASELINE", f"{name}: expected RETAIN_BASELINE")
        require(d.get("promotion_allowed") is False, f"{name}: rejected candidate unexpectedly promotable")

    require(strategy_decision.get("strategy_decision") == "RETAIN_BASELINE", "strategy evidence does not retain v83")
    require(strategy_decision.get("test_consumed") is False, "strategy protected TEST was unexpectedly consumed")

    require(registry.get("active_dataset") == "NLHE_100-200", "active dataset drift")
    require(registry.get("promoted_model", {}).get("preflop") == "training/models/preflop_population_model_v5.json", "preflop production pointer drift")
    require(registry.get("promoted_model", {}).get("postflop") == "training/models/postflop_population_model_v5.json", "postflop production pointer drift")
    require(registry.get("promoted_independent_model", {}).get("alias") == "independent_model_b_v2", "Model B production alias drift")
    require(registry.get("candidate_run") is None, "candidate_run must remain null after retain-all cycle")

    registry_blob = git_blob(REGISTRY)
    require(registry_blob == expected_registry_blob, f"registry blob drift: {registry_blob} != {expected_registry_blob}")

    parent = cycle_manifest["parent_models"]
    preflop = Path(registry["promoted_model"]["preflop"])
    postflop = Path(registry["promoted_model"]["postflop"])
    require(sha256(preflop) == parent["preflop"]["sha256"], "promoted preflop bytes drifted")
    require(sha256(postflop) == parent["postflop"]["sha256"], "promoted postflop bytes drifted")

    release = evidence["release_identity"]
    engine = Path(release["engine_release_artifact"])
    site = Path(release["assembled_site_entrypoint"])
    require(sha256(engine) == release["engine_release_sha256"], "promoted engine bytes drifted")
    require(git_blob(site) == release["assembled_site_git_blob_sha"], "assembled site blob drifted")

    dataset = registry["datasets"]["NLHE_100-200"]["latest_candidate_snapshot"]
    snapshot_archive = Path(dataset["archive"])
    increment_archive = Path(dataset["increment_archive"])
    require(sha256(snapshot_archive) == dataset["source_sha256"], "2026-09-12 source snapshot checksum drift")
    require(sha256(increment_archive) == cycle_manifest["source_increment"]["sha256"], "selected increment checksum drift")

    model_b_dir = Path(registry["promoted_independent_model"]["model_dir"])
    promoted_model_b = {
        name: artifact(model_b_dir / name)
        for name in (
            "prediction_contract.json",
            "profiles.json",
            "preflop_ranges.json",
            "postflop_actions.json",
            "sizing.json",
            "summary.json",
        )
    }

    evidence_artifacts = {
        "gate_evidence": artifact(GATE_EVIDENCE),
        "gate_report": artifact(GATE_REPORT),
        "cycle_manifest": artifact(CYCLE_MANIFEST),
        "snapshot_manifest": artifact(Path(dataset["archive_manifest"])),
        "increment_manifest": artifact(Path(dataset["increment_manifest"])),
        "strategy_contract": artifact(Path("training/strategy/STRATEGY_CANDIDATE_CONTRACT_20260913.json")),
        "strategy_decision": artifact(STRATEGY_DIR / "decision.json"),
        "strategy_validation_selection": artifact(STRATEGY_DIR / "validation_selection.json"),
        "strategy_validation_scenarios": artifact(STRATEGY_DIR / "validation_scenarios.json"),
        "model_b_refresh_decision": artifact(Path("training/runs/20260912_population_increment_cycle/model_b/evaluation/paired_comparison.json")),
        "model_a_rebuild_evidence": artifact(RUN_DIR / "evaluation/model_a_candidate_rebuild_manifest.json"),
    }

    source_state = {
        "population": "NLHE 100-200",
        "source_snapshot": artifact(snapshot_archive),
        "selected_increment": artifact(increment_archive),
        "selected_hand_ids_fingerprint_sha256": dataset["selected_hand_ids_fingerprint_sha256"],
        "split_counts": dataset["split_counts"],
        "genuinely_unseen_hands": dataset["genuinely_unseen_100_200_hands"],
        "resulting_union_unique_hands": dataset["resulting_union_unique_100_200_hands"],
    }

    production = {
        "model_a_preflop": artifact(preflop),
        "model_a_postflop": artifact(postflop),
        "model_b": {
            "alias": registry["promoted_independent_model"]["alias"],
            "run_id": registry["promoted_independent_model"]["run_id"],
            "model_dir": str(model_b_dir),
            "artifacts": promoted_model_b,
        },
        "engine": artifact(engine),
        "assembled_site": {
            "path": str(site),
            "git_blob_sha": git_blob(site),
            "assembled_from_commit": release["assembled_from_commit"],
            "assets_tree_git_sha": release["assets_tree_git_sha"],
        },
    }

    decisions = {
        name: {
            "decision": report["candidate_decisions"][name]["decision"],
            "promotion_allowed": report["candidate_decisions"][name]["promotion_allowed"],
        }
        for name in required_decisions
    }

    return {
        "schema": "poker-training-cycle-final-state/v1",
        "cycle": CYCLE,
        "closed_on": "2026-09-14",
        "finalization_base_commit": gate_merge_commit,
        "gate": {
            "status": report["status"],
            "promotion_ready": report["promotion_ready"],
            "report": evidence_artifacts["gate_report"],
            "evidence": evidence_artifacts["gate_evidence"],
        },
        "production_transition": {
            "type": "NO_OP_RETAIN_ALL",
            "registry_changed": False,
            "model_a_changed": False,
            "model_b_changed": False,
            "engine_changed": False,
            "site_changed": False,
            "registry_before_git_blob_sha": expected_registry_blob,
            "registry_after_git_blob_sha": registry_blob,
            "reason": "All four candidate gates completed with RETAIN_BASELINE; no production pointer is authorized to move.",
        },
        "decisions": decisions,
        "source_state": source_state,
        "production_state": production,
        "evidence_artifacts": evidence_artifacts,
        "holdout_protection": {
            "strategy_test_consumed": False,
            "strategy_test_outcome": strategy_decision.get("test_outcome"),
            "model_b_test_used_for_selection": evidence["model_b"].get("test_used_for_selection"),
            "model_a_preflop_test_used_for_selection": evidence["model_a"]["preflop"].get("test_used_for_selection"),
            "model_a_postflop_test_used_for_selection": evidence["model_a"]["postflop"].get("test_used_for_selection"),
        },
        "rollback": {
            "registry_git_blob_sha": expected_registry_blob,
            "promoted_model_a": registry["promoted_model"],
            "promoted_model_b_alias": registry["promoted_independent_model"]["alias"],
            "promoted_engine_artifact": str(engine),
            "promoted_engine_sha256": release["engine_release_sha256"],
        },
        "deployment": {
            "required_by_this_transition": False,
            "site_release_attempted": False,
            "separate_verification_issue": "#45",
            "reason": "No engine/model/site artifact was promoted in this cycle.",
        },
        "follow_up_not_part_of_closed_cycle": ["#13", "#61", "#73", "#74"],
    }


def canonical_bytes(data: dict) -> bytes:
    return (json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(RUN_DIR / "FINAL_STATE.json"))
    ap.add_argument("--gate-merge-commit", required=True)
    ap.add_argument("--expected-registry-blob", required=True)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    out = ROOT / args.out
    data = build_final_state(
        gate_merge_commit=args.gate_merge_commit,
        expected_registry_blob=args.expected_registry_blob,
    )
    payload = canonical_bytes(data)

    if args.check:
        require(out.is_file(), f"final state missing: {out.relative_to(ROOT)}")
        require(out.read_bytes() == payload, "FINAL_STATE.json is stale or does not match current promoted bytes")
        print(f"final state verified: {out.relative_to(ROOT)}")
        return 0

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(payload)
    print(f"final state written: {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Validate persisted #107 five-position PFPC evidence without recomputation.

This validator is intentionally artifact-only. It proves that the persisted
candidate still contains the exact selected action/sizing decisions emitted by
#106, that every new position accounts for all 169 hand classes, that all
repository/binding hashes agree, and that VALIDATION/TEST remain untouched.

It never runs poker rollouts and never performs strategy selection.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from tools.training.generate_hero_range_decisions import HAND_CLASSES

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE = ROOT / "training/runs/20260918_hero_preflop_unopened_5pos_pfpc_v1"
DEFAULT_BTN = ROOT / "training/runs/20260917_hero_preflop_169_btn_unopened_pfc_v1"

RUN_SCHEMA = "poker-hero-range-decision-run/v1"
CANDIDATE_SCHEMA = "poker-hero-calculated-range-candidate/v1"
REPOSITORY_SCHEMA = "poker-hero-range-repository/v1"
PFC_BINDING_SCHEMA = "poker-hero-range-pfc-binding/v1"
PFPC_BINDING_SCHEMA = "poker-hero-policy-context-binding/v1"
MERGE_RESULT_SCHEMA = "poker-hero-policy-context-merge-result/v1"
PERSISTENCE_SCHEMA = "poker-hero-pfpc-persistence/v1"
DECISION_SCHEMA = "poker-preflop-decision/v1"
POSITIONS = ("LJ", "HJ", "CO", "BTN", "SB")
NEW_POSITIONS = ("LJ", "HJ", "CO", "SB")
EPS = 1e-9


def load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _need(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _range_action(action: str, spot: str) -> str:
    name = str(action or "").upper()
    if name == "SQUEEZE":
        _need(str(spot or "").upper() == "VS_RFI_CALLERS", "SQUEEZE outside VS_RFI_CALLERS")
        return "3BET"
    return name


def _selected_sizing_probability(strategy: Mapping[str, Any], action: str, target: float) -> float:
    probability = 0.0
    for row in (strategy.get("sizings") or {}).get(action, []):
        if abs(float(row["target_total_bb"]) - float(target)) <= 1e-6:
            probability += float(row.get("probability") or 0.0)
    return probability


def _validate_source(
    source_dir: Path,
    *,
    position: str,
    expected_population: str,
) -> dict[str, Any]:
    run_path = source_dir / "DECISION_RUN_PFC.json"
    candidate_path = source_dir / "CANDIDATE_PFC.json"
    repository_path = source_dir / "HERO_RANGE_REPOSITORY_PFC.json"
    binding_path = source_dir / "PFC_BINDING.json"
    for path in (run_path, candidate_path, repository_path, binding_path):
        _need(path.is_file(), f"{position}: missing {path.name}")

    run = load(run_path)
    candidate = load(candidate_path)
    repository = load(repository_path)
    binding = load(binding_path)

    _need(run.get("schema") == RUN_SCHEMA, f"{position}: run schema mismatch")
    _need(candidate.get("schema") == CANDIDATE_SCHEMA, f"{position}: candidate schema mismatch")
    _need(repository.get("schema") == REPOSITORY_SCHEMA, f"{position}: repository schema mismatch")
    _need(binding.get("schema") == PFC_BINDING_SCHEMA, f"{position}: PFC binding schema mismatch")
    _need(run.get("promotion_authorized") is False, f"{position}: run self-promotes")
    _need(candidate.get("promotion_authorized") is False, f"{position}: candidate self-promotes")
    _need(binding.get("promotion_authorized") is False, f"{position}: binding self-promotes")

    population = str(run.get("population_id") or "")
    _need(population == expected_population, f"{position}: population mismatch")
    _need(str(candidate.get("population_id") or "") == population, f"{position}: candidate population mismatch")
    _need(str(binding.get("population_id") or "") == population, f"{position}: binding population mismatch")
    _need(str((run.get("context") or {}).get("position") or "") == position, f"{position}: run position mismatch")
    canonical = dict(run.get("canonical_preflop_context") or {})
    _need(str(canonical.get("actor_position") or "") == position, f"{position}: canonical actor mismatch")
    pfc_id = str(canonical.get("context_id") or "")
    _need(pfc_id.startswith("PFC_"), f"{position}: invalid PFC id")
    _need(str(run.get("context_id") or "") == pfc_id, f"{position}: run/PFC identity mismatch")
    _need(str(binding.get("preflop_context_id") or "") == pfc_id, f"{position}: binding/PFC mismatch")

    rows = list(run.get("rows") or [])
    unsupported = list(run.get("unsupported") or [])
    coverage = dict(run.get("coverage") or {})
    requested = int(coverage.get("requested", -1))
    completed = int(coverage.get("completed", -1))
    unsupported_count = int(coverage.get("unsupported", -1))
    accounted = int(coverage.get("accounted", completed + unsupported_count))
    _need(requested == len(HAND_CLASSES) == 169, f"{position}: requested coverage != 169")
    _need(completed == len(rows), f"{position}: completed count mismatch")
    _need(unsupported_count == len(unsupported), f"{position}: unsupported count mismatch")
    _need(accounted == completed + unsupported_count == 169, f"{position}: incomplete 169 accounting")
    hands = [str(row.get("hand_class") or "") for row in rows]
    unsupported_hands = [str(row.get("hand_class") or "") for row in unsupported]
    _need(len(set(hands)) == len(hands), f"{position}: duplicate supported hand")
    _need(len(set(unsupported_hands)) == len(unsupported_hands), f"{position}: duplicate unsupported hand")
    _need(set(hands).isdisjoint(unsupported_hands), f"{position}: hand both supported and unsupported")
    _need(set(hands) | set(unsupported_hands) == set(HAND_CLASSES), f"{position}: 169 hand set mismatch")
    _need(len(rows) > 0, f"{position}: zero supported classes")

    bind_cov = dict(binding.get("coverage") or {})
    _need(
        bind_cov == {
            "requested": 169,
            "supported": completed,
            "unsupported": unsupported_count,
            "accounted": 169,
        },
        f"{position}: binding coverage drift",
    )
    boundary = dict(binding.get("selection_boundary") or {})
    _need(boundary.get("validation_consumed") is False, f"{position}: VALIDATION already consumed")
    _need(boundary.get("test_consumed") is False, f"{position}: TEST already consumed")

    provenance = dict(run.get("provenance") or {})
    sizing = dict(provenance.get("sizing_support") or {})
    filters = dict(sizing.get("filters") or {})
    _need(filters.get("split") == "TRAIN", f"{position}: sizing evidence is not TRAIN-only")
    _need(filters.get("is_hero") is False, f"{position}: sizing evidence must remain population-only")
    closure = dict(provenance.get("continuation_support") or {})
    _need(closure.get("enabled") is True, f"{position}: continuation closure missing")
    _need(closure.get("nearest_context_substitution") is False, f"{position}: nearest-context substitution enabled")
    _need(closure.get("fallback_contract") == "CHECK_THEN_CALL_THEN_FOLD_V1", f"{position}: closure contract drift")

    candidate_coverage = dict(candidate.get("coverage") or {})
    _need(int(candidate_coverage.get("defined_hand_classes", -1)) == completed, f"{position}: candidate coverage drift")
    _need(int(candidate_coverage.get("required_hand_classes", -1)) == 169, f"{position}: candidate required count drift")
    _need(bool(candidate_coverage.get("complete")) == (completed == 169), f"{position}: candidate completeness drift")
    _need(candidate.get("repository") == repository, f"{position}: candidate repository differs from persisted repository")
    source_decision_run = dict(candidate.get("source_decision_run") or {})
    _need(source_decision_run.get("unsupported") == unsupported, f"{position}: candidate unsupported evidence drift")

    decisions = dict(candidate.get("decisions") or {})
    row_by_hand = {str(row["hand_class"]): row for row in rows}
    _need(set(decisions) == set(row_by_hand), f"{position}: candidate decision coverage differs from run")
    origins = dict(candidate.get("policy_origins") or {})

    contexts = dict(repository.get("contexts") or {})
    _need(len(contexts) == 1, f"{position}: source repository must contain exactly one context")
    node = next(iter(contexts.values()))
    repo_context = dict(node.get("context") or {})
    _need(str(repo_context.get("preflop_context_id") or "") == pfc_id, f"{position}: repository PFC mismatch")
    calculated_hands = dict((((node.get("layers") or {}).get("calculated") or {}).get("hands") or {}))
    _need(set(calculated_hands) == set(row_by_hand), f"{position}: repository hand coverage differs from run")

    parity = 0
    for hand, row in row_by_hand.items():
        decision = dict(row.get("decision") or {})
        _need(decision.get("schema") == DECISION_SCHEMA, f"{position}/{hand}: decision schema mismatch")
        _need(decisions.get(hand) == decision, f"{position}/{hand}: candidate decision payload drift")
        ev = float(decision.get("ev_bb"))
        _need(math.isfinite(ev), f"{position}/{hand}: non-finite EV")
        search = dict(decision.get("search") or {})
        _need(int(search.get("budget") or 0) > 0, f"{position}/{hand}: missing search budget")
        strategy = dict(calculated_hands.get(hand) or {})
        action = _range_action(str(decision.get("action") or ""), str(repo_context.get("spot") or ""))
        action_probability = float((strategy.get("actions") or {}).get(action) or 0.0)
        _need(action_probability > EPS, f"{position}/{hand}: selected action absent from repository")
        target = decision.get("target_total_bb")
        if target is not None:
            _need(
                _selected_sizing_probability(strategy, action, float(target)) > EPS,
                f"{position}/{hand}: selected sizing absent from repository",
            )
        origin = str(origins.get(hand) or "")
        if origin == "SELECTED_DECISION_ONE_HOT":
            _need(abs(action_probability - 1.0) <= EPS, f"{position}/{hand}: one-hot action probability drift")
            _need(len(strategy.get("actions") or {}) == 1, f"{position}/{hand}: one-hot strategy gained actions")
            if target is not None:
                _need(
                    abs(_selected_sizing_probability(strategy, action, float(target)) - 1.0) <= EPS,
                    f"{position}/{hand}: one-hot sizing probability drift",
                )
        else:
            _need(origin == "EXPLICIT_POLICY", f"{position}/{hand}: unknown policy origin {origin!r}")
        parity += 1

    repository_sha = sha256(repository_path)
    binding_sha = sha256(binding_path)
    _need(
        str((binding.get("artifact_sha256") or {}).get("hero_range_repository_pfc") or "") == repository_sha,
        f"{position}: repository SHA differs from binding",
    )
    return {
        "position": position,
        "preflop_context_id": pfc_id,
        "repository_sha256": repository_sha,
        "binding_sha256": binding_sha,
        "supported": completed,
        "unsupported": unsupported_count,
        "parity_checked_hands": parity,
        "context_key": next(iter(contexts)),
        "context_node": node,
    }


def validate(evidence_dir: Path, btn_source: Path = DEFAULT_BTN) -> dict[str, Any]:
    evidence_dir = Path(evidence_dir)
    btn_source = Path(btn_source)
    final_repo_path = evidence_dir / "HERO_RANGE_REPOSITORY_PFPC.json"
    final_binding_path = evidence_dir / "POLICY_CONTEXT_BINDING.json"
    result_path = evidence_dir / "RESULT.json"
    source_record_path = evidence_dir / "SOURCE_RUN.json"
    for path in (final_repo_path, final_binding_path, result_path, source_record_path):
        _need(path.is_file(), f"missing persisted evidence file: {path.name}")

    repository = load(final_repo_path)
    binding = load(final_binding_path)
    result = load(result_path)
    source_record = load(source_record_path)
    _need(repository.get("schema") == REPOSITORY_SCHEMA, "final repository schema mismatch")
    _need(binding.get("schema") == PFPC_BINDING_SCHEMA, "final PFPC binding schema mismatch")
    _need(result.get("schema") == MERGE_RESULT_SCHEMA, "final merge result schema mismatch")
    _need(source_record.get("schema") == PERSISTENCE_SCHEMA, "source persistence schema mismatch")
    _need(result.get("issue") == 107 and source_record.get("issue") == 107, "wrong issue provenance")

    population = str(result.get("population_id") or "")
    _need(population == "pokerstars_nlhe_100-200_zoom_play_6max_v1", "unexpected target population")
    run_id = str(result.get("run_id") or "")
    _need(run_id and str(binding.get("run_id") or "") == run_id, "run id mismatch")
    _need(str(source_record.get("run_id") or "") == run_id, "source record run id mismatch")
    _need(result.get("policy_contexts") == 5, "final PFPC count != 5")
    _need(result.get("repository_contexts") == 5, "final repository context count != 5")
    _need(len(repository.get("contexts") or {}) == 5, "final repository does not contain 5 contexts")
    _need(len(binding.get("bindings") or {}) == 5, "final policy binding does not contain 5 PFPC bindings")
    _need(binding.get("matching") == "EXACT_PFPC_AND_169_HAND_CLASS_ONLY", "PFPC matching contract drift")
    _need(binding.get("nearest_context_substitution") is False, "final binding enables nearest-context substitution")
    _need(binding.get("promotion_authorized") is False and result.get("promotion_authorized") is False, "candidate self-promotes")
    boundary = dict(binding.get("selection_boundary") or {})
    _need(boundary.get("validation_consumed") is False, "final candidate already consumed VALIDATION")
    _need(boundary.get("test_consumed") is False, "final candidate already consumed TEST")
    _need(result.get("validation_consumed") is False, "merge result consumed VALIDATION")
    _need(result.get("test_consumed") is False, "merge result consumed TEST")

    final_repo_sha = sha256(final_repo_path)
    final_binding_sha = sha256(final_binding_path)
    _need(str(result.get("repository_sha256") or "") == final_repo_sha, "final repository SHA/result mismatch")
    _need(str(binding.get("repository_sha256") or "") == final_repo_sha, "final repository SHA/binding mismatch")
    artifacts = dict(source_record.get("artifact_sha256") or {})
    _need(artifacts.get("HERO_RANGE_REPOSITORY_PFPC.json") == final_repo_sha, "source record final repository SHA mismatch")
    _need(artifacts.get("POLICY_CONTEXT_BINDING.json") == final_binding_sha, "source record final binding SHA mismatch")
    _need(artifacts.get("RESULT.json") == sha256(result_path), "source record result SHA mismatch")
    _need(source_record.get("promotion_authorized") is False, "persistence record self-promotes")
    _need(source_record.get("validation_consumed") is False, "persistence record consumed VALIDATION")
    _need(source_record.get("test_consumed") is False, "persistence record consumed TEST")

    final_sources = {str(row.get("actor_position") or ""): dict(row) for row in result.get("sources") or []}
    _need(set(final_sources) == set(POSITIONS), "final source positions mismatch")

    validated_sources: dict[str, dict[str, Any]] = {}
    for position in NEW_POSITIONS:
        validated_sources[position] = _validate_source(
            evidence_dir / "sources" / position,
            position=position,
            expected_population=population,
        )

    btn_repo_path = btn_source / "HERO_RANGE_REPOSITORY_PFC.json"
    btn_binding_path = btn_source / "PFC_BINDING.json"
    _need(btn_repo_path.is_file() and btn_binding_path.is_file(), "immutable BTN source missing")
    btn_repo = load(btn_repo_path)
    btn_binding = load(btn_binding_path)
    _need(btn_repo.get("schema") == REPOSITORY_SCHEMA, "BTN repository schema mismatch")
    _need(btn_binding.get("schema") == PFC_BINDING_SCHEMA, "BTN binding schema mismatch")
    btn_contexts = dict(btn_repo.get("contexts") or {})
    _need(len(btn_contexts) == 1, "BTN source repository must contain one context")
    btn_cov = dict(btn_binding.get("coverage") or {})
    validated_sources["BTN"] = {
        "position": "BTN",
        "preflop_context_id": str(btn_binding.get("preflop_context_id") or ""),
        "repository_sha256": sha256(btn_repo_path),
        "binding_sha256": sha256(btn_binding_path),
        "supported": int(btn_cov.get("supported") or 0),
        "unsupported": int(btn_cov.get("unsupported") or 0),
        "parity_checked_hands": 0,
        "context_key": next(iter(btn_contexts)),
        "context_node": next(iter(btn_contexts.values())),
    }

    final_contexts = dict(repository.get("contexts") or {})
    binding_rows = dict(binding.get("bindings") or {})
    supported_total = 0
    unsupported_total = 0
    for position in POSITIONS:
        source = validated_sources[position]
        summary = final_sources[position]
        _need(summary.get("repository_sha256") == source["repository_sha256"], f"{position}: final source repository SHA drift")
        _need(summary.get("binding_sha256") == source["binding_sha256"], f"{position}: final source binding SHA drift")
        _need(summary.get("preflop_context_id") == source["preflop_context_id"], f"{position}: final source PFC drift")
        _need(int(summary.get("supported_hand_classes") or 0) == source["supported"], f"{position}: final supported count drift")
        _need(int(summary.get("unsupported_hand_classes") or 0) == source["unsupported"], f"{position}: final unsupported count drift")
        _need(final_contexts.get(source["context_key"]) == source["context_node"], f"{position}: merged repository context drift")

        pfpc_id = str(summary.get("policy_context_id") or "")
        _need(pfpc_id in binding_rows, f"{position}: missing final PFPC binding")
        row = dict(binding_rows[pfpc_id])
        _need(row.get("preflop_context_id") == source["preflop_context_id"], f"{position}: PFPC/PFC link drift")
        _need(row.get("source_repository_sha256") == source["repository_sha256"], f"{position}: PFPC repository SHA drift")
        _need(row.get("source_binding_sha256") == source["binding_sha256"], f"{position}: PFPC source binding SHA drift")
        _need(int(row.get("supported_hand_classes") or 0) == source["supported"], f"{position}: PFPC supported count drift")
        supported_total += source["supported"]
        unsupported_total += source["unsupported"]

    _need(int(result.get("supported_hand_slots") or 0) == supported_total, "final supported slot total drift")
    _need(int(result.get("unsupported_hand_slots") or 0) == unsupported_total, "final unsupported slot total drift")
    _need(all(validated_sources[p]["supported"] > 0 for p in NEW_POSITIONS), "new position has zero supported classes")

    return {
        "schema": "poker-hero-pfpc-evidence-validation/v1",
        "status": "PASS",
        "issue": 107,
        "run_id": run_id,
        "population_id": population,
        "repository_sha256": final_repo_sha,
        "binding_sha256": final_binding_sha,
        "positions": {
            position: {
                "supported": validated_sources[position]["supported"],
                "unsupported": validated_sources[position]["unsupported"],
                "parity_checked_hands": validated_sources[position]["parity_checked_hands"],
            }
            for position in POSITIONS
        },
        "supported_hand_slots": supported_total,
        "unsupported_hand_slots": unsupported_total,
        "new_position_parity_checked_hands": sum(
            validated_sources[position]["parity_checked_hands"] for position in NEW_POSITIONS
        ),
        "validation_consumed": False,
        "test_consumed": False,
        "promotion_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--btn-source", type=Path, default=DEFAULT_BTN)
    args = parser.parse_args()
    try:
        result = validate(args.evidence, args.btn_source)
    except Exception as exc:
        result = {
            "schema": "poker-hero-pfpc-evidence-validation/v1",
            "status": "FAIL",
            "errors": [str(exc)],
        }
        print(json.dumps(result, indent=2, sort_keys=True))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

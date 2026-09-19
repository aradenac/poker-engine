#!/usr/bin/env python3
"""Parity harness for canonical #321 public preflop contexts vs #313/#315 extractors."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from tools.preflop.context_contract import build_context
from tools.preflop.model_a_sizing_likelihood import (
    PUBLIC_CONTEXT_SCHEMA as MODEL_A_PUBLIC_SCHEMA,
    public_sizing_context,
)
from tools.repro_preflop_fixture import (
    ROOT,
    canonical_sha256,
    load_verified_reference,
)
from tools.simulation.model_b_preflop_response_to_price import (
    public_context as model_b_public_context,
)

REPORT_SCHEMA = "poker-engine-kts-model-a-b-public-parity/v1"
REPORT_PATH = ROOT / "analysis/repro/kts_sb_iso_model_a_b_parity.json"
MODEL_B_PROFILE_SENTINEL = "CANONICAL_FIXTURE_PROFILE_UNSPECIFIED"

DECISIONS = (
    {
        "snapshot_id": "before_bb_call",
        "action_id": "bb_call_iso",
        "actor": "BB",
        "expected": {
            "pot_before_bb": 7.0,
            "price_to_pot": 0.428571429,
            "pot_odds": 0.3,
            "caller_count": 0,
            "model_a_family": "VS_ISO",
            "model_b_price_bucket": "P25_50",
            "sequence": "CO_LIMP>BTN_LIMP>SB_ISO",
        },
    },
    {
        "snapshot_id": "before_co_call",
        "action_id": "co_call_iso",
        "actor": "CO",
        "expected": {
            "pot_before_bb": 10.0,
            "price_to_pot": 0.3,
            "pot_odds": 0.230769231,
            "caller_count": 1,
            "model_a_family": "LIMPER_VS_ISO_CALLERS",
            "model_b_price_bucket": "P25_50",
            "sequence": "CO_LIMP>BTN_LIMP>SB_ISO>BB_CALL",
        },
    },
    {
        "snapshot_id": "before_btn_call",
        "action_id": "btn_call_iso",
        "actor": "BTN",
        "expected": {
            "pot_before_bb": 13.0,
            "price_to_pot": 0.230769231,
            "pot_odds": 0.1875,
            "caller_count": 2,
            "model_a_family": "LIMPER_VS_ISO_CALLERS",
            "model_b_price_bucket": "P00_25",
            "sequence": "CO_LIMP>BTN_LIMP>SB_ISO>BB_CALL>CO_CALL",
        },
    },
)


class ParityError(ValueError):
    pass


def _player_position_map(fixture: Mapping[str, Any]) -> dict[str, str]:
    scenario = fixture["scenario"]
    mapping = {str(k): str(v) for k, v in scenario["positions"].items()}
    if mapping.get("Hero") != "SB":
        raise ParityError("canonical Hero position must remain SB")
    return mapping


def _history_before(
    fixture: Mapping[str, Any],
    *,
    action_id: str,
    positions: Mapping[str, str],
) -> list[dict[str, str]]:
    history: list[dict[str, str]] = []
    raised = False
    for action in fixture["scenario"]["actions"]:
        if action["id"] == action_id:
            break
        raw = str(action["action"]).upper()
        if raw == "FOLD":
            continue
        player = str(action["player"])
        position = positions[player]
        if raw == "RAISE":
            normalized = "RAISE"
            raised = True
        elif raw == "CALL":
            normalized = "CALL" if raised else "LIMP"
        else:
            normalized = raw
        history.append({"position": position, "action": normalized})
    else:
        raise ParityError(f"unknown canonical action id: {action_id}")
    return history


def _model_b_sequence(history: list[dict[str, str]], *, raiser_position: str) -> str:
    tokens: list[str] = []
    for item in history:
        position = item["position"]
        action = item["action"]
        if position == raiser_position and action == "RAISE":
            action = "ISO"
        tokens.append(f"{position}_{action}")
    return ">".join(tokens)


def _snapshot_by_id(fixture: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(row["id"]): row for row in fixture["snapshots"]}


def _public_pfc(
    fixture: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    *,
    action_id: str,
    positions: Mapping[str, str],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    state = snapshot["state"]
    legal = snapshot["legal"]
    actor_player = str(legal["actor"])
    history = _history_before(fixture, action_id=action_id, positions=positions)

    live_positions = [
        positions[player]
        for player in state["seats"]
        if not state["folded"][player]
    ]
    all_in_positions = [
        positions[player]
        for player in state["seats"]
        if state["all_in"][player] and not state["folded"][player]
    ]
    contributions = {
        positions[player]: float(state["street_committed_bb"][player])
        for player in state["seats"]
    }
    starting_stacks = {
        positions[player]: float(state["starting_stacks_bb"][player])
        for player in state["seats"]
    }
    pending = [positions[player] for player in legal["remaining_to_act"]]

    context = build_context(
        table_size=len(state["seats"]),
        actor_position=positions[actor_player],
        live_positions=live_positions,
        all_in_positions=all_in_positions,
        history=history,
        contribution_bb_by_position=contributions,
        stack_bb_by_position=starting_stacks,
        pot_before_bb=float(legal["pot_before_bb"]),
        current_price_bb=float(legal["current_price_bb"]),
        pending_positions=pending,
        min_raise_to_bb=legal["min_raise_to_bb"],
        raise_reopened=bool(legal["raise_reopened"]),
    )
    return context, history


def _adapter_has_private_or_future(value: Any) -> bool:
    forbidden = ("hole", "cards", "board", "showdown", "future", "known_cards")
    if isinstance(value, Mapping):
        for key, child in value.items():
            lowered = str(key).lower()
            if any(token in lowered for token in forbidden):
                return True
            if _adapter_has_private_or_future(child):
                return True
    elif isinstance(value, list):
        return any(_adapter_has_private_or_future(child) for child in value)
    return False


def _legacy_fixture_audit(root: Path) -> dict[str, Any]:
    model_a_path = root / "tests/fixtures/model_a_preflop_sizing_cases.json"
    model_b_path = root / "tests/fixtures/model_b_preflop_response_to_price/scenario_4bb_vs_6bb.json"
    model_a = json.loads(model_a_path.read_text(encoding="utf-8"))
    model_b = json.loads(model_b_path.read_text(encoding="utf-8"))

    model_a_four = model_a["contexts"][0]
    legacy_a_limpers = [
        item["position"]
        for item in model_a_four["input"]["history"]
        if item["action"] == "LIMP"
    ]
    low_b = next(v for v in model_b["variants"] if v["variant_id"] == "4BB")
    legacy_b_prices = {
        row["responder_position"]: row["facing_price_to_pot"]
        for row in low_b["responders"]
    }
    return {
        "status": "DOCUMENTED_NOT_PARITY_SOURCE",
        "model_a_scaffold_fixture": {
            "path": str(model_a_path.relative_to(root)),
            "legacy_limper_positions": legacy_a_limpers,
            "canonical_limper_positions": ["CO", "BTN"],
            "difference": "LEGACY_SYNTHETIC_SEATS_DIFFER_FROM_CANONICAL_321",
        },
        "model_b_scaffold_fixture": {
            "path": str(model_b_path.relative_to(root)),
            "legacy_4bb_facing_price_to_pot": legacy_b_prices,
            "canonical_4bb_facing_price_to_pot": {
                "BB": 0.428571429,
                "CO": 0.3,
                "BTN": 0.230769231,
            },
            "difference": "LEGACY_SYNTHETIC_PRICE_INPUTS_DIFFER_FROM_CANONICAL_321",
        },
        "used_to_build_parity_rows": False,
    }


def build_parity_report(root: Path = ROOT) -> dict[str, Any]:
    fixture = load_verified_reference(root)
    positions = _player_position_map(fixture)
    snapshots = _snapshot_by_id(fixture)
    violations: list[str] = []
    rows: list[dict[str, Any]] = []

    for spec in DECISIONS:
        snapshot = snapshots[spec["snapshot_id"]]
        legal = snapshot["legal"]
        pricing = snapshot["pricing"]
        expected = spec["expected"]

        pfc, history = _public_pfc(
            fixture,
            snapshot,
            action_id=spec["action_id"],
            positions=positions,
        )
        model_a = public_sizing_context(pfc)

        model_b_input = {
            "profile": MODEL_B_PROFILE_SENTINEL,
            "family": "ISO_OVER_LIMPERS",
            "responder_position": pfc["actor_position"],
            "raiser_position": positions["Hero"],
            "sequence": _model_b_sequence(history, raiser_position=positions["Hero"]),
            "limper_count": model_a["limper_count"],
            "hero_raise_size_bb": model_a["target_total_bb"],
            "facing_price_to_pot": model_a["price_to_pot_ratio"],
            "effective_stack_bb": model_a["effective_stack_bb"],
        }
        model_b = model_b_public_context(model_b_input)

        checks = {
            "actor_position": pfc["actor_position"] == spec["actor"],
            "target_total_bb": (
                model_a["target_total_bb"] == 4.0
                and model_a["target_total_bb"] == float(legal["current_price_bb"])
            ),
            "to_call_bb": (
                model_a["to_call_bb"] == 3.0
                and model_a["to_call_bb"] == float(pricing["to_call_bb"])
            ),
            "pot_before_bb": (
                model_a["pot_before_bb"] == expected["pot_before_bb"]
                and model_a["pot_before_bb"] == float(legal["pot_before_bb"])
            ),
            "price_to_pot": (
                model_a["price_to_pot_ratio"] == expected["price_to_pot"]
                and model_a["price_to_pot_ratio"] == float(pricing["price_to_pot"])
            ),
            "pot_odds": model_a["pot_odds"] == expected["pot_odds"],
            "limper_count": model_a["limper_count"] == 2,
            "caller_count": model_a["caller_count"] == expected["caller_count"],
            "effective_stack_bb": model_a["effective_stack_bb"] == 100.0,
            "model_a_family": model_a["family"] == expected["model_a_family"],
            "sequence": model_b_input["sequence"] == expected["sequence"],
            "model_b_exact_input_from_model_a": (
                model_b_input["hero_raise_size_bb"] == model_a["target_total_bb"]
                and model_b_input["facing_price_to_pot"] == model_a["price_to_pot_ratio"]
                and model_b_input["effective_stack_bb"] == model_a["effective_stack_bb"]
                and model_b_input["limper_count"] == model_a["limper_count"]
            ),
            "model_b_family_mapping": model_b["family"] == "ISO_OVER_LIMPERS",
            "model_b_raise_size_bucket": model_b["raise_size_bucket"] == "S3_4P5",
            "model_b_price_bucket": model_b["price_bucket"] == expected["model_b_price_bucket"],
            "model_b_effective_stack_bucket": model_b["effective_stack_bucket"] == "E80_150",
            "model_b_limper_bucket": model_b["limper_count_bucket"] == "L2",
            "preflop_board_not_consumed": snapshot["state"]["board"] == [],
            "model_a_information_boundary": (
                model_a["information_boundary"]["public_only"] is True
                and model_a["information_boundary"]["future_cards_consumed"] is False
                and model_a["information_boundary"]["opponent_hole_cards_consumed"] is False
            ),
            "adapter_inputs_public_only": (
                not _adapter_has_private_or_future(pfc)
                and not _adapter_has_private_or_future(model_b_input)
            ),
        }

        failed = sorted(name for name, ok in checks.items() if not ok)
        if failed:
            violations.append(f"{spec['actor']}:{','.join(failed)}")

        rows.append({
            "snapshot_id": spec["snapshot_id"],
            "actor": spec["actor"],
            "canonical_public": {
                "target_total_bb": float(legal["current_price_bb"]),
                "to_call_bb": float(pricing["to_call_bb"]),
                "pot_before_bb": float(legal["pot_before_bb"]),
                "price_to_pot": float(pricing["price_to_pot"]),
                "sequence": model_b_input["sequence"],
                "limper_positions": list(model_a.get("limper_positions") or pfc["limper_positions"]),
                "caller_positions": list(pfc["caller_positions"]),
                "effective_stack_bb": float(model_a["effective_stack_bb"]),
            },
            "model_a": {
                "schema": model_a["schema"],
                "actor_position": model_a["actor_position"],
                "family": model_a["family"],
                "target_total_bb": model_a["target_total_bb"],
                "to_call_bb": model_a["to_call_bb"],
                "pot_before_bb": model_a["pot_before_bb"],
                "price_to_pot_ratio": model_a["price_to_pot_ratio"],
                "pot_odds": model_a["pot_odds"],
                "effective_stack_bb": model_a["effective_stack_bb"],
                "limper_count": model_a["limper_count"],
                "caller_count": model_a["caller_count"],
                "information_boundary": model_a["information_boundary"],
            },
            "model_b_input": model_b_input,
            "model_b": model_b,
            "checks": checks,
            "status": "PASS" if not failed else "FAIL",
        })

    legacy = _legacy_fixture_audit(root)
    report = {
        "schema": REPORT_SCHEMA,
        "status": "PASS" if not violations else "FAIL",
        "issue": 333,
        "source_fixture": {
            "issue": 321,
            "scenario_id": fixture["scenario_id"],
            "schema": fixture["schema"],
            "public_timeline_sha256": fixture["public_timeline_sha256"],
            "used_directly": True,
            "new_kts_fixture_created": False,
        },
        "extractors": {
            "model_a": {
                "issue": 313,
                "callable": "tools.preflop.model_a_sizing_likelihood.public_sizing_context",
                "schema": MODEL_A_PUBLIC_SCHEMA,
            },
            "model_b": {
                "issue": 315,
                "callable": "tools.simulation.model_b_preflop_response_to_price.public_context",
                "representation": "BUCKETED_PUBLIC_CONTEXT",
            },
            "shared_public_adapter": "tools.preflop.context_contract.build_context",
        },
        "decisions": rows,
        "representation_differences": {
            "family": {
                "model_a": "actor-relative PFC family (VS_ISO / LIMPER_VS_ISO_CALLERS)",
                "model_b": "scenario response family ISO_OVER_LIMPERS",
                "compatibility": "COMPATIBLE_SAME_CANONICAL_ISO_OVER_TWO_LIMPERS",
            },
            "price": {
                "model_a": "exact price_to_pot_ratio",
                "model_b": "price_bucket derived from the exact Model-A/public ratio",
                "compatibility": "COMPATIBLE_BUCKETED_REPRESENTATION",
            },
            "profile": {
                "canonical_321": "NOT_DEFINED",
                "model_b_adapter": MODEL_B_PROFILE_SENTINEL,
                "parity_assertion": False,
            },
        },
        "legacy_scaffold_fixture_audit": legacy,
        "violations": violations,
    }
    report["report_sha256"] = canonical_sha256({
        key: value for key, value in report.items() if key != "report_sha256"
    })
    return report


def verify_persisted_report(root: Path = ROOT) -> list[str]:
    expected = build_parity_report(root)
    path = root / REPORT_PATH.relative_to(ROOT)
    if not path.is_file():
        return [f"missing parity report: {path}"]
    actual = json.loads(path.read_text(encoding="utf-8"))
    violations: list[str] = []
    if expected["status"] != "PASS":
        violations.extend(expected["violations"] or ["generated parity report failed"])
    if actual != expected:
        violations.append("persisted parity report differs from canonical regeneration")
    return violations


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    report = build_parity_report(ROOT)
    if args.write:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.check:
        violations = verify_persisted_report(ROOT)
        print(json.dumps({
            "schema": "poker-engine-kts-model-a-b-public-parity-verification/v1",
            "status": "FAIL" if violations else "PASS",
            "violations": violations,
            "report_sha256": report["report_sha256"],
        }, indent=2, sort_keys=True))
        return 2 if violations else 0
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())

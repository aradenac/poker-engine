#!/usr/bin/env python3
"""Canonical reproducible preflop reference fixture for issue #321."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from tools.simulation.game_core import NoLimitHoldemState
from tools.simulation.hand_history_state import replay_public_hand

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests/fixtures/repro/kts_sb_two_limp_iso4_three_calls.snapshots.json"
PUBLIC_SNAPSHOT_SCHEMA = "poker-engine-preflop-public-snapshot/v1"
FIXTURE_SCHEMA = "poker-engine-kts-sb-iso-reference/v1"


class ReferenceFixtureError(ValueError):
    pass


def _normalize(value: Any) -> Any:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return round(float(value), 9)
    if isinstance(value, list):
        return [_normalize(x) for x in value]
    if isinstance(value, dict):
        return {str(k): _normalize(v) for k, v in value.items()}
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        _normalize(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_reference_fixture(root: Path = ROOT) -> dict[str, Any]:
    path = root / FIXTURE_PATH.relative_to(ROOT)
    if not path.is_file():
        raise ReferenceFixtureError(f"missing reference fixture: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema") != FIXTURE_SCHEMA:
        raise ReferenceFixtureError("unexpected reference fixture schema")
    return value


def load_hand_history(fixture: dict[str, Any], root: Path = ROOT) -> str:
    rel = fixture.get("hand_history_file")
    if not isinstance(rel, str) or not rel:
        raise ReferenceFixtureError("fixture missing hand_history_file")
    path = root / rel
    if not path.is_file():
        raise ReferenceFixtureError(f"missing hand history fixture: {path}")
    return path.read_text(encoding="utf-8")


def _pricing(legal: dict[str, Any] | None) -> dict[str, Any] | None:
    if legal is None:
        return None
    pot = float(legal["pot_before_bb"])
    to_call = float(legal["to_call_bb"])
    return {
        "to_call_bb": round(to_call, 9),
        "call_target_total_bb": round(
            float(legal["actor_street_contribution_bb"]) + to_call,
            9,
        ),
        "price_to_pot": None if pot == 0 else round(to_call / pot, 9),
    }


def _public_snapshot(state: NoLimitHoldemState, snapshot_id: str) -> dict[str, Any]:
    legal = state.legal_view() if state.next_actor is not None else None
    payload = {
        "schema": PUBLIC_SNAPSHOT_SCHEMA,
        "state": state.to_snapshot(include_log=False),
        "legal": legal,
        "pricing": _pricing(legal),
    }
    return {
        "id": snapshot_id,
        **payload,
        "public_fingerprint_sha256": canonical_sha256(payload),
    }


def reconstruct_reference(
    fixture: dict[str, Any] | None = None,
    root: Path = ROOT,
) -> dict[str, Any]:
    fixture = fixture or load_reference_fixture(root)
    scenario = fixture.get("scenario")
    if not isinstance(scenario, dict):
        raise ReferenceFixtureError("fixture missing scenario")

    seats = scenario["seats"]
    state = NoLimitHoldemState(
        seats=seats,
        button=scenario["button"],
        stacks_bb=scenario["starting_stacks_bb"],
        small_blind_bb=scenario["blinds_bb"]["small"],
        big_blind_bb=scenario["blinds_bb"]["big"],
    )

    points = scenario.get("snapshot_points")
    if not isinstance(points, list) or not points:
        raise ReferenceFixtureError("fixture missing snapshot_points")
    before: dict[str, list[str]] = {}
    after: dict[str, list[str]] = {}
    flop_ids: list[str] = []
    for point in points:
        if not isinstance(point, dict) or not isinstance(point.get("id"), str):
            raise ReferenceFixtureError("invalid snapshot point")
        if "before_action" in point:
            before.setdefault(str(point["before_action"]), []).append(point["id"])
        elif "after_action" in point:
            after.setdefault(str(point["after_action"]), []).append(point["id"])
        elif point.get("after_flop") is True:
            flop_ids.append(point["id"])
        else:
            raise ReferenceFixtureError(f"snapshot point has no anchor: {point}")

    snapshots: list[dict[str, Any]] = []
    action_trace: list[dict[str, Any]] = []
    for action in scenario.get("actions", []):
        action_id = str(action["id"])
        player = str(action["player"])
        kind = str(action["action"]).upper()

        for snapshot_id in before.get(action_id, []):
            snapshots.append(_public_snapshot(state, snapshot_id))

        state_before = state.to_snapshot(include_log=False)
        legal_before = state.legal_view(player)
        target = action.get("target_total_bb")
        if kind == "RAISE":
            if target is None:
                raise ReferenceFixtureError(f"raise missing target_total_bb: {action_id}")
            state.apply_action(player, kind, target_total_bb=float(target))
        else:
            if target is not None:
                raise ReferenceFixtureError(f"non-raise has target_total_bb: {action_id}")
            state.apply_action(player, kind)

        action_trace.append({
            "id": action_id,
            "player": player,
            "action": kind.lower(),
            "target_total_bb": None if target is None else float(target),
            "state_before": state_before,
            "legal_before": legal_before,
        })
        for snapshot_id in after.get(action_id, []):
            snapshots.append(_public_snapshot(state, snapshot_id))

    if not state.betting_complete:
        raise ReferenceFixtureError("preflop action is not complete")
    state.advance_street(scenario["flop_cards"])
    for snapshot_id in flop_ids:
        snapshots.append(_public_snapshot(state, snapshot_id))

    expected_order = [str(x["id"]) for x in points]
    actual_order = [x["id"] for x in snapshots]
    if actual_order != expected_order:
        raise ReferenceFixtureError(
            f"snapshot order mismatch: expected {expected_order}, got {actual_order}"
        )

    return {
        "snapshots": snapshots,
        "action_trace": action_trace,
        "flop_state": state.to_snapshot(include_log=False),
        "public_timeline_sha256": canonical_sha256(
            [x["public_fingerprint_sha256"] for x in snapshots]
        ),
    }


def _forbidden_result_keys(value: Any) -> list[str]:
    forbidden = {
        "ev",
        "equity",
        "range",
        "ranges",
        "recommendation",
        "recommended_action",
        "strategy",
        "model",
        "model_output",
    }
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in forbidden:
                found.append(str(key))
            found.extend(_forbidden_result_keys(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_forbidden_result_keys(child))
    return found


def verify_reference(root: Path = ROOT) -> list[str]:
    fixture = load_reference_fixture(root)
    violations: list[str] = []

    scenario = fixture.get("scenario", {})
    hero = scenario.get("hero", {}) if isinstance(scenario, dict) else {}
    if hero != {"player": "Hero", "position": "SB", "hand_class": "KTs"}:
        violations.append("hero identity must be exactly KTs in SB")
    if scenario.get("format") != "6-max":
        violations.append("scenario must be 6-max")
    if scenario.get("positions", {}).get("CO") != "CO":
        violations.append("CO position mapping missing")
    if scenario.get("positions", {}).get("BTN") != "BTN":
        violations.append("BTN position mapping missing")

    forbidden = sorted(set(_forbidden_result_keys(fixture)))
    if forbidden:
        violations.append(f"fixture contains forbidden result keys: {forbidden}")

    rebuilt = reconstruct_reference(fixture, root)
    stored = fixture.get("snapshots")
    if stored != rebuilt["snapshots"]:
        violations.append("stored canonical snapshots differ from game-core reconstruction")
    if fixture.get("public_timeline_sha256") != rebuilt["public_timeline_sha256"]:
        violations.append("public timeline fingerprint mismatch")

    if isinstance(stored, list):
        for row in stored:
            payload = {
                "schema": row.get("schema"),
                "state": row.get("state"),
                "legal": row.get("legal"),
                "pricing": row.get("pricing"),
            }
            if row.get("public_fingerprint_sha256") != canonical_sha256(payload):
                violations.append(f"snapshot fingerprint mismatch: {row.get('id')}")

    raw = load_hand_history(fixture, root)
    dealt = re.findall(r"(?im)^Dealt to\s+(.+?)\s+\[", raw)
    if dealt != ["Hero"]:
        violations.append("hand history must expose hole cards for Hero only")

    replay = replay_public_hand(raw)
    direct = rebuilt["action_trace"]
    if len(replay["trace"]) != len(direct):
        violations.append("hand-history action count differs from direct reconstruction")
    else:
        for left, right in zip(replay["trace"], direct):
            if left["player"] != right["player"] or left["action"] != right["action"]:
                violations.append(f"hand-history action mismatch at {right['id']}")
                continue
            if left["state_before"] != right["state_before"]:
                violations.append(f"hand-history state mismatch at {right['id']}")
            if left["legal_before"] != right["legal_before"]:
                violations.append(f"hand-history legal view mismatch at {right['id']}")
    if replay["final_state"] != rebuilt["flop_state"]:
        violations.append("hand-history final flop state differs from direct reconstruction")

    for row in rebuilt["snapshots"]:
        state = row["state"]
        if state["street"] == "preflop" and state["board"]:
            violations.append(f"future board leaked into preflop snapshot {row['id']}")
        serialized = json.dumps(state, sort_keys=True).lower()
        if "hole" in serialized or "hero_cards" in serialized or "opponent_cards" in serialized:
            violations.append(f"private-card field leaked into public snapshot {row['id']}")

    return violations


def load_verified_reference(root: Path = ROOT) -> dict[str, Any]:
    violations = verify_reference(root)
    if violations:
        raise ReferenceFixtureError("; ".join(violations))
    fixture = copy.deepcopy(load_reference_fixture(root))
    fixture["reconstructed"] = reconstruct_reference(fixture, root)
    return fixture


def main() -> int:
    violations = verify_reference(ROOT)
    report = {
        "schema": "poker-engine-kts-sb-iso-reference-verification/v1",
        "status": "FAIL" if violations else "PASS",
        "scenario_id": load_reference_fixture(ROOT)["scenario_id"],
        "violations": violations,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 2 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())

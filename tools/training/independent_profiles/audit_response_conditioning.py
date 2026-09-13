#!/usr/bin/env python3
"""Audit promoted Model B response realism across omitted strategic variables.

The promoted v2 response model conditions on profile/street/mode/position/pot type/
preflop role, but not facing price, SPR, board texture or hand strength. This audit
measures held-out response shifts along those omitted dimensions while holding the
v2 base context fixed whenever sample support permits.

No Model A output is consumed. VALIDATION and TEST are reported separately; TEST is
not used to select a representation here.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import re
from pathlib import Path

from tools.datasets.build_hand_history_increment import split_for
from tools.simulation.model_b_runtime import best
from tools.training.independent_profiles.build_player_features import merge_archives
from tools.training.independent_profiles.build_model_b import (
    apply_event, numeric_tokens, parse_hand, preflop_summary, relative_position,
)
from tools.training.independent_profiles.evaluate_model_b import action_probabilities, choose_node, load

SCHEMA = "independent-model-b-response-conditioning-audit/v1"
CARD_RE = re.compile(r"(?<![A-Za-z0-9])([2-9TJQKA][shdc])(?![A-Za-z0-9])", re.I)


def board_by_street(text: str) -> dict[str, list[str]]:
    out = {"flop": [], "turn": [], "river": []}
    for raw in text.replace("\r", "").splitlines():
        line = raw.strip()
        street = None
        if line.startswith("*** FLOP ***"):
            street = "flop"
        elif line.startswith(("*** TURN ***", "*** TOURNANT ***")):
            street = "turn"
        elif line.startswith(("*** RIVER ***", "*** RIVIÈRE ***", "*** RIVIERE ***")):
            street = "river"
        if street:
            cards = [c[0].upper() + c[1].lower() for c in CARD_RE.findall(line)]
            expected = {"flop": 3, "turn": 4, "river": 5}[street]
            if len(cards) >= expected:
                out[street] = cards[-expected:]
    return out


def starting_stacks(text: str, players: set[str]) -> dict[str, float]:
    stacks: dict[str, float] = {}
    for raw in text.replace("\r", "").splitlines():
        if raw.startswith("***"):
            break
        line = raw.strip()
        for player in players:
            marker = f": {player} ("
            if marker not in line:
                continue
            m = re.search(r"\(([^)]*)\)", line)
            nums = numeric_tokens(m.group(1)) if m else []
            if nums and nums[0] > 0:
                stacks[player] = float(nums[0])
            break
    return stacks


def price_bucket(x: float | None) -> str:
    if x is None or not math.isfinite(x): return "UNKNOWN"
    if x <= 0.25: return "P00_25"
    if x <= 0.50: return "P25_50"
    if x <= 0.75: return "P50_75"
    if x <= 1.00: return "P75_100"
    if x <= 1.50: return "P100_150"
    return "P150_PLUS"


def spr_bucket(x: float | None) -> str:
    if x is None or not math.isfinite(x) or x < 0: return "UNKNOWN"
    if x < 1.0: return "SPR_LT1"
    if x < 3.0: return "SPR_1_3"
    if x < 6.0: return "SPR_3_6"
    if x < 12.0: return "SPR_6_12"
    return "SPR_12_PLUS"


def board_texture(board: list[str]) -> str:
    if len(board) < 3:
        return "UNKNOWN"
    ranks = [c[0].upper() for c in board]
    suits = collections.Counter(c[1].lower() for c in board)
    paired = "PAIRED" if len(set(ranks)) < len(ranks) else "UNPAIRED"
    max_suit = max(suits.values())
    suit = "RAINBOW" if max_suit == 1 else "TWO_SUIT" if max_suit == 2 else f"{max_suit}_FLUSH"
    return f"{paired}_{suit}"


def strength_bucket(cards: list[str] | None, board: list[str]) -> str:
    if not cards or len(cards) != 2 or len(board) < 3:
        return "UNKNOWN"
    try:
        category = int(best(cards + board)[0])
    except Exception:
        return "UNKNOWN"
    if category == 0: return "HIGH_CARD"
    if category == 1: return "ONE_PAIR"
    if category == 2: return "TWO_PAIR"
    if category == 3: return "TRIPS"
    return "STRAIGHT_PLUS"


def target_success(mode: str, action: str) -> int:
    return int(action == ("FOLD" if mode == "FACING" else "BET"))


def target_probability(mode: str, probs: dict[str, float]) -> float:
    return float(probs.get("FOLD" if mode == "FACING" else "BET", 0.0))


def new_cell() -> dict:
    return {"n": 0, "success": 0, "predicted": 0.0, "loss": 0.0, "actions": collections.Counter()}


def add_cell(cell: dict, *, mode: str, action: str, probs: dict[str, float]) -> None:
    cell["n"] += 1
    cell["success"] += target_success(mode, action)
    cell["predicted"] += target_probability(mode, probs)
    cell["loss"] += -math.log(max(float(probs[action]), 1e-15))
    cell["actions"][action] += 1


def wilson(success: int, n: int, z: float = 1.96) -> list[float] | None:
    if n <= 0:
        return None
    p = success / n
    d = 1.0 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [max(0.0, c - h), min(1.0, c + h)]


def finish_cell(cell: dict) -> dict:
    n = cell["n"]
    return {
        "n": n,
        "observed_target_rate": cell["success"] / n if n else None,
        "observed_target_rate_ci95": wilson(cell["success"], n),
        "mean_model_target_probability": cell["predicted"] / n if n else None,
        "action_log_loss": cell["loss"] / n if n else None,
        "action_counts": dict(sorted(cell["actions"].items())),
        "action_frequency": {k: v / n for k, v in sorted(cell["actions"].items())} if n else {},
    }


def matched_context_sensitivity(context_cells: dict, *, min_bucket_n: int) -> dict:
    rows = []
    weighted_gap = 0.0
    weighted_n = 0
    for context, buckets in sorted(context_cells.items(), key=lambda x: str(x[0])):
        supported = [(b, c) for b, c in buckets.items() if c["n"] >= min_bucket_n]
        if len(supported) < 2:
            continue
        observed = [c["success"] / c["n"] for _, c in supported]
        predicted = [c["predicted"] / c["n"] for _, c in supported]
        gap = max(observed) - min(observed)
        pred_gap = max(predicted) - min(predicted)
        n = sum(c["n"] for _, c in supported)
        weighted_gap += gap * n
        weighted_n += n
        rows.append({
            "context": list(context),
            "supported_buckets": {b: finish_cell(c) for b, c in supported},
            "observed_target_rate_gap": gap,
            "model_target_probability_gap": pred_gap,
            "n": n,
        })
    rows.sort(key=lambda r: (-r["observed_target_rate_gap"], -r["n"], r["context"]))
    return {
        "min_observations_per_bucket": min_bucket_n,
        "contexts_with_two_or_more_supported_buckets": len(rows),
        "supported_observations": weighted_n,
        "weighted_mean_observed_target_rate_gap": weighted_gap / weighted_n if weighted_n else None,
        "max_observed_target_rate_gap": max((r["observed_target_rate_gap"] for r in rows), default=None),
        "max_model_target_probability_gap": max((r["model_target_probability_gap"] for r in rows), default=None),
        "largest_gaps": rows[:25],
    }


def audit_split(records, split_name: str, model_dir: Path, excluded: set[str], min_bucket_n: int) -> dict:
    profiles = load(model_dir / "profiles.json")
    actions = load(model_dir / "postflop_actions.json")
    contract = load(model_dir / "prediction_contract.json")
    player_profile = profiles["player_profile"]
    default_profile = int(max(profiles["profiles"], key=lambda p: p["appearance_weight"])["profile"])
    alpha = float(contract["postflop_action"]["alpha_per_action"])
    min_obs = int(actions["backoff_min_observations"])

    dims = ("price", "spr", "strength", "texture")
    dimensions = {name: collections.defaultdict(new_cell) for name in dims}
    matched = {name: collections.defaultdict(lambda: collections.defaultdict(new_cell)) for name in dims}
    reveal = {mode: {"all": new_cell(), "revealed": new_cell()} for mode in ("FREE", "FACING")}
    counters = collections.Counter()

    for record in records:
        if split_for(record.hand_id) != split_name:
            continue
        hand = parse_hand(record)
        if hand is None:
            counters["hands_unparsed"] += 1
            continue
        counters["hands_parsed"] += 1
        boards = board_by_street(record.text)
        stacks = starting_stacks(record.text, set(hand["players"]))
        counters["hands_with_all_starting_stacks"] += int(len(stacks) == len(hand["players"]))
        pot_type, roles, active, allin, _ = preflop_summary(hand)

        paid = collections.defaultdict(float)
        contributed = collections.defaultdict(float)
        price = 0.0
        pot = 0.0
        for event in hand["events"]["preflop"]:
            pot, price, added = apply_event(event, paid, pot, price)
            contributed[event["player"]] += added

        for street in ("flop", "turn", "river"):
            street_paid = collections.defaultdict(float)
            street_price = 0.0
            board = boards[street]
            for event in hand["events"][street]:
                actor = event["player"]
                typ = event["type"]
                if typ in {"return", "post"}:
                    pot, street_price, added = apply_event(event, street_paid, pot, street_price)
                    contributed[actor] += added
                    continue
                if typ not in {"fold", "check", "call", "bet", "raise"}:
                    continue
                to_call = max(0.0, street_price - street_paid[actor])
                mode = "FACING" if to_call > 1e-9 else "FREE"
                action = {"check":"CHECK","fold":"FOLD","call":"CALL","bet":"BET","raise":"RAISE"}[typ]
                valid = (mode == "FREE" and action in {"CHECK","BET"}) or (mode == "FACING" and action in {"FOLD","CALL","RAISE"})
                if actor not in excluded and valid:
                    profile = int(player_profile.get(actor, default_profile))
                    row = {
                        "profile": profile,
                        "street": street,
                        "mode": mode,
                        "relative_position": relative_position(hand, actor, active, allin),
                        "pot_type": pot_type,
                        "preflop_role": roles.get(actor, "OTHER"),
                    }
                    node, _level, _key = choose_node(actions["levels"], row, min_obs)
                    probs = action_probabilities(node, actions["labels"][mode], alpha)
                    base_context = (profile, street, mode, row["relative_position"], pot_type, row["preflop_role"])
                    p2p = to_call / pot if mode == "FACING" and pot > 0 else None
                    stack = stacks.get(actor)
                    remaining = max(0.0, stack - contributed[actor]) if stack is not None else None
                    spr = remaining / pot if remaining is not None and pot > 0 else None
                    revealed = actor in hand["known_cards"]
                    buckets = {
                        "price": price_bucket(p2p) if mode == "FACING" else "FREE",
                        "spr": spr_bucket(spr),
                        "strength": strength_bucket(hand["known_cards"].get(actor), board),
                        "texture": board_texture(board),
                    }
                    for dim, bucket in buckets.items():
                        add_cell(dimensions[dim][f"{mode}|{bucket}"], mode=mode, action=action, probs=probs)
                        if dim != "strength" or bucket != "UNKNOWN":
                            add_cell(matched[dim][base_context][bucket], mode=mode, action=action, probs=probs)
                    add_cell(reveal[mode]["all"], mode=mode, action=action, probs=probs)
                    if revealed:
                        add_cell(reveal[mode]["revealed"], mode=mode, action=action, probs=probs)
                    counters["decisions"] += 1
                    counters["revealed_decisions"] += int(revealed)
                    counters["decisions_with_stack"] += int(stack is not None)
                    counters["decisions_with_board"] += int(len(board) >= 3)
                elif actor not in excluded:
                    counters[f"invalid_{mode.lower()}_{action.lower()}"] += 1

                pot, street_price, added = apply_event(event, street_paid, pot, street_price)
                contributed[actor] += added
                if typ == "fold":
                    active.discard(actor); allin.discard(actor)
                if event["allin"]:
                    allin.add(actor)

    reveal_report = {}
    for mode in ("FREE", "FACING"):
        all_row = finish_cell(reveal[mode]["all"])
        rev_row = finish_cell(reveal[mode]["revealed"])
        reveal_report[mode] = {"all": all_row, "revealed": rev_row}
        if all_row["observed_target_rate"] is not None and rev_row["observed_target_rate"] is not None:
            reveal_report[mode]["revealed_minus_all_target_rate"] = rev_row["observed_target_rate"] - all_row["observed_target_rate"]

    return {
        "split": split_name,
        "audit_counts": dict(sorted(counters.items())),
        "coverage": {
            "revealed_decision_fraction": counters["revealed_decisions"] / counters["decisions"] if counters["decisions"] else None,
            "stack_decision_fraction": counters["decisions_with_stack"] / counters["decisions"] if counters["decisions"] else None,
            "board_decision_fraction": counters["decisions_with_board"] / counters["decisions"] if counters["decisions"] else None,
        },
        "revealed_hand_selection_bias": reveal_report,
        "marginal_buckets": {
            dim: {key: finish_cell(cell) for key, cell in sorted(cells.items())}
            for dim, cells in dimensions.items()
        },
        "matched_base_context_sensitivity": {
            dim: matched_context_sensitivity(cells, min_bucket_n=min_bucket_n) for dim, cells in matched.items()
        },
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive", type=Path, action="append", required=True)
    p.add_argument("--model-dir", type=Path, required=True)
    p.add_argument("--stake", action="append", default=["100/200"])
    p.add_argument("--exclude-player", action="append", default=[])
    p.add_argument("--min-bucket-observations", type=int, default=30)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()

    by_id, provenance = merge_archives(args.archive, set(args.stake))
    records = list(by_id.values())
    result = {
        "schema": SCHEMA,
        "scope": "opponent postflop decisions only; response realism diagnostic, not a strategy promotion result",
        "dataset": provenance,
        "model_dir": args.model_dir.as_posix(),
        "independence_contract": "hand histories + promoted Model B artifacts only; no Model A EV/policy/recommendation inputs",
        "runtime_conditioning_contract": {
            "conditions_on": ["profile","street","mode","relative_position","pot_type","preflop_role"],
            "does_not_condition_on": ["facing_price_to_pot","SPR","board_texture","hidden_or_revealed_hand_strength"],
            "note": "within an otherwise identical base context the current response table cannot react directly to these omitted variables",
        },
        "target_definition": {"FACING":"fold probability","FREE":"bet probability"},
        "revealed_hand_caveat": "strength buckets use only showdown/revealed hole cards and are selection-biased; revealed-vs-all response deltas are reported explicitly",
        "validation": audit_split(records, "VALIDATION", args.model_dir, set(args.exclude_player), args.min_bucket_observations),
        "test": audit_split(records, "TEST", args.model_dir, set(args.exclude_player), args.min_bucket_observations),
        "test_used_for_model_selection": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

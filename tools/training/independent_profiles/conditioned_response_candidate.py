#!/usr/bin/env python3
"""Build and evaluate a response-conditioned Model B v3 candidate.

The promoted v2 profiles and preflop ranges are frozen.  This experiment changes
only postflop response/sizing representation and learns only from TRAIN hand
histories.  Candidate structure is selected on VALIDATION; TEST is evaluated only
after a variant has cleared the VALIDATION gate.

Hand-strength conditioning is deliberately withheld from FACING decisions: folds
cannot reveal cards at showdown, so revealed-card strength is missing-not-at-
random.  The v3 candidate instead conditions on variables observable for every
postflop decision: facing price-to-pot, SPR, and board texture.
"""
from __future__ import annotations

import argparse
import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path

from tools.datasets.build_hand_history_increment import split_for
from tools.training.independent_profiles.audit_response_conditioning import (
    board_by_street,
    board_texture,
    price_bucket,
    spr_bucket,
    starting_stacks,
)
from tools.training.independent_profiles.build_model_b import (
    POSTFLOP_LEVELS,
    SIZING_LEVELS,
    add_count,
    apply_event,
    key_for,
    parse_hand,
    preflop_summary,
    relative_position,
    serialize_count_levels,
    serialize_sizing_levels,
    sha256_file,
)
from tools.training.independent_profiles.build_player_features import merge_archives
from tools.training.independent_profiles.evaluate_model_b import (
    action_probabilities,
    add_sizing_observation,
    choose_node,
    finalize_sizing_metrics,
    load,
    new_sizing_metrics,
    percentile,
)

SCHEMA = "independent-model-b-response-conditioned-selection/v1"
ACTION_SCHEMA = "independent-postflop-actions/v3-conditioned"
SIZING_SCHEMA = "independent-postflop-sizing/v3-conditioned"
MODEL_SCHEMA = "independent-opponent-model-b/v3-response-conditioned"
CONTRACT_SCHEMA = "independent-opponent-model-b-prediction-contract/v2"
EPS = 1e-15
SEED = 20260913
BOOTSTRAP_SAMPLES = 5000
VARIANTS = [
    ("price", ["price_bucket"]),
    ("price_spr", ["price_bucket", "spr_bucket"]),
    ("price_spr_texture", ["price_bucket", "spr_bucket", "texture_bucket"]),
]


def unique_levels(rows: list[list[str]]) -> list[list[str]]:
    out: list[list[str]] = []
    seen = set()
    for row in rows:
        key = tuple(row)
        if key not in seen:
            out.append(row)
            seen.add(key)
    return out


def action_levels(condition_dims: list[str]) -> list[list[str]]:
    base = [
        "profile", "street", "mode", "relative_position", "pot_type", "preflop_role"
    ]
    enriched = [
        base + condition_dims,
        ["profile", "street", "mode", "relative_position", "pot_type"] + condition_dims,
        ["profile", "street", "mode", "relative_position"] + condition_dims,
        ["profile", "street", "mode"] + condition_dims,
        ["street", "mode"] + condition_dims,
    ]
    return unique_levels(enriched + [list(x) for x in POSTFLOP_LEVELS])


def sizing_levels(condition_dims: list[str]) -> list[list[str]]:
    enriched = [
        ["profile", "street", "mode", "action", "pot_type"] + condition_dims,
        ["profile", "street", "mode", "action"] + condition_dims,
        ["street", "mode", "action"] + condition_dims,
    ]
    return unique_levels(enriched + [list(x) for x in SIZING_LEVELS])


def state_buckets(*, mode: str, to_call: float, pot: float, remaining: float | None, board: list[str]) -> dict:
    p2p = to_call / pot if mode == "FACING" and pot > 0 else None
    spr = remaining / pot if remaining is not None and pot > 0 else None
    return {
        "price_bucket": price_bucket(p2p) if mode == "FACING" else "FREE",
        "spr_bucket": spr_bucket(spr),
        "texture_bucket": board_texture(board),
    }


def action_name(typ: str) -> str:
    return {"check": "CHECK", "fold": "FOLD", "call": "CALL", "bet": "BET", "raise": "RAISE"}[typ]


def valid_action(mode: str, action: str) -> bool:
    return (mode == "FREE" and action in {"CHECK", "BET"}) or (
        mode == "FACING" and action in {"FOLD", "CALL", "RAISE"}
    )


def iterate_decisions(record, profiles: dict, excluded: set[str]):
    """Yield decision state before applying each postflop action."""
    hand = parse_hand(record)
    if hand is None:
        return
    player_profile = profiles["player_profile"]
    default_profile = int(max(profiles["profiles"], key=lambda p: p["appearance_weight"])["profile"])
    boards = board_by_street(record.text)
    stacks = starting_stacks(record.text, set(hand["players"]))
    pot_type, roles, active, allin, _ = preflop_summary(hand)

    pre_paid = defaultdict(float)
    contributed = defaultdict(float)
    pre_price = 0.0
    pot = 0.0
    for event in hand["events"]["preflop"]:
        pot, pre_price, added = apply_event(event, pre_paid, pot, pre_price)
        contributed[event["player"]] += added

    for street in ("flop", "turn", "river"):
        paid = defaultdict(float)
        price = 0.0
        board = boards[street]
        for event in hand["events"][street]:
            actor = event["player"]
            typ = event["type"]
            if typ in {"return", "post"}:
                pot, price, added = apply_event(event, paid, pot, price)
                contributed[actor] += added
                continue
            if typ not in {"fold", "check", "call", "bet", "raise"}:
                continue

            to_call = max(0.0, price - paid[actor])
            mode = "FACING" if to_call > 1e-9 else "FREE"
            action = action_name(typ)
            stack = stacks.get(actor)
            remaining = max(0.0, stack - contributed[actor]) if stack is not None else None
            row = {
                "profile": int(player_profile.get(actor, default_profile)),
                "street": street,
                "mode": mode,
                "relative_position": relative_position(hand, actor, active, allin),
                "pot_type": pot_type,
                "preflop_role": roles.get(actor, "OTHER"),
                "action": action,
                **state_buckets(mode=mode, to_call=to_call, pot=pot, remaining=remaining, board=board),
            }
            pot_before = pot
            eligible = actor not in excluded and valid_action(mode, action)
            yield {
                "actor": actor,
                "row": row,
                "action": action,
                "mode": mode,
                "eligible": eligible,
                "pot_before": pot_before,
                "event": event,
            }

            pot, price, added = apply_event(event, paid, pot, price)
            contributed[actor] += added
            if typ == "fold":
                active.discard(actor)
                allin.discard(actor)
            if event["allin"]:
                allin.add(actor)


def build_tables(records, profiles: dict, excluded: set[str], condition_dims: list[str]) -> tuple[dict, dict, dict]:
    alevels = action_levels(condition_dims)
    slevels = sizing_levels(condition_dims)
    action_data = [defaultdict(Counter) for _ in alevels]
    sizing_data = [defaultdict(list) for _ in slevels]
    audit = Counter()

    for record in records:
        for d in iterate_decisions(record, profiles, excluded) or ():
            if not d["eligible"]:
                if d["actor"] not in excluded:
                    audit[f"invalid_{d['mode'].lower()}_{d['action'].lower()}"] += 1
                continue
            row = d["row"]
            action = d["action"]
            add_count(action_data, alevels, row, action)
            audit["postflop_decisions"] += 1

            event = d["event"]
            if action in {"BET", "RAISE"} and d["pot_before"] > 0:
                # Reconstruct the action's incremental cost without mutating iterator state.
                typ = event["type"]
                if typ == "bet":
                    added = float(event["amount"])
                elif event.get("to") is not None:
                    # paid-before is not exposed here; derive ratio in a second pass below.
                    added = None
                else:
                    added = float(event["amount"])
                if added is not None and added > 0:
                    ratio = added / d["pot_before"]
                    if math.isfinite(ratio) and ratio > 0:
                        for i, cols in enumerate(slevels):
                            sizing_data[i][key_for(cols, row)].append(ratio)
                        audit["sizing_observations_direct"] += 1

    # RAISE 'to' amounts require street-paid state, so collect all sizing observations
    # with the canonical build_model_b accounting in a dedicated exact pass.
    sizing_data = [defaultdict(list) for _ in slevels]
    audit["sizing_observations"] = 0
    for record in records:
        hand = parse_hand(record)
        if hand is None:
            continue
        boards = board_by_street(record.text)
        stacks = starting_stacks(record.text, set(hand["players"]))
        pot_type, roles, active, allin, _ = preflop_summary(hand)
        player_profile = profiles["player_profile"]
        default_profile = int(max(profiles["profiles"], key=lambda p: p["appearance_weight"])["profile"])
        pre_paid = defaultdict(float); contributed = defaultdict(float); pre_price = 0.0; pot = 0.0
        for event in hand["events"]["preflop"]:
            pot, pre_price, added = apply_event(event, pre_paid, pot, pre_price)
            contributed[event["player"]] += added
        for street in ("flop", "turn", "river"):
            paid = defaultdict(float); price = 0.0; board = boards[street]
            for event in hand["events"][street]:
                actor = event["player"]; typ = event["type"]
                if typ in {"return", "post"}:
                    pot, price, added = apply_event(event, paid, pot, price); contributed[actor] += added; continue
                if typ not in {"fold", "check", "call", "bet", "raise"}: continue
                to_call = max(0.0, price - paid[actor]); mode = "FACING" if to_call > 1e-9 else "FREE"
                action = action_name(typ); stack = stacks.get(actor)
                remaining = max(0.0, stack - contributed[actor]) if stack is not None else None
                row = {
                    "profile": int(player_profile.get(actor, default_profile)), "street": street, "mode": mode,
                    "relative_position": relative_position(hand, actor, active, allin), "pot_type": pot_type,
                    "preflop_role": roles.get(actor, "OTHER"), "action": action,
                    **state_buckets(mode=mode, to_call=to_call, pot=pot, remaining=remaining, board=board),
                }
                pot_before = pot
                pot, price, added = apply_event(event, paid, pot, price); contributed[actor] += added
                if actor not in excluded and valid_action(mode, action) and action in {"BET", "RAISE"} and pot_before > 0 and added > 0:
                    ratio = added / pot_before
                    if math.isfinite(ratio) and ratio > 0:
                        for i, cols in enumerate(slevels): sizing_data[i][key_for(cols, row)].append(ratio)
                        audit["sizing_observations"] += 1
                if typ == "fold": active.discard(actor); allin.discard(actor)
                if event["allin"]: allin.add(actor)

    actions = {
        "schema": ACTION_SCHEMA,
        "representation": "response-conditioned",
        "conditioning_dimensions": condition_dims,
        "labels": {"FREE": ["CHECK", "BET"], "FACING": ["FOLD", "CALL", "RAISE"]},
        "backoff_min_observations": 30,
        "levels": serialize_count_levels(alevels, action_data),
    }
    sizings = {
        "schema": SIZING_SCHEMA,
        "representation": "response-conditioned",
        "conditioning_dimensions": condition_dims,
        "semantics": "incremental action cost / pot immediately before action",
        "backoff_min_observations": 12,
        "levels": serialize_sizing_levels(slevels, sizing_data),
    }
    return actions, sizings, dict(sorted(audit.items()))


def new_action_metrics() -> dict:
    return {"n": 0, "loss": 0.0, "brier": 0.0, "correct": 0, "obs": Counter(), "pred": defaultdict(float), "levels": Counter(), "rel": defaultdict(lambda: [0, 0.0, 0])}


def add_action(metrics: dict, actual: str, probs: dict[str, float], level: int) -> None:
    labels = list(probs)
    metrics["n"] += 1
    metrics["loss"] += -math.log(max(float(probs[actual]), EPS))
    metrics["brier"] += sum((probs[x] - (1.0 if x == actual else 0.0)) ** 2 for x in labels)
    pred = max(labels, key=lambda x: (probs[x], x)); ok = int(pred == actual)
    metrics["correct"] += ok; metrics["obs"][actual] += 1; metrics["levels"][str(level)] += 1
    for x in labels: metrics["pred"][x] += probs[x]
    conf = max(probs.values()); b = str(min(9, int(conf * 10)))
    metrics["rel"][b][0] += 1; metrics["rel"][b][1] += conf; metrics["rel"][b][2] += ok


def finish_action(metrics: dict) -> dict:
    n = metrics["n"]
    if not n: return {"n": 0}
    ece = 0.0
    for row in metrics["rel"].values():
        rn, csum, good = row; ece += rn / n * abs(csum / rn - good / rn)
    labels = sorted(set(metrics["obs"]) | set(metrics["pred"]))
    return {
        "n": n, "log_loss": metrics["loss"] / n, "brier": metrics["brier"] / n,
        "accuracy": metrics["correct"] / n, "ece_confidence": ece,
        "selected_level_counts": dict(sorted(metrics["levels"].items(), key=lambda x: int(x[0]))),
        "observed_frequency": {x: metrics["obs"][x] / n for x in labels},
        "mean_predicted_frequency": {x: metrics["pred"][x] / n for x in labels},
    }


def bootstrap_action(rows: list[dict], *, seed: int = SEED, samples: int = BOOTSTRAP_SAMPLES) -> dict:
    if not rows: raise ValueError("no paired rows")
    rng = random.Random(seed); values = []; n_hands = len(rows)
    obs_n = sum(r["n"] for r in rows); obs = sum(r["delta"] for r in rows) / obs_n
    for _ in range(samples):
        loss = 0.0; n = 0
        for _ in range(n_hands):
            r = rows[rng.randrange(n_hands)]; loss += r["delta"]; n += r["n"]
        if n: values.append(loss / n)
    return {
        "cluster_unit": "hand_id", "hands": n_hands, "bootstrap_samples": samples, "seed": seed,
        "observed": obs, "ci95": [percentile(values, .025), percentile(values, .975)],
        "probability_candidate_better": sum(x < 0 for x in values) / len(values), "decisions": obs_n,
    }


def evaluate(records, split_name: str, profiles: dict, incumbent_actions: dict, incumbent_sizing: dict, candidate_actions: dict, candidate_sizing: dict, excluded: set[str], alpha: float) -> dict:
    inc_m = new_action_metrics(); cand_m = new_action_metrics()
    inc_s = new_sizing_metrics(); cand_s = new_sizing_metrics(); pairs = []
    by_hand: dict[str, list[float | int]] = defaultdict(lambda: [0, 0.0])
    inc_min = int(incumbent_actions["backoff_min_observations"]); cand_min = int(candidate_actions["backoff_min_observations"])
    inc_smin = int(incumbent_sizing["backoff_min_observations"]); cand_smin = int(candidate_sizing["backoff_min_observations"])

    for record in records:
        if split_for(record.hand_id) != split_name: continue
        for d in iterate_decisions(record, profiles, excluded) or ():
            if not d["eligible"]: continue
            row = d["row"]; mode = d["mode"]; actual = d["action"]; labels = candidate_actions["labels"][mode]
            inode, ilvl, _ = choose_node(incumbent_actions["levels"], row, inc_min)
            cnode, clvl, _ = choose_node(candidate_actions["levels"], row, cand_min)
            ip = action_probabilities(inode, labels, alpha); cp = action_probabilities(cnode, labels, alpha)
            add_action(inc_m, actual, ip, ilvl); add_action(cand_m, actual, cp, clvl)
            delta = -math.log(max(cp[actual], EPS)) + math.log(max(ip[actual], EPS))
            by_hand[str(record.hand_id)][0] += 1; by_hand[str(record.hand_id)][1] += delta

        # Exact sizing evaluation requires the same accounting as training.
        hand = parse_hand(record)
        if hand is None: continue
        boards = board_by_street(record.text); stacks = starting_stacks(record.text, set(hand["players"]))
        pot_type, roles, active, allin, _ = preflop_summary(hand); player_profile = profiles["player_profile"]
        default_profile = int(max(profiles["profiles"], key=lambda p: p["appearance_weight"])["profile"])
        pre_paid = defaultdict(float); contributed = defaultdict(float); pre_price = 0.0; pot = 0.0
        for event in hand["events"]["preflop"]:
            pot, pre_price, added = apply_event(event, pre_paid, pot, pre_price); contributed[event["player"]] += added
        for street in ("flop", "turn", "river"):
            paid = defaultdict(float); price = 0.0; board = boards[street]
            for event in hand["events"][street]:
                actor = event["player"]; typ = event["type"]
                if typ in {"return", "post"}:
                    pot, price, added = apply_event(event, paid, pot, price); contributed[actor] += added; continue
                if typ not in {"fold", "check", "call", "bet", "raise"}: continue
                to_call = max(0.0, price - paid[actor]); mode = "FACING" if to_call > 1e-9 else "FREE"; action = action_name(typ)
                stack = stacks.get(actor); remaining = max(0.0, stack - contributed[actor]) if stack is not None else None
                row = {"profile": int(player_profile.get(actor, default_profile)), "street": street, "mode": mode,
                       "relative_position": relative_position(hand, actor, active, allin), "pot_type": pot_type,
                       "preflop_role": roles.get(actor, "OTHER"), "action": action,
                       **state_buckets(mode=mode, to_call=to_call, pot=pot, remaining=remaining, board=board)}
                pot_before = pot; pot, price, added = apply_event(event, paid, pot, price); contributed[actor] += added
                if actor not in excluded and valid_action(mode, action) and action in {"BET", "RAISE"} and pot_before > 0 and added > 0:
                    ratio = added / pot_before
                    inode, ilvl, _ = choose_node(incumbent_sizing["levels"], row, inc_smin)
                    cnode, clvl, _ = choose_node(candidate_sizing["levels"], row, cand_smin)
                    add_sizing_observation(inc_s, ratio, inode, ilvl, True); add_sizing_observation(cand_s, ratio, cnode, clvl, True)
                if typ == "fold": active.discard(actor); allin.discard(actor)
                if event["allin"]: allin.add(actor)

    pairs = [{"hand_id": hid, "n": int(v[0]), "delta": float(v[1])} for hid, v in sorted(by_hand.items()) if v[0]]
    return {
        "split": split_name,
        "incumbent_actions": finish_action(inc_m), "candidate_actions": finish_action(cand_m),
        "paired_action_log_loss": bootstrap_action(pairs),
        "incumbent_sizing": finalize_sizing_metrics(inc_s), "candidate_sizing": finalize_sizing_metrics(cand_s),
    }


def validation_gate(result: dict) -> dict:
    pair = result["paired_action_log_loss"]; action = result["candidate_actions"]; sizing = result["candidate_sizing"]
    checks = {
        "paired_action_ci95_upper_le_zero": float(pair["ci95"][1]) <= 0.0,
        "action_ece_le_0_05": float(action["ece_confidence"]) <= 0.05,
        "sizing_p10_p90_coverage": 0.70 <= float(sizing["inside_training_p10_p90_fraction"]) <= 0.90,
        "sizing_above_p99_le_0_03": float(sizing["above_training_p99_fraction"]) <= 0.03,
    }
    return {"pass": all(checks.values()), "checks": checks}


def contract(condition_dims: list[str]) -> dict:
    return {
        "schema": CONTRACT_SCHEMA,
        "model_schema": MODEL_SCHEMA,
        "profile_assignment": "unchanged from promoted independent_model_b_v2",
        "preflop_range": "byte-identical promoted v2 artifact",
        "postflop_action": {
            "selection": "finest hierarchy node with n >= 30, then explicit v2-compatible backoff",
            "smoothing": "symmetric Dirichlet/additive smoothing over legal labels",
            "alpha_per_action": 1.0,
            "conditioning_dimensions": condition_dims,
        },
        "sizing": {
            "selection": "finest hierarchy node with n >= 12, then explicit v2-compatible backoff",
            "distribution": "empirical TRAIN values; no clipping or synthetic tail",
            "conditioning_dimensions": condition_dims,
        },
        "hand_strength": {
            "status": "withheld_revealed_selection_bias",
            "reason": "FACING folds are structurally absent from showdown/revealed-card strength data; no MNAR-biased strength-conditioned fold table is trained",
        },
        "independence": "hand histories plus promoted Model B profile assignments only; no Model A EV, policy, recommendation, or response output",
    }


def persist_model(output_dir: Path, incumbent_dir: Path, condition_dims: list[str], actions: dict, sizings: dict, audit: dict, dataset: dict, validation: dict, test: dict | None) -> None:
    model_dir = output_dir / "selected_candidate" / "model"; model_dir.mkdir(parents=True, exist_ok=True)
    for name in ("profiles.json", "preflop_ranges.json"):
        (model_dir / name).write_bytes((incumbent_dir / name).read_bytes())
    (model_dir / "postflop_actions.json").write_text(json.dumps(actions, ensure_ascii=False, indent=2) + "\n")
    (model_dir / "sizing.json").write_text(json.dumps(sizings, ensure_ascii=False, indent=2) + "\n")
    (model_dir / "prediction_contract.json").write_text(json.dumps(contract(condition_dims), ensure_ascii=False, indent=2) + "\n")
    summary = {
        "schema": MODEL_SCHEMA, "model_version": "independent_model_b_v3_response_conditioned_candidate",
        "fit_split": "TRAIN", "dataset": dataset, "conditioning_dimensions": condition_dims,
        "counts": audit, "profiles_and_ranges": "frozen promoted independent_model_b_v2",
        "hand_strength_conditioning": "withheld_revealed_selection_bias",
        "validation_gate": validation_gate(validation), "test_locked_confirmation": validation_gate(test) if test else None,
        "promotion_status": "candidate_not_promoted", "production_effect": "NONE",
    }
    (model_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive", type=Path, action="append", required=True)
    p.add_argument("--stake", action="append", default=["100/200"])
    p.add_argument("--exclude-player", action="append", default=[])
    p.add_argument("--incumbent-model-dir", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args()

    incumbent_dir = args.incumbent_model_dir; profiles = load(incumbent_dir / "profiles.json")
    incumbent_actions = load(incumbent_dir / "postflop_actions.json"); incumbent_sizing = load(incumbent_dir / "sizing.json")
    incumbent_contract = load(incumbent_dir / "prediction_contract.json"); alpha = float(incumbent_contract["postflop_action"]["alpha_per_action"])
    by_id, provenance = merge_archives(args.archive, set(args.stake)); records = list(by_id.values()); excluded = set(args.exclude_player)
    train = [r for r in records if split_for(r.hand_id) == "TRAIN"]

    variants = {}; passing = []
    selected_payload = None
    for name, dims in VARIANTS:
        actions, sizings, audit = build_tables(train, profiles, excluded, dims)
        val = evaluate(records, "VALIDATION", profiles, incumbent_actions, incumbent_sizing, actions, sizings, excluded, alpha)
        gate = validation_gate(val)
        variants[name] = {"conditioning_dimensions": dims, "validation": val, "gate": gate}
        if gate["pass"]:
            passing.append((float(val["paired_action_log_loss"]["observed"]), len(dims), name, dims, actions, sizings, audit, val))

    if passing:
        passing.sort(key=lambda x: (x[0], x[1], x[2])); _, _, name, dims, actions, sizings, audit, val = passing[0]
        # Variant is frozen here. TEST is consulted only after this VALIDATION-only selection.
        test = evaluate(records, "TEST", profiles, incumbent_actions, incumbent_sizing, actions, sizings, excluded, alpha)
        test_gate = validation_gate(test)
        final_decision = "PROMOTE_RESPONSE_CANDIDATE" if test_gate["pass"] else "RETAIN_INCUMBENT"
        selected_payload = (name, dims, actions, sizings, audit, val, test)
    else:
        name = None; test = None; final_decision = "RETAIN_INCUMBENT"

    result = {
        "schema": SCHEMA,
        "scope": "heads-up-compatible postflop opponent response representation; no Hero strategy selection",
        "dataset": provenance,
        "train_hands": len(train),
        "incumbent_model_dir": incumbent_dir.as_posix(),
        "incumbent_artifacts": {
            "profiles_sha256": sha256_file(incumbent_dir / "profiles.json"),
            "ranges_sha256": sha256_file(incumbent_dir / "preflop_ranges.json"),
            "actions_sha256": sha256_file(incumbent_dir / "postflop_actions.json"),
            "sizing_sha256": sha256_file(incumbent_dir / "sizing.json"),
        },
        "selection_policy": {
            "model_selection_split": "VALIDATION", "test_used_for_selection": False,
            "variants": [x[0] for x in VARIANTS],
            "gate": "paired action log-loss CI95 upper <= 0; action ECE <= .05; sizing p10-p90 coverage .70-.90; sizing >p99 <= .03",
        },
        "strength_conditioning": {
            "status": "withheld_revealed_selection_bias",
            "reason": "revealed-card FACING sample excludes folds by construction; training fold response by revealed strength would encode showdown selection bias",
            "diagnostic_source": "training/runs/20260913_model_b_response_audit/response_conditioning_audit.json",
        },
        "variants": variants,
        "selected_variant": name,
        "test_locked_confirmation": test,
        "decision": final_decision,
        "production_effect": "NONE",
        "independence_contract": "hand histories plus frozen promoted Model B profiles/ranges only; no Model A outputs",
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "selection.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    if selected_payload:
        _name, dims, actions, sizings, audit, val, test = selected_payload
        persist_model(args.output_dir, incumbent_dir, dims, actions, sizings, audit, provenance, val, test)
    print(json.dumps({"selected_variant": name, "decision": final_decision, "train_hands": len(train)}, indent=2))


if __name__ == "__main__":
    main()

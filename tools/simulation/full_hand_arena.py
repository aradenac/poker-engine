#!/usr/bin/env python3
"""Policy-neutral full-hand NLHE simulation arena.

The trusted scenario owns all private cards and the five-card runout. Policies are
queried with a reconstructed *public* ``NoLimitHoldemState`` plus only the acting
player's two cards. This makes future/opponent-card leakage structurally harder
and keeps accounting delegated to the shared #100 rules core.
"""
from __future__ import annotations

import collections
import copy
import math
import statistics
from typing import Any, Callable, Mapping, Sequence

from tools.simulation.game_core import EPS, NoLimitHoldemState, RuleError
from tools.simulation.model_b_runtime import best

RESULT_SCHEMA = "full-hand-arena-result/v1"
REPORT_SCHEMA = "full-hand-arena-report/v1"


def _preflop_summary(state: NoLimitHoldemState, actor: str) -> tuple[str, str]:
    preflop = [event for event in state.action_log if event.get("street") == "preflop"]
    raises = 0
    raise_seen = False
    last_raiser = None
    actor_role = "OTHER"
    for event in preflop:
        action = str(event.get("action", "")).upper()
        player = str(event.get("player", ""))
        if action == "RAISE":
            raises += 1
            raise_seen = True
            last_raiser = player
        elif player == actor and action == "CALL":
            actor_role = "CALLER" if raise_seen else "LIMPER"
        elif player == actor and action == "CHECK":
            actor_role = "BB_CHECK"
    if last_raiser == actor:
        actor_role = "PFA"
    pot_type = "LIMPED" if raises == 0 else "SRP" if raises == 1 else "3BP" if raises == 2 else "4BP_PLUS"
    return pot_type, actor_role


def _relative_position(state: NoLimitHoldemState, actor: str, scenario: Mapping) -> str:
    if state.street == "preflop":
        return str(scenario.get("positions", {}).get(actor, "NA"))
    start = (state.seats.index(state.button) + 1) % len(state.seats)
    order = list(state.seats[start:]) + list(state.seats[:start])
    actionable = [
        player for player in order
        if not state.folded[player] and (player == actor or not state.all_in[player])
    ]
    if actor not in actionable or len(actionable) <= 1:
        return "ONLY"
    index = actionable.index(actor)
    if index == 0:
        return "OOP"
    if index == len(actionable) - 1:
        return "IP"
    return "MIDDLE"


def _invoke_policy(policy, public_state: NoLimitHoldemState, *, seed_parts: Sequence[object], context: dict) -> dict:
    if hasattr(policy, "decide"):
        decision = policy.decide(public_state, seed_parts=tuple(seed_parts), **context)
    elif callable(policy):
        decision = policy(public_state, seed_parts=tuple(seed_parts), **context)
    else:
        raise TypeError("policy must be callable or expose decide(state, ..., **context)")
    if not isinstance(decision, Mapping):
        raise TypeError("policy decision must be a mapping")
    return dict(decision)


def _normalize_decision(state: NoLimitHoldemState, actor: str, decision: Mapping[str, Any]) -> tuple[str, float | None]:
    action = str(decision.get("action", "")).upper().replace("-", "_")
    view = state.legal_view(actor)
    legal = list(view["legal_actions"])
    target = decision.get("target_total_bb")

    # Optional convenience labels are normalized to the canonical #100 core API.
    if action == "BET":
        action = "RAISE"
    elif action == "ALL_IN":
        if "RAISE" in legal and float(view["max_raise_to_bb"]) > float(view["current_price_bb"]) + EPS:
            action = "RAISE"
            target = float(view["max_raise_to_bb"])
        elif "CALL" in legal:
            action = "CALL"
            target = None
        else:
            raise RuleError("ALL_IN is not legal in the current public state")

    if action not in legal:
        raise RuleError(f"policy returned illegal action {action!r} for {actor}; legal={legal}")
    if action == "RAISE":
        if target is None:
            raise RuleError("RAISE decision requires target_total_bb")
        target = float(target)
        if not math.isfinite(target):
            raise RuleError("raise target must be finite")
    else:
        target = None
    return action, target


def _validate_scenario(scenario: Mapping) -> None:
    seats = [str(player) for player in scenario.get("seats", [])]
    if len(seats) < 2 or len(seats) != len(set(seats)):
        raise ValueError("scenario requires at least two unique seats")
    hero = str(scenario.get("hero"))
    if hero not in seats:
        raise ValueError("scenario hero must be seated")
    if scenario.get("button") not in seats:
        raise ValueError("scenario button must be seated")
    stacks = scenario.get("stacks_bb", {})
    holes = scenario.get("hole_cards", {})
    if set(stacks) != set(seats) or set(holes) != set(seats):
        raise ValueError("scenario stacks/hole_cards must cover exactly the seats")
    if any(float(stacks[player]) < 0 for player in seats):
        raise ValueError("scenario contains a negative stack")
    if any(len(holes[player]) != 2 for player in seats):
        raise ValueError("each player must have exactly two hole cards")
    board = list(scenario.get("board", []))
    if len(board) != 5:
        raise ValueError("scenario requires a complete five-card board runout")
    cards = [card for player in seats for card in holes[player]] + board
    if len(cards) != len(set(cards)):
        raise ValueError("scenario contains duplicate cards")
    seeds = scenario.get("component_seeds", {})
    required = {"deck", "opponent_actions", "hero_policy", "monte_carlo"}
    if set(seeds) != required:
        raise ValueError(f"scenario component_seeds must be exactly {sorted(required)}")


def run_full_hand(
    scenario: Mapping,
    *,
    hero_policy,
    opponent_policy,
    net_pot_fn: Callable[[float], float] | None = None,
    max_actions: int = 200,
) -> dict:
    """Run one trusted full-hand scenario through the shared rules core."""
    _validate_scenario(scenario)
    seats = [str(player) for player in scenario["seats"]]
    hero = str(scenario["hero"])
    holes = {player: tuple(scenario["hole_cards"][player]) for player in seats}
    board = list(scenario["board"])
    state = NoLimitHoldemState(
        seats=seats,
        button=str(scenario["button"]),
        stacks_bb={player: float(scenario["stacks_bb"][player]) for player in seats},
    )

    trace: list[dict] = []
    decision_no = collections.Counter()
    players_to_flop = 0
    settlement = None

    for _ in range(int(max_actions) + 20):
        if len(state.live_players) == 1:
            settlement = state.settle_by_fold(net_pot_fn=net_pot_fn)
            break

        actor = state.next_actor
        if actor is not None:
            if len(trace) >= int(max_actions):
                raise RuntimeError("full-hand arena exceeded max_actions")
            before = copy.deepcopy(state.to_snapshot())
            # Reconstruct a detached public state before every decision. No private
            # cards or unrevealed board cards can be reached through this object.
            policy_state = NoLimitHoldemState.from_snapshot(copy.deepcopy(before))
            pot_type, preflop_role = _preflop_summary(policy_state, actor)
            context = {
                "actor": actor,
                "hole_cards": holes[actor],
                "profile": scenario.get("profiles", {}).get(actor),
                "relative_position": _relative_position(policy_state, actor, scenario),
                "pot_type": pot_type,
                "preflop_role": preflop_role,
            }
            seed_namespace = "hero" if actor == hero else "opponent"
            component_seed_key = "hero_policy" if actor == hero else "opponent_actions"
            decision_seed = int(scenario["component_seeds"][component_seed_key])
            seed_parts = (
                scenario["scenario_id"],
                decision_seed,
                seed_namespace,
                actor,
                int(decision_no[actor]),
                policy_state.street,
            )
            policy = hero_policy if actor == hero else opponent_policy
            raw_decision = _invoke_policy(policy, policy_state, seed_parts=seed_parts, context=context)
            action, target = _normalize_decision(state, actor, raw_decision)
            record = state.apply_action(actor, action, target_total_bb=target)
            decision_no[actor] += 1
            trace.append({
                "index": len(trace),
                "street": before["street"],
                "actor": actor,
                "policy_role": seed_namespace,
                "decision_seed_namespace": component_seed_key,
                "public_state_before": before,
                "context": {
                    "profile": context["profile"],
                    "relative_position": context["relative_position"],
                    "pot_type": context["pot_type"],
                    "preflop_role": context["preflop_role"],
                },
                "seed_parts": list(seed_parts),
                "action": action,
                "target_total_bb": target,
                "incremental_cost_bb": record["incremental_cost_bb"],
                "actor_all_in_after": bool(state.all_in[actor]),
            })
            continue

        # Betting is complete (possibly because all remaining players are all-in).
        if state.street == "river":
            ranks = {player: best(list(holes[player]) + board) for player in state.live_players}
            settlement = state.settle_showdown(ranks, net_pot_fn=net_pot_fn)
            break

        if state.street == "preflop":
            players_to_flop = len(state.live_players)
            next_cards = board[:3]
        elif state.street == "flop":
            next_cards = [board[3]]
        elif state.street == "turn":
            next_cards = [board[4]]
        else:  # defensive; NoLimitHoldemState constrains streets.
            raise RuntimeError(f"cannot advance unknown street {state.street!r}")
        state.advance_street(next_cards)
    else:  # pragma: no cover - loop guard should make this unreachable.
        raise RuntimeError("full-hand arena failed to terminate")

    if settlement is None:
        raise RuntimeError("full-hand arena terminated without settlement")

    preflop_actions = [row for row in trace if row["street"] == "preflop"]
    preflop_raises = sum(1 for row in preflop_actions if row["action"] == "RAISE")
    preflop_folds = sum(1 for row in preflop_actions if row["action"] == "FOLD")
    side_pot_layers = len(settlement.pots)
    coverage = {
        "table_players": len(seats),
        "terminal": settlement.terminal,
        "terminal_street": state.street,
        "reached_flop": players_to_flop > 0,
        "players_to_flop": int(players_to_flop),
        "multiway_flop": players_to_flop >= 3,
        "preflop_folds": preflop_folds,
        "preflop_raises": preflop_raises,
        "preflop_raise_bucket": "NONE" if preflop_raises == 0 else "OPEN" if preflop_raises == 1 else "3BET" if preflop_raises == 2 else "4BET_PLUS",
        "all_in": any(row["actor_all_in_after"] for row in trace),
        "side_pot": side_pot_layers > 1,
        "pot_layers": side_pot_layers,
        "uncalled_refund": any(float(value) > EPS for value in settlement.refunds_bb.values()),
    }
    return {
        "schema": RESULT_SCHEMA,
        "scenario_id": scenario["scenario_id"],
        "cluster_id": scenario.get("cluster_id", scenario.get("source_hand_id", scenario["scenario_id"])),
        "population_id": scenario.get("population_id"),
        "hero": hero,
        "hero_net_bb": float(settlement.net_results_bb[hero]),
        "settlement": settlement.as_dict(),
        "coverage": coverage,
        "trace": trace,
        "trust_contract": "policy receives detached public state plus actor hole cards only",
    }


def _clustered_stats(values_by_cluster: Mapping[str, Sequence[float]]) -> dict[str, float | int | None]:
    means = [statistics.fmean(values) for values in values_by_cluster.values() if values]
    if not means:
        return {"independent_hands": 0, "mean_bb_per_hand": None, "se_bb_per_hand": None, "ci95_low_bb_per_hand": None, "ci95_high_bb_per_hand": None}
    mean = statistics.fmean(means)
    if len(means) >= 2:
        se = statistics.stdev(means) / math.sqrt(len(means))
        low, high = mean - 1.96 * se, mean + 1.96 * se
    else:
        se = low = high = None
    return {
        "independent_hands": len(means),
        "mean_bb_per_hand": mean,
        "se_bb_per_hand": se,
        "ci95_low_bb_per_hand": low,
        "ci95_high_bb_per_hand": high,
    }


def summarize_results(results: Sequence[Mapping]) -> dict:
    if not results:
        raise ValueError("cannot summarize an empty result set")
    hero = str(results[0]["hero"])
    if any(str(row["hero"]) != hero for row in results):
        raise ValueError("all results must use the same hero")
    clusters: dict[str, list[float]] = collections.defaultdict(list)
    coverage = collections.Counter()
    contexts = collections.Counter()
    nets = []
    for row in results:
        value = float(row["hero_net_bb"])
        nets.append(value)
        clusters[str(row["cluster_id"])].append(value)
        cov = row["coverage"]
        for key in ("reached_flop", "multiway_flop", "all_in", "side_pot", "uncalled_refund"):
            coverage[key] += int(bool(cov.get(key)))
        contexts[f"players={cov.get('table_players')}"] += 1
        contexts[f"preflop={cov.get('preflop_raise_bucket')}"] += 1
        contexts[f"terminal={cov.get('terminal_street')}:{cov.get('terminal')}"] += 1

    clustered = _clustered_stats(clusters)
    mean = statistics.fmean(nets)
    se = clustered["se_bb_per_hand"]
    return {
        "schema": REPORT_SCHEMA,
        "hero": hero,
        "simulated_hands": len(results),
        "independent_hands": clustered["independent_hands"],
        "mean_bb_per_hand": mean,
        "bb_per_100_simulated_hands": mean * 100.0,
        "clustered_se_bb_per_100": None if se is None else float(se) * 100.0,
        "clustered_ci95_bb_per_100": None if se is None else [
            float(clustered["ci95_low_bb_per_hand"]) * 100.0,
            float(clustered["ci95_high_bb_per_hand"]) * 100.0,
        ],
        "coverage_counts": dict(sorted(coverage.items())),
        "context_distribution": dict(sorted(contexts.items())),
        "interpretation": "simulation-environment estimate; not an observed real-money/play-money winrate",
    }


def compare_paired(candidate: Sequence[Mapping], baseline: Sequence[Mapping]) -> dict:
    """Paired candidate-minus-baseline comparison on identical scenario IDs."""
    base_by_id = {str(row["scenario_id"]): row for row in baseline}
    deltas_by_cluster: dict[str, list[float]] = collections.defaultdict(list)
    matched = 0
    for row in candidate:
        sid = str(row["scenario_id"])
        if sid not in base_by_id:
            continue
        other = base_by_id[sid]
        if str(row["hero"]) != str(other["hero"]):
            raise ValueError(f"hero mismatch for paired scenario {sid}")
        cluster = str(row["cluster_id"])
        deltas_by_cluster[cluster].append(float(row["hero_net_bb"]) - float(other["hero_net_bb"]))
        matched += 1
    if matched == 0:
        raise ValueError("candidate and baseline have no matching scenario IDs")
    stats = _clustered_stats(deltas_by_cluster)
    means = [value for values in deltas_by_cluster.values() for value in values]
    mean = statistics.fmean(means)
    se = stats["se_bb_per_hand"]
    return {
        "schema": "full-hand-arena-paired-comparison/v1",
        "matched_scenarios": matched,
        "independent_hands": stats["independent_hands"],
        "mean_delta_bb_per_hand": mean,
        "delta_bb_per_100": mean * 100.0,
        "clustered_se_bb_per_100": None if se is None else float(se) * 100.0,
        "clustered_ci95_bb_per_100": None if se is None else [
            float(stats["ci95_low_bb_per_hand"]) * 100.0,
            float(stats["ci95_high_bb_per_hand"]) * 100.0,
        ],
    }

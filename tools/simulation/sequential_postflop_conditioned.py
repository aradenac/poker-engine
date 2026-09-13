#!/usr/bin/env python3
"""Sequential arena adapter for the unpromoted price-conditioned Model B v3.

The normal arena remains bound to the promoted v2 runtime.  This adapter replaces
only opponent response sampling so #46/#39 can run paired strategic sensitivity
checks before any production pointer changes.
"""
from __future__ import annotations

import asyncio

from tools.simulation import sequential_postflop as arena
from tools.simulation.model_b_conditioned_runtime import ConditionedModelBEnvironment


async def rollout(scenario: dict, policy: str, oracle: arena.AnalyzerOracle, env: ConditionedModelBEnvironment) -> dict:
    hero = scenario["hero"]
    opponent = scenario["opponent"]
    profile = int(scenario["profile"])
    hero_cards = list(scenario["hero_cards"])
    opponent_cards = list(scenario["opponent_cards"])
    flop = list(scenario["flop"])
    runout = list(scenario["runout"])
    order = list(scenario["postflop_order"])
    stacks = dict(scenario["stacks_bb"])
    total = dict(scenario["preflop_contributions_bb"])
    pot = float(scenario["flop_pot_bb"])
    bb_chips = float(scenario["big_blind_chips"])
    post_invested = 0.0
    hero_actions: list[dict] = []
    history_lines = [f"*** FLOP *** [{' '.join(flop)}]"]
    street_cards = {"flop": flop, "turn": flop + [runout[0]], "river": flop + runout}
    hero_decision_no = 0
    opponent_action_no = 0

    for street in ("flop", "turn", "river"):
        board = street_cards[street]
        if street == "turn":
            history_lines.append(f"*** TURN *** [{' '.join(board[:3])}] [{board[3]}]")
        elif street == "river":
            history_lines.append(f"*** RIVER *** [{' '.join(board[:4])}] [{board[4]}]")

        street_paid = {hero: 0.0, opponent: 0.0}
        last_raise_inc = 1.0
        pending = list(order)

        while pending:
            actor = pending.pop(0)
            other = opponent if actor == hero else hero
            max_paid = max(street_paid.values())
            to_call = max(0.0, max_paid - street_paid[actor])
            remaining = max(0.0, stacks[actor] - total[actor])
            if remaining <= 1e-9:
                continue

            if actor == hero:
                placeholder = "FOLD" if to_call > 1e-9 else "CHECK"
                placeholder_line = arena.action_line(hero, placeholder, 0.0, street_paid[hero], max_paid, remaining, bb_chips)
                synthetic = arena.preflop_prefix(scenario["raw_hand"]) + "\n" + "\n".join(history_lines + [placeholder_line]) + "\n"
                detail = await oracle.decide(synthetic)
                alt = arena.choose_variant(detail, policy, pot)
                label = str(alt["label"])
                hero_decision_no += 1
                ev_final = arena.finite_value(alt)
                hero_actions.append({
                    "street": street,
                    "label": label,
                    "pot_bb": pot,
                    "to_call_bb": to_call,
                    "ev_final_bb": ev_final,
                    "ev_model_bb": alt.get("evBB"),
                    "cost_bb": alt.get("costBB"),
                    "size_ratio": (float(alt.get("costBB")) / max(pot, 0.01)) if alt.get("costBB") is not None else None,
                    "response_observation_floor": alt.get("responseObservationFloor"),
                    "continue_range_quality": alt.get("continueRangeQuality"),
                    "p_all_fold": alt.get("pAllFold"),
                })
                if label == "FOLD":
                    kind, cost = "FOLD", 0.0
                elif label == "CHECK":
                    kind, cost = "CHECK", 0.0
                elif label == "CALL":
                    kind, cost = "CALL", min(to_call, remaining)
                else:
                    kind = "AGG"
                    proposed = alt.get("costBB")
                    cost = min(float(proposed) if proposed is not None else remaining, remaining)
            else:
                mode = "FACING" if to_call > 1e-9 else "FREE"
                relative = "OOP" if actor == order[0] else "IP"
                can_raise = remaining > to_call + 1e-9 and stacks[other] - total[other] > 1e-9
                facing_price_to_pot = (to_call / pot) if mode == "FACING" and pot > 0 else None
                action = env.sample_action(
                    seed_parts=(scenario["environment_seed"], street, opponent_action_no, "action"),
                    profile=profile,
                    street=street,
                    mode=mode,
                    relative_position=relative,
                    pot_type=scenario["pot_type"],
                    preflop_role=scenario["preflop_roles"][opponent],
                    can_raise=can_raise,
                    facing_price_to_pot=facing_price_to_pot,
                )
                opponent_action_no += 1
                if action == "FOLD":
                    kind, cost = "FOLD", 0.0
                elif action == "CHECK":
                    kind, cost = "CHECK", 0.0
                elif action == "CALL":
                    kind, cost = "CALL", min(to_call, remaining)
                else:
                    kind = "AGG"
                    sizing_action = "RAISE" if mode == "FACING" else "BET"
                    ratio = env.sample_sizing(
                        seed_parts=(scenario["environment_seed"], street, opponent_action_no, "size"),
                        profile=profile,
                        street=street,
                        mode=mode,
                        action=sizing_action,
                        pot_type=scenario["pot_type"],
                        facing_price_to_pot=facing_price_to_pot,
                    )
                    desired = max(0.005, ratio * pot)
                    if to_call <= 1e-9:
                        cost = min(remaining, desired)
                    else:
                        min_target = max_paid + last_raise_inc
                        min_cost = max(0.0, min_target - street_paid[actor])
                        cost = min(remaining, max(desired, min_cost))
                        if cost <= to_call + 1e-9:
                            kind, cost = "CALL", min(to_call, remaining)

            if kind == "AGG":
                if stacks[other] - total[other] <= 1e-9 or cost <= to_call + 1e-9:
                    kind, cost = ("CALL", min(to_call, remaining)) if to_call > 1e-9 else ("CHECK", 0.0)
                else:
                    minimum = to_call + last_raise_inc if to_call > 1e-9 else 1.0
                    cost = min(remaining, max(minimum, round(cost * bb_chips) / bb_chips))
            if kind == "CALL" and to_call <= 1e-9:
                kind, cost = "CHECK", 0.0
            if kind == "CHECK" and to_call > 1e-9:
                raise RuntimeError("illegal check facing a bet")
            if actor == hero:
                hero_actions[-1]["executed_kind"] = kind
                hero_actions[-1]["executed_cost_bb"] = cost
            if kind == "FOLD":
                history_lines.append(arena.action_line(actor, "FOLD", 0.0, street_paid[actor], max_paid, remaining, bb_chips))
                if actor == hero:
                    return {"scenario_id": scenario["scenario_id"], "policy": policy, "utility_bb": -post_invested,
                            "hero_decisions": hero_decision_no, "terminal": "hero_fold", "hero_actions": hero_actions}
                uncalled = max(0.0, street_paid[hero] - street_paid[opponent])
                final_pot = max(0.0, pot - uncalled)
                effective_invested = max(0.0, post_invested - uncalled)
                return {"scenario_id": scenario["scenario_id"], "policy": policy,
                        "utility_bb": arena.rake_net(final_pot) - effective_invested,
                        "hero_decisions": hero_decision_no, "terminal": "opponent_fold",
                        "uncalled_return_bb": uncalled, "hero_actions": hero_actions}

            if kind == "CHECK":
                history_lines.append(arena.action_line(actor, "CHECK", 0.0, street_paid[actor], max_paid, remaining, bb_chips))
                continue

            if kind == "CALL":
                history_lines.append(arena.action_line(actor, "CALL", cost, street_paid[actor], max_paid, remaining, bb_chips))
                street_paid[actor] += cost
                total[actor] += cost
                pot += cost
                if actor == hero:
                    post_invested += cost
                pending = []
            else:
                old_max = max_paid
                history_lines.append(arena.action_line(actor, "AGG", cost, street_paid[actor], max_paid, remaining, bb_chips))
                street_paid[actor] += cost
                total[actor] += cost
                pot += cost
                if actor == hero:
                    post_invested += cost
                new_max = max(street_paid.values())
                last_raise_inc = max(last_raise_inc, new_max - old_max)
                pending = [other]

            if total[hero] >= stacks[hero] - 1e-9 or total[opponent] >= stacks[opponent] - 1e-9:
                if pending:
                    continue
                if total[hero] > total[opponent]:
                    returned = total[hero] - total[opponent]
                    total[hero] -= returned
                    pot -= returned
                    post_invested = max(0.0, post_invested - returned)
                elif total[opponent] > total[hero]:
                    returned = total[opponent] - total[hero]
                    total[opponent] -= returned
                    pot -= returned
                final_board = street_cards["river"]
                hero_score = arena.best(hero_cards + final_board)
                opp_score = arena.best(opponent_cards + final_board)
                net = arena.rake_net(pot)
                share = net if hero_score > opp_score else net / 2.0 if hero_score == opp_score else 0.0
                return {"scenario_id": scenario["scenario_id"], "policy": policy, "utility_bb": share - post_invested,
                        "hero_decisions": hero_decision_no, "terminal": "allin_showdown", "hero_actions": hero_actions}

        if street == "river":
            hero_score = arena.best(hero_cards + board)
            opp_score = arena.best(opponent_cards + board)
            net = arena.rake_net(pot)
            share = net if hero_score > opp_score else net / 2.0 if hero_score == opp_score else 0.0
            return {"scenario_id": scenario["scenario_id"], "policy": policy, "utility_bb": share - post_invested,
                    "hero_decisions": hero_decision_no, "terminal": "showdown", "hero_actions": hero_actions}

    raise RuntimeError("rollout reached no terminal state")


def main() -> None:
    arena.ModelBEnvironment = ConditionedModelBEnvironment
    arena.rollout = rollout
    asyncio.run(arena.main())


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Sequential Hero sensitivity arena for the unpromoted #197 response-to-price Model B."""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
import sys
from pathlib import Path
from typing import Any, Sequence

from tools.simulation import sequential_postflop as arena
from tools.simulation import sequential_postflop_conditioned as conditioned
from tools.simulation import v83_hh_compat as compat
from tools.simulation.conditioned_baseline_runner import ConditionedAnalyzerOracle
from tools.simulation.model_b_price_response import ResponseToPriceModel
from tools.simulation.model_b_runtime import ModelBEnvironment, hseed, sha256_file, weighted_choice

ROOT = Path(__file__).resolve().parents[2]
VARIANTS = {"nominal", "fold_low", "fold_high"}
DEPENDENCY_FILES = ("profiles.json", "preflop_ranges.json")


def sequence_token(actions: Sequence[str]) -> str:
    return ">".join(actions[-4:]) if actions else "START"


def v83_prefix(raw: str) -> str:
    return compat.normalize_prefix_text_for_v83(conditioned.preflop_prefix_for_v83(raw))


def _with_fold(probabilities: dict[str, float], target_fold: float) -> dict[str, float]:
    target = min(1.0, max(0.0, float(target_fold)))
    residual = 1.0 - float(probabilities["FOLD"])
    if residual <= 1e-15:
        return {"FOLD": 1.0, "CALL": 0.0, "RAISE": 0.0}
    scale = (1.0 - target) / residual
    return {
        "FOLD": target,
        "CALL": float(probabilities["CALL"]) * scale,
        "RAISE": float(probabilities["RAISE"]) * scale,
    }


class PriceResponseArenaEnvironment(ModelBEnvironment):
    """Reference Model B for materialization/FREE actions + #197 FACING response candidate."""

    def __init__(self, model_dir: Path, alias: str = "candidate", population_id: str | None = None) -> None:
        candidate_dir = Path(model_dir)
        config = json.loads((candidate_dir / "arena_config.json").read_text(encoding="utf-8"))
        if config.get("schema") != "model-b-response-to-price-arena-config/v1":
            raise ValueError("unsupported response-to-price arena config")
        expected_population = str(config.get("population_id") or "")
        actual_population = str(population_id or expected_population)
        if not expected_population or actual_population != expected_population:
            raise ValueError(
                f"response-to-price population mismatch: config={expected_population!r} requested={actual_population!r}"
            )
        base_path = Path(str(config["base_model_dir"]))
        if not base_path.is_absolute():
            base_path = ROOT / base_path
        self.candidate_dir = candidate_dir
        self.base_model_dir = base_path
        self.config = config
        variant = str(os.environ.get("MODEL_B_RESPONSE_VARIANT", "nominal")).lower()
        if variant not in VARIANTS:
            raise ValueError(f"unsupported MODEL_B_RESPONSE_VARIANT={variant!r}")
        self.variant = variant
        super().__init__(
            base_path,
            alias=f"response_to_price_v1:{variant}",
            population_id=actual_population,
        )
        response_name = str(config.get("response_artifact") or "response_to_price.json")
        self.response_path = candidate_dir / response_name
        self.response = ResponseToPriceModel(
            json.loads(self.response_path.read_text(encoding="utf-8"))
        )
        # ModelBEnvironment stores the base path. Expose the explicit candidate
        # directory in metadata without affecting loaded reference tables.
        self.model_dir = candidate_dir

    def artifact_fingerprints(self) -> dict[str, str]:
        names = [
            "profiles.json",
            "preflop_ranges.json",
            "postflop_actions.json",
            "sizing.json",
            "prediction_contract.json",
        ]
        fingerprints = {name: sha256_file(self.base_model_dir / name) for name in names}
        fingerprints["response_to_price.json"] = sha256_file(self.response_path)
        fingerprints["arena_config.json"] = sha256_file(self.candidate_dir / "arena_config.json")
        return fingerprints

    def _response_probabilities(
        self,
        *,
        profile: int,
        street: str,
        relative_position: str,
        pot_type: str,
        sequence: str,
        facing_price_to_pot: float,
        spr: float | None,
        can_raise: bool,
    ) -> dict[str, float]:
        prediction = self.response.predict(
            profile=profile,
            street=street,
            relative_position=relative_position,
            pot_type=pot_type,
            sequence=sequence,
            facing_price_to_pot=facing_price_to_pot,
            spr=spr,
        )
        probabilities = {
            action: float(prediction["probabilities"][action])
            for action in ("FOLD", "CALL", "RAISE")
        }
        if self.variant == "fold_low":
            probabilities = _with_fold(
                probabilities,
                prediction["uncertainty"]["FOLD"]["approx_95"][0],
            )
        elif self.variant == "fold_high":
            probabilities = _with_fold(
                probabilities,
                prediction["uncertainty"]["FOLD"]["approx_95"][1],
            )
        if not can_raise:
            probabilities["CALL"] += probabilities["RAISE"]
            probabilities["RAISE"] = 0.0
        total = sum(probabilities.values())
        return {key: value / total for key, value in probabilities.items()}

    def sample_action(
        self,
        *,
        seed_parts: Sequence[object],
        profile: int,
        street: str,
        mode: str,
        relative_position: str,
        pot_type: str,
        preflop_role: str,
        can_raise: bool = True,
        facing_price_to_pot: float | None = None,
        spr: float | None = None,
        sequence: str = "START",
    ) -> str:
        if str(mode).upper() != "FACING" or facing_price_to_pot is None:
            return super().sample_action(
                seed_parts=seed_parts,
                profile=profile,
                street=street,
                mode=mode,
                relative_position=relative_position,
                pot_type=pot_type,
                preflop_role=preflop_role,
                can_raise=can_raise,
            )
        probabilities = self._response_probabilities(
            profile=profile,
            street=street,
            relative_position=relative_position,
            pot_type=pot_type,
            sequence=sequence,
            facing_price_to_pot=float(facing_price_to_pot),
            spr=spr,
            can_raise=can_raise,
        )
        return str(
            weighted_choice(
                list(probabilities),
                list(probabilities.values()),
                *seed_parts,
            )
        )

    def sample_sizing(
        self,
        *,
        seed_parts: Sequence[object],
        profile: int,
        street: str,
        mode: str,
        action: str,
        pot_type: str,
        relative_position: str | None = None,
        preflop_role: str | None = None,
        facing_price_to_pot: float | None = None,
        spr: float | None = None,
        sequence: str = "START",
    ) -> float:
        if str(mode).upper() == "FACING" and str(action).upper() == "RAISE" and facing_price_to_pot is not None:
            values = self.response.sizing_values(
                profile=profile,
                street=street,
                relative_position=relative_position or "NA",
                pot_type=pot_type,
                sequence=sequence,
                facing_price_to_pot=float(facing_price_to_pot),
                spr=spr,
            )
            if values:
                return float(values[hseed(*seed_parts) % len(values)])
        return super().sample_sizing(
            seed_parts=seed_parts,
            profile=profile,
            street=street,
            mode=mode,
            action=action,
            pot_type=pot_type,
        )


def retarget_manifest(manifest: dict, source_env: ModelBEnvironment, target_env: PriceResponseArenaEnvironment) -> dict:
    if manifest.get("schema") != "sequential-arena-scenario-manifest/v2":
        raise ValueError("unexpected scenario manifest schema")
    population_id = str(manifest.get("population_id") or "")
    if source_env.population_id != population_id or target_env.population_id != population_id:
        raise ValueError("scenario/model population mismatch")
    source_fp = source_env.artifact_fingerprints()
    target_fp = target_env.artifact_fingerprints()
    if (manifest.get("model_b") or {}).get("artifact_sha256") != source_fp:
        raise ValueError("source manifest does not match source Model B")
    source_deps = {name: source_fp[name] for name in DEPENDENCY_FILES}
    target_deps = {name: target_fp[name] for name in DEPENDENCY_FILES}
    if source_deps != target_deps:
        raise ValueError("scenario materialization dependencies differ")
    out = copy.deepcopy(manifest)
    out["model_b"] = {
        "alias": target_env.alias,
        "model_dir": target_env.model_dir.as_posix(),
        "artifact_sha256": target_fp,
    }
    out["scenario_materialization_provenance"] = {
        "retargeted": True,
        "population_id": population_id,
        "source_alias": source_env.alias,
        "target_alias": target_env.alias,
        "dependency_files": list(DEPENDENCY_FILES),
        "dependency_sha256": source_deps,
        "scenario_fingerprint_unchanged": True,
    }
    return out


async def rollout(
    scenario: dict,
    policy: str,
    oracle: arena.AnalyzerOracle,
    env: PriceResponseArenaEnvironment,
) -> dict:
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
    history_lines = [compat.street_marker_for_v83("flop", flop)]
    street_cards = {"flop": flop, "turn": flop + [runout[0]], "river": flop + runout}
    hero_decision_no = 0
    opponent_action_no = 0

    for street in ("flop", "turn", "river"):
        board = street_cards[street]
        if street in {"turn", "river"}:
            history_lines.append(compat.street_marker_for_v83(street, board))

        street_paid = {hero: 0.0, opponent: 0.0}
        last_raise_inc = 1.0
        pending = list(order)
        public_sequence: list[str] = []

        while pending:
            actor = pending.pop(0)
            other = opponent if actor == hero else hero
            max_paid = max(street_paid.values())
            to_call = max(0.0, max_paid - street_paid[actor])
            remaining = max(0.0, stacks[actor] - total[actor])
            if remaining <= 1e-9:
                continue
            mode = "FACING" if to_call > 1e-9 else "FREE"
            sequence = sequence_token(public_sequence)
            spr = (remaining / pot) if pot > 0 else None
            facing_price_to_pot = (to_call / pot) if mode == "FACING" and pot > 0 else None

            if actor == hero:
                placeholder = "FOLD" if to_call > 1e-9 else "CHECK"
                placeholder_line = compat.action_line_for_v83(
                    hero, placeholder, 0.0, street_paid[hero], max_paid, remaining, bb_chips
                )
                synthetic = v83_prefix(scenario["raw_hand"]) + "\n" + "\n".join(history_lines + [placeholder_line]) + "\n"
                detail = await oracle.decide(synthetic)
                alt = arena.choose_variant(detail, policy, pot)
                label = str(alt["label"])
                hero_decision_no += 1
                hero_actions.append({
                    "street": street,
                    "label": label,
                    "pot_bb": pot,
                    "to_call_bb": to_call,
                    "ev_final_bb": arena.finite_value(alt),
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
                relative = "OOP" if actor == order[0] else "IP"
                can_raise = remaining > to_call + 1e-9 and stacks[other] - total[other] > 1e-9
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
                    spr=spr,
                    sequence=sequence,
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
                        relative_position=relative,
                        preflop_role=scenario["preflop_roles"][opponent],
                        facing_price_to_pot=facing_price_to_pot,
                        spr=spr,
                        sequence=sequence,
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

            canonical = (
                "FOLD" if kind == "FOLD"
                else "CHECK" if kind == "CHECK"
                else "CALL" if kind == "CALL"
                else "RAISE" if mode == "FACING"
                else "BET"
            )

            if kind == "FOLD":
                history_lines.append(compat.action_line_for_v83(
                    actor, "FOLD", 0.0, street_paid[actor], max_paid, remaining, bb_chips
                ))
                public_sequence.append(canonical)
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
                history_lines.append(compat.action_line_for_v83(
                    actor, "CHECK", 0.0, street_paid[actor], max_paid, remaining, bb_chips
                ))
                public_sequence.append(canonical)
                continue

            if kind == "CALL":
                history_lines.append(compat.action_line_for_v83(
                    actor, "CALL", cost, street_paid[actor], max_paid, remaining, bb_chips
                ))
                street_paid[actor] += cost
                total[actor] += cost
                pot += cost
                if actor == hero:
                    post_invested += cost
                public_sequence.append(canonical)
                pending = []
            else:
                old_max = max_paid
                history_lines.append(compat.action_line_for_v83(
                    actor, "AGG", cost, street_paid[actor], max_paid, remaining, bb_chips
                ))
                street_paid[actor] += cost
                total[actor] += cost
                pot += cost
                if actor == hero:
                    post_invested += cost
                new_max = max(street_paid.values())
                last_raise_inc = max(last_raise_inc, new_max - old_max)
                public_sequence.append(canonical)
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


async def run(args) -> dict:
    original_env = arena.ModelBEnvironment
    original_rollout = arena.rollout
    original_oracle = arena.AnalyzerOracle
    arena.ModelBEnvironment = PriceResponseArenaEnvironment
    arena.rollout = rollout
    arena.AnalyzerOracle = ConditionedAnalyzerOracle
    try:
        document = await arena.run(args)
    finally:
        arena.ModelBEnvironment = original_env
        arena.rollout = original_rollout
        arena.AnalyzerOracle = original_oracle
    document.setdefault("metadata", {})["response_variant"] = os.environ.get("MODEL_B_RESPONSE_VARIANT", "nominal")
    document["metadata"]["production_effect"] = "NONE"
    document["metadata"]["test_consumed"] = False
    return document


def retarget_cli(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--population", required=True)
    p.add_argument("--manifest", required=True)
    p.add_argument("--source-model-dir", required=True)
    p.add_argument("--target-model-dir", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    source = ModelBEnvironment(
        Path(args.source_model_dir),
        alias="independent_model_b_v2",
        population_id=args.population,
    )
    target = PriceResponseArenaEnvironment(
        Path(args.target_model_dir),
        population_id=args.population,
    )
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    out = retarget_manifest(manifest, source, target)
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(out["scenario_fingerprint_sha256"])
    return 0


async def arena_cli() -> int:
    args = arena.parse_args()
    document = await run(args)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"DONE {out} variant={document['metadata']['response_variant']}", flush=True)
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "retarget":
        return retarget_cli(sys.argv[2:])
    return asyncio.run(arena_cli())


if __name__ == "__main__":
    raise SystemExit(main())

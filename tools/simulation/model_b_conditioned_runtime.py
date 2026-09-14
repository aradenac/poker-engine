#!/usr/bin/env python3
"""Candidate runtime for response-conditioned independent Model B artifacts.

This module does not change the promoted Model B pointer.  It extends the v2
runtime contract only for candidate experiments, adding observable facing
price-to-pot conditioning with the same explicit hierarchy backoff used during
TRAIN/VALIDATION evaluation.
"""
from __future__ import annotations

import math
from pathlib import Path

from tools.simulation.model_b_runtime import ModelBEnvironment, select_node


def price_bucket(x: float | None) -> str:
    if x is None or not math.isfinite(float(x)):
        return "UNKNOWN"
    x = float(x)
    if x <= 0.25:
        return "P00_25"
    if x <= 0.50:
        return "P25_50"
    if x <= 0.75:
        return "P50_75"
    if x <= 1.00:
        return "P75_100"
    if x <= 1.50:
        return "P100_150"
    return "P150_PLUS"


class ConditionedModelBEnvironment(ModelBEnvironment):
    """Read-only runtime supporting the selected v3 price-conditioned schema."""

    def __init__(
        self,
        model_dir: Path,
        alias: str = "independent_model_b_v3_response_conditioned_candidate",
        population_id: str | None = None,
    ) -> None:
        super().__init__(model_dir, alias=alias, population_id=population_id)

    def _validate(self) -> None:
        if self.profiles.get("schema") != "independent-opponent-profiles/v2":
            raise ValueError(f"unsupported profiles schema: {self.profiles.get('schema')}")
        if self.ranges.get("schema") != "independent-preflop-ranges/v2":
            raise ValueError(f"unsupported ranges schema: {self.ranges.get('schema')}")
        if self.actions.get("schema") not in {
            "independent-postflop-actions/v2",
            "independent-postflop-actions/v3-conditioned",
        }:
            raise ValueError(f"unsupported actions schema: {self.actions.get('schema')}")
        if self.sizing.get("schema") not in {
            "independent-postflop-sizing/v2",
            "independent-postflop-sizing/v3-conditioned",
        }:
            raise ValueError(f"unsupported sizing schema: {self.sizing.get('schema')}")
        if self.contract.get("schema") not in {
            "independent-opponent-model-b-prediction-contract/v1",
            "independent-opponent-model-b-prediction-contract/v2",
        }:
            raise ValueError(f"unsupported prediction contract schema: {self.contract.get('schema')}")
        if sum(int(v) for v in self.ranges["multiplicity"].values()) != 1326:
            raise ValueError("invalid 1326-combo multiplicity contract")

    @staticmethod
    def _price_value(mode: str, facing_price_to_pot: float | None) -> str:
        return "FREE" if mode.upper() == "FREE" else price_bucket(facing_price_to_pot)

    def action_probabilities(
        self,
        *,
        profile: int,
        street: str,
        mode: str,
        relative_position: str,
        pot_type: str,
        preflop_role: str,
        can_raise: bool = True,
        facing_price_to_pot: float | None = None,
    ) -> dict[str, float]:
        mode = mode.upper()
        labels = list(self.actions["labels"][mode])
        row = {
            "profile": int(profile),
            "street": street.lower(),
            "mode": mode,
            "relative_position": relative_position,
            "pot_type": pot_type,
            "preflop_role": preflop_role,
            "price_bucket": self._price_value(mode, facing_price_to_pot),
        }
        node, _, _ = select_node(self.actions["levels"], row, int(self.actions["backoff_min_observations"]))
        counts = node.get("counts", {})
        alpha = float(self.contract["postflop_action"]["alpha_per_action"])
        legal_n = sum(float(counts.get(label, 0)) for label in labels)
        den = legal_n + alpha * len(labels)
        probs = {label: (float(counts.get(label, 0)) + alpha) / den for label in labels}
        if mode == "FACING" and not can_raise and "RAISE" in probs:
            probs["CALL"] += probs["RAISE"]
            probs["RAISE"] = 0.0
        total = sum(probs.values())
        return {k: v / total for k, v in probs.items()}

    def sizing_values(
        self,
        *,
        profile: int,
        street: str,
        mode: str,
        action: str,
        pot_type: str,
        facing_price_to_pot: float | None = None,
    ) -> list[float]:
        mode = mode.upper()
        row = {
            "profile": int(profile),
            "street": street.lower(),
            "mode": mode,
            "action": action.upper(),
            "pot_type": pot_type,
            "price_bucket": self._price_value(mode, facing_price_to_pot),
        }
        node, _, _ = select_node(self.sizing["levels"], row, int(self.sizing["backoff_min_observations"]))
        values = [float(x) for x in node.get("values", []) if math.isfinite(float(x)) and float(x) > 0]
        if not values:
            raise ValueError(f"no empirical sizing values for {row}")
        return values

    def sample_sizing(
        self,
        *,
        seed_parts: tuple[object, ...],
        profile: int,
        street: str,
        mode: str,
        action: str,
        pot_type: str,
        facing_price_to_pot: float | None = None,
    ) -> float:
        from tools.simulation.model_b_runtime import hseed

        values = self.sizing_values(
            profile=profile,
            street=street,
            mode=mode,
            action=action,
            pot_type=pot_type,
            facing_price_to_pot=facing_price_to_pot,
        )
        return values[hseed(*seed_parts) % len(values)]

#!/usr/bin/env python3
"""Deterministic sensitivity wrappers around the retained public-only Model B.

The environments in this module are robustness stresses, not refitted opponent
models.  They preserve the selected #104 public-only hierarchy and modify only
RAISE odds and empirical raise sizing according to a frozen, content-addressed
configuration.  All legality remains delegated to ``NoLimitHoldemState``.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from tools.simulation.game_core import EPS, NoLimitHoldemState
from tools.simulation.model_b_public_reference import RetainedPublicModelBPolicy
from tools.simulation.model_b_runtime import weighted_choice

SCHEMA = "poker-model-b-sensitivity-set/v1"
DECISION_SCHEMA = "independent-opponent-model-b-sensitivity-decision/v1"
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "training/full_hand/MODEL_B_SENSITIVITY_ENVIRONMENTS_20260917.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_sensitivity_set(path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if document.get("schema") != SCHEMA:
        raise ValueError(f"unsupported Model B sensitivity schema: {document.get('schema')!r}")
    if document.get("status") != "FROZEN_BEFORE_STRATEGY_RESULTS":
        raise ValueError("Model B sensitivity set must be frozen before strategy results")
    rows = document.get("environments") or []
    if len(rows) < 3:
        raise ValueError("at least three Model B sensitivity environments are required")
    roles = [str(row.get("role") or "") for row in rows]
    ids = [str(row.get("environment_id") or "") for row in rows]
    if len(set(roles)) != len(roles) or any(not role for role in roles):
        raise ValueError("Model B sensitivity roles must be unique and non-empty")
    if len(set(ids)) != len(ids) or any(not value for value in ids):
        raise ValueError("Model B sensitivity environment ids must be unique and non-empty")
    if "nominal" not in roles:
        raise ValueError("Model B sensitivity set requires a nominal environment")
    for row in rows:
        for field in ("raise_odds_multiplier", "raise_sizing_multiplier"):
            value = float(row.get(field, 0.0))
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{field} must be finite and positive")
    return document


def environment_spec(document: Mapping[str, Any], environment_id: str) -> dict[str, Any]:
    matches = [
        dict(row)
        for row in document.get("environments", [])
        if str(row.get("environment_id")) == str(environment_id)
    ]
    if len(matches) != 1:
        raise ValueError(f"unknown Model B sensitivity environment {environment_id!r}")
    return matches[0]


class ModelBSensitivityPolicy:
    """Apply one frozen sensitivity transform to the selected public Model B."""

    def __init__(
        self,
        base_policy: RetainedPublicModelBPolicy,
        *,
        sensitivity_document: Mapping[str, Any],
        sensitivity_sha256: str,
        environment_id: str,
    ) -> None:
        self.base_policy = base_policy
        self.document = dict(sensitivity_document)
        self.config_sha256 = str(sensitivity_sha256)
        self.spec = environment_spec(self.document, environment_id)
        self.population_id = str(base_policy.population_id)
        expected_population = str(self.document.get("population_id") or "")
        if self.population_id != expected_population:
            raise ValueError(
                f"Model B sensitivity population mismatch: base={self.population_id!r}, config={expected_population!r}"
            )
        expected_base = str((self.document.get("base_reference") or {}).get("artifact_sha256") or "")
        if expected_base != str(base_policy.artifact_sha256):
            raise ValueError(
                "Model B sensitivity config does not target the supplied retained public reference"
            )

    @classmethod
    def from_paths(
        cls,
        behavior_path: Path,
        issue_104_result_path: Path,
        *,
        environment_id: str,
        sensitivity_path: Path = DEFAULT_CONFIG,
    ) -> "ModelBSensitivityPolicy":
        sensitivity_path = Path(sensitivity_path)
        document = load_sensitivity_set(sensitivity_path)
        base = RetainedPublicModelBPolicy.from_paths(behavior_path, issue_104_result_path)
        return cls(
            base,
            sensitivity_document=document,
            sensitivity_sha256=sha256_file(sensitivity_path),
            environment_id=environment_id,
        )

    def identity(self) -> dict[str, Any]:
        return {
            "schema": "model-b-sensitivity-identity/v1",
            "population_id": self.population_id,
            "role": self.spec["role"],
            "environment_id": self.spec["environment_id"],
            "sensitivity_config_sha256": self.config_sha256,
            "raise_odds_multiplier": float(self.spec["raise_odds_multiplier"]),
            "raise_sizing_multiplier": float(self.spec["raise_sizing_multiplier"]),
            "base": self.base_policy.identity(),
        }

    def action_probabilities(self, state: NoLimitHoldemState, **context: Any) -> dict[str, Any]:
        info = self.base_policy.action_probabilities(state, **context)
        probabilities = {key: float(value) for key, value in info["probabilities"].items()}
        multiplier = float(self.spec["raise_odds_multiplier"])
        if "RAISE" in probabilities:
            probabilities["RAISE"] *= multiplier
        total = sum(probabilities.values())
        if not math.isfinite(total) or total <= EPS:
            raise ValueError("sensitivity transform removed all finite action probability mass")
        probabilities = {key: value / total for key, value in probabilities.items()}
        return {
            **info,
            "probabilities": probabilities,
            "sensitivity": {
                "environment_id": self.spec["environment_id"],
                "role": self.spec["role"],
                "raise_odds_multiplier": multiplier,
            },
        }

    def sizing_candidates(self, state: NoLimitHoldemState, **context: Any) -> dict[str, Any]:
        info = self.base_policy.sizing_candidates(state, **context)
        multiplier = float(self.spec["raise_sizing_multiplier"])
        sensitivity = {
            "environment_id": self.spec["environment_id"],
            "role": self.spec["role"],
            "raise_sizing_multiplier": multiplier,
        }
        # The nominal environment is the identity treatment.  Preserve the
        # retained reference candidates byte-for-byte rather than rebuilding
        # target totals from a derived ratio (which could introduce rounding or
        # expose an inconsistent fixture/model payload).
        if abs(multiplier - 1.0) <= EPS:
            return {
                **info,
                "candidates": [dict(row) for row in info["candidates"]],
                "sensitivity": sensitivity,
            }

        actor = str(context["actor"])
        view = state.legal_view(actor)
        pot = float(view["pot_before_bb"])
        paid = float(view["actor_street_contribution_bb"])
        current = float(view["current_price_bb"])
        maximum = float(view["max_raise_to_bb"])
        minimum = None if view["min_raise_to_bb"] is None else float(view["min_raise_to_bb"])
        transformed: dict[float, dict[str, float]] = {}
        for row in info["candidates"]:
            ratio = float(row["incremental_cost_over_pot"]) * multiplier
            target = paid + ratio * pot
            if minimum is not None:
                target = max(target, minimum)
            target = min(target, maximum)
            if target <= current + EPS:
                continue
            target = round(target, 9)
            effective_ratio = (target - paid) / pot
            weight = float(row.get("weight", 0.0))
            if weight <= 0 or not math.isfinite(weight):
                continue
            if target in transformed:
                transformed[target]["weight"] += weight
            else:
                transformed[target] = {
                    "incremental_cost_over_pot": effective_ratio,
                    "target_total_bb": target,
                    "weight": weight,
                }
        if not transformed:
            raise ValueError("sensitivity sizing transform produced no legal raise target")
        return {
            **info,
            "candidates": [transformed[key] for key in sorted(transformed)],
            "sensitivity": sensitivity,
        }

    def decide(
        self,
        state: NoLimitHoldemState,
        *,
        seed_parts: Sequence[object],
        **context: Any,
    ) -> dict[str, Any]:
        actor = str(context["actor"])
        view = state.legal_view(actor)
        action_info = self.action_probabilities(state, **context)
        probabilities = action_info["probabilities"]
        # Keep common random numbers across all sensitivity environments.  The
        # probability transform, not the random stream, is the treatment.
        action = str(
            weighted_choice(
                list(probabilities),
                list(probabilities.values()),
                *seed_parts,
                "action",
            )
        )
        target = None
        sizing_info = None
        if action == "RAISE":
            sizing_info = self.sizing_candidates(state, **context)
            candidates = sizing_info["candidates"]
            selected = weighted_choice(
                candidates,
                [float(row["weight"]) for row in candidates],
                *seed_parts,
                "sizing",
            )
            target = float(selected["target_total_bb"])
            incremental = target - float(view["actor_street_contribution_bb"])
        elif action == "CALL":
            incremental = float(view["to_call_bb"])
        else:
            incremental = 0.0
        return {
            "schema": DECISION_SCHEMA,
            "action": action,
            "target_total_bb": target,
            "incremental_cost_bb": round(float(incremental), 9),
            "probabilities": probabilities,
            "features": action_info["features"],
            "action_selection": action_info["selection"],
            "sizing": sizing_info,
            "environment": self.identity(),
        }

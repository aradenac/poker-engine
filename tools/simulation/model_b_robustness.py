#!/usr/bin/env python3
"""Robustness contract for Hero recommendations across plausible Model B environments.

The module aggregates *already evaluated* alternatives across predeclared opponent
environments. It deliberately keeps Monte-Carlo uncertainty and environment/model
uncertainty separate and never turns environments into probability weights.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ENVIRONMENT_SET_SCHEMAS = {
    "poker-model-b-sensitivity-set/v1",
    "model-b-robustness-environment-set/v1",
}
REPORT_SCHEMA = "hero-model-b-robustness/v1"
SUMMARY_SCHEMA = "hero-model-b-robustness-summary/v1"
EPS = 1e-12


def _finite(value: Any, *, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _sizing_key(value: Any) -> str:
    if value is None:
        return "NONE"
    return f"{_finite(value, name='sizing'):.9f}"


def alternative_key(row: Mapping[str, Any]) -> str:
    explicit = row.get("alternative_id")
    if explicit:
        return str(explicit)
    action = str(row.get("action") or "").upper()
    if not action:
        raise ValueError("alternative requires action or alternative_id")
    return f"{action}@{_sizing_key(row.get('sizing'))}"


def load_environment_declarations(path: Path) -> list[dict[str, Any]]:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    return environment_declarations(document)


def environment_declarations(document: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Validate and normalize a frozen/predeclared Model B environment set."""
    schema = str(document.get("schema") or "")
    if schema not in ENVIRONMENT_SET_SCHEMAS:
        raise ValueError(f"unsupported Model B environment-set schema: {schema!r}")
    rows = list(document.get("environments") or [])
    if len(rows) < 2:
        raise ValueError("robustness requires at least two Model B environments")
    normalized = []
    ids = set()
    nominal_count = 0
    for raw in rows:
        environment_id = str(raw.get("environment_id") or "")
        role = str(raw.get("role") or "")
        if not environment_id or not role:
            raise ValueError("environment_id and role are required")
        if environment_id in ids:
            raise ValueError(f"duplicate environment_id: {environment_id}")
        ids.add(environment_id)
        if role == "nominal":
            nominal_count += 1
        # A declared stress may contain multipliers/metadata, but it must not
        # carry a posterior/probability weight used to manufacture a mean EV.
        for forbidden in ("weight", "probability", "posterior_probability"):
            if raw.get(forbidden) is not None:
                raise ValueError(f"environment {environment_id} has forbidden {forbidden}")
        normalized.append(
            {
                "environment_id": environment_id,
                "role": role,
                "metadata": {
                    key: value
                    for key, value in raw.items()
                    if key not in {"environment_id", "role"}
                },
            }
        )
    if nominal_count != 1:
        raise ValueError("environment set requires exactly one nominal role")
    return normalized


@dataclass(frozen=True)
class Evaluation:
    alternative_id: str
    action: str
    sizing: float | None
    ev_bb: float
    mc_ci95: tuple[float, float] | None
    environment_supported: bool
    is_shove: bool
    is_overbet: bool


def _evaluation(row: Mapping[str, Any]) -> Evaluation:
    action = str(row.get("action") or "").upper()
    if not action:
        raise ValueError("evaluation requires action")
    sizing = row.get("sizing")
    sizing_value = None if sizing is None else _finite(sizing, name="sizing")
    ev = _finite(row.get("ev_bb"), name="ev_bb")
    ci = row.get("mc_ci95")
    parsed_ci = None
    if ci is not None:
        if not isinstance(ci, Sequence) or isinstance(ci, (str, bytes)) or len(ci) != 2:
            raise ValueError("mc_ci95 must be [low, high]")
        low = _finite(ci[0], name="mc_ci95.low")
        high = _finite(ci[1], name="mc_ci95.high")
        if low > high:
            raise ValueError("mc_ci95 low must be <= high")
        parsed_ci = (low, high)
    return Evaluation(
        alternative_id=alternative_key(row),
        action=action,
        sizing=sizing_value,
        ev_bb=ev,
        mc_ci95=parsed_ci,
        environment_supported=bool(row.get("environment_supported", True)),
        is_shove=bool(row.get("is_shove", False)),
        is_overbet=bool(row.get("is_overbet", False)) or (
            sizing_value is not None and sizing_value > 1.0
        ),
    )


def _rank(rows: Mapping[str, Evaluation]) -> list[str]:
    return [
        key
        for key, _ in sorted(
            rows.items(),
            key=lambda item: (-item[1].ev_bb, item[0]),
        )
    ]


def _sizing_equal(a: float | None, b: float | None, tolerance: float) -> bool:
    if a is None or b is None:
        return a is b
    return abs(a - b) <= tolerance + EPS


def evaluate_robustness(
    *,
    decision_id: str,
    environments: Sequence[Mapping[str, Any]],
    evaluations: Iterable[Mapping[str, Any]],
    quasi_dominant_regret_bb: float = 0.10,
    sizing_tolerance: float = 1e-9,
) -> dict[str, Any]:
    """Compare one decision's alternatives across declared Model B environments.

    ``evaluations`` contains one row per environment/alternative with EV and
    optional MC CI. Environment uncertainty is the cross-environment envelope;
    MC uncertainty remains attached to each evaluated row and is never pooled.
    """
    regret_limit = _finite(quasi_dominant_regret_bb, name="quasi_dominant_regret_bb")
    if regret_limit < 0:
        raise ValueError("quasi_dominant_regret_bb must be non-negative")
    tolerance = _finite(sizing_tolerance, name="sizing_tolerance")
    if tolerance < 0:
        raise ValueError("sizing_tolerance must be non-negative")

    declarations = [dict(row) for row in environments]
    if len(declarations) < 2:
        raise ValueError("at least two environments are required")
    ids = [str(row.get("environment_id") or "") for row in declarations]
    if any(not value for value in ids) or len(set(ids)) != len(ids):
        raise ValueError("environment declarations require unique environment_id")
    roles = {str(row["environment_id"]): str(row.get("role") or "") for row in declarations}
    nominal_ids = [env_id for env_id in ids if roles[env_id] == "nominal"]
    if len(nominal_ids) != 1:
        raise ValueError("exactly one nominal environment is required")
    nominal_id = nominal_ids[0]
    for row in declarations:
        for forbidden in ("weight", "probability", "posterior_probability"):
            if row.get(forbidden) is not None:
                raise ValueError(f"environment {row['environment_id']} has forbidden {forbidden}")

    by_environment: dict[str, dict[str, Evaluation]] = {env_id: {} for env_id in ids}
    for raw in evaluations:
        env_id = str(raw.get("environment_id") or "")
        if env_id not in by_environment:
            raise ValueError(f"evaluation references undeclared environment {env_id!r}")
        item = _evaluation(raw)
        if item.alternative_id in by_environment[env_id]:
            raise ValueError(f"duplicate evaluation for {env_id}/{item.alternative_id}")
        by_environment[env_id][item.alternative_id] = item

    empty = [env_id for env_id, rows in by_environment.items() if not rows]
    if empty:
        raise ValueError(f"missing evaluations for environments: {empty}")
    alternatives = set(by_environment[nominal_id])
    for env_id, rows in by_environment.items():
        if set(rows) != alternatives:
            raise ValueError(
                f"all environments must evaluate the same alternatives; mismatch in {env_id}"
            )

    rankings = {env_id: _rank(rows) for env_id, rows in by_environment.items()}
    best_ids = {env_id: ranking[0] for env_id, ranking in rankings.items()}
    nominal_best_id = best_ids[nominal_id]
    nominal_best = by_environment[nominal_id][nominal_best_id]

    regret_by_environment = {}
    nominal_ev_by_environment = {}
    best_by_environment = {}
    all_supported = True
    for env_id in ids:
        rows = by_environment[env_id]
        best_id = best_ids[env_id]
        best = rows[best_id]
        nominal_here = rows[nominal_best_id]
        regret = max(0.0, best.ev_bb - nominal_here.ev_bb)
        regret_by_environment[env_id] = regret
        nominal_ev_by_environment[env_id] = nominal_here.ev_bb
        all_supported = all_supported and all(item.environment_supported for item in rows.values())
        best_by_environment[env_id] = {
            "alternative_id": best.alternative_id,
            "action": best.action,
            "sizing": best.sizing,
            "ev_bb": best.ev_bb,
            "mc_ci95": list(best.mc_ci95) if best.mc_ci95 is not None else None,
            "ranking": rankings[env_id],
        }

    best_actions = [best_by_environment[env_id]["action"] for env_id in ids]
    action_stable = len(set(best_actions)) == 1
    nominal_sizing = nominal_best.sizing
    sizing_stable = all(
        _sizing_equal(best_by_environment[env_id]["sizing"], nominal_sizing, tolerance)
        for env_id in ids
    )
    ranking_stable = len({tuple(rankings[env_id]) for env_id in ids}) == 1
    max_regret = max(regret_by_environment.values())
    quasi_dominant = max_regret <= regret_limit + EPS
    model_ev_span = [
        min(nominal_ev_by_environment.values()),
        max(nominal_ev_by_environment.values()),
    ]

    if not all_supported:
        classification = "INSUFFICIENTLY_SUPPORTED"
    elif action_stable and sizing_stable and quasi_dominant:
        classification = "ROBUST"
    else:
        classification = "SENSITIVE"

    aggressive_nominal = nominal_best.is_shove or nominal_best.is_overbet
    aggressive_fragility = None
    if aggressive_nominal:
        changed = [
            env_id
            for env_id in ids
            if env_id != nominal_id
            and (
                best_ids[env_id] != nominal_best_id
                or regret_by_environment[env_id] > regret_limit + EPS
            )
        ]
        aggressive_fragility = {
            "nominal_is_shove": nominal_best.is_shove,
            "nominal_is_overbet": nominal_best.is_overbet,
            "advantage_disappears": bool(changed),
            "affected_environments": changed,
            "max_regret_bb": max_regret,
        }

    environment_rows = []
    for env_id in ids:
        environment_rows.append(
            {
                "environment_id": env_id,
                "role": roles[env_id],
                "best": best_by_environment[env_id],
                "nominal_recommendation_ev_bb": nominal_ev_by_environment[env_id],
                "nominal_recommendation_regret_bb": regret_by_environment[env_id],
            }
        )

    return {
        "schema": REPORT_SCHEMA,
        "decision_id": str(decision_id),
        "classification": classification,
        "nominal_environment_id": nominal_id,
        "nominal_recommendation": {
            "alternative_id": nominal_best.alternative_id,
            "action": nominal_best.action,
            "sizing": nominal_best.sizing,
            "ev_bb": nominal_best.ev_bb,
            "mc_uncertainty": {
                "ci95": list(nominal_best.mc_ci95) if nominal_best.mc_ci95 is not None else None,
                "source": "MONTE_CARLO",
            },
        },
        "environment_uncertainty": {
            "source": "MODEL_B_VARIANTS",
            "environments_weighted": False,
            "nominal_recommendation_ev_span_bb": model_ev_span,
            "nominal_recommendation_ev_range_width_bb": model_ev_span[1] - model_ev_span[0],
            "max_regret_bb": max_regret,
            "regret_by_environment_bb": regret_by_environment,
        },
        "stability": {
            "action_stable": action_stable,
            "sizing_stable": sizing_stable,
            "ranking_stable": ranking_stable,
            "quasi_dominant": quasi_dominant,
            "quasi_dominant_regret_bb": regret_limit,
        },
        "support": {
            "all_environments_supported": all_supported,
            "unsupported_environment_count": sum(
                1
                for env_id in ids
                if not all(item.environment_supported for item in by_environment[env_id].values())
            ),
        },
        "aggressive_fragility": aggressive_fragility,
        "environments": environment_rows,
    }


def compact_robustness_summary(report: Mapping[str, Any]) -> dict[str, Any]:
    """Small feed/detail/export contract; deliberately hides full simulation detail."""
    if report.get("schema") != REPORT_SCHEMA:
        raise ValueError("unsupported robustness report schema")
    nominal = report["nominal_recommendation"]
    environment = report["environment_uncertainty"]
    stability = report["stability"]
    classification = str(report["classification"])
    labels = {
        "ROBUST": "robust",
        "SENSITIVE": "sensitive",
        "INSUFFICIENTLY_SUPPORTED": "insufficiently_supported",
    }
    if classification not in labels:
        raise ValueError(f"unknown robustness classification: {classification}")
    return {
        "schema": SUMMARY_SCHEMA,
        "decision_id": report["decision_id"],
        "status": labels[classification],
        "nominal": {
            "action": nominal["action"],
            "sizing": nominal["sizing"],
            "ev_bb": nominal["ev_bb"],
            "mc_ci95": nominal["mc_uncertainty"]["ci95"],
        },
        "model_environment": {
            "ev_span_bb": environment["nominal_recommendation_ev_span_bb"],
            "max_regret_bb": environment["max_regret_bb"],
            "environment_count": len(report["environments"]),
            "weighted": False,
        },
        "stability": {
            "action": stability["action_stable"],
            "sizing": stability["sizing_stable"],
        },
        "aggressive_fragility": report.get("aggressive_fragility"),
        "detail_available": True,
    }

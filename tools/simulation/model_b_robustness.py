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
RESPONSE_TO_PRICE_ENVIRONMENT_SCHEMA = "model-b-response-to-price-plausible-environments/v1"
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


def response_to_price_context_environment_sets(
    document: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Normalize the contextual plausible environments persisted by issue #197.

    #197 stores one unweighted fold-low/nominal/fold-high set per public context.
    This function preserves that contextual boundary: environments from different
    contexts are never pooled and no probability over environments is invented.
    """
    schema = str(document.get("schema") or "")
    if schema != RESPONSE_TO_PRICE_ENVIRONMENT_SCHEMA:
        raise ValueError(f"unsupported response-to-price environment schema: {schema!r}")
    if document.get("environments_weighted") is not False:
        raise ValueError("response-to-price environment set must declare environments_weighted=false")

    contexts = list(document.get("contexts") or [])
    if not contexts:
        raise ValueError("response-to-price environment document has no contexts")

    normalized_contexts: list[dict[str, Any]] = []
    seen_indexes: set[int] = set()
    for raw_context in contexts:
        index = int(raw_context.get("context_index"))
        if index in seen_indexes:
            raise ValueError(f"duplicate response-to-price context_index: {index}")
        seen_indexes.add(index)

        context = dict(raw_context.get("context") or {})
        identifiability = str(raw_context.get("identifiability") or "")
        validation_support = int(context.get("validation_support") or 0)
        context_supported = (
            identifiability in {"LOCAL_SUPPORTED", "BACKOFF_SUPPORTED"}
            and validation_support > 0
        )
        rows = list(raw_context.get("environments") or [])
        if len(rows) < 2:
            raise ValueError(f"context {index} requires at least two environments")

        normalized = []
        ids: set[str] = set()
        nominal_count = 0
        for raw in rows:
            environment_id = str(raw.get("environment_id") or "")
            if not environment_id:
                raise ValueError(f"context {index} has environment without environment_id")
            if environment_id in ids:
                raise ValueError(f"context {index} has duplicate environment_id {environment_id}")
            ids.add(environment_id)

            for forbidden in ("weight", "probability", "posterior_probability"):
                if raw.get(forbidden) is not None:
                    raise ValueError(
                        f"context {index} environment {environment_id} has forbidden {forbidden}"
                    )

            probabilities = raw.get("probabilities")
            if not isinstance(probabilities, Mapping):
                raise ValueError(
                    f"context {index} environment {environment_id} requires response probabilities"
                )
            required_actions = {"FOLD", "CALL", "RAISE"}
            if set(probabilities) != required_actions:
                raise ValueError(
                    f"context {index} environment {environment_id} probabilities must be "
                    f"exactly {sorted(required_actions)}"
                )
            parsed_probabilities = {
                action: _finite(probabilities[action], name=f"{environment_id}.{action}")
                for action in sorted(required_actions)
            }
            if any(value < 0.0 or value > 1.0 for value in parsed_probabilities.values()):
                raise ValueError(
                    f"context {index} environment {environment_id} has probability outside [0,1]"
                )
            if abs(sum(parsed_probabilities.values()) - 1.0) > 1e-9:
                raise ValueError(
                    f"context {index} environment {environment_id} probabilities do not sum to 1"
                )

            if environment_id == "nominal":
                role = "nominal"
                nominal_count += 1
            elif environment_id == "fold-low":
                role = "lower_fold_response_stress"
            elif environment_id == "fold-high":
                role = "higher_fold_response_stress"
            else:
                role = "response_stress"

            normalized.append(
                {
                    "environment_id": environment_id,
                    "role": role,
                    "environment_supported": context_supported,
                    "metadata": {
                        "response_probabilities": parsed_probabilities,
                        "source_schema": RESPONSE_TO_PRICE_ENVIRONMENT_SCHEMA,
                        "context_index": index,
                        "identifiability": identifiability,
                        "validation_support": validation_support,
                    },
                }
            )

        if nominal_count != 1:
            raise ValueError(f"context {index} requires exactly one nominal environment")

        normalized_contexts.append(
            {
                "context_index": index,
                "context_id": f"response-to-price-context-{index}",
                "context": context,
                "identifiability": identifiability,
                "validation_support": validation_support,
                "environment_supported": context_supported,
                "environments": normalized,
            }
        )

    return normalized_contexts


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
    """Compare the same Hero alternatives across declared Model B environments.

    The contract is deliberately fail-closed:
    - undeclared environments are rejected;
    - missing environments, missing alternatives, or unsupported evidence produce
      INSUFFICIENTLY_SUPPORTED rather than a robustness claim;
    - Monte-Carlo uncertainty stays attached to each evaluation;
    - Model-B uncertainty is represented only by the unweighted cross-environment
      envelope/regret. No environment probability is synthesized.
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
    declaration_support = {
        str(row["environment_id"]): bool(row.get("environment_supported", True))
        for row in declarations
    }
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

    missing_environment_ids = [env_id for env_id in ids if not by_environment[env_id]]
    nominal_rows = by_environment[nominal_id]
    required_alternatives = set(nominal_rows)
    noncomparable_environment_ids: list[str] = []
    missing_alternatives_by_environment: dict[str, list[str]] = {}
    extra_alternatives_by_environment: dict[str, list[str]] = {}
    if required_alternatives:
        for env_id in ids:
            actual = set(by_environment[env_id])
            missing = sorted(required_alternatives - actual)
            extra = sorted(actual - required_alternatives)
            if missing:
                missing_alternatives_by_environment[env_id] = missing
            if extra:
                extra_alternatives_by_environment[env_id] = extra
            if missing or extra:
                noncomparable_environment_ids.append(env_id)
    else:
        noncomparable_environment_ids = list(ids)

    comparable = bool(required_alternatives) and not missing_environment_ids and not noncomparable_environment_ids
    support_by_environment = {
        env_id: (
            declaration_support[env_id]
            and bool(by_environment[env_id])
            and all(item.environment_supported for item in by_environment[env_id].values())
        )
        for env_id in ids
    }
    all_supported = all(support_by_environment.values())

    rankings = {
        env_id: _rank(rows)
        for env_id, rows in by_environment.items()
        if rows
    }
    best_ids = {
        env_id: ranking[0]
        for env_id, ranking in rankings.items()
        if ranking
    }
    nominal_best_id = best_ids.get(nominal_id)
    nominal_best = nominal_rows.get(nominal_best_id) if nominal_best_id else None

    nominal_advantage_bb: float | None = None
    if nominal_best is not None and len(rankings.get(nominal_id, [])) >= 2:
        second_id = rankings[nominal_id][1]
        nominal_advantage_bb = nominal_best.ev_bb - nominal_rows[second_id].ev_bb

    regret_by_environment: dict[str, float | None] = {env_id: None for env_id in ids}
    nominal_ev_by_environment: dict[str, float | None] = {env_id: None for env_id in ids}
    best_by_environment: dict[str, dict[str, Any] | None] = {}
    for env_id in ids:
        rows = by_environment[env_id]
        best_id = best_ids.get(env_id)
        if best_id is None:
            best_by_environment[env_id] = None
            continue
        best = rows[best_id]
        best_by_environment[env_id] = {
            "alternative_id": best.alternative_id,
            "action": best.action,
            "sizing": best.sizing,
            "ev_bb": best.ev_bb,
            "mc_ci95": list(best.mc_ci95) if best.mc_ci95 is not None else None,
            "ranking": rankings[env_id],
        }
        if nominal_best_id is not None and nominal_best_id in rows:
            nominal_here = rows[nominal_best_id]
            nominal_ev_by_environment[env_id] = nominal_here.ev_bb
            regret_by_environment[env_id] = max(0.0, best.ev_bb - nominal_here.ev_bb)

    if comparable:
        best_actions = [best_by_environment[env_id]["action"] for env_id in ids]
        action_stable: bool | None = len(set(best_actions)) == 1
        nominal_sizing = nominal_best.sizing if nominal_best is not None else None
        sizing_stable: bool | None = all(
            _sizing_equal(best_by_environment[env_id]["sizing"], nominal_sizing, tolerance)
            for env_id in ids
        )
        ranking_stable: bool | None = len({tuple(rankings[env_id]) for env_id in ids}) == 1
        complete_regrets = [float(regret_by_environment[env_id]) for env_id in ids]
        max_regret: float | None = max(complete_regrets)
        quasi_dominant: bool | None = max_regret <= regret_limit + EPS
        complete_nominal_evs = [float(nominal_ev_by_environment[env_id]) for env_id in ids]
        model_ev_span: list[float] | None = [
            min(complete_nominal_evs),
            max(complete_nominal_evs),
        ]
        model_ev_range_width: float | None = model_ev_span[1] - model_ev_span[0]
        worst_env_id = max(ids, key=lambda env_id: (float(regret_by_environment[env_id]), -ids.index(env_id)))
        worst_environment_regret: dict[str, Any] | None = {
            "environment_id": worst_env_id,
            "regret_bb": float(regret_by_environment[worst_env_id]),
        }
    else:
        action_stable = None
        sizing_stable = None
        ranking_stable = None
        max_regret = None
        quasi_dominant = None
        model_ev_span = None
        model_ev_range_width = None
        worst_environment_regret = None

    if not comparable or not all_supported:
        classification = "insufficiently_supported"
    elif action_stable and sizing_stable and quasi_dominant:
        classification = "robust"
    else:
        classification = "sensitive"

    def fragility(kind: str, applicable: bool) -> dict[str, Any]:
        if not applicable or nominal_best_id is None:
            return {
                "applicable": False,
                "fragile": None,
                "affected_environments": [],
                "nominal_advantage_bb": nominal_advantage_bb,
                "worst_environment_regret": worst_environment_regret,
            }
        affected: list[str] = []
        if comparable:
            for env_id in ids:
                if env_id == nominal_id:
                    continue
                if (
                    best_ids[env_id] != nominal_best_id
                    or float(regret_by_environment[env_id]) > regret_limit + EPS
                ):
                    affected.append(env_id)
        return {
            "applicable": True,
            "kind": kind,
            "fragile": None if not comparable or not all_supported else bool(affected),
            "affected_environments": affected,
            "nominal_advantage_bb": nominal_advantage_bb,
            "worst_environment_regret": worst_environment_regret,
        }

    shove_fragility = fragility("SHOVE", bool(nominal_best and nominal_best.is_shove))
    overbet_fragility = fragility("OVERBET", bool(nominal_best and nominal_best.is_overbet))

    environment_rows = []
    for env_id in ids:
        rows = by_environment[env_id]
        alternatives = []
        for alt_id in rankings.get(env_id, []):
            item = rows[alt_id]
            ci = list(item.mc_ci95) if item.mc_ci95 is not None else None
            alternatives.append(
                {
                    "alternative_id": item.alternative_id,
                    "action": item.action,
                    "sizing": item.sizing,
                    "ev_bb": item.ev_bb,
                    "mc_uncertainty": {
                        "source": "MONTE_CARLO",
                        "ci95": ci,
                        "ci95_width_bb": (
                            item.mc_ci95[1] - item.mc_ci95[0]
                            if item.mc_ci95 is not None
                            else None
                        ),
                    },
                    "environment_supported": item.environment_supported,
                    "is_shove": item.is_shove,
                    "is_overbet": item.is_overbet,
                }
            )
        environment_rows.append(
            {
                "environment_id": env_id,
                "role": roles[env_id],
                "environment_supported": support_by_environment[env_id],
                "comparable_alternatives": comparable,
                "best": best_by_environment.get(env_id),
                "ranking": rankings.get(env_id, []),
                "alternatives": alternatives,
                "nominal_recommendation_ev_bb": nominal_ev_by_environment[env_id],
                "nominal_recommendation_regret_bb": regret_by_environment[env_id],
            }
        )

    return {
        "schema": REPORT_SCHEMA,
        "decision_id": str(decision_id),
        "classification": classification,
        "nominal_environment_id": nominal_id,
        "nominal_recommendation": (
            None
            if nominal_best is None
            else {
                "alternative_id": nominal_best.alternative_id,
                "action": nominal_best.action,
                "sizing": nominal_best.sizing,
                "ev_bb": nominal_best.ev_bb,
                "nominal_advantage_bb": nominal_advantage_bb,
                "mc_uncertainty": {
                    "ci95": list(nominal_best.mc_ci95) if nominal_best.mc_ci95 is not None else None,
                    "ci95_width_bb": (
                        nominal_best.mc_ci95[1] - nominal_best.mc_ci95[0]
                        if nominal_best.mc_ci95 is not None
                        else None
                    ),
                    "source": "MONTE_CARLO",
                },
            }
        ),
        "environment_uncertainty": {
            "source": "MODEL_B_VARIANTS",
            "environments_weighted": False,
            "comparable": comparable,
            "required_environment_ids": ids,
            "missing_environment_ids": missing_environment_ids,
            "noncomparable_environment_ids": noncomparable_environment_ids,
            "missing_alternatives_by_environment": missing_alternatives_by_environment,
            "extra_alternatives_by_environment": extra_alternatives_by_environment,
            "nominal_recommendation_ev_span_bb": model_ev_span,
            "nominal_recommendation_ev_range_width_bb": model_ev_range_width,
            "max_regret_bb": max_regret,
            "regret_by_environment_bb": regret_by_environment,
            "worst_environment_regret": worst_environment_regret,
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
            "unsupported_environment_ids": [
                env_id for env_id in ids if not support_by_environment[env_id]
            ],
            "unsupported_environment_count": sum(
                1 for env_id in ids if not support_by_environment[env_id]
            ),
        },
        "diagnostics": {
            "nominal_advantage_bb": nominal_advantage_bb,
            "worst_environment_regret": worst_environment_regret,
            "shove_fragility": shove_fragility,
            "overbet_fragility": overbet_fragility,
        },
        # Backward-compatible aggregate alias for earlier #199 consumers.
        "aggressive_fragility": {
            "nominal_is_shove": bool(nominal_best and nominal_best.is_shove),
            "nominal_is_overbet": bool(nominal_best and nominal_best.is_overbet),
            "advantage_disappears": (
                None
                if not comparable or not all_supported
                else bool(
                    shove_fragility.get("fragile")
                    or overbet_fragility.get("fragile")
                )
            ),
            "affected_environments": sorted(
                set(shove_fragility["affected_environments"])
                | set(overbet_fragility["affected_environments"])
            ),
            "max_regret_bb": max_regret,
        },
        "environments": environment_rows,
    }

def compact_robustness_summary(report: Mapping[str, Any]) -> dict[str, Any]:
    """Small feed/detail/export contract; deliberately hides full simulation detail."""
    if report.get("schema") != REPORT_SCHEMA:
        raise ValueError("unsupported robustness report schema")
    nominal = report.get("nominal_recommendation")
    environment = report["environment_uncertainty"]
    stability = report["stability"]
    diagnostics = report.get("diagnostics") or {}
    classification = str(report["classification"])
    allowed = {"robust", "sensitive", "insufficiently_supported"}
    if classification not in allowed:
        raise ValueError(f"unknown robustness classification: {classification}")
    nominal_summary = None
    if nominal is not None:
        nominal_summary = {
            "action": nominal["action"],
            "sizing": nominal["sizing"],
            "ev_bb": nominal["ev_bb"],
            "advantage_bb": nominal.get("nominal_advantage_bb"),
            "mc_ci95": nominal["mc_uncertainty"]["ci95"],
            "mc_ci95_width_bb": nominal["mc_uncertainty"].get("ci95_width_bb"),
        }
    return {
        "schema": SUMMARY_SCHEMA,
        "decision_id": report["decision_id"],
        "status": classification,
        "nominal": nominal_summary,
        "model_environment": {
            "comparable": environment.get("comparable"),
            "ev_span_bb": environment["nominal_recommendation_ev_span_bb"],
            "max_regret_bb": environment["max_regret_bb"],
            "worst_environment_regret": environment.get("worst_environment_regret"),
            "environment_count": len(report["environments"]),
            "missing_environment_ids": environment.get("missing_environment_ids", []),
            "noncomparable_environment_ids": environment.get(
                "noncomparable_environment_ids", []
            ),
            "weighted": False,
        },
        "stability": {
            "action": stability["action_stable"],
            "sizing": stability["sizing_stable"],
            "ranking": stability.get("ranking_stable"),
        },
        "support": {
            "all_environments_supported": report["support"]["all_environments_supported"],
            "unsupported_environment_count": report["support"]["unsupported_environment_count"],
        },
        "shove_fragility": diagnostics.get("shove_fragility"),
        "overbet_fragility": diagnostics.get("overbet_fragility"),
        "aggressive_fragility": report.get("aggressive_fragility"),
        "detail_available": True,
    }

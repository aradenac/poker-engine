from __future__ import annotations

import hashlib
import math
import statistics
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from tools.simulation.game_core import EPS, NoLimitHoldemState, RuleError

DECISION_SCHEMA = "poker-preflop-decision/v1"
EV_REFERENCE = "decision_point_incremental_bb"
CANONICAL_ACTIONS = {
    "FOLD",
    "CHECK",
    "LIMP",
    "OVERLIMP",
    "CALL",
    "OPEN",
    "ISO",
    "SQUEEZE",
    "3BET",
    "4BET",
    "SHOVE",
    "CALL_SHOVE",
}
RAISE_ACTIONS = {"OPEN", "ISO", "SQUEEZE", "3BET", "4BET"}
CALL_ACTIONS = {"LIMP", "OVERLIMP", "CALL"}


class PreflopEvaluationError(ValueError):
    """Raised when a preflop decision grid cannot be evaluated safely."""


class UnsupportedAlternative(PreflopEvaluationError):
    """Raised by a continuation when one candidate is outside model support."""


@dataclass(frozen=True)
class Candidate:
    id: str
    action: str
    core_action: str
    target_total_bb: float | None
    sizing_origin: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "action": self.action,
            "core_action": self.core_action,
            "target_total_bb": self.target_total_bb,
            "sizing_origin": self.sizing_origin,
        }


RolloutFn = Callable[..., Mapping[str, Any]]
MetadataFn = Callable[[Candidate], Mapping[str, Any] | None]
ConfidenceFn = Callable[[Candidate], float | None]


def _round(value: float) -> float:
    return round(float(value), 9)


def _finite(value: Any, name: str) -> float:
    x = float(value)
    if not math.isfinite(x):
        raise PreflopEvaluationError(f"{name} must be finite")
    return x


def _positive_int(value: Any, name: str) -> int:
    x = int(value)
    if x <= 0 or float(value) != x:
        raise PreflopEvaluationError(f"{name} must be a positive integer")
    return x


def _canonical_action(value: str, *, allowed: set[str], name: str) -> str:
    action = str(value).strip().upper()
    if action not in allowed:
        raise PreflopEvaluationError(f"{name} must be one of {sorted(allowed)}, got {action or '<empty>'}")
    return action


def _format_target(target: float) -> str:
    text = f"{_round(target):.9f}".rstrip("0").rstrip(".")
    return text or "0"


def _candidate_id(action: str, target: float | None) -> str:
    return action if target is None else f"{action}@{_format_target(target)}BB"


def _seed(base_seed: int | str, candidate_id: str, sample_index: int) -> int:
    payload = f"{base_seed}|{candidate_id}|{sample_index}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big", signed=False)


def _normalize_support(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    raw = dict(raw or {})
    observations = raw.get("observations")
    if observations is not None:
        observations = int(observations)
        if observations < 0:
            raise PreflopEvaluationError("support.observations must be >= 0")
    return {
        "observations": observations,
        "backoff_level": str(raw.get("backoff_level") or "UNKNOWN").upper(),
        "source": None if raw.get("source") in (None, "") else str(raw["source"]),
    }


def _normalize_model_uncertainty(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    raw = dict(raw or {})
    lower = raw.get("lower_bb")
    upper = raw.get("upper_bb")
    lower = None if lower is None else _finite(lower, "model_uncertainty.lower_bb")
    upper = None if upper is None else _finite(upper, "model_uncertainty.upper_bb")
    if lower is not None and upper is not None and lower > upper + EPS:
        raise PreflopEvaluationError("model uncertainty lower_bb must be <= upper_bb")
    return {
        "lower_bb": lower,
        "upper_bb": upper,
        "method": None if raw.get("method") in (None, "") else str(raw["method"]),
        "status": str(raw.get("status") or "UNKNOWN").upper(),
    }


def _legal_raise_targets(
    view: Mapping[str, Any],
    raise_targets_bb: Sequence[float],
    *,
    include_jam: bool,
) -> list[tuple[float, str]]:
    if "RAISE" not in view["legal_actions"]:
        return []
    minimum = view.get("min_raise_to_bb")
    maximum = _finite(view["max_raise_to_bb"], "max_raise_to_bb")
    current = _finite(view["current_price_bb"], "current_price_bb")
    rows: dict[float, str] = {}
    for raw in raise_targets_bb:
        target = _round(_finite(raw, "raise target"))
        if target <= current + EPS or target > maximum + EPS:
            continue
        is_jam = abs(target - maximum) <= 1e-6
        if minimum is not None and target + EPS < float(minimum) and not is_jam:
            continue
        rows[target] = "GRID"
    if include_jam and maximum > current + EPS:
        rows[_round(maximum)] = "JAM_BOUNDARY"
    return sorted(rows.items())


def build_candidates(
    state: NoLimitHoldemState,
    *,
    actor: str,
    raise_targets_bb: Sequence[float],
    call_action: str = "CALL",
    raise_action: str = "OPEN",
    include_jam: bool = True,
    sizing_grid_source: str | None = None,
) -> list[Candidate]:
    """Build the exact legal candidate grid for one preflop decision point.

    Semantic labels (LIMP/OVERLIMP/ISO/SQUEEZE/3BET/4BET) are supplied by the
    caller from the shared preflop context contract. The rules core remains the
    authority for legality and chip amounts.
    """

    if state.street != "preflop":
        raise PreflopEvaluationError("preflop evaluator requires a preflop state")
    if state.next_actor != actor:
        raise PreflopEvaluationError(f"{actor} is not the next actor")
    call_label = _canonical_action(call_action, allowed=CALL_ACTIONS, name="call_action")
    raise_label = _canonical_action(raise_action, allowed=RAISE_ACTIONS, name="raise_action")
    view = state.legal_view(actor)
    candidates: list[Candidate] = []

    if "FOLD" in view["legal_actions"]:
        candidates.append(Candidate("FOLD", "FOLD", "FOLD", None, None))
    if "CHECK" in view["legal_actions"]:
        candidates.append(Candidate("CHECK", "CHECK", "CHECK", None, None))
    if "CALL" in view["legal_actions"]:
        paid = _finite(view["actor_street_contribution_bb"], "actor street contribution")
        call_cost = _finite(view["to_call_bb"], "to_call_bb")
        target = _round(paid + call_cost)
        is_all_in = abs(call_cost - _finite(view["actor_remaining_bb"], "actor_remaining_bb")) <= 1e-6
        action = "CALL_SHOVE" if is_all_in else call_label
        candidates.append(Candidate(_candidate_id(action, target), action, "CALL", target, "RULE_CALL_PRICE"))

    raise_candidates = []
    for target, origin in _legal_raise_targets(view, raise_targets_bb, include_jam=include_jam):
        maximum = float(view["max_raise_to_bb"])
        action = "SHOVE" if abs(target - maximum) <= 1e-6 else raise_label
        source = origin if origin == "JAM_BOUNDARY" else (str(sizing_grid_source) if sizing_grid_source else "GRID")
        raise_candidates.append(Candidate(_candidate_id(action, target), action, "RAISE", target, source))
    if "RAISE" in view["legal_actions"] and not raise_candidates:
        raise PreflopEvaluationError("RAISE is legal but the configured sizing grid contains no legal raise candidate")
    candidates.extend(raise_candidates)

    if not candidates:
        raise PreflopEvaluationError("decision point has no legal candidates")
    ids = [candidate.id for candidate in candidates]
    if len(ids) != len(set(ids)):
        raise PreflopEvaluationError("candidate grid contains duplicate identities")
    return candidates


def _apply_candidate(state: NoLimitHoldemState, actor: str, candidate: Candidate) -> tuple[NoLimitHoldemState, float]:
    branch = NoLimitHoldemState.from_snapshot(state.to_snapshot())
    try:
        if candidate.core_action == "RAISE":
            record = branch.apply_action(actor, "RAISE", target_total_bb=candidate.target_total_bb)
        else:
            record = branch.apply_action(actor, candidate.core_action)
    except RuleError as exc:
        raise PreflopEvaluationError(f"candidate {candidate.id} became illegal: {exc}") from exc
    cost = _round(record["incremental_cost_bb"])
    if candidate.target_total_bb is not None:
        paid_before = float(state.street_committed_bb[actor])
        expected = _round(float(candidate.target_total_bb) - paid_before)
        if abs(cost - expected) > 1e-6:
            raise AssertionError(f"candidate {candidate.id} cost {cost} != target minus contribution {expected}")
    return branch, cost


def _rollout_values(
    state_after: NoLimitHoldemState,
    *,
    actor: str,
    candidate: Candidate,
    decision_stack_bb: float,
    rollout: RolloutFn,
    samples: int,
    base_seed: int | str,
) -> list[float]:
    values: list[float] = []
    for sample_index in range(samples):
        sample_state = NoLimitHoldemState.from_snapshot(state_after.to_snapshot())
        seed = _seed(base_seed, candidate.id, sample_index)
        try:
            result = dict(
                rollout(
                    sample_state,
                    actor=actor,
                    seed=seed,
                    sample_index=sample_index,
                    candidate=candidate.as_dict(),
                )
            )
        except UnsupportedAlternative:
            raise
        except Exception as exc:
            raise PreflopEvaluationError(f"rollout failed for {candidate.id}: {exc}") from exc
        if result.get("supported") is False:
            reason = result.get("reason") or "continuation reported unsupported"
            raise UnsupportedAlternative(f"{candidate.id}: {reason}")
        if "ending_stack_bb" not in result:
            raise PreflopEvaluationError(f"rollout for {candidate.id} did not return ending_stack_bb")
        ending_stack = _finite(result["ending_stack_bb"], f"{candidate.id}.ending_stack_bb")
        if ending_stack < -EPS:
            raise PreflopEvaluationError(f"{candidate.id}.ending_stack_bb must be non-negative")
        values.append(ending_stack - decision_stack_bb)
    return values


def _alternative(
    state: NoLimitHoldemState,
    *,
    actor: str,
    candidate: Candidate,
    rollout: RolloutFn,
    samples_per_candidate: int,
    base_seed: int | str,
    support_provider: MetadataFn | None,
    confidence_provider: ConfidenceFn | None,
    model_uncertainty_provider: MetadataFn | None,
) -> tuple[dict[str, Any], int]:
    state_after, cost = _apply_candidate(state, actor, candidate)
    if candidate.action == "FOLD":
        values = [0.0]
        rollout_samples = 0
        mc_samples = 0
        standard_error = 0.0
        mc_method = "exact_fold_reference"
    else:
        values = _rollout_values(
            state_after,
            actor=actor,
            candidate=candidate,
            decision_stack_bb=float(state.stacks_bb[actor]),
            rollout=rollout,
            samples=samples_per_candidate,
            base_seed=base_seed,
        )
        rollout_samples = len(values)
        mc_samples = len(values)
        standard_error = 0.0 if len(values) < 2 else statistics.stdev(values) / math.sqrt(len(values))
        mc_method = "independent_rollout_sample_mean"

    ev = statistics.fmean(values)
    confidence = None if confidence_provider is None else confidence_provider(candidate)
    if confidence is not None:
        confidence = _finite(confidence, f"confidence[{candidate.id}]")
        if confidence < -EPS or confidence > 1 + EPS:
            raise PreflopEvaluationError(f"confidence[{candidate.id}] must be in [0, 1]")
        confidence = max(0.0, min(1.0, confidence))
    support = _normalize_support(None if support_provider is None else support_provider(candidate))
    model_uncertainty = _normalize_model_uncertainty(
        None if model_uncertainty_provider is None else model_uncertainty_provider(candidate)
    )
    row = {
        "id": candidate.id,
        "action": candidate.action,
        "target_total_bb": candidate.target_total_bb,
        "incremental_cost_bb": cost,
        "ev_bb": _round(ev),
        "support": support,
        "confidence": confidence,
        "uncertainty": {
            "monte_carlo": {
                "standard_error_bb": _round(standard_error),
                "samples": mc_samples,
                "method": mc_method,
            },
            "model": model_uncertainty,
        },
        "sizing_origin": candidate.sizing_origin,
        "notes": "",
    }
    return row, rollout_samples


def evaluate_preflop_grid(
    state: NoLimitHoldemState,
    *,
    actor: str,
    context_id: str,
    population_id: str,
    raise_targets_bb: Sequence[float],
    rollout: RolloutFn,
    samples_per_candidate: int,
    base_seed: int | str,
    call_action: str = "CALL",
    raise_action: str = "OPEN",
    include_jam: bool = True,
    sizing_grid_source: str | None = None,
    support_provider: MetadataFn | None = None,
    confidence_provider: ConfidenceFn | None = None,
    model_uncertainty_provider: MetadataFn | None = None,
    status: str = "EXPERIMENTAL",
    notes: str = "",
) -> dict[str, Any]:
    """Evaluate every legal preflop action/sizing and return the canonical decision.

    The continuation callback receives a detached state *after* the candidate action
    and must return an `ending_stack_bb` for Hero. EV is always computed as ending
    stack minus Hero's remaining stack at the decision point, so past contributions
    are sunk while candidate cost, future betting, rake and side-pot settlement can
    all be reflected by the continuation implementation.
    """

    context_id = str(context_id).strip()
    population_id = str(population_id).strip()
    if not context_id:
        raise PreflopEvaluationError("context_id is required")
    if not population_id:
        raise PreflopEvaluationError("population_id is required")
    samples = _positive_int(samples_per_candidate, "samples_per_candidate")
    normalized_status = str(status or "EXPERIMENTAL").strip().upper()
    if normalized_status == "PROMOTED":
        raise PreflopEvaluationError("grid evaluator cannot promote a strategy")
    if state.street != "preflop" or state.next_actor != actor:
        raise PreflopEvaluationError("state must be at actor's pending preflop decision")

    view = state.legal_view(actor)
    candidates = build_candidates(
        state,
        actor=actor,
        raise_targets_bb=raise_targets_bb,
        call_action=call_action,
        raise_action=raise_action,
        include_jam=include_jam,
        sizing_grid_source=sizing_grid_source,
    )
    alternatives: list[dict[str, Any]] = []
    rollout_budget = 0
    for candidate in candidates:
        row, used = _alternative(
            state,
            actor=actor,
            candidate=candidate,
            rollout=rollout,
            samples_per_candidate=samples,
            base_seed=base_seed,
            support_provider=support_provider,
            confidence_provider=confidence_provider,
            model_uncertainty_provider=model_uncertainty_provider,
        )
        alternatives.append(row)
        rollout_budget += used

    selected = max(alternatives, key=lambda row: row["ev_bb"])
    return {
        "schema": DECISION_SCHEMA,
        "status": normalized_status,
        "context_id": context_id,
        "population_id": population_id,
        "ev_reference": EV_REFERENCE,
        "actor_contribution_bb": _round(float(view["actor_street_contribution_bb"])),
        "legal_actions": sorted({row["action"] for row in alternatives}),
        "selected_id": selected["id"],
        "action": selected["action"],
        "target_total_bb": selected["target_total_bb"],
        "bet_to_bb": selected["target_total_bb"],
        "incremental_cost_bb": selected["incremental_cost_bb"],
        "ev_bb": selected["ev_bb"],
        "support": dict(selected["support"]),
        "confidence": selected["confidence"],
        "uncertainty": dict(selected["uncertainty"]),
        "alternatives": alternatives,
        "search": {
            "candidate_ids": [row["id"] for row in alternatives],
            "sizing_grid_source": None if not sizing_grid_source else str(sizing_grid_source),
            "budget": rollout_budget,
            "seed": str(base_seed),
            "notes": f"samples_per_nonfold_candidate={samples}",
        },
        "notes": str(notes or ""),
    }

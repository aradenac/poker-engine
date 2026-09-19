#!/usr/bin/env python3
"""Real #198 paired/adaptive integration for the #106 preflop grid and #196 bridge.

This module preserves the historical fixed evaluator unchanged.  It builds the
same legal Candidate grid, applies each candidate through the shared NLHE rules
core, and evaluates every non-exact alternative on the same candidate-independent
random world for a given decision/sample.  The resulting paired evidence can be
fed directly into the merged #297 bridge without reusing the #196 candidate or
generation identities as local alternative ids.

TEST is deliberately out of scope.  Callers are responsible for supplying the
authorized TRAIN/VALIDATION source and for freezing any scientific protocol
before inspecting performance results.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from tools.simulation.game_core import NoLimitHoldemState
from tools.simulation.model_a_preflop_rollout import (
    ModelAPreflopContinuationRollout,
    _sample_fingerprint,
)
from tools.simulation.paired_adaptive_preflop_ev import AdaptiveBudget, run_paired_search
from tools.simulation.preflop_grid_evaluator import (
    DECISION_SCHEMA,
    EV_REFERENCE,
    Candidate,
    PreflopEvaluationError,
    UnsupportedAlternative,
    _apply_candidate,
    _normalize_model_uncertainty,
    _normalize_support,
    _round,
    build_candidates,
)
from tools.training.bridge_paired_ev_to_hero_generation import (
    REQUEST_SCHEMA,
    bridge_request,
)
from tools.training.validate_hero_preflop_generation import (
    CANONICAL_HAND_SET,
    load_json,
    sha256_path,
)

INTEGRATION_SCHEMA = "poker-paired-preflop-grid-integration/v1"
PAIRING_METHOD = "paired_common_random_numbers"


def exact_decision_id(context_id: str, hand_class: str) -> str:
    context_id = str(context_id).strip()
    hand_class = str(hand_class).strip()
    if not context_id:
        raise PreflopEvaluationError("context_id is required")
    if hand_class not in CANONICAL_HAND_SET:
        raise PreflopEvaluationError(f"invalid canonical hand_class {hand_class!r}")
    return f"{context_id}|{hand_class}"


def _bridge_spec(candidate: Candidate) -> dict[str, Any]:
    if candidate.core_action in {"FOLD", "CHECK", "CALL"}:
        return {
            "action": candidate.core_action,
            "sizing": {"kind": "NONE", "value": None, "unit": None},
        }
    if candidate.core_action != "RAISE":
        raise PreflopEvaluationError(
            f"candidate {candidate.id} has unsupported core action {candidate.core_action!r}"
        )
    if candidate.action == "SHOVE":
        return {
            "action": "SHOVE",
            "sizing": {"kind": "ALL_IN", "value": None, "unit": None},
        }
    if candidate.target_total_bb is None or float(candidate.target_total_bb) <= 0:
        raise PreflopEvaluationError(
            f"candidate {candidate.id} requires a positive exact raise-to sizing"
        )
    return {
        "action": "RAISE",
        "sizing": {
            "kind": "FIXED_BB",
            "value": _round(float(candidate.target_total_bb)),
            "unit": "BB",
        },
    }


def _finite(value: Any, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise PreflopEvaluationError(f"{name} must be numeric") from exc
    if not math.isfinite(result):
        raise PreflopEvaluationError(f"{name} must be finite")
    return result


def evaluate_preflop_grid_paired(
    state: NoLimitHoldemState,
    *,
    actor: str,
    context_id: str,
    hand_class: str,
    population_id: str,
    raise_targets_bb: Sequence[float],
    rollout,
    budget: AdaptiveBudget,
    base_seed: int | str,
    call_action: str = "CALL",
    raise_action: str = "OPEN",
    include_jam: bool = True,
    sizing_grid_source: str | None = None,
    support_provider=None,
    confidence_provider=None,
    model_uncertainty_provider=None,
    status: str = "EXPERIMENTAL",
    notes: str = "",
    require_materialized_common_world: bool = False,
) -> dict[str, Any]:
    """Evaluate the canonical grid using CRN worlds shared across alternatives."""

    population_id = str(population_id).strip()
    if not population_id:
        raise PreflopEvaluationError("population_id is required")
    if state.street != "preflop" or state.next_actor != actor:
        raise PreflopEvaluationError("state must be at actor's pending preflop decision")
    normalized_status = str(status or "EXPERIMENTAL").strip().upper()
    if normalized_status == "PROMOTED":
        raise PreflopEvaluationError("paired grid evaluator cannot promote a strategy")

    decision_id = exact_decision_id(context_id, hand_class)
    candidates = build_candidates(
        state,
        actor=actor,
        raise_targets_bb=raise_targets_bb,
        call_action=call_action,
        raise_action=raise_action,
        include_jam=include_jam,
        sizing_grid_source=sizing_grid_source,
    )

    decision_stack_bb = float(state.stacks_bb[actor])
    payloads: dict[str, dict[str, Any]] = {}
    bridge_alternatives: dict[str, dict[str, Any]] = {}
    exact_values: dict[str, float] = {}

    for candidate in candidates:
        branch, cost = _apply_candidate(state, actor, candidate)
        payloads[candidate.id] = {
            "candidate": candidate.as_dict(),
            "state_after": branch.to_snapshot(),
            "incremental_cost_bb": _round(cost),
        }
        bridge_alternatives[candidate.id] = _bridge_spec(candidate)
        if candidate.core_action == "FOLD":
            exact_values[candidate.id] = 0.0

    non_exact = [candidate for candidate in candidates if candidate.id not in exact_values]
    if not non_exact:
        raise PreflopEvaluationError(
            "paired evaluation requires at least one non-exact continuation alternative"
        )

    public_context = {
        "context_id": str(context_id),
        "population_id": population_id,
        "actor": str(actor),
        "street": "preflop",
        "state_snapshot": state.to_snapshot(),
    }
    materialized_model_a_world = isinstance(rollout, ModelAPreflopContinuationRollout)
    if require_materialized_common_world and not materialized_model_a_world:
        raise PreflopEvaluationError(
            "real VALIDATION requires ModelAPreflopContinuationRollout common-world materialization"
        )

    def world_factory(public, bound_decision_id, sample_index, seed):
        base = {
            "seed": int(seed),
            "sample_index": int(sample_index),
            "decision_id": str(bound_decision_id),
            "public_context_id": str(public["context_id"]),
        }
        if materialized_model_a_world:
            # Hidden cards exist before Hero chooses an alternative. Materialize
            # them from the decision-point public history exactly once, then reuse
            # the same holes + board for every counterfactual candidate.
            decision_state = NoLimitHoldemState.from_snapshot(state.to_snapshot())
            holes = rollout._sample_private_cards(
                decision_state, hero=actor, seed=int(seed)
            )
            board = rollout._sample_board(decision_state, holes, seed=int(seed))
            return {
                **base,
                "world_mode": "MATERIALIZED_MODEL_A_HOLES_AND_BOARD",
                "holes": {player: list(cards) for player, cards in holes.items()},
                "board": list(board),
                "sample_fingerprint_sha256": _sample_fingerprint(holes, board),
            }
        return {**base, "world_mode": "GENERIC_SHARED_SEED"}

    def evaluator(world, candidate_id, payload):
        branch = NoLimitHoldemState.from_snapshot(payload["state_after"])
        try:
            if world["world_mode"] == "MATERIALIZED_MODEL_A_HOLES_AND_BOARD":
                terminal = rollout._run_to_terminal(
                    branch,
                    hero=actor,
                    holes=world["holes"],
                    board=world["board"],
                    seed=int(world["seed"]),
                    sample_index=int(world["sample_index"]),
                    candidate_id=f"PAIRED_WORLD:{decision_id}",
                )
                result = {
                    "supported": True,
                    **terminal,
                    "sample_fingerprint_sha256": world[
                        "sample_fingerprint_sha256"
                    ],
                }
            else:
                callback_candidate = dict(payload["candidate"])
                callback_candidate["alternative_id"] = candidate_id
                callback_candidate["id"] = f"PAIRED_WORLD:{decision_id}"
                result = dict(
                    rollout(
                        branch,
                        actor=actor,
                        seed=int(world["seed"]),
                        sample_index=int(world["sample_index"]),
                        candidate=callback_candidate,
                    )
                )
        except UnsupportedAlternative:
            raise
        except Exception as exc:
            raise PreflopEvaluationError(
                f"paired rollout failed for {candidate_id}: {exc}"
            ) from exc
        if result.get("supported") is False:
            raise UnsupportedAlternative(
                f"{candidate_id}: {result.get('reason') or 'continuation reported unsupported'}"
            )
        if "ending_stack_bb" not in result:
            raise PreflopEvaluationError(
                f"paired rollout for {candidate_id} did not return ending_stack_bb"
            )
        ending_stack = _finite(
            result["ending_stack_bb"], f"{candidate_id}.ending_stack_bb"
        )
        if ending_stack < 0:
            raise PreflopEvaluationError(
                f"{candidate_id}.ending_stack_bb must be non-negative"
            )
        return ending_stack - decision_stack_bb

    paired = run_paired_search(
        payloads,
        decision_id=decision_id,
        public_context=public_context,
        world_factory=world_factory,
        evaluator=evaluator,
        base_seed=base_seed,
        budget=budget,
        exact_values=exact_values,
        adaptive=True,
    )

    by_candidate = {candidate.id: candidate for candidate in candidates}
    alternatives: list[dict[str, Any]] = []
    for candidate in candidates:
        evidence = dict(paired["alternatives"][candidate.id])
        confidence = None if confidence_provider is None else confidence_provider(candidate)
        if confidence is not None:
            confidence = _finite(confidence, f"confidence[{candidate.id}]")
            if confidence < 0 or confidence > 1:
                raise PreflopEvaluationError(
                    f"confidence[{candidate.id}] must be in [0, 1]"
                )
        alternatives.append(
            {
                "id": candidate.id,
                "action": candidate.action,
                "target_total_bb": candidate.target_total_bb,
                "incremental_cost_bb": payloads[candidate.id][
                    "incremental_cost_bb"
                ],
                "ev_bb": evidence["ev_bb"],
                "support": _normalize_support(
                    None if support_provider is None else support_provider(candidate)
                ),
                "confidence": confidence,
                "uncertainty": {
                    "monte_carlo": {
                        "standard_error_bb": evidence["standard_error_bb"],
                        "samples": evidence["rollouts"],
                        "method": (
                            "exact_fold_reference"
                            if evidence["rollouts"] == 0
                            else PAIRING_METHOD
                        ),
                        "ci95_low_bb": evidence["ci_lower_bb"],
                        "ci95_high_bb": evidence["ci_upper_bb"],
                    },
                    "model": _normalize_model_uncertainty(
                        None
                        if model_uncertainty_provider is None
                        else model_uncertainty_provider(candidate)
                    ),
                },
                "paired_delta_vs_selected": dict(
                    evidence["paired_delta_vs_selected"]
                ),
                "sizing_origin": candidate.sizing_origin,
                "notes": "",
            }
        )

    selected_id = str(paired["selected_id"])
    selected = next(row for row in alternatives if row["id"] == selected_id)
    view = state.legal_view(actor)
    decision = {
        "schema": DECISION_SCHEMA,
        "status": normalized_status,
        "context_id": str(context_id),
        "population_id": population_id,
        "ev_reference": EV_REFERENCE,
        "actor_contribution_bb": _round(
            float(view["actor_street_contribution_bb"])
        ),
        "legal_actions": sorted({row["action"] for row in alternatives}),
        "selected_id": selected_id,
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
            "sizing_grid_source": (
                None if not sizing_grid_source else str(sizing_grid_source)
            ),
            "budget": int(paired["search"]["rollout_budget_used"]),
            "seed": str(base_seed),
            "notes": "paired/adaptive common-random-world search",
            "pairing_contract": paired["search"]["pairing_contract"],
            "worlds_materialized": int(
                paired["search"]["worlds_materialized"]
            ),
            "pairwise_deltas": dict(paired["pairwise_deltas"]),
            "common_world_mode": (
                "MATERIALIZED_MODEL_A_HOLES_AND_BOARD"
                if materialized_model_a_world
                else "GENERIC_SHARED_SEED"
            ),
        },
        "notes": str(notes or ""),
    }
    return {
        "schema": INTEGRATION_SCHEMA,
        "decision_id": decision_id,
        "context_id": str(context_id),
        "hand_class": str(hand_class),
        "population_id": population_id,
        "decision": decision,
        "paired_result": paired,
        "bridge_alternatives": bridge_alternatives,
        "test_consumed": False,
    }


def bridge_integration_to_generation(
    integration: Mapping[str, Any],
    *,
    artifact_identity: Mapping[str, Any],
    plan: Mapping[str, Any],
    plan_sha256: str,
) -> dict[str, Any]:
    """Bind one real paired decision to the merged #297/#196 artifact contract."""

    if integration.get("schema") != INTEGRATION_SCHEMA:
        raise PreflopEvaluationError(
            f"unsupported integration schema {integration.get('schema')!r}"
        )
    request = {
        "schema": REQUEST_SCHEMA,
        "paired_result": integration["paired_result"],
        "decision_binding": {
            "decision_id": integration["decision_id"],
            "context_id": integration["context_id"],
            "hand_class": integration["hand_class"],
        },
        "artifact_identity": dict(artifact_identity),
        "alternatives": dict(integration["bridge_alternatives"]),
    }
    return bridge_request(request, plan, plan_sha256=plan_sha256)


def bridge_integration_file(
    integration: Mapping[str, Any],
    *,
    artifact_identity: Mapping[str, Any],
    plan_path: Path,
) -> dict[str, Any]:
    plan_path = Path(plan_path)
    return bridge_integration_to_generation(
        integration,
        artifact_identity=artifact_identity,
        plan=load_json(plan_path),
        plan_sha256=sha256_path(plan_path),
    )

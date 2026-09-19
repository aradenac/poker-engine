#!/usr/bin/env python3
"""#357 orchestration for the #314 Hero preflop ISO EV runner.

This module composes already-merged contracts instead of redefining them:
- #353 legal/exact-support alternatives through the JS contract bridge;
- #198 paired/adaptive common-random-number EV search;
- #322 diagnostics through its JS validator/bridge;
- #332/#320 posterior-reference validation through the Python binding.

The current ticket is integration-only. Tests must use NON_SCIENTIFIC synthetic
providers. A future SCIENTIFIC execution is fail-closed unless the injected
Model A provider explicitly declares ADMITTED_FOR_SIZING_EV.
"""
from __future__ import annotations

import copy
import json
import math
import subprocess
from pathlib import Path
from typing import Any, Mapping

from src.preflop.iso_sizing_posterior_binding import (
    reference_from_posterior_record,
    validate_diagnostics_posterior_bindings,
)
from tools.simulation.paired_adaptive_preflop_ev import (
    AdaptiveBudget,
    PairedSearchError,
    _world_fingerprint,
    run_paired_search,
)

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_BRIDGE = ROOT / "tools/simulation/hero_preflop_iso_contract_bridge.js"

RUNNER_SCHEMA = "poker-hero-preflop-iso-runner-result/v1"
PROVIDER_KIND = "MODEL_A"
ADMITTED = "ADMITTED_FOR_SIZING_EV"
NON_SCIENTIFIC_STATUSES = {
    "NON_SCIENTIFIC_SYNTHETIC",
    "NON_SCIENTIFIC_MOCK",
}
EXECUTION_MODES = {"NON_SCIENTIFIC", "SCIENTIFIC"}
DIAGNOSTIC_WORLDS_SCHEMA = "poker-preflop-iso-sizing-diagnostic-worlds/v1"
DIAGNOSTIC_SCIENTIFIC_EFFECT = "NONE_INTEGRATION_CONTRACT_ONLY"


class HeroPreflopIsoRunnerError(ValueError):
    pass


def _fail(message: str) -> None:
    raise HeroPreflopIsoRunnerError(message)


def _finite(value: Any, name: str) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise HeroPreflopIsoRunnerError(f"{name} must be numeric") from exc
    if not math.isfinite(value):
        _fail(f"{name} must be finite")
    return value


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _node_bridge(command: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    proc = subprocess.run(
        ["node", str(CONTRACT_BRIDGE), command],
        cwd=ROOT,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        _fail(f"{command} contract bridge failed: {detail}")
    try:
        value = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise HeroPreflopIsoRunnerError(
            f"{command} contract bridge returned invalid JSON"
        ) from exc
    if not isinstance(value, dict):
        _fail(f"{command} contract bridge must return an object")
    return value


def _provider_metadata(provider: Any, execution_mode: str) -> dict[str, Any]:
    if provider is None:
        _fail("Model A provider is required")
    raw = getattr(provider, "metadata", None)
    raw = raw() if callable(raw) else raw
    if not isinstance(raw, Mapping):
        _fail("Model A provider.metadata must be an object or zero-argument method")
    metadata = copy.deepcopy(dict(raw))
    if str(metadata.get("provider_kind") or "").upper() != PROVIDER_KIND:
        _fail("provider_kind must be MODEL_A")
    identity = metadata.get("identity")
    if not isinstance(identity, Mapping):
        _fail("provider identity is required")
    for key in ("population_id", "model_id", "model_version", "source_id"):
        if not str(identity.get(key) or "").strip():
            _fail(f"provider identity.{key} is required")
    admission = str(metadata.get("admission_status") or "").upper()
    effect = str(metadata.get("scientific_effect") or "").upper()
    if execution_mode == "SCIENTIFIC":
        if admission != ADMITTED:
            _fail("SCIENTIFIC execution requires Model A ADMITTED_FOR_SIZING_EV")
        if effect not in {"SCIENTIFIC", "SCIENTIFIC_ADMITTED"}:
            _fail("admitted scientific provider must declare scientific_effect")
    else:
        if admission not in NON_SCIENTIFIC_STATUSES:
            _fail(
                "NON_SCIENTIFIC execution requires explicit synthetic/mock admission status"
            )
        if effect != "NON_SCIENTIFIC":
            _fail("synthetic/mock provider must declare scientific_effect=NON_SCIENTIFIC")
    for method in ("materialize_world", "evaluate_alternative"):
        if not callable(getattr(provider, method, None)):
            _fail(f"Model A provider must implement {method}()")
    return metadata


def _enumerate(
    *,
    state_snapshot: Mapping[str, Any],
    requested_raise_targets_bb: list[float],
    exact_support: Mapping[str, Any],
    position_by_player: Mapping[str, str] | None,
) -> dict[str, Any]:
    if state_snapshot.get("schema") != "nlhe-game-state/v1":
        _fail("state_snapshot must use nlhe-game-state/v1")
    if str(state_snapshot.get("street") or "").lower() != "preflop":
        _fail("runner is preflop-only")
    if state_snapshot.get("board"):
        _fail("preflop public state cannot contain future board cards")
    return _node_bridge(
        "enumerate",
        {
            "state_snapshot": dict(state_snapshot),
            "requested_raise_targets_bb": list(requested_raise_targets_bb),
            "exact_support": dict(exact_support),
            "position_by_player": dict(position_by_player or {}),
        },
    )


def _comparable_alternatives(
    enumeration: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    payloads: dict[str, dict[str, Any]] = {}
    unsupported: list[str] = []
    for raw in enumeration.get("alternatives") or []:
        row = copy.deepcopy(dict(raw))
        alt_id = str(row.get("id") or "")
        if not alt_id:
            _fail("enumerated alternative id is required")
        status = str((row.get("support") or {}).get("status") or "").upper()
        if row.get("action") == "ISO" and status == "LEGAL_BUT_UNSUPPORTED":
            unsupported.append(alt_id)
            continue
        if row.get("action") == "ISO" and status != "EXACT_SUPPORTED":
            _fail(f"{alt_id} ISO sizing is not exact-supported")
        payloads[alt_id] = row
    if not payloads:
        _fail("no comparable alternatives remain after exact-support filtering")
    return payloads, unsupported


def _canonical_alt(
    raw: Mapping[str, Any],
    paired: Mapping[str, Any] | None,
    *,
    non_scientific: bool,
) -> dict[str, Any]:
    target = None
    if isinstance(raw.get("target_sizing"), Mapping):
        target = raw["target_sizing"].get("target_total_bb")
    row = copy.deepcopy(dict(raw))
    row["target_total_bb"] = target
    if paired is None:
        row["ev_bb"] = None
        row["uncertainty"] = None
        row["confidence"] = None
        row["comparable"] = False
        row["comparability_reason"] = "LEGAL_BUT_UNSUPPORTED_EXACT_PRICE_REQUIRED"
        row["paired_delta_vs_selected"] = None
        return row
    row["ev_bb"] = paired["ev_bb"]
    row["uncertainty"] = {
        "monte_carlo": {
            "method": "PAIRED_COMMON_RANDOM_NUMBERS",
            "samples": paired["samples"],
            "standard_error_bb": paired["standard_error_bb"],
            "ci95_low_bb": paired["ci_lower_bb"],
            "ci95_high_bb": paired["ci_upper_bb"],
        },
        "model": {
            "status": (
                "NON_SCIENTIFIC_SYNTHETIC"
                if non_scientific
                else "SCIENTIFIC_PROVIDER_ADMITTED"
            ),
            "method": "INJECTED_MODEL_A_PROVIDER",
        },
    }
    row["confidence"] = None
    row["comparable"] = True
    row["comparability_reason"] = "PAIRED_EV_AVAILABLE"
    row["paired_delta_vs_selected"] = copy.deepcopy(
        paired["paired_delta_vs_selected"]
    )
    return row


def _max_ev_id(decision_alternatives: list[Mapping[str, Any]]) -> str:
    comparable = [
        row
        for row in decision_alternatives
        if row.get("comparable") is True and row.get("ev_bb") is not None
    ]
    if not comparable:
        _fail("no comparable EV alternatives")
    return min(
        comparable,
        key=lambda row: (-_finite(row["ev_bb"], f"{row['id']}.ev_bb"), str(row["id"])),
    )["id"]


def _indifference(
    decision_alternatives: list[Mapping[str, Any]], selected_id: str
) -> list[dict[str, Any]]:
    out = []
    for row in decision_alternatives:
        if row["id"] == selected_id:
            status = "SELECTED_MAX_EV"
            stats = row.get("paired_delta_vs_selected")
        elif row.get("comparable") is not True:
            status = "UNSUPPORTED_NOT_COMPARED"
            stats = None
        else:
            stats = row.get("paired_delta_vs_selected") or {}
            low = stats.get("ci_lower_bb")
            high = stats.get("ci_upper_bb")
            if low is None or high is None:
                status = "INSUFFICIENT_PAIRED_EVIDENCE"
            elif float(low) <= 0 <= float(high):
                status = "STATISTICALLY_INDISTINGUISHABLE"
            elif float(high) < 0:
                status = "STATISTICALLY_SEPARATED_LOWER_EV"
            else:
                status = "FAIL_CLOSED_UNEXPECTED_RELATION"
        out.append(
            {
                "alternative_id": row["id"],
                "status": status,
                "paired_delta_vs_selected": copy.deepcopy(stats),
            }
        )
    if any(x["status"] == "FAIL_CLOSED_UNEXPECTED_RELATION" for x in out):
        _fail("paired relation contradicts max-EV selection")
    return out


def run_hero_preflop_iso(
    *,
    state_snapshot: Mapping[str, Any],
    public_state_fingerprint: str,
    requested_raise_targets_bb: list[float],
    exact_support: Mapping[str, Any],
    provider: Any,
    decision_id: str,
    base_seed: int | str,
    budget: AdaptiveBudget,
    execution_mode: str = "NON_SCIENTIFIC",
    position_by_player: Mapping[str, str] | None = None,
    public_context_extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble one #314-style decision without consuming scientific data itself."""

    mode = str(execution_mode or "").upper()
    if mode not in EXECUTION_MODES:
        _fail(f"execution_mode must be one of {sorted(EXECUTION_MODES)}")
    metadata = _provider_metadata(provider, mode)
    decision_id = str(decision_id or "").strip()
    if not decision_id:
        _fail("decision_id is required")
    public_state_fingerprint = str(public_state_fingerprint or "").strip()
    if not public_state_fingerprint:
        _fail("public_state_fingerprint is required")

    enumeration = _enumerate(
        state_snapshot=state_snapshot,
        requested_raise_targets_bb=requested_raise_targets_bb,
        exact_support=exact_support,
        position_by_player=position_by_player,
    )
    if enumeration.get("exact_support", {}).get("nearest_price_used") is not False:
        _fail("nearest-price substitution is forbidden")
    if enumeration.get("exact_support", {}).get("no_silent_nearest_price") is not True:
        _fail("exact support must explicitly forbid nearest-price substitution")
    info = enumeration.get("information_boundary") or {}
    if (
        info.get("future_cards_consumed") is not False
        or info.get("opponent_hole_cards_consumed") is not False
        or info.get("recommendation_consumed") is not False
    ):
        _fail("legal-alternative enumerator violated information boundary")

    candidate_payloads, unsupported_ids = _comparable_alternatives(enumeration)
    exact_values = {"FOLD": 0.0} if "FOLD" in candidate_payloads else {}

    public_context = {
        "state_snapshot": copy.deepcopy(dict(state_snapshot)),
        "public_state_fingerprint": public_state_fingerprint,
        "context_id": enumeration["context_id"],
        "provider_identity": copy.deepcopy(dict(metadata["identity"])),
        **copy.deepcopy(dict(public_context_extra or {})),
    }

    diagnostic_observations: dict[str, list[dict[str, Any]]] = {
        cid: []
        for cid, payload in candidate_payloads.items()
        if payload.get("action") == "ISO"
    }
    posterior_catalog: dict[str, dict[str, Any]] = {}
    posterior_records: dict[str, dict[str, Any]] = {}

    def world_factory(
        public: Mapping[str, Any],
        bound_decision_id: str,
        sample_index: int,
        seed: int,
    ) -> Mapping[str, Any]:
        world = provider.materialize_world(
            copy.deepcopy(public),
            bound_decision_id,
            int(sample_index),
            int(seed),
        )
        if not isinstance(world, Mapping):
            _fail("provider.materialize_world must return an object")
        return copy.deepcopy(dict(world))

    def evaluator(
        world: Mapping[str, Any],
        candidate_id: str,
        payload: Mapping[str, Any],
    ) -> float:
        result = provider.evaluate_alternative(
            copy.deepcopy(dict(world)),
            copy.deepcopy(dict(payload)),
        )
        if not isinstance(result, Mapping):
            _fail("provider.evaluate_alternative must return an object")
        ev = _finite(result.get("ev_bb"), f"{candidate_id}.ev_bb")
        fingerprint = _world_fingerprint(world)
        reported = result.get("world_fingerprint_sha256")
        if reported is not None and str(reported) != fingerprint:
            _fail(f"{candidate_id} diagnostics world differs from EV world")

        if payload.get("action") == "ISO":
            continuers_out = []
            continuers = result.get("continuers")
            if not isinstance(continuers, list):
                _fail(f"{candidate_id} ISO result must provide continuers")
            for continuer in continuers:
                if not isinstance(continuer, Mapping):
                    _fail(f"{candidate_id} continuer must be an object")
                position = str(continuer.get("position") or "").upper()
                response = str(continuer.get("response") or "").upper()
                ref_id = str(continuer.get("posterior_ref_id") or "")
                record = continuer.get("posterior_record")
                if not position or response not in {"CALL", "3BET", "JAM"} or not ref_id:
                    _fail(f"{candidate_id} invalid continuer identity")
                if not isinstance(record, Mapping):
                    _fail(f"{candidate_id} continuer requires full #320 posterior_record")
                full = copy.deepcopy(dict(record))
                reference = reference_from_posterior_record(ref_id, full)
                old_full = posterior_records.get(ref_id)
                if old_full is not None and _canonical(old_full) != _canonical(full):
                    _fail(f"posterior record drift for {ref_id}")
                old_ref = posterior_catalog.get(ref_id)
                if old_ref is not None and _canonical(old_ref) != _canonical(reference):
                    _fail(f"posterior reference drift for {ref_id}")
                posterior_records[ref_id] = full
                posterior_catalog[ref_id] = reference
                continuers_out.append(
                    {
                        "position": position,
                        "response": response,
                        "posterior_ref_id": ref_id,
                    }
                )
            sample_index = int(world.get("sample_index"))
            diagnostic_observations[candidate_id].append(
                {
                    "sample_index": sample_index,
                    "world_fingerprint_sha256": fingerprint,
                    "continuers": continuers_out,
                }
            )
        return ev

    try:
        paired = run_paired_search(
            candidate_payloads,
            decision_id=decision_id,
            public_context=public_context,
            world_factory=world_factory,
            evaluator=evaluator,
            base_seed=base_seed,
            budget=budget,
            exact_values=exact_values,
            adaptive=True,
        )
    except PairedSearchError as exc:
        raise HeroPreflopIsoRunnerError(str(exc)) from exc

    enumeration_by_id = {
        str(row["id"]): row for row in enumeration.get("alternatives") or []
    }
    decision_alternatives: list[dict[str, Any]] = []
    for raw in enumeration.get("alternatives") or []:
        alt_id = str(raw["id"])
        decision_alternatives.append(
            _canonical_alt(
                raw,
                paired["alternatives"].get(alt_id),
                non_scientific=(mode == "NON_SCIENTIFIC"),
            )
        )

    max_ev = _max_ev_id(decision_alternatives)
    if paired["selected_id"] != max_ev:
        _fail(
            f"paired/adaptive selected {paired['selected_id']} but point max-EV is {max_ev}"
        )
    selected = next(row for row in decision_alternatives if row["id"] == max_ev)
    decision = {
        "schema": "poker-preflop-decision/v1",
        "contract_profile": "CANONICAL_RUNTIME_DECISION_V1",
        "status": "EXPERIMENTAL",
        "decision_id": decision_id,
        "context_id": enumeration["context_id"],
        "public_state_fingerprint": public_state_fingerprint,
        "population_id": metadata["identity"]["population_id"],
        "ev_reference": "decision_point_incremental_bb",
        "selected_id": max_ev,
        "action": selected["action"],
        "target_total_bb": selected["target_total_bb"],
        "bet_to_bb": selected["target_total_bb"],
        "incremental_cost_bb": selected["incremental_cost_bb"],
        "ev_bb": selected["ev_bb"],
        "support": copy.deepcopy(selected["support"]),
        "uncertainty": copy.deepcopy(selected["uncertainty"]),
        "alternatives": decision_alternatives,
        "search": {
            "source_schema": paired["schema"],
            "pairing_contract": paired["search"]["pairing_contract"],
            "candidate_ids": list(candidate_payloads),
            "unsupported_ids": unsupported_ids,
            "sizing_grid_source": enumeration["exact_support"].get("source_id"),
            "nearest_price_used": False,
            "base_seed": str(base_seed),
            "rollout_budget_used": paired["search"]["rollout_budget_used"],
        },
        "recommendation_admissibility": {
            "hero_recommendation_allowed": mode == "SCIENTIFIC",
            "status": (
                "SCIENTIFIC_PROVIDER_ADMITTED"
                if mode == "SCIENTIFIC"
                else "NON_SCIENTIFIC_INTEGRATION_ONLY"
            ),
        },
    }

    support_by_alt = {
        cid: copy.deepcopy(enumeration_by_id[cid]["support"])
        for cid in diagnostic_observations
    }
    synthetic = mode == "NON_SCIENTIFIC"
    diagnostic_worlds = {
        "schema": DIAGNOSTIC_WORLDS_SCHEMA,
        "synthetic_fixture": synthetic,
        "support_by_alternative": support_by_alt,
        "alternatives": diagnostic_observations,
        "posterior_catalog": posterior_catalog,
        "execution_boundary": {
            "mode": mode,
            "model_a_admission_status": metadata["admission_status"],
        },
        "provenance": {
            "scientific_effect": DIAGNOSTIC_SCIENTIFIC_EFFECT,
            "synthetic_fixture": synthetic,
            "provider_identity": copy.deepcopy(dict(metadata["identity"])),
        },
    }
    diagnostics_bridge = _node_bridge(
        "diagnostics",
        {
            "decision": decision,
            "evaluated_ids": list(candidate_payloads),
            "paired_result": paired,
            "diagnostic_worlds": diagnostic_worlds,
        },
    )
    posterior_binding = validate_diagnostics_posterior_bindings(
        diagnostics_bridge["artifact"], posterior_records
    )

    indifference = _indifference(decision_alternatives, max_ev)
    return {
        "schema": RUNNER_SCHEMA,
        "execution_mode": mode,
        "scientific_effect": (
            "NONE_SYNTHETIC_INTEGRATION"
            if mode == "NON_SCIENTIFIC"
            else "SCIENTIFIC_PROVIDER_ADMITTED"
        ),
        "provider": metadata,
        "legal_alternatives": enumeration,
        "decision": decision,
        "paired_result": paired,
        "paired_deltas": copy.deepcopy(paired["pairwise_deltas"]),
        "statistical_indifference": indifference,
        "diagnostics": diagnostics_bridge["artifact"],
        "resolved": diagnostics_bridge["resolved"],
        "posterior_binding": posterior_binding,
        "information_boundary": {
            "future_cards_consumed": False,
            "opponent_hole_cards_consumed": False,
            "nearest_price_used": False,
        },
        "scientific_boundary": {
            "validation_consumed": False,
            "test_consumed": False,
            "model_a_modified": False,
            "model_b_modified": False,
            "promotion_performed": False,
            "ui_modified": False,
        },
    }

#!/usr/bin/env python3
"""#419 hierarchical exact-context sizing likelihood contract regressions.

The contract is candidate-only and TRAIN/synthetic-only.  These tests never
parse a hand history, never read a holdout split and never touch an active
model.  They exercise the exact-key resolution API, the support isolation rule,
the fail-closed behaviour and the machine-readable pooling/uncertainty
provenance.
"""
from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.preflop.context_contract import build_context  # noqa: E402
from tools.preflop.model_a_sizing_hierarchical import (  # noqa: E402
    ALPHA_PER_LEGAL_ACTION,
    CANDIDATE_ID,
    GATE_POOLING_LEVEL,
    GATE_REASON_BY_ID,
    GATE_UNCERTAINTY,
    KAPPA0,
    LAYER_A_EXACT_EMPIRICAL_SUPPORT,
    LAYER_B_EXACT_CONTEXT_ESTIMATE_ADMISSIBILITY,
    LAYER_B_GATES,
    LEVEL_SPECS,
    MIN_DISTINCT_HANDS,
    MIN_MARGINAL_OBSERVATIONS,
    NEVER_MUTUALIZABLE_AXES,
    NODE_CLOSURE_RULE_ID,
    POOLING_LEVELS,
    REASON_NO_ADMISSIBLE_POOLING,
    REASON_NO_EXACT_SUPPORT_NO_CONTEXT,
    REASON_RAISE_SIZING_UNRESOLVED,
    STATUS_EXACT_EMPIRICAL_STRONG,
    STATUS_EXACT_HIERARCHICAL_ESTIMATE,
    STATUS_EXACT_UNRESOLVED,
    SUPPORT_ISOLATION_RULE,
    SUPPORT_LEVEL,
    HierarchicalSizingError,
    SupportIsolationError,
    admissibility_block,
    assert_support_isolation,
    canonical_candidate_sha256,
    canonical_response_sha256,
    effective_sample_size_block,
    empirical_support_block,
    hierarchical_exact_key,
    hierarchical_exact_key_from_whitelist,
    hierarchical_public_whitelist,
    level_key,
    level_keys,
    make_synthetic_hierarchical_candidate,
    pooling_provenance_block,
    resolve_exact_context,
    runtime_exact_preflop_node_key,
    uncertainty_is_machine_readable,
    validate_candidate,
    validate_response,
)
from tools.preflop.model_a_sizing_likelihood import (  # noqa: E402
    CANDIDATE_IDS as EXACT_PRICE_CANDIDATE_IDS,
    sizing_context_key,
    support_context_key,
)
from tools.training.audit_model_a_exact_tree import (  # noqa: E402
    exact_key as audit_exact_key,
    public_context as audit_public_context,
    runtime_exact_preflop_node_key as audit_node_key,
)

FIXTURE = json.loads(
    (ROOT / "tests/fixtures/model_a_preflop_sizing_cases.json").read_text(encoding="utf-8")
)
BASE_INPUT = FIXTURE["contexts"][0]["input"]
POPULATION = FIXTURE["population_id"]
LEGAL = ["FOLD", "CALL", "RAISE", "JAM"]


def _context(**overrides):
    payload = copy.deepcopy(BASE_INPUT)
    for key, value in overrides.items():
        payload[key] = value
    return build_context(**payload)


def _stack_variant(stack_bb):
    stacks = dict(BASE_INPUT["stack_bb_by_position"])
    stacks["BB"] = stack_bb
    return _context(stack_bb_by_position=stacks)


def _price_variant(price, pot, min_raise):
    contributions = dict(BASE_INPUT["contribution_bb_by_position"])
    contributions["SB"] = price
    return _context(
        contribution_bb_by_position=contributions,
        current_price_bb=price,
        pot_before_bb=pot,
        min_raise_to_bb=min_raise,
    )


def _aggressor_variant(position):
    """The same BB spot facing a raise from a different position."""
    history = [dict(row) for row in BASE_INPUT["history"]]
    history[-1] = {"position": position, "action": "RAISE"}
    contributions = dict(BASE_INPUT["contribution_bb_by_position"])
    contributions["SB"] = 1.0
    contributions[position] = 4.0
    return _context(
        history=history,
        contribution_bb_by_position=contributions,
        current_price_bb=4.0,
        pot_before_bb=7.0,
        min_raise_to_bb=7.0,
    )


def _limper_variant():
    """The same BB spot with one limper instead of two."""
    history = [dict(BASE_INPUT["history"][0]), dict(BASE_INPUT["history"][2])]
    contributions = dict(BASE_INPUT["contribution_bb_by_position"])
    contributions["HJ"] = 0.0
    return _context(history=history, contribution_bb_by_position=contributions)


def _caller_variant():
    """The same BB spot with a caller behind the aggressor."""
    history = [dict(row) for row in BASE_INPUT["history"]]
    history.append({"position": "BTN", "action": "CALL"})
    return _context(history=history)


def _rows(context, hand_prefix, count, target):
    actions = ["FOLD", "CALL", "RAISE", "JAM"]
    rows = []
    for index in range(count):
        action = actions[index % len(actions)]
        rows.append(
            {
                "context": context,
                "hand_id": f"{hand_prefix}-{index}",
                "action": action,
                "target_total_bb": target if action in ("RAISE", "JAM") else None,
            }
        )
    return rows


def _audit_row(context):
    """The #388 audit row shape for the same public state."""
    return {
        "family": context["family"],
        "actor_position": context["actor_position"],
        "history": context["history"],
        "current_price_bb": context["current_price_bb"],
        "to_call_bb": context["to_call_bb"],
        "table_size": context["table_size"],
        "raise_level": context["raise_level"],
        "live_positions": context["live_positions"],
        "all_in_positions": context["all_in_positions"],
        "pot_before_bb": context["pot_before_bb"],
        "effective_stack_bb": context["effective_stack_bb"],
    }


def _is_type(value, name):
    if name == "object":
        return isinstance(value, dict)
    if name == "array":
        return isinstance(value, list)
    if name == "string":
        return isinstance(value, str)
    if name == "boolean":
        return isinstance(value, bool)
    if name == "null":
        return value is None
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    raise AssertionError(f"unsupported contract type: {name}")


def _contract_errors(node, value, root, path="$"):
    """A tiny stdlib checker for the JSON-Schema subset this contract uses."""
    if "$ref" in node:
        target = root
        for part in node["$ref"].lstrip("#/").split("/"):
            target = target[part]
        return _contract_errors(target, value, root, path)
    errors = []
    expected = node.get("type")
    if expected is not None:
        allowed = expected if isinstance(expected, list) else [expected]
        if not any(_is_type(value, name) for name in allowed):
            errors.append(f"{path}: expected {allowed}, got {type(value).__name__}")
            return errors
    if "const" in node and value != node["const"]:
        errors.append(f"{path}: const {node['const']!r} != {value!r}")
    if "enum" in node and value not in node["enum"]:
        errors.append(f"{path}: {value!r} not in enum")
    if isinstance(value, dict):
        for key in node.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required {key}")
        properties = node.get("properties", {})
        extra = sorted(set(value) - set(properties))
        if extra and node.get("additionalProperties") is False:
            errors.append(f"{path}: unexpected keys {extra}")
        for key, sub in properties.items():
            if key in value:
                errors.extend(_contract_errors(sub, value[key], root, f"{path}.{key}"))
        additional = node.get("additionalProperties")
        if isinstance(additional, dict):
            for key, child in value.items():
                if key not in properties:
                    errors.extend(_contract_errors(additional, child, root, f"{path}.{key}"))
        if "minProperties" in node and len(value) < node["minProperties"]:
            errors.append(f"{path}: too few properties")
    if isinstance(value, list):
        if "minItems" in node and len(value) < node["minItems"]:
            errors.append(f"{path}: too few items")
        if "maxItems" in node and len(value) > node["maxItems"]:
            errors.append(f"{path}: too many items")
        for index, child in enumerate(value):
            if "items" in node:
                errors.extend(_contract_errors(node["items"], child, root, f"{path}[{index}]"))
    if isinstance(value, str) and "pattern" in node and not re.search(node["pattern"], value):
        errors.append(f"{path}: pattern mismatch")
    if _is_type(value, "number") or _is_type(value, "integer"):
        if "minimum" in node and value < node["minimum"]:
            errors.append(f"{path}: below minimum")
        if "maximum" in node and value > node["maximum"]:
            errors.append(f"{path}: above maximum")
        if "exclusiveMinimum" in node and value <= node["exclusiveMinimum"]:
            errors.append(f"{path}: not above exclusiveMinimum")
        if "exclusiveMaximum" in node and value >= node["exclusiveMaximum"]:
            errors.append(f"{path}: not below exclusiveMaximum")
    return errors


def test_candidate_identity_is_distinct_candidate_only_and_not_active():
    candidate = make_synthetic_hierarchical_candidate(
        population_id=POPULATION,
        observations=_rows(_context(), "id", MIN_MARGINAL_OBSERVATIONS, 7.0),
    )
    validate_candidate(candidate)
    identity = candidate["identity"]
    assert identity["candidate_id"] == CANDIDATE_ID
    assert identity["candidate_id"] not in EXACT_PRICE_CANDIDATE_IDS
    assert identity["model_family"] == "MODEL_A_PREFLOP"
    assert identity["status"] == "CANDIDATE_ONLY_NOT_ACTIVE"
    assert identity["active_model_replaced"] is False
    assert identity["identity_granularity"] == "hierarchical_exact_key"
    assert identity["support_isolation_rule"] == SUPPORT_ISOLATION_RULE
    assert candidate["nearest_price_fallback"] is False
    assert candidate["nearest_context_fallback"] is False
    assert candidate["representative_price_fallback"] is False
    assert candidate["exact_context_granularity"] == "hierarchical_exact_key"
    assert candidate["shrinkage"]["kappa0"] == KAPPA0
    assert candidate["shrinkage"]["alpha_per_legal_marginal_action"] == ALPHA_PER_LEGAL_ACTION
    assert candidate["thresholds"]["minimum_marginal_observations"] == MIN_MARGINAL_OBSERVATIONS
    assert candidate["thresholds"]["minimum_distinct_hands"] == MIN_DISTINCT_HANDS
    assert candidate["pooling_levels"][0]["support_source_allowed"] is True
    for level in candidate["pooling_levels"][1:]:
        assert level["support_source_allowed"] is False


def test_exact_key_is_byte_identical_to_the_issue_388_audit_key():
    for context in (_context(), _stack_variant(60.0), _price_variant(6.0, 9.0, 11.0)):
        whitelist = hierarchical_public_whitelist(context)
        assert whitelist == audit_public_context(_audit_row(context))
        assert hierarchical_exact_key(context) == audit_exact_key(whitelist)
        assert runtime_exact_preflop_node_key(context) == audit_node_key(whitelist)
    key = hierarchical_exact_key(_context())
    assert key.startswith("MAPSUP_") and "|public=" in key
    assert len(key.rsplit("|public=", 1)[1]) == 64
    assert key != support_context_key(hierarchical_public_whitelist(_context()))
    assert sizing_context_key(hierarchical_public_whitelist(_context())).startswith("MAPSIZ_")


def test_actor_aggressor_limper_caller_and_price_mismatches_are_distinct_keys():
    base = _context()
    whitelist = hierarchical_public_whitelist(base)
    variants = {
        "actor_position": "BTN",
        "aggressor_position": "BTN",
        "limper_count": 1,
        "caller_count": 1,
        "target_total_bb": 6.0,
        "to_call_bb": 2.0,
    }
    for axis, value in variants.items():
        probe = dict(whitelist, **{axis: value})
        # the exact key (L0) is never blind to a public axis
        assert hierarchical_exact_key_from_whitelist(probe) != hierarchical_exact_key(base), axis
        assert level_key("L0_EXACT_KEY", probe) != level_key("L0_EXACT_KEY", whitelist), axis
        for spec in LEVEL_SPECS:
            # a level key splits on exactly the axes it retains; the frozen
            # never-mutualizable axes are retained on every level
            if axis not in spec["key_axes"]:
                assert axis in spec["drops"], (axis, spec["level"])
                continue
            assert level_key(spec["level"], probe) != level_key(spec["level"], whitelist), (
                axis,
                spec["level"],
            )
    # the same mismatches through live public contexts, not just whitelists
    live = [base, _aggressor_variant("BTN"), _limper_variant(), _caller_variant(),
            _price_variant(6.0, 9.0, 11.0)]
    keys = [hierarchical_exact_key(context) for context in live]
    assert len(set(keys)) == len(live)
    for spec in LEVEL_SPECS:
        assert "requested_key_identity" in spec["retains"]
        assert "requested_key_identity" not in spec["drops"]
        assert "requested_key_identity" not in spec["key_axes"]


def test_no_nearest_context_substitution_between_distinct_exact_keys():
    base = _context()
    other = _aggressor_variant("BTN")
    candidate = make_synthetic_hierarchical_candidate(
        population_id=POPULATION,
        observations=_rows(base, "base", MIN_MARGINAL_OBSERVATIONS, 7.0),
    )
    assert resolve_exact_context(candidate=candidate, context=base)["status"] == (
        STATUS_EXACT_EMPIRICAL_STRONG
    )
    response = resolve_exact_context(candidate=candidate, context=other, legal_actions=LEGAL)
    validate_response(response)
    assert response["status"] == STATUS_EXACT_UNRESOLVED
    assert response["support"]["observations"] == 0
    assert response["support"]["source_key"] == response["requested_key"]
    assert response["posterior"] is None
    assert response["pooling"] is None
    assert response["granularity"]["nearest_context_lookup"] is False
    assert all(band["source_observations"] == 0 for band in response["pooling_diagnostics"])
    # the two contexts are distinct at every level, so not even a parent can answer
    for level in POOLING_LEVELS:
        assert level_key(level, base) != level_key(level, other), level


def test_level_keys_freeze_the_never_mutualizable_axes_and_L3_is_the_runtime_key():
    context = _context()
    whitelist = hierarchical_public_whitelist(context)
    keys = level_keys(context)
    assert tuple(keys) == POOLING_LEVELS
    assert keys["L0_EXACT_KEY"] == hierarchical_exact_key(context)
    assert keys["L3_RUNTIME_SUPPORT_CONTEXT"] == support_context_key(whitelist)
    # requested_key_identity is the answered question, retained on every level
    # but never a level-key composition dimension; the four positional/price
    # axes are frozen into every level key.
    frozen_key_axes = (
        "actor_position",
        "aggressor_position",
        "target_total_bb",
        "to_call_bb",
    )
    for spec in LEVEL_SPECS:
        assert set(NEVER_MUTUALIZABLE_AXES).issubset(set(spec["retains"]))
        assert set(frozen_key_axes).issubset(set(spec["key_axes"]))
        assert "requested_key_identity" in spec["retains"]
        assert "requested_key_identity" not in spec["key_axes"]
        assert not (set(NEVER_MUTUALIZABLE_AXES) & set(spec["drops"]))
    sibling = _stack_variant(60.0)
    sibling_keys = level_keys(sibling)
    assert keys["L0_EXACT_KEY"] != sibling_keys["L0_EXACT_KEY"]
    assert keys["L1_STACK_POOL"] == sibling_keys["L1_STACK_POOL"]
    other_price = level_keys(_price_variant(6.0, 9.0, 11.0))
    for level in POOLING_LEVELS:
        assert keys[level] != other_price[level]
    assert level_key("L2_POT_POOL", _context(pot_before_bb=13.0)) == keys["L2_POT_POOL"]
    assert level_key("L1_STACK_POOL", _context(pot_before_bb=13.0)) != keys["L1_STACK_POOL"]


def test_exact_strong_requires_both_thresholds_at_l0_with_exact_support_only():
    context = _context()
    candidate = make_synthetic_hierarchical_candidate(
        population_id=POPULATION,
        observations=_rows(context, "strong", MIN_MARGINAL_OBSERVATIONS, 7.0),
    )
    response = resolve_exact_context(candidate=candidate, context=context)
    validate_response(response)
    assert response["status"] == STATUS_EXACT_EMPIRICAL_STRONG
    assert response["reason_code"] == STATUS_EXACT_EMPIRICAL_STRONG
    assert response["posterior"] is not None
    assert response["support"]["observations"] == MIN_MARGINAL_OBSERVATIONS
    assert response["support"]["distinct_hands"] == MIN_DISTINCT_HANDS
    assert response["support"]["effective_sample_size"] == float(MIN_DISTINCT_HANDS)
    assert response["support"]["action_counts"] == {"FOLD": 5, "CALL": 5, "RAISE": 5, "JAM": 5}
    assert response["support"]["source_key"] == response["requested_key"]
    assert response["support"]["borrowed_from_other_keys"] is False
    assert response["pooling"]["level"] == SUPPORT_LEVEL
    assert response["pooling"]["weight_exact"] == 1.0
    assert response["pooling"]["source_key"] == response["requested_key"]
    assert response["uncertainty"]["level_used"] == SUPPORT_LEVEL
    assert abs(sum(response["posterior"].values()) - 1.0) < 1e-9
    short = make_synthetic_hierarchical_candidate(
        population_id=POPULATION,
        observations=_rows(context, "short", MIN_MARGINAL_OBSERVATIONS - 1, 7.0),
    )
    unresolved = resolve_exact_context(candidate=short, context=context)
    assert unresolved["status"] == STATUS_EXACT_UNRESOLVED
    assert unresolved["unresolved_reason"] == REASON_NO_ADMISSIBLE_POOLING
    assert unresolved["posterior"] is None
    assert unresolved["uncertainty"] is None


def test_frozen_20_20_thresholds_are_neither_lowered_nor_widened():
    context = _context()
    candidate = make_synthetic_hierarchical_candidate(
        population_id=POPULATION,
        observations=_rows(context, "threshold", MIN_MARGINAL_OBSERVATIONS, 7.0),
    )
    validate_candidate(candidate)
    assert candidate["thresholds"] == {
        "minimum_marginal_observations": MIN_MARGINAL_OBSERVATIONS,
        "minimum_distinct_hands": MIN_DISTINCT_HANDS,
    }
    assert candidate["thresholds"] == {
        "minimum_marginal_observations": 20,
        "minimum_distinct_hands": 20,
    }
    # A candidate that moves either frozen threshold is refused outright, so the
    # 20/20 rule can be neither lowered nor widened.
    for field in ("minimum_marginal_observations", "minimum_distinct_hands"):
        for value in (19, 0, 1, MIN_MARGINAL_OBSERVATIONS + 1):
            broken = copy.deepcopy(candidate)
            broken["thresholds"][field] = value
            try:
                validate_candidate(broken)
            except HierarchicalSizingError:
                continue
            raise AssertionError(f"a candidate may not move {field} to {value}")

    exact = resolve_exact_context(candidate=candidate, context=context)
    validate_response(exact)
    assert exact["status"] == STATUS_EXACT_EMPIRICAL_STRONG
    assert exact["pooling"]["level"] == SUPPORT_LEVEL
    assert exact["support"]["observations"] == MIN_MARGINAL_OBSERVATIONS
    assert exact["support"]["distinct_hands"] == MIN_DISTINCT_HANDS
    assert exact["support"]["source_key"] == exact["requested_key"]

    # One observation below the marginal threshold, and one *distinct hand* below
    # the distinct-hand threshold, both stay unresolved: the rule is exactly
    # 20 observations / 20 distinct hands, and neither abstention is relabelled as
    # exact support.
    below_observations = resolve_exact_context(
        candidate=make_synthetic_hierarchical_candidate(
            population_id=POPULATION,
            observations=_rows(context, "below", MIN_MARGINAL_OBSERVATIONS - 1, 7.0),
        ),
        context=context,
    )
    validate_response(below_observations)
    assert below_observations["status"] == STATUS_EXACT_UNRESOLVED
    assert below_observations["support"]["observations"] == MIN_MARGINAL_OBSERVATIONS - 1
    assert below_observations["pooling"] is None
    assert below_observations["posterior"] is None

    duplicated = _rows(context, "duplicated", MIN_MARGINAL_OBSERVATIONS, 7.0)
    duplicated[1]["hand_id"] = duplicated[0]["hand_id"]
    below_distinct_hands = resolve_exact_context(
        candidate=make_synthetic_hierarchical_candidate(
            population_id=POPULATION, observations=duplicated
        ),
        context=context,
    )
    validate_response(below_distinct_hands)
    assert below_distinct_hands["status"] == STATUS_EXACT_UNRESOLVED
    assert below_distinct_hands["support"]["observations"] == MIN_MARGINAL_OBSERVATIONS
    assert below_distinct_hands["support"]["distinct_hands"] == MIN_DISTINCT_HANDS - 1
    assert below_distinct_hands["pooling"] is None
    assert below_distinct_hands["posterior"] is None


def test_hierarchical_estimate_reports_pooling_provenance_and_mandatory_uncertainty():
    context = _stack_variant(100.0)
    sibling = _stack_variant(60.0)
    exact_key = hierarchical_exact_key(context)
    observations = [
        {"context": context, "hand_id": "exact-1", "action": "RAISE", "target_total_bb": 7.0}
    ]
    observations += _rows(sibling, "sibling", 21, 9.0)
    candidate = make_synthetic_hierarchical_candidate(
        population_id=POPULATION, observations=observations
    )
    response = resolve_exact_context(candidate=candidate, context=context)
    validate_response(response)
    assert response["status"] == STATUS_EXACT_HIERARCHICAL_ESTIMATE
    assert response["reason_code"] == STATUS_EXACT_HIERARCHICAL_ESTIMATE
    assert response["support"]["observations"] == 1
    assert response["support"]["distinct_hands"] == 1
    assert response["support"]["source_key"] == exact_key
    pooling = response["pooling"]
    assert pooling["level"] == "L1_STACK_POOL"
    assert pooling["source_key"] != exact_key
    assert pooling["source_observations"] == 22
    assert pooling["source_distinct_hands"] == 22
    assert pooling["pooled_axes"] == ["effective_stack_bucket"]
    assert set(NEVER_MUTUALIZABLE_AXES).issubset(set(pooling["retained_axes"]))
    assert pooling["weight_exact"] == round(1 / (1 + KAPPA0), 12)
    assert pooling["parent_dominated"] is True
    uncertainty = response["uncertainty"]
    assert uncertainty is not None
    assert uncertainty["level_used"] == pooling["level"]
    assert uncertainty["effective_sample_size"] == 22.0
    assert set(uncertainty["actions"]) == set(response["posterior"])
    for action, band in uncertainty["actions"].items():
        assert band["credible_interval"]["low"] <= band["mean"] <= band["credible_interval"]["high"]
        assert band["mean"] == response["posterior"][action]
        assert band["std_error"] >= 0.0
    broken = copy.deepcopy(response)
    broken["uncertainty"] = None
    try:
        validate_response(broken)
    except HierarchicalSizingError as exc:
        assert "uncertainty" in str(exc)
    else:
        raise AssertionError("a hierarchical estimate without uncertainty must be rejected")


def test_no_admissible_pooling_fails_closed_with_a_reason_code():
    context = _context()
    candidate = make_synthetic_hierarchical_candidate(
        population_id=POPULATION,
        observations=[
            {"context": context, "hand_id": "only", "action": "RAISE", "target_total_bb": 7.0}
        ],
    )
    response = resolve_exact_context(candidate=candidate, context=context)
    validate_response(response)
    assert response["status"] == STATUS_EXACT_UNRESOLVED
    assert response["reason_code"] == STATUS_EXACT_UNRESOLVED
    assert response["unresolved_reason"] == REASON_NO_ADMISSIBLE_POOLING
    assert response["posterior"] is None
    assert response["uncertainty"] is None
    assert response["reason_detail"]
    assert all(band["qualifies"] is False for band in response["pooling_diagnostics"])
    assert [band["level"] for band in response["pooling_diagnostics"]] == list(POOLING_LEVELS)
    keyless = resolve_exact_context(
        candidate=candidate,
        requested_key=hierarchical_exact_key(_price_variant(9.0, 12.0, 15.0)),
        legal_actions=LEGAL,
    )
    assert keyless["status"] == STATUS_EXACT_UNRESOLVED
    assert keyless["unresolved_reason"] == REASON_NO_EXACT_SUPPORT_NO_CONTEXT
    assert keyless["pooling"] is None


def test_no_nearest_price_substitution_between_4bb_and_6bb():
    four = _context()
    six = _price_variant(6.0, 9.0, 11.0)
    five = _price_variant(5.0, 8.0, 9.0)
    candidate = make_synthetic_hierarchical_candidate(
        population_id=POPULATION,
        observations=_rows(four, "four", MIN_MARGINAL_OBSERVATIONS, 7.0)
        + _rows(six, "six", MIN_MARGINAL_OBSERVATIONS, 11.0),
    )
    assert resolve_exact_context(candidate=candidate, context=four)["status"] == (
        STATUS_EXACT_EMPIRICAL_STRONG
    )
    assert resolve_exact_context(candidate=candidate, context=six)["status"] == (
        STATUS_EXACT_EMPIRICAL_STRONG
    )
    between = resolve_exact_context(candidate=candidate, context=five)
    validate_response(between)
    assert between["status"] == STATUS_EXACT_UNRESOLVED
    assert between["support"]["observations"] == 0
    assert between["posterior"] is None
    assert between["raise_sizing"]["supported_targets"] == []
    assert between["raise_sizing"]["nearest_price_used"] is False
    assert between["raise_sizing"]["representative_price_used"] is False
    assert between["raise_sizing"]["interpolation_used"] is False
    assert between["granularity"]["nearest_price_lookup"] is False
    assert all(band["source_observations"] == 0 for band in between["pooling_diagnostics"])


def test_zero_exact_support_never_borrows_from_a_pooled_parent():
    context = _stack_variant(100.0)
    sibling = _stack_variant(60.0)
    candidate = make_synthetic_hierarchical_candidate(
        population_id=POPULATION,
        observations=_rows(sibling, "sib", MIN_MARGINAL_OBSERVATIONS, 7.0),
    )
    response = resolve_exact_context(candidate=candidate, context=context)
    validate_response(response)
    assert response["status"] == STATUS_EXACT_HIERARCHICAL_ESTIMATE
    assert response["support"]["observations"] == 0
    assert response["support"]["effective_sample_size"] == 0.0
    assert response["support"]["source_key"] == response["requested_key"]
    assert response["pooling"]["source_observations"] == MIN_MARGINAL_OBSERVATIONS
    assert response["pooling"]["source_key"] != response["requested_key"]
    assert response["pooling"]["weight_exact"] == 0.0
    assert response["pooling"]["parent_dominated"] is True
    assert hierarchical_exact_key(context) != hierarchical_exact_key(sibling)
    whitelist = hierarchical_public_whitelist(context)
    assert level_key("L3_RUNTIME_SUPPORT_CONTEXT", whitelist) == level_key(
        "L3_RUNTIME_SUPPORT_CONTEXT", hierarchical_public_whitelist(sibling)
    )


def test_support_isolation_violations_fail_closed():
    try:
        assert_support_isolation(requested_key="MAPSUP_a|public=x", source_key="MAPSUP_b|public=y")
    except SupportIsolationError as exc:
        assert exc.reason_code == "COARSE_KEY_SUPPORT_LAUNDERING"
        assert "COARSE_KEY_SUPPORT_LAUNDERING" in str(exc)
    else:
        raise AssertionError("support from a different key must raise")
    context = _context()
    try:
        make_synthetic_hierarchical_candidate(
            population_id=POPULATION,
            observations=[
                {
                    "context": context,
                    "hand_id": "liar",
                    "action": "CALL",
                    "hierarchical_exact_key": "MAPSUP_deadbeef|public=" + "0" * 64,
                }
            ],
        )
    except HierarchicalSizingError:
        pass
    else:
        raise AssertionError("a mismatched declared exact key must fail closed")
    candidate = make_synthetic_hierarchical_candidate(
        population_id=POPULATION,
        observations=_rows(context, "iso", MIN_MARGINAL_OBSERVATIONS, 7.0),
    )
    response = resolve_exact_context(candidate=candidate, context=context)
    tampered = copy.deepcopy(response)
    tampered["support"]["source_key"] = "MAPSUP_other|public=" + "1" * 64
    try:
        validate_response(tampered)
    except SupportIsolationError:
        pass
    else:
        raise AssertionError("laundered support must be refused")


def test_exact_claim_cannot_use_a_parent_pooling_level():
    context = _context()
    candidate = make_synthetic_hierarchical_candidate(
        population_id=POPULATION,
        observations=_rows(context, "lvl", MIN_MARGINAL_OBSERVATIONS, 7.0),
    )
    response = resolve_exact_context(candidate=candidate, context=context)
    broken = copy.deepcopy(response)
    broken["pooling"]["level"] = "L1_STACK_POOL"
    try:
        validate_response(broken)
    except HierarchicalSizingError as exc:
        assert "L0_EXACT_KEY" in str(exc)
    else:
        raise AssertionError("an exact claim must use L0_EXACT_KEY")


def test_private_or_future_information_is_rejected():
    contaminated = dict(_context())
    contaminated["hole_cards"] = ["Ks", "Ts"]
    try:
        hierarchical_public_whitelist(contaminated)
    except HierarchicalSizingError as exc:
        assert "private" in str(exc).lower() or "card" in str(exc).lower()
    else:
        raise AssertionError("private cards must be rejected")
    try:
        make_synthetic_hierarchical_candidate(
            population_id=POPULATION,
            observations=[
                {
                    "context": _context(),
                    "hand_id": "future",
                    "action": "CALL",
                    "future_cards": ["As"],
                }
            ],
        )
    except HierarchicalSizingError as exc:
        assert "private" in str(exc).lower() or "card" in str(exc).lower()
    else:
        raise AssertionError("future cards must be rejected")


def test_unresolved_raise_frontier_stays_explicitly_unresolved():
    context = _context()
    key = hierarchical_exact_key(context)
    candidate = make_synthetic_hierarchical_candidate(
        population_id=POPULATION,
        observations=_rows(context, "front", MIN_MARGINAL_OBSERVATIONS, 7.0),
        unresolved_raise_frontiers=[key],
    )
    response = resolve_exact_context(candidate=candidate, context=context)
    validate_response(response)
    assert response["status"] == STATUS_EXACT_UNRESOLVED
    assert response["unresolved_reason"] == REASON_RAISE_SIZING_UNRESOLVED
    assert response["raise_sizing"]["state"] == "UNRESOLVED_SIZING_FRONTIER"
    assert response["raise_sizing"]["unresolved"] is True
    assert response["posterior"] is None
    assert response["raise_sizing"]["exact_support_only"] is True
    assert response["raise_sizing"]["nearest_price_used"] is False
    # an observed target stays reported, but the branch is still unresolved and
    # no representative/legal-minimum/nearest price may fill it
    assert response["raise_sizing"]["supported_targets"] == [
        {"target_total_bb": 7.0, "observations": 10}
    ]


def test_raise_targets_are_reported_per_exact_target_only():
    context = _context()
    observations = _rows(context, "price", 20, 7.0) + _rows(context, "price", 20, 9.0)
    for index, row in enumerate(observations):
        row["hand_id"] = f"price-{index}"
    candidate = make_synthetic_hierarchical_candidate(
        population_id=POPULATION, observations=observations
    )
    response = resolve_exact_context(candidate=candidate, context=context)
    validate_response(response)
    assert response["status"] == STATUS_EXACT_EMPIRICAL_STRONG
    targets = {
        row["target_total_bb"]: row["observations"]
        for row in response["raise_sizing"]["supported_targets"]
    }
    assert targets == {7.0: 10, 9.0: 10}
    assert response["raise_sizing"]["structural_node_key"].startswith("MAPNODE_")


def test_resolution_is_deterministic_and_hash_bound():
    context = _context()
    candidate = make_synthetic_hierarchical_candidate(
        population_id=POPULATION,
        observations=_rows(context, "det", MIN_MARGINAL_OBSERVATIONS, 7.0),
    )
    first = resolve_exact_context(candidate=candidate, context=context)
    second = resolve_exact_context(candidate=candidate, context=context)
    assert first == second
    assert canonical_response_sha256(first) == canonical_response_sha256(second)
    assert canonical_candidate_sha256(candidate) == canonical_candidate_sha256(candidate)
    by_key = resolve_exact_context(
        candidate=candidate,
        requested_key=hierarchical_exact_key(context),
        legal_actions=LEGAL,
    )
    assert by_key == first


def test_implementation_is_bound_to_the_frozen_issue_419_spec():
    spec = json.loads(
        (ROOT / "analysis/issue419_hierarchical_tree/HIERARCHICAL_MODEL_SPEC.json").read_text(
            encoding="utf-8"
        )
    )
    assert spec["schema"] == "poker-hierarchical-exact-context-model-spec/v1"
    hierarchy = spec["hierarchy_prior_shrinkage"]
    assert [level["level"] for level in hierarchy["levels"]] == list(POOLING_LEVELS)
    assert hierarchy["hierarchical_strength_kappa0"] == KAPPA0
    assert hierarchy["base_prior"]["alpha_per_legal_marginal_action"] == ALPHA_PER_LEGAL_ACTION
    assert hierarchy["exact_weight"] == "w_exact = n0 / (n0 + kappa0), non-decreasing in n0"
    for level in hierarchy["levels"]:
        ours = next(row for row in LEVEL_SPECS if row["level"] == level["level"])
        assert sorted(ours["drops"]) == sorted(level["drops"]), level["level"]
        assert sorted(ours["retains"]) == sorted(level["retains"]), level["level"]
        assert ours["support_source_allowed"] == level["support_source_allowed"], level["level"]
        assert ours["equals_runtime_provider_key"] == level["equals_runtime_provider_key"]
    axes = spec["parameter_pooling"]["axes"]
    assert tuple(axes["never_mutualizable"]) == NEVER_MUTUALIZABLE_AXES
    assert set(axes["mutualizable"]).isdisjoint(set(NEVER_MUTUALIZABLE_AXES))
    thresholds = spec["decision_thresholds"]
    assert thresholds["minimum_marginal_observations"] == MIN_MARGINAL_OBSERVATIONS
    assert thresholds["minimum_distinct_hands"] == MIN_DISTINCT_HANDS
    isolation = spec["support_isolation_rule"]
    assert isolation["rule_id"] == SUPPORT_ISOLATION_RULE
    assert isolation["runtime_invariant"] == "support.source_key == requested_key"
    assert isolation["violation_reason_code"] == "COARSE_KEY_SUPPORT_LAUNDERING"
    contract = spec["runtime_support_contract"]
    assert sorted(contract["reason_codes"]) == sorted(
        [STATUS_EXACT_EMPIRICAL_STRONG, STATUS_EXACT_HIERARCHICAL_ESTIMATE, STATUS_EXACT_UNRESOLVED]
    )
    assert contract["requested_key"] == "hierarchical_exact_key (L0_EXACT_KEY)"
    forbidden = spec["raise_sizing_policy"]["forbidden"]
    for item in (
        "representative raise price",
        "legal-minimum substitution",
        "nearest-price or nearest-context substitution",
        "target drift or interpolation between observed sizings",
        "pruning an unresolved frontier as zero mass",
    ):
        assert item in forbidden
    prohibitions = spec["prohibitions"]
    assert prohibitions["nearest_price"] is False
    assert prohibitions["nearest_context"] is False
    assert prohibitions["representative_raise_price"] is False
    assert prohibitions["admission"] == "NONE"
    assert spec["status"] == "SPEC_ONLY_NOT_ADMITTED"


def _frozen_layer_b_vocabulary():
    """The T1 gate ids and reason codes, read from the frozen v2 protocol."""
    protocol = json.loads(
        (
            ROOT
            / "analysis/issue419_hierarchical_tree/validation_protocol_v2"
            / "FROZEN_VALIDATION_PROTOCOL_V2.json"
        ).read_text(encoding="utf-8")
    )
    gates = protocol["gates"]
    return (
        list(gates["layer_b_admissibility_gate_ids"]),
        list(gates["layer_b_admissibility_gate_reason_codes"]),
    )


def _estimate_context():
    """A context whose exact key is thin but whose L1 stack pool qualifies."""
    context = _stack_variant(100.0)
    sibling = _stack_variant(60.0)
    candidate = make_synthetic_hierarchical_candidate(
        population_id=POPULATION,
        observations=[
            {"context": context, "hand_id": "exact", "action": "RAISE", "target_total_bb": 7.0}
        ]
        + _rows(sibling, "sib", MIN_MARGINAL_OBSERVATIONS, 9.0),
    )
    return context, candidate


def test_two_layer_blocks_are_serialized_explicitly_for_every_status():
    context = _context()
    strong = make_synthetic_hierarchical_candidate(
        population_id=POPULATION,
        observations=_rows(context, "strong", MIN_MARGINAL_OBSERVATIONS, 7.0),
    )
    thin = make_synthetic_hierarchical_candidate(
        population_id=POPULATION,
        observations=[
            {"context": context, "hand_id": "only", "action": "RAISE", "target_total_bb": 7.0}
        ],
    )
    estimate_context, estimate_candidate = _estimate_context()
    responses = {
        STATUS_EXACT_EMPIRICAL_STRONG: resolve_exact_context(
            candidate=strong, context=context
        ),
        STATUS_EXACT_HIERARCHICAL_ESTIMATE: resolve_exact_context(
            candidate=estimate_candidate, context=estimate_context
        ),
        STATUS_EXACT_UNRESOLVED: resolve_exact_context(candidate=thin, context=context),
    }
    assert sorted(responses) == sorted(
        [STATUS_EXACT_EMPIRICAL_STRONG, STATUS_EXACT_HIERARCHICAL_ESTIMATE, STATUS_EXACT_UNRESOLVED]
    )
    for status, response in responses.items():
        with_status = f"status={status}"
        assert response["status"] == status, with_status
        assert response["reason_code"] == status, with_status
        for block in (
            "empirical_support",
            "pooling_provenance",
            "effective_sample_size",
            "uncertainty",
            "admissibility",
            "posterior_identity",
        ):
            assert block in response, f"{with_status}: {block} must be serialized"
        # Layer A is always the exact requested key, never a pooled level.
        empirical = response["empirical_support"]
        assert empirical["layer"] == LAYER_A_EXACT_EMPIRICAL_SUPPORT, with_status
        assert empirical["source_key"] == response["requested_key"], with_status
        assert empirical["counts_from_pooled_level"] is False, with_status
        assert empirical["qualifies_as_exact_support"] is (
            empirical["observations"] >= MIN_MARGINAL_OBSERVATIONS
            and empirical["distinct_hands"] >= MIN_DISTINCT_HANDS
        ), with_status
        # Layer B reports per-gate state with the frozen T1 reason codes.
        admissibility = response["admissibility"]
        assert admissibility["layer"] == LAYER_B_EXACT_CONTEXT_ESTIMATE_ADMISSIBILITY
        assert admissibility["node_closure_rule_id"] == NODE_CLOSURE_RULE_ID
        assert admissibility["status"] == status, with_status
        assert [
            gate["gate_id"] for gate in admissibility["gates"]
        ] == [gate_id for _, gate_id, _, _ in LAYER_B_GATES], with_status
        assert [
            gate["reason_code"] for gate in admissibility["gates"]
        ] == [reason for _, _, reason, _ in LAYER_B_GATES], with_status
        identity = response["posterior_identity"]
        assert identity["status"] == status and identity["reason_code"] == status
        assert identity["posterior_present"] is (response["posterior"] is not None)
        assert identity["probability_emitted"] is (response["posterior"] is not None)
        validate_response(response)


def test_hierarchical_estimate_is_never_exported_as_empirical_support():
    context, candidate = _estimate_context()
    response = resolve_exact_context(candidate=candidate, context=context)
    assert response["status"] == STATUS_EXACT_HIERARCHICAL_ESTIMATE
    # The exact key has one observation; the admissible parent has 21.
    assert response["empirical_support"]["observations"] == 1
    assert response["empirical_support"]["distinct_hands"] == 1
    assert response["empirical_support"]["source_key"] == response["requested_key"]
    assert response["empirical_support"]["qualifies_as_exact_support"] is False
    assert response["pooling_provenance"]["source_observations"] == 21
    assert response["pooling_provenance"]["source_key"] != response["requested_key"]
    assert response["pooling_provenance"]["counts_as_exact_support"] is False
    assert POOLING_LEVELS.index(response["pooling"]["level"]) > POOLING_LEVELS.index(
        SUPPORT_LEVEL
    )
    assert response["uncertainty"] is not None
    assert uncertainty_is_machine_readable(response["uncertainty"]) is True
    assert response["admissibility"]["admissible"] is True
    assert response["admissibility"]["primary_failure_gate"] is None
    # The zero-exact-support estimate still reports zero layer-A counts.
    sibling = _stack_variant(60.0)
    zero_candidate = make_synthetic_hierarchical_candidate(
        population_id=POPULATION,
        observations=_rows(sibling, "sib", MIN_MARGINAL_OBSERVATIONS, 7.0),
    )
    zero = resolve_exact_context(candidate=zero_candidate, context=context)
    assert zero["status"] == STATUS_EXACT_HIERARCHICAL_ESTIMATE
    assert zero["empirical_support"]["observations"] == 0
    assert zero["empirical_support"]["effective_sample_size"] == 0.0
    assert zero["pooling_provenance"]["source_observations"] >= MIN_MARGINAL_OBSERVATIONS


def test_admissibility_gates_match_the_frozen_t1_gate_vocabulary():
    gate_ids, reason_codes = _frozen_layer_b_vocabulary()
    assert [gate_id for _, gate_id, _, _ in LAYER_B_GATES] == gate_ids
    assert [reason for _, _, reason, _ in LAYER_B_GATES] == reason_codes
    assert [GATE_REASON_BY_ID[gate_id] for gate_id in gate_ids] == reason_codes
    context = _context()
    candidate = make_synthetic_hierarchical_candidate(
        population_id=POPULATION,
        observations=_rows(context, "strong", MIN_MARGINAL_OBSERVATIONS, 7.0),
    )
    response = resolve_exact_context(candidate=candidate, context=context)
    for gate in response["admissibility"]["gates"]:
        assert gate["reason_code"] == GATE_REASON_BY_ID[gate["gate_id"]]


def test_absence_of_admissible_pooling_or_uncertainty_fails_closed():
    context, candidate = _estimate_context()
    response = resolve_exact_context(candidate=candidate, context=context)
    support = response["support"]
    pooling = response["pooling"]
    uncertainty = response["uncertainty"]
    assert "RAISE" in uncertainty["actions"]

    admissible = admissibility_block(
        requested_key=response["requested_key"],
        support=support,
        pooling=pooling,
        uncertainty=uncertainty,
        raise_sizing=response["raise_sizing"],
        status=STATUS_EXACT_HIERARCHICAL_ESTIMATE,
    )
    assert admissible["admissible"] is True

    # An answered estimate without its machine-readable uncertainty band is not
    # admissible: the UNCERTAINTY gate fails with the frozen T1 reason code.
    assert uncertainty_is_machine_readable(None) is False
    without_uncertainty = admissibility_block(
        requested_key=response["requested_key"],
        support=support,
        pooling=pooling,
        uncertainty=None,
        raise_sizing=response["raise_sizing"],
        status=STATUS_EXACT_HIERARCHICAL_ESTIMATE,
    )
    assert without_uncertainty["admissible"] is False
    assert without_uncertainty["primary_failure_gate"] == GATE_UNCERTAINTY
    assert without_uncertainty["reason_code"] == "REFUSED_UNCERTAINTY"

    # Absence of an admissible pooling level is EXACT_UNRESOLVED, with the
    # failing gate and its frozen reason code serialized.
    thin = make_synthetic_hierarchical_candidate(
        population_id=POPULATION,
        observations=[
            {"context": context, "hand_id": "only", "action": "RAISE", "target_total_bb": 7.0}
        ],
    )
    unresolved = resolve_exact_context(candidate=thin, context=context)
    assert unresolved["status"] == STATUS_EXACT_UNRESOLVED
    assert unresolved["unresolved_reason"] == REASON_NO_ADMISSIBLE_POOLING
    assert unresolved["posterior"] is None
    assert unresolved["uncertainty"] is None
    assert unresolved["pooling"] is None
    assert unresolved["pooling_provenance"] is None
    assert unresolved["admissibility"]["admissible"] is False
    assert unresolved["admissibility"]["primary_failure_gate"] == GATE_POOLING_LEVEL
    assert unresolved["admissibility"]["reason_code"] == "REFUSED_POOLING_LEVEL"
    validate_response(unresolved)


def test_schema_locks_the_hierarchical_contract_and_validates_the_outputs():
    schema_path = (
        ROOT / "contracts/training/model-a-preflop-sizing-hierarchical-likelihood.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["properties"]["schema"]["const"] == (
        "poker-model-a-preflop-sizing-hierarchical-likelihood/v1"
    )
    assert schema["properties"]["identity"]["$ref"] == "#/$defs/identity"
    assert schema["$defs"]["identity"]["properties"]["candidate_id"]["const"] == CANDIDATE_ID
    assert schema["$defs"]["identity"]["properties"]["active_model_replaced"]["const"] is False
    assert schema["properties"]["nearest_price_fallback"]["const"] is False
    assert schema["properties"]["nearest_context_fallback"]["const"] is False
    assert schema["properties"]["support_isolation_rule"]["const"] == SUPPORT_ISOLATION_RULE
    assert schema["properties"]["shrinkage"]["properties"]["kappa0"]["const"] == KAPPA0
    assert schema["$defs"]["status"]["enum"] == [
        STATUS_EXACT_EMPIRICAL_STRONG,
        STATUS_EXACT_HIERARCHICAL_ESTIMATE,
        STATUS_EXACT_UNRESOLVED,
    ]
    # Provider/schema parity for the explicit two-layer serialization: the
    # blocks are required by the contract, and every provider output below
    # validates with them present.
    response_required = set(schema["$defs"]["response"]["required"])
    for block in (
        "empirical_support",
        "pooling_provenance",
        "effective_sample_size",
        "admissibility",
        "posterior_identity",
    ):
        assert block in response_required, block
    assert schema["$defs"]["empiricalSupport"]["properties"]["layer"]["const"] == (
        LAYER_A_EXACT_EMPIRICAL_SUPPORT
    )
    assert schema["$defs"]["empiricalSupport"]["properties"]["source_key"]["$ref"] == (
        "#/$defs/exactKey"
    )
    assert schema["$defs"]["empiricalSupport"]["properties"]["counts_from_pooled_level"][
        "const"
    ] is False
    assert schema["$defs"]["empiricalSupport"]["properties"]["thresholds"]["properties"] == {
        "minimum_marginal_observations": {"const": MIN_MARGINAL_OBSERVATIONS},
        "minimum_distinct_hands": {"const": MIN_DISTINCT_HANDS},
    }
    assert schema["$defs"]["admissibility"]["properties"]["layer"]["const"] == (
        LAYER_B_EXACT_CONTEXT_ESTIMATE_ADMISSIBILITY
    )
    assert schema["$defs"]["admissibility"]["properties"]["node_closure_rule_id"][
        "const"
    ] == NODE_CLOSURE_RULE_ID
    gate_schema = schema["$defs"]["admissibility"]["properties"]["gates"]["items"]
    assert gate_schema["properties"]["gate_id"]["enum"] == [
        gate_id for _, gate_id, _, _ in LAYER_B_GATES
    ]
    assert gate_schema["properties"]["reason_code"]["enum"] == [
        reason for _, _, reason, _ in LAYER_B_GATES
    ]
    assert schema["$defs"]["effectiveSampleSize"]["properties"]["credited_at"]["const"] == (
        "DISTINCT_HANDS_NEVER_INFLATED_BY_POOLING"
    )
    assert schema["$defs"]["posteriorIdentity"]["properties"]["status"]["$ref"] == (
        "#/$defs/status"
    )
    exact_schema = json.loads(
        (ROOT / "contracts/training/model-a-preflop-sizing-likelihood.schema.json").read_text(
            encoding="utf-8"
        )
    )
    enum = exact_schema["properties"]["identity"]["properties"]["candidate_id"]["enum"]
    assert enum == [
        "model-a-preflop-sizing-aware-candidate-v1",
        "model-a-preflop-sizing-aware-candidate-v2",
        CANDIDATE_ID,
    ]
    context = _stack_variant(100.0)
    sibling = _stack_variant(60.0)
    candidate = make_synthetic_hierarchical_candidate(
        population_id=POPULATION,
        observations=[
            {"context": context, "hand_id": "exact", "action": "RAISE", "target_total_bb": 7.0}
        ]
        + _rows(sibling, "sib", MIN_MARGINAL_OBSERVATIONS, 9.0),
    )
    assert _contract_errors(schema, candidate, schema) == []
    hierarchical = resolve_exact_context(candidate=candidate, context=context)
    response_node = {"$ref": "#/$defs/response"}
    assert _contract_errors(response_node, hierarchical, schema) == []
    assert hierarchical["status"] == STATUS_EXACT_HIERARCHICAL_ESTIMATE
    strong = make_synthetic_hierarchical_candidate(
        population_id=POPULATION,
        observations=_rows(context, "sch", MIN_MARGINAL_OBSERVATIONS, 7.0),
    )
    assert _contract_errors(
        response_node, resolve_exact_context(candidate=strong, context=context), schema
    ) == []
    assert _contract_errors(
        response_node,
        resolve_exact_context(candidate=strong, context=_price_variant(5.0, 8.0, 9.0)),
        schema,
    ) == []


def _two_layer_responses():
    """The exact-key / pooled-parameter pair used by the two-layer regressions."""
    context = _stack_variant(100.0)
    sibling = _stack_variant(60.0)
    estimate_candidate = make_synthetic_hierarchical_candidate(
        population_id=POPULATION,
        observations=[
            {"context": context, "hand_id": "exact-1", "action": "RAISE", "target_total_bb": 7.0}
        ]
        + _rows(sibling, "sibling", MIN_MARGINAL_OBSERVATIONS, 9.0),
    )
    estimate = resolve_exact_context(candidate=estimate_candidate, context=context)
    strong_candidate = make_synthetic_hierarchical_candidate(
        population_id=POPULATION,
        observations=_rows(context, "strong", MIN_MARGINAL_OBSERVATIONS, 7.0),
    )
    strong = resolve_exact_context(candidate=strong_candidate, context=context)
    unresolved_candidate = make_synthetic_hierarchical_candidate(
        population_id=POPULATION,
        observations=[{"context": context, "hand_id": "only", "action": "RAISE",
                       "target_total_bb": 7.0}],
    )
    unresolved = resolve_exact_context(candidate=unresolved_candidate, context=context)
    return strong, estimate, unresolved


def _assert_rejected(response, *, needle):
    try:
        validate_response(response)
    except HierarchicalSizingError as exc:
        assert needle in str(exc), (needle, str(exc))
        return
    raise AssertionError(f"an invalid response must fail closed ({needle!r})")


def test_empirical_support_stays_exact_key_only_for_a_hierarchical_estimate():
    strong, estimate, unresolved = _two_layer_responses()

    # Layer 1: an EXACT_EMPIRICAL_STRONG answer is the requested key's own support.
    assert strong["status"] == STATUS_EXACT_EMPIRICAL_STRONG
    support = strong["support"]
    assert support["source_key"] == strong["requested_key"]
    assert support["borrowed_from_other_keys"] is False
    assert support["observations"] >= MIN_MARGINAL_OBSERVATIONS
    assert support["distinct_hands"] >= MIN_DISTINCT_HANDS
    assert support["effective_sample_size"] == float(support["distinct_hands"])
    assert support["denominator"] == sum(support["action_counts"].values())

    # Layer 2: the estimate keeps exact-key counts (possibly below threshold) and
    # never exports the parent's pooled counts as empirical support.
    assert estimate["status"] == STATUS_EXACT_HIERARCHICAL_ESTIMATE
    pooled_support = estimate["support"]
    assert pooled_support["source_key"] == estimate["requested_key"]
    assert pooled_support["borrowed_from_other_keys"] is False
    assert pooled_support["support_isolation_rule"] == SUPPORT_ISOLATION_RULE
    assert pooled_support["observations"] == 1
    assert pooled_support["denominator"] == 1
    assert pooled_support["action_counts"]["RAISE"] == 1
    assert pooled_support["distinct_hands"] == 1
    assert pooled_support["effective_sample_size"] == 1.0
    assert pooled_support["observations"] < MIN_MARGINAL_OBSERVATIONS
    assert pooled_support["distinct_hands"] < MIN_DISTINCT_HANDS
    for leaked in ("source_observations", "source_distinct_hands",
                   "source_effective_sample_size", "weight_parent", "weight_exact"):
        assert leaked not in pooled_support
    assert estimate["pooling"]["source_observations"] > pooled_support["observations"]

    # An abstention still reports its own empty exact-key support.
    assert unresolved["status"] == STATUS_EXACT_UNRESOLVED
    assert unresolved["support"]["source_key"] == unresolved["requested_key"]
    assert unresolved["support"]["observations"] == 1
    assert unresolved["support"]["denominator"] == 1
    assert unresolved["support"]["effective_sample_size"] == 1.0
    assert unresolved["support"]["observations"] < MIN_MARGINAL_OBSERVATIONS

    # A coarse parent key may never be declared as the support source.
    loaned = copy.deepcopy(estimate)
    loaned["support"]["source_key"] = estimate["pooling"]["source_key"]
    try:
        validate_response(loaned)
    except SupportIsolationError as exc:
        assert exc.reason_code == "COARSE_KEY_SUPPORT_LAUNDERING"
    else:
        raise AssertionError("borrowed support must fail closed")
    borrowed = copy.deepcopy(estimate)
    borrowed["support"]["borrowed_from_other_keys"] = True
    _assert_rejected(borrowed, needle="borrowed")


def test_hierarchical_estimate_pooling_provenance_above_l0_and_same_key():
    strong, estimate, _unresolved = _two_layer_responses()
    pooling = estimate["pooling"]
    # The answer is still for the requested exact key ...
    assert estimate["requested_key"] == estimate["support"]["source_key"]
    assert estimate["requested_key"] == pooling["support_source_key"]
    # ... while the parameters come from a strictly coarser parent key.
    assert pooling["source_key"] != estimate["requested_key"]
    assert pooling["level"] != SUPPORT_LEVEL
    assert POOLING_LEVELS.index(pooling["level"]) > POOLING_LEVELS.index(SUPPORT_LEVEL)
    assert pooling["rank"] == POOLING_LEVELS.index(pooling["level"])
    assert estimate["uncertainty"] is not None
    assert estimate["uncertainty"]["level_used"] == pooling["level"]
    assert estimate["uncertainty"]["effective_sample_size"] == pooling[
        "source_effective_sample_size"
    ]
    assert set(estimate["uncertainty"]["actions"]) == set(estimate["posterior"])
    for band in estimate["uncertainty"]["actions"].values():
        assert band["credible_interval"]["low"] <= band["mean"]
        assert band["mean"] <= band["credible_interval"]["high"]
        assert band["std_error"] >= 0.0
    assert abs(sum(estimate["posterior"].values()) - 1.0) <= 1e-9

    strong_pooling = strong["pooling"]
    assert strong_pooling["level"] == SUPPORT_LEVEL
    assert strong_pooling["source_key"] == strong["requested_key"]
    assert strong_pooling["support_source_key"] == strong["requested_key"]

    mislabelled = copy.deepcopy(estimate)
    mislabelled["pooling"]["level"] = SUPPORT_LEVEL
    _assert_rejected(mislabelled, needle="parent level it used")
    substituted = copy.deepcopy(estimate)
    substituted["pooling"]["source_key"] = estimate["requested_key"]
    _assert_rejected(substituted, needle="pool toward a parent")


def test_two_layer_response_identity_distinguishes_all_three_statuses():
    strong, estimate, unresolved = _two_layer_responses()

    # Every answer is still serialized under the exact key that was requested.
    for response in (strong, estimate, unresolved):
        assert response["requested_key_granularity"] == "hierarchical_exact_key"
        assert response["reason_code"] == response["status"]
        assert response["support"]["source_key"] == response["requested_key"]
        assert response["requested_key"] == hierarchical_exact_key(_stack_variant(100.0))

    # An exact-support claim is only ever serialized at L0 with its own support.
    assert strong["status"] == STATUS_EXACT_EMPIRICAL_STRONG
    assert strong["pooling"]["level"] == SUPPORT_LEVEL
    assert strong["uncertainty"]["level_used"] == SUPPORT_LEVEL
    assert strong["pooling"]["source_key"] == strong["requested_key"]

    # The estimate answers the same exact key with pooled parameters ...
    assert estimate["status"] == STATUS_EXACT_HIERARCHICAL_ESTIMATE
    assert estimate["pooling"]["level"] != SUPPORT_LEVEL
    assert estimate["pooling"]["source_key"] != estimate["requested_key"]
    assert estimate["uncertainty"]["level_used"] == estimate["pooling"]["level"]
    assert set(estimate["posterior"]) == set(estimate["uncertainty"]["actions"])
    # ... and it is never labeled as an exact empirical answer.
    assert estimate["pooling"]["support_source_key"] == estimate["requested_key"]
    assert estimate["pooling"]["support_isolation_rule"] == SUPPORT_ISOLATION_RULE
    assert estimate["granularity"]["support"] == SUPPORT_LEVEL
    assert estimate["granularity"]["nearest_price_lookup"] is False
    assert estimate["granularity"]["nearest_context_lookup"] is False

    # An abstention emits no probability and no uncertainty at all.
    assert unresolved["status"] == STATUS_EXACT_UNRESOLVED
    assert unresolved["posterior"] is None
    assert unresolved["uncertainty"] is None
    assert unresolved["pooling"] is None
    assert unresolved["unresolved_reason"] in (
        REASON_NO_ADMISSIBLE_POOLING,
        REASON_NO_EXACT_SUPPORT_NO_CONTEXT,
        REASON_RAISE_SIZING_UNRESOLVED,
    )
    assert unresolved["reason_detail"]
    forged = copy.deepcopy(unresolved)
    forged["posterior"] = {"FOLD": 1.0}
    _assert_rejected(forged, needle="no probability")

    # The provider never substitutes a representative or interpolated price.
    assert estimate["raise_sizing"]["nearest_price_used"] is False
    assert estimate["raise_sizing"]["representative_price_used"] is False
    assert estimate["raise_sizing"]["interpolation_used"] is False
    assert estimate["raise_sizing"]["exact_support_only"] is True


def test_provider_schema_parity_for_the_two_layer_response():
    """Acceptance 4: the frozen contract schema mirrors the provider semantics."""
    schema_path = (
        ROOT / "contracts/training/model-a-preflop-sizing-hierarchical-likelihood.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    response = schema["$defs"]["response"]
    support = response["properties"]["support"]
    pooling = response["properties"]["pooling"]
    uncertainty = schema["$defs"]["response"]["properties"]["uncertainty"]

    assert schema["$defs"]["status"]["enum"] == [
        STATUS_EXACT_EMPIRICAL_STRONG,
        STATUS_EXACT_HIERARCHICAL_ESTIMATE,
        STATUS_EXACT_UNRESOLVED,
    ]
    assert schema["$defs"]["reasonCode"]["enum"] == [
        REASON_NO_ADMISSIBLE_POOLING,
        REASON_RAISE_SIZING_UNRESOLVED,
        REASON_NO_EXACT_SUPPORT_NO_CONTEXT,
    ]
    assert schema["$defs"]["poolingLevel"]["properties"]["level"]["enum"] == list(
        POOLING_LEVELS
    )
    for field in (
        "observations",
        "distinct_hands",
        "effective_sample_size",
        "source_key",
        "borrowed_from_other_keys",
        "support_isolation_rule",
    ):
        assert field in support["required"], field
    for field in ("level", "source_key", "support_source_key"):
        assert field in pooling["required"], field
    for field in (
        "method",
        "confidence_level",
        "level_used",
        "effective_sample_size",
        "concentration",
        "actions",
    ):
        assert field in uncertainty["required"], field
    action_band = uncertainty["properties"]["actions"]["additionalProperties"]
    for field in ("mean", "alpha", "beta", "std_error", "credible_interval"):
        assert field in action_band["required"], field
    assert support["properties"]["support_isolation_rule"]["const"] == SUPPORT_ISOLATION_RULE
    assert pooling["properties"]["support_isolation_rule"]["const"] == SUPPORT_ISOLATION_RULE
    # No field of a hierarchical estimate may be published as empirical support:
    # the support block is closed, and every pooled quantity lives under pooling.
    assert support["additionalProperties"] is False
    pooled_quantities = (
        "source_observations",
        "source_distinct_hands",
        "source_effective_sample_size",
        "weight_exact",
        "weight_parent",
    )
    for field in pooled_quantities:
        assert field not in support["properties"], field
        assert field in pooling["properties"], field
    assert pooling["properties"]["level"]["enum"] == list(POOLING_LEVELS)

    response_node = {"$ref": "#/$defs/response"}
    strong, estimate, unresolved = _two_layer_responses()
    for response_value in (strong, estimate, unresolved):
        assert _contract_errors(response_node, response_value, schema) == []


if __name__ == "__main__":
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
    print(f"preflop hierarchical sizing contract tests: {len(tests)} passed")

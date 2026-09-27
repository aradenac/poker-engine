#!/usr/bin/env python3
"""Fail-closed #425 -> #344 contract bridge (task ``backlog-uso``).

This module is the dependency-free contract layer between the synthetic
robustness input of issue #425
(``contracts/training/model-b-hero-robustness-input.schema.json``,
``$id = hero-model-b-robustness-input/v1``) and the synthetic-only sensitivity
harness request of issue #344
(``model-b-preflop-sensitivity-harness-request/v1``).

It exposes exactly two responsibilities:

``validate_robustness_input`` / ``load_robustness_input``
    A fail-closed loader-validator for the #425 input. It checks the ``schema``
    id, the ``source_kind``, the pinned ``provenance`` block, the all-false
    ``information_boundary`` block, the required ``hero_entry``/``support``
    blocks and the absence of unknown fields. Nothing is repaired, defaulted or
    enriched, non-finite numbers are refused, and every failure is raised as a
    :class:`RobustnessContractError` carrying a machine-readable
    ``reason_code`` (``SCHEMA_MISMATCH``, ``MISSING_PROVENANCE``,
    ``MISSING_SUPPORT``, ``FORBIDDEN_FEATURE``, ...).

``project_to_harness_request``
    A projection producing a valid #344 harness request. Only the public action
    identity crosses the boundary: every alternative is reduced to
    ``{alternative_id, action, target_total_bb, incremental_cost_bb}`` derived
    from ``hero_entry.alternatives``. The synthetic EV envelope, uncertainty,
    paired delta, route/source, support verdict and posterior references are
    never copied, and the request keeps ``source_kind=SYNTHETIC_HARNESS_ONLY``,
    ``synthetic_fixture=true`` and an all-false information boundary. The
    projected request is passed through ``harness.validate_request`` and through
    a final scan reusing the harness ``FORBIDDEN_MODEL_FEATURES`` catalogue.

Nothing in this module edits or forks the #344 harness: it imports its
constants and validator, so both modules share one source of truth.
"""
from __future__ import annotations

import copy
import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from tools.simulation.model_b_preflop_sensitivity_harness import (
    CANONICAL_DECISION_SCHEMA,
    FORBIDDEN_ALTERNATIVE_LEAK_FIELDS,
    FORBIDDEN_MODEL_FEATURES,
    HERO_ROBUSTNESS_INPUT_SCHEMA,
    HERO_ROBUSTNESS_INPUT_SOURCE_KIND,
    SCHEMA as HARNESS_REQUEST_SCHEMA,
    SOURCE_KIND as HARNESS_SOURCE_KIND,
    SUPPORTED_HERO_ACTIONS,
    validate_request as validate_harness_request,
)

__all__ = [
    "RobustnessContractError",
    "ContractError",
    "INPUT_SCHEMA",
    "INPUT_SOURCE_KIND",
    "SCHEMA",
    "REQUEST_SCHEMA",
    "PROJECTED_SOURCE_KIND",
    "CONTRACT_PATH",
    "PROVENANCE_FLAGS",
    "INFORMATION_BOUNDARY_FLAGS",
    "SUPPORT_STATUSES",
    "FORBIDDEN_MODEL_FEATURES",
    "FORBIDDEN_LEAK_FIELDS",
    "validate_robustness_input",
    "load_robustness_input",
    "validate_projected_request",
    "project_to_harness_request",
    "check_forbidden_features",
    "validate_input",
    "validate",
    "load_input",
    "load",
    "load_and_validate",
    "project_harness_request",
    "project_to_harness",
    "project_request",
    "project_robustness_input",
    "scan_forbidden_features",
]

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "contracts/training/model-b-hero-robustness-input.schema.json"
CONTRACT_ID = HERO_ROBUSTNESS_INPUT_SCHEMA

#: ``schema`` id of the #425 input (``CONTRACT_ID`` of the shipped contract).
INPUT_SCHEMA = HERO_ROBUSTNESS_INPUT_SCHEMA
SCHEMA = INPUT_SCHEMA
INPUT_SOURCE_KIND = HERO_ROBUSTNESS_INPUT_SOURCE_KIND
REQUEST_SCHEMA = HARNESS_REQUEST_SCHEMA
#: The projection always targets the unchanged default harness source kind of
#: #344; it never promotes a synthetic robustness input to a real one.
PROJECTED_SOURCE_KIND = HARNESS_SOURCE_KIND

#: Fields of the pinned #425 ``provenance`` block.
PROVENANCE_FLAGS = (
    "synthetic_fixture",
    "real_issue_367_consumed",
    "validation_consumed",
    "test_consumed",
)
PROVENANCE_FORBIDDEN_FLAGS = (
    "real_issue_367_consumed",
    "validation_consumed",
    "test_consumed",
)

#: Boundary flags that must be present and explicitly ``False`` in the input
#: and in the projected request.
INFORMATION_BOUNDARY_FLAGS = (
    "hero_ev_consumed",
    "model_a_consumed",
    "recommendation_consumed",
    "future_cards_consumed",
    "opponent_hole_cards_consumed",
)

#: The closed #425 support vocabulary.
SUPPORT_STATUSES = frozenset(
    {
        "CONSISTENT",
        "SENSITIVE",
        "TOO_CLOSE",
        "INSUFFICIENT_SUPPORT",
        "OOD_UNTESTABLE",
    }
)

#: Every key that may never appear in a projected request: the #344 forbidden
#: Model A / EV / recommendation / route catalogue plus the robustness-shaped
#: leak fields (uncertainty, paired delta, support, posterior references, ...).
FORBIDDEN_LEAK_FIELDS = frozenset(FORBIDDEN_MODEL_FEATURES) | frozenset(
    FORBIDDEN_ALTERNATIVE_LEAK_FIELDS
)

_PROJECTED_ALTERNATIVE_KEYS = (
    "alternative_id",
    "action",
    "target_total_bb",
    "incremental_cost_bb",
)
_CONTEXT_REQUIRED_FIELDS = (
    "hero_position",
    "hero_contribution_before_bb",
    "pot_before_hero_action_bb",
    "initial_sequence",
    "limper_count",
    "responders",
)
_REASON_CODE_PRECEDENCE = (
    "FORBIDDEN_FEATURE",
    "NON_FINITE_NUMBER",
    "UNKNOWN_FIELD",
    "INPUT_SCHEMA_VIOLATION",
)


class RobustnessContractError(ValueError):
    """Fail-closed contract failure carrying machine-readable reason codes.

    ``reason_code`` is always the primary, most specific code; ``reason_codes``
    keeps the ordered catalogue (primary first) when a failure has several
    facets. The base class is :class:`ValueError` so callers may keep catching
    ``ValueError`` while reading the code from the exception.
    """

    def __init__(
        self,
        reason_code: str,
        message: str,
        *,
        reason_codes: tuple[str, ...] | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self.reason_code = str(reason_code)
        self.reason_codes = tuple(
            dict.fromkeys(reason_codes or (self.reason_code,))
        )
        self.message = str(message)
        self.details = dict(details or {})
        super().__init__(f"{self.reason_code}: {self.message}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": "FAIL_CLOSED",
            "reason_code": self.reason_code,
            "reason_codes": list(self.reason_codes),
            "message": self.message,
            "details": dict(self.details),
        }


#: Short alias kept for callers that import ``ContractError``.
ContractError = RobustnessContractError


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_finite_number(value: Any) -> bool:
    return _is_number(value) and math.isfinite(float(value))


_JSON_TYPES = {
    "object": lambda value: isinstance(value, Mapping),
    "array": lambda value: isinstance(value, list),
    "string": lambda value: isinstance(value, str),
    "number": _is_finite_number,
    "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
    "boolean": lambda value: isinstance(value, bool),
    "null": lambda value: value is None,
}


def _reject_json_constant(name: str) -> Any:
    raise RobustnessContractError(
        "NON_FINITE_NUMBER",
        f"JSON constant {name!r} is not allowed: the #425 contract is finite-only",
        details={"constant": name},
    )


@lru_cache(maxsize=8)
def _load_contract(contract_path: str) -> Mapping[str, Any]:
    """Read the #425 JSON schema and verify its ``$id`` (fail-closed)."""
    try:
        contract = json.loads(
            Path(contract_path).read_text(encoding="utf-8"),
            parse_constant=_reject_json_constant,
        )
    except RobustnessContractError:
        raise
    except (OSError, ValueError) as exc:  # pragma: no cover - defensive
        raise RobustnessContractError(
            "CONTRACT_UNREADABLE",
            f"cannot read the #425 contract schema {contract_path}: {exc}",
            details={"contract_path": contract_path},
        ) from exc
    if not isinstance(contract, Mapping) or contract.get("$id") != CONTRACT_ID:
        raise RobustnessContractError(
            "CONTRACT_ID_MISMATCH",
            f"expected #425 contract $id {CONTRACT_ID!r}, "
            f"got {contract.get('$id') if isinstance(contract, Mapping) else None!r}",
            details={"contract_path": contract_path},
        )
    return contract


def _schema_violations(
    value: Any,
    schema: Any,
    path: str,
) -> list[tuple[str, str]]:
    """Minimal dependency-free JSON-Schema walker (fail-closed, finite-only)."""
    if not isinstance(schema, Mapping):
        return []
    found: list[tuple[str, str]] = []

    if _is_number(value) and not _is_finite_number(value):
        found.append(("NON_FINITE_NUMBER", f"{path}: non-finite number is not allowed"))

    declared_type = schema.get("type")
    if declared_type is not None:
        types = declared_type if isinstance(declared_type, list) else [declared_type]
        known = [name for name in types if name in _JSON_TYPES]
        if known and not any(_JSON_TYPES[name](value) for name in known):
            if found:
                return found
            found.append(
                ("INPUT_SCHEMA_VIOLATION", f"{path}: expected type {declared_type!r}")
            )
            return found

    if "const" in schema and value != schema["const"]:
        found.append(
            ("INPUT_SCHEMA_VIOLATION", f"{path}: expected const {schema['const']!r}")
        )

    enum = schema.get("enum")
    if isinstance(enum, list) and value not in enum:
        found.append(
            ("INPUT_SCHEMA_VIOLATION", f"{path}: value {value!r} outside enum {enum}")
        )

    if isinstance(value, Mapping):
        properties = schema.get("properties")
        properties = properties if isinstance(properties, Mapping) else {}
        for key in schema.get("required", []):
            if key not in value:
                found.append(
                    ("INPUT_SCHEMA_VIOLATION", f"{path}: missing required property {key!r}")
                )
        if schema.get("additionalProperties") is False:
            for key in value:
                if key in properties:
                    continue
                lowered = str(key).lower()
                if lowered in FORBIDDEN_MODEL_FEATURES or lowered.startswith("model_a"):
                    found.append(
                        (
                            "FORBIDDEN_FEATURE",
                            f"{path}.{key}: forbidden Model A/EV/recommendation feature",
                        )
                    )
                else:
                    found.append(
                        ("UNKNOWN_FIELD", f"{path}.{key}: unknown property is not allowed")
                    )
        for key, child in value.items():
            if key in properties:
                found.extend(
                    _schema_violations(child, properties[key], f"{path}.{key}")
                )

    if isinstance(value, list):
        items = schema.get("items")
        if isinstance(items, Mapping):
            for index, child in enumerate(value):
                found.extend(_schema_violations(child, items, f"{path}[{index}]"))
        minimum_items = schema.get("minItems")
        if isinstance(minimum_items, int) and len(value) < minimum_items:
            found.append(
                (
                    "INPUT_SCHEMA_VIOLATION",
                    f"{path}: needs at least {minimum_items} item(s)",
                )
            )
        maximum_items = schema.get("maxItems")
        if isinstance(maximum_items, int) and len(value) > maximum_items:
            found.append(
                (
                    "INPUT_SCHEMA_VIOLATION",
                    f"{path}: allows at most {maximum_items} item(s)",
                )
            )

    if isinstance(value, str):
        min_length = schema.get("minLength")
        if isinstance(min_length, int) and len(value) < min_length:
            found.append(
                (
                    "INPUT_SCHEMA_VIOLATION",
                    f"{path}: shorter than minLength {min_length}",
                )
            )

    if _is_finite_number(value):
        minimum = schema.get("minimum")
        if _is_number(minimum) and value < minimum:
            found.append(
                ("INPUT_SCHEMA_VIOLATION", f"{path}: below minimum {minimum}")
            )

    return found


def _validate_provenance(document: Mapping[str, Any]) -> None:
    """Fail closed on any missing/opened #425 provenance block."""
    provenance = document.get("provenance")
    if not isinstance(provenance, Mapping):
        raise RobustnessContractError(
            "MISSING_PROVENANCE",
            "robustness input provenance block is required",
        )
    missing = [flag for flag in PROVENANCE_FLAGS if flag not in provenance]
    if missing:
        raise RobustnessContractError(
            "MISSING_PROVENANCE",
            f"robustness provenance is missing: {missing}",
            reason_codes=("MISSING_PROVENANCE", "PROVENANCE_INCOMPLETE"),
            details={"missing": missing},
        )
    if provenance.get("synthetic_fixture") is not True:
        raise RobustnessContractError(
            "MISSING_PROVENANCE",
            "robustness provenance must declare synthetic_fixture=true",
        )
    opened = [
        flag for flag in PROVENANCE_FORBIDDEN_FLAGS if provenance.get(flag) is not False
    ]
    if opened:
        raise RobustnessContractError(
            "MISSING_PROVENANCE",
            "robustness provenance must not consume real/VALIDATION/TEST evidence: "
            f"{opened}",
            details={"violations": opened},
        )


def _validate_information_boundary(document: Mapping[str, Any]) -> None:
    """Fail closed unless every #425 boundary flag is explicitly ``False``."""
    boundary = document.get("information_boundary")
    if not isinstance(boundary, Mapping):
        raise RobustnessContractError(
            "INFORMATION_BOUNDARY_VIOLATION",
            "robustness input information_boundary block is required",
        )
    missing = [flag for flag in INFORMATION_BOUNDARY_FLAGS if flag not in boundary]
    violations = sorted(
        key for key, value in boundary.items() if value is not False
    )
    if missing or violations:
        raise RobustnessContractError(
            "INFORMATION_BOUNDARY_VIOLATION",
            "robustness information boundary must explicitly forbid "
            f"private/predictive information (missing={missing}, "
            f"not_false={violations})",
            details={"missing": missing, "violations": violations},
        )


def _validate_support(support: Any, path: str) -> None:
    """Fail closed on a missing or malformed per-entry ``support`` block."""
    if support is None or not isinstance(support, Mapping):
        raise RobustnessContractError(
            "MISSING_SUPPORT",
            f"{path}.support is required; a missing/declared-null support verdict "
            "may never be silently upgraded",
        )
    missing = [key for key in ("status", "tier", "ood") if key not in support]
    if missing:
        raise RobustnessContractError(
            "MISSING_SUPPORT",
            f"{path}.support is incomplete: missing {missing}",
            reason_codes=("MISSING_SUPPORT", "SUPPORT_INCOMPLETE"),
            details={"missing": missing},
        )
    if support.get("status") not in SUPPORT_STATUSES:
        raise RobustnessContractError(
            "SUPPORT_INVALID",
            f"{path}.support.status {support.get('status')!r} is outside the closed "
            f"#425 vocabulary {sorted(SUPPORT_STATUSES)}",
        )
    if not isinstance(support.get("tier"), str) or not support.get("tier"):
        raise RobustnessContractError(
            "SUPPORT_INVALID",
            f"{path}.support.tier must be a non-empty string",
        )
    if not isinstance(support.get("ood"), bool):
        raise RobustnessContractError(
            "SUPPORT_INVALID",
            f"{path}.support.ood must be a boolean",
        )


def _validate_hero_entry(document: Mapping[str, Any]) -> Mapping[str, Any]:
    hero_entry = document.get("hero_entry")
    if not isinstance(hero_entry, Mapping):
        raise RobustnessContractError(
            "HERO_ENTRY_MISSING",
            "robustness input hero_entry block is required",
        )
    _validate_support(hero_entry.get("support"), "$.hero_entry")
    alternatives = hero_entry.get("alternatives")
    if not isinstance(alternatives, list) or not alternatives:
        raise RobustnessContractError(
            "ALTERNATIVES_MISSING",
            "hero_entry.alternatives must be a non-empty array",
        )
    seen: set[str] = set()
    for index, alternative in enumerate(alternatives):
        path = f"$.hero_entry.alternatives[{index}]"
        if not isinstance(alternative, Mapping):
            raise RobustnessContractError(
                "ALTERNATIVE_INVALID", f"{path} must be an object"
            )
        alternative_id = alternative.get("alternative_id")
        if not isinstance(alternative_id, str) or not alternative_id:
            raise RobustnessContractError(
                "ALTERNATIVE_INVALID", f"{path}.alternative_id is required"
            )
        if alternative_id in seen:
            raise RobustnessContractError(
                "ALTERNATIVE_INVALID",
                f"{path}.alternative_id {alternative_id!r} is duplicated",
            )
        seen.add(alternative_id)
        _validate_support(alternative.get("support"), path)
    return hero_entry


def _raise_schema_violations(violations: list[tuple[str, str]]) -> None:
    if not violations:
        return
    ranked = sorted(
        violations,
        key=lambda item: (_REASON_CODE_PRECEDENCE.index(item[0]), item[1]),
    )
    code = ranked[0][0]
    messages = [message for _code, message in ranked]
    raise RobustnessContractError(
        code,
        "robustness input violates the #425 contract: " + "; ".join(messages[:4]),
    )


def validate_robustness_input(
    robustness_input: Any,
    *,
    contract_path: Path | str = CONTRACT_PATH,
) -> Mapping[str, Any]:
    """Validate one synthetic #425 robustness input fail-closed.

    The input is returned unchanged when it is valid; nothing is ever repaired,
    defaulted or enriched. Every rejection is a
    :class:`RobustnessContractError` (a :class:`ValueError`) whose
    ``reason_code`` is machine-readable -- ``SCHEMA_MISMATCH``,
    ``MISSING_PROVENANCE``, ``MISSING_SUPPORT``, ``FORBIDDEN_FEATURE``, ...
    """
    if not isinstance(robustness_input, Mapping):
        raise RobustnessContractError(
            "INPUT_NOT_OBJECT",
            "robustness input must be a JSON object",
        )

    schema_id = robustness_input.get("schema")
    if schema_id != INPUT_SCHEMA:
        raise RobustnessContractError(
            "SCHEMA_MISMATCH",
            f"expected robustness input schema {INPUT_SCHEMA!r}, got {schema_id!r}",
            details={"expected": INPUT_SCHEMA, "actual": schema_id},
        )
    if robustness_input.get("source_kind") != INPUT_SOURCE_KIND:
        raise RobustnessContractError(
            "SOURCE_KIND_MISMATCH",
            f"expected source_kind {INPUT_SOURCE_KIND!r}, "
            f"got {robustness_input.get('source_kind')!r}",
        )

    _validate_provenance(robustness_input)
    _validate_information_boundary(robustness_input)
    _validate_hero_entry(robustness_input)

    contract = _load_contract(str(contract_path))
    _raise_schema_violations(_schema_violations(robustness_input, contract, "$"))
    return robustness_input


def load_robustness_input(
    path: Path | str,
    *,
    contract_path: Path | str = CONTRACT_PATH,
) -> Mapping[str, Any]:
    """Load and validate one synthetic #425 robustness input from ``path``."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise RobustnessContractError(
            "INPUT_UNREADABLE",
            f"cannot read robustness input {path}: {exc}",
            details={"path": str(path)},
        ) from exc
    try:
        document = json.loads(text, parse_constant=_reject_json_constant)
    except RobustnessContractError:
        raise
    except ValueError as exc:
        raise RobustnessContractError(
            "INPUT_UNREADABLE",
            f"cannot parse robustness input {path}: {exc}",
            details={"path": str(path)},
        ) from exc
    return validate_robustness_input(document, contract_path=contract_path)


def _finite(value: Any, *, reason_code: str, name: str) -> float:
    if not _is_number(value):
        raise RobustnessContractError(reason_code, f"{name} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise RobustnessContractError(
            "NON_FINITE_NUMBER", f"{name} must be finite"
        )
    return number


def _walk_forbidden(value: Any, path: str, found: list[str]) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            lowered = str(key).lower()
            if lowered in FORBIDDEN_LEAK_FIELDS or lowered.startswith("model_a"):
                found.append(f"{path}.{key}")
            _walk_forbidden(child, f"{path}.{key}", found)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_forbidden(child, f"{path}[{index}]", found)


def check_forbidden_features(request: Any) -> list[str]:
    """Return every forbidden feature path found in a projected request.

    The ``information_boundary`` block names the boundary flags themselves
    (``hero_ev_consumed``, ``model_a_consumed``, ...) and is asserted all-false
    separately, so it is not scanned as a feature leak.
    """
    scanned = request
    if isinstance(request, Mapping):
        scanned = {
            key: value
            for key, value in request.items()
            if key != "information_boundary"
        }
    found: list[str] = []
    _walk_forbidden(scanned, "$", found)
    return sorted(set(found))


def assert_no_forbidden_features(request: Mapping[str, Any]) -> None:
    """Fail closed when the projected request leaks a forbidden feature."""
    hits = check_forbidden_features(request)
    if hits:
        raise RobustnessContractError(
            "FORBIDDEN_FEATURE",
            "projected #344 request leaked forbidden Model A/EV/robustness "
            "features: " + ", ".join(hits),
            details={"hits": hits},
        )


def validate_projected_request(request: Mapping[str, Any]) -> Mapping[str, Any]:
    """Validate a projected request against #344 plus the final leak scan."""
    if not isinstance(request, Mapping):
        raise RobustnessContractError(
            "INPUT_NOT_OBJECT", "projected harness request must be an object"
        )
    # The final forbidden-feature scan runs first so a leak is always reported
    # as FORBIDDEN_FEATURE, before the harness' own (code-free) validation.
    assert_no_forbidden_features(request)
    try:
        validate_harness_request(request)
    except ValueError as exc:
        raise RobustnessContractError(
            "HARNESS_REQUEST_INVALID",
            f"projected request rejected by the #344 harness: {exc}",
        ) from exc
    return request


def _project_alternatives(
    hero_entry: Mapping[str, Any],
    *,
    hero_contribution_before_bb: float,
) -> list[dict[str, Any]]:
    alternatives = hero_entry.get("alternatives")
    if not isinstance(alternatives, list) or not alternatives:
        raise RobustnessContractError(
            "ALTERNATIVES_MISSING",
            "hero_entry.alternatives must be a non-empty array",
        )

    projected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, alternative in enumerate(alternatives):
        path = f"$.hero_entry.alternatives[{index}]"
        if not isinstance(alternative, Mapping):
            raise RobustnessContractError(
                "ALTERNATIVE_INVALID", f"{path} must be an object"
            )
        alternative_id = alternative.get("alternative_id")
        if not isinstance(alternative_id, str) or not alternative_id:
            raise RobustnessContractError(
                "ALTERNATIVE_INVALID", f"{path}.alternative_id is required"
            )
        if alternative_id in seen:
            raise RobustnessContractError(
                "ALTERNATIVE_INVALID",
                f"{path}.alternative_id {alternative_id!r} is duplicated",
            )
        seen.add(alternative_id)

        action = str(alternative.get("action") or "").upper()
        if action not in SUPPORTED_HERO_ACTIONS:
            raise RobustnessContractError(
                "UNSUPPORTED_ACTION",
                f"{path}.action {alternative.get('action')!r} is not a supported "
                f"Hero action {sorted(SUPPORTED_HERO_ACTIONS)}",
            )

        sizing = alternative.get("sizing")
        if action == "FOLD":
            if sizing is not None and _finite(
                sizing, reason_code="ALTERNATIVE_INVALID", name=f"{path}.sizing"
            ) != 0.0:
                raise RobustnessContractError(
                    "ALTERNATIVE_INVALID",
                    f"{path} FOLD sizing must be null or zero",
                )
            target: float | None = None
            incremental = 0.0
        else:
            target = _finite(
                sizing, reason_code="ALTERNATIVE_INVALID", name=f"{path}.sizing"
            )
            incremental = target - hero_contribution_before_bb
            if incremental < 0:
                raise RobustnessContractError(
                    "ALTERNATIVE_INVALID",
                    f"{path}.sizing {target} is below Hero current contribution "
                    f"{hero_contribution_before_bb}",
                )

        projected.append(
            {
                "alternative_id": alternative_id,
                "action": action,
                "target_total_bb": target,
                "incremental_cost_bb": float(incremental),
            }
        )
    return projected


def _validate_context(context: Any) -> Mapping[str, Any]:
    if not isinstance(context, Mapping):
        raise RobustnessContractError(
            "CONTEXT_INVALID",
            "a public synthetic harness context is required for the projection",
        )
    if context.get("synthetic_fixture") is not True:
        raise RobustnessContractError(
            "CONTEXT_INVALID",
            "the projection accepts synthetic harness contexts only "
            "(synthetic_fixture=true)",
        )
    missing = [key for key in _CONTEXT_REQUIRED_FIELDS if context.get(key) is None]
    if missing:
        raise RobustnessContractError(
            "CONTEXT_INVALID",
            f"harness context is missing required fields: {missing}",
            details={"missing": missing},
        )
    return context


def project_to_harness_request(
    robustness_input: Any,
    context: Mapping[str, Any] | None = None,
    *,
    public_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project a validated #425 input onto a #344 harness request.

    Only the public action identity crosses the boundary. Each alternative is
    reduced to ``alternative_id``, ``action``, the exact ``target_total_bb``
    derived from ``sizing`` and the ``incremental_cost_bb`` versus the context
    Hero contribution; the EV envelope, uncertainty, paired delta, route/source,
    support verdict and posterior references are dropped, never copied and never
    defaulted. The result keeps ``source_kind=SYNTHETIC_HARNESS_ONLY``,
    ``synthetic_fixture=true`` and an all-false information boundary, is accepted
    by ``harness.validate_request`` and passes the final forbidden-feature scan.
    """
    if context is None:
        context = public_context
    document = validate_robustness_input(robustness_input)
    public = _validate_context(context)
    hero_entry = _validate_hero_entry(document)

    context_position = str(public.get("hero_position") or "").upper()
    entry_position = hero_entry.get("hero_position")
    if entry_position is not None and str(entry_position).upper() != context_position:
        raise RobustnessContractError(
            "CONTEXT_INVALID",
            f"hero_entry.hero_position {entry_position!r} does not match context "
            f"hero_position {public.get('hero_position')!r}",
        )

    hero_before = _finite(
        public.get("hero_contribution_before_bb"),
        reason_code="CONTEXT_INVALID",
        name="hero_contribution_before_bb",
    )
    context_id = (
        hero_entry.get("context_id")
        or public.get("context_id")
        or public.get("scenario_id")
    )
    if not context_id:
        raise RobustnessContractError(
            "CONTEXT_ID_MISSING",
            "the projection requires hero_entry.context_id or a context id",
        )

    request: dict[str, Any] = {
        "schema": REQUEST_SCHEMA,
        "source_kind": PROJECTED_SOURCE_KIND,
        "synthetic_fixture": True,
        "decision_ref": {
            "canonical_schema": CANONICAL_DECISION_SCHEMA,
            "decision_id": hero_entry.get("decision_id"),
            "context_id": context_id,
        },
        "public_context": copy.deepcopy(dict(public)),
        "alternatives": _project_alternatives(
            hero_entry, hero_contribution_before_bb=hero_before
        ),
        "information_boundary": {
            flag: False for flag in INFORMATION_BOUNDARY_FLAGS
        },
    }
    for alternative in request["alternatives"]:
        if tuple(alternative) != _PROJECTED_ALTERNATIVE_KEYS:
            raise RobustnessContractError(  # pragma: no cover - defensive
                "PROJECTION_INVALID",
                "projected alternative keys must be exactly "
                f"{list(_PROJECTED_ALTERNATIVE_KEYS)}",
            )

    validate_projected_request(request)
    return request


# Compatibility aliases: one implementation, several call-site spellings.
validate_input = validate_robustness_input
validate = validate_robustness_input
load_input = load_robustness_input
load = load_robustness_input
load_and_validate = load_robustness_input
project_harness_request = project_to_harness_request
project_to_harness = project_to_harness_request
project_request = project_to_harness_request
project_robustness_input = project_to_harness_request
scan_forbidden_features = check_forbidden_features

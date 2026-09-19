#!/usr/bin/env python3
"""Bind #322 iso-sizing posterior references to final #320 posterior records.

This module intentionally does not reimplement posterior projection or semantic
validation. Every bound record is first validated by
src.ranges.posterior_range.validate_posterior_range().
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from src.ranges.posterior_range import SCHEMA as POSTERIOR_SCHEMA
from src.ranges.posterior_range import validate_posterior_range

DIAGNOSTICS_SCHEMA = "poker-preflop-iso-sizing-diagnostics/v1"


class IsoSizingPosteriorBindingError(ValueError):
    pass


def _fail(message: str) -> None:
    raise IsoSizingPosteriorBindingError(message)


def _validate_record(record: Any) -> Mapping[str, Any]:
    errors = validate_posterior_range(record)
    if errors:
        _fail("invalid #320 posterior record: " + "; ".join(errors))
    return record


def reference_from_posterior_record(ref_id: str, record: Mapping[str, Any]) -> dict[str, Any]:
    """Project only immutable #320 identity needed by the diagnostics artifact."""
    record = _validate_record(record)
    if not isinstance(ref_id, str) or not ref_id.strip():
        _fail("ref_id is required")
    provenance = record["provenance"]
    return {
        "ref_id": ref_id,
        "schema": POSTERIOR_SCHEMA,
        "hand_id": record["hand_id"],
        "step_id": record["step_id"],
        "public_state_fingerprint": record["public_state_fingerprint"],
        "player": record["player"],
        "position": record["position"],
        "identity": deepcopy(record["identity"]),
        "moment": record["moment"],
        "public_action": deepcopy(record["public_action"]),
        "status": record["status"],
        "distribution_fingerprint": record["distribution_fingerprint"],
        "source_fingerprint": provenance["source_fingerprint"],
    }


def validate_reference_against_record(
    reference: Mapping[str, Any],
    record: Mapping[str, Any],
    *,
    expected_position: str | None = None,
    expected_response: str | None = None,
) -> bool:
    """Validate a compact #322 reference against one full, valid #320 record."""
    if not isinstance(reference, Mapping):
        _fail("posterior reference must be an object")
    ref_id = reference.get("ref_id")
    projected = reference_from_posterior_record(str(ref_id or ""), record)

    if dict(reference) != projected:
        keys = sorted(set(reference) | set(projected))
        mismatches = [key for key in keys if reference.get(key) != projected.get(key)]
        _fail("posterior reference mismatch: " + ", ".join(mismatches))

    if projected["schema"] != POSTERIOR_SCHEMA:
        _fail(f"posterior schema must be {POSTERIOR_SCHEMA}")
    if expected_position is not None and projected["position"] != expected_position:
        _fail("posterior position does not match diagnostic position")
    if expected_response is not None:
        if projected["moment"] != "AFTER_ACTION":
            _fail("diagnostic response posterior must use AFTER_ACTION")
        action = projected.get("public_action")
        if not isinstance(action, Mapping) or str(action.get("action") or "").upper() != str(expected_response).upper():
            _fail("posterior public action does not match diagnostic response")
    return True


def validate_diagnostics_posterior_bindings(
    diagnostics: Mapping[str, Any],
    records_by_ref: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Validate every #322 posterior reference through the final #320 validator."""
    if not isinstance(diagnostics, Mapping) or diagnostics.get("schema") != DIAGNOSTICS_SCHEMA:
        _fail(f"expected {DIAGNOSTICS_SCHEMA}")
    if not isinstance(records_by_ref, Mapping):
        _fail("records_by_ref must be an object")

    validated = 0
    referenced_ids: set[str] = set()
    for alternative in diagnostics.get("alternatives") or []:
        refs = alternative.get("posterior_refs")
        if refs is None:
            continue
        if not isinstance(refs, list):
            _fail("posterior_refs must be a list or null")
        for entry in refs:
            if not isinstance(entry, Mapping) or not isinstance(entry.get("ref"), Mapping):
                _fail("posterior_refs entry/ref must be objects")
            reference = entry["ref"]
            ref_id = reference.get("ref_id")
            if ref_id not in records_by_ref:
                _fail(f"posterior record not found for {ref_id!r}")
            validate_reference_against_record(
                reference,
                records_by_ref[ref_id],
                expected_position=str(entry.get("position") or ""),
                expected_response=str(entry.get("response") or ""),
            )
            referenced_ids.add(str(ref_id))
            validated += 1

    if validated == 0:
        _fail("diagnostics contain no posterior references to validate")
    return {
        "schema": "poker-preflop-iso-posterior-binding-validation/v1",
        "posterior_schema": POSTERIOR_SCHEMA,
        "validated_references": validated,
        "unique_records": len(referenced_ids),
        "selection_effect": "NONE_EXPLANATORY_ONLY",
    }

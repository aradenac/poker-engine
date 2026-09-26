#!/usr/bin/env python3
"""Machine-readable Model B Hero robustness classifier (#425).

``classify_robustness`` turns one already evaluated, robustness-shaped input
(``hero-model-b-robustness-input/v1``) into a single deterministic verdict
drawn from the closed ``STATUSES`` vocabulary. It never runs a Model B
evaluation, never blends the declared environments into a mean and never emits
a status outside ``STATUSES``.

Precedence (most severe first) is fixed and fail-closed:

1. ``OOD_UNTESTABLE`` -- an alternative is out of distribution
   (``support.ood`` true), its declared ``support.status`` is not an admissible
   verdict, or the ``support`` block is missing; the comparison cannot be tested.
2. ``INSUFFICIENT_SUPPORT`` -- ``provenance`` is missing or incomplete, the
   information boundary is violated, ``support.status`` is explicitly
   ``INSUFFICIENT_SUPPORT``, ``ev_bb`` is missing or invalid, the compared
   alternative carries no ``uncertainty``, or its CI95 width exceeds the policy
   bound.
3. ``TOO_CLOSE`` -- the advantage over the runner-up (or an explicit paired
   delta / paired CI) sits inside the policy noise, so no ordering can be
   asserted.
4. ``SENSITIVE`` -- the declared support, or an explicit stability block,
   reports an unstable action / sizing / ranking.
5. ``CONSISTENT`` -- every alternative keeps its standing within the declared
   policy tolerances.

The function is pure: identical inputs always produce identical outputs, ties
are broken lexically on ``alternative_id`` and ``reason_codes`` are sorted. No
per-environment share is ever synthesized, and no Model A value is read or
exposed.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

__all__ = [
    "STATUSES",
    "STATUS_PRECEDENCE",
    "REASON_CODES",
    "RobustnessPolicy",
    "DEFAULT_POLICY",
    "classify_robustness",
]

OUTPUT_SCHEMA = "model-b-hero-robustness-status/v1"
INPUT_SCHEMA = "hero-model-b-robustness-input/v1"

#: The exact, closed status vocabulary. ``classify_robustness`` may never emit
#: anything else.
STATUSES = frozenset(
    {
        "CONSISTENT",
        "SENSITIVE",
        "TOO_CLOSE",
        "INSUFFICIENT_SUPPORT",
        "OOD_UNTESTABLE",
    }
)

#: Precedence order, most severe first. Kept as a tuple so the ordering itself
#: is testable and never depends on set iteration order.
STATUS_PRECEDENCE = (
    "OOD_UNTESTABLE",
    "INSUFFICIENT_SUPPORT",
    "TOO_CLOSE",
    "SENSITIVE",
    "CONSISTENT",
)

_OOD_REASON_CODES = frozenset(
    {
        "INPUT_NOT_MAPPING",
        "ALTERNATIVES_MISSING",
        "ALTERNATIVE_INVALID",
        "SUPPORT_MISSING",
        "SUPPORT_OOD",
        "SUPPORT_STATUS_OOD",
        "SUPPORT_STATUS_UNKNOWN",
    }
)
_INSUFFICIENT_REASON_CODES = frozenset(
    {
        "PROVENANCE_MISSING",
        "PROVENANCE_INCOMPLETE",
        "INFORMATION_BOUNDARY_VIOLATION",
        "SUPPORT_STATUS_INSUFFICIENT",
        "EV_MISSING",
        "EV_INVALID",
        "UNCERTAINTY_MISSING",
        "UNCERTAINTY_INVALID",
        "CI95_WIDTH_EXCEEDS_POLICY",
    }
)
_TOO_CLOSE_REASON_CODES = frozenset(
    {
        "SUPPORT_STATUS_TOO_CLOSE",
        "ADVANTAGE_WITHIN_TOLERANCE",
        "PAIRED_DELTA_WITHIN_TOLERANCE",
        "PAIRED_CI_INCLUDES_ZERO",
    }
)
_SENSITIVE_REASON_CODES = frozenset(
    {
        "SUPPORT_STATUS_SENSITIVE",
        "UNSTABLE_ACTION",
        "UNSTABLE_SIZING",
        "UNSTABLE_RANKING",
    }
)
_CONSISTENT_REASON_CODES = frozenset({"CONSISTENT_ACROSS_ENVIRONMENTS"})

_REASON_CODES_BY_STATUS = {
    "OOD_UNTESTABLE": _OOD_REASON_CODES,
    "INSUFFICIENT_SUPPORT": _INSUFFICIENT_REASON_CODES,
    "TOO_CLOSE": _TOO_CLOSE_REASON_CODES,
    "SENSITIVE": _SENSITIVE_REASON_CODES,
    "CONSISTENT": _CONSISTENT_REASON_CODES,
}

#: Every explicit reason code the classifier may report.
REASON_CODES = frozenset().union(*_REASON_CODES_BY_STATUS.values())

#: The declared environments are read as a single envelope: no per-environment
#: share is ever derived to blend them into a mean.
ENVIRONMENT_AGGREGATION = "ENVELOPE_ONLY"

_EPS = 1e-12


@dataclass(frozen=True)
class RobustnessPolicy:
    """Thresholds and fail-closed switches used by :func:`classify_robustness`.

    ``too_close_tolerance_bb`` is the quasi-dominant gap below which no ordering
    can be asserted. ``max_ci95_width_bb`` is the largest Monte-Carlo CI95 width
    accepted for the compared alternatives. Both are explicit policy inputs: the
    classifier never derives a threshold from the data and never turns an
    environment into a per-environment share.
    """

    too_close_tolerance_bb: float = 0.05
    max_ci95_width_bb: float = 1.0
    require_uncertainty: bool = True
    require_provenance: bool = True


DEFAULT_POLICY = RobustnessPolicy()


def _finite(value: Any, *, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def _finite_or_none(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def _coerce_policy(policy: Any) -> RobustnessPolicy:
    if policy is None:
        return DEFAULT_POLICY
    if isinstance(policy, RobustnessPolicy):
        candidate = policy
    else:
        def _get(key: str) -> Any:
            if isinstance(policy, Mapping):
                if key in policy:
                    return policy[key]
                return getattr(DEFAULT_POLICY, key)
            return getattr(policy, key, getattr(DEFAULT_POLICY, key))

        candidate = RobustnessPolicy(
            too_close_tolerance_bb=_get("too_close_tolerance_bb"),
            max_ci95_width_bb=_get("max_ci95_width_bb"),
            require_uncertainty=_get("require_uncertainty"),
            require_provenance=_get("require_provenance"),
        )
    tolerance = _finite(candidate.too_close_tolerance_bb, name="too_close_tolerance_bb")
    if tolerance < 0:
        raise ValueError("too_close_tolerance_bb must be non-negative")
    max_width = _finite(candidate.max_ci95_width_bb, name="max_ci95_width_bb")
    if max_width < 0:
        raise ValueError("max_ci95_width_bb must be non-negative")
    return RobustnessPolicy(
        too_close_tolerance_bb=tolerance,
        max_ci95_width_bb=max_width,
        require_uncertainty=bool(candidate.require_uncertainty),
        require_provenance=bool(candidate.require_provenance),
    )


def _alternative_id(raw: Mapping[str, Any], index: int) -> str:
    explicit = raw.get("alternative_id")
    if explicit is not None and str(explicit) != "":
        return str(explicit)
    action = str(raw.get("action") or "").upper()
    if action:
        sizing = _finite_or_none(raw.get("sizing"))
        sizing_label = "NONE" if sizing is None else f"{sizing:.9f}"
        return f"{action}@{sizing_label}"
    return f"alternative[{index}]"


def _parse_uncertainty(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    ci = value.get("ci95")
    if not isinstance(ci, Sequence) or isinstance(ci, (str, bytes)) or len(ci) != 2:
        return None
    low = _finite_or_none(ci[0])
    high = _finite_or_none(ci[1])
    if low is None or high is None or low > high:
        return None
    reported_width = _finite_or_none(value.get("width_bb"))
    width = reported_width if reported_width is not None else high - low
    if width < 0:
        return None
    return {"ci95": [low, high], "width_bb": width}


def _paired_ci_includes_zero(value: Any) -> bool:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 2:
        return False
    low = _finite_or_none(value[0])
    high = _finite_or_none(value[1])
    if low is None or high is None or low > high:
        return False
    return low <= 0.0 <= high


def _sorted_unique(values: Sequence[str]) -> list[str]:
    return sorted({str(value) for value in values})


def _base_evidence(policy: RobustnessPolicy) -> dict[str, Any]:
    return {
        "schema": OUTPUT_SCHEMA,
        "input_schema": INPUT_SCHEMA,
        "decision_id": None,
        "alternative_count": 0,
        "comparison": "NO_ALTERNATIVES",
        "ranked_alternatives": [],
        "best_alternative_id": None,
        "second_best_alternative_id": None,
        "advantage_bb": None,
        "stability": None,
        "declared_statuses": {},
        "ood_alternatives": [],
        "unsupported_alternatives": [],
        "too_close_alternatives": [],
        "sensitive_alternatives": [],
        "support_missing_alternatives": [],
        "invalid_alternatives": [],
        "ev_missing_alternatives": [],
        "ev_invalid_alternatives": [],
        "missing_uncertainty_alternatives": [],
        "invalid_uncertainty_alternatives": [],
        "ci95_width_exceeding_alternatives": [],
        "boundary_violations": [],
        "provenance_present": False,
        "information_boundary_present": False,
        "environment_aggregation": ENVIRONMENT_AGGREGATION,
        "policy": {
            "too_close_tolerance_bb": policy.too_close_tolerance_bb,
            "max_ci95_width_bb": policy.max_ci95_width_bb,
            "require_uncertainty": policy.require_uncertainty,
            "require_provenance": policy.require_provenance,
        },
    }


def _finalize(status: str, reasons: Sequence[str], evidence: dict[str, Any]) -> dict[str, Any]:
    if status not in STATUSES:  # pragma: no cover - defensive invariant
        raise AssertionError(f"classifier produced non-vocabulary status: {status!r}")
    return {
        "status": status,
        "reason_codes": _sorted_unique(reasons),
        "evidence": _normalize_evidence(evidence),
    }


def _resolve_status(buckets: Mapping[str, set[str]]) -> str:
    for status in STATUS_PRECEDENCE:
        if status == "CONSISTENT":
            break
        if buckets[status]:
            return status
    return "CONSISTENT"


def _buckets_for_evidence(buckets: Mapping[str, set[str]]) -> dict[str, list[str]]:
    return {status: _sorted_unique(list(buckets[status])) for status in STATUS_PRECEDENCE}


_LIST_EVIDENCE_KEYS = (
    "ood_alternatives",
    "unsupported_alternatives",
    "too_close_alternatives",
    "sensitive_alternatives",
    "support_missing_alternatives",
    "invalid_alternatives",
    "ev_missing_alternatives",
    "ev_invalid_alternatives",
    "missing_uncertainty_alternatives",
    "invalid_uncertainty_alternatives",
    "ci95_width_exceeding_alternatives",
    "boundary_violations",
)


def _normalize_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(evidence)
    for key in _LIST_EVIDENCE_KEYS:
        normalized[key] = _sorted_unique(normalized.get(key, []))
    return normalized


def classify_robustness(input: Any, *, policy: Any = None) -> dict[str, Any]:
    """Classify one robustness-shaped input into a single explicit status.

    The return value is exactly ``{"status", "reason_codes", "evidence"}``. The
    function is deterministic: the same input always yields the same output, and
    reordering the ``alternatives`` list does not change the result.
    """
    effective = _coerce_policy(policy)
    buckets: dict[str, set[str]] = {status: set() for status in STATUS_PRECEDENCE}
    evidence = _base_evidence(effective)

    if not isinstance(input, Mapping):
        buckets["OOD_UNTESTABLE"].add("INPUT_NOT_MAPPING")
        evidence["reason_codes_by_status"] = _buckets_for_evidence(buckets)
        return _finalize("OOD_UNTESTABLE", buckets["OOD_UNTESTABLE"], evidence)

    decision = input.get("decision")
    if isinstance(decision, Mapping):
        decision_id = decision.get("decision_id")
        evidence["decision_id"] = None if decision_id is None else str(decision_id)

    # --- Provenance and hard information boundary -----------------------------
    provenance = input.get("provenance")
    provenance_present = isinstance(provenance, Mapping) and bool(provenance)
    evidence["provenance_present"] = provenance_present
    if effective.require_provenance:
        if not provenance_present:
            buckets["INSUFFICIENT_SUPPORT"].add("PROVENANCE_MISSING")
        else:
            required_provenance = (
                "parent_issue",
                "upstream_result_schema",
                "synthetic_fixture",
                "real_issue_367_consumed",
                "real_issue_314_consumed",
                "validation_consumed",
                "test_consumed",
            )
            if any(key not in provenance for key in required_provenance):
                buckets["INSUFFICIENT_SUPPORT"].add("PROVENANCE_INCOMPLETE")

    boundary = input.get("information_boundary")
    boundary_present = isinstance(boundary, Mapping)
    evidence["information_boundary_present"] = boundary_present
    if boundary_present:
        violations = sorted(key for key, value in boundary.items() if value is not False)
        if violations:
            buckets["INSUFFICIENT_SUPPORT"].add("INFORMATION_BOUNDARY_VIOLATION")
            evidence["boundary_violations"] = violations

    # --- Per-alternative evidence ---------------------------------------------
    raw_alternatives = input.get("alternatives")
    if (
        isinstance(raw_alternatives, Sequence)
        and not isinstance(raw_alternatives, (str, bytes))
        and len(raw_alternatives) > 0
    ):
        alternatives = list(raw_alternatives)
    else:
        alternatives = []
        buckets["OOD_UNTESTABLE"].add("ALTERNATIVES_MISSING")
    evidence["alternative_count"] = len(alternatives)

    evaluated: list[dict[str, Any]] = []
    declared_statuses: list[tuple[str, str]] = []
    for index, raw in enumerate(alternatives):
        if not isinstance(raw, Mapping):
            buckets["OOD_UNTESTABLE"].add("ALTERNATIVE_INVALID")
            evidence["invalid_alternatives"].append(f"alternative[{index}]")
            continue
        alternative_id = _alternative_id(raw, index)
        support = raw.get("support")
        declared_status: str | None = None
        if not isinstance(support, Mapping):
            buckets["OOD_UNTESTABLE"].add("SUPPORT_MISSING")
            evidence["support_missing_alternatives"].append(alternative_id)
        else:
            declared_status = str(support.get("status") or "")
            declared_statuses.append((alternative_id, declared_status))
            if support.get("ood") is True or raw.get("ood") is True:
                buckets["OOD_UNTESTABLE"].add("SUPPORT_OOD")
                evidence["ood_alternatives"].append(alternative_id)
            if declared_status == "OOD_UNTESTABLE":
                buckets["OOD_UNTESTABLE"].add("SUPPORT_STATUS_OOD")
                evidence["ood_alternatives"].append(alternative_id)
            elif declared_status not in STATUSES:
                buckets["OOD_UNTESTABLE"].add("SUPPORT_STATUS_UNKNOWN")
                evidence["ood_alternatives"].append(alternative_id)
            elif declared_status == "INSUFFICIENT_SUPPORT":
                buckets["INSUFFICIENT_SUPPORT"].add("SUPPORT_STATUS_INSUFFICIENT")
                evidence["unsupported_alternatives"].append(alternative_id)
            elif declared_status == "TOO_CLOSE":
                buckets["TOO_CLOSE"].add("SUPPORT_STATUS_TOO_CLOSE")
                evidence["too_close_alternatives"].append(alternative_id)
            elif declared_status == "SENSITIVE":
                buckets["SENSITIVE"].add("SUPPORT_STATUS_SENSITIVE")
                evidence["sensitive_alternatives"].append(alternative_id)

        raw_ev = raw.get("ev_bb")
        ev_bb = _finite_or_none(raw_ev)
        if raw_ev is None:
            buckets["INSUFFICIENT_SUPPORT"].add("EV_MISSING")
            evidence["ev_missing_alternatives"].append(alternative_id)
        elif ev_bb is None:
            buckets["INSUFFICIENT_SUPPORT"].add("EV_INVALID")
            evidence["ev_invalid_alternatives"].append(alternative_id)

        evaluated.append(
            {
                "alternative_id": alternative_id,
                "action": str(raw.get("action") or "").upper(),
                "sizing": _finite_or_none(raw.get("sizing")),
                "ev_bb": ev_bb,
                "paired_delta_vs_best_bb": _finite_or_none(raw.get("paired_delta_vs_best_bb")),
                "paired_delta_ci95": raw.get("paired_delta_ci95"),
                "uncertainty": raw.get("uncertainty"),
                "declared_status": declared_status,
            }
        )

    evidence["declared_statuses"] = dict(sorted(declared_statuses))

    # Deterministic ranking: highest EV first, ties broken lexically by id.
    ranked = sorted(
        (item for item in evaluated if item["ev_bb"] is not None),
        key=lambda item: (-item["ev_bb"], item["alternative_id"]),
    )
    evidence["ranked_alternatives"] = [
        {
            "alternative_id": item["alternative_id"],
            "action": item["action"],
            "sizing": item["sizing"],
            "ev_bb": item["ev_bb"],
            "paired_delta_vs_best_bb": item["paired_delta_vs_best_bb"],
            "declared_status": item["declared_status"],
        }
        for item in ranked
    ]

    if not ranked:
        evidence["comparison"] = "NO_EVALUATED_ALTERNATIVE"
    else:
        evidence["comparison"] = (
            "SINGLE_ALTERNATIVE" if len(ranked) == 1 else "PAIRED_ALTERNATIVES"
        )
        best = ranked[0]
        evidence["best_alternative_id"] = best["alternative_id"]
        if len(ranked) >= 2:
            evidence["second_best_alternative_id"] = ranked[1]["alternative_id"]

        # --- INSUFFICIENT: uncertainty of the compared alternatives -----------
        for item in ranked[:2]:
            alternative_id = item["alternative_id"]
            uncertainty = item["uncertainty"]
            if uncertainty is None:
                if effective.require_uncertainty:
                    buckets["INSUFFICIENT_SUPPORT"].add("UNCERTAINTY_MISSING")
                    evidence["missing_uncertainty_alternatives"].append(alternative_id)
                continue
            parsed = _parse_uncertainty(uncertainty)
            if parsed is None:
                buckets["INSUFFICIENT_SUPPORT"].add("UNCERTAINTY_INVALID")
                evidence["invalid_uncertainty_alternatives"].append(alternative_id)
                continue
            if parsed["width_bb"] > effective.max_ci95_width_bb + _EPS:
                buckets["INSUFFICIENT_SUPPORT"].add("CI95_WIDTH_EXCEEDS_POLICY")
                evidence["ci95_width_exceeding_alternatives"].append(alternative_id)

        # --- TOO_CLOSE: gap inside the declared noise -------------------------
        if len(ranked) >= 2:
            advantage = best["ev_bb"] - ranked[1]["ev_bb"]
            evidence["advantage_bb"] = advantage
            if advantage <= effective.too_close_tolerance_bb + _EPS:
                buckets["TOO_CLOSE"].add("ADVANTAGE_WITHIN_TOLERANCE")
                evidence["too_close_alternatives"].append(ranked[1]["alternative_id"])
            for item in ranked[1:]:
                delta = item["paired_delta_vs_best_bb"]
                if delta is not None and abs(delta) <= effective.too_close_tolerance_bb + _EPS:
                    buckets["TOO_CLOSE"].add("PAIRED_DELTA_WITHIN_TOLERANCE")
                    evidence["too_close_alternatives"].append(item["alternative_id"])
                if _paired_ci_includes_zero(item["paired_delta_ci95"]):
                    buckets["TOO_CLOSE"].add("PAIRED_CI_INCLUDES_ZERO")
                    evidence["too_close_alternatives"].append(item["alternative_id"])

    # --- SENSITIVE: explicit action / sizing / ranking instability -------------
    stability = input.get("stability")
    if isinstance(stability, Mapping):
        stability_evidence: dict[str, Any] = {}
        for key, code in (
            ("action", "UNSTABLE_ACTION"),
            ("sizing", "UNSTABLE_SIZING"),
            ("ranking", "UNSTABLE_RANKING"),
        ):
            value = stability.get(key)
            stability_evidence[key] = None if value is None else bool(value is True)
            if value is False:
                buckets["SENSITIVE"].add(code)
        evidence["stability"] = stability_evidence

    status = _resolve_status(buckets)
    if status == "CONSISTENT":
        buckets["CONSISTENT"].add("CONSISTENT_ACROSS_ENVIRONMENTS")

    evidence["reason_codes_by_status"] = _buckets_for_evidence(buckets)
    return _finalize(status, buckets[status], evidence)

#!/usr/bin/env python3
"""Deterministic, fail-closed Hero robustness status classifier (task ``backlog-nhg``).

``classify(hero_entry)`` turns one already evaluated Hero robustness entry (the
``hero_entry`` block of ``hero-model-b-robustness-input/v1``) into exactly one
verdict drawn from the closed vocabulary :data:`STATUSES`::

    {"status": "<one of STATUSES>", "reason_codes": ["<sorted>", ...]}

The classifier is a pure function: it never runs a Model B evaluation, never
reads a private/predictive feature, never blends environments into a mean and
never invents a per-environment share. Identical inputs always produce identical
outputs (the same status and the same sorted ``reason_codes``), and the order of
``alternatives`` never changes the result.

Precedence is fixed and strict, most severe first
(:data:`STATUS_PRECEDENCE`):

1. ``OOD_UNTESTABLE`` -- the support verdict is missing/invalid, declares an
   out-of-distribution environment (``support.ood`` true) or a status outside the
   closed vocabulary, so the comparison cannot be tested at all.
2. ``INSUFFICIENT_SUPPORT`` -- the declared support is present but sparse
   (``INSUFFICIENT_SUPPORT`` status or a sparse tier), the comparison set /
   evaluated EV is missing, or the Monte-Carlo uncertainty envelope of the Hero
   entry or of any compared alternative is missing, malformed, incoherent
   (``width_bb`` contradicting the ``ci95`` bounds, reversed or non-finite
   bounds, invalid declared width) or wider than :data:`MAX_CI95_WIDTH_BB`.
3. ``TOO_CLOSE`` -- the alternative standing sits inside the noise band
   (:data:`TOO_CLOSE_DELTA_BB`): the runner-up is quasi ex-aequo or an explicit
   ``paired_delta`` sits in the band, so no ordering can be asserted. ``TOO_CLOSE``
   is never collapsed into ``CONSISTENT``/``SENSITIVE``.
4. ``SENSITIVE`` -- the standing holds only within the wider sensitivity band
   (:data:`SENSITIVE_DELTA_BB`): a sizing variation beyond the close band moves
   the outcome, or the declared support reports ``SENSITIVE``.
5. ``CONSISTENT`` -- the standing survives every declared tolerance.

Fail-closed: ``hero_entry`` must be a mapping carrying every required field
(:data:`REQUIRED_HERO_ENTRY_FIELDS`) and each alternative must carry
:data:`REQUIRED_ALTERNATIVE_FIELDS`. A missing/unknown structure raises an
explicit :class:`RobustnessClassifyError` (a ``ValueError``) instead of silently
defaulting to a status. A field that is *present but null* is the schema's
"not evaluated" marker and is classified through the precedence above rather
than through an error.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence

__all__ = [
    "SCHEMA",
    "Status",
    "STATUSES",
    "STATUS_PRECEDENCE",
    "STATUS_VALUES",
    "STATUS_ENUM",
    "ROBUSTNESS_STATUSES",
    "REASON_CODES",
    "REASON_CODES_BY_STATUS",
    "REQUIRED_HERO_ENTRY_FIELDS",
    "REQUIRED_ALTERNATIVE_FIELDS",
    "TOO_CLOSE_DELTA_BB",
    "SENSITIVE_DELTA_BB",
    "MAX_CI95_WIDTH_BB",
    "CI95_WIDTH_TOLERANCE_BB",
    "SPARSE_TIERS",
    "REQUIRE_UNCERTAINTY",
    "RobustnessPolicy",
    "DEFAULT_POLICY",
    "RobustnessClassifyError",
    "ClassifyError",
    "classify",
    "classify_hero_entry",
]

#: Output schema id of a classification result.
SCHEMA = "model-b-hero-robustness-classify/v1"


class Status(str, Enum):
    """The closed Hero robustness status vocabulary.

    ``str``-mixin so a member compares equal to its plain string value and can be
    emitted directly inside the JSON-serialisable result.
    """

    CONSISTENT = "CONSISTENT"
    SENSITIVE = "SENSITIVE"
    TOO_CLOSE = "TOO_CLOSE"
    INSUFFICIENT_SUPPORT = "INSUFFICIENT_SUPPORT"
    OOD_UNTESTABLE = "OOD_UNTESTABLE"


#: The exact, closed status vocabulary of :func:`classify`. Nothing outside this
#: set may ever be emitted.
STATUSES = frozenset(member.value for member in Status)

#: Precedence order, most severe first. A tuple (never a set) so the ordering
#: itself is testable and never depends on hash iteration order.
STATUS_PRECEDENCE = (
    "OOD_UNTESTABLE",
    "INSUFFICIENT_SUPPORT",
    "TOO_CLOSE",
    "SENSITIVE",
    "CONSISTENT",
)

#: Compatibility aliases for the same closed vocabulary.
STATUS_VALUES = STATUSES
ROBUSTNESS_STATUSES = STATUSES
STATUS_ENUM = Status

# --------------------------------------------------------------------------- #
# Named, documented thresholds.
#
# The classifier never derives a threshold from the data: every band is an
# explicit policy constant so a verdict is reproducible and reviewable.
# --------------------------------------------------------------------------- #

#: Maximum EV advantage (bb) the top-ranked alternative may sit below the Hero
#: entry before the standing is declared ``TOO_CLOSE``. Inside this band the two
#: options are quasi ex-aequo and no ordering may be asserted.
TOO_CLOSE_DELTA_BB = 0.05

#: Sensitivity band (bb). A Hero advantage above :data:`TOO_CLOSE_DELTA_BB` but
#: at or below this bound means a sizing variation can still move the outcome, so
#: the entry is ``SENSITIVE`` rather than ``CONSISTENT``. Must be >= the close
#: band; a wider advantage than this is treated as a settled standing.
SENSITIVE_DELTA_BB = 0.25

#: Largest accepted Monte-Carlo CI95 width (bb) for the Hero entry and the
#: top-ranked alternative. Anything wider is "high uncertainty" and yields
#: ``INSUFFICIENT_SUPPORT``.
MAX_CI95_WIDTH_BB = 1.0

#: Absolute numerical tolerance (bb) used when the declared
#: ``uncertainty.width_bb`` is verified against the width *derived from the*
#: ``ci95`` bounds. Float arithmetic on the endpoints reintroduces a few ulps of
#: noise (``1.45 - 1.39 == 0.06000000000000005``), so the coherence check is an
#: explicit, named tolerance instead of an exact equality -- and the width used
#: for the policy comparison is always the derived one, so a declared width can
#: never shrink (nor widen) a measured envelope.
CI95_WIDTH_TOLERANCE_BB = 1e-9

#: Support tiers that mean "sparse support" and therefore ``INSUFFICIENT_SUPPORT``
#: while the support verdict is present. A tier never upgrades a status: this set
#: only adds severity, it never relaxes one.
SPARSE_TIERS = frozenset({"LOW", "VERY_LOW", "SPARSE", "NONE", "MINIMAL"})

#: Fail-closed switch: a robustness claim without a Monte-Carlo uncertainty
#: envelope is unverifiable and is reported as ``INSUFFICIENT_SUPPORT``.
REQUIRE_UNCERTAINTY = True

#: Required (but possibly null-valued) fields of a ``hero_entry`` block.
REQUIRED_HERO_ENTRY_FIELDS = (
    "action",
    "sizing",
    "ev",
    "uncertainty",
    "paired_delta",
    "route_source",
    "support",
    "posterior_refs",
    "alternatives",
)

#: Required (but possibly null-valued) fields of an ``alternatives[]`` entry.
REQUIRED_ALTERNATIVE_FIELDS = (
    "alternative_id",
    "action",
    "sizing",
    "ev",
    "uncertainty",
    "paired_delta",
    "route_source",
    "support",
    "posterior_refs",
)

_OOD_REASON_CODES = frozenset(
    {
        "INPUT_NOT_MAPPING",
        "SUPPORT_MISSING",
        "SUPPORT_INVALID",
        "SUPPORT_OOD",
        "SUPPORT_STATUS_OOD",
        "SUPPORT_STATUS_UNKNOWN",
    }
)
_INSUFFICIENT_REASON_CODES = frozenset(
    {
        "SUPPORT_STATUS_INSUFFICIENT",
        "SPARSE_SUPPORT_TIER",
        "NO_COMPARISON_SET",
        "NO_EVALUATED_ALTERNATIVE",
        "ALTERNATIVE_EV_MISSING",
        "ALTERNATIVE_EV_INVALID",
        "EV_MISSING",
        "EV_INVALID",
        "UNCERTAINTY_MISSING",
        "UNCERTAINTY_INVALID",
        "UNCERTAINTY_WIDTH_MISMATCH",
        "CI95_WIDTH_EXCEEDS_POLICY",
    }
)
_TOO_CLOSE_REASON_CODES = frozenset(
    {
        "SUPPORT_STATUS_TOO_CLOSE",
        "ADVANTAGE_WITHIN_TOLERANCE",
        "ALTERNATIVE_MATCHES_OR_EXCEEDS_HERO",
        "PAIRED_DELTA_WITHIN_TOLERANCE",
        "PAIRED_CI_INCLUDES_ZERO",
    }
)
_SENSITIVE_REASON_CODES = frozenset(
    {
        "SUPPORT_STATUS_SENSITIVE",
        "ADVANTAGE_WITHIN_SENSITIVITY_BAND",
        "SIZING_VARIATION_WITHIN_SENSITIVITY_BAND",
    }
)
_CONSISTENT_REASON_CODES = frozenset({"CONSISTENT_WITHIN_POLICY"})

#: Reason codes grouped by the status they can accompany.
REASON_CODES_BY_STATUS = {
    "OOD_UNTESTABLE": _OOD_REASON_CODES,
    "INSUFFICIENT_SUPPORT": _INSUFFICIENT_REASON_CODES,
    "TOO_CLOSE": _TOO_CLOSE_REASON_CODES,
    "SENSITIVE": _SENSITIVE_REASON_CODES,
    "CONSISTENT": _CONSISTENT_REASON_CODES,
}

#: Every reason code the classifier may report.
REASON_CODES = frozenset().union(*REASON_CODES_BY_STATUS.values())

_EPS = 1e-12


class RobustnessClassifyError(ValueError):
    """Fail-closed error raised when a required structure/field is missing.

    Carries a machine-readable ``reason_code`` next to the human message so a
    caller can branch without parsing text. It is a :class:`ValueError` so a
    plain ``except ValueError`` still catches it.
    """

    def __init__(self, message: str, *, reason_code: str = "MISSING_REQUIRED_FIELD") -> None:
        super().__init__(message)
        self.reason_code = reason_code


#: Alias kept for callers that prefer the shorter name.
ClassifyError = RobustnessClassifyError


@dataclass(frozen=True)
class RobustnessPolicy:
    """Explicit, named thresholds used by :func:`classify`.

    The default value of every field is the module constant of the same name, so
    the shipped verdicts are reproducible from the constants alone.
    """

    too_close_delta_bb: float = TOO_CLOSE_DELTA_BB
    sensitive_delta_bb: float = SENSITIVE_DELTA_BB
    max_ci95_width_bb: float = MAX_CI95_WIDTH_BB
    ci95_width_tolerance_bb: float = CI95_WIDTH_TOLERANCE_BB
    require_uncertainty: bool = REQUIRE_UNCERTAINTY


DEFAULT_POLICY = RobustnessPolicy()


def _coerce_policy(policy: Any) -> RobustnessPolicy:
    if policy is None:
        return DEFAULT_POLICY
    if isinstance(policy, RobustnessPolicy):
        candidate = policy
    else:
        def _get(key: str) -> Any:
            if isinstance(policy, Mapping):
                return policy.get(key, getattr(DEFAULT_POLICY, key))
            return getattr(policy, key, getattr(DEFAULT_POLICY, key))

        candidate = RobustnessPolicy(
            too_close_delta_bb=_get("too_close_delta_bb"),
            sensitive_delta_bb=_get("sensitive_delta_bb"),
            max_ci95_width_bb=_get("max_ci95_width_bb"),
            ci95_width_tolerance_bb=_get("ci95_width_tolerance_bb"),
            require_uncertainty=_get("require_uncertainty"),
        )
    close_band = _finite(candidate.too_close_delta_bb, name="too_close_delta_bb")
    sensitive_band = _finite(candidate.sensitive_delta_bb, name="sensitive_delta_bb")
    max_width = _finite(candidate.max_ci95_width_bb, name="max_ci95_width_bb")
    width_tolerance = _finite(
        candidate.ci95_width_tolerance_bb, name="ci95_width_tolerance_bb"
    )
    if close_band < 0:
        raise ValueError("too_close_delta_bb must be non-negative")
    if sensitive_band < close_band:
        raise ValueError("sensitive_delta_bb must be >= too_close_delta_bb")
    if max_width < 0:
        raise ValueError("max_ci95_width_bb must be non-negative")
    if width_tolerance < 0:
        raise ValueError("ci95_width_tolerance_bb must be non-negative")
    return RobustnessPolicy(
        too_close_delta_bb=close_band,
        sensitive_delta_bb=sensitive_band,
        max_ci95_width_bb=max_width,
        ci95_width_tolerance_bb=width_tolerance,
        require_uncertainty=bool(candidate.require_uncertainty),
    )


def _finite(value: Any, *, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def _finite_or_none(value: Any) -> float | None:
    """Return ``value`` as a finite float, or ``None`` when it is not a number."""

    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def _envelope_number(value: Any) -> float | None:
    """Return ``value`` as a finite float only when it is a real JSON number.

    The uncertainty envelope is already evaluated evidence, so it is read
    strictly: a numeric *string* (``"0.06"``) is malformed input and is refused
    instead of being coerced, exactly like a non-finite or non-numeric value.
    """

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    if not math.isfinite(result):
        return None
    return result


def _sorted_unique(values: Sequence[str]) -> list[str]:
    return sorted({str(value) for value in values})


def _unwrap_hero_entry(payload: Any) -> Mapping[str, Any]:
    """Return the ``hero_entry`` mapping, tolerating a full #425 document."""

    if not isinstance(payload, Mapping):
        raise RobustnessClassifyError(
            f"hero_entry must be a mapping, got {type(payload).__name__}",
            reason_code="INPUT_NOT_MAPPING",
        )
    nested = payload.get("hero_entry")
    if isinstance(nested, Mapping):
        payload = nested
    return payload


def _require_fields(
    entry: Mapping[str, Any],
    required: Sequence[str],
    *,
    label: str,
) -> None:
    missing = [field for field in required if field not in entry]
    if missing:
        raise RobustnessClassifyError(
            f"{label} is missing required field(s): {', '.join(missing)}",
            reason_code="MISSING_REQUIRED_FIELD",
        )


def _uncertainty_diagnostic(
    value: Any,
    *,
    tolerance: float,
) -> tuple[str | None, float | None]:
    """Verify one uncertainty envelope and return ``(reason_code, width)``.

    ``reason_code`` is ``None`` when the envelope is coherent; otherwise it is
    the ``INSUFFICIENT_SUPPORT`` diagnostic to record. ``width`` is the width
    **derived from the ``ci95`` bounds** whenever those bounds are usable, even
    when the envelope is rejected for another reason, so the policy comparison
    can never be driven by a declared value.

    Fail-closed rules:

    * a non-mapping envelope, a ``ci95`` that is not exactly two finite JSON
      numbers, or reversed bounds (``low > high``) is ``UNCERTAINTY_INVALID``;
    * a missing/``null``/non-numeric (a numeric string is malformed, never
      coerced)/non-finite/negative declared ``width_bb`` is
      ``UNCERTAINTY_INVALID`` as well;
    * a declared ``width_bb`` that contradicts ``high - low`` by more than the
      explicit ``tolerance`` is ``UNCERTAINTY_WIDTH_MISMATCH``.
    """

    if not isinstance(value, Mapping):
        return "UNCERTAINTY_INVALID", None
    ci95 = value.get("ci95")
    if (
        not isinstance(ci95, Sequence)
        or isinstance(ci95, (str, bytes))
        or len(ci95) != 2
    ):
        return "UNCERTAINTY_INVALID", None
    low = _envelope_number(ci95[0])
    high = _envelope_number(ci95[1])
    if low is None or high is None or low > high:
        return "UNCERTAINTY_INVALID", None
    width = high - low

    reported = _envelope_number(value.get("width_bb"))
    if reported is None or reported < 0:
        return "UNCERTAINTY_INVALID", width
    if abs(reported - width) > tolerance:
        return "UNCERTAINTY_WIDTH_MISMATCH", width
    return None, width


def _check_uncertainty(
    entry: Mapping[str, Any],
    buckets: dict[str, set[str]],
    policy: RobustnessPolicy,
) -> None:
    """Fold one entry's ``uncertainty`` envelope into the reason buckets.

    A present-but-null envelope is the schema's "not measured" marker and is
    reported as ``UNCERTAINTY_MISSING``; an incoherent envelope is reported with
    its own diagnostic; a coherent envelope wider than
    :attr:`RobustnessPolicy.max_ci95_width_bb` is ``CI95_WIDTH_EXCEEDS_POLICY``.
    """

    uncertainty = entry.get("uncertainty")
    if uncertainty is None:
        if policy.require_uncertainty:
            buckets["INSUFFICIENT_SUPPORT"].add("UNCERTAINTY_MISSING")
        return
    reason_code, width = _uncertainty_diagnostic(
        uncertainty, tolerance=policy.ci95_width_tolerance_bb
    )
    if reason_code is not None:
        buckets["INSUFFICIENT_SUPPORT"].add(reason_code)
        return
    if width is not None and width > policy.max_ci95_width_bb + _EPS:
        buckets["INSUFFICIENT_SUPPORT"].add("CI95_WIDTH_EXCEEDS_POLICY")


def _paired_ci_includes_zero(value: Any) -> bool:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 2:
        return False
    low = _finite_or_none(value[0])
    high = _finite_or_none(value[1])
    if low is None or high is None or low > high:
        return False
    return low <= 0.0 <= high


def _support_verdict(
    entry: Mapping[str, Any],
    buckets: dict[str, set[str]],
) -> str | None:
    """Fold one ``support`` block into the reason buckets and return its status."""

    support = entry.get("support")
    if support is None:
        buckets["OOD_UNTESTABLE"].add("SUPPORT_MISSING")
        return None
    if not isinstance(support, Mapping):
        buckets["OOD_UNTESTABLE"].add("SUPPORT_INVALID")
        return None

    if support.get("ood") is True:
        buckets["OOD_UNTESTABLE"].add("SUPPORT_OOD")

    declared = support.get("status")
    declared = None if declared is None else str(declared)
    if declared is None:
        buckets["OOD_UNTESTABLE"].add("SUPPORT_STATUS_UNKNOWN")
    elif declared == "OOD_UNTESTABLE":
        buckets["OOD_UNTESTABLE"].add("SUPPORT_STATUS_OOD")
    elif declared not in STATUSES:
        buckets["OOD_UNTESTABLE"].add("SUPPORT_STATUS_UNKNOWN")
    elif declared == "INSUFFICIENT_SUPPORT":
        buckets["INSUFFICIENT_SUPPORT"].add("SUPPORT_STATUS_INSUFFICIENT")
    elif declared == "TOO_CLOSE":
        buckets["TOO_CLOSE"].add("SUPPORT_STATUS_TOO_CLOSE")
    elif declared == "SENSITIVE":
        buckets["SENSITIVE"].add("SUPPORT_STATUS_SENSITIVE")

    tier = support.get("tier")
    if tier is not None and str(tier).strip().upper() in SPARSE_TIERS:
        buckets["INSUFFICIENT_SUPPORT"].add("SPARSE_SUPPORT_TIER")
    return declared


def _rank_key(item: Mapping[str, Any]) -> tuple[float, str]:
    # Only evaluated items are ranked, so ``ev`` is always a finite float here.
    return (-float(item["ev"]), str(item["alternative_id"]))


def classify(hero_entry: Any, policy: Any = None) -> dict[str, Any]:
    """Classify one Hero robustness entry into a single explicit status.

    Parameters
    ----------
    hero_entry:
        The ``hero_entry`` mapping of a ``hero-model-b-robustness-input/v1``
        document (a full document carrying a ``hero_entry`` block is also
        accepted). Every required field must be present; a present-but-null value
        is the schema's "not evaluated" marker.
    policy:
        Optional threshold override (a :class:`RobustnessPolicy` or a mapping with
        the same field names). Defaults to the module constants.

    Returns
    -------
    dict
        Exactly ``{"status": <one of STATUSES>, "reason_codes": [<sorted>]}``.

    Raises
    ------
    RobustnessClassifyError
        When the entry (or an alternative) is not a mapping or is missing a
        required field. The classifier never falls back to a default status.
    """

    effective = _coerce_policy(policy)
    entry = _unwrap_hero_entry(hero_entry)
    _require_fields(entry, REQUIRED_HERO_ENTRY_FIELDS, label="hero_entry")

    buckets: dict[str, set[str]] = {status: set() for status in STATUS_PRECEDENCE}

    _support_verdict(entry, buckets)

    hero_ev = _finite_or_none(entry.get("ev"))
    if entry.get("ev") is None:
        buckets["INSUFFICIENT_SUPPORT"].add("EV_MISSING")
    elif hero_ev is None:
        buckets["INSUFFICIENT_SUPPORT"].add("EV_INVALID")

    # The Hero envelope is verified before any comparison can be declared.
    _check_uncertainty(entry, buckets, effective)

    hero_sizing = _finite_or_none(entry.get("sizing"))

    raw_alternatives = entry.get("alternatives")
    alternatives: list[Mapping[str, Any]] = []
    if raw_alternatives is None:
        buckets["INSUFFICIENT_SUPPORT"].add("NO_COMPARISON_SET")
    elif not isinstance(raw_alternatives, Sequence) or isinstance(raw_alternatives, (str, bytes)):
        raise RobustnessClassifyError(
            f"hero_entry.alternatives must be an array, got {type(raw_alternatives).__name__}",
            reason_code="INVALID_ALTERNATIVES",
        )
    elif len(raw_alternatives) == 0:
        buckets["INSUFFICIENT_SUPPORT"].add("NO_COMPARISON_SET")
    else:
        for index, raw in enumerate(raw_alternatives):
            if not isinstance(raw, Mapping):
                raise RobustnessClassifyError(
                    f"hero_entry.alternatives[{index}] must be a mapping, "
                    f"got {type(raw).__name__}",
                    reason_code="INVALID_ALTERNATIVE",
                )
            _require_fields(raw, REQUIRED_ALTERNATIVE_FIELDS, label=f"alternatives[{index}]")
            alternatives.append(raw)

    evaluated: list[dict[str, Any]] = []
    for index, raw in enumerate(alternatives):
        alternative_id = raw.get("alternative_id")
        alternative_id = (
            str(alternative_id) if alternative_id not in (None, "") else f"alternative[{index}]"
        )
        _support_verdict(raw, buckets)

        # Every alternative of the comparison set is verified as strictly as the
        # Hero entry: a secondary alternative that carries no, a malformed or a
        # too-wide uncertainty envelope forbids CONSISTENT as well.
        _check_uncertainty(raw, buckets, effective)

        raw_ev = raw.get("ev")
        ev = _finite_or_none(raw_ev)
        if raw_ev is None:
            buckets["INSUFFICIENT_SUPPORT"].add("ALTERNATIVE_EV_MISSING")
        elif ev is None:
            buckets["INSUFFICIENT_SUPPORT"].add("ALTERNATIVE_EV_INVALID")

        evaluated.append(
            {
                "alternative_id": alternative_id,
                "sizing": _finite_or_none(raw.get("sizing")),
                "ev": ev,
                "paired_delta": _finite_or_none(raw.get("paired_delta")),
                "paired_delta_ci95": raw.get("paired_delta_ci95"),
            }
        )

    ranked = sorted((item for item in evaluated if item["ev"] is not None), key=_rank_key)

    if alternatives and not ranked:
        buckets["INSUFFICIENT_SUPPORT"].add("NO_EVALUATED_ALTERNATIVE")

    if ranked:
        best = ranked[0]

        for item in ranked:
            delta = item["paired_delta"]
            if delta is not None and abs(delta) <= effective.too_close_delta_bb + _EPS:
                buckets["TOO_CLOSE"].add("PAIRED_DELTA_WITHIN_TOLERANCE")
            if _paired_ci_includes_zero(item.get("paired_delta_ci95")):
                buckets["TOO_CLOSE"].add("PAIRED_CI_INCLUDES_ZERO")

        if hero_ev is not None:
            advantage = hero_ev - best["ev"]
            if advantage <= effective.too_close_delta_bb + _EPS:
                buckets["TOO_CLOSE"].add("ADVANTAGE_WITHIN_TOLERANCE")
                if advantage <= 0.0:
                    buckets["TOO_CLOSE"].add("ALTERNATIVE_MATCHES_OR_EXCEEDS_HERO")
            elif advantage <= effective.sensitive_delta_bb + _EPS:
                buckets["SENSITIVE"].add("ADVANTAGE_WITHIN_SENSITIVITY_BAND")

            for item in ranked:
                item_sizing = item["sizing"]
                if hero_sizing is None or item_sizing is None:
                    continue
                if item_sizing == hero_sizing:
                    continue
                gap = hero_ev - item["ev"]
                if effective.too_close_delta_bb + _EPS < gap <= effective.sensitive_delta_bb + _EPS:
                    buckets["SENSITIVE"].add("SIZING_VARIATION_WITHIN_SENSITIVITY_BAND")

    status = "CONSISTENT"
    for candidate in STATUS_PRECEDENCE:
        if candidate == "CONSISTENT":
            break
        if buckets[candidate]:
            status = candidate
            break
    if status == "CONSISTENT":
        buckets["CONSISTENT"].add("CONSISTENT_WITHIN_POLICY")

    if status not in STATUSES:  # pragma: no cover - defensive invariant
        raise AssertionError(f"classifier produced non-vocabulary status: {status!r}")

    return {"status": status, "reason_codes": _sorted_unique(list(buckets[status]))}


#: Alias kept for callers that prefer the explicit name.
classify_hero_entry = classify

#!/usr/bin/env python3
"""Pure runtime contract/projector for opponent posterior ranges.

The module does not fit Model A and never consumes hidden/future cards.
It accepts an exact-combo distribution, applies declared decision-time PUBLIC
blockers, normalizes it, projects it to the canonical 169 classes, and
validates the serialized runtime contract fail-closed.

Existing posterior producers can pass their combos/weights directly; card
encoding/classification reuses model_b_runtime so the 1326->169 mapping is not
reimplemented here.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Sequence

from tools.simulation.model_b_runtime import ccode, cid, combo_class_ids

SCHEMA = "poker-opponent-posterior-range/v1"
MOMENTS = {"BEFORE_ACTION", "AFTER_ACTION"}
STATUSES = {"AVAILABLE", "UNSUPPORTED", "INVALID"}
PUBLIC_BLOCKER_SCOPE = "PUBLIC"
EPS = 1e-12
DEFAULT_TOLERANCE = 1e-9


class PosteriorRangeError(ValueError):
    pass


class UnsupportedPosteriorRange(PosteriorRangeError):
    pass


def _all_hand_classes() -> tuple[str, ...]:
    return tuple(sorted({combo_class_ids(a, b) for a in range(52) for b in range(a + 1, 52)}))


HAND_CLASSES = _all_hand_classes()
if len(HAND_CLASSES) != 169:
    raise AssertionError(f"expected 169 hand classes, got {len(HAND_CLASSES)}")


def _canonical_combo(value: Sequence[int | str]) -> tuple[int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise PosteriorRangeError("each exact combo must contain exactly two cards")
    ids = []
    for card in value:
        if isinstance(card, bool):
            raise PosteriorRangeError("boolean card ids are invalid")
        card_id = cid(card) if isinstance(card, str) else int(card)
        if not 0 <= card_id < 52:
            raise PosteriorRangeError(f"invalid card id: {card_id}")
        ids.append(card_id)
    if ids[0] == ids[1]:
        raise PosteriorRangeError("an exact combo cannot contain the same card twice")
    return tuple(sorted(ids))


def _canonical_blockers(blockers: Sequence[dict[str, Any]] | None) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    for raw in blockers or []:
        if not isinstance(raw, dict):
            raise PosteriorRangeError("blockers_applied entries must be objects")
        allowed = {"card", "knowledge_scope", "source_step_id"}
        unknown = set(raw) - allowed
        if unknown:
            raise PosteriorRangeError(f"unsupported blocker fields: {sorted(unknown)}")
        if raw.get("knowledge_scope") != PUBLIC_BLOCKER_SCOPE:
            raise PosteriorRangeError(
                "only decision-time PUBLIC blockers are permitted; opponent-private/future cards are forbidden"
            )
        card = raw.get("card")
        if not isinstance(card, str):
            raise PosteriorRangeError("blocker card must be a two-character card code")
        card_id = cid(card)
        if card_id in seen:
            raise PosteriorRangeError(f"duplicate blocker card: {ccode(card_id)}")
        source_step_id = raw.get("source_step_id")
        if not isinstance(source_step_id, (str, int)) or isinstance(source_step_id, bool):
            raise PosteriorRangeError("blocker source_step_id is required")
        seen.add(card_id)
        rows.append(
            {
                "card": ccode(card_id),
                "knowledge_scope": PUBLIC_BLOCKER_SCOPE,
                "source_step_id": source_step_id,
            }
        )
    rows.sort(key=lambda row: cid(row["card"]))
    return tuple(rows)


def full_combo_multiplicity() -> dict[str, int]:
    counts = {hand: 0 for hand in HAND_CLASSES}
    for a in range(52):
        for b in range(a + 1, 52):
            counts[combo_class_ids(a, b)] += 1
    if sum(counts.values()) != 1326:
        raise AssertionError("invalid full combo multiplicity")
    return counts


FULL_COMBO_MULTIPLICITY = full_combo_multiplicity()


def legal_combo_multiplicity(blockers: Sequence[dict[str, Any]] | None = None) -> dict[str, int]:
    canonical = _canonical_blockers(blockers)
    blocked = {cid(row["card"]) for row in canonical}
    counts = {hand: 0 for hand in HAND_CLASSES}
    for a in range(52):
        if a in blocked:
            continue
        for b in range(a + 1, 52):
            if b in blocked:
                continue
            counts[combo_class_ids(a, b)] += 1
    return counts


def _finite_nonnegative(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise PosteriorRangeError(f"{label} must be numeric") from exc
    if not math.isfinite(number) or number < 0:
        raise PosteriorRangeError(f"{label} must be finite and non-negative")
    return number


def _distribution_fingerprint(exact_rows: Sequence[dict[str, Any]]) -> str:
    payload = [{"cards": list(row["cards"]), "weight": float(row["weight"])} for row in exact_rows]
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def project_exact_combo_weights(
    combos: Sequence[Sequence[int | str]],
    weights: Sequence[float],
    blockers_applied: Sequence[dict[str, Any]] | None = None,
    *,
    tolerance: float = DEFAULT_TOLERANCE,
) -> dict[str, Any]:
    """Apply PUBLIC blockers, normalize exact combos, and project to 169."""
    if len(combos) != len(weights):
        raise PosteriorRangeError("combos and weights must have equal length")
    if not combos:
        raise UnsupportedPosteriorRange("posterior contains no exact combos")
    if tolerance <= 0 or not math.isfinite(float(tolerance)):
        raise PosteriorRangeError("tolerance must be finite and positive")

    blockers = _canonical_blockers(blockers_applied)
    blocked_ids = {cid(row["card"]) for row in blockers}
    seen: set[tuple[int, int]] = set()
    retained: list[tuple[tuple[int, int], float]] = []
    input_mass = 0.0
    blocked_mass = 0.0

    for index, (combo_raw, weight_raw) in enumerate(zip(combos, weights)):
        combo = _canonical_combo(combo_raw)
        if combo in seen:
            raise PosteriorRangeError(f"duplicate exact combo: {ccode(combo[0])}{ccode(combo[1])}")
        seen.add(combo)
        weight = _finite_nonnegative(weight_raw, f"weight[{index}]")
        input_mass += weight
        if combo[0] in blocked_ids or combo[1] in blocked_ids:
            blocked_mass += weight
            continue
        retained.append((combo, weight))

    retained_mass = sum(weight for _, weight in retained)
    if retained_mass <= EPS:
        raise UnsupportedPosteriorRange("public blockers/support removed all positive posterior mass")

    normalized = [(combo, weight / retained_mass) for combo, weight in retained]
    normalized.sort(key=lambda item: item[0])
    exact_rows = [
        {"cards": [ccode(combo[0]), ccode(combo[1])], "weight": weight}
        for combo, weight in normalized
        if weight > 0
    ]
    if not exact_rows:
        raise UnsupportedPosteriorRange("posterior has no positive exact-combo support")

    classes = {hand: 0.0 for hand in HAND_CLASSES}
    for combo, weight in normalized:
        if weight > 0:
            classes[combo_class_ids(*combo)] += weight
    output_mass = sum(classes.values())
    if not math.isclose(output_mass, 1.0, rel_tol=0.0, abs_tol=tolerance):
        raise PosteriorRangeError(f"projected probability mass is {output_mass}, expected 1")

    support_weights = [row["weight"] for row in exact_rows]
    effective_support = 1.0 / sum(weight * weight for weight in support_weights)
    entropy_nats = -sum(weight * math.log(weight) for weight in support_weights if weight > 0)

    return {
        "exact_combo_weights": exact_rows,
        "projection_169": {
            "classes": classes,
            "full_combo_multiplicity": dict(FULL_COMBO_MULTIPLICITY),
            "legal_combo_multiplicity": legal_combo_multiplicity(blockers),
        },
        "blockers_applied": [dict(row) for row in blockers],
        "normalization": {
            "input_mass": input_mass,
            "blocked_mass": blocked_mass,
            "retained_mass": retained_mass,
            "output_mass": output_mass,
            "tolerance": float(tolerance),
        },
        "probability_mass": output_mass,
        "support": {
            "exact_combo_support": len(exact_rows),
            "effective_support": effective_support,
            "entropy_nats": entropy_nats,
        },
        "distribution_fingerprint": _distribution_fingerprint(exact_rows),
    }


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_identity(identity: Any, errors: list[str]) -> None:
    required = {"population_id", "model_id", "model_version", "source_id"}
    if not isinstance(identity, dict):
        errors.append("identity must be an object")
        return
    if set(identity) != required:
        errors.append("identity must contain exactly population_id/model_id/model_version/source_id")
    for field in required:
        if not _nonempty(identity.get(field)):
            errors.append(f"identity.{field} is required")


def _validate_public_action(moment: str, action: Any, errors: list[str]) -> None:
    if moment == "BEFORE_ACTION":
        if action is not None:
            errors.append("public_action must be null for BEFORE_ACTION")
        return
    if not isinstance(action, dict):
        errors.append("public_action is required for AFTER_ACTION")
        return
    allowed = {"action", "source_step_id", "sizing"}
    if set(action) - allowed:
        errors.append("public_action contains unsupported fields")
    if not _nonempty(action.get("action")):
        errors.append("public_action.action is required")
    if not isinstance(action.get("source_step_id"), (str, int)) or isinstance(action.get("source_step_id"), bool):
        errors.append("public_action.source_step_id is required")
    sizing = action.get("sizing")
    if sizing is None:
        return
    if not isinstance(sizing, dict):
        errors.append("public_action.sizing must be null or an object")
        return
    allowed_sizing = {"semantic", "observed_size_bb", "target_total_bb", "pot_before_bb", "pot_fraction"}
    if set(sizing) != allowed_sizing:
        errors.append("public_action.sizing fields are incomplete or unsupported")
    if sizing.get("semantic") not in {"INCREMENTAL_COST_BB", "TARGET_TOTAL_BB", "POT_FRACTION", "UNSPECIFIED"}:
        errors.append("public_action.sizing.semantic is invalid")
    for key in allowed_sizing - {"semantic"}:
        if sizing.get(key) is None:
            continue
        try:
            value = float(sizing[key])
        except (TypeError, ValueError):
            errors.append(f"public_action.sizing.{key} must be numeric or null")
            continue
        if not math.isfinite(value) or value < 0:
            errors.append(f"public_action.sizing.{key} must be finite and non-negative")


def _validate_provenance(provenance: Any, errors: list[str]) -> None:
    required = {"producer", "contract_version", "source_artifact", "source_fingerprint"}
    if not isinstance(provenance, dict):
        errors.append("provenance must be an object")
        return
    if set(provenance) != required:
        errors.append("provenance fields are incomplete or unsupported")
    for field in required:
        if not _nonempty(provenance.get(field)):
            errors.append(f"provenance.{field} is required")


def _zero_projection(blockers: Sequence[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "classes": {hand: 0.0 for hand in HAND_CLASSES},
        "full_combo_multiplicity": dict(FULL_COMBO_MULTIPLICITY),
        "legal_combo_multiplicity": legal_combo_multiplicity(blockers),
    }


def build_available_record(
    *,
    hand_id: str,
    step_id: str | int,
    public_state_fingerprint: str,
    player: str,
    position: str,
    identity: dict[str, str],
    moment: str,
    public_action: dict[str, Any] | None,
    combos: Sequence[Sequence[int | str]],
    weights: Sequence[float],
    blockers_applied: Sequence[dict[str, Any]] | None,
    source_observations: int,
    backoff_level: str,
    backoff_reason: str | None,
    provenance: dict[str, str],
    tolerance: float = DEFAULT_TOLERANCE,
) -> dict[str, Any]:
    projected = project_exact_combo_weights(combos, weights, blockers_applied, tolerance=tolerance)
    record = {
        "schema": SCHEMA,
        "status": "AVAILABLE",
        "reason": None,
        "hand_id": hand_id,
        "step_id": step_id,
        "public_state_fingerprint": public_state_fingerprint,
        "player": player,
        "position": position,
        "identity": dict(identity),
        "moment": moment,
        "public_action": public_action,
        "exact_combo_weights": projected["exact_combo_weights"],
        "projection_169": projected["projection_169"],
        "blockers_applied": projected["blockers_applied"],
        "normalization": projected["normalization"],
        "probability_mass": projected["probability_mass"],
        "support": {
            "source_observations": int(source_observations),
            "exact_combo_support": projected["support"]["exact_combo_support"],
            "effective_support": projected["support"]["effective_support"],
            "entropy_nats": projected["support"]["entropy_nats"],
            "backoff": {"level": backoff_level, "reason": backoff_reason},
        },
        "distribution_fingerprint": projected["distribution_fingerprint"],
        "provenance": dict(provenance),
    }
    errors = validate_posterior_range(record, tolerance=tolerance)
    if errors:
        raise PosteriorRangeError("; ".join(errors))
    return record


def build_fail_closed_record(
    *,
    status: str,
    reason: str,
    hand_id: str,
    step_id: str | int,
    public_state_fingerprint: str,
    player: str,
    position: str,
    identity: dict[str, str],
    moment: str,
    public_action: dict[str, Any] | None,
    blockers_applied: Sequence[dict[str, Any]] | None,
    source_observations: int,
    backoff_level: str,
    backoff_reason: str | None,
    provenance: dict[str, str],
) -> dict[str, Any]:
    if status not in {"UNSUPPORTED", "INVALID"}:
        raise PosteriorRangeError("fail-closed status must be UNSUPPORTED or INVALID")
    blockers = _canonical_blockers(blockers_applied)
    record = {
        "schema": SCHEMA,
        "status": status,
        "reason": reason,
        "hand_id": hand_id,
        "step_id": step_id,
        "public_state_fingerprint": public_state_fingerprint,
        "player": player,
        "position": position,
        "identity": dict(identity),
        "moment": moment,
        "public_action": public_action,
        "exact_combo_weights": [],
        "projection_169": _zero_projection(blockers),
        "blockers_applied": [dict(row) for row in blockers],
        "normalization": {
            "input_mass": 0.0,
            "blocked_mass": 0.0,
            "retained_mass": 0.0,
            "output_mass": 0.0,
            "tolerance": DEFAULT_TOLERANCE,
        },
        "probability_mass": 0.0,
        "support": {
            "source_observations": int(source_observations),
            "exact_combo_support": 0,
            "effective_support": 0.0,
            "entropy_nats": 0.0,
            "backoff": {"level": backoff_level, "reason": backoff_reason},
        },
        "distribution_fingerprint": None,
        "provenance": dict(provenance),
    }
    errors = validate_posterior_range(record)
    if errors:
        raise PosteriorRangeError("; ".join(errors))
    return record


def record_from_combo_posterior(posterior: Any, **metadata: Any) -> dict[str, Any]:
    combos = getattr(posterior, "combos", None)
    weights = getattr(posterior, "weights", None)
    if combos is None or weights is None:
        raise PosteriorRangeError("posterior adapter requires combos and weights")
    return build_available_record(combos=combos, weights=weights, **metadata)


def validate_posterior_range(record: Any, *, tolerance: float = DEFAULT_TOLERANCE) -> list[str]:
    errors: list[str] = []
    if not isinstance(record, dict):
        return ["record must be an object"]

    allowed_top = {
        "schema", "status", "reason", "hand_id", "step_id", "public_state_fingerprint",
        "player", "position", "identity", "moment", "public_action",
        "exact_combo_weights", "projection_169", "blockers_applied", "normalization",
        "probability_mass", "support", "distribution_fingerprint", "provenance",
    }
    unknown_top = set(record) - allowed_top
    if unknown_top:
        errors.append(f"unsupported top-level fields: {sorted(unknown_top)}")
    if record.get("schema") != SCHEMA:
        errors.append(f"schema must be {SCHEMA}")

    status = record.get("status")
    if status not in STATUSES:
        errors.append("status must be AVAILABLE, UNSUPPORTED or INVALID")
    moment = record.get("moment")
    if moment not in MOMENTS:
        errors.append("moment must be BEFORE_ACTION or AFTER_ACTION")
    for field in ("hand_id", "public_state_fingerprint", "player", "position"):
        if not _nonempty(record.get(field)):
            errors.append(f"{field} is required")
    if not isinstance(record.get("step_id"), (str, int)) or isinstance(record.get("step_id"), bool):
        errors.append("step_id is required")
    _validate_identity(record.get("identity"), errors)
    if moment in MOMENTS:
        _validate_public_action(moment, record.get("public_action"), errors)
    _validate_provenance(record.get("provenance"), errors)

    try:
        blockers = _canonical_blockers(record.get("blockers_applied"))
    except PosteriorRangeError as exc:
        blockers = ()
        errors.append(str(exc))

    support = record.get("support")
    if not isinstance(support, dict):
        errors.append("support must be an object")
        support = {}
    else:
        expected_support = {
            "source_observations", "exact_combo_support", "effective_support",
            "entropy_nats", "backoff",
        }
        if set(support) != expected_support:
            errors.append("support fields are incomplete or unsupported")
        for key in ("source_observations", "exact_combo_support"):
            value = support.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                errors.append(f"support.{key} must be a non-negative integer")
        for key in ("effective_support", "entropy_nats"):
            try:
                value = float(support.get(key))
            except (TypeError, ValueError):
                errors.append(f"support.{key} must be finite and non-negative")
                continue
            if not math.isfinite(value) or value < 0:
                errors.append(f"support.{key} must be finite and non-negative")
        backoff = support.get("backoff")
        if not isinstance(backoff, dict) or set(backoff) != {"level", "reason"}:
            errors.append("support.backoff must contain exactly level/reason")
        else:
            if not _nonempty(backoff.get("level")):
                errors.append("support.backoff.level is required")
            if backoff.get("reason") is not None and not isinstance(backoff.get("reason"), str):
                errors.append("support.backoff.reason must be null or string")

    normalization = record.get("normalization")
    expected_norm = {"input_mass", "blocked_mass", "retained_mass", "output_mass", "tolerance"}
    if not isinstance(normalization, dict):
        errors.append("normalization must be an object")
        normalization = {}
    elif set(normalization) != expected_norm:
        errors.append("normalization fields are incomplete or unsupported")
    else:
        for key in ("input_mass", "blocked_mass", "retained_mass", "output_mass"):
            try:
                value = float(normalization[key])
            except (TypeError, ValueError):
                errors.append(f"normalization.{key} must be numeric")
                continue
            if not math.isfinite(value) or value < 0:
                errors.append(f"normalization.{key} must be finite and non-negative")
        try:
            norm_tolerance = float(normalization["tolerance"])
        except (TypeError, ValueError):
            errors.append("normalization.tolerance must be numeric")
        else:
            if not math.isfinite(norm_tolerance) or norm_tolerance <= 0:
                errors.append("normalization.tolerance must be finite and positive")
        try:
            if not math.isclose(
                float(normalization["input_mass"]),
                float(normalization["blocked_mass"]) + float(normalization["retained_mass"]),
                rel_tol=0.0,
                abs_tol=max(tolerance, 1e-12),
            ):
                errors.append("normalization input_mass must equal blocked_mass + retained_mass")
        except (TypeError, ValueError):
            pass

    exact_rows = record.get("exact_combo_weights")
    projection = record.get("projection_169")
    classes = projection.get("classes") if isinstance(projection, dict) else None
    full_mult = projection.get("full_combo_multiplicity") if isinstance(projection, dict) else None
    legal_mult = projection.get("legal_combo_multiplicity") if isinstance(projection, dict) else None
    if not isinstance(exact_rows, list):
        errors.append("exact_combo_weights must be a list")
        exact_rows = []
    else:
        for index, row in enumerate(exact_rows):
            if not isinstance(row, dict) or set(row) != {"cards", "weight"}:
                errors.append(f"exact_combo_weights[{index}] must contain exactly cards/weight")
    if not isinstance(projection, dict):
        errors.append("projection_169 must be an object")
    if not isinstance(classes, dict) or set(classes) != set(HAND_CLASSES):
        errors.append("projection_169.classes must contain exactly the canonical 169 classes")
        classes = {}
    if full_mult != FULL_COMBO_MULTIPLICITY:
        errors.append("projection_169.full_combo_multiplicity must match canonical 1326 multiplicity")
    try:
        expected_legal = legal_combo_multiplicity(blockers)
    except PosteriorRangeError as exc:
        expected_legal = None
        errors.append(str(exc))
    if expected_legal is not None and legal_mult != expected_legal:
        errors.append("projection_169.legal_combo_multiplicity does not match applied blockers")

    reason = record.get("reason")
    if status == "AVAILABLE":
        if reason is not None:
            errors.append("AVAILABLE reason must be null")
        if not exact_rows:
            errors.append("AVAILABLE requires positive exact-combo support")
        try:
            recomputed = project_exact_combo_weights(
                [row["cards"] for row in exact_rows],
                [row["weight"] for row in exact_rows],
                blockers,
                tolerance=tolerance,
            )
        except (KeyError, TypeError, PosteriorRangeError) as exc:
            recomputed = None
            errors.append(f"exact combo distribution invalid: {exc}")
        if recomputed is not None:
            for hand in HAND_CLASSES:
                try:
                    actual = float(classes.get(hand))
                except (TypeError, ValueError):
                    errors.append(f"projection_169.classes.{hand} must be numeric")
                    continue
                if not math.isfinite(actual) or actual < 0:
                    errors.append(f"projection_169.classes.{hand} must be finite and non-negative")
                elif not math.isclose(
                    actual, recomputed["projection_169"]["classes"][hand],
                    rel_tol=0.0, abs_tol=tolerance
                ):
                    errors.append(f"projection mismatch for {hand}")
            try:
                probability_mass = float(record.get("probability_mass"))
            except (TypeError, ValueError):
                probability_mass = math.nan
            if not math.isclose(probability_mass, 1.0, rel_tol=0.0, abs_tol=tolerance):
                errors.append("AVAILABLE probability_mass must equal 1")
            if normalization:
                try:
                    output_mass = float(normalization.get("output_mass"))
                except (TypeError, ValueError):
                    output_mass = math.nan
                if not math.isclose(output_mass, 1.0, rel_tol=0.0, abs_tol=tolerance):
                    errors.append("AVAILABLE normalization.output_mass must equal 1")
            if support.get("exact_combo_support") != recomputed["support"]["exact_combo_support"]:
                errors.append("support.exact_combo_support mismatch")
            for key in ("effective_support", "entropy_nats"):
                try:
                    actual = float(support.get(key))
                except (TypeError, ValueError):
                    continue
                if not math.isclose(
                    actual, recomputed["support"][key],
                    rel_tol=0.0, abs_tol=max(tolerance, 1e-12)
                ):
                    errors.append(f"support.{key} mismatch")
            if record.get("distribution_fingerprint") != recomputed["distribution_fingerprint"]:
                errors.append("distribution_fingerprint mismatch")
    elif status in {"UNSUPPORTED", "INVALID"}:
        if not _nonempty(reason):
            errors.append(f"{status} requires a non-empty reason")
        if exact_rows:
            errors.append(f"{status} must not expose exact combo weights")
        if classes:
            for hand, value in classes.items():
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    errors.append(f"projection_169.classes.{hand} must be numeric")
                    break
                if not math.isclose(number, 0.0, rel_tol=0.0, abs_tol=tolerance):
                    errors.append(f"{status} projection must have zero mass")
                    break
        try:
            probability_mass = float(record.get("probability_mass"))
        except (TypeError, ValueError):
            probability_mass = math.nan
        if not math.isclose(probability_mass, 0.0, rel_tol=0.0, abs_tol=tolerance):
            errors.append(f"{status} probability_mass must equal 0")
        if record.get("distribution_fingerprint") is not None:
            errors.append(f"{status} distribution_fingerprint must be null")
        if support.get("exact_combo_support") not in {0, None}:
            errors.append(f"{status} support.exact_combo_support must be 0")
        for key in ("effective_support", "entropy_nats"):
            try:
                number = float(support.get(key))
            except (TypeError, ValueError):
                continue
            if not math.isclose(number, 0.0, rel_tol=0.0, abs_tol=tolerance):
                errors.append(f"{status} support.{key} must be 0")
        if normalization:
            for key in ("input_mass", "blocked_mass", "retained_mass", "output_mass"):
                try:
                    number = float(normalization.get(key))
                except (TypeError, ValueError):
                    continue
                if not math.isclose(number, 0.0, rel_tol=0.0, abs_tol=tolerance):
                    errors.append(f"{status} normalization.{key} must be 0")

    return errors


__all__ = [
    "SCHEMA", "HAND_CLASSES", "FULL_COMBO_MULTIPLICITY",
    "PosteriorRangeError", "UnsupportedPosteriorRange",
    "legal_combo_multiplicity", "project_exact_combo_weights",
    "build_available_record", "build_fail_closed_record",
    "record_from_combo_posterior", "validate_posterior_range",
]

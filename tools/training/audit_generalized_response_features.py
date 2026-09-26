#!/usr/bin/env python3
"""#421 - TRAIN-only fragmentation audit / representation justification.

The generalized public-only adverse-response dataset (#421) carries twelve
candidate dimensions: ``family``, ``actor_position``, ``aggressor_position``,
``limper_count``, ``caller_count``, ``live_positions``, ``table_size``,
``raise_level``, ``to_call_bb``, ``pot_odds``, ``pot_before_bb`` and
``effective_stack_bb``.  Before that representation is frozen for modelling, the
question this audit answers, dimension by dimension, is:

    should the dimension be *kept*, *aggregated* or *removed*?

Method (deterministic and TRAIN-only):

* only certified TRAIN hands cross the parser boundary
  (``audit_hero_preflop_coverage.load_train_records``) and the row projection is
  reused verbatim from ``build_generalized_response_dataset``, so the audited
  rows are the persisted dataset rows; VALIDATION and TEST decisions are never
  read and TEST is refused fail-closed by the reused loader/projector;
* TRAIN hands are split by hand id into a FIT fold and a HOLDOUT fold
  (``stable_hash(hand_id) % holdout_modulus``); one hand lives in a single fold,
  so the measured gain of a dimension cannot leak across the split;
* **predictive gain** = reduction of the held-out log loss (bits per decision)
  against the FIT global action distribution, with a documented m-estimate
  backoff (``smoothing_mass``) and a minimum cell support (``min_support_rows``);
  cells below that support fall back to the global distribution;
* **fragmentation** = observed level cardinality, effective cardinality
  (perplexity ``2**H``), share of levels/rows below the support thresholds, and
  the measured growth of the joint representation when the dimension is crossed
  with the previously retained dimensions;
* **verdict**:
  - ``KEEP`` - a real held-out gain and raw levels that are already supported;
  - ``AGGREGATE`` - a real held-out gain but fragmented raw levels: the smallest
    documented coarsening that retains the measured gain is proposed;
  - ``REMOVE`` - no measurable gain: the dimension only pays fragmentation cost.

The audit is descriptive: it fits no model, selects nothing, promotes nothing and
touches no runtime surface.  It writes
``analysis/issue421_generalized_response/GENERALIZED_RESPONSE_DATASET_REPORT.json``.
"""
from __future__ import annotations

import argparse
import collections
import dataclasses
import json
import math
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.datasets.build_hand_history_increment import fingerprint, sha256_file  # noqa: E402
from tools.training.audit_hero_preflop_coverage import (  # noqa: E402
    DEFAULT_CERTIFICATION,
    load_train_records,
    support_tier,
)
from tools.training.audit_preflop_sizing_support import bin_for, empirical_bins  # noqa: E402
from tools.training.build_generalized_response_dataset import (  # noqa: E402
    FORBIDDEN_SPLITS,
    ROW_FIELDS,
    SPLITS,
    iter_response_rows,
    stable_hash,
)

SCHEMA = "poker-generalized-response-dataset-report/v1"
POPULATION_ID = "pokerstars_nlhe_100-200_zoom_play_6max_v1"

OUTPUT_DIR = ROOT / "analysis/issue421_generalized_response"
DEFAULT_OUTPUT = OUTPUT_DIR / "GENERALIZED_RESPONSE_DATASET_REPORT.json"
DATASET_MANIFEST = OUTPUT_DIR / "dataset/GENERALIZED_RESPONSE_DATASET.json"
DATASET_PAYLOAD = OUTPUT_DIR / "dataset/GENERALIZED_RESPONSE_DATASET.jsonl"

#: Total order of the observed response space; every probability vector is
#: aligned on it so log-loss sums are independent of the input row order.
ACTIONS = ("FOLD", "CALL", "RAISE", "JAM")
ACTION_INDEX = {action: index for index, action in enumerate(ACTIONS)}

#: Support contract, aligned with the repository-wide ``support_tier`` scale
#: (SPARSE < 20 <= LOW < 50 <= MEDIUM < 250 <= HIGH < 1000 <= VERY_HIGH).
MIN_SUPPORT_ROWS = 20
STRONG_SUPPORT_ROWS = 50
VERY_STRONG_SUPPORT_ROWS = 250

#: Verdict thresholds.
REMOVE_GAIN_THRESHOLD_BITS = 0.002
REMOVE_GAIN_THRESHOLD_RELATIVE = 0.0025
AGGREGATE_GAIN_RETENTION = 0.8
AGGREGATE_LOW_SUPPORT_SHARE = 0.05
#: A raw level set with more levels than this cannot be supported at all, even
#: when every individual level happens to clear the support floor.
UNUSABLE_RAW_LEVELS = 64

#: Aggregation candidates.
NUMERIC_BIN_CANDIDATES = (2, 3, 4, 5, 6, 8, 10, 12, 16)
MERGE_CANDIDATES = (
    ("MERGE_BELOW_MIN_SUPPORT", MIN_SUPPORT_ROWS, None),
    ("MERGE_BELOW_STRONG_SUPPORT", STRONG_SUPPORT_ROWS, None),
    ("TOP_8_LEVELS", None, 8),
    ("TOP_4_LEVELS", None, 4),
)

#: m-estimate smoothing mass (pseudo-observations) toward the FIT prior.
SMOOTHING_MASS = 10.0

#: One TRAIN hand out of ``HOLDOUT_MODULUS`` goes to the held-out fold.
HOLDOUT_MODULUS = 5

#: Listing caps: the report stays reviewable while the counts stay exhaustive.
LIST_CAP_LEVELS = 40
LIST_CAP_SUPPORTED_CELLS = 100
LIST_CAP_LOW_SUPPORT_CELLS = 200


def _round(value: Any, digits: int = 6) -> float | None:
    """Deterministic float formatting used by every emitted number."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    rounded = round(number, digits)
    return 0.0 if rounded == 0 else rounded


def _number_label(value: Any) -> str:
    rounded = _round(value)
    return "MISSING" if rounded is None else repr(rounded)


def _format_gain(value: float | None) -> str:
    return "n/a" if value is None else format(value, "+.6f")


def _effective_remove_threshold(baseline_log_loss: float | None) -> float:
    """Absolute floor and relative floor (share of the global baseline)."""
    relative = (
        REMOVE_GAIN_THRESHOLD_RELATIVE * float(baseline_log_loss)
        if baseline_log_loss
        else 0.0
    )
    return _round(max(REMOVE_GAIN_THRESHOLD_BITS, relative)) or REMOVE_GAIN_THRESHOLD_BITS


def _get_family(row: Mapping[str, Any]) -> str:
    return str(row.get("family") or "")


def _get_actor_position(row: Mapping[str, Any]) -> str:
    return str(row.get("actor_position") or "")


def _get_aggressor_position(row: Mapping[str, Any]) -> str | None:
    value = row.get("aggressor_position")
    return None if value in (None, "") else str(value)


def _get_limper_count(row: Mapping[str, Any]) -> int:
    return int(row.get("limper_count") or 0)


def _get_caller_count(row: Mapping[str, Any]) -> int:
    return int(row.get("caller_count") or 0)


def _get_live_positions(row: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(str(position) for position in (row.get("live_positions") or []))


def _get_table_size(row: Mapping[str, Any]) -> int:
    return int(row.get("table_size") or 0)


def _get_raise_level(row: Mapping[str, Any]) -> int:
    return int(row.get("raise_level") or 0)


def _get_to_call_bb(row: Mapping[str, Any]) -> float | None:
    return _round(row.get("to_call_bb"))


def _get_pot_odds(row: Mapping[str, Any]) -> float | None:
    return _round(row.get("pot_odds"))


def _get_pot_before_bb(row: Mapping[str, Any]) -> float | None:
    return _round(row.get("pot_before_bb"))


def _get_effective_stack_bb(row: Mapping[str, Any]) -> float | None:
    return _round(row.get("effective_stack_bb"))


@dataclasses.dataclass(frozen=True)
class Dimension:
    """One auditable dimension of the response representation."""

    name: str
    axis: str
    kind: str  # CATEGORICAL | INTEGER | NUMERIC
    get: Callable[[Mapping[str, Any]], Any]
    description: str


#: Canonical audit order; the order also drives the incremental
#: "cells induced by this dimension" measurement.
DIMENSIONS: tuple[Dimension, ...] = (
    Dimension(
        name="family",
        axis="FAMILY",
        kind="CATEGORICAL",
        get=_get_family,
        description="public preflop family immediately before the response",
    ),
    Dimension(
        name="actor_position",
        axis="POSITION",
        kind="CATEGORICAL",
        get=_get_actor_position,
        description="position of the adverse actor facing the response",
    ),
    Dimension(
        name="aggressor_position",
        axis="POSITION",
        kind="CATEGORICAL",
        get=_get_aggressor_position,
        description="position of the last raiser/jammer, NONE when the pot is unraised",
    ),
    Dimension(
        name="limper_count",
        axis="POSITION",
        kind="INTEGER",
        get=_get_limper_count,
        description="number of limpers before the first raise",
    ),
    Dimension(
        name="caller_count",
        axis="POSITION",
        kind="INTEGER",
        get=_get_caller_count,
        description="number of callers after the first raise",
    ),
    Dimension(
        name="live_positions",
        axis="POSITION",
        kind="CATEGORICAL",
        get=_get_live_positions,
        description="exact set of live positions before the action",
    ),
    Dimension(
        name="table_size",
        axis="POSITION",
        kind="INTEGER",
        get=_get_table_size,
        description="number of seated players",
    ),
    Dimension(
        name="raise_level",
        axis="SIZING",
        kind="INTEGER",
        get=_get_raise_level,
        description="number of raises already in the hand (0 = unraised)",
    ),
    Dimension(
        name="to_call_bb",
        axis="SIZING",
        kind="NUMERIC",
        get=_get_to_call_bb,
        description="price to call in big blinds",
    ),
    Dimension(
        name="pot_odds",
        axis="SIZING",
        kind="NUMERIC",
        get=_get_pot_odds,
        description="to_call / (pot + to_call); price_to_pot is a monotone transform",
    ),
    Dimension(
        name="pot_before_bb",
        axis="SIZING",
        kind="NUMERIC",
        get=_get_pot_before_bb,
        description="pot before the action in big blinds",
    ),
    Dimension(
        name="effective_stack_bb",
        axis="STACK",
        kind="NUMERIC",
        get=_get_effective_stack_bb,
        description="effective stack in big blinds before the action",
    ),
)

DIMENSION_ORDER = tuple(dimension.name for dimension in DIMENSIONS)
DIMENSIONS_BY_NAME = {dimension.name: dimension for dimension in DIMENSIONS}

#: Public dimensions tracked as descriptive only: they are the *observed* sizing
#: outcome of RAISE/JAM rows, so they are consequences of the label and must
#: never be used to predict it.
OUTCOME_DIMENSIONS = ("target_total_bb", "observed_sizing_bb")


def dimension_by_name(report: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    """Lookup helper used by the guard suite and reviewers."""
    for dimension in report.get("dimensions") or []:
        if dimension.get("name") == name:
            return dimension
    raise KeyError(f"dimension {name!r} is absent from the report")


def assert_train_row(row: Mapping[str, Any]) -> None:
    """Fail closed on anything that is not a TRAIN response row of the dataset."""
    if not isinstance(row, Mapping):
        raise AssertionError("response row must be a mapping")
    missing = sorted(set(ROW_FIELDS) - set(row))
    if missing:
        raise AssertionError(f"response row is missing dataset fields: {missing}")
    split = str(row.get("split") or "").upper()
    if split in FORBIDDEN_SPLITS:
        raise AssertionError(f"{split} decision rows are forbidden: TRAIN-only audit")
    if split != "TRAIN":
        raise AssertionError(f"non-TRAIN decision row supplied: split={split!r}")
    if str(row.get("action") or "") not in ACTIONS:
        raise AssertionError(f"action outside {ACTIONS}: {row.get('action')!r}")


def _raw_label(dimension: Dimension, value: Any) -> str:
    if value is None:
        return "NONE"
    if dimension.kind == "NUMERIC":
        return _number_label(value)
    if dimension.kind == "INTEGER":
        return str(int(value))
    if isinstance(value, tuple):
        return "|".join(value)
    return str(value)


def _raw_labels_for(name: str, rows: Sequence[Mapping[str, Any]]) -> list[str]:
    dimension = DIMENSIONS_BY_NAME[name]
    return [_raw_label(dimension, dimension.get(row)) for row in rows]


def _m_estimate(
    counts: Mapping[str, int],
    total: int,
    prior: Sequence[float],
    smoothing_mass: float = SMOOTHING_MASS,
) -> tuple[float, ...]:
    """m-estimate action distribution: counts smoothed toward the FIT prior."""
    denominator = total + smoothing_mass
    return tuple(
        (counts.get(action, 0) + smoothing_mass * prior[index]) / denominator
        for index, action in enumerate(ACTIONS)
    )


def _global_prior(rows: Sequence[Mapping[str, Any]], indices: Sequence[int]) -> tuple[float, ...]:
    counts: collections.Counter[str] = collections.Counter(rows[index]["action"] for index in indices)
    total = sum(counts.values())
    if not total:
        return tuple(1.0 / len(ACTIONS) for _ in ACTIONS)
    return tuple(counts.get(action, 0) / total for action in ACTIONS)


def _log_loss_bits(
    labels: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
    fit_indices: Sequence[int],
    holdout_indices: Sequence[int],
    prior: Sequence[float],
    *,
    min_support: int = MIN_SUPPORT_ROWS,
    smoothing_mass: float = SMOOTHING_MASS,
) -> float | None:
    """Held-out log loss of ``action | level`` with a documented backoff.

    The sum runs over sorted cells and, inside a cell, over the fixed ACTIONS
    order, so the value is independent of the input row order.
    """
    if not holdout_indices:
        return None
    cell_counts: dict[str, collections.Counter[str]] = {}
    cell_totals: collections.Counter[str] = collections.Counter()
    global_counts: collections.Counter[str] = collections.Counter()
    for index in fit_indices:
        action = str(rows[index]["action"])
        cell = labels[index]
        cell_counts.setdefault(cell, collections.Counter())[action] += 1
        cell_totals[cell] += 1
        global_counts[action] += 1
    global_probabilities = _m_estimate(
        global_counts, sum(global_counts.values()), prior, smoothing_mass
    )
    cell_probabilities = {
        cell: _m_estimate(cell_counts[cell], cell_totals[cell], prior, smoothing_mass)
        for cell in cell_counts
        if cell_totals[cell] >= min_support
    }
    holdout_counts: dict[str, collections.Counter[str]] = {}
    for index in holdout_indices:
        holdout_counts.setdefault(labels[index], collections.Counter())[
            str(rows[index]["action"])
        ] += 1
    total_bits = 0.0
    for cell in sorted(holdout_counts):
        probabilities = cell_probabilities.get(cell, global_probabilities)
        for action in ACTIONS:
            observations = holdout_counts[cell].get(action, 0)
            if observations:
                total_bits += observations * (-math.log2(probabilities[ACTION_INDEX[action]]))
    return _round(total_bits / len(holdout_indices))


def _shannon(counts: Mapping[Any, int], total: int) -> float:
    entropy = 0.0
    for key in sorted(counts, key=str):
        probability = counts[key] / total
        if probability > 0:
            entropy -= probability * math.log2(probability)
    return entropy


def _mutual_information_bits(labels: Sequence[str], actions: Sequence[str]) -> dict[str, Any]:
    """I(action; level) on the full TRAIN fold, plus its normalisation."""
    total = len(actions)
    joint: collections.Counter[tuple[str, str]] = collections.Counter(zip(labels, actions))
    level_counts: collections.Counter[str] = collections.Counter(labels)
    action_counts: collections.Counter[str] = collections.Counter(actions)
    mutual_information = 0.0
    for (level, action), count in sorted(joint.items()):
        p_joint = count / total
        p_level = level_counts[level] / total
        p_action = action_counts[action] / total
        mutual_information += p_joint * math.log2(p_joint / (p_level * p_action))
    entropy_action = _shannon(action_counts, total)
    return {
        "entropy_action_bits": _round(entropy_action),
        "mutual_information_bits": _round(mutual_information),
        "normalized_mutual_information": _round(
            mutual_information / entropy_action if entropy_action else 0.0
        ),
    }


def _fragmentation(labels: Sequence[str], hand_ids: Sequence[str]) -> dict[str, Any]:
    """Cardinality and support profile of one level mapping."""
    total = len(labels)
    counts: collections.Counter[str] = collections.Counter(labels)
    hands_by_level: dict[str, set[str]] = {}
    for level, hand_id in zip(labels, hand_ids):
        hands_by_level.setdefault(level, set()).add(hand_id)
    entropy_levels = _shannon(counts, total) if total else 0.0
    below_min = sorted(
        (level for level, count in counts.items() if count < MIN_SUPPORT_ROWS),
        key=lambda level: (-counts[level], level),
    )
    below_strong = [level for level, count in counts.items() if count < STRONG_SUPPORT_ROWS]
    rows_below_min = sum(counts[level] for level in below_min)
    hands_below_min: set[str] = set()
    for level in below_min:
        hands_below_min |= hands_by_level[level]
    rows_in_supported = total - rows_below_min
    return {
        "distinct_levels": len(counts),
        "effective_levels": _round(2.0 ** entropy_levels),
        "level_entropy_bits": _round(entropy_levels),
        "top_level_share": _round(max(counts.values()) / total) if total else None,
        "levels_below_min_support": len(below_min),
        "level_share_below_min_support": _round(len(below_min) / len(counts)) if counts else None,
        "rows_in_levels_below_min_support": rows_below_min,
        "rows_share_in_levels_below_min_support": _round(rows_below_min / total) if total else None,
        "rows_in_supported_levels": rows_in_supported,
        "rows_share_in_supported_levels": _round(rows_in_supported / total) if total else None,
        "distinct_hands_in_levels_below_min_support": len(hands_below_min),
        "levels_below_strong_support": len(below_strong),
        "low_support_levels": below_min[:LIST_CAP_LEVELS],
        "low_support_levels_truncated": len(below_min) > LIST_CAP_LEVELS,
    }


def _level_table(labels: Sequence[str], hand_ids: Sequence[str]) -> dict[str, Any]:
    """Distribution of the levels, capped for reviewability."""
    counts: collections.Counter[str] = collections.Counter(labels)
    hands_by_level: dict[str, set[str]] = {}
    for level, hand_id in zip(labels, hand_ids):
        hands_by_level.setdefault(level, set()).add(hand_id)
    total = len(labels)
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    entries = [
        {
            "value": level,
            "observations": count,
            "share": _round(count / total) if total else None,
            "distinct_hands": len(hands_by_level.get(level, ())),
            "support_tier": support_tier(count),
        }
        for level, count in ordered[:LIST_CAP_LEVELS]
    ]
    return {
        "levels_total": len(counts),
        "levels_truncated": len(ordered) > LIST_CAP_LEVELS,
        "entries": entries,
    }


def _merge_candidates(fit_labels: Sequence[str]) -> list[dict[str, Any]]:
    """Coarsening candidates that merge rare levels into ``OTHER``."""
    counts: collections.Counter[str] = collections.Counter(fit_labels)
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for candidate_id, min_support, keep_top in MERGE_CANDIDATES:
        if min_support is not None:
            retained = [level for level, count in ordered if count >= min_support]
        else:
            retained = [level for level, _ in ordered[: int(keep_top or 0)]]
        if not retained or len(retained) >= len(ordered):
            continue
        # Merging n rare levels into one OTHER level must strictly reduce the
        # cardinality, otherwise the candidate is not a coarsening at all.
        if len(retained) + 1 >= len(ordered):
            continue
        key = tuple(sorted(retained))
        if key in seen:
            continue
        seen.add(key)
        retained_sorted = sorted(retained, key=lambda level: (-counts[level], level))
        candidates.append(
            {
                "candidate_id": candidate_id,
                "strategy": "MERGE_RARE_LEVELS_INTO_OTHER",
                "detail": {
                    "retained_levels": retained_sorted[:LIST_CAP_LEVELS],
                    "retained_levels_truncated": len(retained_sorted) > LIST_CAP_LEVELS,
                    "merged_level_count": len(ordered) - len(retained),
                    "resulting_levels": len(retained) + 1,
                    "min_support_rows": min_support,
                    "keep_top_levels": keep_top,
                },
                "retained": frozenset(retained),
            }
        )
    return candidates


def _candidate_levels(
    dimension: Dimension,
    rows: Sequence[Mapping[str, Any]],
    fit_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Raw level mapping plus every documented aggregation candidate."""
    raw_labels = [_raw_label(dimension, dimension.get(row)) for row in rows]
    fit_raw_labels = [_raw_label(dimension, dimension.get(row)) for row in fit_rows]
    candidates: list[dict[str, Any]] = [
        {
            "candidate_id": "RAW",
            "strategy": "RAW_OBSERVED_LEVELS",
            "detail": {"levels_total": len(set(raw_labels)), "base": "RAW"},
            "labels": raw_labels,
        }
    ]

    def add_merge_variants(
        base_id: str,
        base_labels: Sequence[str],
        fit_base_labels: Sequence[str],
        detail: Mapping[str, Any],
    ) -> None:
        for candidate in _merge_candidates(fit_base_labels):
            retained = candidate["retained"]
            candidates.append(
                {
                    "candidate_id": base_id + "__" + candidate["candidate_id"],
                    "strategy": candidate["strategy"],
                    "detail": {**detail, **candidate["detail"]},
                    "labels": [label if label in retained else "OTHER" for label in base_labels],
                }
            )

    if dimension.kind == "NUMERIC":
        fit_values = [dimension.get(row) for row in fit_rows]
        for bin_count in NUMERIC_BIN_CANDIDATES:
            bins = empirical_bins(fit_values, max_bins=bin_count)
            if not bins:
                continue
            candidates.append(
                {
                    "candidate_id": "EMPIRICAL_BINS_" + str(len(bins)),
                    "strategy": "EQUAL_MASS_EMPIRICAL_BINS",
                    "detail": {
                        "base": "RAW",
                        "requested_bins": bin_count,
                        "bins_total": len(bins),
                        "bins_fitted_on": "TRAIN_FIT_SPLIT",
                        "bins": bins,
                    },
                    "labels": [bin_for(dimension.get(row), bins) for row in rows],
                }
            )
        add_merge_variants(
            "RAW", raw_labels, fit_raw_labels, {"base": "RAW", "levels_total": len(set(raw_labels))}
        )
        return candidates

    add_merge_variants(
        "RAW", raw_labels, fit_raw_labels, {"base": "RAW", "levels_total": len(set(raw_labels))}
    )
    if dimension.name == "live_positions":
        count_labels = ["LIVE_" + str(len(dimension.get(row) or ())) for row in rows]
        fit_count_labels = ["LIVE_" + str(len(dimension.get(row) or ())) for row in fit_rows]
        detail = {
            "base": "LIVE_PLAYER_COUNT",
            "note": "coarsens the exact live-position set to the number of live players",
        }
        candidates.append(
            {
                "candidate_id": "LIVE_PLAYER_COUNT",
                "strategy": "COUNT_LIVE_PLAYERS",
                "detail": detail,
                "labels": count_labels,
            }
        )
        add_merge_variants("LIVE_PLAYER_COUNT", count_labels, fit_count_labels, detail)
    return candidates


def _select_aggregation(
    candidates: Sequence[dict[str, Any]],
    raw_distinct_levels: int,
    raw_gain_bits: float,
) -> tuple[dict[str, Any] | None, bool]:
    """Smallest real coarsening that retains the measured gain.

    A candidate only counts when it strictly reduces the level cardinality, so a
    trivial rename or a merge of a single rare level can never be presented as an
    aggregation.  ``retains`` is ``False`` when the raw gain is non-positive: in
    that case the "retention" language is meaningless.
    """
    alternatives = [
        candidate
        for candidate in candidates
        if candidate["candidate_id"] != "RAW"
        and candidate["fragmentation"]["distinct_levels"] < raw_distinct_levels
    ]
    if not alternatives:
        return None, False
    target = AGGREGATE_GAIN_RETENTION * max(raw_gain_bits, 0.0)
    ordered = sorted(
        alternatives,
        key=lambda candidate: (
            candidate["fragmentation"]["distinct_levels"],
            -candidate["predictive_gain"]["held_out_gain_bits"],
            candidate["candidate_id"],
        ),
    )
    if raw_gain_bits > 0:
        for candidate in ordered:
            if candidate["predictive_gain"]["held_out_gain_bits"] >= target:
                return candidate, True
    best = max(
        alternatives,
        key=lambda candidate: (
            candidate["predictive_gain"]["held_out_gain_bits"],
            -candidate["fragmentation"]["distinct_levels"],
        ),
    )
    return best, raw_gain_bits > 0 and best["predictive_gain"]["held_out_gain_bits"] >= target


def _verdict(
    raw_fragmentation: Mapping[str, Any],
    raw_gain_bits: float,
    aggregated: Mapping[str, Any] | None,
    aggregation_retains_gain: bool,
    remove_threshold_bits: float,
) -> tuple[str, str, list[str]]:
    """Deterministic verdict + French label + evidence-backed justification."""
    raw_levels = raw_fragmentation["distinct_levels"]
    raw_low_share = raw_fragmentation["rows_share_in_levels_below_min_support"] or 0.0
    aggregated_gain = (
        aggregated["predictive_gain"]["held_out_gain_bits"] if aggregated is not None else None
    )
    best_gain = max(raw_gain_bits, aggregated_gain if aggregated_gain is not None else raw_gain_bits)
    #: A raw level set is fragmented as soon as one observed level sits below the
    #: support floor, or when its cardinality is simply too large to be supported.
    fragmented = (
        raw_fragmentation["levels_below_min_support"] > 0 or raw_levels > UNUSABLE_RAW_LEVELS
    )

    if best_gain <= remove_threshold_bits:
        return "REMOVE", "supprim\u00e9e", [
            (
                "held-out predictive gain {0} bits/decision (aggregated {1}) is at or below the "
                "effective removal threshold {2} bits: no measurable signal".format(
                    _format_gain(raw_gain_bits),
                    _format_gain(aggregated_gain),
                    remove_threshold_bits,
                )
            ),
            (
                "raw representation costs {0} levels, {1} below the {2}-row support floor covering "
                "{3} of TRAIN rows".format(
                    raw_levels,
                    raw_fragmentation["levels_below_min_support"],
                    MIN_SUPPORT_ROWS,
                    raw_fragmentation["rows_share_in_levels_below_min_support"],
                )
            ),
            (
                "removal is justified by the absence of predictive gain: the fragmentation cost is "
                "paid for nothing"
            ),
        ]

    if not fragmented and raw_low_share <= AGGREGATE_LOW_SUPPORT_SHARE:
        justification = [
            (
                "held-out predictive gain {0} bits/decision exceeds the effective removal threshold "
                "{1} bits".format(_format_gain(raw_gain_bits), remove_threshold_bits)
            ),
            (
                "raw levels are fully supported: {0} levels, {1} below the {2}-row support floor, "
                "{3} of TRAIN rows in supported levels".format(
                    raw_levels,
                    raw_fragmentation["levels_below_min_support"],
                    MIN_SUPPORT_ROWS,
                    raw_fragmentation["rows_share_in_supported_levels"],
                )
            ),
        ]
        if aggregated is not None:
            loss = (raw_gain_bits or 0.0) - (aggregated_gain or 0.0)
            justification.append(
                "the best coarsening {0} would keep {1} levels but lose {2} bits/decision of the "
                "measured gain, so keeping the raw levels is justified by predictive gain".format(
                    aggregated["candidate_id"],
                    aggregated["fragmentation"]["distinct_levels"],
                    format(_round(loss) or 0.0, ".6f"),
                )
            )
        else:
            justification.append(
                "no coarsening reduces the level count and no observed level is unsupported"
            )
        return "KEEP", "conserv\u00e9e", justification

    if aggregated is not None:
        aggregated_fragmentation = aggregated["fragmentation"]
        justification = [
            (
                "best held-out predictive gain (raw {0}, aggregated {1} bits/decision) exceeds the "
                "effective removal threshold {2} bits, so the dimension carries signal".format(
                    _format_gain(raw_gain_bits), _format_gain(aggregated_gain), remove_threshold_bits
                )
            ),
            (
                "raw levels are fragmented: {0} levels, {1} below the {2}-row support floor ({3} of "
                "TRAIN rows), effective cardinality {4}".format(
                    raw_levels,
                    raw_fragmentation["levels_below_min_support"],
                    MIN_SUPPORT_ROWS,
                    raw_fragmentation["rows_share_in_levels_below_min_support"],
                    raw_fragmentation["effective_levels"],
                )
            ),
            (
                "proposed aggregation {0} ({1}) keeps {2} levels with {3} of rows in low-support "
                "levels and a held-out gain of {4} bits".format(
                    aggregated["candidate_id"],
                    aggregated["strategy"],
                    aggregated_fragmentation["distinct_levels"],
                    aggregated_fragmentation["rows_share_in_levels_below_min_support"],
                    _format_gain(aggregated_gain),
                )
            ),
        ]
        if aggregation_retains_gain:
            retention = _round(aggregated_gain / raw_gain_bits) if raw_gain_bits > 0 else None
            justification.append(
                "aggregation retains at least {0:.0%} of the raw gain (measured retention {1})".format(
                    AGGREGATE_GAIN_RETENTION, retention
                )
            )
        elif raw_gain_bits <= 0:
            justification.append(
                "retention against the raw gain is not meaningful because the raw gain is "
                "non-positive; the aggregation is selected by absolute held-out gain instead, and "
                "the signal only appears once the unsupportable raw levels are coarsened"
            )
        else:
            justification.append(
                "no coarsening reaches the {0:.0%} retention target; the best available aggregation "
                "is reported with its measured loss instead of keeping an unsupportable raw level "
                "set".format(AGGREGATE_GAIN_RETENTION)
            )
        if raw_levels > UNUSABLE_RAW_LEVELS:
            justification.append(
                "{0} raw levels exceed the usable ceiling of {1} levels, so the raw level set could "
                "not be supported in production anyway".format(raw_levels, UNUSABLE_RAW_LEVELS)
            )
        return "AGGREGATE", "agr\u00e9g\u00e9e", justification

    return "KEEP", "conserv\u00e9e", [
        (
            "held-out predictive gain {0} bits/decision exceeds the effective removal threshold {1} "
            "bits".format(_format_gain(raw_gain_bits), remove_threshold_bits)
        ),
        (
            "raw levels are fragmented ({0} levels, {1} below the {2}-row support floor) and no "
            "documented coarsening reduces the level count, so the raw levels stay the only "
            "supported representation ({3} of TRAIN rows in supported levels)".format(
                raw_levels,
                raw_fragmentation["levels_below_min_support"],
                MIN_SUPPORT_ROWS,
                raw_fragmentation["rows_share_in_supported_levels"],
            )
        ),
    ]


def _dimension_audit(
    dimension: Dimension,
    rows: Sequence[Mapping[str, Any]],
    hand_ids: Sequence[str],
    fit_indices: Sequence[int],
    holdout_indices: Sequence[int],
    prior: Sequence[float],
    baseline_log_loss: float | None,
) -> tuple[dict[str, Any], list[str]]:
    """Distributions, fragmentation, predictive gain and verdict of one dimension.

    Returns the reviewable (public) dimension block and, separately, the
    recommended per-row label list used internally to build the joint
    representation (never persisted: it is one label per row).
    """
    fit_rows = [rows[index] for index in fit_indices]
    candidates = _candidate_levels(dimension, rows, fit_rows)
    actions = [str(row["action"]) for row in rows]
    for candidate in candidates:
        candidate["fragmentation"] = _fragmentation(candidate["labels"], hand_ids)
        log_loss = _log_loss_bits(candidate["labels"], rows, fit_indices, holdout_indices, prior)
        gain = (
            None
            if log_loss is None or baseline_log_loss is None
            else _round(baseline_log_loss - log_loss)
        )
        candidate["predictive_gain"] = {
            "held_out_log_loss_bits_per_decision": log_loss,
            "baseline_log_loss_bits_per_decision": baseline_log_loss,
            "held_out_gain_bits": gain,
            "held_out_gain_relative": _round(
                gain / baseline_log_loss if gain is not None and baseline_log_loss else None
            ),
            **_mutual_information_bits(candidate["labels"], actions),
        }

    raw = candidates[0]
    raw_gain = raw["predictive_gain"]["held_out_gain_bits"] or 0.0
    aggregated, retains_gain = _select_aggregation(
        candidates, raw["fragmentation"]["distinct_levels"], raw_gain
    )
    remove_threshold = _effective_remove_threshold(baseline_log_loss)
    verdict, verdict_fr, justification = _verdict(
        raw["fragmentation"], raw_gain, aggregated, retains_gain, remove_threshold
    )

    def present(candidate: Mapping[str, Any] | None) -> dict[str, Any] | None:
        if candidate is None:
            return None
        return {
            "candidate_id": candidate["candidate_id"],
            "strategy": candidate["strategy"],
            "detail": candidate["detail"],
            "distinct_levels": candidate["fragmentation"]["distinct_levels"],
            "levels": _level_table(candidate["labels"], hand_ids),
            "fragmentation": candidate["fragmentation"],
            "predictive_gain": candidate["predictive_gain"],
        }

    if verdict == "REMOVE":
        # A removed dimension must not fragment the recommended representation,
        # so every row collapses onto a single placeholder level.
        recommended_id = "REMOVED"
        recommended_labels = ["REMOVED"] * len(rows)
    else:
        recommended = aggregated if verdict == "AGGREGATE" and aggregated is not None else raw
        recommended_id = recommended["candidate_id"]
        recommended_labels = list(recommended["labels"])
    block = {
        "name": dimension.name,
        "axis": dimension.axis,
        "kind": dimension.kind,
        "description": dimension.description,
        "observations": len(rows),
        "distinct_hands": len(set(hand_ids)),
        "raw": present(raw),
        "aggregation": present(aggregated),
        "aggregation_retains_measured_gain": bool(retains_gain) if aggregated else None,
        "verdict": verdict,
        "verdict_fr": verdict_fr,
        "justification": justification,
        "evidence": {
            "predictive_gain_bits_per_decision": {
                "raw": raw_gain,
                "aggregated": aggregated["predictive_gain"]["held_out_gain_bits"]
                if aggregated
                else None,
                "aggregated_retains_measured_gain": bool(retains_gain) if aggregated else None,
                "effective_remove_threshold_bits": remove_threshold,
                "absolute_remove_threshold_bits": REMOVE_GAIN_THRESHOLD_BITS,
                "relative_remove_threshold": REMOVE_GAIN_THRESHOLD_RELATIVE,
            },
            "fragmentation": {
                "raw_distinct_levels": raw["fragmentation"]["distinct_levels"],
                "aggregated_distinct_levels": aggregated["fragmentation"]["distinct_levels"]
                if aggregated
                else None,
                "raw_rows_share_in_low_support_levels": raw["fragmentation"][
                    "rows_share_in_levels_below_min_support"
                ],
                "aggregated_rows_share_in_low_support_levels": aggregated["fragmentation"][
                    "rows_share_in_levels_below_min_support"
                ]
                if aggregated
                else None,
            },
            "support_thresholds": {
                "min_support_rows": MIN_SUPPORT_ROWS,
                "strong_support_rows": STRONG_SUPPORT_ROWS,
            },
            "low_support_level_examples": raw["fragmentation"]["low_support_levels"],
        },
        "recommended_candidate_id": recommended_id,
    }
    return block, recommended_labels


def _joint_cell_stats(
    label_lists: Mapping[str, Sequence[str]],
    actions: Sequence[str],
    order: Sequence[str],
    *,
    include_zone_lists: bool = False,
) -> dict[str, Any]:
    """Joint representation: cell count, support profile, covered/low zones."""
    cells: dict[tuple[str, ...], collections.Counter[str]] = {}
    for index, action in enumerate(actions):
        key = tuple(label_lists[name][index] for name in order)
        cells.setdefault(key, collections.Counter())[action] += 1
    sizes = sorted(sum(counter.values()) for counter in cells.values())
    total_rows = len(actions)
    supported = {
        key: counter for key, counter in cells.items() if sum(counter.values()) >= MIN_SUPPORT_ROWS
    }
    low_support = {
        key: counter for key, counter in cells.items() if sum(counter.values()) < MIN_SUPPORT_ROWS
    }
    rows_in_supported = sum(sum(counter.values()) for counter in supported.values())
    rows_in_low_support = total_rows - rows_in_supported

    def cell_entry(key: tuple[str, ...], counter: collections.Counter[str]) -> dict[str, Any]:
        observations = sum(counter.values())
        return {
            "levels": dict(zip(order, key)),
            "observations": observations,
            "share": _round(observations / total_rows) if total_rows else None,
            "support_tier": support_tier(observations),
            "actions": {action: int(counter.get(action, 0)) for action in ACTIONS},
        }

    supported_entries = [
        cell_entry(key, supported[key])
        for key in sorted(supported, key=lambda k: (-sum(supported[k].values()), k))
    ]
    low_support_entries = [
        cell_entry(key, low_support[key])
        for key in sorted(low_support, key=lambda k: (-sum(low_support[k].values()), k))
    ]
    stats: dict[str, Any] = {
        "dimensions": list(order),
        "cells_total": len(cells),
        "rows_total": total_rows,
        "mean_cell_support": _round(total_rows / len(cells)) if cells else None,
        "median_cell_support": _round(sizes[len(sizes) // 2]) if sizes else None,
        "supported_cells": len(supported),
        "supported_cells_share": _round(len(supported) / len(cells)) if cells else None,
        "rows_in_supported_cells": rows_in_supported,
        "rows_share_in_supported_cells": _round(rows_in_supported / total_rows)
        if total_rows
        else None,
        "low_support_cells": len(low_support),
        "rows_in_low_support_cells": rows_in_low_support,
        "rows_share_in_low_support_cells": _round(rows_in_low_support / total_rows)
        if total_rows
        else None,
        "min_support_rows": MIN_SUPPORT_ROWS,
        "covered_zones": supported_entries[:LIST_CAP_SUPPORTED_CELLS],
        "covered_zones_truncated": len(supported_entries) > LIST_CAP_SUPPORTED_CELLS,
    }
    if include_zone_lists:
        stats["low_support_zones"] = low_support_entries[:LIST_CAP_LOW_SUPPORT_CELLS]
        stats["low_support_zones_truncated"] = len(low_support_entries) > LIST_CAP_LOW_SUPPORT_CELLS
    return stats


def _induced_fragmentation(
    label_lists: Mapping[str, Sequence[str]],
    order: Sequence[str],
    actions: Sequence[str],
) -> list[dict[str, Any]]:
    """Cell growth measured when each dimension joins the retained prefix."""
    total_rows = len(actions)
    prefix_keys: list[tuple[str, ...]] = [() for _ in range(total_rows)]
    growth: list[dict[str, Any]] = []
    before = 0
    for name in order:
        values = label_lists[name]
        prefix_keys = [key + (values[index],) for index, key in enumerate(prefix_keys)]
        sizes: collections.Counter[tuple[str, ...]] = collections.Counter(prefix_keys)
        low_support_sizes = [size for size in sizes.values() if size < MIN_SUPPORT_ROWS]
        low_support_rows = sum(low_support_sizes)
        growth.append(
            {
                "dimension": name,
                "cells_before": before,
                "cells_after": len(sizes),
                "cells_added": len(sizes) - before,
                "cell_multiplier": _round(len(sizes) / before) if before else None,
                "low_support_cells_after": len(low_support_sizes),
                "low_support_cells_after_share": _round(len(low_support_sizes) / len(sizes))
                if sizes
                else None,
                "rows_in_low_support_cells_after": low_support_rows,
                "rows_share_in_low_support_cells_after": _round(low_support_rows / total_rows)
                if total_rows
                else None,
            }
        )
        before = len(sizes)
    return growth


def _action_summary(actions: Sequence[str]) -> dict[str, Any]:
    counts: collections.Counter[str] = collections.Counter(actions)
    total = len(actions)
    return {
        "observations": total,
        "counts": {action: int(counts.get(action, 0)) for action in ACTIONS},
        "rates": {
            action: _round(counts.get(action, 0) / total) if total else None for action in ACTIONS
        },
    }


def _observed_sizing_outcomes(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Descriptive sizing sides: label-derived, never a predictor."""
    raised = [
        row
        for row in rows
        if str(row.get("action")) in ("RAISE", "JAM") and row.get("target_total_bb") is not None
    ]
    targets: collections.Counter[str] = collections.Counter(
        _number_label(row.get("target_total_bb")) for row in raised
    )
    observed: collections.Counter[str] = collections.Counter(
        _number_label(row.get("observed_sizing_bb")) for row in raised
    )

    def top(counter: collections.Counter[str]) -> list[dict[str, Any]]:
        return [
            {"value": value, "observations": count}
            for value, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))[
                :LIST_CAP_LEVELS
            ]
        ]

    return {
        "role": "DESCRIPTIVE_LABEL_DERIVED_OUTCOME",
        "excluded_from_predictive_dimensions": True,
        "reason": (
            "target_total_bb/observed_sizing_bb only exist for RAISE/JAM, so they are consequences "
            "of the observed action and must not be used as predictors of it"
        ),
        "raise_or_jam_rows": len(raised),
        "distinct_target_total_bb": len(targets),
        "distinct_observed_sizing_bb": len(observed),
        "target_total_bb": top(targets),
        "observed_sizing_bb": top(observed),
    }


def _holdout_split(hand_ids: Sequence[str], modulus: int) -> tuple[list[int], list[int]]:
    """Hand-disjoint FIT/HOLDOUT fold assignment inside TRAIN."""
    fit_indices: list[int] = []
    holdout_indices: list[int] = []
    assignment: dict[str, bool] = {}
    for index, hand_id in enumerate(hand_ids):
        is_holdout = assignment.get(hand_id)
        if is_holdout is None:
            is_holdout = int(stable_hash(hand_id)[:8], 16) % modulus == 0
            assignment[hand_id] = is_holdout
        (holdout_indices if is_holdout else fit_indices).append(index)
    return fit_indices, holdout_indices


def _dataset_artifact_evidence() -> dict[str, Any]:
    """Link to the persisted dataset revision, without reading VALIDATION rows."""
    evidence: dict[str, Any] = {
        "payload_path": DATASET_PAYLOAD.relative_to(ROOT).as_posix(),
        "manifest_path": DATASET_MANIFEST.relative_to(ROOT).as_posix(),
        "payload_present": DATASET_PAYLOAD.is_file(),
        "manifest_present": DATASET_MANIFEST.is_file(),
        "validation_rows_read": 0,
        "test_rows_read": 0,
    }
    if DATASET_PAYLOAD.is_file():
        evidence["payload_sha256"] = sha256_file(DATASET_PAYLOAD)
        evidence["payload_bytes"] = DATASET_PAYLOAD.stat().st_size
    if DATASET_MANIFEST.is_file():
        manifest = json.loads(DATASET_MANIFEST.read_text(encoding="utf-8"))
        train = (manifest.get("splits") or {}).get("TRAIN") or {}
        evidence["manifest_schema"] = manifest.get("schema")
        evidence["train_split"] = {
            "hands": train.get("hands"),
            "response_rows": train.get("response_rows"),
            "hand_ids_fingerprint_sha256": train.get("hand_ids_fingerprint_sha256"),
        }
        evidence["manifest_validation_block_consumed"] = False
    return evidence


def analyze_rows(
    rows: Sequence[Mapping[str, Any]],
    provenance: Mapping[str, Any] | None = None,
    *,
    holdout_modulus: int = HOLDOUT_MODULUS,
) -> dict[str, Any]:
    """TRAIN-only fragmentation / representation report over response rows."""
    if not rows:
        raise ValueError("no TRAIN response rows supplied to the audit")
    if holdout_modulus < 2:
        raise ValueError("holdout_modulus must be >= 2")
    for row in rows:
        assert_train_row(row)

    hand_ids = [str(row["hand_id"]) for row in rows]
    actions = [str(row["action"]) for row in rows]
    fit_indices, holdout_indices = _holdout_split(hand_ids, holdout_modulus)
    prior = _global_prior(rows, fit_indices)
    baseline_log_loss = _log_loss_bits(
        ["ALL"] * len(rows), rows, fit_indices, holdout_indices, prior
    )

    dimensions: list[dict[str, Any]] = []
    recommended_labels: dict[str, list[str]] = {}
    for dimension in DIMENSIONS:
        block, labels = _dimension_audit(
            dimension, rows, hand_ids, fit_indices, holdout_indices, prior, baseline_log_loss
        )
        dimensions.append(block)
        recommended_labels[dimension.name] = labels
    raw_labels = {name: _raw_labels_for(name, rows) for name in DIMENSION_ORDER}

    family_rows: dict[str, list[str]] = {}
    for row, action in zip(rows, actions):
        family_rows.setdefault(_raw_label(DIMENSIONS_BY_NAME["family"], _get_family(row)), []).append(
            action
        )
    family_action_counts = {
        label: _action_summary(family_rows[label])
        for label in sorted(family_rows, key=lambda name: (-len(family_rows[name]), name))
    }

    order = list(DIMENSION_ORDER)
    removed = [dimension["name"] for dimension in dimensions if dimension["verdict"] == "REMOVE"]
    recommended_order = [name for name in DIMENSION_ORDER if name not in removed]
    recommended_representation_labels = {
        name: recommended_labels[name] for name in recommended_order
    }
    raw_joint = _joint_cell_stats(raw_labels, actions, order)
    recommended_joint = _joint_cell_stats(
        recommended_representation_labels, actions, recommended_order, include_zone_lists=True
    )
    verdict_counts: collections.Counter[str] = collections.Counter(
        dimension["verdict"] for dimension in dimensions
    )
    verdict_by_axis: dict[str, dict[str, list[str]]] = {}
    for dimension in dimensions:
        by_verdict = verdict_by_axis.setdefault(
            dimension["axis"], {verdict: [] for verdict in ("KEEP", "AGGREGATE", "REMOVE")}
        )
        by_verdict[dimension["verdict"]].append(dimension["name"])
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "population_id": POPULATION_ID,
        "scope": {
            "split_consumed": "TRAIN",
            "validation_consumed": False,
            "test_consumed": False,
            "splits_available_in_dataset": list(SPLITS),
            "refused_splits": list(FORBIDDEN_SPLITS),
            "validation_decisions_read": 0,
            "test_decisions_read": 0,
            "rows_reprojected_from_certified_train_hands": True,
            "optimization_performed": False,
            "model_fitted": False,
            "runtime_surface_touched": False,
            "purpose": (
                "TRAIN-only fragmentation diagnostic and representation justification (issue #421)"
            ),
        },
        "provenance": dict(provenance or {}),
        "semantics": {
            "predictive_gain_definition": (
                "reduction of held-out log loss (bits per decision) against the TRAIN FIT global "
                "action distribution"
            ),
            "fragmentation_definition": (
                "observed level cardinality, effective cardinality (2**H), share of levels and rows "
                "below the support thresholds, and induced joint-cell growth"
            ),
            "verdict_semantics": {
                "KEEP": "real held-out gain, raw levels already supported",
                "AGGREGATE": "real held-out gain, raw levels fragmented: coarsening proposed",
                "REMOVE": "no measurable held-out gain: only fragmentation cost remains",
            },
            "verdict_labels_fr": {
                "KEEP": "conserv\u00e9e",
                "AGGREGATE": "agr\u00e9g\u00e9e",
                "REMOVE": "supprim\u00e9e",
            },
            "scientific_effect": "NONE_ANALYTICS_ONLY",
            "level_support_caveat": (
                "support counts rows, not independent hands; distinct_hands is reported alongside "
                "every level so correlated same-hand rows stay visible"
            ),
            "outcome_dimensions_excluded": list(OUTCOME_DIMENSIONS),
            "price_transform_note": (
                "price_to_pot is a monotone transform of pot_odds for a fixed to_call_bb, so it "
                "adds no information and is intentionally not audited as a separate dimension"
            ),
        },
        "support_thresholds": {
            "min_support_rows": MIN_SUPPORT_ROWS,
            "strong_support_rows": STRONG_SUPPORT_ROWS,
            "very_strong_support_rows": VERY_STRONG_SUPPORT_ROWS,
            "remove_gain_threshold_bits": REMOVE_GAIN_THRESHOLD_BITS,
            "remove_gain_threshold_relative": REMOVE_GAIN_THRESHOLD_RELATIVE,
            "effective_remove_threshold_bits": _effective_remove_threshold(baseline_log_loss),
            "aggregate_gain_retention": AGGREGATE_GAIN_RETENTION,
            "aggregate_low_support_share": AGGREGATE_LOW_SUPPORT_SHARE,
            "unusable_raw_levels": UNUSABLE_RAW_LEVELS,
            "fragmentation_trigger": (
                "raw levels are fragmented as soon as one observed level is below the support floor "
                "or the raw cardinality exceeds unusable_raw_levels"
            ),
            "remove_rule": (
                "max(absolute_floor, relative_floor * baseline_log_loss): a dimension must reduce "
                "held-out log loss by at least that many bits per decision to be informative"
            ),
            "support_tiers": {
                "VERY_HIGH": ">=1000 observations",
                "HIGH": "250-999 observations",
                "MEDIUM": "50-249 observations",
                "LOW": "20-49 observations",
                "SPARSE": "<20 observations",
            },
            "source": "aligns with tools/training/audit_hero_preflop_coverage.support_tier",
        },
        "accounting": {
            "train_response_rows": len(rows),
            "train_distinct_hands": len(set(hand_ids)),
            "fit_rows": len(fit_indices),
            "fit_hands": len({hand_ids[index] for index in fit_indices}),
            "holdout_rows": len(holdout_indices),
            "holdout_hands": len({hand_ids[index] for index in holdout_indices}),
            "baseline_log_loss_bits_per_decision": baseline_log_loss,
            "actions": _action_summary(actions),
        },
        "holdout_protocol": {
            "split": "TRAIN -> FIT/HOLDOUT",
            "assignment": "stable_hash(hand_id) % holdout_modulus == 0 -> HOLDOUT",
            "hand_disjoint": True,
            "holdout_modulus": holdout_modulus,
            "holdout_share": _round(len(holdout_indices) / len(rows)) if rows else None,
            "smoothing": "m-estimate toward the FIT prior",
            "smoothing_mass": SMOOTHING_MASS,
            "backoff": "cells with FIT support < {0} rows use the FIT global distribution".format(
                MIN_SUPPORT_ROWS
            ),
            "log_base": 2,
            "validation_used": False,
            "test_used": False,
        },
        "action_distribution_by_family": family_action_counts,
        "observed_sizing_outcomes": _observed_sizing_outcomes(rows),
        "dimensions": dimensions,
        "verdict_summary": {
            "counts": {
                verdict: int(verdict_counts.get(verdict, 0))
                for verdict in ("KEEP", "AGGREGATE", "REMOVE")
            },
            "KEEP": [d["name"] for d in dimensions if d["verdict"] == "KEEP"],
            "AGGREGATE": [d["name"] for d in dimensions if d["verdict"] == "AGGREGATE"],
            "REMOVE": [d["name"] for d in dimensions if d["verdict"] == "REMOVE"],
            "by_axis": verdict_by_axis,
        },
        "fragmentation": {
            "raw_full_representation": raw_joint,
            "recommended_representation": {
                key: value
                for key, value in recommended_joint.items()
                if key not in ("low_support_zones", "low_support_zones_truncated")
            },
            "induced_by_dimension": _induced_fragmentation(
                recommended_representation_labels, recommended_order, actions
            ),
            "recommended_representation_definition": {
                "KEEP": "raw observed levels",
                "AGGREGATE": "selected aggregation candidate",
                "REMOVE": "dimension dropped from the joint representation entirely",
            },
            "removed_dimensions": removed,
        },
        "low_support_zones": {
            "definition": "joint cells of the recommended representation with < {0} TRAIN rows".format(
                MIN_SUPPORT_ROWS
            ),
            "cells_total": recommended_joint["low_support_cells"],
            "rows_total": recommended_joint["rows_in_low_support_cells"],
            "rows_share": recommended_joint["rows_share_in_low_support_cells"],
            "cells": recommended_joint.get("low_support_zones", []),
            "cells_truncated": recommended_joint.get("low_support_zones_truncated", False),
            "per_dimension": [
                {
                    "name": dimension["name"],
                    "axis": dimension["axis"],
                    "verdict": dimension["verdict"],
                    "candidate_id": dimension["recommended_candidate_id"],
                    "levels_below_min_support": dimension["raw"]["fragmentation"][
                        "levels_below_min_support"
                    ],
                    "rows_share_in_levels_below_min_support": dimension["raw"]["fragmentation"][
                        "rows_share_in_levels_below_min_support"
                    ],
                    "examples": dimension["raw"]["fragmentation"]["low_support_levels"],
                }
                for dimension in dimensions
            ],
        },
        "dataset_artifact": _dataset_artifact_evidence(),
    }
    report["report_hash"] = stable_hash(
        {key: value for key, value in report.items() if key != "report_hash"}
    )
    return report


def audit(
    certification: Path = DEFAULT_CERTIFICATION,
    *,
    holdout_modulus: int = HOLDOUT_MODULUS,
) -> dict[str, Any]:
    """Re-project certified TRAIN hands through the dataset projection and audit."""
    certification = Path(certification)
    records, provenance = load_train_records(certification)
    rows, counters = iter_response_rows(records, "TRAIN")
    hand_ids = [str(record.hand_id) for record in records]
    expected = int((provenance.get("certified_split_counts") or {}).get("TRAIN") or 0)
    if len(hand_ids) != expected:
        raise AssertionError("certified TRAIN hand count mismatch: {0} != {1}".format(len(hand_ids), expected))
    splits_seen = {str(row["split"]) for row in rows}
    if splits_seen != {"TRAIN"}:
        raise AssertionError("non-TRAIN rows crossed the projection boundary: {0}".format(splits_seen))
    provenance = {
        **provenance,
        "certification_path": certification.relative_to(ROOT).as_posix()
        if certification.is_relative_to(ROOT)
        else str(certification),
        "train_hand_count": len(hand_ids),
        "train_hand_ids_fingerprint_sha256": fingerprint(hand_ids),
        "row_projector": (
            "tools/training/build_generalized_response_dataset.py::iter_response_rows(records, 'TRAIN')"
        ),
        "test_hands_consumed": 0,
        "validation_hands_consumed": 0,
        "certified_split_counts_note": (
            "certified_split_counts is population certification metadata; only the TRAIN hand ids "
            "are loaded, and no VALIDATION or TEST decision ever crosses the parser boundary"
        ),
        "train_projection_counters": counters,
        "auditor": {
            "path": Path(__file__).resolve().relative_to(ROOT).as_posix(),
            "sha256": sha256_file(Path(__file__).resolve()),
        },
    }
    return analyze_rows(rows, provenance, holdout_modulus=holdout_modulus)


def render_summary(report: Mapping[str, Any]) -> str:
    """Compact console summary (the JSON report stays authoritative)."""
    lines = [
        "schema: " + str(report["schema"]),
        "scope: split_consumed={0} validation_consumed={1} test_consumed={2}".format(
            report["scope"]["split_consumed"],
            report["scope"]["validation_consumed"],
            report["scope"]["test_consumed"],
        ),
        "TRAIN rows={0} hands={1} fit_rows={2} holdout_rows={3}".format(
            report["accounting"]["train_response_rows"],
            report["accounting"]["train_distinct_hands"],
            report["accounting"]["fit_rows"],
            report["accounting"]["holdout_rows"],
        ),
        "raw joint cells={0} rows_in_low_support_share={1}".format(
            report["fragmentation"]["raw_full_representation"]["cells_total"],
            report["fragmentation"]["raw_full_representation"]["rows_share_in_low_support_cells"],
        ),
        "recommended joint cells={0} rows_in_low_support_share={1}".format(
            report["fragmentation"]["recommended_representation"]["cells_total"],
            report["fragmentation"]["recommended_representation"]["rows_share_in_low_support_cells"],
        ),
        "verdicts:",
    ]
    for dimension in report["dimensions"]:
        lines.append(
            "  {0:<22} {1:<9} gain_raw={2} gain_aggregated={3}".format(
                dimension["name"],
                dimension["verdict"],
                _format_gain(dimension["raw"]["predictive_gain"]["held_out_gain_bits"]),
                _format_gain(
                    dimension["aggregation"]["predictive_gain"]["held_out_gain_bits"]
                    if dimension["aggregation"]
                    else None
                ),
            )
        )
    lines.append("report_hash: " + str(report["report_hash"]))
    return "\n".join(lines)


def canonical_report_bytes(report: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")


def write_report(report: Mapping[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--certification", type=Path, default=DEFAULT_CERTIFICATION)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--holdout-modulus", type=int, default=HOLDOUT_MODULUS)
    parser.add_argument("--print-json", action="store_true", help="print the full report to stdout")
    parser.add_argument("--no-write", action="store_true", help="skip persisting the report")
    parser.add_argument("--summary", action="store_true", help="print the compact console summary")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    certification = args.certification if args.certification.is_absolute() else ROOT / args.certification
    report = audit(certification, holdout_modulus=args.holdout_modulus)
    if not args.no_write:
        output = args.output_json if args.output_json.is_absolute() else ROOT / args.output_json
        write_report(report, output)
    if args.print_json:
        sys.stdout.write(canonical_report_bytes(report).decode("utf-8"))
    elif args.summary:
        print(render_summary(report))
    else:
        print(
            json.dumps(
                {
                    "schema": report["schema"],
                    "report_hash": report["report_hash"],
                    "accounting": report["accounting"],
                    "verdict_summary": report["verdict_summary"],
                    "low_support_zone_rows_share": report["low_support_zones"]["rows_share"],
                },
                indent=2,
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

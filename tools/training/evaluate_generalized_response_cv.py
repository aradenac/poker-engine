#!/usr/bin/env python3
"""#421 T4 - TRAIN-only, hand-grouped cross-validation of the response architectures.

The T3 deliverable (``tools/preflop/generalized_response_model.py``) exposes two
comparable architectures over the public-only adverse-response dataset:
``regularized_multinomial_spline`` (A) and
``hierarchical_empirical_bayes_dirichlet`` (B).  T3 selected its operating
point on a *single* deterministic holdout derived from the TRAIN rows and left
the architecture choice to a direct comparison.  T4 hardens that choice:

* the comparison happens **on TRAIN only**, through an internal ``k``-fold
  cross-validation whose folds are grouped by ``hand_id`` so that two decisions
  of the same hand never land on both sides of a split (proved by an explicit
  no-leak assertion, not by convention);
* every architecture is refit once per fold and scored **out of fold** on the
  held-out fold, so the reported numbers never reuse the rows a candidate was
  fitted on;
* the report carries the full metric surface requested by the task --
  multiclass log loss, Brier, expected calibration error (ECE), coverage after
  a *provisional* OOD gate, per-position / per-family / per-sizing-bucket
  breakdowns, and the three decision strata that matter for generalization
  (frequent exact contexts, rare exact contexts, and exact contexts absent from
  the fit fold although every individual feature value is in-domain);
* the architecture is selected by a **preregistered** decision procedure
  written down in :data:`PREREGISTERED_SELECTION_CRITERIA` and applied to
  out-of-fold evidence only.

The VALIDATION and TEST folds are never read: ``scope.validation_consumed`` and
``scope.test_consumed`` are ``false`` and the loader fails closed on TEST.  The
persisted report is byte-reproducible (no timestamps, no wall-clock timings;
runtime simplicity is compared through a deterministic, predeclared complexity
rank plus the fitted model's node-cell footprint).

Only the Python standard library is used.
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.preflop import generalized_response_model as grm  # noqa: E402

SCHEMA = "poker-generalized-response-train-cv/v1"
SELF_CHECK_SCHEMA = "poker-generalized-response-train-cv-self-check/v1"

DEFAULT_DATASET = ROOT / "analysis/issue421_generalized_response/dataset/GENERALIZED_RESPONSE_DATASET.jsonl"
DEFAULT_OUTPUT = ROOT / "analysis/issue421_generalized_response/TRAIN_CV_REPORT.json"

#: The CV consumes one fold only; every other split stays unconsumed.
MAIN_SPLIT = "TRAIN"
CONSUMED_SPLITS = ("TRAIN",)
FORBIDDEN_SPLITS = grm.FORBIDDEN_SPLITS

#: Hand-grouped k-fold protocol.
CV_FOLDS = 5
CV_SEED = 421

#: Support thresholds.  ``FREQUENT_EXACT_MIN_SUPPORT`` reuses the repository's
#: minimum-support convention (``interaction_min_support`` /
#: ``MINIMUM_BIN_SUPPORT`` = 20): an exact context seen at least 20 times in the
#: fit fold is "frequent", between 1 and 19 times is "rare", never seen is
#: "absent".
FREQUENT_EXACT_MIN_SUPPORT = 20
RARE_EXACT_MIN_SUPPORT = 1

#: Provisional OOD gate: accept a decision only when the fit fold saw the exact
#: context signature at least this many times *and* every individual feature
#: value is in-domain.  Provisional by construction -- it is a coverage probe
#: for T4, not a frozen runtime gate.
PROVISIONAL_OOD_GATE_MIN_EXACT_SUPPORT = 5
PROVISIONAL_OOD_GATE_SENSITIVITY = (1, 5, 20)

#: Frozen T2 calibration definition (equal-count reliability bins per action
#: class, absolute gap, weighted by bin mass).
CALIBRATION_BINS = 10
CALIBRATION_MINIMUM_BIN_SUPPORT = 20

#: Tolerance bands of the preregistered selection procedure.
LOGLOSS_TOLERANCE_BITS_PER_DECISION = 0.005
CALIBRATION_TOLERANCE_ECE = 0.002
BRIER_TOLERANCE = 0.001
STABILITY_TOLERANCE_BITS_PER_DECISION = 0.005

#: Predeclared runtime complexity of each architecture (1 = simplest).  The rank
#: is a property of the estimator, not of the machine that ran it.
RUNTIME_COMPLEXITY_RANK: dict[str, int] = {
    grm.ARCH_REGULARIZED: 1,
    grm.ARCH_HIERARCHICAL: 2,
}

#: Sizing buckets are the pot-relative observed raise target
#: ``target_total_bb / (pot_before_bb + to_call_bb)``.  Passive decisions carry
#: no raise target: they are reported as a distinct bucket instead of being
#: folded into a fabricated sizing.
SIZING_BUCKET_EDGES: tuple[float, ...] = (0.5, 1.0, 2.0, 4.0)
SIZING_BUCKET_LABELS: tuple[str, ...] = ("R<=0.5", "R0.5-1", "R1-2", "R2-4", "R>4")
NO_OBSERVED_SIZING = "NO_OBSERVED_SIZING"

#: Pot bucket edges used by the "exact context" signature (the model itself
#: splines ``pot_before_bb``; the signature needs a finite, deterministic grid).
POT_BUCKET_EDGES: tuple[float, ...] = (2.5, 6.0, 15.0, 40.0)

#: Bucket labels of the exact-context signature (the coarse buckets reuse the
#: model's own edges, so a signature is exactly what the models index).
TO_CALL_BUCKET_LABELS: tuple[str, ...] = tuple(
    f"B{index}" for index in range(len(grm.COARSE_BUCKETS["to_call_bucket"]) + 1)
)
EFFECTIVE_STACK_BUCKET_LABELS: tuple[str, ...] = tuple(
    f"B{index}" for index in range(len(grm.COARSE_BUCKETS["effective_stack_bucket"]) + 1)
)
POT_BUCKET_LABELS: tuple[str, ...] = tuple(f"P{index}" for index in range(len(POT_BUCKET_EDGES) + 1))

#: Strata of the generalization analysis, in report order.
STRATUM_FREQUENT_EXACT = "frequent_exact"
STRATUM_RARE_EXACT = "rare_exact"
STRATUM_EXACT_ABSENT_IN_DOMAIN = "exact_absent_in_domain"
STRATUM_EXACT_ABSENT_OUT_OF_DOMAIN = "exact_absent_out_of_domain"
STRATA = (
    STRATUM_FREQUENT_EXACT,
    STRATUM_RARE_EXACT,
    STRATUM_EXACT_ABSENT_IN_DOMAIN,
    STRATUM_EXACT_ABSENT_OUT_OF_DOMAIN,
)

#: Feature blocks whose *single-feature* node label decides in-domain-ness.
FEATURE_BLOCKS: tuple[str, ...] = grm.CATEGORICAL_BLOCKS + (
    "to_call_bucket",
    "effective_stack_bucket",
    "pot_bucket",
)

CALIBRATION_DEFINITION = (
    "equal-count reliability bins per action class (frozen T2 definition of "
    "tools/training/validate_hierarchical_validation.py::expected_calibration_error): "
    "for each action, sort rows by predicted probability, cut 10 equal-count bins, "
    "accumulate bin-mass-weighted |mean predicted - mean observed| and average over "
    "the four action classes"
)

STRATA_DEFINITION = (
    "held-out decisions stratified by the fit-fold support of their exact context signature "
    f"(exact_context_key): frequent_exact = support >= {FREQUENT_EXACT_MIN_SUPPORT}, "
    f"rare_exact = {RARE_EXACT_MIN_SUPPORT} <= support < {FREQUENT_EXACT_MIN_SUPPORT}, "
    "exact_absent_in_domain = support == 0 while every single-feature node label is observed in "
    "the fit fold, exact_absent_out_of_domain = support == 0 with at least one unseen feature value"
)

PROVISIONAL_OOD_GATE_DEFINITION = (
    "provisional, predeclared OOD gate: accept a held-out decision iff every single-feature node "
    "label of the decision was observed in the fit fold (feature-level in-domain) AND the fit fold "
    "saw the decision's exact context signature at least "
    f"{PROVISIONAL_OOD_GATE_MIN_EXACT_SUPPORT} times; coverage is the accepted share of the "
    "held-out fold"
)

PREREGISTERED_SELECTION_CRITERIA: dict[str, Any] = {
    "preregistered": True,
    "registered_before_evaluation": True,
    "consumed_splits": list(CONSUMED_SPLITS),
    "evidence_basis": "out_of_fold_holdout_only",
    "validation_consumed": False,
    "test_consumed": False,
    "direction": "lower_is_better",
    "steps": [
        {
            "step": 1,
            "name": "out_of_fold_performance",
            "metric": "out_of_fold.log_loss_bits_per_decision",
            "tolerance": LOGLOSS_TOLERANCE_BITS_PER_DECISION,
            "rule": (
                "keep every architecture whose pooled out-of-fold multiclass log loss is "
                "within the preregistered tolerance of the best one"
            ),
        },
        {
            "step": 2,
            "name": "calibration",
            "metric": "out_of_fold.expected_calibration_error.ece",
            "tolerance": CALIBRATION_TOLERANCE_ECE,
            "rule": "among the survivors, keep the architectures within the ECE tolerance of the best",
        },
        {
            "step": 3,
            "name": "brier",
            "metric": "out_of_fold.brier_score",
            "tolerance": BRIER_TOLERANCE,
            "rule": "among the survivors, keep the architectures within the Brier tolerance of the best",
        },
        {
            "step": 4,
            "name": "stability",
            "metric": "stability.fold_log_loss_stddev",
            "tolerance": STABILITY_TOLERANCE_BITS_PER_DECISION,
            "rule": "among the survivors, keep the architectures with the most stable fold-to-fold log loss",
        },
        {
            "step": 5,
            "name": "runtime_simplicity",
            "metric": "runtime.complexity_rank",
            "tolerance": 0.0,
            "rule": "among the survivors, keep the lowest predeclared runtime complexity rank",
        },
        {
            "step": 6,
            "name": "deterministic_tiebreak",
            "metric": "architecture",
            "tolerance": 0.0,
            "rule": "final deterministic tiebreak on the architecture name",
        },
    ],
    "runtime_complexity_rank": dict(RUNTIME_COMPLEXITY_RANK),
}


class TrainCrossValidationError(RuntimeError):
    """Fail-closed error for the TRAIN cross-validation surface."""


# ---------------------------------------------------------------------------
# small numeric helpers
# ---------------------------------------------------------------------------


def _round(value: Any, digits: int = 6) -> Any:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    number = float(value)
    if not math.isfinite(number):
        return None
    return round(number, digits)


def _finalize(value: Any) -> Any:
    """Recursively round floats so the report is deterministic and readable."""
    if isinstance(value, Mapping):
        return {key: _finalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finalize(item) for item in value]
    if isinstance(value, float):
        return _round(value)
    return value


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _stddev(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = _mean(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(path: str | Path) -> str:
    resolved = Path(path).resolve()
    try:
        return str(resolved.relative_to(ROOT))
    except ValueError:
        return str(resolved)


def _bucket_label(edges: Sequence[float], value: Any, labels: Sequence[str]) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return grm.MISSING
    if not math.isfinite(number):
        return grm.MISSING
    index = bisect.bisect_right([float(edge) for edge in edges], max(0.0, number))
    return labels[min(index, len(labels) - 1)]


# ---------------------------------------------------------------------------
# exact context signature, feature levels, sizing buckets
# ---------------------------------------------------------------------------


def exact_context_key(row: Mapping[str, Any], config: Mapping[str, Any] | None = None) -> str:
    """Deterministic signature of the public context at the model's resolution.

    The signature combines exactly the discrete node labels the two T3
    architectures actually index -- the seven categorical blocks plus the two
    coarse buckets they already use -- and adds one pot bucket.  Two decisions
    share an exact context iff the models see them as the same discrete cell, so
    "the exact combination was never observed" is a statement about the models'
    own resolution rather than about an unrelated rounding.
    """
    del config  # the node grid is fully determined by the module-level tables
    parts = [grm.categorical_node(block, row) for block in grm.CATEGORICAL_BLOCKS]
    parts.append(_bucket_label(grm.COARSE_BUCKETS["to_call_bucket"], row.get("to_call_bb"), TO_CALL_BUCKET_LABELS))
    parts.append(
        _bucket_label(
            grm.COARSE_BUCKETS["effective_stack_bucket"],
            row.get("effective_stack_bb"),
            EFFECTIVE_STACK_BUCKET_LABELS,
        )
    )
    parts.append(_bucket_label(POT_BUCKET_EDGES, row.get("pot_before_bb"), POT_BUCKET_LABELS))
    return "|".join(parts)


def feature_levels(row: Mapping[str, Any], config: Mapping[str, Any] | None = None) -> dict[str, str]:
    """One node label per single-feature block (the in-domain test surface)."""
    del config
    levels = {block: grm.categorical_node(block, row) for block in grm.CATEGORICAL_BLOCKS}
    levels["to_call_bucket"] = _bucket_label(
        grm.COARSE_BUCKETS["to_call_bucket"], row.get("to_call_bb"), TO_CALL_BUCKET_LABELS
    )
    levels["effective_stack_bucket"] = _bucket_label(
        grm.COARSE_BUCKETS["effective_stack_bucket"],
        row.get("effective_stack_bb"),
        EFFECTIVE_STACK_BUCKET_LABELS,
    )
    levels["pot_bucket"] = _bucket_label(POT_BUCKET_EDGES, row.get("pot_before_bb"), POT_BUCKET_LABELS)
    return levels


def sizing_bucket(row: Mapping[str, Any]) -> str:
    """Pot-relative bucket of the observed raise target (or a no-sizing label)."""
    target = row.get("target_total_bb")
    if target is None:
        return NO_OBSERVED_SIZING
    try:
        target_value = float(target)
        denominator = float(row.get("pot_before_bb") or 0.0) + float(row.get("to_call_bb") or 0.0)
    except (TypeError, ValueError):
        return NO_OBSERVED_SIZING
    if not math.isfinite(target_value) or not math.isfinite(denominator):
        return NO_OBSERVED_SIZING
    ratio = max(0.0, target_value) / max(denominator, grm.EPS)
    return SIZING_BUCKET_LABELS[
        min(bisect.bisect_right(SIZING_BUCKET_EDGES, ratio), len(SIZING_BUCKET_LABELS) - 1)
    ]


# ---------------------------------------------------------------------------
# hand-grouped folds (the no-leak core)
# ---------------------------------------------------------------------------


def fold_of(hand_id: str, seed: int = CV_SEED, folds: int = CV_FOLDS) -> int:
    """Deterministic fold index of one hand; every decision of a hand shares it."""
    folds = int(folds)
    if folds < 2:
        raise TrainCrossValidationError("cross-validation needs at least two folds")
    identity = str(hand_id).strip()
    if not identity:
        raise TrainCrossValidationError("cross-validation requires a non-empty hand_id")
    return int(grm.stable_hash(f"grm-cv/{int(seed)}/{identity}")[:8], 16) % folds


class FoldIndex:
    """Fit-fold sufficient statistics used to classify held-out decisions."""

    def __init__(self) -> None:
        self.exact_support: dict[str, int] = {}
        self.feature_values: dict[str, set[str]] = {block: set() for block in FEATURE_BLOCKS}
        self.rows = 0
        self.hands: set[str] = set()

    def add(self, row: Mapping[str, Any]) -> None:
        config = None
        key = exact_context_key(row, config)
        self.exact_support[key] = self.exact_support.get(key, 0) + 1
        for block, level in feature_levels(row, config).items():
            self.feature_values[block].add(level)
        self.rows += 1
        self.hands.add(str(row.get("hand_id") or "").strip())


class Fold:
    """One cross-validation fold: the fit rows, the held-out rows and the index."""

    def __init__(self, index: int, train_rows: list[dict[str, Any]], holdout_rows: list[dict[str, Any]]) -> None:
        self.index = int(index)
        self.train_rows = train_rows
        self.holdout_rows = holdout_rows
        self.fit_index = FoldIndex()
        for row in train_rows:
            self.fit_index.add(row)
        self.train_hands = {str(row.get("hand_id") or "").strip() for row in train_rows}
        self.holdout_hands = {str(row.get("hand_id") or "").strip() for row in holdout_rows}

    def summary(self) -> dict[str, Any]:
        return {
            "fold": self.index,
            "fit_rows": len(self.train_rows),
            "fit_hands": len(self.train_hands),
            "holdout_rows": len(self.holdout_rows),
            "holdout_hands": len(self.holdout_hands),
            "hand_overlap_with_fit": len(self.train_hands & self.holdout_hands),
            "holdout_exact_contexts": len({exact_context_key(row) for row in self.holdout_rows}),
            "fit_exact_contexts": len(self.fit_index.exact_support),
        }


def grouped_folds(
    rows: Iterable[Mapping[str, Any]],
    *,
    folds: int = CV_FOLDS,
    seed: int = CV_SEED,
) -> list[Fold]:
    """Hand-grouped k-fold split with an explicit, fail-closed no-leak assertion.

    Rows are canonically ordered first (so the split never depends on input
    order), then every row is assigned to the fold of its ``hand_id``.  The
    function asserts, from the data it just built, that (a) each hand maps to
    exactly one fold, (b) the per-fold holdout hands are pairwise disjoint, and
    (c) no fold holds out a hand that also appears in its own fit rows.
    """
    ordered = grm.order_rows(rows)  # refuses TEST, validates the action space
    if not ordered:
        raise TrainCrossValidationError("no rows to cross-validate")
    fold_count = int(folds)
    if fold_count < 2:
        raise TrainCrossValidationError("cross-validation needs at least two folds")

    holdout: list[list[dict[str, Any]]] = [[] for _ in range(fold_count)]
    hand_to_fold: dict[str, int] = {}
    for index, row in enumerate(ordered):
        hand_id = str(row.get("hand_id") or "").strip()
        if not hand_id:
            raise TrainCrossValidationError(
                f"row {index} has no hand_id: a hand-grouped split cannot be proven"
            )
        assigned = fold_of(hand_id, seed, fold_count)
        existing = hand_to_fold.get(hand_id)
        if existing is not None and existing != assigned:
            raise TrainCrossValidationError(f"hand {hand_id!r} is assigned to two folds")
        hand_to_fold[hand_id] = assigned
        holdout[assigned].append(row)

    fold_holdout_hands = [{str(row["hand_id"]).strip() for row in bucket} for bucket in holdout]
    all_hands = set(hand_to_fold)
    for bucket in holdout:
        if not bucket:
            raise TrainCrossValidationError("a cross-validation fold holds no row; lower the fold count")

    # ---- no-leak assertion (the acceptance criterion, checked not assumed) ----
    for position, hands in enumerate(fold_holdout_hands):
        other = set().union(*(set(x) for index, x in enumerate(fold_holdout_hands) if index != position))
        assert not (hands & other), "hand-grouped split leaked a hand across folds"
    assert set().union(*fold_holdout_hands) == all_hands, "the split did not cover every hand"
    assert sum(len(hands) for hands in fold_holdout_hands) == len(all_hands), "a hand landed in two folds"

    folds_out: list[Fold] = []
    for position in range(fold_count):
        train_rows = [row for index, bucket in enumerate(holdout) if index != position for row in bucket]
        built = Fold(position, train_rows, holdout[position])
        assert not (built.train_hands & built.holdout_hands), "hand-grouped split leaked into its own fit rows"
        folds_out.append(built)
    return folds_out


def no_leak_proof(folds: Sequence[Fold]) -> dict[str, Any]:
    """Machine-checkable evidence that the split is hand-disjoint."""
    holdout_hands = [fold.holdout_hands for fold in folds]
    hands = set().union(*holdout_hands) if holdout_hands else set()
    overlaps = [len(fold.train_hands & fold.holdout_hands) for fold in folds]
    return {
        "group_key": "hand_id",
        "folds": len(folds),
        "hands": len(hands),
        "hands_assigned_to_exactly_one_fold": sum(len(item) for item in holdout_hands) == len(hands),
        "holdout_hands_pairwise_disjoint": True,
        "max_hand_overlap_between_fit_and_holdout": max(overlaps) if overlaps else 0,
        "holdout_hands_per_fold": [len(item) for item in holdout_hands],
        "assertion": (
            "assert not (holdout_hands_i & train_hands_i) for every fold i, and "
            "assert the holdout hand sets partition the hand universe"
        ),
        "checked_at_runtime": True,
    }


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------


def _equal_count_bins(count: int, bins: int) -> list[list[int]]:
    groups: list[list[int]] = []
    for index in range(bins):
        chunk = list(range(index * count // bins, (index + 1) * count // bins))
        if chunk:
            groups.append(chunk)
    return groups


def expected_calibration_error(
    records: Sequence[Mapping[str, Any]],
    *,
    bins: int = CALIBRATION_BINS,
    minimum_bin_support: int = CALIBRATION_MINIMUM_BIN_SUPPORT,
) -> dict[str, Any]:
    """Equal-count reliability bins per action class (the frozen T2 definition)."""
    if not records:
        return {
            "ece": None,
            "per_action_class": {},
            "bins_per_action_class": bins,
            "minimum_bin_support": minimum_bin_support,
            "bins_meeting_minimum_support": 0,
            "claim_supportable": False,
        }
    count = len(records)
    per_class: dict[str, float] = {}
    qualifying_bins = 0
    for action in grm.ACTIONS:
        order = sorted(
            range(count),
            key=lambda position: (float(records[position]["probabilities"].get(action, 0.0)), position),
        )
        value = 0.0
        for chunk in _equal_count_bins(count, bins):
            members = [order[position] for position in chunk]
            if len(members) >= minimum_bin_support:
                qualifying_bins += 1
            mean_predicted = sum(
                float(records[position]["probabilities"].get(action, 0.0)) for position in members
            ) / len(members)
            mean_observed = sum(
                1.0 for position in members if records[position]["observed"] == action
            ) / len(members)
            value += (len(members) / count) * abs(mean_predicted - mean_observed)
        per_class[action] = value
    return {
        "ece": sum(per_class.values()) / len(per_class),
        "per_action_class": per_class,
        "bins_per_action_class": bins,
        "minimum_bin_support": minimum_bin_support,
        "bins_meeting_minimum_support": qualifying_bins,
        "claim_supportable": qualifying_bins > 0,
    }


def summary_metrics(records: Sequence[Mapping[str, Any]], prior: Mapping[str, float]) -> dict[str, Any]:
    """Full metric surface of one record set (log loss, Brier, accuracy, ECE)."""
    if not records:
        return {
            "n": 0,
            "log_loss_bits_per_decision": None,
            "baseline_log_loss_bits_per_decision": None,
            "gain_bits_per_decision": None,
            "brier_score": None,
            "accuracy": None,
            "expected_calibration_error": expected_calibration_error(()),
        }
    total = 0.0
    baseline = 0.0
    brier = 0.0
    correct = 0
    observed_counts = {action: 0 for action in grm.ACTIONS}
    predicted_mass = {action: 0.0 for action in grm.ACTIONS}
    max_probability_sum_error = 0.0
    max_illegal_mass = 0.0
    for record in records:
        observed = str(record["observed"])
        probabilities = record["probabilities"]
        total -= math.log2(max(float(probabilities[observed]), grm.PROBABILITY_FLOOR))
        baseline -= math.log2(max(float(prior[observed]), grm.PROBABILITY_FLOOR))
        brier += sum(
            (float(probabilities[action]) - (1.0 if action == observed else 0.0)) ** 2
            for action in grm.ACTIONS
        )
        if max(probabilities, key=lambda action: probabilities[action]) == observed:
            correct += 1
        observed_counts[observed] += 1
        for action in grm.ACTIONS:
            predicted_mass[action] += float(probabilities[action])
        max_probability_sum_error = max(
            max_probability_sum_error, abs(sum(float(value) for value in probabilities.values()) - 1.0)
        )
        max_illegal_mass = max(
            max_illegal_mass, sum(float(probabilities[action]) for action in record.get("masked_actions", ()))
        )
    n = len(records)
    log_loss = total / n
    baseline_log_loss = baseline / n
    return {
        "n": n,
        "log_loss_bits_per_decision": log_loss,
        "baseline_log_loss_bits_per_decision": baseline_log_loss,
        "gain_bits_per_decision": baseline_log_loss - log_loss,
        "brier_score": brier / n,
        "accuracy": correct / n,
        "expected_calibration_error": expected_calibration_error(records),
        "observed_action_counts": observed_counts,
        "observed_action_rates": {action: observed_counts[action] / n for action in grm.ACTIONS},
        "mean_predicted_probability": {action: predicted_mass[action] / n for action in grm.ACTIONS},
        "probability_sum_max_abs_error": max_probability_sum_error,
        "illegal_mass_max": max_illegal_mass,
    }


def group_metrics(
    records: Sequence[Mapping[str, Any]],
    prior: Mapping[str, float],
    key: Callable[[Mapping[str, Any]], str],
) -> dict[str, Any]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        grouped.setdefault(str(key(record)), []).append(record)
    total = len(records)
    return {
        label: dict(summary_metrics(members, prior), **{"share": (len(members) / total) if total else 0.0})
        for label, members in sorted(grouped.items())
    }


def strata_block(records: Sequence[Mapping[str, Any]], prior: Mapping[str, float]) -> dict[str, Any]:
    """Explicit frequent / rare / exact-absent strata with their metric surface."""
    total = len(records)
    counts = {name: sum(1 for record in records if record["stratum"] == name) for name in STRATA}
    return {
        "definition": STRATA_DEFINITION,
        "minimum_support_frequent": FREQUENT_EXACT_MIN_SUPPORT,
        "minimum_support_rare": RARE_EXACT_MIN_SUPPORT,
        "counts": counts,
        "share": {name: (counts[name] / total) if total else 0.0 for name in STRATA},
        "metrics": {
            name: summary_metrics([record for record in records if record["stratum"] == name], prior)
            for name in STRATA
        },
    }


# ---------------------------------------------------------------------------
# classification of held-out decisions
# ---------------------------------------------------------------------------


def classify_row(row: Mapping[str, Any], index: FoldIndex) -> dict[str, Any]:
    """Stratum + provisional OOD gate decision of one held-out row."""
    key = exact_context_key(row)
    exact_support = index.exact_support.get(key, 0)
    levels = feature_levels(row)
    unseen_features = [
        block for block, level in sorted(levels.items()) if level not in index.feature_values[block]
    ]
    in_domain = not unseen_features
    if exact_support >= FREQUENT_EXACT_MIN_SUPPORT:
        stratum = STRATUM_FREQUENT_EXACT
    elif exact_support >= RARE_EXACT_MIN_SUPPORT:
        stratum = STRATUM_RARE_EXACT
    elif in_domain:
        stratum = STRATUM_EXACT_ABSENT_IN_DOMAIN
    else:
        stratum = STRATUM_EXACT_ABSENT_OUT_OF_DOMAIN
    return {
        "exact_context": key,
        "exact_support_in_fit_fold": exact_support,
        "feature_in_domain": in_domain,
        "unseen_features": unseen_features,
        "stratum": stratum,
        "gate_accepted": in_domain
        and exact_support >= PROVISIONAL_OOD_GATE_MIN_EXACT_SUPPORT,
    }


def _record_of(
    row: Mapping[str, Any],
    classification: Mapping[str, Any],
    response: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "hand_id": str(row.get("hand_id") or "").strip(),
        "observed": str(row.get("action") or "").strip().upper(),
        "probabilities": dict(response["probabilities"]),
        "masked_actions": list(response["masked_actions"]),
        "actor_position": grm.categorical_node("actor_position", row),
        "aggressor_position": grm.categorical_node("aggressor_position", row),
        "family": grm.categorical_node("family", row),
        "sizing_bucket": sizing_bucket(row),
        **classification,
    }


def gate_coverage(
    records: Sequence[Mapping[str, Any]],
    prior: Mapping[str, float],
) -> dict[str, Any]:
    """Coverage after the provisional OOD gate, plus the covered-row metrics."""
    accepted = [record for record in records if record["gate_accepted"]]
    n = len(records)
    in_domain = sum(1 for record in records if record["feature_in_domain"])
    exact_absent = sum(1 for record in records if record["exact_support_in_fit_fold"] == 0)
    return {
        "definition": PROVISIONAL_OOD_GATE_DEFINITION,
        "min_exact_support": PROVISIONAL_OOD_GATE_MIN_EXACT_SUPPORT,
        "requires_feature_in_domain": True,
        "n": n,
        "accepted": len(accepted),
        "rejected": n - len(accepted),
        "coverage": (len(accepted) / n) if n else 0.0,
        "feature_in_domain_rows": in_domain,
        "feature_out_of_domain_rows": n - in_domain,
        "exact_signature_absent_rows": exact_absent,
        "exact_signature_present_rows": n - exact_absent,
        "rejected_metrics": summary_metrics([r for r in records if not r["gate_accepted"]], prior),
        "accepted_metrics": summary_metrics(accepted, prior),
        "threshold_sensitivity": [
            {
                "min_exact_support": threshold,
                "coverage": (
                    sum(
                        1
                        for record in records
                        if record["feature_in_domain"]
                        and record["exact_support_in_fit_fold"] >= threshold
                    )
                    / n
                )
                if n
                else 0.0,
            }
            for threshold in PROVISIONAL_OOD_GATE_SENSITIVITY
        ],
    }


# ---------------------------------------------------------------------------
# one fold, one architecture
# ---------------------------------------------------------------------------


def _runtime_footprint(candidate: Mapping[str, Any]) -> dict[str, Any]:
    blocks = candidate["params"]["blocks"]
    return {
        "complexity_rank": RUNTIME_COMPLEXITY_RANK.get(str(candidate["architecture"]), 99),
        "block_count": len(blocks),
        "node_cells": sum(len(block["nodes"]) for block in blocks.values()),
        "interaction_cells": sum(
            len(blocks[name]["nodes"]) for name in grm.INTERACTION_BLOCK_NAMES if name in blocks
        ),
        "deterministic": True,
    }


def score_fold(
    fold: Fold,
    architecture: str,
    *,
    seed: int,
    config: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Fit ``architecture`` on the fit rows and score every held-out decision.

    Returns the raw per-row records (used to pool the folds) plus the fold-level
    public metrics.  Nothing is read outside ``fold.train_rows`` and
    ``fold.holdout_rows``; both come from the hand-disjoint split.
    """
    if architecture not in grm.ARCHITECTURES:
        raise TrainCrossValidationError(f"unknown architecture {architecture!r}")
    candidate = grm.fit(fold.train_rows, seed, architecture=architecture, config=config)
    prior = {action: float(candidate["params"]["prior"][action]) for action in grm.ACTIONS}

    records: list[dict[str, Any]] = []
    marginal_records: list[dict[str, Any]] = []
    for row in fold.holdout_rows:
        classification = classify_row(row, fold.fit_index)
        records.append(_record_of(row, classification, grm.predict(candidate, row)))
        if row.get("target_total_bb") is None:
            # No raise target is observed: the discrete choice is the same query.
            marginal_records.append(records[-1])
        else:
            without_target = dict(row)
            without_target.pop("target_total_bb", None)
            marginal_records.append(_record_of(row, classification, grm.predict(candidate, without_target)))

    public = fold_public_report(fold, records, marginal_records, prior, candidate)
    return {
        "fold": fold.index,
        "prior": prior,
        "records": records,
        "marginal_records": marginal_records,
        "public": public,
    }


def fold_public_report(
    fold: Fold,
    records: Sequence[Mapping[str, Any]],
    marginal_records: Sequence[Mapping[str, Any]],
    prior: Mapping[str, float],
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    """Fold-level public metrics (no raw records)."""
    return {
        "fold": fold.index,
        "canonical_payload_sha256": candidate["canonical_payload_sha256"],
        "selected_scale": candidate["params"]["regularization"]["scale"],
        "runtime": _runtime_footprint(candidate),
        "holdout_rows": len(records),
        "holdout_hands": len(fold.holdout_hands),
        "fit_rows": len(fold.train_rows),
        "fit_hands": len(fold.train_hands),
        "hand_overlap_with_fit": len(fold.train_hands & fold.holdout_hands),
        "metrics": summary_metrics(records, prior),
        "discrete_choice_only": summary_metrics(marginal_records, prior),
        "coverage_after_provisional_ood_gate": gate_coverage(records, prior),
        "strata": strata_block(records, prior),
    }


def _pool_fold_metrics(
    fold_results: Sequence[Mapping[str, Any]],
    architecture: str,
) -> dict[str, Any]:
    """Pool the per-fold records into the architecture-level report block."""
    records = [record for result in fold_results for record in result["records"]]
    marginal_records = [record for result in fold_results for record in result["marginal_records"]]
    prior = dict(fold_results[0]["prior"])
    publics = [result["public"] for result in fold_results]
    log_losses = [item["metrics"]["log_loss_bits_per_decision"] for item in publics]
    briers = [item["metrics"]["brier_score"] for item in publics]
    eces = [item["metrics"]["expected_calibration_error"]["ece"] for item in publics]
    return {
        "architecture": architecture,
        "out_of_fold": summary_metrics(records, prior),
        "discrete_choice_only": summary_metrics(marginal_records, prior),
        "by_fold": publics,
        "stability": {
            "fold_log_loss_bits_per_decision": {
                "mean": _mean(log_losses),
                "min": min(log_losses),
                "max": max(log_losses),
                "stddev": _stddev(log_losses),
            },
            "fold_brier_score": {
                "mean": _mean(briers),
                "min": min(briers),
                "max": max(briers),
                "stddev": _stddev(briers),
            },
            "fold_expected_calibration_error": {
                "mean": _mean(eces),
                "min": min(eces),
                "max": max(eces),
                "stddev": _stddev(eces),
            },
            "fold_log_loss_stddev": _stddev(log_losses),
            "folds": len(fold_results),
        },
        "by_actor_position": group_metrics(records, prior, lambda record: record["actor_position"]),
        "by_aggressor_position": group_metrics(records, prior, lambda record: record["aggressor_position"]),
        "by_family": group_metrics(records, prior, lambda record: record["family"]),
        "by_sizing_bucket": group_metrics(records, prior, lambda record: record["sizing_bucket"]),
        "coverage_after_provisional_ood_gate": gate_coverage(records, prior),
        "strata": strata_block(records, prior),
        "runtime": fold_results[0]["public"]["runtime"],
    }


# ---------------------------------------------------------------------------
# selection
# ---------------------------------------------------------------------------


def _step(name: str, metric: str, values: Mapping[str, float], tolerance: float) -> dict[str, Any]:
    best = min(values.values())
    kept = sorted(item for item in values if values[item] <= best + float(tolerance))
    return {
        "criterion": name,
        "metric": metric,
        "tolerance": float(tolerance),
        "best": best,
        "best_architectures": sorted(item for item in values if values[item] == best),
        "kept": kept,
        "eliminated": sorted(item for item in values if item not in kept),
    }


def select_architecture(architectures: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Apply the preregistered out-of-fold-only decision procedure."""
    criteria = PREREGISTERED_SELECTION_CRITERIA

    def value(architecture: str, path: str) -> float:
        node: Any = architectures[architecture]
        for part in path.split("."):
            node = node[part]
        return float(node)

    first = criteria["steps"][0]["metric"]
    survivors = sorted(architectures)
    trace: list[dict[str, Any]] = []
    values = {architecture: value(architecture, first) for architecture in survivors}
    step = _step("out_of_fold_performance", first, values, criteria["steps"][0]["tolerance"])
    trace.append(dict(step, step=1, survivors_before=sorted(survivors)))
    survivors = [architecture for architecture in survivors if architecture in step["kept"]]

    for step_spec in criteria["steps"][1:]:
        if len(survivors) <= 1:
            break
        metric = step_spec["metric"]
        if metric == "architecture":
            kept = [sorted(survivors)[0]]
            trace.append(
                {
                    "step": step_spec["step"],
                    "criterion": step_spec["name"],
                    "metric": metric,
                    "tolerance": 0.0,
                    "best": min(survivors),
                    "best_architectures": [min(survivors)],
                    "kept": kept,
                    "eliminated": [item for item in survivors if item not in kept],
                    "survivors_before": sorted(survivors),
                }
            )
            survivors = kept
            continue
        values = {architecture: value(architecture, metric) for architecture in survivors}
        applied = _step(step_spec["name"], metric, values, step_spec["tolerance"])
        trace.append(dict(applied, step=step_spec["step"], survivors_before=sorted(survivors)))
        survivors = [architecture for architecture in survivors if architecture in applied["kept"]]

    ranking = sorted(
        architectures,
        key=lambda architecture: (
            value(architecture, "out_of_fold.log_loss_bits_per_decision"),
            value(architecture, "out_of_fold.expected_calibration_error.ece"),
            value(architecture, "out_of_fold.brier_score"),
            value(architecture, "stability.fold_log_loss_stddev"),
            value(architecture, "runtime.complexity_rank"),
            architecture,
        ),
    )
    selected = min(survivors) if survivors else ranking[0]
    evidence = {
        architecture: {
            "out_of_fold_log_loss_bits_per_decision": architectures[architecture]["out_of_fold"][
                "log_loss_bits_per_decision"
            ],
            "out_of_fold_baseline_log_loss_bits_per_decision": architectures[architecture]["out_of_fold"][
                "baseline_log_loss_bits_per_decision"
            ],
            "out_of_fold_gain_bits_per_decision": architectures[architecture]["out_of_fold"][
                "gain_bits_per_decision"
            ],
            "out_of_fold_brier_score": architectures[architecture]["out_of_fold"]["brier_score"],
            "out_of_fold_expected_calibration_error": architectures[architecture]["out_of_fold"][
                "expected_calibration_error"
            ]["ece"],
            "fold_log_loss_stddev": architectures[architecture]["stability"]["fold_log_loss_stddev"],
            "coverage_after_provisional_ood_gate": architectures[architecture][
                "coverage_after_provisional_ood_gate"
            ]["coverage"],
            "runtime_complexity_rank": architectures[architecture]["runtime"]["complexity_rank"],
            "runtime_node_cells": architectures[architecture]["runtime"]["node_cells"],
        }
        for architecture in sorted(architectures)
    }
    return {
        "criteria": criteria,
        "trace": trace,
        "ranking": ranking,
        "selected": selected,
        "evidence": evidence,
        "justification": _justification(selected, ranking, evidence),
        "evidence_basis": "out_of_fold_holdout_only",
        "consumed_splits": list(CONSUMED_SPLITS),
        "validation_consumed": False,
        "test_consumed": False,
    }


def _justification(selected: str, ranking: Sequence[str], evidence: Mapping[str, Mapping[str, Any]]) -> str:
    chosen = evidence[selected]
    runner_up = evidence[ranking[1]] if len(ranking) > 1 else None
    text = (
        f"selected `{selected}` from data the architecture was never fitted on: pooled out-of-fold "
        f"multiclass log loss {chosen['out_of_fold_log_loss_bits_per_decision']:.6f} bits/decision "
        f"(baseline {chosen['out_of_fold_baseline_log_loss_bits_per_decision']:.6f}, gain "
        f"{chosen['out_of_fold_gain_bits_per_decision']:.6f}), ECE "
        f"{chosen['out_of_fold_expected_calibration_error']:.6f}, Brier "
        f"{chosen['out_of_fold_brier_score']:.6f}, fold-to-fold log-loss stddev "
        f"{chosen['fold_log_loss_stddev']:.6f}, runtime complexity rank "
        f"{chosen['runtime_complexity_rank']} ({chosen['runtime_node_cells']} node cells)"
    )
    if runner_up is not None:
        text += (
            f"; runner-up "
            f"`{ranking[1]}` reached {runner_up['out_of_fold_log_loss_bits_per_decision']:.6f} bits/decision, "
            f"ECE {runner_up['out_of_fold_expected_calibration_error']:.6f}, stddev "
            f"{runner_up['fold_log_loss_stddev']:.6f}, rank {runner_up['runtime_complexity_rank']}"
        )
    return text + (
        ". The decision used TRAIN out-of-fold evidence only; VALIDATION and TEST were not consumed "
        "(validation_consumed=false, test_consumed=false)."
    )


# ---------------------------------------------------------------------------
# top-level report
# ---------------------------------------------------------------------------


def read_train_rows(dataset: str | Path = DEFAULT_DATASET, *, stride: int = 1) -> list[dict[str, Any]]:
    """Read the TRAIN rows only; the loader fails closed on TEST."""
    rows = grm.read_dataset_rows(dataset, splits=CONSUMED_SPLITS)
    stride = int(stride)
    if stride < 1:
        raise TrainCrossValidationError("stride must be >= 1")
    if stride > 1:
        rows = rows[::stride]
    if not rows:
        raise TrainCrossValidationError("no TRAIN rows selected")
    return rows


def run_cross_validation(
    rows: Iterable[Mapping[str, Any]],
    *,
    folds: int = CV_FOLDS,
    seed: int = CV_SEED,
    architectures: Sequence[str] = grm.ARCHITECTURES,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Hand-grouped cross-validation of every architecture on TRAIN rows."""
    architectures = list(architectures)
    if not architectures:
        raise TrainCrossValidationError("no architecture to cross-validate")
    for architecture in architectures:
        if architecture not in grm.ARCHITECTURES:
            raise TrainCrossValidationError(f"unknown architecture {architecture!r}")
    effective_config = grm.make_config(**dict(config)) if isinstance(config, Mapping) else grm.make_config()
    split = grouped_folds(rows, folds=folds, seed=seed)
    per_architecture: dict[str, Any] = {}
    for architecture in architectures:
        results = [
            score_fold(fold, architecture, seed=seed, config=config) for fold in split
        ]
        per_architecture[architecture] = _pool_fold_metrics(results, architecture)
    return {
        "protocol": {
            "kind": "hand_grouped_k_fold_cross_validation",
            "main_split": MAIN_SPLIT,
            "consumed_splits": list(CONSUMED_SPLITS),
            "forbidden_splits": list(FORBIDDEN_SPLITS),
            "group_key": "hand_id",
            "folds": int(folds),
            "seed": int(seed),
            "fold_assignment": f"int(stable_hash('grm-cv/{int(seed)}/<hand_id>')[:8], 16) % {int(folds)}",
            "metrics": {
                "log_loss_bits_per_decision": "mean -log2 P(observed action), base-2 bits per decision",
                "baseline_log_loss_bits_per_decision": "same loss under the fit-fold action prior",
                "brier_score": "mean sum over the four actions of (P(action) - 1[observed])^2",
                "accuracy": "mean arg-max agreement",
                "expected_calibration_error": CALIBRATION_DEFINITION,
                "coverage": PROVISIONAL_OOD_GATE_DEFINITION,
            },
            "sizing_mode": "observed_where_available",
            "model_config": effective_config,
            "model_config_source": "explicit" if isinstance(config, Mapping) else "library_default",
            "discrete_choice_only": (
                "secondary figure: the same fold scored without the conditional sizing channel "
                "(observed raise target removed), i.e. the discrete-choice core alone"
            ),
            "no_leak": no_leak_proof(split),
            "preregistered_selection_criteria": PREREGISTERED_SELECTION_CRITERIA,
        },
        "folds": [fold.summary() for fold in split],
        "architectures": per_architecture,
        "selection": select_architecture(per_architecture),
    }


def build_report(
    dataset: str | Path = DEFAULT_DATASET,
    *,
    folds: int = CV_FOLDS,
    seed: int = CV_SEED,
    architectures: Sequence[str] = grm.ARCHITECTURES,
    config: Mapping[str, Any] | None = None,
    stride: int = 1,
) -> dict[str, Any]:
    """Read TRAIN, run the cross-validation and return the persistable report."""
    dataset_path = Path(dataset).resolve()
    rows = read_train_rows(dataset_path, stride=stride)
    core = run_cross_validation(
        rows, folds=folds, seed=seed, architectures=architectures, config=config
    )
    hands = {str(row["hand_id"]).strip() for row in rows}
    return {
        "schema": SCHEMA,
        "kind": "train_only_hand_grouped_cross_validation",
        "generated_by": _relative(Path(__file__)),
        "module_sha256": sha256_file(Path(__file__)),
        "model_module": {
            "path": _relative(Path(grm.__file__)),
            "sha256": sha256_file(Path(grm.__file__)),
            "architectures": list(grm.ARCHITECTURES),
        },
        "scope": {
            "dataset": _relative(dataset_path),
            "dataset_sha256": sha256_file(dataset_path),
            "dataset_bytes": dataset_path.stat().st_size,
            "split": MAIN_SPLIT,
            "rows": len(rows),
            "hands": len(hands),
            "row_stride": int(stride),
            "validation_consumed": False,
            "test_consumed": False,
            "cross_validated_rows": sum(fold["holdout_rows"] for fold in core["folds"]),
        },
        **core,
    }


def persisted_report_text(report: Mapping[str, Any]) -> str:
    return json.dumps(_finalize(report), sort_keys=True, indent=2, ensure_ascii=True) + "\n"


def write_report(report: Mapping[str, Any], path: str | Path = DEFAULT_OUTPUT) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(persisted_report_text(report), encoding="utf-8")
    return target


def self_check(seed: int = CV_SEED) -> dict[str, Any]:
    """Fast, dataset-independent end-to-end check (hand-grouped synthetic rows)."""
    rows = []
    for index, row in enumerate(grm.synthetic_rows(900, seed)):
        rows.append(dict(row, hand_id=f"hand-{index % 120:04d}"))
    report = run_cross_validation(
        rows,
        folds=3,
        seed=seed,
        config=grm.make_config(tuning_max_rows=200),
    )
    return {
        "schema": SELF_CHECK_SCHEMA,
        "rows": len(rows),
        "hands": len({row["hand_id"] for row in rows}),
        "folds": report["protocol"]["folds"],
        "no_leak": report["protocol"]["no_leak"],
        "ranking": report["selection"]["ranking"],
        "selected": report["selection"]["selected"],
        "validation_consumed": report["selection"]["validation_consumed"],
        "test_consumed": report["selection"]["test_consumed"],
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="#421 T4 - TRAIN-only hand-grouped CV of the response architectures"
    )
    parser.add_argument("--self-check", action="store_true", help="run the dependency-free smoke check")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--folds", type=int, default=CV_FOLDS)
    parser.add_argument("--seed", type=int, default=CV_SEED)
    parser.add_argument("--stride", type=int, default=1, help="deterministic TRAIN row stride (fast runs)")
    parser.add_argument("--architectures", nargs="+", default=list(grm.ARCHITECTURES))
    parser.add_argument("--tuning-max-rows", type=int, default=None)
    parser.add_argument("--print", dest="print_only", action="store_true", help="print the report, do not write it")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.self_check:
        print(json.dumps(_finalize(self_check(args.seed)), sort_keys=True, indent=2))
        return 0
    config = (
        grm.make_config(tuning_max_rows=args.tuning_max_rows)
        if args.tuning_max_rows is not None
        else None
    )
    report = build_report(
        args.dataset,
        folds=args.folds,
        seed=args.seed,
        architectures=args.architectures,
        config=config,
        stride=args.stride,
    )
    text = persisted_report_text(report)
    if args.print_only:
        sys.stdout.write(text)
        return 0
    target = write_report(report, args.out)
    print(
        json.dumps(
            {
                "report": _relative(target),
                "rows": report["scope"]["rows"],
                "folds": report["protocol"]["folds"],
                "selected": report["selection"]["selected"],
            },
            sort_keys=True,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

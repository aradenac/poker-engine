#!/usr/bin/env python3
"""#423 T2 -- in-fold fitted / out-of-fold evaluated calibration of the response model.

The #421 generalized response model is a *distributional* estimator: its
out-of-fold TRAIN cross-validation reports an expected calibration error (ECE)
of ``0.024187`` for the selected architecture while the frozen active reference
sits at ``0.014743``.  #423 therefore needs a post-hoc calibration stage that
is chosen on TRAIN evidence only.  This module is that stage.

Scientific contract
-------------------

* **Fit strictly in-fold.**  A fold's calibration is fitted from the frozen
  cross-validation model's *own predictions on the fold's fit rows*
  (``provenance = "in_fold_fit"``).  The held-out fold is never passed to a
  fitting routine; :func:`fold_calibration` scores it separately.
* **Evaluate out-of-fold.**  Every reported number -- log loss, Brier, ECE and
  the per-stratum before/after table -- is computed on the held-out fold of the
  same hand-grouped split the #421 cross-validation uses, so no metric reuses a
  row a calibration (or a model) was fitted on.
* **TRAIN only.**  The module consumes ``TRAIN`` decisions exclusively.
  ``VALIDATION`` and ``TEST`` are refused at runtime (:func:`assert_train_only`)
  and the module has no holdout loader at all: it reads the dataset through
  :func:`tools.training.evaluate_generalized_response_cv.read_train_rows`, which
  fails closed on ``TEST`` and only ever requests ``TRAIN``.  The persisted
  report proves the refusal instead of asserting it.
* **Isotonic is gated.**  Isotonic regression is the only non-parametric member
  of the comparison and it is admitted **only** when the in-fold calibration
  sample clears the preregistered support floor
  (:data:`ISOTONIC_MINIMUM_SUPPORT`).  Below the floor the method is refused
  and the documented fallback (retain the best *admissible* method, never an
  unverified isotonic map) applies.  ``strict_isotonic=True`` turns the refusal
  into a hard error, so both the fail-closed and the documented-fallback
  behaviours are exercisable.
* **Byte-reproducible.**  The persisted report carries no timestamp, no wall
  clock and no random number generator; it is written with sorted keys and
  recursively rounded floats, and it is pinned by a ``.sha256`` sidecar.

Harness integration
-------------------

This module *is* the calibration stage of the #421/#423 cross-validation
harness (:mod:`tools.training.evaluate_generalized_response_cv`): it imports the
harness's hand-grouped split (:func:`...grouped_folds`), its strata
classifier (:func:`...classify_row`), its frozen metric definitions
(:func:`...summary_metrics` / :func:`...expected_calibration_error`) and its
canonical ``TRAIN`` loader.  The report records the harness module digest, the
fold assignment, the machine-checked no-leak proof, and -- when the harness
report is present -- the absolute delta between this module's *uncalibrated*
out-of-fold metric surface and the harness's own, which is what makes the
"before" column auditable against #421's published numbers.

The harness module itself is deliberately **not modified**: its digest is
pinned by the frozen #421 evidence (``TRAIN_CV_REPORT.module_sha256``, the
``FROZEN_VALIDATION_PROTOCOL`` evidence list, ``ARTIFACTS.json`` and the #423
``HYBRID_ROUTER_SPEC`` evidence bindings), and #423 must not rewrite frozen
#421 bytes.  Integration therefore happens by consumption, and is proved by
tests that compare harness outputs with this module's outputs.

Only the Python standard library is used.
"""
from __future__ import annotations

import argparse
import ast
import bisect
import hashlib
import json
import math
import sys
from array import array
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.preflop import generalized_response_model as grm  # noqa: E402
from tools.training import evaluate_generalized_response_cv as harness  # noqa: E402

SCHEMA = "poker-generalized-response-calibration/v1"
REPORT_SCHEMA = "poker-generalized-response-calibration-report/v1"
SELF_CHECK_SCHEMA = "poker-generalized-response-calibration-self-check/v1"

HERE = ROOT / "analysis/issue423_hybrid_router"
REPORT_NAME = "GENERALIZED_CALIBRATION_REPORT.json"
REPORT_PATH = HERE / REPORT_NAME
DIGEST_PATH = HERE / "GENERALIZED_CALIBRATION_REPORT.sha256"

DEFAULT_DATASET = grm.DEFAULT_DATASET
HARNESS_REPORT_PATH = ROOT / "analysis/issue421_generalized_response/TRAIN_CV_REPORT.json"

#: The calibration consumes one split only.  ``VALIDATION`` is not "not needed"
#: here: recalibrating on the historical holdout is a data-snooping defect, so
#: the split is explicitly refused rather than merely unused.
MAIN_SPLIT = "TRAIN"
CONSUMED_SPLITS = ("TRAIN",)
ALLOWED_SPLITS = ("TRAIN",)
REFUSED_SPLITS = ("VALIDATION", "TEST")
FORBIDDEN_SPLITS = grm.FORBIDDEN_SPLITS

#: Compared calibration families.  ``uncalibrated`` is the baseline column that
#: makes "after" interpretable; it is evaluated but never fitted.
METHOD_UNCALIBRATED = "uncalibrated"
METHOD_TEMPERATURE = "temperature_scaling"
METHOD_VECTOR = "vector_scaling"
METHOD_ISOTONIC = "isotonic"
COMPARED_METHODS = (METHOD_TEMPERATURE, METHOD_VECTOR, METHOD_ISOTONIC)
EVALUATED_METHODS = (METHOD_UNCALIBRATED,) + COMPARED_METHODS

#: Predeclared runtime complexity of each family (0 = no calibration at all).
METHOD_COMPLEXITY_RANK: dict[str, int] = {
    METHOD_UNCALIBRATED: 0,
    METHOD_TEMPERATURE: 1,
    METHOD_VECTOR: 2,
    METHOD_ISOTONIC: 3,
}

#: Deterministic in-fold calibration sample.  The whole fit fold is ~75k rows;
#: the calibration is fitted on a deterministic stride sample of it so the
#: parametric optimisers stay cheap while the isotonic support statistics stay
#: representative.  The rule is preregistered, deterministic and in-fold only.
CALIBRATION_FIT_MAX_ROWS = 12000

#: A parametric fit needs more than a handful of rows to mean anything.
PARAMETRIC_MINIMUM_FIT_ROWS = 100

#: Preregistered isotonic support floor.  Isotonic regression fits a monotone
#: step map per action class; with too few positive labels -- or too few
#: distinct probability levels -- that map memorises the sample instead of
#: calibrating it, so it is refused instead of fitted.
ISOTONIC_MINIMUM_SUPPORT: dict[str, int] = {
    "fit_rows": 500,
    "class_positives": 50,
    "class_observations": 100,
    "distinct_probability_levels": 5,
}

#: Deterministic temperature search: a fixed log-spaced grid plus a fixed
#: golden-section refinement inside the best bracket (no RNG anywhere).
TEMPERATURE_GRID: tuple[float, ...] = tuple(
    round(0.25 * (8.0 / 0.25) ** (index / 24.0), 6) for index in range(25)
)
TEMPERATURE_REFINE_ITERATIONS = 24
TEMPERATURE_REFINE_RATIO = (math.sqrt(5.0) - 1.0) / 2.0

#: Deterministic vector-scaling fit: convex multinomial log loss in the
#: per-class (scale, bias) pair, minimised by fixed-iteration gradient descent
#: from the identity start, so the identity is always a feasible point.
VECTOR_SCALING_MAX_FIT_ROWS = 4000
VECTOR_SCALING_ITERATIONS = 150
VECTOR_SCALING_LEARNING_RATE = 1.0
VECTOR_SCALING_L2 = 1e-4
LOGIT_CLIP = 60.0

#: Isotonic maps are persisted inline when they stay small; above the cap the
#: report keeps the digest and the shape instead of a megabyte of knots.
ISOTONIC_MAX_INLINE_KNOTS = 512

#: Preregistered method-selection tolerances (out-of-fold TRAIN evidence only).
SELECTION_LOGLOSS_TOLERANCE_BITS = 0.005
SELECTION_ECE_TOLERANCE = 0.0005
SELECTION_BRIER_TOLERANCE = 0.001

#: Tolerance used to certify that this module's *uncalibrated* out-of-fold
#: metric surface reproduces the harness's published one.  The harness report
#: persists its metrics rounded to six decimals, so the bound is the
#: corresponding rounding step; the test suite additionally compares a fresh
#: harness run with the calibration run at full precision (nine decimals).
HARNESS_CONSISTENCY_TOLERANCE = 1e-6
HARNESS_CONSISTENCY_PRECISION = 6

CALIBRATION_FIT_RULE = (
    "fitted on the frozen cross-validation model's own predictions on the fold's fit rows "
    "(provenance=in_fold_fit); the in-fold calibration sample is the canonically ordered fit "
    f"fold walked with stride ceil(fit_rows/{CALIBRATION_FIT_MAX_ROWS}) (or the whole fit fold "
    "when it is smaller than the cap)"
)

EVALUATION_RULE = (
    "every reported metric is computed on the held-out fold of the same hand-grouped split the "
    "architecture was fitted on (provenance=out_of_fold_holdout)"
)

TEMPERATURE_DEFINITION = (
    "q(a) proportional to p(a)^(1/T) restricted to the legal actions, T fitted in-fold by "
    "minimising the in-fold multiclass log loss over a fixed log-spaced grid refined by a fixed "
    "golden-section search"
)

VECTOR_DEFINITION = (
    "q(a) proportional to exp(scale(a) * log p(a) + bias(a)) restricted to the legal actions; the "
    "eight parameters start at the identity (scale=1, bias=0) and are fitted in-fold by "
    f"{VECTOR_SCALING_ITERATIONS} fixed gradient-descent steps (learning rate "
    f"{VECTOR_SCALING_LEARNING_RATE}, L2 {VECTOR_SCALING_L2} towards the identity), a deterministic "
    "descent on a convex objective"
)

ISOTONIC_DEFINITION = (
    "per action class, a monotone map from the predicted probability to the observed frequency "
    "(pool-adjacent-violators knots read by linear interpolation, extended towards the identity "
    "anchors (0, 0) and (1, 1) outside the fitted range so a probability outside the in-fold knots "
    "is never mapped to a fabricated extreme), renormalised across the legal actions; only fitted "
    "when the preregistered support floor is met"
)

ISOTONIC_ADMISSION_RULE = (
    "isotonic is admitted iff the in-fold calibration sample has at least "
    f"{ISOTONIC_MINIMUM_SUPPORT['fit_rows']} rows, every action class has at least "
    f"{ISOTONIC_MINIMUM_SUPPORT['class_positives']} observed positives and at least "
    f"{ISOTONIC_MINIMUM_SUPPORT['class_observations']} decisions where it was legal, and every "
    f"class shows at least {ISOTONIC_MINIMUM_SUPPORT['distinct_probability_levels']} distinct "
    "predicted probabilities"
)

ISOTONIC_FALLBACK_RULE = (
    "a refused isotonic is never applied and never scored: the refusal is persisted verbatim and "
    "the retained method is selected among the admissible members of the comparison plus the "
    "uncalibrated baseline"
)

PREREGISTERED_SELECTION_CRITERIA: dict[str, Any] = {
    "preregistered": True,
    "registered_before_evaluation": True,
    "evidence_basis": "out_of_fold_holdout_only",
    "consumed_splits": list(CONSUMED_SPLITS),
    "validation_consumed": False,
    "test_consumed": False,
    "direction": "lower_is_better",
    "steps": [
        {
            "step": 1,
            "name": "admissibility",
            "metric": "admissibility.isotonic_support_gate",
            "tolerance": 0.0,
            "rule": "drop every method whose preregistered support gate refused it (isotonic)",
        },
        {
            "step": 2,
            "name": "log_loss_non_degradation",
            "metric": "out_of_fold.log_loss_bits_per_decision",
            "tolerance": SELECTION_LOGLOSS_TOLERANCE_BITS,
            "rule": (
                "keep every admissible method whose out-of-fold log loss stays within the "
                "preregistered tolerance of the best admissible family, so a method can never be "
                "retained by improving calibration at the cost of the predictive distribution"
            ),
        },
        {
            "step": 3,
            "name": "calibration_quality",
            "metric": "out_of_fold.expected_calibration_error.ece",
            "tolerance": SELECTION_ECE_TOLERANCE,
            "rule": "among the survivors, keep the methods within the preregistered ECE tolerance of the best",
        },
        {
            "step": 4,
            "name": "brier",
            "metric": "out_of_fold.brier_score",
            "tolerance": SELECTION_BRIER_TOLERANCE,
            "rule": "among the survivors, keep the methods within the Brier tolerance of the best",
        },
        {
            "step": 5,
            "name": "simplicity",
            "metric": "runtime.complexity_rank",
            "tolerance": 0.0,
            "rule": "among the survivors, keep the lowest predeclared complexity rank",
        },
    ],
    "fallback": ISOTONIC_FALLBACK_RULE,
}

#: Symbols that would indicate a holdout (VALIDATION/TEST) read.  The generator
#: must use none of them; the scan runs at build time and in tests.
HOLDOUT_LOADER_SYMBOLS = (
    "read_dataset_rows",
    "load_validation_records",
    "validation_records",
    "validation_hand_ids",
    "VALIDATION_HANDS",
    "load_holdout",
    "holdout_records",
    "build_validation_decisions",
    "load_test_records",
    "TEST_HANDS",
    "test_hand_ids",
)


class CalibrationError(RuntimeError):
    """Fail-closed error for the generalized response calibration surface."""


# ---------------------------------------------------------------------------
# small numeric helpers
# ---------------------------------------------------------------------------


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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


def _canonical(value: Any) -> str:
    return json.dumps(_finalize(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


# ---------------------------------------------------------------------------
# split guards: TRAIN only, refuse VALIDATION and TEST
# ---------------------------------------------------------------------------


def record_split(record: Mapping[str, Any]) -> str:
    return str(record.get("split") or "").strip().upper()


def assert_train_only(records: Iterable[Mapping[str, Any]], *, context: str) -> int:
    """Fail closed on any record whose split is not ``TRAIN``.

    ``VALIDATION`` is refused as loudly as ``TEST``: the historical holdout is
    the split whose numbers #423 must not tune against, so a recalibration that
    touched it would be a data-snooping defect rather than a missing feature.
    """
    checked = 0
    for index, record in enumerate(records):
        split = record_split(record)
        if split in REFUSED_SPLITS:
            raise CalibrationError(
                f"{context} refuses split {split}: the calibration consumes "
                f"{list(CONSUMED_SPLITS)} only"
            )
        if split not in ALLOWED_SPLITS:
            raise CalibrationError(
                f"{context} requires an explicit TRAIN record at position {index}, got {split!r}"
            )
        checked += 1
    return checked


def verify_no_holdout_access(source: str | None = None) -> dict[str, Any]:
    """Static proof that this module names no holdout loader.

    Mirrors the #423 spec generator's guard: the calibration stage must not be
    *able* to read ``VALIDATION``/``TEST``, and the property is checked on the
    module source rather than promised in a comment.
    """
    text = Path(__file__).read_text(encoding="utf-8") if source is None else source
    tree = ast.parse(text)
    hits: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in HOLDOUT_LOADER_SYMBOLS:
            hits.append({"line": node.lineno, "symbol": node.attr, "kind": "attribute"})
        elif isinstance(node, ast.Name) and node.id in HOLDOUT_LOADER_SYMBOLS:
            hits.append({"line": node.lineno, "symbol": node.id, "kind": "name"})
        elif isinstance(node, ast.keyword) and node.arg == "splits":
            for literal in ast.walk(node.value):
                if isinstance(literal, ast.Constant) and literal.value in REFUSED_SPLITS:
                    hits.append(
                        {"line": literal.lineno, "symbol": str(literal.value), "kind": "splits_keyword"}
                    )
    return {
        "result": "PASS" if not hits else "FAIL",
        "hits": hits,
        "scanned_module": _relative(Path(__file__)),
        "consumed_splits": list(CONSUMED_SPLITS),
        "allowed_splits": list(ALLOWED_SPLITS),
        "refused_splits": list(REFUSED_SPLITS),
        "forbidden_splits": list(FORBIDDEN_SPLITS),
    }


# ---------------------------------------------------------------------------
# probability algebra (masked, renormalised, exactly closed)
# ---------------------------------------------------------------------------


def probability_vector(probabilities: Mapping[str, Any]) -> list[float]:
    values: list[float] = []
    for action in grm.ACTIONS:
        try:
            value = float(probabilities.get(action, 0.0) or 0.0)
        except (TypeError, ValueError):
            value = 0.0
        if not math.isfinite(value) or value < 0.0:
            value = 0.0
        values.append(value)
    return values


def masked_actions(record: Mapping[str, Any]) -> frozenset[str]:
    raw = record.get("masked_actions") or ()
    return frozenset(str(action).strip().upper() for action in raw)


def normalize_vector(values: Sequence[float], masked: frozenset[str] = frozenset()) -> list[float]:
    """Mask, normalise and exactly close the legal distribution.

    The final step mirrors ``generalized_response_model._normalize_legal``: the
    last legal action absorbs the residual so ``sum(probabilities) == 1.0`` in
    IEEE-754 arithmetic, which keeps the calibrated distribution in the same
    probability space the runtime contract expects.
    """
    legal = [action for action in grm.ACTIONS if action not in masked]
    if not legal:
        raise CalibrationError("a record cannot mask every action")
    probability = {action: 0.0 for action in grm.ACTIONS}
    total = 0.0
    for index, action in enumerate(grm.ACTIONS):
        if action in masked:
            continue
        value = float(values[index])
        if not math.isfinite(value) or value < 0.0:
            value = 0.0
        probability[action] = value
        total += value
    if total <= grm.EPS:
        share = 1.0 / len(legal)
        for action in legal:
            probability[action] = share
        probability[legal[-1]] = max(0.0, 1.0 - share * (len(legal) - 1))
        return [probability[action] for action in grm.ACTIONS]
    for action in legal:
        probability[action] /= total
    others = sum(probability[action] for action in legal[:-1])
    probability[legal[-1]] = max(0.0, 1.0 - others)
    return [probability[action] for action in grm.ACTIONS]


def vector_to_probabilities(values: Sequence[float]) -> dict[str, float]:
    rounded = [round(float(value), 12) for value in values]
    probabilities = dict(zip(grm.ACTIONS, rounded, strict=True))
    # Keep the same exact closure the model applies before rounding.
    residual = 1.0 - sum(probabilities.values())
    if abs(residual) > 1e-12:
        last = probabilities[grm.ACTIONS[-1]] + residual
        probabilities[grm.ACTIONS[-1]] = round(last, 12)
    return probabilities


def _log_probabilities(values: Sequence[float]) -> list[float]:
    return [math.log(max(float(value), grm.PROBABILITY_FLOOR)) for value in values]


def _observed_index(record: Mapping[str, Any]) -> int:
    action = str(record.get("observed") or "").strip().upper()
    if action not in grm.ACTION_INDEX:
        raise CalibrationError(f"record observed action outside the response space: {action!r}")
    return grm.ACTION_INDEX[action]


# ---------------------------------------------------------------------------
# temperature scaling
# ---------------------------------------------------------------------------


def apply_temperature(
    probabilities: Sequence[float],
    temperature: float,
    masked: frozenset[str] = frozenset(),
) -> list[float]:
    temperature = max(float(temperature), 1e-6)
    values = [
        0.0 if grm.ACTIONS[index] in masked else float(probabilities[index]) ** (1.0 / temperature)
        for index in range(len(grm.ACTIONS))
    ]
    return normalize_vector(values, masked)


def _temperature_nll(prepared: Sequence[tuple[list[float], tuple[bool, ...], int]], temperature: float) -> float:
    inverse = 1.0 / max(float(temperature), 1e-6)
    total = 0.0
    for logprobabilities, mask, observed in prepared:
        maximum = -math.inf
        for index in range(len(grm.ACTIONS)):
            if mask[index]:
                continue
            value = logprobabilities[index] * inverse
            if value > maximum:
                maximum = value
        denominator = 0.0
        for index in range(len(grm.ACTIONS)):
            if mask[index]:
                continue
            denominator += math.exp(logprobabilities[index] * inverse - maximum)
        total -= logprobabilities[observed] * inverse - maximum - math.log(denominator)
    return total / len(prepared)


def _prepare(records: Sequence[Mapping[str, Any]]) -> list[tuple[list[float], tuple[bool, ...], int]]:
    prepared: list[tuple[list[float], tuple[bool, ...], int]] = []
    for record in records:
        mask = masked_actions(record)
        prepared.append(
            (
                _log_probabilities(probability_vector(record["probabilities"])),
                tuple(action in mask for action in grm.ACTIONS),
                _observed_index(record),
            )
        )
    return prepared


def fit_temperature(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Fit one temperature on the in-fold calibration sample."""
    assert_train_only(records, context="fit_temperature")
    if len(records) < PARAMETRIC_MINIMUM_FIT_ROWS:
        return {
            "method": METHOD_TEMPERATURE,
            "admitted": False,
            "params": None,
            "refusal": {
                "reason": "INSUFFICIENT_FIT_ROWS",
                "observed_fit_rows": len(records),
                "minimum_fit_rows": PARAMETRIC_MINIMUM_FIT_ROWS,
                "fallback": ISOTONIC_FALLBACK_RULE,
            },
        }
    prepared = _prepare(records)
    grid = list(TEMPERATURE_GRID)
    losses = [_temperature_nll(prepared, temperature) for temperature in grid]
    best = min(range(len(grid)), key=lambda index: (losses[index], index))
    left = grid[max(best - 1, 0)]
    right = grid[min(best + 1, len(grid) - 1)]
    a, b = left, right
    c = b - TEMPERATURE_REFINE_RATIO * (b - a)
    d = a + TEMPERATURE_REFINE_RATIO * (b - a)
    for _ in range(TEMPERATURE_REFINE_ITERATIONS):
        if _temperature_nll(prepared, c) <= _temperature_nll(prepared, d):
            b = d
        else:
            a = c
        c = b - TEMPERATURE_REFINE_RATIO * (b - a)
        d = a + TEMPERATURE_REFINE_RATIO * (b - a)
    temperature = _round(max((a + b) / 2.0, 1e-3), 6)
    params = {"temperature": temperature}
    return {
        "method": METHOD_TEMPERATURE,
        "admitted": True,
        "params": params,
        "params_sha256": grm.stable_hash(_finalize(params)),
        "fit_rows": len(records),
        "in_fold_log_loss": {
            "uncalibrated": _round(_temperature_nll(prepared, 1.0), 9),
            "fitted": _round(_temperature_nll(prepared, temperature), 9),
            "grid_best": _round(losses[best], 9),
        },
        "refusal": None,
    }


# ---------------------------------------------------------------------------
# vector scaling
# ---------------------------------------------------------------------------


def apply_vector_scaling(
    probabilities: Sequence[float],
    scales: Sequence[float],
    biases: Sequence[float],
    masked: frozenset[str] = frozenset(),
) -> list[float]:
    values = [0.0] * len(grm.ACTIONS)
    for index, action in enumerate(grm.ACTIONS):
        if action in masked:
            continue
        logit = float(scales[index]) * math.log(max(float(probabilities[index]), grm.PROBABILITY_FLOOR))
        logit += float(biases[index])
        values[index] = math.exp(max(min(logit, LOGIT_CLIP), -LOGIT_CLIP))
    return normalize_vector(values, masked)


def fit_vector_scaling(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Fit per-class (scale, bias) by deterministic gradient descent in-fold."""
    assert_train_only(records, context="fit_vector_scaling")
    if len(records) < PARAMETRIC_MINIMUM_FIT_ROWS:
        return {
            "method": METHOD_VECTOR,
            "admitted": False,
            "params": None,
            "refusal": {
                "reason": "INSUFFICIENT_FIT_ROWS",
                "observed_fit_rows": len(records),
                "minimum_fit_rows": PARAMETRIC_MINIMUM_FIT_ROWS,
                "fallback": ISOTONIC_FALLBACK_RULE,
            },
        }
    sample, stride = fit_sample(records, VECTOR_SCALING_MAX_FIT_ROWS)
    prepared = _prepare(sample)
    count = len(prepared)
    size = len(grm.ACTIONS)
    scales = [1.0] * size
    biases = [0.0] * size
    for _ in range(VECTOR_SCALING_ITERATIONS):
        scale_gradient = [0.0] * size
        bias_gradient = [0.0] * size
        for logprobabilities, mask, observed in prepared:
            logits = [0.0] * size
            maximum = -math.inf
            for index in range(size):
                if mask[index]:
                    continue
                logit = scales[index] * logprobabilities[index] + biases[index]
                logit = max(min(logit, LOGIT_CLIP), -LOGIT_CLIP)
                logits[index] = logit
                if logit > maximum:
                    maximum = logit
            denominator = 0.0
            for index in range(size):
                if mask[index]:
                    continue
                denominator += math.exp(logits[index] - maximum)
            for index in range(size):
                if mask[index]:
                    continue
                share = math.exp(logits[index] - maximum) / denominator
                delta = share - (1.0 if index == observed else 0.0)
                scale_gradient[index] += delta * logprobabilities[index]
                bias_gradient[index] += delta
        for index in range(size):
            scale_gradient[index] = scale_gradient[index] / count + VECTOR_SCALING_L2 * (scales[index] - 1.0)
            bias_gradient[index] = bias_gradient[index] / count + VECTOR_SCALING_L2 * biases[index]
            scales[index] -= VECTOR_SCALING_LEARNING_RATE * scale_gradient[index]
            biases[index] -= VECTOR_SCALING_LEARNING_RATE * bias_gradient[index]
    params = {
        "scale": {action: _round(scales[index], 6) for index, action in enumerate(grm.ACTIONS)},
        "bias": {action: _round(biases[index], 6) for index, action in enumerate(grm.ACTIONS)},
    }
    return {
        "method": METHOD_VECTOR,
        "admitted": True,
        "params": params,
        "params_sha256": grm.stable_hash(_finalize(params)),
        "fit_rows": len(records),
        "descent_sample_rows": len(sample),
        "descent_sample_stride": stride,
        "refusal": None,
    }


# ---------------------------------------------------------------------------
# isotonic regression (gated)
# ---------------------------------------------------------------------------


def _pool_adjacent_violators(pairs: Sequence[tuple[float, float]]) -> tuple[list[float], list[float]]:
    """Monotone non-decreasing least-squares fit of ``y`` on sorted ``x``."""
    xs: list[float] = []
    ys: list[float] = []
    weights: list[float] = []
    for x, y in pairs:
        xs.append(float(x))
        ys.append(float(y))
        weights.append(1.0)
        while len(ys) > 1 and ys[-2] > ys[-1]:
            weight = weights[-2] + weights[-1]
            merged = (ys[-2] * weights[-2] + ys[-1] * weights[-1]) / weight
            upper = xs[-1]
            xs.pop()
            ys.pop()
            weights.pop()
            xs[-1] = upper
            ys[-1] = merged
            weights[-1] = weight
    return xs, ys


def isotonic_support(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """In-fold support statistics the preregistered isotonic gate reads."""
    positives = {action: 0 for action in grm.ACTIONS}
    observations = {action: 0 for action in grm.ACTIONS}
    levels = {action: set() for action in grm.ACTIONS}
    for record in records:
        mask = masked_actions(record)
        values = probability_vector(record["probabilities"])
        observed = str(record.get("observed") or "").strip().upper()
        for index, action in enumerate(grm.ACTIONS):
            if action in mask:
                continue
            observations[action] += 1
            levels[action].add(round(values[index], 12))
            if action == observed:
                positives[action] += 1
    return {
        "fit_rows": len(records),
        "class_positives": positives,
        "class_observations": observations,
        "distinct_probability_levels": {action: len(levels[action]) for action in grm.ACTIONS},
    }


def evaluate_isotonic_gate(support: Mapping[str, Any]) -> dict[str, Any]:
    """Apply the preregistered support floor to the in-fold statistics."""
    failures: list[dict[str, Any]] = []
    if int(support["fit_rows"]) < ISOTONIC_MINIMUM_SUPPORT["fit_rows"]:
        failures.append(
            {
                "criterion": "fit_rows",
                "observed": int(support["fit_rows"]),
                "minimum": ISOTONIC_MINIMUM_SUPPORT["fit_rows"],
            }
        )
    for action in grm.ACTIONS:
        if int(support["class_positives"][action]) < ISOTONIC_MINIMUM_SUPPORT["class_positives"]:
            failures.append(
                {
                    "criterion": "class_positives",
                    "action": action,
                    "observed": int(support["class_positives"][action]),
                    "minimum": ISOTONIC_MINIMUM_SUPPORT["class_positives"],
                }
            )
        if int(support["class_observations"][action]) < ISOTONIC_MINIMUM_SUPPORT["class_observations"]:
            failures.append(
                {
                    "criterion": "class_observations",
                    "action": action,
                    "observed": int(support["class_observations"][action]),
                    "minimum": ISOTONIC_MINIMUM_SUPPORT["class_observations"],
                }
            )
        if (
            int(support["distinct_probability_levels"][action])
            < ISOTONIC_MINIMUM_SUPPORT["distinct_probability_levels"]
        ):
            failures.append(
                {
                    "criterion": "distinct_probability_levels",
                    "action": action,
                    "observed": int(support["distinct_probability_levels"][action]),
                    "minimum": ISOTONIC_MINIMUM_SUPPORT["distinct_probability_levels"],
                }
            )
    return {
        "admitted": not failures,
        "failures": failures,
        "rule": ISOTONIC_ADMISSION_RULE,
        "minimum_support": dict(ISOTONIC_MINIMUM_SUPPORT),
    }


def fit_isotonic(
    records: Sequence[Mapping[str, Any]],
    *,
    strict: bool = False,
) -> dict[str, Any]:
    """Fit the per-class monotone map -- or refuse it below the support floor."""
    assert_train_only(records, context="fit_isotonic")
    support = isotonic_support(records)
    gate = evaluate_isotonic_gate(support)
    if not gate["admitted"]:
        refusal = {
            "reason": "INSUFFICIENT_SUPPORT",
            "gate": gate,
            "support": support,
            "fallback": ISOTONIC_FALLBACK_RULE,
        }
        if strict:
            raise CalibrationError(
                "isotonic support gate refused the fit: "
                + ", ".join(
                    f"{item['criterion']}"
                    + (f"[{item['action']}]" if "action" in item else "")
                    + f" observed {item['observed']} < {item['minimum']}"
                    for item in gate["failures"]
                )
            )
        return {
            "method": METHOD_ISOTONIC,
            "admitted": False,
            "params": None,
            "support": support,
            "refusal": refusal,
        }

    knots: dict[str, dict[str, list[float]]] = {}
    for index, action in enumerate(grm.ACTIONS):
        pairs = []
        for record in records:
            if action in masked_actions(record):
                continue
            value = probability_vector(record["probabilities"])[index]
            label = 1.0 if str(record.get("observed") or "").strip().upper() == action else 0.0
            pairs.append((value, label))
        pairs.sort(key=lambda item: item[0])
        xs, ys = _pool_adjacent_violators(pairs)
        # Compress the step function: keep the last x of every constant run.
        compressed_x: list[float] = []
        compressed_y: list[float] = []
        for x, y in zip(xs, ys, strict=True):
            if compressed_y and y == compressed_y[-1]:
                compressed_x[-1] = x
                continue
            compressed_x.append(x)
            compressed_y.append(y)
        knots[action] = {
            "x": [_round(value, 6) for value in compressed_x],
            "y": [_round(value, 6) for value in compressed_y],
        }
    params = {"knots": knots, "basis": "pool_adjacent_violators_step_map"}
    inline = all(
        len(knots[action]["x"]) <= ISOTONIC_MAX_INLINE_KNOTS for action in grm.ACTIONS
    )
    payload: dict[str, Any] = {
        "method": METHOD_ISOTONIC,
        "admitted": True,
        "params": params if inline else None,
        "params_sha256": grm.stable_hash(_finalize(params)),
        "support": support,
        "fit_rows": len(records),
        "knot_counts": {action: len(knots[action]["x"]) for action in grm.ACTIONS},
        "params_inlined": inline,
        "refusal": None,
    }
    return payload


def isotonic_lookup(xs: Sequence[float], ys: Sequence[float], probability: float) -> float:
    """Monotone map value, anchored at ``(0, 0)`` and ``(1, 1)``.

    A raw pool-adjacent-violators *step* map is only defined between its first
    and last knot, and clamping outside that range fabricates extremes: a
    held-out decision whose predicted probability falls just below the first
    in-fold knot would be mapped to that knot's frequency -- often ``0`` for a
    rare class -- which is exactly how a calibration destroys the out-of-fold
    log loss.  Reading the knots by linear interpolation, and extending the map
    towards the identity anchors, keeps it monotone, keeps ``[0, 1]`` as its
    domain, and keeps the map continuous at the knots.
    """
    if not xs or not ys:
        return float(probability)
    value = min(max(float(probability), 0.0), 1.0)
    if value <= xs[0]:
        if xs[0] <= 0.0:
            return float(ys[0])
        return float(ys[0]) * (value / float(xs[0]))
    if value >= xs[-1]:
        if xs[-1] >= 1.0:
            return float(ys[-1])
        share = (value - float(xs[-1])) / (1.0 - float(xs[-1]))
        return float(ys[-1]) + share * (1.0 - float(ys[-1]))
    position = bisect.bisect_right(list(xs), value) - 1
    left_x, right_x = float(xs[position]), float(xs[position + 1])
    left_y, right_y = float(ys[position]), float(ys[position + 1])
    if right_x <= left_x:
        return right_y
    share = (value - left_x) / (right_x - left_x)
    return left_y + share * (right_y - left_y)


def apply_isotonic(
    probabilities: Sequence[float],
    knots: Mapping[str, Mapping[str, Sequence[float]]],
    masked: frozenset[str] = frozenset(),
) -> list[float]:
    values = [0.0] * len(grm.ACTIONS)
    for index, action in enumerate(grm.ACTIONS):
        if action in masked:
            continue
        table = knots.get(action) or {}
        values[index] = isotonic_lookup(
            list(table.get("x") or ()), list(table.get("y") or ()), float(probabilities[index])
        )
    return normalize_vector(values, masked)


# ---------------------------------------------------------------------------
# generic calibration surface
# ---------------------------------------------------------------------------


def fit_calibration(
    method: str,
    records: Sequence[Mapping[str, Any]],
    *,
    strict_isotonic: bool = False,
) -> dict[str, Any]:
    """Fit one calibration family on in-fold records only."""
    assert_train_only(records, context=f"fit_calibration[{method}]")
    if method == METHOD_TEMPERATURE:
        fitted = fit_temperature(records)
    elif method == METHOD_VECTOR:
        fitted = fit_vector_scaling(records)
    elif method == METHOD_ISOTONIC:
        fitted = fit_isotonic(records, strict=strict_isotonic)
    else:
        raise CalibrationError(f"unknown calibration method {method!r}")
    fitted.setdefault("params_sha256", None)
    fitted.setdefault("support", None)
    fitted.setdefault("refusal", None)
    return fitted


def apply_calibration(
    fitted: Mapping[str, Any],
    probabilities: Sequence[float],
    masked: frozenset[str] = frozenset(),
) -> list[float]:
    """Apply a fitted calibration; an uncalibrated/refused fit is the identity."""
    method = str(fitted.get("method"))
    if method == METHOD_UNCALIBRATED or not fitted.get("admitted"):
        return normalize_vector(list(probabilities), masked)
    params = fitted.get("params")
    if not isinstance(params, Mapping):
        raise CalibrationError(
            f"calibration {method!r} was admitted but its parameters are not persisted inline"
        )
    if method == METHOD_TEMPERATURE:
        return apply_temperature(probabilities, float(params["temperature"]), masked)
    if method == METHOD_VECTOR:
        scales = [float(params["scale"][action]) for action in grm.ACTIONS]
        biases = [float(params["bias"][action]) for action in grm.ACTIONS]
        return apply_vector_scaling(probabilities, scales, biases, masked)
    if method == METHOD_ISOTONIC:
        return apply_isotonic(probabilities, params["knots"], masked)
    raise CalibrationError(f"unknown calibration method {method!r}")


def calibrate_record(
    fitted: Mapping[str, Any],
    record: Mapping[str, Any],
) -> dict[str, float]:
    assert_train_only([record], context="calibrate_record")
    mask = masked_actions(record)
    values = apply_calibration(fitted, probability_vector(record["probabilities"]), mask)
    return vector_to_probabilities(values)


# ---------------------------------------------------------------------------
# pooling: compact out-of-fold probability stores
# ---------------------------------------------------------------------------


class ProbabilityStore:
    """Compact per-stratum store of out-of-fold probabilities.

    Pooling ~94k decisions per (architecture, method) in Python dicts would cost
    hundreds of megabytes; the store keeps the four probabilities of every
    decision in a flat ``array('d')`` and expands to harness records lazily.
    """

    __slots__ = ("observed", "probabilities", "strata", "masks")

    def __init__(self) -> None:
        self.observed = array("b")
        self.probabilities = array("d")
        self.strata: list[str] = []
        self.masks: list[int] = []

    def __len__(self) -> int:
        return len(self.observed)

    def add(self, values: Sequence[float], observed: int, stratum: str, mask: frozenset[str]) -> None:
        self.observed.append(int(observed))
        self.probabilities.extend(float(value) for value in values)
        self.strata.append(str(stratum))
        self.masks.append(sum(1 << index for index, action in enumerate(grm.ACTIONS) if action in mask))

    def records(self, stratum: str | None = None) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for position in range(len(self.observed)):
            if stratum is not None and self.strata[position] != stratum:
                continue
            base = position * len(grm.ACTIONS)
            probabilities = {
                action: self.probabilities[base + index] for index, action in enumerate(grm.ACTIONS)
            }
            mask = self.masks[position]
            records.append(
                {
                    "observed": grm.ACTIONS[self.observed[position]],
                    "probabilities": probabilities,
                    "masked_actions": [
                        action
                        for index, action in enumerate(grm.ACTIONS)
                        if mask & (1 << index)
                    ],
                }
            )
        return records

    def stratum_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for stratum in self.strata:
            counts[stratum] = counts.get(stratum, 0) + 1
        return counts


def fit_sample(
    rows: Sequence[Mapping[str, Any]],
    maximum: int = CALIBRATION_FIT_MAX_ROWS,
) -> tuple[list[Mapping[str, Any]], int]:
    """Deterministic stride sample of the (already canonically ordered) fit rows."""
    maximum = int(maximum)
    if maximum < 1:
        raise CalibrationError("the calibration fit-sample cap must be >= 1")
    if len(rows) <= maximum:
        return list(rows), 1
    stride = math.ceil(len(rows) / maximum)
    return list(rows[::stride]), stride


# ---------------------------------------------------------------------------
# one fold: fit in-fold, evaluate out-of-fold
# ---------------------------------------------------------------------------


class Fold:
    """(fit rows, held-out rows, in-fold calibration sample, fitted calibrations)."""

    def __init__(
        self,
        split_fold: harness.Fold,
        architecture: str,
        *,
        seed: int,
        config: Mapping[str, Any] | None,
        methods: Sequence[str],
        strict_isotonic: bool,
        fit_max_rows: int,
    ) -> None:
        if architecture not in grm.ARCHITECTURES:
            raise CalibrationError(f"unknown architecture {architecture!r}")
        self.index = split_fold.index
        self.architecture = architecture
        self.split_fold = split_fold
        self.candidate = grm.fit(split_fold.train_rows, seed, architecture=architecture, config=config)
        self.prior = {action: float(self.candidate["params"]["prior"][action]) for action in grm.ACTIONS}

        self.fit_rows = list(split_fold.train_rows)
        self.sample_rows, self.sample_stride = fit_sample(self.fit_rows, fit_max_rows)
        self.fit_records = self._predictions(self.sample_rows, provenance="in_fold_fit", classify=False)
        self.out_of_fold_records = self._predictions(
            split_fold.holdout_rows, provenance="out_of_fold_holdout", classify=True
        )
        self.fitted: dict[str, dict[str, Any]] = {
            method: fit_calibration(method, self.fit_records, strict_isotonic=strict_isotonic)
            for method in methods
        }
        self.stores: dict[str, ProbabilityStore] = {
            METHOD_UNCALIBRATED: self._store(METHOD_UNCALIBRATED)
        }
        for method in methods:
            if self.fitted[method]["admitted"]:
                self.stores[method] = self._store(method)

    def _predictions(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        provenance: str,
        classify: bool,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        index = self.split_fold.fit_index
        for row in rows:
            split = str(row.get("split") or "").strip().upper()
            if split != MAIN_SPLIT:
                raise CalibrationError(
                    f"the calibration consumes {list(CONSUMED_SPLITS)} only; got split {split!r}"
                )
            prediction = grm.predict(self.candidate, row)
            record: dict[str, Any] = {
                "hand_id": str(row.get("hand_id") or "").strip(),
                "split": split,
                "provenance": provenance,
                "observed": str(row.get("action") or "").strip().upper(),
                "probabilities": dict(prediction["probabilities"]),
                "masked_actions": list(prediction["masked_actions"]),
            }
            record["stratum"] = harness.classify_row(row, index)["stratum"] if classify else None
            records.append(record)
        return records

    def _store(self, method: str) -> ProbabilityStore:
        fitted = (
            {"method": METHOD_UNCALIBRATED, "admitted": False, "params": None}
            if method == METHOD_UNCALIBRATED
            else self.fitted[method]
        )
        store = ProbabilityStore()
        for record in self.out_of_fold_records:
            mask = masked_actions(record)
            values = apply_calibration(fitted, probability_vector(record["probabilities"]), mask)
            store.add(values, _observed_index(record), record["stratum"], mask)
        return store

    def metrics(self, method: str, *, stratum: str | None = None) -> dict[str, Any]:
        if method not in self.stores:
            raise CalibrationError(f"method {method!r} was refused and is therefore not scored")
        return harness.summary_metrics(self.stores[method].records(stratum), self.prior)

    def public(self, methods: Sequence[str]) -> dict[str, Any]:
        summary = self.split_fold.summary()
        fold_metrics: dict[str, Any] = {}
        for method in (METHOD_UNCALIBRATED,) + tuple(methods):
            if method not in self.stores:
                fold_metrics[method] = None
                continue
            metrics = self.metrics(method)
            fold_metrics[method] = {
                "log_loss_bits_per_decision": metrics["log_loss_bits_per_decision"],
                "expected_calibration_error": metrics["expected_calibration_error"],
                "brier_score": metrics["brier_score"],
            }
        return {
            **summary,
            "architecture": self.architecture,
            "candidate_canonical_payload_sha256": self.candidate["canonical_payload_sha256"],
            "calibration_fit_rows": len(self.fit_records),
            "calibration_fit_stride": self.sample_stride,
            "prior": self.prior,
            "support": isotonic_support(self.fit_records),
            "methods": {
                method: {
                    "admitted": bool(self.fitted[method]["admitted"]),
                    "params_sha256": self.fitted[method]["params_sha256"],
                    "params": self.fitted[method]["params"],
                    "knot_counts": self.fitted[method].get("knot_counts"),
                    "params_inlined": self.fitted[method].get("params_inlined", True),
                    "refusal": self.fitted[method]["refusal"],
                }
                for method in methods
            },
            "fold_metrics": fold_metrics,
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
        "best_methods": sorted(item for item in values if values[item] == best),
        "kept": kept,
        "eliminated": sorted(item for item in values if item not in kept),
    }


def select_method(methods: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Apply the preregistered out-of-fold-only method-selection procedure."""
    criteria = PREREGISTERED_SELECTION_CRITERIA

    def value(method: str, path: str) -> float:
        node: Any = methods[method]
        for part in path.split("."):
            node = node[part]
        return float(node)

    admissible = sorted(method for method in methods if methods[method]["admissible"])
    trace: list[dict[str, Any]] = [
        {
            "step": 1,
            "criterion": "admissibility",
            "metric": "admissibility.isotonic_support_gate",
            "tolerance": 0.0,
            "best": None,
            "best_methods": admissible,
            "kept": admissible,
            "eliminated": sorted(method for method in methods if method not in admissible),
            "survivors_before": sorted(methods),
            "refusals": {
                method: methods[method].get("refusal")
                for method in methods
                if not methods[method]["admissible"]
            },
        }
    ]
    survivors = admissible
    for step_spec in criteria["steps"][1:]:
        if len(survivors) <= 1:
            break
        metric = step_spec["metric"]
        values = {method: value(method, metric) for method in survivors}
        applied = _step(step_spec["name"], metric, values, step_spec["tolerance"])
        trace.append(dict(applied, step=step_spec["step"], survivors_before=sorted(survivors)))
        survivors = [method for method in survivors if method in applied["kept"]]
    ranking = sorted(
        admissible,
        key=lambda method: (
            value(method, "out_of_fold.expected_calibration_error.ece"),
            value(method, "out_of_fold.log_loss_bits_per_decision"),
            value(method, "out_of_fold.brier_score"),
            value(method, "runtime.complexity_rank"),
            method,
        ),
    )
    retained = min(survivors) if survivors else ranking[0]
    return {
        "criteria": criteria,
        "trace": trace,
        "ranking": ranking,
        "retained": retained,
        "admissible_methods": admissible,
        "refused_methods": {
            method: methods[method].get("refusal")
            for method in sorted(methods)
            if not methods[method]["admissible"]
        },
        "evidence": {
            method: {
                "out_of_fold_log_loss_bits_per_decision": methods[method]["out_of_fold"].get(
                    "log_loss_bits_per_decision"
                ),
                "out_of_fold_expected_calibration_error": (
                    methods[method]["out_of_fold"].get("expected_calibration_error") or {}
                ).get("ece"),
                "out_of_fold_brier_score": methods[method]["out_of_fold"].get("brier_score"),
                "runtime_complexity_rank": methods[method]["runtime"]["complexity_rank"],
                "admissible": methods[method]["admissible"],
                "scored": bool(methods[method]["out_of_fold"].get("scored")),
            }
            for method in sorted(methods)
        },
        "evidence_basis": "out_of_fold_holdout_only",
        "consumed_splits": list(CONSUMED_SPLITS),
        "validation_consumed": False,
        "test_consumed": False,
    }


def _justification(selection: Mapping[str, Any], architecture: str) -> str:
    retained = selection["retained"]
    evidence = selection["evidence"][retained]
    text = (
        f"retained `{retained}` for architecture `{architecture}` on TRAIN out-of-fold evidence only: "
        f"ECE {evidence['out_of_fold_expected_calibration_error']:.6f}, log loss "
        f"{evidence['out_of_fold_log_loss_bits_per_decision']:.6f} bits/decision, Brier "
        f"{evidence['out_of_fold_brier_score']:.6f}, complexity rank "
        f"{evidence['runtime_complexity_rank']}"
    )
    refused = selection["refused_methods"]
    if refused:
        text += "; refused by their preregistered gate: " + ", ".join(
            f"{method} ({(refusal or {}).get('reason', 'UNKNOWN')})" for method, refusal in refused.items()
        )
    baseline = selection["evidence"].get(METHOD_UNCALIBRATED)
    if baseline is not None:
        text += (
            f"; uncalibrated baseline ECE {baseline['out_of_fold_expected_calibration_error']:.6f}, "
            f"log loss {baseline['out_of_fold_log_loss_bits_per_decision']:.6f}"
        )
    return text + (
        ". The decision used TRAIN out-of-fold evidence only; VALIDATION and TEST were not consumed "
        "and no calibration is applied on VALIDATION (validation_consumed=false, test_consumed=false)."
    )


# ---------------------------------------------------------------------------
# top-level run and report
# ---------------------------------------------------------------------------


def harness_selected_architecture() -> str | None:
    """The architecture the #421 harness selected, when its report is readable."""
    if not HARNESS_REPORT_PATH.exists():
        return None
    try:
        report = json.loads(HARNESS_REPORT_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    selected = report.get("selection", {}).get("selected")
    return str(selected) if selected in grm.ARCHITECTURES else None


def primary_architecture(architectures: Sequence[str]) -> str:
    """Architecture whose retained method is the report's headline decision.

    The headline follows the #421 harness selection (the architecture #423's
    router consumes); a run over a different set falls back to the first
    requested architecture, and every architecture still carries its own
    retained method.
    """
    selected = harness_selected_architecture()
    if selected is not None and selected in architectures:
        return selected
    return list(architectures)[0]


def read_train_rows(dataset: str | Path = DEFAULT_DATASET, *, stride: int = 1) -> list[dict[str, Any]]:
    """Read TRAIN through the #421 harness loader (which fails closed on TEST)."""
    rows = harness.read_train_rows(dataset, stride=stride)
    assert_train_only(rows, context="read_train_rows")
    return rows


def run_calibration(
    rows: Iterable[Mapping[str, Any]],
    *,
    folds: int = harness.CV_FOLDS,
    seed: int = harness.CV_SEED,
    architectures: Sequence[str] = grm.ARCHITECTURES,
    methods: Sequence[str] = COMPARED_METHODS,
    config: Mapping[str, Any] | None = None,
    strict_isotonic: bool = False,
    fit_max_rows: int = CALIBRATION_FIT_MAX_ROWS,
) -> dict[str, Any]:
    """Fit every calibration family in-fold and score it out-of-fold on TRAIN."""
    architectures = list(architectures)
    methods = list(methods)
    for method in methods:
        if method not in COMPARED_METHODS:
            raise CalibrationError(f"unknown calibration method {method!r}")
    for architecture in architectures:
        if architecture not in grm.ARCHITECTURES:
            raise CalibrationError(f"unknown architecture {architecture!r}")
    if not architectures:
        raise CalibrationError("no architecture to calibrate")
    effective_config = grm.make_config(**dict(config)) if isinstance(config, Mapping) else grm.make_config()

    split = harness.grouped_folds(rows, folds=folds, seed=seed)
    no_leak = harness.no_leak_proof(split)
    per_architecture: dict[str, Any] = {}
    for architecture in architectures:
        fold_results = [
            Fold(
                split_fold,
                architecture,
                seed=seed,
                config=config,
                methods=methods,
                strict_isotonic=strict_isotonic,
                fit_max_rows=fit_max_rows,
            )
            for split_fold in split
        ]
        public_folds = [result.public(methods) for result in fold_results]
        admissible = {
            method: (
                method == METHOD_UNCALIBRATED
                or all(result.fitted[method]["admitted"] for result in fold_results)
            )
            for method in (METHOD_UNCALIBRATED,) + tuple(methods)
        }
        pooled: dict[str, ProbabilityStore] = {
            method: ProbabilityStore()
            for method in (METHOD_UNCALIBRATED,) + tuple(methods)
            if admissible[method]
        }
        for result in fold_results:
            for method in pooled:
                source = result.stores[method]
                for position in range(len(source)):
                    base = position * len(grm.ACTIONS)
                    pooled[method].add(
                        list(source.probabilities[base : base + len(grm.ACTIONS)]),
                        source.observed[position],
                        source.strata[position],
                        frozenset(
                            action
                            for index, action in enumerate(grm.ACTIONS)
                            if source.masks[position] & (1 << index)
                        ),
                    )
        prior = dict(fold_results[0].prior)
        out_of_fold: dict[str, Any] = {}
        refusal: dict[str, Any] = {}
        for method in (METHOD_UNCALIBRATED,) + tuple(methods):
            if not admissible[method]:
                refusal[method] = next(
                    (
                        result.fitted[method]["refusal"]
                        for result in fold_results
                        if not result.fitted[method]["admitted"]
                    ),
                    None,
                )
                out_of_fold[method] = {
                    "scored": False,
                    "reason": "refused by its preregistered support gate; never applied and never scored",
                    "refusal": refusal[method],
                    "runtime": {"complexity_rank": METHOD_COMPLEXITY_RANK[method]},
                }
                continue
            metrics = harness.summary_metrics(pooled[method].records(), prior)
            out_of_fold[method] = {
                **metrics,
                "scored": True,
                "by_stratum": {
                    stratum: harness.summary_metrics(pooled[method].records(stratum), prior)
                    for stratum in harness.STRATA
                },
                "runtime": {"complexity_rank": METHOD_COMPLEXITY_RANK[method]},
            }
        selection_input = {
            method: {
                "admissible": bool(admissible[method]),
                "out_of_fold": out_of_fold[method],
                "runtime": {"complexity_rank": METHOD_COMPLEXITY_RANK[method]},
                "refusal": refusal.get(method),
            }
            for method in (METHOD_UNCALIBRATED,) + tuple(methods)
        }
        selection = select_method(selection_input)
        retained = selection["retained"]
        ece_before = out_of_fold[METHOD_UNCALIBRATED]["expected_calibration_error"]["ece"]
        ece_after = out_of_fold[retained]["expected_calibration_error"]["ece"]
        per_architecture[architecture] = {
            "architecture": architecture,
            "folds": public_folds,
            "out_of_fold": out_of_fold,
            "ece_before_after_by_stratum": {
                stratum: {
                    "n": out_of_fold[METHOD_UNCALIBRATED]["by_stratum"][stratum]["n"],
                    "ece_before": out_of_fold[METHOD_UNCALIBRATED]["by_stratum"][stratum][
                        "expected_calibration_error"
                    ]["ece"],
                    "ece_after": out_of_fold[retained]["by_stratum"][stratum][
                        "expected_calibration_error"
                    ]["ece"],
                    "log_loss_before": out_of_fold[METHOD_UNCALIBRATED]["by_stratum"][stratum][
                        "log_loss_bits_per_decision"
                    ],
                    "log_loss_after": out_of_fold[retained]["by_stratum"][stratum][
                        "log_loss_bits_per_decision"
                    ],
                    "brier_before": out_of_fold[METHOD_UNCALIBRATED]["by_stratum"][stratum][
                        "brier_score"
                    ],
                    "brier_after": out_of_fold[retained]["by_stratum"][stratum]["brier_score"],
                }
                for stratum in harness.STRATA
            },
            "ece_delta": {"before": ece_before, "after": ece_after},
            "stability": {
                "fold_expected_calibration_error": {
                    "uncalibrated": [
                        block["fold_metrics"][METHOD_UNCALIBRATED]["expected_calibration_error"]["ece"]
                        for block in public_folds
                    ],
                    "retained": [
                        block["fold_metrics"][retained]["expected_calibration_error"]["ece"]
                        for block in public_folds
                    ],
                },
                "folds": len(fold_results),
            },
            "retained": {
                "method": retained,
                "params_by_fold": [
                    {
                        "fold": result.index,
                        "params_sha256": result.fitted[retained]["params_sha256"]
                        if retained != METHOD_UNCALIBRATED
                        else None,
                        "params": result.fitted[retained]["params"]
                        if retained != METHOD_UNCALIBRATED
                        else None,
                    }
                    for result in fold_results
                ],
            },
            "selection": selection,
        }
    primary = primary_architecture(architectures)
    return {
        "protocol": {
            "kind": "in_fold_fitted_out_of_fold_evaluated_calibration",
            "main_split": MAIN_SPLIT,
            "consumed_splits": list(CONSUMED_SPLITS),
            "forbidden_splits": list(FORBIDDEN_SPLITS),
            "refused_splits": list(REFUSED_SPLITS),
            "group_key": "hand_id",
            "folds": int(folds),
            "seed": int(seed),
            "fold_assignment": (
                f"int(stable_hash('grm-cv/{int(seed)}/<hand_id>')[:8], 16) % {int(folds)}"
            ),
            "no_leak": no_leak,
            "calibration_fit_rule": CALIBRATION_FIT_RULE,
            "evaluation_rule": EVALUATION_RULE,
            "calibration_fit_max_rows": int(fit_max_rows),
            "model_config": effective_config,
            "model_config_source": "explicit" if isinstance(config, Mapping) else "library_default",
            "architectures": list(architectures),
            "compared_methods": list(methods),
            "evaluated_methods": list(EVALUATED_METHODS),
            "baseline_method": METHOD_UNCALIBRATED,
            "definitions": {
                METHOD_TEMPERATURE: TEMPERATURE_DEFINITION,
                METHOD_VECTOR: VECTOR_DEFINITION,
                METHOD_ISOTONIC: ISOTONIC_DEFINITION,
            },
            "isotonic": {
                "admission_rule": ISOTONIC_ADMISSION_RULE,
                "minimum_support": dict(ISOTONIC_MINIMUM_SUPPORT),
                "on_refusal": ISOTONIC_FALLBACK_RULE,
                "strict_mode": bool(strict_isotonic),
            },
            "no_validation_recalibration": {
                "consumed_splits": list(CONSUMED_SPLITS),
                "recalibrated_splits": list(CONSUMED_SPLITS),
                "refused_splits": list(REFUSED_SPLITS),
                "validation_consumed": False,
                "test_consumed": False,
                "enforcement": (
                    "fit_calibration/calibrate_record call assert_train_only, which raises "
                    "CalibrationError on any record whose split is VALIDATION or TEST; the loader is "
                    "the harness TRAIN-only reader"
                ),
                "static_scan": verify_no_holdout_access(),
            },
            "metrics": {
                "log_loss_bits_per_decision": "mean -log2 P(observed action), base-2 bits per decision",
                "brier_score": "mean sum over the four actions of (P(action) - 1[observed])^2",
                "expected_calibration_error": harness.CALIBRATION_DEFINITION,
                "calibration_bins": harness.CALIBRATION_BINS,
                "minimum_bin_support": harness.CALIBRATION_MINIMUM_BIN_SUPPORT,
                "strata_definition": harness.STRATA_DEFINITION,
            },
        },
        "folds": [fold.summary() for fold in split],
        "architectures": per_architecture,
        "retained_method": per_architecture[primary]["retained"]["method"],
        "retained_architecture": primary,
        "retained_methods_by_architecture": {
            architecture: per_architecture[architecture]["retained"]["method"]
            for architecture in architectures
        },
        "justification": {
            architecture: _justification(per_architecture[architecture]["selection"], architecture)
            for architecture in architectures
        },
    }


def _harness_consistency(
    architectures: Mapping[str, Mapping[str, Any]],
    *,
    dataset_path: Path,
    stride: int,
    config: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Absolute delta between this run's uncalibrated metrics and the #421 harness report."""
    if stride != 1 or config is not None:
        return {
            "checked": False,
            "reason": "the harness report is the full-TRAIN default-config run; a strided or re-tuned run is not comparable",
        }
    if not HARNESS_REPORT_PATH.exists():
        return {"checked": False, "reason": f"missing {_relative(HARNESS_REPORT_PATH)}"}
    report = json.loads(HARNESS_REPORT_PATH.read_text(encoding="utf-8"))
    if report.get("scope", {}).get("dataset_sha256") != sha256_file(dataset_path):
        return {"checked": False, "reason": "the harness report was built from a different dataset"}
    if report.get("model_module", {}).get("sha256") != sha256_file(Path(grm.__file__)):
        return {"checked": False, "reason": "the harness report was built with a different model module"}
    comparisons: dict[str, Any] = {}
    within = True
    for architecture, block in architectures.items():
        if architecture not in report.get("architectures", {}):
            continue
        reference = report["architectures"][architecture]
        mine = block["out_of_fold"][METHOD_UNCALIBRATED]
        deltas = {
            "log_loss_bits_per_decision": abs(
                float(mine["log_loss_bits_per_decision"])
                - float(reference["out_of_fold"]["log_loss_bits_per_decision"])
            ),
            "expected_calibration_error": abs(
                float(mine["expected_calibration_error"]["ece"])
                - float(reference["out_of_fold"]["expected_calibration_error"]["ece"])
            ),
            "brier_score": abs(
                float(mine["brier_score"]) - float(reference["out_of_fold"]["brier_score"])
            ),
        }
        stratum_deltas = {
            stratum: abs(
                float(mine["by_stratum"][stratum]["expected_calibration_error"]["ece"] or 0.0)
                - float(
                    reference["strata"]["metrics"][stratum]["expected_calibration_error"]["ece"] or 0.0
                )
            )
            for stratum in harness.STRATA
            if reference["strata"]["metrics"][stratum]["expected_calibration_error"]["ece"] is not None
            and mine["by_stratum"][stratum]["expected_calibration_error"]["ece"] is not None
        }
        published = {
            "log_loss_bits_per_decision": round(
                float(mine["log_loss_bits_per_decision"]), HARNESS_CONSISTENCY_PRECISION
            )
            == reference["out_of_fold"]["log_loss_bits_per_decision"],
            "expected_calibration_error": round(
                float(mine["expected_calibration_error"]["ece"]), HARNESS_CONSISTENCY_PRECISION
            )
            == reference["out_of_fold"]["expected_calibration_error"]["ece"],
            "brier_score": round(float(mine["brier_score"]), HARNESS_CONSISTENCY_PRECISION)
            == reference["out_of_fold"]["brier_score"],
            "by_stratum_ece": all(
                round(
                    float(mine["by_stratum"][stratum]["expected_calibration_error"]["ece"]),
                    HARNESS_CONSISTENCY_PRECISION,
                )
                == reference["strata"]["metrics"][stratum]["expected_calibration_error"]["ece"]
                for stratum in stratum_deltas
            ),
        }
        within = within and all(
            value <= HARNESS_CONSISTENCY_TOLERANCE for value in list(deltas.values()) + list(stratum_deltas.values())
        )
        comparisons[architecture] = {
            "absolute_delta": deltas,
            "absolute_delta_by_stratum_ece": stratum_deltas,
            "equal_at_published_precision": published,
            "harness_metrics": {
                "log_loss_bits_per_decision": reference["out_of_fold"]["log_loss_bits_per_decision"],
                "expected_calibration_error": reference["out_of_fold"]["expected_calibration_error"]["ece"],
                "brier_score": reference["out_of_fold"]["brier_score"],
            },
            "calibration_metrics": {
                "log_loss_bits_per_decision": mine["log_loss_bits_per_decision"],
                "expected_calibration_error": mine["expected_calibration_error"]["ece"],
                "brier_score": mine["brier_score"],
            },
        }
    return {
        "checked": True,
        "reason": None,
        "path": _relative(HARNESS_REPORT_PATH),
        "sha256": sha256_file(HARNESS_REPORT_PATH),
        "tolerance": HARNESS_CONSISTENCY_TOLERANCE,
        "published_precision": HARNESS_CONSISTENCY_PRECISION,
        "definition": (
            "absolute delta between this module's uncalibrated out-of-fold metric surface and the "
            "#421 harness report, plus the equality of both surfaces at the precision the harness "
            "persists"
        ),
        "within_tolerance": within,
        "architectures": comparisons,
    }


def build_report(
    dataset: str | Path = DEFAULT_DATASET,
    *,
    folds: int = harness.CV_FOLDS,
    seed: int = harness.CV_SEED,
    architectures: Sequence[str] = grm.ARCHITECTURES,
    methods: Sequence[str] = COMPARED_METHODS,
    config: Mapping[str, Any] | None = None,
    stride: int = 1,
    strict_isotonic: bool = False,
    fit_max_rows: int = CALIBRATION_FIT_MAX_ROWS,
) -> dict[str, Any]:
    """Read TRAIN, run the in-fold/out-of-fold calibration and return the report."""
    dataset_path = Path(dataset).resolve()
    rows = read_train_rows(dataset_path, stride=stride)
    core = run_calibration(
        rows,
        folds=folds,
        seed=seed,
        architectures=architectures,
        methods=methods,
        config=config,
        strict_isotonic=strict_isotonic,
        fit_max_rows=fit_max_rows,
    )
    hands = {str(row["hand_id"]).strip() for row in rows}
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "kind": "train_only_in_fold_fitted_out_of_fold_evaluated_calibration",
        "generated_by": _relative(Path(__file__)),
        "module_sha256": sha256_file(Path(__file__)),
        "harness": {
            "module": _relative(Path(harness.__file__)),
            "module_sha256": sha256_file(Path(harness.__file__)),
            "schema": harness.SCHEMA,
            "group_key": "hand_id",
            "folds": int(folds),
            "seed": int(seed),
            "fold_assignment": core["protocol"]["fold_assignment"],
            "no_leak": core["protocol"]["no_leak"],
            "strata": list(harness.STRATA),
            "metric_definitions": {
                "expected_calibration_error": harness.CALIBRATION_DEFINITION,
                "calibration_bins": harness.CALIBRATION_BINS,
                "minimum_bin_support": harness.CALIBRATION_MINIMUM_BIN_SUPPORT,
            },
            "integration": (
                "the calibration folds, strata classifier and metric definitions are the #421 harness "
                "ones; the harness module is consumed, not rewritten, because its digest is pinned by "
                "frozen #421 evidence"
            ),
            "selected_architecture": harness_selected_architecture(),
            "headline_architecture": core["retained_architecture"],
            "architecture_selection_rule": (
                "the headline `retained_method` is the method retained for the architecture the #421 "
                "harness ranked first on TRAIN out-of-fold evidence; every calibrated architecture "
                "still carries its own retained method"
            ),
            "train_cv_report_consistency": _harness_consistency(
                core["architectures"], dataset_path=dataset_path, stride=stride, config=config
            ),
        },
        "scope": {
            "dataset": _relative(dataset_path),
            "dataset_sha256": sha256_file(dataset_path),
            "dataset_bytes": dataset_path.stat().st_size,
            "split": MAIN_SPLIT,
            "rows": len(rows),
            "hands": len(hands),
            "row_stride": int(stride),
            "consumed_splits": list(CONSUMED_SPLITS),
            "recalibrated_splits": list(CONSUMED_SPLITS),
            "forbidden_splits": list(FORBIDDEN_SPLITS),
            "refused_splits": list(REFUSED_SPLITS),
            "validation_consumed": False,
            "test_consumed": False,
            "cross_validated_rows": sum(fold["holdout_rows"] for fold in core["folds"]),
        },
        **core,
        "guards": {
            "train_only": True,
            "validation_consumed": False,
            "test_consumed": False,
            "validation_recalibrated": False,
            "recalibration_scope": list(CONSUMED_SPLITS),
            "validation_recalibration_refused": True,
            "validation_recalibration_refusal_proof": (
                "assert_train_only raises CalibrationError for any VALIDATION or TEST record; "
                "tests/preflop/test_generalized_response_calibration.py exercises the refusal"
            ),
            "isotonic_support_gate_enforced": True,
            "isotonic_fallback_documented": ISOTONIC_FALLBACK_RULE,
            "no_holdout_loader": verify_no_holdout_access()["result"] == "PASS",
            "byte_stable": True,
        },
    }
    report["canonical_payload_sha256"] = grm.stable_hash(_canonical_payload(_finalize(report)))
    return report


def _canonical_payload(report: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in report.items() if key != "canonical_payload_sha256"}


def persisted_report_text(report: Mapping[str, Any]) -> str:
    return json.dumps(_finalize(report), sort_keys=True, indent=2, ensure_ascii=True) + "\n"


def sidecar_text(report: Mapping[str, Any], *, name: str = REPORT_NAME) -> str:
    payload = persisted_report_text(report)
    return (
        f"{sha256_bytes(payload.encode('utf-8'))}  {name}\n"
        f"# canonical_payload_sha256 {grm.stable_hash(_canonical_payload(_finalize(report)))}\n"
        f"# retained_method {report.get('retained_method')}\n"
        f"# scope TRAIN_ONLY_NO_VALIDATION_RECALIBRATION\n"
    )


def write_report(report: Mapping[str, Any], path: str | Path = REPORT_PATH) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(persisted_report_text(report), encoding="utf-8")
    digest_target = target.with_suffix(".sha256")
    digest_target.write_text(sidecar_text(report, name=target.name), encoding="utf-8")
    return target


def verify_persisted(path: str | Path = REPORT_PATH) -> list[str]:
    """Cheap structural verification of the persisted report and its sidecar."""
    target = Path(path)
    problems: list[str] = []
    if not target.exists():
        return [f"missing {_relative(target)}"]
    digest_target = target.with_suffix(".sha256")
    if not digest_target.exists():
        return [f"missing {_relative(digest_target)}"]
    raw = target.read_bytes()
    report = json.loads(raw.decode("utf-8"))
    if report.get("schema") != REPORT_SCHEMA:
        problems.append(f"schema must be {REPORT_SCHEMA}")
    if report.get("module_sha256") != sha256_file(Path(__file__)):
        problems.append("module_sha256 does not match the on-disk calibration module")
    if report.get("canonical_payload_sha256") != grm.stable_hash(
        _canonical_payload(_finalize(report))
    ):
        problems.append("canonical payload digest mismatch")
    sidecar = digest_target.read_text(encoding="utf-8").splitlines()
    if not sidecar or sidecar[0].split()[0] != sha256_bytes(raw):
        problems.append("report .sha256 sidecar does not pin the persisted bytes")
    scope = report.get("scope", {})
    if scope.get("split") != MAIN_SPLIT or scope.get("consumed_splits") != list(CONSUMED_SPLITS):
        problems.append("the report must declare a TRAIN-only scope")
    if scope.get("validation_consumed") or scope.get("test_consumed"):
        problems.append("the report claims to have consumed a holdout split")
    guards = report.get("guards", {})
    if not guards.get("validation_recalibration_refused"):
        problems.append("the report does not prove that VALIDATION is never recalibrated")
    if report.get("retained_method") is None:
        problems.append("the report does not name a retained method")
    return problems


def check(path: str | Path = REPORT_PATH) -> list[str]:
    """Verify the persisted report; ``--check-full`` adds a full rebuild."""
    return verify_persisted(path)


def check_full(path: str | Path = REPORT_PATH) -> list[str]:
    """Re-verify the persisted report against a fresh TRAIN-only rebuild (~minutes)."""
    target = Path(path)
    problems = verify_persisted(target)
    if problems:
        return problems
    persisted = json.loads(target.read_text(encoding="utf-8"))
    scope = persisted.get("scope", {})
    protocol = persisted.get("protocol", {})
    config = protocol.get("model_config") if protocol.get("model_config_source") == "explicit" else None
    expected = build_report(
        scope.get("dataset", str(DEFAULT_DATASET)),
        folds=int(protocol.get("folds", harness.CV_FOLDS)),
        seed=int(protocol.get("seed", harness.CV_SEED)),
        architectures=protocol.get("architectures") or sorted(persisted.get("architectures", {})),
        methods=protocol.get("compared_methods", list(COMPARED_METHODS)),
        config=config,
        stride=int(scope.get("row_stride", 1)),
        fit_max_rows=int(protocol.get("calibration_fit_max_rows", CALIBRATION_FIT_MAX_ROWS)),
        strict_isotonic=bool(protocol.get("isotonic", {}).get("strict_mode", False)),
    )
    if persisted_report_text(persisted) != persisted_report_text(expected):
        problems.append("persisted report bytes diverge from a fresh TRAIN-only rebuild")
    return problems


def self_check(seed: int = harness.CV_SEED) -> dict[str, Any]:
    """Fast, dataset-independent end-to-end check (hand-grouped synthetic rows)."""
    rows = []
    for index, row in enumerate(grm.synthetic_rows(1200, seed)):
        rows.append(dict(row, hand_id=f"cal-hand-{index % 120:04d}"))
    report = run_calibration(
        rows,
        folds=3,
        seed=seed,
        config=grm.make_config(tuning_max_rows=400),
        fit_max_rows=3000,
    )
    return {
        "schema": SELF_CHECK_SCHEMA,
        "rows": len(rows),
        "hands": len({row["hand_id"] for row in rows}),
        "folds": report["protocol"]["folds"],
        "no_leak": report["protocol"]["no_leak"],
        "compared_methods": report["protocol"]["compared_methods"],
        "retained_methods_by_architecture": report["retained_methods_by_architecture"],
        "isotonic_admitted": {
            architecture: report["architectures"][architecture]["selection"]["evidence"][METHOD_ISOTONIC][
                "admissible"
            ]
            for architecture in report["architectures"]
        },
        "validation_consumed": False,
        "test_consumed": False,
        "static_scan": report["protocol"]["no_validation_recalibration"]["static_scan"]["result"],
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="#423 T2 - in-fold fitted / out-of-fold evaluated response calibration"
    )
    parser.add_argument("--self-check", action="store_true", help="run the dependency-free smoke check")
    parser.add_argument("--check", action="store_true", help="re-verify the persisted report")
    parser.add_argument(
        "--check-full",
        action="store_true",
        help="re-verify the persisted report and rebuild it from TRAIN (slow)",
    )
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--out", default=str(REPORT_PATH))
    parser.add_argument("--folds", type=int, default=harness.CV_FOLDS)
    parser.add_argument("--seed", type=int, default=harness.CV_SEED)
    parser.add_argument("--stride", type=int, default=1, help="deterministic TRAIN row stride (fast runs)")
    parser.add_argument("--architectures", nargs="+", default=list(grm.ARCHITECTURES))
    parser.add_argument("--methods", nargs="+", default=list(COMPARED_METHODS))
    parser.add_argument("--tuning-max-rows", type=int, default=None)
    parser.add_argument("--calibration-fit-max-rows", type=int, default=CALIBRATION_FIT_MAX_ROWS)
    parser.add_argument(
        "--strict-isotonic",
        action="store_true",
        help="fail closed instead of falling back when the isotonic support floor is missed",
    )
    parser.add_argument("--print", dest="print_only", action="store_true", help="print, do not write")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.self_check:
        print(json.dumps(_finalize(self_check(args.seed)), sort_keys=True, indent=2))
        return 0
    if args.check:
        problems = check(args.out)
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1 if problems else 0
    if args.check_full:
        problems = check_full(args.out)
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1 if problems else 0
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
        methods=args.methods,
        config=config,
        stride=args.stride,
        strict_isotonic=args.strict_isotonic,
        fit_max_rows=args.calibration_fit_max_rows,
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
                "retained_method": report["retained_method"],
                "retained_methods_by_architecture": report["retained_methods_by_architecture"],
            },
            sort_keys=True,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

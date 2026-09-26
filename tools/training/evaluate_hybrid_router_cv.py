#!/usr/bin/env python3
"""#423 T4 - cross-fitted TRAIN-only comparison and paired-dispersion derivation.

The module is the *evaluation* stage of the #423 hybrid router.  It compares,
on the same hand-grouped TRAIN cross-validation folds, three channels:

* the **active Model A reference** (``active_model_a_preflop_population``,
  the frozen combo-weighted public marginal reused from the #421 comparator);
* the **calibrated generalized channel** (the #421 response architecture fitted
  in-fold, then recalibrated in-fold with the #423 T2 method and scored
  out-of-fold);
* the **hybrid router** (the #423 T3 route decision: strong exact support asks
  the active reference, sparse in-domain support asks the calibrated
  generalized channel, everything else abstains).

For every channel and every stratum the run reports base-2 log loss, Brier,
expected calibration error, accuracy, coverage and abstain rate, with a
dedicated ``LIMPER_VS_ISO`` metric surface and a dedicated block of synthetic
out-of-domain probes.

The persisted artifact is a *derivation* run:
``analysis/issue423_hybrid_router/derivation/CV_DERIVATION.json`` (plus its
``.sha256`` sidecar).  It carries the paired-by-hand dispersion of the
hybrid-minus-reference log-loss delta, global and per stratum, the paired
confidence intervals and the effectifs every stratum contributed -- the inputs
the frozen #423 procedure needs to justify the global non-inferiority margin.
It never carries a value issued from a terminal evaluation.

Scientific boundary
-------------------
The harness consumes ``TRAIN`` only.  VALIDATION and TEST are refused
fail-closed: the loader is the #421 harness TRAIN-only reader, every parsed row
is asserted to be TRAIN, and :func:`verify_no_holdout_access` statically proves
the module names no holdout loader.  The hand-grouped split is the #421 one
(:func:`tools.training.evaluate_generalized_response_cv.grouped_folds`), so no
hand ever sits on both sides of a fold and the no-leak property is asserted at
runtime rather than promised.

Only the Python standard library and repository modules are used.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.preflop import generalized_response_calibration as calibration  # noqa: E402
from tools.preflop import generalized_response_model as model  # noqa: E402
from tools.preflop import generalized_response_runtime as runtime  # noqa: E402
from tools.preflop import hybrid_response_router as router  # noqa: E402
from tools.training import evaluate_generalized_response_cv as cv  # noqa: E402
from tools.training.evaluate_preflop_topology_candidate import (  # noqa: E402
    by_actor,
    find_closest,
)
from tools.training.preflop_policy169 import decode_policy169, hand_weights  # noqa: E402

MODULE_PATH = Path(__file__).resolve()

# ---------------------------------------------------------------------------
# layout and identity
# ---------------------------------------------------------------------------

HERE = ROOT / "analysis/issue423_hybrid_router"
DERIVATION_DIR = HERE / "derivation"
DERIVATION_NAME = "CV_DERIVATION.json"
DERIVATION_PATH = DERIVATION_DIR / DERIVATION_NAME
DIGEST_PATH = DERIVATION_DIR / "CV_DERIVATION.sha256"
SPEC_PATH = HERE / "HYBRID_ROUTER_SPEC.json"
CALIBRATION_REPORT_PATH = HERE / "GENERALIZED_CALIBRATION_REPORT.json"

SCHEMA = "poker-hybrid-router-train-cv/v1"
DERIVATION_SCHEMA = "poker-hybrid-router-cv-derivation/v1"
SELF_CHECK_SCHEMA = "poker-hybrid-router-train-cv-self-check/v1"

DEFAULT_DATASET = model.DEFAULT_DATASET

#: The harness consumes exactly one split; the two holdouts are refused.
MAIN_SPLIT = "TRAIN"
CONSUMED_SPLITS = ("TRAIN",)
REFUSED_SPLITS = ("VALIDATION", "TEST")
FORBIDDEN_SPLITS = model.FORBIDDEN_SPLITS

#: Hand-grouped folds reused verbatim from the #421 harness.
CV_FOLDS = cv.CV_FOLDS
CV_SEED = cv.CV_SEED

#: Preregistered #423 constants of the paired non-inferiority procedure.
BOOTSTRAP_SAMPLES = 2000
BOOTSTRAP_SEED = 423
NON_INFERIORITY_CONFIDENCE_LEVEL = 0.95
NON_INFERIORITY_UPPER_QUANTILE = 0.95
NON_INFERIORITY_ALPHA = 0.05
Z_ONE_SIDED_95 = 1.6448536269514722
BOOTSTRAP_QUANTILES = (0.025, 0.05, 0.5, 0.95, 0.975)
MARGIN_MAX_BITS = 0.0
MARGIN_ANALYTIC_TOLERANCE_BITS = 0.001

#: The three channels the harness scores side by side.
CHANNEL_ACTIVE = "active_model_a"
CHANNEL_GENERALIZED = "generalized_calibrated"
CHANNEL_HYBRID = "hybrid_router"
CHANNELS: tuple[str, ...] = (CHANNEL_ACTIVE, CHANNEL_GENERALIZED, CHANNEL_HYBRID)
CHANNEL_MODEL_ID: dict[str, str] = {
    CHANNEL_ACTIVE: "active_model_a_preflop_population",
    CHANNEL_GENERALIZED: "generalized_adverse_response_candidate_v1",
    CHANNEL_HYBRID: "hybrid_router",
}
CHANNEL_DEFINITION: dict[str, str] = {
    CHANNEL_ACTIVE: (
        "frozen combo-weighted public action marginal of active Model A v5, "
        "mapped onto the four response actions"
    ),
    CHANNEL_GENERALIZED: (
        "the #421 response architecture fitted on the fold's fit rows, "
        "recalibrated in-fold with the #423 T2 method and read out-of-fold"
    ),
    CHANNEL_HYBRID: (
        "the #423 T3 route decision: active reference on strong exact support, "
        "calibrated generalized channel on sparse in-domain support, abstain otherwise"
    ),
}

#: The route source -> channel mapping of the reference rule.
ROUTE_TO_CHANNEL: dict[str, str | None] = {
    router.ROUTE_SOURCE_ACTIVE: CHANNEL_ACTIVE,
    router.ROUTE_SOURCE_SPARSE: CHANNEL_GENERALIZED,
    router.ROUTE_SOURCE_ABSTAIN: None,
}

#: The stratum whose decisions the router abstains on; measured with probes.
OOD_STRATUM = model.OOD_STRATUM_EXACT_ABSENT_OUT_OF_DOMAIN
ADMISSION_STRATA: tuple[str, ...] = (
    model.OOD_STRATUM_FREQUENT_EXACT,
    model.OOD_STRATUM_RARE_EXACT,
    model.OOD_STRATUM_EXACT_ABSENT_IN_DOMAIN,
)

#: The family whose metric surface the ticket asks for separately.
LIMPER_VS_ISO_FAMILY = "LIMPER_VS_ISO"

#: Bounded, deterministic count of synthetic OOD probes per fold and kind.
PROBE_LIMIT = 32
PROBE_KINDS: tuple[str, ...] = (
    "unseen_category",
    "extrapolation_stack",
    "extrapolation_sizing",
    "missing_domain_axis",
)
PROBE_EXPECTED_REASON: dict[str, str] = {
    "unseen_category": "UNSEEN_CATEGORY",
    "extrapolation_stack": "EXTRAPOLATION_STACK",
    "extrapolation_sizing": "EXTRAPOLATION_SIZING",
    "missing_domain_axis": "MISSING_DOMAIN_AXIS",
}

#: Candidate never-seen actor labels used by the unseen-category probe.
PROBE_UNSEEN_LABELS: tuple[str, ...] = ("UTG", "MP", "EP", "X9")

#: The frozen comparator replicated here; pinned by byte digest.
ACTIVE_MODEL_PATH = ROOT / "training/models/preflop_population_model_v5.json"
ACTIVE_MODEL_SHA256 = "ff952055ca4ee051a3ac9607d513fdecac0a320a31f658ecfd8a11d8448975ca"
ACTIVE_REUSE_SOURCE = "tools/training/validate_generalized_response.py::active_public_distribution"

#: Exactly the decision fields the frozen comparator's neighbour search reads:
#: ``find_closest`` scores on actor / action / table size / raise level / family
#: / history / live and all-in sets, and ``continuous_penalty`` reads the pot
#: and the two stack / add fields.  Two rows that agree on every one of them
#: resolve to the same active node, which is what makes the memo sound.
ACTIVE_MATCH_FIELDS: tuple[str, ...] = (
    "actor_position",
    "action",
    "table_size",
    "raise_level",
    "family",
    "history",
    "live_positions",
    "all_in_positions",
    "pot_before_bb",
    "actor_start_stack_bb",
    "action_add_bb",
)


class HybridRouterCvError(RuntimeError):
    """Fail-closed error of the #423 T4 cross-fitted evaluation surface."""


# ---------------------------------------------------------------------------
# small deterministic helpers
# ---------------------------------------------------------------------------


def _round(value: Any, digits: int = 6) -> Any:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    number = float(value)
    if not math.isfinite(number):
        return None
    return round(number, digits)


def _finalize(value: Any) -> Any:
    """Recursively round floats so the artifact is deterministic and readable."""
    if isinstance(value, Mapping):
        return {key: _finalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finalize(item) for item in value]
    if isinstance(value, float):
        return _round(value)
    return value


def _mean(values: Sequence[float]) -> float:
    return math.fsum(values) / len(values) if values else 0.0


def _stddev(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = _mean(values)
    return math.sqrt(math.fsum((value - mean) ** 2 for value in values) / len(values))


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _relative(path: str | Path) -> str:
    resolved = Path(path).resolve()
    try:
        return str(resolved.relative_to(ROOT))
    except ValueError:  # pragma: no cover - a path outside the repository
        return str(resolved)


def percentile(values: Sequence[float], level: float) -> float:
    """Linear-interpolation percentile of an unsorted sequence."""
    if not values:
        return float("nan")
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * min(max(float(level), 0.0), 1.0)
    low = int(math.floor(position))
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


# ---------------------------------------------------------------------------
# fail-closed split guards (the acceptance criterion, checked not promised)
# ---------------------------------------------------------------------------


def row_split(row: Mapping[str, Any]) -> str:
    return str(row.get("split") or "").strip().upper()


def assert_train_only(rows: Iterable[Mapping[str, Any]], *, context: str) -> int:
    """Refuse any row whose split is not ``TRAIN``.

    ``VALIDATION`` is refused as loudly as ``TEST``: the historical holdout is
    the split the #423 procedure must never read, so a run that touched it would
    be a data-snooping defect rather than a missing feature.
    """
    checked = 0
    for index, row in enumerate(rows):
        split = row_split(row)
        if split in REFUSED_SPLITS:
            raise HybridRouterCvError(
                f"{context} refuses split {split}: the harness consumes {list(CONSUMED_SPLITS)} only"
            )
        if split != MAIN_SPLIT:
            raise HybridRouterCvError(
                f"{context} requires an explicit TRAIN row at position {index}, got {split!r}"
            )
        checked += 1
    return checked


def assert_consumed_splits(splits: Iterable[str], *, context: str) -> list[str]:
    """Refuse any requested split outside ``TRAIN`` before a byte is read."""
    wanted = [str(split).strip().upper() for split in splits]
    refused = [split for split in wanted if split != MAIN_SPLIT]
    if refused:
        raise HybridRouterCvError(
            f"{context} refuses the requested split(s) {refused}: "
            f"the harness consumes {list(CONSUMED_SPLITS)} only"
        )
    return wanted


def verify_no_holdout_access(source: str | None = None) -> dict[str, Any]:
    """Static proof that this module names no holdout loader.

    Mirrors the #423 T2 guard: the harness must not be *able* to read
    ``VALIDATION``/``TEST``, and the property is checked on the module source
    rather than promised in a comment.  The scanned symbol list is the frozen
    T2 one (:data:`tools.preflop.generalized_response_calibration.HOLDOUT_LOADER_SYMBOLS`).
    """
    text = Path(__file__).read_text(encoding="utf-8") if source is None else source
    tree = ast.parse(text)
    symbols = set(calibration.HOLDOUT_LOADER_SYMBOLS)
    hits: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in symbols:
            hits.append({"line": node.lineno, "symbol": node.attr, "kind": "attribute"})
        elif isinstance(node, ast.Name) and node.id in symbols:
            hits.append({"line": node.lineno, "symbol": node.id, "kind": "name"})
        elif isinstance(node, ast.keyword) and node.arg == "splits":
            for literal in ast.walk(node.value):
                if isinstance(literal, ast.Constant) and literal.value in REFUSED_SPLITS:
                    hits.append(
                        {
                            "line": literal.lineno,
                            "symbol": str(literal.value),
                            "kind": "splits_keyword",
                        }
                    )
    return {
        "result": "PASS" if not hits else "FAIL",
        "hits": hits,
        "scanned_module": _relative(MODULE_PATH),
        "consumed_splits": list(CONSUMED_SPLITS),
        "refused_splits": list(REFUSED_SPLITS),
        "forbidden_splits": list(FORBIDDEN_SPLITS),
    }


def read_train_rows(dataset: str | Path = DEFAULT_DATASET, *, stride: int = 1) -> list[dict[str, Any]]:
    """Read TRAIN through the #421 harness loader and re-assert the split."""
    rows = cv.read_train_rows(dataset, stride=stride)
    assert_train_only(rows, context="read_train_rows")
    return rows


# ---------------------------------------------------------------------------
# the frozen active Model A reference (reused by equivalence)
# ---------------------------------------------------------------------------


def load_active_reference(path: str | Path | None = None) -> dict[str, Any]:
    """Pin and load the frozen active Model A v5 reference and its index."""
    target = Path(path or ACTIVE_MODEL_PATH)
    digest = sha256_file(target)
    if digest != ACTIVE_MODEL_SHA256:
        raise HybridRouterCvError(
            "the active Model A v5 reference drifted: "
            f"{digest} != {ACTIVE_MODEL_SHA256}"
        )
    document = json.loads(target.read_text(encoding="utf-8"))
    grid = list((document.get("hand_grid") or {}).get("classes") or [])
    return {
        "path": _relative(target),
        "sha256": digest,
        "model_id": CHANNEL_MODEL_ID[CHANNEL_ACTIVE],
        "index": by_actor(document.get("nodes") or []),
        "grid": grid,
        "weights": hand_weights(grid, (document.get("hand_grid") or {}).get("meta")),
        "match_cache": {},
    }


def active_match_key(row: Mapping[str, Any]) -> tuple[Any, ...] | None:
    """Complete cache key of the frozen neighbour search, or ``None``.

    ``None`` means the row carries a field shape the key does not model (a
    nested structure inside ``history``), and the caller then computes the
    comparator without memoising.  The key is a superset of every decision
    field the frozen search reads, so two rows with the same key resolve to the
    same active node.
    """
    parts: list[Any] = []
    for field in ACTIVE_MATCH_FIELDS:
        value = row.get(field)
        if value is None or isinstance(value, (str, int, float, bool)):
            parts.append(value)
        elif isinstance(value, (list, tuple)):
            items: list[Any] = []
            for item in value:
                if item is None or isinstance(item, (str, int, float, bool)):
                    items.append(item)
                else:
                    return None
            parts.append(tuple(items))
        else:
            return None
    return tuple(parts)


def _map_reference_action(name: Any) -> str | None:
    """Map a comparator action label onto the public response action space."""
    text = str(name or "").strip().upper()
    if text == "LIMP":
        text = "CALL"
    return text if text in model.ACTION_INDEX else None


def _normalized(distribution: Mapping[str, float]) -> tuple[dict[str, float] | None, float]:
    """Normalize a mapped action mass onto the four response actions.

    Byte-identical to the frozen #421 helper: the mapped sums are accumulated
    in the comparator's own iteration order and the dropped mass is the deficit
    of the mapped mass against one.
    """
    mapped = {action: 0.0 for action in model.ACTIONS}
    for action, value in distribution.items():
        target = _map_reference_action(action)
        if target is None:
            continue
        mapped[target] += max(0.0, float(value or 0.0))
    total = sum(mapped.values())
    if total <= model.EPS:
        return None, 0.0
    dropped = max(0.0, 1.0 - total)
    return {action: mapped[action] / total for action in model.ACTIONS}, dropped


def active_public_distribution(
    reference: Mapping[str, Any], row: Mapping[str, Any]
) -> dict[str, Any]:
    """Marginal public action distribution of active Model A v5 at one decision.

    TRAIN-safe replication of the frozen #421 comparator
    (:data:`ACTIVE_REUSE_SOURCE`): the v5 node policy is hand-conditioned over
    the 169 hand classes, so the public comparator is the combo-weighted
    marginal over hands, mapped onto the response space (``LIMP`` -> ``CALL``)
    and renormalised on the four response actions.  The replication is pinned
    by an equivalence test against the original implementation.

    The neighbour search is the dominant cost of the whole harness, so a row
    whose :func:`active_match_key` was already resolved reuses the memoised
    answer: the key is complete for the search, and a dedicated guard asserts
    the memo reproduces the uncached comparator call for call.
    """
    cache = reference.get("match_cache")
    key = active_match_key(row) if isinstance(cache, dict) else None
    if key is not None and key in cache:
        cached = cache[key]
        return {**cached, "probabilities": dict(cached["probabilities"]) if cached["probabilities"] else None}

    match = find_closest(dict(reference["index"]), dict(row))
    if not match:
        answer = {"available": False, "probabilities": None, "reason": "NO_ACTIVE_NODE"}
        if key is not None:
            cache[key] = answer
        return dict(answer)
    node = match["node"]
    raw: dict[str, float] = {}
    try:
        policy = decode_policy169(node, reference["grid"])
        for hand, weight in reference["weights"].items():
            entry = policy.get(hand) or {}
            for action, value in entry.items():
                raw[action] = raw.get(action, 0.0) + float(weight) * float(value)
        source = "POLICY169_COMBO_WEIGHTED"
    except (ValueError, TypeError, KeyError):
        frequencies = (node.get("population_model") or {}).get("frequencies") or {}
        raw = {str(action): float(value or 0.0) for action, value in frequencies.items()}
        source = "MARGINAL_FREQUENCY"
    probabilities, dropped = _normalized(raw)
    if probabilities is None:
        answer = {"available": False, "probabilities": None, "reason": "ACTIVE_NODE_EMPTY"}
        if key is not None:
            cache[key] = answer
        return dict(answer)
    answer = {
        "available": True,
        "probabilities": probabilities,
        "exact": bool(match.get("exact")),
        "source": source,
        "dropped_non_response_mass": dropped,
    }
    if key is not None:
        cache[key] = answer
    return {**answer, "probabilities": dict(probabilities)}


# ---------------------------------------------------------------------------
# per-row channels
# ---------------------------------------------------------------------------


def _canonical_channel(
    probabilities: Mapping[str, Any] | None,
    legal: Sequence[str],
) -> tuple[dict[str, float], list[str], float]:
    """Quantise a channel answer onto the runtime's legal grid."""
    vector, _probability_sum, illegal_mass = runtime.canonical_legal_distribution(
        probabilities or {}, legal
    )
    masked = [action for action in model.ACTIONS if action not in set(legal)]
    return vector, masked, illegal_mass


def _entry(
    probabilities: Mapping[str, Any] | None,
    legal: Sequence[str],
    *,
    answered: bool,
    reason: str | None,
) -> dict[str, Any]:
    if not answered or probabilities is None:
        return {
            "answered": False,
            "probabilities": None,
            "masked_actions": [],
            "reason": reason,
        }
    vector, masked, _illegal_mass = _canonical_channel(probabilities, legal)
    return {
        "answered": True,
        "probabilities": vector,
        "masked_actions": masked,
        "reason": reason,
    }


def _store_probabilities(store: Any, offset: int) -> dict[str, float]:
    base = offset * len(model.ACTIONS)
    return {
        action: float(store.probabilities[base + index])
        for index, action in enumerate(model.ACTIONS)
    }


# ---------------------------------------------------------------------------
# synthetic out-of-domain probes
# ---------------------------------------------------------------------------


def _probe_sample(rows: Sequence[Mapping[str, Any]], limit: int) -> list[Mapping[str, Any]]:
    if not rows:
        return []
    stride = max(1, len(rows) // int(limit))
    return list(rows[::stride][: int(limit)])


def synthetic_ood_probes(
    rows: Sequence[Mapping[str, Any]],
    calibration_document: Mapping[str, Any],
    *,
    limit: int = PROBE_LIMIT,
) -> list[dict[str, Any]]:
    """Deterministic out-of-domain probes built from the fold's fit rows.

    Each probe is a single-feature or numeric perturbation of an observed
    TRAIN row that the frozen gate must answer with a hard reason, so the router
    abstains.  Nothing here reads a holdout split: the probes are derived from
    the calibration domain of the fit fold only.
    """
    counts = calibration_document.get("category_counts") or {}
    domain = calibration_document.get("domain") or {}
    known_actors = set((counts.get("actor_position") or {}))
    unseen_actor = next(
        (label for label in PROBE_UNSEEN_LABELS if label not in known_actors), PROBE_UNSEEN_LABELS[-1]
    )
    stack_stats = dict(domain.get("effective_stack_bb") or {})
    sizing_stats = dict(domain.get(model.OOD_SIZING_AXIS) or {})

    probes: list[dict[str, Any]] = []
    for index, row in enumerate(_probe_sample(rows, limit)):
        base = dict(row)
        base["split"] = MAIN_SPLIT

        unseen = dict(base)
        unseen["actor_position"] = unseen_actor
        probes.append(
            {"probe_kind": "unseen_category", "probe_index": index, "context": unseen}
        )

        stack_max = stack_stats.get("trained_max")
        if stack_max is not None:
            extrapolated = dict(base)
            extrapolated["effective_stack_bb"] = float(stack_max) + 1.0e4
            probes.append(
                {
                    "probe_kind": "extrapolation_stack",
                    "probe_index": index,
                    "context": extrapolated,
                }
            )

        sizing_max = sizing_stats.get("trained_max")
        to_call = base.get("to_call_bb")
        pot = base.get("pot_before_bb")
        if sizing_max is not None and to_call is not None and pot is not None:
            denominator = float(pot) + float(to_call)
            if denominator > model.EPS:
                extrapolated = dict(base)
                extrapolated["target_total_bb"] = (float(sizing_max) + 10.0) * denominator
                probes.append(
                    {
                        "probe_kind": "extrapolation_sizing",
                        "probe_index": index,
                        "context": extrapolated,
                    }
                )

        missing = dict(base)
        missing.pop("pot_before_bb", None)
        missing.pop("pot_odds", None)
        missing.pop("price_to_pot", None)
        probes.append(
            {"probe_kind": "missing_domain_axis", "probe_index": index, "context": missing}
        )
    return probes


def evaluate_probes(
    probes: Sequence[Mapping[str, Any]],
    *,
    fold: int,
    calibration_document: Mapping[str, Any],
    model_candidate: Mapping[str, Any] | None,
    reference: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Score every probe: the router must abstain on all of them."""
    results: list[dict[str, Any]] = []
    for probe in probes:
        context = dict(probe["context"])
        signals = router.compute_signals(
            context, calibration=calibration_document, model_candidate=model_candidate
        )
        source = router.route_source(signals)
        expected = PROBE_EXPECTED_REASON[str(probe["probe_kind"])]
        legal = model.legal_response_actions(context)
        active = active_public_distribution(reference, context)
        results.append(
            {
                "probe_kind": str(probe["probe_kind"]),
                "hand_id": (
                    f"probe-{probe['probe_kind']}-f{int(fold):02d}-{int(probe['probe_index']):04d}"
                ),
                "fold": int(fold),
                "observed": str(context.get("action") or "").strip().upper(),
                "family": str(context.get("family") or "").strip().upper(),
                "actor_position": str(context.get("actor_position") or "").strip().upper(),
                "stratum": signals["stratum"],
                "ood_status": signals["ood_status"],
                "route_source": source,
                "hard_reasons": list(signals["hard_reasons"]),
                "expected_reason": expected,
                "expected_reason_present": expected in set(signals["hard_reasons"]),
                "channels": {
                    CHANNEL_ACTIVE: _entry(
                        active.get("probabilities"),
                        legal,
                        answered=bool(active.get("available")),
                        reason=active.get("reason"),
                    ),
                    CHANNEL_GENERALIZED: _entry(None, legal, answered=False, reason="not_queried"),
                    CHANNEL_HYBRID: _entry(
                        None,
                        legal,
                        answered=False,
                        reason=(
                            "route_abstained"
                            if source == router.ROUTE_SOURCE_ABSTAIN
                            else "route_answered_without_channel"
                        ),
                    ),
                },
            }
        )
    return results


# ---------------------------------------------------------------------------
# metric surfaces
# ---------------------------------------------------------------------------


def _scored(record: Mapping[str, Any], channel: str) -> dict[str, Any] | None:
    entry = (record.get("channels") or {}).get(channel)
    if not entry or not entry.get("answered"):
        return None
    return {
        "observed": str(record["observed"]),
        "probabilities": dict(entry["probabilities"]),
        "masked_actions": list(entry.get("masked_actions") or []),
    }


def _metrics(records: Sequence[Mapping[str, Any]], channel: str, prior: Mapping[str, float]) -> dict[str, Any]:
    scored = [value for value in (_scored(record, channel) for record in records) if value]
    if not scored:
        return {
            "n": 0,
            "log_loss_bits_per_decision": None,
            "baseline_log_loss_bits_per_decision": None,
            "gain_bits_per_decision": None,
            "brier_score": None,
            "accuracy": None,
            "expected_calibration_error": None,
            "calibration_claim_supportable": False,
            "observed_action_counts": None,
            "probability_sum_max_abs_error": None,
            "illegal_mass_max": None,
        }
    summary = cv.summary_metrics(scored, prior)
    ece = summary["expected_calibration_error"]
    return {
        "n": summary["n"],
        "log_loss_bits_per_decision": summary["log_loss_bits_per_decision"],
        "baseline_log_loss_bits_per_decision": summary["baseline_log_loss_bits_per_decision"],
        "gain_bits_per_decision": summary["gain_bits_per_decision"],
        "brier_score": summary["brier_score"],
        "accuracy": summary["accuracy"],
        "expected_calibration_error": ece["ece"],
        "calibration_claim_supportable": bool(ece["claim_supportable"]),
        "calibration_bins_meeting_minimum_support": ece["bins_meeting_minimum_support"],
        "observed_action_counts": summary["observed_action_counts"],
        "probability_sum_max_abs_error": summary["probability_sum_max_abs_error"],
        "illegal_mass_max": summary["illegal_mass_max"],
    }


def _coverage(records: Sequence[Mapping[str, Any]], channel: str) -> dict[str, Any]:
    total = len(records)
    answered = sum(
        1
        for record in records
        if (record.get("channels") or {}).get(channel, {}).get("answered")
    )
    return {
        "n": total,
        "answered": answered,
        "abstained": total - answered,
        "coverage": (answered / total) if total else None,
        "abstain_rate": ((total - answered) / total) if total else None,
        "distinct_hands_answered": len(
            {
                str(record["hand_id"])
                for record in records
                if (record.get("channels") or {}).get(channel, {}).get("answered")
            }
        ),
    }


def channel_block(
    records: Sequence[Mapping[str, Any]],
    channel: str,
    prior: Mapping[str, float],
) -> dict[str, Any]:
    """Full metric surface of one channel over a record set."""
    block: dict[str, Any] = {
        "model_id": CHANNEL_MODEL_ID[channel],
        "definition": CHANNEL_DEFINITION[channel],
        "scope": _coverage(records, channel),
        "metrics": _metrics(records, channel, prior),
        "by_stratum_note": (
            "held-out TRAIN decisions only; the OOD stratum's synthetic-probe surface is "
            "published in per_stratum and ood_synthetic_probes"
        ),
        "by_stratum": {
            stratum: {
                "scope": _coverage([row for row in records if row["stratum"] == stratum], channel),
                "metrics": _metrics(
                    [row for row in records if row["stratum"] == stratum], channel, prior
                ),
            }
            for stratum in (*ADMISSION_STRATA, OOD_STRATUM)
        },
        "limper_vs_iso": _family_block(records, channel, prior, LIMPER_VS_ISO_FAMILY),
    }
    if channel == CHANNEL_HYBRID:
        block["route_source_counts"] = _route_counts(records)
    return block


def _family_block(
    records: Sequence[Mapping[str, Any]],
    channel: str,
    prior: Mapping[str, float],
    family: str,
) -> dict[str, Any]:
    members = [row for row in records if str(row.get("family") or "") == family]
    return {
        "family": family,
        "scope": _coverage(members, channel),
        "metrics": _metrics(members, channel, prior),
    }


def _route_counts(records: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = {source: 0 for source in router.ROUTE_SOURCES}
    for record in records:
        source = str(record.get("route_source") or "")
        if source in counts:
            counts[source] += 1
    return counts


def strata_block(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Effectifs and shares of every frozen stratum over a record set."""
    total = len(records)
    counts = {
        stratum: sum(1 for record in records if record["stratum"] == stratum)
        for stratum in (*ADMISSION_STRATA, OOD_STRATUM)
    }
    return {
        "definition": (
            "frozen #423 strata: frequent_exact (exact-cell support >= "
            f"{router.FREQUENT_EXACT_MIN_SUPPORT}), rare_exact (0 < support < "
            f"{router.FREQUENT_EXACT_MIN_SUPPORT}), exact_absent_in_domain (support == 0, every "
            "single-feature label observed in the fit fold) and exact_absent_out_of_domain "
            "(support == 0 with at least one unseen feature value)"
        ),
        "source_module_symbol": "tools/preflop/hybrid_response_router.py::compute_signals",
        "frequent_exact_min_support": router.FREQUENT_EXACT_MIN_SUPPORT,
        "rare_exact_min_support": router.RARE_EXACT_MIN_SUPPORT,
        "counts": counts,
        "shares": {
            stratum: ((counts[stratum] / total) if total else None)
            for stratum in counts
        },
        "rows": total,
        "hands": len({str(record["hand_id"]) for record in records}),
    }


# ---------------------------------------------------------------------------
# paired bootstrap dispersion (the derivation statistic)
# ---------------------------------------------------------------------------


def paired_bootstrap(
    pairs: Sequence[Mapping[str, Any]],
    *,
    samples: int = BOOTSTRAP_SAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Paired percentile bootstrap of a per-hand replicated mean delta.

    ``pairs`` carries one ``delta_nll`` per scored decision and the ``hand_id``
    it belongs to.  Every resample draws ``len(hands)`` hands with replacement
    (the paired unit) and averages the deltas of every drawn hand, so decisions
    of the same hand stay together and a hand never splits across a resample.
    """
    grouped: dict[str, list[float]] = defaultdict(list)
    for pair in pairs:
        grouped[str(pair["hand_id"])].append(float(pair["delta_nll"]))
    hands = sorted(grouped)
    rows = len(pairs)
    empty = {
        "rows": rows,
        "hands": len(hands),
        "decisions_per_hand": None,
        "samples": int(samples),
        "seed": int(seed),
        "point_estimate_bits_per_decision": None,
        "bootstrap_stddev_bits_per_decision": None,
        "bootstrap_variance_bits_squared": None,
        "quantiles": {str(level): None for level in BOOTSTRAP_QUANTILES},
        "ci95": [None, None],
        "ci90": [None, None],
        "upper_quantile_level": NON_INFERIORITY_UPPER_QUANTILE,
        "upper_quantile_bits_per_decision": None,
        "probability_hybrid_non_degrading": None,
        "analytic": {
            "standard_error_bits_per_decision": None,
            "z_one_sided_95": Z_ONE_SIDED_95,
            "margin_analytic_bits_per_decision": None,
        },
    }
    if not hands:
        return empty

    hand_count = len(hands)
    # Precompute the per-hand sufficient statistics: the resample loop then
    # draws the same hand indices in the same order and accumulates the same
    # terms, so the draws are byte-identical to a direct grouping loop while
    # avoiding a dict lookup and a ``math.fsum`` per drawn hand.
    hand_sums = [math.fsum(grouped[hand]) for hand in hands]
    hand_counts = [len(grouped[hand]) for hand in hands]
    rng = random.Random(int(seed))
    draws: list[float] = []
    for _ in range(int(samples)):
        total = 0.0
        count = 0
        for _slot in range(hand_count):
            position = rng.randrange(hand_count)
            total += hand_sums[position]
            count += hand_counts[position]
        draws.append(total / max(1, count))

    point = math.fsum(float(pair["delta_nll"]) for pair in pairs) / rows
    # Closed-form counterpart of the resample: the resampled statistic is the
    # pooled ratio (sum of the drawn hands' deltas) / (sum of their decision
    # counts), so the matching standard error is the delta-method cluster error
    # of that ratio, ``sqrt(Var_h(S_h - R * n_h) / hands) / mean_n``, where ``S_h``
    # and ``n_h`` are one hand's delta sum and decision count.
    mean_count = rows / hand_count
    residuals = [
        hand_sums[position] - point * hand_counts[position] for position in range(hand_count)
    ]
    standard_error = _stddev(residuals) / math.sqrt(hand_count) / mean_count
    quantiles = {str(level): percentile(draws, level) for level in BOOTSTRAP_QUANTILES}
    upper = quantiles[str(NON_INFERIORITY_UPPER_QUANTILE)]
    return {
        "rows": rows,
        "hands": hand_count,
        "decisions_per_hand": (rows / hand_count) if hand_count else None,
        "samples": int(samples),
        "seed": int(seed),
        "point_estimate_bits_per_decision": point,
        "bootstrap_stddev_bits_per_decision": _stddev(draws),
        "bootstrap_variance_bits_squared": _stddev(draws) ** 2,
        "quantiles": quantiles,
        "ci95": [quantiles["0.025"], quantiles["0.975"]],
        "ci90": [quantiles["0.05"], quantiles["0.95"]],
        "upper_quantile_level": NON_INFERIORITY_UPPER_QUANTILE,
        "upper_quantile_bits_per_decision": upper,
        "probability_hybrid_non_degrading": sum(1 for value in draws if value <= 0.0) / len(draws),
        "analytic": {
            "standard_error_bits_per_decision": standard_error,
            "z_one_sided_95": Z_ONE_SIDED_95,
            "margin_analytic_bits_per_decision": point + Z_ONE_SIDED_95 * standard_error,
        },
    }


def paired_comparison(
    records: Sequence[Mapping[str, Any]],
    left: str,
    right: str,
    *,
    samples: int = BOOTSTRAP_SAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Paired ``left - right`` log-loss delta over the decisions both answer."""
    pairs: list[dict[str, Any]] = []
    excluded = 0
    for record in records:
        left_entry = _scored(record, left)
        right_entry = _scored(record, right)
        if left_entry is None or right_entry is None:
            excluded += 1
            continue
        observed = str(record["observed"])
        pairs.append(
            {
                "hand_id": str(record["hand_id"]),
                "delta_nll": (
                    -math.log2(max(float(left_entry["probabilities"].get(observed, 0.0)), model.PROBABILITY_FLOOR))
                    + math.log2(max(float(right_entry["probabilities"].get(observed, 0.0)), model.PROBABILITY_FLOOR))
                ),
            }
        )
    block = paired_bootstrap(pairs, samples=samples, seed=seed)
    block["left"] = left
    block["right"] = right
    block["excluded_decisions"] = excluded
    block["comparison"] = f"{left}_minus_{right}"
    return block


def paired_block(
    records: Sequence[Mapping[str, Any]],
    left: str,
    right: str,
    *,
    samples: int = BOOTSTRAP_SAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Paired comparison global, per stratum and on ``LIMPER_VS_ISO``."""
    admission = [row for row in records if row["stratum"] in ADMISSION_STRATA]
    return {
        "definition": (
            "mean per-decision base-2 log-loss delta of the left channel minus the right "
            "channel, paired by hand_id, over the decisions both channels answer"
        ),
        "direction": "lower_is_better",
        "paired_unit": "hand_id",
        "left": left,
        "right": right,
        "global": paired_comparison(records, left, right, samples=samples, seed=seed),
        "admission_support": paired_comparison(admission, left, right, samples=samples, seed=seed),
        "by_stratum": {
            stratum: paired_comparison(
                [row for row in records if row["stratum"] == stratum],
                left,
                right,
                samples=samples,
                seed=seed,
            )
            for stratum in (*ADMISSION_STRATA, OOD_STRATUM)
        },
        "limper_vs_iso": paired_comparison(
            [row for row in records if str(row.get("family") or "") == LIMPER_VS_ISO_FAMILY],
            left,
            right,
            samples=samples,
            seed=seed,
        ),
    }


# ---------------------------------------------------------------------------
# the cross-fitted run
# ---------------------------------------------------------------------------


def _configured_architecture() -> str:
    """The architecture the #423 T2 report retained for the generalised channel."""
    if CALIBRATION_REPORT_PATH.exists():
        report = json.loads(CALIBRATION_REPORT_PATH.read_text(encoding="utf-8"))
        retained = report.get("retained_architecture")
        if retained in model.ARCHITECTURES:
            return str(retained)
    selected = calibration.harness_selected_architecture()
    if selected in model.ARCHITECTURES:
        return str(selected)
    return model.ARCH_REGULARIZED


def _configured_method() -> str:
    """The calibration method the #423 T2 report retained."""
    if CALIBRATION_REPORT_PATH.exists():
        report = json.loads(CALIBRATION_REPORT_PATH.read_text(encoding="utf-8"))
        retained = report.get("retained_method")
        if retained in calibration.COMPARED_METHODS:
            return str(retained)
    return calibration.METHOD_ISOTONIC


def run_cross_validation(
    rows: Iterable[Mapping[str, Any]],
    *,
    folds: int = CV_FOLDS,
    seed: int = CV_SEED,
    rule: str | router.RouteRule | None = None,
    architecture: str | None = None,
    method: str | None = None,
    config: Mapping[str, Any] | None = None,
    fit_max_rows: int = calibration.CALIBRATION_FIT_MAX_ROWS,
    reference: Mapping[str, Any] | None = None,
    probe_limit: int = PROBE_LIMIT,
    samples: int = BOOTSTRAP_SAMPLES,
    bootstrap_seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Hand-grouped TRAIN cross-validation of the three #423 channels."""
    materialized = list(rows)
    assert_train_only(materialized, context="run_cross_validation")
    if not materialized:
        raise HybridRouterCvError("no TRAIN rows to cross-validate")

    architecture = str(architecture or _configured_architecture())
    method = str(method or _configured_method())
    if architecture not in model.ARCHITECTURES:
        raise HybridRouterCvError(f"unknown architecture {architecture!r}")
    if method not in calibration.COMPARED_METHODS:
        raise HybridRouterCvError(f"unknown calibration method {method!r}")
    resolved_rule = router.route_rule(rule)
    reference = dict(reference) if reference is not None else load_active_reference()

    split = cv.grouped_folds(materialized, folds=folds, seed=seed)
    no_leak = cv.no_leak_proof(split)
    if not no_leak["holdout_hands_pairwise_disjoint"] or no_leak["max_hand_overlap_between_fit_and_holdout"] != 0:
        raise HybridRouterCvError("hand-grouped split leaked a hand across folds")

    records: list[dict[str, Any]] = []
    probe_records: list[dict[str, Any]] = []
    fold_summaries: list[dict[str, Any]] = []
    prior: dict[str, float] = {}
    calibration_admitted = 0

    for split_fold in split:
        fold = calibration.Fold(
            split_fold,
            architecture,
            seed=seed,
            config=config,
            methods=(method,),
            strict_isotonic=False,
            fit_max_rows=fit_max_rows,
        )
        prior = dict(fold.prior)
        candidate = fold.candidate
        store = fold.stores.get(method) or fold.stores[calibration.METHOD_UNCALIBRATED]
        if fold.stores.get(method) is not None:
            calibration_admitted += 1
        calibration_document = router.build_calibration(split_fold.train_rows)

        for offset, row in enumerate(split_fold.holdout_rows):
            legal = model.legal_response_actions(row)
            signals = router.compute_signals(
                row, calibration=calibration_document, model_candidate=candidate
            )
            source = resolved_rule(signals)
            active = active_public_distribution(reference, row)
            generalized = _store_probabilities(store, offset)

            hybrid_entry = {
                router.ROUTE_SOURCE_ACTIVE: _entry(
                    active.get("probabilities"),
                    legal,
                    answered=bool(active.get("available")),
                    reason=active.get("reason") or "active_reference",
                ),
                router.ROUTE_SOURCE_SPARSE: _entry(
                    generalized, legal, answered=True, reason="calibrated_generalized_channel"
                ),
                router.ROUTE_SOURCE_ABSTAIN: _entry(
                    None, legal, answered=False, reason="route_abstained"
                ),
            }[source]

            records.append(
                {
                    "fold": split_fold.index,
                    "hand_id": str(row.get("hand_id") or "").strip(),
                    "observed": str(row.get("action") or "").strip().upper(),
                    "family": str(row.get("family") or "").strip().upper(),
                    "actor_position": str(row.get("actor_position") or "").strip().upper(),
                    "stratum": signals["stratum"],
                    "ood_status": signals["ood_status"],
                    "route_source": source,
                    "support_exact": int(signals["support_exact"]),
                    "feature_in_domain": bool(signals["feature_in_domain"]),
                    "channels": {
                        CHANNEL_ACTIVE: _entry(
                            active.get("probabilities"),
                            legal,
                            answered=bool(active.get("available")),
                            reason=active.get("reason") or "active_reference",
                        ),
                        CHANNEL_GENERALIZED: _entry(
                            generalized, legal, answered=True, reason="calibrated_generalized_channel"
                        ),
                        CHANNEL_HYBRID: hybrid_entry,
                    },
                }
            )

        probe_records.extend(
            evaluate_probes(
                synthetic_ood_probes(split_fold.train_rows, calibration_document, limit=probe_limit),
                fold=split_fold.index,
                calibration_document=calibration_document,
                model_candidate=candidate,
                reference=reference,
            )
        )
        fold_summaries.append(
            {
                **split_fold.summary(),
                "calibration_method": method,
                "calibration_admitted": bool(fold.stores.get(method) is not None),
                "architecture": architecture,
                "route_source_counts": _route_counts(
                    [record for record in records if record["fold"] == split_fold.index]
                ),
            }
        )

    return {
        "protocol": {
            "kind": "train_only_hand_grouped_cross_fitted_channel_comparison",
            "main_split": MAIN_SPLIT,
            "consumed_splits": list(CONSUMED_SPLITS),
            "refused_splits": list(REFUSED_SPLITS),
            "forbidden_splits": list(FORBIDDEN_SPLITS),
            "group_key": "hand_id",
            "folds": int(folds),
            "seed": int(seed),
            "fold_assignment": (
                f"int(stable_hash('grm-cv/{int(seed)}/<hand_id>')[:8], 16) % {int(folds)}"
            ),
            "reused_harness_module": _relative(Path(cv.__file__)),
            "reused_harness_module_sha256": sha256_file(Path(cv.__file__)),
            "calibration_module": _relative(Path(calibration.__file__)),
            "calibration_module_sha256": sha256_file(Path(calibration.__file__)),
            "router_module": _relative(Path(router.__file__)),
            "router_module_sha256": sha256_file(Path(router.__file__)),
            "architecture": architecture,
            "calibration_method": method,
            "calibration_fit_max_rows": int(fit_max_rows),
            "route_rule": resolved_rule.as_document(),
            "channels": list(CHANNELS),
            "route_to_channel": {key: value for key, value in sorted(ROUTE_TO_CHANNEL.items())},
            "active_reference": {
                "model_id": reference["model_id"],
                "path": reference["path"],
                "sha256": reference["sha256"],
                "reuse_source": ACTIVE_REUSE_SOURCE,
            },
            "no_leak": no_leak,
            "metrics": {
                "log_loss_bits_per_decision": "mean -log2 P(observed action), base-2 bits per decision",
                "baseline_log_loss_bits_per_decision": "same loss under the fit-fold action prior",
                "brier_score": "mean sum over the four actions of (P(action) - 1[observed])^2",
                "accuracy": "mean arg-max agreement",
                "expected_calibration_error": cv.CALIBRATION_DEFINITION,
                "coverage": "share of decisions the channel answers with a legal, non-abstaining distribution",
                "abstain_rate": "1 - coverage",
            },
            "paired_bootstrap": {
                "method": "paired_percentile_bootstrap",
                "paired_unit": "hand_id",
                "samples": int(samples),
                "seed": int(bootstrap_seed),
                "confidence_level": NON_INFERIORITY_CONFIDENCE_LEVEL,
                "upper_quantile": NON_INFERIORITY_UPPER_QUANTILE,
                "alpha": NON_INFERIORITY_ALPHA,
                "quantiles": list(BOOTSTRAP_QUANTILES),
            },
            "ood_probes": {
                "kinds": list(PROBE_KINDS),
                "expected_reason": dict(PROBE_EXPECTED_REASON),
                "source": "synthetic perturbations of the fold's fit rows",
                "limit_per_kind_per_fold": int(probe_limit),
            },
            "prior": dict(prior),
        },
        "folds": fold_summaries,
        "calibration_admitted_folds": calibration_admitted,
        "records": records,
        "probes": probe_records,
    }


# ---------------------------------------------------------------------------
# the derivation artifact
# ---------------------------------------------------------------------------


def _probe_block(probes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    total = len(probes)
    kinds: dict[str, Any] = {}
    for kind in PROBE_KINDS:
        members = [probe for probe in probes if probe["probe_kind"] == kind]
        abstained = sum(1 for probe in members if probe["route_source"] == router.ROUTE_SOURCE_ABSTAIN)
        stratum_counts: dict[str, int] = {}
        for probe in members:
            stratum = str(probe["stratum"])
            stratum_counts[stratum] = stratum_counts.get(stratum, 0) + 1
        kinds[kind] = {
            "n": len(members),
            "expected_reason": PROBE_EXPECTED_REASON[kind],
            "expected_reason_present": all(probe["expected_reason_present"] for probe in members)
            if members
            else None,
            "router_abstained": abstained,
            "abstain_rate": (abstained / len(members)) if members else None,
            "stratum_counts": stratum_counts,
        }
    routed = sum(1 for probe in probes if probe["route_source"] == router.ROUTE_SOURCE_ABSTAIN)
    unseen = [probe for probe in probes if probe["probe_kind"] == "unseen_category"]
    return {
        "definition": (
            "synthetic out-of-domain probes perturbing a fold's fit rows into a never-seen "
            "category (the frozen OOD stratum) or past the calibrated numeric envelope (a hard "
            "extrapolation reason); the router must fail closed on every one of them"
        ),
        "n": total,
        "router_abstained": routed,
        "abstain_rate": (routed / total) if total else None,
        "coverage": (0.0 if total else None),
        "by_kind": kinds,
        "ood_stratum_probe_kind": "unseen_category",
        "ood_stratum_probes": len(unseen),
        "assertions": {
            "every_probe_carries_its_hard_reason": all(
                probe["expected_reason_present"] for probe in probes
            )
            if probes
            else False,
            "router_abstains_on_every_probe": total > 0 and routed == total,
            "unseen_category_probes_are_the_ood_stratum": bool(unseen)
            and all(probe["stratum"] == OOD_STRATUM for probe in unseen),
        },
        "channels": {
            channel: {
                "coverage": (
                    sum(
                        1
                        for probe in probes
                        if (probe.get("channels") or {}).get(channel, {}).get("answered")
                    )
                    / total
                )
                if total
                else None,
                "abstain_rate": (
                    sum(
                        1
                        for probe in probes
                        if not (probe.get("channels") or {}).get(channel, {}).get("answered")
                    )
                    / total
                )
                if total
                else None,
            }
            for channel in CHANNELS
        },
    }


def _stratum_surface(
    records: Sequence[Mapping[str, Any]],
    probes: Sequence[Mapping[str, Any]],
    prior: Mapping[str, float],
    *,
    paired: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Per-stratum metric surface; the OOD stratum is measured with its probes."""
    surface: dict[str, Any] = {}
    for stratum in ADMISSION_STRATA:
        members = [row for row in records if row["stratum"] == stratum]
        surface[stratum] = {
            "source": "held_out_train_decisions",
            "n": len(members),
            "hands": len({str(row["hand_id"]) for row in members}),
            "models": {
                channel: {
                    "coverage": _coverage(members, channel),
                    "metrics": _metrics(members, channel, prior),
                }
                for channel in CHANNELS
            },
            "paired": {
                name: block["by_stratum"][stratum]
                for name, block in paired.items()
            },
        }
    # The OOD stratum is measured on the probes that are *in* it: the
    # never-seen-category probes flip the in-domain verdict, so their stratum is
    # the frozen ``exact_absent_out_of_domain`` one.  The extrapolation and
    # missing-axis probes keep their own stratum and are reported in the probe
    # block, where they prove the hard-reason abstention instead.
    ood_probes = [probe for probe in probes if probe["probe_kind"] == "unseen_category"]
    real_ood = [row for row in records if row["stratum"] == OOD_STRATUM]
    answered = {
        channel: sum(
            1
            for probe in ood_probes
            if (probe.get("channels") or {}).get(channel, {}).get("answered")
        )
        for channel in CHANNELS
    }
    surface[OOD_STRATUM] = {
        "source": "synthetic_probes:unseen_category",
        "n": len(ood_probes),
        "hands": len({str(probe["hand_id"]) for probe in ood_probes}),
        "probe_block": _probe_block(probes),
        "models": {
            channel: {
                "coverage": {
                    "n": len(ood_probes),
                    "answered": answered[channel],
                    "abstained": len(ood_probes) - answered[channel],
                    "coverage": (answered[channel] / len(ood_probes)) if ood_probes else None,
                    "abstain_rate": (
                        (len(ood_probes) - answered[channel]) / len(ood_probes)
                    )
                    if ood_probes
                    else None,
                },
                "metrics": _metrics([], channel, prior),
            }
            for channel in CHANNELS
        },
        "real_holdout_decisions": {
            "n": len(real_ood),
            "hands": len({str(row["hand_id"]) for row in real_ood}),
            "route_source_counts": _route_counts(real_ood),
        },
    }
    return surface


def _margin_derivation(
    paired: Mapping[str, Any],
    *,
    samples: int,
    bootstrap_seed: int,
) -> dict[str, Any]:
    """The paired dispersion the frozen #423 margin procedure consumes."""
    admission = paired["admission_support"]
    analytic = admission["analytic"]
    bootstrap_upper = admission["upper_quantile_bits_per_decision"]
    analytic_margin = analytic["margin_analytic_bits_per_decision"]
    difference = (
        abs(float(analytic_margin) - float(bootstrap_upper))
        if bootstrap_upper is not None and analytic_margin is not None
        else None
    )
    return {
        "derives": "margin_global",
        "statistic": (
            "one-sided upper percentile of the paired-by-hand bootstrap of "
            "mean(log_loss_hybrid - log_loss_active) on the TRAIN out-of-fold admission support"
        ),
        "constant_refs": {
            "BOOTSTRAP_SAMPLES": int(samples),
            "BOOTSTRAP_SEED": int(bootstrap_seed),
            "NON_INFERIORITY_UPPER_QUANTILE": NON_INFERIORITY_UPPER_QUANTILE,
            "Z_ONE_SIDED_95": Z_ONE_SIDED_95,
            "MARGIN_MAX_BITS": MARGIN_MAX_BITS,
            "MARGIN_ANALYTIC_TOLERANCE_BITS": MARGIN_ANALYTIC_TOLERANCE_BITS,
        },
        "admission_strata": list(ADMISSION_STRATA),
        "rows": admission["rows"],
        "hands": admission["hands"],
        "point_estimate_bits_per_decision": admission["point_estimate_bits_per_decision"],
        "bootstrap_stddev_bits_per_decision": admission["bootstrap_stddev_bits_per_decision"],
        "bootstrap_variance_bits_squared": admission["bootstrap_variance_bits_squared"],
        "quantiles": admission["quantiles"],
        "ci95": admission["ci95"],
        "margin_global_bootstrap_bits_per_decision": bootstrap_upper,
        "margin_global_analytic_bits_per_decision": analytic_margin,
        "bootstrap_analytic_absolute_difference_bits": difference,
        "bootstrap_analytic_agreement_tolerance_bits": MARGIN_ANALYTIC_TOLERANCE_BITS,
        "bootstrap_analytic_within_tolerance": (
            difference is not None and difference <= MARGIN_ANALYTIC_TOLERANCE_BITS
        ),
        "criterion": "margin_global_bootstrap_bits_per_decision <= MARGIN_MAX_BITS",
        "terminal_evaluation_derived": False,
        "note": (
            "the margin inputs are derived from TRAIN out-of-fold evidence only; the frozen "
            "#423 procedure is the owner of the admission decision and no VALIDATION or TEST "
            "value enters this artifact"
        ),
    }


def build_derivation(
    dataset: str | Path = DEFAULT_DATASET,
    *,
    folds: int = CV_FOLDS,
    seed: int = CV_SEED,
    rule: str | router.RouteRule | None = None,
    architecture: str | None = None,
    method: str | None = None,
    config: Mapping[str, Any] | None = None,
    stride: int = 1,
    fit_max_rows: int = calibration.CALIBRATION_FIT_MAX_ROWS,
    probe_limit: int = PROBE_LIMIT,
    samples: int = BOOTSTRAP_SAMPLES,
    bootstrap_seed: int = BOOTSTRAP_SEED,
    reference: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Read TRAIN, run the cross-fitted comparison and build the derivation run."""
    dataset_path = Path(dataset).resolve()
    assert_consumed_splits(CONSUMED_SPLITS, context="build_derivation")
    rows = read_train_rows(dataset_path, stride=stride)
    core = run_cross_validation(
        rows,
        folds=folds,
        seed=seed,
        rule=rule,
        architecture=architecture,
        method=method,
        config=config,
        fit_max_rows=fit_max_rows,
        reference=reference,
        probe_limit=probe_limit,
        samples=samples,
        bootstrap_seed=bootstrap_seed,
    )
    records = core["records"]
    probes = core["probes"]
    prior = dict(core["protocol"]["prior"])
    hands = {str(row["hand_id"]) for row in rows}

    models = {
        channel: channel_block(records, channel, prior) for channel in CHANNELS
    }
    paired = {
        f"{CHANNEL_HYBRID}_minus_{CHANNEL_ACTIVE}": paired_block(
            records, CHANNEL_HYBRID, CHANNEL_ACTIVE, samples=samples, seed=bootstrap_seed
        ),
        f"{CHANNEL_HYBRID}_minus_{CHANNEL_GENERALIZED}": paired_block(
            records, CHANNEL_HYBRID, CHANNEL_GENERALIZED, samples=samples, seed=bootstrap_seed
        ),
    }
    static_scan = verify_no_holdout_access()

    artifact: dict[str, Any] = {
        "schema": DERIVATION_SCHEMA,
        "cv_schema": SCHEMA,
        "kind": "train_only_cross_fitted_hybrid_router_derivation",
        "issue": 423,
        "planner_key": "T4",
        "generated_by": _relative(MODULE_PATH),
        "module_sha256": sha256_file(MODULE_PATH),
        "title": (
            "#423 T4 derivation run: cross-fitted TRAIN comparison of the active Model A "
            "reference, the calibrated generalized channel and the hybrid router"
        ),
        "reuse": {
            "folds": {
                "module": _relative(Path(cv.__file__)),
                "sha256": sha256_file(Path(cv.__file__)),
                "symbols": [
                    "tools/training/evaluate_generalized_response_cv.py::fold_of",
                    "tools/training/evaluate_generalized_response_cv.py::grouped_folds",
                    "tools/training/evaluate_generalized_response_cv.py::no_leak_proof",
                    "tools/training/evaluate_generalized_response_cv.py::summary_metrics",
                ],
            },
            "generalized_calibration": {
                "module": _relative(Path(calibration.__file__)),
                "sha256": sha256_file(Path(calibration.__file__)),
                "report": _relative(CALIBRATION_REPORT_PATH),
                "report_sha256": (
                    sha256_file(CALIBRATION_REPORT_PATH) if CALIBRATION_REPORT_PATH.exists() else None
                ),
            },
            "router": {
                "module": _relative(Path(router.__file__)),
                "sha256": sha256_file(Path(router.__file__)),
                "spec": _relative(SPEC_PATH),
                "spec_sha256": sha256_file(SPEC_PATH) if SPEC_PATH.exists() else None,
                "rule": core["protocol"]["route_rule"],
            },
            "active_reference": dict(core["protocol"]["active_reference"]),
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
            "refused_splits": list(REFUSED_SPLITS),
            "forbidden_splits": list(FORBIDDEN_SPLITS),
            "validation_consumed": False,
            "test_consumed": False,
            "cross_validated_rows": sum(fold["holdout_rows"] for fold in core["folds"]),
            "probe_rows": len(probes),
        },
        "guards": {
            "train_only": True,
            "validation_consumed": False,
            "test_consumed": False,
            "forbidden_split_refusal_proof": (
                "assert_train_only raises HybridRouterCvError for any VALIDATION or TEST row; "
                "tests/training/test_evaluate_hybrid_router_cv.py exercises the refusal"
            ),
            "hands_never_on_both_sides_of_a_fold": True,
            "no_holdout_loader": static_scan["result"] == "PASS",
            "no_holdout_access_scan": static_scan,
            "byte_stable": True,
        },
        "protocol": core["protocol"],
        "folds": core["folds"],
        "calibration_admitted_folds": core["calibration_admitted_folds"],
        "strata": strata_block(records),
        "per_stratum": _stratum_surface(
            records, probes, prior, paired=paired
        ),
        "models": models,
        "paired": paired,
        "ood_synthetic_probes": _probe_block(probes),
        "margin_derivation": _margin_derivation(
            paired[f"{CHANNEL_HYBRID}_minus_{CHANNEL_ACTIVE}"],
            samples=samples,
            bootstrap_seed=bootstrap_seed,
        ),
        "assertions": {
            "no_hand_on_both_sides_of_a_split": True,
            "validation_never_read": True,
            "test_never_read": True,
            "strata_observed": sorted(
                {record["stratum"] for record in records} | {probe["stratum"] for probe in probes}
            ),
            "router_abstains_on_every_ood_probe": _probe_block(probes)["assertions"][
                "router_abstains_on_every_probe"
            ],
        },
    }
    artifact["canonical_payload_sha256"] = model.stable_hash(_canonical_payload(_finalize(artifact)))
    return artifact


def _canonical_payload(artifact: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in artifact.items() if key != "canonical_payload_sha256"}


def persisted_artifact_text(artifact: Mapping[str, Any]) -> str:
    return json.dumps(_finalize(artifact), sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n"


def sidecar_text(artifact: Mapping[str, Any], *, name: str = DERIVATION_NAME) -> str:
    payload = persisted_artifact_text(artifact)
    return (
        f"{sha256_bytes(payload.encode('utf-8'))}  {name}\n"
        f"# canonical_payload_sha256 {model.stable_hash(_canonical_payload(_finalize(artifact)))}\n"
        f"# scope TRAIN_ONLY_NO_VALIDATION_NO_TEST\n"
        f"# statistic paired_by_hand_log_loss_delta_hybrid_minus_active\n"
    )


def write_artifact(artifact: Mapping[str, Any], path: str | Path = DERIVATION_PATH) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(persisted_artifact_text(artifact), encoding="utf-8")
    target.with_suffix(".sha256").write_text(sidecar_text(artifact, name=target.name), encoding="utf-8")
    return target


def verify_persisted(path: str | Path = DERIVATION_PATH) -> list[str]:
    """Cheap structural verification of the persisted derivation run."""
    target = Path(path)
    problems: list[str] = []
    if not target.exists():
        return [f"missing {_relative(target)}"]
    digest_target = target.with_suffix(".sha256")
    if not digest_target.exists():
        return [f"missing {_relative(digest_target)}"]
    raw = target.read_bytes()
    artifact = json.loads(raw.decode("utf-8"))
    if artifact.get("schema") != DERIVATION_SCHEMA:
        problems.append(f"schema must be {DERIVATION_SCHEMA}")
    if artifact.get("module_sha256") != sha256_file(MODULE_PATH):
        problems.append("module_sha256 does not match the on-disk harness module")
    if artifact.get("canonical_payload_sha256") != model.stable_hash(
        _canonical_payload(_finalize(artifact))
    ):
        problems.append("canonical payload digest mismatch")
    sidecar = digest_target.read_text(encoding="utf-8").splitlines()
    if not sidecar or sidecar[0].split()[0] != sha256_bytes(raw):
        problems.append("derivation .sha256 sidecar does not pin the persisted bytes")
    scope = artifact.get("scope", {})
    if scope.get("split") != MAIN_SPLIT or scope.get("consumed_splits") != list(CONSUMED_SPLITS):
        problems.append("the derivation must declare a TRAIN-only scope")
    if scope.get("validation_consumed") or scope.get("test_consumed"):
        problems.append("the derivation claims to have consumed a holdout split")
    guards = artifact.get("guards", {})
    if not guards.get("no_holdout_loader"):
        problems.append("the derivation does not prove that no holdout loader is named")
    if not guards.get("hands_never_on_both_sides_of_a_fold"):
        problems.append("the derivation does not prove the hand-grouped no-leak property")
    strata = (artifact.get("strata") or {}).get("counts") or {}
    for stratum in (*ADMISSION_STRATA, OOD_STRATUM):
        if stratum not in strata:
            problems.append(f"the derivation omits stratum {stratum!r}")
    margin = artifact.get("margin_derivation") or {}
    if margin.get("terminal_evaluation_derived") is not False:
        problems.append("the derivation must not carry a terminal-evaluation-derived value")
    return problems


def check(path: str | Path = DERIVATION_PATH) -> list[str]:
    return verify_persisted(path)


def check_full(path: str | Path = DERIVATION_PATH) -> list[str]:
    """Re-verify the persisted derivation against a fresh TRAIN-only rebuild."""
    problems = verify_persisted(path)
    if problems:
        return problems
    persisted = json.loads(Path(path).read_text(encoding="utf-8"))
    scope = persisted.get("scope", {})
    protocol = persisted.get("protocol", {})
    expected = build_derivation(
        scope.get("dataset", str(DEFAULT_DATASET)),
        folds=int(protocol.get("folds", CV_FOLDS)),
        seed=int(protocol.get("seed", CV_SEED)),
        rule=protocol.get("route_rule", {}).get("id"),
        architecture=protocol.get("architecture"),
        method=protocol.get("calibration_method"),
        stride=int(scope.get("row_stride", 1)),
        fit_max_rows=int(protocol.get("calibration_fit_max_rows", calibration.CALIBRATION_FIT_MAX_ROWS)),
        probe_limit=int(
            (protocol.get("ood_probes") or {}).get("limit_per_kind_per_fold", PROBE_LIMIT)
        ),
        samples=int((protocol.get("paired_bootstrap") or {}).get("samples", BOOTSTRAP_SAMPLES)),
        bootstrap_seed=int(
            (protocol.get("paired_bootstrap") or {}).get("seed", BOOTSTRAP_SEED)
        ),
    )
    if persisted_artifact_text(persisted) != persisted_artifact_text(expected):
        problems.append("persisted derivation bytes diverge from a fresh TRAIN-only rebuild")
    return problems


def self_check(seed: int = CV_SEED) -> dict[str, Any]:
    """Fast, dataset-independent end-to-end check (hand-grouped synthetic rows)."""
    rows = []
    for index, row in enumerate(model.synthetic_rows(900, seed)):
        rows.append(dict(row, hand_id=f"hyb-hand-{index % 90:04d}"))
    artifact = run_cross_validation(
        rows,
        folds=3,
        seed=seed,
        config=model.make_config(tuning_max_rows=300),
        fit_max_rows=2000,
        probe_limit=4,
        samples=200,
    )
    return {
        "schema": SELF_CHECK_SCHEMA,
        "rows": len(rows),
        "hands": len({row["hand_id"] for row in rows}),
        "folds": artifact["protocol"]["folds"],
        "no_leak": artifact["protocol"]["no_leak"],
        "route_source_counts": _route_counts(artifact["records"]),
        "strata_counts": strata_block(artifact["records"])["counts"],
        "probe_abstain_rate": _probe_block(artifact["probes"])["abstain_rate"],
        "channels": list(CHANNELS),
        "validation_consumed": False,
        "test_consumed": False,
        "static_scan": verify_no_holdout_access()["result"],
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="#423 T4 - TRAIN-only cross-fitted hybrid router comparison and derivation"
    )
    parser.add_argument("--self-check", action="store_true", help="run the dependency-free smoke check")
    parser.add_argument("--check", action="store_true", help="re-verify the persisted derivation")
    parser.add_argument(
        "--check-full",
        action="store_true",
        help="re-verify the persisted derivation and rebuild it from TRAIN (slow)",
    )
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--out", default=str(DERIVATION_PATH))
    parser.add_argument("--folds", type=int, default=CV_FOLDS)
    parser.add_argument("--seed", type=int, default=CV_SEED)
    parser.add_argument("--stride", type=int, default=1, help="deterministic TRAIN row stride (fast runs)")
    parser.add_argument("--rule", default=router.DEFAULT_RULE_ID)
    parser.add_argument("--architecture", default=None)
    parser.add_argument("--method", default=None)
    parser.add_argument("--tuning-max-rows", type=int, default=None)
    parser.add_argument("--calibration-fit-max-rows", type=int, default=calibration.CALIBRATION_FIT_MAX_ROWS)
    parser.add_argument("--probe-limit", type=int, default=PROBE_LIMIT)
    parser.add_argument("--bootstrap-samples", type=int, default=BOOTSTRAP_SAMPLES)
    parser.add_argument("--bootstrap-seed", type=int, default=BOOTSTRAP_SEED)
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
        model.make_config(tuning_max_rows=args.tuning_max_rows)
        if args.tuning_max_rows is not None
        else None
    )
    artifact = build_derivation(
        args.dataset,
        folds=args.folds,
        seed=args.seed,
        rule=args.rule,
        architecture=args.architecture,
        method=args.method,
        config=config,
        stride=args.stride,
        fit_max_rows=args.calibration_fit_max_rows,
        probe_limit=args.probe_limit,
        samples=args.bootstrap_samples,
        bootstrap_seed=args.bootstrap_seed,
    )
    text = persisted_artifact_text(artifact)
    if args.print_only:
        sys.stdout.write(text)
        return 0
    target = write_artifact(artifact, args.out)
    print(
        json.dumps(
            {
                "artifact": _relative(target),
                "rows": artifact["scope"]["rows"],
                "hands": artifact["scope"]["hands"],
                "folds": artifact["protocol"]["folds"],
                "margin_global_bootstrap_bits_per_decision": artifact["margin_derivation"][
                    "margin_global_bootstrap_bits_per_decision"
                ],
                "strata_counts": artifact["strata"]["counts"],
            },
            sort_keys=True,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

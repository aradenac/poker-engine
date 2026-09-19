#!/usr/bin/env python3
"""Observed-vs-simulated Model B calibration for issue #272.

Finalization rerun marker: protocol and scientific semantics unchanged.

Scientific constraints:
- the reference and candidate are pre-existing TRAIN-fitted artifacts;
- metrics are computed on VALIDATION only;
- TEST is forbidden and no TEST metric/report field may be produced;
- reference and candidate are evaluated on exactly the same observed rows;
- exact public contexts are never silently pooled;
- Model A EV/policy/recommendations are never features;
- this analysis cannot promote or modify the active Model B.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import random
import statistics
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from tools.datasets.build_hand_history_increment import split_for
from tools.simulation.model_b_price_response import (
    ACTIONS,
    HIERARCHY,
    ResponseToPriceModel,
    artifact_sha256,
    price_bucket,
    spr_bucket,
)
from tools.training.independent_profiles.build_model_b import sha256_file
from tools.training.independent_profiles.build_player_features import merge_archives
from tools.training.independent_profiles.evaluate_model_b import choose_node
from tools.training.independent_profiles.evaluate_response_to_price_v1 import (
    ReferencePredictor,
    load_json,
    records_to_observations,
)

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = "model-b-observed-vs-simulated-calibration/v1"
SUMMARY_SCHEMA = "model-b-observed-vs-simulated-calibration-summary/v1"
PROTOCOL_SCHEMA = "model-b-observed-vs-simulated-calibration-protocol/v1"
SEED = 20260919
EPS = 1e-12
EXACT_CONTEXT_DIMENSIONS = (
    "profile",
    "street",
    "relative_position",
    "pot_type",
    "sequence",
    "price_bucket",
    "spr_bucket",
)
DOMAIN_DIMENSIONS = (
    "street",
    "relative_position",
    "pot_type",
    "sequence",
    "price_bucket",
    "spr_bucket",
    "profile",
)
SUPPORT_STATES = (
    "SUPPORTED",
    "LOW_SUPPORT",
    "INSUFFICIENT_SUPPORT",
    "NOT_APPLICABLE",
)


def write_json(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _finite(value: Any, *, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def quantile(values: Sequence[float], q: float) -> float | None:
    clean = sorted(float(v) for v in values if math.isfinite(float(v)))
    if not clean:
        return None
    if len(clean) == 1:
        return clean[0]
    pos = max(0.0, min(1.0, float(q))) * (len(clean) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return clean[lo]
    w = pos - lo
    return clean[lo] * (1.0 - w) + clean[hi] * w


def distribution_summary(values: Sequence[float]) -> dict[str, Any]:
    clean = [float(v) for v in values if math.isfinite(float(v)) and float(v) > 0]
    return {
        "n": len(clean),
        "p10": quantile(clean, 0.10),
        "median": quantile(clean, 0.50),
        "p90": quantile(clean, 0.90),
        "p99": quantile(clean, 0.99),
    }


def wilson95(successes: int, total: int) -> list[float] | None:
    if total <= 0:
        return None
    z = 1.959963984540054
    p = successes / total
    denom = 1.0 + (z * z / total)
    center = (p + z * z / (2.0 * total)) / denom
    half = z * math.sqrt((p * (1.0 - p) / total) + z * z / (4.0 * total * total)) / denom
    return [max(0.0, center - half), min(1.0, center + half)]


def _support_state(
    observations: int,
    distinct_hands: int,
    *,
    supported_n: int,
    supported_hands: int,
    low_n: int,
    low_hands: int,
    applicable: bool = True,
) -> str:
    if not applicable:
        return "NOT_APPLICABLE"
    if observations >= supported_n and distinct_hands >= supported_hands:
        return "SUPPORTED"
    if observations >= low_n and distinct_hands >= low_hands:
        return "LOW_SUPPORT"
    return "INSUFFICIENT_SUPPORT"


def action_support_state(n: int, hands: int) -> str:
    return _support_state(
        n,
        hands,
        supported_n=30,
        supported_hands=20,
        low_n=10,
        low_hands=5,
    )


def sizing_support_state(raises: int, hands: int) -> str:
    return _support_state(
        raises,
        hands,
        supported_n=12,
        supported_hands=8,
        low_n=5,
        low_hands=3,
        applicable=raises > 0,
    )


def select_validation_records(
    records: Iterable[Any],
    *,
    split_fn: Callable[[str], str] = split_for,
) -> list[Any]:
    """Select the only split issue #272 is allowed to evaluate."""
    selected = []
    for record in records:
        split = str(split_fn(str(record.hand_id)))
        if split == "VALIDATION":
            selected.append(record)
    return selected


def exact_context(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "profile": int(row["profile"]),
        "street": str(row["street"]).lower(),
        "relative_position": str(row["relative_position"]),
        "pot_type": str(row["pot_type"]),
        "sequence": str(row["sequence"]),
        "price_bucket": price_bucket(row.get("facing_price_to_pot")),
        "spr_bucket": spr_bucket(row.get("spr")),
    }


def context_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    c = exact_context(row)
    return tuple(c[name] for name in EXACT_CONTEXT_DIMENSIONS)


def context_id(context: Mapping[str, Any]) -> str:
    payload = json.dumps(
        {name: context[name] for name in EXACT_CONTEXT_DIMENSIONS},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "ctx-" + hashlib.sha256(payload).hexdigest()[:16]


def _relative_error(predicted: float, observed: float) -> float | None:
    if observed <= EPS:
        return None
    return abs(predicted - observed) / observed


def _probability_metrics(actuals: Sequence[str], probs: Sequence[Mapping[str, float]]) -> dict[str, Any]:
    if not actuals:
        return {
            "n": 0,
            "log_loss": None,
            "brier": None,
            "ece_confidence": None,
        }
    loss = 0.0
    brier = 0.0
    bins: dict[int, list[float]] = collections.defaultdict(lambda: [0.0, 0.0, 0.0])
    for actual, raw in zip(actuals, probs):
        p = {action: _finite(raw[action], name=f"probability.{action}") for action in ACTIONS}
        total = sum(p.values())
        if abs(total - 1.0) > 1e-8:
            raise ValueError(f"probabilities do not sum to 1: {p}")
        loss -= math.log(max(EPS, p[actual]))
        brier += sum((p[action] - (1.0 if action == actual else 0.0)) ** 2 for action in ACTIONS)
        predicted = max(ACTIONS, key=lambda action: (p[action], action))
        confidence = p[predicted]
        bucket = min(9, int(confidence * 10.0))
        bins[bucket][0] += 1.0
        bins[bucket][1] += confidence
        bins[bucket][2] += 1.0 if predicted == actual else 0.0
    n = len(actuals)
    ece = 0.0
    for bn, confidence_sum, correct_sum in bins.values():
        ece += (bn / n) * abs((confidence_sum / bn) - (correct_sum / bn))
    return {
        "n": n,
        "log_loss": loss / n,
        "brier": brier / n,
        "ece_confidence": ece,
    }


def _stable_seed(label: str, seed: int = SEED) -> int:
    digest = hashlib.sha256(f"{seed}|{label}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _paired_logloss_bootstrap(
    rows: Sequence[Mapping[str, Any]],
    *,
    samples: int,
    seed_label: str,
) -> dict[str, Any] | None:
    by_hand: dict[str, list[float]] = collections.defaultdict(list)
    for row in rows:
        by_hand[str(row["hand_id"])].append(float(row["logloss_delta"]))
    hands = sorted(by_hand)
    if len(hands) < 2 or sum(len(v) for v in by_hand.values()) < 10:
        return None
    observed_values = [v for hand in hands for v in by_hand[hand]]
    observed = statistics.fmean(observed_values)
    rng = random.Random(_stable_seed(seed_label))
    draws = []
    for _ in range(int(samples)):
        sample_values: list[float] = []
        for _ in hands:
            picked = hands[rng.randrange(len(hands))]
            sample_values.extend(by_hand[picked])
        draws.append(statistics.fmean(sample_values))
    return {
        "cluster_unit": "hand_id",
        "distinct_hands": len(hands),
        "decisions": len(observed_values),
        "bootstrap_samples": int(samples),
        "seed": _stable_seed(seed_label),
        "candidate_minus_reference_log_loss": observed,
        "ci95": [quantile(draws, 0.025), quantile(draws, 0.975)],
    }


def _reference_sizing_values(reference: ReferencePredictor, row: Mapping[str, Any]) -> list[float]:
    selector = {
        "profile": int(row["profile"]),
        "street": str(row["street"]).lower(),
        "mode": "FACING",
        "relative_position": row["relative_position"],
        "pot_type": row["pot_type"],
        "preflop_role": row["preflop_role"],
        "action": "RAISE",
    }
    node, _, _ = choose_node(reference.sizing["levels"], selector, reference.sizing_min)
    return [
        float(v)
        for v in node.get("values", [])
        if math.isfinite(float(v)) and float(v) > 0
    ]


def _deterministic_sizing_samples(
    values: Sequence[float],
    *,
    label: str,
    count: int = 16,
) -> list[float]:
    clean = [float(v) for v in values if math.isfinite(float(v)) and float(v) > 0]
    if not clean:
        return []
    out = []
    for index in range(int(count)):
        digest = hashlib.sha256(f"{SEED}|{label}|{index}".encode("utf-8")).digest()
        out.append(clean[int.from_bytes(digest[:8], "big") % len(clean)])
    return out


def _aggressive_rates(
    sizing_values: Sequence[float],
    *,
    spr: float | None,
    price: float | None,
) -> dict[str, float] | None:
    clean = [float(v) for v in sizing_values if math.isfinite(float(v)) and float(v) > 0]
    if not clean:
        return None
    jam = 0
    overbet = 0
    tail = 0
    for sizing in clean:
        jam_like = spr is not None and float(spr) > 0 and sizing >= float(spr) * (1.0 - 1e-9)
        is_overbet = sizing > 1.0
        is_tail = jam_like or (price is not None and float(price) > 1.5) or sizing > 1.5
        jam += int(jam_like)
        overbet += int(is_overbet)
        tail += int(is_tail)
    n = len(clean)
    return {
        "jam_like_conditional_on_raise": jam / n,
        "overbet_conditional_on_raise": overbet / n,
        "tail_conditional_on_raise": tail / n,
    }


def _classification_from_bootstrap(
    support_state: str,
    bootstrap: Mapping[str, Any] | None,
) -> str:
    if support_state != "SUPPORTED" or bootstrap is None:
        return "INSUFFICIENT_SUPPORT"
    low, high = bootstrap["ci95"]
    if float(high) < 0.0:
        return "CANDIDATE_IMPROVES"
    if float(low) > 0.0:
        return "CANDIDATE_DEGRADES"
    return "SIMILAR"


def calibrate_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    reference: ReferencePredictor,
    candidate: ResponseToPriceModel,
    bootstrap_samples: int,
    label: str,
) -> dict[str, Any]:
    if not rows:
        raise ValueError("calibration group must contain observations")

    actuals: list[str] = []
    ref_probs: list[dict[str, float]] = []
    cand_probs: list[dict[str, float]] = []
    observed = collections.Counter()
    hand_ids: set[str] = set()
    raise_hand_ids: set[str] = set()
    observed_sizings: list[float] = []
    ref_simulated_sizings: list[float] = []
    cand_simulated_sizings: list[float] = []
    ref_log2_errors: list[float] = []
    cand_log2_errors: list[float] = []
    paired_rows: list[dict[str, Any]] = []
    observed_jam = observed_overbet = observed_tail = 0
    ref_expected = collections.Counter()
    cand_expected = collections.Counter()
    ref_sizing_coverage = cand_sizing_coverage = 0

    for row_index, row in enumerate(rows):
        actual = str(row["action"]).upper()
        if actual not in ACTIONS:
            raise ValueError(f"unsupported observed action {actual!r}")
        hand_id = str(row["hand_id"])
        hand_ids.add(hand_id)
        observed[actual] += 1
        actuals.append(actual)

        rp = reference(row)
        cp = candidate.predict(**row)
        rp_probs = {action: float(rp["probabilities"][action]) for action in ACTIONS}
        cp_probs = {action: float(cp["probabilities"][action]) for action in ACTIONS}
        ref_probs.append(rp_probs)
        cand_probs.append(cp_probs)
        paired_rows.append({
            "hand_id": hand_id,
            "logloss_delta": (
                -math.log(max(EPS, cp_probs[actual]))
                + math.log(max(EPS, rp_probs[actual]))
            ),
        })

        price = row.get("facing_price_to_pot")
        spr = row.get("spr")
        ref_values = _reference_sizing_values(reference, row)
        cand_values = candidate.sizing_values(**row)
        ref_rates = _aggressive_rates(ref_values, spr=spr, price=price)
        cand_rates = _aggressive_rates(cand_values, spr=spr, price=price)
        if ref_rates is not None:
            ref_sizing_coverage += 1
            for metric, conditional in ref_rates.items():
                key = metric.split("_conditional")[0]
                ref_expected[key] += rp_probs["RAISE"] * conditional
        if cand_rates is not None:
            cand_sizing_coverage += 1
            for metric, conditional in cand_rates.items():
                key = metric.split("_conditional")[0]
                cand_expected[key] += cp_probs["RAISE"] * conditional

        actual_sizing = row.get("raise_sizing_ratio")
        is_raise = actual == "RAISE" and actual_sizing is not None
        if bool(row.get("is_jam")):
            observed_jam += 1
        if is_raise and float(actual_sizing) > 1.0:
            observed_overbet += 1
        if (
            bool(row.get("is_jam"))
            or (price is not None and float(price) > 1.5 and actual == "RAISE")
            or (is_raise and float(actual_sizing) > 1.5)
        ):
            observed_tail += 1

        if not is_raise:
            continue
        actual_value = float(actual_sizing)
        if not math.isfinite(actual_value) or actual_value <= 0:
            continue
        raise_hand_ids.add(hand_id)
        observed_sizings.append(actual_value)
        token = f"{label}|{hand_id}|{row_index}"
        ref_simulated_sizings.extend(
            _deterministic_sizing_samples(ref_values, label=f"reference|{token}")
        )
        cand_simulated_sizings.extend(
            _deterministic_sizing_samples(cand_values, label=f"candidate|{token}")
        )
        rmedian = (rp.get("sizing") or {}).get("median")
        cmedian = (cp.get("sizing") or {}).get("median")
        if rmedian is not None and float(rmedian) > 0:
            ref_log2_errors.append(abs(math.log2(actual_value / float(rmedian))))
        if cmedian is not None and float(cmedian) > 0:
            cand_log2_errors.append(abs(math.log2(actual_value / float(cmedian))))

    n = len(rows)
    hands = len(hand_ids)
    support = action_support_state(n, hands)
    sizing_support = sizing_support_state(len(observed_sizings), len(raise_hand_ids))
    mean_ref = {
        action: statistics.fmean(p[action] for p in ref_probs)
        for action in ACTIONS
    }
    mean_cand = {
        action: statistics.fmean(p[action] for p in cand_probs)
        for action in ACTIONS
    }
    action_rows = {}
    for action in ACTIONS:
        count = int(observed[action])
        freq = count / n
        r = mean_ref[action]
        c = mean_cand[action]
        action_rows[action] = {
            "observed_count": count,
            "observed_frequency": freq,
            "observed_frequency_ci95": wilson95(count, n),
            "simulated_reference_frequency": r,
            "simulated_candidate_frequency": c,
            "reference_absolute_error": abs(r - freq),
            "candidate_absolute_error": abs(c - freq),
            "reference_relative_error": _relative_error(r, freq),
            "candidate_relative_error": _relative_error(c, freq),
        }

    ref_probability = _probability_metrics(actuals, ref_probs)
    cand_probability = _probability_metrics(actuals, cand_probs)
    bootstrap = _paired_logloss_bootstrap(
        paired_rows,
        samples=bootstrap_samples,
        seed_label=label,
    )
    observed_dist = distribution_summary(observed_sizings)
    ref_dist = distribution_summary(ref_simulated_sizings)
    cand_dist = distribution_summary(cand_simulated_sizings)

    def error_summary(values: Sequence[float]) -> dict[str, Any]:
        return {
            "n": len(values),
            "median_absolute_log2_error": quantile(values, 0.50),
            "p90_absolute_log2_error": quantile(values, 0.90),
            "mean_absolute_log2_error": statistics.fmean(values) if values else None,
        }

    aggressive = {
        "definition": {
            "jam_observed": "HH all-in flag on a RAISE decision",
            "jam_simulated": "raise sizing >= live SPR; derived proxy because Model B sizing artifacts do not store an explicit jam class",
            "overbet": "raise sizing > 1.0 pot",
            "tail": "jam OR facing_price_to_pot > 1.5 OR raise_sizing_ratio > 1.5",
        },
        "observed": {
            "jam_count": observed_jam,
            "jam_frequency": observed_jam / n,
            "overbet_count": observed_overbet,
            "overbet_frequency": observed_overbet / n,
            "tail_count": observed_tail,
            "tail_frequency": observed_tail / n,
        },
        "reference": {
            "jam_frequency": ref_expected["jam_like"] / n,
            "overbet_frequency": ref_expected["overbet"] / n,
            "tail_frequency": ref_expected["tail"] / n,
            "sizing_prediction_coverage": ref_sizing_coverage / n,
        },
        "candidate": {
            "jam_frequency": cand_expected["jam_like"] / n,
            "overbet_frequency": cand_expected["overbet"] / n,
            "tail_frequency": cand_expected["tail"] / n,
            "sizing_prediction_coverage": cand_sizing_coverage / n,
        },
    }
    for metric in ("jam_frequency", "overbet_frequency", "tail_frequency"):
        obs = aggressive["observed"][metric]
        aggressive["reference"][f"{metric}_absolute_error"] = abs(
            aggressive["reference"][metric] - obs
        )
        aggressive["candidate"][f"{metric}_absolute_error"] = abs(
            aggressive["candidate"][metric] - obs
        )

    return {
        "observations": n,
        "distinct_hands": hands,
        "support_tier": support,
        "interpretable": support == "SUPPORTED",
        "actions": action_rows,
        "probability_calibration": {
            "reference": ref_probability,
            "candidate": cand_probability,
            "candidate_minus_reference": {
                "log_loss": (
                    cand_probability["log_loss"] - ref_probability["log_loss"]
                    if cand_probability["log_loss"] is not None
                    else None
                ),
                "brier": (
                    cand_probability["brier"] - ref_probability["brier"]
                    if cand_probability["brier"] is not None
                    else None
                ),
                "ece_confidence": (
                    cand_probability["ece_confidence"] - ref_probability["ece_confidence"]
                    if cand_probability["ece_confidence"] is not None
                    else None
                ),
                "paired_log_loss_cluster_bootstrap": bootstrap,
            },
        },
        "sizing_calibration": {
            "support_tier": sizing_support,
            "interpretable": sizing_support == "SUPPORTED",
            "observed_raise_count": len(observed_sizings),
            "distinct_raise_hands": len(raise_hand_ids),
            "observed_distribution": observed_dist,
            "simulated_reference_distribution": ref_dist,
            "simulated_candidate_distribution": cand_dist,
            "reference_log2_error": error_summary(ref_log2_errors),
            "candidate_log2_error": error_summary(cand_log2_errors),
        },
        "aggressive_tails": aggressive,
        "comparison": _classification_from_bootstrap(support, bootstrap),
    }


def _groups_by_exact_context(
    rows: Sequence[Mapping[str, Any]],
) -> list[tuple[dict[str, Any], list[Mapping[str, Any]]]]:
    grouped: dict[tuple[Any, ...], list[Mapping[str, Any]]] = collections.defaultdict(list)
    representative: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        key = context_key(row)
        grouped[key].append(row)
        representative.setdefault(key, exact_context(row))
    return [(representative[key], grouped[key]) for key in sorted(grouped)]


def _domain_groups(
    rows: Sequence[Mapping[str, Any]],
    dimension: str,
) -> list[tuple[dict[str, Any], list[Mapping[str, Any]]]]:
    groups: dict[str, list[Mapping[str, Any]]] = collections.defaultdict(list)
    for row in rows:
        if dimension == "price_bucket":
            value = price_bucket(row.get("facing_price_to_pot"))
        elif dimension == "spr_bucket":
            value = spr_bucket(row.get("spr"))
        else:
            value = str(row[dimension])
        groups[str(value)].append(row)
    return [
        ({"dimension": dimension, "value": value, "aggregation": "EXPLICIT_SINGLE_DIMENSION"}, groups[value])
        for value in sorted(groups)
    ]


def _dimension_value(row: Mapping[str, Any], dimension: str) -> Any:
    if dimension == "price_bucket":
        return price_bucket(row.get("facing_price_to_pot"))
    if dimension == "spr_bucket":
        return spr_bucket(row.get("spr"))
    if dimension == "profile":
        return int(row["profile"])
    return str(row[dimension])


def _hierarchy_groups(
    rows: Sequence[Mapping[str, Any]],
    dimensions: Sequence[str],
) -> list[tuple[dict[str, Any], list[Mapping[str, Any]]]]:
    dims = tuple(dimensions)
    groups: dict[tuple[Any, ...], list[Mapping[str, Any]]] = collections.defaultdict(list)
    for row in rows:
        key = tuple(_dimension_value(row, dimension) for dimension in dims)
        groups[key].append(row)
    out = []
    for key in sorted(groups):
        context = {dimension: value for dimension, value in zip(dims, key)}
        out.append((context, groups[key]))
    return out


def _context_fingerprint(context_rows: Sequence[Mapping[str, Any]]) -> str:
    payload = [
        {
            "context_id": row["context_id"],
            "observations": row["calibration"]["observations"],
        }
        for row in context_rows
    ]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _identity_file(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _summary(report: Mapping[str, Any]) -> dict[str, Any]:
    supported = [
        row for row in report["context_rows"]
        if row["calibration"]["support_tier"] == "SUPPORTED"
    ]
    low = [
        row for row in report["context_rows"]
        if row["calibration"]["support_tier"] != "SUPPORTED"
    ]
    statuses = collections.Counter(
        row["calibration"]["comparison"] for row in report["context_rows"]
    )
    domain_status = collections.Counter(
        row["calibration"]["comparison"] for row in report["domain_summaries"]
    )
    hierarchy_status = collections.Counter(
        row["calibration"]["comparison"] for row in report["hierarchy_summaries"]
    )

    def score(row: Mapping[str, Any]) -> float:
        delta = row["calibration"]["probability_calibration"]["candidate_minus_reference"]["log_loss"]
        return float(delta) if delta is not None else 0.0

    improvements = sorted(
        [row for row in report["domain_summaries"] if row["calibration"]["comparison"] == "CANDIDATE_IMPROVES"],
        key=score,
    )
    degradations = sorted(
        [row for row in report["domain_summaries"] if row["calibration"]["comparison"] == "CANDIDATE_DEGRADES"],
        key=score,
        reverse=True,
    )
    similar = [
        row for row in report["domain_summaries"]
        if row["calibration"]["comparison"] == "SIMILAR"
    ]

    def compact_domain(row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "domain": row["domain"],
            "observations": row["calibration"]["observations"],
            "distinct_hands": row["calibration"]["distinct_hands"],
            "candidate_minus_reference_log_loss": row["calibration"]["probability_calibration"]["candidate_minus_reference"]["log_loss"],
            "paired_ci95": (
                row["calibration"]["probability_calibration"]["candidate_minus_reference"]
                ["paired_log_loss_cluster_bootstrap"] or {}
            ).get("ci95"),
        }

    worst_candidate = sorted(
        supported,
        key=lambda row: row["calibration"]["probability_calibration"]["candidate"]["log_loss"],
        reverse=True,
    )[:20]
    return {
        "schema": SUMMARY_SCHEMA,
        "issue": 272,
        "evaluation_split": "VALIDATION",
        "test_consumed": False,
        "production_effect": "NONE",
        "context_counts": {
            "total": len(report["context_rows"]),
            "supported": len(supported),
            "not_fully_supported": len(low),
            "comparison": dict(sorted(statuses.items())),
        },
        "global_calibration_snapshot": {
            "observations": report["global_calibration"]["observations"],
            "distinct_hands": report["global_calibration"]["distinct_hands"],
            "support_tier": report["global_calibration"]["support_tier"],
            "comparison": report["global_calibration"]["comparison"],
            "actions": report["global_calibration"]["actions"],
            "probability_calibration": report["global_calibration"]["probability_calibration"],
            "sizing_calibration": report["global_calibration"]["sizing_calibration"],
            "aggressive_tails": report["global_calibration"]["aggressive_tails"],
        },
        "domain_comparison_counts": dict(sorted(domain_status.items())),
        "hierarchy_comparison_counts": dict(sorted(hierarchy_status.items())),
        "candidate_improves_domains": [compact_domain(row) for row in improvements[:20]],
        "similar_domains": [compact_domain(row) for row in similar[:20]],
        "candidate_degrades_domains": [compact_domain(row) for row in degradations[:20]],
        "insufficiently_supported_contexts": len(low),
        "worst_candidate_calibration_contexts": [
            {
                "context_id": row["context_id"],
                "context": row["context"],
                "observations": row["calibration"]["observations"],
                "candidate_log_loss": row["calibration"]["probability_calibration"]["candidate"]["log_loss"],
                "reference_log_loss": row["calibration"]["probability_calibration"]["reference"]["log_loss"],
            }
            for row in worst_candidate
        ],
        "interpretation": (
            "Descriptive VALIDATION calibration only. CANDIDATE_IMPROVES/DEGRADES requires "
            "SUPPORTED context and a paired hand-cluster bootstrap CI for candidate-minus-reference "
            "log-loss that excludes zero. No promotion decision is made."
        ),
    }


def evaluate(args: argparse.Namespace) -> int:
    protocol = load_json(Path(args.protocol))
    if protocol.get("schema") != PROTOCOL_SCHEMA:
        raise ValueError("unsupported issue #272 protocol")
    if protocol.get("status") != "FROZEN_BEFORE_ISSUE_272_EVALUATION":
        raise ValueError("issue #272 protocol must be frozen before evaluation")
    split_contract = protocol["split_contract"]
    if split_contract.get("evaluate") != ["VALIDATION"]:
        raise ValueError("issue #272 evaluation split must be VALIDATION only")
    if split_contract.get("forbidden") != ["TEST"] or split_contract.get("test_consumed") is not False:
        raise ValueError("TEST must be forbidden and unconsumed")
    if tuple(protocol.get("context_dimensions") or ()) != EXACT_CONTEXT_DIMENSIONS:
        raise ValueError("issue #272 context dimensions differ from frozen protocol")
    science = protocol["scientific_constraints"]
    if science.get("production_effect") != "NONE" or science.get("automatic_promotion") is not False:
        raise ValueError("issue #272 must remain analysis-only")

    source197 = load_json(Path(args.source197_protocol))
    result197 = load_json(Path(args.source197_result))
    if source197["data"]["split_contract"]["fit"] != ["TRAIN"]:
        raise ValueError("#197 candidate was not fit on TRAIN only")
    if source197["data"]["split_contract"]["evaluate"] != ["VALIDATION"]:
        raise ValueError("#197 candidate evaluation identity changed")
    if source197["data"]["split_contract"]["forbidden"] != ["TEST"]:
        raise ValueError("#197 TEST contract changed")
    if result197.get("test_consumed") is not False:
        raise ValueError("#197 evidence indicates TEST consumption")
    if result197.get("production_effect") != "NONE":
        raise ValueError("#197 candidate must remain non-production")

    candidate_doc = load_json(Path(args.candidate_artifact))
    forbidden_features = set((candidate_doc.get("feature_contract") or {}).get("forbidden_sources") or [])
    expected_forbidden = {"model_a_ev", "model_a_policy", "model_a_recommendation"}
    if not expected_forbidden.issubset(forbidden_features):
        raise ValueError("candidate feature guard no longer forbids Model A recommendation/EV sources")
    candidate = ResponseToPriceModel(candidate_doc)
    reference = ReferencePredictor(Path(args.incumbent_model_dir))

    expected_archives = {row["path"]: row["sha256"] for row in source197["data"]["archives"]}
    archive_identity = []
    for path in args.archive:
        path = Path(path)
        actual = sha256_file(path)
        expected = expected_archives.get(str(path))
        if expected is None or expected != actual:
            raise ValueError(f"archive identity differs from frozen #197 protocol: {path}")
        archive_identity.append({"path": str(path), "sha256": actual})

    by_id, _ = merge_archives(args.archive, set(args.stake))
    validation_records = select_validation_records(by_id.values())
    profiles = load_json(Path(args.incumbent_model_dir) / "profiles.json")
    validation = records_to_observations(
        validation_records,
        profiles,
        set(args.exclude_player),
    )
    if not validation:
        raise ValueError("VALIDATION contains no eligible FACING observations")
    # This is the only evaluation-row materialization in issue #272.
    if any(split_for(str(row["hand_id"])) != "VALIDATION" for row in validation):
        raise ValueError("non-VALIDATION observation reached issue #272 evaluation")

    context_rows = []
    for context, group in _groups_by_exact_context(validation):
        cid = context_id(context)
        calibration = calibrate_rows(
            group,
            reference=reference,
            candidate=candidate,
            bootstrap_samples=args.bootstrap_samples,
            label=cid,
        )
        context_rows.append({
            "context_id": cid,
            "context": context,
            "calibration": calibration,
        })

    hierarchy_rows = []
    for level_index, dimensions in enumerate(HIERARCHY):
        if tuple(dimensions) == EXACT_CONTEXT_DIMENSIONS:
            continue
        for context, group in _hierarchy_groups(validation, dimensions):
            label = "hierarchy|" + str(level_index) + "|" + json.dumps(
                context, sort_keys=True, separators=(",", ":")
            )
            hierarchy_rows.append({
                "level_index": level_index,
                "dimensions": list(dimensions),
                "aggregation": "DECLARED_ISSUE_197_BACKOFF",
                "context": context,
                "calibration": calibrate_rows(
                    group,
                    reference=reference,
                    candidate=candidate,
                    bootstrap_samples=args.bootstrap_samples,
                    label=label,
                ),
            })

    domain_rows = []
    for dimension in DOMAIN_DIMENSIONS:
        for domain, group in _domain_groups(validation, dimension):
            label = f"domain|{dimension}|{domain['value']}"
            domain_rows.append({
                "domain": domain,
                "calibration": calibrate_rows(
                    group,
                    reference=reference,
                    candidate=candidate,
                    bootstrap_samples=args.bootstrap_samples,
                    label=label,
                ),
            })

    global_calibration = calibrate_rows(
        validation,
        reference=reference,
        candidate=candidate,
        bootstrap_samples=args.bootstrap_samples,
        label="GLOBAL",
    )
    fingerprint = _context_fingerprint(context_rows)
    validation_hand_ids = sorted({str(row["hand_id"]) for row in validation})
    source_counts = {
        "validation_hand_records": len(validation_records),
        "validation_facing_decisions": len(validation),
        "validation_distinct_hands_with_facing_decisions": len(validation_hand_ids),
        "exact_contexts": len(context_rows),
        "sum_context_observations": sum(row["calibration"]["observations"] for row in context_rows),
    }
    if source_counts["sum_context_observations"] != len(validation):
        raise AssertionError("context rows do not partition VALIDATION decisions exactly")

    incumbent = Path(args.incumbent_model_dir)
    report = {
        "schema": SCHEMA,
        "issue": 272,
        "status": "COMPLETE",
        "dataset": {
            "population_id": args.population_id,
            "evaluation_split": "VALIDATION",
            "fit_source": "EXISTING_TRAIN_FITTED_ARTIFACTS",
            "reserved_holdout": "TEST_NOT_CONSUMED",
            "test_consumed": False,
            "archives": archive_identity,
            "validation_hand_id_fingerprint_sha256": hashlib.sha256(
                "\n".join(validation_hand_ids).encode("utf-8")
            ).hexdigest(),
        },
        "reference_identity": {
            "role": "REFERENCE_MODEL_B",
            "model_dir": str(incumbent),
            "files": [
                _identity_file(incumbent / name)
                for name in ("profiles.json", "postflop_actions.json", "sizing.json", "prediction_contract.json")
            ],
        },
        "candidate_identity": {
            "role": "CANDIDATE_RESPONSE_TO_PRICE_ISSUE_197",
            "source_issue": 197,
            "artifact_path": str(args.candidate_artifact),
            "file_sha256": sha256_file(Path(args.candidate_artifact)),
            "semantic_artifact_sha256": artifact_sha256(candidate_doc),
            "model_version": candidate_doc["model_version"],
            "fit_split": candidate_doc["fit_split"],
            "production_effect": candidate_doc["production_effect"],
        },
        "comparability": {
            "same_validation_rows": True,
            "same_exact_context_set": True,
            "exact_context_dimensions": list(EXACT_CONTEXT_DIMENSIONS),
            "reference_row_conditioned_extra_dimensions": ["preflop_role"],
            "context_set_fingerprint_sha256": fingerprint,
            "silent_context_pooling": False,
            "hierarchy_summaries_follow_issue_197_declared_backoff": True,
            "domain_summaries_are_explicit_aggregations": True,
        },
        "source_counts": source_counts,
        "global_calibration": global_calibration,
        "context_rows": context_rows,
        "hierarchy_summaries": hierarchy_rows,
        "domain_summaries": domain_rows,
        "worst_calibration_gaps": sorted(
            [
                {
                    "context_id": row["context_id"],
                    "context": row["context"],
                    "support_tier": row["calibration"]["support_tier"],
                    "candidate_log_loss": row["calibration"]["probability_calibration"]["candidate"]["log_loss"],
                    "reference_log_loss": row["calibration"]["probability_calibration"]["reference"]["log_loss"],
                    "candidate_minus_reference_log_loss": row["calibration"]["probability_calibration"]["candidate_minus_reference"]["log_loss"],
                }
                for row in context_rows
                if row["calibration"]["support_tier"] == "SUPPORTED"
            ],
            key=lambda row: float(row["candidate_log_loss"]),
            reverse=True,
        )[:30],
        "feature_safety": {
            "model_a_recommendation_or_ev_consumed": False,
            "candidate_forbidden_sources": sorted(forbidden_features),
        },
        "test_consumed": False,
        "production_effect": "NONE",
        "automatic_promotion": False,
        "active_model_b_changed": False,
    }
    summary = _summary(report)
    output = Path(args.output_dir)
    write_json(output / "REPORT.json", report)
    write_json(output / "SUMMARY.json", summary)
    print(json.dumps({
        "schema": report["schema"],
        "validation_decisions": len(validation),
        "exact_contexts": len(context_rows),
        "global_candidate_minus_reference_log_loss": (
            global_calibration["probability_calibration"]["candidate_minus_reference"]["log_loss"]
        ),
        "test_consumed": False,
        "production_effect": "NONE",
    }, indent=2))
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive", type=Path, action="append", required=True)
    p.add_argument("--stake", action="append", default=["100/200"])
    p.add_argument("--exclude-player", action="append", default=[])
    p.add_argument("--incumbent-model-dir", type=Path, required=True)
    p.add_argument("--candidate-artifact", type=Path, required=True)
    p.add_argument("--source197-protocol", type=Path, required=True)
    p.add_argument("--source197-result", type=Path, required=True)
    p.add_argument("--protocol", type=Path, required=True)
    p.add_argument("--population-id", required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--bootstrap-samples", type=int, default=1000)
    p.set_defaults(func=evaluate)
    return p


def main() -> int:
    args = parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

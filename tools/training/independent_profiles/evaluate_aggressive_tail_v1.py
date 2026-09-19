#!/usr/bin/env python3
"""Frozen TRAIN-fit / VALIDATION-only evaluation for issue #298.

Final validation trigger after current-main refresh.
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
from typing import Any, Mapping, Sequence

from tools.datasets.build_hand_history_increment import split_for
from tools.simulation.model_b_aggressive_tail import (
    AggressiveTailModel,
    TAIL_CLASSES,
    artifact_sha256 as tail_artifact_sha256,
    build_artifact,
)
from tools.simulation.model_b_price_response import ResponseToPriceModel, HIERARCHY
from tools.simulation.model_b_support_aware_backoff import (
    SupportAwareBackoffModel,
    artifact_sha256 as support_artifact_sha256,
)
from tools.training.independent_profiles.build_model_b import sha256_file
from tools.training.independent_profiles.build_player_features import merge_archives
from tools.training.independent_profiles.evaluate_observed_vs_simulated_calibration_v1 import (
    _aggressive_rates,
    _domain_groups,
    _probability_metrics,
    _reference_sizing_values,
    _stable_seed,
    action_support_state,
    context_id,
    exact_context,
    quantile,
    sizing_support_state,
    wilson95,
)
from tools.training.independent_profiles.evaluate_response_to_price_v1 import (
    ReferencePredictor,
    load_json,
    records_to_observations,
    write_json,
)

REPORT_SCHEMA = "model-b-aggressive-tail-validation/v1"
SUMMARY_SCHEMA = "model-b-aggressive-tail-summary/v1"
RESULT_SCHEMA = "model-b-aggressive-tail-result/v1"
EPS = 1e-12
TAIL_METRICS = ("jam", "overbet", "aggressive_tail")


def select_split(records, split_name: str):
    if split_name not in {"TRAIN", "VALIDATION"}:
        raise ValueError("issue #298 permits only TRAIN and VALIDATION")
    return [r for r in records if split_for(str(r.hand_id)) == split_name]


def _file_identity(path: Path) -> dict[str, Any]:
    return {"path": str(path), "sha256": sha256_file(path), "size_bytes": path.stat().st_size}


def _row_action_probs(kind: str, model, row: Mapping[str, Any]) -> dict[str, float]:
    raw = model(row) if kind == "reference" else model.predict(**row)
    return {a: float(raw["probabilities"][a]) for a in ("FOLD", "CALL", "RAISE")}


def _row_sizing_median(kind: str, model, row: Mapping[str, Any]) -> float | None:
    raw = model(row) if kind == "reference" else model.predict(**row)
    median = (raw.get("sizing") or {}).get("median")
    return None if median is None else float(median)


def _row_sizing_values(kind: str, model, row: Mapping[str, Any]) -> list[float]:
    if kind == "reference":
        return _reference_sizing_values(model, row)
    return [float(v) for v in model.sizing_values(**row)]


def _observed_tail_indicators(row: Mapping[str, Any]) -> dict[str, float]:
    action = str(row["action"]).upper()
    sizing = row.get("raise_sizing_ratio")
    is_raise = action == "RAISE" and sizing is not None
    value = float(sizing) if is_raise else None
    price = row.get("facing_price_to_pot")
    jam = bool(row.get("is_jam"))
    overbet = bool(is_raise and value > 1.0)
    aggressive_tail = bool(
        jam
        or (is_raise and price is not None and float(price) > 1.5)
        or (is_raise and value > 1.5)
    )
    return {
        "jam": float(jam),
        "overbet": float(overbet),
        "aggressive_tail": float(aggressive_tail),
    }


def _row_expected_tails(kind: str, model, row: Mapping[str, Any]) -> dict[str, float]:
    probs = _row_action_probs(kind, model, row)
    raise_prob = probs["RAISE"]
    if kind == "tail":
        t = model.tail_probabilities(**row)
        return {
            "jam": raise_prob * float(t["jam_conditional_on_raise"]),
            "overbet": raise_prob * float(t["overbet_conditional_on_raise"]),
            "aggressive_tail": raise_prob * float(t["aggressive_tail_conditional_on_raise"]),
        }
    values = _row_sizing_values(kind, model, row)
    rates = _aggressive_rates(
        values,
        spr=row.get("spr"),
        price=row.get("facing_price_to_pot"),
    )
    if rates is None:
        return {metric: 0.0 for metric in TAIL_METRICS}
    return {
        "jam": raise_prob * float(rates["jam_like_conditional_on_raise"]),
        "overbet": raise_prob * float(rates["overbet_conditional_on_raise"]),
        "aggressive_tail": raise_prob * float(rates["tail_conditional_on_raise"]),
    }


def _action_calibration(rows, kind: str, model) -> dict[str, Any]:
    actuals = [str(r["action"]).upper() for r in rows]
    probs = [_row_action_probs(kind, model, r) for r in rows]
    metrics = _probability_metrics(actuals, probs)
    observed = collections.Counter(actuals)
    per_action = {}
    for action in ("FOLD", "CALL", "RAISE"):
        obs = observed[action] / len(rows)
        pred = statistics.fmean(p[action] for p in probs)
        per_action[action] = {
            "observed_count": int(observed[action]),
            "observed_frequency": obs,
            "observed_frequency_ci95": wilson95(int(observed[action]), len(rows)),
            "predicted_frequency": pred,
            "absolute_error": abs(pred - obs),
        }
    return {**metrics, "actions": per_action}


def _sizing_calibration(rows, kind: str, model) -> dict[str, Any]:
    errors = []
    distinct_hands = set()
    for row in rows:
        if str(row["action"]).upper() != "RAISE" or row.get("raise_sizing_ratio") is None:
            continue
        actual = float(row["raise_sizing_ratio"])
        median = _row_sizing_median(kind, model, row)
        if median is None or median <= 0 or actual <= 0:
            continue
        distinct_hands.add(str(row["hand_id"]))
        errors.append(abs(math.log2(actual / median)))
    return {
        "n": len(errors),
        "distinct_raise_hands": len(distinct_hands),
        "mean_absolute_log2_error": statistics.fmean(errors) if errors else None,
        "median_absolute_log2_error": quantile(errors, 0.5),
        "p90_absolute_log2_error": quantile(errors, 0.9),
    }


def _tail_rows(rows, models: Mapping[str, tuple[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        item = {
            "hand_id": str(row["hand_id"]),
            "observed": _observed_tail_indicators(row),
            "expected": {},
        }
        for name, (kind, model) in models.items():
            item["expected"][name] = _row_expected_tails(kind, model, row)
        out.append(item)
    return out


def _tail_aggregate(items: Sequence[Mapping[str, Any]], model_name: str) -> dict[str, Any]:
    n = len(items)
    if n == 0:
        raise ValueError("tail aggregate requires rows")
    metrics = {}
    errors = []
    for metric in TAIL_METRICS:
        observed_count = sum(float(x["observed"][metric]) for x in items)
        obs = observed_count / n
        pred = statistics.fmean(float(x["expected"][model_name][metric]) for x in items)
        err = abs(pred - obs)
        errors.append(err)
        metrics[metric] = {
            "observed_count": int(observed_count),
            "observed_frequency": obs,
            "observed_frequency_ci95": wilson95(int(observed_count), n),
            "predicted_frequency": pred,
            "absolute_error": err,
        }
    return {
        "observations": n,
        "metrics": metrics,
        "tail_score_mean_absolute_error": statistics.fmean(errors),
    }


def _support_state(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    hands = {str(r["hand_id"]) for r in rows}
    raise_rows = [
        r for r in rows
        if str(r["action"]).upper() == "RAISE" and r.get("raise_sizing_ratio") is not None
    ]
    raise_hands = {str(r["hand_id"]) for r in raise_rows}
    action = action_support_state(len(rows), len(hands))
    sizing = sizing_support_state(len(raise_rows), len(raise_hands))
    supported = action == "SUPPORTED" and sizing == "SUPPORTED"
    return {
        "observations": len(rows),
        "distinct_hands": len(hands),
        "raise_observations": len(raise_rows),
        "distinct_raise_hands": len(raise_hands),
        "action_support": action,
        "tail_support": sizing,
        "joint_support": "SUPPORTED" if supported else (
            "LOW_SUPPORT" if action != "INSUFFICIENT_SUPPORT" and sizing != "INSUFFICIENT_SUPPORT"
            else "INSUFFICIENT_SUPPORT"
        ),
    }


def _tail_bootstrap_delta(
    items: Sequence[Mapping[str, Any]],
    *,
    candidate: str,
    baseline: str,
    samples: int,
    label: str,
) -> dict[str, Any] | None:
    by_hand: dict[str, list[Mapping[str, Any]]] = collections.defaultdict(list)
    for item in items:
        by_hand[str(item["hand_id"])].append(item)
    hands = sorted(by_hand)
    if len(hands) < 2 or len(items) < 10:
        return None

    def deltas(sample_items):
        ca = _tail_aggregate(sample_items, candidate)
        ba = _tail_aggregate(sample_items, baseline)
        result = {
            "tail_score": ca["tail_score_mean_absolute_error"] - ba["tail_score_mean_absolute_error"]
        }
        for metric in TAIL_METRICS:
            result[metric] = (
                ca["metrics"][metric]["absolute_error"]
                - ba["metrics"][metric]["absolute_error"]
            )
        return result

    observed = deltas(items)
    rng = random.Random(_stable_seed(label))
    draws = {name: [] for name in ("tail_score", *TAIL_METRICS)}
    for _ in range(int(samples)):
        sampled = []
        for _ in hands:
            picked = hands[rng.randrange(len(hands))]
            sampled.extend(by_hand[picked])
        d = deltas(sampled)
        for name in draws:
            draws[name].append(float(d[name]))

    return {
        "cluster_unit": "hand_id",
        "distinct_hands": len(hands),
        "decisions": len(items),
        "bootstrap_samples": int(samples),
        "seed": _stable_seed(label),
        "candidate_minus_baseline": {
            name: {
                "observed": float(observed[name]),
                "ci95": [quantile(draws[name], 0.025), quantile(draws[name], 0.975)],
            }
            for name in draws
        },
    }


def _comparison_class(support: Mapping[str, Any], bootstrap: Mapping[str, Any] | None) -> str:
    if support["joint_support"] != "SUPPORTED" or bootstrap is None:
        return "INSUFFICIENT_SUPPORT"
    low, high = bootstrap["candidate_minus_baseline"]["tail_score"]["ci95"]
    if float(high) < 0:
        return "IMPROVED"
    if float(low) > 0:
        return "DEGRADED"
    return "SIMILAR"


def _tail_selection_coverage(rows, model: AggressiveTailModel) -> dict[str, Any]:
    counts = collections.Counter()
    reasons = collections.Counter()
    for row in rows:
        t = model.tail_probabilities(**row)
        counts[str(t["selected_level"]["index"])] += 1
        reasons[str(t["fallback_reason"])] += 1
    n = len(rows)
    return {
        "predictions": n,
        "selected_level_counts": dict(sorted(counts.items())),
        "selected_level_fraction": {k: v / n for k, v in sorted(counts.items())} if n else {},
        "fallback_reason_counts": dict(sorted(reasons.items())),
        "exact_fraction": counts.get("0", 0) / n if n else None,
        "backoff_fraction": (n - counts.get("0", 0)) / n if n else None,
    }


def _domain_summary(rows, models, tail_model, samples: int):
    items_by_row = _tail_rows(rows, models)
    index_by_id = {id(row): idx for idx, row in enumerate(rows)}
    out = []
    for dimension in ("street","relative_position","pot_type","sequence","price_bucket","spr_bucket","profile"):
        for domain, group in _domain_groups(rows, dimension):
            idxs = [index_by_id[id(r)] for r in group]
            items = [items_by_row[i] for i in idxs]
            support = _support_state(group)
            bootstrap = _tail_bootstrap_delta(
                items,
                candidate="tail298",
                baseline="support286",
                samples=samples,
                label=f"domain|{dimension}|{domain['value']}|tail298-vs-286",
            )
            out.append({
                "domain": domain,
                "support": support,
                "tail298": _tail_aggregate(items, "tail298"),
                "support286": _tail_aggregate(items, "support286"),
                "candidate_minus_286_uncertainty": bootstrap,
                "comparison_vs_286": _comparison_class(support, bootstrap),
            })
    return out


def evaluate(args: argparse.Namespace) -> int:
    protocol = load_json(Path(args.protocol))
    graph = load_json(Path(args.graph))
    if protocol.get("schema") != "model-b-aggressive-tail-protocol/v1":
        raise ValueError("unsupported #298 protocol")
    if protocol.get("status") != "FROZEN_BEFORE_VALIDATION":
        raise ValueError("#298 protocol is not frozen")
    split = protocol["split_contract"]
    if split.get("fit") != ["TRAIN"] or split.get("evaluate") != ["VALIDATION"]:
        raise ValueError("TRAIN/VALIDATION split contract changed")
    if split.get("forbidden") != ["TEST"] or split.get("test_consumed") is not False:
        raise ValueError("TEST must remain forbidden")
    science = protocol["scientific_constraints"]
    if science.get("hyperparameters_selected_on_validation") is not False:
        raise ValueError("VALIDATION hyperparameter selection forbidden")
    if science.get("production_effect") != "NONE" or science.get("automatic_promotion") is not False:
        raise ValueError("analysis must remain non-production")
    if [x["dimensions"] for x in graph["levels"]] != [list(x) for x in HIERARCHY]:
        raise ValueError("tail graph differs from #286 hierarchy")

    source197_result = load_json(Path(args.source197_result))
    source286_result = load_json(Path(args.source286_result))
    if source197_result.get("test_consumed") is not False or source286_result.get("test_consumed") is not False:
        raise ValueError("upstream TEST state changed")

    candidate197_doc = load_json(Path(args.candidate197_artifact))
    support286_doc = load_json(Path(args.candidate286_artifact))
    support_sha = support_artifact_sha256(support286_doc)
    if support_sha != str(protocol["source_issue_286_candidate_artifact_sha256"]):
        raise ValueError("#286 candidate artifact identity changed")
    candidate197 = ResponseToPriceModel(candidate197_doc)
    support286 = SupportAwareBackoffModel(support286_doc)

    source197_protocol = load_json(Path(args.source197_protocol))
    expected_archives = {row["path"]: row["sha256"] for row in source197_protocol["data"]["archives"]}
    archive_identity = []
    for raw in args.archive:
        path = Path(raw)
        digest = sha256_file(path)
        if expected_archives.get(str(path)) != digest:
            raise ValueError(f"archive identity differs from #197 frozen protocol: {path}")
        archive_identity.append({"path": str(path), "sha256": digest})

    by_id, provenance = merge_archives(args.archive, set(args.stake))
    records = list(by_id.values())
    profiles = load_json(Path(args.incumbent_model_dir) / "profiles.json")
    excluded = set(args.exclude_player)

    train_records = select_split(records, "TRAIN")
    train = records_to_observations(train_records, profiles, excluded)
    for row in train:
        row["source_split"] = "TRAIN"
    if not train:
        raise ValueError("no TRAIN observations")

    # Freeze the complete #298 candidate before materializing VALIDATION observations.
    tail_doc = build_artifact(
        train,
        graph=graph,
        base_action_artifact=support286_doc,
        alpha_per_tail_class=float(protocol["method"]["alpha_per_tail_class"]),
    )
    tail_model = AggressiveTailModel(tail_doc, support286_doc)
    model_dir = Path(args.output_dir) / "model"
    model_dir.mkdir(parents=True, exist_ok=True)
    write_json(model_dir / "aggressive_tail.json", tail_doc)

    train_raises = [
        r for r in train
        if str(r["action"]).upper() == "RAISE" and r.get("raise_sizing_ratio") is not None
    ]
    global_class_counts = collections.Counter()
    for row in train_raises:
        t = tail_model.tail_probabilities(**row)
        # Use fit artifact counts for provenance audit via selected context; raw class totals are below.
        del t
        from tools.simulation.model_b_aggressive_tail import tail_class
        global_class_counts[tail_class(row)] += 1
    fit_audit = {
        "schema": "model-b-aggressive-tail-train-fit-audit/v1",
        "fit_split": "TRAIN",
        "test_consumed": False,
        "validation_used_for_selection": False,
        "representation": protocol["representation"],
        "thresholds": tail_doc["thresholds"],
        "alpha_per_tail_class": tail_doc["alpha_per_tail_class"],
        "training_counts": tail_doc["training_counts"],
        "global_class_counts": {klass: int(global_class_counts.get(klass, 0)) for klass in TAIL_CLASSES},
        "level_node_counts": [
            {
                "level": level["index"],
                "dimensions": level["dimensions"],
                "nodes": len(level["data"]),
                "supported_nodes": sum(
                    1 for node in level["data"].values()
                    if node["raise_observations"] >= graph["tail_support"]["min_raises"]
                    and node["distinct_raise_hands"] >= graph["tail_support"]["min_distinct_hands"]
                ),
            }
            for level in tail_doc["levels"]
        ],
        "train_raise_selection_coverage": _tail_selection_coverage(train_raises, tail_model),
    }
    write_json(Path(args.output_dir) / "TRAIN_FIT_AUDIT.json", fit_audit)

    validation_records = select_split(records, "VALIDATION")
    validation = records_to_observations(validation_records, profiles, excluded)
    if not validation:
        raise ValueError("no VALIDATION observations")
    if any(split_for(str(row["hand_id"])) != "VALIDATION" for row in validation):
        raise ValueError("non-VALIDATION row reached #298 evaluation")

    reference = ReferencePredictor(Path(args.incumbent_model_dir))
    models = {
        "reference": ("reference", reference),
        "candidate197": ("candidate", candidate197),
        "support286": ("candidate", support286),
        "tail298": ("tail", tail_model),
    }

    # Strong global guard: #298 cannot move action probabilities or sizing distribution.
    for row in validation:
        p286 = support286.predict(**row)
        p298 = tail_model.predict(**row)
        if p286["probabilities"] != p298["probabilities"]:
            raise AssertionError("#298 changed #286 action probabilities")
        if support286.sizing_values(**row) != tail_model.sizing_values(**row):
            raise AssertionError("#298 changed #286 conditional sizing distribution")

    action_metrics = {
        name: _action_calibration(validation, kind, model)
        for name, (kind, model) in models.items()
    }
    sizing_metrics = {
        name: _sizing_calibration(validation, kind, model)
        for name, (kind, model) in models.items()
    }
    tail_items = _tail_rows(validation, models)
    tail_metrics = {name: _tail_aggregate(tail_items, name) for name in models}
    global_support = _support_state(validation)
    global_bootstrap = _tail_bootstrap_delta(
        tail_items,
        candidate="tail298",
        baseline="support286",
        samples=args.bootstrap_samples,
        label="GLOBAL|tail298-vs-286",
    )

    action_guard = (
        action_metrics["tail298"]["log_loss"] == action_metrics["support286"]["log_loss"]
        and action_metrics["tail298"]["brier"] == action_metrics["support286"]["brier"]
        and action_metrics["tail298"]["ece_confidence"] == action_metrics["support286"]["ece_confidence"]
        and action_metrics["tail298"]["actions"] == action_metrics["support286"]["actions"]
    )
    sizing_guard = sizing_metrics["tail298"] == sizing_metrics["support286"]
    if global_support["joint_support"] != "SUPPORTED" or global_bootstrap is None:
        gate = "INSUFFICIENT_SUPPORT"
    else:
        low, high = global_bootstrap["candidate_minus_baseline"]["tail_score"]["ci95"]
        improved = float(high) < 0
        if improved and action_guard and sizing_guard:
            gate = "TAIL_IMPROVEMENT_WITHOUT_GLOBAL_DEGRADATION"
        elif improved:
            gate = "GLOBAL_TAIL_TRADEOFF"
        else:
            gate = "NO_GAIN"

    domains = _domain_summary(
        validation, models, tail_model,
        samples=args.bootstrap_samples,
    )
    domain_counts = collections.Counter(row["comparison_vs_286"] for row in domains)

    row_fingerprint = hashlib.sha256(
        json.dumps(
            [(str(r["hand_id"]), exact_context(r), str(r["action"]), bool(r.get("is_jam")), r.get("raise_sizing_ratio")) for r in validation],
            sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()

    predictions = []
    for idx, row in enumerate(validation):
        t = tail_model.tail_probabilities(**row)
        predictions.append({
            "row_index": idx,
            "hand_id": str(row["hand_id"]),
            "exact_context": exact_context(row),
            "actual_action": str(row["action"]),
            "actual_tail_indicators": _observed_tail_indicators(row),
            "expected_tails": {
                name: _row_expected_tails(kind, model, row)
                for name, (kind, model) in models.items()
            },
            "tail298_provenance": t,
        })

    report = {
        "schema": REPORT_SCHEMA,
        "issue": 298,
        "status": "COMPLETE",
        "dataset": {
            "population_id": args.population_id,
            "fit_split": "TRAIN",
            "evaluation_split": "VALIDATION",
            "reserved_holdout": "TEST_NOT_CONSUMED",
            "test_consumed": False,
            "archives": archive_identity,
            "train_hand_records": len(train_records),
            "train_facing_decisions": len(train),
            "train_raise_decisions": len(train_raises),
            "validation_hand_records": len(validation_records),
            "validation_facing_decisions": len(validation),
            "validation_distinct_hands": len({str(r["hand_id"]) for r in validation}),
            "validation_row_fingerprint": row_fingerprint,
        },
        "comparability": {
            "same_validation_rows_all_models": True,
            "same_public_context_set_all_models": True,
            "context_dimensions": list(HIERARCHY[0]),
            "model_names": list(models),
            "tail_definitions_shared": True,
        },
        "identities": {
            "reference": {"model_dir": str(args.incumbent_model_dir)},
            "candidate197": _file_identity(Path(args.candidate197_artifact)),
            "support286": {
                **_file_identity(Path(args.candidate286_artifact)),
                "artifact_sha256": support_sha,
            },
            "tail298": {
                "artifact_sha256": tail_artifact_sha256(tail_doc),
                "protocol": _file_identity(Path(args.protocol)),
                "graph": _file_identity(Path(args.graph)),
                "base_support286_artifact_sha256": support_sha,
            },
        },
        "global": {
            "support": global_support,
            "action_calibration": action_metrics,
            "sizing_calibration": sizing_metrics,
            "tail_calibration": tail_metrics,
            "tail298_vs_286_uncertainty": global_bootstrap,
            "action_guard_equal_to_286": action_guard,
            "sizing_guard_equal_to_286": sizing_guard,
            "descriptive_gate": gate,
        },
        "tail298_selection_coverage": _tail_selection_coverage(validation, tail_model),
        "domain_summaries": domains,
        "domain_comparison_counts_vs_286": dict(sorted(domain_counts.items())),
        "predictions": predictions,
        "test_consumed": False,
        "production_effect": "NONE",
        "automatic_promotion": False,
        "active_model_b_changed": False,
        "feature_safety": {
            "model_a_or_hero_or_ev_consumed": False,
            "allowed_dimensions": list(HIERARCHY[0]),
        },
        "provenance": {"raw_provenance_available": bool(provenance)},
    }
    write_json(Path(args.output_dir) / "REPORT.json", report)

    improved_domains = [d for d in domains if d["comparison_vs_286"] == "IMPROVED"]
    degraded_domains = [d for d in domains if d["comparison_vs_286"] == "DEGRADED"]
    summary = {
        "schema": SUMMARY_SCHEMA,
        "issue": 298,
        "evaluation_split": "VALIDATION",
        "test_consumed": False,
        "production_effect": "NONE",
        "descriptive_gate": gate,
        "global_support": global_support,
        "action_calibration": {
            name: {
                "log_loss": value["log_loss"],
                "brier": value["brier"],
                "ece_confidence": value["ece_confidence"],
                "actions": value["actions"],
            }
            for name, value in action_metrics.items()
        },
        "sizing_calibration": sizing_metrics,
        "tail_calibration": tail_metrics,
        "tail298_vs_286_uncertainty": global_bootstrap,
        "action_guard_equal_to_286": action_guard,
        "sizing_guard_equal_to_286": sizing_guard,
        "tail298_selection_coverage": report["tail298_selection_coverage"],
        "domain_comparison_counts_vs_286": dict(sorted(domain_counts.items())),
        "improved_domains_vs_286": improved_domains[:20],
        "degraded_domains_vs_286": degraded_domains[:20],
        "interpretation": (
            "Descriptive frozen VALIDATION comparison only. The #298 component leaves #286 action "
            "probabilities and sizing distribution unchanged and evaluates an explicit TRAIN-fitted "
            "conditional aggressive-tail probability component. No activation or promotion follows."
        ),
    }
    write_json(Path(args.output_dir) / "SUMMARY.json", summary)

    result = {
        "schema": RESULT_SCHEMA,
        "issue": 298,
        "status": "COMPLETE",
        "descriptive_gate": gate,
        "test_consumed": False,
        "production_effect": "NONE",
        "automatic_promotion": False,
        "active_model_b_changed": False,
        "dod": {
            "protocol_thresholds_hyperparameters_frozen_before_validation": True,
            "train_validation_strictly_separated": True,
            "test_unconsumed": True,
            "same_validation_rows_all_models": True,
            "jams_overbets_aggressive_tails_reported_separately": True,
            "global_calibration_guarded": bool(action_guard and sizing_guard),
            "support_provenance_persisted": True,
            "deterministic_report_contract": True,
            "active_model_b_pointer_unchanged": True,
            "no_108_model_a_hero_central_ui": True,
        },
        "artifacts": {
            "protocol": "PROTOCOL.json",
            "graph": "TAIL_GRAPH.json",
            "candidate": "model/aggressive_tail.json",
            "train_fit_audit": "TRAIN_FIT_AUDIT.json",
            "report": "REPORT.json",
            "summary": "SUMMARY.json",
        },
    }
    write_json(Path(args.output_dir) / "RESULT.json", result)

    print(json.dumps({
        "train_decisions": len(train),
        "train_raises": len(train_raises),
        "validation_decisions": len(validation),
        "gate": gate,
        "action_guard_equal_to_286": action_guard,
        "sizing_guard_equal_to_286": sizing_guard,
        "tails": {
            name: tail_metrics[name]
            for name in ("reference","candidate197","support286","tail298")
        },
        "tail298_vs_286_uncertainty": global_bootstrap,
        "domain_counts": dict(sorted(domain_counts.items())),
        "test_consumed": False,
        "production_effect": "NONE",
    }, indent=2))
    return 0


def parser():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive",type=Path,action="append",required=True)
    p.add_argument("--stake",action="append",default=["100/200"])
    p.add_argument("--exclude-player",action="append",default=[])
    p.add_argument("--incumbent-model-dir",type=Path,required=True)
    p.add_argument("--candidate197-artifact",type=Path,required=True)
    p.add_argument("--candidate286-artifact",type=Path,required=True)
    p.add_argument("--source197-protocol",type=Path,required=True)
    p.add_argument("--source197-result",type=Path,required=True)
    p.add_argument("--source286-result",type=Path,required=True)
    p.add_argument("--protocol",type=Path,required=True)
    p.add_argument("--graph",type=Path,required=True)
    p.add_argument("--population-id",required=True)
    p.add_argument("--output-dir",type=Path,required=True)
    p.add_argument("--bootstrap-samples",type=int,default=1000)
    p.set_defaults(func=evaluate)
    return p


def main():
    args=parser().parse_args()
    return int(args.func(args))


if __name__=="__main__":
    raise SystemExit(main())

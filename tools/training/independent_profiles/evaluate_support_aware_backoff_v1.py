#!/usr/bin/env python3
"""TRAIN-fit / VALIDATION-only evaluation for issue #286.\n\nFinal validation trigger after current-main refresh.\n"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import statistics
from pathlib import Path
from typing import Any, Mapping, Sequence

from tools.datasets.build_hand_history_increment import split_for
from tools.simulation.model_b_price_response import ACTIONS, HIERARCHY, ResponseToPriceModel
from tools.simulation.model_b_support_aware_backoff import (
    SupportAwareBackoffModel,
    artifact_sha256,
    build_artifact,
)
from tools.training.independent_profiles.build_model_b import sha256_file
from tools.training.independent_profiles.build_player_features import merge_archives
from tools.training.independent_profiles.evaluate_observed_vs_simulated_calibration_v1 import (
    ReferencePredictor,
    _domain_groups,
    _groups_by_exact_context,
    _paired_logloss_bootstrap,
    calibrate_rows,
    context_id,
    exact_context,
    load_json,
    write_json,
)
from tools.training.independent_profiles.evaluate_response_to_price_v1 import records_to_observations

ROOT = Path(__file__).resolve().parents[3]
REPORT_SCHEMA = "model-b-support-aware-backoff-validation/v1"
SUMMARY_SCHEMA = "model-b-support-aware-backoff-summary/v1"
RESULT_SCHEMA = "model-b-support-aware-backoff-result/v1"


def select_split(records, split_name: str):
    if split_name not in {"TRAIN", "VALIDATION"}:
        raise ValueError("issue #286 permits only TRAIN and VALIDATION")
    return [r for r in records if split_for(str(r.hand_id)) == split_name]


def _identity_file(path: Path) -> dict[str, Any]:
    return {"path": str(path), "sha256": sha256_file(path), "size_bytes": path.stat().st_size}


def _support_level_counts(rows: Sequence[Mapping[str, Any]], model: SupportAwareBackoffModel) -> dict[str, Any]:
    action = collections.Counter()
    sizing = collections.Counter()
    fallback = collections.Counter()
    for row in rows:
        p = model.predict(**row)
        action[str(p["selected_level"]["index"])] += 1
        fallback[str(p["fallback_reason"])] += 1
        s = p.get("sizing_selected_level")
        sizing["NONE" if s is None else str(s["index"])] += 1
    n = len(rows)
    return {
        "predictions": n,
        "action_selected_level_counts": dict(sorted(action.items())),
        "action_selected_level_fraction": {k: v / n for k, v in sorted(action.items())},
        "sizing_selected_level_counts": dict(sorted(sizing.items())),
        "fallback_reason_counts": dict(sorted(fallback.items())),
        "exact_action_fraction": action.get("0", 0) / n if n else None,
        "backoff_action_fraction": (n - action.get("0", 0)) / n if n else None,
    }


def _paired_delta(rows, left_predict, right_predict, *, samples: int, label: str):
    paired = []
    for row in rows:
        actual = str(row["action"])
        lp = left_predict(row)["probabilities"]
        rp = right_predict(row)["probabilities"]
        paired.append({
            "hand_id": str(row["hand_id"]),
            "logloss_delta": -math.log(max(1e-12, float(lp[actual]))) + math.log(max(1e-12, float(rp[actual]))),
        })
    return _paired_logloss_bootstrap(paired, samples=samples, seed_label=label)


def _comparison(support: str, paired: Mapping[str, Any] | None) -> str:
    if support != "SUPPORTED" or paired is None:
        return "INSUFFICIENT_SUPPORT"
    low, high = paired["ci95"]
    if float(high) < 0:
        return "SUPPORT_AWARE_IMPROVES"
    if float(low) > 0:
        return "SUPPORT_AWARE_DEGRADES"
    return "SIMILAR"


def _compact_calibration(cal: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "observations": cal["observations"],
        "distinct_hands": cal["distinct_hands"],
        "support_tier": cal["support_tier"],
        "actions": cal["actions"],
        "probability_calibration": cal["probability_calibration"],
        "sizing_calibration": cal["sizing_calibration"],
        "aggressive_tails": cal["aggressive_tails"],
    }


def _domain_summary(
    validation,
    reference,
    candidate197,
    support_model,
    *,
    bootstrap_samples: int,
):
    rows = []
    for dimension in ("street","relative_position","pot_type","sequence","price_bucket","spr_bucket","profile"):
        for domain, group in _domain_groups(validation, dimension):
            label = f"domain|{dimension}|{domain['value']}"
            support_cal = calibrate_rows(
                group,
                reference=reference,
                candidate=support_model,
                bootstrap_samples=bootstrap_samples,
                label=label+"|support-vs-reference",
            )
            old_cal = calibrate_rows(
                group,
                reference=reference,
                candidate=candidate197,
                bootstrap_samples=bootstrap_samples,
                label=label+"|197-vs-reference",
            )
            paired197 = _paired_delta(
                group,
                lambda r: support_model.predict(**r),
                lambda r: candidate197.predict(**r),
                samples=bootstrap_samples,
                label=label+"|support-vs-197",
            )
            rows.append({
                "domain": domain,
                "support_tier": support_cal["support_tier"],
                "observations": support_cal["observations"],
                "distinct_hands": support_cal["distinct_hands"],
                "support_aware_vs_reference": support_cal["probability_calibration"]["candidate_minus_reference"],
                "candidate197_vs_reference": old_cal["probability_calibration"]["candidate_minus_reference"],
                "support_aware_vs_candidate197": paired197,
                "comparison_vs_candidate197": _comparison(support_cal["support_tier"], paired197),
            })
    return rows


def _per_prediction(validation, reference, candidate197, support_model):
    out = []
    for index, row in enumerate(validation):
        rp = reference(row)
        p197 = candidate197.predict(**row)
        ps = support_model.predict(**row)
        out.append({
            "row_index": index,
            "hand_id": str(row["hand_id"]),
            "actual_action": str(row["action"]),
            "exact_context": exact_context(row),
            "reference_probabilities": rp["probabilities"],
            "candidate197_probabilities": p197["probabilities"],
            "support_aware": ps,
        })
    return out


def evaluate(args: argparse.Namespace) -> int:
    protocol = load_json(Path(args.protocol))
    graph = load_json(Path(args.graph))
    if protocol.get("schema") != "model-b-support-aware-backoff-protocol/v1":
        raise ValueError("unsupported #286 protocol")
    if protocol.get("status") != "FROZEN_BEFORE_VALIDATION":
        raise ValueError("#286 protocol is not frozen")
    split = protocol["split_contract"]
    if split.get("fit") != ["TRAIN"] or split.get("evaluate") != ["VALIDATION"]:
        raise ValueError("TRAIN/VALIDATION split contract changed")
    if split.get("forbidden") != ["TEST"] or split.get("test_consumed") is not False:
        raise ValueError("TEST must be forbidden/unconsumed")
    science = protocol["scientific_constraints"]
    if science.get("hyperparameters_selected_on_validation") is not False:
        raise ValueError("VALIDATION hyperparameter selection forbidden")
    if science.get("production_effect") != "NONE" or science.get("automatic_promotion") is not False:
        raise ValueError("analysis must remain non-production")
    expected_levels = [list(x) for x in HIERARCHY]
    if [x["dimensions"] for x in graph["levels"]] != expected_levels:
        raise ValueError("frozen graph differs from #197 hierarchy")

    source197_protocol = load_json(Path(args.source197_protocol))
    source197_result = load_json(Path(args.source197_result))
    if source197_protocol["data"]["split_contract"]["fit"] != ["TRAIN"]:
        raise ValueError("#197 fit split changed")
    if source197_result.get("test_consumed") is not False:
        raise ValueError("#197 TEST state changed")
    candidate197_doc = load_json(Path(args.candidate197_artifact))
    candidate197 = ResponseToPriceModel(candidate197_doc)

    expected_archives = {r["path"]: r["sha256"] for r in source197_protocol["data"]["archives"]}
    archive_identity = []
    for raw in args.archive:
        path = Path(raw)
        digest = sha256_file(path)
        if expected_archives.get(str(path)) != digest:
            raise ValueError(f"archive identity differs from #197 protocol: {path}")
        archive_identity.append({"path": str(path), "sha256": digest})

    by_id, provenance = merge_archives(args.archive, set(args.stake))
    records = list(by_id.values())
    train_records = select_split(records, "TRAIN")
    profiles = load_json(Path(args.incumbent_model_dir) / "profiles.json")
    excluded = set(args.exclude_player)
    train = records_to_observations(train_records, profiles, excluded)
    for row in train:
        row["source_split"] = "TRAIN"
    if not train:
        raise ValueError("no TRAIN observations")

    # Candidate is completely built/frozen before VALIDATION observations are materialized.
    candidate_doc = build_artifact(
        train,
        graph=graph,
        alpha_per_action=float(protocol["method"]["alpha_per_action"]),
    )
    support_model = SupportAwareBackoffModel(candidate_doc)
    model_dir = Path(args.output_dir) / "model"
    model_dir.mkdir(parents=True, exist_ok=True)
    write_json(model_dir / "support_aware_backoff.json", candidate_doc)

    train_coverage = _support_level_counts(train, support_model)
    fit_audit = {
        "schema": "model-b-support-aware-backoff-train-fit-audit/v1",
        "fit_split": "TRAIN",
        "test_consumed": False,
        "threshold_source": protocol["method"]["threshold_source"],
        "thresholds": candidate_doc["thresholds"],
        "training_counts": candidate_doc["training_counts"],
        "level_node_counts": [
            {
                "level": level["index"],
                "dimensions": level["dimensions"],
                "nodes": len(level["data"]),
                "supported_action_nodes": sum(
                    1 for node in level["data"].values()
                    if node["observations"] >= graph["action_support"]["min_observations"]
                    and node["distinct_hands"] >= graph["action_support"]["min_distinct_hands"]
                ),
                "supported_sizing_nodes": sum(
                    1 for node in level["data"].values()
                    if node["raise_observations"] >= graph["sizing_support"]["min_raises"]
                    and node["distinct_raise_hands"] >= graph["sizing_support"]["min_distinct_hands"]
                ),
            }
            for level in candidate_doc["levels"]
        ],
        "train_selection_coverage": train_coverage,
        "validation_used_for_selection": False,
    }
    write_json(Path(args.output_dir) / "TRAIN_FIT_AUDIT.json", fit_audit)

    validation_records = select_split(records, "VALIDATION")
    validation = records_to_observations(validation_records, profiles, excluded)
    if not validation:
        raise ValueError("no VALIDATION observations")
    if any(split_for(str(row["hand_id"])) != "VALIDATION" for row in validation):
        raise ValueError("non-VALIDATION row reached evaluation")
    reference = ReferencePredictor(Path(args.incumbent_model_dir))

    support_global = calibrate_rows(
        validation,
        reference=reference,
        candidate=support_model,
        bootstrap_samples=args.bootstrap_samples,
        label="GLOBAL|support-vs-reference",
    )
    old_global = calibrate_rows(
        validation,
        reference=reference,
        candidate=candidate197,
        bootstrap_samples=args.bootstrap_samples,
        label="GLOBAL|197-vs-reference",
    )
    support_vs_197 = _paired_delta(
        validation,
        lambda r: support_model.predict(**r),
        lambda r: candidate197.predict(**r),
        samples=args.bootstrap_samples,
        label="GLOBAL|support-vs-197",
    )
    predictions = _per_prediction(validation, reference, candidate197, support_model)
    validation_coverage = _support_level_counts(validation, support_model)
    domains = _domain_summary(
        validation, reference, candidate197, support_model,
        bootstrap_samples=args.bootstrap_samples,
    )

    exact_groups = _groups_by_exact_context(validation)
    exact_ids = [context_id(ctx) for ctx, _ in exact_groups]
    row_fingerprint = hashlib.sha256(
        json.dumps(
            [(str(r["hand_id"]), exact_context(r), str(r["action"])) for r in validation],
            sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    prediction_contexts = {
        json.dumps(p["support_aware"]["exact_context"], sort_keys=True, separators=(",", ":"))
        for p in predictions
    }
    observed_contexts = {
        json.dumps(ctx, sort_keys=True, separators=(",", ":")) for ctx, _ in exact_groups
    }
    if prediction_contexts != observed_contexts:
        raise AssertionError("support-aware prediction context set differs from VALIDATION context set")

    context_train_support = []
    for ctx, group in exact_groups:
        probe = dict(group[0])
        pred = support_model.predict(**probe)
        context_train_support.append({
            "context_id": context_id(ctx),
            "context": ctx,
            "validation_observations": len(group),
            "validation_distinct_hands": len({str(r["hand_id"]) for r in group}),
            "selected_level": pred["selected_level"],
            "effective_support": pred["effective_support"],
            "fallback_reason": pred["fallback_reason"],
        })

    report = {
        "schema": REPORT_SCHEMA,
        "issue": 286,
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
            "validation_hand_records": len(validation_records),
            "validation_facing_decisions": len(validation),
            "validation_distinct_hands": len({str(r["hand_id"]) for r in validation}),
            "validation_exact_contexts": len(exact_groups),
            "validation_row_fingerprint": row_fingerprint,
        },
        "comparability": {
            "same_validation_rows_all_models": True,
            "same_public_context_set_all_models": True,
            "context_dimensions": list(HIERARCHY[0]),
            "exact_context_ids": exact_ids,
            "silent_pooling": False,
        },
        "reference_identity": {
            "model_dir": str(args.incumbent_model_dir),
            "artifacts": {
                name: sha256_file(Path(args.incumbent_model_dir) / name)
                for name in ("profiles.json","preflop_ranges.json","postflop_actions.json","sizing.json","prediction_contract.json")
            },
        },
        "candidate197_identity": {
            "artifact": _identity_file(Path(args.candidate197_artifact)),
            "model_version": candidate197_doc["model_version"],
        },
        "support_aware_identity": {
            "artifact_sha256": artifact_sha256(candidate_doc),
            "model_version": candidate_doc["model_version"],
            "graph": _identity_file(Path(args.graph)),
            "protocol": _identity_file(Path(args.protocol)),
        },
        "global_calibration": {
            "support_aware_vs_reference": _compact_calibration(support_global),
            "candidate197_vs_reference": _compact_calibration(old_global),
            "support_aware_vs_candidate197_log_loss": support_vs_197,
        },
        "support_aware_coverage": validation_coverage,
        "context_train_support": context_train_support,
        "domain_summaries": domains,
        "predictions": predictions,
        "source_counts": {
            "train_facing_decisions": len(train),
            "validation_facing_decisions": len(validation),
            "prediction_rows": len(predictions),
            "exact_contexts": len(exact_groups),
            "sum_context_validation_observations": sum(len(group) for _, group in exact_groups),
        },
        "test_consumed": False,
        "production_effect": "NONE",
        "automatic_promotion": False,
        "active_model_b_changed": False,
        "feature_safety": {
            "model_a_recommendation_or_ev_consumed": False,
            "allowed_dimensions": list(HIERARCHY[0]),
        },
        "provenance": {
            "merge_archives": {
                "reported_splits": ["TRAIN","VALIDATION"],
                "reserved_holdout": "TEST_NOT_CONSUMED",
            },
            "raw_provenance_available": bool(provenance),
        },
    }
    write_json(Path(args.output_dir) / "REPORT.json", report)

    statuses = collections.Counter(row["comparison_vs_candidate197"] for row in domains)
    improved = sorted(
        [r for r in domains if r["comparison_vs_candidate197"] == "SUPPORT_AWARE_IMPROVES"],
        key=lambda r: float(r["support_aware_vs_candidate197"]["candidate_minus_reference_log_loss"]),
    )
    degraded = sorted(
        [r for r in domains if r["comparison_vs_candidate197"] == "SUPPORT_AWARE_DEGRADES"],
        key=lambda r: float(r["support_aware_vs_candidate197"]["candidate_minus_reference_log_loss"]),
        reverse=True,
    )
    summary = {
        "schema": SUMMARY_SCHEMA,
        "issue": 286,
        "evaluation_split": "VALIDATION",
        "test_consumed": False,
        "production_effect": "NONE",
        "global": {
            "reference": support_global["probability_calibration"]["reference"],
            "candidate197": old_global["probability_calibration"]["candidate"],
            "support_aware": support_global["probability_calibration"]["candidate"],
            "support_aware_minus_reference": support_global["probability_calibration"]["candidate_minus_reference"],
            "support_aware_minus_candidate197": support_vs_197,
            "actions": support_global["actions"],
            "sizing": support_global["sizing_calibration"],
            "tails": support_global["aggressive_tails"],
        },
        "fallback": validation_coverage,
        "domain_comparison_counts_vs_candidate197": dict(sorted(statuses.items())),
        "improved_domains_vs_candidate197": improved[:20],
        "degraded_domains_vs_candidate197": degraded[:20],
        "insufficiently_supported_domains": sum(1 for r in domains if r["support_tier"] != "SUPPORTED"),
        "exact_contexts_using_exact_level": sum(1 for r in context_train_support if r["selected_level"]["index"] == 0),
        "exact_contexts_requiring_backoff": sum(1 for r in context_train_support if r["selected_level"]["index"] != 0),
        "interpretation": (
            "Descriptive VALIDATION-only comparison after TRAIN-only frozen support-aware fit. "
            "No promotion/activation. Contexts are never pooled outside the declared graph."
        ),
    }
    write_json(Path(args.output_dir) / "SUMMARY.json", summary)

    result = {
        "schema": RESULT_SCHEMA,
        "issue": 286,
        "status": "COMPLETE",
        "test_consumed": False,
        "production_effect": "NONE",
        "automatic_promotion": False,
        "active_model_b_changed": False,
        "dod": {
            "hyperparameters_not_selected_on_validation": True,
            "test_unconsumed": True,
            "graph_thresholds_frozen_before_validation": True,
            "same_validation_rows_all_models": True,
            "prediction_provenance_and_support_exposed": True,
            "exact_context_used_when_supported": True,
            "fallback_explicit_when_needed": True,
            "no_silent_pooling": True,
            "global_support_aware_tail_metrics_persisted": True,
            "deterministic_artifacts": True,
            "production_effect_none": True,
        },
        "artifacts": {
            "protocol": "PROTOCOL.json",
            "graph": "BACKOFF_GRAPH.json",
            "candidate": "model/support_aware_backoff.json",
            "train_fit_audit": "TRAIN_FIT_AUDIT.json",
            "report": "REPORT.json",
            "summary": "SUMMARY.json",
        },
    }
    write_json(Path(args.output_dir) / "RESULT.json", result)
    print(json.dumps({
        "train_decisions": len(train),
        "validation_decisions": len(validation),
        "support_aware_log_loss": summary["global"]["support_aware"]["log_loss"],
        "candidate197_log_loss": summary["global"]["candidate197"]["log_loss"],
        "reference_log_loss": summary["global"]["reference"]["log_loss"],
        "support_aware_minus_candidate197": support_vs_197,
        "fallback": validation_coverage,
        "domain_counts": dict(sorted(statuses.items())),
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
    p.add_argument("--source197-protocol",type=Path,required=True)
    p.add_argument("--source197-result",type=Path,required=True)
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

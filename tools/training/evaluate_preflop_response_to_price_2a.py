#!/usr/bin/env python3
"""Issue #340: TRAIN-fit and independent VALIDATION for preflop Model B response-to-price.

This evaluator is deliberately fail-closed:
- only certified TRAIN rows are parsed for fit;
- candidate/reference artifacts are frozen on disk before VALIDATION is loaded;
- VALIDATION is used only for paired evaluation;
- TEST is never selected or parsed;
- Model A / Hero EV / Hero recommendation features are forbidden;
- no active pointer, promotion, registry, strategy, or UI mutation is performed.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import random
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]

from tools.datasets.build_hand_history_increment import fingerprint, read_archive, sha256_file, split_for
from tools.simulation.model_b_preflop_response_to_price import (
    ACTIONS,
    EMPIRICAL_FAMILIES,
    EmpiricalPreflopResponseToPriceModel,
    artifact_sha256,
    build_train_artifact,
)
from tools.training.audit_preflop_sizing_support import normalize_action, prepare
from tools.training.increment_decisions import decision_rows, parse_hand

PROTOCOL_SCHEMA = "model-b-preflop-response-to-price-2a-protocol/v1"
REPORT_SCHEMA = "model-b-preflop-response-to-price-2a-validation/v1"
RESULT_SCHEMA = "model-b-preflop-response-to-price-2a-result/v1"
SUMMARY_SCHEMA = "model-b-preflop-response-to-price-2a-summary/v1"
EPS = 1e-15


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def _certified_split_records(certification_path: Path, split_name: str):
    if split_name not in {"TRAIN", "VALIDATION"}:
        raise ValueError("issue #340 may select only TRAIN or VALIDATION")
    cert = load_json(certification_path)
    if cert.get("schema") != "poker-population-certification/v1":
        raise ValueError("unexpected population certification schema")
    status = cert.get("status") or {}
    admissible = status.get("ADMISSIBLE") or {}
    excluded = {str(x) for x in (status.get("EXCLUDED") or {}).get("hand_ids") or []}
    if int((status.get("AMBIGUOUS") or {}).get("unique_hands") or 0):
        raise ValueError("AMBIGUOUS certified hands present")

    by_id = {}
    archives = []
    for source in cert.get("archives") or []:
        rel = str(source.get("path") or "")
        path = ROOT / rel
        if sha256_file(path) != str(source.get("sha256") or ""):
            raise ValueError(f"certified archive hash mismatch: {rel}")
        records, meta = read_archive(path)
        archives.append({"path": rel, "sha256": str(source["sha256"]), "unique_hands": int(meta["unique_hands"])})
        for record in records:
            old = by_id.get(record.hand_id)
            if old is None or (getattr(old, "language", "") != "en" and record.language == "en"):
                by_id[record.hand_id] = record

    target_ids = set(by_id) - excluded
    if len(target_ids) != int(admissible.get("unique_hands") or 0):
        raise ValueError("certified population count mismatch")
    if fingerprint(target_ids) != str(admissible.get("fingerprint_sha256") or ""):
        raise ValueError("certified population fingerprint mismatch")
    selected_ids = {hid for hid in target_ids if split_for(hid) == split_name}
    expected = int((admissible.get("split_counts") or {}).get(split_name) or 0)
    if len(selected_ids) != expected:
        raise ValueError(f"certified {split_name} count mismatch")
    records = [by_id[hid] for hid in sorted(selected_ids, key=int)]
    provenance = {
        "population_id": "pokerstars_nlhe_100-200_zoom_play_6max_v1",
        "certification_path": certification_path.relative_to(ROOT).as_posix(),
        "certification_sha256": sha256_file(certification_path),
        "archives": archives,
        "selected_split": split_name,
        "selected_hands": len(selected_ids),
        "selected_hand_ids_fingerprint_sha256": fingerprint(selected_ids),
        "reserved_holdout": "TEST_NOT_CONSUMED",
        "test_consumed": False,
    }
    return records, provenance


def _profile_identity(profiles: Mapping[str, Any]) -> tuple[Mapping[str, Any], int]:
    player_profile = profiles.get("player_profile") or {}
    rows = profiles.get("profiles") or []
    if not player_profile or not rows:
        raise ValueError("Model B TRAIN profile artifact is incomplete")
    default_profile = int(max(rows, key=lambda row: float(row["appearance_weight"]))["profile"])
    return player_profile, default_profile


def observations_from_records(records, split_name: str, profiles: Mapping[str, Any]) -> list[dict[str, Any]]:
    player_profile, default_profile = _profile_identity(profiles)
    rows: list[dict[str, Any]] = []
    for record in records:
        if split_for(record.hand_id) != split_name:
            raise AssertionError(f"non-{split_name} record crossed parser boundary")
        hand = parse_hand(record.text, record.source_file)
        if not hand:
            raise ValueError(f"certified {split_name} hand failed normalization: {record.hand_id}")
        for raw in decision_rows(hand, include_preflop_context_v1=True):
            if raw.get("split") != split_name:
                raise AssertionError("decision split differs from selected certified split")
            if raw.get("street") != "preflop" or raw.get("is_hero"):
                continue
            family = str(raw.get("family") or "")
            if family not in EMPIRICAL_FAMILIES:
                continue
            action = normalize_action(raw.get("action"))
            if action not in ACTIONS:
                continue
            p = prepare(raw)
            effective = p.get("_effective_stack_bb")
            if effective is None:
                effective = raw.get("actor_remaining_bb_before")
            price = p.get("_price_to_pot")
            target = p.get("_target_total_bb")
            if effective is None or price is None or target is None:
                continue
            player = str(raw.get("player") or "")
            profile = int(player_profile.get(player, default_profile))
            rows.append({
                "source_split": split_name,
                "hand_id": str(raw["hand_id"]),
                "profile": profile,
                "family": family,
                "responder_position": str(raw.get("actor_position") or "NA"),
                "raiser_position": str(p.get("_aggressor_position") or "NONE"),
                "sequence": str(p.get("_action_sequence") or "START"),
                "limper_count": int(p.get("_limper_count") or 0),
                "caller_count": int(p.get("_caller_count") or 0),
                "target_total_bb": float(target),
                "facing_price_to_pot": float(price),
                "effective_stack_bb": float(effective),
                "action": action,
            })
    return rows


def _new_metrics() -> dict[str, Any]:
    return {
        "n": 0,
        "log_loss_sum": 0.0,
        "brier_sum": 0.0,
        "correct": 0,
        "observed": collections.Counter(),
        "predicted": collections.defaultdict(float),
        "support": collections.Counter(),
        "reliability": collections.defaultdict(lambda: {"n": 0, "confidence": 0.0, "correct": 0}),
    }


def _add_metric(state: dict[str, Any], action: str, prediction: Mapping[str, Any]) -> float:
    probs = prediction["probabilities"]
    p = max(float(probs[action]), EPS)
    loss = -math.log(p)
    state["n"] += 1
    state["log_loss_sum"] += loss
    state["brier_sum"] += sum((float(probs[a]) - (1.0 if a == action else 0.0)) ** 2 for a in ACTIONS)
    predicted_action = max(ACTIONS, key=lambda a: (float(probs[a]), a))
    correct = int(predicted_action == action)
    state["correct"] += correct
    state["observed"][action] += 1
    state["support"][str(prediction["support_state"])] += 1
    for a in ACTIONS:
        state["predicted"][a] += float(probs[a])
    confidence = max(float(probs[a]) for a in ACTIONS)
    bucket = str(min(9, int(confidence * 10)))
    state["reliability"][bucket]["n"] += 1
    state["reliability"][bucket]["confidence"] += confidence
    state["reliability"][bucket]["correct"] += correct
    return loss


def _final_metrics(state: Mapping[str, Any]) -> dict[str, Any]:
    n = int(state["n"])
    if not n:
        return {"n": 0}
    ece = 0.0
    reliability = {}
    for key in sorted(state["reliability"], key=int):
        row = state["reliability"][key]
        avg = row["confidence"] / row["n"]
        acc = row["correct"] / row["n"]
        ece += row["n"] / n * abs(avg - acc)
        reliability[key] = {"n": row["n"], "confidence": avg, "accuracy": acc}
    return {
        "n": n,
        "log_loss": state["log_loss_sum"] / n,
        "brier": state["brier_sum"] / n,
        "accuracy": state["correct"] / n,
        "ece_confidence": ece,
        "observed_frequency": {a: state["observed"][a] / n for a in ACTIONS},
        "mean_predicted_frequency": {a: state["predicted"][a] / n for a in ACTIONS},
        "support_state_counts": dict(sorted(state["support"].items())),
        "reliability": reliability,
    }


def paired_validation(
    rows: Sequence[Mapping[str, Any]],
    candidate: EmpiricalPreflopResponseToPriceModel,
    reference: EmpiricalPreflopResponseToPriceModel,
    *,
    bootstrap_samples: int,
    seed: int,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    cand_state, ref_state = _new_metrics(), _new_metrics()
    clustered = collections.defaultdict(lambda: [0.0, 0])
    zone_state: dict[tuple[str, str, str], dict[str, Any]] = {}

    for row in rows:
        cp = candidate.predict(**row)
        rp = reference.predict(**row)
        cl = _add_metric(cand_state, str(row["action"]), cp)
        rl = _add_metric(ref_state, str(row["action"]), rp)
        clustered[str(row["hand_id"])][0] += cl - rl
        clustered[str(row["hand_id"])][1] += 1

        z = cp["price_zone"]
        key = (str(row["family"]), str(z["target_bin"]), str(z["price_bin"]))
        state = zone_state.setdefault(key, {
            "validation_n": 0,
            "observed": collections.Counter(),
            "predicted": collections.defaultdict(float),
            "uncertainty_low": collections.defaultdict(float),
            "uncertainty_high": collections.defaultdict(float),
            "support": collections.Counter(),
        })
        state["validation_n"] += 1
        state["observed"][str(row["action"])] += 1
        state["support"][str(cp["support_state"])] += 1
        for action in ACTIONS:
            state["predicted"][action] += float(cp["probabilities"][action])
            interval = cp["uncertainty"][action]["approx_95"]
            state["uncertainty_low"][action] += float(interval[0])
            state["uncertainty_high"][action] += float(interval[1])

    hands = sorted(clustered)
    total_loss = sum(v[0] for v in clustered.values())
    total_n = sum(v[1] for v in clustered.values())
    observed = total_loss / total_n
    rng = random.Random(seed)
    samples = []
    for _ in range(int(bootstrap_samples)):
        s_loss = 0.0
        s_n = 0
        for _ in range(len(hands)):
            hid = hands[rng.randrange(len(hands))]
            s_loss += clustered[hid][0]
            s_n += clustered[hid][1]
        samples.append(s_loss / s_n)
    samples.sort()
    lo = samples[int(0.025 * (len(samples) - 1))]
    hi = samples[int(0.975 * (len(samples) - 1))]
    paired = {
        "metric": "candidate_minus_reference_action_log_loss",
        "cluster_unit": "hand_id",
        "hands": len(hands),
        "decisions": total_n,
        "bootstrap_samples": int(bootstrap_samples),
        "seed": int(seed),
        "observed": observed,
        "ci95": [lo, hi],
        "probability_candidate_better": sum(x < 0 for x in samples) / len(samples),
    }

    zones = []
    for (family, target_bin, price_bin), state in sorted(zone_state.items()):
        n = state["validation_n"]
        zones.append({
            "family": family,
            "target_bin": target_bin,
            "price_bin": price_bin,
            "validation_n": n,
            "observed_frequency": {a: state["observed"][a] / n for a in ACTIONS},
            "candidate_mean_probability": {a: state["predicted"][a] / n for a in ACTIONS},
            "candidate_mean_approx_95": {
                a: [state["uncertainty_low"][a] / n, state["uncertainty_high"][a] / n]
                for a in ACTIONS
            },
            "support_state_counts": dict(sorted(state["support"].items())),
        })
    return _final_metrics(cand_state), _final_metrics(ref_state), paired, zones


def _train_fit_audit(candidate_doc: Mapping[str, Any]) -> dict[str, Any]:
    levels = []
    for level in candidate_doc["levels"]:
        states = collections.Counter(node["support_state"] for node in level["data"].values())
        levels.append({
            "level": int(level["index"]),
            "dimensions": level["dimensions"],
            "nodes": len(level["data"]),
            "support_states": dict(sorted(states.items())),
        })
    return {
        "schema": "model-b-preflop-response-to-price-2a-train-fit-audit/v1",
        "fit_split": "TRAIN",
        "validation_used_for_fit": False,
        "test_consumed": False,
        "source_issue_319_report_hash": candidate_doc["source_issue_319_report_hash"],
        "training_counts": candidate_doc["training_counts"],
        "thresholds": candidate_doc["thresholds"],
        "levels": levels,
        "no_cross_family_pooling": True,
        "nearest_context_heuristic": False,
    }


def validate_protocol(protocol: Mapping[str, Any], support: Mapping[str, Any]) -> None:
    if protocol.get("schema") != PROTOCOL_SCHEMA:
        raise ValueError("unexpected issue #340 protocol schema")
    if protocol.get("status") != "FROZEN_BEFORE_VALIDATION":
        raise ValueError("issue #340 protocol must be frozen before VALIDATION")
    split = protocol.get("split_contract") or {}
    if split.get("fit") != ["TRAIN"] or split.get("evaluate") != ["VALIDATION"]:
        raise ValueError("invalid TRAIN/VALIDATION protocol")
    if split.get("forbidden") != ["TEST"] or split.get("test_consumed") is not False:
        raise ValueError("TEST must remain forbidden")
    constraints = protocol.get("scientific_constraints") or {}
    if constraints.get("model_a_features_allowed") is not False:
        raise ValueError("Model A features are forbidden")
    if constraints.get("hero_ev_or_recommendation_allowed") is not False:
        raise ValueError("Hero EV/recommendation is forbidden")
    if constraints.get("automatic_promotion") is not False:
        raise ValueError("automatic promotion is forbidden")
    expected = str((protocol.get("source_issue_319") or {}).get("report_hash") or "")
    actual = str((support.get("full_report") or {}).get("report_hash") or "")
    if not expected or expected != actual:
        raise ValueError(f"#319 report hash mismatch: expected={expected} actual={actual}")


def evaluate(args: argparse.Namespace) -> int:
    protocol = load_json(args.protocol)
    support = load_json(args.support_summary)
    validate_protocol(protocol, support)
    profiles = load_json(args.profiles)
    bin_proposals = support.get("bin_proposals") or {}
    method = protocol["method"]

    # TRAIN is the only split crossing the parser boundary before candidate/reference freeze.
    train_records, train_provenance = _certified_split_records(args.certification, "TRAIN")
    train = observations_from_records(train_records, "TRAIN", profiles)
    if not train:
        raise ValueError("no eligible TRAIN preflop response observations")

    common = {
        "bin_proposals": bin_proposals,
        "source_report_hash": (support["full_report"]["report_hash"]),
        "min_observations": int(method["min_observations"]),
        "min_distinct_hands": int(method["min_distinct_hands"]),
        "alpha_per_action": float(method["alpha_per_action"]),
    }
    candidate_doc = build_train_artifact(train, reference_mode=False, **common)
    reference_doc = build_train_artifact(train, reference_mode=True, **common)
    candidate = EmpiricalPreflopResponseToPriceModel(candidate_doc)
    reference = EmpiricalPreflopResponseToPriceModel(reference_doc)

    out = args.output_dir
    model_dir = out / "model"
    write_json(model_dir / "candidate.json", candidate_doc)
    write_json(model_dir / "price_agnostic_reference.json", reference_doc)
    fit_audit = _train_fit_audit(candidate_doc)
    write_json(out / "TRAIN_FIT_AUDIT.json", fit_audit)

    # Only after both TRAIN-fit artifacts are materialized do VALIDATION records cross the parser boundary.
    validation_records, validation_provenance = _certified_split_records(args.certification, "VALIDATION")
    validation = observations_from_records(validation_records, "VALIDATION", profiles)
    if not validation:
        raise ValueError("no eligible VALIDATION preflop response observations")
    if any(row["source_split"] != "VALIDATION" for row in validation):
        raise AssertionError("fit/evaluation split leak")

    candidate_metrics, reference_metrics, paired, zones = paired_validation(
        validation,
        candidate,
        reference,
        bootstrap_samples=int(protocol["paired_validation"]["bootstrap_samples"]),
        seed=int(protocol["paired_validation"]["seed"]),
    )
    lo, hi = paired["ci95"]
    if hi < 0:
        decision = "VALIDATION_SUPPORTS_PRICE_AWARE_CANDIDATE__NO_PROMOTION"
    elif lo > 0:
        decision = "VALIDATION_FAVORS_PRICE_AGNOSTIC_REFERENCE__NO_PROMOTION"
    else:
        decision = "VALIDATION_INCONCLUSIVE__NO_PROMOTION"

    report = {
        "schema": REPORT_SCHEMA,
        "issue": 340,
        "status": "COMPLETE",
        "population_id": train_provenance["population_id"],
        "dataset": {
            "fit_split": "TRAIN",
            "evaluation_split": "VALIDATION",
            "train_hands": train_provenance["selected_hands"],
            "train_decisions": len(train),
            "validation_hands": validation_provenance["selected_hands"],
            "validation_decisions": len(validation),
            "train_hand_ids_fingerprint_sha256": train_provenance["selected_hand_ids_fingerprint_sha256"],
            "validation_hand_ids_fingerprint_sha256": validation_provenance["selected_hand_ids_fingerprint_sha256"],
            "reserved_holdout": "TEST_NOT_CONSUMED",
            "test_consumed": False,
        },
        "source_issue_319": {
            "summary_path": args.support_summary.relative_to(ROOT).as_posix(),
            "report_hash": support["full_report"]["report_hash"],
            "bin_proposals_consumed": True,
            "provenance": support.get("provenance") or {},
        },
        "profile_reference": {
            "path": args.profiles.relative_to(ROOT).as_posix(),
            "schema": profiles.get("schema"),
            "sha256": sha256_file(args.profiles),
            "role": "TRAIN-derived public Model B profile labels only",
        },
        "candidate_identity": {
            **candidate.identity,
            "path": "model/candidate.json",
        },
        "reference_identity": {
            **reference.identity,
            "path": "model/price_agnostic_reference.json",
            "kind": "TRAIN_FITTED_PRICE_AGNOSTIC_PUBLIC_MODEL_B_BASELINE",
            "reason": "the retained Model B has no preflop action-response artifact directly comparable to #340",
        },
        "comparability": {
            "same_validation_rows": True,
            "same_action_taxonomy": list(ACTIONS),
            "candidate_adds_price_sizing_conditioning": True,
            "family_never_dropped": True,
            "nearest_context_heuristic": False,
            "model_a_features_consumed": False,
            "hero_ev_or_recommendation_consumed": False,
        },
        "candidate_actions": candidate_metrics,
        "reference_actions": reference_metrics,
        "paired_action_log_loss": paired,
        "price_zone_validation": zones,
        "decision": decision,
        "test_consumed": False,
        "production_effect": "NONE",
        "automatic_promotion": False,
        "active_model_b_changed": False,
    }
    write_json(out / "VALIDATION_REPORT.json", report)

    summary = {
        "schema": SUMMARY_SCHEMA,
        "issue": 340,
        "status": "COMPLETE",
        "decision": decision,
        "train_decisions": len(train),
        "validation_decisions": len(validation),
        "candidate_log_loss": candidate_metrics["log_loss"],
        "reference_log_loss": reference_metrics["log_loss"],
        "paired_candidate_minus_reference": paired,
        "candidate_support_state_counts": candidate_metrics["support_state_counts"],
        "price_zones": len(zones),
        "candidate_artifact_sha256": artifact_sha256(candidate_doc),
        "reference_artifact_sha256": artifact_sha256(reference_doc),
        "source_issue_319_report_hash": support["full_report"]["report_hash"],
        "test_consumed": False,
        "production_effect": "NONE",
    }
    write_json(out / "SUMMARY.json", summary)

    result = {
        "schema": RESULT_SCHEMA,
        "issue": 340,
        "status": "COMPLETE",
        "decision": decision,
        "test_consumed": False,
        "production_effect": "NONE",
        "automatic_promotion": False,
        "active_model_b_changed": False,
        "hero_sensitivity_run": False,
        "hero_sensitivity_blocked_by": "#314",
        "parent_issue_315_should_remain_open": True,
        "scientific_dod": {
            "reproducible_train_fit": True,
            "issue_319_support_consumed_with_provenance": True,
            "model_b_independent_from_model_a": True,
            "hero_ev_or_recommendation_not_consumed": True,
            "four_action_response_taxonomy": True,
            "support_aware_backoff_preserves_family": True,
            "sparse_and_absent_finer_support_explicit": True,
            "protocol_frozen_before_validation": True,
            "paired_validation_vs_reference_persisted": True,
            "price_zone_uncertainty_persisted": True,
            "test_unconsumed": True,
            "automatic_promotion_disabled": True,
            "active_model_b_unchanged": True,
            "hero_sensitivity_deferred": True,
        },
        "artifacts": {
            "protocol": "PROTOCOL.json",
            "candidate": "model/candidate.json",
            "reference": "model/price_agnostic_reference.json",
            "train_fit_audit": "TRAIN_FIT_AUDIT.json",
            "validation_report": "VALIDATION_REPORT.json",
            "summary": "SUMMARY.json",
        },
    }
    write_json(out / "RESULT.json", result)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--protocol", type=Path, required=True)
    p.add_argument("--support-summary", type=Path, default=ROOT / "analysis/preflop_sizing_support_train.json")
    p.add_argument("--profiles", type=Path, default=ROOT / "training/runs/20260912_independent_profiles_v2/model/profiles.json")
    p.add_argument("--certification", type=Path, default=ROOT / "training/datasets/NLHE_100-200/population_certification.json")
    p.add_argument("--output-dir", type=Path, required=True)
    p.set_defaults(func=evaluate)
    return p


def main() -> int:
    args = parser().parse_args()
    for name in ("protocol", "support_summary", "profiles", "certification", "output_dir"):
        value = getattr(args, name)
        if isinstance(value, Path) and not value.is_absolute():
            setattr(args, name, ROOT / value)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

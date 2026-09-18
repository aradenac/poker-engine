#!/usr/bin/env python3
"""Scientific TRAIN/VALIDATION evaluation for issue #197 response-to-price Model B.

Hard constraints:
- fit only on TRAIN;
- evaluate only on VALIDATION;
- never compute TEST metrics;
- never consume Model A EV/policy/recommendations as Model B features;
- never modify the active Model B or promote automatically.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import statistics
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from tools.datasets.build_hand_history_increment import split_for
from tools.simulation.model_b_price_diagnostics import (
    counterfactual_response_report,
    evaluate_validation,
    plausible_action_environments,
)
from tools.simulation.model_b_price_response import (
    ACTIONS,
    ResponseToPriceModel,
    artifact_sha256,
    build_response_artifact,
    price_bucket,
    spr_bucket,
)
from tools.training.independent_profiles.audit_response_conditioning import starting_stacks
from tools.training.independent_profiles.build_model_b import (
    apply_event,
    parse_hand,
    preflop_summary,
    relative_position,
    sha256_file,
)
from tools.training.independent_profiles.build_player_features import merge_archives
from tools.training.independent_profiles.evaluate_model_b import (
    action_probabilities,
    choose_node,
)

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = "model-b-response-to-price-scientific-evaluation/v1"
HERO_SCHEMA = "model-b-response-to-price-hero-sensitivity/v1"
FINAL_SCHEMA = "model-b-response-to-price-final-decision/v1"
SEED = 20260919
DEFAULT_PRICE_POINTS = (0.20, 0.40, 0.60, 0.90, 1.25, 1.75, 2.50)


def load_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def canonical_action(typ: str) -> str:
    return {
        "check": "CHECK",
        "fold": "FOLD",
        "call": "CALL",
        "bet": "BET",
        "raise": "RAISE",
    }[typ]


def sequence_token(actions: Sequence[str]) -> str:
    return ">".join(actions[-4:]) if actions else "START"


def facing_observations(record, profiles: Mapping[str, Any], excluded: set[str]) -> list[dict[str, Any]]:
    """Reconstruct observable postflop FACING states without private future features."""
    hand = parse_hand(record)
    if hand is None:
        return []
    player_profile = profiles["player_profile"]
    default_profile = int(max(profiles["profiles"], key=lambda p: p["appearance_weight"])["profile"])
    stacks = starting_stacks(record.text, set(hand["players"]))
    pot_type, roles, active, allin, _ = preflop_summary(hand)

    pre_paid = collections.defaultdict(float)
    contributed = collections.defaultdict(float)
    pre_price = 0.0
    pot = 0.0
    for event in hand["events"]["preflop"]:
        pot, pre_price, added = apply_event(event, pre_paid, pot, pre_price)
        contributed[event["player"]] += added

    observations: list[dict[str, Any]] = []
    for street in ("flop", "turn", "river"):
        paid = collections.defaultdict(float)
        price = 0.0
        public_sequence: list[str] = []
        for event in hand["events"][street]:
            actor = event["player"]
            typ = event["type"]
            if typ in {"return", "post"}:
                pot, price, added = apply_event(event, paid, pot, price)
                contributed[actor] += added
                continue
            if typ not in {"fold", "check", "call", "bet", "raise"}:
                continue

            to_call = max(0.0, price - paid[actor])
            mode = "FACING" if to_call > 1e-9 else "FREE"
            action = canonical_action(typ)
            stack = stacks.get(actor)
            remaining = max(0.0, stack - contributed[actor]) if stack is not None else None
            pot_before = float(pot)
            sequence = sequence_token(public_sequence)
            row = {
                "hand_id": str(record.hand_id),
                "profile": int(player_profile.get(actor, default_profile)),
                "street": street,
                "relative_position": relative_position(hand, actor, active, allin),
                "pot_type": pot_type,
                "preflop_role": roles.get(actor, "OTHER"),
                "sequence": sequence,
                "facing_price_to_pot": (to_call / pot_before) if mode == "FACING" and pot_before > 0 else None,
                "spr": (remaining / pot_before) if remaining is not None and pot_before > 0 else None,
                "action": action,
                "is_jam": bool(event.get("allin")),
                "actor": actor,
            }

            pot, price, added = apply_event(event, paid, pot, price)
            contributed[actor] += added
            if (
                mode == "FACING"
                and action in ACTIONS
                and actor not in excluded
                and row["facing_price_to_pot"] is not None
            ):
                if action == "RAISE" and pot_before > 0 and added > 0:
                    row["raise_sizing_ratio"] = float(added) / pot_before
                observations.append(row)

            if typ == "fold":
                active.discard(actor)
                allin.discard(actor)
            if event.get("allin"):
                allin.add(actor)
            public_sequence.append(action)
    return observations


def records_to_observations(records: Iterable, profiles: Mapping[str, Any], excluded: set[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        rows.extend(facing_observations(record, profiles, excluded))
    return rows


def q(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return ordered[0]
    pos = max(0.0, min(1.0, quantile)) * (len(ordered) - 1)
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return ordered[lo]
    w = pos - lo
    return ordered[lo] * (1.0 - w) + ordered[hi] * w


def values_summary(values: Sequence[float]) -> dict[str, Any]:
    clean = [float(v) for v in values if math.isfinite(float(v)) and float(v) > 0]
    return {
        "n": len(clean),
        "p10": q(clean, 0.10),
        "median": q(clean, 0.50),
        "p90": q(clean, 0.90),
        "p99": q(clean, 0.99),
    }


class ReferencePredictor:
    def __init__(self, model_dir: Path) -> None:
        self.model_dir = Path(model_dir)
        self.actions = load_json(self.model_dir / "postflop_actions.json")
        self.sizing = load_json(self.model_dir / "sizing.json")
        self.contract = load_json(self.model_dir / "prediction_contract.json")
        self.action_min = int(self.actions["backoff_min_observations"])
        self.sizing_min = int(self.sizing["backoff_min_observations"])
        self.alpha = float(self.contract["postflop_action"]["alpha_per_action"])

    def __call__(self, observation: Mapping[str, Any]) -> dict[str, Any]:
        row = {
            "profile": int(observation["profile"]),
            "street": str(observation["street"]).lower(),
            "mode": "FACING",
            "relative_position": observation["relative_position"],
            "pot_type": observation["pot_type"],
            "preflop_role": observation["preflop_role"],
        }
        labels = list(self.actions["labels"]["FACING"])
        node, level, key = choose_node(self.actions["levels"], row, self.action_min)
        probabilities = action_probabilities(node, labels, self.alpha)
        sizing_row = {**row, "action": "RAISE"}
        snode, slevel, skey = choose_node(self.sizing["levels"], sizing_row, self.sizing_min)
        sizing = values_summary(snode.get("values", []))
        return {
            "probabilities": probabilities,
            "sizing": sizing,
            "selection": {"level": level, "key": key, "support": int(node.get("n", 0))},
            "sizing_selection": {"level": slevel, "key": skey, "support": int(snode.get("n", 0))},
            "identifiability": "REFERENCE",
        }


def sizing_metrics(
    observations: Sequence[Mapping[str, Any]],
    predictor,
) -> dict[str, Any]:
    errors: list[float] = []
    tail_errors: list[float] = []
    inside = above_p99 = predicted = tail_predicted = 0
    raises = tail_raises = 0
    for row in observations:
        if str(row["action"]) != "RAISE" or row.get("raise_sizing_ratio") is None:
            continue
        actual = float(row["raise_sizing_ratio"])
        raises += 1
        tail = bool(row.get("is_jam")) or float(row.get("facing_price_to_pot") or 0.0) > 1.5 or actual > 1.5
        if tail:
            tail_raises += 1
        pred = predictor(row)
        sizing = pred.get("sizing") or {}
        median = sizing.get("median")
        if median is None or float(median) <= 0:
            continue
        predicted += 1
        if tail:
            tail_predicted += 1
        error = abs(math.log2(max(actual, 1e-12) / max(float(median), 1e-12)))
        errors.append(error)
        if tail:
            tail_errors.append(error)
        p10, p90, p99 = sizing.get("p10"), sizing.get("p90"), sizing.get("p99")
        if p10 is not None and p90 is not None and float(p10) <= actual <= float(p90):
            inside += 1
        if p99 is not None and actual > float(p99):
            above_p99 += 1
    return {
        "raises": raises,
        "predicted": predicted,
        "prediction_coverage": predicted / raises if raises else None,
        "median_absolute_log2_error": q(errors, 0.50),
        "mean_absolute_log2_error": statistics.fmean(errors) if errors else None,
        "p90_absolute_log2_error": q(errors, 0.90),
        "inside_predicted_p10_p90_fraction": inside / predicted if predicted else None,
        "above_predicted_p99_fraction": above_p99 / predicted if predicted else None,
        "tail": {
            "raises": tail_raises,
            "predicted": tail_predicted,
            "median_absolute_log2_error": q(tail_errors, 0.50),
            "p90_absolute_log2_error": q(tail_errors, 0.90),
        },
    }


def support_audit(train: Sequence[Mapping[str, Any]], validation: Sequence[Mapping[str, Any]], *, action_min: int, sizing_min: int) -> dict[str, Any]:
    cells: dict[tuple[str, str, str], dict[str, Any]] = {}
    marginals = {
        "price": collections.Counter(),
        "spr": collections.Counter(),
        "sequence": collections.Counter(),
    }
    for split_name, rows in (("TRAIN", train), ("VALIDATION", validation)):
        for row in rows:
            price = price_bucket(row.get("facing_price_to_pot"))
            spr = spr_bucket(row.get("spr"))
            seq = str(row["sequence"])
            key = (price, spr, seq)
            cell = cells.setdefault(key, {
                "price_bucket": price,
                "spr_bucket": spr,
                "sequence": seq,
                "train_n": 0,
                "validation_n": 0,
                "train_raise_n": 0,
                "validation_raise_n": 0,
                "train_actions": {action: 0 for action in ACTIONS},
                "validation_actions": {action: 0 for action in ACTIONS},
            })
            prefix = "train" if split_name == "TRAIN" else "validation"
            cell[f"{prefix}_n"] += 1
            cell[f"{prefix}_actions"][str(row["action"])] += 1
            if str(row["action"]) == "RAISE":
                cell[f"{prefix}_raise_n"] += 1
            marginals["price"][(split_name, price)] += 1
            marginals["spr"][(split_name, spr)] += 1
            marginals["sequence"][(split_name, seq)] += 1
    out_cells = []
    for key in sorted(cells):
        cell = cells[key]
        cell["action_supported"] = cell["train_n"] >= action_min
        cell["sizing_supported"] = cell["train_raise_n"] >= sizing_min
        out_cells.append(cell)

    def marginal(kind: str) -> list[dict[str, Any]]:
        labels = sorted({key[1] for key in marginals[kind]})
        return [{
            kind: label,
            "train_n": int(marginals[kind][("TRAIN", label)]),
            "validation_n": int(marginals[kind][("VALIDATION", label)]),
        } for label in labels]

    return {
        "schema": "model-b-response-to-price-support-audit/v1",
        "action_min_support": action_min,
        "sizing_min_support": sizing_min,
        "train_decisions": len(train),
        "validation_decisions": len(validation),
        "cells": out_cells,
        "marginals": {
            "price": marginal("price"),
            "spr": marginal("spr"),
            "sequence": marginal("sequence"),
        },
    }


def candidate_support_summary(validation: Sequence[Mapping[str, Any]], model: ResponseToPriceModel) -> dict[str, Any]:
    counts = collections.Counter()
    sizing_counts = collections.Counter()
    for row in validation:
        prediction = model.predict(**row)
        counts[str(prediction["identifiability"])] += 1
        selection = prediction.get("sizing_selection")
        if selection is None:
            sizing_counts["NO_SIZING_SUPPORT"] += 1
        elif selection.get("below_min_support"):
            sizing_counts["LOW_SUPPORT"] += 1
        elif selection.get("used_backoff"):
            sizing_counts["BACKOFF_SUPPORTED"] += 1
        else:
            sizing_counts["LOCAL_SUPPORTED"] += 1
    low = counts["LOW_SUPPORT"]
    return {
        "validation_decisions": len(validation),
        "action_identifiability_counts": dict(sorted(counts.items())),
        "low_action_support_fraction": low / len(validation) if validation else None,
        "sizing_identifiability_counts": dict(sorted(sizing_counts.items())),
    }


def representative_contexts(validation: Sequence[Mapping[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    groups: dict[tuple, list[Mapping[str, Any]]] = collections.defaultdict(list)
    for row in validation:
        key = (
            int(row["profile"]), row["street"], row["relative_position"],
            row["pot_type"], row["sequence"], spr_bucket(row.get("spr")),
        )
        groups[key].append(row)
    selected = sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))[:limit]
    contexts = []
    for _, rows in selected:
        sprs = [float(r["spr"]) for r in rows if r.get("spr") is not None]
        prices = [float(r["facing_price_to_pot"]) for r in rows if r.get("facing_price_to_pot") is not None]
        first = rows[0]
        contexts.append({
            "profile": int(first["profile"]),
            "street": first["street"],
            "relative_position": first["relative_position"],
            "pot_type": first["pot_type"],
            "sequence": first["sequence"],
            "spr": q(sprs, 0.50),
            "representative_price_to_pot": q(prices, 0.50),
            "validation_support": len(rows),
        })
    return contexts


def predictive_gate(evaluation: Mapping[str, Any], sizing: Mapping[str, Any], support: Mapping[str, Any]) -> dict[str, Any]:
    cand = evaluation["candidate_actions"]
    ref = evaluation["reference_actions"]
    pair = evaluation["paired_action_log_loss"]
    cs, rs = sizing["candidate"], sizing["reference"]
    checks = {
        "paired_log_loss_ci95_upper_le_zero": float(pair["ci95"][1]) <= 0.0,
        "candidate_brier_not_worse_by_gt_0_002": float(cand["brier"]) <= float(ref["brier"]) + 0.002,
        "candidate_ece_not_worse_by_gt_0_01": float(cand["ece_confidence"]) <= float(ref["ece_confidence"]) + 0.01,
        "sizing_median_abs_log2_not_worse_by_gt_0_05": (
            cs["median_absolute_log2_error"] is not None
            and rs["median_absolute_log2_error"] is not None
            and float(cs["median_absolute_log2_error"]) <= float(rs["median_absolute_log2_error"]) + 0.05
        ),
        "validation_low_action_support_le_0_10": float(support["low_action_support_fraction"] or 0.0) <= 0.10,
    }
    return {"pass": all(checks.values()), "checks": checks}


def fit_evaluate(args: argparse.Namespace) -> int:
    output = Path(args.output_dir)
    model_dir = output / "model"
    incumbent = Path(args.incumbent_model_dir)
    profiles = load_json(incumbent / "profiles.json")
    by_id, provenance = merge_archives(args.archive, set(args.stake))
    records = list(by_id.values())
    safe_provenance = json.loads(json.dumps(provenance))
    if isinstance(safe_provenance.get("split_counts"), dict):
        safe_provenance["split_counts"].pop("TEST", None)
    safe_provenance["reported_splits"] = ["TRAIN", "VALIDATION"]
    safe_provenance["reserved_holdout"] = "TEST_NOT_CONSUMED"

    # TEST records may exist in the archives but are never selected into either list below.
    train_records = [record for record in records if split_for(record.hand_id) == "TRAIN"]
    validation_records = [record for record in records if split_for(record.hand_id) == "VALIDATION"]
    excluded = set(args.exclude_player)
    train = records_to_observations(train_records, profiles, excluded)
    validation = records_to_observations(validation_records, profiles, excluded)
    if not train or not validation:
        raise ValueError("TRAIN and VALIDATION must both contain FACING observations")

    artifact = build_response_artifact(
        train,
        min_support=args.action_min_support,
        sizing_min_support=args.sizing_min_support,
        alpha_per_action=args.alpha,
        model_version="model_b_response_to_price_v1_candidate_20260919",
    )
    candidate = ResponseToPriceModel(artifact)
    reference = ReferencePredictor(incumbent)
    evaluation = evaluate_validation(
        validation,
        candidate_predict=lambda row: candidate.predict(**row),
        reference_predict=reference,
        bootstrap_samples=args.bootstrap_samples,
    )
    sizing = {
        "candidate": sizing_metrics(validation, lambda row: candidate.predict(**row)),
        "reference": sizing_metrics(validation, reference),
    }
    support = support_audit(
        train,
        validation,
        action_min=args.action_min_support,
        sizing_min=args.sizing_min_support,
    )
    support_summary = candidate_support_summary(validation, candidate)

    contexts = representative_contexts(validation, limit=args.counterfactual_contexts)
    counterfactual_input = [
        {key: value for key, value in ctx.items() if key not in {"representative_price_to_pot", "validation_support"}}
        for ctx in contexts
    ]
    counterfactual = counterfactual_response_report(
        counterfactual_input,
        price_points=DEFAULT_PRICE_POINTS,
        predict=lambda row: candidate.predict(**row),
    )
    for row, source in zip(counterfactual["contexts"], contexts):
        row["validation_support"] = source["validation_support"]
        row["representative_price_to_pot"] = source["representative_price_to_pot"]

    plausible = []
    for index, context in enumerate(contexts):
        probe = {key: value for key, value in context.items() if key not in {"validation_support", "representative_price_to_pot"}}
        probe["facing_price_to_pot"] = context["representative_price_to_pot"]
        prediction = candidate.predict(**probe)
        plausible.append({
            "context_index": index,
            "context": context,
            "identifiability": prediction["identifiability"],
            "environments": plausible_action_environments(prediction),
        })

    gate = predictive_gate(evaluation, sizing, support_summary)
    decision = (
        "RETAIN_ACTIVE_REFERENCE__CANDIDATE_VALIDATION_SUPPORTED"
        if gate["pass"]
        else "RETAIN_ACTIVE_REFERENCE__CANDIDATE_REJECTED"
    )

    model_dir.mkdir(parents=True, exist_ok=True)
    write_json(model_dir / "response_to_price.json", artifact)
    arena_config = {
        "schema": "model-b-response-to-price-arena-config/v1",
        "base_model_dir": incumbent.relative_to(ROOT).as_posix() if incumbent.is_relative_to(ROOT) else incumbent.as_posix(),
        "population_id": args.population_id,
        "response_artifact": "response_to_price.json",
        "production_effect": "NONE",
    }
    write_json(model_dir / "arena_config.json", arena_config)
    write_json(output / "support_audit.json", support)
    write_json(output / "predictive_evaluation.json", evaluation)
    write_json(output / "sizing_evaluation.json", sizing)
    write_json(output / "counterfactual_response.json", counterfactual)
    write_json(output / "plausible_environments.json", {
        "schema": "model-b-response-to-price-plausible-environments/v1",
        "environments_weighted": False,
        "contexts": plausible,
    })

    result = {
        "schema": SCHEMA,
        "issue": 197,
        "status": "PREDICTIVE_EVALUATION_COMPLETE_HERO_SENSITIVITY_PENDING",
        "population_id": args.population_id,
        "fit_split": "TRAIN",
        "evaluation_split": "VALIDATION",
        "test_consumed": False,
        "test_metrics_present": False,
        "production_effect": "NONE",
        "automatic_promotion": False,
        "independence_contract": "hand histories + TRAIN-fitted Model B profiles only; no Model A EV/policy/recommendations as features",
        "dataset": safe_provenance,
        "holdout_access_contract": (
            "archives are deduplicated before deterministic split assignment; "
            "TEST rows are never passed to fit, predictive evaluation, counterfactual diagnostics, "
            "or Hero sensitivity"
        ),
        "counts": {
            "train_hands": len(train_records),
            "validation_hands": len(validation_records),
            "train_facing_decisions": len(train),
            "validation_facing_decisions": len(validation),
        },
        "incumbent_model_dir": incumbent.as_posix(),
        "incumbent_artifacts": {
            name: sha256_file(incumbent / name)
            for name in ("profiles.json", "preflop_ranges.json", "postflop_actions.json", "sizing.json", "prediction_contract.json")
        },
        "candidate": {
            "model_version": artifact["model_version"],
            "artifact_sha256": artifact_sha256(artifact),
            "action_min_support": args.action_min_support,
            "sizing_min_support": args.sizing_min_support,
            "feature_dimensions": artifact["feature_contract"]["allowed_dimensions"],
            "price_monotonicity_assumption": "NONE",
        },
        "predictive_gate": gate,
        "interim_decision": decision,
        "hero_sensitivity_required_before_close": True,
    }
    write_json(output / "RESULT.partial.json", result)
    print(json.dumps({
        "train_facing_decisions": len(train),
        "validation_facing_decisions": len(validation),
        "paired_delta": evaluation["paired_action_log_loss"]["observed_candidate_minus_reference_log_loss"],
        "paired_ci95": evaluation["paired_action_log_loss"]["ci95"],
        "gate": gate,
        "interim_decision": decision,
    }, indent=2))
    return 0


def summarize_hero(args: argparse.Namespace) -> int:
    documents: dict[str, dict[str, Any]] = {}
    for spec in args.arena:
        name, path = spec.split("=", 1)
        documents[name] = load_json(Path(path))
    if "reference" not in documents or len(documents) < 3:
        raise ValueError("hero sensitivity requires reference plus at least two response environments")

    indexed = {}
    for name, doc in documents.items():
        rows = [row for row in doc.get("results", []) if str(row.get("policy")) == args.policy]
        by_id = {str(row["scenario_id"]): row for row in rows}
        if len(by_id) != len(rows):
            raise ValueError(f"{name}: duplicate scenario ids")
        indexed[name] = by_id
    ids = set(indexed["reference"])
    if not ids or any(set(rows) != ids for rows in indexed.values()):
        raise ValueError("hero sensitivity arenas must contain identical scenario ids")

    env_summaries = {}
    for name, rows in indexed.items():
        utilities = [float(row["utility_bb"]) for row in rows.values()]
        first_actions = collections.Counter()
        sizes = []
        for row in rows.values():
            hero_actions = list(row.get("hero_actions") or [])
            if hero_actions:
                first_actions[str(hero_actions[0].get("label"))] += 1
                if hero_actions[0].get("size_ratio") is not None:
                    sizes.append(float(hero_actions[0]["size_ratio"]))
        env_summaries[name] = {
            "scenarios": len(rows),
            "mean_utility_bb": statistics.fmean(utilities),
            "first_action_counts": dict(sorted(first_actions.items())),
            "first_sizing_p50": q(sizes, 0.50),
            "first_sizing_p90": q(sizes, 0.90),
        }

    reference = indexed["reference"]
    pairwise = {}
    action_changed_any = set()
    sizing_changed_any = set()
    for name, rows in indexed.items():
        if name == "reference":
            continue
        action_changed = sizing_changed = 0
        utility_deltas = []
        for sid in sorted(ids):
            base = reference[sid]
            other = rows[sid]
            utility_deltas.append(float(other["utility_bb"]) - float(base["utility_bb"]))
            ba = list(base.get("hero_actions") or [])
            oa = list(other.get("hero_actions") or [])
            base_action = str(ba[0].get("label")) if ba else "NONE"
            other_action = str(oa[0].get("label")) if oa else "NONE"
            if base_action != other_action:
                action_changed += 1
                action_changed_any.add(sid)
            base_size = ba[0].get("size_ratio") if ba else None
            other_size = oa[0].get("size_ratio") if oa else None
            if base_size is None or other_size is None:
                changed = base_size is not other_size
            else:
                changed = abs(float(base_size) - float(other_size)) > args.sizing_change_threshold
            if changed:
                sizing_changed += 1
                sizing_changed_any.add(sid)
        pairwise[name] = {
            "first_action_changed_fraction": action_changed / len(ids),
            "first_sizing_changed_fraction": sizing_changed / len(ids),
            "mean_utility_delta_bb_vs_reference": statistics.fmean(utility_deltas),
            "utility_delta_p10_bb": q(utility_deltas, 0.10),
            "utility_delta_p90_bb": q(utility_deltas, 0.90),
        }

    report = {
        "schema": HERO_SCHEMA,
        "scenario_split": "VALIDATION",
        "test_consumed": False,
        "policy": args.policy,
        "environments_weighted": False,
        "matched_scenarios": len(ids),
        "environment_summaries": env_summaries,
        "pairwise_vs_reference": pairwise,
        "any_environment": {
            "first_action_changed_fraction": len(action_changed_any) / len(ids),
            "first_sizing_changed_fraction": len(sizing_changed_any) / len(ids),
        },
        "interpretation": "paired strategic sensitivity diagnostic; not a probability-weighted true environment estimate",
    }
    write_json(Path(args.output), report)
    print(json.dumps(report["any_environment"], indent=2))
    return 0


def finalize(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    partial = load_json(run_dir / "RESULT.partial.json")
    hero = load_json(Path(args.hero_sensitivity))
    if partial.get("test_consumed") is not False or hero.get("test_consumed") is not False:
        raise ValueError("TEST consumption is forbidden for issue #197")
    gate = partial["predictive_gate"]
    supported = bool(gate["pass"])
    decision = (
        "RETAIN_ACTIVE_REFERENCE__RESPONSE_CANDIDATE_VALIDATION_SUPPORTED__NO_PROMOTION_WITHOUT_FROZEN_FINAL_PROTOCOL"
        if supported
        else "RETAIN_ACTIVE_REFERENCE__RESPONSE_CANDIDATE_REJECTED_ON_VALIDATION"
    )
    final = {
        "schema": FINAL_SCHEMA,
        "issue": 197,
        "status": "COMPLETE",
        "decision": decision,
        "predictive_gate": gate,
        "hero_sensitivity": hero,
        "test_consumed": False,
        "production_effect": "NONE",
        "automatic_promotion": False,
        "active_model_b_changed": False,
        "scientific_dod": {
            "fit_train_only": True,
            "support_audit_price_spr_sequence": True,
            "paired_validation_vs_reference": True,
            "log_loss_calibration_brier": True,
            "sizing_metrics": True,
            "overbet_jam_tail_diagnostics": True,
            "counterfactual_price_response": True,
            "hero_strategy_sensitivity": True,
            "persisted_artifacts": True,
            "test_unconsumed": True,
            "automatic_promotion_disabled": True,
        },
        "artifacts": {
            "predictive_result": "RESULT.partial.json",
            "support": "support_audit.json",
            "predictive_evaluation": "predictive_evaluation.json",
            "sizing_evaluation": "sizing_evaluation.json",
            "counterfactual": "counterfactual_response.json",
            "plausible_environments": "plausible_environments.json",
            "hero_sensitivity": Path(args.hero_sensitivity).name,
            "candidate_model": "model/response_to_price.json",
        },
    }
    write_json(run_dir / "RESULT.json", final)
    print(json.dumps({"decision": decision, "test_consumed": False}, indent=2))
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    fit = sub.add_parser("fit-evaluate")
    fit.add_argument("--archive", type=Path, action="append", required=True)
    fit.add_argument("--stake", action="append", default=["100/200"])
    fit.add_argument("--exclude-player", action="append", default=[])
    fit.add_argument("--incumbent-model-dir", type=Path, required=True)
    fit.add_argument("--population-id", required=True)
    fit.add_argument("--output-dir", type=Path, required=True)
    fit.add_argument("--action-min-support", type=int, default=30)
    fit.add_argument("--sizing-min-support", type=int, default=12)
    fit.add_argument("--alpha", type=float, default=1.0)
    fit.add_argument("--bootstrap-samples", type=int, default=5000)
    fit.add_argument("--counterfactual-contexts", type=int, default=12)
    fit.set_defaults(func=fit_evaluate)

    hero = sub.add_parser("summarize-hero")
    hero.add_argument("--arena", action="append", required=True, help="name=path")
    hero.add_argument("--policy", default="current")
    hero.add_argument("--sizing-change-threshold", type=float, default=0.25)
    hero.add_argument("--output", required=True)
    hero.set_defaults(func=summarize_hero)

    fin = sub.add_parser("finalize")
    fin.add_argument("--run-dir", required=True)
    fin.add_argument("--hero-sensitivity", required=True)
    fin.set_defaults(func=finalize)
    return p


def main() -> int:
    args = parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

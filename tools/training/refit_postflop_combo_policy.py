#!/usr/bin/env python3
"""Refit runtime-consumed Model A postflop combo-policy residuals.

Stage B for issue #102. The tool starts from an already selected Stage-A
response candidate and refits only ``combo_policy_models.*.coef_std``.
Private-card uncertainty is preserved strictly before every target decision:
revealed hands become point masses only after the prior is built, while hidden
hands contribute fractional training weight over a deterministic quadrature of
their exact-combo posterior.

The fit is local to the exact Stage-A runtime: Stage-A calibrated per-combo
action probabilities are used as offsets and Stage B learns only coefficient
deltas around the parent. This preserves the theory + IPF baseline at delta=0;
the independent VALIDATION gate then evaluates the complete runtime again.

TEST is never used for fitting or selection and production models are never
mutated by this tool.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

from tools.simulation.model_b_runtime import cid
from tools.training.audit_model_a_latent_ranges import group_hands
from tools.training.model_a_latent_ranges import LatentRangeError, posterior_before_postflop_action
from tools.training.model_a_postflop_runtime import (
    calibrated_action_matrix,
    exact_postflop_node,
    learned_combo_feature_map,
    observed_action_probabilities,
    target_frequencies,
)

SCHEMA = "poker-model-a-postflop-combo-refit/v1"
OVERLAY_SCHEMA = "poker-model-a-postflop-continuation-overlay/v1"
EPS = 1e-12


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_rows(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def softmax(logits: list[float]) -> list[float]:
    m = max(logits)
    exps = [math.exp(x - m) for x in logits]
    total = sum(exps) or 1.0
    return [x / total for x in exps]


def normalized_coef(spec: dict) -> list[list[float]]:
    classes = list(spec.get("classes") or [])
    nf = len(spec.get("features") or [])
    src = spec.get("coef_std") or []
    return [
        [float(src[i][j]) if i < len(src) and j < len(src[i]) else 0.0 for j in range(nf)]
        for i in range(len(classes))
    ]


def standardized_combo_features(combo: tuple[int, int], row: dict, spec: dict) -> list[float]:
    fmap = learned_combo_feature_map(combo, row)
    features = list(spec.get("features") or [])
    mean = list(spec.get("feature_mean") or [])
    std = list(spec.get("feature_std") or [])
    out = []
    for j, name in enumerate(features):
        m = float(mean[j] if j < len(mean) else 0.0)
        s = max(1e-9, float(std[j] if j < len(std) else 1.0))
        out.append((float(fmap.get(name) or 0.0) - m) / s)
    return out


def posterior_quadrature(
    combos: Iterable[tuple[int, int]], weights: Iterable[float], budget: int
) -> list[tuple[tuple[int, int], float]]:
    """Deterministic inverse-CDF quadrature of an exact-combo posterior."""
    pairs = [
        (combo, max(0.0, float(weight)))
        for combo, weight in zip(combos, weights)
        if float(weight) > 0
    ]
    if not pairs:
        raise ValueError("empty posterior support")
    total = sum(weight for _, weight in pairs)
    pairs = [(combo, weight / total) for combo, weight in pairs]
    if budget <= 0 or len(pairs) <= budget:
        return pairs

    selected: dict[tuple[int, int], float] = defaultdict(float)
    cumulative = 0.0
    index = 0
    for q in range(budget):
        target = (q + 0.5) / budget
        while index < len(pairs) - 1 and cumulative + pairs[index][1] < target:
            cumulative += pairs[index][1]
            index += 1
        selected[pairs[index][0]] += 1.0 / budget
    return list(selected.items())


def fractional_feature_points(
    posterior, row: dict, spec: dict, *, hidden_budget: int
) -> tuple[list[dict], dict]:
    """Return private-feature points with weights summing to one per decision."""
    known = list(row.get("known_cards") or [])
    if len(known) == 2:
        target = tuple(sorted((cid(known[0]), cid(known[1]))))
        if posterior.probability_of_cards(known) <= 0:
            raise LatentRangeError("revealed combo is outside pre-action posterior support")
        return [{
            "combo": target,
            "z": standardized_combo_features(target, row, spec),
            "weight": 1.0,
        }], {
            "label_policy": "REVEALED_POINT_MASS",
            "quadrature_points": 1,
            "posterior_support": posterior.support,
        }

    quad = posterior_quadrature(posterior.combos, posterior.weights, hidden_budget)
    return [
        {
            "combo": combo,
            "z": standardized_combo_features(combo, row, spec),
            "weight": float(weight),
        }
        for combo, weight in quad
    ], {
        "label_policy": "HIDDEN_FRACTIONAL_POSTERIOR",
        "quadrature_points": len(quad),
        "posterior_support": posterior.support,
    }


def _model_key(row: dict) -> str:
    return f"{row.get('street')}_{row.get('mode')}"


def _attach_stage_a_offsets(points: list[dict], posterior, row: dict, target: dict, model: dict, classes: list[str]) -> None:
    actions, matrix = calibrated_action_matrix(
        posterior.combos, posterior.weights, row, target, model
    )
    action_index = {action: idx for idx, action in enumerate(actions)}
    if any(action not in action_index for action in classes):
        missing = [action for action in classes if action not in action_index]
        raise KeyError(f"combo-policy classes outside runtime action support: {missing}")
    combo_index = {combo: idx for idx, combo in enumerate(posterior.combos)}
    for point in points:
        idx = combo_index.get(tuple(point["combo"]))
        if idx is None:
            raise LatentRangeError("fractional combo is outside posterior support")
        point["offsets"] = [
            math.log(max(EPS, float(matrix[idx][action_index[action]])))
            for action in classes
        ]


def build_examples(
    preflop_model: dict,
    postflop_model: dict,
    rows: list[dict],
    split: str,
    *,
    hidden_budget: int,
) -> tuple[dict[str, list[dict]], dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    counts = Counter()
    quadrature_points = []
    effective_support = []

    for hand_rows in group_hands(rows):
        if str(hand_rows[0].get("split") or "") != split:
            continue
        for idx, row in enumerate(hand_rows):
            if row.get("is_hero") or row.get("street") not in {"flop", "turn", "river"}:
                continue
            counts["population_postflop_targets"] += 1
            key = _model_key(row)
            spec = (postflop_model.get("combo_policy_models") or {}).get(key)
            if not spec:
                counts["excluded_missing_combo_policy_model"] += 1
                continue
            classes = list(spec.get("classes") or [])
            if row.get("action") not in classes:
                counts["excluded_action_outside_combo_classes"] += 1
                continue
            node = exact_postflop_node(postflop_model, row)
            if node is None:
                counts["excluded_missing_exact_postflop_node"] += 1
                continue
            target = target_frequencies(node, row, postflop_model)
            if row.get("action") not in target:
                counts["excluded_action_outside_runtime_target"] += 1
                continue
            try:
                posterior = posterior_before_postflop_action(
                    hand_rows, idx, preflop_model, postflop_model
                )
                points, label_info = fractional_feature_points(
                    posterior, row, spec, hidden_budget=hidden_budget
                )
                _attach_stage_a_offsets(
                    points, posterior, row, target, postflop_model, classes
                )
            except LatentRangeError:
                counts["excluded_latent_range_error"] += 1
                continue
            except (KeyError, ValueError):
                counts["excluded_runtime_support_error"] += 1
                continue

            if label_info["label_policy"] == "REVEALED_POINT_MASS":
                counts["admitted_revealed"] += 1
            else:
                counts["admitted_hidden_fractional"] += 1
            counts["admitted"] += 1
            counts["fractional_feature_points"] += len(points)
            quadrature_points.append(label_info["quadrature_points"])
            effective_support.append(posterior.effective_support)
            grouped[key].append({
                "hand_id": str(row.get("hand_id")),
                "action": str(row.get("action")),
                "points": points,
                "revealed": label_info["label_policy"] == "REVEALED_POINT_MASS",
                "matched_postflop_actions": posterior.matched_postflop_actions,
            })

    counts["models_with_examples"] = len(grouped)
    return grouped, {
        "counts": dict(sorted(counts.items())),
        "quadrature_points_per_decision": {
            "mean": sum(quadrature_points) / len(quadrature_points) if quadrature_points else None,
            "max": max(quadrature_points) if quadrature_points else None,
        },
        "effective_combo_support": {
            "mean": sum(effective_support) / len(effective_support) if effective_support else None,
            "min": min(effective_support) if effective_support else None,
            "max": max(effective_support) if effective_support else None,
        },
    }


def fit_one(
    spec: dict,
    examples: list[dict],
    *,
    epochs: int,
    learning_rate: float,
    l2_to_parent: float,
    coefficient_delta_cap: float,
    minimum_effective_weight: float,
) -> tuple[list[list[float]], dict]:
    classes = list(spec.get("classes") or [])
    parent = normalized_coef(spec)
    nf = len(spec.get("features") or [])
    scale = float(spec.get("data_scale") or 0.0)
    effective_decisions = float(len(examples))
    if not classes or not nf or not scale or effective_decisions < minimum_effective_weight:
        return copy.deepcopy(parent), {
            "examples": len(examples),
            "fractional_points": sum(len(ex.get("points") or []) for ex in examples),
            "epochs": 0,
            "decision": "BACKOFF_PARENT",
            "reason": "insufficient examples or inactive runtime scale",
            "max_parent_coefficient_delta": 0.0,
            "saturated_coefficients": 0,
        }

    delta = [[0.0] * nf for _ in classes]
    for _ in range(epochs):
        grad = [[0.0] * nf for _ in classes]
        used_weight = 0.0
        for ex in examples:
            action = ex["action"]
            if action not in classes:
                continue
            target_ci = classes.index(action)
            for point in ex.get("points") or []:
                point_weight = max(0.0, float(point.get("weight") or 0.0))
                if point_weight <= 0:
                    continue
                z = point["z"]
                offsets = point.get("offsets") or []
                if len(offsets) != len(classes):
                    raise ValueError("fractional point lacks Stage-A runtime offsets")
                logits = [
                    float(offsets[ci])
                    + scale * sum(delta[ci][j] * z[j] for j in range(nf))
                    for ci in range(len(classes))
                ]
                probs = softmax(logits)
                for ci in range(len(classes)):
                    err = probs[ci] - (1.0 if ci == target_ci else 0.0)
                    for j in range(nf):
                        grad[ci][j] += point_weight * err * scale * z[j]
                used_weight += point_weight
        if used_weight <= 0:
            break
        inv = 1.0 / used_weight
        for ci in range(len(classes)):
            for j in range(nf):
                g = grad[ci][j] * inv + l2_to_parent * delta[ci][j]
                proposed = delta[ci][j] - learning_rate * g
                delta[ci][j] = max(
                    -coefficient_delta_cap,
                    min(coefficient_delta_cap, proposed),
                )

    fitted = [
        [parent[ci][j] + delta[ci][j] for j in range(nf)]
        for ci in range(len(classes))
    ]
    deltas = [abs(value) for row in delta for value in row]
    saturated = sum(1 for value in deltas if value >= coefficient_delta_cap - 1e-9)
    return fitted, {
        "examples": len(examples),
        "fractional_points": sum(len(ex.get("points") or []) for ex in examples),
        "epochs": epochs,
        "decision": "REFIT",
        "fit_reference": "Stage-A calibrated per-combo action probabilities; optimize coefficient delta only",
        "max_parent_coefficient_delta": max(deltas, default=0.0),
        "saturated_coefficients": saturated,
    }


def refit(
    stage_a_model: dict,
    preflop_model: dict,
    rows: list[dict],
    *,
    hidden_budget: int = 48,
    epochs: int = 50,
    learning_rate: float = 0.05,
    l2_to_parent: float = 0.30,
    minimum_effective_weight: float = 20.0,
    coefficient_delta_cap: float = 1.5,
) -> tuple[dict, dict]:
    candidate = copy.deepcopy(stage_a_model)
    train, coverage = build_examples(
        preflop_model,
        stage_a_model,
        rows,
        "TRAIN",
        hidden_budget=hidden_budget,
    )
    fit_summary = {}
    changed = 0
    for key, spec in (candidate.get("combo_policy_models") or {}).items():
        old = normalized_coef(spec)
        new, info = fit_one(
            spec,
            train.get(key, []),
            epochs=epochs,
            learning_rate=learning_rate,
            l2_to_parent=l2_to_parent,
            coefficient_delta_cap=coefficient_delta_cap,
            minimum_effective_weight=minimum_effective_weight,
        )
        spec["coef_std"] = new
        fit_summary[key] = info
        if new != old:
            changed += 1
    candidate["combo_policy_refit"] = {
        "schema": SCHEMA,
        "runtime_component": "combo_policy_models.*.coef_std",
        "selection_split": "VALIDATION",
        "test_consumed": False,
        "production_effect": "NONE",
        "frozen_components": ["nodes", "response_models", "hand_policy_prior"],
        "hidden_hand_policy": "fractional weighted feature points from pre-action exact-combo posterior",
        "revealed_hand_policy": "point mass after pre-action posterior construction",
        "fit_reference": "Stage-A calibrated conditional action probabilities; coefficient deltas only",
        "parameters": {
            "hidden_quadrature_budget": hidden_budget,
            "epochs": epochs,
            "learning_rate": learning_rate,
            "l2_to_parent": l2_to_parent,
            "minimum_effective_weight": minimum_effective_weight,
            "coefficient_delta_cap_std": coefficient_delta_cap,
        },
    }
    return candidate, {
        "combo_policy_models_changed": changed,
        "fit": fit_summary,
        "train_coverage": coverage,
    }


def _hash_rank(hand_id: str, index: int) -> str:
    return hashlib.sha256(f"stage-b-validation-v1|{hand_id}|{index}".encode()).hexdigest()


def revealed_validation_targets(
    model: dict, rows: list[dict], *, budget: int
) -> tuple[list[dict], dict]:
    """Select revealed VALIDATION targets before private-card likelihood work."""
    eligible = []
    counts = Counter()
    for hand_rows in group_hands(rows):
        if str(hand_rows[0].get("split") or "") != "VALIDATION":
            continue
        for idx, row in enumerate(hand_rows):
            if row.get("is_hero") or row.get("street") not in {"flop", "turn", "river"}:
                continue
            if len(list(row.get("known_cards") or [])) != 2:
                counts["hidden_not_directly_scored"] += 1
                continue
            spec = (model.get("combo_policy_models") or {}).get(_model_key(row))
            if not spec or row.get("action") not in (spec.get("classes") or []):
                counts["unsupported_combo_model"] += 1
                continue
            if exact_postflop_node(model, row) is None:
                counts["missing_exact_postflop_node"] += 1
                continue
            eligible.append({
                "hand_rows": hand_rows,
                "index": idx,
                "row": row,
                "rank": _hash_rank(str(row.get("hand_id")), idx),
            })
    eligible.sort(key=lambda item: item["rank"])
    selected = eligible[:budget] if budget > 0 else eligible
    counts["eligible_revealed"] = len(eligible)
    counts["selected_revealed"] = len(selected)
    return selected, dict(sorted(counts.items()))


def _revealed_action_probability(
    preflop_model: dict,
    model: dict,
    hand_rows: list[dict],
    index: int,
    row: dict,
) -> float:
    posterior = posterior_before_postflop_action(
        hand_rows, index, preflop_model, model
    )
    known = tuple(sorted((cid(row["known_cards"][0]), cid(row["known_cards"][1]))))
    try:
        combo_index = list(posterior.combos).index(known)
    except ValueError as exc:
        raise LatentRangeError(
            "revealed combo is outside pre-action posterior support"
        ) from exc
    return observed_action_probabilities(
        posterior.combos, posterior.weights, row, model
    )[combo_index]


def evaluate_revealed(
    preflop_model: dict,
    baseline: dict,
    candidate: dict,
    rows: list[dict],
    *,
    budget: int,
) -> tuple[dict, dict[str, list[float]], dict[str, list[float]]]:
    selected, coverage = revealed_validation_targets(
        baseline, rows, budget=budget
    )
    base_by_hand: dict[str, list[float]] = defaultdict(list)
    cand_by_hand: dict[str, list[float]] = defaultdict(list)
    base_loss = 0.0
    cand_loss = 0.0
    changed = 0
    by_model = defaultdict(
        lambda: {"n": 0, "baseline_loss": 0.0, "candidate_loss": 0.0}
    )

    for ex in selected:
        row = ex["row"]
        try:
            bp = _revealed_action_probability(
                preflop_model,
                baseline,
                ex["hand_rows"],
                ex["index"],
                row,
            )
            cp = _revealed_action_probability(
                preflop_model,
                candidate,
                ex["hand_rows"],
                ex["index"],
                row,
            )
        except (LatentRangeError, KeyError, ValueError):
            coverage["runtime_scoring_error"] = (
                coverage.get("runtime_scoring_error", 0) + 1
            )
            continue
        bll = -math.log(max(EPS, bp))
        cll = -math.log(max(EPS, cp))
        base_loss += bll
        cand_loss += cll
        if abs(cp - bp) > 1e-12:
            changed += 1
        hid = str(row.get("hand_id"))
        base_by_hand[hid].append(bll)
        cand_by_hand[hid].append(cll)
        key = _model_key(row)
        by_model[key]["n"] += 1
        by_model[key]["baseline_loss"] += bll
        by_model[key]["candidate_loss"] += cll

    n = sum(len(values) for values in base_by_hand.values())
    per_model = {}
    for key, stats in sorted(by_model.items()):
        count = stats["n"]
        per_model[key] = {
            "n": count,
            "baseline_log_loss": stats["baseline_loss"] / count if count else None,
            "candidate_log_loss": stats["candidate_loss"] / count if count else None,
        }
    return {
        "split": "VALIDATION",
        "metric": "revealed_combo_conditional_action_log_loss",
        "rows": n,
        "baseline_log_loss": base_loss / n if n else None,
        "candidate_log_loss": cand_loss / n if n else None,
        "prediction_changed_rows": changed,
        "coverage": coverage,
        "by_model": per_model,
    }, base_by_hand, cand_by_hand


def paired_bootstrap(
    base_by_hand: dict[str, list[float]],
    cand_by_hand: dict[str, list[float]],
    *,
    seed: int,
    iterations: int,
) -> dict:
    ids = sorted(set(base_by_hand) & set(cand_by_hand))
    deltas = []
    for hid in ids:
        baseline = base_by_hand[hid]
        candidate = cand_by_hand[hid]
        if baseline and candidate:
            deltas.append(
                sum(candidate) / len(candidate) - sum(baseline) / len(baseline)
            )
    if not deltas:
        return {
            "hands": 0,
            "iterations": 0,
            "mean_delta_candidate_minus_baseline": None,
            "ci95": None,
            "probability_candidate_better": None,
        }
    rng = random.Random(seed)
    samples = []
    for _ in range(iterations):
        samples.append(
            sum(deltas[rng.randrange(len(deltas))] for _ in deltas) / len(deltas)
        )
    samples.sort()
    lo = samples[max(0, int(0.025 * len(samples)) - 1)]
    hi = samples[min(len(samples) - 1, int(0.975 * len(samples)))]
    return {
        "hands": len(deltas),
        "iterations": iterations,
        "mean_delta_candidate_minus_baseline": sum(deltas) / len(deltas),
        "ci95": [lo, hi],
        "probability_candidate_better": (
            sum(1 for value in samples if value < 0) / len(samples)
        ),
    }


def continuation_overlay(
    base_model: dict,
    selected_model: dict,
    *,
    base_sha256: str,
    decision: str,
) -> dict:
    response = {
        key: {"numeric_coef": spec.get("numeric_coef")}
        for key, spec in (selected_model.get("response_models") or {}).items()
    }
    combo = {
        key: {"coef_std": spec.get("coef_std")}
        for key, spec in (selected_model.get("combo_policy_models") or {}).items()
    }
    return {
        "schema": OVERLAY_SCHEMA,
        "base_postflop_model_sha256": base_sha256,
        "selection": {"stage_b_decision": decision, "test_consumed": False},
        "response_models": response,
        "combo_policy_models": combo,
    }


def apply_overlay(base_model: dict, overlay: dict) -> dict:
    out = copy.deepcopy(base_model)
    for key, patch in (overlay.get("response_models") or {}).items():
        if key not in (out.get("response_models") or {}):
            raise KeyError(f"overlay response model missing from base: {key}")
        out["response_models"][key]["numeric_coef"] = patch["numeric_coef"]
    for key, patch in (overlay.get("combo_policy_models") or {}).items():
        if key not in (out.get("combo_policy_models") or {}):
            raise KeyError(f"overlay combo model missing from base: {key}")
        out["combo_policy_models"][key]["coef_std"] = patch["coef_std"]
    return out


def run(
    stage_a_path: Path,
    production_baseline_path: Path,
    preflop_path: Path,
    decisions_path: Path,
    candidate_path: Path,
    overlay_path: Path,
    report_path: Path,
    *,
    hidden_budget: int,
    epochs: int,
    learning_rate: float,
    l2_to_parent: float,
    minimum_effective_weight: float,
    coefficient_delta_cap: float,
    validation_revealed_budget: int,
    seed: int,
    bootstrap_iterations: int,
) -> dict:
    stage_a = json.loads(stage_a_path.read_text(encoding="utf-8"))
    production_baseline = json.loads(
        production_baseline_path.read_text(encoding="utf-8")
    )
    preflop = json.loads(preflop_path.read_text(encoding="utf-8"))
    rows = load_rows(decisions_path)

    candidate, fit = refit(
        stage_a,
        preflop,
        rows,
        hidden_budget=hidden_budget,
        epochs=epochs,
        learning_rate=learning_rate,
        l2_to_parent=l2_to_parent,
        minimum_effective_weight=minimum_effective_weight,
        coefficient_delta_cap=coefficient_delta_cap,
    )
    evaluation, base_hands, cand_hands = evaluate_revealed(
        preflop,
        stage_a,
        candidate,
        rows,
        budget=validation_revealed_budget,
    )
    bootstrap = paired_bootstrap(
        base_hands,
        cand_hands,
        seed=seed,
        iterations=bootstrap_iterations,
    )
    delta = None
    if (
        evaluation["baseline_log_loss"] is not None
        and evaluation["candidate_log_loss"] is not None
    ):
        delta = (
            evaluation["candidate_log_loss"]
            - evaluation["baseline_log_loss"]
        )
    ci = bootstrap.get("ci95")
    decision = (
        "PROMOTE_STAGE_B_SCIENTIFICALLY"
        if delta is not None
        and delta < 0
        and ci
        and ci[1] < 0
        and evaluation["prediction_changed_rows"] > 0
        else "RETAIN_STAGE_A"
    )
    selected = (
        candidate if decision == "PROMOTE_STAGE_B_SCIENTIFICALLY" else stage_a
    )

    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    overlay_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_path.write_text(
        json.dumps(candidate, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    overlay = continuation_overlay(
        production_baseline,
        selected,
        base_sha256=sha256_file(production_baseline_path),
        decision=decision,
    )
    overlay_path.write_text(
        json.dumps(overlay, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    report = {
        "schema": SCHEMA,
        "component": "Model A postflop combo_policy_models.*.coef_std",
        "scientific_decision": decision,
        "production_effect": "NONE",
        "selection": {"split": "VALIDATION", "test_consumed": False},
        "fit": fit,
        "validation": evaluation,
        "delta_candidate_minus_stage_a": delta,
        "paired_hand_bootstrap": bootstrap,
        "gates": {
            "target_action_leakage": "PASS_BY_CONSTRUCTION",
            "future_board_cards_for_prior_action": "PASS_BY_CHRONOLOGICAL_BLOCKING",
            "nearest_context_substitution": "DISABLED",
            "production_mutation": "NONE",
            "fit_zero_delta_runtime_parity": "PASS_BY_STAGE_A_CONDITIONAL_OFFSETS",
        },
        "limits": [
            "hidden-hand fractional sufficient statistics use deterministic posterior quadrature with the persisted budget",
            "fit is a regularized local delta around Stage-A calibrated per-combo action probabilities",
            "Stage-B selection uses revealed-combo conditional likelihood because runtime IPF deliberately fixes marginal action frequencies",
            "baseline and candidate each reconstruct their own chronological posterior during VALIDATION",
            "TEST is not read for fitting or selection",
        ],
        "provenance": {
            "stage_a": str(stage_a_path),
            "stage_a_sha256": sha256_file(stage_a_path),
            "production_baseline": str(production_baseline_path),
            "production_baseline_sha256": sha256_file(production_baseline_path),
            "preflop_model": str(preflop_path),
            "preflop_model_sha256": sha256_file(preflop_path),
            "decisions": str(decisions_path),
            "decisions_sha256": sha256_file(decisions_path),
            "tool": str(Path(__file__)),
            "tool_sha256": sha256_file(Path(__file__)),
            "candidate": str(candidate_path),
            "candidate_sha256": sha256_file(candidate_path),
            "selected_overlay": str(overlay_path),
            "selected_overlay_sha256": sha256_file(overlay_path),
            "seed": seed,
            "bootstrap_iterations": bootstrap_iterations,
            "hidden_quadrature_budget": hidden_budget,
            "validation_revealed_budget": validation_revealed_budget,
            "epochs": epochs,
            "learning_rate": learning_rate,
            "l2_to_parent": l2_to_parent,
            "minimum_effective_weight": minimum_effective_weight,
            "coefficient_delta_cap_std": coefficient_delta_cap,
        },
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage-a", required=True, type=Path)
    parser.add_argument("--production-baseline", required=True, type=Path)
    parser.add_argument("--preflop-model", required=True, type=Path)
    parser.add_argument("--decisions", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--overlay", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--hidden-quadrature-budget", type=int, default=48)
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    parser.add_argument("--l2-to-parent", type=float, default=0.30)
    parser.add_argument("--minimum-effective-weight", type=float, default=20.0)
    parser.add_argument("--coefficient-delta-cap-std", type=float, default=1.5)
    parser.add_argument("--validation-revealed-budget", type=int, default=600)
    parser.add_argument("--seed", type=int, default=20260916)
    parser.add_argument("--bootstrap-iterations", type=int, default=2000)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run(
        args.stage_a,
        args.production_baseline,
        args.preflop_model,
        args.decisions,
        args.candidate,
        args.overlay,
        args.report,
        hidden_budget=args.hidden_quadrature_budget,
        epochs=args.epochs,
        learning_rate=args.learning_rate,
        l2_to_parent=args.l2_to_parent,
        minimum_effective_weight=args.minimum_effective_weight,
        coefficient_delta_cap=args.coefficient_delta_cap_std,
        validation_revealed_budget=args.validation_revealed_budget,
        seed=args.seed,
        bootstrap_iterations=args.bootstrap_iterations,
    )


if __name__ == "__main__":
    main()

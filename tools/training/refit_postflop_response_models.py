#!/usr/bin/env python3
"""Refit runtime-consumed Model A postflop response models without promotion.

The browser runtime applies ``response_models`` as bounded residual logits on top
of each exact postflop node's marginal action frequencies.  This tool refits
those same coefficients from admissible TRAIN population decisions and evaluates
the resulting candidate against the unchanged baseline on VALIDATION only.

This tranche deliberately does *not* refit ``combo_policy_models`` or
``hand_policy_prior``.  Unrevealed hands are admissible for response fitting
because these response models condition on public/action context only; revealed
combo composition is a separate model family and is reported, not fabricated.
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

SCHEMA = "poker-model-a-postflop-response-refit/v1"
EPS = 1e-9


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def feature_value(row: dict, name: str) -> float:
    """Mirror site/index.html postflopNumericFeature exactly."""
    board = row.get("board_features") or {}
    spr = max(0.0, min(50.0, float(row.get("spr") or 0.0)))
    facing = max(0.0, min(5.0, float(row.get("facing_price_pot") or 0.0)))
    log_spr = math.log1p(spr)
    log_facing = math.log1p(facing)
    if name == "log_spr":
        return log_spr
    if name == "spr_h1":
        return max(0.0, log_spr - math.log1p(1.0))
    if name == "spr_h4":
        return max(0.0, log_spr - math.log1p(4.0))
    if name == "spr_h10":
        return max(0.0, log_spr - math.log1p(10.0))
    if name in {"paired", "trips", "flushiness", "connectivity", "high_rank_norm", "broadway_norm", "new_overcard", "new_pairs_board"}:
        return float(board.get(name) or 0.0)
    if name == "log_pot":
        return math.log1p(max(0.0, float(row.get("pot_before_bb") or 0.0)))
    if name == "log_facing_price":
        return log_facing
    if name == "size_h25":
        return max(0.0, log_facing - math.log1p(0.25))
    if name == "size_h50":
        return max(0.0, log_facing - math.log1p(0.50))
    if name == "size_h100":
        return max(0.0, log_facing - math.log1p(1.0))
    return 0.0


def softmax(logits: list[float]) -> list[float]:
    m = max(logits)
    exps = [math.exp(x - m) for x in logits]
    total = sum(exps)
    return [x / total for x in exps]


def runtime_prediction(node: dict, spec: dict, row: dict, coef: list[list[float]] | None = None) -> dict[str, float]:
    """Python parity implementation of browser postflopTargetFrequencies."""
    pm = node.get("population_model") or {}
    base = pm.get("frequencies") or {}
    actions = [a for a in (pm.get("legal_actions") or list(base)) if float(base.get(a, -1)) >= 0]
    if not actions:
        return {}
    classes = list(spec.get("classes") or [])
    features = list(spec.get("features") or [])
    matrix = coef if coef is not None else (spec.get("numeric_coef") or [])
    center = pm.get("numeric_feature_center") or spec.get("global_mean") or []
    std = spec.get("global_std") or []
    scale = float(spec.get("application_scale") if spec.get("application_scale") is not None else 0.55)
    cap = float(spec.get("max_logit_adjustment") if spec.get("max_logit_adjustment") is not None else 1.8)
    logits = [math.log(max(EPS, float(base.get(a) or 0.0))) for a in actions]
    for ai, action in enumerate(actions):
        if action not in classes:
            continue
        ci = classes.index(action)
        coeffs = matrix[ci] if ci < len(matrix) else []
        adj = 0.0
        for j, feature in enumerate(features):
            x = feature_value(row, feature)
            c = float(center[j] if j < len(center) else (spec.get("global_mean") or [0.0] * len(features))[j])
            s = max(1e-6, float(std[j] if j < len(std) else 1.0))
            w = float(coeffs[j] if j < len(coeffs) else 0.0)
            adj += w * (x - c) / s
        logits[ai] += max(-cap, min(cap, adj * scale))
    probs = softmax(logits)
    return dict(zip(actions, probs))


def load_rows(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def node_maps(model: dict) -> tuple[dict[str, dict], dict[str, str]]:
    by_key = {}
    response_key = {}
    for node in model.get("nodes") or []:
        key = node.get("canonical_key")
        if not key:
            continue
        by_key[key] = node
        rk = (node.get("population_model") or {}).get("response_model_key")
        if rk:
            response_key[key] = rk
    return by_key, response_key


def classify_rows(model: dict, rows: Iterable[dict], split: str) -> tuple[dict[str, list[tuple[dict, dict]]], Counter]:
    by_key, response_key = node_maps(model)
    specs = model.get("response_models") or {}
    grouped: dict[str, list[tuple[dict, dict]]] = defaultdict(list)
    counts = Counter()
    for row in rows:
        if row.get("split") != split or row.get("is_hero") or row.get("street") not in {"flop", "turn", "river"}:
            continue
        counts["population_postflop_rows"] += 1
        if row.get("known_cards"):
            counts["revealed_rows"] += 1
        else:
            counts["unrevealed_rows"] += 1
        if float(row.get("facing_price_pot") or 0.0) > 5.0:
            counts["facing_price_clipped_by_runtime"] += 1
        if float(row.get("spr") or 0.0) > 50.0:
            counts["spr_clipped_by_runtime"] += 1
        key = row.get("canonical_key")
        node = by_key.get(key)
        if node is None:
            counts["no_exact_node"] += 1
            continue
        rk = response_key.get(key)
        spec = specs.get(rk) if rk else None
        if not spec:
            counts["no_response_model"] += 1
            continue
        action = row.get("action")
        if action not in (spec.get("classes") or []):
            counts["action_outside_response_classes"] += 1
            continue
        if action not in ((node.get("population_model") or {}).get("frequencies") or {}):
            counts["action_outside_node_support"] += 1
            continue
        grouped[rk].append((row, node))
        counts["usable_rows"] += 1
    return grouped, counts


def z_vector(row: dict, node: dict, spec: dict) -> list[float]:
    features = list(spec.get("features") or [])
    pm = node.get("population_model") or {}
    center = pm.get("numeric_feature_center") or spec.get("global_mean") or []
    mean = spec.get("global_mean") or []
    std = spec.get("global_std") or []
    out = []
    for j, name in enumerate(features):
        c = float(center[j] if j < len(center) else (mean[j] if j < len(mean) else 0.0))
        s = max(1e-6, float(std[j] if j < len(std) else 1.0))
        out.append((feature_value(row, name) - c) / s)
    return out


def normalized_matrix(spec: dict) -> list[list[float]]:
    classes = list(spec.get("classes") or [])
    nf = len(spec.get("features") or [])
    src = spec.get("numeric_coef") or []
    return [[float(src[i][j]) if i < len(src) and j < len(src[i]) else 0.0 for j in range(nf)] for i in range(len(classes))]


def fit_one(spec: dict, examples: list[tuple[dict, dict]], *, epochs: int, learning_rate: float, l2_to_parent: float) -> tuple[list[list[float]], dict]:
    classes = list(spec.get("classes") or [])
    parent = normalized_matrix(spec)
    coef = copy.deepcopy(parent)
    scale = float(spec.get("application_scale") if spec.get("application_scale") is not None else 0.55)
    cap = float(spec.get("max_logit_adjustment") if spec.get("max_logit_adjustment") is not None else 1.8)
    if not examples or not classes:
        return coef, {"examples": len(examples), "epochs": 0}

    # Full-batch deterministic gradient descent.  The parent acts as an explicit
    # prior, avoiding a wholesale replacement from one incremental snapshot.
    for _ in range(epochs):
        grad = [[0.0] * len(row) for row in coef]
        used = 0
        for obs, node in examples:
            pm = node.get("population_model") or {}
            freqs = pm.get("frequencies") or {}
            action = obs.get("action")
            if action not in classes:
                continue
            z = z_vector(obs, node, spec)
            logits = []
            active = []
            for ci, cls in enumerate(classes):
                if cls not in freqs or float(freqs.get(cls, -1)) < 0:
                    continue
                raw = sum(coef[ci][j] * z[j] for j in range(len(z))) * scale
                active.append(ci)
                logits.append(math.log(max(EPS, float(freqs.get(cls) or 0.0))) + max(-cap, min(cap, raw)))
            if classes.index(action) not in active or not active:
                continue
            probs = softmax(logits)
            target_ci = classes.index(action)
            for local_i, ci in enumerate(active):
                raw = sum(coef[ci][j] * z[j] for j in range(len(z))) * scale
                derivative = 0.0 if raw <= -cap or raw >= cap else scale
                err = probs[local_i] - (1.0 if ci == target_ci else 0.0)
                for j in range(len(z)):
                    grad[ci][j] += err * derivative * z[j]
            used += 1
        if not used:
            break
        inv = 1.0 / used
        for ci in range(len(coef)):
            for j in range(len(coef[ci])):
                g = grad[ci][j] * inv + l2_to_parent * (coef[ci][j] - parent[ci][j])
                coef[ci][j] -= learning_rate * g

    max_delta = max((abs(coef[i][j] - parent[i][j]) for i in range(len(coef)) for j in range(len(coef[i]))), default=0.0)
    return coef, {"examples": len(examples), "epochs": epochs, "max_parent_coefficient_delta": max_delta}


def evaluate(model: dict, rows: Iterable[dict], split: str) -> tuple[dict, dict[str, list[float]]]:
    grouped, counts = classify_rows(model, rows, split)
    by_hand: dict[str, list[float]] = defaultdict(list)
    loss = 0.0
    n = 0
    for rk, examples in grouped.items():
        spec = (model.get("response_models") or {}).get(rk) or {}
        for row, node in examples:
            p = runtime_prediction(node, spec, row).get(row.get("action"), 0.0)
            ll = -math.log(max(EPS, p))
            loss += ll
            n += 1
            by_hand[str(row.get("hand_id"))].append(ll)
    return {"split": split, "log_loss": loss / n if n else None, "rows": n, "coverage": dict(counts)}, by_hand


def paired_bootstrap(base_by_hand: dict[str, list[float]], cand_by_hand: dict[str, list[float]], *, seed: int, iterations: int) -> dict:
    ids = sorted(set(base_by_hand) & set(cand_by_hand))
    deltas = []
    for hid in ids:
        b = base_by_hand[hid]
        c = cand_by_hand[hid]
        if b and c:
            deltas.append(sum(c) / len(c) - sum(b) / len(b))
    if not deltas:
        return {"hands": 0, "iterations": 0, "mean_delta_candidate_minus_baseline": None, "ci95": None, "probability_candidate_better": None}
    rng = random.Random(seed)
    samples = []
    for _ in range(iterations):
        samples.append(sum(deltas[rng.randrange(len(deltas))] for _ in deltas) / len(deltas))
    samples.sort()
    lo = samples[max(0, int(0.025 * len(samples)) - 1)]
    hi = samples[min(len(samples) - 1, int(0.975 * len(samples)))]
    return {
        "hands": len(deltas),
        "iterations": iterations,
        "mean_delta_candidate_minus_baseline": sum(deltas) / len(deltas),
        "ci95": [lo, hi],
        "probability_candidate_better": sum(1 for x in samples if x < 0) / len(samples),
    }


def refit(baseline: dict, rows: list[dict], *, epochs: int = 60, learning_rate: float = 0.08, l2_to_parent: float = 0.25) -> tuple[dict, dict]:
    candidate = copy.deepcopy(baseline)
    train, train_counts = classify_rows(baseline, rows, "TRAIN")
    fit_summary = {}
    changed = 0
    for rk, spec in (candidate.get("response_models") or {}).items():
        new_coef, info = fit_one(spec, train.get(rk, []), epochs=epochs, learning_rate=learning_rate, l2_to_parent=l2_to_parent)
        old = normalized_matrix(spec)
        if new_coef != old:
            changed += 1
        spec["numeric_coef"] = new_coef
        fit_summary[rk] = info
    candidate["response_refit"] = {
        "schema": SCHEMA,
        "runtime_component": "response_models.numeric_coef",
        "selection_split": "VALIDATION",
        "test_consumed": False,
        "production_effect": "NONE",
        "frozen_components": ["nodes", "combo_policy_models", "hand_policy_prior"],
        "nonrevealed_policy": "included: response models use public/action context only",
        "rare_context_policy": "exact canonical node required; otherwise excluded and counted",
        "out_of_support_policy": "runtime-equivalent clipping: facing_price_pot<=5, spr<=50; counts persisted",
        "parameters": {"epochs": epochs, "learning_rate": learning_rate, "l2_to_parent": l2_to_parent},
    }
    return candidate, {"response_models_changed": changed, "fit": fit_summary, "train_coverage": dict(train_counts)}


def run(baseline_path: Path, decisions_path: Path, out_path: Path, report_path: Path, *, epochs: int, learning_rate: float, l2_to_parent: float, seed: int, bootstrap_iterations: int) -> dict:
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    rows = load_rows(decisions_path)
    candidate, fit = refit(baseline, rows, epochs=epochs, learning_rate=learning_rate, l2_to_parent=l2_to_parent)
    base_eval, base_hands = evaluate(baseline, rows, "VALIDATION")
    cand_eval, cand_hands = evaluate(candidate, rows, "VALIDATION")
    boot = paired_bootstrap(base_hands, cand_hands, seed=seed, iterations=bootstrap_iterations)
    delta = None
    if base_eval["log_loss"] is not None and cand_eval["log_loss"] is not None:
        delta = cand_eval["log_loss"] - base_eval["log_loss"]
    ci = boot.get("ci95")
    decision = "PROMOTE_CANDIDATE_SCIENTIFICALLY" if delta is not None and delta < 0 and ci and ci[1] < 0 else "RETAIN_BASELINE"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(candidate, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    report = {
        "schema": SCHEMA,
        "component": "Model A postflop response_models.numeric_coef",
        "scientific_decision": decision,
        "production_effect": "NONE",
        "candidate_is_continuation_compatible": True,
        "selection": {"split": "VALIDATION", "test_consumed": False},
        "baseline_validation": base_eval,
        "candidate_validation": cand_eval,
        "delta_candidate_minus_baseline": delta,
        "paired_hand_bootstrap": boot,
        "fit": fit,
        "limits": [
            "combo_policy_models and hand_policy_prior are frozen in this tranche",
            "unrevealed hands inform public/action response conditioning but not revealed-combo composition",
            "unseen exact canonical contexts are excluded rather than materialized implicitly",
            "sizing and SPR beyond runtime support are clipped identically to the browser and counted",
        ],
        "provenance": {
            "baseline": str(baseline_path), "baseline_sha256": sha256_file(baseline_path),
            "decisions": str(decisions_path), "decisions_sha256": sha256_file(decisions_path),
            "tool": str(Path(__file__)), "tool_sha256": sha256_file(Path(__file__)),
            "candidate": str(out_path), "candidate_sha256": sha256_file(out_path),
            "seed": seed, "bootstrap_iterations": bootstrap_iterations,
            "epochs": epochs, "learning_rate": learning_rate, "l2_to_parent": l2_to_parent,
        },
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--baseline", required=True, type=Path)
    p.add_argument("--decisions", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--report", required=True, type=Path)
    p.add_argument("--epochs", type=int, default=60)
    p.add_argument("--learning-rate", type=float, default=0.08)
    p.add_argument("--l2-to-parent", type=float, default=0.25)
    p.add_argument("--seed", type=int, default=20260915)
    p.add_argument("--bootstrap-iterations", type=int, default=2000)
    return p.parse_args()


def main() -> None:
    a = parse_args()
    run(a.baseline, a.decisions, a.out, a.report, epochs=a.epochs, learning_rate=a.learning_rate,
        l2_to_parent=a.l2_to_parent, seed=a.seed, bootstrap_iterations=a.bootstrap_iterations)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Build a reproducible strategic-baseline report from sequential arena JSON.

The report deliberately separates realized independent-environment utility from the
analyser's displayed EV. Confidence intervals are deterministic cluster bootstraps
at the historical base-hand level, so repeated runouts of one hand are not treated
as independent observations.
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
from typing import Any, Callable

from tools.simulation.model_b_runtime import best

REPORT_SCHEMA = "sequential-v83-baseline-report/v1"
HAND_STRENGTH = [
    "high_card", "pair", "two_pair", "trips", "straight",
    "flush", "full_house", "quads", "straight_flush",
]
SPR_BUCKETS = ((2.0, "<2"), (4.0, "2-4"), (8.0, "4-8"), (16.0, "8-16"))


def quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    xs = sorted(float(x) for x in values)
    if len(xs) == 1:
        return xs[0]
    pos = q * (len(xs) - 1)
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    if lo == hi:
        return xs[lo]
    frac = pos - lo
    return xs[lo] * (1 - frac) + xs[hi] * frac


def stable_seed(*parts: object) -> int:
    text = "|".join(map(str, parts)).encode("utf-8")
    return int.from_bytes(hashlib.sha256(text).digest()[:8], "big")


def cluster_ratio(
    rows: list[dict],
    numerator: Callable[[dict], float],
    denominator: Callable[[dict], float],
    *,
    seed: int,
    label: str,
    samples: int = 5000,
) -> dict[str, Any]:
    clusters: dict[str, list[dict]] = collections.defaultdict(list)
    for row in rows:
        clusters[str(row["hand_id"])].append(row)
    keys = sorted(clusters)
    cluster_values = []
    total_num = total_den = 0.0
    for key in keys:
        num = sum(float(numerator(x)) for x in clusters[key])
        den = sum(float(denominator(x)) for x in clusters[key])
        total_num += num
        total_den += den
        cluster_values.append((num, den))
    estimate = total_num / total_den if total_den > 0 else None
    ci = None
    if len(keys) >= 2 and samples > 0:
        rng = random.Random(stable_seed(seed, "cluster-bootstrap", label))
        draws: list[float] = []
        for _ in range(samples):
            num = den = 0.0
            for _ in keys:
                cnum, cden = cluster_values[rng.randrange(len(cluster_values))]
                num += cnum
                den += cden
            if den > 0:
                draws.append(num / den)
        if draws:
            ci = [quantile(draws, 0.025), quantile(draws, 0.975)]
    return {
        "estimate": estimate,
        "ci95_cluster_bootstrap": ci,
        "clusters": len(keys),
        "observations": len(rows),
        "bootstrap_samples": samples if ci is not None else 0,
        "cluster_unit": "base_hand_id",
    }


def initial_spr(scenario: dict) -> float | None:
    hero = scenario.get("hero")
    opp = scenario.get("opponent")
    stacks = scenario.get("stacks_bb") or {}
    paid = scenario.get("preflop_contributions_bb") or {}
    pot = float(scenario.get("flop_pot_bb") or 0.0)
    if not hero or not opp or pot <= 0:
        return None
    remaining = min(
        float(stacks.get(hero, 0.0)) - float(paid.get(hero, 0.0)),
        float(stacks.get(opp, 0.0)) - float(paid.get(opp, 0.0)),
    )
    return max(0.0, remaining) / pot


def spr_bucket(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "unknown"
    lower = 0.0
    for upper, label in SPR_BUCKETS:
        if value < upper:
            return label
        lower = upper
    return "16+"


def board_for_street(scenario: dict, street: str) -> list[str]:
    flop = list(scenario.get("flop") or [])
    runout = list(scenario.get("runout") or [])
    if street == "flop":
        return flop
    if street == "turn":
        return flop + runout[:1]
    if street == "river":
        return flop + runout[:2]
    return flop


def strength_bucket(scenario: dict, street: str) -> str:
    cards = list(scenario.get("hero_cards") or []) + board_for_street(scenario, street)
    if len(cards) < 5:
        return "unknown"
    category = int(best(cards)[0])
    return HAND_STRENGTH[category] if 0 <= category < len(HAND_STRENGTH) else "unknown"


def action_family(action: dict) -> str:
    label = str(action.get("label") or "").strip().lower()
    if label == "fold":
        return "FOLD"
    if label == "check":
        return "CHECK"
    if label == "call":
        return "CALL"
    if "all-in effectif" in label:
        return "EFFECTIVE_ALLIN"
    if "jam" in label or ("all-in" in label and "effectif" not in label):
        return "JAM"
    return "RAISE" if float(action.get("to_call_bb") or 0.0) > 1e-9 else "BET"


def context_summary(rows: list[dict], seed: int, label: str) -> dict[str, Any]:
    if not rows:
        return {"rollouts": 0}
    utilities = [float(x["utility_bb"]) for x in rows]
    utility = cluster_ratio(rows, lambda x: float(x["utility_bb"]), lambda _x: 1.0, seed=seed, label=label)
    per_decision = cluster_ratio(
        rows,
        lambda x: float(x["utility_bb"]),
        lambda x: float(x.get("hero_decisions") or 0),
        seed=seed,
        label=label + ":per-decision",
    )
    return {
        "rollouts": len(rows),
        "base_hands": len({str(x["hand_id"]) for x in rows}),
        "mean_utility_bb": utility["estimate"],
        "utility_ci95_cluster_bootstrap": utility["ci95_cluster_bootstrap"],
        "median_utility_bb": statistics.median(utilities),
        "p10_utility_bb": quantile(utilities, 0.10),
        "p90_utility_bb": quantile(utilities, 0.90),
        "realized_utility_per_hero_decision_bb": per_decision["estimate"],
        "utility_per_decision_ci95_cluster_bootstrap": per_decision["ci95_cluster_bootstrap"],
    }


def grouped_rollout_summary(rows: list[dict], key: str, seed: int) -> dict[str, Any]:
    groups: dict[str, list[dict]] = collections.defaultdict(list)
    for row in rows:
        groups[str(row.get(key, "unknown"))].append(row)
    return {name: context_summary(items, seed, f"{key}:{name}") for name, items in sorted(groups.items())}


def decision_rows(rows: list[dict], scenarios: dict[str, dict]) -> list[dict]:
    out = []
    for row in rows:
        scenario = scenarios[str(row["scenario_id"])]
        hero = scenario.get("hero")
        position = (scenario.get("positions") or {}).get(hero, "NA")
        spr = initial_spr(scenario)
        for idx, action in enumerate(row.get("hero_actions") or []):
            street = str(action.get("street") or "unknown")
            ratio = action.get("size_ratio")
            out.append({
                "scenario_id": str(row["scenario_id"]),
                "hand_id": str(row["hand_id"]),
                "rep": row.get("rep"),
                "policy": row.get("policy"),
                "profile": str(row.get("profile", "unknown")),
                "hero_position": position,
                "pot_type": scenario.get("pot_type", "unknown"),
                "initial_spr": spr,
                "initial_spr_bucket": spr_bucket(spr),
                "decision_index": idx,
                "street": street,
                "hand_strength": strength_bucket(scenario, street),
                "label": action.get("label"),
                "family": action_family(action),
                "pot_bb": action.get("pot_bb"),
                "to_call_bb": action.get("to_call_bb"),
                "cost_bb": action.get("cost_bb"),
                "size_ratio": ratio,
                "ev_final_bb": action.get("ev_final_bb"),
                "ev_model_bb": action.get("ev_model_bb"),
                "response_observation_floor": action.get("response_observation_floor"),
                "continue_range_quality": action.get("continue_range_quality"),
                "p_all_fold": action.get("p_all_fold"),
            })
    return out


def decision_summary(rows: list[dict]) -> dict[str, Any]:
    families = collections.Counter(str(x["family"]) for x in rows)
    labels = collections.Counter(str(x.get("label")) for x in rows)
    ratios = [float(x["size_ratio"]) for x in rows if x.get("size_ratio") is not None and math.isfinite(float(x["size_ratio"]))]
    aggressive = [x for x in rows if x["family"] in {"BET", "RAISE", "JAM", "EFFECTIVE_ALLIN"}]
    overbets = [x for x in aggressive if x.get("size_ratio") is not None and float(x["size_ratio"]) > 1.0 + 1e-9]
    true_jams = [x for x in rows if x["family"] == "JAM"]
    effective = [x for x in rows if x["family"] == "EFFECTIVE_ALLIN"]
    return {
        "decisions": len(rows),
        "family_counts": dict(sorted(families.items())),
        "label_counts": dict(sorted(labels.items())),
        "aggressive_decisions": len(aggressive),
        "overbet_count": len(overbets),
        "overbet_rate_of_aggression": len(overbets) / len(aggressive) if aggressive else None,
        "true_jam_count": len(true_jams),
        "true_jam_rate": len(true_jams) / len(rows) if rows else None,
        "effective_allin_count": len(effective),
        "effective_allin_rate": len(effective) / len(rows) if rows else None,
        "size_ratio": {
            "n": len(ratios),
            "p50": quantile(ratios, 0.50),
            "p90": quantile(ratios, 0.90),
            "p99": quantile(ratios, 0.99),
            "max": max(ratios) if ratios else None,
        },
    }


def grouped_decision_summary(rows: list[dict], key: str) -> dict[str, Any]:
    groups: dict[str, list[dict]] = collections.defaultdict(list)
    for row in rows:
        groups[str(row.get(key, "unknown"))].append(row)
    return {name: decision_summary(items) for name, items in sorted(groups.items())}


def suspicious_decisions(rows: list[dict], limit: int = 100) -> list[dict]:
    flagged = []
    for row in rows:
        reasons = []
        ratio = row.get("size_ratio")
        observations = row.get("response_observation_floor")
        if row["family"] == "JAM":
            reasons.append("true_jam")
        if ratio is not None and float(ratio) > 2.0:
            reasons.append("sizing_above_2x_pot")
        if row["family"] in {"BET", "RAISE", "JAM", "EFFECTIVE_ALLIN"} and observations is not None and float(observations) < 10:
            reasons.append("response_observation_floor_below_10")
        if not reasons:
            continue
        flagged.append({
            "scenario_id": row["scenario_id"],
            "hand_id": row["hand_id"],
            "rep": row["rep"],
            "profile": row["profile"],
            "street": row["street"],
            "hero_position": row["hero_position"],
            "hand_strength": row["hand_strength"],
            "label": row["label"],
            "family": row["family"],
            "size_ratio": ratio,
            "response_observation_floor": observations,
            "ev_final_bb": row.get("ev_final_bb"),
            "reasons": reasons,
        })
    flagged.sort(key=lambda x: (-max(float(x.get("size_ratio") or 0), 0), x["hand_id"], x["street"]))
    return flagged[:limit]


def paired_policy_comparisons(rows: list[dict], seed: int, reference: str = "current") -> tuple[dict[str, Any], dict[str, Any] | None]:
    by_policy_scenario: dict[str, dict[str, dict]] = collections.defaultdict(dict)
    for row in rows:
        by_policy_scenario[str(row["policy"])][str(row["scenario_id"])] = row
    if reference not in by_policy_scenario:
        return {}, None
    ref = by_policy_scenario[reference]
    comparisons: dict[str, Any] = {}
    common_all = set(ref)
    for policy, mapped in sorted(by_policy_scenario.items()):
        if policy == reference:
            continue
        common = sorted(set(ref) & set(mapped))
        deltas = [
            {
                "hand_id": str(ref[sid]["hand_id"]),
                "delta": float(mapped[sid]["utility_bb"]) - float(ref[sid]["utility_bb"]),
            }
            for sid in common
        ]
        stats = cluster_ratio(deltas, lambda x: x["delta"], lambda _x: 1.0, seed=seed, label=f"paired:{policy}-vs-{reference}") if deltas else None
        comparisons[policy] = {
            "reference": reference,
            "paired_scenarios": len(common),
            "paired_base_hands": len({x["hand_id"] for x in deltas}),
            "mean_delta_utility_bb": stats["estimate"] if stats else None,
            "delta_ci95_cluster_bootstrap": stats["ci95_cluster_bootstrap"] if stats else None,
            "win_tie_loss": {
                "win": sum(x["delta"] > 1e-12 for x in deltas),
                "tie": sum(abs(x["delta"]) <= 1e-12 for x in deltas),
                "loss": sum(x["delta"] < -1e-12 for x in deltas),
            },
        }
        common_all &= set(mapped)

    regret = None
    if len(by_policy_scenario) > 1 and common_all:
        regret_rows = []
        for sid in sorted(common_all):
            ref_row = ref[sid]
            best_utility = max(float(mapped[sid]["utility_bb"]) for mapped in by_policy_scenario.values())
            regret_rows.append({
                "hand_id": str(ref_row["hand_id"]),
                "regret": max(0.0, best_utility - float(ref_row["utility_bb"])),
            })
        stats = cluster_ratio(regret_rows, lambda x: x["regret"], lambda _x: 1.0, seed=seed, label="policy-set-regret")
        regret = {
            "definition": "Diagnostic regret of current versus the best realized utility among only the explicitly evaluated policy variants; not exhaustive action-level counterfactual regret.",
            "policy_set": sorted(by_policy_scenario),
            "paired_scenarios": len(regret_rows),
            "mean_regret_bb": stats["estimate"],
            "ci95_cluster_bootstrap": stats["ci95_cluster_bootstrap"],
        }
    return comparisons, regret


def build_report(arena: dict) -> dict[str, Any]:
    if arena.get("schema") != "sequential-independent-arena/v2":
        raise ValueError("expected sequential-independent-arena/v2")
    metadata = arena.get("metadata") or {}
    manifest = arena.get("scenario_manifest") or {}
    scenarios = {str(x["scenario_id"]): x for x in manifest.get("scenarios") or []}
    rows = []
    for source in arena.get("results") or []:
        sid = str(source["scenario_id"])
        if sid not in scenarios:
            raise ValueError(f"result references unknown scenario {sid}")
        scenario = scenarios[sid]
        hero = scenario.get("hero")
        enriched = dict(source)
        enriched.update({
            "hero_position": (scenario.get("positions") or {}).get(hero, "NA"),
            "pot_type": scenario.get("pot_type", "unknown"),
            "initial_spr": initial_spr(scenario),
            "initial_spr_bucket": spr_bucket(initial_spr(scenario)),
        })
        rows.append(enriched)
    seed = int(metadata.get("master_seed") or manifest.get("master_seed") or 0)
    by_policy: dict[str, list[dict]] = collections.defaultdict(list)
    for row in rows:
        by_policy[str(row["policy"])].append(row)

    policies: dict[str, Any] = {}
    all_decisions: list[dict] = []
    for policy, policy_rows in sorted(by_policy.items()):
        decisions = decision_rows(policy_rows, scenarios)
        all_decisions.extend(decisions)
        policies[policy] = {
            "overall": context_summary(policy_rows, seed, f"policy:{policy}"),
            "rollout_breakdowns": {
                "profile": grouped_rollout_summary(policy_rows, "profile", seed),
                "hero_position": grouped_rollout_summary(policy_rows, "hero_position", seed),
                "pot_type": grouped_rollout_summary(policy_rows, "pot_type", seed),
                "initial_spr_bucket": grouped_rollout_summary(policy_rows, "initial_spr_bucket", seed),
            },
            "decisions": decision_summary(decisions),
            "decision_breakdowns": {
                "street": grouped_decision_summary(decisions, "street"),
                "profile": grouped_decision_summary(decisions, "profile"),
                "hero_position": grouped_decision_summary(decisions, "hero_position"),
                "initial_spr_bucket": grouped_decision_summary(decisions, "initial_spr_bucket"),
                "hand_strength": grouped_decision_summary(decisions, "hand_strength"),
            },
            "suspicious_decisions": suspicious_decisions(decisions),
        }

    comparisons, regret = paired_policy_comparisons(rows, seed)
    return {
        "schema": REPORT_SCHEMA,
        "source_arena_schema": arena["schema"],
        "scope": {
            "heads_up_postflop": True,
            "preflop_strategy": False,
            "multiway_strategy": False,
            "utility_definition": "Realized future utility from the generated flop state; preflop contributions are sunk. It is not an overall cash-game win rate.",
            "spr_breakdown": "Initial effective flop SPR. Decision-level SPR is not recorded by sequential-independent-arena/v2.",
        },
        "environment_limitations": [
            "Model B v2 postflop action probabilities are conditioned on profile, street, FREE/FACING mode, relative position, pot type and preflop role.",
            "Model B v2 postflop action probabilities are not conditioned on hidden hand strength, board texture, facing price-to-pot or SPR; hidden cards affect showdown but not action frequencies.",
            "Sizing conclusions are therefore diagnostic until the response-realism/sensitivity work tracked by issue #46 is satisfied.",
        ],
        "statistical_contract": {
            "confidence_level": 0.95,
            "method": "deterministic nonparametric cluster bootstrap",
            "cluster_unit": "base_hand_id",
            "bootstrap_samples": 5000,
            "rationale": "Multiple runouts/repetitions derived from one historical hand are not counted as independent clusters.",
        },
        "provenance": {
            "code_commit": metadata.get("code_commit"),
            "engine": metadata.get("engine"),
            "model_a": metadata.get("model_a"),
            "model_b": metadata.get("model_b"),
            "scenario_fingerprint_sha256": metadata.get("scenario_fingerprint_sha256"),
            "scenario_split": metadata.get("scenario_split"),
            "master_seed": seed,
            "trials": metadata.get("trials"),
            "observed_monte_carlo_trials": metadata.get("observed_monte_carlo_trials"),
            "policies": metadata.get("policies"),
            "simulation_source_sha256": metadata.get("simulation_source_sha256"),
        },
        "sample": {
            "eligible_hands": manifest.get("eligible_hands"),
            "requested_hands": manifest.get("requested_hands"),
            "reps": manifest.get("reps"),
            "scenarios": len(scenarios),
            "results": len(rows),
            "base_hands": len({str(x.get("hand_id")) for x in rows}),
        },
        "spr_buckets": ["<2", "2-4", "4-8", "8-16", "16+"],
        "hand_strength_buckets": HAND_STRENGTH,
        "policies": policies,
        "paired_policy_comparisons_vs_current": comparisons,
        "diagnostic_policy_set_regret": regret,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arena", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    arena = json.loads(Path(args.arena).read_text(encoding="utf-8"))
    report = build_report(arena)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "schema": report["schema"],
        "sample": report["sample"],
        "policies": sorted(report["policies"]),
    }, indent=2))


if __name__ == "__main__":
    main()

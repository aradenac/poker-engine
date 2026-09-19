#!/usr/bin/env python3
"""Issue #352: TRAIN-only hierarchical sizing-aware Model A v2 and frozen VALIDATION.

The v2 candidate keeps the exact-price marginal likelihoods from #339, but
replaces the sparse hard threshold for revealed hand classes with a global
TRAIN-only empirical-Bayes Dirichlet shrinkage strength selected on a fixed,
predeclared grid. VALIDATION is inaccessible until a separate frozen protocol
is committed. TEST is never loaded.
"""
from __future__ import annotations

import argparse
import collections
import copy
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.preflop.model_a_sizing_likelihood import (
    BACKOFF_POLICY,
    RUNTIME_CANDIDATE_V2_ID,
    candidate_identity,
    canonical_candidate_sha256,
    support_context_key,
    validate_candidate,
)
from tools.training import fit_model_a_preflop_sizing as v1

FIT_PROTOCOL = ROOT / "analysis/model_a_preflop_sizing_v2_fit_protocol.json"
VALIDATION_PROTOCOL = ROOT / "analysis/model_a_preflop_sizing_v2_validation_protocol.json"
V1_FIT = ROOT / "analysis/model_a_preflop_sizing_fit.json"
V1_VALIDATION = ROOT / "analysis/model_a_preflop_sizing_validation.json"
REFERENCE = ROOT / "training/models/preflop_population_model_v5.json"
EXPECTED_SUPPORT_HASH = v1.EXPECTED_SUPPORT_HASH
EXPECTED_REFERENCE_HASH = v1.EXPECTED_REFERENCE_HASH
ACTIONS = v1.ACTIONS
EPS = v1.EPS


def canonical_hash(value: Any) -> str:
    return v1.canonical_hash(value)


def load_fit_protocol() -> dict[str, Any]:
    value = json.loads(FIT_PROTOCOL.read_text(encoding="utf-8"))
    if value.get("schema") != "poker-model-a-preflop-sizing-v2-fit-protocol/v1":
        raise ValueError("unexpected #352 fit protocol schema")
    if value.get("status") != "FROZEN_TRAIN_ONLY_BEFORE_FIT_EXECUTION":
        raise ValueError("#352 fit protocol must be frozen before TRAIN fit")
    candidate = value.get("candidate") or {}
    hand = candidate.get("hand_class") or {}
    if candidate.get("id") != RUNTIME_CANDIDATE_V2_ID:
        raise ValueError("#352 candidate_id drifted")
    if candidate.get("nearest_price_fallback") is not False:
        raise ValueError("#352 nearest-price fallback is forbidden")
    grid = hand.get("prior_strength_grid")
    if not isinstance(grid, list) or not grid or any(float(x) <= 0 for x in grid):
        raise ValueError("#352 prior-strength grid is invalid")
    if len({float(x) for x in grid}) != len(grid):
        raise ValueError("#352 prior-strength grid must be unique")
    if value.get("forbidden") and "VALIDATION_DURING_HYPERPARAMETER_SELECTION" not in value["forbidden"]:
        raise ValueError("#352 TRAIN-only hyperparameter boundary missing")
    return value


def _dirichlet_multinomial_log_kernel(
    counts: Mapping[str, Any],
    marginal: Mapping[str, float],
    prior_strength: float,
) -> float:
    n = sum(max(0, int(counts.get(action) or 0)) for action in ACTIONS)
    tau = float(prior_strength)
    if n <= 0 or tau <= 0:
        raise ValueError("Dirichlet-multinomial cell requires positive support and prior")
    score = math.lgamma(tau) - math.lgamma(tau + n)
    for action in ACTIONS:
        p = max(EPS, float(marginal[action]))
        alpha = tau * p
        c = max(0, int(counts.get(action) or 0))
        score += math.lgamma(alpha + c) - math.lgamma(alpha)
    return score


def _support_band(n: int) -> str:
    if n < 5:
        return "SPARSE_REVEAL_SHRUNK"
    if n < 20:
        return "LOW_REVEAL_SHRUNK"
    if n < 50:
        return "MEDIUM_REVEAL_SHRUNK"
    return "IDENTIFIABLE_REVEAL_SHRUNK"


def _base_marginal_candidate(
    report: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Mapping[str, Any]]]:
    protocol = v1.load_protocol()
    candidate, _ = v1.build_candidate(protocol, report)
    marginal_nodes = {
        str(node["support_context_key"]): node
        for node in candidate["nodes"]
        if node.get("hand_class") is None
    }
    return candidate, marginal_nodes


def select_prior_strength(
    fit_protocol: Mapping[str, Any],
    report: Mapping[str, Any],
    marginal_nodes: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    grid = [
        float(x)
        for x in fit_protocol["candidate"]["hand_class"]["prior_strength_grid"]
    ]
    scored_cells: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    for cell in report.get("revealed_hand_class_support") or []:
        counts = (cell.get("actions") or {}).get("counts") or {}
        supported_n = sum(max(0, int(counts.get(action) or 0)) for action in ACTIONS)
        if supported_n < 1:
            continue
        key = support_context_key(v1._support_mapping(cell))
        marginal = marginal_nodes.get(key)
        if marginal is None:
            continue
        scored_cells.append((cell, marginal))

    if not scored_cells:
        raise ValueError("#352 has no TRAIN revealed hand-class cells on supported marginals")

    scores: list[dict[str, Any]] = []
    for tau in grid:
        total = 0.0
        observations = 0
        for cell, marginal in scored_cells:
            counts = (cell.get("actions") or {}).get("counts") or {}
            total += _dirichlet_multinomial_log_kernel(
                counts,
                marginal["probabilities"],
                tau,
            )
            counts = (cell.get("actions") or {}).get("counts") or {}
            observations += sum(max(0, int(counts.get(action) or 0)) for action in ACTIONS)
        scores.append({
            "prior_strength": tau,
            "log_marginal_likelihood_kernel": round(total, 12),
            "cells": len(scored_cells),
            "revealed_observations": observations,
        })

    best_score = max(float(row["log_marginal_likelihood_kernel"]) for row in scores)
    winners = [
        row for row in scores
        if math.isclose(
            float(row["log_marginal_likelihood_kernel"]),
            best_score,
            rel_tol=1e-15,
            abs_tol=1e-12,
        )
    ]
    chosen = min(winners, key=lambda row: float(row["prior_strength"]))
    return {
        "method": "DIRICHLET_EMPIRICAL_BAYES_TO_EXACT_PRICE_MARGINAL",
        "selection_scope": "CERTIFIED_TRAIN_REVEALED_ROWS_ONLY",
        "objective": "MAXIMIZE_SUM_DIRICHLET_MULTINOMIAL_LOG_MARGINAL_LIKELIHOOD",
        "tie_break": "SMALLEST_PRIOR_STRENGTH",
        "grid": scores,
        "selected_prior_strength": float(chosen["prior_strength"]),
        "cells_scored": int(chosen["cells"]),
        "revealed_observations_scored": int(chosen["revealed_observations"]),
        "validation_consumed": False,
        "test_consumed": False,
    }


def build_candidate(
    fit_protocol: Mapping[str, Any],
    report: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    base, marginal_nodes = _base_marginal_candidate(report)
    selection = select_prior_strength(fit_protocol, report, marginal_nodes)
    tau = float(selection["selected_prior_strength"])

    nodes = [copy.deepcopy(node) for node in marginal_nodes.values()]
    band_counts: collections.Counter[str] = collections.Counter()
    hand_nodes = 0
    for cell in report.get("revealed_hand_class_support") or []:
        counts = (cell.get("actions") or {}).get("counts") or {}
        raw = {action: max(0, int(counts.get(action) or 0)) for action in ACTIONS}
        n = sum(raw.values())
        if n < int(
            fit_protocol["candidate"]["hand_class"][
                "minimum_revealed_observations_for_node"
            ]
        ):
            continue
        key = support_context_key(v1._support_mapping(cell))
        marginal = marginal_nodes.get(key)
        if marginal is None:
            continue
        denom = n + tau
        probabilities = {
            action: (
                raw[action] + tau * float(marginal["probabilities"][action])
            ) / denom
            for action in ACTIONS
        }
        data_weight = n / denom
        prior_weight = tau / denom
        hand_class = str(cell["hand_class"])
        band = _support_band(n)
        node = {
            "node_id": "MAPH2_" + hashlib.sha256(
                (key + "|" + hand_class).encode("utf-8")
            ).hexdigest()[:16],
            "sizing_context_key": marginal["sizing_context_key"],
            "support_context_key": key,
            "public_context": dict(marginal["public_context"]),
            "hand_class": hand_class,
            "probabilities": probabilities,
            "support": n,
            "support_denominator": n,
            "support_class": band,
            "source_report_hash": EXPECTED_SUPPORT_HASH,
            "fit_method": (
                "DIRICHLET_EMPIRICAL_BAYES_TO_EXACT_PRICE_MARGINAL_"
                f"PRIOR_{tau:g}"
            ),
            "reveal_bias": {
                "reveal_selected": True,
                "reveal_fraction": (marginal.get("reveal_bias") or {}).get(
                    "reveal_fraction"
                ),
                "mechanism": "MNAR",
                "hidden_hands_imputed": False,
            },
            "shrinkage": {
                "method": "DIRICHLET_EMPIRICAL_BAYES_TO_EXACT_PRICE_MARGINAL",
                "prior_strength": tau,
                "data_weight": data_weight,
                "prior_weight": prior_weight,
                "selection_scope": "CERTIFIED_TRAIN_REVEALED_ROWS_ONLY",
                "selection_rule": (
                    "fixed grid; maximize summed Dirichlet-multinomial "
                    "TRAIN log marginal likelihood; ties -> smallest prior"
                ),
                "train_revealed_observations": n,
            },
        }
        nodes.append(node)
        band_counts[band] += 1
        hand_nodes += 1

    candidate = {
        "schema": base["schema"],
        "identity": candidate_identity(
            population_id=str(report["population_id"]),
            fit_scope="TRAIN_EMPIRICAL_FIT",
            data_scope="CERTIFIED_TRAIN_ONLY",
            source_report_hash=EXPECTED_SUPPORT_HASH,
            candidate_id=RUNTIME_CANDIDATE_V2_ID,
        ),
        "backoff_policy": list(BACKOFF_POLICY),
        "nearest_price_fallback": False,
        "nodes": sorted(
            nodes,
            key=lambda node: (
                str(node.get("support_context_key") or ""),
                "" if node.get("hand_class") is None else str(node["hand_class"]),
            ),
        ),
    }
    validate_candidate(candidate)
    candidate_sha = canonical_candidate_sha256(candidate)

    weights = [
        float(node["shrinkage"]["prior_weight"])
        for node in candidate["nodes"]
        if node.get("hand_class") is not None
    ]
    fit_evidence = {
        "schema": "poker-model-a-preflop-sizing-v2-fit-evidence/v1",
        "issue": 352,
        "parent_issue": 314,
        "population_id": report["population_id"],
        "split_consumed": "TRAIN",
        "validation_consumed": False,
        "test_consumed": False,
        "source_support_report_hash": EXPECTED_SUPPORT_HASH,
        "fit_protocol": {
            "path": FIT_PROTOCOL.relative_to(ROOT).as_posix(),
            "sha256": v1.sha256_file(FIT_PROTOCOL),
            "status": fit_protocol["status"],
        },
        "candidate_sha256": candidate_sha,
        "candidate_identity": candidate["identity"],
        "nodes": {
            "total": len(candidate["nodes"]),
            "marginal_exact_price": len(marginal_nodes),
            "revealed_hand_class_shrunk": hand_nodes,
            "by_support_band": dict(sorted(band_counts.items())),
        },
        "shrinkage": {
            **selection,
            "prior_weight_summary": {
                "minimum": min(weights) if weights else None,
                "maximum": max(weights) if weights else None,
                "mean": round(sum(weights) / len(weights), 12) if weights else None,
            },
            "marginal_anchor": "SAME_EXACT_PRICE_ONLY",
            "nearest_price_fallback": False,
            "hidden_hands_imputed": False,
            "reveal_bias": "MNAR_REVEAL_SELECTED",
        },
        "reference_candidate_339": {
            "candidate_id": "model-a-preflop-sizing-aware-candidate-v1",
            "fit_evidence_path": V1_FIT.relative_to(ROOT).as_posix(),
            "fit_evidence_sha256": canonical_hash(
                json.loads(V1_FIT.read_text(encoding="utf-8"))
            ),
        },
        "production_effect": "NONE",
        "active_model_replaced": False,
        "model_b_consumed": False,
        "hero_ev_consumed": False,
        "ui_modified": False,
        "issue_314_real_optimization": False,
        "reproduction": (
            "python3 tools/training/fit_model_a_preflop_sizing_v2.py --phase fit"
        ),
    }
    fit_evidence["posterior_321"] = v1.evaluate_kts_posterior(candidate)
    fit_evidence["evidence_sha256"] = canonical_hash(
        {k: v for k, v in fit_evidence.items() if k != "evidence_sha256"}
    )
    return candidate, fit_evidence


def load_validation_protocol(
    fit_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    if not VALIDATION_PROTOCOL.is_file():
        raise ValueError(
            "#352 VALIDATION protocol is not committed; VALIDATION is forbidden"
        )
    protocol = json.loads(VALIDATION_PROTOCOL.read_text(encoding="utf-8"))
    if (
        protocol.get("schema")
        != "poker-model-a-preflop-sizing-v2-validation-protocol/v1"
    ):
        raise ValueError("unexpected #352 VALIDATION protocol schema")
    if protocol.get("status") != "FROZEN_BEFORE_VALIDATION":
        raise ValueError("#352 protocol must be frozen before VALIDATION")
    evaluation = protocol.get("evaluation") or {}
    if evaluation.get("split") != "VALIDATION":
        raise ValueError("#352 may evaluate only VALIDATION")
    if evaluation.get("test_consumed") is not False:
        raise ValueError("TEST must stay unconsumed")
    frozen_fit = protocol.get("frozen_train_fit") or {}
    if frozen_fit.get("candidate_sha256") != fit_evidence.get("candidate_sha256"):
        raise ValueError("v2 candidate hash differs from frozen protocol")
    if not math.isclose(
        float(frozen_fit.get("selected_prior_strength")),
        float(fit_evidence["shrinkage"]["selected_prior_strength"]),
        rel_tol=0.0,
        abs_tol=0.0,
    ):
        raise ValueError("v2 selected TRAIN prior differs from frozen protocol")
    if frozen_fit.get("fit_evidence_sha256") != fit_evidence.get("evidence_sha256"):
        raise ValueError("v2 fit evidence differs from frozen protocol")
    return protocol


def _index(
    candidate: Mapping[str, Any],
) -> dict[tuple[str, str | None], Mapping[str, Any]]:
    return v1._candidate_index(candidate)


def _score_model_rows(
    rows: Sequence[Mapping[str, Any]],
    model_names: Sequence[str],
    pair_specs: Sequence[tuple[str, str, str]],
    *,
    bootstrap_samples: int,
    bootstrap_seed: int,
) -> dict[str, Any]:
    if not rows:
        return {
            "rows": 0,
            "hands": 0,
            "model_logloss": {name: None for name in model_names},
            "pairwise": {},
        }
    model_logloss = {
        name: sum(float(row["nll"][name]) for row in rows) / len(rows)
        for name in model_names
    }
    pairwise: dict[str, Any] = {}
    for offset, (label, left, right) in enumerate(pair_specs):
        detail = [
            {
                "hand_id": str(row["hand_id"]),
                "delta_nll": float(row["nll"][left]) - float(row["nll"][right]),
            }
            for row in rows
        ]
        paired = v1.bootstrap(
            detail,
            samples=bootstrap_samples,
            seed=bootstrap_seed + offset,
        )
        pairwise[label] = {
            "left": left,
            "right": right,
            "delta_logloss": model_logloss[left] - model_logloss[right],
            "paired_bootstrap": paired,
        }
    return {
        "rows": len(rows),
        "hands": len({str(row["hand_id"]) for row in rows}),
        "model_logloss": model_logloss,
        "pairwise": pairwise,
    }


def evaluate_validation(
    protocol: Mapping[str, Any],
    candidate: Mapping[str, Any],
    fit_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    if v1.sha256_file(REFERENCE) != EXPECTED_REFERENCE_HASH:
        raise ValueError("active Model A v5 reference hash drifted")
    v1_protocol = v1.load_protocol()
    _, report = v1.load_support_report()
    candidate_339, fit_339 = v1.build_candidate(v1_protocol, report)
    persisted_339 = json.loads(V1_FIT.read_text(encoding="utf-8"))
    if fit_339["candidate_sha256"] != persisted_339["candidate_sha256"]:
        raise ValueError("#339 candidate reconstruction drifted")

    model = json.loads(REFERENCE.read_text(encoding="utf-8"))
    reference_index = v1.by_actor(list(model.get("nodes") or []))
    v1_index = _index(candidate_339)
    v2_index = _index(candidate)
    rows, validation_provenance = v1.validation_rows()

    global_rows: list[dict[str, Any]] = []
    hand_rows: list[dict[str, Any]] = []
    exact_unresolved = 0
    hand_min_support = int(
        protocol["evaluation"]["hand_conditioned"]["minimum_train_revealed_support"]
    )

    for row in rows:
        key = support_context_key(row)
        marginal_v2 = v2_index.get((key, None))
        marginal_v1 = v1_index.get((key, None))
        if marginal_v2 is None or marginal_v1 is None:
            exact_unresolved += 1
            continue
        action = v1._normalised_action(row.get("action"))
        if action not in ACTIONS:
            continue
        active_p, _, _ = v1._reference_probability(
            model,
            reference_index,
            row,
            hand_conditioned=False,
        )
        p339 = max(
            EPS,
            min(1.0, float(marginal_v1["probabilities"][action])),
        )
        p2 = max(
            EPS,
            min(1.0, float(marginal_v2["probabilities"][action])),
        )
        global_rows.append({
            "hand_id": str(row["hand_id"]),
            "nll": {
                "active_v5": -math.log(active_p),
                "candidate_339": -math.log(p339),
                "candidate_v2": -math.log(p2),
            },
        })

        hand_class = row.get("known_hand_class")
        if not hand_class:
            continue
        h2 = v2_index.get((key, str(hand_class)))
        if h2 is None or int(h2.get("support") or 0) < hand_min_support:
            continue
        h1 = v1_index.get((key, str(hand_class)))
        h1_source = h1 if h1 is not None else marginal_v1
        active_hp, _, _ = v1._reference_probability(
            model,
            reference_index,
            row,
            hand_conditioned=True,
        )
        pv2 = max(EPS, min(1.0, float(h2["probabilities"][action])))
        pold = max(EPS, min(1.0, float(h1_source["probabilities"][action])))
        pmarg = max(EPS, min(1.0, float(marginal_v2["probabilities"][action])))
        hand_rows.append({
            "hand_id": str(row["hand_id"]),
            "train_revealed_support": int(h2["support"]),
            "candidate_339_source": (
                "HAND_CLASS" if h1 is not None else "MARGINAL_EXACT_PRICE"
            ),
            "nll": {
                "active_v5": -math.log(active_hp),
                "candidate_339": -math.log(pold),
                "candidate_v2": -math.log(pv2),
                "v2_exact_price_marginal": -math.log(pmarg),
            },
        })

    primary_cfg = protocol["evaluation"]["global_exact_price"]
    hand_cfg = protocol["evaluation"]["hand_conditioned"]
    global_metric = _score_model_rows(
        global_rows,
        ["active_v5", "candidate_339", "candidate_v2"],
        [
            ("v2_minus_active", "candidate_v2", "active_v5"),
            ("v2_minus_339", "candidate_v2", "candidate_339"),
        ],
        bootstrap_samples=int(primary_cfg["bootstrap_samples"]),
        bootstrap_seed=int(primary_cfg["bootstrap_seed"]),
    )
    hand_metric = _score_model_rows(
        hand_rows,
        [
            "active_v5",
            "candidate_339",
            "candidate_v2",
            "v2_exact_price_marginal",
        ],
        [
            ("v2_minus_active", "candidate_v2", "active_v5"),
            ("v2_minus_339", "candidate_v2", "candidate_339"),
            (
                "v2_minus_exact_price_marginal",
                "candidate_v2",
                "v2_exact_price_marginal",
            ),
        ],
        bootstrap_samples=int(hand_cfg["bootstrap_samples"]),
        bootstrap_seed=int(hand_cfg["bootstrap_seed"]),
    )

    global_gate = (
        global_metric["rows"] > 0
        and float(
            global_metric["pairwise"]["v2_minus_active"]["paired_bootstrap"]["ci95"][1]
        ) <= 0.0
        and abs(
            float(global_metric["pairwise"]["v2_minus_339"]["delta_logloss"])
        ) <= float(primary_cfg["maximum_abs_delta_vs_339"])
    )
    hand_support_gate = (
        int(hand_metric["rows"]) >= int(hand_cfg["minimum_validation_rows"])
        and int(hand_metric["hands"]) >= int(hand_cfg["minimum_validation_hands"])
    )
    hand_active_gate = (
        hand_support_gate
        and float(
            hand_metric["pairwise"]["v2_minus_active"]["paired_bootstrap"]["ci95"][1]
        ) <= 0.0
    )
    hand_339_gate = (
        hand_support_gate
        and float(
            hand_metric["pairwise"]["v2_minus_339"]["paired_bootstrap"]["ci95"][1]
        ) <= 0.0
    )
    hand_information_gate = (
        hand_support_gate
        and float(
            hand_metric["pairwise"]["v2_minus_exact_price_marginal"][
                "paired_bootstrap"
            ]["ci95"][1]
        ) <= 0.0
    )
    admitted = (
        global_gate
        and hand_support_gate
        and hand_active_gate
        and hand_339_gate
        and hand_information_gate
    )

    result = {
        "schema": "poker-model-a-preflop-sizing-v2-validation/v1",
        "issue": 352,
        "parent_issue": 314,
        "phase": "VALIDATION",
        "selection_split": "VALIDATION",
        "protocol": {
            "path": VALIDATION_PROTOCOL.relative_to(ROOT).as_posix(),
            "sha256": v1.sha256_file(VALIDATION_PROTOCOL),
            "status": protocol["status"],
        },
        "inputs": {
            "active_reference": {
                "id": "active-model-a-preflop-v5",
                "path": REFERENCE.relative_to(ROOT).as_posix(),
                "sha256": EXPECTED_REFERENCE_HASH,
            },
            "candidate_339": {
                "candidate_id": candidate_339["identity"]["candidate_id"],
                "candidate_sha256": fit_339["candidate_sha256"],
                "role": "DESCRIPTIVE_REJECTED_PREDECESSOR_ONLY",
                "persisted_validation": V1_VALIDATION.relative_to(ROOT).as_posix(),
            },
            "candidate_v2": {
                "candidate_id": candidate["identity"]["candidate_id"],
                "candidate_sha256": fit_evidence["candidate_sha256"],
                "selected_prior_strength": fit_evidence["shrinkage"][
                    "selected_prior_strength"
                ],
            },
            "support_report_hash": EXPECTED_SUPPORT_HASH,
            "validation": validation_provenance,
        },
        "coverage": {
            "validation_population_rows_in_scope": len(rows),
            "exact_price_rows_scored": len(global_rows),
            "unresolved_no_exact_supported_price_cell": exact_unresolved,
            "hand_conditioned_rows_scored": len(hand_rows),
            "minimum_train_revealed_support_for_hand_gate": hand_min_support,
        },
        "metrics": {
            "global_exact_price": global_metric,
            "hand_conditioned": hand_metric,
        },
        "gate": {
            "global_v2_vs_active_and_339_parity": global_gate,
            "hand_support_minimum_met": hand_support_gate,
            "hand_v2_vs_active": hand_active_gate,
            "hand_v2_vs_339": hand_339_gate,
            "hand_v2_adds_information_vs_exact_price_marginal": hand_information_gate,
        },
        "outcome": "ADMIT_CANDIDATE" if admitted else "RETAIN_ACTIVE_REFERENCE",
        "reason": (
            "all frozen global and hand-conditioned predictive gates passed"
            if admitted
            else "one or more frozen VALIDATION gates failed; active Model A remains unchanged"
        ),
        "test_consumed": False,
        "test_authorized": False,
        "production_effect": "NONE",
        "active_model_replaced": False,
        "automatic_promotion": False,
        "model_b_consumed": False,
        "hero_ev_consumed": False,
        "ui_modified": False,
        "issue_314_real_optimization": False,
    }
    result["evidence_sha256"] = canonical_hash(result)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("fit", "validation", "both"), default="fit")
    parser.add_argument("--candidate-out", type=Path)
    parser.add_argument("--fit-evidence-out", type=Path)
    parser.add_argument("--validation-out", type=Path)
    parser.add_argument("--print-marker", action="store_true")
    return parser.parse_args()


def write_json(path: Path | None, value: Mapping[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    fit_protocol = load_fit_protocol()
    _, report = v1.load_support_report()
    candidate, fit = build_candidate(fit_protocol, report)
    write_json(args.candidate_out, candidate)
    write_json(args.fit_evidence_out, fit)

    validation = None
    if args.phase in {"validation", "both"}:
        protocol = load_validation_protocol(fit)
        validation = evaluate_validation(protocol, candidate, fit)
        write_json(args.validation_out, validation)

    payload = {"fit": fit, "validation": validation}
    if args.print_marker:
        print(
            "ISSUE352_RESULT="
            + json.dumps(payload, sort_keys=True, separators=(",", ":"))
        )
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def load(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"expected JSON object: {p}")
    return data


def require(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(msg)


def normalized_model_b_summary(data: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(data)
    features = out.get("features")
    if isinstance(features, dict):
        features.pop("path", None)
    return out


def verify_model_b(
    actual: dict[str, Any],
    expected: dict[str, Any],
    *,
    candidate_summary: dict[str, Any] | None = None,
    expected_candidate_summary: dict[str, Any] | None = None,
) -> None:
    require(actual.get("schema") == "independent-model-b-paired-comparison/v1", "unexpected Model B comparison schema")
    require(actual.get("dataset") == expected.get("dataset"), "Model B dataset identity differs from canonical cycle")
    require(actual.get("paired") == expected.get("paired"), "Model B paired holdout result differs from canonical cycle")
    require(actual.get("guardrails") == expected.get("guardrails"), "Model B guardrails differ from canonical cycle")

    for side in ("candidate", "incumbent"):
        keys = ["profiles_sha256", "ranges_sha256", "actions_sha256", "sizing_sha256"]
        if side == "incumbent":
            keys.append("summary_sha256")
        for key in keys:
            require(actual.get(side, {}).get(key) == expected.get(side, {}).get(key), f"Model B {side}.{key} differs")

    if candidate_summary is not None or expected_candidate_summary is not None:
        require(candidate_summary is not None and expected_candidate_summary is not None, "both candidate summaries are required")
        require(
            normalized_model_b_summary(candidate_summary) == normalized_model_b_summary(expected_candidate_summary),
            "Model B candidate summary differs beyond features.path provenance",
        )

    require(actual.get("decision") == expected.get("decision"), "Model B decision differs from canonical cycle")


def verify_strategy(actual: dict[str, Any], expected: dict[str, Any]) -> None:
    require(actual.get("schema") == "poker-strategy-candidate-gate/v1", "unexpected strategy gate schema")
    for key in (
        "phase", "selection_split", "status", "outcome", "frozen_finalist",
        "test_authorized", "test_used_for_selection", "sample", "candidates",
        "required_ci95_lower_bound_bb", "minimum_paired_base_hands",
    ):
        require(actual.get(key) == expected.get(key), f"strategy {key} differs from canonical cycle")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-b-report")
    ap.add_argument("--expected-model-b", default="training/runs/20260912_population_increment_cycle/model_b/evaluation/paired_comparison.json")
    ap.add_argument("--candidate-summary")
    ap.add_argument("--expected-candidate-summary", default="training/runs/20260912_population_increment_cycle/model_b/model/summary.json")
    ap.add_argument("--strategy-selection")
    ap.add_argument("--expected-strategy", default="training/runs/20260913_strategy_candidate_v84/validation_selection.json")
    args = ap.parse_args()

    if not args.model_b_report and not args.strategy_selection:
        raise SystemExit("at least one artifact must be supplied")
    if args.model_b_report:
        verify_model_b(
            load(args.model_b_report),
            load(args.expected_model_b),
            candidate_summary=load(args.candidate_summary) if args.candidate_summary else None,
            expected_candidate_summary=load(args.expected_candidate_summary) if args.candidate_summary else None,
        )
        print("Model B reference result verified")
    if args.strategy_selection:
        verify_strategy(load(args.strategy_selection), load(args.expected_strategy))
        print("strategy reference result verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Select and confirm a Hero strategy candidate without consuming TEST for tuning.

VALIDATION phase reads a paired baseline report, applies the repository's frozen
strategy-candidate contract, and either freezes exactly one finalist or retains the
promoted baseline. TEST phase can only confirm the already-frozen finalist; it
cannot select a different policy or retune thresholds.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

SCHEMA = "poker-strategy-candidate-gate/v1"


def _finite(value: Any) -> float:
    x = float(value)
    if not math.isfinite(x):
        raise ValueError(f"non-finite numeric value: {value!r}")
    return x


def _comparison(report: dict[str, Any], policy: str) -> dict[str, Any]:
    comparisons = report.get("paired_policy_comparisons_vs_current") or {}
    value = comparisons.get(policy)
    if not isinstance(value, dict):
        raise ValueError(f"missing paired comparison for policy {policy!r}")
    ci = value.get("delta_ci95_cluster_bootstrap")
    if not isinstance(ci, list) or len(ci) != 2:
        raise ValueError(f"missing CI95 for policy {policy!r}")
    return {
        "policy": policy,
        "reference": value.get("reference"),
        "paired_scenarios": int(value.get("paired_scenarios") or 0),
        "paired_base_hands": int(value.get("paired_base_hands") or 0),
        "mean_delta_utility_bb": _finite(value.get("mean_delta_utility_bb")),
        "ci95": [_finite(ci[0]), _finite(ci[1])],
        "win_tie_loss": value.get("win_tie_loss"),
    }


def _common(contract: dict[str, Any], report: dict[str, Any], phase: str) -> dict[str, Any]:
    env = contract["strategy_environment"]
    if report.get("environment_variant") != "independent_model_b_v3_response_conditioned_candidate":
        raise ValueError("report is not from the response-conditioned Model B v3 environment")
    sample = report.get("sample") or {}
    split_cfg = contract[phase]
    expected_base = int(split_cfg["base_hands"])
    observed_base = int(sample.get("base_hands") or 0)
    if observed_base < expected_base:
        raise ValueError(f"{phase} report has only {observed_base} base hands; contract requires {expected_base}")
    return {
        "contract_version": contract["contract_version"],
        "phase": phase.upper(),
        "environment": {
            "response_variant": env["response_variant"],
            "production_effect": env["production_effect"],
            "supported_scope": env["supported_scope"],
            "benchmark_reference": env["benchmark_reference"],
        },
        "sample": {
            "base_hands": observed_base,
            "scenarios": int(sample.get("scenarios") or 0),
            "required_base_hands": expected_base,
        },
    }


def evaluate_validation(contract: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    cfg = contract["validation"]
    out = _common(contract, report, "validation")
    required_lower = _finite(cfg["selection_rule"]["required_ci95_lower_bound_candidate_minus_current_bb"])
    minimum = int(cfg["minimum_paired_base_hands"])
    candidates: list[dict[str, Any]] = []
    for order, policy in enumerate(cfg["candidates"]):
        item = _comparison(report, str(policy))
        sample_ok = item["paired_base_hands"] >= minimum
        lower_ok = item["ci95"][0] >= required_lower
        item.update({
            "contract_order": order,
            "sample_gate_pass": sample_ok,
            "ci95_lower_gate_pass": lower_ok,
            "eligible": sample_ok and lower_ok,
        })
        candidates.append(item)

    eligible = [x for x in candidates if x["eligible"]]
    eligible.sort(key=lambda x: (-x["ci95"][0], -x["mean_delta_utility_bb"], x["contract_order"]))
    finalist = eligible[0]["policy"] if eligible else None
    outcome = "FREEZE_FINALIST" if finalist else "RETAIN_BASELINE"
    out.update({
        "schema": SCHEMA,
        "status": "PASS",
        "selection_split": "VALIDATION",
        "test_used_for_selection": False,
        "reference_policy": cfg["reference_policy"],
        "required_ci95_lower_bound_bb": required_lower,
        "minimum_paired_base_hands": minimum,
        "candidates": candidates,
        "outcome": outcome,
        "frozen_finalist": finalist,
        "test_authorized": finalist is not None,
        "reason": (
            f"{finalist} clears the pre-specified VALIDATION paired-CI and sample gates and is frozen for TEST confirmation."
            if finalist
            else "No candidate clears the pre-specified VALIDATION paired-CI and sample gates; retain v83 and do not consume TEST for candidate selection."
        ),
    })
    return out


def evaluate_test(contract: dict[str, Any], report: dict[str, Any], validation: dict[str, Any]) -> dict[str, Any]:
    out = _common(contract, report, "test")
    if validation.get("schema") != SCHEMA or validation.get("phase") != "VALIDATION":
        raise ValueError("validation selection is not a valid frozen VALIDATION gate result")
    if validation.get("outcome") != "FREEZE_FINALIST" or not validation.get("frozen_finalist"):
        raise ValueError("TEST cannot run without a frozen VALIDATION finalist")
    finalist = str(validation["frozen_finalist"])
    allowed = {str(x) for x in contract["validation"]["candidates"]}
    if finalist not in allowed:
        raise ValueError("frozen finalist is not part of the pre-specified candidate set")

    cfg = contract["test"]
    comparison = _comparison(report, finalist)
    minimum = int(cfg["base_hands"])
    required_lower = _finite(cfg["confirmation_rule"]["required_ci95_lower_bound_finalist_minus_current_bb"])
    sample_ok = comparison["paired_base_hands"] >= minimum
    lower_ok = comparison["ci95"][0] >= required_lower
    confirmed = sample_ok and lower_ok
    out.update({
        "schema": SCHEMA,
        "status": "PASS",
        "selection_split": "TEST",
        "test_used_for_selection": False,
        "test_may_select_alternative": False,
        "test_may_retune": False,
        "frozen_finalist": finalist,
        "comparison": comparison,
        "required_ci95_lower_bound_bb": required_lower,
        "sample_gate_pass": sample_ok,
        "ci95_lower_gate_pass": lower_ok,
        "outcome": "CONFIRM_FINALIST" if confirmed else "RETAIN_BASELINE",
        "strategy_decision": "PROMOTE_CANDIDATE" if confirmed else "RETAIN_BASELINE",
        "reason": (
            f"Protected TEST confirms frozen finalist {finalist} under the pre-specified paired-CI gate."
            if confirmed
            else f"Protected TEST does not confirm frozen finalist {finalist}; retain v83. TEST did not select an alternative."
        ),
    })
    return out


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--contract", required=True)
    p.add_argument("--report", required=True)
    p.add_argument("--phase", required=True, choices=("validation", "test"))
    p.add_argument("--validation-selection", default="", help="required only for TEST; frozen VALIDATION gate JSON")
    p.add_argument("--out", required=True)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    contract = json.loads(Path(args.contract).read_text(encoding="utf-8"))
    if contract.get("schema") != "poker-strategy-candidate-contract/v1":
        raise ValueError("unsupported strategy candidate contract schema")
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    if args.phase == "validation":
        result = evaluate_validation(contract, report)
    else:
        if not args.validation_selection:
            raise ValueError("--validation-selection is required for TEST")
        validation = json.loads(Path(args.validation_selection).read_text(encoding="utf-8"))
        result = evaluate_test(contract, report, validation)
    text = json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

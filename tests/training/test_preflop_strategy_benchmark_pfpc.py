#!/usr/bin/env python3
from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training.validate_preflop_strategy_benchmark_pfpc import (  # noqa: E402
    DEFAULT_BASE,
    DEFAULT_CONTRACT,
    DEFAULT_PREVIOUS,
    DEFAULT_REFERENCE,
    DEFAULT_SENSITIVITY,
    DEFAULT_ZERO_EXPOSURE,
    load,
    validate_contract,
)


def inputs():
    return (
        load(DEFAULT_CONTRACT),
        load(DEFAULT_PREVIOUS),
        load(DEFAULT_BASE),
        load(DEFAULT_REFERENCE),
        load(DEFAULT_SENSITIVITY),
        load(DEFAULT_ZERO_EXPOSURE),
    )


def test_persisted_pfpc_contract_validates() -> None:
    result = validate_contract(*inputs())
    assert result["status"] == "PASS", result["errors"]
    assert result["contract_version"] == "2026-09-18.3"


def test_pfpc_contract_cannot_change_frozen_budget_or_threshold_semantics() -> None:
    contract, previous, base, reference, sensitivity, zero = inputs()
    mutated = copy.deepcopy(contract)
    mutated["statistics"]["bootstrap_samples"] = int(mutated["statistics"]["bootstrap_samples"]) + 1
    result = validate_contract(mutated, previous, base, reference, sensitivity, zero)
    assert result["status"] == "FAIL"
    assert any("statistics" in error for error in result["errors"])

    mutated = copy.deepcopy(contract)
    mutated["validation_selection"]["required_ci95_lower_bound_bb_per_100"] = -0.01
    result = validate_contract(mutated, previous, base, reference, sensitivity, zero)
    assert result["status"] == "FAIL"
    assert any("validation rule" in error for error in result["errors"])


def test_pfpc_matching_and_binding_identity_are_mandatory() -> None:
    contract, previous, base, reference, sensitivity, zero = inputs()
    mutated = copy.deepcopy(contract)
    mutated["candidate_policy"]["matching"] = "EXACT_PFC_AND_169_HAND_CLASS_ONLY"
    result = validate_contract(mutated, previous, base, reference, sensitivity, zero)
    assert result["status"] == "FAIL"
    assert any("candidate policy" in error for error in result["errors"])

    mutated = copy.deepcopy(contract)
    required = mutated["run_manifest_requirements"]["required_before_any_promotion_eligible_rollout"]
    required.remove("candidate_binding_sha256")
    result = validate_contract(mutated, previous, base, reference, sensitivity, zero)
    assert result["status"] == "FAIL"
    assert any("binding SHA/schema" in error for error in result["errors"])


def test_pfpc_replacement_requires_persisted_zero_exposure_predecessor() -> None:
    contract, previous, base, reference, sensitivity, zero = inputs()
    mutated_zero = copy.deepcopy(zero)
    first = next(iter(mutated_zero["completed_environments"].values()))
    first["supported_decisions"] = 1
    result = validate_contract(contract, previous, base, reference, sensitivity, mutated_zero)
    assert result["status"] == "FAIL"
    assert any("exposure is not zero" in error for error in result["errors"])


def main() -> None:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"PFPC benchmark contract tests: {len(tests)} passed")


if __name__ == "__main__":
    main()

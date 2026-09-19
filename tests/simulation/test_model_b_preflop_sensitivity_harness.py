#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.simulation.model_b_preflop_sensitivity_harness import (
    SOURCE_KIND,
    load_json,
    project_canonical_decision,
    run_harness,
    validate_request,
    verify_issue_340_identity,
)

DECISION = ROOT / "tests/fixtures/iso-sizing-diagnostics/canonical_decision.json"
CONTEXT = ROOT / "tests/fixtures/model_b_preflop_sensitivity/synthetic_sb_two_limpers_context.json"
RUN340 = ROOT / "training/runs/20260919_model_b_preflop_response_to_price_2a"
CANDIDATE = RUN340 / "model/candidate.json"
REFERENCE = RUN340 / "model/price_agnostic_reference.json"
SUMMARY = RUN340 / "SUMMARY.json"
RESULT = RUN340 / "RESULT.json"
PROVENANCE = RUN340 / "RUN_PROVENANCE.json"


def inputs():
    return {
        "candidate_doc": load_json(CANDIDATE),
        "reference_doc": load_json(REFERENCE),
        "summary": load_json(SUMMARY),
        "result": load_json(RESULT),
        "provenance": load_json(PROVENANCE),
    }


def main():
    decision = load_json(DECISION)
    context = load_json(CONTEXT)
    request = project_canonical_decision(decision, context=context)

    assert request["schema"] == "model-b-preflop-sensitivity-harness-request/v1"
    assert request["source_kind"] == SOURCE_KIND
    assert request["decision_ref"]["canonical_schema"] == "poker-preflop-decision/v1"
    assert [x["alternative_id"] for x in request["alternatives"]] == [
        "FOLD", "OVERLIMP@1", "ISO@4", "ISO@5", "ISO@6"
    ]
    encoded = json.dumps(request, sort_keys=True)
    for forbidden in ("ev_bb", "uncertainty", "confidence", "selected_id"):
        assert forbidden not in encoded, forbidden

    docs = inputs()
    identity = verify_issue_340_identity(**docs)
    assert identity["candidate_artifact_sha256"] == "87736a611a0000a8bc30b142a3c1db0ac2086368c6fa18441cdc211bd17f3a06"
    assert identity["reference_artifact_sha256"] == "31e3e6401e30fd2e82926e2abefb904080dcab325430f0153702e5392a2f9915"
    assert identity["validation_data_consumed_by_this_harness"] is False
    assert identity["test_consumed_by_this_harness"] is False

    a = run_harness(request, **docs)
    b = run_harness(copy.deepcopy(request), **docs)
    assert a == b, "harness must be deterministic"
    assert a["status"] == "SYNTHETIC_HARNESS_ONLY"
    assert a["scope"] == {
        "real_issue_314_consumed": False,
        "hero_ev_consumed": False,
        "model_a_consumed": False,
        "recommendation_consumed": False,
        "train_consumed": False,
        "validation_consumed": False,
        "test_consumed": False,
        "active_model_b_changed": False,
        "automatic_promotion": False,
        "production_effect": "NONE",
        "ui_modified": False,
    }

    candidate = {x["alternative_id"]: x for x in a["candidate"]["alternatives"]}
    reference = {x["alternative_id"]: x for x in a["reference_control"]["alternatives"]}
    assert candidate["FOLD"]["status"] == "NOT_APPLICABLE"
    assert candidate["OVERLIMP@1"]["status"] == "NOT_APPLICABLE"
    for alternative_id, target in (("ISO@4", 4.0), ("ISO@5", 5.0), ("ISO@6", 6.0)):
        row = candidate[alternative_id]
        assert row["status"] == "AVAILABLE", row
        assert row["target_total_bb"] == target
        assert row["support"]["nearest_price_substitution"] is False
        assert row["support"]["family_never_dropped"] is True
        assert row["support"]["non_identifiability"] in {
            "EXACT_IDENTIFIABLE", "DECLARED_BACKOFF_OR_BINNED_SUPPORT"
        }
        assert len(row["responder_probabilities"]) == 3
        assert 0 <= row["aggregate"]["p_all_fold"] <= 1
        assert row["aggregate"]["expected_continuers"] >= 0
        assert 0 <= row["aggregate"]["p_3bet_or_jam"] <= 1
        partition = row["aggregate"]["caller_partition_with_aggressive_terminal"]
        assert math.isclose(sum(partition.values()), 1.0, rel_tol=0, abs_tol=1e-9)
        for responder in row["responder_probabilities"]:
            probs = responder["conditional_action_probabilities"]
            if responder["reach_probability"] > 0:
                assert math.isclose(sum(probs.values()), 1.0, rel_tol=0, abs_tol=1e-9)

    assert len(a["candidate"]["pairwise_sizing_deltas"]) == 3
    assert len(a["reference_control"]["pairwise_sizing_deltas"]) == 3
    assert all(x["status"] == "AVAILABLE" for x in a["candidate"]["pairwise_sizing_deltas"])
    # The frozen #340 reference is explicitly price-agnostic. With the same
    # public responder sequence its sizing deltas must remain numerically zero.
    for delta in a["reference_control"]["pairwise_sizing_deltas"]:
        assert delta["status"] == "AVAILABLE"
        for value in delta["high_minus_low"]["aggregate"].values():
            assert abs(value) < 1e-12, delta

    # Candidate should expose at least one actual response-to-price sensitivity.
    candidate_changes = [
        abs(value)
        for delta in a["candidate"]["pairwise_sizing_deltas"]
        for value in delta["high_minus_low"]["aggregate"].values()
    ]
    assert max(candidate_changes) > 1e-6

    bad = copy.deepcopy(request)
    bad["public_context"]["hero_ev"] = 1.0
    try:
        validate_request(bad)
    except ValueError as exc:
        assert "forbidden" in str(exc).lower()
    else:
        raise AssertionError("Hero EV injection must fail closed")

    bad = copy.deepcopy(request)
    next(x for x in bad["alternatives"] if x["alternative_id"] == "ISO@5")["incremental_cost_bb"] = 4.0
    try:
        validate_request(bad)
    except ValueError as exc:
        assert "exact target sizing" in str(exc)
    else:
        raise AssertionError("incompatible exact sizing must fail closed")

    bad = copy.deepcopy(request)
    bad["public_context"].pop("responders")
    try:
        validate_request(bad)
    except ValueError as exc:
        assert "missing public sensitivity context" in str(exc)
    else:
        raise AssertionError("missing public context must fail closed")

    tampered = copy.deepcopy(docs["candidate_doc"])
    tampered["alpha_per_action"] = 2.0
    try:
        verify_issue_340_identity(
            candidate_doc=tampered,
            reference_doc=docs["reference_doc"],
            summary=docs["summary"],
            result=docs["result"],
            provenance=docs["provenance"],
        )
    except ValueError as exc:
        assert "hash mismatch" in str(exc)
    else:
        raise AssertionError("tampered #340 candidate must fail closed")

    print("Issue #344 synthetic Model B sensitivity harness: PASS")


if __name__ == "__main__":
    main()

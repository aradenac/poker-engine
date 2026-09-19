#!/usr/bin/env python3
from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.simulation.model_b_preflop_response_to_price import (
    ACTIONS,
    EmpiricalPreflopResponseToPriceModel,
    build_train_artifact,
)
from tools.training.evaluate_preflop_response_to_price_2a import paired_validation, validate_protocol


BINS = {
    "VS_ISO": {
        "target_total_bb": [
            {"bin_id": "B1", "min_observed": 4.0, "max_observed": 4.0, "observations": 40},
            {"bin_id": "B2", "min_observed": 6.0, "max_observed": 6.0, "observations": 40},
        ],
        "price_to_pot": [
            {"bin_id": "B1", "min_observed": 0.2, "max_observed": 0.5, "observations": 40},
            {"bin_id": "B2", "min_observed": 0.5, "max_observed": 1.0, "observations": 40},
        ],
        "effective_stack_bb": [
            {"bin_id": "B1", "min_observed": 20.0, "max_observed": 100.0, "observations": 80},
        ],
    },
    "VS_RFI": {
        "target_total_bb": [{"bin_id": "B1", "min_observed": 2.5, "max_observed": 3.0, "observations": 30}],
        "price_to_pot": [{"bin_id": "B1", "min_observed": 0.2, "max_observed": 0.8, "observations": 30}],
        "effective_stack_bb": [{"bin_id": "B1", "min_observed": 20.0, "max_observed": 100.0, "observations": 30}],
    },
}


def row(hand, *, split="TRAIN", family="VS_ISO", target=4.0, price=0.4, action="CALL", profile=0):
    return {
        "source_split": split,
        "hand_id": str(hand),
        "profile": profile,
        "family": family,
        "responder_position": "CO",
        "raiser_position": "SB" if family == "VS_ISO" else "BTN",
        "sequence": "CO:LIMP>BTN:LIMP>SB:RAISE" if family == "VS_ISO" else "BTN:RAISE",
        "limper_count": 2 if family == "VS_ISO" else 0,
        "caller_count": 0,
        "target_total_bb": target,
        "facing_price_to_pot": price,
        "effective_stack_bb": 80.0,
        "action": action,
    }


def build_pair():
    train = []
    for i in range(30):
        train.append(row(1000 + i, target=4.0, price=0.4, action="CALL" if i < 24 else "FOLD"))
    for i in range(30):
        train.append(row(2000 + i, target=6.0, price=0.8, action="FOLD" if i < 24 else "CALL"))
    common = dict(
        bin_proposals=BINS,
        source_report_hash="fixture-319",
        min_observations=20,
        min_distinct_hands=15,
        alpha_per_action=1.0,
    )
    candidate = EmpiricalPreflopResponseToPriceModel(build_train_artifact(train, reference_mode=False, **common))
    reference = EmpiricalPreflopResponseToPriceModel(build_train_artifact(train, reference_mode=True, **common))
    return train, candidate, reference


def main():
    train, candidate, reference = build_pair()

    p4 = candidate.predict(**row("v4", split="VALIDATION", target=4.0, price=0.4))
    p6 = candidate.predict(**row("v6", split="VALIDATION", target=6.0, price=0.8))
    assert p4["probabilities"]["CALL"] > p6["probabilities"]["CALL"]
    assert p4["probabilities"]["FOLD"] < p6["probabilities"]["FOLD"]
    assert p4["support_state"] == "EXACT_SUPPORTED"
    assert p6["support_state"] == "EXACT_SUPPORTED"
    assert set(p4["probabilities"]) == set(ACTIONS)
    assert all("approx_95" in p4["uncertainty"][a] for a in ACTIONS)

    r4 = reference.predict(**row("r4", split="VALIDATION", target=4.0, price=0.4))
    r6 = reference.predict(**row("r6", split="VALIDATION", target=6.0, price=0.8))
    assert r4["probabilities"] == r6["probabilities"], "price-agnostic reference must ignore target/price"

    mixed = train + [
        row(3000 + i, family="VS_RFI", target=2.5, price=0.4, action="FOLD")
        for i in range(30)
    ]
    doc = build_train_artifact(
        mixed,
        bin_proposals=BINS,
        source_report_hash="fixture-319",
        min_observations=20,
        min_distinct_hands=15,
    )
    model = EmpiricalPreflopResponseToPriceModel(doc)
    pred = model.predict(**row("rv", split="VALIDATION", family="VS_RFI", target=2.5, price=0.4))
    assert pred["probabilities"]["FOLD"] > 0.85
    assert all("family" in level["dimensions"] for level in doc["levels"])
    assert doc["feature_contract"]["no_cross_family_pooling"] is True
    assert doc["feature_contract"]["nearest_context_heuristic"] is False

    bad = copy.deepcopy(train)
    bad[0]["source_split"] = "VALIDATION"
    try:
        build_train_artifact(bad, bin_proposals=BINS, source_report_hash="fixture-319")
    except ValueError as exc:
        assert "TRAIN" in str(exc)
    else:
        raise AssertionError("VALIDATION fit row must fail closed")

    bad_feature = copy.deepcopy(train[0])
    bad_feature["hero_ev"] = 12.0
    try:
        candidate.predict(**bad_feature)
    except ValueError as exc:
        assert "forbidden" in str(exc).lower()
    else:
        raise AssertionError("Hero EV must be rejected")

    validation = [
        row(4000 + i, split="VALIDATION", target=4.0, price=0.4, action="CALL")
        for i in range(20)
    ] + [
        row(5000 + i, split="VALIDATION", target=6.0, price=0.8, action="FOLD")
        for i in range(20)
    ]
    a = paired_validation(validation, candidate, reference, bootstrap_samples=100, seed=7)
    b = paired_validation(validation, candidate, reference, bootstrap_samples=100, seed=7)
    assert a[2] == b[2]
    assert a[0]["n"] == a[1]["n"] == 40
    assert a[2]["cluster_unit"] == "hand_id"
    assert a[3]

    protocol = {
        "schema": "model-b-preflop-response-to-price-2a-protocol/v1",
        "status": "FROZEN_BEFORE_VALIDATION",
        "source_issue_319": {"report_hash": "fixture-319"},
        "split_contract": {
            "fit": ["TRAIN"], "evaluate": ["VALIDATION"], "forbidden": ["TEST"], "test_consumed": False
        },
        "scientific_constraints": {
            "model_a_features_allowed": False,
            "hero_ev_or_recommendation_allowed": False,
            "automatic_promotion": False,
        },
    }
    support = {"full_report": {"report_hash": "fixture-319"}}
    validate_protocol(protocol, support)
    broken = copy.deepcopy(protocol)
    broken["split_contract"]["evaluate"] = ["TEST"]
    try:
        validate_protocol(broken, support)
    except ValueError:
        pass
    else:
        raise AssertionError("TEST protocol must fail closed")

    print("Issue #340 preflop Model B response-to-price 2A contracts: PASS")


if __name__ == "__main__":
    main()

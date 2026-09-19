#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training.audit_preflop_sizing_support import (
    SCHEMA,
    analyze_rows,
    empirical_bins,
    render_markdown,
    summary_report,
)


def row(
    hand,
    *,
    family="VS_LIMPERS",
    actor="SB",
    history=None,
    action="CALL",
    current_price=1.0,
    to_call=0.5,
    pot=3.5,
    effective=100.0,
    target=None,
    known=None,
):
    if history is None:
        history = [
            {"position": "CO", "action": "LIMP"},
            {"position": "BTN", "action": "LIMP"},
        ]
    return {
        "hand_id": str(hand),
        "split": "TRAIN",
        "street": "preflop",
        "is_hero": False,
        "actor_position": actor,
        "action": action,
        "family": family,
        "history": history,
        "pot_before_bb": pot,
        "to_call_bb": to_call,
        "current_price_bb": current_price,
        "known_hand_class": known,
        "preflop_context_v1": {
            "current_price_bb": current_price,
            "effective_stack_bb": effective,
        },
        "action_sizing_v1": {
            "incremental_cost_bb": 0 if action == "FOLD" else to_call,
            "target_total_bb": target,
        },
    }


def main():
    rows = [
        row(1, action="RAISE", target=4.0, known="KTs"),
        row(2, action="RAISE", target=4.0),
        row(3, action="LIMP"),
        row(4, action="FOLD"),
        row(
            5,
            family="LIMPER_VS_ISO",
            actor="CO",
            history=[
                {"position": "CO", "action": "LIMP"},
                {"position": "BTN", "action": "LIMP"},
                {"position": "SB", "action": "RAISE"},
            ],
            action="CALL",
            current_price=4.0,
            to_call=3.0,
            pot=7.0,
            known="AJo",
        ),
        row(
            6,
            family="LIMPER_VS_ISO",
            actor="BTN",
            history=[
                {"position": "CO", "action": "LIMP"},
                {"position": "BTN", "action": "LIMP"},
                {"position": "SB", "action": "RAISE"},
                {"position": "CO", "action": "CALL"},
            ],
            action="FOLD",
            current_price=4.0,
            to_call=3.0,
            pot=10.0,
        ),
        row(
            7,
            family="VS_ISO",
            actor="BB",
            history=[
                {"position": "CO", "action": "LIMP"},
                {"position": "BTN", "action": "LIMP"},
                {"position": "SB", "action": "RAISE"},
            ],
            action="JAM",
            current_price=6.0,
            to_call=5.0,
            pot=9.0,
            target=100.0,
        ),
        row(
            8,
            family="VS_RFI",
            actor="BB",
            history=[{"position": "BTN", "action": "RAISE"}],
            action="CALL",
            current_price=2.5,
            to_call=1.5,
            pot=4.0,
        ),
    ]

    a = analyze_rows(rows, provenance={"fixture": "synthetic"})
    b = analyze_rows(list(reversed(copy.deepcopy(rows))), provenance={"fixture": "synthetic"})
    assert a == b
    assert a["schema"] == SCHEMA
    assert a["scope"]["split_consumed"] == "TRAIN"
    assert a["scope"]["validation_consumed"] is False
    assert a["scope"]["test_consumed"] is False
    assert a["scope"]["issue_108_consumed"] is False
    assert a["scope"]["active_model_consumed"] is False
    assert a["scope"]["active_model_modified"] is False
    assert a["scope"]["ui_modified"] is False
    assert a["semantics"]["sizing_reconstructed_from_fixed_grid"] is False
    assert a["semantics"]["consumable_by"] == ["#313", "#315"]
    assert a["backoff_contract"]["no_silent_nearest_price"] is True
    assert a["backoff_contract"]["absence_of_exact_cell_means"] == "NO_SUPPORT"
    assert a["semantics"]["limp_response_mapping"]
    assert a["semantics"]["iso_event_mapping"]
    assert a["binned_support"]

    cell = next(
        x for x in a["matrix"]
        if x["family"] == "VS_LIMPERS"
        and x["actor_position"] == "SB"
        and x["target_total_bb"] == 1.0
    )
    assert cell["actions"]["denominator"] == 4
    assert cell["actions"]["counts"] == {"FOLD": 1, "CALL": 1, "RAISE": 2, "JAM": 0}
    assert cell["reveal"]["revealed_decisions"] == 1
    assert cell["reveal"]["unrevealed_decisions"] == 3
    assert cell["reveal"]["non_revealed_fraction"] == 0.75
    assert cell["observed_raise_or_jam_targets"] == [{"target_total_bb": 4.0, "observations": 2}]

    revealed = [x for x in a["revealed_hand_class_support"] if x["hand_class"] == "KTs"]
    assert len(revealed) == 1
    assert revealed[0]["revealed_observations"] == 1

    projection = a["kts_sb_two_limpers_projection"]
    assert projection["scenario"]["public_context_only"] is True
    assert projection["scenario"]["opponent_hidden_cards_consumed"] is False
    assert projection["scenario"]["hero_hand_used_to_filter_opponent_rows"] is False
    requested = {x["target_total_bb"]: x for x in projection["requested_4_5_6bb_exact_support"]}
    assert requested[4.0]["state"] == "EXACT_SUPPORT"
    assert requested[5.0]["state"] == "NO_EXACT_SUPPORT"
    assert requested[6.0]["state"] == "EXACT_SUPPORT"

    bins = empirical_bins([2, 2, 2.5, 3, 4, 6, 6, 10])
    observed = {2.0, 2.5, 3.0, 4.0, 6.0, 10.0}
    assert bins
    assert all(x["min_observed"] in observed and x["max_observed"] in observed for x in bins)

    summary = summary_report(a)
    assert summary["schema"] == "poker-preflop-sizing-support-audit-summary/v1"
    assert summary["full_report"]["report_hash"] == a["report_hash"]
    assert summary["top_binned_support"]
    md = render_markdown(a)
    assert "No fixed sizing grid" in md
    assert "KTs SB + two limpers" in md

    bad = copy.deepcopy(rows)
    bad[0]["split"] = "TEST"
    try:
        analyze_rows(bad)
    except AssertionError as exc:
        assert "non-TRAIN" in str(exc)
    else:
        raise AssertionError("TEST row must fail closed")

    bad = copy.deepcopy(rows)
    bad[0]["is_hero"] = True
    try:
        analyze_rows(bad)
    except AssertionError as exc:
        assert "Hero row" in str(exc)
    else:
        raise AssertionError("Hero population row must fail closed")

    encoded = json.dumps(a, sort_keys=True)
    assert '"test_consumed": false' in encoded
    print("Certified TRAIN preflop sizing/price support audit contract: PASS")


if __name__ == "__main__":
    main()

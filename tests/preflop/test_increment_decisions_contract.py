#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.preflop.context_contract import v5_runtime_signature  # noqa: E402
from tools.training.audit_preflop_key_runtime_parity import runtime_signature  # noqa: E402
from tools.training.increment_decisions import decision_rows, parse_hand  # noqa: E402

HH = """PokerStars Zoom Hand #900000000000000001: Hold'em No Limit (100/200) - 2026/09/15 07:00:00 CET
Table 'ContractFixture' 6-max Seat #6 is the button
Seat 1: sb (20000 in chips)
Seat 2: bb (20000 in chips)
Seat 3: hero (20000 in chips)
Seat 4: iso (20000 in chips)
Seat 5: cutoff (20000 in chips)
Seat 6: button (20000 in chips)
sb: posts small blind 100
bb: posts big blind 200
*** HOLE CARDS ***
Dealt to hero [As Kd]
hero: calls 200
iso: raises 600 to 800
cutoff: folds
button: calls 800
sb: folds
bb: folds
hero: calls 600
*** FLOP *** [2c 7d Jh]
hero: checks
iso: checks
button: checks
*** SUMMARY ***
Total pot 2600 | Rake 0
"""


def preflop_rows():
    hand = parse_hand(HH, "contract-fixture.txt")
    assert hand is not None
    return [r for r in decision_rows(hand, include_preflop_context_v1=True) if r["street"] == "preflop"]


def test_every_preflop_row_has_before_action_contract():
    rows = preflop_rows()
    assert [r["action"] for r in rows] == ["LIMP", "RAISE", "FOLD", "CALL", "FOLD", "FOLD", "CALL"]
    for row in rows:
        ctx = row["preflop_context_v1"]
        assert ctx["state_timing"] == "BEFORE_ACTION"
        assert row["actor_position"] == ctx["actor_position"]
        assert row["table_size"] == ctx["table_size"]
        assert row["raise_level"] == ctx["raise_level"]
        assert row["family"] == ctx["family"]
        assert row["live_positions"] == ctx["live_positions"]
        assert row["all_in_positions"] == ctx["all_in_positions"]
        assert row["history"] == ctx["history"]
        assert row["to_call_bb"] == ctx["to_call_bb"]
        assert row["current_price_bb"] == ctx["current_price_bb"]
        assert v5_runtime_signature(ctx) == runtime_signature(row)
        # Structural decision state must never acquire showdown/known cards.
        text = json.dumps(ctx).lower()
        assert "card" not in text and "showdown" not in text and "future" not in text


def test_raise_amount_is_incremental_and_target_total_is_explicit():
    rows = preflop_rows()
    iso = next(r for r in rows if r["player"] == "iso")
    assert iso["action"] == "RAISE"
    assert iso["action_sizing_v1"] == {"incremental_cost_bb": 4.0, "target_total_bb": 4.0}
    assert iso["preflop_context_v1"]["current_price_bb"] == 1.0
    assert iso["preflop_context_v1"]["to_call_bb"] == 1.0
    assert iso["preflop_context_v1"]["min_raise_to_bb"] == 2.0


def test_limper_second_decision_sees_only_prior_actions():
    rows = preflop_rows()
    hero_rows = [r for r in rows if r["player"] == "hero"]
    assert len(hero_rows) == 2
    first, second = hero_rows
    assert first["history"] == []
    assert first["family"] == "UNOPENED"
    # CO/SB/BB folds are deliberately not structural history; the later BTN
    # call is visible because it happened before Hero's second decision.
    assert second["history"] == [
        {"position": "LJ", "action": "LIMP"},
        {"position": "HJ", "action": "RAISE"},
        {"position": "BTN", "action": "CALL"},
    ]
    assert second["family"] == "LIMPER_VS_ISO_CALLERS"
    assert second["preflop_context_v1"]["remaining_to_act_positions"] == []


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
    print(f"increment decision preflop contract tests: {len(tests)} passed")


def test_default_extractor_stays_legacy_for_closed_runs():
    hand = parse_hand(HH, "contract-fixture.txt")
    assert hand is not None
    rows = [r for r in decision_rows(hand) if r["street"] == "preflop"]
    assert rows
    assert all("preflop_context_v1" not in r for r in rows)
    assert all("action_sizing_v1" not in r for r in rows)

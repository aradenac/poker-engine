#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training.evaluate_preflop_policy169_candidate import evaluate  # noqa: E402
from tools.training.preflop_policy169 import encode_policy169  # noqa: E402

ACTIONS = ["FOLD", "RAISE"]
GRID = ["AA", "72o"]
META = {"AA": {"combo_weight": 3}, "72o": {"combo_weight": 1}}
CONTEXT = {
    "table_size": 6,
    "actor_position": "CO",
    "family": "UNOPENED",
    "raise_level": 0,
    "free_check": False,
    "live_positions": ["LJ", "HJ", "CO", "BTN", "SB", "BB"],
    "all_in_positions": [],
    "history": [],
}


def model(policy: dict) -> dict:
    q = encode_policy169(
        policy,
        actions=ACTIONS,
        hand_grid=GRID,
        template={"hand_order": GRID, "method": "fixture_embedded"},
    )
    return {
        "hand_grid": {"classes": GRID, "meta": META},
        "nodes": [{
            "id": "PF4_fixture",
            "canonical_key": "fixture",
            "context": CONTEXT,
            "coverage": {"population_decisions": 100},
            "population_model": {
                "legal_actions": ACTIONS,
                "frequencies": {"FOLD": 0.5, "RAISE": 0.5},
                "policy169_q_b64": q,
            },
        }],
    }


def rows(split: str) -> list[dict]:
    out = []
    # Every hand contributes three premium raises and one weak-hand fold, so
    # candidate-minus-prior loss is negative in every bootstrap cluster.
    for hand_no in range(4):
        hid = f"{split}-{hand_no}"
        for _ in range(3):
            out.append({**CONTEXT, "hand_id": hid, "split": split, "street": "preflop", "is_hero": False, "action": "RAISE", "known_hand_class": "AA"})
        out.append({**CONTEXT, "hand_id": hid, "split": split, "street": "preflop", "is_hero": False, "action": "FOLD", "known_hand_class": "72o"})
    return out


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(root: Path):
    prior = root / "prior.json"
    candidate = root / "candidate.json"
    decisions = root / "decisions.jsonl"
    protocol = root / "protocol.json"
    prior.write_text(json.dumps(model({"AA": {"FOLD": 0.5, "RAISE": 0.5}, "72o": {"FOLD": 0.5, "RAISE": 0.5}})), encoding="utf-8")
    candidate.write_text(json.dumps(model({"AA": {"FOLD": 0.05, "RAISE": 0.95}, "72o": {"FOLD": 0.95, "RAISE": 0.05}})), encoding="utf-8")
    all_rows = rows("VALIDATION") + rows("TEST") + [{**CONTEXT, "hand_id": "hero", "split": "VALIDATION", "street": "preflop", "is_hero": True, "action": "RAISE", "known_hand_class": "AA"}]
    decisions.write_text("".join(json.dumps(row) + "\n" for row in all_rows), encoding="utf-8")
    protocol.write_text(json.dumps({
        "schema": "poker-preflop-policy169-experiment/v1",
        "status": "FROZEN_BEFORE_EXPERIMENT",
        "evaluation": {
            "bootstrap_samples": 200,
            "bootstrap_seed": 17,
            "required_hand_conditioned": {"minimum_validation_rows": 8, "minimum_validation_hands": 4},
        },
    }), encoding="utf-8")
    return prior, candidate, decisions, protocol


def args(root: Path, phase: str, validation: Path | None = None):
    prior, candidate, decisions, protocol = fixture(root)
    return argparse.Namespace(
        phase=phase,
        protocol=protocol,
        prior=prior,
        candidate=candidate,
        decisions=decisions,
        out=root / f"{phase}.json",
        validation_selection=validation,
    )


def test_validation_dual_gate_authorizes_exact_candidate():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        a = args(root, "validation")
        result = evaluate(a)
        assert result["phase"] == "VALIDATION"
        assert result["test_used"] is False
        assert result["test_authorized"] is True
        assert result["outcome"] == "VALIDATION_FINALIST"
        assert result["gate"]["support_ok"] is True
        assert result["gate"]["affected_support_ok"] is True
        assert result["metrics"]["all_rows"]["rows"] == 16
        assert result["metrics"]["revealed_hand_rows"]["rows"] == 16
        assert result["metrics"]["all_rows"]["candidate_policy169_rows"] == 16
        assert result["metrics"]["all_rows"]["paired_bootstrap"]["ci95"][1] < 0
        assert result["metrics"]["revealed_hand_rows"]["paired_bootstrap"]["ci95"][1] < 0


def test_test_requires_authorized_validation_and_same_candidate_sha():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        va = args(root, "validation")
        validation = evaluate(va)
        selection = root / "selection.json"
        selection.write_text(json.dumps(validation), encoding="utf-8")

        ta = args(root, "test", selection)
        test_result = evaluate(ta)
        assert test_result["phase"] == "TEST"
        assert test_result["test_used"] is True
        assert test_result["test_used_for_selection"] is False
        assert test_result["outcome"] == "FINALIST_CONFIRMED"

        bad = json.loads(selection.read_text(encoding="utf-8"))
        bad["inputs"]["candidate"]["sha256"] = "0" * 64
        selection.write_text(json.dumps(bad), encoding="utf-8")
        ta.validation_selection = selection
        try:
            evaluate(ta)
        except SystemExit as exc:
            assert "candidate changed" in str(exc)
        else:
            raise AssertionError("TEST must reject a candidate not pinned by VALIDATION")


def test_test_remains_locked_after_validation_rejection():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        a = args(root, "test")
        selection = root / "rejected.json"
        selection.write_text(json.dumps({
            "phase": "VALIDATION",
            "test_authorized": False,
            "inputs": {"candidate": {"sha256": sha256(a.candidate)}},
        }), encoding="utf-8")
        a.validation_selection = selection
        try:
            evaluate(a)
        except SystemExit as exc:
            assert "not authorized" in str(exc)
        else:
            raise AssertionError("TEST must remain locked after rejected VALIDATION")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
    print(f"preflop policy169 evaluator tests: {len(tests)} passed")

#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training.preflop_policy169 import (  # noqa: E402
    DEFAULT_SCALE,
    decode_policy169,
    encode_policy169,
    policy_probability,
)
from tools.training.rebuild_preflop_increment_candidate import rebuild  # noqa: E402

ACTIONS = ["FOLD", "CALL", "RAISE"]
GRID = ["AA", "AKs", "72o"]
META = {
    "AA": {"combo_weight": 6},
    "AKs": {"combo_weight": 4},
    "72o": {"combo_weight": 12},
}
BASE_POLICY = {
    "AA": {"FOLD": 0.02, "CALL": 0.18, "RAISE": 0.80},
    "AKs": {"FOLD": 0.08, "CALL": 0.42, "RAISE": 0.50},
    "72o": {"FOLD": 0.84, "CALL": 0.14, "RAISE": 0.02},
}


def baseline_doc() -> dict:
    return {
        "schema_version": "4.0.0",
        "model_type": "preflop_population",
        "model_version": "fixture_v5",
        "training": {"selected_hierarchy_alphas": [20, 300, 80, 40]},
        "hand_grid": {"classes": GRID, "meta": META},
        "nodes": [
            {
                "id": "PF4_fixture",
                "canonical_key": "fixture-context",
                "policy169_q_b64": encode_policy169(BASE_POLICY, actions=ACTIONS, hand_grid=GRID),
                "policy169_q_meta": {
                    "actions": ACTIONS,
                    "hand_grid": GRID,
                    "scale": DEFAULT_SCALE,
                    "encoding": "uint16_le_base64",
                },
                "population_observed": {
                    "n": 100,
                    "actions": {
                        "FOLD": {"count": 45, "frequency": 0.45},
                        "CALL": {"count": 35, "frequency": 0.35},
                        "RAISE": {"count": 20, "frequency": 0.20},
                    },
                },
                "population_model": {
                    "legal_actions": ACTIONS,
                    "frequencies": {"FOLD": 0.45, "CALL": 0.35, "RAISE": 0.20},
                    "method": "hierarchical_train_only_v4",
                },
                "coverage": {"population_decisions": 100},
            }
        ],
        "coverage": {"core90_nodes": 1, "core95_nodes": 1, "core99_nodes": 1},
        "response_models": {},
        "revealed_policy_models": {},
    }


def overlay_doc() -> dict:
    return {
        "schema": "poker-population-increment-overlay/v1",
        "preflop_nodes": [
            {
                "id": "PF4_fixture",
                "canonical_key": "fixture-context",
                "n_delta": 20,
                "actions": {"FOLD": 8, "CALL": 4, "RAISE": 8},
                # Only actually revealed hands. Twelve other rows remain hidden.
                "known_by_action": {
                    "RAISE": {"AA": 6},
                    "CALL": {"AKs": 2},
                },
            }
        ],
    }


def write_fixture(root: Path) -> tuple[Path, Path, Path]:
    baseline = root / "baseline.json"
    overlay = root / "overlay.json"
    decisions = root / "decisions.jsonl"
    baseline.write_text(json.dumps(baseline_doc()), encoding="utf-8")
    overlay.write_text(json.dumps(overlay_doc()), encoding="utf-8")
    rows = [
        {"hand_id": "train-1", "split": "TRAIN"},
        {"hand_id": "validation-1", "split": "VALIDATION"},
        {"hand_id": "test-1", "split": "TEST"},
    ]
    decisions.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return baseline, overlay, decisions


def run_rebuild(root: Path, weight: float, *, evidence_mode: str) -> dict:
    baseline, overlay, decisions = write_fixture(root)
    return rebuild(
        baseline=baseline,
        overlay_path=overlay,
        decisions=decisions,
        out=root / f"candidate-{evidence_mode}-{weight}.json",
        date="2026-09-15",
        source_label="controlled-fixture",
        lineage_fingerprint="fixture-lineage",
        model_version=f"fixture-policy169-{evidence_mode}-{weight}",
        policy169_update_weight=weight,
        policy169_prior_strength=40,
        evidence_mode=evidence_mode,
        action_prior_strength=40,
    )


def test_historical_incremental_zero_weight_preserves_contract():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        before = baseline_doc()["nodes"][0]["policy169_q_b64"]
        candidate = run_rebuild(root, 0.0, evidence_mode="incremental")
        node = candidate["nodes"][0]
        meta = candidate["incremental_update"]
        assert node["policy169_q_b64"] == before
        assert meta["version"] == "1.0.0"
        assert meta["policy169"] == "FROZEN from v5"
        assert "policy169_update_weight" not in meta
        assert node["population_observed"]["n"] == 120
        assert node["population_observed"]["actions"]["RAISE"]["count"] == 28


def test_historical_incremental_rejects_policy_refit():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        try:
            run_rebuild(root, 1.0, evidence_mode="incremental")
        except ValueError as exc:
            assert "replace_population" in str(exc)
        else:
            raise AssertionError("historical incremental mode must reject policy169 refit")


def test_target_positive_weight_changes_runtime_consumed_policy():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        base = baseline_doc()
        before_node = base["nodes"][0]
        before_blob = before_node["policy169_q_b64"]
        before_aa_raise = policy_probability(before_node, "AA", "RAISE", GRID)

        candidate = run_rebuild(root, 1.0, evidence_mode="replace_population")
        node = candidate["nodes"][0]
        meta = candidate["incremental_update"]
        after_aa_raise = policy_probability(node, "AA", "RAISE", GRID)
        decoded = decode_policy169(node, GRID)

        assert node["policy169_q_b64"] != before_blob
        assert abs(after_aa_raise - before_aa_raise) > 1e-5
        assert node["population_observed"]["n"] == 20
        assert node["population_observed"]["actions"]["RAISE"]["count"] == 8
        assert meta["evidence_mode"] == "replace_population"
        assert meta["population_scope"].startswith("certified target TRAIN only")
        assert meta["policy169_nodes_seen"] == 1
        assert meta["policy169_nodes_refit"] == 1
        assert meta["policy169_nodes_changed"] == 1
        assert meta["policy169_train_revealed_rows"] == 8
        assert meta["policy169_hidden_hands_imputed"] == 0
        assert meta["policy169_update_weight"] == 1.0
        assert candidate["incremental_update"]["test_hands"] == 1
        for hand in GRID:
            assert abs(sum(decoded[hand].values()) - 1.0) < 1e-9


def test_target_zero_weight_is_marginal_only_control():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        before = baseline_doc()["nodes"][0]["policy169_q_b64"]
        candidate = run_rebuild(root, 0.0, evidence_mode="replace_population")
        node = candidate["nodes"][0]
        meta = candidate["incremental_update"]
        assert node["policy169_q_b64"] == before
        assert node["population_observed"]["n"] == 20
        assert meta["policy169_nodes_seen"] == 1
        assert meta["policy169_nodes_refit"] == 1
        assert meta["policy169_nodes_changed"] == 0
        assert meta["policy169_hidden_hands_imputed"] == 0
        assert meta["policy169_update_weight"] == 0.0


def test_invalid_weight_fails_closed():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        baseline, overlay, decisions = write_fixture(root)
        try:
            rebuild(
                baseline=baseline,
                overlay_path=overlay,
                decisions=decisions,
                out=root / "bad.json",
                date="2026-09-15",
                source_label="controlled-fixture",
                lineage_fingerprint="fixture-lineage",
                policy169_update_weight=1.1,
                evidence_mode="replace_population",
            )
        except ValueError as exc:
            assert "[0, 1]" in str(exc)
        else:
            raise AssertionError("invalid policy169 update weight must fail closed")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
    print(f"preflop policy169 rebuild tests: {len(tests)} passed")

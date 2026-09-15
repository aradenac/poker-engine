import importlib.util
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "refit_postflop_response_models", ROOT / "tools/training/refit_postflop_response_models.py"
)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(mod)


def baseline_model():
    spec = {
        "classes": ["FOLD", "CALL"],
        "features": ["log_facing_price", "log_spr"],
        "global_mean": [0.0, 0.0],
        "global_std": [1.0, 1.0],
        "numeric_coef": [[0.0, 0.0], [0.0, 0.0]],
        "application_scale": 1.0,
        "max_logit_adjustment": 2.0,
    }
    node = {
        "canonical_key": "flop|2|2|OOP|SRP|CALLER|BET",
        "population_model": {
            "frequencies": {"FOLD": 0.5, "CALL": 0.5},
            "legal_actions": ["FOLD", "CALL"],
            "response_model_key": "flop_FACING",
            "numeric_feature_center": [0.0, 0.0],
        },
    }
    return {
        "model_type": "postflop_population",
        "nodes": [node],
        "response_models": {"flop_FACING": spec},
        "combo_policy_models": {"flop_FACING": {"sentinel": "must-stay-frozen"}},
        "hand_policy_prior": {"sentinel": "must-stay-frozen"},
    }


def row(i, split, action, facing, *, known=False):
    return {
        "hand_id": str(i),
        "split": split,
        "street": "flop",
        "is_hero": False,
        "action": action,
        "canonical_key": "flop|2|2|OOP|SRP|CALLER|BET",
        "facing_price_pot": facing,
        "spr": 3.0,
        "pot_before_bb": 8.0,
        "board_features": {},
        "known_cards": ["As", "Kd"] if known else None,
    }


def test_feature_mapping_matches_runtime_clipping_and_hinges():
    r = row(1, "TRAIN", "FOLD", 99.0)
    assert math.isclose(mod.feature_value(r, "log_facing_price"), math.log1p(5.0))
    assert math.isclose(mod.feature_value(r, "size_h100"), math.log1p(5.0) - math.log1p(1.0))
    r["spr"] = 999
    assert math.isclose(mod.feature_value(r, "log_spr"), math.log1p(50.0))


def test_refit_changes_runtime_prediction_but_keeps_other_model_families_frozen():
    model = baseline_model()
    rows = []
    # Strong, deterministic price signal: expensive calls fold, cheap calls continue.
    for i in range(60):
        rows.append(row(i, "TRAIN", "CALL", 0.15, known=(i % 5 == 0)))
        rows.append(row(100 + i, "TRAIN", "FOLD", 2.0, known=(i % 7 == 0)))
    for i in range(20):
        rows.append(row(300 + i, "VALIDATION", "CALL", 0.15))
        rows.append(row(400 + i, "VALIDATION", "FOLD", 2.0))

    candidate, info = mod.refit(model, rows, epochs=80, learning_rate=0.3, l2_to_parent=0.02)
    assert info["response_models_changed"] == 1
    assert candidate["combo_policy_models"] == model["combo_policy_models"]
    assert candidate["hand_policy_prior"] == model["hand_policy_prior"]
    assert candidate["response_refit"]["test_consumed"] is False
    assert candidate["response_refit"]["production_effect"] == "NONE"

    node = model["nodes"][0]
    cheap = row(999, "VALIDATION", "CALL", 0.15)
    expensive = row(1000, "VALIDATION", "FOLD", 2.0)
    before_cheap = mod.runtime_prediction(node, model["response_models"]["flop_FACING"], cheap)
    after_cheap = mod.runtime_prediction(node, candidate["response_models"]["flop_FACING"], cheap)
    after_expensive = mod.runtime_prediction(node, candidate["response_models"]["flop_FACING"], expensive)
    assert after_cheap["CALL"] > before_cheap["CALL"]
    assert after_expensive["FOLD"] > after_cheap["FOLD"]


def test_split_and_support_contract_is_fail_closed_and_auditable():
    model = baseline_model()
    rows = [
        row(1, "TRAIN", "CALL", 0.2),
        row(2, "TEST", "FOLD", 2.0),
        row(3, "TRAIN", "FOLD", 8.0),
        {**row(4, "TRAIN", "CALL", 0.2), "canonical_key": "unseen"},
    ]
    grouped, counts = mod.classify_rows(model, rows, "TRAIN")
    assert len(grouped["flop_FACING"]) == 2
    assert counts["population_postflop_rows"] == 3
    assert counts["no_exact_node"] == 1
    assert counts["facing_price_clipped_by_runtime"] == 1
    # TEST is never admitted to the TRAIN refit path.
    assert all(obs["split"] == "TRAIN" for obs, _ in grouped["flop_FACING"])


def test_validation_comparison_uses_identical_holdout_rows():
    model = baseline_model()
    rows = [row(i, "VALIDATION", "CALL" if i % 2 else "FOLD", 0.5) for i in range(20)]
    candidate = baseline_model()
    b, bh = mod.evaluate(model, rows, "VALIDATION")
    c, ch = mod.evaluate(candidate, rows, "VALIDATION")
    assert b["rows"] == c["rows"] == 20
    assert b["log_loss"] == c["log_loss"]
    boot = mod.paired_bootstrap(bh, ch, seed=7, iterations=100)
    assert boot["hands"] == 20
    assert boot["mean_delta_candidate_minus_baseline"] == 0.0
    assert boot["ci95"] == [0.0, 0.0]

import importlib.util
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "model_a_postflop_runtime", ROOT / "tools/training/model_a_postflop_runtime.py"
)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def decision(action="CALL"):
    return {
        "canonical_key": "flop|2|2|OOP|SRP|CALLER|BET",
        "street": "flop",
        "mode": "FACING",
        "action": action,
        "board": ["2c", "7d", "Jh"],
        "board_features": {"flushiness": 1, "connectivity": 1},
        "active_players": 2,
        "preflop_role": "CALLER",
        "relative_position": "OOP",
        "pot_type": "SRP",
        "facing_price_pot": 0.75,
        "own_size_pot": None,
        "spr": 4.0,
    }


def model():
    return {
        "nodes": [{
            "canonical_key": "flop|2|2|OOP|SRP|CALLER|BET",
            "coverage": {"population_decisions": 100},
            "population_model": {
                "frequencies": {"FOLD": 0.40, "CALL": 0.60},
                "legal_actions": ["FOLD", "CALL"],
            },
        }],
        "hand_policy_prior": {},
        "combo_policy_models": {},
        "response_models": {},
    }


def test_hand_score_orders_standard_categories():
    high = mod.hand_score(["As", "Kd", "9c", "7h", "3s"])
    pair = mod.hand_score(["As", "Ad", "9c", "7h", "3s"])
    trips = mod.hand_score(["As", "Ad", "Ac", "7h", "3s"])
    flush = mod.hand_score(["As", "Js", "9s", "7s", "3s"])
    full = mod.hand_score(["As", "Ad", "Ac", "7h", "7s"])
    assert high < pair < trips < flush < full


def test_combo_features_detect_strength_draws_and_blockers():
    made = mod.combo_features([mod.cid("Ah"), mod.cid("Ad")], ["2c", "7d", "Jh"])
    draw = mod.combo_features([mod.cid("As"), mod.cid("Qs")], ["2s", "7s", "Jh"])
    assert made["strength"] > draw["strength"]
    assert draw["draw"] > 0
    assert draw["blocker"] > 0


def test_ipf_preserves_population_action_marginals():
    d = decision(); m = model()
    combos = [
        (mod.cid("Ah"), mod.cid("Ad")),
        (mod.cid("3h"), mod.cid("4d")),
        (mod.cid("Jd"), mod.cid("Tc")),
        (mod.cid("8h"), mod.cid("9h")),
    ]
    weights = [0.10, 0.25, 0.30, 0.35]
    actions, rows = mod.calibrated_action_matrix(combos, weights, d, {"FOLD": 0.4, "CALL": 0.6}, m)
    assert actions == ["FOLD", "CALL"]
    for row in rows:
        assert math.isclose(sum(row), 1.0, rel_tol=0, abs_tol=1e-9)
    total = sum(weights)
    marg = [sum(w * row[j] for w, row in zip(weights, rows)) / total for j in range(2)]
    assert math.isclose(marg[0], 0.4, rel_tol=0, abs_tol=2e-6)
    assert math.isclose(marg[1], 0.6, rel_tol=0, abs_tol=2e-6)


def test_facing_action_likelihood_orders_strong_combo_above_air_for_call():
    d = decision(); m = model()
    combos = [
        (mod.cid("Ah"), mod.cid("Ad")),
        (mod.cid("3h"), mod.cid("4d")),
    ]
    weights = [0.5, 0.5]
    probs = mod.observed_action_probabilities(combos, weights, d, m)
    assert probs[0] > probs[1]


def test_exact_postflop_context_is_required():
    d = decision(); m = model()
    assert mod.exact_postflop_node(m, d) is not None
    bad = dict(d); bad["canonical_key"] = "unseen"
    assert mod.exact_postflop_node(m, bad) is None

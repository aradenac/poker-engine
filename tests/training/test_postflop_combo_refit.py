import base64
import copy
import math
import struct

from tools.training import model_a_latent_ranges as latent
from tools.training import refit_postflop_combo_policy as combo
from tools.training import sample_postflop_stage_b_decisions as sample


def encoded_policy():
    hands = latent.matrix_notations()
    actions = ["FOLD", "CALL"]
    values = []
    for action in actions:
        for hand in hands:
            if hand == "AA":
                values.append(100 if action == "FOLD" else 900)
            else:
                values.append(500)
    raw = struct.pack("<" + "H" * len(values), *values)
    return {
        "hand_order": hands,
        "actions": actions,
        "shape": [2, len(hands)],
        "scale": 1000,
        "dtype": "uint16-le",
        "data": base64.b64encode(raw).decode("ascii"),
    }


def preflop_row(split="TRAIN"):
    return {
        "hand_id": "1",
        "split": split,
        "street": "preflop",
        "player": "Villain",
        "is_hero": False,
        "actor_position": "BB",
        "action": "CALL",
        "table_size": 2,
        "raise_level": 1,
        "family": "VS_OPEN",
        "live_positions": ["BTN", "BB"],
        "all_in_positions": [],
        "history": [{"position": "BTN", "action": "RAISE"}],
        "known_cards": None,
    }


def preflop_model():
    row = preflop_row()
    return {
        "hand_grid": {"classes": latent.matrix_notations()},
        "nodes": [{
            "id": "PF",
            "context": {
                "actor_position": row["actor_position"],
                "table_size": row["table_size"],
                "raise_level": row["raise_level"],
                "family": row["family"],
                "live_positions": row["live_positions"],
                "all_in_positions": row["all_in_positions"],
                "history": row["history"],
            },
            "coverage": {"population_decisions": 100},
            "population_model": {
                "legal_actions": ["FOLD", "CALL"],
                "policy169_q_b64": encoded_policy(),
            },
        }],
    }


def post_row(street, board, action, key, *, split="TRAIN", known=None):
    return {
        "hand_id": "1",
        "split": split,
        "street": street,
        "player": "Villain",
        "is_hero": False,
        "action": action,
        "canonical_key": key,
        "mode": "FACING",
        "board": board,
        "board_features": {"flushiness": 1, "connectivity": 1},
        "active_players": 2,
        "preflop_role": "CALLER",
        "relative_position": "OOP",
        "pot_type": "SRP",
        "facing_price_pot": 0.75,
        "own_size_pot": None,
        "spr": 4.0,
        "known_cards": known,
    }


def postflop_model():
    spec = {
        "classes": ["FOLD", "CALL"],
        "features": ["score_norm"],
        "feature_mean": [0.0],
        "feature_std": [1.0],
        "coef_std": [[0.0], [0.0]],
        "data_scale": 1.0,
    }
    nodes = []
    for key in ("flop-node", "turn-node"):
        nodes.append({
            "canonical_key": key,
            "coverage": {"population_decisions": 100},
            "population_model": {
                "frequencies": {"FOLD": 0.45, "CALL": 0.55},
                "legal_actions": ["FOLD", "CALL"],
            },
        })
    return {
        "nodes": nodes,
        "response_models": {},
        "combo_policy_models": {
            "flop_FACING": copy.deepcopy(spec),
            "turn_FACING": copy.deepcopy(spec),
        },
        "hand_policy_prior": {},
    }


def hero_row(split="TRAIN"):
    return {
        "hand_id": "1", "split": split, "street": "preflop", "player": "Hero",
        "is_hero": True, "action": "RAISE", "known_cards": ["As", "Kd"],
    }


def test_posterior_propagates_prior_postflop_action_without_target_leakage():
    flop = post_row("flop", ["2c", "7d", "Jh"], "CALL", "flop-node")
    turn = post_row("turn", ["2c", "7d", "Jh", "Ts"], "FOLD", "turn-node")
    rows = [hero_row(), preflop_row(), flop, turn]
    p1 = latent.posterior_before_postflop_action(rows, 3, preflop_model(), postflop_model())
    changed = [dict(x) for x in rows]
    changed[3] = {**changed[3], "action": "CALL"}
    p2 = latent.posterior_before_postflop_action(changed, 3, preflop_model(), postflop_model())
    assert p1.matched_preflop_actions == 1
    assert p1.matched_postflop_actions == 1
    assert p1.combos == p2.combos
    assert p1.weights == p2.weights
    assert math.isclose(sum(p1.weights), 1.0, rel_tol=0, abs_tol=1e-12)
    ts = latent.cid("Ts")
    assert all(ts not in hand for hand in p1.combos)


def test_posterior_quadrature_is_deterministic_and_mass_preserving():
    combos = [(1, 2), (3, 4), (5, 6), (7, 8)]
    weights = [0.05, 0.15, 0.30, 0.50]
    q1 = combo.posterior_quadrature(combos, weights, 3)
    q2 = combo.posterior_quadrature(combos, weights, 3)
    assert q1 == q2
    assert len(q1) <= 3
    assert math.isclose(sum(w for _, w in q1), 1.0)


def test_combo_fit_moves_coefficients_toward_observed_signal_with_parent_cap():
    spec = {
        "classes": ["FOLD", "CALL"],
        "features": ["score_norm"],
        "coef_std": [[0.0], [0.0]],
        "data_scale": 1.0,
    }
    examples = []
    for _ in range(60):
        examples.append({
            "action": "CALL",
            "points": [{"z": [1.0], "weight": 0.75}, {"z": [0.4], "weight": 0.25}],
            "offsets": [math.log(0.5), math.log(0.5)],
        })
        examples.append({
            "action": "FOLD",
            "points": [{"z": [-1.0], "weight": 0.75}, {"z": [-0.4], "weight": 0.25}],
            "offsets": [math.log(0.5), math.log(0.5)],
        })
    fitted, info = combo.fit_one(
        spec, examples, epochs=50, learning_rate=0.2, l2_to_parent=0.02,
        coefficient_delta_cap=0.7, minimum_effective_weight=20,
    )
    assert info["decision"] == "REFIT"
    assert info["fractional_points"] == 240
    assert fitted != spec["coef_std"]
    assert fitted[1][0] > fitted[0][0]
    assert info["max_parent_coefficient_delta"] <= 0.7 + 1e-9


def test_continuation_overlay_round_trip_changes_only_runtime_parameter_families():
    base = postflop_model()
    selected = copy.deepcopy(base)
    selected["response_models"] = {
        "flop_FACING": {"numeric_coef": [[1.0]], "sentinel": "keep"}
    }
    base["response_models"] = {
        "flop_FACING": {"numeric_coef": [[0.0]], "sentinel": "keep"}
    }
    selected["combo_policy_models"]["flop_FACING"]["coef_std"] = [[0.2], [-0.2]]
    overlay = combo.continuation_overlay(base, selected, base_sha256="abc", decision="PROMOTE_STAGE_B_SCIENTIFICALLY")
    rebuilt = combo.apply_overlay(base, overlay)
    assert rebuilt["nodes"] == base["nodes"]
    assert rebuilt["hand_policy_prior"] == base["hand_policy_prior"]
    assert rebuilt["response_models"]["flop_FACING"]["numeric_coef"] == [[1.0]]
    assert rebuilt["response_models"]["flop_FACING"]["sentinel"] == "keep"
    assert rebuilt["combo_policy_models"]["flop_FACING"]["coef_std"] == [[0.2], [-0.2]]


def test_stage_b_budget_is_deterministic_stratified_and_never_selects_test():
    model = postflop_model()
    rows = []
    for split in ("TRAIN", "VALIDATION", "TEST"):
        for i in range(12):
            hid = f"{split}-{i}"
            known = ["Ah", "Ad"] if split == "VALIDATION" else None
            rows.append({
                **post_row("flop", ["2c", "7d", "Jh"], "CALL", "flop-node", split=split, known=known),
                "hand_id": hid,
            })
    ids1, info1 = sample.select_hand_ids(
        rows, model, train_hands_per_model=4, validation_revealed_hands_per_model=3
    )
    ids2, info2 = sample.select_hand_ids(
        rows, model, train_hands_per_model=4, validation_revealed_hands_per_model=3
    )
    assert ids1 == ids2
    assert info1 == info2
    assert sum(h.startswith("TRAIN-") for h in ids1) == 4
    assert sum(h.startswith("VALIDATION-") for h in ids1) == 3
    assert not any(h.startswith("TEST-") for h in ids1)

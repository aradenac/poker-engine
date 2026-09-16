import base64
import importlib.util
import math
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "model_a_latent_ranges", ROOT / "tools/training/model_a_latent_ranges.py"
)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def encoded_policy(*, aa_call=900, aa_fold=100, other_call=500, other_fold=500):
    hands = mod.matrix_notations()
    actions = ["FOLD", "CALL"]
    values = []
    for action in actions:  # action-major [action][hand]
        for hand in hands:
            if hand == "AA":
                values.append(aa_fold if action == "FOLD" else aa_call)
            else:
                values.append(other_fold if action == "FOLD" else other_call)
    raw = struct.pack("<" + "H" * len(values), *values)
    return {
        "hand_order": hands,
        "actions": actions,
        "shape": [2, len(hands)],
        "scale": 1000,
        "dtype": "uint16-le",
        "data": base64.b64encode(raw).decode("ascii"),
    }


def preflop_row(action="CALL"):
    return {
        "hand_id": "h1",
        "split": "TRAIN",
        "street": "preflop",
        "player": "Villain",
        "is_hero": False,
        "actor_position": "BB",
        "action": action,
        "table_size": 2,
        "raise_level": 1,
        "family": "VS_OPEN",
        "live_positions": ["BTN", "BB"],
        "all_in_positions": [],
        "history": [{"position": "BTN", "action": "RAISE"}],
        "known_cards": None,
    }


def model():
    row = preflop_row()
    return {
        "hand_grid": {"classes": mod.matrix_notations()},
        "nodes": [{
            "id": "PF_TEST",
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


def postflop_row(action="FOLD", board=None, known=None):
    return {
        "hand_id": "h1",
        "split": "TRAIN",
        "street": "flop",
        "player": "Villain",
        "is_hero": False,
        "action": action,
        "board": board or ["2c", "7d", "Jh"],
        "known_cards": known,
    }


def hero_row():
    return {
        "hand_id": "h1", "split": "TRAIN", "street": "preflop", "player": "Hero",
        "is_hero": True, "action": "RAISE", "known_cards": ["As", "Kd"],
    }


def test_quantized_policy_decoder_is_action_major_and_normalized():
    m = model()
    policy = mod.decode_policy169(m["nodes"][0], m)
    assert math.isclose(policy["AA"]["CALL"], 0.9)
    assert math.isclose(policy["AA"]["FOLD"], 0.1)
    assert math.isclose(sum(policy["72o"].values()), 1.0)


def test_quantized_policy_decoder_resolves_symbolic_root_hand_order():
    m = model()
    m["nodes"][0]["population_model"]["policy169_q_b64"]["hand_order"] = "hand_grid.classes"
    policy = mod.decode_policy169(m["nodes"][0], m)
    assert len(policy) == 169
    assert math.isclose(policy["AA"]["CALL"], 0.9)


def test_quantized_zero_uses_runtime_midpoint_not_hard_impossibility():
    q = encoded_policy()
    raw = bytearray(base64.b64decode(q["data"]))
    # AA is first hand. First uint16 is FOLD/AA in action-major storage.
    raw[0:2] = b"\x00\x00"
    q["data"] = base64.b64encode(raw).decode("ascii")
    m = model(); m["nodes"][0]["population_model"]["policy169_q_b64"] = q
    p = mod.decode_policy169(m["nodes"][0], m)["AA"]
    assert p["FOLD"] > 0
    assert p["CALL"] > p["FOLD"]


def test_exact_preflop_matching_never_uses_nearest_context():
    m = model(); row = preflop_row()
    assert mod.exact_preflop_node(m, row)["id"] == "PF_TEST"
    bad = dict(row); bad["raise_level"] = 2
    assert mod.exact_preflop_node(m, bad) is None


def test_posterior_conditions_on_preflop_action_and_blocks_only_known_cards():
    rows = [hero_row(), preflop_row("CALL"), postflop_row()]
    p = mod.posterior_before_first_postflop_action(rows, 2, model())
    assert math.isclose(sum(p.weights), 1.0)
    assert p.matched_preflop_actions == 1
    blocked = {"As", "Kd", "2c", "7d", "Jh"}
    assert set(p.blocked_cards) == blocked
    for a, b in p.combos:
        assert mod.ccode(a) not in blocked
        assert mod.ccode(b) not in blocked
    # CALL is 90% for AA and 50% for ordinary classes, so surviving AA receives
    # more posterior mass per exact combo than 72o.
    classes = p.class_mass()
    aa_n = sum(1 for a, b in p.combos if mod.combo_class_ids(a, b) == "AA")
    x_n = sum(1 for a, b in p.combos if mod.combo_class_ids(a, b) == "72o")
    assert classes["AA"] / aa_n > classes["72o"] / x_n


def test_target_action_is_not_used_to_build_its_own_hidden_hand_posterior():
    base = [hero_row(), preflop_row("CALL"), postflop_row("FOLD")]
    changed = [dict(x) for x in base]
    changed[2]["action"] = "RAISE"
    p1 = mod.posterior_before_first_postflop_action(base, 2, model())
    p2 = mod.posterior_before_first_postflop_action(changed, 2, model())
    assert p1.combos == p2.combos
    assert p1.weights == p2.weights


def test_later_postflop_decision_fails_closed_until_ipf_parity_exists():
    rows = [hero_row(), preflop_row("CALL"), postflop_row("CHECK"), {**postflop_row("CALL"), "street": "turn", "board": ["2c", "7d", "Jh", "Ts"]}]
    try:
        mod.posterior_before_first_postflop_action(rows, 3, model())
    except mod.UnsupportedPostflopHistory as exc:
        assert "earlier postflop" in str(exc)
    else:
        raise AssertionError("later postflop target must fail closed")


def test_reveal_is_a_label_after_posterior_build_not_a_prior_condition():
    rows = [hero_row(), preflop_row("CALL"), postflop_row(known=["Ah", "Ad"])]
    p = mod.posterior_before_first_postflop_action(rows, 2, model())
    audit = mod.revealed_label_audit(p, rows[2]["known_cards"])
    assert audit["revealed"] is True
    assert audit["label_policy"] == "POINT_MASS_AFTER_POSTERIOR_BUILD"
    assert audit["posterior_probability"] > 0
    hidden = mod.revealed_label_audit(p, None)
    assert hidden["label_policy"] == "LATENT_POSTERIOR"

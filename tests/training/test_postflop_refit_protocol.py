import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = ROOT / "training/runs/20260915_model_a_postflop_refit_v1/PROTOCOL.json"


def load_protocol():
    return json.loads(PROTOCOL.read_text(encoding="utf-8"))


def test_protocol_keeps_test_and_production_out_of_selection():
    p = load_protocol()
    assert p["schema"] == "poker-model-a-postflop-refit-protocol/v1"
    assert p["production_effect"] == "NONE"
    assert p["data"]["split_contract"] == {
        "fit": ["TRAIN"],
        "selection": ["VALIDATION"],
        "test": "FORBIDDEN_UNTIL_AN_INDEPENDENT_PROMOTION_DECISION_IS_FROZEN",
    }
    assert p["evaluation"]["scientific_decision"]["test_consumed"] is False
    assert p["continuation_contract"]["production_location_untouched"] == "training/models/"
    assert p["continuation_contract"]["candidate_location"].startswith("training/runs/")


def test_protocol_binds_immutable_baseline_and_source():
    p = load_protocol()
    assert p["baseline"]["postflop_model"]["path"] == "training/models/postflop_population_model_v5.json"
    assert len(p["baseline"]["postflop_model"]["git_blob_sha"]) == 40
    assert p["baseline"]["preflop_model"]["path"] == "training/models/preflop_population_model_v5.json"
    assert len(p["baseline"]["preflop_model"]["git_blob_sha"]) == 40
    assert p["data"]["source"].endswith("selected_100_200.zip")
    assert len(p["data"]["source_git_blob_sha"]) == 40


def test_hidden_hands_remain_latent_without_target_action_leakage():
    p = load_protocol()["stage_b_combo_refit"]
    assert p["label_policy"]["revealed_private_hand"].startswith("POINT_MASS")
    assert p["label_policy"]["hidden_private_hand"].startswith("LATENT_POSTERIOR")
    prior = p["latent_prior"]
    assert "target postflop action is forbidden" in prior["conditioning"]
    assert prior["future_cards"] == "FORBIDDEN"
    assert "1326" in prior["initial_support"]
    assert "fractional sufficient statistics" in p["fit_semantics"]


def test_rare_context_and_regularization_contract_is_fail_closed():
    p = load_protocol()["stage_b_combo_refit"]
    assert p["regularization"]["minimum_effective_weight"] == 20.0
    assert p["regularization"]["coefficient_delta_cap_std"] == 1.5
    assert p["backoff"][-1] == "no new synthetic node/context"
    audits = set(p["required_audits"])
    assert "target-action leakage check" in audits
    assert "rare-context/backoff counts" in audits
    assert "board-blocker mass removed at each street" in audits


def test_stage_a_hyperparameters_are_frozen_to_workflow_contract():
    p = load_protocol()["stage_a_response_refit"]
    assert p["epochs"] == 60
    assert p["learning_rate"] == 0.08
    assert p["l2_to_parent"] == 0.25
    assert p["seed"] == 20260915
    assert p["paired_hand_bootstrap_iterations"] == 2000
    assert p["unknown_context_policy"].startswith("EXCLUDE_AND_COUNT")
    assert p["out_of_support_policy"].startswith("MATCH_RUNTIME_CLIPPING")

#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

SPEC = importlib.util.spec_from_file_location(
    "posterior_range",
    ROOT / "src" / "ranges" / "posterior_range.py",
)
assert SPEC and SPEC.loader
posterior = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(posterior)

from tools.simulation.model_b_runtime import combo_class_ids  # noqa: E402


def all_combos() -> list[tuple[int, int]]:
    return [(a, b) for a in range(52) for b in range(a + 1, 52)]


def metadata(moment: str = "AFTER_ACTION", blockers=None) -> dict:
    return {
        "hand_id": "h1",
        "step_id": 4,
        "public_state_fingerprint": "sha256:public",
        "player": "Villain",
        "position": "CO",
        "identity": {
            "population_id": "population-v1",
            "model_id": "posterior-source",
            "model_version": "v1",
            "source_id": "unit-test",
        },
        "moment": moment,
        "public_action": None if moment == "BEFORE_ACTION" else {
            "action": "CALL",
            "source_step_id": 4,
            "sizing": {
                "semantic": "TARGET_TOTAL_BB",
                "observed_size_bb": 4.0,
                "target_total_bb": 4.0,
                "pot_before_bb": 9.5,
                "pot_fraction": None,
            },
        },
        "blockers_applied": blockers or [],
        "source_observations": 100,
        "backoff_level": "POSITION_ACTION",
        "backoff_reason": None,
        "provenance": {
            "producer": "unit-test",
            "contract_version": posterior.SCHEMA,
            "source_artifact": "synthetic",
            "source_fingerprint": "sha256:synthetic",
        },
    }


def test_canonical_169_and_1326_multiplicity() -> None:
    assert len(posterior.HAND_CLASSES) == 169
    assert len(posterior.FULL_COMBO_MULTIPLICITY) == 169
    assert sum(posterior.FULL_COMBO_MULTIPLICITY.values()) == 1326
    assert posterior.FULL_COMBO_MULTIPLICITY["AA"] == 6
    assert posterior.FULL_COMBO_MULTIPLICITY["AKs"] == 4
    assert posterior.FULL_COMBO_MULTIPLICITY["AKo"] == 12


def test_uniform_1326_projects_by_combo_multiplicity() -> None:
    combos = all_combos()
    out = posterior.project_exact_combo_weights(combos, [1.0] * len(combos))
    assert math.isclose(out["probability_mass"], 1.0)
    assert math.isclose(out["projection_169"]["classes"]["AA"], 6 / 1326)
    assert math.isclose(out["projection_169"]["classes"]["AKs"], 4 / 1326)
    assert math.isclose(out["projection_169"]["classes"]["AKo"], 12 / 1326)
    assert not math.isclose(
        out["projection_169"]["classes"]["AA"],
        out["projection_169"]["classes"]["AKo"],
    )


def test_non_uniform_exact_distribution_remains_non_uniform() -> None:
    out = posterior.project_exact_combo_weights(
        [["As", "Ah"], ["7c", "2d"]],
        [9.0, 1.0],
    )
    assert math.isclose(out["projection_169"]["classes"]["AA"], 0.9)
    assert math.isclose(out["projection_169"]["classes"]["72o"], 0.1)
    assert out["projection_169"]["classes"]["AA"] > out["projection_169"]["classes"]["72o"]


def test_public_blocker_filters_combos_and_adjusts_multiplicity() -> None:
    blockers = [{"card": "As", "knowledge_scope": "PUBLIC", "source_step_id": 3}]
    out = posterior.project_exact_combo_weights(all_combos(), [1.0] * 1326, blockers)
    assert len(out["exact_combo_weights"]) == 1275
    assert out["projection_169"]["legal_combo_multiplicity"]["AA"] == 3
    assert out["projection_169"]["legal_combo_multiplicity"]["AKs"] == 3
    assert out["projection_169"]["legal_combo_multiplicity"]["AKo"] == 9
    assert all("As" not in row["cards"] for row in out["exact_combo_weights"])
    assert math.isclose(out["probability_mass"], 1.0)


def test_weights_are_normalized_after_blocking() -> None:
    blockers = [{"card": "As", "knowledge_scope": "PUBLIC", "source_step_id": 3}]
    out = posterior.project_exact_combo_weights(
        [["As", "Ah"], ["Kd", "Kh"], ["7c", "2d"]],
        [10.0, 2.0, 3.0],
        blockers,
    )
    assert math.isclose(out["normalization"]["input_mass"], 15.0)
    assert math.isclose(out["normalization"]["blocked_mass"], 10.0)
    assert math.isclose(out["normalization"]["retained_mass"], 5.0)
    by_class = out["projection_169"]["classes"]
    assert math.isclose(by_class["KK"], 0.4)
    assert math.isclose(by_class["72o"], 0.6)


def test_duplicate_negative_and_zero_mass_fail_closed() -> None:
    try:
        posterior.project_exact_combo_weights([["As", "Ah"], ["Ah", "As"]], [1.0, 1.0])
    except posterior.PosteriorRangeError as exc:
        assert "duplicate" in str(exc)
    else:
        raise AssertionError("duplicate exact combo must fail")

    try:
        posterior.project_exact_combo_weights([["As", "Ah"]], [-1.0])
    except posterior.PosteriorRangeError as exc:
        assert "non-negative" in str(exc)
    else:
        raise AssertionError("negative weight must fail")

    try:
        posterior.project_exact_combo_weights([["As", "Ah"]], [0.0])
    except posterior.UnsupportedPosteriorRange:
        pass
    else:
        raise AssertionError("zero posterior mass must be UNSUPPORTED")


def test_all_mass_blocked_is_unsupported_not_uniform_fallback() -> None:
    blockers = [{"card": "As", "knowledge_scope": "PUBLIC", "source_step_id": 2}]
    try:
        posterior.project_exact_combo_weights([["As", "Ah"]], [1.0], blockers)
    except posterior.UnsupportedPosteriorRange as exc:
        assert "removed all positive" in str(exc)
    else:
        raise AssertionError("all-blocked range must fail closed")



def test_distribution_fingerprint_is_idempotent_across_1326_reprojection() -> None:
    combos = all_combos()
    weights = [float(i + 1) for i in range(len(combos))]
    first = posterior.project_exact_combo_weights(combos, weights)
    second = posterior.project_exact_combo_weights(
        [row["cards"] for row in first["exact_combo_weights"]],
        [row["weight"] for row in first["exact_combo_weights"]],
    )
    assert first["distribution_fingerprint"] == second["distribution_fingerprint"]
    assert math.isclose(second["probability_mass"], 1.0)


def test_available_record_validates_and_has_deterministic_fingerprint() -> None:
    a = posterior.build_available_record(
        combos=[["As", "Ah"], ["7c", "2d"], ["Ks", "Qs"]],
        weights=[9.0, 1.0, 3.0],
        **metadata(),
    )
    b = posterior.build_available_record(
        combos=[["Ks", "Qs"], ["7c", "2d"], ["As", "Ah"]],
        weights=[3.0, 1.0, 9.0],
        **metadata(),
    )
    assert posterior.validate_posterior_range(a) == []
    assert a["distribution_fingerprint"] == b["distribution_fingerprint"]
    assert a["projection_169"]["classes"] == b["projection_169"]["classes"]


def test_combo_posterior_adapter_does_not_depend_on_model_a_type() -> None:
    source = SimpleNamespace(
        combos=((0, 1), (2, 3)),
        weights=(0.25, 0.75),
    )
    record = posterior.record_from_combo_posterior(source, **metadata(moment="BEFORE_ACTION"))
    assert posterior.validate_posterior_range(record) == []
    assert math.isclose(record["probability_mass"], 1.0)


def test_after_action_requires_action_and_supports_future_sizing_likelihood_fields() -> None:
    good = posterior.build_available_record(
        combos=[["As", "Ah"], ["7c", "2d"]],
        weights=[1.0, 1.0],
        **metadata("AFTER_ACTION"),
    )
    sizing = good["public_action"]["sizing"]
    assert sizing["observed_size_bb"] == 4.0
    assert sizing["target_total_bb"] == 4.0

    broken = copy.deepcopy(good)
    broken["public_action"] = None
    assert any("public_action is required" in error for error in posterior.validate_posterior_range(broken))


def test_before_action_forbids_conditioning_on_target_action() -> None:
    record = posterior.build_available_record(
        combos=[["As", "Ah"], ["7c", "2d"]],
        weights=[1.0, 1.0],
        **metadata("BEFORE_ACTION"),
    )
    assert record["public_action"] is None
    broken = copy.deepcopy(record)
    broken["public_action"] = {
        "action": "CALL",
        "source_step_id": 4,
        "sizing": None,
    }
    assert any("must be null" in error for error in posterior.validate_posterior_range(broken))


def test_public_only_boundary_rejects_opponent_private_future_and_unknown_fields() -> None:
    for scope in ("OPPONENT_PRIVATE", "FUTURE"):
        try:
            posterior.project_exact_combo_weights(
                [["As", "Ah"], ["7c", "2d"]],
                [1.0, 1.0],
                [{"card": "Kd", "knowledge_scope": scope, "source_step_id": 9}],
            )
        except posterior.PosteriorRangeError as exc:
            assert "PUBLIC" in str(exc)
        else:
            raise AssertionError(scope)

    record = posterior.build_available_record(
        combos=[["As", "Ah"], ["7c", "2d"]],
        weights=[1.0, 1.0],
        **metadata(),
    )
    record["future_cards"] = ["Kd"]
    assert any("unsupported top-level fields" in error for error in posterior.validate_posterior_range(record))


def test_identity_and_provenance_are_mandatory() -> None:
    record = posterior.build_available_record(
        combos=[["As", "Ah"], ["7c", "2d"]],
        weights=[1.0, 1.0],
        **metadata(),
    )
    broken = copy.deepcopy(record)
    del broken["identity"]["source_id"]
    assert any("identity" in error for error in posterior.validate_posterior_range(broken))
    broken = copy.deepcopy(record)
    broken["provenance"]["source_fingerprint"] = ""
    assert any("source_fingerprint" in error for error in posterior.validate_posterior_range(broken))


def test_projection_mismatch_and_all_100_grid_are_rejected() -> None:
    record = posterior.build_available_record(
        combos=[["As", "Ah"], ["7c", "2d"]],
        weights=[9.0, 1.0],
        **metadata(),
    )
    broken = copy.deepcopy(record)
    broken["projection_169"]["classes"]["AA"] = 0.5
    assert any("projection mismatch" in error for error in posterior.validate_posterior_range(broken))

    all_100 = copy.deepcopy(record)
    all_100["projection_169"]["classes"] = {hand: 1.0 for hand in posterior.HAND_CLASSES}
    errors = posterior.validate_posterior_range(all_100)
    assert errors
    assert any("projection mismatch" in error for error in errors)


def test_fail_closed_records_have_zero_mass_and_no_fake_100_grid() -> None:
    record = posterior.build_fail_closed_record(
        status="UNSUPPORTED",
        reason="insufficient exact support",
        **metadata(),
    )
    assert posterior.validate_posterior_range(record) == []
    assert record["probability_mass"] == 0.0
    assert record["exact_combo_weights"] == []
    assert set(record["projection_169"]["classes"].values()) == {0.0}

    broken = copy.deepcopy(record)
    broken["projection_169"]["classes"]["AA"] = 1.0
    assert any("zero mass" in error for error in posterior.validate_posterior_range(broken))


def test_fixture_builds_a_valid_available_record() -> None:
    fixture = json.loads(
        (ROOT / "tests" / "fixtures" / "ranges" / "posterior" / "basic.json").read_text(encoding="utf-8")
    )
    combos = fixture.pop("combos")
    weights = fixture.pop("weights")
    record = posterior.build_available_record(combos=combos, weights=weights, **fixture)
    assert posterior.validate_posterior_range(record) == []
    assert record["status"] == "AVAILABLE"
    assert math.isclose(record["probability_mass"], 1.0)
    assert record["projection_169"]["classes"]["AA"] > record["projection_169"]["classes"]["72o"]


def test_schema_declares_fail_closed_statuses_and_required_identity() -> None:
    schema = json.loads((ROOT / "contracts" / "posterior-range.schema.json").read_text(encoding="utf-8"))
    assert schema["$id"] == posterior.SCHEMA
    assert schema["properties"]["status"]["enum"] == ["AVAILABLE", "UNSUPPORTED", "INVALID"]
    assert set(schema["properties"]["identity"]["required"]) == {
        "population_id", "model_id", "model_version", "source_id"
    }
    assert schema["properties"]["blockers_applied"]["items"]["properties"]["knowledge_scope"]["const"] == "PUBLIC"


def test_classification_reuses_existing_runtime_mapping() -> None:
    out = posterior.project_exact_combo_weights(
        [["As", "Ks"], ["Ah", "Kd"], ["Ac", "Ad"]],
        [1.0, 2.0, 3.0],
    )
    expected = {
        combo_class_ids(12, 11),
        combo_class_ids(25, 50),
        combo_class_ids(38, 51),
    }
    positive = {hand for hand, mass in out["projection_169"]["classes"].items() if mass > 0}
    assert positive == expected


def main() -> None:
    tests = [
        value for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
    print(f"posterior range tests: {len(tests)} passed")


if __name__ == "__main__":
    main()

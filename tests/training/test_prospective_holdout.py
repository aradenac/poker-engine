#!/usr/bin/env python3
from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.validate_prospective_holdout import (  # noqa: E402
    canonical_sha256,
    load_json,
    validate_manifest,
    validate_protocol,
    validate_transition,
)

PROTOCOL = load_json(ROOT / "training" / "prospective" / "PROTOCOL.json")
PROTOCOL_SHA = canonical_sha256(PROTOCOL)
A = "a" * 64
B = "b" * 64
C = "c" * 64
D = "d" * 64
E = "e" * 64
F = "f" * 64
COMMIT = "1" * 40


def frozen() -> dict:
    return {
        "schema": "poker-prospective-holdout/v1",
        "holdout_id": "prospective-fixture-g1",
        "generation": 1,
        "parent_holdout_id": None,
        "population_id": "pokerstars_nlhe_100-200_zoom_play_6max_v1",
        "state": "UNCONSUMED",
        "previous_manifest_sha256": None,
        "precommit": {
            "frozen_at": "2026-09-19T00:00:00Z",
            "source_commit_sha": COMMIT,
            "prior_hand_ids_sha256": F,
            "fit": {
                "completed_at": "2026-09-18T23:00:00Z",
                "training_dataset_sha256": A,
                "training_hand_ids_sha256": B,
            },
            "candidate": {
                "id": "fixture-candidate",
                "artifact_sha256": C,
                "pack_sha256": D,
            },
            "models": {
                "model_a_sha256": D,
                "model_b_sha256": E,
            },
            "strategy_sha256": C,
            "protocol_sha256": PROTOCOL_SHA,
            "metrics_sha256": A,
            "thresholds_sha256": B,
        },
        "temporal_boundary": {
            "cutoff_utc": "2026-09-19T00:00:00Z",
            "admission_not_before_utc": "2026-09-20T00:00:00Z",
        },
        "hands": [],
        "evaluation": None,
        "training_transition": None,
    }


def hand(hand_id: str = "h1", digest: str = C) -> dict:
    return {
        "hand_id": hand_id,
        "sha256": digest,
        "observed_at": "2026-09-20T00:01:00Z",
        "first_seen_at": "2026-09-20T00:02:00Z",
        "novelty_proof": {
            "checked_against_hand_ids_sha256": F,
            "absent_from_prior_hand_ids": True,
            "checked_against_candidate_fit_hand_ids_sha256": B,
            "absent_from_candidate_fit_hand_ids": True,
            "evidence_sha256": D,
        },
        "train_eligible": False,
    }


def with_hand(previous: dict | None = None) -> dict:
    previous = previous or frozen()
    row = copy.deepcopy(previous)
    row["previous_manifest_sha256"] = canonical_sha256(previous)
    row["hands"] = [hand()]
    return row


def evaluating(previous: dict | None = None) -> dict:
    previous = previous or with_hand()
    row = copy.deepcopy(previous)
    row["state"] = "EVALUATING"
    row["previous_manifest_sha256"] = canonical_sha256(previous)
    row["evaluation"] = {
        "started_at": "2026-09-20T01:00:00Z",
        "closed_at": None,
        "report": None,
    }
    return row


def closed(previous: dict | None = None) -> dict:
    previous = previous or evaluating()
    row = copy.deepcopy(previous)
    row["state"] = "CLOSED"
    row["previous_manifest_sha256"] = canonical_sha256(previous)
    row["evaluation"] = {
        "started_at": previous["evaluation"]["started_at"],
        "closed_at": "2026-09-21T00:00:00Z",
        "report": {
            "sha256": E,
            "classification": {
                "population_drift": "PASS",
                "coverage": "WARN",
                "performance": "INCONCLUSIVE",
            },
        },
    }
    return row


def released(previous: dict | None = None) -> dict:
    previous = previous or closed()
    row = copy.deepcopy(previous)
    row["state"] = "RELEASED_TO_FUTURE_TRAIN"
    row["previous_manifest_sha256"] = canonical_sha256(previous)
    for item in row["hands"]:
        item["train_eligible"] = True
    row["training_transition"] = {
        "released_at": "2026-09-22T00:00:00Z",
        "next_training_cycle_id": "future-cycle-2",
    }
    return row


def test_repository_protocol_is_structurally_valid() -> None:
    assert validate_protocol(PROTOCOL) == []


def test_valid_fail_closed_lifecycle() -> None:
    f = frozen()
    u = with_hand(f)
    e = evaluating(u)
    c = closed(e)
    r = released(c)
    assert validate_manifest(f, PROTOCOL)["status"] == "PASS"
    assert validate_transition(f, u, PROTOCOL)["status"] == "PASS"
    assert validate_transition(u, e, PROTOCOL)["status"] == "PASS"
    assert validate_transition(e, c, PROTOCOL)["status"] == "PASS"
    assert validate_transition(c, r, PROTOCOL)["status"] == "PASS"


def test_fit_must_finish_before_candidate_freeze() -> None:
    row = frozen()
    row["precommit"]["fit"]["completed_at"] = "2026-09-19T00:01:00Z"
    report = validate_manifest(row, PROTOCOL)
    assert report["status"] == "FAIL", report
    assert any("fit.completed_at" in error for error in report["errors"])


def test_candidate_must_be_frozen_before_admission_cutoff() -> None:
    row = frozen()
    row["precommit"]["frozen_at"] = "2026-09-19T00:01:00Z"
    report = validate_manifest(row, PROTOCOL)
    assert report["status"] == "FAIL", report
    assert any("frozen_at" in error for error in report["errors"])


def test_protocol_hash_cannot_be_reinterpreted() -> None:
    row = frozen()
    row["precommit"]["protocol_sha256"] = A
    report = validate_manifest(row, PROTOCOL)
    assert report["status"] == "FAIL", report
    assert any("versioned protocol" in error for error in report["errors"])


def test_candidate_threshold_and_fit_identity_are_immutable() -> None:
    before = frozen()
    after = with_hand(before)
    after["precommit"]["thresholds_sha256"] = F
    after["precommit"]["fit"]["training_dataset_sha256"] = F
    report = validate_transition(before, after, PROTOCOL)
    assert report["status"] == "FAIL", report
    assert any("precommit is immutable" in error for error in report["errors"])


def test_future_hand_cannot_predate_admission_boundary() -> None:
    before = frozen()
    after = with_hand(before)
    after["hands"][0]["observed_at"] = "2026-09-19T23:59:59Z"
    report = validate_transition(before, after, PROTOCOL)
    assert report["status"] == "FAIL", report
    assert any("admission boundary" in error for error in report["errors"])


def test_novelty_proof_must_bind_to_candidate_fit_fingerprint() -> None:
    before = frozen()
    after = with_hand(before)
    after["hands"][0]["novelty_proof"]["checked_against_candidate_fit_hand_ids_sha256"] = A
    report = validate_transition(before, after, PROTOCOL)
    assert report["status"] == "FAIL", report
    assert any("candidate fit hand-ID fingerprint" in error for error in report["errors"])


def test_prospective_hand_must_be_absent_from_candidate_fit() -> None:
    before = frozen()
    after = with_hand(before)
    after["hands"][0]["novelty_proof"]["absent_from_candidate_fit_hand_ids"] = False
    report = validate_transition(before, after, PROTOCOL)
    assert report["status"] == "FAIL", report
    assert any("absent_from_candidate_fit_hand_ids" in error for error in report["errors"])


def test_hand_cannot_be_train_eligible_before_release() -> None:
    row = with_hand()
    row["hands"][0]["train_eligible"] = True
    report = validate_manifest(row, PROTOCOL)
    assert report["status"] == "FAIL", report
    assert any("train_eligible must be false" in error for error in report["errors"])


def test_evaluation_cannot_start_before_all_hands_are_seen() -> None:
    row = evaluating()
    row["evaluation"]["started_at"] = "2026-09-20T00:01:30Z"
    report = validate_manifest(row, PROTOCOL)
    assert report["status"] == "FAIL", report
    assert any("every admitted first_seen_at" in error for error in report["errors"])


def test_ledger_freezes_when_evaluation_starts() -> None:
    before = evaluating()
    after = closed(before)
    after["hands"].append(hand("h2", D))
    report = validate_transition(before, after, PROTOCOL)
    assert report["status"] == "FAIL", report
    assert any("ledger must be frozen" in error for error in report["errors"])


def test_append_only_unconsumed_ledger_rejects_rewrite() -> None:
    before = with_hand()
    after = copy.deepcopy(before)
    after["previous_manifest_sha256"] = canonical_sha256(before)
    after["hands"][0]["sha256"] = E
    report = validate_transition(before, after, PROTOCOL)
    assert report["status"] == "FAIL", report
    assert any("hands[0] was modified" in error for error in report["errors"])


def test_closed_report_separates_drift_coverage_performance() -> None:
    before = evaluating()
    after = closed(before)
    del after["evaluation"]["report"]["classification"]["coverage"]
    report = validate_transition(before, after, PROTOCOL)
    assert report["status"] == "FAIL", report
    assert any("coverage" in error for error in report["errors"])


def test_release_requires_closed_evaluation_and_new_future_cycle() -> None:
    before = closed()
    after = released(before)
    after["training_transition"]["released_at"] = "2026-09-20T12:00:00Z"
    after["training_transition"]["next_training_cycle_id"] = ""
    report = validate_transition(before, after, PROTOCOL)
    assert report["status"] == "FAIL", report
    assert any("cannot precede evaluation.closed_at" in error for error in report["errors"])
    assert any("next_training_cycle_id" in error for error in report["errors"])


def test_generation_chain_requires_parent_after_generation_one() -> None:
    row = frozen()
    row["generation"] = 2
    report = validate_manifest(row, PROTOCOL)
    assert report["status"] == "FAIL", report
    assert any("parent_holdout_id" in error for error in report["errors"])


def main() -> None:
    cases = [
        value for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for case in cases:
        case()
    print(f"prospective holdout tests: {len(cases)} passed")


if __name__ == "__main__":
    main()

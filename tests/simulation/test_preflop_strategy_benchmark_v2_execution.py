#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.simulation.preflop_strategy_benchmark_v2 import (  # noqa: E402
    ENV_REPORT_SCHEMA,
    PFC_BINDING_SCHEMA,
    candidate_binding_identity,
    candidate_policy_binding_path,
    paired_cluster_bootstrap,
    select_validation,
    summarize_environment_rows,
)
from tools.simulation.hero_preflop_overlay import POLICY_BINDING_SCHEMA  # noqa: E402


def rows():
    out = []
    deltas = {"h1": [1.0, 3.0], "h2": [-1.0, 1.0]}
    for hand, values in deltas.items():
        for rep, delta in enumerate(values):
            out.append(
                {
                    "scenario_id": f"{hand}-{rep}",
                    "hand_id": hand,
                    "rep": rep,
                    "hero_position": "BTN",
                    "preflop_policy_context_id": "PFPC_FIXTURE",
                    "preflop_family": "UNOPENED",
                    "limper_count": 0,
                    "caller_count": 0,
                    "stack_depth_bucket": "GT75_LE125",
                    "delta_bb": delta,
                    "candidate_audit": {
                        "hero_preflop_decisions": 1,
                        "candidate_supported_decisions": 1 if hand == "h1" else 0,
                        "candidate_out_of_support_decisions": 0 if hand == "h1" else 1,
                    },
                    "reference_outcome": {
                        "players_to_flop": 2,
                        "won_without_flop": False,
                        "all_in_preflop": False,
                        "hero_jam_preflop": False,
                        "side_pot": False,
                    },
                    "candidate_outcome": {
                        "players_to_flop": 3,
                        "won_without_flop": False,
                        "all_in_preflop": hand == "h1",
                        "hero_jam_preflop": hand == "h1",
                        "side_pot": False,
                    },
                }
            )
    return out


def report(environment_id: str, passed: bool = True):
    return {
        "schema": ENV_REPORT_SCHEMA,
        "candidate_id": "candidate-1",
        "environment": {"environment_id": environment_id},
        "gate": {"pass": passed},
        "paired": {
            "observed_delta_bb_per_100": 25.0,
            "ci95_bb_per_100": [1.0 if passed else -1.0, 50.0],
        },
        "candidate_coverage": {
            "supported_decision_rate": 0.5,
            "out_of_support_decision_rate": 0.5,
        },
    }


def run_manifest():
    return {
        "contract_version": "fixture",
        "identities": {
            "candidate_id": "candidate-1",
            "model_b_environment_ids": ["nominal", "low", "high"],
        },
    }



def _write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_candidate_binding_identity_supports_legacy_pfc_and_pfpc() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        candidate = root / "candidate.json"
        candidate.write_text('{"schema":"fixture"}\n', encoding="utf-8")
        candidate_sha = hashlib.sha256(candidate.read_bytes()).hexdigest()

        legacy = root / "legacy-binding.json"
        _write_json(legacy, {
            "schema": PFC_BINDING_SCHEMA,
            "run_id": "legacy-candidate",
            "promotion_authorized": False,
            "artifact_sha256": {"hero_range_repository_pfc": candidate_sha},
            "selection_boundary": {"validation_consumed": False, "test_consumed": False},
        })
        legacy_id = candidate_binding_identity(legacy, candidate)
        assert legacy_id["candidate_id"] == "legacy-candidate"
        assert legacy_id["candidate_artifact_sha256"] == candidate_sha
        assert legacy_id["candidate_binding_schema"] == PFC_BINDING_SCHEMA
        legacy_manifest = {"identities": dict(legacy_id)}
        assert candidate_policy_binding_path(legacy, candidate, legacy_manifest) is None

        pfpc = root / "pfpc-binding.json"
        _write_json(pfpc, {
            "schema": POLICY_BINDING_SCHEMA,
            "run_id": "pfpc-candidate",
            "promotion_authorized": False,
            "repository_sha256": candidate_sha,
            "selection_boundary": {"validation_consumed": False, "test_consumed": False},
        })
        pfpc_id = candidate_binding_identity(pfpc, candidate)
        assert pfpc_id["candidate_id"] == "pfpc-candidate"
        assert pfpc_id["candidate_binding_schema"] == POLICY_BINDING_SCHEMA
        pfpc_manifest = {"identities": dict(pfpc_id)}
        assert candidate_policy_binding_path(pfpc, candidate, pfpc_manifest) == pfpc


def test_candidate_binding_identity_rejects_repository_or_binding_drift() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        candidate = root / "candidate.json"
        candidate.write_text('{"schema":"fixture"}\n', encoding="utf-8")
        candidate_sha = hashlib.sha256(candidate.read_bytes()).hexdigest()
        binding = root / "binding.json"
        _write_json(binding, {
            "schema": POLICY_BINDING_SCHEMA,
            "run_id": "candidate-1",
            "promotion_authorized": False,
            "repository_sha256": candidate_sha,
            "selection_boundary": {"validation_consumed": False, "test_consumed": False},
        })
        frozen = candidate_binding_identity(binding, candidate)
        manifest = {"identities": dict(frozen)}

        candidate.write_text('{"schema":"mutated"}\n', encoding="utf-8")
        try:
            candidate_policy_binding_path(binding, candidate, manifest)
        except ValueError as exc:
            assert "candidate repository hash differs" in str(exc)
        else:
            raise AssertionError("repository drift must fail closed")

        candidate.write_text('{"schema":"fixture"}\n', encoding="utf-8")
        _write_json(binding, {
            "schema": POLICY_BINDING_SCHEMA,
            "run_id": "candidate-1",
            "promotion_authorized": False,
            "repository_sha256": candidate_sha,
            "selection_boundary": {"validation_consumed": False, "test_consumed": False},
            "extra": "binding drift",
        })
        try:
            candidate_policy_binding_path(binding, candidate, manifest)
        except ValueError as exc:
            assert "candidate binding changed" in str(exc)
        else:
            raise AssertionError("binding drift must fail closed")

def test_paired_bootstrap_clusters_repetitions_by_hand() -> None:
    stats = paired_cluster_bootstrap(rows(), samples=200, seed=7)
    # Cluster means are h1=2bb and h2=0bb, so paired estimate is 1bb/hand.
    assert stats["independent_hands"] == 2
    assert stats["observations"] == 4
    assert stats["repetitions_per_hand"] == 2
    assert stats["observed_delta_bb_per_100"] == 100.0
    assert stats["ci95_bb_per_100"][0] <= 100.0 <= stats["ci95_bb_per_100"][1]


def test_environment_summary_reports_support_and_required_breakdowns() -> None:
    summary = summarize_environment_rows(
        rows(),
        environment={"environment_id": "nominal", "role": "nominal"},
        candidate_id="candidate-1",
        bootstrap_samples=200,
        bootstrap_seed=9,
        threshold=-1000.0,
    )
    assert summary["gate"]["pass"] is True
    assert summary["candidate_coverage"]["hero_preflop_decisions"] == 4
    assert summary["candidate_coverage"]["supported_decisions"] == 2
    assert summary["candidate_coverage"]["out_of_support_decisions"] == 2
    assert summary["candidate_coverage"]["out_of_support_decision_rate"] == 0.5
    assert set(summary["breakdowns"]) == {
        "position",
        "policy_context",
        "candidate_support_by_policy_context",
        "preflop_family",
        "limper_count",
        "caller_count",
        "stack_depth_bucket",
        "reference_outcomes",
        "candidate_outcomes",
    }
    assert summary["breakdowns"]["candidate_outcomes"]["jam_frequency"] == 0.5
    pfpc = summary["breakdowns"]["candidate_support_by_policy_context"]["PFPC_FIXTURE"]
    assert pfpc["hero_preflop_decisions"] == 4
    assert pfpc["supported_decisions"] == 2
    assert pfpc["out_of_support_decisions"] == 2


def test_validation_selection_requires_every_frozen_environment() -> None:
    selected = select_validation(
        [report("nominal"), report("low"), report("high")],
        run_manifest(),
    )
    assert selected["outcome"] == "FREEZE_FINALIST"
    assert selected["frozen_finalist"] == "candidate-1"
    assert selected["test_authorized"] is True
    assert selected["test_consumed"] is False
    assert selected["promotion_authorized"] is False

    retained = select_validation(
        [report("nominal"), report("low", passed=False), report("high")],
        run_manifest(),
    )
    assert retained["outcome"] == "RETAIN_REFERENCE"
    assert retained["frozen_finalist"] is None
    assert retained["test_authorized"] is False
    assert retained["test_consumed"] is False


def main() -> None:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"Preflop strategy benchmark v2 execution tests: {len(tests)} passed")


if __name__ == "__main__":
    main()

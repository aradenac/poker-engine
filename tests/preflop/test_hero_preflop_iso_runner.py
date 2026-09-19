#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.ranges.posterior_range import build_available_record
from tools.simulation.hero_preflop_iso_runner import (
    HeroPreflopIsoRunnerError,
    run_hero_preflop_iso,
)
from tools.simulation.paired_adaptive_preflop_ev import AdaptiveBudget

REPRO = ROOT / "tests/fixtures/repro/kts_sb_two_limp_iso4_three_calls.snapshots.json"
SUPPORT = ROOT / "analysis/preflop_sizing_support_train.json"
DIAG_FIX = ROOT / "tests/fixtures/iso-sizing-diagnostics"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def issue321_state() -> tuple[dict, str]:
    fixture = load(REPRO)
    row = next(item for item in fixture["snapshots"] if item["id"] == "before_hero")
    state = copy.deepcopy(row["state"])
    state["action_log"] = [
        {"street": "preflop", "player": "UTG", "action": "FOLD", "target_total_bb": None, "incremental_cost_bb": 0},
        {"street": "preflop", "player": "HJ", "action": "FOLD", "target_total_bb": None, "incremental_cost_bb": 0},
        {"street": "preflop", "player": "CO", "action": "CALL", "target_total_bb": None, "incremental_cost_bb": 1},
        {"street": "preflop", "player": "BTN", "action": "CALL", "target_total_bb": None, "incremental_cost_bb": 1},
    ]
    return state, row["public_fingerprint_sha256"]


def issue319_exact_support() -> dict:
    report = load(SUPPORT)
    rows = report["kts_sb_two_limpers_projection"]["hero_public_context_support"]["observed_iso_targets"]
    wanted = {4.0, 5.0, 6.0}
    chosen = []
    for row in rows:
        target = float(row["target_total_bb"])
        if target not in wanted:
            continue
        n = int(row["observations"])
        chosen.append(
            {
                "target_total_bb": target,
                "observations": n,
                "support_tier": "MEDIUM" if n >= 50 else "LOW",
                "identifiability": "IDENTIFIABLE_MARGINAL" if n >= 50 else "LOW_SUPPORT",
            }
        )
    assert {row["target_total_bb"] for row in chosen} == wanted
    return {
        "schema": "poker-preflop-exact-support-view/v1",
        "source_schema": report["schema"],
        "source_id": "issue-319:kts-sb-two-limpers:hero-observed-iso-targets",
        "source_hash": report["full_report"]["report_hash"],
        "exact_price_only": True,
        "no_silent_nearest_price": True,
        "exact_target_support": sorted(chosen, key=lambda row: row["target_total_bb"]),
    }


class SyntheticModelAProvider:
    def __init__(self, *, wrong_world=False, bad_posterior=False):
        self.calls = 0
        self.wrong_world = wrong_world
        self.bad_posterior = bad_posterior
        source = load(DIAG_FIX / "posterior_records_source.json")
        self.records = {
            ref_id: build_available_record(**args)
            for ref_id, args in source["records"].items()
        }
        self.patterns = load(DIAG_FIX / "diagnostic_worlds.json")["alternatives"]

    def metadata(self):
        return {
            "provider_kind": "MODEL_A",
            "admission_status": "NON_SCIENTIFIC_SYNTHETIC",
            "scientific_effect": "NON_SCIENTIFIC",
            "identity": {
                "population_id": "synthetic-issue-357",
                "model_id": "synthetic-model-a-357",
                "model_version": "fixture-v1",
                "source_id": "issue-357-provider",
            },
            "provenance": {
                "issue": 357,
                "fixture": "#321",
                "real_strategy": False,
            },
        }

    def materialize_world(self, public_context, decision_id, sample_index, seed):
        self.calls += 1
        return {
            "decision_id": decision_id,
            "sample_index": int(sample_index),
            "seed": int(seed),
            "synthetic_bucket": int(sample_index) % 8,
            "public_state_fingerprint": public_context["public_state_fingerprint"],
        }

    def evaluate_alternative(self, world, alternative):
        alt_id = alternative["id"]
        index = int(world["sample_index"])
        if alt_id == "OVERLIMP@1":
            ev = 0.10
        elif alt_id == "ISO@4":
            ev = 0.20
        elif alt_id == "ISO@5":
            ev = 0.36
        elif alt_id == "ISO@6":
            ev = 0.35 + (0.04 if index % 2 == 0 else -0.04)
        else:
            raise AssertionError("unexpected evaluated alternative " + alt_id)

        result = {"ev_bb": ev}
        if self.wrong_world:
            result["world_fingerprint_sha256"] = "0" * 64

        if alternative["action"] == "ISO":
            pattern = self.patterns[alt_id][index % len(self.patterns[alt_id])]
            continuers = []
            for item in pattern["continuers"]:
                record = copy.deepcopy(self.records[item["posterior_ref_id"]])
                if self.bad_posterior:
                    record["position"] = "HJ" if item["position"] != "HJ" else "CO"
                continuers.append(
                    {
                        "position": item["position"],
                        "response": item["response"],
                        "posterior_ref_id": item["posterior_ref_id"],
                        "posterior_record": record,
                    }
                )
            result["continuers"] = continuers
        return result


def run_fixture(provider=None, **overrides):
    state, fingerprint = issue321_state()
    args = {
        "state_snapshot": state,
        "public_state_fingerprint": fingerprint,
        "requested_raise_targets_bb": [4, 5, 6, 6.0001],
        "exact_support": issue319_exact_support(),
        "provider": provider or SyntheticModelAProvider(),
        "decision_id": "synthetic:#321:KTs:hero-preflop",
        "base_seed": "issue-357-synthetic",
        "budget": AdaptiveBudget(
            initial_samples_per_alternative=8,
            max_samples_per_alternative=16,
            batch_size=4,
            max_total_rollouts=64,
            confidence_z=1.96,
            elimination_margin_bb=0,
        ),
        "execution_mode": "NON_SCIENTIFIC",
    }
    args.update(overrides)
    return run_hero_preflop_iso(**args)


def expect_runner_error(fn, contains: str | None = None):
    try:
        fn()
    except HeroPreflopIsoRunnerError as exc:
        if contains is not None:
            assert contains in str(exc), str(exc)
        return
    raise AssertionError("expected HeroPreflopIsoRunnerError")


def test_issue321_end_to_end_synthetic_only() -> None:
    result = run_fixture()
    assert result["schema"] == "poker-hero-preflop-iso-runner-result/v1"
    assert result["execution_mode"] == "NON_SCIENTIFIC"
    assert result["decision"]["recommendation_admissibility"] == {
        "hero_recommendation_allowed": False,
        "status": "NON_SCIENTIFIC_INTEGRATION_ONLY",
    }
    alternatives = {row["id"]: row for row in result["decision"]["alternatives"]}
    assert set(("FOLD", "OVERLIMP@1", "ISO@4", "ISO@5", "ISO@6", "ISO@6.0001")) <= set(alternatives)
    assert alternatives["ISO@4"]["incremental_cost_bb"] == 3.5
    assert alternatives["ISO@5"]["incremental_cost_bb"] == 4.5
    assert alternatives["ISO@6"]["incremental_cost_bb"] == 5.5
    assert alternatives["ISO@4"]["support"]["observations"] == 13
    assert alternatives["ISO@5"]["support"]["observations"] == 56
    assert alternatives["ISO@6"]["support"]["observations"] == 9

    unsupported = alternatives["ISO@6.0001"]
    assert unsupported["support"]["status"] == "LEGAL_BUT_UNSUPPORTED"
    assert unsupported["ev_bb"] is None
    assert unsupported["comparable"] is False
    assert result["information_boundary"]["nearest_price_used"] is False

    # Selection is point max-EV only. ISO@6 remains statistically compatible.
    assert result["decision"]["selected_id"] == "ISO@5"
    assert result["decision"]["ev_bb"] == max(
        row["ev_bb"] for row in alternatives.values() if row["ev_bb"] is not None
    )
    indiff = {row["alternative_id"]: row for row in result["statistical_indifference"]}
    assert indiff["ISO@6"]["status"] == "STATISTICALLY_INDISTINGUISHABLE"
    assert indiff["ISO@4"]["status"] == "STATISTICALLY_SEPARATED_LOWER_EV"
    assert indiff["ISO@6.0001"]["status"] == "UNSUPPORTED_NOT_COMPARED"

    diagnostics = {row["alternative_id"]: row for row in result["diagnostics"]["alternatives"]}
    for alt_id in ("ISO@4", "ISO@5", "ISO@6"):
        row = diagnostics[alt_id]
        assert row["status"] == "AVAILABLE"
        assert row["provenance"]["same_worlds_as_ev"] is True
        paired_fingerprints = result["paired_result"]["search"]["world_fingerprints_sha256"]
        for index, fingerprint in row["provenance"]["world_fingerprints_sha256"].items():
            assert fingerprint == paired_fingerprints[index]
    assert diagnostics["ISO@6.0001"]["status"] == "UNSUPPORTED"
    assert result["diagnostics"]["selection_contract"]["diagnostics_can_select"] is False
    assert result["posterior_binding"]["posterior_schema"] == "poker-opponent-posterior-range/v1"
    assert result["posterior_binding"]["validated_references"] > 0

    assert result["scientific_boundary"] == {
        "validation_consumed": False,
        "test_consumed": False,
        "model_a_modified": False,
        "model_b_modified": False,
        "promotion_performed": False,
        "ui_modified": False,
    }


def test_scientific_execution_requires_explicit_admission() -> None:
    provider = SyntheticModelAProvider()
    expect_runner_error(
        lambda: run_fixture(provider, execution_mode="SCIENTIFIC"),
        "ADMITTED_FOR_SIZING_EV",
    )
    assert provider.calls == 0


def test_world_mismatch_fails_closed() -> None:
    expect_runner_error(
        lambda: run_fixture(SyntheticModelAProvider(wrong_world=True)),
        "diagnostics world differs from EV world",
    )


def test_posterior_incoherence_fails_closed() -> None:
    expect_runner_error(lambda: run_fixture(SyntheticModelAProvider(bad_posterior=True)))


def test_future_private_public_context_fails_closed() -> None:
    provider = SyntheticModelAProvider()
    expect_runner_error(
        lambda: run_fixture(
            provider,
            public_context_extra={"future_board": ["As", "Kd", "Qc"]},
        ),
        "future/private information",
    )
    assert provider.calls == 0


def test_exact_support_refuses_nearest_price_contract() -> None:
    support = issue319_exact_support()
    support["no_silent_nearest_price"] = False
    expect_runner_error(lambda: run_fixture(exact_support=support), "contract bridge failed")


if __name__ == "__main__":
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
    print(f"hero preflop iso runner #357 tests: {len(tests)} passed")

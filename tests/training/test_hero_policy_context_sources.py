#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.preflop.policy_context import build_policy_context  # noqa: E402
from tools.training.enrich_hero_range_context import canonical_context_for_state  # noqa: E402
from tools.training.generate_hero_range_decisions import ContextSpec, build_context_state  # noqa: E402
from tools.training.materialize_hero_pfc_source import (  # noqa: E402
    canonical_json_bytes,
    materialize,
)
from tools.training.merge_hero_policy_context_sources import merge_sources  # noqa: E402

POPULATION = "pokerstars_nlhe_100-200_zoom_play_6max_v1"


def fixture(position: str, stack: float = 100.0):
    spec = ContextSpec(position=position, effective_stack_bb=stack, spot="UNOPENED")
    canonical = canonical_context_for_state(build_context_state(spec), position)
    pfc = canonical["context_id"]
    context = {
        "population_id": POPULATION,
        "table_size": 6,
        "position": position,
        "effective_stack_bb": stack,
        "spot": "UNOPENED",
        "preflop_context_id": pfc,
    }
    key = f"{POPULATION}|6|{position}|{stack:g}|UNOPENED|{pfc}"
    repository = {
        "schema": "poker-hero-range-repository/v1",
        "version": 1,
        "source": {"format": None, "preserved_verbatim": False, "meta": None, "range_folder": None},
        "defaults": {"population_id": POPULATION, "table_size": 6, "effective_stack_bb": 100},
        "contexts": {
            key: {
                "context": context,
                "layers": {
                    "personal": {"kind": "personal", "version": None, "provenance": None, "hands": {}},
                    "calculated": {
                        "kind": "calculated",
                        "version": "fixture-v1",
                        "provenance": {"fixture": True},
                        "hands": {
                            "AA": {
                                "actions": {"OPEN": 1.0},
                                "sizings": {"OPEN": [{"target_total_bb": 3.0, "probability": 1.0}]},
                                "notes": "fixture",
                            }
                        },
                    },
                },
            }
        },
    }
    run = {
        "schema": "poker-hero-range-decision-run/v1",
        "population_id": POPULATION,
        "version": f"fixture-{position}",
        "context_id": pfc,
        "legacy_context_id": spec.context_id,
        "canonical_preflop_context": canonical,
        "context": context,
        "rows": [{"hand_class": "AA", "decision": {}}],
        "unsupported": [{"hand_class": "KK", "reason": "fixture unsupported"}],
        "coverage": {"requested": 2, "completed": 1, "complete_169": False},
        "provenance": {
            "context_identity": {
                "schema": "poker-preflop-context/v1",
                "preflop_context_id": pfc,
                "legacy_context_id": spec.context_id,
                "binding": "IDENTITY_ONLY_FROM_SAME_PUBLIC_STATE_BEFORE_ACTION",
                "decision_payload_mutation": "NONE",
                "rollout_recomputation": False,
            }
        },
    }
    candidate = {
        "schema": "poker-hero-calculated-range-candidate/v1",
        "promotion_authorized": False,
        "repository": repository,
    }
    return run, candidate


def write_source(root: Path, name: str, position: str, stack: float = 100.0):
    run, candidate = fixture(position, stack)
    repository, binding = materialize(run, candidate, run_id=name)
    repo_path = root / f"{name}-repository.json"
    binding_path = root / f"{name}-binding.json"
    repo_path.write_bytes(canonical_json_bytes(repository))
    binding_path.write_bytes(canonical_json_bytes(binding))
    return repo_path, binding_path, run


def test_materialized_source_preserves_exact_pfc_and_no_holdout() -> None:
    run, candidate = fixture("BTN")
    repository, binding = materialize(run, candidate, run_id="fixture-btn")
    assert binding["preflop_context_id"] == run["canonical_preflop_context"]["context_id"]
    assert binding["coverage"] == {"requested": 2, "supported": 1, "unsupported": 1, "accounted": 2}
    assert binding["selection_boundary"]["validation_consumed"] is False
    assert binding["selection_boundary"]["test_consumed"] is False
    assert list(repository["contexts"].values())[0]["context"]["preflop_context_id"] == binding["preflop_context_id"]


def test_merge_builds_distinct_position_pfpc_bindings() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        btn_repo, btn_binding, btn_run = write_source(root, "btn", "BTN")
        co_repo, co_binding, co_run = write_source(root, "co", "CO")
        repository, binding, summary = merge_sources(
            [btn_repo, co_repo], [btn_binding, co_binding], run_id="multi-unopened-v1"
        )
        assert len(repository["contexts"]) == 2
        assert summary["policy_contexts"] == 2
        assert summary["supported_hand_slots"] == 2
        assert summary["unsupported_hand_slots"] == 2
        expected = {
            build_policy_context(btn_run["canonical_preflop_context"])["policy_context_id"],
            build_policy_context(co_run["canonical_preflop_context"])["policy_context_id"],
        }
        assert set(binding["bindings"]) == expected
        assert binding["nearest_context_substitution"] is False
        assert binding["selection_boundary"] == {"validation_consumed": False, "test_consumed": False}


def test_same_pfpc_two_source_representatives_fail_closed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        repo100, binding100, run100 = write_source(root, "btn100", "BTN", 100.0)
        repo80, binding80, run80 = write_source(root, "btn80", "BTN", 80.0)
        assert run100["canonical_preflop_context"]["context_id"] != run80["canonical_preflop_context"]["context_id"]
        assert (
            build_policy_context(run100["canonical_preflop_context"])["policy_context_id"]
            == build_policy_context(run80["canonical_preflop_context"])["policy_context_id"]
        )
        try:
            merge_sources(
                [repo100, repo80], [binding100, binding80], run_id="collision-v1"
            )
        except ValueError as exc:
            assert "PFPC collision" in str(exc)
        else:
            raise AssertionError("multiple representatives for one PFPC must fail closed")


def main() -> None:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"Hero policy-context source tests: {len(tests)} passed")


if __name__ == "__main__":
    main()

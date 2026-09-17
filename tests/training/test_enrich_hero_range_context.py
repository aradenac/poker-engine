#!/usr/bin/env python3
from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training.enrich_hero_range_context import (  # noqa: E402
    canonical_context_for_state,
    enrich_run,
)
from tools.training.generate_hero_range_decisions import (  # noqa: E402
    ContextSpec,
    build_context_state,
)


def fixture_run(spec: ContextSpec):
    return {
        "schema": "poker-hero-range-decision-run/v1",
        "status": "EXPERIMENTAL",
        "population_id": spec.population_id,
        "context": spec.repository_context(),
        "context_id": spec.context_id,
        "version": "fixture",
        "rows": [
            {
                "hand_class": "AA",
                "representative_cards": ["As", "Ah"],
                "decision": {
                    "schema": "fixture-decision-kept-byte-for-byte",
                    "action": "OPEN",
                    "target_total_bb": 3.0,
                    "ev_bb": 1.25,
                },
            }
        ],
        "unsupported": [],
        "coverage": {"requested": 1, "completed": 1, "complete_169": False},
        "provenance": {"master_seed": 20260916, "budget": {"rollouts": 42}},
    }


def test_unopened_context_gets_canonical_pfc_id() -> None:
    spec = ContextSpec(position="BTN", spot="UNOPENED", effective_stack_bb=100)
    enriched = enrich_run(fixture_run(spec), spec)
    assert enriched["context_id"].startswith("PFC_")
    assert len(enriched["context_id"]) == 20
    assert enriched["context"]["preflop_context_id"] == enriched["context_id"]
    assert enriched["canonical_preflop_context"]["context_id"] == enriched["context_id"]
    assert enriched["canonical_preflop_context"]["family"] == "UNOPENED"


def test_identity_enrichment_does_not_mutate_decision_or_budget() -> None:
    spec = ContextSpec(position="BTN", spot="UNOPENED")
    source = fixture_run(spec)
    before_rows = copy.deepcopy(source["rows"])
    before_budget = copy.deepcopy(source["provenance"]["budget"])
    enriched = enrich_run(source, spec)
    assert enriched["rows"] == before_rows
    assert enriched["provenance"]["budget"] == before_budget
    assert enriched["provenance"]["context_identity"]["decision_payload_mutation"] == "NONE"
    assert enriched["provenance"]["context_identity"]["rollout_recomputation"] is False


def test_different_rfi_openers_have_distinct_pfc_ids() -> None:
    lj = ContextSpec(position="BTN", spot="VS_RFI", opener_position="LJ", open_to_bb=2.5)
    co = ContextSpec(position="BTN", spot="VS_RFI", opener_position="CO", open_to_bb=2.5)
    lj_ctx = canonical_context_for_state(build_context_state(lj), "BTN")
    co_ctx = canonical_context_for_state(build_context_state(co), "BTN")
    assert lj_ctx["context_id"] != co_ctx["context_id"]
    assert lj_ctx["family"] == co_ctx["family"] == "VS_RFI"
    assert lj_ctx["history"] != co_ctx["history"]


def test_open_size_changes_canonical_identity() -> None:
    small = ContextSpec(position="BTN", spot="VS_RFI", opener_position="CO", open_to_bb=2.0)
    large = ContextSpec(position="BTN", spot="VS_RFI", opener_position="CO", open_to_bb=3.5)
    small_ctx = canonical_context_for_state(build_context_state(small), "BTN")
    large_ctx = canonical_context_for_state(build_context_state(large), "BTN")
    assert small_ctx["context_id"] != large_ctx["context_id"]
    assert small_ctx["to_call_bb"] != large_ctx["to_call_bb"]


def test_run_mismatch_fails_closed() -> None:
    spec = ContextSpec(position="BTN", spot="UNOPENED")
    wrong = fixture_run(spec)
    wrong["context"]["position"] = "CO"
    try:
        enrich_run(wrong, spec)
    except ValueError as exc:
        assert "position" in str(exc)
    else:
        raise AssertionError("mismatched run context must fail closed")


def main() -> None:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"Hero range PFC enrichment tests: {len(tests)} passed")


if __name__ == "__main__":
    main()

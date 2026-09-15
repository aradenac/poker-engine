#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HTML = (ROOT / "site/index.html").read_text(encoding="utf-8")
CONTRACT = (ROOT / "site/preflop-contract.js").read_text(encoding="utf-8")
SHARED_CONTRACT = (ROOT / "src/preflop/contract.js").read_text(encoding="utf-8")


def test_static_browser_artifact_is_exact_shared_source():
    # The browser still loads from site/, while Node/tool consumers import the
    # canonical source. Keeping the generated artifact byte-identical makes
    # this extraction behavior-neutral and prevents two implementations from
    # drifting apart.
    assert CONTRACT == SHARED_CONTRACT


def test_contract_loads_before_inline_analyser():
    external = HTML.index('<script src="./preflop-contract.js"></script>')
    inline = HTML.index('<script>', external)
    assert external < inline


def test_runtime_trace_attaches_canonical_before_action_context():
    start = HTML.index("function populationPreflopDecisionTrace(")
    end = HTML.index("function sameStringArray", start)
    trace = HTML[start:end]
    assert "contract.buildContext" in trace
    assert "preflop_context_v1:ctx" in trace
    assert "action_sizing_v1" in trace
    assert "incremental_cost_bb" in trace
    assert "target_total_bb" in trace
    assert "current_price_bb" in trace
    assert "to_call_bb" in trace
    assert "legal_actions" in trace
    assert "remaining_to_act_positions" in trace

    # The structural before-action trace may inspect stacks and prior monetary
    # state, but never known/showdown cards or the future board.
    for forbidden in ("knownCards", "heroCards", "showdown", ".board"):
        assert forbidden not in trace, f"future/card leakage in preflop trace: {forbidden}"


def test_incumbent_matcher_fields_remain_issue_88_projection():
    start = HTML.index("function findClosestPopulationNode(")
    end = HTML.index("function populationPolicyBaseLog", start)
    matcher = HTML[start:end]
    for required in (
        "c.table_size", "decision.table_size",
        "c.raise_level", "decision.raise_level",
        "c.family===decision.family",
        "c.live_positions", "decision.live_positions",
        "c.all_in_positions", "decision.all_in_positions",
        "historyExact",
    ):
        assert required in matcher, required
    # #88 retained the matcher without free_check.  The richer context has it,
    # but it must not silently alter exact selection.
    assert "free_check" not in matcher


def test_browser_contract_declares_before_action_and_probability_schemas():
    assert "poker-preflop-context/v1" in CONTRACT
    assert "poker-preflop-action-probabilities/v1" in CONTRACT
    assert "BEFORE_ACTION" in CONTRACT
    assert "runtime_signature_ignores_free_check:true" in CONTRACT


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
    print(f"site preflop contract tests: {len(tests)} passed")

#!/usr/bin/env python3
"""Explicit posterior-state contract for `populationRangeEstimateForPlayer` (#391).

This is a representation-layer contract only. It pins that:

- `posteriorState` is derived from the number of exploited public actions
  (`prior_uninformative` vs `conditioned`) and that zero surviving mass is an
  explicit `degenerate` (fail-closed) result;
- the silent re-seed from `legacyRangeEntriesForHistoryPlayer` on a failed
  conditioning normalization is gone;
- a uniform distribution is never re-wrapped as a 100 % relative-weight grid;
- public hero/board blockers stay applied and no opponent-private/future card is
  consumed.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX = (ROOT / "site/index.html").read_text(encoding="utf-8")


def section(start: str, end: str) -> str:
    return INDEX.split(start, 1)[1].split(end, 1)[0]


def main() -> None:
    estimate = section(
        "function populationRangeEstimateForPlayer(",
        "function legacyUnderlyingRangeEntriesForOpponent(",
    )
    display = section("function gridFreqMapFromEstimate(", "function resetSeatEquities(")
    export = section("function aiExportRangeSnapshot(", "function aiExportSeatEquityForStep(")
    matrix = section("function renderMatrix(", "function normalizePopulationPosition(")

    # posteriorState is computed from the exploited public actions only.
    assert "const informativeActions=preMatched+postMatched" in estimate
    assert 'const posteriorState=informativeActions>0?"conditioned":"prior_uninformative"' in estimate
    assert "informativeActions" in estimate

    # Zero surviving mass is explicit and fail-closed: no null return and no
    # silent re-seed from the imported legacy range.
    assert 'posteriorState:"degenerate"' in INDEX
    assert "function degenerateComboRangeResult(" in INDEX
    assert "degenerateReason" in estimate
    assert "state.postflopRangeCache[cacheKey]=null" not in estimate
    assert (
        "combos=exactComboPriorFromEntries(legacyRangeEntriesForHistoryPlayer(player),heroBlocked);\n      break;"
        not in estimate
    )
    assert 'degenerateReason="preflop_action_zero_mass"' in estimate
    assert 'degenerateReason="postflop_blockers_zero_mass"' in estimate
    assert 'degenerateReason="postflop_action_zero_mass"' in estimate
    assert 'degenerateReason=degenerateReason||"public_blockers_removed_all_mass"' in estimate

    # Public blockers stay applied; no opponent-private/future card is consumed.
    assert "filterComboBlockers(combos,[...heroBlocked,...d.board])" in estimate
    assert "filterComboBlockers(combos,[...heroBlocked,...currentBoard])" in estimate
    assert "knownCards" not in estimate

    # A uniform distribution keeps a mass projection instead of a 100 % grid.
    assert "const relativeWeightPctFor=uniformPrior?null:" in INDEX
    assert "relativeWeightPct:relativeWeightPctFor?relativeWeightPctFor(w):null" in INDEX

    # Display surfaces fail closed on a degenerate posterior.
    assert 'if(estimate?.posteriorState==="degenerate")return new Map();' in display
    assert 'const degenerate=estimate?.posteriorState==="degenerate";' in display
    assert "Posterior dégénéré" in display
    assert 'matrixPopulationEstimate?.posteriorState==="degenerate"' in matrix
    assert "gridEntries" in display and "gridEntries" in matrix
    assert 'posterior_state:estimate?.posteriorState||null' in export
    assert 'estimate?.posteriorState==="degenerate"?[]:' in export
    assert "const relativeWeightPct=estimate?.uniformPrior?null:" in export
    assert "relative_weight_pct:relativeWeightPct" in export
    assert "relative_weight_pct:aiExportNumber(100*(Number(c.weight)||0)/maxW,5)" not in export

    print("posterior state contract checks: OK")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Explicit posterior-state contract for `populationRangeEstimateForPlayer` (#391).

This is a representation-layer contract only. It pins that:

- `posteriorState` is derived from the number of exploited public actions
  (`conditioned` when at least one matched) plus the full-support uniformity of
  the kept prior (`prior_uninformative` only for a uniform prior covering every
  legal exact combo after the PUBLIC blockers, otherwise the distinct
  `source_prior_unconditioned`), and zero surviving mass is an explicit
  `degenerate` (fail-closed) result;
- the silent re-seed from `legacyRangeEntriesForHistoryPlayer` on a failed
  conditioning normalization is gone;
- a uniform distribution is never re-wrapped as a 100 % relative-weight grid;
- public hero/board blockers stay applied and no opponent-private/future card is
  consumed.
"""
from __future__ import annotations

import subprocess
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

    # posteriorState is computed from the exploited public actions plus the
    # full-support uniformity of the kept prior: at least one exploited action
    # => conditioned; zero action with a full-support uniform legal-combo prior
    # => prior_uninformative; zero action with any other imported/source prior
    # (non-uniform, or uniform over a strict subset) => the distinct
    # source_prior_unconditioned state (never prior_uninformative/degenerate).
    assert "const informativeActions=preMatched+postMatched" in estimate
    assert 'const posteriorState=informativeActions>0?"conditioned":(priorIsNonInformative(combos,[...heroBlocked,...currentBoard])?"prior_uninformative":"source_prior_unconditioned")' in estimate
    assert "informativeActions" in estimate
    assert "function priorIsNonInformative(combos,blockedCards,legalComboCount){" in INDEX
    assert "return (combos||[]).length===count;" in INDEX
    assert 'const posteriorState=meta.posteriorState||(informativeActions>0?"conditioned":(nonInformativePrior?"prior_uninformative":"source_prior_unconditioned"))' in INDEX

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

    # Display surfaces fail closed on a degenerate posterior, and render both
    # zero-action priors as explicit states (uniform => prior_uninformative,
    # non-uniform imported/source => source_prior_unconditioned).
    assert 'if(estimate?.posteriorState==="degenerate")return new Map();' in display
    assert 'if(estimate?.posteriorState==="prior_uninformative")return new Map();' in display
    assert 'if(estimate?.posteriorState==="source_prior_unconditioned")return new Map();' in display
    assert 'const degenerate=estimate?.posteriorState==="degenerate";' in display
    assert 'const sourcePriorUnconditioned=estimate?.posteriorState==="source_prior_unconditioned";' in display
    assert "const hasNumericGrid=!!estimate&&!degenerate&&!uninformative&&!sourcePriorUnconditioned;" in display
    assert "Posterior dégénéré" in display
    assert 'matrixPopulationEstimate?.posteriorState==="degenerate"' in matrix
    assert 'const sourcePriorUnconditioned=matrixPopulationEstimate?.posteriorState==="source_prior_unconditioned";' in matrix
    assert 'matrixNotion="source_prior_unconditioned";entries=[];' in matrix
    assert matrix.index('matrixNotion="source_prior_unconditioned";entries=[];') < matrix.index("matrixEntries.some(e=>e.relativeWeightPct!=null)")
    assert 'matrixNotion==="source_prior_unconditioned"' in matrix
    assert "gridEntries" in display and "gridEntries" in matrix
    assert 'posterior_state:estimate?.posteriorState||null' in export
    assert 'estimate?.posteriorState==="degenerate"?[]:' in export
    assert 'estimate?.posteriorState==="source_prior_unconditioned"?"source_prior_unconditioned"' in export
    assert "const relativeWeightPct=estimate?.uniformPrior?null:" in export
    assert "relative_weight_pct:relativeWeightPct" in export
    assert "relative_weight_pct:aiExportNumber(100*(Number(c.weight)||0)/maxW,5)" not in export

    # The diagnostic relative-weight grid never falls back to the canonical
    # frequency/mass when the relative weight is undefined: it is absent (null)
    # for a uniform prior or when no entry carries a relativeWeightPct.
    assert "const relativeDefined=estimate?.uniformPrior!==true&&entries.some(e=>e.relativeWeightPct!=null);" in export
    assert "let gridRelative=null;" in export
    assert "gridRelative=Object.create(null);" in export
    assert "frequency:Number(e.relativeWeightPct)||0" in export
    old_relative_fallback = "frequency:e.relativeWeightPct!=null?Number(e.relativeWeightPct):(Number(e.frequency)||0)"
    assert old_relative_fallback not in export
    assert old_relative_fallback not in matrix
    assert "matrixEntries.some(e=>e.relativeWeightPct!=null)" in matrix

    # Point 3 (#391): `rangeEntriesForHistoryPlayer` must never substitute the
    # legacy imported range for a degenerate population estimate. The legacy
    # fallback is reachable only when no estimate exists at all (no model /
    # historical imported path); a degenerate estimate returns [] so every
    # equity/EV/tree consumer fails closed on zero length instead of silently
    # re-seeding the imported range.
    history_range = section(
        "function rangeEntriesForHistoryPlayer(",
        "function resetSeatEquities(",
    )
    assert 'if(estimated.posteriorState==="degenerate") return [];' in history_range
    assert "const estimated=populationRangeEstimateForPlayer(player,replayIndex);" in history_range
    assert "if(estimated){" in history_range
    assert "if(estimated.entries?.length) return estimated.entries;" in history_range
    # The legacy fallback is the unconditional final return: it is reached only
    # after the `if(estimated){...}` early returns, i.e. only when no estimate
    # record exists (no population model / historical imported path).
    estimated_idx = history_range.index("if(estimated){")
    legacy_idx = history_range.index("return legacyRangeEntriesForHistoryPlayer(player);")
    assert estimated_idx < legacy_idx
    assert history_range.rfind("return legacyRangeEntriesForHistoryPlayer(player);") == legacy_idx
    # Inside the estimate branch there is no legacy substitution: empty entries
    # fail closed with [].
    estimate_branch = history_range.split("if(estimated){", 1)[1].split("\n  }", 1)[0]
    assert "return [];" in estimate_branch
    assert "return legacyRangeEntriesForHistoryPlayer" not in estimate_branch

    # Downstream equity/EV/tree consumers fail closed on a zero-length range:
    # they return null / skip rather than re-seeding or emitting a 100 % value.
    assert "if(!hands.length)return null;" in INDEX  # buildActionScenarioPlayers
    assert "if(!rangeHands.length)return null;" in INDEX  # buildActionScenarioPlayers
    assert "if(!actorHands.length)return null;" in INDEX  # postflopRaiseTreeSnapshot
    assert "if(!baseEntries.length)continue;" in INDEX  # postflopRaiseTreeSnapshot responder
    assert "if(!priorEntries.length)return null;" in INDEX  # postflopFoldSelectedRange
    assert "if(players.length===0||players.some(p=>!p.hands.length))return null;" in INDEX  # tableEquitySnapshotForStep
    assert "const hasRange=rangeHands.length>0;" in INDEX  # buildSeatEquityPlayers
    assert "hasRange[p.name]=rangeEntriesForHistoryPlayer(p,replayIndex).length>0;" in INDEX  # updateSeatEquityMeta

    # Executable proof: the production `rangeEntriesForHistoryPlayer` extracted
    # from site/index.html returns [] for a degenerate estimate and never reaches
    # the legacy imported-range fallback, while no estimate at all keeps it.
    subprocess.run(
        ["node", "tests/trainer/degenerate_legacy_failclose_runtime.js"],
        cwd=ROOT,
        check=True,
    )

    print("posterior state contract checks: OK")


if __name__ == "__main__":
    main()

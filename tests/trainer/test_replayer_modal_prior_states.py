#!/usr/bin/env python3
"""Replayer range-modal contract for the non-informative/degenerate states (#391).

This is a representation/display contract only. It pins that the replayer range
modal:

- replaces the numeric 169 grid with an explicit state for
  `prior_uninformative`, `source_prior_unconditioned` and `degenerate`, and never
  renders a 100 % grid for a uniform prior;
- displays the canonical mass projection (`projectCombosTo169Mass` through
  `estimate.gridEntries`) for a conditioned posterior;
- uses one and the same mass notion for the grid, the exact-combo list and the
  delta panel, so every legend describes the value actually displayed;
- has no remaining silent fallback to `legacyRangeEntriesForHistoryPlayer` for
  the grid rendering, and no « 100 % = poids relatif maximal » label.

It does not touch the model/fit or the equity consumers.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX = (ROOT / "site/index.html").read_text(encoding="utf-8")


def section(start: str, end: str) -> str:
    return INDEX.split(start, 1)[1].split(end, 1)[0]


def main() -> None:
    modal = section("function openPopulationRangeModal(", "populationRangeModalClose?.addEventListener")
    grid_fn = section("function gridFreqMapFromEstimate(", "function openPopulationRangeModal(")
    mass_fn = section("function massGridFreqMapFromEstimate(", "function gridFreqMapFromEstimate(")
    export = section("function aiExportRangeSnapshot(", "function aiExportSeatEquityForStep(")

    # The three explicit states return no numeric grid; the conditioned state uses
    # the canonical mass projection carried by estimate.gridEntries.
    assert 'if(estimate?.posteriorState==="degenerate")return new Map();' in grid_fn
    assert 'if(estimate?.posteriorState==="prior_uninformative")return new Map();' in grid_fn
    assert 'if(estimate?.posteriorState==="source_prior_unconditioned")return new Map();' in grid_fn
    # `prior_uninformative` is reserved for the full-support uniform prior over
    # the legal combos after the public hero/board blockers; the derivation uses
    # the dedicated `priorIsNonInformative` predicate.
    assert "function priorIsNonInformative(combos,blockedCards,legalComboCount){" in INDEX
    assert "massGridFreqMapFromEstimate(estimate)" in grid_fn
    assert "estimate?.gridEntries?.length?estimate.gridEntries:[]" in mass_fn
    assert "projectCombosTo169Mass" in mass_fn
    # No silent fallback to the legacy imported range for the grid rendering.
    assert "legacyRangeEntriesForHistoryPlayer" not in grid_fn
    assert "legacyRangeEntriesForHistoryPlayer" not in modal

    # The modal gates the numeric grid on the posterior state.
    assert 'const uninformative=estimate?.posteriorState==="prior_uninformative";' in modal
    assert 'const sourcePriorUnconditioned=estimate?.posteriorState==="source_prior_unconditioned";' in modal
    assert "const hasNumericGrid=!!estimate&&!degenerate&&!uninformative&&!sourcePriorUnconditioned;" in modal
    assert "const grid=hasNumericGrid?" in modal

    # Dedicated explicit states are rendered instead of the 169 grid.
    assert "Posterior dégénéré · masse nulle après blockers publics" in modal
    assert "Prior non informatif · range non estimée" in modal
    assert "Prior source non conditionné · range importée non conditionnée" in modal

    # Every legend describes the displayed mass value: grid, combo list and delta.
    assert "projection 169 (masse)" in modal
    assert "Pourcentage = masse probabiliste" in modal
    assert "Variation en points de masse probabiliste (projection 169)" in modal
    assert "100 % = poids relatif maximal" not in modal
    assert "poids relatif" not in modal

    # The delta compares the same mass notion as the grid and is only shown when
    # both steps have a numeric mass projection.
    assert "massGridFreqMapFromEstimate(prev.estimate)" in modal
    assert "const deltaVisible=hasNumericGrid&&!!prevFreq&&prevFreq.size>0;" in modal
    assert "deltaVisible?ALL_NOTATIONS.map" in modal

    # The export keeps the canonical mass projection for the 169 grid.
    assert "grid_169_probability_pct" in export

    print("replayer modal prior-state contract checks: OK")


if __name__ == "__main__":
    main()

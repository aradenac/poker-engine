#!/usr/bin/env python3
"""Distinct `source_prior_unconditioned` state contract (#391).

Representation-layer contract only. It pins that a non-uniform imported/source
prior kept with zero matched public action is a distinct explicit state:

- `source_prior_unconditioned`, never `prior_uninformative` (reserved for a
  uniform legal-combo prior) and never `degenerate`;
- present in `OPPONENT_RANGE_DISPLAY_CONTRACT.posterior_states`;
- rendered by the replayer modal/export with its own label, never as a numeric
  169 grid and never as a 100 % range.

The runtime half extracts the real functions from `site/index.html` and proves
the derivation and the fail-closed UI behaviour on a deliberately non-uniform
imported prior. It does not touch the model/fit or the equity consumers.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX = (ROOT / "site/index.html").read_text(encoding="utf-8")


def section(start: str, end: str) -> str:
    return INDEX.split(start, 1)[1].split(end, 1)[0]


def main() -> None:
    contract = section("const OPPONENT_RANGE_DISPLAY_CONTRACT=Object.freeze({", "const state = {")
    estimate = section(
        "function populationRangeEstimateForPlayer(",
        "function legacyUnderlyingRangeEntriesForOpponent(",
    )
    combo_result = section(
        "function exactComboRangeResult(",
        "function degenerateComboRangeResult(",
    )
    grid_fn = section("function gridFreqMapFromEstimate(", "function openPopulationRangeModal(")
    modal = section("function openPopulationRangeModal(", "populationRangeModalClose?.addEventListener")
    export = section("function aiExportRangeSnapshot(", "function aiExportSeatEquityForStep(")
    matrix = section("function renderMatrix(", "function normalizePopulationPosition(")

    # 1. The state is part of the versioned display contract.
    assert '"source_prior_unconditioned"' in contract, contract
    assert (
        'posterior_states:Object.freeze(["prior_uninformative","source_prior_unconditioned","conditioned","degenerate"])'
        in INDEX
    )

    # 2. The derivation reserves prior_uninformative for a truly uniform prior.
    assert (
        'const posteriorState=informativeActions>0?"conditioned":(comboWeightsAreUniform(combos)?"prior_uninformative":"source_prior_unconditioned")'
        in estimate
    )
    assert (
        'const posteriorState=meta.posteriorState||(informativeActions>0?"conditioned":(uniformPrior?"prior_uninformative":"source_prior_unconditioned"))'
        in combo_result
    )

    # 3. UI: explicit state, no numeric grid, never a 100 % range.
    assert 'if(estimate?.posteriorState==="source_prior_unconditioned")return new Map();' in grid_fn
    assert 'const sourcePriorUnconditioned=estimate?.posteriorState==="source_prior_unconditioned";' in modal
    assert "const hasNumericGrid=!!estimate&&!degenerate&&!uninformative&&!sourcePriorUnconditioned;" in modal
    assert "Prior source non conditionné · range importée non conditionnée" in modal
    assert modal.count("Prior source non conditionné · range importée non conditionnée") >= 2
    assert "jamais un posterior conditionné" in modal or "ni un posterior conditionné" in modal
    assert "Aucune grille 169 n’est affichée" in modal

    # The calculator matrix also keeps this state textual. In particular, its
    # branch runs before the relative-weight path and supplies no numeric entry,
    # so a max-normalized source class can never surface as 100 %.
    source_matrix_branch = 'else if(sourcePriorUnconditioned){\n      // Keep this state textual:'
    assert 'const sourcePriorUnconditioned=matrixPopulationEstimate?.posteriorState==="source_prior_unconditioned";' in matrix
    assert source_matrix_branch in matrix
    assert 'matrixNotion="source_prior_unconditioned";entries=[];' in matrix
    assert matrix.index(source_matrix_branch) < matrix.index('matrixEntries.some(e=>e.relativeWeightPct!=null)')
    assert 'matrixNotion==="source_prior_unconditioned"' in matrix
    source_title_branch = matrix.split('matrixNotion==="source_prior_unconditioned"', 1)[1].split("}else{", 1)[0]
    assert "100" not in source_title_branch
    assert "%" not in source_title_branch
    assert "range source importée non conditionnée" in source_title_branch

    # 4. Export carries the distinct state and never labels it as conditioned.
    assert 'posterior_state:estimate?.posteriorState||null' in export
    assert 'estimate?.posteriorState==="source_prior_unconditioned"?"source_prior_unconditioned"' in export

    # 5. Runtime proof on a deliberately non-uniform imported prior with zero
    #    matched public action.
    subprocess.run(
        ["node", "tests/trainer/source_prior_unconditioned_runtime.js"],
        cwd=ROOT,
        check=True,
    )

    print("source prior unconditioned contract checks: OK")


if __name__ == "__main__":
    main()

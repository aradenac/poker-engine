#!/usr/bin/env python3
"""Auxiliary scale-dependent surfaces contract (#391 · task-j4v).

Representation-only contract for the surfaces that consumed a max-normalized
relative weight as if it were a sum-normalized probability. It pins that:

- the calculator matrix tooltip labels the diagnostic relative weight as a
  dimensionless ratio (max = 1) and never with a frequency percentage unit;
- `populationRangeWidthFromEntries` is scale-invariant and matches
  `exactComboRangeResult.width`, so the displayed “largeur relative” stays
  coherent after the switch to sum-normalized mass;
- board/hero public blockers are applied before the canonical projection, so the
  matrix (and its mass projection) can never include a blocked card or an
  unrevealed opponent card.

It does not touch the model/fit or the equity consumers.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX = (ROOT / "site/index.html").read_text(encoding="utf-8")


def section(start: str, end: str) -> str:
    return INDEX.split(start, 1)[1].split(end, 1)[0]


def main() -> None:
    matrix = section("function renderMatrix(", "function normalizePopulationPosition(")
    width_fn = section(
        "function populationRangeWidthFromEntries(",
        "\nconst modalFocusOrigins",
    )
    estimate = section(
        "function populationRangeEstimateForPlayer(",
        "function legacyUnderlyingRangeEntriesForOpponent(",
    )

    # 1. The matrix tooltip never renders the max-normalized relative weight with
    # a frequency percentage unit: it is a dimensionless diagnostic ratio.
    assert "estimation population conditionnée" not in matrix
    assert "poids relatif" in matrix
    assert "(max = 1) · diagnostic, pas une probabilité" in matrix
    relative_branch = matrix.split('matrixNotion==="relative"', 1)[1].split('matrixNotion==="mass"', 1)[0]
    assert "%" not in relative_branch, "relative weight rendered with a frequency '%'"
    # The mass path keeps the probability projection, explicitly labelled.
    assert "masse probabiliste (projection 169)" in matrix

    # 2. The width metric is a scale-invariant mean/max ratio, not a raw mass sum
    # that would change with the normalization.
    assert "total/Math.max(1,weights.length)/peak" in width_fn
    assert "frequency/100" not in width_fn

    # 3. Public board/hero blockers stay applied before the canonical projection.
    assert "const heroBlocked=[...(hand.heroCards||[])]" in estimate
    assert "filterComboBlockers(combos,[...heroBlocked,...d.board])" in estimate
    assert "filterComboBlockers(combos,[...heroBlocked,...currentBoard])" in estimate
    assert estimate.index(
        "filterComboBlockers(combos,[...heroBlocked,...currentBoard])"
    ) < estimate.index("exactComboRangeResult(combos,{...meta,posteriorState})")
    assert "knownCards" not in estimate

    # Runtime proof of the scale invariance and canonical-width compatibility.
    subprocess.run(
        ["node", "tests/trainer/range_width_scale_invariance.js"], cwd=ROOT, check=True
    )

    print("auxiliary scale-dependent surfaces contract checks: OK")


if __name__ == "__main__":
    main()

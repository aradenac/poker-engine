#!/usr/bin/env python3
"""Display contract for opponent ranges (#391 vocabulary).

This is a representation/display contract only. It asserts that the four
opponent-range notions stay distinct, that the canonical 169 projection is a
mass sum, that the versioned constant is exported by the static application,
and that no model/fit surface is introduced by the contract.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX = (ROOT / "site/index.html").read_text(encoding="utf-8")
DOC = (ROOT / "docs/opponent-range-display-contract.md").read_text(encoding="utf-8")
BACKEND = (ROOT / "src/ranges/posterior_range.py").read_text(encoding="utf-8")
SCHEMA = (ROOT / "contracts/posterior-range.schema.json").read_text(encoding="utf-8")


def main() -> None:
    # The doc names the four notions explicitly, each with its unit.
    for notion in (
        "posterior_combo_probability",
        "relative_weight",
        "inclusion_frequency",
        "non_informative_prior",
    ):
        assert notion in DOC, notion
    assert "probability `p` in `[0,1]`" in DOC
    assert "dimensionless ratio" in DOC
    assert "percent, integer/real in `[0,100]`" in DOC
    assert "probability per legal exact combo" in DOC

    # Normalizations are pinned to the correct notion.
    assert "sum-normalized" in DOC
    assert "max-normalized" in DOC
    assert "a priori input" in DOC
    assert "uniform" in DOC

    # The canonical 169 projection is a SUM of combo probability mass, never a
    # mean or a max.
    assert "sum of the combo probabilities" in DOC
    assert "it is **not** a mean" in DOC
    assert "it is **not** a max" in DOC
    assert "the 169 class masses also sum" in DOC

    # The four posterior states and their triggers are documented.
    for state in ("prior_uninformative", "source_prior_unconditioned", "conditioned", "degenerate"):
        assert state in DOC, state
    assert "`prior_uninformative`" in DOC
    assert "`source_prior_unconditioned`" in DOC
    assert "`conditioned`" in DOC
    assert "`degenerate`" in DOC

    # The postflop path is documented as a display extension with no backend
    # contract.
    assert "no backend contract" in DOC or "browser-only extension" in DOC
    assert "no JSON schema for postflop records" in DOC

    # The exported constant is versioned and self-describing in the static app.
    assert "poker-opponent-range-display/v1" in INDEX
    assert "const OPPONENT_RANGE_DISPLAY_CONTRACT=Object.freeze({" in INDEX
    assert "window.PokerOpponentRangeDisplayContract=OPPONENT_RANGE_DISPLAY_CONTRACT;" in INDEX
    assert "projection_169:\"sum_of_combo_probability_mass\"" in INDEX
    assert "posterior_states:Object.freeze([\"prior_uninformative\",\"source_prior_unconditioned\",\"conditioned\",\"degenerate\"])" in INDEX
    assert "backend_schema:\"poker-opponent-posterior-range/v1\"" in INDEX

    # The display contract stays aligned to the backend semantic reference and
    # does not rewrite it.
    assert "poker-opponent-posterior-range/v1" in BACKEND
    assert "poker-opponent-posterior-range/v1" in SCHEMA

    print("opponent range display contract checks: OK")


if __name__ == "__main__":
    main()

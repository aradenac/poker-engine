#!/usr/bin/env python3
"""Documentation contract for the displayed opponent-range semantics (#391 T11).

This pins that the backend documents
(`docs/posterior-range-contract.md`, `docs/model-a-posterior-runtime.md`) stay
coherent with the versioned display contract of T1
(`docs/opponent-range-display-contract.md`, `poker-opponent-range-display/v1`)
and with the semantic reference `src/ranges/posterior_range.py`:

- the four notions are named and kept distinct;
- the canonical 169 projection is a sum of combo probability mass;
- the `posteriorState` states and their backend correspondence are documented;
- the Replayer UI mapping is explicit and references real surfaces.

It is a documentation/representation contract only and changes no model/fit.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_DOC = (ROOT / "docs/posterior-range-contract.md").read_text(encoding="utf-8")
MODEL_DOC = (ROOT / "docs/model-a-posterior-runtime.md").read_text(encoding="utf-8")
DISPLAY_DOC = (ROOT / "docs/opponent-range-display-contract.md").read_text(encoding="utf-8")
BACKEND = (ROOT / "src/ranges/posterior_range.py").read_text(encoding="utf-8")
SCHEMA = (ROOT / "contracts/posterior-range.schema.json").read_text(encoding="utf-8")
INDEX = (ROOT / "site/index.html").read_text(encoding="utf-8")

NOTIONS = (
    "posterior_combo_probability",
    "relative_weight",
    "inclusion_frequency",
    "non_informative_prior",
)
STATES = ("prior_uninformative", "conditioned", "degenerate")
def flat(text: str) -> str:
    """Collapse markdown line wrapping so phrase assertions are stable."""
    return " ".join(text.split())


REPLAYER_SURFACES = (
    "populationRangeEstimateForPlayer",
    "projectCombosTo169Mass",
    "gridFreqMapFromEstimate",
    "massGridFreqMapFromEstimate",
    "openPopulationRangeModal",
    "aiExportRangeSnapshot",
    "knownHandOverride",
)


def main() -> None:
    # The backend docs name all four notions and keep them distinct.
    for notion in NOTIONS:
        assert notion in BACKEND_DOC, notion
        assert notion in DISPLAY_DOC, notion
    assert "sum-normalized" in BACKEND_DOC
    assert "max-normalized" in BACKEND_DOC
    assert "never a probability" in BACKEND_DOC
    assert "not conditioned on observed actions" in BACKEND_DOC

    # The 169 projection is documented as a mass sum, not a mean/max.
    backend_flat = flat(BACKEND_DOC)
    assert "sum of the exact-combo probabilities" in backend_flat
    assert "it is not a mean and not a max" in backend_flat
    assert "the 169 class masses also sum to `1`" in backend_flat

    # The three posterior states and their backend correspondence are documented.
    for state in STATES:
        assert state in BACKEND_DOC, state
    assert "status = AVAILABLE" in BACKEND_DOC
    assert "UNSUPPORTED, INVALID" in BACKEND_DOC
    assert "A concentrated but `AVAILABLE` posterior is not `degenerate`" in BACKEND_DOC

    # The Replayer mapping is explicit and every referenced surface exists.
    assert "Replayer UI mapping" in BACKEND_DOC
    for surface in REPLAYER_SURFACES:
        assert surface in BACKEND_DOC, surface
        assert surface in INDEX, surface
    assert "Prior non informatif · range non estimée" in BACKEND_DOC
    assert "Posterior dégénéré · masse nulle après blockers publics" in BACKEND_DOC
    assert "Prior non informatif · range non estimée" in INDEX
    assert "Posterior dégénéré · masse nulle après blockers publics" in INDEX

    # The Model A hand-off explains the UNCONDITIONED_COMBO_PRIOR state mapping.
    assert "UNCONDITIONED_COMBO_PRIOR" in MODEL_DOC
    assert "EXACT_NODE_HISTORY" in MODEL_DOC
    for state in STATES:
        assert state in MODEL_DOC, state
    assert "Displayed semantics and Replayer hand-off" in MODEL_DOC
    assert "docs/opponent-range-display-contract.md" in MODEL_DOC
    assert "Displayed semantics and Replayer UI mapping" in BACKEND_DOC
    assert "docs/opponent-range-display-contract.md" in BACKEND_DOC

    # The display contract surfaces the Replayer mapping too.
    assert "Replayer surfaces" in DISPLAY_DOC

    # No divergence with the backend semantic reference.
    assert "poker-opponent-posterior-range/v1" in BACKEND_DOC
    assert "poker-opponent-posterior-range/v1" in BACKEND
    assert "poker-opponent-posterior-range/v1" in SCHEMA
    assert "poker-opponent-range-display/v1" in DISPLAY_DOC
    assert "probability_mass" in BACKEND_DOC and "probability_mass" in BACKEND
    assert "projection_169" in BACKEND_DOC and "projection_169" in BACKEND
    assert "output_mass" in BACKEND_DOC and "output_mass" in BACKEND
    # The doc's "mass sums to 1" claim matches the projector's output-mass check.
    assert "math.isclose(output_mass, 1.0" in BACKEND
    assert "classes[combo_class_ids(*combo)] += weight" in BACKEND
    assert "projectCombosTo169Mass(combos)" in INDEX
    assert "grid_169_probability_pct:gridProbability" in INDEX

    print("range display docs contract checks: OK")


if __name__ == "__main__":
    main()

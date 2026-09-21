#!/usr/bin/env python3
"""Integration anti-regression contract for the four #391 opponent-range fixes.

This module is the single, versioned integration contract that pins the four
semantic corrections of the opponent-range rework together, so a regression of
one fix cannot hide behind a green per-fix contract:

1. ``prior_uninformative`` is full-support-uniform-only. The state is derived
   from ``priorIsNonInformative``: the kept weights must be uniform
   (``comboWeightsAreUniform``) **and** the support must cover every legal exact
   combo after the PUBLIC hero/board blockers. A non-uniform prior, or a uniform
   prior over a strict subset, with zero matched public action is never
   relabelled ``prior_uninformative``.
2. The distinct ``source_prior_unconditioned`` state is present end to end:
   exported in ``OPPONENT_RANGE_DISPLAY_CONTRACT.posterior_states``, derived by
   ``populationRangeEstimateForPlayer`` / ``exactComboRangeResult``, and rendered
   by the replayer modal, the calculator matrix and the snapshot export as its
   own label (never a conditioned posterior, never a numeric 169 grid, never a
   100 % range).
3. For a uniform prior ``grid_169_relative_weight_pct`` is ``null``/empty (and
   each combo's ``relative_weight_pct`` is ``null``); the max-normalized
   diagnostic is never derived from the canonical sum-normalized mass.
4. A degenerate posterior has no silent legacy fallback:
   ``rangeEntriesForHistoryPlayer`` returns ``[]`` instead of re-seeding the
   imported range, and every downstream equity/EV/tree consumer fails closed.
5. The display contract documents that ``entries[].frequency`` carries the
   sum-normalized probability-mass semantics of notion (a) in the conditioned
   engine, distinct from the ``relativeWeightPct`` diagnostic.

The runtime halves of corrections 1/2/4 are proven by executing the production
functions extracted from ``site/index.html``. This is a representation-layer
contract only: no model/fit, no equity semantics, no immutable repro evidence and
no frozen workflow is touched.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX = (ROOT / "site/index.html").read_text(encoding="utf-8")
DOC = (ROOT / "docs/opponent-range-display-contract.md").read_text(encoding="utf-8")

CONTRACT_VERSION = "poker-opponent-range-semantics-rework-contract/v1"

# The four zero/one-shot states of the display contract. The two zero-action
# states must stay distinct, and `prior_uninformative` must stay uniform-only.
POSTERIOR_STATES = (
    "prior_uninformative",
    "source_prior_unconditioned",
    "conditioned",
    "degenerate",
)

# Legacy relative-weight fallback that would substitute the canonical mass for an
# undefined diagnostic. It must not exist anywhere in the display code.
LEGACY_RELATIVE_FALLBACK = "frequency:e.relativeWeightPct!=null?Number(e.relativeWeightPct):(Number(e.frequency)||0)"


def section(start: str, end: str) -> str:
    return INDEX.split(start, 1)[1].split(end, 1)[0]


def flat(text: str) -> str:
    """Collapse markdown line wrapping so phrase assertions are stable."""
    return " ".join(text.split())


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
    degenerate = section(
        "function degenerateComboRangeResult(",
        "function populationRangeEstimateForPlayer(",
    )
    grid_fn = section("function gridFreqMapFromEstimate(", "function openPopulationRangeModal(")
    modal = section("function openPopulationRangeModal(", "populationRangeModalClose?.addEventListener")
    export = section("function aiExportRangeSnapshot(", "function aiExportSeatEquityForStep(")
    matrix = section("function renderMatrix(", "function normalizePopulationPosition(")
    history_range = section("function rangeEntriesForHistoryPlayer(", "function resetSeatEquities(")
    doc_flat = flat(DOC)

    # The four states are exported as one frozen versioned list, so the two
    # zero-action states can never be merged or renamed.
    states_row = (
        'posterior_states:Object.freeze(["prior_uninformative",'
        '"source_prior_unconditioned","conditioned","degenerate"])'
    )
    assert states_row in contract, states_row
    for state in POSTERIOR_STATES:
        assert f'"{state}"' in contract, state

    # ------------------------------------------------------------------
    # Correction 1 (#391 · Point 1): prior_uninformative is uniform-only AND
    # full-support.
    # ------------------------------------------------------------------
    # The production derivation only picks `prior_uninformative` when the kept
    # legal-combo prior is uniform AND covers every legal exact combo after the
    # public hero/board blockers; otherwise it is the distinct
    # `source_prior_unconditioned` (never `prior_uninformative`).
    assert (
        'const posteriorState=informativeActions>0?"conditioned":'
        '(priorIsNonInformative(combos,[...heroBlocked,...currentBoard])?"prior_uninformative":"source_prior_unconditioned")'
        in estimate
    ), estimate
    assert "const uniformPrior=comboWeightsAreUniform(combos);" in combo_result
    assert (
        'const nonInformativePrior=priorIsNonInformative(combos,meta.blockedCards,meta.legalComboCount);'
        in combo_result
    )
    assert (
        'const posteriorState=meta.posteriorState||(informativeActions>0?"conditioned":'
        '(nonInformativePrior?"prior_uninformative":"source_prior_unconditioned"))'
        in combo_result
    ), combo_result
    # Uniformity is defined from the positive legal-combo weights, and full
    # support from the number of legal exact combos after the public blockers,
    # not from the number of actions.
    assert "function comboWeightsAreUniform(combos){" in INDEX
    assert "if(Math.abs(w-ref)>1e-9*Math.max(1,Math.abs(ref)))return false;" in INDEX
    assert "function priorIsNonInformative(combos,blockedCards,legalComboCount){" in INDEX
    assert "if(!comboWeightsAreUniform(combos))return false;" in INDEX
    assert "return (combos||[]).length===count;" in INDEX
    assert "uniformExactComboPrior(blockedCards||[]).length" in INDEX
    # UI: a uniform full-support prior is an explicit non-numeric state.
    assert 'if(estimate?.posteriorState==="prior_uninformative")return new Map();' in grid_fn
    # Docs: the trigger explicitly requires a full-support uniform kept prior.
    assert "the kept prior is the full-support uniform prior over the legal exact combos" in doc_flat

    # ------------------------------------------------------------------
    # Correction 2 (#391 · Point 2): distinct source/imported unconditioned state.
    # ------------------------------------------------------------------
    # Derivation: zero matched actions + non-full-support kept prior => distinct
    # state (this covers both a non-uniform prior and a uniform strict subset).
    assert (
        'const posteriorState=informativeActions>0?"conditioned":'
        '(priorIsNonInformative(combos,[...heroBlocked,...currentBoard])?"prior_uninformative":"source_prior_unconditioned")'
        in estimate
    )
    # UI: no numeric grid, never a conditioned posterior, never a 100 % range.
    assert 'if(estimate?.posteriorState==="source_prior_unconditioned")return new Map();' in grid_fn
    assert 'const sourcePriorUnconditioned=estimate?.posteriorState==="source_prior_unconditioned";' in modal
    assert 'const sourcePriorUnconditioned=matrixPopulationEstimate?.posteriorState==="source_prior_unconditioned";' in matrix
    assert "const hasNumericGrid=!!estimate&&!degenerate&&!uninformative&&!sourcePriorUnconditioned;" in modal
    source_label = "Prior source non conditionné · range importée non conditionnée"
    assert modal.count(source_label) >= 2, modal.count(source_label)
    assert source_label in doc_flat
    # The dedicated explanation rejects both other states and shows no grid.
    assert "la range source importée (non uniforme) est conservée telle quelle, sans conditionnement" in modal
    assert "Ce n’est ni le prior uniforme non informatif ni un posterior conditionné" in modal
    assert "aucune grille 169 n’est affichée" in modal
    # Matrix keeps the state textual (empty entries) and never derives a 100 %
    # diagnostic from the source mass; this branch runs before the relative path.
    source_matrix_branch = 'else if(sourcePriorUnconditioned){'
    assert source_matrix_branch in matrix
    assert 'matrixNotion="source_prior_unconditioned";entries=[];' in matrix
    assert matrix.index(source_matrix_branch) < matrix.index(
        "matrixEntries&&matrixEntries.some(e=>e.relativeWeightPct!=null)"
    )
    assert 'matrixNotion==="source_prior_unconditioned"' in matrix
    source_title_branch = matrix.split('matrixNotion==="source_prior_unconditioned"', 1)[1].split("}else{", 1)[0]
    assert "100" not in source_title_branch
    assert "%" not in source_title_branch
    assert "range source importée non conditionnée" in source_title_branch
    # Export carries the distinct state and never labels it conditioned.
    assert "posterior_state:estimate?.posteriorState||null" in export
    assert (
        'estimate?.posteriorState==="source_prior_unconditioned"?"source_prior_unconditioned"'
        in export
    )
    # Docs name the state and keep it distinct from the uniform prior.
    assert "`source_prior_unconditioned`" in doc_flat
    assert "never assimilates it to the conditioned posterior" in doc_flat

    # ------------------------------------------------------------------
    # Correction 3 (#391 · Point 2): relative grid null/empty unless the
    # posterior is conditioned (and its weights are non-uniform).
    # ------------------------------------------------------------------
    # Per combo: the diagnostic is defined only for a conditioned, non-uniform
    # posterior. It is absent for `prior_uninformative` and
    # `source_prior_unconditioned` (max-normalizing a uniform distribution would
    # wrap every legal combo at 100 %).
    assert 'const relativeWeightPctFor=(posteriorState==="conditioned"&&!uniformPrior)?' in combo_result
    assert "relativeWeightPct:relativeWeightPctFor?relativeWeightPctFor(w):null" in combo_result
    assert 'const relativeWeightDefined=estimate?.posteriorState==="conditioned"&&estimate?.uniformPrior!==true;' in export
    assert "const relativeWeightPct=relativeWeightDefined?" in export
    assert "relative_weight_pct:relativeWeightPct" in export
    assert "relative_weight_pct:aiExportNumber(100*(Number(c.weight)||0)/maxW,5)" not in export
    # 169 grid: absent (null) unless the posterior is conditioned and an entry
    # carries a relativeWeightPct. The canonical mass is never substituted.
    assert (
        "const relativeDefined=relativeWeightDefined"
        "&&entries.some(e=>e.relativeWeightPct!=null);" in export
    )
    assert "let gridRelative=null;" in export
    assert "gridRelative=Object.create(null);" in export
    assert "frequency:Number(e.relativeWeightPct)||0" in export
    assert "grid_169_relative_weight_pct:gridRelative" in export
    assert LEGACY_RELATIVE_FALLBACK not in export
    # Matrix: no numeric grid for the two unconditioned priors, and the numeric
    # relative/mass paths are gated on a conditioned posterior.
    assert 'const priorUninformative=matrixPopulationEstimate?.posteriorState==="prior_uninformative";' in matrix
    assert 'const conditioned=matrixPopulationEstimate?.posteriorState==="conditioned";' in matrix
    assert 'matrixNotion="prior_uninformative";entries=[];' in matrix
    assert "else if(conditioned&&matrixEntries&&matrixEntries.some(e=>e.relativeWeightPct!=null)){" in matrix
    assert "else if(conditioned&&matrixPopulationEstimate?.gridEntries?.length){" in matrix
    # No unconditional massGrid branch remains reachable by a uniform prior.
    assert "const massGrid=matrixPopulationEstimate?.uniformPrior" not in matrix
    assert 'matrixNotion==="prior_uninformative"' in matrix
    prior_title_branch = matrix.split('matrixNotion==="prior_uninformative"', 1)[1].split(
        'matrixNotion==="degenerate"', 1
    )[0]
    assert "100" not in prior_title_branch
    assert "%" not in prior_title_branch
    assert "aucune valeur numérique affichée" in prior_title_branch
    # Matrix also refuses to fall back from relativeWeightPct to the mass.
    assert "matrixEntries&&matrixEntries.some(e=>e.relativeWeightPct!=null)" in matrix
    assert "matrixEntries.filter(e=>e.relativeWeightPct!=null)" in matrix
    assert 'matrixNotion="relative";' in matrix
    assert LEGACY_RELATIVE_FALLBACK not in matrix
    # Docs: `null`/empty diagnostic, distinct from the canonical mass projection.
    assert "grid_169_relative_weight_pct" in doc_flat
    assert "`null`/empty" in doc_flat
    assert "the diagnostic is never derived from the canonical mass" in doc_flat

    # ------------------------------------------------------------------
    # Correction 4 (#391 · Point 3): no legacy fallback for a degenerate posterior.
    # ------------------------------------------------------------------
    # Zero surviving mass is explicit and fail-closed.
    assert 'posteriorState:"degenerate"' in degenerate
    assert "entries:[],gridEntries:[]" in degenerate
    assert 'degenerateReason:meta.degenerateReason||"no_positive_mass_after_public_blockers"' in degenerate
    assert 'if(estimate?.posteriorState==="degenerate")return new Map();' in grid_fn
    assert 'const degenerate=estimate?.posteriorState==="degenerate";' in modal
    assert 'matrixPopulationEstimate?.posteriorState==="degenerate"' in matrix
    assert 'matrixNotion="degenerate";entries=[];' in matrix
    # `rangeEntriesForHistoryPlayer` must never substitute the imported legacy
    # range for a degenerate estimate: it returns [] inside the estimate branch,
    # and the legacy fallback is the unconditional final return reached only when
    # no estimate record exists at all.
    assert "const estimated=populationRangeEstimateForPlayer(player,replayIndex);" in history_range
    assert 'if(estimated.posteriorState==="degenerate") return [];' in history_range
    assert "if(estimated){" in history_range
    assert "if(estimated.entries?.length) return estimated.entries;" in history_range
    estimated_idx = history_range.index("if(estimated){")
    legacy_idx = history_range.index("return legacyRangeEntriesForHistoryPlayer(player);")
    assert estimated_idx < legacy_idx
    assert history_range.rfind("return legacyRangeEntriesForHistoryPlayer(player);") == legacy_idx
    estimate_branch = history_range.split("if(estimated){", 1)[1].split("\n  }", 1)[0]
    assert "return [];" in estimate_branch
    assert "return legacyRangeEntriesForHistoryPlayer" not in estimate_branch
    # Export fails closed too (no exact combos, degenerate posterior_state).
    assert 'estimate?.posteriorState==="degenerate"?[]:' in export
    # Downstream equity/EV/tree consumers fail closed on a zero-length range
    # instead of re-seeding or emitting a 100 % value.
    assert "if(!hands.length)return null;" in INDEX
    assert "if(!rangeHands.length)return null;" in INDEX
    assert "if(!actorHands.length)return null;" in INDEX
    assert "if(!baseEntries.length)continue;" in INDEX
    assert "if(!priorEntries.length)return null;" in INDEX
    assert "players.some(p=>!p.hands.length)" in INDEX
    assert "const hasRange=rangeHands.length>0;" in INDEX
    # Docs: the postflop trigger names the fail-closed behaviour.
    assert "silent re-seed from the imported legacy range" in doc_flat

    # ------------------------------------------------------------------
    # Correction 5 (#391 · Point 4): docs pin the mass semantics of frequency.
    # ------------------------------------------------------------------
    mass_phrase = (
        "the numeric field `entries[].frequency` is reused by the conditioned "
        "exact-combo engine in `exactComboRangeResult`, where it carries the "
        "**sum-normalized probability mass** semantics of notion (a)"
    )
    assert mass_phrase in doc_flat, mass_phrase
    assert "entries[].relativeWeightPct" in doc_flat
    assert "sum-normalized probability mass" in doc_flat
    # The projection stays a sum, and the relative diagnostic never substitutes
    # the canonical probability projection.
    assert "projection_169:\"sum_of_combo_probability_mass\"" in INDEX
    assert "grid_169_probability_pct:gridProbability" in export
    assert "grid_169_probability_pct" in doc_flat

    # ------------------------------------------------------------------
    # Runtime proof: execute the production functions extracted from the app.
    # ------------------------------------------------------------------
    for script in (
        "tests/trainer/source_prior_unconditioned_runtime.js",
        "tests/trainer/degenerate_legacy_failclose_runtime.js",
    ):
        subprocess.run(["node", script], cwd=ROOT, check=True)

    print(f"{CONTRACT_VERSION} checks: OK")


if __name__ == "__main__":
    main()

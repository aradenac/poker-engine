#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX = (ROOT / "site/index.html").read_text(encoding="utf-8")


def section(start: str, end: str) -> str:
    return INDEX.split(start, 1)[1].split(end, 1)[0]


def main() -> None:
    key_points = section('function actionDetailKeyPointsHtml(args){', 'function actionRetrospectivePanelHtml(args){')
    retrospective = section('function actionRetrospectivePanelHtml(args){', 'function foldRangeAnalysisHtml(stepIndex,decisionSummary){')
    modal = section('function actionDetailModalInnerHtml(stepIndex,step){', 'function openActionDetailModal(stepIndex){')

    # Main verdict path is strictly prior-only.
    assert 'priorEq' in key_points
    assert 'priorMetrics' in key_points
    assert 'priorTree' in key_points
    for forbidden in ('postEq', 'postMetrics', 'postTree'):
        assert forbidden not in key_points, forbidden
    assert 'Frontière d’information.' in key_points
    assert 'sources.prior' in key_points

    # Future/revealed-card information has one explicitly retrospective surface.
    assert 'Analyse rétrospective / cartes révélées' in retrospective
    assert 'Information future — hors verdict.' in retrospective
    assert 'n’entre jamais dans la recommandation' in retrospective
    assert 'sources.post' in retrospective

    # Recommendation and canonical delta are still built from prior only.
    assert 'postflopDecisionAlternativeSummary(stepIndex,priorEq,cached)' in modal
    assert 'decisionCanonicalSummary(stepIndex,step,cached)' in modal
    assert 'const retrospective=actionRetrospectivePanelHtml' in modal
    assert modal.index('${primary}${retrospective}') < modal.index('<details class="action-advanced">')
    assert 'actionSingleEquityHtml(eq,sources.prior' in modal
    assert 'actionEquityValuesHtml(' not in modal

    # Raw exports retain both views with explicit labels.
    export = section('function aiExportActionAnalysisForStep(stepIndex){', 'function aiExportAnalysisProgress(){')
    assert 'prior_used:aiExportNumber(priorEq)' in export
    assert 'posterior_used:aiExportNumber(postEq)' in export
    assert 'scenario_sources:aiExportPlain(sources)' in export
    assert 'Posterior/real-hand fields may use cards only known after the decision' in INDEX

    # ---- Displayed semantics of the estimated opponent range (#391) ----
    # The canonical 169 projection is a SUM of combo probability mass. The
    # non-informative prior, the unconditioned source prior and the degenerate
    # posterior are explicit text states rendered in place of a numeric grid,
    # never a max-normalized 100 % range; the `knownHandOverride` flag is the only
    # single-class 100 % surface.
    range_modal = section('function openPopulationRangeModal(', 'populationRangeModalClose?.addEventListener')
    grid_fn = section('function gridFreqMapFromEstimate(', 'function openPopulationRangeModal(')
    projection = section('function projectCombosTo169Mass(', 'function uniformExactComboPrior(')
    combo_result = section('function exactComboRangeResult(', 'function degenerateComboRangeResult(')
    range_export = section('function aiExportRangeSnapshot(', 'function aiExportSeatEquityForStep(')
    display_contract = section('const OPPONENT_RANGE_DISPLAY_CONTRACT=Object.freeze({', 'const state = {')

    # Explicit non-informative / unconditioned-source / degenerate states: clear
    # vocabulary and no numeric grid, so a uniform prior can never read as a 100 %
    # range and a non-uniform imported prior is never assimilated to a posterior.
    assert 'Prior non informatif · range non estimée' in range_modal
    assert range_modal.count('Prior non informatif · range non estimée') >= 2
    assert 'Prior source non conditionné · range importée non conditionnée' in range_modal
    assert range_modal.count('Prior source non conditionné · range importée non conditionnée') >= 2
    assert 'Posterior dégénéré · masse nulle après blockers publics' in range_modal
    assert 'Aucune grille 169 n’est affichée.' in range_modal
    assert 'if(estimate?.posteriorState==="degenerate")return new Map();' in grid_fn
    assert 'if(estimate?.posteriorState==="prior_uninformative")return new Map();' in grid_fn
    assert 'if(estimate?.posteriorState==="source_prior_unconditioned")return new Map();' in grid_fn

    # Every legend of the grid, the combo list and the delta panel describes the
    # same displayed probability mass.
    for legend in (
        'projection 169 (masse)',
        'Chaque classe = somme des probabilités de ses combos légaux (masse probabiliste, somme = 100 %).',
        'Pourcentage = masse probabiliste après normalisation de tous les combos légaux (somme = 100 %).',
        'Variation en points de masse probabiliste (projection 169).',
    ):
        assert legend in range_modal, legend

    # The misleading max-normalized label is gone, and the canonical output is
    # the sum-normalized mass projection, never a division by the maximum weight.
    assert '100 % = poids relatif maximal' not in INDEX
    assert 'poids relatif maximal' not in INDEX
    assert 'w/total' in projection and 'maxWeight' not in projection
    assert 'gridEntries:projectCombosTo169Mass(combos)' in combo_result
    assert 'const relativeWeightPctFor=uniformPrior?null:' in combo_result
    assert 'return massGridFreqMapFromEstimate(estimate);' in grid_fn
    assert 'const freq=gridFreqMapFromEstimate(estimate,player);' in range_modal
    assert 'normalizeComboWeightsInPlace' not in range_modal
    assert 'normalizeComboWeightsToMass(combos)' in combo_result
    assert 'const p=(Number(c.weight)||0)/total;' in range_export
    assert 'probability_pct:aiExportNumber(100*p,7)' in range_export
    assert 'grid_169_probability_pct:gridProbability' in range_export
    assert 'gridProbability[e.hand]=aiExportNumber(e.frequency,7)' in range_export
    # A uniform prior (or any estimate without a defined relativeWeightPct)
    # exports no relative-weight projection: the mass is never substituted.
    assert 'const relativeDefined=estimate?.uniformPrior!==true&&entries.some(e=>e.relativeWeightPct!=null);' in range_export
    assert 'let gridRelative=null;' in range_export

    # The known-hand override is a separate, explicitly flagged mechanism: it is
    # the only legitimate 100 % single-class display and never a posterior.
    assert 'flag:"knownHandOverride"' in display_contract
    assert 'merge_with_posterior:false' in display_contract
    assert 'knownHandOverride:true' in INDEX
    assert 'function knownHandOverrideEntry(cards){' in INDEX
    assert 'data-known-hand-override="true"' in range_modal
    assert 'seul cas légitime' in range_modal
    assert 'Override main connue · mécanisme séparé du posterior.' in range_modal

    print('prior/posterior UI boundary checks: OK')


if __name__ == '__main__':
    main()

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

    print('prior/posterior UI boundary checks: OK')


if __name__ == '__main__':
    main()

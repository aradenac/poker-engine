#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
INDEX=(ROOT/"site/index.html").read_text(encoding="utf-8")


def main() -> int:
    assert "function replayActionActorRole(step)" in INDEX
    assert "function replayOpponentCommentStateFromEvidence" in INDEX
    assert "function replayOpponentCommentState(stepIndex,step)" in INDEX
    assert "function replayHeroCommentState(stepIndex,step,cached" in INDEX
    assert 'data-comment-actor="HERO"' in INDEX
    assert 'data-comment-actor="OPPONENT"' in INDEX
    assert "SPOT_NON_COUVERT" in INDEX
    assert "Aucune recommandation EV validée pour ce contexte" in INDEX
    assert "OPPONENT_ANALYZABLE" in INDEX
    assert "OPPONENT_SUPPORT_INSUFFICIENT" in INDEX
    assert "OPPONENT_ANALYSIS_UNAVAILABLE" in INDEX
    assert "Analyse adverse non disponible pour ce contexte" in INDEX
    assert "Support insuffisant pour estimer cette action" in INDEX
    assert "Aucune alternative EV validée" not in INDEX

    opponent=INDEX.split("function replayOpponentCommentStateFromEvidence",1)[1].split("function replayOpponentCommentState(stepIndex,step)",1)[0]
    assert "population_decisions" in opponent
    assert "preflop_context_v1" in opponent
    for forbidden in ("populationRangeEstimateForPlayer(", "populationPreflopRangeEstimateForPlayer(", "finalDecisionEV(", "postflopDecisionAlternativeSummary("):
        assert forbidden not in opponent, forbidden

    hero=INDEX.split("function replayHeroCommentState",1)[1].split("function replayOpponentCommentHtml",1)[0]
    assert 'canonicalDecision?.schema==="decision-summary/v1"' in hero
    assert 'source_contract:"preflop-call-fold-baseline"' in hero
    assert "observedEvidence===undefined?replayObservedDecisionEvidence" in hero
    assert "VS_LIMPERS" not in hero
    assert "VS_ISO" not in hero

    feed=INDEX.split("function actionAnalysisHtml",1)[1].split("function safeActionAnalysisHtml",1)[0]
    assert 'if(replayActionActorRole(step)==="OPPONENT")return replayOpponentCommentHtml(stepIndex,step);' in feed
    assert "decisionCanonicalSummary" in feed
    assert "HERO · RECOMMANDATION_VALIDÉE" in feed

    modal=INDEX.split("function actionDetailModalInnerHtml",1)[1].split("function openActionDetailModal",1)[0]
    assert 'if(replayActionActorRole(step)==="OPPONENT")return replayOpponentCommentHtml(stepIndex,step,{detail:true});' in modal
    assert "alternative EV Hero" not in modal

    print("replayer actor/comment semantics contract: PASS")
    return 0


if __name__=="__main__":
    raise SystemExit(main())

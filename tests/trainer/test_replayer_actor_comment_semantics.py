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
    assert "OPPONENT_NODE_ABSENT" in INDEX
    assert "OPPONENT_ANALYSIS_UNAVAILABLE" in INDEX
    assert "Analyse adverse non disponible pour ce contexte" in INDEX
    assert "Aucun nœud de population pour cette action observée" in INDEX
    assert "Support insuffisant pour estimer cette action" in INDEX
    assert "Aucune alternative EV validée" not in INDEX

    # #393 T5: the Hero comment derives its primary state/label from the shared
    # `poker-analysis-state/v1` module while the historical actor states stay as
    # the actor dimension.
    assert '<script src="./analytics/analysis-state.js"></script>' in INDEX
    assert "window.PokerAnalysisState" in INDEX
    assert "Module.mapAnalysisState" in INDEX
    assert "function heroAnalysisStateFromActor(actorState" in INDEX
    assert "function heroAnalysisStateFromDecision(decision){" in INDEX
    assert "actor_state:actorState" in INDEX
    assert "taxonomy_label:heroTaxonomyLabel(taxonomy_state)" in INDEX
    assert "admissible,ev_comparable," in INDEX

    opponent=INDEX.split("function replayOpponentCommentStateFromEvidence",1)[1].split("function replayOpponentCommentState(stepIndex,step)",1)[0]
    assert "population_decisions" in opponent
    assert "preflop_context_v1" in opponent
    # The opponent comment never computes a Hero EV; the range availability is
    # read from the cached #391 posterior representation (#393 T6 / rule D5).
    for forbidden in ("populationPreflopRangeEstimateForPlayer(", "finalDecisionEV(", "postflopDecisionAlternativeSummary("):
        assert forbidden not in opponent, forbidden

    # #393 T6 / rule D5: the three precise opponent causes are mapped onto the
    # shared taxonomy, the observed action + support/likelihood + range
    # before/after are exposed, and no EV alternative is promised.
    opponent_t6=INDEX.split("const OPPONENT_ACTOR_ANALYSIS_INPUT=",1)[1].split("function heroCommentView(",1)[0]
    assert 'OPPONENT_ANALYZABLE:{coverage_state:"COVERED"}' in opponent_t6
    assert 'OPPONENT_SUPPORT_INSUFFICIENT:{reason_codes:["INSUFFICIENT_SUPPORT"]}' in opponent_t6
    assert 'OPPONENT_NODE_ABSENT:{reason_codes:["NODE_ABSENT"]}' in opponent_t6
    assert "Module.mapAnalysisState(input)" in opponent_t6
    assert "const state=analysis?.state||actorState;" in opponent_t6
    assert "actor_state:actorState" in opponent_t6
    assert "function replayOpponentRangeAvailability(stepIndex,step){" in opponent_t6
    assert "populationRangeEstimateForPlayer(player,Math.max(0,Number(idx)||0))" in opponent_t6
    assert "read(idx-1)" in opponent_t6 and "read(idx)" in opponent_t6
    assert "input.posterior_availability=posterior" in opponent_t6
    assert "range_before:availability.before" in opponent_t6
    assert "range_after:availability.after" in opponent_t6
    for forbidden in ("finalDecisionEV(", "postflopDecisionAlternativeSummary(", "recommended_ev_bb", "EV optimale"):
        assert forbidden not in opponent_t6, forbidden

    opp_html=INDEX.split("function replayOpponentCommentHtml(",1)[1].split("function actionDetailKeyPointsHtml(",1)[0]
    assert "action observée" in opp_html
    assert "support " in opp_html
    assert "range avant" in opp_html and "après" in opp_html
    assert "Aucune recommandation ni alternative EV Hero n’est appliquée" in opp_html
    assert "EV optimale" not in opp_html

    hero=INDEX.split("function replayHeroCommentState",1)[1].split("function replayOpponentCommentHtml",1)[0]
    assert 'canonicalDecision?.schema==="decision-summary/v1"' in hero
    assert 'source_contract:"preflop-call-fold-baseline"' in hero
    assert "observedEvidence===undefined?replayObservedDecisionEvidence" in hero
    assert "VS_LIMPERS" not in hero
    assert "VS_ISO" not in hero

    feed=INDEX.split("function actionAnalysisHtml",1)[1].split("function safeActionAnalysisHtml",1)[0]
    assert 'if(replayActionActorRole(step)==="OPPONENT")return replayOpponentCommentHtml(stepIndex,step);' in feed
    assert "decisionCanonicalSummary" in feed
    # Feed: taxonomy label only; no raw reason codes.
    assert "heroPrimaryPillHtml(heroState" in feed
    assert "heroState.taxonomy_label" in feed
    assert "reason_codes" not in feed
    assert 'data-comment-state="${escapeHtml(heroState.state)}"' in feed

    modal=INDEX.split("function actionDetailModalInnerHtml",1)[1].split("function openActionDetailModal",1)[0]
    assert 'if(replayActionActorRole(step)==="OPPONENT")return replayOpponentCommentHtml(stepIndex,step,{detail:true});' in modal
    assert "alternative EV Hero" not in modal
    # Detail: the technical dimensions/reason codes live here.
    assert "heroAnalysisDimensionsHtml(view.analysis)" in INDEX
    assert 'data-analysis-detail="1"' in INDEX

    print("replayer actor/comment semantics contract: PASS")
    return 0


if __name__=="__main__":
    raise SystemExit(main())

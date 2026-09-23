#!/usr/bin/env python3
"""Replayer Hero analysis-state contract (#393 T5).

The Replayer Hero surface must derive its user-facing state from the shared
`poker-analysis-state/v1` module (#393 T2) instead of inventing a local label.
This contract pins:

- the shared module is loaded before every consumer;
- `replayHeroCommentState` translates each historical actor state into the
  module input dimensions and returns the canonical taxonomy state as `state`;
- the feed only renders the taxonomy label, while the reason codes and the
  separated technical dimensions are emitted by `preflopDecisionDetailHtml`
  (the modal detail);
- rule D6: the Hero EV/recommendation fields are only rendered when the module
  reports `recommendation_admissibility.admissible` AND
  `ev_comparability.comparable`;
- a complete postflop `decision-summary/v1` synthesis feeds the shared taxonomy
  dimensions (coverage COVERED + admissible + comparable) so the D6 EV gate
  opens, while an incomplete synthesis stays fail-safe.

The runtime halves (`tests/trainer/replayer_analysis_state_runtime.js` and
`tests/trainer/postflop_decision_summary_runtime.js`) extract the real functions
from `site/index.html` and prove every Hero transition (admissible, partiel, non
supporté, en cours, erreur), the pending and worker error cases, the VS_LIMPERS
unsupported spot and a complete canonical decision, plus the postflop
present-when-admissible-and-comparable / absent-otherwise D6 behaviour rendered
through `actionAnalysisHtml` and `actionDetailModalInnerHtml`.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX = (ROOT / "site/index.html").read_text(encoding="utf-8")


def section(start: str, end: str) -> str:
    assert start in INDEX, f"missing section start: {start}"
    body = INDEX.split(start, 1)[1]
    assert end in body, f"missing section end: {end}"
    return body.split(end, 1)[0]


def main() -> None:
    # 1. The shared module is loaded before every consumer (Inbox, Trainer, ...).
    module_tag = '<script src="./analytics/analysis-state.js"></script>'
    assert module_tag in INDEX
    assert INDEX.index(module_tag) < INDEX.index('<script src="./analytics/review-inbox.js"></script>')
    assert INDEX.index(module_tag) < INDEX.index('<script src="./trainer.js"></script>')

    helpers = section("const HERO_ACTOR_ANALYSIS_INPUT=Object.freeze({", "function preflopDecisionCompactHtml(")
    hero = section("function heroCommentView(", "function replayOpponentCommentHtml(")
    compact = section("function preflopDecisionCompactHtml(", "function preflopDecisionDetailHtml(")
    detail = section("function preflopDecisionDetailHtml(", "function replayOpponentCommentStateFromEvidence(")
    feed = section("function actionAnalysisHtml(", "function safeActionAnalysisHtml(")

    # 2. Every historical Hero transition is mapped through the shared module.
    for actor_state in (
        "HERO_COVERED",
        "HERO_BASELINE_VALIDATED",
        "HERO_ALTERNATIVES_NON_COMPARABLES",
        "HERO_PENDING",
        "HERO_ANALYSIS_ERROR",
        "SPOT_NON_COUVERT",
        "HERO_RECOMMENDATION_UNAVAILABLE",
    ):
        assert actor_state in helpers, actor_state
    assert "window.PokerAnalysisState" in helpers
    assert "Module.mapAnalysisState" in helpers
    assert "function heroAnalysisStateFromDecision(decision){" in helpers
    # The canonical preflop decision dimensions are fed to the module untouched.
    assert "Module.mapAnalysisState(decision)" in helpers
    # The primary returned state is the shared taxonomy state.
    assert "state:taxonomy_state" in hero
    assert "taxonomy_state," in hero and "taxonomy_label:heroTaxonomyLabel" in hero
    assert "admissible,ev_comparable," in hero
    assert "show_ev:admissible&&ev_comparable" in hero

    # 3. The feed renders the taxonomy label; reason codes stay in the detail.
    assert "heroPrimaryPillHtml(heroState" in feed
    assert "heroState.taxonomy_label" in feed
    assert 'actionCompactPillHtml(`HERO · ${escapeHtml(heroState.taxonomy_label)}`' in feed
    assert "data-comment-state=\"${escapeHtml(heroState.state)}\"" in feed
    assert "reason_codes" not in compact, "the feed/compact view must not expose raw reason codes"
    assert "heroAnalysisDimensionsHtml" in detail
    assert 'data-analysis-detail="1"' in helpers
    assert "analysis.reason_codes" in helpers
    assert "heroAnalysisDimensionsHtml(view.analysis)" in detail

    # 4. Rule D6 gates the preflop decision EV/recommendation fields.
    assert "if(!view.show_ev){" in compact
    assert "Aucune recommandation EV validée" in compact
    assert "recommended_action" in compact  # only reached inside the show_ev branch
    assert "recommended_ev_bb" in compact
    assert "if(!view.show_ev){" in detail
    assert "heroState.show_ev" in feed

    # 5. The runtime half proves each transition against the shared enum.
    proc = subprocess.run(
        ["node", "tests/trainer/replayer_analysis_state_runtime.js"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert '"status":"PASS"' in proc.stdout, proc.stdout + proc.stderr
    assert '"schema":"poker-analysis-state/v1"' in proc.stdout, proc.stdout

    # 6. The postflop canonical summary feeds the shared taxonomy dimensions so
    #    the D6 gate opens on a complete synthesis, and stays fail-safe otherwise.
    assert "function decisionSummaryTaxonomyDimensions(complete){" in INDEX
    assert "function decisionCanonicalSummary(stepIndex,step,cached=null)" in INDEX
    taxonomy = section("function decisionSummaryTaxonomyDimensions(", "function decisionCanonicalSummary(")
    assert 'coverage_state:"COVERED"' in taxonomy
    assert "recommendation_admissibility:{admissible:true,status:\"ADMISSIBLE\",reason_codes:[]}" in taxonomy
    assert "ev_comparability:{comparable:true,reason:null}" in taxonomy
    assert 'NON_COMPARABLE_ALTERNATIVES' in taxonomy
    canonical = section("function decisionCanonicalSummary(", "const DecisionActionSizingEV=window.PokerActionSizingEV;")
    assert "const complete=!!best&&ordered.length>=2&&Number.isFinite(bestEV)&&Number.isFinite(playedEV);" in canonical
    assert "recommended:complete?normalize(best,true):null" in canonical
    assert "...decisionSummaryTaxonomyDimensions(complete)" in canonical

    # The client-facing runtime proof renders the postflop decision-summary/v1
    # through the real feed and modal, present iff admissible+comparable.
    postflop = subprocess.run(
        ["node", "tests/trainer/postflop_decision_summary_runtime.js"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert '"status":"PASS"' in postflop.stdout, postflop.stdout + postflop.stderr
    assert '"ANALYSE_DISPONIBLE"' in postflop.stdout, postflop.stdout
    assert '"ANALYSE_PARTIELLE"' in postflop.stdout, postflop.stdout
    assert '"actionAnalysisHtml"' in postflop.stdout, postflop.stdout
    assert '"actionDetailModalInnerHtml"' in postflop.stdout, postflop.stdout

    print("replayer Hero analysis-state contract: PASS")


if __name__ == "__main__":
    main()

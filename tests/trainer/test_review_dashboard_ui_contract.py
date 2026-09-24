#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

PAIRS = (
    ("src/analytics/leak-training-target.js", "site/analytics/leak-training-target.js"),
    ("src/analytics/review-dashboard.js", "site/analytics/review-dashboard.js"),
)

def main() -> None:
    for source, runtime in PAIRS:
        source_text = (ROOT / source).read_text(encoding="utf-8")
        runtime_text = (ROOT / runtime).read_text(encoding="utf-8")
        assert runtime_text == source_text, (source, runtime)

    index = (ROOT / "site/index.html").read_text(encoding="utf-8")
    target_pos = index.index('<script src="./analytics/leak-training-target.js"></script>')
    dashboard_pos = index.index('<script src="./analytics/review-dashboard.js"></script>')
    assert target_pos < dashboard_pos

    assert 'Dashboard.buildReviewDashboard' in index
    assert 'function reviewDashboardSourceScores()' in index
    assert 'if(score&&score.signature===sig)out[id]=score;' in index
    assert 'complete:false,analyzableDecisions:0' not in index[index.index('function reviewDashboardSourceScores()'):index.index('function reviewDashboardBuild()')]
    assert 'Leak.analyzeLeaks' not in index
    assert 'PokerReviewDashboard' in index
    assert 'NO_HANDS' in index
    assert 'ANALYSIS_PENDING' in index
    assert 'ANALYSIS_INCOMPLETE' in index
    assert 'NO_SIGNIFICANT_LOSS' in index
    assert 'READY' in index

    # #393 T4: the Dashboard derives its dominant scope state from the shared
    # poker-analysis-state taxonomy and exposes the explicit French label as the
    # primary surface, while the technical reason codes stay in the secondary
    # details view (tooltip), never as the primary message.
    assert 'model?.analysis_state_label' in index
    assert 'reviewDashboardState.dataset.analysisState=' in index
    assert 'taxonomy?.reason_codes' in index
    assert 'Raisons techniques' in index
    for state in (
        "ANALYSE_DISPONIBLE",
        "ANALYSE_PARTIELLE",
        "CALCUL_EN_COURS",
        "DONNEES_INSUFFISANTES",
        "SPOT_NON_SUPPORTE",
        "ERREUR_CALCUL",
    ):
        assert state in index, state

    schema = json.loads(
        (ROOT / "contracts/analytics/review-dashboard.schema.json").read_text(encoding="utf-8")
    )
    taxonomy = schema["$defs"]["analysis_state"]
    assert set(taxonomy["properties"]["state"]["enum"]) == {
        "ANALYSE_DISPONIBLE",
        "ANALYSE_PARTIELLE",
        "CALCUL_EN_COURS",
        "DONNEES_INSUFFISANTES",
        "SPOT_NON_SUPPORTE",
        "ERREUR_CALCUL",
    }
    # The embedded taxonomy must not drift from the canonical shared schema.
    canonical = json.loads(
        (ROOT / "contracts/analytics/analysis-state.schema.json").read_text(encoding="utf-8")
    )
    assert taxonomy["properties"]["state"]["enum"] == canonical["properties"]["state"]["enum"]
    assert (
        taxonomy["properties"]["computational_status"]["enum"]
        == canonical["properties"]["computational_status"]["enum"]
    )
    assert (
        taxonomy["properties"]["statistical_support"]["properties"]["availability"]["enum"]
        == canonical["properties"]["statistical_support"]["properties"]["availability"]["enum"]
    )
    assert schema["properties"]["analysis_state_label"]["enum"] == [
        "Analyse disponible",
        "Analyse partielle",
        "Calcul en cours",
        "Données insuffisantes",
        "Spot non supporté",
        "Erreur de calcul",
        None,
    ]
    mapping = schema["properties"]["state"]["description"]
    for pair in ("NO_HANDS", "ANALYSIS_PENDING", "ANALYSIS_INCOMPLETE", "NO_SIGNIFICANT_LOSS", "READY"):
        assert pair in mapping, pair

    # #393 T5: the explicit empty-state -> taxonomy mapping is exported by the
    # shared dashboard module, and every precise French message is present in the
    # UI, so no screen can collapse two derivable causes into a single generic
    # message. The technical codes stay documented as a secondary field.
    dashboard_js = (ROOT / "src/analytics/review-dashboard.js").read_text(encoding="utf-8")
    assert "EMPTY_STATE_REASON_CODES" in dashboard_js
    assert "INCOMPLETE_SUPPORT_SHORTAGE" in dashboard_js
    for code in ("NO_HANDS", "ANALYSIS_PENDING", "ANALYSIS_INCOMPLETE", "NO_SIGNIFICANT_LOSS", "READY"):
        assert code + ":['" in dashboard_js, code
    assert "EMPTY_STATE_REASON_CODES" in schema["$defs"]["analysis_state"]["properties"]["reason_codes"]["description"]
    for message in (
        "Analyse partielle ·",
        "Données insuffisantes ·",
        "Calcul en cours ·",
        "Spot non supporté ·",
        "Erreur de calcul ·",
    ):
        assert message in index, message

    assert 'return openReviewInboxDeepLink(cta.target);' in index
    assert 'target.dimension!=="spot_family"' in index
    assert 'UNSUPPORTED_LEAK_DIMENSION' in index
    assert 'String(target.scope_key)!==String(model.scope_key)' in index
    assert 'reviewDashboardTrainingBtn.hidden=!trainingEnabled' in index
    assert 'if(!cta?.enabled||!cta.target)' in index
    assert 'trainerOpenBtn?.click();' in index

    # Dashboard and inbox consume the same population-bound Review scope derived
    # from the Hero strategy resolver, never a hard-coded "Custom" identity.
    assert 'scope:reviewInboxScopeInput()' in index
    assert 'reviewScopeFromResolution' in index
    assert 'UNAVAILABLE_STRATEGY' in index
    assert 'hero-custom' not in index
    # The dashboard inherits the contextual override status carried by the shared
    # Review scope (same value as the Trainer/header chip).
    assert 'override:productPersonalOverrideState()' in index

    # #394 T3/T1: the dashboard is the "Pilotage" pane of the Review view, which it
    # shares with the import surface and the review inbox only. The Replayer is a
    # distinct view reached from Review and it hands back to Review
    # ("← Retour à la Review") with the selected hand preserved, without any manual
    # tool leaking into Review.
    review_view = index.split('<div id="mainPage"', 1)[1].split('<div id="strategyPage"', 1)[0]
    assert 'id="reviewDashboard"' in review_view
    assert 'id="historiesSection"' in review_view and 'id="handSelectionSection"' in review_view
    for manual_id in ("opponentsSection", "cardsSection", "rangeDisplaySection", "equitySection"):
        assert f'id="{manual_id}"' not in review_view, manual_id
    assert 'data-view-shell="review"' in index and 'data-view-shell="replayer"' in index
    assert '← Retour à la Review' in index
    assert 'replayerBackBtn?.addEventListener("click",returnToHandsPage);' in index

    # The generic one-click destinations remain independent from gated dashboard CTAs.
    home = index.split('<div class="actions product-home-actions"', 1)[1].split('</div>', 1)[0]
    for label in ("Review", "Training", "Strategy", "Equity Lab"):
        assert label in home, (label, home)

    print("review dashboard UI contract checks: OK")

if __name__ == "__main__":
    main()

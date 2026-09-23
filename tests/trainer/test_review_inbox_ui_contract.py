#!/usr/bin/env python3
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

PAIRS = (
    ("src/analytics/leak-analyzer.js", "site/analytics/leak-analyzer.js"),
    ("src/analytics/review-score-adapter.js", "site/analytics/review-score-adapter.js"),
    ("src/analytics/review-inbox.js", "site/analytics/review-inbox.js"),
)

def main() -> None:
    for source, runtime in PAIRS:
        source_text = (ROOT / source).read_text(encoding="utf-8")
        runtime_text = (ROOT / runtime).read_text(encoding="utf-8")
        assert runtime_text == source_text, (source, runtime)

    index = (ROOT / "site/index.html").read_text(encoding="utf-8")
    assert '<script src="./analytics/analysis-state.js"></script>' in index
    assert index.index('<script src="./analytics/analysis-state.js"></script>') < index.index('<script src="./analytics/review-inbox.js"></script>')
    assert '<script src="./analytics/leak-analyzer.js"></script>' in index
    assert '<script src="./analytics/review-score-adapter.js"></script>' in index
    assert '<script src="./analytics/review-inbox.js"></script>' in index
    assert "Inbox.queryInbox(inbox,reviewInboxFiltersInput(),reviewInboxSortMode())" in index
    assert "Inbox.setReviewed" in index
    assert 'REVIEW_INBOX_METADATA_DB_KEY="reviewInboxUserMetadataByScope"' in index
    assert 'localDbSet(REVIEW_INBOX_METADATA_DB_KEY,state.reviewInboxUserMetadataByScope||{})' in index
    assert 'localDbGet(REVIEW_INBOX_METADATA_DB_KEY)' in index
    assert 'Review Inbox user metadata must not mutate reviewScores' in index
    assert 'DECISION_NOT_FOUND' in index
    assert 'aucune autre décision n’a été sélectionnée' in index
    assert 'className="review-inbox-open"' in index
    assert 'open.type="button"' in index
    assert 'data-review-inbox-reviewed' in index
    assert 'item.status==="INCOMPLETE_ANALYSIS"' in index
    assert 'item.costliest_decision||item.primary_decision' in index
    assert 'reviewInboxSortMode()' in index
    assert 'EV_LOSS_DESC' in index
    assert 'STATUS_ASC' in index
    assert 'STREET_ASC' in index
    assert 'POSITION_ASC' in index
    assert 'HAND_ID_ASC' in index

    # #394 T3: Review is a dedicated view made of exactly two panes — the pilotage
    # dashboard and the review inbox. The manual tools (cards/board, opponents,
    # method, equity, range edition) live in the Spot Lab view, never here.
    review_view = index.split('<div id="mainPage"', 1)[1].split('<div id="strategyPage"', 1)[0]
    assert 'id="reviewDashboard"' in review_view
    assert 'id="historiesSection"' in review_view
    assert 'id="handSelectionSection"' in review_view
    for manual_id in ("opponentsSection", "cardsSection", "rangeDisplaySection", "equitySection"):
        assert f'id="{manual_id}"' not in review_view, manual_id
    assert set(re.findall(r'data-app-subview-panel="([^"]+)"', review_view)) == {"pilotage", "inbox"}
    assert set(re.findall(r'data-app-subview="([^"]+)"', review_view)) == {"pilotage", "inbox"}

    # #394 T3 — Replayer entry/return contract: the Replayer is opened from the
    # Review inbox by openReplayerPage(), and its "Retour" brings the user back to
    # the Review view with the selected hand preserved. The return is a pure view
    # change: it activates the inbox pane, never scrolls the document, and never
    # re-schedules the background review scoring (T8 contract).
    replayer_entry = index[index.index('function openReplayerPage('):index.index('function returnToHandsPage')]
    assert "state.appView='replayer'" in replayer_entry
    assert 'scheduleBackgroundReviewScoring' not in replayer_entry
    assert 'scheduleAutoCalculate' not in replayer_entry
    back = index[index.index('function returnToHandsPage'):index.index('function leaveHistoryMode')]
    assert 'if(state.hhMode) leaveHistoryMode();' in back
    assert 'activateAppSubview("inbox")' in back
    assert 'scrollIntoView' not in back
    assert 'scheduleBackgroundReviewScoring' not in back
    assert 'state.selectedHand=null' not in back
    assert 'replayerBackBtn?.addEventListener("click",returnToHandsPage);' in index
    # The dashboard leak CTA switches to the Inbox pane the same way, without
    # scrolling the document either.
    leak_cta = index[index.index('function openReviewDashboardLeak'):index.index('function openReviewDashboardTraining')]
    assert 'activateAppSubview("inbox")' in leak_cta
    assert 'scrollIntoView' not in leak_cta

    # #393 T3: the Inbox exposes the canonical analysis-state taxonomy as the
    # primary status label and as an explicit filter, while the raw reason codes
    # stay only in the secondary/technical view.
    assert 'id="reviewAnalysisStateFilter"' in index
    for state in (
        "ANALYSE_DISPONIBLE",
        "ANALYSE_PARTIELLE",
        "CALCUL_EN_COURS",
        "DONNEES_INSUFFISANTES",
        "SPOT_NON_SUPPORTE",
        "ERREUR_CALCUL",
    ):
        assert state in index, state
    assert 'analysis_state:f.analysis_state||""' in index
    assert '[reviewAnalysisStateFilter,"analysis_state"]' in index
    assert 'item.analysis_state_label' in index
    assert 'data-analysis-state' in index
    assert 'reviewInboxReasons' in index
    assert 'Raisons techniques' in index
    assert 'item.analysis_state?.reason_codes' in index

    # The Review scope identity is population-bound: it derives from the Hero
    # strategy resolver and never from a hard-coded "Custom"/"hero-custom" token.
    assert 'hero-custom' not in index
    assert 'strategy_id:"hero-custom"' not in index
    assert 'reviewScopeFromResolution' in index
    assert 'UNAVAILABLE_STRATEGY' in index
    scope_block = index[index.index('function reviewInboxScopeInput()'):index.index('function modelBRobustnessDecisionId')]
    assert 'productHeroStrategyResolution()' in scope_block
    assert 'reviewScopeFromResolution' in scope_block
    assert 'population_id:String(population)' in scope_block
    # #task-a0n: the Review scope consumes the same contextual override status as
    # the Trainer/header chip, never a global presence promoted to active.
    assert 'override:productPersonalOverrideState()' in scope_block

    # #408 blocker 2 / #393 blocker 2: statistical_support is derived from the real
    # per-decision model support with a documented conservative aggregation rule;
    # the counters are non-null integers >= 0 and the explicit availability signal
    # carries unknown/unavailable, so a review decision count can never masquerade
    # as observations and the embedded shape stays in sync with the canonical
    # analysis-state schema + the JS validator.
    schema = json.loads(
        (ROOT / "contracts/analytics/review-inbox.schema.json").read_text(encoding="utf-8")
    )
    support = schema["$defs"]["analysis_state"]["properties"]["statistical_support"]
    for field in ("observations", "distinct_hands"):
        assert support["properties"][field]["type"] == "integer", field
        assert support["properties"][field]["minimum"] == 0, field
    assert set(support["properties"]["availability"]["enum"]) == {
        "AVAILABLE",
        "UNKNOWN",
        "UNAVAILABLE",
    }
    assert "minimum" in support["description"].lower()
    assert "decision" in support["description"].lower()
    inbox_source = (ROOT / "src/analytics/review-inbox.js").read_text(encoding="utf-8")
    assert "statisticalSupportFor" in inbox_source
    assert "observations:comparable.length" not in inbox_source
    assert "distinct_hands:comparable.length?1:0" not in inbox_source

    doc = (ROOT / "docs/analysis-state-contract.md").read_text(encoding="utf-8")
    assert "Règle d'agrégation du support statistique" in doc
    assert "event.support.observations" in doc
    assert "jamais inventé à `1`" in doc

    print("review inbox runtime mirror/UI contract checks: OK")

if __name__ == "__main__":
    main()

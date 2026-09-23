#!/usr/bin/env python3
import json
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

    # #408 blocker 2: statistical_support is derived from the real per-decision
    # model support with a documented conservative aggregation rule; it must be
    # able to represent an explicit unknown/unavailable support and never let a
    # review decision count masquerade as observations.
    schema = json.loads(
        (ROOT / "contracts/analytics/review-inbox.schema.json").read_text(encoding="utf-8")
    )
    support = schema["$defs"]["analysis_state"]["properties"]["statistical_support"]
    for field in ("observations", "distinct_hands"):
        assert set(support["properties"][field]["type"]) == {"integer", "null"}, field
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

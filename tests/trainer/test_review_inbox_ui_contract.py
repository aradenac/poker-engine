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


def select_option_values(html: str, element_id: str) -> list:
    """Option values of `<select id="...">` in declaration order."""
    start = html.index(f'<select id="{element_id}">')
    block = html[start:html.index("</select>", start)]
    return re.findall(r'<option value="([^"]*)"', block)


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

    # #395 T4 — the Review inbox opens on a *first level* made of the real-result
    # filter and the sort selector only; status / analysis state / coverage are
    # secondary filters, grouped in their own collapsible panel. A regression
    # that promotes a technical filter back into the primary row (or drops the
    # result filter) must break this test.
    primary_start = index.index('<div class="review-inbox-primary-tools">')
    secondary_start = index.index('<details class="review-inbox-filters">')
    assert primary_start < secondary_start, "the secondary filters must follow the primary tools"
    primary_tools = index[primary_start:secondary_start]
    assert 'id="reviewResultFilter"' in primary_tools
    assert 'id="hhSortSelect"' in primary_tools
    assert 'id="hhListCount"' in primary_tools
    for secondary_id in ("reviewStatusFilter", "reviewAnalysisStateFilter", "reviewCoverageFilter"):
        assert f'id="{secondary_id}"' not in primary_tools, secondary_id

    secondary_panel = index[secondary_start:index.index("</details>", secondary_start)]
    assert "<summary>Statut, analyse et filtres secondaires</summary>" in secondary_panel
    for secondary_id in ("reviewStatusFilter", "reviewAnalysisStateFilter", "reviewCoverageFilter"):
        assert f'id="{secondary_id}"' in secondary_panel, secondary_id
    assert 'id="reviewInboxReasons"' in secondary_panel

    # The real-result filter exposes exactly the schema's result enumeration,
    # behind an "all" sentinel, and feeds the query input.
    result_options = select_option_values(index, "reviewResultFilter")
    assert result_options == ["", "WIN", "LOSS", "EVEN", "UNKNOWN"], result_options
    assert 'result:f.result||""' in index

    # #395 T4 — the sort codes are persisted preference identifiers translated
    # to the poker-review-inbox/v1 sort modes. The five temporal / real-result
    # codes are locked, and TIMESTAMP_DESC (most recent first) stays the default.
    codes_start = index.index("const REVIEW_INBOX_SORT_CODES=[")
    codes_block = index[codes_start:index.index("];", codes_start)]
    sort_codes = re.findall(r'"([a-z_]+)"', codes_block)
    assert "recent_desc" in sort_codes and "recent_asc" in sort_codes, sort_codes

    modes_start = index.index("const REVIEW_INBOX_SORT_MODES={")
    modes_block = index[modes_start:index.index("};", modes_start)]
    sort_modes = dict(re.findall(r'([a-z_]+):"([A-Z_]+)"', modes_block))
    for code in ("TIMESTAMP_DESC", "TIMESTAMP_ASC", "RESULT_GAIN_DESC", "RESULT_LOSS_DESC", "EV_LOSS_DESC"):
        assert code in sort_modes.values(), code
    assert 'const REVIEW_INBOX_DEFAULT_SORT="recent_desc";' in index
    assert sort_modes["recent_desc"] == "TIMESTAMP_DESC", sort_modes
    assert 'hhSort:"recent_desc"' in index
    # The selector is declared in the same order as the persisted codes and its
    # first option is the default (most recent first).
    sort_options = select_option_values(index, "hhSortSelect")
    assert sort_options[0] == "recent_desc", sort_options
    assert set(sort_options) == set(sort_codes), (sort_options, sort_codes)
    # An unknown (or legacy) stored code falls back to the declared default,
    # never to an arbitrary mode.
    assert "return REVIEW_INBOX_SORT_CODES.includes(code)?code:REVIEW_INBOX_DEFAULT_SORT;" in index

    # #395 T5 — the inbox list is bounded by its pager, not by an internal
    # scroll: the bar lives inside the inbox pane, right after the list, and is
    # the only place where the page / hand window is spelled out.
    inbox_pane = index[index.index('id="handSelectionSection"'):index.index('id="strategyPage"')]
    assert 'id="hhHands" class="hh-list"' in inbox_pane
    assert 'id="hhListPager"' in inbox_pane
    assert inbox_pane.index('id="hhHands"') < inbox_pane.index('id="hhListPager"')
    pager_block = inbox_pane[inbox_pane.index('id="hhListPager"'):inbox_pane.index("</nav>", inbox_pane.index('id="hhListPager"'))]
    assert "hidden" in pager_block
    assert 'id="hhPagePrev"' in pager_block and 'id="hhPageNext"' in pager_block
    assert 'id="hhPageInfo"' in pager_block
    assert 'class="app-list-pager-info" role="status" aria-live="polite"' in pager_block
    assert ".hh-list{flex:1 1 auto;min-height:0;max-height:none;overflow:hidden}" in index

    def page_size_const(name: str) -> int:
        match = re.search(rf"const {name}=(\d+);", index)
        assert match is not None, name
        return int(match.group(1))

    page_min = page_size_const("REVIEW_INBOX_PAGE_SIZE_MIN")
    page_max = page_size_const("REVIEW_INBOX_PAGE_SIZE_MAX")
    assert 10 <= page_min <= page_max <= 15, (page_min, page_max)
    assert "const REVIEW_INBOX_PAGE_SIZE_DEFAULT=REVIEW_INBOX_PAGE_SIZE_MIN;" in index
    assert "REVIEW_INBOX_PAGE_FIT_ATTEMPTS=" in index
    assert "function updateReviewInboxPager(" in index
    assert "`Page ${page+1} / ${pages} · mains ${first+1}–${last} sur ${total}`" in index

    # Any first-level change (sort, result filter, known-cards checkbox, and the
    # secondary filter loop) restarts on page 1 and persists the preference.
    for change_block in (
        'state.hhSort=normalizeReviewInboxSortCode(hhSortSelect.value);\n  state.reviewInboxPage=0;',
        'state.reviewInboxFilters.result=reviewResultFilter.value;\n  state.reviewInboxPage=0;',
        "state.hhKnownOnly=hhKnownFilter.checked;\n  state.reviewInboxPage=0;",
        '].forEach(([el,key])=>el?.addEventListener("change",()=>{state.reviewInboxFilters[key]=el.value;state.reviewInboxPage=0;schedulePersistPrefs();renderHistoryHands();}));',
    ):
        assert change_block in index, change_block
    for handler in ("hhSortSelect?.addEventListener", "reviewResultFilter?.addEventListener"):
        start = index.index(handler)
        assert "state.reviewInboxPage=0;" in index[start:index.index("});", start)]
        assert "schedulePersistPrefs();" in index[start:index.index("});", start)]

    # #395 T4 — the result filter and the sort code survive a reload: they are
    # written in the local prefs snapshot and restored through an explicit
    # whitelist, so an unknown stored value can never be injected into the UI.
    prefs = index[index.index("function currentLocalPrefs(){"):index.index("function schedulePersistPrefs(")]
    assert "hhSort:state.hhSort," in prefs
    assert "reviewInboxFilters:{...state.reviewInboxFilters}," in prefs
    restore = index[index.index("const savedSort=String(prefs.hhSort"):index.index("state.hhKnownOnly=!!prefs.hhKnownOnly;")]
    for code in sort_codes:
        assert f'"{code}"' in restore, code
    assert 'if(savedSort==="review_desc") state.hhSort="ev_loss_desc";' in restore
    assert 'result:["","WIN","LOSS","EVEN","UNKNOWN"],' in restore
    assert 'coverage:["","COMPLETE","INCOMPLETE"],' in restore

    # The JSON schema is the single source of truth: every enumeration the UI
    # exposes must be a subset of the schema's, and the item fields consumed by
    # the row (result / coverage / analysis state / status / deep link / review
    # state) must be declared. A UI option that drifts from the schema, or a
    # schema field the UI silently reads, breaks here.
    inbox_schema = json.loads(
        (ROOT / "contracts/analytics/review-inbox.schema.json").read_text(encoding="utf-8")
    )
    schema_sort = set(inbox_schema["$defs"]["review_sort"]["enum"])
    for code in ("TIMESTAMP_DESC", "TIMESTAMP_ASC", "RESULT_GAIN_DESC", "RESULT_LOSS_DESC", "EV_LOSS_DESC"):
        assert code in schema_sort, code
    assert set(sort_modes.values()) <= schema_sort, set(sort_modes.values()) - schema_sort
    assert "EV_LOSS_DESC" in inbox_schema["$defs"]["review_sort"]["description"]

    item_props = inbox_schema["$defs"]["item"]["properties"]
    for field in ("hand_id", "result", "coverage", "analysis_state", "analysis_state_label", "status", "status_label", "deep_link", "user_review"):
        assert field in item_props, field
    assert set(item_props["result"]["properties"]["state"]["enum"]) == {"WIN", "LOSS", "EVEN", "UNKNOWN"}
    assert set(item_props["result"]["properties"]["state"]["enum"]) == set(result_options) - {""}
    assert set(item_props["coverage"]["properties"]["state"]["enum"]) == {"COMPLETE", "INCOMPLETE"}
    assert set(item_props["coverage"]["properties"]["state"]["enum"]) == set(select_option_values(index, "reviewCoverageFilter")) - {""}
    assert set(item_props["status"]["enum"]) == set(select_option_values(index, "reviewStatusFilter")) - {""}
    analysis_state_enum = set(inbox_schema["$defs"]["analysis_state"]["properties"]["state"]["enum"])
    assert analysis_state_enum == set(select_option_values(index, "reviewAnalysisStateFilter")) - {""}
    assert analysis_state_enum == {
        "ANALYSE_DISPONIBLE",
        "ANALYSE_PARTIELLE",
        "CALCUL_EN_COURS",
        "DONNEES_INSUFFISANTES",
        "SPOT_NON_SUPPORTE",
        "ERREUR_CALCUL",
    }
    assert "reason_codes" in inbox_schema["$defs"]["analysis_state"]["properties"]
    assert "reviewInboxReasons" in index and "item.analysis_state?.reason_codes" in index

    # Each row keeps its secondary column: the analysis-state label is the
    # primary user-facing badge (raw reason codes only as a title), the review
    # toggle lives there, and the coverage counters stay in the secondary text.
    row_paint = index[index.index("function paintReviewInboxRows("):index.index("async function clearLoadedHands(")]
    assert 'row.className="hh-hand review-inbox-row"' in row_paint
    assert 'status.className="review-inbox-status";' in row_paint
    assert 'data-analysis-state="${escapeHtml(analysisState?.state||"")}"' in row_paint
    assert 'data-review-inbox-reviewed="${escapeHtml(h.id)}"' in row_paint
    assert "item.analysis_state_label||analysisState?.state||item.status_label" in row_paint
    assert "Support ${item.coverage?.decisions_covered??0}/${item.coverage?.decisions_total??0}" in row_paint
    assert "row.append(open,status);" in row_paint

    # #394 T3/T1: Review is a dedicated view made of exactly three panes — the
    # pilotage dashboard, the import surface and the review inbox. The import
    # surface is its own pane so the whole import block (advanced options
    # included) fits in the bounded shell instead of sharing the shell height
    # with the dashboard. The manual tools (cards/board, opponents, method,
    # equity, range edition) live in the Spot Lab view, never here.
    review_view = index.split('<div id="mainPage"', 1)[1].split('<div id="strategyPage"', 1)[0]
    assert 'id="reviewDashboard"' in review_view
    assert 'id="historiesSection"' in review_view
    assert 'id="handSelectionSection"' in review_view
    for manual_id in ("opponentsSection", "cardsSection", "rangeDisplaySection", "equitySection"):
        assert f'id="{manual_id}"' not in review_view, manual_id
    assert set(re.findall(r'data-app-subview-panel="([^"]+)"', review_view)) == {"pilotage", "import", "inbox"}
    assert set(re.findall(r'data-app-subview="([^"]+)"', review_view)) == {"pilotage", "import", "inbox"}
    assert (
        '<section id="historiesSection" class="panel wide app-subview-panel"'
        ' role="tabpanel" aria-labelledby="reviewImportTab"'
        ' data-app-subview-panel="import" hidden>'
    ) in review_view
    assert (
        '<button type="button" class="app-subview-tab" id="reviewImportTab"'
        ' role="tab" aria-selected="false" aria-controls="historiesSection"'
        ' data-app-subview="import">Import</button>'
    ) in review_view
    # The dashboard CTA opens the Import pane before clicking the file input, so
    # the picker never depends on an input inside a `hidden` pane.
    assert 'reviewDashboardImportBtn?.addEventListener("click",()=>{activateAppSubview("import");hhFileInput?.click();});' in index

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

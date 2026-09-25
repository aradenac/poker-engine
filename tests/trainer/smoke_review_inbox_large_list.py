#!/usr/bin/env python3
"""#395 T7 — Review inbox smoke on a large list (pagination, sorts, deep link, prefs).

What this smoke proves, and on what
-----------------------------------
It imports a real PokerStars export of 32 hands
(`tests/trainer/fixtures/review_inbox_large_list.hand.txt`, built by the
committed builder next to it) through the real `#hhFileInput`, then drives the
Review inbox **in a browser**:

1. bounded rendering — the list is painted one measured page at a time, the
   page never exceeds `REVIEW_INBOX_PAGE_SIZE_MAX = 15` rows, `.hh-list` stays
   `overflow:hidden`, `#hhHands.scrollHeight <= clientHeight` and the document
   itself never scrolls: no list scroll is needed to reach the hands;
2. pagination — `#hhPageInfo` spells `Page x / y · mains a–b sur N`, `Précédent`
   / `Suivant` walk the whole list page by page without ever leaving a page
   behind, and the buttons are disabled exactly at the two ends;
3. ordering — for the five first-level sorts (`recent_desc`, `recent_asc`,
   `ev_loss_desc`, `gain_desc`, `loss_desc`) the concatenation of the painted
   pages is *exactly* the order the fixture authors: most recent first, biggest
   gain first, biggest loss first, biggest EV loss first, and the hands whose
   real settlement is unavailable carried after the settled ones. The expected
   orders are computed in Python from the fixture table; the guard
   (`test_review_inbox_large_list_smoke_contract.py`) replays the same fixture
   through the served analytics modules and fails if the expectation and the
   contract disagree, so this smoke never asserts against itself;
4. result filter — `#reviewResultFilter` selects the four real-result states
   (WIN / LOSS / EVEN / UNKNOWN) on the ids the fixture authors, restarts on
   page 1, and a filtered list that fits one page hides the pager;
5. selection — a hand selected from the inbox stays selected when it is painted
   again after a page round-trip;
6. deep link — opening a row goes to the Replayer on the *decision* the inbox
   advertises (`data-decision-id` / `data-step-index`), i.e. `state.replayIndex`
   equals the advertised step and the replayer status names it. A hand without
   any comparable decision stays explicit (`Analyse incomplète`, step 0) instead
   of opening a misleading decision;
7. preferences — the sort and the result filter survive a reload and are
   re-applied to the restored list (hands + prefs, both from local storage).

Why the review scores are injected
----------------------------------
The inbox ordering of the EV dimension is a pure function of `state.reviewScores`
(`total_loss_bb`), which the real background batch fills by running equity/EV
workers per visible hand. To keep this smoke deterministic *and* to keep the
ordering assertions exhaustive rather than monotonicity-only, the smoke freezes
that batch (`cancelObsoleteReviewComputation`) and injects one authored
`review_score` per hand — the same shape the batch writes, built from the hands
the real adapter parsed. The freeze is *measured*, not assumed: the smoke reads
`state.reviewBatchBusy` / `state.reviewBatchPreparing` back and re-reads the
injected loss of every hand before asserting anything, and fails with those
values when the scheduler did not settle.

The numeric engine itself is not re-tested here (it is covered by
`smoke_trainer.py` and the #391/#394 smokes): this module is a
representation/application-shell smoke of the Review inbox, on a real import.

CI registration
---------------
Like `smoke_opponent_range_numeric.py`, `smoke_equity_scale_invariance.py` and
`smoke_modes_desktop.py`, it is orchestrated by `tests/trainer/smoke_trainer.py`
(`run_driver_smokes`): the frozen `browser-smoke` job of
`.github/workflows/trainer-smoke.yml` runs it through its single
`python3 tests/trainer/smoke_trainer.py` step, and the workflow file itself stays
untouched (its digest is protected by `tests/ci/test_repro_workflow_batch2.py`).
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
import threading
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:  # pragma: no cover - import guard, asserted in `main`
    from playwright.async_api import async_playwright
except Exception as exc:  # pragma: no cover - optional dependency
    async_playwright = None
    PLAYWRIGHT_IMPORT_ERROR = repr(exc)
else:  # pragma: no cover - trivial branch
    PLAYWRIGHT_IMPORT_ERROR = ""

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "site"
# The fixture, its deterministic builder and the node probe live under
# `tests/trainer/` on purpose: the frozen `.github/workflows/trainer-smoke.yml`
# triggers on `tests/trainer/**` (it does not watch `tests/fixtures/**`), so a
# change to any of them re-runs the CI that executes this smoke.
FIXTURE_DIR = ROOT / "tests/trainer/fixtures"
FIXTURE = FIXTURE_DIR / "review_inbox_large_list.hand.txt"
sys.path.insert(0, str(FIXTURE_DIR))
import review_inbox_large_list_builder as fixture_builder  # noqa: E402

# Reference viewport of the fix-height desktop shell (#394). The shell contract
# is measured at 1500x1000 and 1366x768 by `smoke_modes_desktop.py`; this smoke
# measures the *list* bound at the taller reference viewport, where the 15-row
# page cap binds.
VIEWPORT = (1500, 1000)
SORT_SELECTOR = "#hhSortSelect"
RESULT_FILTER_SELECTOR = "#reviewResultFilter"
# The five first-level sorts of the inbox: temporal (both directions), real
# result (gain / loss) and EV loss.
SORT_CODES = ("recent_desc", "recent_asc", "ev_loss_desc", "gain_desc", "loss_desc")
PAGE_SIZE_MAX = 15
HAND_TOTAL = fixture_builder.HAND_TOTAL
# Bounded reconciliation of the background review batch: the smoke freezes the
# batch, waits for it to settle and re-injects, then verifies the injected loss
# of every hand. A scheduler that keeps writing scores fails loudly with the
# measured mismatches instead of drifting into a flaky assertion later.
REVIEW_SCORE_SETTLE_ATTEMPTS = 4
REVIEW_SCORE_SETTLE_MS = 400


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def expected_order(specs: list[dict], code: str) -> list[str]:
    """Ids the served `poker-review-inbox/v1` contract must paint, in order.

    Mirrors `sortInboxItems` (src/analytics/review-inbox.js): every comparison
    falls back to the ascending hand id, the real-result sorts key on the
    signed net in BB and carry the unsettled hands (`UNKNOWN`, no net) *after*
    the settled ones in both directions.
    """
    rows = list(specs)
    if code == "recent_desc":
        rows.sort(key=lambda row: row["hand_id"])
        rows.sort(key=lambda row: _parse_timestamp(row["timestamp"]), reverse=True)
    elif code == "recent_asc":
        rows.sort(key=lambda row: row["hand_id"])
        rows.sort(key=lambda row: _parse_timestamp(row["timestamp"]))
    elif code == "gain_desc":
        rows.sort(key=lambda row: row["hand_id"])
        rows.sort(key=lambda row: row["net_bb"] if row["net_bb"] is not None else 0.0, reverse=True)
        rows.sort(key=lambda row: row["net_bb"] is None)
    elif code == "loss_desc":
        rows.sort(key=lambda row: row["hand_id"])
        rows.sort(key=lambda row: row["net_bb"] if row["net_bb"] is not None else 0.0)
        rows.sort(key=lambda row: row["net_bb"] is None)
    elif code == "ev_loss_desc":
        rows.sort(key=lambda row: row["hand_id"])
        rows.sort(key=lambda row: row["ev_loss_bb"], reverse=True)
    else:
        raise AssertionError(f"tri non couvert par le smoke: {code}")
    return [row["hand_id"] for row in rows]


def expected_ids_for_result(specs: list[dict], state: str) -> list[str]:
    """Ids of the hands whose real result is `state` (contract order, by id)."""
    return sorted(row["hand_id"] for row in specs if row["result"] == state)


READ_INBOX_FN = """() => {
  const list=document.querySelector('#hhHands');
  const pager=document.querySelector('#hhListPager');
  const rows=[...list.querySelectorAll('.hh-hand')];
  return {
    ids:rows.map(row=>String(row.dataset.handId)),
    selected:rows.filter(row=>row.classList.contains('selected')).map(row=>String(row.dataset.handId)),
    deepLinks:rows.filter(row=>row.dataset.decisionId).map(row=>({
      handId:String(row.dataset.handId),
      decisionId:String(row.dataset.decisionId),
      stepIndex:Number(row.dataset.stepIndex)
    })),
    pageSize:Number(state.reviewInboxPageSize)||0,
    page:Number(state.reviewInboxPage)||0,
    pageInfo:(document.querySelector('#hhPageInfo')||{}).textContent||'',
    pagerHidden:!pager||pager.hidden===true,
    prevDisabled:!!(document.querySelector('#hhPagePrev')||{}).disabled,
    nextDisabled:!!(document.querySelector('#hhPageNext')||{}).disabled,
    total:(state.reviewInboxView&&state.reviewInboxView.items||[]).length,
    sort:state.hhSort,
    sortValue:document.querySelector('#hhSortSelect').value,
    result:state.reviewInboxFilters.result,
    resultValue:document.querySelector('#reviewResultFilter').value,
    selectedHandId:state.selectedHand?String(state.selectedHand.id):null,
    replayIndex:Number(state.replayIndex)||0,
    scrollTop:(typeof list.scrollTop==='number')?list.scrollTop:-1,
    listOverflowY:getComputedStyle(list).overflowY,
    listScrollHeight:list.scrollHeight,
    listClientHeight:list.clientHeight,
    docScrollHeight:document.scrollingElement.scrollHeight,
    docClientHeight:document.scrollingElement.clientHeight
  };
}"""

FREEZE_REVIEW_SCORING_JS = """() => {
  cancelObsoleteReviewComputation();
  state.reviewAnalyzeAll=false;
  return {
    scheduled:!!state.reviewBatchScheduled,
    busy:!!state.reviewBatchBusy,
    preparing:!!state.reviewBatchPreparing
  };
}"""

INJECT_REVIEW_SCORES_FN = """(payload) => {
  const Adapter=window.PokerReviewLeakAdapter;
  const analyzable=step=>(['call','bet','raise'].includes(step.actionType))
    ||(['FLOP','TURN','RIVER'].includes(step.street)&&['check','fold'].includes(step.actionType));
  const parsed=Adapter.parseStoredHandHistories((state.hhHands||[]).map(hand=>({
    name:hand.sourceName||payload.source_name,
    content:String(hand.raw||'')
  })));
  const signature=reviewContextSignature();
  const scores={};
  for(const hand of (state.hhHands||[])){
    const id=String(hand.id),spec=payload.hands[id],parsedHand=parsed.get(id);
    const details=[];
    if(spec&&spec.loss_bb>0&&parsedHand){
      for(const step of parsedHand.steps){
        if(step.player!==parsedHand.heroName||!analyzable(step))continue;
        details.push({
          stepIndex:step.stepIndex,
          bestLabel:'CALL',
          chosenEV:0,
          bestEV:spec.loss_bb,
          rawLossBB:spec.loss_bb,
          lossBB:spec.loss_bb,
          comparable:true,
          withinNoise:false,
          simContext:{potType:'SRP',preflopRole:'CALLER',relativePosition:'IP'}
        });
      }
    }
    scores[id]={
      signature,
      complete:details.length>0,
      analyzableDecisions:details.length,
      finishedDecisions:details.length,
      details
    };
  }
  state.reviewScores=scores;
  // Selecting a hand makes the app recompute that hand's score from the
  // replayer cache (`refreshReviewScoreForSelectedHand`) and re-render the list;
  // repainting here keeps the painted order the deterministic one the smoke
  // asserts, whatever the app wrote for the selected hand in between.
  renderHistoryHands();
  return {
    signature,
    hands:Object.keys(scores).length,
    details:Object.values(scores).reduce((count,score)=>count+score.details.length,0)
  };
}"""

VERIFY_INJECTED_SCORES_FN = """(payload) => {
  const signature=reviewContextSignature();
  const mismatches=[];
  for(const hand of (state.hhHands||[])){
    const id=String(hand.id),spec=payload.hands[id]||{loss_bb:0},score=state.reviewScores?.[id];
    if(!score||score.signature!==signature){mismatches.push({hand_id:id,reason:'signature'});continue;}
    const total=(score.details||[]).reduce((sum,detail)=>sum+Math.max(0,Number(detail.lossBB)||0),0);
    if(Math.abs(total-spec.loss_bb)>1e-9){
      mismatches.push({hand_id:id,reason:'loss',total,expected:spec.loss_bb});
    }
  }
  return {
    mismatches,
    scheduled:!!state.reviewBatchScheduled,
    busy:!!state.reviewBatchBusy,
    preparing:!!state.reviewBatchPreparing
  };
}"""

OPEN_DEEP_LINK_JS = """() => ({
  selectedHandId:state.selectedHand?String(state.selectedHand.id):null,
  replayIndex:Number(state.replayIndex)||0,
  status:(document.querySelector('#replayerExportStatus')||{}).textContent||'',
  statusClass:(document.querySelector('#replayerExportStatus')||{}).className||''
})"""

# The in-page helpers are installed once per document. Selecting a hand lets the
# app rewrite that hand's review score from its own asynchronous replayer work
# and repaint the list, so "inject the deterministic scores, repaint, read the
# bounded page" is composed into a *single* evaluation: the DOM an assertion
# reads is then the one the injected scores produced, whatever the app computed
# in between.
INSTALL_REVIEW_SMOKE_JS = (
    "() => {\n"
    "  window.__reviewInboxSmoke={\n"
    "    read:" + READ_INBOX_FN + ",\n"
    "    inject:" + INJECT_REVIEW_SCORES_FN + ",\n"
    "    verify:" + VERIFY_INJECTED_SCORES_FN + "\n"
    "  };\n"
    "  return Object.keys(window.__reviewInboxSmoke);\n"
    "}"
)
INJECT_AND_READ_JS = (
    "(payload) => { window.__reviewInboxSmoke.inject(payload);"
    " return window.__reviewInboxSmoke.read(); }"
)


def _serve_site():
    """Ephemeral static server over `site/`, like the other browser smokes."""
    handler = partial(SimpleHTTPRequestHandler, directory=str(SITE))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}/index.html"
    return httpd, url


def parse_page_info(text: str) -> dict:
    """`Page x / y · mains a–b sur N`, parsed — the smoke never trusts a caption."""
    match = re.fullmatch(r"Page (\d+) / (\d+) · mains (\d+)–(\d+) sur (\d+)", text.strip())
    assert match is not None, f"caption de pagination inattendue: {text!r}"
    page, pages, first, last, total = (int(group) for group in match.groups())
    return {"page": page, "pages": pages, "first": first, "last": last, "total": total}


async def _install_helpers(page) -> list[str]:
    """Install the in-page readout / inject / verify helpers of this smoke."""
    installed = await page.evaluate(INSTALL_REVIEW_SMOKE_JS)
    assert sorted(installed) == ["inject", "read", "verify"], installed
    return installed


async def _read(page) -> dict:
    return await page.evaluate("() => window.__reviewInboxSmoke.read()")


async def _inject_and_read(page, payload: dict) -> dict:
    """Re-inject the deterministic scores, repaint and read the page atomically."""
    return await page.evaluate(INJECT_AND_READ_JS, payload)


def assert_bounded(page_state: dict, label: str) -> None:
    """`rendu borné sans scroll de liste` (#395 T7)."""
    assert page_state["listOverflowY"] in ("hidden", "clip"), (label, page_state)
    assert page_state["scrollTop"] <= 1, (label, page_state)
    assert page_state["listScrollHeight"] <= page_state["listClientHeight"] + 1, (label, page_state)
    assert page_state["docScrollHeight"] <= page_state["docClientHeight"] + 1, (label, page_state)
    assert 1 <= page_state["pageSize"] <= PAGE_SIZE_MAX, (label, page_state)
    assert len(page_state["ids"]) <= PAGE_SIZE_MAX, (label, page_state)


async def _walk_pages(page) -> list[dict]:
    """Every painted page of the current query, from the first to the last."""
    current = await _read(page)
    assert not current["pagerHidden"], (
        "la liste doit être paginée par `#hhListPager` (rendu borné), or le pager est masqué "
        f"pour {current['total']} éléments (taille de page {current['pageSize']})"
    )
    pages = [current]
    while not pages[0]["prevDisabled"]:
        await page.click("#hhPagePrev")
        pages.insert(0, await _read(page))
    while not pages[-1]["nextDisabled"]:
        await page.click("#hhPageNext")
        pages.append(await _read(page))
    return pages


def assert_pagination(pages: list[dict], expected_ids: list[str], label: str) -> None:
    """The whole ordered list is reachable page by page, with exact captions."""
    total = len(expected_ids)
    painted: list[str] = []
    for page in pages:
        info = parse_page_info(page["pageInfo"])
        assert info["total"] == total, (label, page, total)
        assert info["page"] == page["page"] + 1, (label, page)
        assert info["pages"] == len(pages), (label, page, len(pages))
        assert info["first"] == len(painted) + 1, (label, page, painted)
        assert info["last"] == len(painted) + len(page["ids"]), (label, page)
        assert page["ids"] == expected_ids[len(painted):len(painted) + len(page["ids"])], (
            label, f"page {info['page']}", page["ids"]
        )
        painted.extend(page["ids"])
    assert painted == expected_ids, (label, painted, expected_ids)


async def _stabilise_review_scores(page, payload: dict) -> dict:
    """Freeze the real review batch and prove the injected scores survived it."""
    last: dict = {}
    for _ in range(REVIEW_SCORE_SETTLE_ATTEMPTS):
        freeze = await page.evaluate(FREEZE_REVIEW_SCORING_JS)
        await page.wait_for_timeout(REVIEW_SCORE_SETTLE_MS)
        injected = await page.evaluate(
            "(payload) => window.__reviewInboxSmoke.inject(payload)", payload
        )
        probe = await page.evaluate(
            "(payload) => window.__reviewInboxSmoke.verify(payload)", payload
        )
        last = {"freeze": freeze, "injected": injected, "probe": probe}
        if not probe["mismatches"] and not probe["busy"] and not probe["preparing"]:
            return last
    raise AssertionError(
        "les scores de review déterministes du smoke n'ont pas été stabilisés "
        f"({REVIEW_SCORE_SETTLE_ATTEMPTS} tentatives): {json.dumps(last, ensure_ascii=False)}"
    )


async def run() -> None:
    assert FIXTURE.is_file(), f"fixture de grande liste introuvable: {FIXTURE}"
    specs = fixture_builder.hand_specs()
    assert len(specs) == HAND_TOTAL and HAND_TOTAL >= 30, specs
    assert FIXTURE.read_text(encoding="utf-8") == fixture_builder.build_fixture(), (
        "la fixture committée a dérivé de son builder déterministe"
    )
    payload = {
        "source_name": FIXTURE.name,
        "hands": {spec["hand_id"]: {"loss_bb": spec["ev_loss_bb"]} for spec in specs},
    }
    expected = {code: expected_order(specs, code) for code in SORT_CODES}
    # Non-vacuity of the fixture itself: five requested orders that were not
    # actually different would let a broken sort pass the smoke.
    assert len({tuple(order) for order in expected.values()}) == len(SORT_CODES), expected

    page_errors: list[str] = []
    console_errors: list[str] = []
    audit: dict = {"viewport": f"{VIEWPORT[0]}x{VIEWPORT[1]}", "hands": HAND_TOTAL, "sorts": {}}
    httpd, url = _serve_site()
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            try:
                context = await browser.new_context(
                    viewport={"width": VIEWPORT[0], "height": VIEWPORT[1]}
                )
                page = await context.new_page()
                page.on("pageerror", lambda exc: page_errors.append(str(exc)))
                page.on(
                    "console",
                    lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
                )
                await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                await page.wait_for_function("() => state.persistenceReady===true", timeout=45_000)
                await _install_helpers(page)

                # --- Import the large list through the real file input ---------
                # The Review view is mounted on its *Import* pane, so the inbox
                # is not painted when the import schedules the background review
                # batch: no hand is visible, the batch finds no candidate and the
                # deterministic scores below can never race it.
                await page.click('button.mode-card[data-app-view="review"]')
                await page.wait_for_function(
                    "() => document.body.dataset.appView==='review'", timeout=20_000
                )
                await page.click("#reviewImportTab")
                assert await page.locator("#historiesSection").is_visible()
                assert await page.locator("#handSelectionSection").is_hidden()
                await page.locator("#hhFileInput").set_input_files(
                    files=[{
                        "name": FIXTURE.name,
                        "mimeType": "text/plain",
                        "buffer": FIXTURE.read_bytes(),
                    }],
                )
                await page.wait_for_function(
                    "() => Array.isArray(state.hhHands) && state.hhHands.length === "
                    + str(HAND_TOTAL),
                    timeout=30_000,
                )
                imported = await page.evaluate("() => state.hhHands.map(hand => String(hand.id))")
                assert sorted(imported) == sorted(spec["hand_id"] for spec in specs), imported
                audit["imported"] = imported
                scores = await _stabilise_review_scores(page, payload)
                audit["review_scores"] = scores

                # --- The inbox paints one bounded page -------------------------
                await page.click("#reviewInboxTab")
                await page.wait_for_function(
                    "() => document.querySelectorAll('#hhHands .hh-hand').length > 0",
                    timeout=20_000,
                )
                first_page = await _read(page)
                assert_bounded(first_page, "page 1")
                assert first_page["page"] == 0 and len(first_page["ids"]) < HAND_TOTAL, first_page
                assert not first_page["prevDisabled"], first_page
                assert len(first_page["ids"]) == first_page["pageSize"], first_page

                # --- Ordering, page by page, for the five first-level sorts ----
                for code in SORT_CODES:
                    await page.select_option(SORT_SELECTOR, code)
                    await page.wait_for_function(
                        "(code) => state.hhSort===code", arg=code, timeout=10_000
                    )
                    pages = await _walk_pages(page)
                    for painted_page in pages:
                        assert_bounded(painted_page, f"{code} page {painted_page['page'] + 1}")
                        assert painted_page["sortValue"] == code, painted_page
                    assert_pagination(pages, expected[code], f"tri {code}")
                    audit["sorts"][code] = {
                        "pages": len(pages),
                        "page_size": pages[0]["pageSize"],
                        "page_1": pages[0]["ids"],
                    }
                    # Coming back to the first page is what the next assertion
                    # needs; `_walk_pages` left us on the last one.
                    while not (await _read(page))["prevDisabled"]:
                        await page.click("#hhPagePrev")
                    assert (await _read(page))["page"] == 0

                # --- The result filter ----------------------------------------
                await page.select_option(SORT_SELECTOR, "recent_desc")
                for result_state in ("WIN", "LOSS", "EVEN", "UNKNOWN"):
                    await page.select_option(RESULT_FILTER_SELECTOR, result_state)
                    await page.wait_for_function(
                        "(value) => state.reviewInboxFilters.result===value",
                        arg=result_state,
                        timeout=10_000,
                    )
                    filtered = await _read(page)
                    assert filtered["page"] == 0, (
                        "un changement de filtre doit repartir de la page 1", filtered
                    )
                    assert_bounded(filtered, f"filtre {result_state}")
                    wanted = expected_ids_for_result(specs, result_state)
                    assert filtered["total"] == len(wanted), (result_state, filtered, wanted)
                    assert sorted(filtered["ids"]) == wanted, (result_state, filtered["ids"])
                    # The pager follows the filtered total: it is hidden exactly
                    # when the filtered list fits one measured page.
                    assert filtered["pagerHidden"] == (len(wanted) <= filtered["pageSize"]), (
                        result_state, filtered
                    )
                    # The filter keeps the selected sort (most recent first here).
                    assert filtered["ids"] == [
                        hand_id for hand_id in expected["recent_desc"] if hand_id in set(wanted)
                    ], (result_state, filtered["ids"])
                    audit[f"filter_{result_state}"] = {
                        "ids": filtered["ids"], "pager_hidden": filtered["pagerHidden"],
                    }
                await page.select_option(RESULT_FILTER_SELECTOR, "")
                await page.wait_for_function(
                    "() => state.reviewInboxFilters.result===''", timeout=10_000
                )

                # --- Preferences survive a reload ------------------------------
                await page.select_option(SORT_SELECTOR, "loss_desc")
                await page.select_option(RESULT_FILTER_SELECTOR, "LOSS")
                await page.wait_for_function(
                    "() => state.hhSort==='loss_desc' && state.reviewInboxFilters.result==='LOSS'",
                    timeout=10_000,
                )
                # The two changes are persisted by a debounced writer
                # (`schedulePersistPrefs`, 80 ms): force it and wait for the real
                # "saved" status before reloading, so the restore always reads
                # the preferences this smoke just wrote.
                await page.evaluate("() => { schedulePersistPrefs(0); return true; }")
                await page.wait_for_function(
                    "() => { const el=document.getElementById('localPersistenceStatus');"
                    " return !state.persistPrefsTimer && !!el"
                    " && /Sauvegarde locale automatique active/.test(el.textContent); }",
                    timeout=20_000,
                )
                await page.reload(wait_until="domcontentloaded", timeout=45_000)
                await page.wait_for_function("() => state.persistenceReady===true", timeout=45_000)
                await _install_helpers(page)
                await page.wait_for_function(
                    "() => Array.isArray(state.hhHands) && state.hhHands.length === "
                    + str(HAND_TOTAL),
                    timeout=30_000,
                )
                await _stabilise_review_scores(page, payload)
                await page.click("#reviewInboxTab")
                await page.wait_for_function(
                    "() => document.querySelectorAll('#hhHands .hh-hand').length > 0",
                    timeout=20_000,
                )
                restored = await _read(page)
                assert restored["sort"] == "loss_desc" and restored["sortValue"] == "loss_desc", restored
                assert restored["result"] == "LOSS" and restored["resultValue"] == "LOSS", restored
                assert restored["page"] == 0, restored
                wanted_losses = expected_ids_for_result(specs, "LOSS")
                assert restored["ids"] == [
                    hand_id for hand_id in expected["loss_desc"] if hand_id in set(wanted_losses)
                ], restored["ids"]
                audit["reload"] = {
                    "sort": restored["sort"], "result": restored["result"],
                    "ids": restored["ids"], "hands_restored": len(imported),
                }

                # --- Selection stability + deep link ---------------------------
                await page.select_option(RESULT_FILTER_SELECTOR, "")
                await page.select_option(SORT_SELECTOR, "ev_loss_desc")
                await page.wait_for_function(
                    "() => state.hhSort==='ev_loss_desc' && state.reviewInboxFilters.result===''",
                    timeout=10_000,
                )
                page_one = await _read(page)
                assert_bounded(page_one, "selection")
                target = next(entry for entry in page_one["deepLinks"])
                spec = next(row for row in specs if row["hand_id"] == target["handId"])
                assert target["decisionId"] == f"review:{target['handId']}:{target['stepIndex']}", target
                assert target["stepIndex"] == spec["decision_step_index"], (target, spec)

                await page.click(
                    f"#hhHands .hh-hand[data-hand-id='{target['handId']}'] .review-inbox-open"
                )
                await page.wait_for_function(
                    "() => document.body.dataset.appView==='replayer'", timeout=20_000
                )
                opened = await page.evaluate(OPEN_DEEP_LINK_JS)
                assert opened["selectedHandId"] == target["handId"], (target, opened)
                assert opened["replayIndex"] == target["stepIndex"], (target, opened)
                assert f"étape {target['stepIndex'] + 1}" in opened["status"], (target, opened)
                assert "introuvable" not in opened["status"], (target, opened)
                audit["deep_link"] = {
                    "hand_id": target["handId"], "decision_id": target["decisionId"],
                    "step_index": target["stepIndex"], "status": opened["status"],
                }

                await page.click("#replayerBackBtn")
                await page.wait_for_function(
                    "() => document.body.dataset.appView==='review'", timeout=20_000
                )
                # Selecting the hand let the app rewrite that hand's score from
                # its own (asynchronous) replayer work: the read below restores
                # the deterministic scores and repaints in the same turn, so the
                # page it measures is the one this smoke authored.
                back = await _inject_and_read(page, payload)
                assert back["page"] == 0, back
                assert back["selectedHandId"] == target["handId"], back
                assert target["handId"] in back["ids"] and target["handId"] in back["selected"], back

                # The selection survives a page round-trip: the hand leaves the
                # painted page, comes back, and is still the selected one.
                await page.click("#hhPageNext")
                moved = await _inject_and_read(page, payload)
                assert moved["page"] == 1, moved
                assert target["handId"] not in moved["ids"], moved
                assert moved["selectedHandId"] == target["handId"], moved
                await page.click("#hhPagePrev")
                returned = await _inject_and_read(page, payload)
                assert returned["page"] == 0, returned
                assert returned["selectedHandId"] == target["handId"], returned
                assert target["handId"] in returned["ids"], returned
                assert target["handId"] in returned["selected"], returned
                audit["selection"] = {
                    "hand_id": target["handId"], "painted_after_round_trip": returned["ids"],
                    "selected": returned["selected"],
                }

                # --- A hand without any comparable decision stays explicit -----
                no_decision = next(row for row in specs if row["decision_step_index"] is None)
                await page.select_option(SORT_SELECTOR, "hand_asc")
                await page.select_option(RESULT_FILTER_SELECTOR, no_decision["result"])
                await page.wait_for_function(
                    "(value) => state.reviewInboxFilters.result===value",
                    arg=no_decision["result"],
                    timeout=10_000,
                )
                assert no_decision["hand_id"] in (await _inject_and_read(page, payload))["ids"], (
                    no_decision
                )
                await page.click(
                    f"#hhHands .hh-hand[data-hand-id='{no_decision['hand_id']}'] .review-inbox-open"
                )
                await page.wait_for_function(
                    "() => document.body.dataset.appView==='replayer'", timeout=20_000
                )
                incomplete = await page.evaluate(OPEN_DEEP_LINK_JS)
                assert incomplete["selectedHandId"] == no_decision["hand_id"], (no_decision, incomplete)
                assert incomplete["replayIndex"] == 0, (no_decision, incomplete)
                assert "analyse incomplète" in incomplete["status"].casefold(), (no_decision, incomplete)
                audit["no_decision"] = {
                    "hand_id": no_decision["hand_id"], "status": incomplete["status"],
                }
                # The replayer starts background equity/EV work when a hand is
                # opened; let it settle so the "no console error / no page error"
                # acceptance is measured on a settled page, not on a snapshot
                # taken before the asynchronous work reports.
                await page.wait_for_timeout(300)
                await context.close()
            finally:
                await browser.close()
    finally:
        httpd.shutdown()

    print(json.dumps(audit, ensure_ascii=False, indent=2))
    assert not page_errors, f"erreurs de page: {page_errors}"
    assert not console_errors, f"erreurs console: {console_errors}"
    print(
        "review inbox large list smoke: PASS "
        f"({HAND_TOTAL} mains · rendu borné ≤{PAGE_SIZE_MAX}/page sans scroll de liste · "
        "pagination précédent/suivant · ordre temporel/gain/perte/EV par page · "
        "filtre résultat · sélection stable · deep link main · prefs restaurées après reload)"
    )


def main() -> None:
    if async_playwright is None:
        raise SystemExit(
            "smoke_review_inbox_large_list: Playwright is unavailable "
            f"({PLAYWRIGHT_IMPORT_ERROR}). Install the locked dependencies "
            "(requirements.lock.txt) and the pinned browser runtime "
            "(python3 tools/repro_ci_browser.py install) before running this smoke."
        )
    asyncio.run(run())


if __name__ == "__main__":
    main()

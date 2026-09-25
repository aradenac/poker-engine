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
1b. measured page size — at the reference viewport the smoke *reads back* what
   the page really paints: the served `reviewInboxFitCount()` / the measured row
   pitch (`reviewInboxRowPitch()`), the constrained height, and
   `state.reviewInboxPageSize`. It is consigned per sort in the audit and
   **pinned**: a paginated list may not paint fewer rows than
   `REVIEW_INBOX_PAGE_SIZE_MIN` when the measured height holds them, so a silent
   regression below the documented page size fails here (the geometry itself is
   derived from the served declarations, without a browser, by
   `tests/trainer/test_review_inbox_pagination_contract.py`, #395 T5b);
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
   (WIN / LOSS / EVEN / UNKNOWN) on the ids the fixture authors and restarts on
   page 1; each filtered list is then walked **page by page** (the same
   `Précédent` / `Suivant` march as the sorts) and the concatenated ids must be
   the `recent_desc` order restricted to the filtered ids. A filtered list that
   fits one measured page hides the pager (`hhListPager.hidden = !multipage`)
   and the walk returns that single page; a filtered list that overflows it
   (EVEN here) is walked across every page;
5. selection — a hand selected from the inbox stays selected when it is painted
   again after a page round-trip. The targeted hand is picked on the first page
   of the page-aware walk (never a `page_one` assumed to hold the whole list),
   and the round trip is computed from the page that really carries it, so it
   stays valid whatever the measured page size (10–11 here) paints;
6. deep link — opening a row goes to the Replayer on the *decision* the inbox
   advertises (`data-decision-id` / `data-step-index`), i.e. `state.replayIndex`
   equals the advertised step and the replayer status names it. A hand without
   any comparable decision stays explicit (`Analyse incomplète`, step 0) instead
   of opening a misleading decision: the hand is located on the page that
   paints it (the `EVEN` filter overflows one measured page), not assumed to sit
   on the current one;
7. preferences — the sort and the result filter survive a reload and are
   re-applied to the restored list (hands + prefs, both from local storage).
   The restored list is read page by page, so a restored filter that overflows
   one measured page is still compared whole instead of from page 1 alone.

Why the waits are causal (and not timed)
----------------------------------------
No paint and no persistence is carried by a fixed budget any more. The inbox
tab click (`activateAppSubview("inbox")`) calls `renderHistoryHands()` inside
the click itself: the smoke proves that synchronous paint with a DOM count taken
the moment `page.click` returns, then measures the page with the same atomic
inject+repaint read the rest of the file uses. The prefs step waits for what the
reload really re-reads (`localDbGet("prefs")` → `hhSort` / `result`
`reviewInboxFilters.result`, the two fields `restoreLocalState` applies), plus
the served saved chip, instead of matching a status *message* against the
status *chip* — the exact mismatch that made the old 20 s wait unsatisfiable
(`persistenceStatus` writes « Sauvegardé localement » into
`#localPersistenceStatus` and the message into `#localPersistenceDetail`,
`site/index.html:2546-2548`).

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
import time
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
# #395 T5b — la cible basse servie (`REVIEW_INBOX_PAGE_SIZE_MIN`), épinglée ici :
# une liste paginée ne peut pas peindre moins de lignes que la cible quand la
# hauteur **mesurée** les porte.
PAGE_SIZE_MIN = 10
HAND_TOTAL = fixture_builder.HAND_TOTAL
# Bounded reconciliation of the background review batch: the smoke freezes the
# batch, waits for it to settle and re-injects, then verifies the injected loss
# of every hand. A scheduler that keeps writing scores fails loudly with the
# measured mismatches instead of drifting into a flaky assertion later.
REVIEW_SCORE_SETTLE_ATTEMPTS = 4
REVIEW_SCORE_SETTLE_MS = 400
# #395 T1 (rework) — la préférence (tri + filtre résultat) est désormais
# attendue sur son *effet persistant*, jamais sur un texte de la pastille de
# statut. `persistenceStatus` (site/index.html:2544-2549) écrit le libellé
# « Sauvegardé localement » dans `#localPersistenceStatus` et le message
# « Sauvegarde locale automatique active · … » dans `#localPersistenceDetail` :
# attendre ce message dans la pastille ne peut *jamais* aboutir, d'où le
# `TimeoutError: Timeout 20000ms exceeded` reproductible du job browser-smoke.
# Le libellé épinglé ici est celui du contrat servi, déjà asserté par
# tests/trainer/smoke_trainer.py (`local_persistence["saved"]`).
PERSISTENCE_SAVED_LABEL = "Sauvegardé localement"
PREFS_PERSIST_POLL_MS = 100
PREFS_PERSIST_TIMEOUT_MS = 20_000


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
    pageSizeMin:Number(REVIEW_INBOX_PAGE_SIZE_MIN)||0,
    pageSizeMax:Number(REVIEW_INBOX_PAGE_SIZE_MAX)||0,
    fitCount:(typeof reviewInboxFitCount==='function')?reviewInboxFitCount():-1,
    rowPitch:(typeof reviewInboxRowPitch==='function')?reviewInboxRowPitch():-1,
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
    listRowGap:(parseFloat(getComputedStyle(list).rowGap)||0),
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

# #395 T1 (rework) — la lecture causale de la persistance des préférences. Elle
# relit exactement ce que `restoreLocalState` relira au prochain chargement
# (`localDbGet("prefs")`, site/index.html:9953 puis l'application des codes en
# 9970-10000) et, à titre de contrôle de surface, le libellé de la pastille
# servie. Un texte attendu dans le mauvais élément — la panne corrigée ici — ne
# peut plus faire expirer une attente à 20 s : c'est la *valeur persistée* qui
# décide.
PERSISTED_PREFS_FN = """async () => {
  const prefs=await localDbGet('prefs').catch(()=>null);
  const filters=prefs&&prefs.reviewInboxFilters&&typeof prefs.reviewInboxFilters==='object'
    ?prefs.reviewInboxFilters:null;
  return {
    stored:!!prefs,
    busy:!!state.persistPrefsTimer,
    sort:prefs?String(prefs.hhSort||''):'',
    result:filters?String(filters.result||''):'',
    chip:(document.querySelector('#localPersistenceStatus')||{}).textContent||'',
    detail:(document.querySelector('#localPersistenceDetail')||{}).textContent||''
  };
}"""

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


def assert_page_size_target(page_state: dict, label: str) -> None:
    """#395 T5b — la borne basse mesurée au viewport de référence.

    La page peinte est lue sur la vraie coque, puis comparée à ce que cette même
    coque mesure : `reviewInboxFitCount()` (les lignes que la hauteur contrainte
    porte au pas mesuré) et `state.reviewInboxPageSize`. Deux choses sont
    épinglées :

    * une liste **paginée** ne peut pas peindre moins de `REVIEW_INBOX_PAGE_SIZE_MIN`
      lignes sans que la hauteur mesurée le justifie — une page de la cible
      devrait alors déborder (`MIN * pas - gouttière > hauteur contrainte + 1`),
      et la page peinte est exactement la capacité mesurée ;
    * la page ne descend jamais sous ce que la hauteur mesurée peut porter, ni
      au-dessus du plafond servi.
    """
    fit = page_state["fitCount"]
    size = page_state["pageSize"]
    pitch = page_state["rowPitch"]
    client = page_state["listClientHeight"]
    gap = page_state["listRowGap"]
    total = page_state["total"]
    assert page_state["pageSizeMin"] == PAGE_SIZE_MIN, (label, page_state)
    assert page_state["pageSizeMax"] == PAGE_SIZE_MAX, (label, page_state)
    assert fit >= 1 and pitch > 0, (label, page_state)
    # La page ne peut pas être plus petite que ce que la hauteur mesurée porte,
    # ni que la cible quand la liste a de quoi la remplir.
    assert size >= min(total, PAGE_SIZE_MIN, fit), (
        "la page peinte est plus petite que la cible portée par la hauteur mesurée",
        label,
        page_state,
    )
    if total > size and size < PAGE_SIZE_MIN:
        assert size == fit, (
            f"sous la cible ({PAGE_SIZE_MIN}), la page peinte doit être exactement "
            "la capacité mesurée",
            label,
            page_state,
        )
        assert PAGE_SIZE_MIN * pitch - gap > client + 1, (
            f"sous la cible ({PAGE_SIZE_MIN}), la hauteur mesurée doit prouver "
            "qu'une page de la cible déborderait",
            label,
            page_state,
        )


async def _walk_pages(page, read=_read) -> list[dict]:
    """Every painted page of the current query, from the first to the last.

    A query that fits one measured page hides the pager
    (`hhListPager.hidden = !multipage`): the painted page *is* then the whole
    list, so the walk returns it without clicking. That is the shape of a
    filtered list that does not overflow the served page size (the WIN / LOSS /
    UNKNOWN result filters below). A multi-page query is walked with the same
    `Précédent` / `Suivant` polarity the served pager exposes.

    `read` is the page readout: the default `_read` is the plain DOM read, while
    a score-dependent query (the EV-loss order) hands in the atomic
    inject+repaint read so every walked page is the one the injected scores
    paint. The walk starts from the current page, walks back while the pager
    still enables « Précédent », then forward — and leaves the pager on the last
    page, exactly what the callers that rewind afterwards expect.
    """
    current = await read(page)
    if current["pagerHidden"]:
        return [current]
    pages = [current]
    while not pages[0]["prevDisabled"]:
        await page.click("#hhPagePrev")
        pages.insert(0, await read(page))
    while not pages[-1]["nextDisabled"]:
        await page.click("#hhPageNext")
        pages.append(await read(page))
    return pages


async def _return_to_first_page(page, read=_read) -> dict:
    """Walk the pager back to the first page (Précédent disabled) and read it.

    `_walk_pages` leaves the pager on the last page; the deep-link / selection
    assertions need the page that carries the chosen hand, so this brings the
    pager back to page 1 the same « Précédent » way the walk walked back.
    """
    while not (await read(page))["prevDisabled"]:
        await page.click("#hhPagePrev")
    current = await read(page)
    assert current["page"] == 0, current
    return current


async def _goto_page_holding(page, hand_id: str, label: str, read=_read) -> dict:
    """#395 T2 — leave the pager on the page that really paints `hand_id`.

    A result filter or a sort can overflow one measured page, so an expected id
    is never read from the *current* page: the walk visits every painted page of
    the query, the page that carries the id is located, and the pager is left on
    it before the caller drives the row. Fails loud with every painted page when
    no page carries the id.
    """
    pages = await _walk_pages(page, read=read)
    holding = next((entry for entry in pages if hand_id in entry["ids"]), None)
    assert holding is not None, (
        f"aucune page ne peint l'id attendu ({label})",
        hand_id,
        [(entry["page"], entry["ids"]) for entry in pages],
    )
    await _return_to_first_page(page, read=read)
    while (await read(page))["page"] < holding["page"]:
        await page.click("#hhPageNext")
    current = await read(page)
    assert current["page"] == holding["page"], (label, hand_id, current)
    assert hand_id in current["ids"], (label, hand_id, current)
    return current


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


async def _wait_persisted_prefs(page, *, sort: str, result: str) -> dict:
    """#395 T1 (rework) — attendre l'*effet persistant* des préférences.

    Le smoke écrit `loss_desc` + `LOSS` puis force le writer débouncé
    (`schedulePersistPrefs(0)`) avant de recharger la page. La garantie qui
    compte n'est pas un libellé d'interface mais ce que `restoreLocalState`
    relira : les préférences réellement écrites sous la clé `prefs` du store
    local. Cette boucle lit cette valeur (jamais un délai fixe) et échoue avec
    l'état mesuré — pastille et détail servis inclus — si elle n'y arrive pas.
    """
    deadline = time.monotonic() + PREFS_PERSIST_TIMEOUT_MS / 1000
    last: dict = {}
    while True:
        last = await page.evaluate(PERSISTED_PREFS_FN)
        if (
            last["stored"]
            and not last["busy"]
            and last["sort"] == sort
            and last["result"] == result
            and last["chip"].strip() == PERSISTENCE_SAVED_LABEL
        ):
            return last
        if time.monotonic() >= deadline:
            raise AssertionError(
                "les préférences (tri/filtre) n'ont pas atteint leur état persistant "
                f"avant le reload (attendu {sort}/{result}): "
                f"{json.dumps(last, ensure_ascii=False)}"
            )
        await page.wait_for_timeout(PREFS_PERSIST_POLL_MS)


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
                assert await page.locator("#handSelectionSection").is_visible()
                # #395 T1 (rework) — la peinture n'est plus portée par un budget
                # fixe. `activateAppSubview("inbox")` (site/index.html:7029)
                # rappelle `renderHistoryHands()` *dans le clic* : l'appli a donc
                # déjà peint sa première page quand `page.click` rend la main, et
                # le décompte ci-dessous le prouve sans aucun délai. La mesure
                # ensuite relit la même page par l'évaluation atomique
                # inject+repaint (`window.__reviewInboxSmoke.inject` →
                # `renderHistoryHands` → lecture DOM) : aucune attente de temps
                # ne garantit plus la peinture, celle-ci est un état mesuré.
                painted_by_click = await page.evaluate(
                    "() => document.querySelectorAll('#hhHands .hh-hand').length"
                )
                assert painted_by_click > 0, (
                    "le clic sur l'onglet Inbox doit peindre la première page "
                    f"(lignes peintes: {painted_by_click})"
                )
                audit["tab_click_paints"] = {"first_visit": painted_by_click}
                first_page = await _inject_and_read(page, payload)
                assert first_page["ids"], (
                    "la page mesurée doit peindre au moins une main", first_page
                )
                assert_bounded(first_page, "page 1")
                assert_page_size_target(first_page, "page 1")
                assert first_page["page"] == 0 and len(first_page["ids"]) < HAND_TOTAL, first_page
                # #395 T1/T2 — le pager servi désactive « Précédent » sur la
                # première page (`if(hhPagePrev)hhPagePrev.disabled=page<=0;`) et
                # laisse « Suivant » actif: le smoke porte le même signe, jamais
                # l'inverse.
                assert first_page["prevDisabled"], (
                    "Précédent désactivé sur la première page"
                )
                assert not first_page["nextDisabled"], (
                    "Suivant actif sur la première page"
                )
                assert len(first_page["ids"]) == first_page["pageSize"], first_page
                # #395 T5b — la mesure de référence, consignée dans l'audit : la
                # taille de page peinte à 1500x1000 avec la fixture 32 mains, et
                # les hauteurs qui la portent (capacité mesurée, pas de rangée,
                # hauteur contrainte, gouttière de liste).
                audit["page_size_reference"] = {
                    "viewport": f"{VIEWPORT[0]}x{VIEWPORT[1]}",
                    "hands": HAND_TOTAL,
                    "page_size": first_page["pageSize"],
                    "painted_rows": len(first_page["ids"]),
                    "fit_count": first_page["fitCount"],
                    "row_pitch": first_page["rowPitch"],
                    "list_client_height": first_page["listClientHeight"],
                    "list_row_gap": first_page["listRowGap"],
                    "page_size_min": first_page["pageSizeMin"],
                    "page_size_max": first_page["pageSizeMax"],
                }

                # --- Ordering, page by page, for the five first-level sorts ----
                for code in SORT_CODES:
                    await page.select_option(SORT_SELECTOR, code)
                    await page.wait_for_function(
                        "(code) => state.hhSort===code", arg=code, timeout=10_000
                    )
                    pages = await _walk_pages(page)
                    # The whole 32-hand list must stay paginated by
                    # `#hhListPager` (bounded rendering): unlike a filtered list
                    # that fits one page, it may not hide its pager.
                    assert not pages[0]["pagerHidden"], (
                        "la liste complète doit être paginée par `#hhListPager` "
                        "(rendu borné), or le pager est masqué pour "
                        f"{pages[0]['total']} éléments (taille de page {pages[0]['pageSize']})"
                    )
                    for painted_page in pages:
                        assert_bounded(painted_page, f"{code} page {painted_page['page'] + 1}")
                        assert_page_size_target(
                            painted_page, f"{code} page {painted_page['page'] + 1}"
                        )
                        assert painted_page["sortValue"] == code, painted_page
                    assert_pagination(pages, expected[code], f"tri {code}")
                    audit["sorts"][code] = {
                        "pages": len(pages),
                        "page_size": pages[0]["pageSize"],
                        # #395 T5b — la mesure explicite au viewport de référence :
                        # ce que la coque mesurée porte (fit / pas / hauteur
                        # contrainte / gouttière) et ce que la page peint.
                        "fit_count": pages[0]["fitCount"],
                        "row_pitch": pages[0]["rowPitch"],
                        "list_client_height": pages[0]["listClientHeight"],
                        "list_row_gap": pages[0]["listRowGap"],
                        "page_1": pages[0]["ids"],
                    }
                    # Coming back to the first page is what the next assertion
                    # needs; `_walk_pages` left us on the last one, and the walk
                    # back to page 1 is the same page-aware rewind the selection
                    # and deep-link sections use.
                    assert (await _return_to_first_page(page))["page"] == 0

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
                    wanted = expected_ids_for_result(specs, result_state)
                    assert filtered["total"] == len(wanted), (result_state, filtered, wanted)
                    # The pager follows the filtered total: it is hidden exactly
                    # when the filtered list fits one measured page. A hidden
                    # pager is not a shortcut: the walk below still reads that
                    # single painted page and checks it page by page.
                    assert filtered["pagerHidden"] == (len(wanted) <= filtered["pageSize"]), (
                        result_state, filtered
                    )
                    # Walk *every* painted page of the filtered query (the same
                    # `Précédent` / `Suivant` march the sorts use) and concatenate
                    # the ids each page really painted. On a single-page query the
                    # walk returns that page alone; on a multi-page one it visits
                    # them all.
                    pages = await _walk_pages(page)
                    # `pages = ceil(total / pageSize)` is the served contract
                    # (`reviewInboxPageWindow`); pinning it here proves the walk
                    # really visited every page instead of stopping on page 1.
                    expected_pages = -(-len(wanted) // max(1, filtered["pageSize"]))
                    assert len(pages) == expected_pages, (
                        result_state, len(pages), expected_pages, filtered
                    )
                    painted: list[str] = []
                    for painted_page in pages:
                        assert_bounded(
                            painted_page, f"filtre {result_state} page {painted_page['page'] + 1}"
                        )
                        assert_page_size_target(
                            painted_page, f"filtre {result_state} page {painted_page['page'] + 1}"
                        )
                        painted.extend(painted_page["ids"])
                    # The filter keeps the selected sort (most recent first
                    # here): the *concatenation* of the painted pages is exactly
                    # the `recent_desc` order restricted to the wanted ids — an
                    # order check over the whole filtered list, not a page-1
                    # snapshot compared to the full set.
                    assert painted == [
                        hand_id for hand_id in expected["recent_desc"] if hand_id in set(wanted)
                    ], (result_state, painted)
                    audit[f"filter_{result_state}"] = {
                        "pages": len(pages),
                        "ids": painted,
                        "pager_hidden": filtered["pagerHidden"],
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
                # persisted prefs before reloading, so the restore always reads
                # the preferences this smoke just wrote.
                await page.evaluate("() => { schedulePersistPrefs(0); return true; }")
                # #395 T1 (rework) — l'ancienne attente testait
                # `/Sauvegarde locale automatique active/` sur
                # `#localPersistenceStatus.textContent`, un texte que la coque
                # servie n'écrit *jamais* dans cette pastille (elle y écrit
                # « Sauvegardé localement », le message partant dans
                # `#localPersistenceDetail`) : l'attente ne pouvait pas aboutir
                # et mourait en `Timeout 20000ms exceeded`. On attend maintenant
                # la valeur relue par le reload (`localDbGet("prefs")`).
                audit["prefs_persisted"] = await _wait_persisted_prefs(
                    page, sort="loss_desc", result="LOSS"
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
                assert await page.locator("#handSelectionSection").is_visible()
                # Même peinture causale qu'à la première visite : le clic
                # d'onglet peint, puis la relecture inject+repaint mesure la page
                # restaurée, sans budget de temps.
                restored_painted_by_click = await page.evaluate(
                    "() => document.querySelectorAll('#hhHands .hh-hand').length"
                )
                assert restored_painted_by_click > 0, (
                    "le clic sur l'onglet Inbox doit repeindre la liste restaurée "
                    f"(lignes peintes: {restored_painted_by_click})"
                )
                audit["tab_click_paints"]["after_reload"] = restored_painted_by_click
                restored = await _inject_and_read(page, payload)
                assert restored["ids"], (
                    "la liste restaurée doit peindre au moins une main", restored
                )
                assert restored["sort"] == "loss_desc" and restored["sortValue"] == "loss_desc", restored
                assert restored["result"] == "LOSS" and restored["resultValue"] == "LOSS", restored
                # The restore re-applies `reviewInboxPage:0` (both change
                # handlers reset it), so the restored list starts on page 1.
                assert restored["page"] == 0, restored
                wanted_losses = expected_ids_for_result(specs, "LOSS")
                # #395 T2 — la liste restaurée se lit **page par page** : un
                # filtre `LOSS` assez large pour dépasser la page mesurée garde
                # la même égalité, la concaténation des pages peintes portant
                # tout le filtre dans l'ordre `loss_desc`. La page courante seule
                # ne dit rien de la liste entière.
                restored_pages = await _walk_pages(page)
                assert len(restored_pages) == -(-len(wanted_losses) // max(1, restored["pageSize"])), (
                    "la marche doit visiter toutes les pages du filtre restauré",
                    restored,
                    len(restored_pages),
                )
                for painted_page in restored_pages:
                    assert_bounded(painted_page, f"reload page {painted_page['page'] + 1}")
                    assert_page_size_target(
                        painted_page, f"reload page {painted_page['page'] + 1}"
                    )
                restored_ids = [
                    hand_id for painted_page in restored_pages for hand_id in painted_page["ids"]
                ]
                assert restored_ids == [
                    hand_id for hand_id in expected["loss_desc"] if hand_id in set(wanted_losses)
                ], restored_ids
                audit["reload"] = {
                    "sort": restored["sort"], "result": restored["result"],
                    "ids": restored_ids, "pages": len(restored_pages),
                    "hands_restored": len(imported),
                }

                # --- Selection stability + deep link ---------------------------
                await page.select_option(RESULT_FILTER_SELECTOR, "")
                await page.select_option(SORT_SELECTOR, "ev_loss_desc")
                await page.wait_for_function(
                    "() => state.hhSort==='ev_loss_desc' && state.reviewInboxFilters.result===''",
                    timeout=10_000,
                )
                # #395 T2 — la main ciblée est lue sur la **marche page-aware**,
                # jamais sur un `page_one` supposé tenir toute la liste :
                # `ev_loss_desc` peint `ceil(32 / taille mesurée)` pages (la
                # taille mesurée vaut 10–11), donc la page 1 n'est pas la liste.
                # L'ordre EV dépend des scores injectés, donc la marche relit
                # chaque page avec la même lecture atomique inject+repaint que
                # les assertions de sélection ci-dessous.
                listing = await _walk_pages(
                    page, read=partial(_inject_and_read, payload=payload)
                )
                assert len(listing) >= 2, (
                    "le va-et-vient de sélection exige une page suivante", listing
                )
                page_one = listing[0]
                assert page_one["page"] == 0, page_one
                assert_bounded(page_one, "selection")
                target = next(entry for entry in page_one["deepLinks"])
                spec = next(row for row in specs if row["hand_id"] == target["handId"])
                assert target["decisionId"] == f"review:{target['handId']}:{target['stepIndex']}", target
                assert target["stepIndex"] == spec["decision_step_index"], (target, spec)
                # `target` is painted by `page_one`; the round-trip below is
                # derived from *that* page (`target_page`), so the neighbour
                # assertions stay valid whatever the measured page size paints on
                # page 1. `_walk_pages` left the pager on the last page, so come
                # back to the page that carries `target` before opening it.
                target_page = page_one["page"]
                rewound = await _return_to_first_page(
                    page, read=partial(_inject_and_read, payload=payload)
                )
                assert rewound["page"] == target_page, (page_one, rewound)
                assert target["handId"] in rewound["ids"], (target, rewound)

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
                assert back["page"] == target_page, (target_page, back)
                assert back["selectedHandId"] == target["handId"], back
                assert target["handId"] in back["ids"] and target["handId"] in back["selected"], back

                # The selection survives a page round-trip: the hand leaves the
                # painted page, comes back, and is still the selected one. The
                # neighbour page is derived from `target_page` (never hard-coded
                # to 1), so the round trip stays valid whatever the measured page
                # size paints on page 1.
                await page.click("#hhPageNext")
                moved = await _inject_and_read(page, payload)
                assert moved["page"] == target_page + 1, (target_page, moved)
                assert target["handId"] not in moved["ids"], moved
                assert moved["selectedHandId"] == target["handId"], moved
                await page.click("#hhPagePrev")
                returned = await _inject_and_read(page, payload)
                assert returned["page"] == target_page, (target_page, returned)
                assert returned["selectedHandId"] == target["handId"], returned
                assert target["handId"] in returned["ids"], returned
                assert target["handId"] in returned["selected"], returned
                audit["selection"] = {
                    "hand_id": target["handId"], "target_page": target_page,
                    "painted_after_round_trip": returned["ids"], "selected": returned["selected"],
                }

                # --- A hand without any comparable decision stays explicit -----
                no_decision = next(row for row in specs if row["decision_step_index"] is None)
                await page.select_option(SORT_SELECTOR, "hand_asc")
                await page.select_option(RESULT_FILTER_SELECTOR, no_decision["result"])
                await page.wait_for_function(
                    "(value) => state.hhSort==='hand_asc'"
                    " && state.reviewInboxFilters.result===value",
                    arg=no_decision["result"],
                    timeout=10_000,
                )
                # #395 T2 — le filtre `result` de la main sans décision peut
                # dépasser une page mesurée (le filtre EVEN en porte 14 ici) : on
                # ne lit pas `ids` de la page courante, on se place sur la page
                # qui peint vraiment l'id attendu par la marche page-aware.
                no_decision_page = await _goto_page_holding(
                    page, no_decision["hand_id"], "sans décision"
                )
                painted_no_decision = await _inject_and_read(page, payload)
                assert painted_no_decision["page"] == no_decision_page["page"], (
                    no_decision, no_decision_page, painted_no_decision
                )
                assert no_decision["hand_id"] in painted_no_decision["ids"], (
                    no_decision, painted_no_decision
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
    reference = audit["page_size_reference"]
    measured_page = (
        f"page peinte mesurée {reference['page_size']} "
        f"(cible {PAGE_SIZE_MIN}–{PAGE_SIZE_MAX}, capacité mesurée {reference['fit_count']} "
        f"au pas {reference['row_pitch']:.1f}px)"
    )
    print(
        "review inbox large list smoke: PASS "
        f"({HAND_TOTAL} mains · rendu borné ≤{PAGE_SIZE_MAX}/page sans scroll de liste · "
        f"{measured_page} · "
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

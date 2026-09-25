#!/usr/bin/env python3
"""#395 T5 — the Review inbox page is measured, bounded and selection-safe.

What is checked, and from what
------------------------------
The inbox is the only list of the desktop shell that keeps every hand
reachable without a scroll zone of its own: it is painted one bounded page at a
time. This module pins the *measured* page size contract on the served bytes:

* static contract on ``site/index.html`` — the page-size window is declared as
  ``REVIEW_INBOX_PAGE_SIZE_MIN=10`` / ``REVIEW_INBOX_PAGE_SIZE_MAX=15`` (the
  ``_DEFAULT`` fallback mirrors the minimum), the pager keeps its
  ``Précédent`` / ``Suivant`` / ``Page x / y · mains a–b sur N`` shape, the
  desktop rule of ``.hh-list`` stays ``overflow:hidden`` (no internal list
  scroll) and every filter/sort input resets ``state.reviewInboxPage`` to 0 —
  so a filter change always lands on page 1;
* runtime invariance (``node``) — the real
  ``renderReviewInboxPage`` / ``reviewInboxPageSizeGuess`` sources are executed
  against a minimal measured DOM where ``scrollHeight`` is derived from the
  painted rows and ``clientHeight`` from the constrained shell *including* the
  pager bar. The painted page must:
  - hold between 10 and 15 rows when the measured height allows it,
  - never exceed 15 rows, whatever the viewport,
  - shrink below the 10-row target rather than clip a row behind
    ``overflow:hidden``,
  - leave ``scrollHeight <= clientHeight`` once the pager is visible (the
    pager is part of the constrained height: it is shown *before* the
    measurement, so its own appearance cannot hide the last row),
  - clamp ``state.reviewInboxPage`` to ``[0, pages-1]`` and keep
    ``state.selectedHand`` untouched.

Non-vacuity is replayed, not asserted: two in-memory mutations of the served
source are run through the same harness — raising ``REVIEW_INBOX_PAGE_SIZE_MAX``
must let the page exceed 15 rows, and removing the pager-first assignment must
produce the hidden overflow the real source avoids. A guard that still passed
with those declarations weakened would be vacuous.

The module is static + ``node`` only: no browser, no server, no network, no
write. ``site/index.html`` is never modified (the mutations only exist as
strings in memory and the delivered bytes are re-read at the end).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX_PATH = ROOT / "site" / "index.html"
INDEX = INDEX_PATH.read_text(encoding="utf-8")


def check_static_contract() -> None:
    assert "const REVIEW_INBOX_PAGE_SIZE_MIN=10;" in INDEX
    assert "const REVIEW_INBOX_PAGE_SIZE_MAX=15;" in INDEX
    assert "const REVIEW_INBOX_PAGE_SIZE_DEFAULT=REVIEW_INBOX_PAGE_SIZE_MIN;" in INDEX
    # The measured target is documented where it is implemented.
    assert "#395 T5" in INDEX
    assert "10 à 15 mains par page" in INDEX

    # The bounded pager keeps its operational shape: previous / next plus the
    # page and hand-window caption.
    assert 'id="hhListPager"' in INDEX
    assert 'id="hhPagePrev"' in INDEX and 'id="hhPageNext"' in INDEX
    assert 'id="hhPageInfo"' in INDEX
    assert "`Page ${page+1} / ${pages} · mains ${first+1}–${last} sur ${total}`" in INDEX
    assert 'hhPagePrev?.addEventListener("click"' in INDEX
    assert 'hhPageNext?.addEventListener("click"' in INDEX

    # No internal list scroll on the desktop shell: the page size is the only
    # bound, the list itself stays clipped (and is never a scroll zone).
    assert ".hh-list{flex:1 1 auto;min-height:0;max-height:none;overflow:hidden}" in INDEX
    for rule in re.findall(r"\.hh-list\{([^}]*)\}", INDEX):
        assert "overflow:auto" not in rule and "overflow:scroll" not in rule, rule
    assert "max-height:310px;overflow:auto" not in INDEX

    # A selected hand keeps its highlight across a bounded repaint, and no
    # repaint clears the selection.
    assert 'row.className="hh-hand review-inbox-row"+(state.selectedHand?.id===h.id?" selected":"");' in INDEX

    # Filter / sort changes restart on page 1.
    for reset in (
        "state.hhSort=normalizeReviewInboxSortCode(hhSortSelect.value);\n  state.reviewInboxPage=0;",
        "state.hhKnownOnly=hhKnownFilter.checked;\n  state.reviewInboxPage=0;",
        "state.reviewInboxFilters.result=reviewResultFilter.value;\n  state.reviewInboxPage=0;",
        "state.reviewInboxFilters[key]=el.value;state.reviewInboxPage=0;",
    ):
        assert reset in INDEX, reset
    leak_cta = INDEX[INDEX.index("function openReviewDashboardLeak"):INDEX.index("function openReviewDashboardTraining")]
    assert "state.reviewInboxPage=0;" in leak_cta

    # The page-size window is re-derived after a shell resize, without any
    # compute scheduling (the #394 T3 contract forbids scroll/visibility
    # triggers, not layout re-measurement).
    assert "function relayoutReviewInbox(){" in INDEX
    assert 'window.addEventListener("resize"' in INDEX
    relayout = INDEX[INDEX.index("function relayoutReviewInbox(){"):INDEX.index('window.addEventListener("resize"')]
    assert "renderReviewInboxPage(hands,byId);" in relayout
    assert "scheduleBackgroundReviewScoring" not in relayout
    assert "scheduleAutoCalculate" not in relayout


PAGINATION_RUNTIME_SCRIPT = r"""
const fs=require('node:fs');
const assert=require('node:assert/strict');
const vm=require('node:vm');

const MUTATIONS={
  cap:['const REVIEW_INBOX_PAGE_SIZE_MAX=15;','const REVIEW_INBOX_PAGE_SIZE_MAX=25;'],
  'pager-first':[
    '    if(hhListPager)hhListPager.hidden=pageWindow.pages<=1;\n'
      +'    paintReviewInboxRows(hands.slice(pageWindow.start,pageWindow.end),byId);',
    '    paintReviewInboxRows(hands.slice(pageWindow.start,pageWindow.end),byId);',
  ],
};
let source=fs.readFileSync('site/index.html','utf8');
const mutation=process.env.PAGINATION_MUTATION||'';
if(mutation){
  const [token,replacement]=MUTATIONS[mutation];
  assert.ok(token&&replacement,'unknown mutation: '+mutation);
  assert.equal(source.split(token).length-1,1,'mutation token must occur exactly once: '+mutation);
  source=source.replace(token,replacement);
}

function extractFn(src,name){
  const start=src.indexOf('function '+name+'(');
  if(start<0)throw new Error('missing '+name);
  let cursor=src.indexOf('(',start+'function '.length),depth=0;
  for(;cursor<src.length;cursor++){
    const ch=src[cursor];
    if(ch==='(')depth++;
    else if(ch===')'){depth--;if(depth===0)break;}
  }
  cursor=src.indexOf('{',cursor);depth=0;
  for(;cursor<src.length;cursor++){
    const ch=src[cursor];
    if(ch==='{')depth++;
    else if(ch==='}'){depth--;if(depth===0)return src.slice(start,cursor+1);}
  }
  throw new Error('unbalanced '+name);
}

function pageSizeConsts(src){
  const re=/^const (REVIEW_INBOX_PAGE_SIZE_[A-Z]+|REVIEW_INBOX_ROW_PITCH_[A-Z]+|REVIEW_INBOX_PAGE_FIT_ATTEMPTS)=[^\n]*$/gm;
  const consts=src.match(re)||[];
  assert.ok(consts.length>=6,'page-size constants must be declared: '+consts.length);
  return consts.join('\n');
}

// A measured DOM: scrollHeight is derived from the painted rows, clientHeight
// from the constrained shell minus the pager bar whenever the pager is shown.
function harness({desktop=true,rowHeight=54,gap=6,baseHeight=900,pagerHeight=44,tallFrom=0,tallRowHeight=0}={}){
  const pagerState={visible:false};
  const paints=[];
  const hhHandsEl={
    children:[],
    appendChild(node){this.children.push(node);},
    querySelector(){return this.children.find(c=>String(c.className||'').includes('hh-hand'))||null;},
    set innerHTML(value){this.children=[];},
    get innerHTML(){return '';},
  };
  Object.defineProperty(hhHandsEl,'scrollHeight',{get(){
    const n=this.children.length;
    return n?this.children.reduce((sum,child)=>sum+child.height,0)+(n-1)*gap:0;
  }});
  Object.defineProperty(hhHandsEl,'clientHeight',{get(){
    return baseHeight-(pagerState.visible?pagerHeight:0);
  }});
  const hhListPager={};
  Object.defineProperty(hhListPager,'hidden',{
    get(){return !pagerState.visible;},
    set(value){pagerState.visible=!value;},
  });
  const hhPageInfo={textContent:''};
  const hhPagePrev={disabled:false};
  const hhPageNext={disabled:false};
  const state={reviewInboxPage:0,reviewInboxPageSize:10,selectedHand:null};
  const sandbox={
    console,state,hhHandsEl,hhListPager,hhPageInfo,hhPagePrev,hhPageNext,
    window:{matchMedia:()=>({matches:!!desktop})},
    getComputedStyle:()=>({rowGap:gap+'px'}),
    paintReviewInboxRows(pageHands){
      hhHandsEl.innerHTML='';
      pageHands.forEach((hand,index)=>{
        const height=tallFrom&&index+1>=tallFrom?tallRowHeight:rowHeight;
        hhHandsEl.appendChild({
          className:'hh-hand review-inbox-row',handId:String(hand.id),
          height,getBoundingClientRect:()=>({height}),
        });
      });
      paints.push({ids:pageHands.map(hand=>String(hand.id)),pagerVisible:pagerState.visible});
    },
  };
  vm.createContext(sandbox);
  vm.runInContext([
    pageSizeConsts(source),
    extractFn(source,'reviewInboxIsHeightBound'),
    extractFn(source,'reviewInboxRowPitch'),
    extractFn(source,'reviewInboxFitCount'),
    extractFn(source,'reviewInboxBoundedSize'),
    extractFn(source,'reviewInboxPageSizeGuess'),
    extractFn(source,'updateReviewInboxPager'),
    extractFn(source,'reviewInboxPageWindow'),
    extractFn(source,'renderReviewInboxPage'),
  ].join('\n'),sandbox);
  return {sandbox,state,hhHandsEl,hhListPager,hhPageInfo,hhPagePrev,hhPageNext,pagerState,paints};
}

function run({pitch=60,total=100,page=0,selected=null,...options}={}){
  const h=harness({rowHeight:pitch-6,gap:6,...options});
  h.state.reviewInboxPage=page;
  if(selected!==null)h.state.selectedHand=selected;
  const hands=Array.from({length:total},(_,index)=>({id:String(index+1)}));
  h.sandbox.renderReviewInboxPage(hands,new Map());
  const last=h.paints[h.paints.length-1];
  return {
    painted:last.ids,
    paintedCount:last.ids.length,
    paints:h.paints.length,
    pagerVisible:h.pagerState.visible,
    everyPaintMeasuredWithPager:h.paints.every(paint=>paint.pagerVisible===h.pagerState.visible||!h.pagerState.visible),
    size:h.state.reviewInboxPageSize,
    page:h.state.reviewInboxPage,
    info:h.hhPageInfo.textContent,
    prevDisabled:h.hhPagePrev.disabled,
    nextDisabled:h.hhPageNext.disabled,
    scrollHeight:h.hhHandsEl.scrollHeight,
    clientHeight:h.hhHandsEl.clientHeight,
    overflow:h.hhHandsEl.scrollHeight>h.hhHandsEl.clientHeight,
    selectedHand:h.state.selectedHand,
  };
}

const results={
  // 1200px of measured list: the 15-row cap binds (19 rows would fit).
  capped:run({baseHeight:1200,total:100}),
  // 800px of measured list: 12 rows fit, inside the 10–15 target.
  measured:run({baseHeight:800,total:100}),
  // 500px of measured list: only 7 rows fit — the page shrinks below the
  // 10-row target instead of clipping rows behind overflow:hidden.
  belowTarget:run({baseHeight:500,total:100}),
  // A 6-hand inbox is a single bounded page: no pager, no scroll.
  singlePage:run({baseHeight:900,total:6}),
  // A short shell (600px) where the pager bar is what decides the fit: the
  // pager must be shown before the measurement, or the last row is hidden.
  pagerFirst:run({baseHeight:600,total:100}),
  // A page whose grown range contains a taller (wrapped) row: the growth is
  // measured again and reverted instead of leaving an overflow behind.
  wrappedRow:run({baseHeight:700,rowHeight:50,gap:6,tallFrom:11,tallRowHeight:150,total:100}),
  // Page index is clamped, never trusted blindly.
  clampHigh:run({baseHeight:1200,total:100,page:999}),
  clampLow:run({baseHeight:1200,total:100,page:-5}),
  // Selection survives a repaint; the selected hand keeps its row when visible.
  selection:run({baseHeight:800,total:100,page:0,selected:{id:'5'}}),
  // Below 901px the shell is not height-bound: the document flow renders all.
  mobile:run({desktop:false,baseHeight:400,total:100}),
};
results.mutation=mutation;
process.stdout.write(JSON.stringify(results));
"""


def run_runtime(mutation: str | None = None) -> dict:
    node = shutil.which("node")
    assert node is not None, "node runtime is required for the inbox pagination contract"
    completed = subprocess.run(
        [node, "-e", PAGINATION_RUNTIME_SCRIPT],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "PAGINATION_MUTATION": mutation or ""},
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return json.loads(completed.stdout)


def check_runtime_contract() -> None:
    results = run_runtime()

    capped = results["capped"]
    assert capped["paintedCount"] == 15, capped
    assert capped["size"] == 15, capped
    assert capped["painted"][0] == "1" and capped["painted"][-1] == "15", capped
    assert capped["pagerVisible"] and not capped["overflow"], capped
    assert capped["info"] == "Page 1 / 7 · mains 1–15 sur 100", capped
    assert capped["prevDisabled"] and not capped["nextDisabled"], capped

    measured = results["measured"]
    assert 10 <= measured["paintedCount"] <= 15, measured
    assert measured["paintedCount"] == 12, measured
    assert not measured["overflow"], measured

    below = results["belowTarget"]
    assert below["paintedCount"] == 7, below
    assert below["paintedCount"] < 10, "a page may only fall below the target when the height cannot hold it"
    assert not below["overflow"], below

    single = results["singlePage"]
    assert single["paintedCount"] == 6 and single["painted"] == [str(i) for i in range(1, 7)], single
    assert not single["pagerVisible"] and not single["overflow"] and single["size"] == 6, single

    pager_first = results["pagerFirst"]
    assert not pager_first["overflow"], pager_first
    assert pager_first["clientHeight"] < 600, "the pager bar is part of the constrained height"
    assert pager_first["everyPaintMeasuredWithPager"], pager_first
    assert pager_first["scrollHeight"] <= pager_first["clientHeight"], pager_first

    wrapped = results["wrappedRow"]
    assert wrapped["paintedCount"] == 10 and wrapped["size"] == 10, wrapped
    assert not wrapped["overflow"], wrapped
    assert wrapped["paints"] >= 3, "the grown page must be measured and reverted: " + str(wrapped)

    high = results["clampHigh"]
    assert high["page"] == 6 and high["painted"][-1] == "100" and high["painted"][0] == "91", high
    assert high["info"] == "Page 7 / 7 · mains 91–100 sur 100", high
    assert not high["prevDisabled"] and high["nextDisabled"], high
    low = results["clampLow"]
    assert low["page"] == 0 and low["prevDisabled"] and not low["nextDisabled"], low

    selection = results["selection"]
    assert "5" in selection["painted"], selection
    assert selection["selectedHand"] == {"id": "5"}, "a bounded repaint must not clear the selection"

    mobile = results["mobile"]
    assert mobile["paintedCount"] == 100 and not mobile["pagerVisible"], mobile

    # Non-vacuity: the two load-bearing declarations are replayed as strings.
    raised = run_runtime("cap")
    assert raised["capped"]["paintedCount"] > 15, (
        "raising the page-size cap must let the measured page exceed 15 rows, else the cap is not proven",
        raised["capped"],
    )
    unhidden = run_runtime("pager-first")
    assert unhidden["pagerFirst"]["overflow"], (
        "without the pager-first measurement, the pager appearance hides the last row: the guard is load-bearing",
        unhidden["pagerFirst"],
    )

    assert INDEX_PATH.read_text(encoding="utf-8") == INDEX, "the replay must never write site/index.html"


def main() -> None:
    check_static_contract()
    check_runtime_contract()
    print(
        "review inbox pagination contract checks: OK "
        "(page window 10–15 measured on the constrained shell, shrink without hidden overflow, "
        "bounded pager, filter/sort restart at page 1, selection preserved)"
    )


if __name__ == "__main__":
    main()

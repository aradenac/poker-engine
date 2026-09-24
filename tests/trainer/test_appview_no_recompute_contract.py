#!/usr/bin/env python3
"""#394 T3 — a view change must stay a pure DOM toggle.

Two layers are checked.

1. Static contract (always run, no browser, no server):

   * no scroll / `IntersectionObserver` / `visibilitychange` listener anywhere in
     the served site may re-schedule a computation (`scheduleBackgroundReviewScoring`
     or `scheduleAutoCalculate`) — including the removed
     `hhHandsEl.addEventListener('scroll', …)` trigger;
   * `updateAppView()` schedules no compute: it only toggles the DOM shells and
     (re)poses the per-view `pokerComputeScheduler.hold(...)` gates;
   * the per-view holds are always re-evaluated from the mounted view, so a hold
     posed on view entry is released on view exit and cannot leak across views;
   * reopening a view reuses the already produced results
     (`state.reviewScores`, `state.actionEquityCache`, `state.seatEquityCache`)
     instead of scoring again, while the inbox pagination
     (`renderReviewInboxPage` + `#hhListPager`) stays the sole bound of the list.
   * selecting a sub-view tab (the Replayer contextual panel
     Décision / Ranges / Détails included) is a pure visibility toggle scoped to
     the owning shell: one pane visible, `aria-selected` / roving `tabindex`
     updated, no pane re-rendered and no computation scheduled.

2. Runtime invariance (`node`, required — the trainer CI job already runs Node):
   the real `updateAppView()` source is executed against the real
   `ComputeScheduler` from `site/compute-scheduler.js` while cycling every view.
   It must create no worker, enqueue no task and call no scheduling entry point,
   keep the holds balanced, and the holds must actually gate background admission.

3. Runtime sub-view invariance (`node`): the real `activateAppSubview()` /
   `activateAppSubviewForTarget()` sources are executed against a minimal DOM
   modelling the Replayer and Review shells, with the compute entry points and
   the pane renderers instrumented: switching tabs must toggle exactly one pane
   per owning shell, never leak into a neighbouring view, and never schedule a
   computation or re-render a pane.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX_PATH = ROOT / "site" / "index.html"
INDEX = INDEX_PATH.read_text(encoding="utf-8")

SCHEDULING_ENTRY_POINTS = ("scheduleBackgroundReviewScoring", "scheduleAutoCalculate")
SCROLL_RESCHEDULE_PATTERNS = (
    "addEventListener('scroll'",
    'addEventListener("scroll"',
    "addEventListener('scrollend'",
    'addEventListener("scrollend"',
    "onscroll",
    "IntersectionObserver",
    "visibilitychange",
)


def js_function_source(source: str, name: str) -> str:
    """Extract `function <name>(…) { … }` by matching the parameter list then braces."""
    anchor = f"function {name}("
    start = source.index(anchor)
    cursor = source.index("(", start + len("function "))
    depth = 0
    while cursor < len(source):
        char = source[cursor]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                break
        cursor += 1
    cursor = source.index("{", cursor)
    depth = 0
    while cursor < len(source):
        char = source[cursor]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start:cursor + 1]
        cursor += 1
    raise AssertionError(f"unbalanced function body: {name}")


def site_sources() -> dict[str, str]:
    files = {path: path.read_text(encoding="utf-8") for path in sorted((ROOT / "site").rglob("*.js"))}
    files[INDEX_PATH] = INDEX
    return files


def check_no_scroll_rescheduler() -> None:
    for path, text in site_sources().items():
        for pattern in SCROLL_RESCHEDULE_PATTERNS:
            assert pattern not in text, f"{path.relative_to(ROOT)}: forbidden compute trigger {pattern}"
    # The explicit residual trigger removed by #394 T3 stays removed.
    assert "hhHandsEl.addEventListener" not in INDEX, "hhHandsEl must not register a listener"
    assert "scheduleBackgroundReviewScoring(180),{passive:true}" not in INDEX


def check_update_app_view_is_pure() -> None:
    body = js_function_source(INDEX, "updateAppView")
    for entry_point in SCHEDULING_ENTRY_POINTS:
        assert entry_point not in body, f"updateAppView must not schedule compute: {entry_point}"
    for compute in ("createWorker", "requestIdleCallback", "setTimeout", "enqueueReplayPreparation"):
        assert compute not in body, f"updateAppView must stay a DOM toggle: {compute}"

    # Per-view holds are re-derived from the mounted view on every call, so an
    # entry hold is released on exit and no hold can leak between views.
    assert "window.pokerComputeScheduler.hold('replayer',mount==='replayer');" in body
    assert "window.pokerComputeScheduler.hold('training',mount==='training');" in body
    assert body.count("pokerComputeScheduler.hold(") == 2, "updateAppView poses exactly the two view holds"

    # The mount is the single source of truth shared by the DOM toggle and the holds.
    mount_assignment = "const mount=showReplay?'replayer':view;"
    assert mount_assignment in body
    assert body.index(mount_assignment) < body.index("hold('replayer'")
    assert body.index(mount_assignment) < body.index("hold('training'")


def check_view_switch_entry_points_are_pure() -> None:
    for name in ("openReplayerPage", "returnToHandsPage"):
        body = js_function_source(INDEX, name)
        for entry_point in SCHEDULING_ENTRY_POINTS:
            assert entry_point not in body, f"{name} must stay a pure view change: {entry_point}"
    back = js_function_source(INDEX, "returnToHandsPage")
    assert "activateAppSubview(\"inbox\")" in back
    assert "scrollIntoView" not in back, "the shell selects the pane; it never scrolls the document"


def check_cache_reuse() -> None:
    # Review scores: a stored score with the current context signature is returned
    # as-is (same object), never recomputed.
    summary = js_function_source(INDEX, "reviewSummaryForHand")
    assert "state.reviewScores?.[String(hand.id)]||hand.reviewScore||null" in summary
    assert "r.signature===reviewContextSignature()?r:null" in summary
    for entry_point in SCHEDULING_ENTRY_POINTS:
        assert entry_point not in summary

    # Background scoring skips hands whose stored score is complete for the
    # current signature, and the inbox list never re-scores: it is bounded by
    # its pagination instead.
    assert (
        "hand=candidates.find(h=>{const r=state.reviewScores?.[String(h.id)];"
        "return !(r&&r.complete&&r.signature===sig);})" in INDEX
    )
    inbox_page = js_function_source(INDEX, "renderReviewInboxPage")
    for entry_point in SCHEDULING_ENTRY_POINTS:
        assert entry_point not in inbox_page, f"pagination must not reschedule compute: {entry_point}"
    assert "hhListPager" in INDEX and "updateReviewInboxPager(" in INDEX
    assert "REVIEW_INBOX_PAGE_SIZE_DEFAULT" in INDEX

    # Action EV cache and seat equities: a terminal cache entry short-circuits the
    # worker enqueue and repaints from the cached result.
    action_step = js_function_source(INDEX, "prepareActionEquityStep")
    assert "if(existing&&['running','done','error'].includes(existing.status))return;" in action_step
    seat_step = js_function_source(INDEX, "prepareSeatEquityStep")
    assert "const existing=state.seatEquityCache[key];" in seat_step
    assert "if(existing?.status==='done'){" in seat_step
    assert "applySeatEquityCacheResult(existing,stepIndex);renderVisualReplay();" in seat_step
    seat_start = js_function_source(INDEX, "startSeatEquityCalculation")
    assert "if(cached?.status==='done'&&cached.result){applySeatEquityCacheResult(cached,stepIndex);renderVisualReplay();return;}" in seat_start


RUNTIME_SCRIPT = r"""
const fs=require('node:fs');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const {ComputeScheduler}=require('./site/compute-scheduler.js');

const html=fs.readFileSync('site/index.html','utf8');
const APP_VIEWS=["home","review","replayer","spotlab","training","strategy"];

function extractFn(source,name){
  const start=source.indexOf('function '+name+'(');
  if(start<0)throw new Error('missing '+name);
  let cursor=source.indexOf('(',start+'function '.length),depth=0;
  for(;cursor<source.length;cursor++){
    const ch=source[cursor];
    if(ch==='(')depth++;
    else if(ch===')'){depth--;if(depth===0)break;}
  }
  cursor=source.indexOf('{',cursor);depth=0;
  for(;cursor<source.length;cursor++){
    const ch=source[cursor];
    if(ch==='{')depth++;
    else if(ch==='}'){depth--;if(depth===0)return source.slice(start,cursor+1);}
  }
  throw new Error('unbalanced '+name);
}

let workerConstructs=0,scheduleCalls=[],scrollCalls=0,replayRenders=0;
let seatReuse=0;
class CountingWorker{
  constructor(url){workerConstructs++;this.url=url;}
  postMessage(payload){this.payload=payload;}
  terminate(){}
}
const scheduler=new ComputeScheduler({maxWorkers:2,WorkerClass:CountingWorker});
const reviewScores=Object.create(null),actionEquityCache=Object.create(null),seatEquityCache=Object.create(null);
const state={appView:'home',hhMode:false,selectedHand:null,replaySteps:[{}],replayIndex:0,reviewScores,actionEquityCache,seatEquityCache};

const sandbox={
  APP_VIEWS,
  state,
  console,
  quickNav:null,
  replayerPageSub:null,
  window:{pokerComputeScheduler:scheduler,scrollTo(){scrollCalls++;}},
  document:{querySelectorAll:()=>[],body:{classList:{toggle(){}},dataset:{}}},
  requestAnimationFrame:fn=>{fn();},
  currentAppView(){return APP_VIEWS.includes(state.appView)?state.appView:'home';},
  renderVisualReplay(){replayRenders++;},
  renderHistoryReplay(){replayRenders++;},
  appViewUpdateIdentityMirror(){},
  actionEquityKey:()=>'action-key',
  seatEquityKey:()=>'seat-key',
  applySeatEquityCacheResult(){seatReuse++;return true;},
  handStreetLabel:()=>'Street',
  formatBB:value=>String(value),
  reviewContextSignature:()=>'sig-live',
  scheduleBackgroundReviewScoring:reason=>{scheduleCalls.push(String(reason));},
  scheduleAutoCalculate:()=>{scheduleCalls.push('auto');},
};

vm.createContext(sandbox);
vm.runInContext(extractFn(html,'updateAppView'),sandbox);
vm.runInContext(extractFn(html,'reviewSummaryForHand'),sandbox);
vm.runInContext(extractFn(html,'prepareSeatEquityStep'),sandbox);
vm.runInContext(extractFn(html,'prepareActionEquityStep'),sandbox);

// Guard the harness itself: the executed functions are the real site sources.
assert.ok(sandbox.updateAppView.toString().includes("hold('replayer'"),'the real updateAppView was evaluated');
assert.ok(sandbox.reviewSummaryForHand.toString().includes('reviewContextSignature'),'the real reviewSummaryForHand was evaluated');
assert.ok(sandbox.prepareSeatEquityStep.toString().includes('seatEquityCache'),'the real prepareSeatEquityStep was evaluated');
assert.ok(sandbox.prepareActionEquityStep.toString().includes('actionEquityCache'),'the real prepareActionEquityStep was evaluated');

let expectedWorkers=0;
function assertNoCompute(label){
  assert.equal(workerConstructs,expectedWorkers,label+': no worker may be created');
  assert.equal(scheduler.active.size,0,label+': no active task');
  assert.equal(scheduler.queue.length,0,label+': no queued task');
  assert.deepEqual(scheduleCalls,[],label+': no scheduling entry point');
  assert.equal(scrollCalls,0,label+': a pure view switch (no scrollTop) never scrolls the document');
}

// 1. Cycling every view is a pure DOM toggle: no worker, no task, no scheduling.
for(const view of ['home','review','spotlab','strategy','training','home','review']){
  state.appView=view;
  sandbox.updateAppView();
  assert.equal(state.appView,view);
  const expectedHolds=view==='training'?['training']:[];
  assert.deepEqual([...scheduler.holds],expectedHolds,view+': only the mounted view holds compute');
  assertNoCompute(view);
}
const cycleSnapshot=scheduler.snapshot();
assert.deepEqual(cycleSnapshot.queueLength,{interaction:0,replayer:0,explicit:0,prefetch:0,background:0},
  'switching views enqueues no task of any priority');
assert.equal(cycleSnapshot.workersActive,0,'switching views activates no worker');
assert.equal(cycleSnapshot.maxConcurrency,0,'switching views never reaches a worker slot');
assert.equal(cycleSnapshot.cancellations,0);
assert.equal(cycleSnapshot.preemptions,0);
assert.equal(scheduler.paused,false,'background compute stays admitted outside training/replayer');

// 2. A mounted Trainer view holds background admission without leaking on exit.
state.appView='training';
sandbox.updateAppView();
assert.deepEqual([...scheduler.holds],['training'],'training hold is posed on view entry');
assert.equal(scheduler.paused,true,'the mounted Training view pauses background admission');
const held=scheduler.createWorker('about:blank',{kind:'background'});
held.postMessage({seed:1});
assert.equal(scheduler.active.size,0,'background admission is held while Training is mounted');
assert.equal(scheduler.queue.length,1);
state.appView='review';
sandbox.updateAppView();
assert.equal(scheduler.holds.size,0,'the hold is released when the view is left');
assert.equal(scheduler.active.size,1,'releasing the view hold resumes the queued background task');
assert.equal(workerConstructs,1,'the held task is the only worker ever constructed');
expectedWorkers=1;
held.terminate();
assert.equal(scheduler.active.size,0);

// 3. The Replayer view poses its own hold, also released on exit.
state.hhMode=true;
state.selectedHand={id:7,dateText:'2026-01-01',heroName:'Hero'};
state.appView='replayer';
sandbox.updateAppView();
assert.deepEqual([...scheduler.holds],['replayer'],'replayer hold is posed on view entry');
state.appView='review';
sandbox.updateAppView();
assert.equal(scheduler.holds.size,0,'the replayer hold is released when the view is left');
assertNoCompute('replayer cycle');

// 4. Reopening a view reuses the produced results instead of re-scoring them.
const score={signature:'sig-live',complete:true,totalLossBB:2.5};
state.reviewScores['7']=score;
const reused=sandbox.reviewSummaryForHand({id:7});
assert.equal(reused,score,'the stored Review score object is reused as-is');
const stale=sandbox.reviewSummaryForHand({id:8});
assert.equal(stale,null,'an absent score is not fabricated');
assert.equal(state.reviewScores,reviewScores,'the Review score store is never replaced by a view switch');
assert.equal(state.actionEquityCache,actionEquityCache,'the action EV cache is never replaced by a view switch');
assert.equal(state.seatEquityCache,seatEquityCache,'the seat equity cache is never replaced by a view switch');
assertNoCompute('cache reuse');

// 5. The stored caches really short-circuit the workers: a terminal entry is
// repainted from the cache and never enqueues a new computation.
state.hhMode=true;
state.selectedHand={id:7};
state.replayIndex=0;
state.seatEquityCache['seat-key']={status:'done',result:{status:'done',range:{Hero:.5},real:{Hero:.5},heroScenarios:{},hasRange:{},hasReal:{},error:''}};
sandbox.prepareSeatEquityStep(0);
assert.equal(seatReuse,1,'a done seat-equity cache entry is reused instead of recomputed');
assertNoCompute('seat equity cache reuse');

state.actionEquityCache['action-key']={status:'done',equities:{prior:.5},stepIndex:0};
sandbox.prepareActionEquityStep(0,{});
assertNoCompute('action EV cache reuse');

process.stdout.write('runtime view-switch invariance: OK\n');
"""


def check_runtime_invariance() -> None:
    node = shutil.which("node")
    if node is None:
        raise AssertionError("node runtime is required for the view-switch invariance contract")
    completed = subprocess.run(
        [node, "-e", RUNTIME_SCRIPT],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "runtime view-switch invariance: OK" in completed.stdout, completed.stdout


SUBVIEW_RUNTIME_SCRIPT = r"""
const fs=require('node:fs');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const {ComputeScheduler}=require('./site/compute-scheduler.js');

const html=fs.readFileSync('site/index.html','utf8');

function extractFn(source,name){
  const start=source.indexOf('function '+name+'(');
  if(start<0)throw new Error('missing '+name);
  let cursor=source.indexOf('(',start+'function '.length),depth=0;
  for(;cursor<source.length;cursor++){
    const ch=source[cursor];
    if(ch==='(')depth++;
    else if(ch===')'){depth--;if(depth===0)break;}
  }
  cursor=source.indexOf('{',cursor);depth=0;
  for(;cursor<source.length;cursor++){
    const ch=source[cursor];
    if(ch==='{')depth++;
    else if(ch==='}'){depth--;if(depth===0)return source.slice(start,cursor+1);}
  }
  throw new Error('unbalanced '+name);
}

function appHashSubviewsSource(source){
  const start=source.indexOf('const APP_HASH_SUBVIEWS={');
  const end=source.indexOf('};',start);
  if(start<0||end<0)throw new Error('missing APP_HASH_SUBVIEWS');
  return source.slice(start,end+2);
}

// Minimal DOM: only what the scoped sub-view helpers touch.
class FakeElement{
  constructor(tag){
    this.tagName=tag;this.dataset={};this.attributes={};this.children=[];
    this.parentElement=null;this.hidden=false;this.tabIndex=0;this.shell=null;
  }
  setAttribute(name,value){this.attributes[name]=String(value);}
  getAttribute(name){return Object.hasOwn(this.attributes,name)?this.attributes[name]:null;}
  closest(selector){return selector==='[data-view-shell]'?this.shell:null;}
  querySelectorAll(selector){
    const out=[];
    const walk=node=>{
      for(const child of node.children){
        if(selector==='[data-app-subview-panel]'&&child.dataset.appSubviewPanel!==undefined)out.push(child);
        if(selector==='[data-app-subview]'&&child.dataset.appSubview!==undefined)out.push(child);
        walk(child);
      }
    };
    walk(this);
    return out;
  }
}

function makeShell(view,subviews){
  const shell=new FakeElement('div');
  shell.shell=shell;
  shell.dataset.viewShell=view;
  const list=new FakeElement('div');
  list.parentElement=shell;shell.children.push(list);
  const tabs=new Map(),panels=new Map();
  for(const name of subviews){
    const tab=new FakeElement('button');
    tab.dataset.appSubview=name;tab.parentElement=list;tab.shell=shell;list.children.push(tab);
    const panel=new FakeElement('div');
    panel.dataset.appSubviewPanel=name;panel.parentElement=shell;panel.shell=shell;shell.children.push(panel);
    tabs.set(name,tab);panels.set(name,panel);
  }
  return {view,shell,tabs,panels};
}

const REPLAYER_SUBVIEWS=['replayer-decision','replayer-ranges','replayer-details'];
const shells=[
  makeShell('replayer',REPLAYER_SUBVIEWS),
  makeShell('review',['pilotage','inbox']),
  makeShell('spotlab',['spotlab-situation','spotlab-board','spotlab-range','spotlab-equity']),
];
const document={
  querySelectorAll(selector){
    if(selector==='[data-app-subview]')return shells.flatMap(s=>[...s.tabs.values()]);
    if(selector==='[data-app-subview-panel]')return shells.flatMap(s=>[...s.panels.values()]);
    return [];
  }
};

let scheduleCalls=[],workerConstructs=0,paneRenders=0,inboxRenders=0;
class CountingWorker{constructor(url){workerConstructs++;}postMessage(){}terminate(){}}
const scheduler=new ComputeScheduler({maxWorkers:2,WorkerClass:CountingWorker});

const sandbox={
  document,
  Element:FakeElement,
  console,
  state:{},
  window:{pokerComputeScheduler:scheduler},
  scheduleAutoCalculate:()=>scheduleCalls.push('auto'),
  scheduleBackgroundReviewScoring:()=>scheduleCalls.push('review'),
  startSeatEquityCalculation:()=>scheduleCalls.push('seat'),
  renderVisualReplay:()=>paneRenders++,
  renderHistoryReplay:()=>paneRenders++,
  renderHistoryHands:()=>inboxRenders++,
};
vm.createContext(sandbox);
vm.runInContext([
  appHashSubviewsSource(html),
  extractFn(html,'appSubviewForHashTarget'),
  extractFn(html,'appSubviewTabs'),
  extractFn(html,'appSubviewPanels'),
  extractFn(html,'appSubviewScopeFor'),
  extractFn(html,'activateAppSubview'),
  extractFn(html,'activateAppSubviewForTarget'),
].join('\n'),sandbox);

// The executed code is the real production source.
assert.ok(sandbox.activateAppSubview.toString().includes('appSubviewScopeFor(tab)'),'the real activateAppSubview was evaluated');
assert.ok(sandbox.appSubviewForHashTarget.toString().includes('APP_HASH_SUBVIEWS'),'the real APP_HASH_SUBVIEWS was evaluated');
assert.ok(sandbox.appSubviewPanels.toString().includes('[data-app-subview-panel]'),'the real appSubviewPanels was evaluated');

const replayer=shells[0],review=shells[1],spotlab=shells[2];
function visiblePanes(shell){return [...shell.panels.values()].filter(panel=>!panel.hidden).map(panel=>panel.dataset.appSubviewPanel);}
function selectedTabs(shell){return [...shell.tabs.values()].filter(tab=>tab.getAttribute('aria-selected')==='true').map(tab=>tab.dataset.appSubview);}
function assertNoCompute(label){
  assert.deepEqual(scheduleCalls,[],label+': no scheduling entry point');
  assert.equal(workerConstructs,0,label+': no worker created');
  assert.equal(scheduler.active.size,0,label+': no active task');
  assert.equal(scheduler.queue.length,0,label+': no queued task');
  assert.equal(paneRenders,0,label+': no pane re-rendered');
}

// The Replayer contextual panel is a three-pane tab widget: selecting a tab
// shows exactly that pane, updates aria-selected and keeps a roving tabindex.
for(const name of REPLAYER_SUBVIEWS){
  assert.equal(sandbox.activateAppSubview(name),true,name);
  assert.deepEqual(visiblePanes(replayer),[name],name+': exactly one visible pane');
  assert.deepEqual(selectedTabs(replayer),[name],name+': one selected tab');
  assert.deepEqual(
    [...replayer.tabs.values()].map(tab=>tab.tabIndex),
    REPLAYER_SUBVIEWS.map(candidate=>candidate===name?0:-1),
    name+': roving tabindex'
  );
  // A neighbouring shell is never toggled.
  assert.equal(review.panels.get('pilotage').hidden,false,'pilotage stays mounted');
  assert.equal(review.panels.get('inbox').hidden,false,'inbox stays mounted');
  assert.equal(spotlab.panels.get('spotlab-board').hidden,false,'spotlab stays mounted');
  assertNoCompute(name);
}

// A Review tab does not blank the Replayer panes, and vice versa.
sandbox.activateAppSubview('inbox');
assert.deepEqual(visiblePanes(review),['inbox'],'review shows its own pane');
assert.deepEqual(visiblePanes(replayer),['replayer-details'],'the Replayer keeps its own selected pane');
assert.equal(inboxRenders,1,'only the bounded inbox pane renders on activation');
assertNoCompute('cross-view activation');

// Deep links select the owning tab instead of scrolling to the shell.
assert.equal(sandbox.appSubviewForHashTarget('replayerSection'),'replayer-decision');
assert.equal(sandbox.appSubviewForHashTarget('replayerPage'),'replayer-decision');
assert.equal(sandbox.activateAppSubviewForTarget('replayerSection'),true);
assert.deepEqual(selectedTabs(replayer),['replayer-decision'],'the deep link selects the owning tab');
assertNoCompute('deep link');

process.stdout.write('runtime sub-view activation invariance: OK\n');
"""


def check_subview_activation_is_pure() -> None:
    node = shutil.which("node")
    if node is None:
        raise AssertionError("node runtime is required for the sub-view activation contract")
    completed = subprocess.run(
        [node, "-e", SUBVIEW_RUNTIME_SCRIPT],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "runtime sub-view activation invariance: OK" in completed.stdout, completed.stdout


def main() -> None:
    check_no_scroll_rescheduler()
    check_update_app_view_is_pure()
    check_view_switch_entry_points_are_pure()
    check_cache_reuse()
    check_subview_activation_is_pure()
    check_runtime_invariance()
    print("app-view no-recompute contract checks: OK")


if __name__ == "__main__":
    main()

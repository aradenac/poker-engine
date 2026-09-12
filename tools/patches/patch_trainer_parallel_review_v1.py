#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "site" / "index.html"

START = "function runReviewBatchPlan(plan){"
END = "function scheduleBackgroundReviewScoring(delay=120){"

NEW_BLOCK = r'''function reviewBatchWorkerLimit(){
  if(!document.body.classList.contains('trainer-view-open'))return 1;
  const hc=Math.max(1,Number(navigator.hardwareConcurrency)||4);
  return hc>=8?3:hc>=4?2:1;
}
function runReviewBatchPlan(plan){
  state.reviewBatchBusy=true;
  const all=[];
  for(const a of plan.actions)for(const t of a.tasks)all.push({a,t,order:all.length});
  let pos=0,active=0,finished=false;
  state.reviewBatchWorkers=[];

  const finish=()=>{
    if(finished||pos<all.length||active>0)return;
    finished=true;
    for(const a of plan.actions){
      if(!Array.isArray(a.sizingResults))continue;
      a.sizingResults.sort((x,y)=>Number(x.__reviewOrder||0)-Number(y.__reviewOrder||0));
      for(const z of a.sizingResults)delete z.__reviewOrder;
    }
    state.reviewBatchWorker=null;state.reviewBatchWorkers=[];state.reviewBatchBusy=false;
    finalizeReviewBatchPlan(plan);scheduleBackgroundReviewScoring(20);
  };

  const launch=({a,t,order})=>{
    let worker;
    try{worker=(t.kind==='tree'||t.kind==='sizing')?createPostflopBetRaiseEVWorker():createTableEquityWorker();}
    catch(_){a.failed=true;return;}
    active++;
    state.reviewBatchWorkers.push(worker);state.reviewBatchWorker=worker;
    let settled=false;
    const done=(m,isError)=>{
      if(settled)return;settled=true;
      cleanupReplayWorker(worker);
      const wi=state.reviewBatchWorkers.indexOf(worker);if(wi>=0)state.reviewBatchWorkers.splice(wi,1);
      state.reviewBatchWorker=state.reviewBatchWorkers[state.reviewBatchWorkers.length-1]||null;
      active=Math.max(0,active-1);
      if(t.kind==='equity'){
        if(!isError&&m?.type==='result'&&m.out?.names){const idx=m.out.names.indexOf(a.actor);a.values[t.scenario]=idx>=0?m.out.equities[idx]:NaN;}
        else a.values[t.scenario]=NaN;
      }else if(t.kind==='tree')a.treeValues[t.scenario]=(!isError&&m?.type==='result')?m.out:null;
      else if(t.kind==='sizing')a.sizingResults.push({...t.candidate,tree:(!isError&&m?.type==='result')?m.out:null,__reviewOrder:order});
      if(isError||m?.type!=='result')a.failed=true;
      queueMicrotask(pump);
    };
    worker.onmessage=e=>done(e.data,e.data?.type!=='result');
    worker.onerror=e=>done({type:'error',message:e.message||'Erreur worker'},true);
    try{worker.postMessage(t.snapshot);}catch(err){done({type:'error',message:err?.message||String(err)},true);}
  };

  const pump=()=>{
    if(finished)return;
    if(state.appView==='replayer'||state.replayComputeActive.length||state.replayComputeQueue.length){
      if(active===0)setTimeout(pump,80);
      return;
    }
    const limit=reviewBatchWorkerLimit();
    while(active<limit&&pos<all.length){
      const item=all[pos++];launch(item);
    }
    finish();
  };
  pump();
}
'''


def main() -> None:
    text = PATH.read_text(encoding="utf-8")
    if text.count(START) != 1 or text.count(END) != 1:
        raise SystemExit("review batch markers are not unique")
    a = text.index(START)
    b = text.index(END, a)
    old = text[a:b]
    if "state.reviewBatchWorker=worker" not in old or "const next=()=>" not in old:
        raise SystemExit("unexpected review batch implementation; refusing to patch")
    text = text[:a] + NEW_BLOCK + text[b:]
    PATH.write_text(text, encoding="utf-8")
    print("patched trainer review worker pool for issue #23")


if __name__ == "__main__":
    main()

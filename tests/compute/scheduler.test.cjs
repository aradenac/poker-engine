const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const {ComputeScheduler}=require('../../site/compute-scheduler.js');
class Worker {
 static alive=new Set();
 constructor(url){this.url=url;Worker.alive.add(this);}
 postMessage(p){this.payload=p;}
 terminate(){Worker.alive.delete(this);}
 result(){this.onmessage({data:{type:'result',out:this.payload}});}
}
function setup(maxWorkers=2){Worker.alive.clear();return new ComputeScheduler({maxWorkers,WorkerClass:Worker});}
function submit(s,kind){const w=s.createWorker(kind,{kind});w.postMessage({seed:42,budget:100});return w;}
test('global cap and FIFO across producer classes, background cap',()=>{
 const s=setup();const b=submit(s,'background'),b2=submit(s,'background');assert.equal(s.active.size,1);
 const e=submit(s,'explicit');assert.equal(s.active.has(b),true);assert.equal(s.active.has(e),true);
 for(let i=0;i<8;i++)submit(s,'explicit');assert.equal(s.active.size,2);assert.equal(Worker.alive.size,2);
 while(s.active.size)[...s.active][0].worker.result();
 assert.equal(s.metrics.maxConcurrency,2);assert.equal(b2.done,true);assert.equal(s.metrics.backgroundResumed,1);
});
test('priority, preemption, stale completion and cancellation',()=>{
 const s=setup(1),p=submit(s,'prefetch'),old=p.worker;
 const e=submit(s,'explicit'),r=submit(s,'replayer'),i=submit(s,'interaction');
 assert.equal([...s.active][0],i);let stale=0;p.onmessage=()=>stale++;old.result();assert.equal(stale,0);
 i.worker.result();assert.equal([...s.active][0],r);
 e.terminate();r.worker.result();assert.equal([...s.active][0],p);
 p.worker.result();assert.equal(stale,1);assert.equal(s.queue.length,0);
});
test('training/interaction holds stop background admission without restarting active work',()=>{
 const s=setup(),b=submit(s,'background'),instance=b.worker;s.hold('training',true);assert.equal(s.active.has(b),true);
 const queued=submit(s,'background');s.hold('interaction',true);s.hold('training',false);assert.equal(s.active.has(b),true);assert.equal(queued.worker,null);
 s.hold('interaction',false);assert.equal(b.worker,instance);assert.deepEqual(b.worker.payload,{seed:42,budget:100});
 b.terminate();assert.equal(s.active.has(queued),true);queued.terminate();assert.equal(s.active.size,0);
});
test('a hold blocks initial background admission until it is released',()=>{
 const s=setup();s.hold('training',true);const b=submit(s,'background');assert.equal(b.worker,null);
 s.hold('training',false);assert.equal(s.active.has(b),true);b.terminate();
});
test('payload is serialized only by the real worker postMessage',()=>{
 const s=setup(),payload={large:['snapshot']},w=s.createWorker('explicit',{kind:'explicit'});w.postMessage(payload);
 assert.equal(w.payload,payload);assert.equal(w.worker.payload,payload);w.terminate();
});
test('free capacity admits higher priority without preempting active work',()=>{
 const s=setup(2),p=submit(s,'prefetch'),instance=p.worker,r=submit(s,'replayer');
 assert.equal(s.active.has(p),true);assert.equal(p.worker,instance);assert.equal(s.active.has(r),true);
 assert.equal(s.metrics.preemptions,0);
});
test('contention preempts at most one lower-priority task per waiting candidate',()=>{
 const s=setup(2),p1=submit(s,'prefetch'),p2=submit(s,'prefetch'),r=submit(s,'replayer');
 assert.equal(s.active.has(r),true);assert.equal(s.metrics.preemptions,1);
 assert.equal([p1,p2].filter(p=>s.active.has(p)).length,1);
});
test('errors release slots; progress retains slot; cancellation removes queue',()=>{
 const s=setup(1),a=submit(s,'explicit'),b=submit(s,'explicit');b.terminate();
 a.worker.onmessage({data:{type:'progress'}});assert.equal(s.active.size,1);
 a.worker.onerror({message:'failed'});assert.equal(s.active.size,0);
 assert.equal(s.snapshot().queueLength.explicit,0);
});
test('all production worker factories use global scheduler; inline JS parses',()=>{
 const html=fs.readFileSync('site/index.html','utf8');assert.equal((html.match(/createWorker\(url,computeOptions\)/g)||[]).length,3);
 assert.equal(/new Worker\(/.test(html),false);
 for(const m of html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g))new vm.Script(m[1]);
});
test('Training batch runs as explicit while background is held',()=>{
 const s=setup();s.hold('training',true);let final;
 const html=fs.readFileSync('site/index.html','utf8');
 const code=html.slice(html.indexOf('function runReviewBatchPlan('),html.indexOf('function scheduleBackgroundReviewScoring('));
 const state={reviewBatchTicket:1,replayComputeActive:[],replayComputeQueue:[]};
 const context={state,window:{pokerComputeScheduler:s},reviewContextSignature:()=> 'same',reviewBatchWorkerLimit:()=>1,
   createTableEquityWorker:opts=>s.createWorker('equity',opts),cleanupReplayWorker:w=>w.terminate(),
   finalizeReviewBatchPlan:p=>{final=p;},scheduleBackgroundReviewScoring:()=>{},queueMicrotask:fn=>fn(),setTimeout:()=>{throw Error('Training must not wait for its own hold');}};
 vm.createContext(context);vm.runInContext(code,context);
 const plan={signature:'same',actions:[{actor:'Hero',values:{},tasks:[{kind:'equity',scenario:'prior',snapshot:{names:['Hero'],equities:[0.5]}}]}]};
 context.runReviewBatchPlan(plan,{kind:'explicit'});
 assert.equal(s.active.size,1);[...s.active][0].worker.result();assert.equal(final,plan);assert.equal(plan.actions[0].values.prior,0.5);
});
test('obsolete review ticket clears in-flight batch state and workers',()=>{
 const s=setup(1);
 const html=fs.readFileSync('site/index.html','utf8');
 const code=html.slice(html.indexOf('function runReviewBatchPlan('),html.indexOf('function scheduleBackgroundReviewScoring('));
 const state={reviewBatchTicket:1,replayComputeActive:[],replayComputeQueue:[]};
 const context={state,window:{pokerComputeScheduler:s},reviewContextSignature:()=> 'same',reviewBatchWorkerLimit:()=>1,
   createTableEquityWorker:opts=>s.createWorker('equity',opts),cleanupReplayWorker:w=>w.terminate(),
   finalizeReviewBatchPlan:()=>{throw Error('obsolete batch must not finalize');},scheduleBackgroundReviewScoring:()=>{},queueMicrotask:fn=>fn(),setTimeout:()=>{}};
 vm.createContext(context);vm.runInContext(code,context);
 const task=()=>({kind:'equity',scenario:'prior',snapshot:{names:['Hero'],equities:[0.5]}});
 const plan={signature:'same',actions:[{actor:'Hero',values:{},tasks:[task(),task()]}]};
 context.runReviewBatchPlan(plan);state.reviewBatchTicket++;[...s.active][0].worker.result();
 assert.equal(state.reviewBatchBusy,false);assert.equal(state.reviewBatchRun,null);assert.equal(state.reviewBatchWorkers.length,0);assert.equal(s.active.size,0);
});
test('background callback rechecks busy state and sliced preparation is resumable',()=>{
 const html=fs.readFileSync('site/index.html','utf8');
 const prepare=html.slice(html.indexOf('async function prepareReviewBatchPlan('),html.indexOf('function buildReviewBatchPlan('));
 const schedule=html.slice(html.indexOf('function scheduleBackgroundReviewScoring('),html.indexOf('function exportPolicyBenchmarkForSimulator('));
 assert.equal(prepare.includes('buildReviewBatchPlan(hand,i)'),false);
 assert.equal(/holds\.size\)return null/.test(prepare),false);
 assert.match(prepare,/do\{[\s\S]*\}while\(window\.pokerComputeScheduler\.holds\.size\)/);
 assert.match(schedule,/if\(state\.reviewBatchPreparing\|\|state\.reviewBatchBusy\)/);
 assert.match(schedule,/if\(state\.reviewBatchBusy\)/);
});

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
 const e=submit(s,'explicit');assert.equal(s.active.has(b),false);assert.equal(s.active.has(e),true);
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
test('training/interaction holds suspend and resume background without changing payload',()=>{
 const s=setup(),b=submit(s,'background');s.hold('training',true);assert.equal(s.active.size,0);
 s.hold('interaction',true);s.hold('training',false);assert.equal(s.active.size,0);
 s.hold('interaction',false);assert.deepEqual(b.worker.payload,{seed:42,budget:100});
 b.terminate();assert.equal(s.active.size,0);
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

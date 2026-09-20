// Reproducible orchestration benchmark; runs the unchanged browser kernel in Node workers.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const {Worker}=require('node:worker_threads');
const {ComputeScheduler}=require('../../site/compute-scheduler.js');
const html=fs.readFileSync('site/index.html','utf8');
function kernel(html){
 const start=html.indexOf('function createCalcWorker('),end=html.indexOf('\ncalcBtn.addEventListener',start);
 let source;const context={RANKS:[...'23456789TJQKA'],Blob:class{constructor(parts){source=parts.join('');}},URL:{createObjectURL:()=>''},Worker:class{},window:{pokerComputeScheduler:{createWorker:()=>({})}}};
 vm.runInNewContext(html.slice(start,end)+';createCalcWorker();',context);return source;
}
const source=kernel(html),before=kernel(fs.readFileSync(process.argv[2]||'/tmp/compute-before.html','utf8'));
assert.equal(source,before,'Scientific kernel must remain byte-identical');
const corpus=[JSON.parse(fs.readFileSync('tests/regression/hand_262024556922.json')).raw_hand_history,fs.readFileSync('tests/fixtures/repro/kts_sb_two_limp_iso4_three_calls.hand.txt','utf8')];
const card=c=>'shdc'.indexOf(c[1])*13+'23456789TJQKA'.indexOf(c[0]);
const snapshots=corpus.flatMap(raw=>{
 const hero=raw.match(/Dealt to .*?\[(.*?)\]/)[1].split(' ').map(card);
 const flop=raw.match(/\*\*\* FLOP \*\*\* \[(.*?)\]/)[1].split(' ').map(card);
 return [[],flop].map(board=>({hero,board,method:'mc',trials:2000,opponents:[{hands:[{hand:'AA',frequency:100},{hand:'KQs',frequency:100},{hand:'76s',frequency:100}]}]}));
});
let alive=0,maxAlive=0;
class Adapter{
 constructor(){alive++;maxAlive=Math.max(maxAlive,alive);this.dead=false;
  this.w=new Worker(`const {parentPort}=require('node:worker_threads');global.self=global;global.postMessage=m=>parentPort.postMessage(m);let seed=390;Math.random=()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/4294967296;};${source}\nparentPort.on('message',data=>self.onmessage({data}));`,{eval:true});
  this.w.on('message',data=>this.onmessage?.({data}));this.w.on('error',e=>this.onerror?.(e));
 }
 postMessage(p){this.w.postMessage(p);}
 terminate(){if(!this.dead){this.dead=true;alive--;this.w.terminate();}}
}
async function run(scheduled){
 maxAlive=0;const scheduler=new ComputeScheduler({WorkerClass:Adapter}),delays=[],start=performance.now();let last=start;
 const timer=setInterval(()=>{const now=performance.now();delays.push(Math.max(0,now-last-10));last=now;},10);
 const kinds=['background','prefetch','explicit','replayer','interaction','explicit','prefetch','background'];
 const results=await Promise.all(kinds.map((kind,i)=>new Promise((resolve,reject)=>{
  const w=scheduled?scheduler.createWorker('',{kind}):new Adapter();
  w.onmessage=e=>{if(e.data.type==='progress')return;w.terminate();if(e.data.type==='error')reject(Error(e.data.message));else resolve(e.data.out);};w.onerror=reject;w.postMessage(snapshots[i%snapshots.length]);
 })));
 clearInterval(timer);return {results,metrics:{durationMs:performance.now()-start,maxConcurrency:maxAlive,eventLoopDelayMaxMs:Math.max(...delays),eventLoopDelaysOver50:delays.filter(x=>x>50).length,...(scheduled?{scheduler:scheduler.snapshot()}:{})}};
}
(async()=>{const a=await run(false),b=await run(true);assert.deepEqual(b.results,a.results);assert.ok(b.metrics.maxConcurrency<=2);console.log(JSON.stringify({environment:process.version,corpus:['hand_262024556922','kts_sb_two_limp_iso4_three_calls'],seed:390,trials:2000,kernelIdentical:true,outputsIdentical:true,before:a.metrics,after:b.metrics,browserLongTasks:null},null,2));})().catch(e=>{console.error(e);process.exitCode=1;});

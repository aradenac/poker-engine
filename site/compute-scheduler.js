/* Shared admission control. Worker payloads and numerical kernels are untouched. */
(function(root){
'use strict';
const classes=['interaction','replayer','explicit','prefetch','background'];
class ComputeScheduler {
  constructor({maxWorkers=2,WorkerClass=root.Worker,now=()=>performance.now()}={}){
    this.maxWorkers=Math.max(1,Math.min(8,Math.floor(Number(maxWorkers)||2)));
    this.WorkerClass=WorkerClass;this.now=now;this.queue=[];this.active=new Set();this.holds=new Set();
    this.metrics={maxConcurrency:0,cancellations:0,preemptions:0,backgroundPaused:0,backgroundResumed:0,waitMs:[],durationMs:[],longTasks:[],interactionMs:[]};
    this.paused=false;
  }
  sample(key,value){const a=this.metrics[key];a.push(value);if(a.length>512)a.shift();}
  snapshot(){return {...this.metrics,workersActive:this.active.size,queueLength:Object.fromEntries(classes.map(c=>[c,this.queue.filter(t=>t.kind===c).length]))};}
  hold(key,on){if(on)this.holds.add(key);else this.holds.delete(key);this.pump();}
  createWorker(url,{kind='explicit'}={}){
    if(!classes.includes(kind))throw new Error('Unknown compute priority');
    const s=this,t={url,kind,worker:null,payload:null,submitted:false,done:false,onmessage:null,onerror:null};
    t.postMessage=payload=>{if(t.submitted||t.done)throw new Error('Compute task already submitted');t.submitted=true;t.payload=structuredClone(payload);t.queued=s.now();s.queue.push(t);s.pump();};
    t.terminate=()=>{if(t.done)return;t.done=true;s.metrics.cancellations++;s.stop(t);s.queue=s.queue.filter(x=>x!==t);s.pump();};
    return t;
  }
  stop(t){if(t.worker){t.worker.terminate();t.worker=null;this.sample('durationMs',this.now()-t.started);}this.active.delete(t);}
  pump(){
    const paused=this.holds.size>0||[...this.active,...this.queue].some(t=>classes.indexOf(t.kind)<=2);
    if(paused!==this.paused){this.metrics[paused?'backgroundPaused':'backgroundResumed']++;this.paused=paused;}
    const eligible=t=>!(t.kind==='background'&&(paused||[...this.active].some(x=>x.kind==='background')));
    this.queue.sort((a,b)=>classes.indexOf(a.kind)-classes.indexOf(b.kind)||a.queued-b.queued);
    for(const t of [...this.active]){
      const next=this.queue.find(eligible);
      if((paused&&t.kind==='background')||(next&&classes.indexOf(next.kind)<classes.indexOf(t.kind))){this.stop(t);this.metrics.preemptions++;this.queue.push(t);}
    }
    this.queue.sort((a,b)=>classes.indexOf(a.kind)-classes.indexOf(b.kind)||a.queued-b.queued);
    while(this.active.size<this.maxWorkers){
      const i=this.queue.findIndex(eligible);if(i<0)break;
      const t=this.queue.splice(i,1)[0];t.started=this.now();this.sample('waitMs',t.started-t.queued);
      this.active.add(t);this.metrics.maxConcurrency=Math.max(this.metrics.maxConcurrency,this.active.size);
      let instance;
      const finish=(event,error)=>{
        if(t.done||t.worker!==instance)return;
        if(!error&&event.data?.type==='progress'){t.onmessage?.(event);return;}
        t.done=true;this.stop(t);
        try{if(error)t.onerror?.(event);else t.onmessage?.(event);}finally{this.pump();}
      };
      try{t.worker=new this.WorkerClass(t.url);instance=t.worker;t.worker.onmessage=e=>finish(e,false);t.worker.onerror=e=>finish(e,true);t.worker.postMessage(t.payload);}
      catch(e){instance=t.worker;finish({message:e.message},true);}
    }
  }
}
root.PokerComputeScheduler=ComputeScheduler;
if(typeof module!=='undefined')module.exports={ComputeScheduler};
if(root.document){
 const s=root.pokerComputeScheduler=new ComputeScheduler(root.POKER_COMPUTE_CONFIG||{});
 let timer;
 for(const event of ['pointerdown','keydown','wheel'])document.addEventListener(event,()=>{
   const start=s.now();s.hold('interaction',true);clearTimeout(timer);timer=setTimeout(()=>s.hold('interaction',false),180);
   requestAnimationFrame(()=>setTimeout(()=>s.sample('interactionMs',s.now()-start),0));
 },{capture:true,passive:true});
 try{new PerformanceObserver(list=>{for(const e of list.getEntries())if(e.duration>50)s.sample('longTasks',e.duration);}).observe({type:'longtask',buffered:true});}catch(_){}
}
})(typeof globalThis!=='undefined'?globalThis:this);

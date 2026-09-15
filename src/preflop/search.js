(function(root,factory){
  'use strict';
  if(typeof module==='object'&&module.exports){
    module.exports=factory(require('./decision.js'));
    return;
  }
  if(root)root.PokerPreflopSearch=factory(root.PokerPreflopDecision);
})(typeof globalThis!=='undefined'?globalThis:this,function(Decision){
  'use strict';

  if(!Decision||typeof Decision.buildDecision!=='function')throw new Error('PokerPreflopDecision contract is required');

  const SCHEMA='poker-preflop-search/v1';
  const EPS=1e-9;
  const AGGRESSIVE=new Set(['OPEN','ISO','SQUEEZE','3BET','4BET']);
  const SUPPORTED_STRUCTURAL=new Set(['FOLD','CHECK','LIMP','CALL','RAISE','JAM']);

  class UncoveredPreflopSearchError extends Error{
    constructor(message,details={}){super(message);this.name='UncoveredPreflopSearchError';this.details=details;}
  }

  const finite=(value,name)=>{
    const n=Number(value);if(!Number.isFinite(n))throw new Error(`${name} must be finite`);return n;
  };
  const nonnegative=(value,name)=>{const n=finite(value,name);if(n<-EPS)throw new Error(`${name} must be non-negative`);return Math.max(0,n);};
  const roundBB=value=>Number(Number(value).toFixed(9));
  const fmt=value=>{
    const n=roundBB(value);return Number.isInteger(n)?String(n):String(n).replace(/0+$/,'').replace(/\.$/,'');
  };
  const history=context=>Array.isArray(context?.history)?context.history:[];
  const lastAggression=context=>{
    const xs=history(context);for(let i=xs.length-1;i>=0;i--){const a=String(xs[i]?.action||'').toUpperCase();if(a==='RAISE'||a==='JAM')return {...xs[i],action:a};}return null;
  };

  function semanticRaiseAction(context){
    const raiseLevel=Number(context?.raise_level)||0;
    const family=String(context?.family||'').toUpperCase();
    if(raiseLevel===0)return (context?.limper_positions||[]).length||family==='VS_LIMPERS'?'ISO':'OPEN';
    if(raiseLevel===1)return family==='VS_RFI_CALLERS'||family==='VS_ISO_CALLERS'?'SQUEEZE':'3BET';
    if(raiseLevel===2)return '4BET';
    return null;
  }

  function semanticAction(structural,context){
    const action=String(structural||'').toUpperCase();
    if(!SUPPORTED_STRUCTURAL.has(action))throw new UncoveredPreflopSearchError(`unsupported structural preflop action ${action||'<empty>'}`,{action});
    if(action==='FOLD'||action==='CHECK')return action;
    if(action==='LIMP')return (context?.limper_positions||[]).length?'OVERLIMP':'LIMP';
    if(action==='CALL')return lastAggression(context)?.action==='JAM'?'CALL_SHOVE':'CALL';
    if(action==='JAM')return 'SHOVE';
    const mapped=semanticRaiseAction(context);
    if(!mapped)throw new UncoveredPreflopSearchError('non-all-in raise beyond the supported 4-bet semantic vocabulary',{raise_level:Number(context?.raise_level)||0,family:context?.family||null});
    return mapped;
  }

  function semanticLegalActions(context){
    if(!context||context.schema!=='poker-preflop-context/v1')throw new Error('expected poker-preflop-context/v1');
    const out=[];
    for(const structural of context.legal_actions||[]){
      const action=semanticAction(structural,context);
      if(!out.includes(action))out.push(action);
    }
    if(!out.length)throw new UncoveredPreflopSearchError('preflop context has no supported legal action',{context_id:context.context_id||null});
    return out;
  }

  function normalizeSizingGrid(context,values,{source='explicit_observed_grid'}={}){
    const min=context.min_raise_to_bb==null?null:finite(context.min_raise_to_bb,'min_raise_to_bb');
    const max=finite(context.max_raise_to_bb,'max_raise_to_bb');
    const current=finite(context.current_price_bb,'current_price_bb');
    const unique=[];
    for(const raw of values||[]){
      const target=roundBB(finite(raw,'sizing_grid target'));
      if(target<=current+EPS)continue;
      if(min!=null&&target<min-EPS)continue;
      // The stack-cap action is represented separately as SHOVE/JAM.
      if(target>=max-EPS)continue;
      if(!unique.some(x=>Math.abs(x-target)<=EPS))unique.push(target);
    }
    unique.sort((a,b)=>a-b);
    return {source:String(source||'explicit_observed_grid'),targets_bb:unique};
  }

  function buildCandidates(context,{sizing_grid_bb=[],sizing_grid_source='explicit_observed_grid'}={}){
    const actorPaid=nonnegative(context.actor_contribution_bb,'actor_contribution_bb');
    const current=nonnegative(context.current_price_bb,'current_price_bb');
    const max=nonnegative(context.max_raise_to_bb,'max_raise_to_bb');
    const grid=normalizeSizingGrid(context,sizing_grid_bb,{source:sizing_grid_source});
    const candidates=[];
    const push=(action,target,origin)=>{
      const targetTotal=target==null?null:roundBB(target);
      const cost=targetTotal==null?0:roundBB(Math.max(0,targetTotal-actorPaid));
      const id=targetTotal==null?action:`${action}@${fmt(targetTotal)}`;
      if(!candidates.some(row=>row.id===id))candidates.push({id,action,target_total_bb:targetTotal,incremental_cost_bb:cost,sizing_origin:origin});
    };

    for(const structuralRaw of context.legal_actions||[]){
      const structural=String(structuralRaw).toUpperCase(),action=semanticAction(structural,context);
      if(structural==='FOLD'||structural==='CHECK')push(action,null,'no_chips');
      else if(structural==='LIMP'||structural==='CALL')push(action,current,structural==='CALL'?'price_to_call':'blind_or_limp_price');
      else if(structural==='JAM')push('SHOVE',max,'stack_cap');
      else if(structural==='RAISE'){
        if(!grid.targets_bb.length){
          throw new UncoveredPreflopSearchError('RAISE is legal but no explicit in-bounds sizing candidate was supplied',{
            context_id:context.context_id||null,
            semantic_action:action,
            min_raise_to_bb:context.min_raise_to_bb,
            max_raise_to_bb:max,
            sizing_grid_source:grid.source
          });
        }
        for(const target of grid.targets_bb)push(action,target,grid.source);
      }
    }
    if(!candidates.length)throw new UncoveredPreflopSearchError('no evaluable preflop candidate',{context_id:context.context_id||null});
    return {schema:'poker-preflop-search-candidates/v1',context_id:context.context_id||null,sizing_grid:grid,candidates};
  }

  function normalizeEvaluation(candidate,result){
    if(!result||typeof result!=='object')throw new Error(`evaluator returned no result for ${candidate.id}`);
    const ev=finite(result.ev_bb,`${candidate.id}.ev_bb`);
    const confidence=result.confidence==null?null:finite(result.confidence,`${candidate.id}.confidence`);
    if(confidence!=null&&(confidence<-EPS||confidence>1+EPS))throw new Error(`${candidate.id}.confidence must be 0..1`);
    return {
      ...candidate,
      ev_bb:ev,
      support:result.support||{observations:null,backoff_level:'UNKNOWN',source:null},
      confidence,
      uncertainty:result.uncertainty||{monte_carlo:{standard_error_bb:null,samples:null,method:null},model:{lower_bb:null,upper_bb:null,method:null,status:'UNKNOWN'}},
      notes:String(result.notes||'')
    };
  }

  function chooseBest(alternatives){
    if(!alternatives.length)throw new Error('cannot select from empty alternatives');
    return [...alternatives].sort((a,b)=>{
      const ev=b.ev_bb-a.ev_bb;if(Math.abs(ev)>EPS)return ev;
      const cost=a.incremental_cost_bb-b.incremental_cost_bb;if(Math.abs(cost)>EPS)return cost;
      return a.id.localeCompare(b.id);
    })[0];
  }

  async function searchPreflopDecision({
    context,
    population_id=null,
    hand_class=null,
    sizing_grid_bb=[],
    sizing_grid_source='explicit_observed_grid',
    evaluate_alternative,
    budget,
    seed,
    status='EXPERIMENTAL',
    notes=''
  }={}){
    if(typeof evaluate_alternative!=='function')throw new TypeError('evaluate_alternative callback is required');
    const totalBudget=Number(budget);
    if(!Number.isInteger(totalBudget)||totalBudget<0)throw new Error('budget must be a non-negative integer');
    const built=buildCandidates(context,{sizing_grid_bb,sizing_grid_source});
    const evaluated=[];
    const spendable=built.candidates.filter(row=>row.action!=='FOLD');
    const base=spendable.length?Math.floor(totalBudget/spendable.length):0;
    let remainder=spendable.length?totalBudget-base*spendable.length:0;
    let evalIndex=0;

    for(const candidate of built.candidates){
      if(candidate.action==='FOLD'){
        evaluated.push({
          ...candidate,ev_bb:0,
          support:{observations:null,backoff_level:'DETERMINISTIC',source:'decision_point_fold_reference'},
          confidence:1,
          uncertainty:{monte_carlo:{standard_error_bb:0,samples:0,method:'deterministic'},model:{lower_bb:0,upper_bb:0,method:'deterministic',status:'KNOWN'}},
          notes:'Fold is the zero-EV reference at the current decision point.'
        });
        continue;
      }
      const candidateBudget=base+(remainder>0?1:0);if(remainder>0)remainder--;
      const evaluation=await evaluate_alternative(Object.freeze({
        schema:SCHEMA,
        context,
        population_id,
        hand_class,
        candidate:Object.freeze({...candidate}),
        candidate_index:evalIndex++,
        candidate_budget:candidateBudget,
        total_budget:totalBudget,
        seed:seed==null?null:String(seed),
        remaining_to_act_positions:[...(context.remaining_to_act_positions||[])]
      }));
      evaluated.push(normalizeEvaluation(candidate,evaluation));
    }

    const selected=chooseBest(evaluated);
    return Decision.buildDecision({
      status,
      context_id:String(context.context_id||''),
      population_id,
      actor_contribution_bb:context.actor_contribution_bb,
      legal_actions:semanticLegalActions(context),
      selected_id:selected.id,
      alternatives:evaluated,
      search:{
        candidate_ids:evaluated.map(row=>row.id),
        sizing_grid_source:built.sizing_grid.source,
        budget:totalBudget,
        seed:seed==null?null:String(seed),
        notes:`${built.sizing_grid.targets_bb.length} explicit raise sizing(s); ${notes}`.trim()
      },
      notes
    });
  }

  return {SCHEMA,UncoveredPreflopSearchError,semanticRaiseAction,semanticAction,semanticLegalActions,normalizeSizingGrid,buildCandidates,chooseBest,searchPreflopDecision};
});

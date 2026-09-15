(function(root,factory){
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root)root.PokerPreflopDecision=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';

  const SCHEMA='poker-preflop-decision/v1';
  const EV_REFERENCE='decision_point_incremental_bb';
  const ACTIONS=['FOLD','CHECK','LIMP','OVERLIMP','CALL','OPEN','ISO','SQUEEZE','3BET','4BET','SHOVE','CALL_SHOVE'];
  const ZERO_COST_ACTIONS=new Set(['FOLD','CHECK']);
  const CHIP_ACTIONS=new Set(ACTIONS.filter(a=>!ZERO_COST_ACTIONS.has(a)));
  const EPS=1e-9;

  function finite(value,name){
    const n=Number(value);
    if(!Number.isFinite(n))throw new Error(`${name} must be finite`);
    return n;
  }

  function optionalFinite(value,name,{min=null,max=null}={}){
    if(value==null)return null;
    const n=finite(value,name);
    if(min!=null&&n<min-EPS)throw new Error(`${name} must be >= ${min}`);
    if(max!=null&&n>max+EPS)throw new Error(`${name} must be <= ${max}`);
    return n;
  }

  function normalizeUncertainty(input={}){
    const monteCarlo=input.monte_carlo||{};
    const model=input.model||{};
    return {
      monte_carlo:{
        standard_error_bb:optionalFinite(monteCarlo.standard_error_bb,'uncertainty.monte_carlo.standard_error_bb',{min:0}),
        samples:monteCarlo.samples==null?null:Math.trunc(finite(monteCarlo.samples,'uncertainty.monte_carlo.samples')),
        method:String(monteCarlo.method||'').trim()||null
      },
      model:{
        lower_bb:optionalFinite(model.lower_bb,'uncertainty.model.lower_bb'),
        upper_bb:optionalFinite(model.upper_bb,'uncertainty.model.upper_bb'),
        method:String(model.method||'').trim()||null,
        status:String(model.status||'UNKNOWN').toUpperCase()
      }
    };
  }

  function normalizeSupport(input={}){
    const observations=input.observations==null?null:Math.trunc(finite(input.observations,'support.observations'));
    if(observations!=null&&observations<0)throw new Error('support.observations must be >= 0');
    return {
      observations,
      backoff_level:String(input.backoff_level||'UNKNOWN').toUpperCase(),
      source:String(input.source||'').trim()||null
    };
  }

  function normalizeAlternative(input,{actorContributionBB,legalActions}={}){
    if(!input||typeof input!=='object')throw new Error('alternative must be an object');
    const id=String(input.id||'').trim();
    if(!id)throw new Error('alternative.id is required');
    const action=String(input.action||'').toUpperCase();
    if(!ACTIONS.includes(action))throw new Error(`unsupported preflop action ${action}`);
    if(legalActions&&legalActions.size&&!legalActions.has(action))throw new Error(`alternative ${id} uses illegal action ${action}`);

    const ev_bb=finite(input.ev_bb,`alternative ${id}.ev_bb`);
    const confidence=optionalFinite(input.confidence,`alternative ${id}.confidence`,{min:0,max:1});
    let target_total_bb=input.target_total_bb==null?null:finite(input.target_total_bb,`alternative ${id}.target_total_bb`);
    let incremental_cost_bb=finite(input.incremental_cost_bb,`alternative ${id}.incremental_cost_bb`);
    if(incremental_cost_bb<-EPS)throw new Error(`alternative ${id}.incremental_cost_bb must be >= 0`);

    if(ZERO_COST_ACTIONS.has(action)){
      if(Math.abs(incremental_cost_bb)>EPS)throw new Error(`${action} must have zero incremental cost`);
      if(target_total_bb!=null)throw new Error(`${action} must not advertise a target_total_bb`);
      incremental_cost_bb=0;
      target_total_bb=null;
    }else if(CHIP_ACTIONS.has(action)){
      if(target_total_bb==null||target_total_bb<actorContributionBB-EPS)throw new Error(`${action} requires target_total_bb >= actor contribution`);
      const expected=target_total_bb-actorContributionBB;
      if(Math.abs(expected-incremental_cost_bb)>1e-6)throw new Error(`alternative ${id} incremental cost ${incremental_cost_bb} does not match target_total_bb - actor_contribution_bb (${expected})`);
    }

    return {
      id,action,target_total_bb,incremental_cost_bb,ev_bb,
      support:normalizeSupport(input.support||{}),
      confidence,
      uncertainty:normalizeUncertainty(input.uncertainty||{}),
      sizing_origin:String(input.sizing_origin||'').trim()||null,
      notes:String(input.notes||'')
    };
  }

  function buildDecision(input={}){
    const context_id=String(input.context_id||'').trim();
    if(!context_id)throw new Error('context_id is required');
    const actor_contribution_bb=optionalFinite(input.actor_contribution_bb,'actor_contribution_bb',{min:0});
    if(actor_contribution_bb==null)throw new Error('actor_contribution_bb is required');
    const legal_actions=Array.from(new Set((input.legal_actions||[]).map(a=>String(a).toUpperCase())));
    for(const action of legal_actions)if(!ACTIONS.includes(action))throw new Error(`unsupported legal action ${action}`);
    const legalSet=new Set(legal_actions);
    if(!Array.isArray(input.alternatives)||!input.alternatives.length)throw new Error('at least one evaluated alternative is required');
    const alternatives=input.alternatives.map(row=>normalizeAlternative(row,{actorContributionBB:actor_contribution_bb,legalActions:legalSet}));
    const ids=new Set();
    for(const row of alternatives){if(ids.has(row.id))throw new Error(`duplicate alternative id ${row.id}`);ids.add(row.id);}

    const selected_id=String(input.selected_id||'').trim();
    const selected=alternatives.find(row=>row.id===selected_id);
    if(!selected)throw new Error(`selected_id ${selected_id||'<empty>'} was not evaluated`);
    const bestEV=Math.max(...alternatives.map(row=>row.ev_bb));
    if(selected.ev_bb<bestEV-EPS)throw new Error(`selected alternative ${selected.id} is not maximal EV (${selected.ev_bb} < ${bestEV})`);

    const search=input.search||{};
    const budget=search.budget==null?null:Math.trunc(finite(search.budget,'search.budget'));
    if(budget!=null&&budget<0)throw new Error('search.budget must be >= 0');
    const candidate_ids=Array.isArray(search.candidate_ids)?search.candidate_ids.map(String):alternatives.map(row=>row.id);
    for(const id of candidate_ids)if(!ids.has(id))throw new Error(`search references unevaluated alternative ${id}`);

    return {
      schema:SCHEMA,
      status:String(input.status||'EXPERIMENTAL').toUpperCase(),
      context_id,
      population_id:input.population_id==null?null:String(input.population_id),
      ev_reference:EV_REFERENCE,
      actor_contribution_bb,
      legal_actions,
      selected_id:selected.id,
      action:selected.action,
      target_total_bb:selected.target_total_bb,
      bet_to_bb:selected.target_total_bb,
      incremental_cost_bb:selected.incremental_cost_bb,
      ev_bb:selected.ev_bb,
      support:selected.support,
      confidence:selected.confidence,
      uncertainty:selected.uncertainty,
      alternatives,
      search:{
        candidate_ids,
        sizing_grid_source:String(search.sizing_grid_source||'').trim()||null,
        budget,
        seed:search.seed==null?null:String(search.seed),
        notes:String(search.notes||'')
      },
      notes:String(input.notes||'')
    };
  }

  function validateDecision(decision){
    if(!decision||decision.schema!==SCHEMA)throw new Error(`expected ${SCHEMA}`);
    const rebuilt=buildDecision({
      status:decision.status,
      context_id:decision.context_id,
      population_id:decision.population_id,
      actor_contribution_bb:decision.actor_contribution_bb,
      legal_actions:decision.legal_actions,
      selected_id:decision.selected_id,
      alternatives:decision.alternatives,
      search:decision.search,
      notes:decision.notes
    });
    const scalar=['action','target_total_bb','bet_to_bb','incremental_cost_bb','ev_bb','ev_reference'];
    for(const key of scalar){
      const a=decision[key],b=rebuilt[key];
      if(typeof a==='number'||typeof b==='number'){
        if(a==null||b==null||Math.abs(Number(a)-Number(b))>EPS)throw new Error(`decision ${key} does not match selected alternative`);
      }else if(a!==b)throw new Error(`decision ${key} does not match selected alternative`);
    }
    return true;
  }

  return {SCHEMA,EV_REFERENCE,ACTIONS,buildDecision,validateDecision,normalizeAlternative};
});

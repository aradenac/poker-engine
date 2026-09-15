(function(root,factory){
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root)root.PokerPreflopContract=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  const SCHEMA='poker-preflop-context/v1';
  const PROBABILITY_SCHEMA='poker-preflop-action-probabilities/v1';
  const STATE_TIMING='BEFORE_ACTION';
  const EPS=1e-9;
  const LEGACY_ORDER=['LJ','HJ','CO','BTN','SB','BB','SB_BTN'];
  const ACTION_ORDER6=['LJ','HJ','CO','BTN','SB','BB'];
  const ACTION_ORDERHU=['SB_BTN','BB'];
  const normPos=(position,tableSize)=>{
    let p=String(position||'').toUpperCase();
    if(p==='UTG')p='LJ';
    return Number(tableSize)===2&&p==='BTN'?'SB_BTN':p;
  };
  const legacyOrder=()=>LEGACY_ORDER;
  const actionOrder=tableSize=>Number(tableSize)===2?ACTION_ORDERHU:ACTION_ORDER6;
  const sortPositions=(positions,tableSize)=>{
    const order=legacyOrder(),rank=new Map(order.map((p,i)=>[p,i]));
    const xs=[...new Set((positions||[]).filter(Boolean).map(p=>normPos(p,tableSize)))];
    xs.sort((a,b)=>(rank.get(a)??999)-(rank.get(b)??999)||a.localeCompare(b));
    return xs;
  };
  const normalizeHistory=history=>{
    if(history==null)return [];
    if(typeof history==='string'){
      return history.split(/[>,]/).map(x=>x.trim()).filter(Boolean).map(token=>{
        const i=token.indexOf(':');
        if(i<1)throw new Error(`invalid preflop history token: ${token}`);
        return {position:token.slice(0,i).trim().toUpperCase(),action:token.slice(i+1).trim().toUpperCase()};
      });
    }
    if(!Array.isArray(history))throw new TypeError('history must be a string or array');
    return history.map(item=>{
      if(!item||typeof item!=='object')throw new TypeError('history items must be objects');
      const position=String(item.position||'').trim().toUpperCase(),action=String(item.action||'').trim().toUpperCase();
      if(!position||!action)throw new Error('invalid preflop history item');
      return {position,action};
    });
  };
  const historyToken=history=>normalizeHistory(history).map(x=>`${x.position}:${x.action}`).join('>');
  const deriveRemainingToAct=({live_positions,all_in_positions=[],history,actor_position,table_size})=>{
    const actor=normPos(actor_position,table_size),live=new Set((live_positions||[]).map(p=>normPos(p,table_size))),allin=new Set((all_in_positions||[]).map(p=>normPos(p,table_size)));
    const hist=normalizeHistory(history).map(x=>({position:normPos(x.position,table_size),action:x.action}));
    let lastRaise=-1;hist.forEach((x,i)=>{if(['RAISE','JAM'].includes(x.action))lastRaise=i;});
    const acted=new Set();
    if(lastRaise>=0){acted.add(hist[lastRaise].position);for(const x of hist.slice(lastRaise+1))acted.add(x.position);}
    else for(const x of hist)acted.add(x.position);
    return actionOrder(table_size).filter(p=>live.has(p)&&!allin.has(p)&&!acted.has(p)&&p!==actor);
  };
  const familyFromHistory=(history,actorPosition)=>{
    const hist=normalizeHistory(history),actor=String(actorPosition||'').toUpperCase();
    if(!hist.length)return 'UNOPENED';
    const raises=[];hist.forEach((x,i)=>{if(['RAISE','JAM'].includes(x.action))raises.push(i);});
    const limps=hist.filter(x=>x.action==='LIMP');
    if(!raises.length)return 'VS_LIMPERS';
    const first=raises[0],callers=hist.slice(first+1).filter(x=>x.action==='CALL');
    const actorRaised=hist.some(x=>x.position===actor&&['RAISE','JAM'].includes(x.action));
    const actorCalled=hist.some(x=>x.position===actor&&['CALL','LIMP'].includes(x.action));
    if(raises.length===1){
      if(limps.length&&first>0){
        const actorLimped=hist.some(x=>x.position===actor&&x.action==='LIMP');
        if(actorLimped)return callers.length?'LIMPER_VS_ISO_CALLERS':'LIMPER_VS_ISO';
        return callers.length?'VS_ISO_CALLERS':'VS_ISO';
      }
      return callers.length?'VS_RFI_CALLERS':'VS_RFI';
    }
    if(raises.length===2)return actorRaised?'OPENER_OR_ISO_VS_3BET':(actorCalled?'CALLER_VS_SQUEEZE_OR_3BET':'COLD_VS_3BET');
    if(raises.length===3)return actorRaised?'AGGRESSOR_VS_4BET':(actorCalled?'CALLER_VS_4BET':'COLD_VS_4BET');
    if(raises.length===4)return 'VS_5BET';
    return 'VS_6BET_PLUS';
  };
  const finiteNonnegative=(value,field)=>{
    const v=Number(value||0);if(!Number.isFinite(v)||v<-EPS)throw new Error(`${field} must be finite and non-negative`);return Math.max(0,v);
  };
  const roundBB=value=>Number(Number(value).toFixed(9));
  const legalActionsForState=({to_call_bb,actor_contribution_bb,actor_remaining_bb,min_raise_to_bb,max_raise_to_bb,raise_reopened=true,raise_level=0})=>{
    const toCall=Math.max(0,Number(to_call_bb)||0),remaining=Math.max(0,Number(actor_remaining_bb)||0),actorPaid=Math.max(0,Number(actor_contribution_bb)||0),maxTo=Math.max(actorPaid,Number(max_raise_to_bb)||0),rl=Number(raise_level)||0;
    const legal=[];
    if(toCall>EPS){legal.push('FOLD');if(remaining>EPS)legal.push(rl===0?'LIMP':'CALL');}
    else legal.push('CHECK');
    const canIncrease=remaining>toCall+EPS&&maxTo>actorPaid+toCall+EPS;
    if(raise_reopened&&canIncrease){if(min_raise_to_bb!=null&&maxTo+EPS>=Number(min_raise_to_bb))legal.push('RAISE');legal.push('JAM');}
    return legal;
  };
  const canonicalKey=context=>{
    const hist=historyToken(context.history||[]),live=(context.live_positions||[]).join(','),allin=(context.all_in_positions||[]).join(','),remaining=(context.remaining_to_act_positions||[]).join(',');
    return `${Number(context.table_size)||0}|${context.actor_position||''}|family=${context.family||''}|rl=${Number(context.raise_level)||0}|free=${context.free_check?1:0}|live=${live}|allin=${allin}|remaining=${remaining}|hist=${hist}`;
  };
  // FNV-1a is used only as a deterministic browser identifier. Scientific
  // equality is defined by canonical fields/key, not by this short id.
  const contextId=context=>{
    const keys=['schema','state_timing','table_size','actor_position','family','raise_level','live_positions','all_in_positions','remaining_to_act_positions','history','limper_positions','caller_positions','contribution_bb_by_position','actor_contribution_bb','current_price_bb','to_call_bb','free_check','pot_before_bb','actor_remaining_bb','effective_stack_bb','legal_actions','min_raise_to_bb','max_raise_to_bb','raise_reopened'];
    const structural={};for(const k of keys)if(Object.prototype.hasOwnProperty.call(context,k))structural[k]=context[k];
    const text=JSON.stringify(structural,Object.keys(structural).sort());let h=2166136261>>>0;for(let i=0;i<text.length;i++){h^=text.charCodeAt(i);h=Math.imul(h,16777619)>>>0;}return `PFCJS_${h.toString(16).padStart(8,'0')}`;
  };
  const buildContext=args=>{
    const n=Number(args.table_size);if(!Number.isInteger(n)||n<2)throw new Error('table_size must be at least 2');
    const actor=normPos(args.actor_position,n),hist=normalizeHistory(args.history).map(x=>({position:normPos(x.position,n),action:x.action}));
    const live=sortPositions(args.live_positions,n),allin=sortPositions(args.all_in_positions||[],n);if(!live.includes(actor))throw new Error('actor must be live');if(allin.includes(actor))throw new Error('all-in actor cannot act');
    const cin=args.contribution_bb_by_position||{},contrib={};for(const p of [...new Set([...live,...allin])])contrib[p]=roundBB(finiteNonnegative(cin[p]||0,`contribution[${p}]`));
    const actorPaid=contrib[actor]||0,price=finiteNonnegative(args.current_price_bb==null?Math.max(0,...Object.values(contrib)):args.current_price_bb,'current_price_bb'),toCall=Math.max(0,price-actorPaid);
    const sin=args.stack_bb_by_position||{},actorStack=finiteNonnegative(sin[actor]??actorPaid,'actor stack');if(actorStack+EPS<actorPaid)throw new Error('actor stack below contribution');
    const actorRemaining=Math.max(0,actorStack-actorPaid),oppStacks=live.filter(p=>p!==actor).map(p=>finiteNonnegative(sin[p]??contrib[p]??0,`stack[${p}]`)),effectiveStack=Math.min(actorStack,oppStacks.length?Math.max(...oppStacks):actorStack),maxRaiseTo=actorStack;
    const rl=args.raise_level==null?hist.filter(x=>['RAISE','JAM'].includes(x.action)).length:Number(args.raise_level);if(rl<0)throw new Error('negative raise level');
    let minRaiseTo=args.min_raise_to_bb==null?price+1:finiteNonnegative(args.min_raise_to_bb,'min_raise_to_bb');
    let pending;if(args.pending_positions==null)pending=deriveRemainingToAct({live_positions:live,all_in_positions:allin,history:hist,actor_position:actor,table_size:n});else pending=args.pending_positions.map(p=>normPos(p,n)).filter(p=>live.includes(p)&&!allin.includes(p)&&p!==actor);
    const firstRaise=hist.findIndex(x=>['RAISE','JAM'].includes(x.action)),prefix=firstRaise<0?hist:hist.slice(0,firstRaise),limpers=prefix.filter(x=>x.action==='LIMP').map(x=>x.position),callers=firstRaise<0?[]:hist.slice(firstRaise+1).filter(x=>x.action==='CALL').map(x=>x.position);
    const legal=legalActionsForState({to_call_bb:toCall,actor_contribution_bb:actorPaid,actor_remaining_bb:actorRemaining,min_raise_to_bb:minRaiseTo,max_raise_to_bb:maxRaiseTo,raise_reopened:args.raise_reopened!==false,raise_level:rl});
    const result={schema:SCHEMA,state_timing:STATE_TIMING,table_size:n,actor_position:actor,family:familyFromHistory(hist,actor),raise_level:rl,live_positions:live,all_in_positions:allin,remaining_to_act_positions:pending,history:hist,limper_positions:sortPositions(limpers,n),caller_positions:sortPositions(callers,n),contribution_bb_by_position:Object.fromEntries(sortPositions(Object.keys(contrib),n).map(p=>[p,contrib[p]])),actor_contribution_bb:roundBB(actorPaid),current_price_bb:roundBB(price),to_call_bb:roundBB(toCall),free_check:toCall<=EPS,pot_before_bb:roundBB(finiteNonnegative(args.pot_before_bb||0,'pot_before_bb')),actor_remaining_bb:roundBB(actorRemaining),effective_stack_bb:roundBB(effectiveStack),legal_actions:legal,min_raise_to_bb:minRaiseTo<=maxRaiseTo+EPS?roundBB(minRaiseTo):null,max_raise_to_bb:roundBB(maxRaiseTo),raise_reopened:args.raise_reopened!==false,amount_semantics:{call_or_bet_cost:'incremental_cost_bb',raise_cost:'incremental_cost_bb',raise_target:'target_total_bb',check_and_fold_cost_bb:0}};
    result.canonical_key=canonicalKey(result);result.context_id=contextId(result);return result;
  };
  const v5RuntimeSignature=context=>JSON.stringify([String(context.actor_position||''),Number(context.table_size)||0,Number(context.raise_level)||0,String(context.family||''),context.live_positions||[],context.all_in_positions||[],normalizeHistory(context.history||[]).map(x=>[x.position,x.action])]);
  const normalizeActionProbabilities=({context,raw_probabilities,hand_class=null,sizing=null,source,backoff_level,confidence,support})=>{
    const legal=(context.legal_actions||[]).map(x=>String(x).toUpperCase());if(!legal.length)throw new Error('context has no legal actions');const weights={};let total=0;for(const action of legal){const v=Number((raw_probabilities||{})[action]||0);if(!Number.isFinite(v)||v<0)throw new Error(`invalid probability weight for ${action}`);weights[action]=v;total+=v;}if(total<=EPS)throw new Error('zero legal probability mass');const probabilities={};for(const action of legal)probabilities[action]=weights[action]/total;return {schema:PROBABILITY_SCHEMA,behavior_mode:'strict_legal_normalized',context_id:String(context.context_id||contextId(context)),hand_class,legal_actions:legal,probabilities,sizing:sizing==null?null:{...sizing},source:String(source),backoff_level:String(backoff_level),confidence:String(confidence),support:Number(support)||0,incumbent_compatibility:{matcher:'v5/v83',runtime_signature_ignores_free_check:true}};
  };
  const incumbentV5Passthrough=({context,raw_probabilities,hand_class=null,sizing=null,source,backoff_level,confidence,support})=>{
    const probabilities={},raw=raw_probabilities||{};let total=0;for(const [action,valueRaw] of Object.entries(raw)){const actionName=String(action).toUpperCase(),value=Number(valueRaw||0);if(!Number.isFinite(value)||value<0)throw new Error(`invalid incumbent probability for ${actionName}`);probabilities[actionName]=value;total+=value;}if(!Object.keys(probabilities).length)throw new Error('incumbent probability response is empty');if(total<=EPS)throw new Error('incumbent probability mass is zero');const legal=(context.legal_actions||[]).map(x=>String(x).toUpperCase()),legalSet=new Set(legal),positiveIllegal=Object.entries(probabilities).filter(([,p])=>p>EPS).map(([a])=>a).filter(a=>legal.length&&!legalSet.has(a)),missing=legal.filter(a=>!Object.prototype.hasOwnProperty.call(probabilities,a));return {schema:PROBABILITY_SCHEMA,behavior_mode:'incumbent_v5_passthrough',context_id:String(context.context_id||contextId(context)),hand_class,legal_actions:legal,model_actions:Object.keys(probabilities),probabilities,probability_sum:total,action_set_compatible:positiveIllegal.length===0,positive_illegal_model_actions:positiveIllegal,missing_legal_model_actions:missing,sizing:sizing==null?null:{...sizing},source:String(source),backoff_level:String(backoff_level),confidence:String(confidence),support:Number(support)||0,incumbent_compatibility:{matcher:'v5/v83',probabilities_preserved_without_renormalization:true,runtime_signature_ignores_free_check:true}};
  };
  return {SCHEMA,PROBABILITY_SCHEMA,STATE_TIMING,normalizePosition:normPos,sortPositions,normalizeHistory,historyToken,deriveRemainingToAct,familyFromHistory,legalActionsForState,canonicalKey,contextId,buildContext,v5RuntimeSignature,normalizeActionProbabilities,incumbentV5Passthrough};
});

(function(root,factory){
  const api=factory();
  if(typeof module==="object"&&module.exports)module.exports=api;
  root.PokerModelBRobustnessUI=api;
})(typeof globalThis!=="undefined"?globalThis:this,function(){
  "use strict";

  const SUMMARY_SCHEMA="hero-model-b-robustness-summary/v1";
  const DETAIL_SCHEMA="hero-model-b-robustness/v1";
  const ENVELOPE_SCHEMA="hero-model-b-robustness-ui-envelope/v1";
  const STATUSES=new Set(["robust","sensitive","insufficiently_supported"]);
  const IDENTITY_FIELDS=["population_id","pack_id","strategy_id","strategy_version","ev_reference"];

  function finiteOrNull(value){
    const n=Number(value);
    return Number.isFinite(n)?n:null;
  }
  function normalizeIdentity(raw){
    const source=raw&&typeof raw==="object"?raw:{};
    return {
      population_id:String(source.population_id??""),
      pack_id:source.pack_id==null?null:String(source.pack_id),
      strategy_id:String(source.strategy_id??""),
      strategy_version:String(source.strategy_version??""),
      ev_reference:String(source.ev_reference??"")
    };
  }
  function sameIdentity(a,b){
    const left=normalizeIdentity(a),right=normalizeIdentity(b);
    return IDENTITY_FIELDS.every(key=>left[key]===right[key]);
  }
  function summaryErrors(summary){
    const errors=[];
    if(!summary||typeof summary!=="object")return ["SUMMARY_MISSING"];
    if(summary.schema!==SUMMARY_SCHEMA)errors.push("SUMMARY_SCHEMA");
    if(!String(summary.decision_id||""))errors.push("DECISION_ID_MISSING");
    if(!STATUSES.has(String(summary.status||"")))errors.push("STATUS_INVALID");
    const model=summary.model_environment;
    if(!model||typeof model!=="object")errors.push("MODEL_ENVIRONMENT_MISSING");
    else if(model.weighted!==false)errors.push("ENVIRONMENTS_WEIGHTED");
    const support=summary.support;
    if(!support||typeof support!=="object")errors.push("SUPPORT_MISSING");
    return errors;
  }
  function failClosed(reason,expectedDecisionId,identity,summary=null){
    return {
      schema:"hero-model-b-robustness-ui-view/v1",
      evidence_status:"unavailable",
      status:"insufficiently_supported",
      fail_closed:true,
      reason,
      decision_id:String(expectedDecisionId||summary?.decision_id||""),
      identity:normalizeIdentity(identity),
      nominal:null,
      model_environment:null,
      stability:{action:null,sizing:null,ranking:null},
      support:{all_environments_supported:false,unsupported_environment_count:null},
      shove_fragility:null,
      overbet_fragility:null,
      aggressive_fragility:null,
      detail_available:false
    };
  }
  function consumeEnvelope(envelope,expected={}){
    const expectedDecisionId=String(expected.decision_id||"");
    const expectedIdentity=normalizeIdentity(expected.identity);
    if(!envelope||typeof envelope!=="object")return failClosed("NO_ROBUSTNESS_EVIDENCE",expectedDecisionId,expectedIdentity);
    if(envelope.schema!==ENVELOPE_SCHEMA)return failClosed("ENVELOPE_SCHEMA",expectedDecisionId,expectedIdentity);
    if(!sameIdentity(envelope.identity,expectedIdentity))return failClosed("IDENTITY_MISMATCH",expectedDecisionId,expectedIdentity);
    const summary=envelope.summary;
    const errors=summaryErrors(summary);
    if(errors.length)return failClosed(errors.join(","),expectedDecisionId,expectedIdentity,summary);
    if(expectedDecisionId&&String(summary.decision_id)!==expectedDecisionId)return failClosed("DECISION_ID_MISMATCH",expectedDecisionId,expectedIdentity,summary);

    const model=summary.model_environment||{},support=summary.support||{};
    const backendStatus=String(summary.status);
    const supportComplete=support.all_environments_supported===true&&model.comparable===true;
    const status=supportComplete?backendStatus:"insufficiently_supported";
    const failClosedStatus=status==="insufficiently_supported";
    const nominal=summary.nominal&&typeof summary.nominal==="object"?{
      action:String(summary.nominal.action||""),
      sizing:summary.nominal.sizing??null,
      ev_bb:finiteOrNull(summary.nominal.ev_bb),
      advantage_bb:finiteOrNull(summary.nominal.advantage_bb),
      mc_ci95:Array.isArray(summary.nominal.mc_ci95)&&summary.nominal.mc_ci95.length===2
        ?[finiteOrNull(summary.nominal.mc_ci95[0]),finiteOrNull(summary.nominal.mc_ci95[1])]
        :null,
      mc_ci95_width_bb:finiteOrNull(summary.nominal.mc_ci95_width_bb)
    }:null;

    return {
      schema:"hero-model-b-robustness-ui-view/v1",
      evidence_status:"available",
      backend_status:backendStatus,
      status,
      fail_closed:failClosedStatus,
      reason:failClosedStatus&&!supportComplete?"SUPPORT_OR_COMPARABILITY_INCOMPLETE":null,
      decision_id:String(summary.decision_id),
      identity:expectedIdentity,
      nominal,
      model_environment:{
        comparable:model.comparable===true,
        ev_span_bb:Array.isArray(model.ev_span_bb)&&model.ev_span_bb.length===2
          ?[finiteOrNull(model.ev_span_bb[0]),finiteOrNull(model.ev_span_bb[1])]
          :null,
        max_regret_bb:finiteOrNull(model.max_regret_bb),
        worst_environment_regret:model.worst_environment_regret||null,
        environment_count:Number.isFinite(Number(model.environment_count))?Number(model.environment_count):null,
        missing_environment_ids:Array.isArray(model.missing_environment_ids)?model.missing_environment_ids.map(String):[],
        noncomparable_environment_ids:Array.isArray(model.noncomparable_environment_ids)?model.noncomparable_environment_ids.map(String):[],
        weighted:false
      },
      stability:{
        action:summary.stability?.action===true?true:summary.stability?.action===false?false:null,
        sizing:summary.stability?.sizing===true?true:summary.stability?.sizing===false?false:null,
        ranking:summary.stability?.ranking===true?true:summary.stability?.ranking===false?false:null
      },
      support:{
        all_environments_supported:support.all_environments_supported===true,
        unsupported_environment_count:Number.isFinite(Number(support.unsupported_environment_count))?Number(support.unsupported_environment_count):null
      },
      shove_fragility:summary.shove_fragility||null,
      overbet_fragility:summary.overbet_fragility||null,
      aggressive_fragility:summary.aggressive_fragility||null,
      detail_available:summary.detail_available===true,
      summary
    };
  }
  function statusLabel(view){
    if(!view||view.evidence_status!=="available")return "Robustesse Model B non établie";
    if(view.status==="robust")return "Robuste aux variantes Model B";
    if(view.status==="sensitive")return "Sensible aux variantes Model B";
    return "Support Model B insuffisant";
  }
  function affectedEnvironmentIds(view){
    const out=[];
    const add=value=>{for(const id of value||[])if(id!=null&&!out.includes(String(id)))out.push(String(id));};
    add(view?.shove_fragility?.affected_environments);
    add(view?.overbet_fragility?.affected_environments);
    add(view?.model_environment?.missing_environment_ids);
    add(view?.model_environment?.noncomparable_environment_ids);
    const worst=view?.model_environment?.worst_environment_regret?.environment_id;
    if(worst!=null)add([worst]);
    return out;
  }

  return {
    SUMMARY_SCHEMA,
    DETAIL_SCHEMA,
    ENVELOPE_SCHEMA,
    VIEW_SCHEMA:"hero-model-b-robustness-ui-view/v1",
    IDENTITY_FIELDS:Object.freeze([...IDENTITY_FIELDS]),
    normalizeIdentity,
    sameIdentity,
    summaryErrors,
    consumeEnvelope,
    statusLabel,
    affectedEnvironmentIds
  };
});

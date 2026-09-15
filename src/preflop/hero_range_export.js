(function(root,factory){
  if(typeof module==='object'&&module.exports){
    module.exports=factory(require('../../site/hero-ranges.js'),require('./decision.js'));
  }else if(root){
    root.PokerHeroCalculatedRanges=factory(root.PokerHeroRanges,root.PokerPreflopDecision);
  }
})(typeof globalThis!=='undefined'?globalThis:this,function(HeroRanges,PreflopDecision){
  'use strict';

  const SCHEMA='poker-hero-calculated-range-candidate/v1';
  const EPS=1e-9;

  function clone(value){return value==null?value:JSON.parse(JSON.stringify(value));}
  function requiredString(value,name){
    const text=String(value??'').trim();
    if(!text)throw new Error(`${name} is required`);
    return text;
  }
  function sameNumber(a,b,tolerance=1e-6){return Math.abs(Number(a)-Number(b))<=tolerance;}
  function stableStringify(value){
    if(value===null||typeof value!=='object')return JSON.stringify(value);
    if(Array.isArray(value))return '['+value.map(stableStringify).join(',')+']';
    return '{'+Object.keys(value).sort().map(key=>JSON.stringify(key)+':'+stableStringify(value[key])).join(',')+'}';
  }

  function dependencies(){
    if(!HeroRanges)throw new Error('PokerHeroRanges dependency is required');
    if(!PreflopDecision)throw new Error('PokerPreflopDecision dependency is required');
    return {HeroRanges,PreflopDecision};
  }

  function normalizeProvenance(input){
    if(!input||typeof input!=='object'||Array.isArray(input))throw new Error('provenance object is required');
    const provenance=clone(input);
    provenance.code=requiredString(provenance.code,'provenance.code');
    provenance.selection=requiredString(provenance.selection,'provenance.selection');
    if(!provenance.models||typeof provenance.models!=='object'||Array.isArray(provenance.models)||!Object.keys(provenance.models).length){
      throw new Error('provenance.models must identify at least one model');
    }
    for(const [key,value] of Object.entries(provenance.models))requiredString(value,`provenance.models.${key}`);
    if(!provenance.budget||typeof provenance.budget!=='object'||Array.isArray(provenance.budget)||!Object.keys(provenance.budget).length){
      throw new Error('provenance.budget must describe the search/evaluation budget');
    }
    return provenance;
  }

  function selectedSizingProbability(strategy,decision){
    if(decision.target_total_bb==null)return null;
    const rows=strategy.sizings?.[decision.action]||[];
    let probability=0;
    for(const row of rows){
      if(sameNumber(row.target_total_bb,decision.target_total_bb))probability+=Number(row.probability)||0;
    }
    return probability;
  }

  function strategyForRow(row,decision){
    const H=dependencies().HeroRanges;
    if(row.policy!=null){
      const strategy=H.normalizeHandStrategy(row.policy);
      const selectedProbability=Number(strategy.actions?.[decision.action]||0);
      if(selectedProbability<=EPS){
        throw new Error(`${row.hand_class}: explicit policy excludes selected decision action ${decision.action}`);
      }
      if(decision.target_total_bb!=null&&selectedSizingProbability(strategy,decision)<=EPS){
        throw new Error(`${row.hand_class}: explicit policy does not contain selected sizing ${decision.target_total_bb} BB for ${decision.action}`);
      }
      return {strategy,origin:'EXPLICIT_POLICY'};
    }

    const actions={[decision.action]:1};
    const sizings={};
    if(decision.target_total_bb!=null){
      sizings[decision.action]=[{target_total_bb:decision.target_total_bb,probability:1}];
    }
    return {
      strategy:H.normalizeHandStrategy({
        actions,
        sizings,
        notes:`Deterministic projection of selected ${PreflopDecision.SCHEMA} alternative ${decision.selected_id}`
      }),
      origin:'SELECTED_DECISION_ONE_HOT'
    };
  }

  function normalizeRows(rows,{context,requireComplete}){
    const {HeroRanges:H,PreflopDecision:D}=dependencies();
    if(!Array.isArray(rows)||!rows.length)throw new Error('rows must contain at least one hand decision');
    const byHand=new Map();
    for(const input of rows){
      if(!input||typeof input!=='object')throw new Error('row must be an object');
      const hand=requiredString(input.hand_class,'row.hand_class');
      if(!H.HAND_CLASSES.includes(hand))throw new Error(`unknown hand class ${hand}`);
      if(byHand.has(hand))throw new Error(`duplicate hand class ${hand}`);
      const decision=clone(input.decision);
      D.validateDecision(decision);
      if(decision.population_id!=null&&String(decision.population_id)!==String(context.population_id)){
        throw new Error(`${hand}: decision population ${decision.population_id} does not match context population ${context.population_id}`);
      }
      const {strategy,origin}=strategyForRow(input,decision);
      byHand.set(hand,{hand_class:hand,decision,strategy,policy_origin:origin});
    }
    if(requireComplete){
      const missing=H.HAND_CLASSES.filter(hand=>!byHand.has(hand));
      if(missing.length)throw new Error(`complete candidate requires all 169 hand classes; missing ${missing.length}: ${missing.slice(0,8).join(', ')}`);
    }
    return H.HAND_CLASSES.filter(hand=>byHand.has(hand)).map(hand=>byHand.get(hand));
  }

  function buildCandidate(input={}){
    const {HeroRanges:H}=dependencies();
    const context=H.normalizeContext(input.context||{});
    const version=requiredString(input.version,'version');
    const provenance=normalizeProvenance(input.provenance);
    const status=String(input.status||'EXPERIMENTAL').toUpperCase();
    if(status==='PROMOTED')throw new Error('candidate exporter cannot self-promote a Hero strategy');
    const requireComplete=input.require_complete!==false;
    const rows=normalizeRows(input.rows,{context,requireComplete});

    const repository=input.base_repository
      ? H.importDocument(clone(input.base_repository))
      : H.emptyRepository({populationId:context.population_id});
    if(repository.defaults?.population_id&&String(repository.defaults.population_id)!==String(context.population_id)){
      throw new Error(`base repository population ${repository.defaults.population_id} does not match ${context.population_id}`);
    }
    if(!repository.defaults.population_id)repository.defaults.population_id=context.population_id;

    const node=H.ensureContext(repository,context);
    node.layers.calculated.hands={};
    H.setLayerMetadata(repository,context,'calculated',{
      version,
      provenance:{
        ...clone(provenance),
        schema:SCHEMA,
        status,
        source_decision_schema:PreflopDecision.SCHEMA,
        policy_semantics:'explicit policy when supplied; otherwise selected decision projected one-hot; no synthetic mixes'
      }
    });

    const decisions={};
    const policy_origins={};
    for(const row of rows){
      H.setHandStrategy(repository,context,row.hand_class,row.strategy,{layer:'calculated'});
      decisions[row.hand_class]=row.decision;
      policy_origins[row.hand_class]=row.policy_origin;
    }
    H.validateRepository(repository);

    const candidate={
      schema:SCHEMA,
      status,
      population_id:context.population_id,
      context,
      version,
      layer:'calculated',
      promotion_authorized:false,
      coverage:{
        defined_hand_classes:rows.length,
        required_hand_classes:H.HAND_CLASSES.length,
        complete:rows.length===H.HAND_CLASSES.length
      },
      provenance,
      policy_origins,
      decisions,
      repository:H.exportDocument(repository)
    };
    verifyCandidate(candidate,{require_complete:requireComplete});
    return candidate;
  }

  function verifyCandidate(candidate,{require_complete=true}={}){
    const {HeroRanges:H,PreflopDecision:D}=dependencies();
    if(!candidate||candidate.schema!==SCHEMA)throw new Error(`expected ${SCHEMA}`);
    if(candidate.promotion_authorized!==false)throw new Error('candidate must not authorize its own promotion');
    const provenance=normalizeProvenance(candidate.provenance);
    const context=H.normalizeContext(candidate.context||{});
    if(String(candidate.population_id)!==String(context.population_id))throw new Error('candidate population/context mismatch');
    H.validateRepository(candidate.repository);
    if(candidate.repository.defaults?.population_id&&String(candidate.repository.defaults.population_id)!==String(context.population_id)){
      throw new Error('repository population mismatch');
    }
    const node=candidate.repository.contexts?.[H.contextKey(context)];
    if(!node)throw new Error('calculated context missing from repository');
    if(String(node.layers?.calculated?.version??'')!==String(candidate.version??''))throw new Error('calculated layer version mismatch');
    const layerProvenance=node.layers?.calculated?.provenance||{};
    if(layerProvenance.schema!==SCHEMA)throw new Error('calculated layer provenance schema mismatch');
    if(String(layerProvenance.status)!==String(candidate.status))throw new Error('calculated layer provenance status mismatch');
    if(layerProvenance.source_decision_schema!==D.SCHEMA)throw new Error('calculated layer source decision schema mismatch');
    for(const key of ['code','selection']){
      if(String(layerProvenance[key])!==String(provenance[key]))throw new Error(`calculated layer provenance ${key} mismatch`);
    }
    for(const key of ['models','budget']){
      if(stableStringify(layerProvenance[key])!==stableStringify(provenance[key]))throw new Error(`calculated layer provenance ${key} mismatch`);
    }

    const decisionHands=Object.keys(candidate.decisions||{});
    const layerHands=Object.keys(node.layers?.calculated?.hands||{});
    const expectedHands=H.HAND_CLASSES.filter(hand=>decisionHands.includes(hand));
    if(layerHands.length!==expectedHands.length||expectedHands.some(hand=>!layerHands.includes(hand))){
      throw new Error('decision evidence and calculated layer hand coverage differ');
    }
    if(require_complete&&expectedHands.length!==H.HAND_CLASSES.length)throw new Error('candidate is not complete over 169 hand classes');
    if(Number(candidate.coverage?.defined_hand_classes)!==expectedHands.length)throw new Error('coverage count mismatch');
    if(Boolean(candidate.coverage?.complete)!==(expectedHands.length===H.HAND_CLASSES.length))throw new Error('coverage completeness mismatch');

    for(const hand of expectedHands){
      const decision=candidate.decisions[hand];
      D.validateDecision(decision);
      if(decision.population_id!=null&&String(decision.population_id)!==String(context.population_id))throw new Error(`${hand}: decision population mismatch`);
      const strategy=H.getHandStrategy(candidate.repository,context,hand,{layer:'calculated'});
      if(!strategy)throw new Error(`${hand}: calculated strategy missing`);
      const actionProbability=Number(strategy.actions?.[decision.action]||0);
      if(actionProbability<=EPS)throw new Error(`${hand}: selected action ${decision.action} absent from calculated strategy`);
      if(decision.target_total_bb!=null&&selectedSizingProbability(strategy,decision)<=EPS){
        throw new Error(`${hand}: selected sizing ${decision.target_total_bb} BB absent from calculated strategy`);
      }
      const origin=String(candidate.policy_origins?.[hand]||'');
      if(origin==='SELECTED_DECISION_ONE_HOT'){
        if(!sameNumber(actionProbability,1))throw new Error(`${hand}: one-hot projection action probability drifted`);
        if(Object.keys(strategy.actions).length!==1)throw new Error(`${hand}: one-hot projection gained extra actions`);
        if(decision.target_total_bb!=null&&!sameNumber(selectedSizingProbability(strategy,decision),1))throw new Error(`${hand}: one-hot projection sizing probability drifted`);
      }else if(origin!=='EXPLICIT_POLICY'){
        throw new Error(`${hand}: unknown policy origin ${origin}`);
      }
    }
    return true;
  }

  function repositoryDocument(candidate,options={}){
    verifyCandidate(candidate,options);
    return clone(candidate.repository);
  }

  return {SCHEMA,buildCandidate,verifyCandidate,repositoryDocument,selectedSizingProbability};
});

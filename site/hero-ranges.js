(function(root,factory){
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root)root.PokerHeroRanges=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';

  const SCHEMA='poker-hero-range-repository/v1';
  const LAYERS=['personal','calculated'];
  const ACTIONS=['FOLD','CHECK','LIMP','OVERLIMP','CALL','OPEN','ISO','3BET','4BET','SHOVE','CALL_SHOVE'];
  const POSITIONS=['LJ','HJ','CO','BTN','SB','BB'];
  const SPOTS=['UNOPENED','VS_LIMPERS','VS_RFI','VS_RFI_CALLERS','VS_3BET','VS_4BET','VS_JAM'];
  const RANKS=['A','K','Q','J','T','9','8','7','6','5','4','3','2'];
  const EPS=1e-9;
  const PREFLOP_CONTEXT_ID=/^PFC_[0-9a-f]{16}$/i;

  function deepClone(value){return value==null?value:JSON.parse(JSON.stringify(value));}
  function handClasses(){
    const out=[];
    for(let r=0;r<13;r++)for(let c=0;c<13;c++){
      if(r===c)out.push(RANKS[r]+RANKS[c]);
      else if(r<c)out.push(RANKS[r]+RANKS[c]+'s');
      else out.push(RANKS[c]+RANKS[r]+'o');
    }
    return out;
  }
  const HAND_CLASSES=handClasses();
  const HAND_SET=new Set(HAND_CLASSES);

  function comboMultiplicity(hand){
    if(!HAND_SET.has(hand))throw new Error(`unknown hand class ${hand}`);
    if(hand.length===2)return 6;
    return hand.endsWith('s')?4:12;
  }

  function normalizeContext(input={}){
    const population_id=String(input.population_id||'').trim();
    const position=String(input.position||'').toUpperCase();
    const spot=String(input.spot||'').toUpperCase();
    const effective_stack_bb=Number(input.effective_stack_bb);
    const table_size=Number(input.table_size??6);
    const preflop_context_id=input.preflop_context_id==null?'':String(input.preflop_context_id).trim();
    if(!population_id)throw new Error('population_id is required');
    if(!POSITIONS.includes(position))throw new Error(`invalid position ${position}`);
    if(!SPOTS.includes(spot))throw new Error(`invalid spot ${spot}`);
    if(!Number.isFinite(effective_stack_bb)||effective_stack_bb<=0)throw new Error('effective_stack_bb must be positive');
    if(!Number.isInteger(table_size)||table_size<2||table_size>10)throw new Error('table_size must be 2..10');
    if(preflop_context_id&&!PREFLOP_CONTEXT_ID.test(preflop_context_id))throw new Error(`invalid preflop_context_id ${preflop_context_id}`);
    const out={population_id,table_size,position,effective_stack_bb:Number(effective_stack_bb.toFixed(3)),spot};
    if(preflop_context_id)out.preflop_context_id=preflop_context_id;
    return out;
  }

  function contextKey(input){
    const c=normalizeContext(input);
    const legacy=`${c.population_id}|${c.table_size}|${c.position}|${c.effective_stack_bb}|${c.spot}`;
    return c.preflop_context_id?`${legacy}|${c.preflop_context_id}`:legacy;
  }

  function emptyLayer(kind){return {kind,version:null,provenance:null,hands:{}};}

  function emptyRepository({populationId='',sourceDocument=null,sourceMeta=null}={}){
    return {
      schema:SCHEMA,
      version:1,
      source:{
        format:sourceDocument?'range-folder':null,
        preserved_verbatim:!!sourceDocument,
        meta:sourceMeta?deepClone(sourceMeta):null,
        range_folder:sourceDocument?deepClone(sourceDocument):null
      },
      defaults:{population_id:String(populationId||''),table_size:6,effective_stack_bb:100},
      contexts:{}
    };
  }

  function importDocument(document,{populationId='',baseRepository=null}={}){
    if(!document||typeof document!=='object'||Array.isArray(document))throw new Error('range document must be an object');
    if(document.schema===SCHEMA){const repo=deepClone(document);validateRepository(repo);return repo;}
    if(baseRepository){
      validateRepository(baseRepository);
      const repo=deepClone(baseRepository);
      repo.source={format:'range-folder',preserved_verbatim:true,meta:null,range_folder:deepClone(document)};
      if(!repo.defaults?.population_id&&populationId)repo.defaults.population_id=String(populationId);
      validateRepository(repo);
      return repo;
    }
    return emptyRepository({populationId,sourceDocument:document});
  }

  function normalizeSizingList(value){
    if(value==null)return null;
    if(!Array.isArray(value))throw new Error('sizing list must be an array');
    const rows=value.map(row=>({target_total_bb:Number(row.target_total_bb),probability:Number(row.probability)})).filter(row=>row.probability>EPS);
    let total=0;
    for(const row of rows){
      if(!Number.isFinite(row.target_total_bb)||row.target_total_bb<=0)throw new Error('target_total_bb must be positive');
      if(!Number.isFinite(row.probability)||row.probability<0||row.probability>1+EPS)throw new Error('invalid sizing probability');
      total+=row.probability;
    }
    if(rows.length&&Math.abs(total-1)>1e-6)throw new Error(`sizing probabilities must sum to 1, got ${total}`);
    return rows.length?rows:null;
  }

  function normalizeHandStrategy(input){
    if(input==null)return null;
    const actions={};let total=0;
    for(const [name0,value0] of Object.entries(input.actions||{})){
      const name=String(name0).toUpperCase();
      if(!ACTIONS.includes(name))throw new Error(`unsupported Hero action ${name}`);
      const value=Number(value0);
      if(!Number.isFinite(value)||value<0||value>1+EPS)throw new Error(`invalid action probability ${name}`);
      if(value>EPS){actions[name]=value;total+=value;}
    }
    if(!Object.keys(actions).length)throw new Error('defined hand strategy has no positive action');
    if(Math.abs(total-1)>1e-6)throw new Error(`defined hand strategy probabilities must sum to 1, got ${total}`);
    const sizings={};
    for(const [name0,list] of Object.entries(input.sizings||{})){
      const name=String(name0).toUpperCase();
      if(!ACTIONS.includes(name))throw new Error(`unsupported sizing action ${name}`);
      if(!(name in actions))throw new Error(`sizing supplied for zero-probability action ${name}`);
      const normalized=normalizeSizingList(list);if(normalized)sizings[name]=normalized;
    }
    return {actions,sizings,notes:String(input.notes||'')};
  }

  function ensureContext(repo,context){
    if(!repo||repo.schema!==SCHEMA)throw new Error('invalid repository schema');
    const c=normalizeContext(context),key=contextKey(c);
    if(!repo.contexts[key])repo.contexts[key]={context:c,layers:{personal:emptyLayer('personal'),calculated:emptyLayer('calculated')}};
    for(const kind of LAYERS)if(!repo.contexts[key].layers?.[kind])repo.contexts[key].layers[kind]=emptyLayer(kind);
    return repo.contexts[key];
  }

  function setLayerMetadata(repo,context,layer,{version=null,provenance=null}={}){
    if(!LAYERS.includes(layer))throw new Error(`invalid layer ${layer}`);
    const node=ensureContext(repo,context),target=node.layers[layer];
    target.version=version==null?null:String(version);
    target.provenance=provenance==null?null:deepClone(provenance);
    return target;
  }

  function setHandStrategy(repo,context,hand,strategy,{layer='personal'}={}){
    if(!LAYERS.includes(layer))throw new Error(`invalid layer ${layer}`);
    if(!HAND_SET.has(hand))throw new Error(`unknown hand class ${hand}`);
    const node=ensureContext(repo,context),target=node.layers[layer];
    if(strategy==null)delete target.hands[hand];
    else target.hands[hand]=normalizeHandStrategy(strategy);
    return node;
  }

  function getHandStrategy(repo,context,hand,{layer='resolved'}={}){
    if(!repo||repo.schema!==SCHEMA||!HAND_SET.has(hand))return null;
    const node=repo.contexts?.[contextKey(context)];if(!node)return null;
    if(layer==='resolved')return deepClone(node.layers?.personal?.hands?.[hand]||node.layers?.calculated?.hands?.[hand]||null);
    if(!LAYERS.includes(layer))throw new Error(`invalid layer ${layer}`);
    return deepClone(node.layers?.[layer]?.hands?.[hand]||null);
  }

  function resolvedLayer(repo,context,hand){
    const node=repo?.contexts?.[contextKey(context)];
    if(node?.layers?.personal?.hands?.[hand])return 'personal';
    if(node?.layers?.calculated?.hands?.[hand])return 'calculated';
    return null;
  }

  function validateLayer(layer,kind,key){
    if(!layer||typeof layer!=='object')throw new Error(`missing ${kind} layer ${key}`);
    if(layer.kind!==kind)throw new Error(`layer kind mismatch ${key}/${kind}`);
    if(!layer.hands||typeof layer.hands!=='object'||Array.isArray(layer.hands))throw new Error(`invalid hands map ${key}/${kind}`);
    for(const [hand,strategy] of Object.entries(layer.hands)){
      if(!HAND_SET.has(hand))throw new Error(`unknown hand class ${hand}`);
      normalizeHandStrategy(strategy);
    }
  }

  function validateRepository(repo){
    if(!repo||repo.schema!==SCHEMA)throw new Error(`expected ${SCHEMA}`);
    if(repo.source?.preserved_verbatim&&!repo.source?.range_folder)throw new Error('preserved_verbatim source is missing range_folder');
    if(!repo.contexts||typeof repo.contexts!=='object'||Array.isArray(repo.contexts))throw new Error('contexts must be an object');
    for(const [key,node] of Object.entries(repo.contexts)){
      const normalized=normalizeContext(node.context||{});if(key!==contextKey(normalized))throw new Error(`context key mismatch ${key}`);
      for(const kind of LAYERS)validateLayer(node.layers?.[kind],kind,key);
    }
    return true;
  }

  function exportDocument(repo){validateRepository(repo);return deepClone(repo);}

  function legacyRanges(source){
    const root=source?.folder||source,out=[];
    function walk(folder,path=[]){
      if(!folder||typeof folder!=='object')return;
      const here=[...path,folder.name||'Folder'].filter(Boolean);
      for(const range of (folder.ranges||[]))out.push({path:here.join(' / '),range});
      for(const child of (folder.folders||[]))walk(child,here);
    }
    walk(root,[]);return out;
  }

  function repositoryStats(repo){
    validateRepository(repo);
    let personal=0,calculated=0,personalCombos=0,calculatedCombos=0;
    for(const node of Object.values(repo.contexts)){
      for(const hand of Object.keys(node.layers.personal.hands||{})){personal++;personalCombos+=comboMultiplicity(hand);}
      for(const hand of Object.keys(node.layers.calculated.hands||{})){calculated++;calculatedCombos+=comboMultiplicity(hand);}
    }
    return {contexts:Object.keys(repo.contexts).length,personal_defined_hands:personal,calculated_defined_hands:calculated,personal_combo_slots:personalCombos,calculated_combo_slots:calculatedCombos,legacy_ranges:legacyRanges(repo.source?.range_folder).length};
  }

  return {SCHEMA,LAYERS,ACTIONS,POSITIONS,SPOTS,HAND_CLASSES,comboMultiplicity,normalizeContext,contextKey,emptyRepository,importDocument,normalizeHandStrategy,ensureContext,setLayerMetadata,setHandStrategy,getHandStrategy,resolvedLayer,validateRepository,exportDocument,legacyRanges,repositoryStats};
});
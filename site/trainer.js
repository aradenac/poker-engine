"use strict";

/*
  Player trainer MVP.
  - Reuses the existing analyser as the only Hero recommendation / EV oracle.
  - Reuses the replayer table/card CSS primitives.
  - Uses promoted independent Model B v2 for opponent profiles, ranges, actions and sizings.
  - Deliberate v1 boundary: preflop is materialized as a realistic heads-up SRP setup;
    Hero training decisions begin on the flop. Model B v2 postflop action frequencies
    are profile/context conditioned but are not yet conditioned on the hidden combo.
*/

const TRAINER_POPULATION_MANIFEST="./assets/trainer/population.json";

const TRAINER_POSITIONS=["BTN","SB","BB","LJ","HJ","CO"];
const TRAINER_PREFLOP_ORDER=["LJ","HJ","CO","BTN","SB","BB"];
const TRAINER_POSTFLOP_ORDER=["SB","BB","LJ","HJ","CO","BTN"];
const TRAINER_HERO="Hero";
const TRAINER_DELAYS={street:20,opponentThink:35,opponentSettle:25};
const TRAINER_REVIEW_CACHE_MAX=96;
const TrainerActionSizingEV=window.PokerActionSizingEV;
if(!TrainerActionSizingEV?.primarySummaryHtml||!TrainerActionSizingEV?.alternativesStripHtml||!TrainerActionSizingEV?.qualityFromEV)throw new Error("PokerActionSizingEV requis avant trainer.js.");
const trainerWarmAssets={started:false,promise:null,population:null,modelA:null,modelB:null,heroRanges:null,startedAt:0,finishedAt:0,error:null};
const trainerReviewCache={entries:new Map(),preModel:null,postModel:null,hits:0,misses:0,evictions:0};

const trainerState={
  open:false,mode:"training",loading:false,ready:false,error:"",populationId:null,modelB:null,heroRanges:null,
  handNo:0,evalNo:0,hand:null,recommendation:null,feedback:null,
  pauseAfterDecision:false,busy:false,sizingTouched:false,
  perf:{evaluations:0,reused:0,totalMs:0,lastMs:0,modelLoadMs:0,warmupMs:0,warmHit:false,cacheHits:0,cacheMisses:0},
  session:{hands:0,decisions:0,good:0,close:0,poor:0,lossBB:0,breakdown:Object.create(null)},
  testLog:[],
  targeted:{
    active:false,preparing:false,baseTarget:null,target:null,criteria:null,plan:null,pool:[],
    currentIndex:-1,currentScenario:null,currentCompleted:false,events:[],summary:null,
    requestedSize:5,fallback:null,lastError:"",attempts:0,evaluated:0,complete:false
  }
};

const trainerPage=document.getElementById("trainerPage");
const trainerOpenBtn=document.getElementById("trainerOpenBtn");
const trainerNavLink=document.getElementById("trainerNavLink");
const trainerBackBtn=document.getElementById("trainerBackBtn");
const trainerNewHandBtn=document.getElementById("trainerNewHandBtn");
const trainerContinueBtn=document.getElementById("trainerContinueBtn");
const trainerTable=document.getElementById("trainerTable");
const trainerControls=document.getElementById("trainerControls");
const trainerStatus=document.getElementById("trainerStatus");
const trainerRecommendation=document.getElementById("trainerRecommendation");
const trainerFeedback=document.getElementById("trainerFeedback");
const trainerStats=document.getElementById("trainerStats");
const trainerBreakdown=document.getElementById("trainerBreakdown");
const trainerProfiles=document.getElementById("trainerProfiles");
const trainerTestLog=document.getElementById("trainerTestLog");
const trainerPopulationIdentity=document.getElementById("trainerPopulationIdentity");
const trainerTechnicalIdentity=document.getElementById("trainerTechnicalIdentity");
const trainerTargetPanel=document.getElementById("trainerTargetPanel");
const trainerTargetIdentity=document.getElementById("trainerTargetIdentity");
const trainerTargetPosition=document.getElementById("trainerTargetPosition");
const trainerTargetStreet=document.getElementById("trainerTargetStreet");
const trainerTargetSpot=document.getElementById("trainerTargetSpot");
const trainerTargetAction=document.getElementById("trainerTargetAction");
const trainerTargetSizing=document.getElementById("trainerTargetSizing");
const trainerTargetJam=document.getElementById("trainerTargetJam");
const trainerTargetOverbet=document.getElementById("trainerTargetOverbet");
const trainerTargetSessionSize=document.getElementById("trainerTargetSessionSize");
const trainerTargetApplyBtn=document.getElementById("trainerTargetApplyBtn");
const trainerTargetClearBtn=document.getElementById("trainerTargetClearBtn");
const trainerTargetSupport=document.getElementById("trainerTargetSupport");
const trainerTargetSummarySection=document.getElementById("trainerTargetSummarySection");
const trainerTargetSummary=document.getElementById("trainerTargetSummary");

function trainerSleep(ms){return new Promise(r=>setTimeout(r,ms));}
function trainerClamp(x,a,b){return Math.max(a,Math.min(b,x));}
function trainerNum(x,d=2){return Number(x||0).toFixed(d).replace(/\.?0+$/,"");}
function trainerFmtBB(x){return `${new Intl.NumberFormat("fr-FR",{minimumFractionDigits:0,maximumFractionDigits:2}).format(Number(x)||0)} BB`;}
/* #409-RNG-BLOCK-START */
/* #409: unique seedable randomness source for the Trainer.
   `trainerRandom()` is the only entry point Trainer logic uses to draw
   randomness. Production keeps the default Math.random source; tests inject a
   deterministic generator via trainerSetSeed / trainerSetRandomSource without
   ever monkey-patching the global Math.random.
   API (#409): trainerSetRandomSource(fn), trainerSetSeed(seed),
   trainerResetRandomSource(), trainerRandomSeed().
   Documentation (#409): docs/trainer-smoke-determinism.md — mécanisme RNG,
   seed smoke retenue (39) et procédure de reproduction d'une seed en échec.
   The block is delimited by #409-RNG-BLOCK-START / #409-RNG-BLOCK-END so the
   regression tests can extract it verbatim: `Math.random` must appear only
   here, never in the surrounding Trainer logic. */
function trainerMulberry32(seed){
  let a=seed>>>0;
  return function(){
    a=(a+0x6d2b79f5)|0;
    let t=Math.imul(a^(a>>>15),1|a);
    t=(t+Math.imul(t^(t>>>7),61|t))^t;
    return ((t^(t>>>14))>>>0)/4294967296;
  };
}
function trainerNormalizeSeed(seed){
  if(typeof seed==="number"&&Number.isFinite(seed))return seed>>>0;
  const text=String(seed);let h=2166136261>>>0;
  for(let i=0;i<text.length;i++){h^=text.charCodeAt(i);h=Math.imul(h,16777619);}
  return h>>>0;
}
const trainerDefaultRandom=()=>Math.random();
let trainerRandomSource=trainerDefaultRandom;
let trainerCurrentSeed=null;
function trainerRandom(){return trainerRandomSource();}
function trainerSetRandomSource(fn){
  if(typeof fn!=="function")throw new TypeError("trainerSetRandomSource attend une fonction.");
  trainerRandomSource=fn;trainerCurrentSeed=null;
  return trainerRandomSource;
}
function trainerSetSeed(seed){
  trainerCurrentSeed=trainerNormalizeSeed(seed);
  trainerRandomSource=trainerMulberry32(trainerCurrentSeed);
  return trainerCurrentSeed;
}
function trainerResetRandomSource(){trainerRandomSource=trainerDefaultRandom;trainerCurrentSeed=null;}
function trainerRandomSeed(){return trainerCurrentSeed;}
window.trainerSetRandomSource=trainerSetRandomSource;
window.trainerSetSeed=trainerSetSeed;
window.trainerResetRandomSource=trainerResetRandomSource;
window.trainerRandomSeed=trainerRandomSeed;
/* #409-RNG-BLOCK-END */
function trainerRandomInt(n){return Math.floor(trainerRandom()*n);}
function trainerShuffle(a){for(let i=a.length-1;i>0;i--){const j=trainerRandomInt(i+1);[a[i],a[j]]=[a[j],a[i]];}return a;}
function trainerWeightedChoice(items,weights){
  let total=0;const clean=weights.map(w=>{w=Math.max(0,Number(w)||0);total+=w;return w;});
  if(!(total>0))return items[trainerRandomInt(items.length)];
  let x=trainerRandom()*total;
  for(let i=0;i<items.length;i++){x-=clean[i];if(x<=0)return items[i];}
  return items[items.length-1];
}
function trainerPositionForSeat(seat,dealer){return TRAINER_POSITIONS[(seat-dealer+6)%6];}
function trainerSeatForPosition(hand,pos){return hand.positions.findIndex(p=>p===pos);}
function trainerProfileLabel(row){
  const c=row?.centroid||{},vpip=Number(c.vpip)||0,pfr=Number(c.pfr)||0,agg=Number(c.post_aggression_frequency)||0;
  if(vpip<.38)return agg<.21?"serré / passif":"serré / agressif";
  if(pfr>.10||agg>.22)return "loose / agressif";
  return "loose / passif";
}
function trainerProfileById(id){return trainerState.modelB?.profiles?.profiles?.find(x=>Number(x.profile)===Number(id))||null;}
function trainerProfileSummary(id){const p=trainerProfileById(id);return p?`${p.name} · ${trainerProfileLabel(p)}`:`P${id}`;}

async function trainerFetchJson(url){
  const r=await fetch(url,{cache:"force-cache"});
  if(!r.ok)throw new Error(`${url} : HTTP ${r.status}`);
  return r.json();
}
async function trainerFetchText(url){
  const r=await fetch(url,{cache:"force-cache"});
  if(!r.ok)throw new Error(`${url} : HTTP ${r.status}`);
  return r.text();
}
async function trainerLoadWarmAssets(){
  if(trainerWarmAssets.promise)return trainerWarmAssets.promise;
  trainerWarmAssets.started=true;trainerWarmAssets.startedAt=performance.now();
  trainerWarmAssets.promise=(async()=>{
    try{
      const population=await trainerFetchJson(TRAINER_POPULATION_MANIFEST);
      if(population?.schema!=="trainer-population-pack/v1"||!population?.population_id||!population?.assets)throw new Error("Pack trainer : manifeste de population invalide.");
      const asset=population.assets;
      const [profiles,ranges,actions,sizing,contract,preflop,postflop,heroRanges]=await Promise.all([
        trainerFetchJson(asset.modelB.profiles),trainerFetchJson(asset.modelB.ranges),
        trainerFetchJson(asset.modelB.actions),trainerFetchJson(asset.modelB.sizing),
        trainerFetchJson(asset.modelB.contract),trainerFetchText(asset.modelA.preflop),
        trainerFetchText(asset.modelA.postflop),trainerFetchJson(asset.hero.ranges)
      ]);
      trainerWarmAssets.population=population;trainerWarmAssets.modelB={profiles,ranges,actions,sizing,contract};
      trainerWarmAssets.modelA={preflop,postflop};trainerWarmAssets.heroRanges=heroRanges;
      trainerWarmAssets.finishedAt=performance.now();
      trainerState.perf.warmupMs=trainerWarmAssets.finishedAt-trainerWarmAssets.startedAt;
      trainerRefreshHeroStrategyIdentity(population);
      return {population,modelA:trainerWarmAssets.modelA,modelB:trainerWarmAssets.modelB,heroRanges:trainerWarmAssets.heroRanges};
    }catch(err){trainerWarmAssets.error=err;trainerWarmAssets.promise=null;throw err;}
  })();
  return trainerWarmAssets.promise;
}
function trainerScheduleWarmup(){
  const start=()=>{if(!trainerWarmAssets.started)trainerLoadWarmAssets().catch(()=>{});};
  if("requestIdleCallback" in window)window.requestIdleCallback(start,{timeout:2500});
  else window.setTimeout(start,1200);
}

const TRAINER_HERO_REPOSITORY_KEY="poker.hero.range.repository.v1";
const TRAINER_HERO_FAIL_CLOSE="Stratégie indisponible pour cette population";

function trainerHeroRepository(){
  try{
    const Migration=window.PokerHeroRangeMigration;
    if(Migration?.loadRepository&&window.localStorage)return Migration.loadRepository(window.localStorage)||null;
    const raw=window.localStorage?.getItem(TRAINER_HERO_REPOSITORY_KEY);
    return raw?JSON.parse(raw):null;
  }catch(_){return null;}
}
function trainerHeroPackIdentity(){
  const pack=(typeof state!=="undefined"?state:null)?.manualOverrideContract?.base_active_pack||null;
  return pack&&pack.population_id?{population_id:pack.population_id,pack_id:pack.pack_id||null,pack_version:pack.pack_version||null}:null;
}
function trainerHeroRetainedReference(manifest){
  const provenance=manifest?.hero_provenance;
  if(!provenance?.population_id)return null;
  return {
    schema:provenance.schema||null,
    issue:null,
    population_id:provenance.population_id,
    strategy_id:provenance.strategy_id||null,
    strategy_version:provenance.sha256?String(provenance.sha256).slice(0,16):null,
    strategy_sha256:provenance.sha256||null
  };
}
// The personal override chip must never be driven by the mere global presence of
// an override. `active` is recomputed from the context actually resolved for the
// current Hero situation (population/position/stack/spot via
// HeroRanges.contextKey); an unresolvable context is a fail-safe inactive state
// while `available` can still report an override elsewhere in the population.
function trainerHeroOverrideContext(manifest){
  const hand=trainerState.hand;
  if(!hand||hand.ended)return null;
  const hero=Number(hand.heroSeat);
  if(!Number.isInteger(hero)||hero<0)return null;
  const position=String(hand.positions?.[hero]||"").toUpperCase();
  if(!position)return null;
  const population=String(manifest?.population_id||trainerState.populationId||"").trim();
  let table_size=Number(hand.names?.length||0),effective_stack_bb=null,spot=null,preflopContextId=null;
  try{
    if(window.PokerPreflopContract?.buildContext&&hand.core&&!hand.folded?.[hero]&&typeof hand.core.legalView==="function"){
      const ctx=trainerPreflopContext(hand,hero),ctxTable=Number(ctx.table_size);
      if(Number.isInteger(ctxTable)&&ctxTable>=2)table_size=ctxTable;
      effective_stack_bb=Number(ctx.effective_stack_bb);
      spot=String(ctx.family||"").toUpperCase()||null;
      const contextId=String(ctx.context_id||"").trim();
      if(/^PFC_[0-9a-f]{16}$/i.test(contextId))preflopContextId=contextId;
    }
  }catch(_){/* fall through to the raw hand stack, still fail-safe */}
  if(!Number.isFinite(effective_stack_bb)||effective_stack_bb<=0)effective_stack_bb=Number(hand.stacks?.[hero]);
  if(!Number.isInteger(table_size)||table_size<2||!Number.isFinite(effective_stack_bb)||effective_stack_bb<=0||!spot)return null;
  const context={population_id:population,table_size,position,effective_stack_bb,spot};
  if(preflopContextId)context.preflop_context_id=preflopContextId;
  return context;
}
function trainerHeroPersonalOverride(manifest){
  const population=manifest?.population_id||trainerState.populationId||null;
  const repository=trainerHeroRepository(),Migration=window.PokerHeroRangeMigration;
  const context=trainerHeroOverrideContext(manifest);
  if(repository&&Migration?.personalOverrideStatus){
    try{return Migration.personalOverrideStatus(repository,{populationId:population,activePopulationId:population,context});}catch(_){}
  }
  // Fail-safe: an unavailable repository never activates an override and is
  // never presented as the population strategy.
  return {
    schema:"poker-hero-personal-override-status/v1",
    source:"PERSONAL_OVERRIDE",
    population_id:population||null,
    available:false,active:false,active_context_key:null,context_keys:[],count:0
  };
}
function trainerRefreshPersonalOverride(manifest){
  trainerState.personalOverride=trainerHeroPersonalOverride(manifest||trainerWarmAssets.population||null);
  if(typeof updateProductIdentityUi==="function")updateProductIdentityUi();
  return trainerState.personalOverride;
}
window.trainerRefreshPersonalOverride=trainerRefreshPersonalOverride;
// #task-0jt: build the complete population-bound admission object for the
// resolver (role/hash/provenance/candidate/generation/binding) instead of a bare
// {status,population_id} token. The legacy range-folder reference has no
// calculated candidate, so candidate_id/generation_id/binding_sha256 stay null:
// it remains RETAIN_REFERENCE and is never promoted or relabelled.
function trainerHeroAdmissionFromProvenance(provenance,population){
  if(!provenance?.status)return null;
  const populationId=provenance.population_id||population||null;
  const sha=provenance.sha256||null;
  const candidateId=provenance.candidate_id||null;
  const generationId=provenance.generation_id||null;
  const bindingSha=provenance.binding_sha256||null;
  return {
    status:provenance.status,
    role:"hero_strategy",
    population_id:populationId,
    strategy_id:provenance.strategy_id||null,
    strategy_version:provenance.strategy_version||(sha?String(sha).slice(0,16):null),
    candidate_id:candidateId,
    generation_id:generationId,
    binding_sha256:bindingSha,
    artifact:{
      declared_sha256:sha,
      actual_sha256:sha,
      hash_kind:"file_sha256",
      source_path:provenance.ranges_path||null,
      verified:sha!=null
    },
    provenance:{
      source_population_id:populationId,
      manifest_sha256:sha,
      binding_sha256:bindingSha,
      candidate_id:candidateId,
      generation_id:generationId
    }
  };
}
// The coverage bound is only forwarded when an authoritative source declares it
// (generation manifest / required_context_keys). Absent means "unknown", never a
// self-referential completeness claim.
function trainerHeroCoverageBound(manifest,provenance){
  const keys=manifest?.required_context_keys||provenance?.required_context_keys||null;
  const generation=manifest?.generation_manifest||provenance?.generation_manifest||null;
  return {
    required_context_keys:Array.isArray(keys)&&keys.length?keys:null,
    generation_manifest:generation&&typeof generation==="object"?generation:null
  };
}
function trainerRefreshHeroStrategyIdentity(manifest){
  const populationManifest=manifest||trainerWarmAssets.population||null;
  const population=populationManifest?.population_id||trainerState.populationId||null;
  const provenance=populationManifest?.hero_provenance||null;
  const Resolver=window.PokerHeroStrategyResolver;
  if(population)trainerState.populationId=population;
  const coverage=trainerHeroCoverageBound(populationManifest,provenance);
  let resolution=null;
  if(population&&Resolver?.resolveHeroStrategy){
    resolution=Resolver.resolveHeroStrategy({
      population_id:population,
      repository:trainerHeroRepository(),
      trainer_manifest:populationManifest,
      pack_identity:trainerHeroPackIdentity(),
      admissions:provenance?.status?{hero_strategy:trainerHeroAdmissionFromProvenance(provenance,population)}:null,
      retained_reference:trainerHeroRetainedReference(populationManifest),
      required_context_keys:coverage.required_context_keys,
      generation_manifest:coverage.generation_manifest
    });
  }
  trainerState.heroStrategyResolution=resolution;
  trainerState.personalOverride=trainerHeroPersonalOverride(populationManifest);
  if(typeof updateProductIdentityUi==="function")updateProductIdentityUi();
  return resolution;
}
function trainerHeroStrategyLabel(){
  const resolution=trainerState.heroStrategyResolution;
  if(!resolution||resolution.fail_closed||resolution.status!=="ADMISSIBLE_CALCULATED")return TRAINER_HERO_FAIL_CLOSE;
  return String(resolution.strategy_id||"stratégie Hero");
}
function trainerHeroStrategySummary(){
  const resolution=trainerState.heroStrategyResolution;
  if(!resolution||resolution.fail_closed||resolution.status!=="ADMISSIBLE_CALCULATED")return TRAINER_HERO_FAIL_CLOSE;
  const version=resolution.strategy_version?` · version ${resolution.strategy_version}`:"";
  return `stratégie Hero ${resolution.strategy_id||"indisponible"}${version}`;
}
window.trainerRefreshHeroStrategyIdentity=trainerRefreshHeroStrategyIdentity;

async function trainerEnsureModels(){
  if(trainerState.ready)return true;
  if(trainerState.loading){
    while(trainerState.loading)await trainerSleep(100);
    return trainerState.ready;
  }
  trainerState.loading=true;trainerState.error="";trainerRenderStatus("Chargement de la population et de la stratégie…","busy");
  const loadStarted=performance.now();
  try{
    const alreadyWarm=!!(trainerWarmAssets.modelA&&trainerWarmAssets.modelB&&trainerWarmAssets.heroRanges),assets=await trainerLoadWarmAssets();
    trainerState.perf.warmHit=alreadyWarm;
    const {profiles,ranges,actions,sizing,contract}=assets.modelB;
    if(!assets.population?.population_id)throw new Error("Pack trainer : population absente.");
    if(profiles.schema!=="independent-opponent-profiles/v2"||ranges.schema!=="independent-preflop-ranges/v2"||actions.schema!=="independent-postflop-actions/v2"||sizing.schema!=="independent-postflop-sizing/v2")throw new Error("Model B : schéma inattendu.");
    if(assets.heroRanges?.schema!=="trainer-hero-preflop-ranges/v1")throw new Error("Ranges Hero : schéma inattendu.");
    trainerState.populationId=assets.population.population_id;trainerState.modelB=assets.modelB;trainerState.heroRanges=assets.heroRanges;
    if(trainerPopulationIdentity)trainerPopulationIdentity.textContent=trainerState.populationId;
    trainerRefreshHeroStrategyIdentity(assets.population);

    if(!state.populationModel){
      const content=assets.modelA.preflop;
      const ok=await applyPopulationModelSnapshot({name:"preflop_population_model_v5.json",content,size:content.length},{persist:false,restored:true});
      if(!ok)throw new Error("Impossible d'initialiser Model A préflop.");
    }
    if(!state.postflopModel){
      const content=assets.modelA.postflop;
      const ok=await applyPostflopModelSnapshot({name:"postflop_population_model_v5.json",content,size:content.length},{persist:false,restored:true});
      if(!ok)throw new Error("Impossible d'initialiser Model A postflop.");
    }
    trainerState.perf.modelLoadMs=performance.now()-loadStarted;
    trainerState.ready=true;
    if(trainerTechnicalIdentity)trainerTechnicalIdentity.textContent=`Population ${trainerState.populationId} · Model A v5 · Model B v2 · ${trainerHeroStrategySummary()} · init ${trainerState.perf.modelLoadMs.toFixed(0)} ms${trainerState.perf.warmHit?" · assets préchargés":""}.`;
    trainerRenderStatus(`Trainer prêt · ${trainerState.populationId} · ${trainerHeroStrategySummary()}.`);
    return true;
  }catch(err){
    trainerState.error=err?.message||String(err);trainerRenderStatus(`Trainer indisponible : ${trainerState.error}`,"error");return false;
  }finally{trainerState.loading=false;trainerRender();}
}

function trainerTargetApis(){
  const Target=window.PokerLeakTrainingTarget,Selector=window.PokerLeakScenarioSelector,Leak=window.PokerLeakAnalyzer;
  if(!Target?.buildTrainingTarget||!Target?.compileScenarioCriteria||!Target?.scenarioMatchesCriteria)throw new Error("poker-leak-training-target/v1 indisponible.");
  if(!Selector?.buildSessionPlan||!Selector?.summarizePlannedSession)throw new Error("poker-leak-training-session-plan/v1 indisponible.");
  if(!Leak?.buildDecisionEvent)throw new Error("PokerLeakAnalyzer indisponible.");
  return {Target,Selector,Leak};
}
function trainerTargetClone(v){return v==null?v:JSON.parse(JSON.stringify(v));}
function trainerTargetResetSessionCounters(){
  trainerState.session={hands:0,decisions:0,good:0,close:0,poor:0,lossBB:0,breakdown:Object.create(null)};
  trainerState.testLog=[];
}
function trainerTargetSameIdentity(a={},b={}){
  return ["population_id","pack_id","strategy_id","strategy_version","ev_reference"].every(k=>String(a?.[k]??"")===String(b?.[k]??""));
}
function trainerTargetAssertCurrentIdentity(target){
  const currentDashboard=typeof reviewDashboardBuild==="function"?reviewDashboardBuild():state.reviewDashboardView;
  const currentTarget=currentDashboard?.ctas?.training?.target||null;
  if(currentTarget?.identity&&!trainerTargetSameIdentity(currentTarget.identity,target.identity))throw new Error("Le contexte Review a changé : population/pack/stratégie/version/EV ne correspondent plus à ce ciblage.");
}
function trainerTargetIdentityText(target){
  const id=target?.identity||{};
  return `Population ${id.population_id||"—"} · pack ${id.pack_id||"—"} · stratégie ${id.strategy_id||"—"} · version ${id.strategy_version||"—"} · EV ${id.ev_reference||"—"}`;
}
function trainerTargetHydrate(target){
  if(!target)return;
  trainerTargetPanel.hidden=false;
  trainerTargetSummarySection.hidden=false;
  trainerTargetIdentity.textContent=trainerTargetIdentityText(target);
  trainerTargetPosition.value=String(target.context?.position||"");
  trainerTargetStreet.value=String(target.context?.street||"");
  trainerTargetSpot.value=String(target.context?.spot_family||"");
  trainerTargetAction.value=String(target.source_pattern?.recommended_action||"");
  trainerTargetSizing.checked=target.source_pattern?.sizing_error===true;
  trainerTargetJam.checked=target.source_pattern?.jam===true;
  trainerTargetOverbet.checked=target.source_pattern?.overbet===true;
  trainerTargetSessionSize.value=String(trainerState.targeted.requestedSize||5);
}
function trainerTargetBuildFromControls(){
  const {Target}=trainerTargetApis(),base=trainerState.targeted.baseTarget;
  if(!base)throw new Error("Aucun leak source n'est actif.");
  const size=Math.max(1,Math.min(10,Number(trainerTargetSessionSize.value)||5));
  trainerState.targeted.requestedSize=size;
  return Target.buildTrainingTarget({
    identity:trainerTargetClone(base.identity),
    context:{
      position:String(trainerTargetPosition.value||"").toUpperCase()||null,
      street:String(trainerTargetStreet.value||"").toUpperCase()||null,
      spot_family:String(trainerTargetSpot.value||"").trim().toUpperCase()||null
    },
    source_pattern:{
      played_action:base.source_pattern?.played_action||null,
      recommended_action:String(trainerTargetAction.value||"").toUpperCase()||null,
      sizing_error:trainerTargetSizing.checked?true:null,
      jam:trainerTargetJam.checked?true:null,
      overbet:trainerTargetOverbet.checked?true:null
    },
    source_leak:trainerTargetClone(base.source_leak),
    minimum_support:trainerTargetClone(base.minimum_support)
  });
}
function trainerTargetHints(target){
  const street=String(target?.context?.street||"").toUpperCase(),spot=String(target?.context?.spot_family||"").toUpperCase();
  if(street==="PREFLOP")return {unsupported:"PREFLOP_NOT_MATERIALIZED_BY_CURRENT_TRAINER"};
  const parts=spot?spot.split("|"):[];
  if(parts.length&&parts[0]&&parts[0]!=="SRP")return {unsupported:"SPOT_FAMILY_NOT_MATERIALIZED_BY_CURRENT_TRAINER"};
  return {
    position:String(target?.context?.position||"").toUpperCase(),
    preflopRole:["PFA","CALLER"].includes(parts[1])?parts[1]:"",
    relativePosition:["IP","OOP"].includes(parts[2])?parts[2]:"",
    preview:true,strict:true
  };
}
function trainerTargetStreetRank(street){return ({FLOP:0,TURN:1,RIVER:2})[String(street||"").toUpperCase()]??-1;}
function trainerTargetAdvancePreview(hand,target){
  const desired=String(target?.context?.street||"").toUpperCase();
  for(let guard=0;guard<40&&!hand.ended;guard++){
    if(!hand.queue.length){trainerAdvanceStreetOrShowdown(hand);continue;}
    const seat=hand.queue.shift();
    if(hand.folded[seat]||hand.stacks[seat]<=1e-8)continue;
    if(seat!==hand.heroSeat){trainerOpponentAct(hand);continue;}
    hand.awaitingHero=true;hand.decisionNo++;
    const current=String(hand.street||"").toUpperCase();
    if(!desired||current===desired)return hand;
    if(trainerTargetStreetRank(current)>trainerTargetStreetRank(desired))return null;
    const toCall=trainerToCall(hand,hand.heroSeat),kind=toCall>1e-8?"CALL":"CHECK";
    hand.awaitingHero=false;trainerApplyAction(hand,hand.heroSeat,kind,toCall);
  }
  return null;
}
function trainerTargetSpotFamily(detail,hand){
  const sim=detail?.simContext||{},parts=[sim.potType,sim.preflopRole,sim.relativePosition].map(v=>String(v||"").toUpperCase()).filter(Boolean);
  if(parts.length===3)return parts.join("|");
  const heroPos=hand.positions[hand.heroSeat],oppPos=hand.positions[hand.activeOppSeat],relative=trainerPostRank(heroPos)>trainerPostRank(oppPos)?"IP":"OOP";
  return `SRP|${hand.heroRole}|${relative}`;
}
function trainerTargetFocus(hand){
  const toCall=trainerToCall(hand,hand.heroSeat),remaining=Number(hand.stacks[hand.heroSeat])||0;
  const canAggress=remaining>toCall+1e-8&&hand.raises<2;
  return {sizing_decision:canAggress,jam_available:canAggress,overbet_available:canAggress&&remaining>Number(hand.pot||0)+toCall+1e-8};
}
function trainerTargetDescriptor(target,hand,detail,attempt){
  const {Target}=trainerTargetApis(),recommended=trainerRecommendationKind(hand,detail),chosen=Number(detail?.chosenEV),best=Number(detail?.bestEV);
  const comparable=detail?.comparable!==false&&Number.isFinite(chosen)&&Number.isFinite(best),position=String(hand.positions[hand.heroSeat]||"").toUpperCase();
  const board=hand.runout.slice(0,hand.boardCount).map(cardCode).join("-");
  return {
    schema:Target.SCENARIO_SCHEMA,
    scenario_id:`trainer-target:${target.target_id}:${attempt}:${hand.id}:${hand.decisionNo}`,
    identity:trainerTargetClone(target.identity),
    context:{position,street:String(hand.street||"").toUpperCase(),spot_family:trainerTargetSpotFamily(detail,hand)},
    policy:{recommended_action:recommended},
    focus:trainerTargetFocus(hand),
    supported:comparable,
    support:{covered:comparable,reason:comparable?null:"NO_COMPARABLE_EV"},
    diversity_key:`${position}|${hand.heroRole}|${board}`,
    payload_key:`${hand.id}|${hand.decisionNo}`,
    payload:{hand:trainerTargetClone(hand),recommendation:trainerTargetClone(detail)}
  };
}
function trainerTargetSetSupport(text,kind=""){
  if(!trainerTargetSupport)return;
  trainerTargetSupport.textContent=text||"";
  trainerTargetSupport.className=`tiny${kind?" "+kind:""}`;
}
async function trainerTargetMaterializePool(target,requestedSize){
  const {Target}=trainerTargetApis(),criteria=Target.compileScenarioCriteria(target),hints=trainerTargetHints(target);
  if(hints.unsupported)return {pool:[],criteria,attempts:0,evaluated:0,unsupported:hints.unsupported};
  const required=Math.max(requestedSize,Number(target.minimum_support?.scenarios)||1),maxAttempts=Math.max(30,required*18),maxEvaluated=Math.max(14,required*6);
  const pool=[];let matching=0,attempts=0,evaluated=0;
  while(attempts<maxAttempts&&evaluated<maxEvaluated&&matching<required){
    attempts++;
    const hand=trainerBuildHand(hints);if(!hand)break;
    const ready=trainerTargetAdvancePreview(hand,target);if(!ready||ready.ended)continue;
    evaluated++;
    trainerTargetSetSupport(`Qualification des spots… ${matching}/${required} supportés · ${evaluated} évalués`,"busy");
    let detail=null;
    try{
      const ph=trainerPlaceholderLine(ready);
      detail=await trainerTimedReviewText(trainerBuildReviewHH(ready,ph.line,ph.kind,0));
    }catch(err){
      pool.push({
        schema:Target.SCENARIO_SCHEMA,scenario_id:`trainer-target:${target.target_id}:${attempts}:unsupported`,
        identity:trainerTargetClone(target.identity),context:{position:ready.positions[ready.heroSeat],street:String(ready.street).toUpperCase(),spot_family:trainerTargetSpotFamily(null,ready)},
        policy:{recommended_action:"UNKNOWN"},focus:trainerTargetFocus(ready),supported:false,support:{covered:false,reason:"ORACLE_UNAVAILABLE"},
        payload:{hand:trainerTargetClone(ready),recommendation:{error:String(err?.message||err)}}
      });
      continue;
    }
    const descriptor=trainerTargetDescriptor(target,ready,detail,attempts);pool.push(descriptor);
    if(Target.scenarioMatchesCriteria(descriptor,criteria))matching++;
  }
  return {pool,criteria,attempts,evaluated,unsupported:null};
}
function trainerTargetRenderSummary(){
  const t=trainerState.targeted;
  if(!t.active){trainerTargetPanel.hidden=true;trainerTargetSummarySection.hidden=true;return;}
  trainerTargetPanel.hidden=false;trainerTargetSummarySection.hidden=false;
  if(t.fallback){
    const p=t.plan?.pool||{};
    trainerTargetSummary.textContent=`${t.fallback} · ${p.matching_supported??0} spot(s) exact(s) pour ${p.requested_coverage_pct==null?t.requestedSize:t.plan.request.session_size} demandé(s) · aucune substitution silencieuse.`;
    return;
  }
  if(!t.plan){trainerTargetSummary.textContent=t.preparing?"Préparation de la session ciblée…":"Aucun plan ciblé exécutable.";return;}
  const s=t.summary?.summary;
  if(!s){trainerTargetSummary.textContent=`0/${t.plan.selection.length} spot joué · perte ΔEV ciblée : — · le bilan sera calculé uniquement sur les décisions couvertes et comparables.`;return;}
  const change=s.within_session_change;
  const evolution=change?` · évolution descriptive ${trainerFmtBB(change.first_segment_avg_loss_bb)} → ${trainerFmtBB(change.second_segment_avg_loss_bb)} (Δ ${trainerFmtBB(change.delta_avg_loss_bb)})`:" · évolution : échantillon encore insuffisant";
  const longTerm=t.summary.long_term_progression;
  trainerTargetSummary.textContent=`${t.summary.spots_played}/${t.plan.selection.length} spot(s) joué(s) · couvert/comparable ${s.covered_comparable} · perte ΔEV ciblée ${trainerFmtBB(s.total_delta_ev_loss_bb)} · moyenne ${s.average_delta_ev_loss_bb==null?"—":trainerFmtBB(s.average_delta_ev_loss_bb)} · unsupported ${s.unsupported} · non-comparable ${s.non_comparable}${evolution} · progression long terme non inférée (${longTerm.reason}).`;
}
function trainerTargetLoadSelection(index){
  const t=trainerState.targeted,row=t.plan?.selection?.[index],payload=row?.scenario?.payload;
  if(!row||!payload?.hand){
    t.complete=true;t.currentScenario=null;t.currentCompleted=false;
    if(trainerState.hand)trainerState.hand.awaitingHero=false;
    trainerRenderStatus("Session ciblée terminée.");trainerRender();return false;
  }
  t.currentIndex=index;t.currentScenario=row;t.currentCompleted=false;t.complete=false;
  trainerState.hand=trainerTargetClone(payload.hand);trainerState.hand.preview=true;trainerState.hand.awaitingHero=true;
  trainerState.recommendation=trainerTargetClone(payload.recommendation);trainerState.feedback=null;trainerState.pauseAfterDecision=false;trainerState.sizingTouched=false;
  trainerRenderStatus(`Spot ciblé ${index+1}/${t.plan.selection.length} · ${row.context.position} · ${row.context.street} · ${row.context.spot_family}.`);
  trainerRender();return true;
}
function trainerTargetNext(){
  const t=trainerState.targeted;if(!t.active||!t.plan?.ready)return false;
  const next=t.currentIndex+1;
  if(next>=t.plan.selection.length){
    t.complete=true;t.currentScenario=null;t.currentCompleted=false;trainerState.pauseAfterDecision=false;
    if(trainerState.hand)trainerState.hand.awaitingHero=false;
    trainerRenderStatus("Session ciblée terminée · bilan ΔEV disponible.");trainerRender();return false;
  }
  return trainerTargetLoadSelection(next);
}
function trainerTargetEvent(detail,row,actual){
  const t=trainerState.targeted,selection=t.currentScenario,scenario=selection?.scenario,hand=trainerState.hand;
  if(!t.active||!t.plan||!scenario||!hand)return null;
  const {Leak,Selector}=trainerTargetApis(),chosen=Number(detail?.chosenEV),best=Number(detail?.bestEV),comparable=detail?.comparable!==false&&Number.isFinite(chosen)&&Number.isFinite(best);
  const played=String(actual?.kind||row?.played||"UNKNOWN").toUpperCase(),recommended=String(scenario.policy?.recommended_action||"UNKNOWN").toUpperCase();
  const cost=Number(actual?.cost)||0,potBefore=Math.max(.01,Number(hand.pot)||0),bestCost=detail?.bestCostBB!=null?Number(detail.bestCostBB):NaN,rawLoss=Math.max(0,Number(detail?.rawLossBB)||0),effectiveLoss=Math.max(0,Number(row?.lossBB)||0);
  const aggressive=["BET","RAISE"].includes(played),playedRatio=aggressive?cost/potBefore:null,allIn=cost>=Number(hand.stacks[hand.heroSeat]||0)-1e-8&&cost>0;
  const event=Leak.buildDecisionEvent({
    hand_id:`trainer-target-${hand.id}-${t.currentIndex+1}`,decision_id:`trainer-target:${hand.id}:${hand.decisionNo}`,timestamp:new Date(Date.now()+t.events.length).toISOString(),
    ...trainerTargetClone(t.target.identity),position:scenario.context.position,street:scenario.context.street,spot_family:scenario.context.spot_family,context_id:t.target.target_id,
    action_played:played,action_recommended:recommended,played_target_total_bb:(Number(hand.streetPaid[hand.heroSeat])||0)+cost,
    recommended_target_total_bb:Number.isFinite(bestCost)?(Number(hand.streetPaid[hand.heroSeat])||0)+bestCost:null,
    played_size_pot_ratio:playedRatio,recommended_size_pot_ratio:Number.isFinite(bestCost)&&["BET","RAISE"].includes(recommended)?bestCost/potBefore:null,
    played_is_all_in:allIn,played_is_overbet:playedRatio!=null&&playedRatio>1,played_ev_bb:comparable?chosen:null,best_ev_bb:comparable?best:null,
    uncertainty_bb:Math.max(0,rawLoss-effectiveLoss),attributed_loss_bb:comparable?effectiveLoss:null,within_noise:!!detail?.withinNoise,
    sizing_error:played===recommended&&Number.isFinite(bestCost)&&Math.abs(bestCost-cost)>.05,
    support:{covered:comparable,source:"trainer-targeted-runtime",reason:comparable?null:"NO_COMPARABLE_EV"},
    comparability:{comparable,reason:comparable?null:"NO_COMPARABLE_EV"},notes:`target_id=${t.target.target_id}`
  });
  t.events.push(event);
  t.summary=Selector.summarizePlannedSession(t.plan,t.events,{minimum_trend_decisions:4,minimum_long_term_spots:50});
  trainerTargetRenderSummary();return event;
}
async function trainerPrepareTargetSession(target,{hydrate=false}={}){
  const t=trainerState.targeted,{Selector}=trainerTargetApis();
  t.active=true;t.preparing=true;t.target=trainerTargetClone(target);t.plan=null;t.pool=[];t.criteria=null;t.currentIndex=-1;t.currentScenario=null;t.currentCompleted=false;t.events=[];t.summary=null;t.fallback=null;t.lastError="";t.complete=false;
  if(hydrate||!t.baseTarget){t.baseTarget=trainerTargetClone(target);trainerTargetHydrate(target);}
  trainerTargetResetSessionCounters();trainerTargetRenderSummary();
  try{
    trainerTargetAssertCurrentIdentity(target);
    if(!target.source_support?.sufficient)throw new Error("INSUFFICIENT_SOURCE_SUPPORT");
    if(!await trainerEnsureModels())throw new Error(trainerState.error||"Trainer indisponible");
    const materialized=await trainerTargetMaterializePool(target,t.requestedSize);
    t.pool=materialized.pool;t.criteria=materialized.criteria;t.attempts=materialized.attempts;t.evaluated=materialized.evaluated;
    const plan=Selector.buildSessionPlan(target,t.pool,{session_size:t.requestedSize,seed:target.target_id,identity:trainerTargetClone(target.identity)});
    t.plan=plan;t.fallback=plan.fallback||materialized.unsupported||null;
    if(!plan.ready){
      t.fallback=plan.fallback||"INSUFFICIENT_SUPPORTED_SCENARIOS";
      trainerState.hand=null;trainerState.recommendation=null;trainerState.feedback=null;trainerState.pauseAfterDecision=false;
      const p=plan.pool||{};trainerTargetSetSupport(`${t.fallback} · exacts ${p.matching_supported??0}/${plan.request.effective_minimum_supported_scenarios} · ${p.rejected??0} rejeté(s) · aucun spot alternatif sélectionné.`,"error");
      trainerRenderStatus("Session ciblée indisponible : support exact insuffisant.","error");trainerRender();return plan;
    }
    trainerTargetSetSupport(`Plan exact prêt · ${plan.pool.matching_supported} spot(s) supporté(s), ${plan.selection.length} sélectionné(s) · target ${plan.target_id}.`);
    trainerTargetLoadSelection(0);return plan;
  }catch(err){
    t.lastError=String(err?.message||err);t.fallback=t.lastError==="INSUFFICIENT_SOURCE_SUPPORT"?"INSUFFICIENT_SOURCE_SUPPORT":"INSUFFICIENT_SUPPORTED_SCENARIOS";
    trainerState.hand=null;trainerState.recommendation=null;trainerState.feedback=null;trainerState.pauseAfterDecision=false;
    trainerTargetSetSupport(`${t.fallback} · ${t.lastError} · aucune substitution silencieuse.`,"error");
    trainerRenderStatus(`Session ciblée indisponible : ${t.lastError}`,"error");trainerRender();return null;
  }finally{t.preparing=false;trainerTargetRenderSummary();}
}
async function trainerOpenTargetedSession(target){
  const {Target}=trainerTargetApis();
  if(!target||target.schema!==Target.TARGET_SCHEMA)throw new Error("Descriptor poker-leak-training-target/v1 requis.");
  trainerState.targeted.baseTarget=trainerTargetClone(target);trainerState.targeted.requestedSize=Math.max(1,Math.min(10,Number(trainerTargetSessionSize?.value)||5));
  trainerTargetHydrate(target);
  await trainerOpen({deferHand:true});
  return trainerPrepareTargetSession(target,{hydrate:true});
}
window.trainerOpenTargetedSession=trainerOpenTargetedSession;
async function trainerApplyTargetControls(){
  if(!trainerState.targeted.active)return;
  try{const target=trainerTargetBuildFromControls();await trainerPrepareTargetSession(target,{hydrate:false});}
  catch(err){trainerTargetSetSupport(String(err?.message||err),"error");}
}
async function trainerClearTargeting(){
  const t=trainerState.targeted;t.active=false;t.preparing=false;t.baseTarget=null;t.target=null;t.criteria=null;t.plan=null;t.pool=[];t.currentIndex=-1;t.currentScenario=null;t.currentCompleted=false;t.events=[];t.summary=null;t.fallback=null;t.lastError="";t.complete=false;
  trainerTargetPanel.hidden=true;trainerTargetSummarySection.hidden=true;trainerState.hand=null;trainerState.recommendation=null;trainerState.feedback=null;trainerState.pauseAfterDecision=false;
  trainerTargetResetSessionCounters();trainerRenderStatus("Ciblage désactivé · session Training générale.");trainerRender();await trainerNewHand();
}

function trainerKeyFor(cols,row){return !cols?.length?"ALL":cols.map(c=>String(row[c]??"NA")).join("|");}
function trainerSelectNode(levels,row,minObs){
  let fallback=null;
  for(let i=0;i<(levels||[]).length;i++){
    const level=levels[i],key=trainerKeyFor(level.cols,row),node=level.data?.[key];
    if(i===(levels.length-1))fallback=node||fallback;
    if(node&&Number(node.n||0)>=Number(minObs||0))return node;
  }
  if(fallback)return fallback;
  throw new Error(`Aucun nœud Model B pour ${JSON.stringify(row)}`);
}
function trainerSampleProfile(){
  const rows=[...(trainerState.modelB?.profiles?.profiles||[])].sort((a,b)=>Number(a.profile)-Number(b.profile));
  return Number(trainerWeightedChoice(rows.map(x=>Number(x.profile)),rows.map(x=>Number(x.appearance_weight)||0)));
}
function trainerClassProbabilities(profile,position,potType,role){
  const m=trainerState.modelB.ranges,row={profile:Number(profile),position,pot_type:potType,preflop_role:role};
  const node=trainerSelectNode(m.levels,row,m.backoff_min_observations);
  const prior=Number(trainerState.modelB.contract?.preflop_range?.prior_strength)||1,mult=m.multiplicity||{},counts=node.counts||{},n=Number(node.n)||Object.values(counts).reduce((s,x)=>s+Number(x||0),0),den=n+prior;
  const out=Object.create(null);
  for(const h of m.notations)out[h]=(Number(counts[h]||0)+prior*Number(mult[h]||1)/1326)/den;
  return out;
}
function trainerSampleRangeCards(profile,position,potType,role,blocked){
  const probs=trainerClassProbabilities(profile,position,potType,role),mult=trainerState.modelB.ranges.multiplicity||{};
  const combos=[],weights=[];
  for(let a=0;a<52;a++)for(let b=a+1;b<52;b++){
    if(blocked.has(a)||blocked.has(b))continue;
    const cls=cardsToNotation([a,b]);combos.push([a,b]);weights.push((Number(probs[cls])||0)/Math.max(1,Number(mult[cls])||1));
  }
  const c=trainerWeightedChoice(combos,weights);return c||combos[trainerRandomInt(combos.length)];
}
function trainerHeroRangeMap(role,position){return trainerState.heroRanges?.ranges?.[String(role||"").toUpperCase()]?.[String(position||"").toUpperCase()]||null;}
function trainerHeroRangeAvailable(role,position){const range=trainerHeroRangeMap(role,position);return !!range&&Object.values(range).some(x=>Number(x)>0);}
function trainerSampleHeroRangeCards(role,position,blocked=new Set()){
  const range=trainerHeroRangeMap(role,position);if(!range)return null;
  const combos=[],weights=[];
  for(let a=0;a<52;a++)for(let b=a+1;b<52;b++){
    if(blocked.has(a)||blocked.has(b))continue;
    const cls=cardsToNotation([a,b]),weight=Number(range[cls])||0;if(!(weight>0))continue;
    combos.push([a,b]);weights.push(weight);
  }
  return combos.length?trainerWeightedChoice(combos,weights):null;
}
function trainerActionProbabilities(ctx){
  const m=trainerState.modelB.actions,mode=ctx.mode.toUpperCase(),labels=[...(m.labels?.[mode]||[])];
  const row={profile:Number(ctx.profile),street:ctx.street.toLowerCase(),mode,relative_position:ctx.relative_position,pot_type:ctx.pot_type,preflop_role:ctx.preflop_role};
  const node=trainerSelectNode(m.levels,row,m.backoff_min_observations),counts=node.counts||{},alpha=Number(trainerState.modelB.contract?.postflop_action?.alpha_per_action)||1;
  const legalN=labels.reduce((s,a)=>s+Number(counts[a]||0),0),den=legalN+alpha*labels.length,probs=Object.create(null);
  for(const a of labels)probs[a]=(Number(counts[a]||0)+alpha)/Math.max(1e-9,den);
  if(mode==="FACING"&&!ctx.can_raise&&Object.prototype.hasOwnProperty.call(probs,"RAISE")){probs.CALL=(probs.CALL||0)+probs.RAISE;probs.RAISE=0;}
  const z=Object.values(probs).reduce((s,x)=>s+x,0)||1;for(const a of Object.keys(probs))probs[a]/=z;return probs;
}
function trainerSampleOpponentAction(ctx){const p=trainerActionProbabilities(ctx),keys=Object.keys(p);return trainerWeightedChoice(keys,keys.map(k=>p[k]));}
function trainerSizingValues(ctx){
  const m=trainerState.modelB.sizing,row={profile:Number(ctx.profile),street:ctx.street.toLowerCase(),mode:ctx.mode.toUpperCase(),action:ctx.action.toUpperCase(),pot_type:ctx.pot_type};
  const node=trainerSelectNode(m.levels,row,m.backoff_min_observations);return (node.values||[]).map(Number).filter(x=>Number.isFinite(x)&&x>0);
}
function trainerSampleSizing(ctx){const v=trainerSizingValues(ctx);return v.length?v[trainerRandomInt(v.length)]:.66;}

function trainerDraw(deck){if(!deck.length)throw new Error("Paquet vide");return deck.pop();}
function trainerCoreSeat(hand,name){return hand.names.indexOf(name);}
function trainerSyncFromCore(hand){
  const snap=hand.core.toSnapshot(),idx=name=>trainerCoreSeat(hand,name);
  hand.stacks=hand.names.map(n=>Number(snap.stacks_bb[n])||0);
  hand.folded=hand.names.map(n=>!!snap.folded[n]);
  hand.streetPaid=hand.names.map(n=>Number(snap.street_committed_bb[n])||0);
  hand.pot=Number(hand.core.pot_bb)||0;hand.currentBet=Number(snap.current_bet_bb)||0;hand.lastRaise=Number(snap.last_full_raise_bb)||1;
  hand.street=String(snap.street||"preflop");hand.boardCount=hand.runout.length;
  hand.queue=(snap.pending||[]).map(idx).filter(x=>x>=0);
  hand.raises=(snap.action_log||[]).filter(x=>x.street===hand.street&&x.action==="RAISE").length;
}
function trainerBuildHand(hints={},depth=0){
  if(depth>60)return null;
  const Game=window.PokerNlheGameState;
  if(!Game?.NoLimitHoldemState)throw new Error("NoLimitHoldemState navigateur indisponible.");
  const desiredPosition=String(hints.position||"").toUpperCase(),desiredRole=String(hints.preflopRole||"").toUpperCase(),desiredRelative=String(hints.relativePosition||"").toUpperCase();
  const dealer=trainerRandomInt(6),positions=Array.from({length:6},(_,s)=>trainerPositionForSeat(s,dealer));
  const hintedSeat=desiredPosition?positions.indexOf(desiredPosition):-1,heroSeat=hintedSeat>=0?hintedSeat:trainerRandomInt(6);
  const heroPos=positions[heroSeat],heroRank=TRAINER_PREFLOP_ORDER.indexOf(heroPos);
  let heroRole=(heroRank<5&&heroRank>0)?(trainerRandom()<.5?"PFA":"CALLER"):(heroRank===0?"PFA":"CALLER");
  if(["PFA","CALLER"].includes(desiredRole))heroRole=desiredRole;
  let candidates=positions.map((p,s)=>({p,s,r:TRAINER_PREFLOP_ORDER.indexOf(p)})).filter(x=>x.s!==heroSeat);
  if(["IP","OOP"].includes(desiredRelative))candidates=candidates.filter(x=>{
    const heroRelative=trainerPostRank(heroPos)>trainerPostRank(x.p)?"IP":"OOP";return heroRelative===desiredRelative;
  });
  if(!candidates.length||!trainerHeroRangeAvailable(heroRole,heroPos))return hints.strict?null:trainerBuildHand(hints,depth+1);
  trainerState.handNo++;
  const oppSeat=candidates[trainerRandomInt(candidates.length)].s;
  const names=Array.from({length:6},(_,s)=>s===heroSeat?TRAINER_HERO:`Villain ${s+1}`),profiles=Array(6).fill(null);
  for(let s=0;s<6;s++)if(s!==heroSeat)profiles[s]=trainerSampleProfile();
  const hole=Array.from({length:6},()=>[]),blocked=new Set(),heroCards=trainerSampleHeroRangeCards(heroRole,heroPos,blocked);
  if(!heroCards)return hints.strict?null:trainerBuildHand(hints,depth+1);
  hole[heroSeat]=heroCards;heroCards.forEach(c=>blocked.add(c));
  const deck=trainerShuffle(Array.from({length:52},(_,i)=>i).filter(c=>!blocked.has(c)));
  for(let s=0;s<6;s++)if(s!==heroSeat){hole[s]=[trainerDraw(deck),trainerDraw(deck)];}
  const used=new Set(hole.flat()),boardDeck=trainerShuffle(Array.from({length:52},(_,i)=>i).filter(c=>!used.has(c))),runout=[];
  const stacksByName=Object.fromEntries(names.map(n=>[n,100]));
  const core=new Game.NoLimitHoldemState({seats:names,button:names[dealer],stacks_bb:stacksByName,small_blind_bb:.5,big_blind_bb:1});
  const sb=names.indexOf(core.small_blind_player),bb=names.indexOf(core.big_blind_player),id=990000000000+trainerState.handNo*100;
  const lines=[`PokerStars Hand #${id}: Hold'em No Limit (0.50/1.00) - 2026/09/12 14:00:00 CET`,`Table 'Trainer 6-max' 6-max Seat #${dealer+1} is the button`];
  for(let s=0;s<6;s++)lines.push(`Seat ${s+1}: ${names[s]} (100 in chips)`);
  lines.push(`${names[sb]}: posts small blind 0.50`,`${names[bb]}: posts big blind 1.00`,"*** HOLE CARDS ***",`Dealt to ${TRAINER_HERO} [${hole[heroSeat].map(cardCode).join(" ")}]`);
  const hand={id,dealerSeat:dealer,heroSeat,activeOppSeat:oppSeat,pfaSeat:null,callerSeat:null,heroRole,oppRole:heroRole==="PFA"?"CALLER":"PFA",
    positions,names,profiles,hole,boardDeck,runout,core,stacks:Array(6).fill(100),folded:Array(6).fill(false),lastAction:Array(6).fill(""),
    pot:0,street:"preflop",boardCount:0,streetPaid:Array(6).fill(0),currentBet:1,lastRaise:1,raises:0,queue:[],preflopHistory:[],preflopRaiseLevel:0,
    historyLines:lines,ended:false,winner:"",showdown:false,awaitingHero:false,decisionNo:0,preview:!!hints.preview};
  trainerSyncFromCore(hand);return hand;
}

function trainerPostRank(pos){return TRAINER_POSTFLOP_ORDER.indexOf(pos);}
function trainerStartStreet(hand,street,appendMarker=true){
  const target=String(street||"").toLowerCase(),current=String(hand.core.street||"").toLowerCase();
  const expected={preflop:"flop",flop:"turn",turn:"river"}[current];
  if(target!==expected)throw new Error(`Transition de street invalide : ${current} -> ${target}`);
  const drawCount=current==="preflop"?3:1,cards=Array.from({length:drawCount},()=>trainerDraw(hand.boardDeck));
  hand.runout.push(...cards);hand.core.advanceStreet(cards.map(cardCode));trainerSyncFromCore(hand);
  if(!appendMarker)return;
  if(target==="flop")hand.historyLines.push(`*** FLOP *** [${hand.runout.slice(0,3).map(cardCode).join(" ")}]`);
  else if(target==="turn")hand.historyLines.push(`*** TURN *** [${hand.runout.slice(0,3).map(cardCode).join(" ")}] [${cardCode(hand.runout[3])}]`);
  else if(target==="river")hand.historyLines.push(`*** RIVER *** [${hand.runout.slice(0,4).map(cardCode).join(" ")}] [${cardCode(hand.runout[4])}]`);
}
function trainerToCall(hand,seat){return Math.min(Number(hand.stacks[seat]||0),Math.max(0,Number(hand.currentBet)-Number(hand.streetPaid[seat]||0)));}
function trainerOther(hand,seat){return hand.names.map((_,s)=>s).find(s=>s!==seat&&!hand.folded[s])??hand.heroSeat;}
function trainerActionLine(hand,seat,kind,cost=0,target=null,raiseInc=null){
  const name=hand.names[seat],allin=cost>=hand.stacks[seat]-1e-8&&cost>0?" and is all-in":"";
  if(kind==="FOLD")return `${name}: folds`;
  if(kind==="CHECK")return `${name}: checks`;
  if(kind==="CALL")return `${name}: calls ${trainerNum(cost)}${allin}`;
  if(kind==="BET")return `${name}: bets ${trainerNum(cost)}${allin}`;
  return `${name}: raises ${trainerNum(raiseInc)} to ${trainerNum(target)}${allin}`;
}
function trainerCoreLiveSeats(hand){return hand.names.map((_,s)=>s).filter(s=>!hand.folded[s]);}
function trainerPreflopAlias(hand,coreAction,allIn=false){
  if(coreAction==="CALL")return hand.preflopRaiseLevel>0?"CALL":"LIMP";
  if(coreAction==="RAISE")return allIn?"JAM":"RAISE";
  return coreAction;
}
function trainerApplyAction(hand,seat,kind,requestedCost=0){
  kind=String(kind||"").toUpperCase();
  const actor=hand.names[seat],view=hand.core.legalView(actor),paid=Number(view.actor_street_contribution_bb)||0,toCall=Number(view.to_call_bb)||0,remaining=Number(view.actor_remaining_bb)||0;
  const beforeStreet=hand.street,beforePrice=Number(view.current_price_bb)||0;
  let coreAction=kind,lineKind=kind,cost=0,target=null,raiseInc=0;
  if(kind==="BET")coreAction="RAISE";
  if(kind==="CHECK"&&toCall>1e-8){coreAction="CALL";lineKind="CALL";}
  if(coreAction==="CALL"){cost=Math.min(toCall,remaining);lineKind="CALL";}
  else if(coreAction==="RAISE"){
    const minTarget=Number(view.min_raise_to_bb),maxTarget=Number(view.max_raise_to_bb);
    const fallback=Math.max(Number.isFinite(minTarget)?minTarget:beforePrice+1,paid+toCall+Math.max(hand.lastRaise,1));
    target=Math.min(maxTarget,Math.max(Number.isFinite(minTarget)?minTarget:0,paid+(Number(requestedCost)||fallback-paid)));
    if(!(target>beforePrice+1e-8)){coreAction=toCall>1e-8?"CALL":"CHECK";lineKind=coreAction;cost=coreAction==="CALL"?Math.min(toCall,remaining):0;}
    else{cost=target-paid;raiseInc=target-beforePrice;if(kind!=="BET")lineKind="RAISE";}
  }
  const allIn=cost>=remaining-1e-8&&cost>0;
  const line=trainerActionLine(hand,seat,lineKind,cost,target,raiseInc);
  if(coreAction==="RAISE")hand.core.applyAction(actor,"RAISE",{target_total_bb:target});else hand.core.applyAction(actor,coreAction);
  hand.historyLines.push(line);
  if(beforeStreet==="preflop"){
    const alias=trainerPreflopAlias(hand,coreAction,allIn);
    hand.preflopHistory.push({position:hand.positions[seat],action:alias});
    if(coreAction==="RAISE")hand.preflopRaiseLevel++;
  }
  hand.lastAction[seat]=coreAction==="RAISE"?`RAISE à ${trainerFmtBB(target)}`:coreAction==="CALL"?`CALL ${trainerFmtBB(cost)}`:coreAction;
  trainerSyncFromCore(hand);
  const live=trainerCoreLiveSeats(hand);if(live.length===1)trainerEndHand(hand,live[0],false);
}
function trainerPreflopContext(hand,seat){
  const contract=window.PokerPreflopContract,snap=hand.core.toSnapshot(),view=hand.core.legalView(hand.names[seat]),tableSize=hand.names.length;
  const live=[],allIn=[],contrib={},stacks={};
  for(let s=0;s<hand.names.length;s++){
    const pos=contract.normalizePosition(hand.positions[s],tableSize),name=hand.names[s];
    if(!snap.folded[name])live.push(pos);if(snap.all_in[name])allIn.push(pos);
    contrib[pos]=Number(snap.street_committed_bb[name])||0;stacks[pos]=(Number(snap.stacks_bb[name])||0)+(Number(snap.street_committed_bb[name])||0);
  }
  return contract.buildContext({table_size:tableSize,actor_position:hand.positions[seat],live_positions:live,all_in_positions:allIn,
    history:hand.preflopHistory,raise_level:hand.preflopRaiseLevel,contribution_bb_by_position:contrib,stack_bb_by_position:stacks,
    pot_before_bb:hand.core.pot_bb,current_price_bb:view.current_price_bb,min_raise_to_bb:view.min_raise_to_bb,raise_reopened:view.raise_reopened,
    pending_positions:view.remaining_to_act.map(n=>hand.positions[trainerCoreSeat(hand,n)])});
}
function trainerPreflopOpponentAct(hand,seat){
  const ctx=trainerPreflopContext(hand,seat),view=hand.core.legalView(hand.names[seat]);
  const match=typeof findClosestPopulationNode==="function"?findClosestPopulationNode({...ctx,action:"",actor_start_stack_bb:(Number(view.actor_remaining_bb)||0)+(Number(view.actor_street_contribution_bb)||0),pot_before_bb:hand.core.pot_bb,action_add_bb:0}):null;
  const raw=match?.node?.population_model?.frequencies||{},legal=new Set(ctx.legal_actions||[]),actions=[],weights=[];
  for(const [a,w] of Object.entries(raw)){if(legal.has(a)&&Number(w)>0){actions.push(a);weights.push(Number(w));}}
  let sampled=actions.length?trainerWeightedChoice(actions,weights):(view.to_call_bb>1e-8?"FOLD":"CHECK");
  if(sampled==="LIMP")sampled="CALL";
  if(sampled==="JAM"){
    const maxTarget=Number(view.max_raise_to_bb),cost=maxTarget-Number(view.actor_street_contribution_bb||0);trainerApplyAction(hand,seat,"RAISE",cost);return;
  }
  if(sampled==="RAISE"){
    const stats=match?.node?.continuous_population?.action_add_bb||match?.node?.continuous_all?.action_add_bb||{};
    const empirical=Number(stats.median),minTarget=Number(view.min_raise_to_bb),maxTarget=Number(view.max_raise_to_bb),paid=Number(view.actor_street_contribution_bb)||0;
    const target=Math.min(maxTarget,Math.max(Number.isFinite(minTarget)?minTarget:0,Number.isFinite(empirical)&&empirical>0?paid+empirical:(Number.isFinite(minTarget)?minTarget:maxTarget)));
    trainerApplyAction(hand,seat,"RAISE",Math.max(0,target-paid));return;
  }
  trainerApplyAction(hand,seat,sampled);
}
function trainerPotType(hand){return hand.preflopRaiseLevel<=0?"LIMPED":hand.preflopRaiseLevel===1?"SRP":hand.preflopRaiseLevel===2?"3BP":"4BP_PLUS";}
function trainerFinalizePreflopRoles(hand){
  const raises=(hand.core.action_log||[]).filter(x=>x.street==="preflop"&&x.action==="RAISE");
  if(raises.length){hand.pfaSeat=trainerCoreSeat(hand,raises[raises.length-1].player);}
  const live=trainerCoreLiveSeats(hand),others=live.filter(s=>s!==hand.pfaSeat);
  hand.callerSeat=others[0]??null;hand.activeOppSeat=live.find(s=>s!==hand.heroSeat)??hand.activeOppSeat;
  hand.heroRole=hand.heroSeat===hand.pfaSeat?"PFA":(hand.preflopRaiseLevel===0&&hand.positions[hand.heroSeat]==="BB"?"BB_CHECK":"CALLER");
  hand.oppRole=hand.activeOppSeat===hand.pfaSeat?"PFA":(hand.preflopRaiseLevel===0&&hand.positions[hand.activeOppSeat]==="BB"?"BB_CHECK":"CALLER");
}
function trainerOpponentContext(hand,seat){
  const toCall=trainerToCall(hand,seat),relative=trainerPostRank(hand.positions[seat])>trainerPostRank(hand.positions[hand.heroSeat])?"IP":"OOP";
  const view=hand.core.legalView(hand.names[seat]);
  return {profile:hand.profiles[seat],street:hand.street,mode:toCall>1e-8?"FACING":"FREE",relative_position:relative,pot_type:trainerPotType(hand),preflop_role:seat===hand.pfaSeat?"PFA":"CALLER",can_raise:view.legal_actions.includes("RAISE")};
}
function trainerOpponentAct(hand,seat){
  if(hand.street==="preflop"){trainerPreflopOpponentAct(hand,seat);return;}
  const ctx=trainerOpponentContext(hand,seat),toCall=trainerToCall(hand,seat),action=trainerSampleOpponentAction(ctx);
  if(action==="FOLD")trainerApplyAction(hand,seat,"FOLD");
  else if(action==="CHECK")trainerApplyAction(hand,seat,"CHECK");
  else if(action==="CALL")trainerApplyAction(hand,seat,"CALL");
  else{
    const ratio=trainerSampleSizing({...ctx,action:ctx.mode==="FACING"?"RAISE":"BET"}),pot0=hand.pot;
    let cost=Math.max(1,ratio*pot0);if(ctx.mode==="FACING")cost=Math.max(cost,toCall+hand.lastRaise);
    trainerApplyAction(hand,seat,ctx.mode==="FACING"?"RAISE":"BET",cost);
  }
}
function trainerEndHand(hand,winnerSeat,showdown){
  hand.ended=true;hand.queue=[];hand.awaitingHero=false;hand.showdown=!!showdown;hand.winner=winnerSeat===null?"Partage":hand.names[winnerSeat];
  if(!hand.preview)trainerState.session.hands++;
}
function trainerShowdown(hand){
  const live=trainerCoreLiveSeats(hand);if(!live.length){trainerEndHand(hand,null,true);return;}
  const scores=live.map(s=>({s,score:handScore([...hand.hole[s],...hand.runout])})),best=Math.max(...scores.map(x=>x.score)),winners=scores.filter(x=>x.score===best);
  trainerEndHand(hand,winners.length===1?winners[0].s:null,true);
}
function trainerAdvanceStreetOrShowdown(hand){
  const live=trainerCoreLiveSeats(hand);if(live.length<=1){trainerEndHand(hand,live[0]??null,false);return;}
  if(hand.street==="preflop"){trainerFinalizePreflopRoles(hand);trainerStartStreet(hand,"flop",true);return;}
  if(hand.street==="flop"){trainerStartStreet(hand,"turn",true);return;}
  if(hand.street==="turn"){trainerStartStreet(hand,"river",true);return;}
  trainerShowdown(hand);
}

function trainerHypotheticalCost(hand,lineKind,cost){return ["CALL","BET","RAISE"].includes(lineKind)?Math.max(0,Number(cost)||0):0;}
function trainerBuildReviewHH(hand,actionLine,actionKind,cost=0){
  trainerState.evalNo++;const evalId=hand.id+trainerState.evalNo,lines=[...hand.historyLines,actionLine],gross=Math.max(.01,hand.pot+trainerHypotheticalCost(hand,actionKind,cost)),rake=Math.min(13.925,.055*gross);
  lines.push("*** SUMMARY ***",`Total pot ${trainerNum(gross)} | Rake ${trainerNum(rake)}`);
  lines[0]=lines[0].replace(/Hand #\d+/,`Hand #${evalId}`);return lines.join("\n")+"\n";
}
async function trainerWaitFor(fn,timeout=30000){const start=Date.now();while(!fn()){if(Date.now()-start>timeout)throw new Error("Timeout du calcul de recommandation.");await trainerSleep(40);}}
function trainerReviewCacheClone(value){return JSON.parse(JSON.stringify(value));}
function trainerReviewCacheNormalize(text){return String(text||"").replace(/Hand #\d+/,"Hand #<trainer>");}
function trainerReviewCacheEnsureModelIdentity(){
  if(trainerReviewCache.preModel===state.populationModel&&trainerReviewCache.postModel===state.postflopModel)return;
  trainerReviewCache.entries.clear();trainerReviewCache.preModel=state.populationModel;trainerReviewCache.postModel=state.postflopModel;
}
function trainerReviewCacheGet(text){
  trainerReviewCacheEnsureModelIdentity();const key=trainerReviewCacheNormalize(text);
  if(!trainerReviewCache.entries.has(key)){trainerReviewCache.misses++;trainerState.perf.cacheMisses++;return null;}
  const value=trainerReviewCache.entries.get(key);trainerReviewCache.entries.delete(key);trainerReviewCache.entries.set(key,value);
  trainerReviewCache.hits++;trainerState.perf.cacheHits++;return trainerReviewCacheClone(value);
}
function trainerReviewCacheSet(text,value){
  trainerReviewCacheEnsureModelIdentity();const key=trainerReviewCacheNormalize(text),copy=trainerReviewCacheClone(value);
  trainerReviewCache.entries.delete(key);trainerReviewCache.entries.set(key,copy);
  while(trainerReviewCache.entries.size>TRAINER_REVIEW_CACHE_MAX){const oldest=trainerReviewCache.entries.keys().next().value;trainerReviewCache.entries.delete(oldest);trainerReviewCache.evictions++;}
}
async function trainerTimedReviewText(text){
  const started=performance.now(),cached=trainerReviewCacheGet(text);
  if(cached){const ms=performance.now()-started;trainerState.perf.lastMs=ms;trainerState.perf.totalMs+=ms;return cached;}
  trainerState.perf.evaluations++;
  try{const result=await trainerReviewText(text);trainerReviewCacheSet(text,result);return result;}
  finally{const ms=performance.now()-started;trainerState.perf.lastMs=ms;trainerState.perf.totalMs+=ms;}
}
async function trainerReviewText(text){
  if(!state.reviewBatchBusy||state.reviewBatchRun?.kind!=="explicit")cancelObsoleteReviewComputation();
  await trainerWaitFor(()=>!state.reviewBatchBusy,30000);
  const hand=parsePokerStarsHand(text,"trainer");
  if(!hand)throw new Error("Le moteur n'a pas pu parser le spot Training.");
  const saved={hhHands:state.hhHands,selectedHand:state.selectedHand,hhMode:state.hhMode,replaySteps:state.replaySteps,replayIndex:state.replayIndex,popTrace:state.populationTraceCache,popRange:state.populationRangeCache,postTrace:state.postflopTraceCache,postRange:state.postflopRangeCache,actionEq:state.actionEquityCache,seatEq:state.seatEquityCache,preflopRuntime:state.preflopRuntimeDecisionCache};
  const key=String(hand.id);
  try{
    state.populationTraceCache=Object.create(null);state.populationRangeCache=Object.create(null);state.postflopTraceCache=Object.create(null);state.postflopRangeCache=Object.create(null);state.actionEquityCache=Object.create(null);state.seatEquityCache=Object.create(null);state.preflopRuntimeDecisionCache=Object.create(null);
    state.replaySteps=[];state.replayIndex=0;state.hhHands=[hand];state.selectedHand=hand;state.hhMode=true;delete state.reviewScores[key];
    const steps=makeReplaySteps(hand),lastHeroStep=steps.map((step,i)=>step.activePlayer===hand.heroName&&isAnalyzableDecisionAction(step)?i:-1).filter(i=>i>=0).pop();
    const plan=buildReviewBatchPlan(hand,lastHeroStep??-1);plan.actions=plan.actions.filter(a=>a.actor===hand.heroName).slice(-1);if(!plan.actions.length)throw new Error("Aucune décision Hero analysable dans ce spot.");
    runReviewBatchPlan(plan,{kind:"explicit"});
    await trainerWaitFor(()=>!state.reviewBatchBusy&&!!state.reviewScores?.[key],45000);
    const score=state.reviewScores[key],detail=score?.details?.[score.details.length-1];if(!detail)throw new Error("Aucun verdict produit par le moteur.");return JSON.parse(JSON.stringify(detail));
  }finally{
    delete state.reviewScores[key];state.hhHands=saved.hhHands;state.selectedHand=saved.selectedHand;state.hhMode=saved.hhMode;state.replaySteps=saved.replaySteps;state.replayIndex=saved.replayIndex;state.populationTraceCache=saved.popTrace;state.populationRangeCache=saved.popRange;state.postflopTraceCache=saved.postTrace;state.postflopRangeCache=saved.postRange;state.actionEquityCache=saved.actionEq;state.seatEquityCache=saved.seatEq;state.preflopRuntimeDecisionCache=saved.preflopRuntime;
  }
}
function trainerPreflopRuntimeInput(hand){
  const runtime=window.PokerPreflopRuntime;
  if(!runtime)throw new Error("PokerPreflopRuntime indisponible.");
  const hero=hand.heroSeat,ctx=trainerPreflopContext(hand,hero),view=hand.core.legalView(hand.names[hero]);
  return {runtime,ctx,view,public_state:{snapshot:hand.core.toSnapshot(),legal_view:view}};
}
function trainerPreflopScopeCovered(ctx,view){
  const family=String(ctx?.family||"").toUpperCase();
  return Number(view?.to_call_bb)>1e-8&&!["UNOPENED","VS_LIMPERS"].includes(family);
}
function trainerPreflopPlayedAction(actual,view){
  if(!actual)return null;
  const action=String(actual.kind||"").toUpperCase();
  if(action==="FOLD")return {action:"FOLD"};
  if(action==="CALL")return {action:"CALL",target_total_bb:Number(view.current_price_bb)};
  if(action==="RAISE")return {action:"RAISE",target_total_bb:Number(actual.target)};
  if(action==="CHECK")return {action:"CHECK"};
  if(action==="BET")return {action:"RAISE",target_total_bb:Number(actual.target)};
  return {action};
}
/* #393 T5 — Training preflop labels (#393 T2 module).
   The shared `poker-analysis-state/v1` module is the single source of truth for
   the user-facing preflop state. The historical `SPOT_NON_COUVERT` /
   `ACTIVE_REFERENCE_SCOPE_UNSUPPORTED` codes stay as machine-readable reason
   codes, while the displayed primary label is always the taxonomy state. The
   detailed reason codes and the separated technical dimensions are only emitted
   by `trainerAnalysisDimensionsHtml` inside the secondary feedback panel.
   The deliberate v1 flop-only Hero-decision boundary (#206) is unchanged: this
   only relabels the preflop reference surface. */
function trainerAnalysisModule(){
  const Module=window.PokerAnalysisState;
  return Module&&typeof Module.mapAnalysisState==="function"?Module:null;
}
function trainerTaxonomyLabel(state){
  const key=String(state||"").trim().toUpperCase();
  if(!key)return "";
  const Inbox=window.PokerReviewInbox;
  if(Inbox){
    if(typeof Inbox.analysisStateLabel==="function"){
      const label=Inbox.analysisStateLabel(key);
      // Only a real user-facing label is accepted: the primary label is the
      // taxonomy state, never the raw technical enum code echoed back.
      if(label&&String(label).trim().toUpperCase()!==key)return String(label).trim();
    }
    const labels=Inbox.ANALYSIS_STATE_LABELS;
    if(labels&&labels[key])return labels[key];
  }
  return "";
}
// The canonical preflop decision already carries the shared dimensions
// (`coverage_state`, `reason_codes`, `recommendation_admissibility`,
// `ev_comparable`): feed them to the module untouched.
function trainerPreflopAnalysis(decision){
  const Module=trainerAnalysisModule();
  if(!Module||!decision)return null;
  return Module.mapAnalysisState(decision);
}
// Primary taxonomy view. Rule D6: the EV/recommendation fields are only exposed
// when the module reports both `recommendation_admissibility.admissible` and
// `ev_comparability.comparable`. Any other combination stays taxonomy-labelled.
function trainerPreflopDecisionView(decision){
  const analysis=trainerPreflopAnalysis(decision);
  const admissible=analysis?.recommendation_admissibility?.admissible===true;
  const comparable=analysis?.ev_comparability?.comparable===true;
  return {
    analysis,
    taxonomy_state:analysis?.state||null,
    taxonomy_label:trainerTaxonomyLabel(analysis?.state||""),
    admissible,ev_comparable:comparable,show_ev:admissible&&comparable
  };
}
// Secondary/technical view: reason codes and the separated dimensions are only
// rendered here, never as a primary label.
function trainerAnalysisDimensionsHtml(analysis){
  if(!analysis)return "";
  const admissibility=analysis.recommendation_admissibility||{},comparability=analysis.ev_comparability||{},support=analysis.statistical_support||{},error=analysis.error||{};
  const codes=(analysis.reason_codes||[]).join(", ")||"—";
  const errorText=error.type?` · erreur ${escapeHtml(error.type)} (retryable ${escapeHtml(String(error.retryable))})`:"";
  return `<div class="trainer-feedback-body" data-analysis-detail="1">Détails techniques · état ${escapeHtml(analysis.state)} · raisons ${escapeHtml(codes)} · support ${Number(support.observations)||0} obs / ${Number(support.distinct_hands)||0} mains · modèle ${escapeHtml(analysis.model_support_status||"—")} · calcul ${escapeHtml(analysis.computational_status||"—")} · EV comparable ${escapeHtml(String(comparability.comparable))}${comparability.reason?` (${escapeHtml(comparability.reason)})`:""} · recommandation ${escapeHtml(String(admissibility.admissible))}${admissibility.status?` (${escapeHtml(admissibility.status)})`:""} · posterior ${escapeHtml(analysis.posterior_availability||"—")}${errorText}.</div>`;
}
function trainerPreflopTaxonomyLabel(decision){
  const label=trainerPreflopDecisionView(decision).taxonomy_label;
  return label||"Spot non supporté";
}
function trainerDetailFromPreflopDecision(decision,referenceCallEV=null){
  // Rule D6: `view.show_ev` (admissible && comparable) is the single canonical
  // gate. When it is closed the detail carries no usable Hero recommendation:
  // bestEV/played EV are NaN, bestLabel degrades to the shared taxonomy label,
  // the recommended sizing is null and every ΔEV needing the recommended
  // reference stays 0. No local covered/comparable recombination is used here.
  const view=trainerPreflopDecisionView(decision);
  const bestEV=Number(decision?.recommended_ev_bb),playedEV=Number(decision?.played_ev_bb);
  const loss=view.show_ev&&Number.isFinite(bestEV)&&Number.isFinite(playedEV)?Math.max(0,bestEV-playedEV):0;
  return {
    preflopDecision:decision,referenceCallEV:Number.isFinite(Number(referenceCallEV))?Number(referenceCallEV):null,
    taxonomy_state:view.taxonomy_state,taxonomy_label:view.taxonomy_label,analysis:view.analysis,
    bestLabel:view.show_ev?String(decision.recommended_action||"—"):(view.taxonomy_label||"Spot non supporté"),
    bestCostBB:view.show_ev&&Number.isFinite(Number(decision.incremental_cost_bb))?Number(decision.incremental_cost_bb):null,
    bestEV:view.show_ev&&Number.isFinite(bestEV)?bestEV:NaN,chosenEV:view.show_ev&&Number.isFinite(playedEV)?playedEV:NaN,
    lossBB:loss,rawLossBB:loss,withinNoise:false,comparable:view.ev_comparable,showEV:view.show_ev,unsupported:!view.admissible
  };
}
async function trainerComputePreflopReference(hand,actual=null,guide=null){
  const started=performance.now(),{runtime,ctx,view,public_state}=trainerPreflopRuntimeInput(hand);
  const common={public_state,context_id:ctx.context_id,preflop_context:ctx,hero_position:ctx.actor_position,
    hand_id:String(hand.id),decision_id:`trainer-preflop:${hand.id}:${hand.decisionNo}`,
    played_action:trainerPreflopPlayedAction(actual,view)};
  if(!trainerPreflopScopeCovered(ctx,view)){
    const decision=runtime.surfaceBundle(runtime.buildUnsupported({...common,reason:String(ctx.family)==="VS_LIMPERS"?"SPOT_NON_COUVERT":"ACTIVE_REFERENCE_SCOPE_UNSUPPORTED"})).trainer;
    runtime.assertRetainedReference(decision);
    const ms=performance.now()-started;trainerState.perf.lastMs=ms;trainerState.perf.totalMs+=ms;
    return trainerDetailFromPreflopDecision(decision,null);
  }
  let callEV=Number(guide?.referenceCallEV);
  if(Number.isFinite(callEV)){trainerState.perf.reused++;}
  else{
    const callCost=Number(view.to_call_bb),line=trainerActionLine(hand,hand.heroSeat,"CALL",callCost);
    const reviewed=await trainerTimedReviewText(trainerBuildReviewHH(hand,line,"CALL",callCost));
    const source=reviewed?.preflopDecision;
    const callAlt=(source?.alternatives||[]).find(a=>String(a.action).toUpperCase()==="CALL");
    callEV=Number(callAlt?.ev_bb);
    if(!Number.isFinite(callEV))callEV=Number(reviewed?.chosenEV);
    if(!Number.isFinite(callEV))throw new Error("EV CALL de la référence active indisponible.");
  }
  const decision=runtime.surfaceBundle(runtime.buildCallFold({...common,call_ev_bb:callEV,
    hero_hand_class:cardsToNotation(hand.hole[hand.heroSeat]),samples:Number(trialsSelect?.value||0),support_source:"active-reference-call-fold"})).trainer;
  runtime.assertRetainedReference(decision);
  return trainerDetailFromPreflopDecision(decision,callEV);
}
function trainerPlaceholderLine(hand){
  const s=hand.heroSeat,toCall=trainerToCall(hand,s);
  return {kind:toCall>1e-8?"CALL":"CHECK",line:trainerActionLine(hand,s,toCall>1e-8?"CALL":"CHECK",toCall>1e-8?toCall:0),cost:toCall>1e-8?toCall:0};
}
async function trainerComputeRecommendation(){
  const hand=trainerState.hand;if(!hand||hand.ended||!hand.awaitingHero)return;
  trainerState.busy=true;trainerState.recommendation=null;trainerRenderStatus("Calcul de la recommandation…","busy");trainerRender();
  try{
    const detail=hand.street==="preflop"
      ?await trainerComputePreflopReference(hand)
      :await (async()=>{const ph=trainerPlaceholderLine(hand);return trainerTimedReviewText(trainerBuildReviewHH(hand,ph.line,ph.kind,ph.cost));})();
    trainerState.recommendation=detail;
    const stateText=detail?.preflopDecision&&!trainerPreflopDecisionView(detail.preflopDecision).show_ev?` · ${trainerPreflopTaxonomyLabel(detail.preflopDecision)}`:"";
    trainerRenderStatus(`À vous de jouer${stateText} · calcul ${trainerState.perf.lastMs.toFixed(0)} ms.`);
  }
  catch(err){trainerRenderStatus(`Recommandation indisponible : ${err.message}`,"error");trainerState.recommendation={error:err.message};}
  finally{trainerState.busy=false;trainerRender();}
}
function trainerActualLine(hand,kind,cost){
  const s=hand.heroSeat,paid=hand.streetPaid[s],toCall=trainerToCall(hand,s),remaining=hand.stacks[s];kind=kind.toUpperCase();
  if(kind==="FOLD")return {line:trainerActionLine(hand,s,"FOLD"),kind,cost:0,target:null};
  if(kind==="CHECK")return {line:trainerActionLine(hand,s,"CHECK"),kind,cost:0,target:paid};
  if(kind==="CALL"){const c=Math.min(toCall,remaining);return {line:trainerActionLine(hand,s,"CALL",c),kind,cost:c,target:paid+c};}
  if(kind==="BET"){const c=trainerClamp(Number(cost)||1,Math.min(1,remaining),remaining);return {line:trainerActionLine(hand,s,"BET",c,paid+c,c),kind,cost:c,target:paid+c};}
  const minTarget=hand.currentBet+Math.max(hand.lastRaise,1),target=Math.min(paid+remaining,Math.max(minTarget,paid+(Number(cost)||toCall+hand.lastRaise))),c=target-paid,inc=target-hand.currentBet;return {line:trainerActionLine(hand,s,"RAISE",c,target,inc),kind:"RAISE",cost:c,target};
}
function trainerDecisionClass(detail){
  if(detail?.preflopDecision&&!trainerPreflopDecisionView(detail.preflopDecision).show_ev)return "unknown";
  const rawLoss=Math.max(0,Number(detail?.rawLossBB??detail?.lossBB)||0),effectiveLoss=Math.max(0,Number(detail?.lossBB)||0);
  const quality=TrainerActionSizingEV.qualityFromEV({lossEVBB:rawLoss,effectiveLossEVBB:effectiveLoss,withinNoise:!!detail?.withinNoise});
  return quality.key==="unknown"?"close":quality.key;
}
function trainerRecordDecision(detail,playedKind,playedCost){
  const hand=trainerState.hand,loss=Math.max(0,Number(detail?.lossBB)||0),cls=trainerDecisionClass(detail);
  // One canonical derivation for the whole row. A preflop detail is gated by
  // D6 (`view.show_ev`); when the gate is closed the row carries no Hero
  // recommendation payload (no best label, sizing or best/chosen EV).
  const view=detail?.preflopDecision?trainerPreflopDecisionView(detail.preflopDecision):null,showEV=view?view.show_ev:true;
  const row={handNo:trainerState.handNo,street:hand.street,position:hand.positions[hand.heroSeat],played:playedKind,cost:playedCost,bestLabel:showEV?(detail?.bestLabel||"—"):"—",bestCostBB:showEV&&Number.isFinite(Number(detail?.bestCostBB))&&detail?.bestCostBB!=null?Number(detail.bestCostBB):null,bestEV:showEV?Number(detail?.bestEV):NaN,chosenEV:showEV?Number(detail?.chosenEV):NaN,lossBB:loss,withinNoise:!!detail?.withinNoise,cls,comparable:view?!!view.ev_comparable:true,covered:view?view.admissible:true,analysis_state:detail?.taxonomy_state||null,analysis_reason_codes:Array.isArray(detail?.analysis?.reason_codes)?detail.analysis.reason_codes.slice():[]};
  const s=trainerState.session;s.decisions++;s.lossBB+=loss;if(cls==="good")s.good++;else if(cls==="close")s.close++;else if(cls==="poor")s.poor++;
  const key=`${row.position} · ${row.street}`;const b=s.breakdown[key]||(s.breakdown[key]={n:0,loss:0});b.n++;b.loss+=loss;trainerState.testLog.unshift(row);return row;
}
function trainerDecisionCanonical(detail,row){
  if(!detail||!row)return null;
  const source=detail?.decisionSummary?.schema==="decision-summary/v1"?JSON.parse(JSON.stringify(detail.decisionSummary)):null;
  const chosenEV=Number(detail.chosenEV),bestEV=Number(detail.bestEV),bestCost=detail.bestCostBB!=null?Number(detail.bestCostBB):NaN,playedCost=Number(row.cost);
  const family=x=>{const s=String(x||"").toUpperCase();if(s.includes("FOLD"))return "FOLD";if(s.includes("CHECK"))return "CHECK";if(s.includes("CALL"))return "CALL";if(s.includes("RAISE")||s.includes("JAM"))return "RAISE";if(s.includes("BET"))return "BET";return s;};
  const playedLabel=String(row.played||"—").toUpperCase(),recommendedLabel=String(detail.bestLabel||source?.recommended?.label||"—");
  const sizing=(label,cost)=>{const k=family(label);if(k==="FOLD"||k==="CHECK")return "0 BB";return Number.isFinite(cost)?trainerFmtBB(cost):"—";};
  const played={label:playedLabel,sizing:sizing(playedLabel,playedCost),costBB:Number.isFinite(playedCost)?playedCost:null,targetStreetBB:null,evBB:Number.isFinite(chosenEV)?chosenEV:null,chosen:true,recommended:false};
  const recommended={label:recommendedLabel,sizing:Number.isFinite(bestCost)?sizing(recommendedLabel,bestCost):(source?.recommended?.sizing||"—"),costBB:Number.isFinite(bestCost)?bestCost:(source?.recommended?.costBB??null),targetStreetBB:source?.recommended?.targetStreetBB??null,evBB:Number.isFinite(bestEV)?bestEV:(source?.recommended?.evBB??null),chosen:false,recommended:true};
  const alternatives=(source?.alternatives||[]).map(a=>({...a,chosen:false,recommended:false}));
  const same=(a,b)=>family(a?.label)===family(b?.label)&&(!["BET","RAISE"].includes(family(b?.label))||!Number.isFinite(Number(a?.costBB))||!Number.isFinite(Number(b?.costBB))||Math.abs(Number(a.costBB)-Number(b.costBB))<=.05);
  const pi=alternatives.findIndex(a=>same(a,played));if(pi>=0)alternatives[pi]={...alternatives[pi],...played};else alternatives.push(played);
  const ri=alternatives.findIndex(a=>same(a,recommended));if(ri>=0)alternatives[ri]={...alternatives[ri],...recommended,recommended:true,chosen:alternatives[ri].chosen||same(recommended,played)};else alternatives.push(recommended);
  alternatives.sort((a,b)=>(Number.isFinite(Number(b.evBB))?Number(b.evBB):-Infinity)-(Number.isFinite(Number(a.evBB))?Number(a.evBB):-Infinity));
  const delta=Number.isFinite(chosenEV)&&Number.isFinite(bestEV)?chosenEV-bestEV:-Math.max(0,Number(row.lossBB)||0);
  return {schema:"decision-summary/v1",played,recommended,deltaEVBB:delta,lossEVBB:Math.max(0,-delta),effectiveLossEVBB:Math.max(0,Number(row.lossBB)||0),withinNoise:!!row.withinNoise,score:Number(source?.score),alternatives};
}
function trainerRecommendationKind(hand,rec){
  if(!hand||!rec||rec.error)return "";
  if(rec.preflopDecision){
    // The guided action target is gated by the canonical admissibility
    // dimension (`view.admissible`, the admissibility half of D6). The EV and
    // recommended-sizing exposure stays gated by `view.show_ev` in the render
    // paths; no local covered/ev_comparable rule is recombined here.
    if(!trainerPreflopDecisionView(rec.preflopDecision).admissible)return "";
    const action=String(rec.preflopDecision.recommended_action||"").toUpperCase();
    return action==="LIMP"?"CALL":action;
  }
  const label=String(rec.bestLabel||"").trim().toUpperCase();
  if(label.startsWith("FOLD"))return "FOLD";
  if(label.startsWith("CHECK"))return "CHECK";
  if(label.startsWith("CALL"))return "CALL";
  if(label.startsWith("BET"))return "BET";
  if(label.startsWith("RAISE"))return "RAISE";
  const cost=Number(rec.bestCostBB);
  if(Number.isFinite(cost)&&cost>1e-8)return trainerToCall(hand,hand.heroSeat)>1e-8?"RAISE":"BET";
  return "";
}
function trainerRecommendationMatchesAction(rec,actual,hand=trainerState.hand){
  if(!rec||rec.error||!actual||!hand)return false;
  const kind=String(actual.kind||"").toUpperCase(),recommended=trainerRecommendationKind(hand,rec);
  if(!recommended||recommended!==kind)return false;
  if(!["BET","RAISE"].includes(kind))return true;
  const bestCost=Number(rec.bestCostBB),playedCost=Number(actual.cost);
  return Number.isFinite(bestCost)&&Number.isFinite(playedCost)&&Math.abs(bestCost-playedCost)<=0.05;
}
function trainerGuideAnchoredDetail(guide,played){
  const d=JSON.parse(JSON.stringify(played||{})),bestEV=Number(guide?.bestEV),chosenEV=Number(d.chosenEV);
  d.bestLabel=guide?.bestLabel;d.bestCostBB=guide?.bestCostBB;d.bestEV=bestEV;
  const loss=Number.isFinite(bestEV)&&Number.isFinite(chosenEV)?Math.max(0,bestEV-chosenEV):Math.max(0,Number(d.lossBB)||0);
  d.rawLossBB=loss;d.lossBB=loss;d.withinNoise=!!played?.withinNoise;return d;
}
function trainerGuidedClickCost(kind){
  const raw=trainerSizingValue(),rec=trainerState.recommendation,hand=trainerState.hand,k=String(kind||"").toUpperCase();
  if(trainerState.mode!=="guided"||trainerState.sizingTouched||!rec||rec.error||!["BET","RAISE"].includes(k))return raw;
  if(trainerRecommendationKind(hand,rec)!==k)return raw;
  // The recommended sizing is a D6 Hero field: never reuse it when the gate is
  // closed (e.g. admissible but not comparable). Fall back to the raw input.
  if(rec.preflopDecision&&!trainerPreflopDecisionView(rec.preflopDecision).show_ev)return raw;
  const best=rec.bestCostBB!=null?Number(rec.bestCostBB):NaN;return Number.isFinite(best)?best:raw;
}
function trainerReuseBestAsPlayed(rec){
  const d=JSON.parse(JSON.stringify(rec));
  // Keep the canonical D6 state: a preflop recommendation whose gate is closed
  // must not fabricate a chosen EV from an unavailable recommended EV.
  const showEV=rec?.preflopDecision?trainerPreflopDecisionView(rec.preflopDecision).show_ev:true;
  if(showEV)d.chosenEV=Number(d.bestEV);else{d.chosenEV=NaN;d.bestEV=NaN;d.bestCostBB=null;}
  d.lossBB=0;d.withinNoise=true;
  trainerState.perf.reused++;return d;
}
async function trainerHeroAction(kind,cost=0){
  const hand=trainerState.hand;if(!hand||hand.ended||!hand.awaitingHero||trainerState.busy||trainerState.pauseAfterDecision)return;
  const targetReference=trainerState.targeted.active&&trainerState.targeted.currentScenario&&trainerState.recommendation&&!trainerState.recommendation.error?trainerState.recommendation:null;
  const guide=targetReference||(trainerState.mode==="guided"&&trainerState.recommendation&&!trainerState.recommendation.error?trainerState.recommendation:null);
  trainerState.busy=true;hand.awaitingHero=false;trainerRenderStatus("Évaluation de votre décision…","busy");trainerRender();
  let detail=null,row=null,actual=null;
  try{
    actual=trainerActualLine(hand,kind,cost);
    if(hand.street==="preflop"){
      detail=await trainerComputePreflopReference(hand,actual,guide);
    }else if(guide&&trainerRecommendationMatchesAction(guide,actual,hand)){
      detail=trainerReuseBestAsPlayed(guide);
    }else{
      const played=await trainerTimedReviewText(trainerBuildReviewHH(hand,actual.line,actual.kind,actual.cost));
      detail=guide?trainerGuideAnchoredDetail(guide,played):played;
    }
    trainerState.recommendation=hand.street==="preflop"?detail:(guide||detail);row=trainerRecordDecision(detail,actual.kind,actual.cost);
    if(trainerState.targeted.active&&trainerState.targeted.currentScenario)trainerTargetEvent(detail,row,actual);
  }
  catch(err){trainerRenderStatus(`Décision jouée, mais verdict indisponible : ${err.message}`,"error");}
  trainerApplyAction(hand,hand.heroSeat,kind,cost);trainerState.feedback=detail?{detail,row}:null;trainerState.busy=false;
  if(trainerState.targeted.active&&trainerState.targeted.currentScenario){
    trainerState.targeted.currentCompleted=true;
    if(trainerState.mode==="test"){
      trainerState.feedback=null;trainerState.pauseAfterDecision=false;trainerTargetNext();return;
    }
    trainerState.pauseAfterDecision=true;
    const suffix=trainerState.perf.lastMs?` · dernier calcul ${trainerState.perf.lastMs.toFixed(0)} ms`:"";
    trainerRenderStatus(`Spot ciblé terminé${suffix} · passez au spot suivant lorsque vous êtes prêt.`);trainerRender();return;
  }
  if(hand.ended){trainerRenderStatus(`Main terminée · ${hand.winner}.`);trainerRender();return;}
  if(trainerState.mode==="test"){trainerState.feedback=null;trainerRender();await trainerAdvance();}
  else{trainerState.pauseAfterDecision=true;const suffix=trainerState.perf.lastMs?` · dernier calcul ${trainerState.perf.lastMs.toFixed(0)} ms`:"";trainerRenderStatus(`Feedback disponible${suffix}. Continuez lorsque vous êtes prêt.`);trainerRender();}
}

async function trainerAdvance(){
  const hand=trainerState.hand;if(!hand||hand.ended||trainerState.pauseAfterDecision)return;
  while(!hand.ended){
    if(!hand.queue.length){trainerAdvanceStreetOrShowdown(hand);trainerRender();if(hand.ended)break;await trainerSleep(TRAINER_DELAYS.street);continue;}
    const seat=hand.queue.shift();if(hand.folded[seat]||hand.stacks[seat]<=1e-8)continue;
    if(seat===hand.heroSeat){
      hand.awaitingHero=true;hand.decisionNo++;trainerState.feedback=null;trainerState.recommendation=null;trainerState.sizingTouched=false;
      trainerRefreshPersonalOverride();trainerRender();
      if(trainerState.mode==="guided")await trainerComputeRecommendation();
      else trainerRenderStatus("À vous de jouer · recommandation calculée après votre action.");
      return;
    }
    trainerRenderStatus(`${hand.names[seat]} réfléchit…`,"busy");trainerRender();await trainerSleep(TRAINER_DELAYS.opponentThink);trainerOpponentAct(hand,seat);trainerRender();await trainerSleep(TRAINER_DELAYS.opponentSettle);
  }
  if(hand.ended)trainerRenderStatus(`Main terminée · ${hand.winner}.`);
  trainerRender();
}
async function trainerContinue(){
  if(trainerState.targeted.active&&trainerState.targeted.currentCompleted){
    trainerState.feedback=null;trainerState.pauseAfterDecision=false;trainerTargetNext();return;
  }
  trainerState.pauseAfterDecision=false;trainerState.feedback=null;trainerRender();await trainerAdvance();
}
async function trainerNewHand(){
  if(trainerState.busy||trainerState.targeted.preparing)return;
  if(trainerState.targeted.active){
    const t=trainerState.targeted;
    if(t.fallback||t.complete||!t.plan?.ready){if(t.target)await trainerPrepareTargetSession(t.target,{hydrate:false});return;}
    trainerState.feedback=null;trainerState.pauseAfterDecision=false;trainerTargetNext();return;
  }
  if(!await trainerEnsureModels())return;
  trainerState.feedback=null;trainerState.recommendation=null;trainerState.pauseAfterDecision=false;trainerState.testLog=[];trainerState.hand=trainerBuildHand();if(trainerState.hand)trainerRefreshPersonalOverride();trainerRenderStatus("Nouvelle main · blindes postées, préflop réel actif.");trainerRender();await trainerAdvance();
}

function trainerBoardHtml(hand){return Array.from({length:5},(_,i)=>{const c=i<hand.boardCount?hand.runout[i]:null;return `<div class="board-card${c===null?" empty":""}">${c===null?"":cardHtml(c)}</div>`;}).join("");}
function trainerSeatHtml(hand,s){
  const isHero=s===hand.heroSeat,isActive=hand.awaitingHero&&isHero,folded=hand.folded[s],reveal=isHero||(hand.ended&&s===hand.activeOppSeat),cards=reveal?hand.hole[s]:[];
  const cardHtml2=reveal?cards.map(c=>`<div class="hole-card">${cardHtml(c)}</div>`).join(""):`<div class="hole-card empty trainer-seat-hidden">?</div><div class="hole-card empty trainer-seat-hidden">?</div>`;
  const prof=isHero?"":trainerProfileSummary(hand.profiles[s]);
  return `<div class="seat seat${s+1}${isHero?" hero":""}${isActive?" active":""}${folded?" folded":""}">
    <div class="seat-header"><div><div class="seat-name">${escapeHtml(hand.names[s])}</div>${prof?`<div class="trainer-seat-profile">${escapeHtml(prof)}</div>`:""}</div><div class="seat-right-meta"><div class="seat-pos-row"><span class="seat-pos">${escapeHtml(hand.positions[s])}</span></div><span class="seat-stack">${escapeHtml(trainerFmtBB(hand.stacks[s]))}</span></div></div>
    <div class="seat-cards">${cardHtml2}</div><div class="seat-action"><div class="seat-action-main"><span class="tiny">${escapeHtml(hand.lastAction[s]||"")}</span></div></div>
  </div>`;
}
function trainerBetSpotsHtml(hand){return hand.streetPaid.map((x,s)=>x>1e-8?`<div class="bet-spot bet${s+1}">${escapeHtml(trainerFmtBB(x))}</div>`:"").join("");}
function trainerRenderTable(){
  const h=trainerState.hand;if(!trainerTable)return;if(!h){trainerTable.innerHTML='<div class="trainer-note">Cliquez sur « Nouvelle main » pour commencer.</div>';return;}
  trainerTable.innerHTML=`<div class="trainer-table-wrap"><div class="poker-table"><div class="table-center"><div class="table-pot">Pot<br><b>${escapeHtml(trainerFmtBB(h.pot))}</b></div><div class="table-board">${trainerBoardHtml(h)}</div><div class="tiny" style="margin-top:8px">${escapeHtml(h.street.toUpperCase())} · ${escapeHtml(trainerPotType(h))} · ${escapeHtml(`Hero ${h.heroRole||"en décision"}`)} · stratégie Hero ${escapeHtml(trainerHeroStrategyLabel())}</div></div>${replayDealerButtonHtml({buttonSeat:h.dealerSeat+1})}${trainerBetSpotsHtml(h)}${Array.from({length:6},(_,s)=>trainerSeatHtml(h,s)).join("")}</div></div>`;
}
function trainerPreflopTargetText(target){
  const v=Number(target?.target_total_bb);return Number.isFinite(v)?`total ${trainerFmtBB(v)}`:"0 BB";
}
// Precise non-recommendation cause, derived from the shared taxonomy
// dimensions. Rule D6 (`view.show_ev`) alone decides whether a Hero
// recommendation/EV may be exposed; this helper only names the actual blocking
// cause reported by `poker-analysis-state/v1` so distinct causes are never
// collapsed into one generic "aucune recommandation" sentence. It reads the
// separated dimensions, never the raw reason codes (those stay in the secondary
// technical panel).
function trainerPreflopRecommendationCause(view){
  const analysis=view?.analysis;
  if(!analysis)return "Aucune recommandation EV validée pour ce spot.";
  const state=String(analysis.state||"").toUpperCase();
  const model=String(analysis.model_support_status||"").toUpperCase();
  const admissible=analysis.recommendation_admissibility?.admissible===true;
  if(state==="ERREUR_CALCUL"||analysis.error?.type){
    const type=analysis.error?.type?` (${analysis.error.type})`:"";
    return `Erreur worker${type} · la recommandation n'a pas pu être calculée${analysis.error?.retryable?" ; une nouvelle tentative est possible":""}.`;
  }
  if(state==="CALCUL_EN_COURS")return "Calcul en cours · la recommandation n'est pas encore disponible.";
  if(state==="SPOT_NON_SUPPORTE"){
    if(model==="CONTEXT_UNSUPPORTED")return "Contexte non supporté · ce spot sort du périmètre de la référence active.";
    return "Absence de node · aucun nœud de modèle ne couvre ce spot.";
  }
  if(state==="DONNEES_INSUFFISANTES")return "Support insuffisant · trop peu d'observations pour valider une recommandation.";
  if(state==="ANALYSE_PARTIELLE"){
    if(!admissible)return "Recommandation non admise · aucune action admissible n'est exposable sur ce spot.";
    return "Analyse partielle · les EV de la décision jouée et de la recommandation ne sont pas comparables.";
  }
  return "Aucune recommandation EV validée pour ce spot.";
}
// Secondary feedback summary. Rule D6 (`view.show_ev`) is the single gate for
// every exposed EV/recommendation field below: the recommended action, its
// target sizing, its EV, the alternative rows' EV and the ΔEV/perte EV derived
// from the recommended reference. When the gate is closed those fields are all
// absent; the panel still renders the legitimate technical layer (taxonomy
// state, reason codes, computational/model support, statistical support,
// comparability/admissibility reasons and the observed action) plus the precise
// blocking cause. No local D6 rule is duplicated here.
function trainerPreflopDecisionSummaryHtml(decision){
  const view=trainerPreflopDecisionView(decision);
  // The reason codes and the separated dimensions only live in this secondary
  // panel; the primary label above them is the shared taxonomy state.
  const technical=trainerAnalysisDimensionsHtml(view.analysis);
  if(!view.show_ev){
    const label=escapeHtml(trainerPreflopTaxonomyLabel(decision));
    const cause=escapeHtml(trainerPreflopRecommendationCause(view));
    const observed=decision?.played_action?`<div class="trainer-feedback-body">Action observée : <b>${escapeHtml(decision.played_action)}</b> · non évaluée par cette référence (aucun ΔEV exposé).</div>`:"";
    return `<div class="trainer-feedback-body"><b>${label}</b> · aucune recommandation EV exposable · ${cause}</div>${observed}${technical}`;
  }
  const support=Number(decision.support?.observations)||0;
  const rows=(decision.alternatives||[]).map(a=>`<div class="trainer-feedback-body"><b>${escapeHtml(a.action)}</b> · ${escapeHtml(trainerPreflopTargetText(a.target_sizing))} · coût ${escapeHtml(trainerFmtBB(a.incremental_cost_bb))} · EV <b>${escapeHtml(trainerFmtBB(a.ev_bb))}</b></div>`).join("");
  const played=decision.ev_comparable
    ?`EV jouée <b>${escapeHtml(trainerFmtBB(decision.played_ev_bb))}</b> · perte EV <b>${escapeHtml(trainerFmtBB(Math.max(0,Number(decision.recommended_ev_bb)-Number(decision.played_ev_bb))))}</b>.`
    :decision.played_action?`Action jouée <b>${escapeHtml(decision.played_action)}</b> non évaluée par cette référence : aucun ΔEV inventé.`:"";
  return `<div class="trainer-feedback-body">Recommandé : <b>${escapeHtml(decision.recommended_action)}</b> · ${escapeHtml(trainerPreflopTargetText(decision.recommended_target_sizing))} · coût ${escapeHtml(trainerFmtBB(decision.incremental_cost_bb))} · EV <b>${escapeHtml(trainerFmtBB(decision.recommended_ev_bb))}</b> · support ${support.toLocaleString("fr-FR")}.</div>${rows}<div class="trainer-feedback-body">${played}</div>${technical}`;
}
function trainerBestText(rec){
  if(!rec||rec.error)return "—";
  // Preflop best label/sizing are D6 Hero fields: when the canonical gate is
  // closed there is nothing usable to render (no action, no sizing).
  if(rec.preflopDecision&&!trainerPreflopDecisionView(rec.preflopDecision).show_ev)return "—";
  const label=String(rec.bestLabel||"—"),kind=trainerRecommendationKind(trainerState.hand,rec),upper=label.toUpperCase();
  const action=kind&&!upper.startsWith(kind)?`${kind} · `:"",cost=rec.bestCostBB!=null?Number(rec.bestCostBB):NaN,size=Number.isFinite(cost)?` · ${trainerFmtBB(cost)}`:"";
  return `${action}${label}${size}`;
}
function trainerRenderRecommendation(){
  if(!trainerRecommendation)return;const h=trainerState.hand,rec=trainerState.recommendation;
  if(!h||h.ended){trainerRecommendation.className="trainer-recommendation hidden-answer";trainerRecommendation.innerHTML='<div class="trainer-rec-label">Recommandation</div><div class="trainer-rec-main">—</div>';return;}
  const canShow=trainerState.mode==="guided";
  if(trainerState.busy&&!rec){trainerRecommendation.className="trainer-recommendation hidden-answer";trainerRecommendation.innerHTML='<div class="trainer-rec-label">Analyse</div><div class="trainer-rec-main">Calcul…</div>';return;}
  if(!canShow){trainerRecommendation.className="trainer-recommendation hidden-answer";trainerRecommendation.innerHTML=`<div class="trainer-rec-label">${trainerState.mode==="test"?"Mode Test":"Décidez d'abord"}</div><div class="trainer-rec-main">Réponse masquée</div><div class="trainer-rec-ev">${trainerState.mode==="test"?"Le bilan apparaît en fin de main.":"Le feedback apparaît après votre action."}</div>`;return;}
  if(rec?.preflopDecision){
    const d=rec.preflopDecision;
    // Single canonical derivation for this render. D6 (`view.show_ev`) decides
    // whether the recommendation/sizing/EV fields may be exposed; `covered`
    // alone is never sufficient. The panel stays visible either way, so a
    // fail-closed spot renders its taxonomy label and precise cause instead of
    // the hidden-answer placeholder.
    const view=trainerPreflopDecisionView(d);
    trainerRecommendation.className="trainer-recommendation";
    if(view.show_ev){
      trainerRecommendation.innerHTML=`<div class="trainer-rec-label">Action recommandée · référence active #108 conservée</div><div class="trainer-rec-main">${escapeHtml(d.recommended_action)} · ${escapeHtml(trainerPreflopTargetText(d.recommended_target_sizing))}</div><div class="trainer-rec-ev">Coût ${escapeHtml(trainerFmtBB(d.incremental_cost_bb))} · EV ${escapeHtml(trainerFmtBB(d.recommended_ev_bb))} · support ${Number(d.support?.observations||0).toLocaleString("fr-FR")}</div>`;
      return;
    }
    // D6 closed: expose the canonical taxonomy label only, plus the specific
    // blocking cause. No recommended action/sizing/EV and no alternative EV.
    const taxonomyLabel=escapeHtml(trainerPreflopTaxonomyLabel(d));
    trainerRecommendation.innerHTML=`<div class="trainer-rec-label">Préflop · ${taxonomyLabel}</div><div class="trainer-rec-main">${taxonomyLabel}</div><div class="trainer-rec-ev">${escapeHtml(trainerPreflopRecommendationCause(view))}</div>`;
    return;
  }
  trainerRecommendation.className="trainer-recommendation";trainerRecommendation.innerHTML=`<div class="trainer-rec-label">Action recommandée · EV finale</div><div class="trainer-rec-main">${escapeHtml(trainerBestText(rec))}</div><div class="trainer-rec-ev">EV ${Number.isFinite(Number(rec?.bestEV))?escapeHtml(trainerFmtBB(rec.bestEV)):"—"}</div>`;
}
function trainerRenderFeedback(){
  if(!trainerFeedback)return;const f=trainerState.feedback,h=trainerState.hand;
  if(trainerState.mode==="test"&&trainerState.targeted.active&&trainerState.targeted.complete){
    const loss=trainerState.testLog.reduce((sum,x)=>sum+x.lossBB,0);trainerFeedback.className="trainer-feedback";
    trainerFeedback.innerHTML=`<div class="trainer-feedback-title">Bilan Test ciblé</div><div class="trainer-feedback-body">${trainerState.testLog.length} décision(s) · perte EV cumulée <b>${escapeHtml(trainerFmtBB(loss))}</b>. Le bilan ΔEV ciblé est affiché dans « Bilan ciblé ».</div>`;return;
  }
  if(trainerState.mode==="test"&&!h?.ended){trainerFeedback.className="trainer-feedback";trainerFeedback.innerHTML='<div class="trainer-feedback-title">Mode Test</div><div class="trainer-feedback-body">Aucun feedback avant la fin de la main.</div>';return;}
  if(!f){
    if(h?.ended&&trainerState.mode==="test"){const loss=trainerState.testLog.reduce((sum,x)=>sum+x.lossBB,0);trainerFeedback.className="trainer-feedback";trainerFeedback.innerHTML=`<div class="trainer-feedback-title">Bilan de la main</div><div class="trainer-feedback-body">${trainerState.testLog.length} décision(s) · perte EV cumulée <b>${escapeHtml(trainerFmtBB(loss))}</b>.</div>`;return;}
    trainerFeedback.className="trainer-feedback";trainerFeedback.innerHTML='<div class="trainer-feedback-title">Feedback</div><div class="trainer-feedback-body">Jouez une décision Hero pour obtenir le verdict.</div>';return;
  }
  const d=f.detail,r=f.row;
  if(d?.preflopDecision){
    // Canonical D6 state (`view.show_ev`) drives both the feedback headline
    // class and the summary gate; the local covered/ev_comparable combination
    // is no longer recombined here.
    const view=trainerPreflopDecisionView(d.preflopDecision);
    trainerFeedback.className=`trainer-feedback ${view.show_ev?(r.cls==="poor"?"poor":r.cls==="good"?"good":"close"):"close"}`;
    const title=trainerPreflopTaxonomyLabel(d.preflopDecision);
    trainerFeedback.innerHTML=`<div class="trainer-feedback-title">${escapeHtml(title)}</div>${trainerPreflopDecisionSummaryHtml(d.preflopDecision)}`;
    return;
  }
  const summary=trainerDecisionCanonical(d,r);
  const quality=summary?TrainerActionSizingEV.qualityFromEV(summary):{key:r?.cls||"unknown",label:"Indéterminée",note:""};
  const cls=quality.key==="unknown"?"close":quality.key,title=quality.label;
  const primary=summary?`${TrainerActionSizingEV.primarySummaryHtml(summary,{compact:true,escapeHtml,formatBB})}${TrainerActionSizingEV.alternativesStripHtml(summary,{limit:4,escapeHtml,formatBB})}`:`<div class="trainer-feedback-body">Verdict détaillé indisponible.</div>`;
  const noise=r.withinNoise?" · dans le bruit Monte-Carlo":"";
  trainerFeedback.className=`trainer-feedback ${cls}`;
  trainerFeedback.innerHTML=`<div class="trainer-feedback-title">${escapeHtml(title)}</div>${primary}<div class="trainer-feedback-body">Perte EV effective après incertitude : <b>${escapeHtml(trainerFmtBB(r.lossBB))}</b>${noise}.</div><details class="action-advanced"><summary>Pourquoi ? / Détails avancés</summary><div class="action-advanced-body"><div class="trainer-feedback-body">Joué : <b>${escapeHtml(r.played)}${r.cost>0?` · ${escapeHtml(trainerFmtBB(r.cost))}`:""}</b><br>Recommandé : <b>${escapeHtml(trainerBestText(d))}</b><br>EV jouée : <b>${Number.isFinite(Number(d.chosenEV))?escapeHtml(trainerFmtBB(d.chosenEV)):"—"}</b> · meilleure EV : <b>${Number.isFinite(Number(d.bestEV))?escapeHtml(trainerFmtBB(d.bestEV)):"—"}</b><br>La catégorie affichée est dérivée uniquement de la perte EV et de l’incertitude du modèle.</div></div></details>`;
}
function trainerSizingValue(){return Math.max(0,Number(document.getElementById("trainerSizingInput")?.value)||0);}
function trainerSetSizing(x){const input=document.getElementById("trainerSizingInput");if(input)input.value=trainerNum(x);}
function trainerRenderControls(){
  if(!trainerControls)return;const h=trainerState.hand,t=trainerState.targeted;
  if(t.active&&t.complete){trainerControls.innerHTML='<div class="trainer-hand-ended">Session ciblée terminée · le bilan ΔEV est disponible dans le panneau latéral.</div>';return;}
  if(!h){trainerControls.innerHTML="";return;}
  if(h.ended&&!t.active){trainerControls.innerHTML=`<div class="trainer-hand-ended">Main terminée · <b>${escapeHtml(h.winner)}</b>${h.showdown?" · showdown":""}. Cliquez sur « Nouvelle main » pour continuer.</div>`;return;}
  if(trainerState.pauseAfterDecision){
    const label=t.active?"Spot suivant":"Continuer la main";
    trainerControls.innerHTML=`<div class="trainer-decision-box"><div class="trainer-decision-head"><div class="trainer-decision-title">Feedback</div><button type="button" id="trainerInlineContinue" class="primary">${label}</button></div></div>`;
    document.getElementById("trainerInlineContinue")?.addEventListener("click",trainerContinue);return;
  }
  if(!h.awaitingHero){trainerControls.innerHTML='<div class="trainer-decision-box"><div class="trainer-decision-title">Action adverse en cours…</div></div>';return;}
  const view=h.core.legalView(h.names[h.heroSeat]),toCall=Number(view.to_call_bb)||0;
  const legal=(view.legal_actions||[]).map(a=>a==="RAISE"&&toCall<=1e-8?"BET":a);
  const minTarget=Number(view.min_raise_to_bb),paid=Number(view.actor_street_contribution_bb)||0;
  const minAgg=Number.isFinite(minTarget)?Math.max(0,minTarget-paid):(toCall>1e-8?toCall+h.lastRaise:Math.max(1,.33*h.pot));
  const recCost=trainerState.recommendation?.bestCostBB,recCostBB=recCost!=null?Number(recCost):NaN;
  trainerControls.innerHTML=`<div class="trainer-decision-box"><div class="trainer-decision-head"><div><div class="trainer-decision-title">À vous · ${escapeHtml(h.positions[h.heroSeat])} · ${escapeHtml(h.street.toUpperCase())}</div><div class="trainer-context">Pot ${escapeHtml(trainerFmtBB(h.pot))} · ${toCall>0?`à payer ${escapeHtml(trainerFmtBB(toCall))}`:"check possible"} · stack ${escapeHtml(trainerFmtBB(h.stacks[h.heroSeat]))}</div></div></div><div class="trainer-actions">${legal.map(a=>`<button type="button" class="${a==="FOLD"?"danger secondary":a==="CHECK"||a==="CALL"?"secondary":"primary"}" data-trainer-action="${a}">${a}</button>`).join("")}<div class="trainer-sizing"><div class="field"><label for="trainerSizingInput">Coût ajouté / mise (BB)</label><input id="trainerSizingInput" type="number" min="0" step="0.1" value="${trainerNum(Number.isFinite(recCostBB)?recCostBB:minAgg)}"></div><div class="trainer-size-presets"><button type="button" class="secondary" data-size=".5">½ pot</button><button type="button" class="secondary" data-size=".75">¾ pot</button><button type="button" class="secondary" data-size="1">Pot</button><button type="button" class="secondary" data-size="allin">All-in</button></div></div></div></div>`;
  const sizingInput=document.getElementById("trainerSizingInput");sizingInput?.addEventListener("input",()=>{trainerState.sizingTouched=true;});
  trainerControls.querySelectorAll("[data-trainer-action]").forEach(b=>b.addEventListener("click",()=>trainerHeroAction(b.dataset.trainerAction,trainerGuidedClickCost(b.dataset.trainerAction))));
  trainerControls.querySelectorAll("[data-size]").forEach(b=>b.addEventListener("click",()=>{trainerState.sizingTouched=true;const v=b.dataset.size==="allin"?h.stacks[h.heroSeat]:Math.max(toCall>0?toCall+h.lastRaise:1,Number(b.dataset.size)*h.pot);trainerSetSizing(v);}));
}
function trainerRenderStats(){
  if(!trainerStats)return;const s=trainerState.session;trainerStats.innerHTML=`<div class="trainer-stat-grid"><div class="trainer-stat"><div class="k">Mains</div><div class="v">${s.hands}</div></div><div class="trainer-stat"><div class="k">Décisions</div><div class="v">${s.decisions}</div></div><div class="trainer-stat"><div class="k">Bonnes / proches</div><div class="v">${s.good+s.close}</div></div><div class="trainer-stat loss"><div class="k">EV perdue</div><div class="v">${escapeHtml(trainerFmtBB(s.lossBB))}</div></div></div>`;
  const rows=Object.entries(s.breakdown).sort((a,b)=>b[1].loss-a[1].loss).slice(0,8);trainerBreakdown.innerHTML=rows.length?rows.map(([k,v])=>`<div class="trainer-break-row"><span>${escapeHtml(k)}</span><span>${v.n} déc.</span><b>−${escapeHtml(trainerFmtBB(v.loss))}</b></div>`).join(""):'<div class="tiny">Aucune décision enregistrée.</div>';
}
function trainerRenderProfiles(){
  if(!trainerProfiles)return;const h=trainerState.hand;if(!h){trainerProfiles.innerHTML='<div class="tiny">Aucune table active.</div>';return;}
  trainerProfiles.innerHTML=Array.from({length:6},(_,s)=>s===h.heroSeat?"":(()=>{const p=trainerProfileById(h.profiles[s]),c=p?.centroid||{};return `<div class="trainer-profile-row"><b>${escapeHtml(h.names[s])} · ${escapeHtml(h.positions[s])} · ${escapeHtml(trainerProfileSummary(h.profiles[s]))}</b><div class="trainer-profile-metrics">VPIP ${(100*Number(c.vpip||0)).toFixed(0)} % · PFR ${(100*Number(c.pfr||0)).toFixed(0)} % · Agg. postflop ${(100*Number(c.post_aggression_frequency||0)).toFixed(0)} %</div></div>`;})()).join("");
}
function trainerRenderTestLog(){
  if(!trainerTestLog)return;if(trainerState.mode!=="test"){trainerTestLog.innerHTML="";return;}
  const h=trainerState.hand,targetDone=trainerState.targeted.active&&trainerState.targeted.complete;
  if(!targetDone&&!h?.ended){trainerTestLog.innerHTML='<div class="tiny">Les décisions resteront masquées jusqu’à la fin de la session.</div>';return;}
  trainerTestLog.innerHTML=trainerState.testLog.map(r=>`<div class="trainer-test-row">${escapeHtml(r.position)} · ${escapeHtml(r.street)} · joué ${escapeHtml(r.played)}${r.cost?` ${escapeHtml(trainerFmtBB(r.cost))}`:""}<br>Reco <b>${escapeHtml(r.bestLabel)}${r.bestCostBB!==null?` · ${escapeHtml(trainerFmtBB(r.bestCostBB))}`:""}</b> · perte ${escapeHtml(trainerFmtBB(r.lossBB))}</div>`).join("")||'<div class="tiny">Aucune décision Hero.</div>';
}
function trainerRenderStatus(text,cls=""){if(!trainerStatus)return;trainerStatus.textContent=text||"";trainerStatus.className=`trainer-status${cls?` ${cls}`:""}`;}
function trainerRender(){
  trainerRenderTable();trainerRenderControls();trainerRenderRecommendation();trainerRenderFeedback();trainerRenderStats();trainerRenderProfiles();trainerRenderTestLog();trainerTargetRenderSummary();
  if(trainerNewHandBtn){
    trainerNewHandBtn.disabled=trainerState.busy||trainerState.loading||trainerState.targeted.preparing;
    trainerNewHandBtn.textContent=trainerState.targeted.active?(trainerState.targeted.complete||trainerState.targeted.fallback?"Rejouer la session":"Spot suivant"):"Nouvelle main";
  }
  trainerContinueBtn&&(trainerContinueBtn.style.display=trainerState.pauseAfterDecision?"inline-block":"none");
}
async function trainerOpen(options={}){
  const deferHand=options&&options.deferHand===true;
  window.pokerComputeScheduler.hold('training',true);trainerState.open=true;state.appView="training";updateAppView();window.scrollTo({top:0,behavior:"auto"});trainerRender();
  if(await trainerEnsureModels()){if(!deferHand&&!trainerState.hand)await trainerNewHand();}
}
function trainerClose(){window.pokerComputeScheduler.hold('training',false);trainerState.open=false;state.appView="home";updateAppView();window.scrollTo({top:0,behavior:"auto"});}
function trainerSetMode(mode){if(!["guided","training","test"].includes(mode))return;trainerState.mode=mode;trainerState.feedback=null;document.querySelectorAll("[data-trainer-mode]").forEach(b=>b.classList.toggle("active",b.dataset.trainerMode===mode));const needGuide=mode==="guided"&&trainerState.hand?.awaitingHero&&!trainerState.recommendation&&!trainerState.busy;trainerRender();if(needGuide)void trainerComputeRecommendation();}

trainerOpenBtn?.addEventListener("click",trainerOpen);
trainerNavLink?.addEventListener("click",e=>{e.preventDefault();e.stopImmediatePropagation();trainerOpen();},{capture:true});
trainerBackBtn?.addEventListener("click",trainerClose);
trainerNewHandBtn?.addEventListener("click",trainerNewHand);
trainerContinueBtn?.addEventListener("click",trainerContinue);
trainerTargetApplyBtn?.addEventListener("click",trainerApplyTargetControls);
trainerTargetClearBtn?.addEventListener("click",trainerClearTargeting);
document.querySelectorAll("[data-trainer-mode]").forEach(b=>b.addEventListener("click",()=>trainerSetMode(b.dataset.trainerMode)));
trainerScheduleWarmup();
trainerRenderStatus("Ouvrez une session pour charger les modèles promus.");trainerRender();

/* Hero range compliance replayer bootstrap (#98) */
(function loadHeroRangeComplianceReplayer(){
  if(typeof document==='undefined')return;
  const sources=['./hero-ranges.js','./hero-compliance.js','./hero-compliance-replayer.js'];
  let index=0;
  const next=()=>{
    if(index>=sources.length)return;
    const src=sources[index++];
    const existing=[...document.scripts].find(s=>s.getAttribute('src')===src||String(s.src||'').endsWith(src.replace(/^\.\//,'')));
    if(existing){
      if((src.endsWith('hero-ranges.js')&&window.PokerHeroRanges)||(src.endsWith('hero-compliance.js')&&window.PokerHeroCompliance)||(src.endsWith('hero-compliance-replayer.js')&&window.PokerHeroComplianceReplayer))next();
      else existing.addEventListener('load',next,{once:true});
      return;
    }
    const script=document.createElement('script');script.src=src;script.defer=false;script.addEventListener('load',next,{once:true});
    script.addEventListener('error',()=>console.warn('Hero compliance script failed to load:',src),{once:true});
    document.head.appendChild(script);
  };
  next();
})();

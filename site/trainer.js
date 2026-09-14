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
const trainerWarmAssets={started:false,promise:null,population:null,modelA:null,modelB:null,heroRanges:null,startedAt:0,finishedAt:0,error:null};
const trainerReviewCache={entries:new Map(),preModel:null,postModel:null,hits:0,misses:0,evictions:0};

const trainerState={
  open:false,mode:"training",loading:false,ready:false,error:"",populationId:null,modelB:null,heroRanges:null,
  handNo:0,evalNo:0,hand:null,recommendation:null,feedback:null,
  pauseAfterDecision:false,busy:false,sizingTouched:false,
  perf:{evaluations:0,reused:0,totalMs:0,lastMs:0,modelLoadMs:0,warmupMs:0,warmHit:false,cacheHits:0,cacheMisses:0},
  session:{hands:0,decisions:0,good:0,close:0,poor:0,lossBB:0,breakdown:Object.create(null)},
  testLog:[]
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

function trainerSleep(ms){return new Promise(r=>setTimeout(r,ms));}
function trainerClamp(x,a,b){return Math.max(a,Math.min(b,x));}
function trainerNum(x,d=2){return Number(x||0).toFixed(d).replace(/\.?0+$/,"");}
function trainerFmtBB(x){return `${new Intl.NumberFormat("fr-FR",{minimumFractionDigits:0,maximumFractionDigits:2}).format(Number(x)||0)} BB`;}
function trainerRandomInt(n){return Math.floor(Math.random()*n);}
function trainerShuffle(a){for(let i=a.length-1;i>0;i--){const j=trainerRandomInt(i+1);[a[i],a[j]]=[a[j],a[i]];}return a;}
function trainerWeightedChoice(items,weights){
  let total=0;const clean=weights.map(w=>{w=Math.max(0,Number(w)||0);total+=w;return w;});
  if(!(total>0))return items[trainerRandomInt(items.length)];
  let x=Math.random()*total;
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

async function trainerEnsureModels(){
  if(trainerState.ready)return true;
  if(trainerState.loading){
    while(trainerState.loading)await trainerSleep(100);
    return trainerState.ready;
  }
  trainerState.loading=true;trainerState.error="";trainerRenderStatus("Chargement des modèles promus A/B…","busy");
  const loadStarted=performance.now();
  try{
    const alreadyWarm=!!(trainerWarmAssets.modelA&&trainerWarmAssets.modelB&&trainerWarmAssets.heroRanges),assets=await trainerLoadWarmAssets();
    trainerState.perf.warmHit=alreadyWarm;
    const {profiles,ranges,actions,sizing,contract}=assets.modelB;
    if(!assets.population?.population_id)throw new Error("Pack trainer : population absente.");
    if(profiles.schema!=="independent-opponent-profiles/v2"||ranges.schema!=="independent-preflop-ranges/v2"||actions.schema!=="independent-postflop-actions/v2"||sizing.schema!=="independent-postflop-sizing/v2")throw new Error("Model B : schéma inattendu.");
    if(assets.heroRanges?.schema!=="trainer-hero-preflop-ranges/v1")throw new Error("Ranges Hero : schéma inattendu.");
    trainerState.populationId=assets.population.population_id;trainerState.modelB=assets.modelB;trainerState.heroRanges=assets.heroRanges;

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
    trainerRenderStatus(`Trainer prêt · ${trainerState.populationId} · Model A v5 + Model B v2 + ranges Hero Custom · init ${trainerState.perf.modelLoadMs.toFixed(0)} ms${trainerState.perf.warmHit?" · assets préchargés":""}.`);
    return true;
  }catch(err){
    trainerState.error=err?.message||String(err);trainerRenderStatus(`Trainer indisponible : ${trainerState.error}`,"error");return false;
  }finally{trainerState.loading=false;trainerRender();}
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
function trainerBuildHand(){
  const dealer=trainerRandomInt(6),heroSeat=trainerRandomInt(6),positions=Array.from({length:6},(_,s)=>trainerPositionForSeat(s,dealer));
  const heroPos=positions[heroSeat],heroRank=TRAINER_PREFLOP_ORDER.indexOf(heroPos);
  let heroRole=(heroRank<5&&heroRank>0)?(Math.random()<.5?"PFA":"CALLER"):(heroRank===0?"PFA":"CALLER");
  let candidates=[];
  if(heroRole==="PFA")candidates=positions.map((p,s)=>({p,s,r:TRAINER_PREFLOP_ORDER.indexOf(p)})).filter(x=>x.s!==heroSeat&&x.r>heroRank);
  else candidates=positions.map((p,s)=>({p,s,r:TRAINER_PREFLOP_ORDER.indexOf(p)})).filter(x=>x.s!==heroSeat&&x.r<heroRank);
  if(!candidates.length||!trainerHeroRangeAvailable(heroRole,heroPos))return trainerBuildHand();
  trainerState.handNo++;
  const oppSeat=candidates[trainerRandomInt(candidates.length)].s,oppPos=positions[oppSeat],pfaSeat=heroRole==="PFA"?heroSeat:oppSeat,callerSeat=heroRole==="CALLER"?heroSeat:oppSeat;
  const names=Array.from({length:6},(_,s)=>s===heroSeat?TRAINER_HERO:`Villain ${s+1}`),profiles=Array(6).fill(null);
  for(let s=0;s<6;s++)if(s!==heroSeat)profiles[s]=trainerSampleProfile();
  const hole=Array.from({length:6},()=>[]),blocked=new Set(),heroCards=trainerSampleHeroRangeCards(heroRole,heroPos,blocked);
  if(!heroCards)return trainerBuildHand();hole[heroSeat]=heroCards;hole[heroSeat].forEach(c=>blocked.add(c));
  const oppRole=heroRole==="PFA"?"CALLER":"PFA",oppCards=trainerSampleRangeCards(profiles[oppSeat],oppPos,"SRP",oppRole,blocked);
  hole[oppSeat]=oppCards;for(const c of oppCards)blocked.add(c);
  const remaining=Array.from({length:52},(_,i)=>i).filter(c=>!blocked.has(c));trainerShuffle(remaining);
  for(let s=0;s<6;s++)if(s!==heroSeat&&s!==oppSeat){hole[s]=[trainerDraw(remaining),trainerDraw(remaining)];}
  const used=new Set(hole.flat()),boardDeck=trainerShuffle(Array.from({length:52},(_,i)=>i).filter(c=>!used.has(c))),runout=Array.from({length:5},()=>trainerDraw(boardDeck));

  const contrib=Array(6).fill(0),stacks=Array(6).fill(100),folded=Array(6).fill(false),lastAction=Array(6).fill("");
  const sb=trainerSeatForPosition({positions},"SB"),bb=trainerSeatForPosition({positions},"BB");contrib[sb]=.5;contrib[bb]=1;stacks[sb]-=.5;stacks[bb]-=1;
  const id=990000000000+trainerState.handNo*100;
  const lines=[`PokerStars Hand #${id}: Hold'em No Limit (0.50/1.00) - 2026/09/12 14:00:00 CET`,`Table 'Trainer 6-max' 6-max Seat #${dealer+1} is the button`];
  for(let s=0;s<6;s++)lines.push(`Seat ${s+1}: ${names[s]} (100 in chips)`);
  lines.push(`${names[sb]}: posts small blind 0.50`,`${names[bb]}: posts big blind 1.00`,`*** HOLE CARDS ***`,`Dealt to ${TRAINER_HERO} [${hole[heroSeat].map(cardCode).join(" ")}]`);
  for(const pos of TRAINER_PREFLOP_ORDER){
    const s=trainerSeatForPosition({positions},pos),name=names[s];
    if(s===pfaSeat){const target=2.5,add=target-contrib[s];contrib[s]=target;lines.push(`${name}: raises 1.50 to 2.50`);lastAction[s]="RAISE 2,5 BB";stacks[s]-=add;}
    else if(s===callerSeat){const add=2.5-contrib[s];contrib[s]=2.5;lines.push(`${name}: calls ${trainerNum(add)}`);lastAction[s]=`CALL ${trainerNum(add)} BB`;stacks[s]-=add;}
    else{lines.push(`${name}: folds`);folded[s]=true;lastAction[s]="FOLD";}
  }
  const pot=contrib.reduce((s,x)=>s+x,0);
  lines.push(`*** FLOP *** [${runout.slice(0,3).map(cardCode).join(" ")}]`);
  const hand={id,dealerSeat:dealer,heroSeat,activeOppSeat:oppSeat,pfaSeat,callerSeat,heroRole,oppRole,positions,names,profiles,hole,runout,
    stacks,folded,lastAction,pot,street:"flop",boardCount:3,streetPaid:Array(6).fill(0),currentBet:0,lastRaise:1,raises:0,queue:[],historyLines:lines,ended:false,winner:"",showdown:false,awaitingHero:false,decisionNo:0};
  trainerStartStreet(hand,"flop",false);return hand;
}

function trainerPostRank(pos){return TRAINER_POSTFLOP_ORDER.indexOf(pos);}
function trainerStartStreet(hand,street,appendMarker=true){
  hand.street=street;hand.streetPaid=Array(6).fill(0);hand.currentBet=0;hand.lastRaise=1;hand.raises=0;
  if(street==="turn"){hand.boardCount=4;if(appendMarker)hand.historyLines.push(`*** TURN *** [${hand.runout.slice(0,3).map(cardCode).join(" ")}] [${cardCode(hand.runout[3])}]`);}
  if(street==="river"){hand.boardCount=5;if(appendMarker)hand.historyLines.push(`*** RIVER *** [${hand.runout.slice(0,4).map(cardCode).join(" ")}] [${cardCode(hand.runout[4])}]`);}
  const a=hand.heroSeat,b=hand.activeOppSeat,first=trainerPostRank(hand.positions[a])<trainerPostRank(hand.positions[b])?a:b,second=first===a?b:a;hand.queue=[first,second];
}
function trainerToCall(hand,seat){return Math.max(0,Number(hand.currentBet)-Number(hand.streetPaid[seat]||0));}
function trainerOther(hand,seat){return seat===hand.heroSeat?hand.activeOppSeat:hand.heroSeat;}
function trainerActionLine(hand,seat,kind,cost=0,target=null,raiseInc=null){
  const name=hand.names[seat],allin=cost>=hand.stacks[seat]-1e-8&&cost>0?" and is all-in":"";
  if(kind==="FOLD")return `${name}: folds`;
  if(kind==="CHECK")return `${name}: checks`;
  if(kind==="CALL")return `${name}: calls ${trainerNum(cost)}${allin}`;
  if(kind==="BET")return `${name}: bets ${trainerNum(cost)}${allin}`;
  return `${name}: raises ${trainerNum(raiseInc)} to ${trainerNum(target)}${allin}`;
}
function trainerApplyAction(hand,seat,kind,requestedCost=0){
  kind=String(kind).toUpperCase();const paid=Number(hand.streetPaid[seat]||0),toCall=trainerToCall(hand,seat),remaining=Number(hand.stacks[seat]||0),other=trainerOther(hand,seat);let cost=0,target=paid,raiseInc=0;
  if(kind==="FOLD"){hand.historyLines.push(trainerActionLine(hand,seat,"FOLD"));hand.folded[seat]=true;hand.lastAction[seat]="FOLD";trainerEndHand(hand,other,false);return;}
  if(kind==="CHECK"){if(toCall>1e-8)kind="CALL";else{hand.historyLines.push(trainerActionLine(hand,seat,"CHECK"));hand.lastAction[seat]="CHECK";return;}}
  if(kind==="CALL"){cost=Math.min(toCall,remaining);hand.historyLines.push(trainerActionLine(hand,seat,"CALL",cost));hand.stacks[seat]-=cost;hand.streetPaid[seat]+=cost;hand.pot+=cost;hand.lastAction[seat]=`CALL ${trainerFmtBB(cost)}`;hand.queue=[];return;}
  if(kind==="BET"&&toCall>1e-8)kind="RAISE";
  if(kind==="BET"){
    cost=trainerClamp(Number(requestedCost)||Math.max(1,.5*hand.pot),Math.min(1,remaining),remaining);target=paid+cost;
    hand.historyLines.push(trainerActionLine(hand,seat,"BET",cost,target,cost));hand.stacks[seat]-=cost;hand.streetPaid[seat]=target;hand.pot+=cost;hand.currentBet=target;hand.lastRaise=cost;hand.raises++;hand.lastAction[seat]=`BET ${trainerFmtBB(cost)}`;hand.queue=[other];return;
  }
  const minTarget=hand.currentBet+Math.max(hand.lastRaise,1),maxTarget=paid+remaining;target=Math.min(maxTarget,Math.max(minTarget,paid+(Number(requestedCost)||toCall+hand.lastRaise)));
  if(target<=hand.currentBet+1e-8){trainerApplyAction(hand,seat,"CALL",toCall);return;}
  cost=target-paid;raiseInc=target-hand.currentBet;hand.historyLines.push(trainerActionLine(hand,seat,"RAISE",cost,target,raiseInc));hand.stacks[seat]-=cost;hand.streetPaid[seat]=target;hand.pot+=cost;hand.currentBet=target;hand.lastRaise=raiseInc;hand.raises++;hand.lastAction[seat]=`RAISE à ${trainerFmtBB(target)}`;hand.queue=[other];
}

function trainerOpponentContext(hand){
  const s=hand.activeOppSeat,toCall=trainerToCall(hand,s),relative=trainerPostRank(hand.positions[s])>trainerPostRank(hand.positions[hand.heroSeat])?"IP":"OOP";
  return {profile:hand.profiles[s],street:hand.street,mode:toCall>1e-8?"FACING":"FREE",relative_position:relative,pot_type:"SRP",preflop_role:hand.oppRole,can_raise:hand.raises<2&&hand.stacks[s]>toCall+Math.max(hand.lastRaise,1)};
}
function trainerOpponentAct(hand){
  const s=hand.activeOppSeat,ctx=trainerOpponentContext(hand),toCall=trainerToCall(hand,s),action=trainerSampleOpponentAction(ctx);
  if(action==="FOLD")trainerApplyAction(hand,s,"FOLD");
  else if(action==="CHECK")trainerApplyAction(hand,s,"CHECK");
  else if(action==="CALL")trainerApplyAction(hand,s,"CALL");
  else{
    const ratio=trainerSampleSizing({...ctx,action:ctx.mode==="FACING"?"RAISE":"BET"}),pot0=hand.pot;
    let cost=Math.max(1,ratio*pot0);
    if(ctx.mode==="FACING")cost=Math.max(cost,toCall+hand.lastRaise);
    trainerApplyAction(hand,s,ctx.mode==="FACING"?"RAISE":"BET",cost);
  }
}
function trainerEndHand(hand,winnerSeat,showdown){
  hand.ended=true;hand.queue=[];hand.awaitingHero=false;hand.showdown=!!showdown;hand.winner=winnerSeat===null?"Partage":hand.names[winnerSeat];trainerState.session.hands++;
}
function trainerShowdown(hand){
  const heroScore=handScore([...hand.hole[hand.heroSeat],...hand.runout]),oppScore=handScore([...hand.hole[hand.activeOppSeat],...hand.runout]);
  trainerEndHand(hand,heroScore===oppScore?null:(heroScore>oppScore?hand.heroSeat:hand.activeOppSeat),true);
}
function trainerAdvanceStreetOrShowdown(hand){
  if(hand.stacks[hand.heroSeat]<=1e-8||hand.stacks[hand.activeOppSeat]<=1e-8){
    if(hand.street==="flop"){trainerStartStreet(hand,"turn",true);trainerStartStreet(hand,"river",true);}else if(hand.street==="turn")trainerStartStreet(hand,"river",true);
    trainerShowdown(hand);return;
  }
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
async function trainerWaitFor(fn,timeout=30000){const start=Date.now();while(!fn()){if(Date.now()-start>timeout)throw new Error("Timeout du moteur de recommandation.");await trainerSleep(40);}}
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
  await trainerWaitFor(()=>!state.reviewBatchBusy,30000);
  const hand=parsePokerStarsHand(text,"trainer");
  if(!hand)throw new Error("Le moteur n'a pas pu parser le spot Training.");
  const saved={hhHands:state.hhHands,selectedHand:state.selectedHand,hhMode:state.hhMode,replaySteps:state.replaySteps,replayIndex:state.replayIndex,popTrace:state.populationTraceCache,popRange:state.populationRangeCache,postTrace:state.postflopTraceCache,postRange:state.postflopRangeCache,actionEq:state.actionEquityCache,seatEq:state.seatEquityCache};
  const key=String(hand.id);
  try{
    state.populationTraceCache=Object.create(null);state.populationRangeCache=Object.create(null);state.postflopTraceCache=Object.create(null);state.postflopRangeCache=Object.create(null);state.actionEquityCache=Object.create(null);state.seatEquityCache=Object.create(null);
    state.replaySteps=[];state.replayIndex=0;state.hhHands=[hand];state.selectedHand=hand;state.hhMode=true;delete state.reviewScores[key];
    const plan=buildReviewBatchPlan(hand);plan.actions=plan.actions.filter(a=>a.actor===hand.heroName).slice(-1);if(!plan.actions.length)throw new Error("Aucune décision Hero analysable dans ce spot.");
    state.reviewBatchBusy=false;runReviewBatchPlan(plan);
    await trainerWaitFor(()=>!state.reviewBatchBusy&&!!state.reviewScores?.[key],45000);
    const score=state.reviewScores[key],detail=score?.details?.[score.details.length-1];if(!detail)throw new Error("Aucun verdict produit par le moteur.");return JSON.parse(JSON.stringify(detail));
  }finally{
    delete state.reviewScores[key];state.hhHands=saved.hhHands;state.selectedHand=saved.selectedHand;state.hhMode=saved.hhMode;state.replaySteps=saved.replaySteps;state.replayIndex=saved.replayIndex;state.populationTraceCache=saved.popTrace;state.populationRangeCache=saved.popRange;state.postflopTraceCache=saved.postTrace;state.postflopRangeCache=saved.postRange;state.actionEquityCache=saved.actionEq;state.seatEquityCache=saved.seatEq;
  }
}
function trainerPlaceholderLine(hand){const s=hand.heroSeat,toCall=trainerToCall(hand,s);return {kind:toCall>1e-8?"FOLD":"CHECK",line:trainerActionLine(hand,s,toCall>1e-8?"FOLD":"CHECK"),cost:0};}
async function trainerComputeRecommendation(){
  const hand=trainerState.hand;if(!hand||hand.ended||!hand.awaitingHero)return;
  trainerState.busy=true;trainerState.recommendation=null;trainerRenderStatus("Calcul de la recommandation Model A…","busy");trainerRender();
  try{const ph=trainerPlaceholderLine(hand),detail=await trainerTimedReviewText(trainerBuildReviewHH(hand,ph.line,ph.kind,0));trainerState.recommendation=detail;trainerRenderStatus(`À vous de jouer · calcul ${trainerState.perf.lastMs.toFixed(0)} ms.`);}
  catch(err){trainerRenderStatus(`Recommandation indisponible : ${err.message}`,"error");trainerState.recommendation={error:err.message};}
  finally{trainerState.busy=false;trainerRender();}
}
function trainerActualLine(hand,kind,cost){
  const s=hand.heroSeat,paid=hand.streetPaid[s],toCall=trainerToCall(hand,s),remaining=hand.stacks[s];kind=kind.toUpperCase();
  if(kind==="FOLD")return {line:trainerActionLine(hand,s,"FOLD"),kind,cost:0};
  if(kind==="CHECK")return {line:trainerActionLine(hand,s,"CHECK"),kind,cost:0};
  if(kind==="CALL"){const c=Math.min(toCall,remaining);return {line:trainerActionLine(hand,s,"CALL",c),kind,cost:c};}
  if(kind==="BET"){const c=trainerClamp(Number(cost)||1,Math.min(1,remaining),remaining);return {line:trainerActionLine(hand,s,"BET",c,paid+c,c),kind,cost:c};}
  const minTarget=hand.currentBet+Math.max(hand.lastRaise,1),target=Math.min(paid+remaining,Math.max(minTarget,paid+(Number(cost)||toCall+hand.lastRaise))),c=target-paid,inc=target-hand.currentBet;return {line:trainerActionLine(hand,s,"RAISE",c,target,inc),kind:"RAISE",cost:c};
}
function trainerDecisionClass(detail){const loss=Math.max(0,Number(detail?.lossBB)||0);if(detail?.withinNoise||loss<=.15)return "good";if(loss<=.5)return "close";return "bad";}
function trainerRecordDecision(detail,playedKind,playedCost){
  const hand=trainerState.hand,loss=Math.max(0,Number(detail?.lossBB)||0),cls=trainerDecisionClass(detail),row={handNo:trainerState.handNo,street:hand.street,position:hand.positions[hand.heroSeat],played:playedKind,cost:playedCost,bestLabel:detail?.bestLabel||"—",bestCostBB:Number.isFinite(Number(detail?.bestCostBB))?Number(detail.bestCostBB):null,bestEV:Number(detail?.bestEV),chosenEV:Number(detail?.chosenEV),lossBB:loss,withinNoise:!!detail?.withinNoise,cls};
  const s=trainerState.session;s.decisions++;s.lossBB+=loss;if(cls==="good")s.good++;else if(cls==="close")s.close++;else s.poor++;
  const key=`${row.position} · ${row.street}`;const b=s.breakdown[key]||(s.breakdown[key]={n:0,loss:0});b.n++;b.loss+=loss;trainerState.testLog.unshift(row);return row;
}
function trainerRecommendationKind(hand,rec){
  if(!hand||!rec||rec.error)return "";
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
  d.lossBB=loss;d.withinNoise=loss<=0.15;return d;
}
function trainerGuidedClickCost(kind){
  const raw=trainerSizingValue(),rec=trainerState.recommendation,hand=trainerState.hand,k=String(kind||"").toUpperCase();
  if(trainerState.mode!=="guided"||trainerState.sizingTouched||!rec||rec.error||!["BET","RAISE"].includes(k))return raw;
  if(trainerRecommendationKind(hand,rec)!==k)return raw;
  const best=Number(rec.bestCostBB);return Number.isFinite(best)?best:raw;
}
function trainerReuseBestAsPlayed(rec){
  const d=JSON.parse(JSON.stringify(rec));
  d.chosenEV=Number(d.bestEV);d.lossBB=0;d.withinNoise=true;
  trainerState.perf.reused++;return d;
}
async function trainerHeroAction(kind,cost=0){
  const hand=trainerState.hand;if(!hand||hand.ended||!hand.awaitingHero||trainerState.busy||trainerState.pauseAfterDecision)return;
  const guide=trainerState.mode==="guided"&&trainerState.recommendation&&!trainerState.recommendation.error?trainerState.recommendation:null;
  trainerState.busy=true;hand.awaitingHero=false;trainerRenderStatus("Évaluation de votre décision…","busy");trainerRender();
  let detail=null,row=null,actual=null;
  try{
    actual=trainerActualLine(hand,kind,cost);
    if(guide&&trainerRecommendationMatchesAction(guide,actual,hand)){
      detail=trainerReuseBestAsPlayed(guide);
    }else{
      const played=await trainerTimedReviewText(trainerBuildReviewHH(hand,actual.line,actual.kind,actual.cost));
      detail=guide?trainerGuideAnchoredDetail(guide,played):played;
    }
    trainerState.recommendation=guide||detail;row=trainerRecordDecision(detail,actual.kind,actual.cost);
  }
  catch(err){trainerRenderStatus(`Décision jouée, mais verdict indisponible : ${err.message}`,"error");}
  trainerApplyAction(hand,hand.heroSeat,kind,cost);trainerState.feedback=detail?{detail,row}:null;trainerState.busy=false;
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
      trainerRender();
      if(trainerState.mode==="guided")await trainerComputeRecommendation();
      else trainerRenderStatus("À vous de jouer · recommandation calculée après votre action.");
      return;
    }
    trainerRenderStatus(`${hand.names[seat]} réfléchit…`,"busy");trainerRender();await trainerSleep(TRAINER_DELAYS.opponentThink);trainerOpponentAct(hand);trainerRender();await trainerSleep(TRAINER_DELAYS.opponentSettle);
  }
  if(hand.ended)trainerRenderStatus(`Main terminée · ${hand.winner}.`);
  trainerRender();
}
async function trainerContinue(){trainerState.pauseAfterDecision=false;trainerState.feedback=null;trainerRender();await trainerAdvance();}
async function trainerNewHand(){
  if(trainerState.busy)return;if(!await trainerEnsureModels())return;
  trainerState.feedback=null;trainerState.recommendation=null;trainerState.pauseAfterDecision=false;trainerState.testLog=[];trainerState.hand=trainerBuildHand();trainerRenderStatus("Nouvelle main · préflop SRP simulé, entraînement à partir du flop.");trainerRender();await trainerAdvance();
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
  trainerTable.innerHTML=`<div class="trainer-table-wrap"><div class="poker-table"><div class="table-center"><div class="table-pot">Pot<br><b>${escapeHtml(trainerFmtBB(h.pot))}</b></div><div class="table-board">${trainerBoardHtml(h)}</div><div class="tiny" style="margin-top:8px">${escapeHtml(h.street.toUpperCase())} · SRP · ${escapeHtml(h.heroRole==="PFA"?"Hero PFA":"Hero caller")} · range Custom</div></div>${replayDealerButtonHtml({buttonSeat:h.dealerSeat+1})}${trainerBetSpotsHtml(h)}${Array.from({length:6},(_,s)=>trainerSeatHtml(h,s)).join("")}</div></div>`;
}
function trainerBestText(rec){
  if(!rec||rec.error)return "—";
  const label=String(rec.bestLabel||"—"),kind=trainerRecommendationKind(trainerState.hand,rec),upper=label.toUpperCase();
  const action=kind&&!upper.startsWith(kind)?`${kind} · `:"",cost=Number(rec.bestCostBB),size=Number.isFinite(cost)?` · ${trainerFmtBB(cost)}`:"";
  return `${action}${label}${size}`;
}
function trainerRenderRecommendation(){
  if(!trainerRecommendation)return;const h=trainerState.hand,rec=trainerState.recommendation;
  if(!h||h.ended){trainerRecommendation.className="trainer-recommendation hidden-answer";trainerRecommendation.innerHTML='<div class="trainer-rec-label">Recommandation</div><div class="trainer-rec-main">—</div>';return;}
  const canShow=trainerState.mode==="guided";
  if(trainerState.busy&&!rec){trainerRecommendation.className="trainer-recommendation hidden-answer";trainerRecommendation.innerHTML='<div class="trainer-rec-label">Moteur</div><div class="trainer-rec-main">Calcul…</div>';return;}
  if(!canShow){trainerRecommendation.className="trainer-recommendation hidden-answer";trainerRecommendation.innerHTML=`<div class="trainer-rec-label">${trainerState.mode==="test"?"Mode Test":"Décidez d'abord"}</div><div class="trainer-rec-main">Réponse masquée</div><div class="trainer-rec-ev">${trainerState.mode==="test"?"Le bilan apparaît en fin de main.":"Le feedback apparaît après votre action."}</div>`;return;}
  trainerRecommendation.className="trainer-recommendation";trainerRecommendation.innerHTML=`<div class="trainer-rec-label">Action recommandée · EV finale</div><div class="trainer-rec-main">${escapeHtml(trainerBestText(rec))}</div><div class="trainer-rec-ev">EV ${Number.isFinite(Number(rec?.bestEV))?escapeHtml(trainerFmtBB(rec.bestEV)):"—"}</div>`;
}
function trainerRenderFeedback(){
  if(!trainerFeedback)return;const f=trainerState.feedback,h=trainerState.hand;
  if(trainerState.mode==="test"&&!h?.ended){trainerFeedback.className="trainer-feedback";trainerFeedback.innerHTML='<div class="trainer-feedback-title">Mode Test</div><div class="trainer-feedback-body">Aucun feedback avant la fin de la main.</div>';return;}
  if(!f){
    if(h?.ended&&trainerState.mode==="test"){const loss=trainerState.testLog.reduce((s,x)=>s+x.lossBB,0);trainerFeedback.className="trainer-feedback";trainerFeedback.innerHTML=`<div class="trainer-feedback-title">Bilan de la main</div><div class="trainer-feedback-body">${trainerState.testLog.length} décision(s) · perte EV cumulée <b>${escapeHtml(trainerFmtBB(loss))}</b>.</div>`;return;}
    trainerFeedback.className="trainer-feedback";trainerFeedback.innerHTML='<div class="trainer-feedback-title">Feedback</div><div class="trainer-feedback-body">Jouez une décision Hero pour obtenir le verdict.</div>';return;
  }
  const d=f.detail,r=f.row,cls=r?.cls||"close",title=cls==="good"?"Bonne décision":cls==="close"?"Décision proche":"Erreur coûteuse";
  trainerFeedback.className=`trainer-feedback ${cls}`;trainerFeedback.innerHTML=`<div class="trainer-feedback-title">${escapeHtml(title)}</div><div class="trainer-feedback-body">Joué : <b>${escapeHtml(r.played)}${r.cost>0?` · ${escapeHtml(trainerFmtBB(r.cost))}`:""}</b><br>Recommandé : <b>${escapeHtml(trainerBestText(d))}</b><br>EV jouée : <b>${Number.isFinite(Number(d.chosenEV))?escapeHtml(trainerFmtBB(d.chosenEV)):"—"}</b> · meilleure EV : <b>${Number.isFinite(Number(d.bestEV))?escapeHtml(trainerFmtBB(d.bestEV)):"—"}</b><br>Perte EV retenue : <b>${escapeHtml(trainerFmtBB(r.lossBB))}</b>${r.withinNoise?" · dans le bruit Monte-Carlo":""}.</div>`;
}
function trainerSizingValue(){return Math.max(0,Number(document.getElementById("trainerSizingInput")?.value)||0);}
function trainerSetSizing(x){const input=document.getElementById("trainerSizingInput");if(input)input.value=trainerNum(x);}
function trainerRenderControls(){
  if(!trainerControls)return;const h=trainerState.hand;
  if(!h){trainerControls.innerHTML="";return;}
  if(h.ended){trainerControls.innerHTML=`<div class="trainer-hand-ended">Main terminée · <b>${escapeHtml(h.winner)}</b>${h.showdown?" · showdown":""}. Cliquez sur « Nouvelle main » pour continuer.</div>`;return;}
  if(trainerState.pauseAfterDecision){trainerControls.innerHTML='<div class="trainer-decision-box"><div class="trainer-decision-head"><div class="trainer-decision-title">Feedback</div><button type="button" id="trainerInlineContinue" class="primary">Continuer la main</button></div></div>';document.getElementById("trainerInlineContinue")?.addEventListener("click",trainerContinue);return;}
  if(!h.awaitingHero){trainerControls.innerHTML='<div class="trainer-decision-box"><div class="trainer-decision-title">Action adverse en cours…</div></div>';return;}
  const toCall=trainerToCall(h,h.heroSeat),legal=toCall>1e-8?["FOLD","CALL","RAISE"]:["CHECK","BET"],minAgg=toCall>1e-8?toCall+h.lastRaise:Math.max(1,.33*h.pot),recCost=Number(trainerState.recommendation?.bestCostBB);
  trainerControls.innerHTML=`<div class="trainer-decision-box"><div class="trainer-decision-head"><div><div class="trainer-decision-title">À vous · ${escapeHtml(h.positions[h.heroSeat])} · ${escapeHtml(h.street.toUpperCase())}</div><div class="trainer-context">Pot ${escapeHtml(trainerFmtBB(h.pot))} · ${toCall>0?`à payer ${escapeHtml(trainerFmtBB(toCall))}`:"check possible"} · stack ${escapeHtml(trainerFmtBB(h.stacks[h.heroSeat]))}</div></div></div><div class="trainer-actions">${legal.map(a=>`<button type="button" class="${a==="FOLD"?"danger secondary":a==="CHECK"||a==="CALL"?"secondary":"primary"}" data-trainer-action="${a}">${a}</button>`).join("")}<div class="trainer-sizing"><div class="field"><label for="trainerSizingInput">Coût ajouté / mise (BB)</label><input id="trainerSizingInput" type="number" min="0" step="0.1" value="${trainerNum(Number.isFinite(recCost)?recCost:minAgg)}"></div><div class="trainer-size-presets"><button type="button" class="secondary" data-size=".5">½ pot</button><button type="button" class="secondary" data-size=".75">¾ pot</button><button type="button" class="secondary" data-size="1">Pot</button><button type="button" class="secondary" data-size="allin">All-in</button></div></div></div></div>`;
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
  if(!trainerTestLog)return;if(trainerState.mode!=="test"){trainerTestLog.innerHTML="";return;}const h=trainerState.hand;if(!h?.ended){trainerTestLog.innerHTML='<div class="tiny">Les décisions resteront masquées jusqu’à la fin de la main.</div>';return;}trainerTestLog.innerHTML=trainerState.testLog.map(r=>`<div class="trainer-test-row">${escapeHtml(r.position)} · ${escapeHtml(r.street)} · joué ${escapeHtml(r.played)}${r.cost?` ${escapeHtml(trainerFmtBB(r.cost))}`:""}<br>Reco <b>${escapeHtml(r.bestLabel)}${r.bestCostBB!==null?` · ${escapeHtml(trainerFmtBB(r.bestCostBB))}`:""}</b> · perte ${escapeHtml(trainerFmtBB(r.lossBB))}</div>`).join("")||'<div class="tiny">Aucune décision Hero.</div>';
}
function trainerRenderStatus(text,cls=""){if(!trainerStatus)return;trainerStatus.textContent=text||"";trainerStatus.className=`trainer-status${cls?` ${cls}`:""}`;}
function trainerRender(){trainerRenderTable();trainerRenderControls();trainerRenderRecommendation();trainerRenderFeedback();trainerRenderStats();trainerRenderProfiles();trainerRenderTestLog();trainerNewHandBtn&&(trainerNewHandBtn.disabled=trainerState.busy||trainerState.loading);trainerContinueBtn&&(trainerContinueBtn.style.display=trainerState.pauseAfterDecision?"inline-block":"none");}

async function trainerOpen(){
  trainerState.open=true;state.appView="main";updateAppView();mainPage?.classList.add("mode-hidden");replayerPage?.classList.add("mode-hidden");trainerPage?.classList.remove("mode-hidden");trainerPage?.setAttribute("aria-hidden","false");document.body.classList.add("trainer-view-open");if(quickNav)quickNav.style.display="none";window.scrollTo({top:0,behavior:"auto"});trainerRender();if(await trainerEnsureModels()){if(!trainerState.hand)await trainerNewHand();}
}
function trainerClose(){trainerState.open=false;trainerPage?.classList.add("mode-hidden");trainerPage?.setAttribute("aria-hidden","true");document.body.classList.remove("trainer-view-open");if(quickNav)quickNav.style.display="";state.appView="main";updateAppView();window.scrollTo({top:0,behavior:"auto"});}
function trainerSetMode(mode){if(!["guided","training","test"].includes(mode))return;trainerState.mode=mode;trainerState.feedback=null;document.querySelectorAll("[data-trainer-mode]").forEach(b=>b.classList.toggle("active",b.dataset.trainerMode===mode));const needGuide=mode==="guided"&&trainerState.hand?.awaitingHero&&!trainerState.recommendation&&!trainerState.busy;trainerRender();if(needGuide)void trainerComputeRecommendation();}

trainerOpenBtn?.addEventListener("click",trainerOpen);
trainerNavLink?.addEventListener("click",e=>{e.preventDefault();e.stopImmediatePropagation();trainerOpen();},{capture:true});
trainerBackBtn?.addEventListener("click",trainerClose);
trainerNewHandBtn?.addEventListener("click",trainerNewHand);
trainerContinueBtn?.addEventListener("click",trainerContinue);
document.querySelectorAll("[data-trainer-mode]").forEach(b=>b.addEventListener("click",()=>trainerSetMode(b.dataset.trainerMode)));
trainerScheduleWarmup();
trainerRenderStatus("Ouvrez une session pour charger les modèles promus.");trainerRender();

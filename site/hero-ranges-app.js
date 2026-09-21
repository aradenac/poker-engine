"use strict";

const HeroRanges=window.PokerHeroRanges;
const Migration=window.PokerHeroRangeMigration;
const Resolver=window.PokerHeroStrategyResolver;
const STORAGE_KEY="poker.hero.range.repository.v1";
const DEFAULT_POPULATION="pokerstars_nlhe_100-200_zoom_play_6max_v1";
const $=id=>document.getElementById(id);
const els={
  import:$("heroRangeImport"),export:$("heroRangeExport"),sourceBadge:$("sourceBadge"),sourceStatus:$("sourceStatus"),
  sourceRange:$("sourceRangeSelect"),sourcePosition:$("sourcePositionSelect"),sourceHandDetail:$("sourceHandDetail"),
  population:$("populationInput"),position:$("positionSelect"),stack:$("stackInput"),spot:$("spotSelect"),contextStatus:$("contextStatus"),
  bindingBadge:$("populationBindingBadge"),strategySource:$("strategySourceBadge"),overrideBadge:$("overrideBadge"),
  resolutionStatus:$("resolutionStatus"),migrationStatus:$("migrationStatus"),
  grid:$("heroGrid"),gridSummary:$("gridSummary"),selectionSummary:$("selectionSummary"),title:$("selectedHandTitle"),state:$("selectedHandState"),
  comparison:$("comparisonSummary"),actions:$("actionEditor"),actionTotal:$("actionTotal"),notes:$("handNotes"),save:$("saveHand"),
  undefine:$("undefineHand"),quickAction:$("quickAction"),quickApply:$("quickApply"),handStatus:$("handStatus"),
  stats:$("repositoryStats"),contextList:$("contextList")
};
let migrationReport=null;
let repo=restoreRepository();
let selectedHand="AA";
let selectionAnchor="AA";
let selectedHands=new Set(["AA"]);

// The editor is population-bound. The persisted repository keeps its own
// `defaults.population_id`; the deep link may request another population but the
// runtime never relabels a repository, so an incompatible context is surfaced as
// an explicit fail-closed state instead of being treated as the population
// strategy.
function deepLinkPopulation(){try{return String(new URLSearchParams(location.search||"").get("population")||"").trim();}catch(_){return "";}}
function bootstrapPopulationId(){return deepLinkPopulation()||DEFAULT_POPULATION;}
function restoreRepository(){
  const active=bootstrapPopulationId();
  // Safe migration at load: additive, reversible and idempotent. It imports a
  // legacy range-folder payload losslessly as a repository before validating it,
  // snapshots the exact pre-migration bytes under the previous key, and never
  // relabels a foreign population.
  if(Migration&&typeof Migration.migrateStorage==="function"){
    try{
      migrationReport=Migration.migrateStorage(localStorage,{activePopulationId:active});
      if(migrationReport&&migrationReport.repository)return migrationReport.repository;
    }catch(err){
      migrationReport={status:"UNAVAILABLE",reason_codes:["MIGRATION_FAILED"],error:String(err&&err.message||err),rollback_available:false,inherited_population_ids:[]};
    }
  }
  try{const raw=localStorage.getItem(STORAGE_KEY);if(raw)return HeroRanges.importDocument(JSON.parse(raw));}catch(_){}
  return HeroRanges.emptyRepository({populationId:active});
}
function persist(){
  HeroRanges.validateRepository(repo);
  if(Migration&&typeof Migration.persistRepository==="function"){Migration.persistRepository(localStorage,repo);return;}
  localStorage.setItem(STORAGE_KEY,JSON.stringify(repo));
}
function setStatus(el,message,error=false){el.textContent=message;el.classList.toggle("error",!!error);}
function context(){return HeroRanges.normalizeContext({population_id:els.population.value,table_size:6,position:els.position.value,effective_stack_bb:Number(els.stack.value),spot:els.spot.value});}
function repositoryPopulationId(){return HeroRanges.repositoryPopulationId(repo);}
function populationBound(){try{return HeroRanges.populationBound(repo,context());}catch(_){return {population_id:null,repository_population_id:repositoryPopulationId(),compatible:false};}}
function requirePopulationBinding(){
  const bound=populationBound();
  if(!bound.compatible)throw new Error(`contexte ${bound.population_id||"—"} incompatible avec la population liée ${bound.repository_population_id||"—"} : la stratégie population et son override ne peuvent pas être édités hors population`);
  return bound;
}
function currentNode(){try{return repo.contexts[HeroRanges.contextKey(context())]||null;}catch(_){return null;}}
function strategy(hand,layer){return HeroRanges.getHandStrategy(repo,context(),hand,{layer});}
function currentPersonal(){return strategy(selectedHand,"personal");}
function currentCalculated(){return strategy(selectedHand,"calculated");}
function selectedList(){return HeroRanges.HAND_CLASSES.filter(hand=>selectedHands.has(hand));}

// Population-bound resolution of the active strategy. The resolver is
// fail-closed: an un-admitted calculated layer, an inactive candidate and a
// foreign population all resolve to an explicit UNAVAILABLE / incompatible
// state, and a personal override is only ever reported as PERSONAL_OVERRIDE.
function currentResolution(){
  if(!Resolver||typeof Resolver.resolveHeroStrategy!=="function")return null;
  try{const c=context();return Resolver.resolveHeroStrategy({population_id:c.population_id,repository:repo,context:c});}
  catch(_){return null;}
}
function layerInfo(kind){
  const node=currentNode(),layer=node?.layers?.[kind]||null,hands=layer?.hands&&typeof layer.hands==="object"?layer.hands:{};
  return {defined:Object.keys(hands).length,version:layer?.version==null?null:String(layer.version),provenance:layer?.provenance||null};
}
function migrationSummary(){
  if(!migrationReport)return "Migration non exécutée.";
  const status=migrationReport.status||"UNKNOWN";
  const rollback=migrationReport.rollback_available?"copie de retour disponible":"copie de retour indisponible";
  const inherited=(migrationReport.inherited_population_ids||[]).length;
  return `Migration du stockage : ${status} · ${rollback} · populations héritées ${inherited}.`;
}

function initOptions(){
  els.position.innerHTML=HeroRanges.POSITIONS.map(p=>`<option>${p}</option>`).join("");els.position.value="BTN";
  els.spot.innerHTML=HeroRanges.SPOTS.map(s=>`<option>${s}</option>`).join("");
  els.quickAction.innerHTML=HeroRanges.ACTIONS.map(a=>`<option>${a}</option>`).join("");els.quickAction.value="OPEN";
  if(repo.defaults?.population_id)els.population.value=repo.defaults.population_id;
  if(repo.defaults?.effective_stack_bb)els.stack.value=repo.defaults.effective_stack_bb;
}
function canonicalHandClass(value){
  const wanted=String(value||"").trim().toUpperCase();
  if(!wanted)return null;
  return HeroRanges.HAND_CLASSES.find(hand=>hand.toUpperCase()===wanted)||null;
}
function applyDeepLink(){
  const params=new URLSearchParams(location.search||"");
  const population=String(params.get("population")||"").trim();if(population)els.population.value=population;
  const position=String(params.get("position")||"").trim().toUpperCase();if(HeroRanges.POSITIONS.includes(position))els.position.value=position;
  const spot=String(params.get("spot")||"").trim().toUpperCase();if(HeroRanges.SPOTS.includes(spot))els.spot.value=spot;
  const stack=Number(params.get("stack"));if(Number.isFinite(stack)&&stack>0)els.stack.value=String(stack);
  const hand=canonicalHandClass(params.get("hand"));if(hand){selectedHand=hand;selectionAnchor=hand;selectedHands=new Set([hand]);}
}

function legacyEntries(){return HeroRanges.legacyRanges(repo.source?.range_folder);}
function sourceSelection(){
  const entries=legacyEntries(),r=entries[Number(els.sourceRange.value)||0]?.range||null;
  const positions=r?.positions||[],p=positions[Number(els.sourcePosition.value)||0]||null;
  return {range:r,position:p};
}
function sourceHand(hand){
  const {position}=sourceSelection();return (position?.hands||[]).find(h=>String(h.hand||"").toUpperCase()===hand.toUpperCase())||null;
}
function sourceFrequency(hand){
  const row=sourceHand(hand);if(!row)return null;let f=0;
  for(const a of (row.actions||[])){const name=String(a?.name||"").toUpperCase(),v=Number(a?.frequency)||0;if(name!=="FOLD"&&v>0)f+=v;}
  return Math.max(0,Math.min(100,f));
}
function escapeHtml(s){return String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#039;"}[c]));}
function renderSourceBrowser(){
  const entries=legacyEntries();
  els.sourceBadge.textContent=repo.source?.preserved_verbatim?"source importée préservée":"aucune source importée";
  setStatus(els.sourceStatus,repo.source?.preserved_verbatim?`${entries.length} source(s) importée(s) conservée(s) verbatim. Les stratégies personnelles sont stockées à part.`:"Aucune range source importée. Les contextes Hero restent éditables.");
  const oldRange=Number(els.sourceRange.value)||0;
  els.sourceRange.innerHTML=entries.length?entries.map((x,i)=>`<option value="${i}">${escapeHtml(`${x.path} / ${x.range?.name||"Source importée"}`)}</option>`).join(""):'<option value="0">—</option>';
  els.sourceRange.value=String(Math.min(oldRange,Math.max(0,entries.length-1)));
  const range=entries[Number(els.sourceRange.value)||0]?.range,positions=range?.positions||[],oldPos=Number(els.sourcePosition.value)||0;
  els.sourcePosition.innerHTML=positions.length?positions.map((p,i)=>`<option value="${i}">${escapeHtml(p.position||`Position ${i+1}`)}</option>`).join(""):'<option value="0">—</option>';
  els.sourcePosition.value=String(Math.min(oldPos,Math.max(0,positions.length-1)));
  renderSourceHandDetail();
}
function renderSourceHandDetail(){
  const row=sourceHand(selectedHand);els.sourceHandDetail.textContent=row?`${selectedHand}\n${JSON.stringify(row.actions||[],null,2)}`:`${selectedHand} : absent de la position de la range source importée sélectionnée.`;
}

function nearly(a,b){return Math.abs(Number(a||0)-Number(b||0))<1e-8;}
function actionsEqual(a,b){
  const keys=new Set([...Object.keys(a||{}),...Object.keys(b||{})]);
  for(const key of keys)if(!nearly(a?.[key],b?.[key]))return false;
  return true;
}
function sizingListEqual(a,b){
  const left=(a||[]).map(x=>({target:Number(x.target_total_bb),prob:Number(x.probability)})).sort((x,y)=>x.target-y.target||x.prob-y.prob);
  const right=(b||[]).map(x=>({target:Number(x.target_total_bb),prob:Number(x.probability)})).sort((x,y)=>x.target-y.target||x.prob-y.prob);
  if(left.length!==right.length)return false;
  return left.every((x,i)=>nearly(x.target,right[i].target)&&nearly(x.prob,right[i].prob));
}
function sizingsEqual(a,b){
  const keys=new Set([...Object.keys(a||{}),...Object.keys(b||{})]);
  for(const key of keys)if(!sizingListEqual(a?.[key],b?.[key]))return false;
  return true;
}
function comparisonKind(personal,calculated){
  if(!personal&&!calculated)return "undefined";
  if(!personal)return "calculated-only";
  if(!calculated)return "personal-only";
  if(!actionsEqual(personal.actions,calculated.actions))return "action-mismatch";
  if(!sizingsEqual(personal.sizings,calculated.sizings))return "sizing-mismatch";
  return "identical";
}
const COMP_LABELS={
  "undefined":"non définie","calculated-only":"stratégie calculée seule","personal-only":"stratégie personnelle seule",
  "identical":"identique","action-mismatch":"désaccord action","sizing-mismatch":"désaccord sizing"
};
const COMP_MINI={"undefined":"","calculated-only":"C","personal-only":"P","identical":"=","action-mismatch":"A≠","sizing-mismatch":"S≠"};

function selectHand(hand,event){
  if(event.shiftKey){
    const a=HeroRanges.HAND_CLASSES.indexOf(selectionAnchor),b=HeroRanges.HAND_CLASSES.indexOf(hand);
    const [lo,hi]=a<=b?[a,b]:[b,a];
    selectedHands=new Set(HeroRanges.HAND_CLASSES.slice(lo,hi+1));
  }else if(event.ctrlKey||event.metaKey){
    if(selectedHands.has(hand)&&selectedHands.size>1)selectedHands.delete(hand);else selectedHands.add(hand);
    selectionAnchor=hand;
  }else{
    selectedHands=new Set([hand]);selectionAnchor=hand;
  }
  selectedHand=hand;
  if(!selectedHands.has(selectedHand))selectedHand=selectedList()[0]||hand;
  renderAll();
}
function selectCategory(kind){
  let list=[];
  if(kind==="all")list=[...HeroRanges.HAND_CLASSES];
  else if(kind==="pairs")list=HeroRanges.HAND_CLASSES.filter(h=>h.length===2);
  else if(kind==="suited")list=HeroRanges.HAND_CLASSES.filter(h=>h.endsWith("s"));
  else if(kind==="offsuit")list=HeroRanges.HAND_CLASSES.filter(h=>h.endsWith("o"));
  else list=[selectedHand];
  selectedHands=new Set(list);selectedHand=list.includes(selectedHand)?selectedHand:list[0];selectionAnchor=selectedHand;renderAll();
}

function renderGrid(){
  let personal=0,calculated=0,source=0,diffs=0;
  els.grid.innerHTML=HeroRanges.HAND_CLASSES.map(hand=>{
    const p=strategy(hand,"personal"),c=strategy(hand,"calculated"),sf=sourceFrequency(hand),kind=comparisonKind(p,c);
    if(p)personal++;if(c)calculated++;if(sf!=null)source++;if(kind==="action-mismatch"||kind==="sizing-mismatch")diffs++;
    const cls=["hand-cell",kind,sf!=null?"source-only":"",selectedHands.has(hand)?"selected":""].filter(Boolean).join(" ");
    const sourceKind=p?"PERSONAL_OVERRIDE":c?"CALCULATED":"NONE";
    return `<button type="button" class="${cls}" data-hand="${hand}" data-comparison="${kind}" data-source="${sourceKind}"${p?' data-override="true"':""} title="${escapeHtml(COMP_LABELS[kind])}">${hand}<span class="mini">${COMP_MINI[kind]}</span></button>`;
  }).join("");
  const count=selectedHands.size;
  els.selectionSummary.textContent=`${count} main${count>1?"s":""} sélectionnée${count>1?"s":""}`;
  els.gridSummary.textContent=`sélection ${count} · stratégie personnelle ${personal} · stratégie calculée ${calculated} · Δ ${diffs} · source importée ${source}`;
  for(const b of els.grid.querySelectorAll(".hand-cell"))b.addEventListener("click",event=>selectHand(b.dataset.hand,event));
}

function formatPct(v){return `${Math.round(Number(v||0)*10000)/100}%`;}
function strategyLine(value){
  if(!value)return "—";
  const actions=Object.entries(value.actions||{}).map(([name,p])=>`${name} ${formatPct(p)}`).join(" · ")||"—";
  const sizes=Object.entries(value.sizings||{}).map(([name,list])=>`${name}: ${list.map(x=>`${x.target_total_bb} BB @ ${formatPct(x.probability)}`).join(" / ")}`).join(" · ");
  return sizes?`${actions}<br>${sizes}`:actions;
}
function renderComparison(){
  const hands=selectedList();
  const counts={};
  for(const hand of hands){const kind=comparisonKind(strategy(hand,"personal"),strategy(hand,"calculated"));counts[kind]=(counts[kind]||0)+1;}
  const rollup=Object.entries(counts).map(([kind,n])=>`${COMP_LABELS[kind]}: ${n}`).join(" · ");
  const p=currentPersonal(),c=currentCalculated(),kind=comparisonKind(p,c);
  els.comparison.innerHTML=
    `<div class="compare-card calculated" data-layer="calculated" data-source="CALCULATED"><strong>Stratégie calculée · ${escapeHtml(selectedHand)}</strong><span>${strategyLine(c)}</span></div>`+
    `<div class="compare-card personal override" data-layer="personal" data-source="${p?"PERSONAL_OVERRIDE":"NONE"}"><strong>Stratégie personnelle · ${escapeHtml(selectedHand)} <span class="override-tag">override personnel</span></strong><span>${strategyLine(p)}</span></div>`+
    `<div class="compare-rollup">État actif : <strong>${escapeHtml(COMP_LABELS[kind])}</strong>${hands.length>1?` · sélection : ${escapeHtml(rollup)}`:""}</div>`;
}

function sizeRowHtml(action,row={target_total_bb:"",probability:""}){
  const target=row.target_total_bb==null?"":row.target_total_bb;
  const pct=row.probability===""?"":Math.round(Number(row.probability)*10000)/100;
  return `<div class="sizing-row">
    <label class="sizing-input"><span>BB</span><input type="number" min="0.01" step="0.1" data-size-target="${action}" value="${escapeHtml(target)}" aria-label="Sizing ${action} en BB"></label>
    <label class="sizing-input"><span>%</span><input type="number" min="0" max="100" step="1" data-size-prob="${action}" value="${escapeHtml(pct)}" aria-label="Fréquence sizing ${action}"></label>
    <button type="button" class="remove-size" data-remove-size="${action}" aria-label="Retirer ce sizing">×</button>
  </div>`;
}
function sizingEditorHtml(action,list){
  return `<div class="sizing-editor" data-sizes-for="${action}">
    <div class="sizing-head"><span>Sizings structurés</span><span class="sum-badge" data-sizing-total="${action}">aucun</span></div>
    <div class="sizing-rows">${(list||[]).map(row=>sizeRowHtml(action,row)).join("")}</div>
    <button type="button" class="add-size" data-add-size="${action}">+ Ajouter un sizing</button>
  </div>`;
}
function renderActionEditor(){
  const personal=currentPersonal(),calculated=currentCalculated(),strategyValue=personal||calculated;
  const count=selectedHands.size;
  els.title.textContent=count===1?selectedHand:`${count} mains`;
  els.state.textContent=count===1?COMP_LABELS[comparisonKind(personal,calculated)]:"édition groupée";
  els.actions.innerHTML=HeroRanges.ACTIONS.map(action=>{
    const pct=strategyValue?Math.round((strategyValue.actions?.[action]||0)*10000)/100:0;
    return `<div class="action-card">
      <div class="action-head"><span class="name">${action}</span><label>Fréquence %<input data-action-prob="${action}" type="number" min="0" max="100" step="1" value="${pct}" aria-label="Fréquence ${action}"></label></div>
      ${sizingEditorHtml(action,strategyValue?.sizings?.[action]||[])}
    </div>`;
  }).join("");
  els.notes.value=strategyValue?.notes||"";
  const origin=personal?"override personnel (couche personnelle)":calculated?"stratégie calculée (population)":"aucune stratégie";
  setStatus(els.handStatus,count===1?`Édition de ${selectedHand} à partir de la ${origin}.`:`Édition groupée de ${count} mains. Les valeurs affichées proviennent de ${selectedHand}; seules les mains sélectionnées seront modifiées.`);
  refreshEditorValidation();
}

function setSumBadge(el,total,hasRows=true){
  if(!el)return;
  if(!hasRows){el.textContent="aucun";el.classList.remove("ok","bad");return;}
  const ok=Math.abs(total-100)<1e-6;
  el.textContent=`${Math.round(total*100)/100} %`;
  el.classList.toggle("ok",ok);el.classList.toggle("bad",!ok);
}
function refreshEditorValidation(){
  let actionTotal=0;
  for(const input of els.actions.querySelectorAll("[data-action-prob]"))actionTotal+=Number(input.value)||0;
  setSumBadge(els.actionTotal,actionTotal,true);
  for(const action of HeroRanges.ACTIONS){
    const rows=[...els.actions.querySelectorAll(`[data-sizes-for="${action}"] .sizing-row`)];
    const total=rows.reduce((sum,row)=>sum+(Number(row.querySelector("[data-size-prob]").value)||0),0);
    setSumBadge(els.actions.querySelector(`[data-sizing-total="${action}"]`),total,rows.length>0);
  }
}
function readSizing(action){
  const rows=[...els.actions.querySelectorAll(`[data-sizes-for="${action}"] .sizing-row`)];
  const out=[];let total=0;
  for(const row of rows){
    const targetText=row.querySelector("[data-size-target]").value.trim(),pctText=row.querySelector("[data-size-prob]").value.trim();
    if(!targetText&&!pctText)continue;
    const target=Number(targetText),pct=Number(pctText);
    if(!Number.isFinite(target)||target<=0)throw new Error(`${action}: sizing BB invalide`);
    if(!Number.isFinite(pct)||pct<=0||pct>100)throw new Error(`${action}: fréquence de sizing hors ]0–100]`);
    total+=pct;out.push({target_total_bb:target,probability:pct/100});
  }
  if(out.length&&Math.abs(total-100)>1e-6)throw new Error(`${action}: les fréquences de sizing doivent totaliser 100 % (actuellement ${total} %)`);
  return out.length?out:null;
}
function readEditorStrategy(){
  const actions={},sizings={};let total=0;
  for(const action of HeroRanges.ACTIONS){
    const pct=Number(els.actions.querySelector(`[data-action-prob="${action}"]`).value)||0;
    if(pct<0||pct>100)throw new Error(`${action}: fréquence hors 0–100 %`);
    if(pct>0){
      actions[action]=pct/100;total+=pct;
      const sizing=readSizing(action);if(sizing)sizings[action]=sizing;
    }
  }
  if(Math.abs(total-100)>1e-6)throw new Error(`la distribution doit totaliser 100 % (actuellement ${total} %)`);
  return {actions,sizings,notes:els.notes.value||""};
}

function renderRepository(){
  const stats=HeroRanges.repositoryStats(repo);els.stats.textContent=`${stats.contexts} contexte(s) · stratégie personnelle ${stats.personal_defined_hands} · stratégie calculée ${stats.calculated_defined_hands}`;
  const lines=[];
  for(const node of Object.values(repo.contexts)){
    const p=Object.keys(node.layers.personal.hands||{}).length,c=Object.keys(node.layers.calculated.hands||{}).length;
    lines.push(`${node.context.position} · ${node.context.effective_stack_bb} BB · ${node.context.spot} · stratégie personnelle ${p}/169 · stratégie calculée ${c}/169`);
  }
  els.contextList.textContent=lines.length?lines.join("\n"):"Aucun contexte défini.";
}
function renderContextStatus(){
  try{const c=context(),node=currentNode(),p=Object.keys(node?.layers?.personal?.hands||{}).length,calc=Object.keys(node?.layers?.calculated?.hands||{}).length;setStatus(els.contextStatus,`${c.population_id} · ${c.position} · ${c.effective_stack_bb} BB · ${c.spot} · stratégie personnelle ${p}/169 · stratégie calculée ${calc}/169`);}catch(err){setStatus(els.contextStatus,err.message,true);}
}
function renderResolutionStatus(){
  const bound=populationBound(),calc=layerInfo("calculated"),personal=layerInfo("personal");
  if(els.bindingBadge){
    els.bindingBadge.textContent=bound.compatible?`population liée : ${bound.population_id}`:`hors population liée (${bound.population_id||"—"} ≠ ${bound.repository_population_id||"—"})`;
    els.bindingBadge.classList.toggle("ok",bound.compatible);
    els.bindingBadge.classList.toggle("bad",!bound.compatible);
  }
  if(els.overrideBadge){
    els.overrideBadge.textContent=personal.defined>0?`override personnel · ${personal.defined}/169`:"override personnel : aucun";
    els.overrideBadge.classList.toggle("override",personal.defined>0);
    els.overrideBadge.dataset.source=personal.defined>0?"PERSONAL_OVERRIDE":"NONE";
  }
  const resolution=currentResolution(),source=resolution?resolution.source:"NONE";
  if(els.strategySource){
    els.strategySource.textContent=source==="POPULATION"?"source : stratégie population":source==="PERSONAL_OVERRIDE"?"source : override personnel":"source : indisponible";
    els.strategySource.dataset.source=source;
  }
  const provenance=calc.provenance?`stratégie calculée v${calc.version||"—"} · provenance ${calc.provenance.candidate_id||calc.provenance.generation_id||calc.provenance.schema||"présente"}`:`stratégie calculée ${calc.defined}/169`;
  if(!resolution)setStatus(els.resolutionStatus,`Résolution indisponible · ${provenance}`,true);
  else{
    const reasons=Array.isArray(resolution.reason_codes)&&resolution.reason_codes.length?` · motifs ${resolution.reason_codes.join(", ")}`:"";
    const identity=resolution.strategy_id?` · stratégie ${resolution.strategy_id}`:"";
    const version=resolution.strategy_version?` · version ${resolution.strategy_version}`:"";
    const error=!bound.compatible||resolution.status==="POPULATION_INCOMPATIBLE";
    setStatus(els.resolutionStatus,`${bound.compatible?"population liée":"hors population"} · statut ${resolution.status} · source ${source}${identity}${version} · ${provenance} · override personnel ${personal.defined}/169${reasons}`,error);
  }
  if(els.migrationStatus)setStatus(els.migrationStatus,migrationSummary(),false);
}
function renderAll(){renderSourceBrowser();renderContextStatus();try{renderGrid();renderComparison();renderActionEditor();}catch(err){setStatus(els.contextStatus,err.message,true);}renderResolutionStatus();renderRepository();}

function saveSelected(){
  try{
    requirePopulationBinding();
    const value=readEditorStrategy(),hands=selectedList();
    for(const hand of hands)HeroRanges.setHandStrategy(repo,context(),hand,value,{layer:"personal"});
    persist();renderAll();setStatus(els.handStatus,`${hands.length} main${hands.length>1?"s":""} enregistrée${hands.length>1?"s":""} comme override personnel. La stratégie calculée est inchangée.`);
  }catch(err){setStatus(els.handStatus,err.message,true);}
}
function undefineSelected(){
  try{
    requirePopulationBinding();
    const hands=selectedList();
    for(const hand of hands)HeroRanges.setHandStrategy(repo,context(),hand,null,{layer:"personal"});
    persist();renderAll();setStatus(els.handStatus,`Override personnel retiré pour ${hands.length} main${hands.length>1?"s":""}. La stratégie calculée reste intacte.`);
  }catch(err){setStatus(els.handStatus,err.message,true);}
}
function quickApply(){
  for(const action of HeroRanges.ACTIONS)els.actions.querySelector(`[data-action-prob="${action}"]`).value=action===els.quickAction.value?100:0;
  refreshEditorValidation();saveSelected();
}
function addSizing(action){
  const rows=els.actions.querySelector(`[data-sizes-for="${action}"] .sizing-rows`);
  const hasRows=rows.children.length>0;
  rows.insertAdjacentHTML("beforeend",sizeRowHtml(action,{target_total_bb:"",probability:hasRows?0:1}));
  refreshEditorValidation();
}

async function importFile(file){
  const text=await file.text(),json=JSON.parse(text);repo=HeroRanges.importDocument(json,{populationId:els.population.value,baseRepository:repo});
  if(repo.defaults?.population_id)els.population.value=repo.defaults.population_id;if(repo.defaults?.effective_stack_bb)els.stack.value=repo.defaults.effective_stack_bb;
  persist();renderAll();setStatus(els.sourceStatus,`${file.name} importé. Une mise à jour de la range source importée conserve les stratégies personnelles et calculées.`);
}
function exportFile(){
  try{const doc=HeroRanges.exportDocument(repo),blob=new Blob([JSON.stringify(doc,null,2)+"\n"],{type:"application/json"}),url=URL.createObjectURL(blob),a=document.createElement("a");a.href=url;a.download="hero_ranges_repository_v1.json";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);setStatus(els.sourceStatus,"Stratégie Hero exportée avec la range source importée conservée sans conversion destructive.");}catch(err){setStatus(els.sourceStatus,err.message,true);}
}

els.import.addEventListener("change",async e=>{const f=e.target.files?.[0];e.target.value="";if(!f)return;try{await importFile(f);}catch(err){setStatus(els.sourceStatus,`Import impossible : ${err.message}`,true);}});
els.export.addEventListener("click",exportFile);els.save.addEventListener("click",saveSelected);els.undefine.addEventListener("click",undefineSelected);els.quickApply.addEventListener("click",quickApply);
els.sourceRange.addEventListener("change",()=>{renderSourceBrowser();renderGrid();});els.sourcePosition.addEventListener("change",()=>{renderSourceHandDetail();renderGrid();});
for(const el of [els.population,els.position,els.stack,els.spot])el.addEventListener("change",renderAll);
for(const button of document.querySelectorAll("[data-select-kind]"))button.addEventListener("click",()=>selectCategory(button.dataset.selectKind));
els.actions.addEventListener("input",refreshEditorValidation);
els.actions.addEventListener("click",event=>{
  const add=event.target.closest("[data-add-size]");if(add){addSizing(add.dataset.addSize);return;}
  const remove=event.target.closest("[data-remove-size]");if(remove){remove.closest(".sizing-row")?.remove();refreshEditorValidation();}
});

initOptions();applyDeepLink();renderAll();

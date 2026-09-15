"use strict";

const HeroRanges=window.PokerHeroRanges;
const STORAGE_KEY="poker.hero.range.repository.v1";
const $=id=>document.getElementById(id);
const els={
  import:$("heroRangeImport"),export:$("heroRangeExport"),sourceBadge:$("sourceBadge"),sourceStatus:$("sourceStatus"),
  sourceRange:$("sourceRangeSelect"),sourcePosition:$("sourcePositionSelect"),sourceHandDetail:$("sourceHandDetail"),
  population:$("populationInput"),position:$("positionSelect"),stack:$("stackInput"),spot:$("spotSelect"),contextStatus:$("contextStatus"),
  grid:$("heroGrid"),gridSummary:$("gridSummary"),title:$("selectedHandTitle"),state:$("selectedHandState"),actions:$("actionEditor"),
  notes:$("handNotes"),save:$("saveHand"),undefine:$("undefineHand"),quickAction:$("quickAction"),quickApply:$("quickApply"),
  handStatus:$("handStatus"),stats:$("repositoryStats"),contextList:$("contextList")
};
let repo=restoreRepository();
let selectedHand="AA";

function restoreRepository(){
  try{const raw=localStorage.getItem(STORAGE_KEY);if(raw)return HeroRanges.importDocument(JSON.parse(raw));}catch(_){}
  return HeroRanges.emptyRepository({populationId:"pokerstars_nlhe_100-200_zoom_play_6max_v1"});
}
function persist(){HeroRanges.validateRepository(repo);localStorage.setItem(STORAGE_KEY,JSON.stringify(repo));}
function setStatus(el,message,error=false){el.textContent=message;el.classList.toggle("error",!!error);}
function context(){return HeroRanges.normalizeContext({population_id:els.population.value,table_size:6,position:els.position.value,effective_stack_bb:Number(els.stack.value),spot:els.spot.value});}
function currentNode(){try{return repo.contexts[HeroRanges.contextKey(context())]||null;}catch(_){return null;}}
function currentPersonal(){return HeroRanges.getHandStrategy(repo,context(),selectedHand,{layer:"personal"});}
function currentCalculated(){return HeroRanges.getHandStrategy(repo,context(),selectedHand,{layer:"calculated"});}

function initOptions(){
  els.position.innerHTML=HeroRanges.POSITIONS.map(p=>`<option>${p}</option>`).join("");els.position.value="BTN";
  els.spot.innerHTML=HeroRanges.SPOTS.map(s=>`<option>${s}</option>`).join("");
  els.quickAction.innerHTML=HeroRanges.ACTIONS.map(a=>`<option>${a}</option>`).join("");els.quickAction.value="OPEN";
  if(repo.defaults?.population_id)els.population.value=repo.defaults.population_id;
  if(repo.defaults?.effective_stack_bb)els.stack.value=repo.defaults.effective_stack_bb;
}
function applyDeepLink(){
  const params=new URLSearchParams(window.location.search||"");
  const population=String(params.get("population")||"").trim();if(population)els.population.value=population;
  const position=String(params.get("position")||"").toUpperCase();if(HeroRanges.POSITIONS.includes(position))els.position.value=position;
  const stack=Number(params.get("stack"));if(Number.isFinite(stack)&&stack>0)els.stack.value=String(stack);
  const spot=String(params.get("spot")||"").toUpperCase();if(HeroRanges.SPOTS.includes(spot))els.spot.value=spot;
  const requested=String(params.get("hand")||"").trim();
  const canonical=HeroRanges.HAND_CLASSES.find(hand=>hand.toUpperCase()===requested.toUpperCase());
  if(canonical)selectedHand=canonical;
}

function legacyEntries(){return HeroRanges.legacyRanges(repo.source?.range_folder);}
function sourceSelection(){
  const entries=legacyEntries(),r=entries[Number(els.sourceRange.value)||0]?.range||null;
  const positions=r?.positions||[],p=positions[Number(els.sourcePosition.value)||0]||null;
  return {range:r,position:p};
}
function sourceHand(hand){
  const {position}=sourceSelection();return (position?.hands||[]).find(h=>String(h.hand||"").toUpperCase()===hand)||null;
}
function sourceFrequency(hand){
  const row=sourceHand(hand);if(!row)return null;let f=0;
  for(const a of (row.actions||[])){const name=String(a?.name||"").toUpperCase(),v=Number(a?.frequency)||0;if(name!=="FOLD"&&v>0)f+=v;}
  return Math.max(0,Math.min(100,f));
}
function escapeHtml(s){return String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#039;"})[c]);}
function renderSourceBrowser(){
  const entries=legacyEntries();
  els.sourceBadge.textContent=repo.source?.preserved_verbatim?"source préservée":"aucune source";
  setStatus(els.sourceStatus,repo.source?.preserved_verbatim?`${entries.length} range(s) source conservée(s) verbatim. Les éditions personnelles sont stockées à part.`:"Aucun range-folder source importé. Les contextes Hero restent éditables.");
  const oldRange=Number(els.sourceRange.value)||0;
  els.sourceRange.innerHTML=entries.length?entries.map((x,i)=>`<option value="${i}">${escapeHtml(`${x.path} / ${x.range?.name||"Range"}`)}</option>`).join(""):'<option value="0">—</option>';
  els.sourceRange.value=String(Math.min(oldRange,Math.max(0,entries.length-1)));
  const range=entries[Number(els.sourceRange.value)||0]?.range,positions=range?.positions||[],oldPos=Number(els.sourcePosition.value)||0;
  els.sourcePosition.innerHTML=positions.length?positions.map((p,i)=>`<option value="${i}">${escapeHtml(p.position||`Position ${i+1}`)}</option>`).join(""):'<option value="0">—</option>';
  els.sourcePosition.value=String(Math.min(oldPos,Math.max(0,positions.length-1)));
  renderSourceHandDetail();
}
function renderSourceHandDetail(){
  const row=sourceHand(selectedHand);els.sourceHandDetail.textContent=row?`${selectedHand}\n${JSON.stringify(row.actions||[],null,2)}`:`${selectedHand} : absent de la position source sélectionnée.`;
}

function renderGrid(){
  let personal=0,calculated=0,source=0;
  els.grid.innerHTML=HeroRanges.HAND_CLASSES.map(hand=>{
    const p=HeroRanges.getHandStrategy(repo,context(),hand,{layer:"personal"}),c=HeroRanges.getHandStrategy(repo,context(),hand,{layer:"calculated"}),sf=sourceFrequency(hand);
    if(p)personal++;else if(c)calculated++;if(sf!=null)source++;
    const cls=["hand-cell",p||c?"defined":"",sf!=null?"source-only":"",hand===selectedHand?"selected":""].filter(Boolean).join(" ");
    const mini=p?"P":c?"C":sf!=null?`${Math.round(sf)}%`:"";
    return `<button type="button" class="${cls}" data-hand="${hand}">${hand}<span class="mini">${mini}</span></button>`;
  }).join("");
  els.gridSummary.textContent=`P ${personal} · C ${calculated} · source ${source}`;
  for(const b of els.grid.querySelectorAll(".hand-cell"))b.addEventListener("click",()=>{selectedHand=b.dataset.hand;renderAll();});
}

function sizingText(list){return (list||[]).map(x=>`${x.target_total_bb}:${Math.round(x.probability*10000)/100}%`).join(", ");}
function renderActionEditor(){
  const personal=currentPersonal(),calculated=currentCalculated(),strategy=personal||calculated;
  els.title.textContent=selectedHand;
  els.state.textContent=personal?"personnel":calculated?"calculé":"non défini";
  els.actions.innerHTML=HeroRanges.ACTIONS.map(a=>`<div class="action-row"><span class="name">${a}</span><input data-action-prob="${a}" type="number" min="0" max="100" step="1" value="${strategy?Math.round((strategy.actions?.[a]||0)*10000)/100:"0"}" aria-label="Fréquence ${a}"><input data-action-size="${a}" value="${escapeHtml(strategy?.sizings?.[a]?sizingText(strategy.sizings[a]):"")}" placeholder="sizing ex. 2.5 ou 2.2:50%,2.5:50%" aria-label="Sizing ${a}"></div>`).join("");
  els.notes.value=strategy?.notes||"";
  setStatus(els.handStatus,personal?"Couche personnelle active.":calculated?"Couche calculée affichée. Enregistrer créera une personnalisation sans écraser la couche calculée.":"Main non couverte dans ce contexte.");
}

function parseSizing(text){
  const s=String(text||"").trim();if(!s)return null;
  const chunks=s.split(",").map(x=>x.trim()).filter(Boolean),rows=[];
  for(const chunk of chunks){
    const [target0,prob0]=chunk.split(":").map(x=>x.trim()),target=Number(target0);if(!Number.isFinite(target)||target<=0)throw new Error(`sizing invalide: ${chunk}`);
    let probability=prob0==null?1:Number(prob0.replace("%",""));if(prob0!=null&&probability>1)probability/=100;
    rows.push({target_total_bb:target,probability});
  }
  if(rows.length>1&&rows.every(x=>Math.abs(x.probability-1)<1e-9)){const q=1/rows.length;for(const row of rows)row.probability=q;}
  return rows;
}
function readEditorStrategy(){
  const actions={},sizings={};let total=0;
  for(const a of HeroRanges.ACTIONS){
    const pct=Number(els.actions.querySelector(`[data-action-prob="${a}"]`).value)||0;if(pct<0||pct>100)throw new Error(`${a}: fréquence hors 0–100 %`);
    if(pct>0){actions[a]=pct/100;total+=pct;const size=parseSizing(els.actions.querySelector(`[data-action-size="${a}"]`).value);if(size)sizings[a]=size;}
  }
  if(Math.abs(total-100)>1e-6)throw new Error(`la distribution doit totaliser 100 % (actuellement ${total} %)`);
  return {actions,sizings,notes:els.notes.value||""};
}

function renderRepository(){
  const stats=HeroRanges.repositoryStats(repo);els.stats.textContent=`${stats.contexts} contexte(s) · P ${stats.personal_defined_hands} · C ${stats.calculated_defined_hands}`;
  const lines=[];
  for(const node of Object.values(repo.contexts)){
    const p=Object.keys(node.layers.personal.hands||{}).length,c=Object.keys(node.layers.calculated.hands||{}).length;
    lines.push(`${node.context.position} · ${node.context.effective_stack_bb} BB · ${node.context.spot} · personnel ${p}/169 · calculé ${c}/169`);
  }
  els.contextList.textContent=lines.length?lines.join("\n"):"Aucun contexte défini.";
}
function renderContextStatus(){
  try{const c=context(),node=currentNode(),p=Object.keys(node?.layers?.personal?.hands||{}).length,calc=Object.keys(node?.layers?.calculated?.hands||{}).length;setStatus(els.contextStatus,`${c.population_id} · ${c.position} · ${c.effective_stack_bb} BB · ${c.spot} · personnel ${p}/169 · calculé ${calc}/169`);}catch(err){setStatus(els.contextStatus,err.message,true);}
}
function renderAll(){renderSourceBrowser();renderContextStatus();try{renderGrid();renderActionEditor();}catch(err){setStatus(els.contextStatus,err.message,true);}renderRepository();}

function saveSelected(){
  try{const s=readEditorStrategy();HeroRanges.setHandStrategy(repo,context(),selectedHand,s,{layer:"personal"});persist();renderAll();setStatus(els.handStatus,`${selectedHand} enregistrée dans la couche personnelle.`);}catch(err){setStatus(els.handStatus,err.message,true);}
}
function undefineSelected(){
  try{HeroRanges.setHandStrategy(repo,context(),selectedHand,null,{layer:"personal"});persist();renderAll();setStatus(els.handStatus,`${selectedHand} n'a plus de définition personnelle. La couche calculée, si présente, reste intacte.`);}catch(err){setStatus(els.handStatus,err.message,true);}
}
function quickApply(){
  for(const a of HeroRanges.ACTIONS)els.actions.querySelector(`[data-action-prob="${a}"]`).value=a===els.quickAction.value?100:0;
  saveSelected();
}

async function importFile(file){
  const text=await file.text(),json=JSON.parse(text);repo=HeroRanges.importDocument(json,{populationId:els.population.value,baseRepository:repo});
  if(repo.defaults?.population_id)els.population.value=repo.defaults.population_id;if(repo.defaults?.effective_stack_bb)els.stack.value=repo.defaults.effective_stack_bb;
  persist();renderAll();setStatus(els.sourceStatus,`${file.name} importé. Une mise à jour range-folder conserve les couches personnelles et calculées.`);
}
function exportFile(){
  try{const doc=HeroRanges.exportDocument(repo),blob=new Blob([JSON.stringify(doc,null,2)+"\n"],{type:"application/json"}),url=URL.createObjectURL(blob),a=document.createElement("a");a.href=url;a.download="hero_ranges_repository_v1.json";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);setStatus(els.sourceStatus,"Dépôt Hero v1 exporté sans conversion destructive de la source.");}catch(err){setStatus(els.sourceStatus,err.message,true);}
}

els.import.addEventListener("change",async e=>{const f=e.target.files?.[0];e.target.value="";if(!f)return;try{await importFile(f);}catch(err){setStatus(els.sourceStatus,`Import impossible : ${err.message}`,true);}});
els.export.addEventListener("click",exportFile);els.save.addEventListener("click",saveSelected);els.undefine.addEventListener("click",undefineSelected);els.quickApply.addEventListener("click",quickApply);
els.sourceRange.addEventListener("change",()=>{renderSourceBrowser();renderGrid();});els.sourcePosition.addEventListener("change",()=>{renderSourceHandDetail();renderGrid();});
for(const el of [els.population,els.position,els.stack,els.spot])el.addEventListener("change",renderAll);

initOptions();applyDeepLink();renderAll();

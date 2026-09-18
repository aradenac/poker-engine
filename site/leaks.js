(function(){
  'use strict';
  const Leak=window.PokerLeakAnalyzer,Adapter=window.PokerReviewLeakAdapter;
  const DB_NAME='PokerRangeEquityOffline',STORE='kv';
  const $=id=>document.getElementById(id);
  const ui={status:$('loadStatus'),scope:$('scopeSelect'),reload:$('reloadBtn'),json:$('exportJsonBtn'),csv:$('exportCsvBtn'),
    total:$('metricTotalLoss'),bb100:$('metricBb100'),analyzed:$('metricAnalyzed'),coverage:$('metricCoverage'),excluded:$('metricExcluded'),noise:$('metricNoise'),
    pos:$('filterPosition'),street:$('filterStreet'),family:$('filterFamily'),played:$('filterPlayed'),recommended:$('filterRecommended'),coverageFilter:$('filterCoverage'),
    sizingError:$('filterSizingError'),jam:$('filterJam'),overbet:$('filterOverbet'),sizeMin:$('filterSizingMin'),sizeMax:$('filterSizingMax'),from:$('filterFrom'),to:$('filterTo'),
    dimension:$('leakDimension'),leaks:$('leaksBody'),decisions:$('decisionsBody'),diagnostics:$('diagnosticsBody'),reset:$('resetFiltersBtn'),
    sourcePanel:$('sourcePanel'),sourceTitle:$('sourceTitle'),sourceMeta:$('sourceMeta'),sourceAction:$('sourceAction'),sourceRaw:$('sourceRaw'),closeSource:$('closeSourceBtn')};
  const state={adapted:null,scopeKey:'',baseEvents:[],report:null};

  function esc(v){return String(v==null?'':v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
  function bb(v){return Number.isFinite(Number(v))?Number(v).toLocaleString('fr-FR',{minimumFractionDigits:0,maximumFractionDigits:2})+' BB':'—';}
  function pct(v){return Number.isFinite(Number(v))?Number(v).toLocaleString('fr-FR',{maximumFractionDigits:1})+' %':'—';}
  function boolValue(v){return v===''?null:v==='true';}
  function setStatus(message,error=false){ui.status.textContent=message;ui.status.className=error?'status error':'status';}
  async function dbExists(name){if(!indexedDB.databases)return true;try{return (await indexedDB.databases()).some(x=>x.name===name);}catch(_){return true;}}
  async function idbGet(key){
    if(!(await dbExists(DB_NAME)))return null;
    return new Promise((resolve,reject)=>{
      const req=indexedDB.open(DB_NAME);let aborted=false;
      req.onupgradeneeded=()=>{aborted=true;try{req.transaction.abort();}catch(_){}};
      req.onerror=()=>aborted?resolve(null):reject(req.error||new Error('IndexedDB inaccessible'));
      req.onsuccess=()=>{
        const db=req.result;if(!db.objectStoreNames.contains(STORE)){db.close();resolve(null);return;}
        const tx=db.transaction(STORE,'readonly'),get=tx.objectStore(STORE).get(key);
        get.onsuccess=()=>{db.close();resolve(get.result==null?null:get.result);};
        get.onerror=()=>{const e=get.error;db.close();reject(e);};
      };
    });
  }
  async function manifest(){try{const r=await fetch('./assets/trainer/population.json',{cache:'no-store'});return r.ok?await r.json():null;}catch(_){return null;}}
  async function resolveScope(){
    const [m,active]=await Promise.all([manifest(),window.PokerPopulationPacks&&window.PokerPopulationPacks.active?window.PokerPopulationPacks.active().catch(()=>null):Promise.resolve(null)]);
    const population_id=active&&active.population_id||m&&m.population_id;
    if(!population_id)throw new Error('Identité de population introuvable.');
    const pack_id=active?(active.pack_id+'@'+active.pack_version):('static-trainer@'+(m&&m.engine_version||'unknown'));
    const strategy_id=active&&active.entry&&(active.entry.hero_strategy||active.entry.hero_strategy_id)||m&&m.hero_strategy||'review-engine';
    const strategy_version=active&&active.runtime_revision||[m&&m.engine_version,m&&m.model_a_version].filter(Boolean).join('+')||'unknown-runtime';
    return {population_id,pack_id,strategy_id,strategy_version,ev_reference:Adapter.DEFAULT_EV_REFERENCE};
  }
  function groupByScope(events){
    const map=new Map();for(const e of events){const k=Leak.scopeKey(Leak.scopeOf(e));if(!map.has(k))map.set(k,[]);map.get(k).push(e);}return map;
  }
  function scopeLabel(rows){const e=rows[0];return [e.population_id,e.pack_id,e.strategy_id,e.strategy_version].filter(Boolean).join(' · ')+' · '+rows.length+' décisions';}
  function chooseScope(groups){
    if(state.scopeKey&&groups.has(state.scopeKey))return state.scopeKey;
    let best='',n=-1;for(const [k,rows] of groups)if(rows.length>n){best=k;n=rows.length;}return best;
  }
  function renderScope(groups){
    const entries=[...groups.entries()].sort((a,b)=>b[1].length-a[1].length);
    state.scopeKey=chooseScope(groups);
    ui.scope.innerHTML=entries.map(([k,rows])=>'<option value="'+esc(k)+'"'+(k===state.scopeKey?' selected':'')+'>'+esc(scopeLabel(rows))+'</option>').join('');
    ui.scope.disabled=entries.length<=1;
    state.baseEvents=groups.get(state.scopeKey)||[];
  }
  function values(field){
    const set=new Set();for(const e of state.baseEvents){const v=field(e);if(v!=null&&String(v))set.add(String(v));}return [...set].sort((a,b)=>a.localeCompare(b));
  }
  function fillSelect(select,rows,label='Toutes'){
    const old=select.value;select.innerHTML='<option value="">'+esc(label)+'</option>'+rows.map(x=>'<option value="'+esc(x)+'">'+esc(x)+'</option>').join('');
    if(rows.includes(old))select.value=old;
  }
  function populateFilters(){
    fillSelect(ui.pos,values(e=>e.context.position));fillSelect(ui.street,values(e=>e.context.street));fillSelect(ui.family,values(e=>e.context.spot_family));
    fillSelect(ui.played,values(e=>e.played.action));fillSelect(ui.recommended,values(e=>e.recommended.action));
  }
  function filters(){
    const f={};
    if(ui.pos.value)f.position=ui.pos.value;if(ui.street.value)f.street=ui.street.value;if(ui.family.value)f.spot_family=ui.family.value;
    if(ui.played.value)f.action_played=ui.played.value;if(ui.recommended.value)f.action_recommended=ui.recommended.value;
    if(ui.sizingError.value!=='')f.sizing_error=boolValue(ui.sizingError.value);
    if(ui.jam.value!=='')f.jam=boolValue(ui.jam.value);if(ui.overbet.value!=='')f.overbet=boolValue(ui.overbet.value);
    if(ui.sizeMin.value!=='')f.min_played_size_pot_ratio=Number(ui.sizeMin.value);if(ui.sizeMax.value!=='')f.max_played_size_pot_ratio=Number(ui.sizeMax.value);
    if(ui.from.value)f.from=ui.from.value+'T00:00:00Z';if(ui.to.value)f.to=ui.to.value+'T23:59:59Z';
    if(ui.coverageFilter.value==='comparable'){f.covered=true;f.comparable=true;}
    if(ui.coverageFilter.value==='unsupported'){f.covered=false;}
    if(ui.coverageFilter.value==='non_comparable'){f.covered=true;f.comparable=false;}
    if(ui.coverageFilter.value==='within_noise'){f.covered=true;f.comparable=true;f.within_noise=true;}
    return f;
  }
  function badge(text,cls){return '<span class="badge '+(cls||'')+'">'+esc(text)+'</span>';}
  function statusOf(e){
    if(!e.support.covered)return {text:'UNSUPPORTED',cls:'unsupported',reason:e.support.reason||'Non couvert'};
    if(!e.comparability.comparable)return {text:'NON COMPARABLE',cls:'error',reason:e.comparability.reason||'Référence EV non comparable'};
    if(e.within_noise)return {text:'WITHIN NOISE',cls:'noise',reason:'Écart conservé pour audit mais non attribué comme leak'};
    return {text:e.error_type,cls:e.ev.attributed_loss_bb>0?'error':'good',reason:e.error_type};
  }
  function renderMetrics(r){
    ui.total.textContent=bb(r.summary.total_loss_bb);
    ui.bb100.textContent=r.summary.loss_bb_per_100_hands==null?'—':bb(r.summary.loss_bb_per_100_hands);
    ui.analyzed.textContent=r.summary.decisions_eligible.toLocaleString('fr-FR');
    ui.coverage.textContent=(r.summary.decisions_selected?r.summary.decisions_selected.toLocaleString('fr-FR')+' sélectionnées · '+pct(r.summary.coverage_pct):'Aucune décision sélectionnée');
    ui.excluded.textContent=(r.summary.unsupported_decisions+r.summary.non_comparable_decisions).toLocaleString('fr-FR');
    ui.noise.textContent=r.summary.unsupported_decisions+' unsupported · '+r.summary.non_comparable_decisions+' non comparables · '+r.summary.within_noise_decisions+' within noise';
  }
  function renderLeaks(r){
    const rows=r.leaks.by[ui.dimension.value]||[];
    ui.leaks.innerHTML=rows.length?rows.slice(0,30).map(x=>'<tr><td>'+esc(x.key)+'</td><td class="num loss">'+bb(x.total_loss_bb)+'</td><td class="num">'+pct(x.frequency_pct)+'</td><td class="num">'+x.decisions+'</td><td class="num">'+x.hands+'</td></tr>').join(''):'<tr><td class="empty" colspan="5">Aucun groupe pour ces filtres.</td></tr>';
  }
  function sourceButton(hand,decision){return '<button class="source-btn" type="button" data-source-hand="'+esc(hand)+'" data-source-decision="'+esc(decision)+'">Source</button>';}
  function renderDecisions(r){
    const rows=r.leaks.top_decisions||[];
    ui.decisions.innerHTML=rows.length?rows.slice(0,50).map(x=>{
      const tags=[x.jam?'JAM':'',x.overbet?'OVERBET':'',x.error_type==='SIZING_ERROR'?'SIZING':''].filter(Boolean).map(t=>badge(t,'error')).join('');
      return '<tr><td>#'+esc(x.hand_id)+'</td><td>'+esc(x.position)+' · '+esc(x.street)+'<br><small>'+esc(x.spot_family)+'</small></td><td>'+esc(x.action_played)+' → '+esc(x.action_recommended)+'</td><td class="num loss">'+bb(x.loss_bb)+'</td><td>'+tags+'</td><td>'+sourceButton(x.hand_id,x.decision_id)+'</td></tr>';
    }).join(''):'<tr><td class="empty" colspan="6">Aucune perte EV attribuée pour ces filtres.</td></tr>';
  }
  function renderDiagnostics(r){
    const rows=(r.decision_events||[]).filter(e=>!e.support.covered||!e.comparability.comparable||e.within_noise);
    ui.diagnostics.innerHTML=rows.length?rows.slice(0,100).map(e=>{const s=statusOf(e);return '<tr><td>'+badge(s.text,s.cls)+'</td><td>#'+esc(e.hand_id)+'</td><td>'+esc(e.context.street)+'</td><td>'+esc(e.played.action)+'</td><td>'+esc(s.reason)+'</td><td>'+sourceButton(e.hand_id,e.decision_id)+'</td></tr>';}).join(''):'<tr><td class="empty" colspan="6">Aucun diagnostic exclu dans la sélection courante.</td></tr>';
  }
  function render(){
    if(!state.baseEvents.length){state.report=null;renderMetrics({summary:{total_loss_bb:0,loss_bb_per_100_hands:null,decisions_eligible:0,decisions_selected:0,coverage_pct:null,unsupported_decisions:0,non_comparable_decisions:0,within_noise_decisions:0}});renderLeaks({leaks:{by:{}}});renderDecisions({leaks:{top_decisions:[]}});renderDiagnostics({decision_events:[]});ui.json.disabled=true;ui.csv.disabled=true;return;}
    try{state.report=Leak.analyzeLeaks(state.baseEvents,filters());renderMetrics(state.report);renderLeaks(state.report);renderDecisions(state.report);renderDiagnostics(state.report);ui.json.disabled=false;ui.csv.disabled=false;}
    catch(err){setStatus('Filtre invalide : '+(err.message||err),true);}
  }
  function resetFilters(){
    for(const el of [ui.pos,ui.street,ui.family,ui.played,ui.recommended,ui.coverageFilter,ui.sizingError,ui.jam,ui.overbet,ui.sizeMin,ui.sizeMax,ui.from,ui.to])el.value='';
    render();
  }
  function download(content,name,type){const url=URL.createObjectURL(new Blob([content],{type})),a=document.createElement('a');a.href=url;a.download=name;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),500);}
  function showSource(handId,decisionId){
    const src=Adapter.handSource(state.adapted,handId,decisionId);if(!src){setStatus('Main source introuvable pour '+handId,true);return;}
    ui.sourceTitle.textContent='Main #'+src.hand_id;ui.sourceMeta.textContent=[src.source_name,src.timestamp,src.hero_name,src.hero_position].filter(Boolean).join(' · ');
    ui.sourceAction.textContent=src.action_line||'Action exacte non disponible.';ui.sourceRaw.textContent=src.raw_hand_history||'';ui.sourcePanel.classList.remove('hidden');ui.sourcePanel.scrollIntoView({behavior:'smooth',block:'start'});
  }
  async function load(){
    if(!Leak||!Adapter){setStatus('Modules Leak Analyzer indisponibles.',true);return;}
    setStatus('Lecture des reviewScores et Hand Histories locales…');
    try{
      const [reviewScores,hhSources,scope]=await Promise.all([idbGet('reviewScores'),idbGet('hhSources'),resolveScope()]);
      state.adapted=Adapter.adaptPersistedReviewData({reviewScores:reviewScores||{},hhSources:Array.isArray(hhSources)?hhSources:[],scope});
      const groups=groupByScope(state.adapted.events);
      if(!groups.size){
        renderScope(new Map());state.baseEvents=[];populateFilters();render();
        setStatus('Aucune décision analysée exploitable. Importez des HH et laissez la review calculer les reviewScores dans l’application principale.');
        return;
      }
      renderScope(groups);populateFilters();render();
      const warning=state.adapted.warnings.length?' · '+state.adapted.warnings.length+' source(s) HH manquante(s)':'';
      setStatus(state.adapted.events.length+' décisions Hero reconstruites depuis '+state.adapted.hands.size+' main(s) · '+groups.size+' périmètre(s) isolé(s)'+warning);
    }catch(err){setStatus('Chargement impossible : '+(err.message||err),true);}
  }

  ui.reload.addEventListener('click',load);ui.scope.addEventListener('change',()=>{state.scopeKey=ui.scope.value;const groups=groupByScope(state.adapted.events);state.baseEvents=groups.get(state.scopeKey)||[];populateFilters();resetFilters();});
  for(const el of [ui.pos,ui.street,ui.family,ui.played,ui.recommended,ui.coverageFilter,ui.sizingError,ui.jam,ui.overbet,ui.sizeMin,ui.sizeMax,ui.from,ui.to])el.addEventListener('change',render);
  ui.dimension.addEventListener('change',()=>state.report&&renderLeaks(state.report));ui.reset.addEventListener('click',resetFilters);
  ui.json.addEventListener('click',()=>state.report&&download(Leak.exportReportJSON(state.report),'leak-analysis.json','application/json'));
  ui.csv.addEventListener('click',()=>state.report&&download(Leak.exportReportCSV(state.report),'leak-analysis.csv','text/csv;charset=utf-8'));
  document.addEventListener('click',e=>{const b=e.target.closest&&e.target.closest('[data-source-hand]');if(b)showSource(b.dataset.sourceHand,b.dataset.sourceDecision);});
  ui.closeSource.addEventListener('click',()=>ui.sourcePanel.classList.add('hidden'));
  load();
})();
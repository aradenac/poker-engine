(function(root){
  'use strict';

  const STORAGE_KEY='poker.hero.range.repository.v1';
  const PANEL_ID='heroCompliancePanel';
  const RANKS='23456789TJQKA';
  const SUITS={s:'s',h:'h',d:'d',c:'c','♠':'s','♥':'h','♦':'d','♣':'c'};
  let sessionCache={key:null,summary:null};
  let lastMarkup='';

  function esc(value){return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));}
  function cardParts(card){
    if(Number.isInteger(card)&&card>=0&&card<52){
      return {rank:RANKS[card%13],suit:String(Math.floor(card/13))};
    }
    const s=String(card||'').trim();
    if(s.length<2)return null;
    const rank=s[0].toUpperCase(),suit=SUITS[s[1].toLowerCase?.()||s[1]]||SUITS[s[1]];
    if(!RANKS.includes(rank)||!suit)return null;
    return {rank,suit};
  }
  function handClass(cards){
    if(!Array.isArray(cards)||cards.length!==2)return null;
    const a=cardParts(cards[0]),b=cardParts(cards[1]);if(!a||!b)return null;
    if(a.rank===b.rank)return a.rank+b.rank;
    const hi=RANKS.indexOf(a.rank)>RANKS.indexOf(b.rank)?a:b,lo=hi===a?b:a;
    return hi.rank+lo.rank+(hi.suit===lo.suit?'s':'o');
  }

  function loadRepository(){
    const H=root.PokerHeroRanges;
    if(!H)return {repo:null,error:'module Hero range indisponible'};
    let raw=null;
    try{raw=root.localStorage?.getItem(STORAGE_KEY);}catch(err){return {repo:null,error:`stockage inaccessible: ${err.message}`};}
    if(!raw)return {repo:null,error:null};
    try{return {repo:H.importDocument(JSON.parse(raw)),error:null};}
    catch(err){return {repo:null,error:`range Hero invalide: ${err.message}`};}
  }

  function replayPreflopCount(index){
    try{if(typeof replayPreflopDecisionCount==='function')return replayPreflopDecisionCount(index);}catch(_){}
    let n=0;
    const steps=(typeof state!=='undefined'&&state.replaySteps)||[];
    const end=Math.max(0,Math.min(Number(index)||0,Math.max(0,steps.length-1)));
    for(let i=0;i<=end;i++){
      const s=steps[i];if(s?.street==='Préflop'&&['fold','check','call','raise','bet'].includes(s.actionType))n++;
    }
    return n;
  }

  function traceForHand(hand){
    try{return typeof populationPreflopDecisionTrace==='function'?populationPreflopDecisionTrace(hand):[];}catch(err){console.warn('Hero compliance trace unavailable',err);return [];}
  }

  // The compliance verdict is only meaningful against the population the
  // analyser is currently running. Resolve that identity from the same sources
  // the product header uses, then fall back to the repository defaults only when
  // no runtime population is known.
  function activePopulationId(repo){
    try{
      if(typeof trainerState!=='undefined'&&trainerState?.populationId)return String(trainerState.populationId);
    }catch(_){}
    try{
      if(typeof state!=='undefined'){
        const model=state?.populationModel,id=model?.population_id||model?.populationId;
        if(id)return String(id);
        const pack=state?.manualOverrideContract?.base_active_pack;
        if(pack?.population_id)return String(pack.population_id);
      }
    }catch(_){}
    return repo?.defaults?.population_id?String(repo.defaults.population_id):null;
  }
  function heroManifest(){
    try{if(typeof trainerWarmAssets!=='undefined'&&trainerWarmAssets?.population)return trainerWarmAssets.population;}catch(_){}
    return null;
  }
  function heroPackIdentity(){
    try{if(typeof state!=='undefined')return state?.manualOverrideContract?.base_active_pack||null;}catch(_){}
    return null;
  }
  function heroRetainedReference(manifest){
    const provenance=manifest?.hero_provenance;
    if(!provenance?.population_id)return null;
    return {
      schema:provenance.schema||null,issue:null,population_id:provenance.population_id,
      strategy_id:provenance.strategy_id||null,
      strategy_version:provenance.sha256?String(provenance.sha256).slice(0,16):null,
      strategy_sha256:provenance.sha256||null
    };
  }
  function strategyResolutionFor(repo){
    const Resolver=root.PokerHeroStrategyResolver,population=activePopulationId(repo);
    if(Resolver&&typeof Resolver.resolveHeroStrategy==='function'){
      // Only bind the trainer manifest when it describes the active population;
      // a stale manifest from another population must not make the resolver
      // reject an otherwise valid active population.
      let manifest=heroManifest();
      if(manifest&&String(manifest.population_id||'')!==String(population||''))manifest=null;
      const provenance=manifest?.hero_provenance||null;
      try{
        return Resolver.resolveHeroStrategy({
          population_id:population,
          repository:repo,
          trainer_manifest:manifest,
          pack_identity:heroPackIdentity(),
          admissions:provenance?.status?{hero_strategy:{status:provenance.status,population_id:provenance.population_id||population}}:null,
          retained_reference:heroRetainedReference(manifest)
        });
      }catch(err){console.warn('Hero strategy resolution unavailable',err);}
    }
    try{if(typeof trainerState!=='undefined'&&trainerState?.heroStrategyResolution)return trainerState.heroStrategyResolution;}catch(_){}
    return null;
  }

  function evaluate(hand,decision,repo,resolution){
    const C=root.PokerHeroCompliance;if(!C)return null;
    return C.evaluateDecision({repo,decision,handClass:handClass(hand?.heroCards||[]),populationId:resolution?.population_id||repo?.defaults?.population_id||null,strategyResolution:resolution||null});
  }
  function heroTrace(hand){return traceForHand(hand).filter(d=>d?.player===hand?.heroName);}

  function currentEvaluation(hand,repo,providedResolution){
    if(!hand)return {result:null,decision:null,resolution:null,label:'Aucune main sélectionnée'};
    const resolution=providedResolution===undefined?strategyResolutionFor(repo):providedResolution;
    const all=traceForHand(hand),count=replayPreflopCount(typeof state!=='undefined'?state.replayIndex:0),occurred=all.slice(0,count);
    const hero=occurred.filter(d=>d?.player===hand.heroName);
    if(!hero.length)return {result:null,decision:null,resolution,label:'Aucune décision Hero préflop encore jouée'};
    const decision=hero[hero.length-1];
    return {result:evaluate(hand,decision,repo,resolution),decision,resolution,label:'Dernière décision Hero préflop'};
  }

  function sessionSummary(repo,providedResolution){
    const C=root.PokerHeroCompliance;
    if(!C||typeof state==='undefined')return null;
    const resolution=providedResolution===undefined?strategyResolutionFor(repo):providedResolution;
    const hands=Array.isArray(state.hhHands)?state.hhHands:[];
    const token=C.repositoryVersionToken(repo)||'none';
    const ids=hands.length?`${hands[0]?.id||''}:${hands[hands.length-1]?.id||''}`:'';
    const key=`${token}:${hands.length}:${ids}:${resolution?.strategy_sha256||resolution?.strategy_version||resolution?.status||'none'}`;
    if(sessionCache.key===key)return sessionCache.summary;
    const rows=[];
    for(const hand of hands){
      const hc=handClass(hand?.heroCards||[]);if(!hc)continue;
      for(const d of heroTrace(hand))rows.push(C.evaluateDecision({repo,decision:d,handClass:hc,populationId:resolution?.population_id||repo?.defaults?.population_id||null,strategyResolution:resolution||null}));
    }
    const summary=C.summarize(rows);sessionCache={key,summary};return summary;
  }

  function statusLabel(result){
    if(result?.context_status==='POPULATION_INCOMPATIBLE')return 'Hors population';
    if(result?.context_status==='STRATEGY_UNAVAILABLE')return 'Stratégie indisponible';
    const map={COMPLIANT:'Conforme',MIXED_ALLOWED:'Action mixée autorisée',OUT_OF_RANGE:'Hors range',UNCOVERED_HAND:'Main non couverte',UNKNOWN_ACTION:'Action non couverte',NO_VERDICT:'Pas de verdict'};
    return map[result?.action_status]||'Pas de verdict';
  }
  function strategySourceText(result){
    if(result?.strategy_source==='PERSONAL_OVERRIDE')return 'override personnel';
    if(result?.strategy_source==='POPULATION')return 'stratégie population';
    return 'aucune stratégie admissible';
  }
  function resolutionText(resolution){
    if(!resolution)return 'résolution indisponible';
    const parts=[String(resolution.status||'STATUS'),String(resolution.source||'SOURCE')];
    if(resolution.population_id)parts.push(String(resolution.population_id));
    if(resolution.fail_closed)parts.push('fail-closed');
    return parts.join(' · ');
  }
  function statusClass(result){
    if(result?.action_status==='OUT_OF_RANGE')return 'bad';
    if(result?.action_status==='COMPLIANT'||result?.action_status==='MIXED_ALLOWED')return 'good';
    return 'neutral';
  }
  function sizingText(result){
    const s=result?.sizing;if(!s||s.status==='NOT_APPLICABLE')return 'non applicable';
    if(s.status==='UNCOVERED')return 'non couvert';
    if(s.status==='UNKNOWN_OBSERVED_SIZE')return 'attendu mais sizing joué indisponible';
    const expected=(s.expected||[]).map(x=>`${Number(x.target_total_bb).toFixed(2)} BB${Number.isFinite(Number(x.probability))?` (${(100*Number(x.probability)).toFixed(0)} %)` : ''}`).join(' / ');
    if(s.status==='MATCHED')return `conforme · ${expected}`;
    if(s.status==='OUT_OF_RANGE')return `hors plan · attendu ${expected}`;
    return s.status;
  }
  function contextText(result){
    const c=result?.resolved_context;if(!c)return result?.context_status||'non couvert';
    return `${c.position} · ${c.spot} · ${Number(c.effective_stack_bb).toFixed(1)} BB`;
  }
  function frequencyText(result){
    const p=Number(result?.action_probability);return Number.isFinite(p)?`${(100*p).toFixed(p*100<10?1:0)} %`:'—';
  }

  function summaryHtml(summary){
    if(!summary||!summary.decisions)return '<div class="hc-empty">Aucune décision Hero préflop exploitable dans les mains chargées.</div>';
    const groups=(summary.groups||[]).filter(g=>g.key!=='UNRESOLVED').sort((a,b)=>String(a.key).localeCompare(String(b.key)));
    const rows=groups.map(g=>{
      const pct=g.judged?Math.round(100*g.allowed/g.judged):null;
      return `<div class="hc-group"><span>${esc(g.position)} · ${esc(g.spot)}</span><b>${pct==null?'—':pct+' %'}</b><small>${g.allowed}/${g.judged} autorisées · ${g.uncovered} non couvertes${g.sizing_out_of_range?` · ${g.sizing_out_of_range} sizing hors plan`:''}</small></div>`;
    }).join('');
    return `<div class="hc-session-head"><span>Bilan des mains chargées</span><b>${summary.allowed}/${summary.judged} décisions autorisées</b></div>${rows||'<div class="hc-empty">Aucun groupe couvert.</div>'}`;
  }

  function ensurePanel(){
    let panel=document.getElementById(PANEL_ID);if(panel)return panel;
    const anchor=document.getElementById('hhVisualReplay')||document.getElementById('replayerPage');if(!anchor)return null;
    panel=document.createElement('section');panel.id=PANEL_ID;panel.className='hero-compliance-panel';
    panel.innerHTML='<div class="hc-empty">Chargement du contrôle de range Hero…</div>';
    anchor.insertAdjacentElement(anchor.id==='hhVisualReplay'?'afterend':'afterbegin',panel);
    return panel;
  }

  function render(){
    if(typeof document==='undefined'||typeof state==='undefined')return;
    const panel=ensurePanel();if(!panel)return;
    const hand=state.selectedHand;
    const loaded=loadRepository(),repo=loaded.repo;
    let markup='';
    if(loaded.error){
      markup=`<div class="hc-head"><b>Conformité range Hero</b><span class="hc-status neutral">Pas de verdict</span></div><div class="hc-empty">${esc(loaded.error)}</div><a class="hc-link" href="./hero-ranges.html">Ouvrir l’éditeur de ranges</a>`;
    }else if(!repo){
      markup='<div class="hc-head"><b>Conformité range Hero</b><span class="hc-status neutral">Pas de range</span></div><div class="hc-empty">Aucun dépôt Hero enregistré. Le moteur de recommandation reste indépendant de ce contrôle.</div><a class="hc-link" href="./hero-ranges.html">Définir / importer les ranges Hero</a>';
    }else{
      const current=currentEvaluation(hand,repo),resolution=current.resolution,result=current.result,summary=sessionSummary(repo,resolution),token=root.PokerHeroCompliance.repositoryVersionToken(repo);
      if(!result){
        markup=`<div class="hc-head"><b>Conformité range Hero</b><span class="hc-status neutral">Pas de verdict</span></div><div class="hc-empty">${esc(current.label)}</div>${summaryHtml(summary)}<div class="hc-foot">Range ${esc(token)} · ${esc(resolutionText(resolution))} · conformité au plan Hero distincte de la recommandation moteur · écart EV non évalué.</div><a class="hc-link" href="./hero-ranges.html">Ouvrir la grille Hero</a>`;
      }else{
        const layer=result.layer?`${result.layer}${result.layer_version!=null?` v${result.layer_version}`:''}`:'—';
        const overrideNote=result.strategy_source==='PERSONAL_OVERRIDE'
          ?'<div class="hc-note">Override personnel : ce verdict porte sur votre couche personnelle et ne représente pas la stratégie calculée de la population.</div>'
          :'';
        markup=`<div class="hc-head"><div><b>Conformité range Hero</b><small>${esc(current.label)}</small></div><span class="hc-status ${statusClass(result)}">${esc(statusLabel(result))}</span></div>
          <div class="hc-metrics">
            <div><span>Contexte</span><b>${esc(contextText(result))}</b></div>
            <div><span>Main / action</span><b>${esc(result.hand_class||'—')} · ${esc(result.planned_action||result.observed_runtime_action||'—')}</b></div>
            <div><span>Fréquence prescrite</span><b>${esc(frequencyText(result))}</b></div>
            <div><span>Couche / version</span><b>${esc(layer)}</b></div>
            <div class="hc-wide"><span>Origine de la stratégie</span><b>${esc(strategySourceText(result))} · population ${esc(result.population_id||'—')} · ${esc(resolutionText(resolution))}</b></div>
            <div class="hc-wide"><span>Sizing</span><b>${esc(sizingText(result))}</b></div>
            <div><span>Écart EV</span><b>non évalué</b></div>
          </div>
          <div class="hc-note">Une action mixée à fréquence positive est autorisée sur une occurrence isolée ; la calibration des fréquences nécessite un échantillon adapté. Ce verdict n’utilise que les cartes Hero connues dès le départ et l’état antérieur à l’action.</div>
          ${overrideNote}
          ${summaryHtml(summary)}
          <div class="hc-foot">Range ${esc(result.repository_token)} · ${esc(strategySourceText(result))} · population ${esc(result.population_id||'—')} · recommandation moteur et conformité Hero sont deux axes distincts.</div>
          <a class="hc-link" href="${esc(result.editor_href||'./hero-ranges.html')}">Voir / modifier cette grille</a>`;
      }
    }
    const style=`<style>
      #${PANEL_ID}{margin:12px 0;padding:12px 14px;border:1px solid #344465;border-radius:12px;background:#10182a;color:#eef2ff;font:12px/1.35 Inter,system-ui,sans-serif}
      #${PANEL_ID} .hc-head{display:flex;justify-content:space-between;gap:12px;align-items:center;margin-bottom:10px}#${PANEL_ID} .hc-head b{font-size:14px}#${PANEL_ID} .hc-head small{display:block;color:#9aa7c2;margin-top:2px}
      #${PANEL_ID} .hc-status{padding:5px 8px;border-radius:999px;font-weight:800;white-space:nowrap}#${PANEL_ID} .hc-status.good{background:#12352d;color:#78e3bf}#${PANEL_ID} .hc-status.bad{background:#3c1d26;color:#ff9aa9}#${PANEL_ID} .hc-status.neutral{background:#263149;color:#bdc8df}
      #${PANEL_ID} .hc-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:7px}#${PANEL_ID} .hc-metrics>div{padding:7px 8px;border:1px solid #263553;border-radius:8px;background:#0c1424}#${PANEL_ID} .hc-metrics .hc-wide{grid-column:span 3}#${PANEL_ID} .hc-metrics span{display:block;color:#8f9db9;font-size:10px}#${PANEL_ID} .hc-metrics b{display:block;margin-top:2px;font-size:11px}
      #${PANEL_ID} .hc-note,#${PANEL_ID} .hc-foot,#${PANEL_ID} .hc-empty{margin-top:8px;color:#9aa7c2}#${PANEL_ID} .hc-foot{font-size:10px}#${PANEL_ID} .hc-link{display:inline-block;margin-top:8px;color:#9facff;font-weight:700;text-decoration:none}
      #${PANEL_ID} .hc-session-head{display:flex;justify-content:space-between;gap:8px;margin-top:10px;padding-top:9px;border-top:1px solid #263553}#${PANEL_ID} .hc-group{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:1px 8px;padding:4px 0}#${PANEL_ID} .hc-group small{grid-column:1/-1;color:#8492ad}
      @media(max-width:760px){#${PANEL_ID} .hc-metrics{grid-template-columns:1fr 1fr}#${PANEL_ID} .hc-metrics .hc-wide{grid-column:1/-1}}
    </style>`;
    const full=style+markup;if(full===lastMarkup)return;lastMarkup=full;panel.innerHTML=full;
  }

  function invalidate(){sessionCache={key:null,summary:null};lastMarkup='';render();}
  root.addEventListener?.('storage',e=>{if(e.key===STORAGE_KEY)invalidate();});
  root.addEventListener?.('focus',render);
  if(typeof document!=='undefined'){
    if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',render,{once:true});else render();
    setInterval(render,500);
  }
  root.PokerHeroComplianceReplayer={STORAGE_KEY,handClass,loadRepository,activePopulationId,strategyResolutionFor,currentEvaluation,sessionSummary,render,invalidate};
})(typeof globalThis!=='undefined'?globalThis:this);

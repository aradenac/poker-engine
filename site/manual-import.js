"use strict";

(function(global){
  const CONTRACT_SCHEMA="poker-manual-override/v1";
  const CLASSIFICATION="MANUAL_OVERRIDE";
  const NON_STANDARD="NON_STANDARD";
  const DB_NAME="PokerRangeEquityOffline";
  const DB_VERSION=1;
  const STORE="kv";
  const CONTRACT_KEY="manualOverrideContract";
  const ROLE_KEYS={
    hero_ranges:"rangeSource",
    model_a_preflop:"populationModelSource",
    model_a_postflop:"postflopModelSource"
  };
  const SUPPORTED_ROLES=Object.freeze(Object.keys(ROLE_KEYS));
  const RESTORE_ACTION="RESTORE_ACTIVE_PACK";
  const Identity=global.PokerPackIdentity;
  if(!Identity)throw new Error("PokerPackIdentity requis avant manual-import.js.");
  const {sha256,contentIdentity,packIdentity,samePackIdentity}=Identity;

  function openDb(){
    return new Promise((resolve,reject)=>{
      const req=indexedDB.open(DB_NAME,DB_VERSION);
      req.onupgradeneeded=()=>{
        const db=req.result;
        if(!db.objectStoreNames.contains(STORE))db.createObjectStore(STORE);
      };
      req.onsuccess=()=>resolve(req.result);
      req.onerror=()=>reject(req.error||new Error("IndexedDB indisponible"));
    });
  }
  async function getKey(key){
    const db=await openDb();
    try{
      return await new Promise((resolve,reject)=>{
        const tx=db.transaction(STORE,"readonly");
        const req=tx.objectStore(STORE).get(key);
        req.onsuccess=()=>resolve(req.result);
        req.onerror=()=>reject(req.error);
      });
    }finally{db.close();}
  }
  async function atomicWrite({put={},del=[]}){
    const db=await openDb();
    try{
      await new Promise((resolve,reject)=>{
        const tx=db.transaction(STORE,"readwrite"),store=tx.objectStore(STORE);
        for(const [key,value] of Object.entries(put))store.put(value,key);
        for(const key of del)store.delete(key);
        tx.oncomplete=resolve;
        tx.onerror=()=>reject(tx.error||new Error("Transaction override échouée"));
        tx.onabort=()=>reject(tx.error||new Error("Transaction override annulée"));
      });
    }finally{db.close();}
  }

  function clone(value){return value===undefined?undefined:JSON.parse(JSON.stringify(value));}
  function isObject(value){return !!value&&typeof value==="object"&&!Array.isArray(value);}
  function safeString(value){return typeof value==="string"&&value.trim()?value.trim():null;}

  function collectRanges(folder,path=[]){
    const out=[];
    if(!isObject(folder))return out;
    const here=[...path,folder.name||"Folder"].filter(Boolean);
    for(const range of (Array.isArray(folder.ranges)?folder.ranges:[])){
      if(isObject(range))out.push({...range,__path:here.join(" / ")});
    }
    for(const child of (Array.isArray(folder.folders)?folder.folders:[])){
      out.push(...collectRanges(child,here));
    }
    return out;
  }

  function declaredPopulation(json){
    return safeString(
      json?.population_id ??
      json?.populationId ??
      json?.dataset?.population_id ??
      json?.population?.population_id ??
      json?.population_identity?.population_id
    );
  }
  function declaredEngineVersion(json){
    return safeString(
      json?.engine_version ??
      json?.engineVersion ??
      json?.compatibility?.engine_version ??
      json?.dataset?.engine_version
    );
  }
  function schemaLabel(json){
    return safeString(json?.schema ?? json?.schema_version ?? json?.schemaVersion ?? json?.model_type) || "legacy-structural";
  }

  function validateHeroRanges(json){
    if(!isObject(json))throw new Error("JSON de ranges invalide.");
    if(json.exportType&&json.exportType!=="range-folder")throw new Error("Schéma de ranges non supporté.");
    if(json.schemaVersion!==undefined&&Number(json.schemaVersion)!==1)throw new Error("Version de range-folder non supportée.");
    const ranges=collectRanges(json.folder||json);
    if(!ranges.length)throw new Error("Aucune range legacy exploitable trouvée.");
    const usable=ranges.some(r=>Array.isArray(r.positions)&&r.positions.some(p=>Array.isArray(p?.hands)));
    if(!usable)throw new Error("Le fichier ne contient pas de positions/hands exploitables.");
  }
  function validatePreflop(json){
    if(!isObject(json))throw new Error("JSON Model A préflop invalide.");
    if(json.model_type&&json.model_type!=="preflop_population")throw new Error("Rôle incohérent : ce fichier n'est pas un modèle préflop.");
    if(!Array.isArray(json.nodes)||!json.nodes.length)throw new Error("Model A préflop sans nœuds.");
    if(!Array.isArray(json.hand_grid?.classes)||!isObject(json.hand_grid?.meta))throw new Error("Grille 169 préflop absente.");
    const usable=json.nodes.some(n=>n?.context?.actor_position&&n?.population_model?.frequencies);
    if(!usable)throw new Error("Aucun nœud préflop exploitable.");
  }
  function validatePostflop(json){
    if(!isObject(json))throw new Error("JSON Model A postflop invalide.");
    if(json.model_type!=="postflop_population")throw new Error("Rôle incohérent : ce fichier n'est pas un modèle postflop.");
    if(!Array.isArray(json.nodes)||!json.nodes.length)throw new Error("Model A postflop sans nœuds.");
    if(!isObject(json.response_models))throw new Error("Modèles de réponse postflop absents.");
  }
  const ROLE_VALIDATORS={
    hero_ranges:validateHeroRanges,
    model_a_preflop:validatePreflop,
    model_a_postflop:validatePostflop
  };

  async function activePackRecord(){
    const packs=global.PokerPopulationPacks;
    if(!packs?.active)return null;
    return packs.active();
  }
  function preserveHeroPolicy(record){
    const entry=record?.entry||{};
    return entry?.customization_policy?.preserve_hero_manual_ranges===true ||
      entry?.hero_customization_policy?.preserve_manual_ranges===true;
  }

  async function validateFile(role,file,basePack){
    if(!SUPPORTED_ROLES.includes(role))throw new Error("Rôle d'override non supporté.");
    if(!file||typeof file.text!=="function")throw new Error("Fichier manquant.");
    const content=await file.text();
    let json;
    try{json=JSON.parse(content);}catch(_){throw new Error("Fichier JSON corrompu ou invalide.");}
    ROLE_VALIDATORS[role](json);
    const populationId=declaredPopulation(json);
    if(populationId&&basePack.population_id&&populationId!==basePack.population_id){
      throw new Error(`Population incompatible : ${populationId} ≠ ${basePack.population_id}.`);
    }
    const engineVersion=declaredEngineVersion(json);
    if(engineVersion&&basePack.engine_version&&engineVersion!==basePack.engine_version){
      throw new Error(`Version moteur incompatible : ${engineVersion} ≠ ${basePack.engine_version}.`);
    }
    const identity=await contentIdentity(content),digest=identity.sha256;
    const snapshot={
      name:file.name||`${role}.json`,
      size:Number(file.size)||content.length,
      lastModified:Number(file.lastModified)||Date.now(),
      type:file.type||"application/json",
      content
    };
    return {
      role,
      source_type:"MANUAL_JSON_FILE",
      filename:snapshot.name,
      sha256:digest,
      size_bytes:snapshot.size,
      population_id:populationId,
      engine_version:engineVersion,
      schema:schemaLabel(json),
      compatibility_status:"COMPATIBLE",
      snapshot,
      json
    };
  }

  async function loadActiveSources(contract){
    const sources=[];
    if(!contract?.active)return sources;
    for(const source of (contract.sources||[])){
      if(!SUPPORTED_ROLES.includes(source.role))continue;
      const snapshot=await getKey(ROLE_KEYS[source.role]);
      if(!snapshot?.content)throw new Error(`Override persistant incomplet pour ${source.role}.`);
      const file={
        name:snapshot.name||source.filename||`${source.role}.json`,
        size:Number(snapshot.size)||String(snapshot.content).length,
        lastModified:Number(snapshot.lastModified)||Date.now(),
        type:snapshot.type||"application/json",
        text:async()=>String(snapshot.content)
      };
      sources.push({source,snapshot,file});
    }
    return sources;
  }

  function assertCoherentPopulation(sources,basePack){
    const declared=[...new Set(sources.map(s=>s.population_id).filter(Boolean))];
    if(declared.length>1)throw new Error(`Mix de populations incohérent : ${declared.join(", ")}.`);
    if(declared.length===1&&basePack.population_id&&declared[0]!==basePack.population_id){
      throw new Error(`Override d'une autre population refusé : ${declared[0]}.`);
    }
  }

  function contractWarnings(sources,basePack){
    const warnings=["MANUAL_OVERRIDE / NON_STANDARD : ces fichiers ne sont pas des composants promus."];
    if(!basePack.population_id)warnings.push("Population du fallback actif inconnue : compatibilité population non vérifiable.");
    for(const source of sources){
      if(!source.population_id)warnings.push(`${source.role}: population_id absente du fichier.`);
      if(!source.engine_version&&(source.role==="model_a_preflop"||source.role==="model_a_postflop")){
        warnings.push(`${source.role}: version moteur non déclarée ; contrôle limité au schéma/rôle.`);
      }
    }
    return [...new Set(warnings)];
  }

  function sourcePublic(source){
    const copy={...source};
    delete copy.snapshot;
    delete copy.json;
    return copy;
  }

  async function activateFiles(items){
    if(!Array.isArray(items)||!items.length)throw new Error("Aucun fichier sélectionné.");
    const activeRecord=await activePackRecord();
    const basePack=packIdentity(activeRecord);
    const previous=await getKey(CONTRACT_KEY);
    if(previous?.active&&!samePackIdentity(previous.base_active_pack,basePack)){
      throw new Error("Override lié à une autre identité de pack. Utilisez RESTORE_ACTIVE_PACK avant de continuer.");
    }

    const existingByRole=new Map();
    if(previous?.active){
      const activeSources=await loadActiveSources(previous);
      for(const row of activeSources){
        const validated=await validateFile(row.source.role,row.file,basePack);
        existingByRole.set(validated.role,validated);
      }
    }

    const seen=new Set();
    for(const item of items){
      const role=String(item?.role||"");
      if(seen.has(role))throw new Error(`Rôle dupliqué dans la transaction : ${role}.`);
      seen.add(role);
      const validated=await validateFile(role,item.file,basePack);
      existingByRole.set(role,validated);
    }

    const sources=[...existingByRole.values()].sort((a,b)=>a.role.localeCompare(b.role));
    assertCoherentPopulation(sources,basePack);

    const now=new Date().toISOString();
    const sessionId=crypto.randomUUID?crypto.randomUUID():await sha256(now+Math.random());
    const contract={
      schema:CONTRACT_SCHEMA,
      active:true,
      classification:CLASSIFICATION,
      configuration_status:NON_STANDARD,
      source_type:"MANUAL_JSON",
      roles_overridden:sources.map(s=>s.role),
      sources:sources.map(sourcePublic),
      base_active_pack:basePack,
      session:{id:sessionId,activated_at:now,surface:"manual-import"},
      compatibility_status:"COMPATIBLE",
      warnings:contractWarnings(sources,basePack),
      restore_action:RESTORE_ACTION
    };

    const put={[CONTRACT_KEY]:contract};
    for(const source of sources)put[ROLE_KEYS[source.role]]=source.snapshot;
    await atomicWrite({put});

    const persisted=await getKey(CONTRACT_KEY);
    if(!persisted?.active||persisted.session?.id!==sessionId)throw new Error("Activation atomique non vérifiée.");
    return clone(persisted);
  }

  async function restoreActivePack(){
    const activeRecord=await activePackRecord();
    const basePack=packIdentity(activeRecord);
    const current=await getKey(CONTRACT_KEY);
    const preserveHero=preserveHeroPolicy(activeRecord)&&current?.active&&current.roles_overridden?.includes("hero_ranges");
    const now=new Date().toISOString();
    const retained=preserveHero?["hero_ranges"]:[];
    const inactive={
      schema:CONTRACT_SCHEMA,
      active:false,
      classification:preserveHero?"PACK_ALLOWED_CUSTOMIZATION":"ACTIVE_PACK",
      configuration_status:preserveHero?"STANDARD_WITH_PACK_ALLOWED_HERO_CUSTOMIZATION":"STANDARD",
      source_type:"ACTIVE_PACK",
      roles_overridden:[],
      retained_customizations:retained,
      sources:[],
      base_active_pack:basePack,
      session:{restored_at:now,surface:"manual-import"},
      compatibility_status:"RESTORED_ACTIVE_PACK",
      warnings:preserveHero?["Personnalisation Hero conservée car explicitement autorisée par le contrat du pack."]:[],
      restore_action:RESTORE_ACTION
    };
    const del=["populationModelSource","postflopModelSource"];
    if(!preserveHero)del.push("rangeSource");
    await atomicWrite({put:{[CONTRACT_KEY]:inactive},del});

    const verified=await getKey(CONTRACT_KEY);
    if(verified?.active||!samePackIdentity(verified?.base_active_pack,basePack)){
      throw new Error("RESTORE_ACTIVE_PACK non vérifié.");
    }
    for(const role of ["model_a_preflop","model_a_postflop"]){
      if(await getKey(ROLE_KEYS[role]))throw new Error(`RESTORE_ACTIVE_PACK incomplet : ${role} persiste.`);
    }
    if(!preserveHero&&await getKey("rangeSource"))throw new Error("RESTORE_ACTIVE_PACK incomplet : hero_ranges persiste.");
    return clone(verified);
  }

  async function inspect(){
    const activeRecord=await activePackRecord();
    const activePack=packIdentity(activeRecord);
    const stored=await getKey(CONTRACT_KEY);
    if(!stored){
      return {
        schema:CONTRACT_SCHEMA,
        active:false,
        classification:"ACTIVE_PACK",
        configuration_status:"STANDARD",
        source_type:"ACTIVE_PACK",
        roles_overridden:[],
        sources:[],
        base_active_pack:activePack,
        compatibility_status:"NO_OVERRIDE",
        warnings:[],
        restore_action:RESTORE_ACTION
      };
    }
    const out=clone(stored);
    if(out.active&&!samePackIdentity(out.base_active_pack,activePack)){
      out.compatibility_status="STALE_BASE_PACK";
      out.warnings=[...(out.warnings||[]),"Le pack actif a changé : cet override ne doit pas être réutilisé silencieusement."];
    }
    return out;
  }

  function selectedItemsFromUi(){
    const map=[
      ["hero_ranges",document.getElementById("heroRangesInput")],
      ["model_a_preflop",document.getElementById("preflopInput")],
      ["model_a_postflop",document.getElementById("postflopInput")]
    ];
    return map.flatMap(([role,input])=>input?.files?.[0]?[{role,file:input.files[0]}]:[]);
  }
  function resetInputs(){
    for(const id of ["heroRangesInput","preflopInput","postflopInput"]){
      const input=document.getElementById(id);if(input)input.value="";
    }
  }
  function shortIdentity(pack){
    if(pack?.id==="embedded-fallback")return "Fallback embarqué";
    if(!pack?.id)return "Pack actif inconnu";
    return `${pack.pack_id||"pack"} · ${pack.pack_version||"?"} · ${pack.population_id||"population inconnue"}`;
  }
  async function render(){
    if(!global.document)return;
    const state=await inspect();
    const badge=document.getElementById("overrideBadge");
    const title=document.getElementById("overrideTitle");
    const base=document.getElementById("basePack");
    const roles=document.getElementById("activeRoles");
    const compat=document.getElementById("compatibilityBadge");
    const restore=document.getElementById("restoreBtn");
    const pre=document.getElementById("contractJson");
    if(badge){
      badge.textContent=state.active?"Override manuel · configuration non standard":"Pack actif";
      badge.className=`badge ${state.active?"override":"standard"}`;
    }
    if(title)title.textContent=state.active?"MANUAL_OVERRIDE / NON_STANDARD":"Aucun override manuel";
    if(base)base.textContent=shortIdentity(state.base_active_pack);
    if(compat)compat.textContent=state.compatibility_status;
    if(restore)restore.disabled=!state.active;
    if(roles){
      roles.innerHTML=state.active&&state.roles_overridden.length
        ?state.sources.map(s=>`<span class="role-chip" title="${String(s.filename||"").replaceAll('"','&quot;')}">${s.role} · ${s.filename}</span>`).join("")
        :'<span class="muted">Aucun.</span>';
    }
    if(pre)pre.textContent=JSON.stringify(state,null,2);
  }

  async function initUi(){
    if(!global.document)return;
    const activate=document.getElementById("activateBtn");
    const restore=document.getElementById("restoreBtn");
    const status=document.getElementById("actionStatus");
    const inputs=[...document.querySelectorAll('input[type="file"][data-role]')];
    const refreshSelection=()=>{
      const n=selectedItemsFromUi().length;
      if(status){status.textContent=n?`${n} fichier(s) prêt(s) à valider.`:"Aucun fichier sélectionné.";status.className="muted";}
    };
    for(const input of inputs)input.addEventListener("change",refreshSelection);
    activate?.addEventListener("click",async()=>{
      try{
        activate.disabled=true;
        if(status){status.textContent="Validation et activation atomique…";status.className="muted";}
        const result=await activateFiles(selectedItemsFromUi());
        resetInputs();
        if(status){status.textContent=`${result.roles_overridden.length} override(s) actif(s).`;status.className="ok";}
        await render();
      }catch(err){
        if(status){status.textContent=err?.message||String(err);status.className="error";}
      }finally{activate.disabled=false;}
    });
    restore?.addEventListener("click",async()=>{
      try{
        restore.disabled=true;
        if(status){status.textContent="RESTORE_ACTIVE_PACK…";status.className="muted";}
        await restoreActivePack();
        resetInputs();
        if(status){status.textContent="Pack actif restauré. Aucun mix manuel ne reste actif.";status.className="ok";}
        await render();
      }catch(err){
        if(status){status.textContent=err?.message||String(err);status.className="error";}
      }finally{await render();}
    });
    await render();
  }

  global.PokerManualOverrides={
    CONTRACT_SCHEMA,DB_NAME,STORE,CONTRACT_KEY,SUPPORTED_ROLES,RESTORE_ACTION,
    sha256,inspect,activateFiles,restoreActivePack,render,
    _test:{getKey,validateFile,declaredPopulation,declaredEngineVersion,collectRanges,packIdentity}
  };

  if(global.document){
    if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",()=>initUi().catch(console.error));
    else initUi().catch(console.error);
  }
})(window);

"use strict";
const Packs=window.PokerPopulationPacks;
const $=id=>document.getElementById(id);
const els={active:$("activePack"),activeMeta:$("activeMeta"),rollback:$("rollbackBtn"),refresh:$("refreshBtn"),catalog:$("catalog"),catalogStatus:$("catalogStatus"),importZip:$("importZip"),exportSelect:$("exportSelect"),exportBtn:$("exportBtn"),offlineStatus:$("offlineStatus")};
let catalog=null,busy=false;
function status(el,text,kind=""){el.textContent=text;el.className=`notice${kind?` ${kind}`:""}`;}
function esc(x){return String(x??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"})[c]);}
function formatIdentity(e){const p=e.population_identity||{};return [p.platform,p.variant,p.stake,p.money,p.format].filter(Boolean).join(" · ");}
async function snapshot(){const [active,previous,installed]=await Promise.all([Packs.active(),Packs.previous(),Packs.installed()]);return {active,previous,installed};}
async function render(){
  const s=await snapshot();
  if(s.active){els.active.textContent=`${s.active.pack_id}`;els.activeMeta.textContent=`${s.active.population_id} · révision ${s.active.runtime_revision.slice(0,12)} · installé ${new Date(s.active.installed_at).toLocaleString("fr-FR")}`;}
  else{els.active.textContent="Aucun pack navigateur actif — assets statiques par défaut";els.activeMeta.textContent="Le trainer utilise la référence embarquée dans l’application.";}
  els.rollback.disabled=busy||!s.previous;
  els.exportSelect.innerHTML=s.installed.length?s.installed.map(p=>`<option value="${esc(p.id)}">${esc(p.pack_id)} · ${esc(p.runtime_revision.slice(0,10))}</option>`).join(""):'<option value="">Aucun pack installé</option>';
  els.exportBtn.disabled=busy||!s.installed.length;
  if(!catalog){els.catalog.innerHTML="";return;}
  const installedById=new Map(s.installed.map(p=>[p.id,p]));
  els.catalog.innerHTML="";
  for(const e of catalog.entries){
    const id=Packs.storageId(e),exact=installedById.get(id),isActive=s.active?.id===id,older=s.installed.find(p=>p.pack_id===e.pack_id&&p.id!==id);let compatible=true,compatError="";
    try{await Packs.assertCompatibility(e);}catch(err){compatible=false;compatError=err.message||String(err);}
    const card=document.createElement("article");card.className="pack-card";
    const buttonLabel=isActive?"Actif":exact?"Activer":older?"Mettre à jour":"Charger";
    card.innerHTML=`<div><div class="pack-title">${esc(e.pack_id)}</div><div class="badges">${e.recommended?'<span class="badge recommended">recommandé</span>':""}${exact?'<span class="badge installed">installé</span>':""}${isActive?'<span class="badge active">actif</span>':""}</div><div class="pack-meta">${esc(formatIdentity(e))}<br>Version ${esc(e.pack_version)} · moteur ${esc(e.engine_version)} · Model A ${esc(e.model_a_version)} · ${esc(e.model_b_alias)}<br>Révision runtime <code>${esc(e.runtime_revision.slice(0,16))}</code>${compatible?"":`<br><strong>Application à mettre à jour :</strong> ${esc(compatError)}`}</div></div><div class="pack-actions"><button class="primary action" type="button" ${busy||isActive||!compatible?"disabled":""}>${buttonLabel}</button>${exact?'<button class="export-one" type="button">Exporter ZIP</button>':""}</div>`;
    const action=card.querySelector(".action");action?.addEventListener("click",()=>loadAndActivate(e,!!exact));
    card.querySelector(".export-one")?.addEventListener("click",()=>exportPack(id));els.catalog.appendChild(card);
  }
}
async function loadAndActivate(entry,alreadyInstalled){
  if(busy)return;busy=true;status(els.catalogStatus,alreadyInstalled?"Activation transactionnelle…":"Téléchargement et vérification de tous les assets…");await render();
  try{let record=alreadyInstalled?await Packs.installed().then(rows=>rows.find(x=>x.id===Packs.storageId(entry))):await Packs.install(entry);if(!record)throw new Error("Pack installé introuvable.");await Packs.activate(record.id);status(els.catalogStatus,`Pack ${record.pack_id} vérifié et activé. Le prochain chargement de l’analyseur utilisera uniquement cette génération.`,"ok");}
  catch(err){status(els.catalogStatus,`Activation refusée : ${err.message||err}`,"error");}
  finally{busy=false;await render();}
}
async function exportPack(id){try{const row=(await Packs.installed()).find(x=>x.id===id);if(!row)throw new Error("Pack absent.");const zip=await Packs.exportZip(id);Packs.downloadBytes(zip,`${row.pack_id.replace(/[^a-zA-Z0-9._-]+/g,"-")}-runtime.zip`);status(els.offlineStatus,`Export ZIP prêt : ${row.pack_id}.`,"ok");}catch(err){status(els.offlineStatus,`Export impossible : ${err.message||err}`,"error");}}
async function refresh(){
  if(busy)return;busy=true;status(els.catalogStatus,"Chargement du catalogue same-origin…");els.refresh.disabled=true;
  try{catalog=await Packs.fetchCatalog();status(els.catalogStatus,`${catalog.entries.length} génération(s) publiée(s). Les hashes seront revérifiés au téléchargement.`,"ok");}
  catch(err){catalog=null;status(els.catalogStatus,`Catalogue indisponible : ${err.message||err}`,"error");}
  finally{busy=false;els.refresh.disabled=false;await render();}
}
els.rollback.addEventListener("click",async()=>{if(busy)return;busy=true;try{const row=await Packs.rollback();status(els.catalogStatus,`Retour effectué vers ${row.pack_id} · ${row.runtime_revision.slice(0,12)}.`,"ok");}catch(err){status(els.catalogStatus,`Rollback impossible : ${err.message||err}`,"error");}finally{busy=false;await render();}});
els.refresh.addEventListener("click",refresh);
els.exportBtn.addEventListener("click",()=>els.exportSelect.value&&exportPack(els.exportSelect.value));
els.importZip.addEventListener("change",async event=>{const file=event.target.files?.[0];event.target.value="";if(!file||busy)return;busy=true;status(els.offlineStatus,`Vérification de ${file.name}…`);try{const record=await Packs.importZip(await file.arrayBuffer());await Packs.activate(record.id);status(els.offlineStatus,`ZIP validé et activé : ${record.pack_id}.`,"ok");}catch(err){status(els.offlineStatus,`Import refusé, pack actif inchangé : ${err.message||err}`,"error");}finally{busy=false;await render();}});
(async()=>{try{await Packs.registerServiceWorker();}catch(err){status(els.catalogStatus,`Service Worker indisponible : ${err.message||err}`,"error");}await render();await refresh();})();

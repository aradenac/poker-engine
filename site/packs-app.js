"use strict";
const Packs=window.PokerPopulationPacks;
const $=id=>document.getElementById(id);
const els={active:$("activePack"),activeMeta:$("activeMeta"),rollbackMeta:$("rollbackMeta"),rollback:$("rollbackBtn"),refresh:$("refreshBtn"),catalog:$("catalog"),catalogStatus:$("catalogStatus"),importZip:$("importZip"),exportSelect:$("exportSelect"),exportBtn:$("exportBtn"),offlineStatus:$("offlineStatus")};
let catalog=null,busy=false;
function status(el,text,kind=""){el.textContent=text;el.className=`notice${kind?` ${kind}`:""}`;}
function esc(x){return String(x??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"})[c]);}
function formatIdentity(e){const p=e.population_identity||{};return [p.platform,p.variant,p.stake,p.money,p.format].filter(Boolean).join(" · ");}
function displayName(e){const p=e.population_identity||{};const bits=[p.platform,p.variant,p.stake,p.format].filter(Boolean);return bits.length?bits.join(" · "):(e.population_id||e.pack_id);}
function versionLabel(e){return e.pack_version?`Version ${e.pack_version}`:"Version non renseignée";}
function sourceLabel(e){const source=e.source_release||{};return source.tag||source.pack_id||e.release_tag||"Catalogue publié";}
function componentsLabel(e){return (e.assets||[]).map(a=>a.key).join(", ");}
async function snapshot(){const [active,previous,installed]=await Promise.all([Packs.active(),Packs.previous(),Packs.installed()]);return {active,previous,installed};}
async function render(){
  const s=await snapshot();
  if(s.active){
    els.active.textContent=`${displayName(s.active.entry)} — ${versionLabel(s.active.entry).toLowerCase()}`;
    els.activeMeta.textContent=`Utilisée par l’analyseur · installée ${new Date(s.active.installed_at).toLocaleString("fr-FR")}`;
  }else{
    els.active.textContent="Population incluse dans l’application";
    els.activeMeta.textContent="Aucune version personnalisée n’est active.";
  }
  els.rollback.disabled=busy||!s.previous;
  if(s.previous){
    els.rollbackMeta.textContent=`Version précédente disponible : ${displayName(s.previous.entry)} — ${versionLabel(s.previous.entry).toLowerCase()}.`;
    els.rollbackMeta.className="rollback-meta available";
  }else{
    els.rollbackMeta.textContent="Aucune version précédente disponible pour le moment.";
    els.rollbackMeta.className="rollback-meta";
  }
  els.exportSelect.innerHTML=s.installed.length?s.installed.map(p=>`<option value="${esc(p.id)}">${esc(displayName(p.entry))} · ${esc(versionLabel(p.entry))}</option>`).join(""):'<option value="">Aucune version installée</option>';
  els.exportBtn.disabled=busy||!s.installed.length;
  if(!catalog){els.catalog.innerHTML="";return;}
  const installedById=new Map(s.installed.map(p=>[p.id,p]));
  els.catalog.innerHTML="";
  for(const e of catalog.entries){
    const id=Packs.storageId(e),exact=installedById.get(id),isActive=s.active?.id===id,older=s.installed.find(p=>p.pack_id===e.pack_id&&p.id!==id);let compatible=true,compatError="";
    try{await Packs.assertCompatibility(e);}catch(err){compatible=false;compatError=err.message||String(err);}
    const updateAvailable=Boolean(older&&!exact);
    const card=document.createElement("article");
    card.className=`pack-card${isActive?" active-card":""}${compatible?"":" incompatible-card"}`;
    const buttonLabel=isActive?"Version active":exact?"Utiliser cette version":updateAvailable?"Mettre à jour":"Installer";
    const primarySummary=isActive
      ?"Cette version est actuellement utilisée par l’analyseur."
      :!compatible
        ?"Cette version nécessite une mise à jour de l’application avant activation."
        :updateAvailable
          ?"Une version plus récente de cette population est disponible."
          :exact
            ?"Cette version est installée et prête à être utilisée."
            :e.recommended
              ?"Version recommandée, prête à être installée."
              :"Version disponible dans le catalogue.";
    const badges=[
      isActive?'<span class="badge active">active</span>':"",
      isActive&&e.recommended?'<span class="badge current">à jour</span>':"",
      !isActive&&updateAvailable?'<span class="badge update">mise à jour disponible</span>':"",
      !isActive&&e.recommended?'<span class="badge recommended">recommandée</span>':"",
      !isActive&&exact?'<span class="badge installed">installée</span>':"",
      !compatible?'<span class="badge incompatible">incompatible</span>':""
    ].join("");
    card.innerHTML=`<div><div class="pack-title">${esc(displayName(e))}</div><div class="pack-version">${esc(versionLabel(e))}</div><div class="badges">${badges}</div><div class="pack-summary">${esc(primarySummary)}</div>${compatible?"":'<span class="compat-warning">Mise à jour de l’application requise.</span>'}<details class="technical-details"><summary>Détails techniques</summary><dl><dt>Identité</dt><dd>${esc(e.pack_id)}</dd><dt>Population</dt><dd>${esc(formatIdentity(e)||e.population_id)}</dd><dt>Révision runtime</dt><dd><code>${esc(e.runtime_revision)}</code></dd><dt>Moteur</dt><dd>${esc(e.engine_version)}</dd><dt>Modèles</dt><dd>Model A ${esc(e.model_a_version||"?")} · ${esc(e.model_b_alias||"Model B")}</dd><dt>Composants</dt><dd>${esc(componentsLabel(e))}</dd><dt>Provenance</dt><dd>${esc(sourceLabel(e))}</dd><dt>Compatibilité</dt><dd>${compatible?"Compatible avec cette version de l’application.":esc(compatError)}</dd><dt>Activation</dt><dd>Tous les composants sont validés avant bascule atomique de la version active.</dd></dl></details></div><div class="pack-actions"><button class="primary action" type="button" ${busy||isActive||!compatible?"disabled":""}>${buttonLabel}</button>${exact?'<button class="export-one" type="button">Exporter ZIP</button>':""}</div>`;
    const action=card.querySelector(".action");action?.addEventListener("click",()=>loadAndActivate(e,!!exact));
    card.querySelector(".export-one")?.addEventListener("click",()=>exportPack(id));els.catalog.appendChild(card);
  }
}
async function loadAndActivate(entry,alreadyInstalled){
  if(busy)return;busy=true;status(els.catalogStatus,alreadyInstalled?"Activation de la version…":"Téléchargement et vérification de la mise à jour…");await render();
  try{let record=alreadyInstalled?await Packs.installed().then(rows=>rows.find(x=>x.id===Packs.storageId(entry))):await Packs.install(entry);if(!record)throw new Error("Version installée introuvable.");await Packs.activate(record.id);status(els.catalogStatus,`${displayName(record.entry)} — ${versionLabel(record.entry)} est maintenant active.`,"ok");}
  catch(err){status(els.catalogStatus,`Activation impossible : ${err.message||err}`,"error");}
  finally{busy=false;await render();}
}
async function exportPack(id){try{const row=(await Packs.installed()).find(x=>x.id===id);if(!row)throw new Error("Version absente.");const zip=await Packs.exportZip(id);Packs.downloadBytes(zip,`${row.pack_id.replace(/[^a-zA-Z0-9._-]+/g,"-")}-runtime.zip`);status(els.offlineStatus,`Export ZIP prêt : ${displayName(row.entry)}.`,"ok");}catch(err){status(els.offlineStatus,`Export impossible : ${err.message||err}`,"error");}}
async function refresh(){
  if(busy)return;busy=true;status(els.catalogStatus,"Recherche des versions disponibles…");els.refresh.disabled=true;
  try{catalog=await Packs.fetchCatalog();status(els.catalogStatus,`${catalog.entries.length} version(s) disponible(s). Les contrôles techniques seront effectués avant toute activation.`,"ok");}
  catch(err){catalog=null;status(els.catalogStatus,`Recherche impossible : ${err.message||err}`,"error");}
  finally{busy=false;els.refresh.disabled=false;await render();}
}
els.rollback.addEventListener("click",async()=>{if(busy)return;busy=true;try{const row=await Packs.rollback();status(els.catalogStatus,`Version précédente restaurée : ${displayName(row.entry)} — ${versionLabel(row.entry)}.`,"ok");}catch(err){status(els.catalogStatus,`Retour impossible : ${err.message||err}`,"error");}finally{busy=false;await render();}});
els.refresh.addEventListener("click",refresh);
els.exportBtn.addEventListener("click",()=>els.exportSelect.value&&exportPack(els.exportSelect.value));
els.importZip.addEventListener("change",async event=>{const file=event.target.files?.[0];event.target.value="";if(!file||busy)return;busy=true;status(els.offlineStatus,`Vérification de ${file.name}…`);try{const record=await Packs.importZip(await file.arrayBuffer());await Packs.activate(record.id);status(els.offlineStatus,`ZIP validé et activé : ${displayName(record.entry)} — ${versionLabel(record.entry)}.`,"ok");}catch(err){status(els.offlineStatus,`Import refusé, version active inchangée : ${err.message||err}`,"error");}finally{busy=false;await render();}});
(async()=>{try{await Packs.registerServiceWorker();}catch(err){status(els.catalogStatus,`Service Worker indisponible : ${err.message||err}`,"error");}await render();await refresh();})();

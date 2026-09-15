"use strict";
(function(global){
  const DB_NAME="poker-population-packs-v1";
  const DB_VERSION=1;
  const PACK_STORE="packs";
  const META_STORE="meta";
  const ACTIVE_KEY="active";
  const PREVIOUS_KEY="previous";
  const CATALOG_SCHEMA="poker-population-catalog/v1";
  const RUNTIME_SCHEMA="poker-browser-runtime-pack/v1";
  const EXPORT_SCHEMA="poker-browser-runtime-pack-export/v1";
  const encoder=new TextEncoder(),decoder=new TextDecoder();

  function bytes(value){
    if(value instanceof Uint8Array)return value;
    if(value instanceof ArrayBuffer)return new Uint8Array(value);
    if(ArrayBuffer.isView(value))return new Uint8Array(value.buffer,value.byteOffset,value.byteLength);
    if(typeof value==="string")return encoder.encode(value);
    throw new TypeError("unsupported byte source");
  }
  function hex(buffer){return [...new Uint8Array(buffer)].map(x=>x.toString(16).padStart(2,"0")).join("");}
  async function sha256(value){return hex(await crypto.subtle.digest("SHA-256",bytes(value)));}
  function storageId(entry){return `${entry.pack_id}::${entry.runtime_revision}`;}
  function asUrlPath(url){return new URL(url,location.href).pathname;}

  function openDb(){
    return new Promise((resolve,reject)=>{
      const req=indexedDB.open(DB_NAME,DB_VERSION);
      req.onupgradeneeded=()=>{
        const db=req.result;
        if(!db.objectStoreNames.contains(PACK_STORE))db.createObjectStore(PACK_STORE,{keyPath:"id"});
        if(!db.objectStoreNames.contains(META_STORE))db.createObjectStore(META_STORE);
      };
      req.onsuccess=()=>resolve(req.result);req.onerror=()=>reject(req.error);
    });
  }
  async function idbGet(store,key){
    const db=await openDb();
    try{return await new Promise((resolve,reject)=>{const tx=db.transaction(store,"readonly"),r=tx.objectStore(store).get(key);r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});}
    finally{db.close();}
  }
  async function idbGetAll(store){
    const db=await openDb();
    try{return await new Promise((resolve,reject)=>{const tx=db.transaction(store,"readonly"),r=tx.objectStore(store).getAll();r.onsuccess=()=>resolve(r.result||[]);r.onerror=()=>reject(r.error);});}
    finally{db.close();}
  }
  async function putPack(record){
    const db=await openDb();
    try{await new Promise((resolve,reject)=>{const tx=db.transaction(PACK_STORE,"readwrite");tx.objectStore(PACK_STORE).put(record);tx.oncomplete=()=>resolve();tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error);});}
    finally{db.close();}
  }
  async function metaGet(key){return idbGet(META_STORE,key);}
  async function metaSetPair(active,previous){
    const db=await openDb();
    try{await new Promise((resolve,reject)=>{const tx=db.transaction(META_STORE,"readwrite"),s=tx.objectStore(META_STORE);s.put(active,ACTIVE_KEY);if(previous)s.put(previous,PREVIOUS_KEY);else s.delete(PREVIOUS_KEY);tx.oncomplete=()=>resolve();tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error);});}
    finally{db.close();}
  }

  function validateCatalog(doc){
    if(!doc||doc.schema!==CATALOG_SCHEMA||!Array.isArray(doc.entries))throw new Error("Catalogue de packs invalide.");
    for(const e of doc.entries)validateEntry(e);
    return doc;
  }
  function validateEntry(e){
    if(!e||e.schema!==RUNTIME_SCHEMA||!e.pack_id||!e.pack_version||!e.population_id||!e.runtime_revision)throw new Error("Entrée de pack invalide.");
    if(!Array.isArray(e.assets)||!e.assets.length)throw new Error(`Pack ${e.pack_id}: assets absents.`);
    const keys=new Set();
    for(const a of e.assets){
      if(!a.key||!a.url||!/^[0-9a-f]{64}$/.test(String(a.sha256||"")))throw new Error(`Pack ${e.pack_id}: descripteur asset invalide.`);
      if(keys.has(a.key))throw new Error(`Pack ${e.pack_id}: clé asset dupliquée ${a.key}.`);keys.add(a.key);
      if(!String(a.url).startsWith("./"))throw new Error(`Pack ${e.pack_id}: URL non same-origin.`);
    }
    for(const key of ["population_manifest","model_a_preflop","model_a_postflop","model_b_profiles","model_b_ranges","model_b_actions","model_b_sizing","model_b_contract","hero_ranges"]){if(!keys.has(key))throw new Error(`Pack ${e.pack_id}: asset requis absent ${key}.`);}
    return e;
  }
  function validateJsonAsset(asset,data,entry){
    let obj;
    try{obj=JSON.parse(decoder.decode(data));}catch(_){throw new Error(`${asset.key}: JSON invalide.`);}
    if(asset.expected_schema&&obj?.schema!==asset.expected_schema)throw new Error(`${asset.key}: schéma ${obj?.schema||"absent"}, attendu ${asset.expected_schema}.`);
    if(asset.key==="population_manifest"&&obj.population_id!==entry.population_id)throw new Error("Le manifeste trainer appartient à une autre population.");
    if(asset.key==="model_a_preflop"&&obj?.model_type!=="preflop_population")throw new Error("Model A préflop incompatible.");
    if(asset.key==="model_a_postflop"&&obj?.model_type!=="postflop_population")throw new Error("Model A postflop incompatible.");
    return obj;
  }
  async function currentRelease(fetchImpl=fetch){
    const r=await fetchImpl("./RELEASE.json",{cache:"no-store"});if(!r.ok)throw new Error(`RELEASE.json : HTTP ${r.status}`);return r.json();
  }
  async function assertCompatibility(entry,fetchImpl=fetch){
    const release=await currentRelease(fetchImpl),c=entry.compatibility||{};
    if(c.application_release_schema&&release.schema!==c.application_release_schema)throw new Error(`Application incompatible : schéma ${release.schema||"?"}.`);
    if(c.engine_version&&release.version!==c.engine_version)throw new Error(`Moteur ${release.version||"?"} incompatible avec le pack ${c.engine_version}.`);
    return release;
  }
  async function fetchCatalog(url="./packs/catalog.json",fetchImpl=fetch){
    const r=await fetchImpl(url,{cache:"no-store"});if(!r.ok)throw new Error(`Catalogue : HTTP ${r.status}`);return validateCatalog(await r.json());
  }
  async function fetchAndValidate(entry,fetchImpl=fetch){
    validateEntry(entry);await assertCompatibility(entry,fetchImpl);
    const files={};
    for(const asset of entry.assets){
      const r=await fetchImpl(asset.url,{cache:"no-store"});if(!r.ok)throw new Error(`${asset.key}: HTTP ${r.status}`);
      const data=new Uint8Array(await r.arrayBuffer());
      if(Number(asset.size_bytes)!==data.byteLength)throw new Error(`${asset.key}: taille invalide.`);
      const digest=await sha256(data);if(digest!==asset.sha256)throw new Error(`${asset.key}: SHA-256 invalide.`);
      validateJsonAsset(asset,data,entry);
      files[asset.key]={key:asset.key,role:asset.role,url:asset.url,path:asUrlPath(asset.url),media_type:asset.media_type||"application/json",sha256:digest,size_bytes:data.byteLength,bytes:data};
    }
    return files;
  }
  async function install(entry,{fetchImpl=fetch,source="catalog"}={}){
    const files=await fetchAndValidate(entry,fetchImpl);
    const record={id:storageId(entry),pack_id:entry.pack_id,pack_version:entry.pack_version,population_id:entry.population_id,runtime_revision:entry.runtime_revision,entry:structuredClone(entry),files,source,installed_at:new Date().toISOString()};
    await putPack(record);return record;
  }
  async function installed(){return idbGetAll(PACK_STORE);}
  async function active(){const id=await metaGet(ACTIVE_KEY);return id?await idbGet(PACK_STORE,id):null;}
  async function previous(){const id=await metaGet(PREVIOUS_KEY);return id?await idbGet(PACK_STORE,id):null;}
  async function activate(id,{fetchImpl=fetch}={}){
    const target=await idbGet(PACK_STORE,id);if(!target)throw new Error("Pack non installé.");await assertCompatibility(target.entry,fetchImpl);
    const old=await metaGet(ACTIVE_KEY);await metaSetPair(id,old&&old!==id?old:await metaGet(PREVIOUS_KEY));return target;
  }
  async function rollback({fetchImpl=fetch}={}){
    const old=await metaGet(PREVIOUS_KEY);if(!old)throw new Error("Aucune génération précédente disponible.");
    const target=await idbGet(PACK_STORE,old);if(!target)throw new Error("La génération précédente n'est plus installée.");await assertCompatibility(target.entry,fetchImpl);
    const cur=await metaGet(ACTIVE_KEY);await metaSetPair(old,cur);return target;
  }

  function crcTable(){const t=new Uint32Array(256);for(let n=0;n<256;n++){let c=n;for(let k=0;k<8;k++)c=(c&1)?0xedb88320^(c>>>1):c>>>1;t[n]=c>>>0;}return t;}
  const CRC_TABLE=crcTable();
  function crc32(value){let c=0xffffffff;for(const b of bytes(value))c=CRC_TABLE[(c^b)&255]^(c>>>8);return (c^0xffffffff)>>>0;}
  function u16(v){return [v&255,(v>>>8)&255];}function u32(v){return [v&255,(v>>>8)&255,(v>>>16)&255,(v>>>24)&255];}
  function concat(parts){const arrays=parts.map(bytes),n=arrays.reduce((s,a)=>s+a.length,0),out=new Uint8Array(n);let p=0;for(const a of arrays){out.set(a,p);p+=a.length;}return out;}
  function makeStoredZip(fileMap){
    const locals=[],centrals=[];let offset=0,count=0;
    for(const [name0,data0] of Object.entries(fileMap).sort(([a],[b])=>a.localeCompare(b))){
      const name=encoder.encode(name0),data=bytes(data0),crc=crc32(data),local=concat([u32(0x04034b50),u16(20),u16(0),u16(0),u16(0),u16(0),u32(crc),u32(data.length),u32(data.length),u16(name.length),u16(0),name,data]);
      const central=concat([u32(0x02014b50),u16(20),u16(20),u16(0),u16(0),u16(0),u16(0),u32(crc),u32(data.length),u32(data.length),u16(name.length),u16(0),u16(0),u16(0),u16(0),u32(0),u32(offset),name]);locals.push(local);centrals.push(central);offset+=local.length;count++;
    }
    const central=concat(centrals),eocd=concat([u32(0x06054b50),u16(0),u16(0),u16(count),u16(count),u32(central.length),u32(offset),u16(0)]);return concat([...locals,central,eocd]);
  }
  async function inflateRaw(data){if(typeof DecompressionStream==="undefined")throw new Error("Ce navigateur ne sait pas décompresser ce ZIP.");const ds=new DecompressionStream("deflate-raw"),stream=new Blob([data]).stream().pipeThrough(ds);return new Uint8Array(await new Response(stream).arrayBuffer());}
  function read16(v,p){return v.getUint16(p,true);}function read32(v,p){return v.getUint32(p,true);}
  async function readZip(value){
    const data=bytes(value),view=new DataView(data.buffer,data.byteOffset,data.byteLength),out={};let p=0;
    while(p+4<=data.length&&read32(view,p)===0x04034b50){
      if(p+30>data.length)throw new Error("ZIP tronqué.");const flags=read16(view,p+6),method=read16(view,p+8),compressed=read32(view,p+18),uncompressed=read32(view,p+22),nameLen=read16(view,p+26),extraLen=read16(view,p+28);if(flags&8)throw new Error("ZIP avec data descriptor non supporté.");
      const name=decoder.decode(data.slice(p+30,p+30+nameLen)),start=p+30+nameLen+extraLen,end=start+compressed;if(end>data.length)throw new Error("ZIP tronqué.");let payload=data.slice(start,end);if(method===8)payload=await inflateRaw(payload);else if(method!==0)throw new Error(`Compression ZIP ${method} non supportée.`);if(payload.length!==uncompressed)throw new Error(`ZIP ${name}: taille décompressée invalide.`);out[name]=payload;p=end;
    }
    if(!Object.keys(out).length)throw new Error("ZIP sans fichiers lisibles.");return out;
  }
  function exportManifest(record){return {schema:EXPORT_SCHEMA,entry:record.entry,files:Object.fromEntries(Object.entries(record.files).map(([k,f])=>[k,{archive_path:`assets/${k}.json`,sha256:f.sha256,size_bytes:f.size_bytes}]))};}
  async function exportZip(id){
    const record=await idbGet(PACK_STORE,id);if(!record)throw new Error("Pack non installé.");const manifest=exportManifest(record),files={"PACK_RUNTIME.json":encoder.encode(JSON.stringify(manifest,null,2)+"\n")};for(const [k,f] of Object.entries(record.files))files[`assets/${k}.json`]=bytes(f.bytes);return makeStoredZip(files);
  }
  async function importZip(value,{fetchImpl=fetch}={}){
    const z=await readZip(value),manifestBytes=z["PACK_RUNTIME.json"];if(!manifestBytes)throw new Error("PACK_RUNTIME.json absent du ZIP.");let manifest;try{manifest=JSON.parse(decoder.decode(manifestBytes));}catch(_){throw new Error("PACK_RUNTIME.json invalide.");}if(manifest.schema!==EXPORT_SCHEMA)throw new Error("Schéma ZIP runtime non supporté.");const entry=validateEntry(manifest.entry);await assertCompatibility(entry,fetchImpl);const files={};
    for(const asset of entry.assets){const desc=manifest.files?.[asset.key],payload=desc&&z[desc.archive_path];if(!desc||!payload)throw new Error(`${asset.key}: absent du ZIP.`);if(payload.length!==Number(desc.size_bytes)||payload.length!==Number(asset.size_bytes))throw new Error(`${asset.key}: taille ZIP invalide.`);const digest=await sha256(payload);if(digest!==desc.sha256||digest!==asset.sha256)throw new Error(`${asset.key}: hash ZIP invalide.`);validateJsonAsset(asset,payload,entry);files[asset.key]={key:asset.key,role:asset.role,url:asset.url,path:asUrlPath(asset.url),media_type:asset.media_type||"application/json",sha256:digest,size_bytes:payload.length,bytes:payload};}
    const record={id:storageId(entry),pack_id:entry.pack_id,pack_version:entry.pack_version,population_id:entry.population_id,runtime_revision:entry.runtime_revision,entry:structuredClone(entry),files,source:"offline_zip",installed_at:new Date().toISOString()};await putPack(record);return record;
  }
  async function registerServiceWorker(){if(!("serviceWorker" in navigator))throw new Error("Service Worker indisponible.");const reg=await navigator.serviceWorker.register("./population-pack-sw.js",{scope:"./"});await navigator.serviceWorker.ready;return reg;}
  function downloadBytes(value,name,type="application/zip"){const url=URL.createObjectURL(new Blob([bytes(value)],{type})),a=document.createElement("a");a.href=url;a.download=name;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);}

  global.PokerPopulationPacks={DB_NAME,DB_VERSION,PACK_STORE,META_STORE,ACTIVE_KEY,PREVIOUS_KEY,CATALOG_SCHEMA,RUNTIME_SCHEMA,EXPORT_SCHEMA,sha256,storageId,fetchCatalog,install,installed,active,previous,activate,rollback,exportZip,importZip,readZip,makeStoredZip,registerServiceWorker,downloadBytes,assertCompatibility};
})(window);

"use strict";
const DB_NAME="poker-population-packs-v1",DB_VERSION=1,PACK_STORE="packs",META_STORE="meta",ACTIVE_KEY="active";
function openDb(){return new Promise((resolve,reject)=>{const r=indexedDB.open(DB_NAME,DB_VERSION);r.onupgradeneeded=()=>{const db=r.result;if(!db.objectStoreNames.contains(PACK_STORE))db.createObjectStore(PACK_STORE,{keyPath:"id"});if(!db.objectStoreNames.contains(META_STORE))db.createObjectStore(META_STORE);};r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});}
async function get(store,key){const db=await openDb();try{return await new Promise((resolve,reject)=>{const tx=db.transaction(store,"readonly"),r=tx.objectStore(store).get(key);r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});}finally{db.close();}}
async function activeRecord(){const id=await get(META_STORE,ACTIVE_KEY);return id?get(PACK_STORE,id):null;}
self.addEventListener("install",()=>self.skipWaiting());
self.addEventListener("activate",event=>event.waitUntil(self.clients.claim()));
self.addEventListener("fetch",event=>{
  const request=event.request;if(request.method!=="GET")return;
  const url=new URL(request.url);if(url.origin!==self.location.origin)return;
  event.respondWith((async()=>{
    try{
      const pack=await activeRecord();
      if(pack?.files){
        for(const file of Object.values(pack.files)){
          if(file.path===url.pathname){
            const body=file.bytes instanceof Uint8Array?file.bytes:new Uint8Array(file.bytes);
            return new Response(body,{status:200,headers:{"Content-Type":file.media_type||"application/json; charset=utf-8","Cache-Control":"no-store","X-Poker-Pack":pack.id,"X-Poker-Population":pack.population_id}});
          }
        }
      }
    }catch(_){/* Fail open: reviewed static defaults remain available. */}
    return fetch(request);
  })());
});

"use strict";

(function(global){
  const encoder=new TextEncoder();

  function bytes(value){
    if(value instanceof Uint8Array)return value;
    if(value instanceof ArrayBuffer)return new Uint8Array(value);
    if(ArrayBuffer.isView(value))return new Uint8Array(value.buffer,value.byteOffset,value.byteLength);
    if(Array.isArray(value))return Uint8Array.from(value);
    if(typeof value==="string")return encoder.encode(value);
    throw new TypeError("unsupported byte source");
  }

  function hex(buffer){
    return [...new Uint8Array(buffer)].map(x=>x.toString(16).padStart(2,"0")).join("");
  }

  async function sha256(value){
    return hex(await crypto.subtle.digest("SHA-256",bytes(value)));
  }

  async function contentIdentity(value){
    const data=bytes(value);
    return {sha256:await sha256(data),size_bytes:data.byteLength};
  }

  function storageId(entry){
    return `${entry.population_id}::${entry.pack_id}::${entry.pack_version}::${entry.runtime_revision}`;
  }

  function packIdentity(record){
    if(!record){
      return {
        id:"embedded-fallback",
        source:"EMBEDDED_FALLBACK",
        pack_id:null,
        pack_version:null,
        population_id:null,
        runtime_revision:null,
        engine_version:null
      };
    }
    return {
      id:record.id,
      source:"ACTIVE_PACK",
      pack_id:record.pack_id||record.entry?.pack_id||null,
      pack_version:record.pack_version||record.entry?.pack_version||null,
      population_id:record.population_id||record.entry?.population_id||null,
      runtime_revision:record.runtime_revision||record.entry?.runtime_revision||null,
      engine_version:record.entry?.compatibility?.engine_version||record.entry?.engine_version||null
    };
  }

  function samePackIdentity(a,b){
    return !!a&&!!b&&String(a.id||"")===String(b.id||"")&&String(a.population_id||"")===String(b.population_id||"");
  }

  global.PokerPackIdentity=Object.freeze({
    bytes,
    hex,
    sha256,
    contentIdentity,
    storageId,
    packIdentity,
    samePackIdentity
  });
})(window);

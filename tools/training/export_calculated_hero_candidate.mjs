#!/usr/bin/env node
import fs from 'node:fs';
import process from 'node:process';
import {createRequire} from 'node:module';

const require=createRequire(import.meta.url);
const X=require('../../src/preflop/hero_range_export.js');

function parseArgs(argv){
  const out={};
  for(let i=2;i<argv.length;i++){
    const arg=argv[i];
    if(arg==='--input'||arg==='--output'){
      if(i+1>=argv.length)throw new Error(`${arg} requires a value`);
      out[arg.slice(2)]=argv[++i];
    }else{
      throw new Error(`unknown argument ${arg}`);
    }
  }
  if(!out.input||!out.output)throw new Error('--input and --output are required');
  return out;
}

function main(){
  const args=parseArgs(process.argv);
  const run=JSON.parse(fs.readFileSync(args.input,'utf8'));
  if(run.schema!=='poker-hero-range-decision-run/v1')throw new Error(`unsupported input schema ${run.schema}`);
  if(run.promotion_authorized!==false)throw new Error('decision run must explicitly forbid self-promotion');
  if(!Array.isArray(run.rows)||!run.rows.length)throw new Error('decision run contains no completed rows');
  const requireComplete=Boolean(run.coverage?.complete_169);
  const candidate=X.buildCandidate({
    context:run.context,
    version:run.version,
    status:'EXPERIMENTAL',
    rows:run.rows.map(({hand_class,decision})=>({hand_class,decision})),
    provenance:run.provenance,
    require_complete:requireComplete
  });
  X.verifyCandidate(candidate,{require_complete:requireComplete});
  const payload={
    ...candidate,
    source_decision_run:{
      schema:run.schema,
      context_id:run.context_id,
      coverage:run.coverage,
      unsupported:run.unsupported||[]
    }
  };
  fs.writeFileSync(args.output,JSON.stringify(payload,null,2)+'\n');
  console.log(JSON.stringify({
    schema:payload.schema,
    version:payload.version,
    coverage:payload.coverage,
    promotion_authorized:payload.promotion_authorized
  },null,2));
}

try{main();}catch(error){
  console.error(error?.stack||String(error));
  process.exitCode=1;
}

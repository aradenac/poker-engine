#!/usr/bin/env node
'use strict';
const fs=require('fs');
const path=require('path');
const contract=require('../../site/preflop-contract.js');
const fixturePath=path.join(__dirname,'..','fixtures','preflop_contract_cases.json');
const fixture=JSON.parse(fs.readFileSync(fixturePath,'utf8'));
const out={};
for(const row of fixture.cases){
  const ctx=contract.buildContext(row.input);
  out[row.name]=ctx;
}
process.stdout.write(JSON.stringify(out));

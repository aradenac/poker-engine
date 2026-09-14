#!/usr/bin/env python3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
js=ROOT/'site/trainer.js'
text=js.read_text(encoding='utf-8')
old='''const TRAINER_ASSETS={
  modelA:{
    preflop:"./assets/trainer/model_a/preflop_population_model_v5.json",
    postflop:"./assets/trainer/model_a/postflop_population_model_v5.json"
  },
  modelB:{
    profiles:"./assets/trainer/model_b/profiles.json",
    ranges:"./assets/trainer/model_b/preflop_ranges.json",
    actions:"./assets/trainer/model_b/postflop_actions.json",
    sizing:"./assets/trainer/model_b/sizing.json",
    contract:"./assets/trainer/model_b/prediction_contract.json"
  },
  hero:{ranges:"./assets/trainer/hero/custom_ranges_v1.json"}
};
'''
new='''const TRAINER_POPULATION_MANIFEST="./assets/trainer/population.json";
'''
if text.count(old)!=1: raise SystemExit('trainer asset block mismatch')
text=text.replace(old,new,1)
old='''const trainerWarmAssets={started:false,promise:null,modelA:null,modelB:null,heroRanges:null,startedAt:0,finishedAt:0,error:null};'''
new='''const trainerWarmAssets={started:false,promise:null,population:null,modelA:null,modelB:null,heroRanges:null,startedAt:0,finishedAt:0,error:null};'''
if text.count(old)!=1: raise SystemExit('warm assets mismatch')
text=text.replace(old,new,1)
old='''  open:false,mode:"training",loading:false,ready:false,error:"",modelB:null,heroRanges:null,'''
new='''  open:false,mode:"training",loading:false,ready:false,error:"",populationId:null,modelB:null,heroRanges:null,'''
if text.count(old)!=1: raise SystemExit('state mismatch')
text=text.replace(old,new,1)
old='''    try{
      const [profiles,ranges,actions,sizing,contract,preflop,postflop,heroRanges]=await Promise.all([
        trainerFetchJson(TRAINER_ASSETS.modelB.profiles),trainerFetchJson(TRAINER_ASSETS.modelB.ranges),
        trainerFetchJson(TRAINER_ASSETS.modelB.actions),trainerFetchJson(TRAINER_ASSETS.modelB.sizing),
        trainerFetchJson(TRAINER_ASSETS.modelB.contract),trainerFetchText(TRAINER_ASSETS.modelA.preflop),
        trainerFetchText(TRAINER_ASSETS.modelA.postflop),trainerFetchJson(TRAINER_ASSETS.hero.ranges)
      ]);
      trainerWarmAssets.modelB={profiles,ranges,actions,sizing,contract};
      trainerWarmAssets.modelA={preflop,postflop};trainerWarmAssets.heroRanges=heroRanges;
      trainerWarmAssets.finishedAt=performance.now();
      trainerState.perf.warmupMs=trainerWarmAssets.finishedAt-trainerWarmAssets.startedAt;
      return {modelA:trainerWarmAssets.modelA,modelB:trainerWarmAssets.modelB,heroRanges:trainerWarmAssets.heroRanges};
'''
new='''    try{
      const population=await trainerFetchJson(TRAINER_POPULATION_MANIFEST);
      if(population?.schema!=="trainer-population-pack/v1"||!population?.population_id||!population?.assets)throw new Error("Pack trainer : manifeste de population invalide.");
      const asset=population.assets;
      const [profiles,ranges,actions,sizing,contract,preflop,postflop,heroRanges]=await Promise.all([
        trainerFetchJson(asset.modelB.profiles),trainerFetchJson(asset.modelB.ranges),
        trainerFetchJson(asset.modelB.actions),trainerFetchJson(asset.modelB.sizing),
        trainerFetchJson(asset.modelB.contract),trainerFetchText(asset.modelA.preflop),
        trainerFetchText(asset.modelA.postflop),trainerFetchJson(asset.hero.ranges)
      ]);
      trainerWarmAssets.population=population;trainerWarmAssets.modelB={profiles,ranges,actions,sizing,contract};
      trainerWarmAssets.modelA={preflop,postflop};trainerWarmAssets.heroRanges=heroRanges;
      trainerWarmAssets.finishedAt=performance.now();
      trainerState.perf.warmupMs=trainerWarmAssets.finishedAt-trainerWarmAssets.startedAt;
      return {population,modelA:trainerWarmAssets.modelA,modelB:trainerWarmAssets.modelB,heroRanges:trainerWarmAssets.heroRanges};
'''
if text.count(old)!=1: raise SystemExit('loader mismatch')
text=text.replace(old,new,1)
old='''    const {profiles,ranges,actions,sizing,contract}=assets.modelB;
    if(profiles.schema!=="independent-opponent-profiles/v2"||ranges.schema!=="independent-preflop-ranges/v2"||actions.schema!=="independent-postflop-actions/v2"||sizing.schema!=="independent-postflop-sizing/v2")throw new Error("Model B : schéma inattendu.");
'''
new='''    const {profiles,ranges,actions,sizing,contract}=assets.modelB;
    if(!assets.population?.population_id)throw new Error("Pack trainer : population absente.");
    if(profiles.schema!=="independent-opponent-profiles/v2"||ranges.schema!=="independent-preflop-ranges/v2"||actions.schema!=="independent-postflop-actions/v2"||sizing.schema!=="independent-postflop-sizing/v2")throw new Error("Model B : schéma inattendu.");
'''
if text.count(old)!=1: raise SystemExit('ensure models mismatch')
text=text.replace(old,new,1)
old='''    trainerState.modelB=assets.modelB;trainerState.heroRanges=assets.heroRanges;'''
new='''    trainerState.populationId=assets.population.population_id;trainerState.modelB=assets.modelB;trainerState.heroRanges=assets.heroRanges;'''
if text.count(old)!=1: raise SystemExit('state assignment mismatch')
text=text.replace(old,new,1)
old='''    trainerRenderStatus(`Trainer prêt · Model A v5 + Model B v2 + ranges Hero Custom · init ${trainerState.perf.modelLoadMs.toFixed(0)} ms${trainerState.perf.warmHit?" · assets préchargés":""}.`);'''
new='''    trainerRenderStatus(`Trainer prêt · ${trainerState.populationId} · Model A v5 + Model B v2 + ranges Hero Custom · init ${trainerState.perf.modelLoadMs.toFixed(0)} ms${trainerState.perf.warmHit?" · assets préchargés":""}.`);'''
if text.count(old)!=1: raise SystemExit('status mismatch')
text=text.replace(old,new,1)
js.write_text(text,encoding='utf-8')

p=ROOT/'tests/trainer/test_trainer_static.py'
t=p.read_text(encoding='utf-8')
old='''    expected_assets = [
        "assets/trainer/model_a/preflop_population_model_v5.json",
        "assets/trainer/model_a/postflop_population_model_v5.json",
        "assets/trainer/model_b/profiles.json",
        "assets/trainer/model_b/preflop_ranges.json",
        "assets/trainer/model_b/postflop_actions.json",
        "assets/trainer/model_b/sizing.json",
        "assets/trainer/model_b/prediction_contract.json",
    ]
    for rel in expected_assets:
        assert (SITE / rel).is_file(), f"missing trainer asset: {rel}"
'''
new='''    require(js, 'TRAINER_POPULATION_MANIFEST="./assets/trainer/population.json"', "population pack selector")
    assert "TRAINER_ASSETS=" not in js, "trainer model paths must come from the population pack"
    manifest = json.loads((SITE / "assets/trainer/population.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == "trainer-population-pack/v1"
    assert manifest["population_id"] == "legacy_pokerstars_nlhe_100-200_play_6max_mixed_v1"
    assert manifest["population_identity"]["format"] == "MIXED_ZOOM_REGULAR"
    expected_assets = [
        manifest["assets"]["modelA"]["preflop"],
        manifest["assets"]["modelA"]["postflop"],
        manifest["assets"]["modelB"]["profiles"],
        manifest["assets"]["modelB"]["ranges"],
        manifest["assets"]["modelB"]["actions"],
        manifest["assets"]["modelB"]["sizing"],
        manifest["assets"]["modelB"]["contract"],
        manifest["assets"]["hero"]["ranges"],
    ]
    for rel in expected_assets:
        assert (SITE / rel.removeprefix("./")).is_file(), f"missing trainer asset: {rel}"
'''
if t.count(old)!=1: raise SystemExit('static test asset block mismatch')
t=t.replace(old,new,1)
p.write_text(t,encoding='utf-8')
print('trainer population pack patch applied')

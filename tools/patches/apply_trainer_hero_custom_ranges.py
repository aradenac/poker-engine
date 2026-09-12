#!/usr/bin/env python3
"""Use the user's persisted custom preflop ranges for Hero trainer deals."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRAINER = ROOT / "site/trainer.js"
SMOKE = ROOT / "tests/trainer/smoke_trainer.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one marker, found {count}")
    return text.replace(old, new, 1)


def patch_trainer() -> None:
    text = TRAINER.read_text(encoding="utf-8")

    text = replace_once(
        text,
        '''    contract:"./assets/trainer/model_b/prediction_contract.json"\n  }\n};\n''',
        '''    contract:"./assets/trainer/model_b/prediction_contract.json"\n  },\n  hero:{ranges:"./assets/trainer/hero/custom_ranges_v1.json"}\n};\n''',
        "hero range asset path",
    )
    text = replace_once(
        text,
        'const trainerWarmAssets={started:false,promise:null,modelA:null,modelB:null,startedAt:0,finishedAt:0,error:null};\n',
        'const trainerWarmAssets={started:false,promise:null,modelA:null,modelB:null,heroRanges:null,startedAt:0,finishedAt:0,error:null};\n',
        "warm hero range slot",
    )
    text = replace_once(
        text,
        '  open:false,mode:"training",loading:false,ready:false,error:"",modelB:null,\n',
        '  open:false,mode:"training",loading:false,ready:false,error:"",modelB:null,heroRanges:null,\n',
        "trainer hero range state",
    )
    text = replace_once(
        text,
        '''      const [profiles,ranges,actions,sizing,contract,preflop,postflop]=await Promise.all([\n        trainerFetchJson(TRAINER_ASSETS.modelB.profiles),trainerFetchJson(TRAINER_ASSETS.modelB.ranges),\n        trainerFetchJson(TRAINER_ASSETS.modelB.actions),trainerFetchJson(TRAINER_ASSETS.modelB.sizing),\n        trainerFetchJson(TRAINER_ASSETS.modelB.contract),trainerFetchText(TRAINER_ASSETS.modelA.preflop),\n        trainerFetchText(TRAINER_ASSETS.modelA.postflop)\n      ]);\n      trainerWarmAssets.modelB={profiles,ranges,actions,sizing,contract};\n      trainerWarmAssets.modelA={preflop,postflop};\n''',
        '''      const [profiles,ranges,actions,sizing,contract,preflop,postflop,heroRanges]=await Promise.all([\n        trainerFetchJson(TRAINER_ASSETS.modelB.profiles),trainerFetchJson(TRAINER_ASSETS.modelB.ranges),\n        trainerFetchJson(TRAINER_ASSETS.modelB.actions),trainerFetchJson(TRAINER_ASSETS.modelB.sizing),\n        trainerFetchJson(TRAINER_ASSETS.modelB.contract),trainerFetchText(TRAINER_ASSETS.modelA.preflop),\n        trainerFetchText(TRAINER_ASSETS.modelA.postflop),trainerFetchJson(TRAINER_ASSETS.hero.ranges)\n      ]);\n      trainerWarmAssets.modelB={profiles,ranges,actions,sizing,contract};\n      trainerWarmAssets.modelA={preflop,postflop};trainerWarmAssets.heroRanges=heroRanges;\n''',
        "load hero ranges during warmup",
    )
    text = replace_once(
        text,
        '      return {modelA:trainerWarmAssets.modelA,modelB:trainerWarmAssets.modelB};\n',
        '      return {modelA:trainerWarmAssets.modelA,modelB:trainerWarmAssets.modelB,heroRanges:trainerWarmAssets.heroRanges};\n',
        "return warm hero ranges",
    )
    text = replace_once(
        text,
        '    const alreadyWarm=!!(trainerWarmAssets.modelA&&trainerWarmAssets.modelB),assets=await trainerLoadWarmAssets();\n',
        '    const alreadyWarm=!!(trainerWarmAssets.modelA&&trainerWarmAssets.modelB&&trainerWarmAssets.heroRanges),assets=await trainerLoadWarmAssets();\n',
        "hero ranges warm-hit accounting",
    )
    text = replace_once(
        text,
        '''    if(profiles.schema!=="independent-opponent-profiles/v2"||ranges.schema!=="independent-preflop-ranges/v2"||actions.schema!=="independent-postflop-actions/v2"||sizing.schema!=="independent-postflop-sizing/v2")throw new Error("Model B : schéma inattendu.");\n    trainerState.modelB=assets.modelB;\n''',
        '''    if(profiles.schema!=="independent-opponent-profiles/v2"||ranges.schema!=="independent-preflop-ranges/v2"||actions.schema!=="independent-postflop-actions/v2"||sizing.schema!=="independent-postflop-sizing/v2")throw new Error("Model B : schéma inattendu.");\n    if(assets.heroRanges?.schema!=="trainer-hero-preflop-ranges/v1")throw new Error("Ranges Hero : schéma inattendu.");\n    trainerState.modelB=assets.modelB;trainerState.heroRanges=assets.heroRanges;\n''',
        "validate hero ranges",
    )
    text = replace_once(
        text,
        '    trainerRenderStatus(`Trainer prêt · Model A v5 + Model B v2 · init ${trainerState.perf.modelLoadMs.toFixed(0)} ms${trainerState.perf.warmHit?" · assets préchargés":""}.`);\n',
        '    trainerRenderStatus(`Trainer prêt · Model A v5 + Model B v2 + ranges Hero Custom · init ${trainerState.perf.modelLoadMs.toFixed(0)} ms${trainerState.perf.warmHit?" · assets préchargés":""}.`);\n',
        "hero range readiness status",
    )

    marker = '''function trainerSampleRangeCards(profile,position,potType,role,blocked){\n  const probs=trainerClassProbabilities(profile,position,potType,role),mult=trainerState.modelB.ranges.multiplicity||{};\n  const combos=[],weights=[];\n  for(let a=0;a<52;a++)for(let b=a+1;b<52;b++){\n    if(blocked.has(a)||blocked.has(b))continue;\n    const cls=cardsToNotation([a,b]);combos.push([a,b]);weights.push((Number(probs[cls])||0)/Math.max(1,Number(mult[cls])||1));\n  }\n  const c=trainerWeightedChoice(combos,weights);return c||combos[trainerRandomInt(combos.length)];\n}\n'''
    addition = marker + '''function trainerHeroRangeMap(role,position){return trainerState.heroRanges?.ranges?.[String(role||"").toUpperCase()]?.[String(position||"").toUpperCase()]||null;}\nfunction trainerHeroRangeAvailable(role,position){const range=trainerHeroRangeMap(role,position);return !!range&&Object.values(range).some(x=>Number(x)>0);}\nfunction trainerSampleHeroRangeCards(role,position,blocked=new Set()){\n  const range=trainerHeroRangeMap(role,position);if(!range)return null;\n  const combos=[],weights=[];\n  for(let a=0;a<52;a++)for(let b=a+1;b<52;b++){\n    if(blocked.has(a)||blocked.has(b))continue;\n    const cls=cardsToNotation([a,b]),weight=Number(range[cls])||0;if(!(weight>0))continue;\n    combos.push([a,b]);weights.push(weight);\n  }\n  return combos.length?trainerWeightedChoice(combos,weights):null;\n}\n'''
    text = replace_once(text, marker, addition, "hero range sampler")

    text = replace_once(
        text,
        '''function trainerBuildHand(){\n  trainerState.handNo++;\n  const dealer=trainerRandomInt(6),heroSeat=trainerRandomInt(6),positions=Array.from({length:6},(_,s)=>trainerPositionForSeat(s,dealer));\n''',
        '''function trainerBuildHand(){\n  const dealer=trainerRandomInt(6),heroSeat=trainerRandomInt(6),positions=Array.from({length:6},(_,s)=>trainerPositionForSeat(s,dealer));\n''',
        "delay hand number until supported range",
    )
    text = replace_once(
        text,
        '''  if(!candidates.length){heroRole=heroRole==="PFA"?"CALLER":"PFA";return trainerBuildHand();}\n  const oppSeat=candidates[trainerRandomInt(candidates.length)].s,oppPos=positions[oppSeat],pfaSeat=heroRole==="PFA"?heroSeat:oppSeat,callerSeat=heroRole==="CALLER"?heroSeat:oppSeat;\n''',
        '''  if(!candidates.length||!trainerHeroRangeAvailable(heroRole,heroPos))return trainerBuildHand();\n  trainerState.handNo++;\n  const oppSeat=candidates[trainerRandomInt(candidates.length)].s,oppPos=positions[oppSeat],pfaSeat=heroRole==="PFA"?heroSeat:oppSeat,callerSeat=heroRole==="CALLER"?heroSeat:oppSeat;\n''',
        "reject unsupported Hero role-position",
    )
    text = replace_once(
        text,
        '''  const deck=trainerShuffle(Array.from({length:52},(_,i)=>i)),hole=Array.from({length:6},()=>[]),blocked=new Set();\n  hole[heroSeat]=[trainerDraw(deck),trainerDraw(deck)];hole[heroSeat].forEach(c=>blocked.add(c));\n''',
        '''  const hole=Array.from({length:6},()=>[]),blocked=new Set(),heroCards=trainerSampleHeroRangeCards(heroRole,heroPos,blocked);\n  if(!heroCards)return trainerBuildHand();hole[heroSeat]=heroCards;hole[heroSeat].forEach(c=>blocked.add(c));\n''',
        "sample Hero from custom range",
    )
    text = replace_once(
        text,
        '${escapeHtml(h.street.toUpperCase())} · SRP · ${escapeHtml(h.heroRole==="PFA"?"Hero PFA":"Hero caller")}',
        '${escapeHtml(h.street.toUpperCase())} · SRP · ${escapeHtml(h.heroRole==="PFA"?"Hero PFA":"Hero caller")} · range Custom',
        "show Hero range provenance",
    )

    TRAINER.write_text(text, encoding="utf-8")


def patch_smoke() -> None:
    text = SMOKE.read_text(encoding="utf-8")
    marker = '''        assert await page.locator("#trainerTable .seat.hero").count() == 1\n\n'''
    addition = marker + '''        # Hero must be dealt from the persisted Custom range for this exact role/position.\n        hero_range = await page.evaluate(\n            "() => { const h=trainerState.hand, p=h.positions[h.heroSeat], n=cardsToNotation(h.hole[h.heroSeat]); return {role:h.heroRole, position:p, notation:n, frequency:Number(trainerState.heroRanges?.ranges?.[h.heroRole]?.[p]?.[n]||0)}; }"\n        )\n        assert hero_range["frequency"] > 0, hero_range\n        assert not (hero_range["role"] == "CALLER" and hero_range["position"] == "BB"), hero_range\n\n'''
    text = replace_once(text, marker, addition, "browser Hero range assertion")
    text = replace_once(
        text,
        '''            "seats": seats,\n            "guided": guided,\n''',
        '''            "seats": seats,\n            "hero_range": hero_range,\n            "guided": guided,\n''',
        "browser Hero range diagnostics",
    )
    SMOKE.write_text(text, encoding="utf-8")


def main() -> None:
    patch_trainer();patch_smoke();print("trainer custom Hero ranges patch applied")


if __name__ == "__main__":
    main()

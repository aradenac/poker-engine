from __future__ import annotations

import json


async def run_manual_import_smoke(page):
    await page.goto("http://127.0.0.1:8765/manual-import.html", wait_until="domcontentloaded", timeout=45_000)
    await page.wait_for_function(
        "window.PokerManualOverrides && window.PokerPopulationPacks",
        timeout=45_000,
    )

    result = await page.evaluate(
        r"""async () => {
          const P=window.PokerPopulationPacks;
          const M=window.PokerManualOverrides;
          const before=await P.active();
          const previous=await P.previous();
          if(!before)throw new Error('manual smoke requires an active production pack');
          if(!previous)throw new Error('manual smoke requires a previous production pack');

          const makeFile=(name,value,raw=false)=>new File(
            [raw?String(value):JSON.stringify(value)],
            name,
            {type:'application/json',lastModified:1700000000000}
          );
          const pop=before.population_id||before.entry?.population_id;
          const hero={
            name:'Root',
            ranges:[{
              name:'Hero',
              positions:[{
                position:'BTN',
                hands:[{hand:'AA',actions:[{name:'RAISE',frequency:100}]}]
              }]
            }]
          };
          const pre={
            model_type:'preflop_population',
            population_id:pop,
            hand_grid:{classes:['AA'],meta:{}},
            nodes:[{
              context:{actor_position:'BTN'},
              population_model:{frequencies:{FOLD:0.2,CALL:0.3,RAISE:0.5}}
            }]
          };
          const post={
            model_type:'postflop_population',
            population_id:pop,
            nodes:[{context:{street:'flop',mode:'BET'}}],
            response_models:{fold:{kind:'synthetic'}}
          };

          const initial=await M.inspect();
          if(initial.active)await M.restoreActivePack();

          const expectRejected=async(fn,label)=>{
            let rejected=false;
            try{await fn();}catch(_){rejected=true;}
            if(!rejected)throw new Error(label+' was accepted');
            return true;
          };

          const wrongRole=await expectRejected(
            ()=>M.activateFiles([{role:'model_a_preflop',file:makeFile('post-as-pre.json',post)}]),
            'wrong role'
          );
          const badSchema=await expectRejected(
            ()=>M.activateFiles([{role:'model_a_preflop',file:makeFile('bad-schema.json',{schema:'unknown/v99'})}]),
            'bad schema'
          );
          const wrongPopulation=await expectRejected(
            ()=>M.activateFiles([{role:'model_a_preflop',file:makeFile('wrong-pop.json',{...pre,population_id:'another_population'})}]),
            'wrong population'
          );
          const corrupt=await expectRejected(
            ()=>M.activateFiles([{role:'hero_ranges',file:makeFile('corrupt.json','{broken',true)}]),
            'corrupt JSON'
          );
          if((await M.inspect()).active)throw new Error('failed imports created partial override');

          const active=await M.activateFiles([
            {role:'hero_ranges',file:makeFile('hero-ranges.json',hero)},
            {role:'model_a_preflop',file:makeFile('model-a-pre.json',pre)},
            {role:'model_a_postflop',file:makeFile('model-a-post.json',post)}
          ]);
          if(!active.active)throw new Error('valid override not active');
          if(active.classification!=='MANUAL_OVERRIDE'||active.configuration_status!=='NON_STANDARD')throw new Error('override classification missing');
          if(active.compatibility_status!=='COMPATIBLE')throw new Error('valid override compatibility not accepted');
          if(active.roles_overridden.join(',')!=='hero_ranges,model_a_postflop,model_a_preflop')throw new Error('multi-role override incomplete');
          if(active.sources.some(s=>!s.filename||!/^[0-9a-f]{64}$/.test(s.sha256)))throw new Error('source traceability incomplete');
          if(active.base_active_pack.id!==before.id)throw new Error('base pack identity not bound');

          await M.render();
          const badge=document.querySelector('#overrideBadge')?.textContent||'';
          if(!badge.includes('Override manuel'))throw new Error('NON_STANDARD badge not rendered');

          const afterActivation=await P.active();
          if(afterActivation.id!==before.id)throw new Error('manual activation mutated active pack identity');
          if(M.DB_NAME===P.DB_NAME)throw new Error('manual override storage collides with pack cache');

          const sessionId=active.session.id;
          const incoherent=await expectRejected(
            ()=>M.activateFiles([
              {role:'model_a_preflop',file:makeFile('pre-ok.json',pre)},
              {role:'model_a_postflop',file:makeFile('post-other.json',{...post,population_id:'another_population'})}
            ]),
            'incoherent population mix'
          );
          if((await M.inspect()).session.id!==sessionId)throw new Error('incoherent mix mutated previous configuration');

          const atomicFailure=await expectRejected(
            ()=>M.activateFiles([
              {role:'hero_ranges',file:makeFile('hero-ok.json',hero)},
              {role:'model_a_preflop',file:makeFile('pre-corrupt.json','{bad',true)}
            ]),
            'atomic mixed failure'
          );
          if((await M.inspect()).session.id!==sessionId)throw new Error('failed batch partially committed');

          const packChangeBlocked=await expectRejected(
            ()=>P.rollback(),
            'pack rollback while manual override active'
          );
          if((await P.active()).id!==before.id)throw new Error('blocked pack rollback mutated active identity');

          const restored=await M.restoreActivePack();
          if(restored.active)throw new Error('RESTORE_ACTIVE_PACK left override active');
          if(restored.compatibility_status!=='RESTORED_ACTIVE_PACK')throw new Error('restore compatibility status missing');
          if(await M._test.getKey('rangeSource'))throw new Error('Hero manual source remained without pack permission');
          if(await M._test.getKey('populationModelSource'))throw new Error('preflop source remained after restore');
          if(await M._test.getKey('postflopModelSource'))throw new Error('postflop source remained after restore');

          const rolled=await P.rollback();
          if(rolled.id!==previous.id)throw new Error('pack rollback did not succeed after restore');
          const returned=await P.rollback();
          if(returned.id!==before.id)throw new Error('pack identity was not restorable after manual flow');

          return {
            wrong_role_rejected:wrongRole,
            bad_schema_rejected:badSchema,
            wrong_population_rejected:wrongPopulation,
            corrupt_rejected:corrupt,
            incoherent_mix_rejected:incoherent,
            atomic_failure_rejected:atomicFailure,
            pack_change_blocked:packChangeBlocked,
            roles:active.roles_overridden,
            classification:active.classification,
            configuration_status:active.configuration_status,
            base_pack_id:active.base_active_pack.id,
            active_pack_unchanged:afterActivation.id===before.id,
            restored:restored.compatibility_status,
            final_pack_id:(await P.active()).id,
            storage_isolated:M.DB_NAME!==P.DB_NAME,
            badge
          };
        }"""
    )
    assert result["wrong_role_rejected"] is True, result
    assert result["bad_schema_rejected"] is True, result
    assert result["wrong_population_rejected"] is True, result
    assert result["corrupt_rejected"] is True, result
    assert result["incoherent_mix_rejected"] is True, result
    assert result["atomic_failure_rejected"] is True, result
    assert result["pack_change_blocked"] is True, result
    assert result["active_pack_unchanged"] is True, result
    assert result["storage_isolated"] is True, result
    assert result["classification"] == "MANUAL_OVERRIDE", result
    assert result["configuration_status"] == "NON_STANDARD", result
    assert result["restored"] == "RESTORED_ACTIVE_PACK", result
    return result


if __name__ == "__main__":
    print(json.dumps({"note": "import and call run_manual_import_smoke(page) from the pack browser smoke"}))

#!/usr/bin/env python3
import json, hashlib, collections, math, os
from pathlib import Path

SRC=Path('/mnt/data/poker_population_increment_decisions_v2.jsonl')
OUT=Path('/mnt/data/poker_population_increment_overlay_v2.json')

ACTIONS_PRE=['FOLD','CHECK','LIMP','CALL','RAISE','JAM']
ACTIONS_POST=['FOLD','CHECK','CALL','BET','RAISE','JAM']


def pre_v4_key(r):
    hist='>'.join(f"{x['position']}:{x['action']}" for x in (r.get('history') or []))
    free = 1 if r.get('free_check') else 0
    return f"{r['table_size']}|{r['actor_position']}|family={r['family']}|rl={r['raise_level']}|free={free}|live={','.join(r.get('live_positions') or [])}|allin={','.join(r.get('all_in_positions') or [])}|hist={hist}"

def pre_v4_id(key):
    return 'PF4_'+hashlib.sha1(key.encode()).hexdigest()[:12]

def node_context_pre(r):
    return {
      'table_size':r['table_size'],'actor_position':r['actor_position'],'family':r['family'],
      'raise_level':r['raise_level'],'live_positions':r.get('live_positions') or [],
      'all_in_positions':r.get('all_in_positions') or [],'history':r.get('history') or [],
      'free_check':bool(r.get('free_check'))
    }

def add_num(acc,k,v):
    if v is None or not isinstance(v,(int,float)) or not math.isfinite(v): return
    s=acc.setdefault(k,{'n':0,'sum':0.0,'sum_sq':0.0,'min':v,'max':v})
    s['n']+=1;s['sum']+=v;s['sum_sq']+=v*v;s['min']=min(s['min'],v);s['max']=max(s['max'],v)

def finalize_num(d):
    for v in d.values():
        n=v['n']; v['mean']=v['sum']/n if n else None
        var=max(0.0,v['sum_sq']/n-v['mean']**2) if n else None
        v['std']=math.sqrt(var) if var is not None else None

pre=collections.OrderedDict(); post=collections.OrderedDict()
summary={'rows':0,'population_rows':0,'train_population_rows':0,'known_train_population_rows':0}
by_split=collections.Counter()

with SRC.open(encoding='utf-8') as f:
  for line in f:
    r=json.loads(line); summary['rows']+=1; by_split[r['split']]+=1
    if r.get('is_hero'): continue
    summary['population_rows']+=1
    if r['split']!='TRAIN': continue
    summary['train_population_rows']+=1
    if r.get('known_hand_class'): summary['known_train_population_rows']+=1
    if r['street']=='preflop':
      key=pre_v4_key(r); nid=pre_v4_id(key)
      n=pre.setdefault(key,{
        'id':nid,'canonical_key':key,'context':node_context_pre(r),'n_delta':0,
        'actions':collections.Counter(),'known_by_action':{},'continuous':{}
      })
      n['n_delta']+=1;n['actions'][r['action']]+=1
      hc=r.get('known_hand_class')
      if hc:
        n['known_by_action'].setdefault(r['action'],collections.Counter())[hc]+=1
      add_num(n['continuous'],'pot_before_bb',r.get('pot_before_bb'))
      add_num(n['continuous'],'to_call_bb',r.get('to_call_bb'))
      add_num(n['continuous'],'current_price_bb',r.get('current_price_bb'))
      add_num(n['continuous'],'action_add_bb',r.get('action_add_bb'))
      add_num(n['continuous'],'actor_start_stack_bb',r.get('actor_start_stack_bb'))
      add_num(n['continuous'],'actor_remaining_bb_before',r.get('actor_remaining_bb_before'))
    else:
      key=r['canonical_key']
      n=post.setdefault(key,{
        'id':'PFLOP_'+hashlib.sha1(key.encode()).hexdigest()[:12],
        'canonical_key':key,
        'context':{k:r.get(k) for k in ['street','street_start_players','active_players','relative_position','pot_type','preflop_role','street_history','mode']},
        'n_delta':0,'actions':collections.Counter(),'known_by_action':{},'continuous':{},
      })
      n['n_delta']+=1;n['actions'][r['action']]+=1
      hc=r.get('known_hand_class')
      if hc:
        n['known_by_action'].setdefault(r['action'],collections.Counter())[hc]+=1
      for k in ['pot_before_bb','spr','facing_price_pot','own_size_pot']:
        add_num(n['continuous'],k,r.get(k))

# JSON-ize counters and finalize sufficient statistics.
for coll in (pre,post):
  for n in coll.values():
    n['actions']=dict(n['actions'])
    n['known_by_action']={a:dict(c) for a,c in n['known_by_action'].items()}
    finalize_num(n['continuous'])

obj={
 'schema':'poker-population-increment-overlay/v1',
 'purpose':'Additive sufficient statistics for population-model calibration. Contains TRAIN only; VALIDATION/TEST remain in the decision JSONL for model selection/non-regression.',
 'base_contract':{
   'preflop_model':'preflop_population_model_v4.json',
   'postflop_model':'postflop_population_model_v5.json',
   'historical_corpus_fingerprint_sha256':'91a1b1c285add6ace2aedafa568bfc039c644b94216b9d2fdcd28cea59b73d4b',
   'split_namespace':'poker-population-split-v1'
 },
 'source':SRC.name,
 'summary':{**summary,'row_counts_by_split':dict(by_split),'preflop_nodes_train':len(pre),'postflop_nodes_train':len(post)},
 'preflop_nodes':list(pre.values()),'postflop_nodes':list(post.values()),
 'merge_rules':{
   'marginal_counts':'Add delta action counts to historical TRAIN sufficient statistics; never add VALIDATION or TEST counts.',
   'known_hand_composition':'Treat delta revealed-card counts as additional TRAIN evidence only for observable actions. Do not infer FOLD composition from missing showdown cards.',
   'continuous':'Sufficient moments are diagnostic only; raw TRAIN rows in the JSONL are retained for any future refit of continuous response models.',
   'validation':'Select any changed hyperparameter/scale only on VALIDATION. TEST remains metrics-only.'
 }
}
OUT.write_text(json.dumps(obj,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
print(json.dumps(obj['summary'],indent=2,ensure_ascii=False))
print('WROTE',OUT,OUT.stat().st_size)

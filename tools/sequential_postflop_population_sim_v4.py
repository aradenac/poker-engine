#!/usr/bin/env python3
import asyncio, json, pickle, re, hashlib, math, collections, itertools, argparse, sys, time
from pathlib import Path
import numpy as np, pandas as pd
from playwright.async_api import async_playwright
sys.path.insert(0,'/mnt/data')
import independent_decision_arena_seq_v2 as a

P=Path('/mnt/data/sequential_population_inputs_v2')
MODEL_P=Path('/mnt/data/independent_population_v1')
HANDS=pickle.load(open(P/'hands.pkl','rb'))
DF=pickle.load(open(P/'decisions_full.pkl','rb'))
PROF=pickle.load(open(MODEL_P/'player_profiles.pkl','rb'))
RANGES=json.loads((MODEL_P/'preflop_range_tables.json').read_text())
HTML='/mnt/data/poker_range_equity_offline_multiway_v76_seqmeta_benchmark.html'
PRE='/mnt/data/poker_population_release_20260909/preflop_population_model_v5.json'
POST='/mnt/data/poker_population_release_20260909/postflop_population_model_v5.json'
RANKS='23456789TJQKA';SUITS='shdc'
PROFILE_WEIGHTS=(PROF.groupby('profile').appearances.sum()/PROF.appearances.sum()).sort_index()
DEFAULT_PROFILE=int(PROF.groupby('profile').appearances.sum().idxmax())
PLAYER_PROFILE=PROF['profile'].to_dict()

# Empirical independent sizing distributions from TRAIN only.
SZ=DF[(DF.split=='TRAIN') & (~DF.is_hero) & DF.street.isin(['flop','turn','river']) & DF.action.isin(['BET','RAISE'])].copy()
SZ['profile']=SZ.player.map(PLAYER_PROFILE).fillna(DEFAULT_PROFILE).astype(int)
SZ['own_size_pot']=pd.to_numeric(SZ.own_size_pot,errors='coerce')
SZ=SZ[(SZ.own_size_pot>0)&np.isfinite(SZ.own_size_pot)]
SIZE_GROUP={}
for key,g in SZ.groupby(['profile','street','mode','action']):
    if len(g)>=12: SIZE_GROUP[key]=g.own_size_pot.to_numpy(float)
SIZE_FALLBACK={key:g.own_size_pot.to_numpy(float) for key,g in SZ.groupby(['street','mode','action'])}


def hseed(*parts):
    h=hashlib.sha256('|'.join(map(str,parts)).encode()).digest()
    return int.from_bytes(h[:8],'big')
def u01(*parts): return (hseed(*parts)%((1<<53)-1))/float((1<<53)-1)
def rng_for(*parts): return np.random.default_rng(hseed(*parts))

def preflop_prefix(raw):
    i=raw.find('*** FLOP ***')
    return raw[:i].rstrip() if i>=0 else raw.rstrip()

def active_at_flop(h):
    active=set(h['by'])
    allin=set()
    totals=collections.defaultdict(float)
    for e in h['events']:
        if e['street']!='preflop': break
        pl=e['player']; typ=e['type']; add=e.get('add',0)/200.0
        if typ=='fold': active.discard(pl)
        elif typ in ('post','call','bet','raise'): totals[pl]+=add
        elif typ=='return': totals[pl]=max(0,totals[pl]+add)
        if e.get('allin'): allin.add(pl)
    return active,allin,totals

def flop_board(h):
    m=re.search(r'\*\*\* FLOP \*\*\* \[([^]]+)\]',h['raw'])
    return m.group(1).split() if m else []

def profile_range(profile,pos,role,pot_type,hero,board):
    vals={'profile':int(profile),'position':pos,'pot_type':pot_type,'preflop_role':role};cnt=None
    for lev in RANGES['levels']:
        cols=lev['cols'];key='|'.join(str(vals[c]) for c in cols) if cols else 'ALL';z=lev['data'].get(key)
        if z and sum(z.values())>=20:cnt=z;break
    if cnt is None:cnt=RANGES['levels'][-1]['data']['ALL']
    pseudo=50.;mult=RANGES['multiplicity'];den=sum(cnt.values())+pseudo
    classp={n:(cnt.get(n,0)+pseudo*mult[n]/1326)/den for n in RANGES['notations']}
    combos=a.legal_combos(hero,board)
    w=np.array([classp.get(a.combo_class(x,y),1e-8)/max(1,mult.get(a.combo_class(x,y),1)) for x,y in combos],float);w/=w.sum()
    return combos,w

def filter_range(combos,w,blocked_id):
    mask=np.array([blocked_id not in c for c in combos])
    combos=[c for c,m in zip(combos,mask) if m];w=w[mask];w/=w.sum();return combos,w

def rel_position(actor,hero,opp,order): return 'OOP' if actor==order[0] else 'IP'

def model_row(street,actor,profile,h,board,pot,to_call,remaining,hist,order):
    row={'street':street,'profile':int(profile),'position':h['positions'].get(actor,'NA'),'relative_position':rel_position(actor,h['hero'],actor if actor!=h['hero'] else '',order),
         'preflop_role':h['roles'].get(actor,'OTHER'),'pot_type':h['pot_type'],'active_players':2,'street_start_players':2,'pot_before_bb':pot,'to_call_bb':to_call,
         'facing_price_pot':to_call/max(pot,1e-9),'spr':remaining/max(pot,1e-9),'hist_aggr':hist['aggr'],'hist_checks':hist['checks'],'hist_calls':hist['calls'],'own_size_pot':np.nan}
    # relative position is fixed by order, above helper actor only
    row['relative_position']='OOP' if actor==order[0] else 'IP'
    row.update(a.boardfeat(board));return row

def opponent_action_probs(street,row,combos,w,board,actual_combo,can_raise=True):
    target=a.predict_marg(street,row)
    if row['mode']=='FREE':
        rows=[]
        for x,y in combos:
            rr=dict(row);rr.update(a.hfeat([a.ccode(x),a.ccode(y)],board));rows.append(rr)
        X=a.prep_comp(rows);m=a.comp['models'][f'{street}_free_bet'];pb=m.predict_proba(X)[:,1]
        raw=np.column_stack([1-pb,pb]);t=np.array([target.get('CHECK',0),target.get('BET',0)],float);t=np.maximum(t,1e-8);t/=t.sum();M=a.ipf(raw,w,t);labels=['CHECK','BET']
    else:
        raw=a.combo_action_probs(street,row,combos,board);t=np.array([target.get('FOLD',0),target.get('CALL',0),target.get('RAISE',0)],float)
        if not can_raise:t[1]+=t[2];t[2]=0
        t=np.maximum(t,1e-8);t/=t.sum();M=a.ipf(raw,w,t);labels=['FOLD','CALL','RAISE']
        if not can_raise:
            M[:,1]+=M[:,2];M[:,2]=0;M/=M.sum(1,keepdims=True)
    try:i=combos.index(tuple(sorted(actual_combo)))
    except ValueError:return labels,np.array([1/len(labels)]*len(labels)),M
    return labels,M[i],M

def sample_label(labels,p,seedparts):
    p=np.maximum(np.asarray(p,float),0);p/=p.sum();u=u01(*seedparts);c=0
    for lab,q in zip(labels,p):
        c+=q
        if u<=c:return lab
    return labels[-1]

def sample_size(profile,street,mode,action,seedparts):
    arr=SIZE_GROUP.get((int(profile),street,mode,action))
    if arr is None or len(arr)<12:arr=SIZE_FALLBACK.get((street,mode,action),np.array([.5]))
    i=hseed(*seedparts)%len(arr);return float(arr[i])

def postflop_order(h,active):
    seats={v['seat']:p for p,v in h['by'].items()};maxseat=max(seats);button=None
    m=re.search(r"Seat #(\d+) is the button",h['raw']);button=int(m.group(1)) if m else 1
    seq=[]
    for k in range(1,maxseat+1):
        s=((button-1+k)%maxseat)+1
        if s in seats and seats[s] in active:seq.append(seats[s])
    return seq

def action_line(player,kind,cost_bb,street_paid,maxpaid,remaining):
    chips=lambda z:str(int(round(z*200)))
    allin=cost_bb>=remaining-1e-6
    suf=' and is all-in' if allin else ''
    if kind=='CHECK':return f'{player}: checks'
    if kind=='FOLD':return f'{player}: folds'
    if kind=='CALL':return f'{player}: calls {chips(cost_bb)}{suf}'
    target=street_paid+cost_bb
    if maxpaid<=street_paid+1e-9:return f'{player}: bets {chips(cost_bb)}{suf}'
    raise_inc=max(0,target-maxpaid)
    return f'{player}: raises {chips(raise_inc)} to {chips(target)}{suf}'

class Oracle:
    def __init__(self,trials=1000):self.trials=trials;self.pw=self.browser=self.page=None;self.cache={}
    async def start(self):
        self.pw=await async_playwright().start();self.browser=await self.pw.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--no-sandbox','--disable-dev-shm-usage'])
        self.page=await self.browser.new_page();html=Path(HTML).read_text()
        if self.trials!=2500:html=html.replace('snap.trials=2500','snap.trials='+str(self.trials))
        await self.page.set_content(html,wait_until='domcontentloaded',timeout=30000)
        await self.page.set_input_files('#populationModelInput',PRE);await self.page.wait_for_function('state.populationModel&&state.populationModel.nodes.length>0',timeout=30000)
        await self.page.set_input_files('#postflopModelInput',POST);await self.page.wait_for_function('state.postflopModel&&state.postflopModel.nodes.length>0',timeout=30000)
        await self.page.evaluate('scheduleBackgroundReviewScoring=()=>{};')
    async def close(self):
        if self.browser:await self.browser.close()
        if self.pw:await self.pw.stop()
    async def decide(self,hh):
        key=hashlib.sha256(hh.encode()).hexdigest()
        if key in self.cache:return self.cache[key]
        # Give every distinct synthetic state its own deterministic Hand ID.
        # This prevents the application's hand-id keyed trace/range caches from
        # reusing an earlier street state of the same original hand.
        sid=str(800000000000000000 + (int(key[:15],16) % 100000000000000000))
        hh_state=re.sub(r'(PokerStars(?: Zoom)? Hand #)\d+',lambda m:m.group(1)+sid,hh,count=1)
        info=await self.page.evaluate("""(txt)=>{
          state.populationTraceCache=Object.create(null);state.populationRangeCache=Object.create(null);
          state.postflopTraceCache=Object.create(null);state.postflopRangeCache=Object.create(null);
          state.actionEquityCache=Object.create(null);state.seatEquityCache=Object.create(null);
          state.replaySteps=[];state.replayIndex=0;state.reviewScores=Object.create(null);
          const h=parsePokerStarsHand(txt,'sim');state.hhHands=[h];state.selectedHand=h;
          const p=buildReviewBatchPlan(h);p.actions=p.actions.filter(a=>a.actor===h.heroName).slice(-1);window.__p=p;state.reviewBatchBusy=false;runReviewBatchPlan(p);return {id:String(h.id),n:p.actions.length};
        }""",hh_state)
        if not info['n']:raise RuntimeError('oracle found no hero decision')
        await self.page.wait_for_function("!state.reviewBatchBusy && state.reviewScores && Object.keys(state.reviewScores).length>0",timeout=30000)
        r=await self.page.evaluate("state.reviewScores[Object.keys(state.reviewScores)[0]]")
        d=r['details'][-1];self.cache[key]=d;return d

def choose_variant(detail,policy,pot):
    alts=[x for x in detail.get('alternatives',[]) if np.isfinite(float(x.get('policyAdjustedEVBB',x.get('evBB',-1e99))))]
    by={x['label']:x for x in alts};cur=by.get(detail.get('bestLabel'))
    if cur is None:cur=max(alts,key=lambda x:float(x.get('policyAdjustedEVBB',x.get('evBB',-1e99))))
    def val(x):return float(x.get('policyAdjustedEVBB',x.get('evBB',-1e99)))
    nonjam=[x for x in alts if 'jam' not in x['label'].lower()]
    best_non=max(nonjam,key=val) if nonjam else cur
    if policy=='current':return cur
    if policy=='no_jam':return best_non if 'jam' in cur['label'].lower() else cur
    if policy.startswith('jam_margin_') and 'jam' in cur['label'].lower():
        th=float(policy.split('_')[-1]);return cur if val(cur)-val(best_non)>=th else best_non
    if policy.startswith('weakjam_') and 'jam' in cur['label'].lower():
        # Veto only an extreme JAM whose responder model is weakly supported.
        # Syntax weakjam_N => require at least N observations when JAM >3x pot.
        try: th=float(policy.split('_')[-1])
        except: th=10.0
        obs=cur.get('responseObservationFloor')
        ratio=(float(cur.get('costBB') or 0)/max(pot,.01))
        if ratio>3 and obs is not None and float(obs)<th:
            return best_non
        return cur
    if policy.startswith('cap_'):
        cap=float(policy.split('_')[-1])
        # A cap is a veto only: preserve CURRENT whenever its recommended
        # aggression already respects the cap. Do not re-optimize ordinary
        # CHECK/CALL/FOLD/small-bet decisions merely because a cap exists.
        cur_is_aggr=(cur.get('kind')=='aggression')
        cur_cost=cur.get('costBB')
        cur_ratio=(float(cur_cost)/max(pot,.01)) if (cur_is_aggr and cur_cost is not None) else 0.0
        if (not cur_is_aggr) or cur_ratio<=cap:
            return cur
        allowed=[]
        for x in alts:
            if x.get('kind')!='aggression' or x.get('costBB') is None or float(x['costBB'])/max(pot,.01)<=cap:
                allowed.append(x)
        return max(allowed,key=val) if allowed else cur
    return cur

async def rollout(h,profile,opp_cards,runout,policy,oracle,sim_seed):
    hero=h['hero'];active,allin,pre_total=active_at_flop(h);opp=next(p for p in active if p!=hero);order=postflop_order(h,active)
    stacks={p:h['by'][p]['chips']/200 for p in active};total={p:pre_total.get(p,0.) for p in active};flop_start_stack=stacks[hero]-total[hero];post_inv=0.;pot=sum(pre_total.values())
    board=flop_board(h);hero_actions=[];combos,w=profile_range(profile,h['positions'].get(opp,'NA'),h['roles'].get(opp,'OTHER'),h['pot_type'],h['hero_cards'],board);actual=tuple(sorted(a.cid(c) for c in opp_cards))
    if actual not in combos:return None
    hist_lines=[];hist_lines.append(f"*** FLOP *** [{' '.join(board)}]")
    street_cards={'flop':board,'turn':board+[runout[0]],'river':board+runout}
    decision_no=0;opp_act_no=0
    for street in ['flop','turn','river']:
        if street=='turn':
            board=street_cards['turn'];combos,w=filter_range(combos,w,a.cid(runout[0]));hist_lines.append(f"*** TURN *** [{' '.join(board[:3])}] [{board[3]}]")
        elif street=='river':
            board=street_cards['river'];combos,w=filter_range(combos,w,a.cid(runout[1]));hist_lines.append(f"*** RIVER *** [{' '.join(board[:4])}] [{board[4]}]")
        street_paid={hero:0.,opp:0.};last_raise_inc=1.;hist={'aggr':0,'checks':0,'calls':0};pending=list(order)
        while pending:
            actor=pending.pop(0);other=opp if actor==hero else hero;maxpaid=max(street_paid.values());to_call=max(0,maxpaid-street_paid[actor]);remaining=max(0,stacks[actor]-total[actor]);other_rem=max(0,stacks[other]-total[other])
            if remaining<=1e-9:continue
            if actor==hero:
                placeholder='FOLD' if to_call>1e-9 else 'CHECK';phline=action_line(hero,placeholder,0,street_paid[hero],maxpaid,remaining)
                hh=preflop_prefix(h['raw'])+'\n'+'\n'.join(hist_lines+[phline])+'\n'
                detail=await oracle.decide(hh);alt=choose_variant(detail,policy,pot);lab=alt['label'];decision_no+=1
                hero_actions.append({'street':street,'label':lab,'pot_bb':pot,'to_call_bb':to_call,'ev_final_bb':float(alt.get('policyAdjustedEVBB',alt.get('evBB',float('nan')))),'ev_model_bb':float(alt.get('evBB',float('nan'))),'cost_bb':float(alt.get('costBB') or 0) if alt.get('costBB') is not None else None,'size_ratio':(float(alt.get('costBB') or 0)/max(pot,.01)) if alt.get('costBB') is not None else None,'response_observation_floor':alt.get('responseObservationFloor'),'continue_range_quality':alt.get('continueRangeQuality'),'p_all_fold':alt.get('pAllFold')})
                if lab=='FOLD':kind='FOLD';cost=0.
                elif lab=='CHECK':kind='CHECK';cost=0.
                elif lab=='CALL':kind='CALL';cost=min(to_call,remaining)
                else:kind='AGG';cost=min(float(alt.get('costBB') or remaining),remaining)
            else:
                row=model_row(street,opp,profile,h,board,pot,to_call,remaining,hist,order);row['mode']='FACING' if to_call>1e-9 else 'FREE'
                can_raise=remaining>to_call+last_raise_inc+1e-9
                labels,pp,M=opponent_action_probs(street,row,combos,w,board,actual,can_raise=can_raise);lab=sample_label(labels,pp,(sim_seed,street,opp_act_no,'act'));opp_act_no+=1
                col=labels.index(lab);w=w*M[:,col];w/=w.sum()
                if lab=='FOLD':kind='FOLD';cost=0.
                elif lab=='CHECK':kind='CHECK';cost=0.
                elif lab=='CALL':kind='CALL';cost=min(to_call,remaining)
                else:
                    kind='AGG';mode=row['mode'];rat=sample_size(profile,street,mode,'RAISE' if mode=='FACING' else 'BET',(sim_seed,street,opp_act_no,'size'))
                    desired=max(.005,rat*pot)
                    if to_call<=1e-9:cost=min(remaining,max(.005,desired))
                    else:
                        min_target=maxpaid+last_raise_inc;min_cost=max(0,min_target-street_paid[actor]);cost=min(remaining,max(desired,min_cost))
                        if cost<=to_call+1e-9:kind='CALL';cost=min(to_call,remaining)
            # apply
            if kind=='FOLD':
                hist_lines.append(action_line(actor,'FOLD',0,street_paid[actor],maxpaid,remaining))
                if actor==hero:return {'utility':-post_inv,'policy':policy,'decisions':decision_no,'terminal':'hero_fold','hero_actions':hero_actions}
                # Opponent folds: Hero's unmatched excess on the current street is returned
                # before pot/rake accounting. Only the matched part belongs to the pot.
                uncalled=max(0.0,street_paid[hero]-street_paid[opp])
                final_pot=max(0.0,pot-uncalled)
                effective_post_inv=max(0.0,post_inv-uncalled)
                net=a.rake_net(final_pot)
                return {'utility':net-effective_post_inv,'policy':policy,'decisions':decision_no,'terminal':'opp_fold','uncalled_return_bb':uncalled,'hero_actions':hero_actions}
            if kind=='CHECK':
                hist_lines.append(action_line(actor,'CHECK',0,street_paid[actor],maxpaid,remaining));hist['checks']+=1
                continue
            if kind=='CALL':
                hist_lines.append(action_line(actor,'CALL',cost,street_paid[actor],maxpaid,remaining));street_paid[actor]+=cost;total[actor]+=cost;pot+=cost;hist['calls']+=1
                if actor==hero:post_inv+=cost
                # call closes HU betting round
                pending=[]
            else:
                oldmax=maxpaid;hist_lines.append(action_line(actor,'AGG',cost,street_paid[actor],maxpaid,remaining));street_paid[actor]+=cost;total[actor]+=cost;pot+=cost;hist['aggr']+=1
                if actor==hero:post_inv+=cost
                newmax=max(street_paid.values());last_raise_inc=max(.005,newmax-oldmax);pending=[other]
            # all-in terminal once betting is closed or opponent cannot respond further
            if total[hero]>=stacks[hero]-1e-9 or total[opp]>=stacks[opp]-1e-9:
                # if pending, let remaining player respond unless already matched / no call
                if pending:continue
                # return unmatched excess
                eff=min(total[hero],total[opp]);# preflop contributions can differ; exact sidepot in HU: excess above other's total returned
                if total[hero]>total[opp]:
                    ret=total[hero]-total[opp];total[hero]-=ret;pot-=ret;post_inv=max(0,post_inv-ret)
                elif total[opp]>total[hero]:
                    ret=total[opp]-total[hero];total[opp]-=ret;pot-=ret
                finalboard=street_cards['river'];hs=a.best(h['hero_cards']+finalboard);os=a.best(opp_cards+finalboard);net=a.rake_net(pot)
                share=net if hs>os else net/2 if hs==os else 0
                return {'utility':share-post_inv,'policy':policy,'decisions':decision_no,'terminal':'allin_showdown','hero_actions':hero_actions}
        # end street; river => showdown
        if street=='river':
            hs=a.best(h['hero_cards']+board);os=a.best(opp_cards+board);net=a.rake_net(pot);share=net if hs>os else net/2 if hs==os else 0
            return {'utility':share-post_inv,'policy':policy,'decisions':decision_no,'terminal':'showdown','hero_actions':hero_actions}
    return None

def eligible_h3():
    ids=json.load(open('/mnt/data/arena_final_holdout3_manifest.json'))['ids'];out=[]
    for hid in ids:
        h=HANDS.get(str(hid));
        if not h or len(flop_board(h))!=3:continue
        active,allin,tot=active_at_flop(h)
        if len(active)!=2 or h['hero'] not in active or allin:continue
        out.append(str(hid))
    return out

async def main():
    ap=argparse.ArgumentParser();ap.add_argument('--n',type=int,default=6);ap.add_argument('--start',type=int,default=0);ap.add_argument('--ids',default='');ap.add_argument('--reps',type=int,default=1);ap.add_argument('--trials',type=int,default=1000);ap.add_argument('--out',default='/mnt/data/sequential_postflop_benchmark_v2.json');ap.add_argument('--policies',default='current,no_jam,cap_2,cap_3,cap_4');ap.add_argument('--rep-start',type=int,default=0);args=ap.parse_args()
    ids=eligible_h3(); ids=[x.strip() for x in Path(args.ids).read_text().splitlines() if x.strip()] if args.ids else sorted(ids,key=lambda x:hseed('seqpilot',x))[args.start:args.start+args.n]
    policies=[x.strip() for x in args.policies.split(',') if x.strip()]
    oracle=Oracle(args.trials);await oracle.start();results=[]
    try:
      for si,hid in enumerate(ids):
        h=HANDS[hid];active,_,_=active_at_flop(h);opp=next(p for p in active if p!=h['hero']);board=flop_board(h)
        for rep in range(args.rep_start,args.rep_start+args.reps):
          u=u01('profile',hid,rep);c=0;profile=int(PROFILE_WEIGHTS.index[-1])
          for p,wgt in PROFILE_WEIGHTS.items():
            c+=float(wgt)
            if u<=c:profile=int(p);break
          combos,w=profile_range(profile,h['positions'].get(opp,'NA'),h['roles'].get(opp,'OTHER'),h['pot_type'],h['hero_cards'],board)
          idx=int(rng_for('oppcards',hid,rep).choice(len(combos),p=w));opp_cards=[a.ccode(combos[idx][0]),a.ccode(combos[idx][1])]
          blocked={a.cid(c) for c in h['hero_cards']+board+opp_cards};deck=[i for i in range(52) if i not in blocked];rr=rng_for('runout',hid,rep).choice(deck,size=2,replace=False);runout=[a.ccode(int(x)) for x in rr]
          print('scenario',si+1,'/',len(ids),'rep',rep+1,'/',args.reps,hid,'profile',profile,'hero',h['hero_cards'],'opp',opp_cards,'flop',board,'runout',runout,flush=True)
          for pol in policies:
            r=await rollout(h,profile,opp_cards,runout,pol,oracle,hseed('sim',hid,rep));r.update({'hand_id':hid,'rep':rep,'profile':profile,'opp_cards':opp_cards,'hero_cards':h['hero_cards'],'flop':board,'runout':runout});results.append(r)
            print(' ',pol,'utility',round(r['utility'],3),'dec',r['decisions'],r['terminal'],flush=True)
          json.dump({'schema':'sequential-postflop-population-sim/v1','trials':args.trials,'policies':policies,'results':results},open(args.out,'w'),separators=(',',':'))
    finally:await oracle.close()
    print('DONE',args.out,flush=True)
if __name__=='__main__':asyncio.run(main())

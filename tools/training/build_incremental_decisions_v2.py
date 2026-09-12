import zipfile,re,hashlib,datetime as dt,json,collections,math,os
SRC='/mnt/data/RoiDePiqueNique_training2_delta_after_v4v5.zip'
OUT='/mnt/data/poker_population_increment_decisions_v2.jsonl'
SUM='/mnt/data/poker_population_increment_stats_v2.json'
NS='poker-population-split-v1'
RANKS='23456789TJQKA'

def split_for(hid):
    d=hashlib.sha256((NS+':'+hid).encode()).digest(); b=int.from_bytes(d[:8],'big')%10000
    return 'TRAIN' if b<8000 else ('VALIDATION' if b<9000 else 'TEST')

def amount(s):
    s=str(s).strip().replace(' ','').replace('€','').replace('$','').replace('£','')
    if ',' in s and '.' in s: s=s.replace(',','')
    elif ',' in s:
        p=s.split(','); s=p[0]+'.'+p[1] if len(p)==2 and len(p[1])!=3 else s.replace(',','')
    try:return float(s)
    except:return float('nan')

def hand_class(cards):
    if not cards or len(cards)!=2:return None
    a,b=cards
    r1,s1=a[0].upper(),a[1].lower(); r2,s2=b[0].upper(),b[1].lower()
    i1,i2=RANKS.index(r1),RANKS.index(r2)
    if i1==i2:return r1+r2
    if i2>i1:r1,r2,s1,s2,i1,i2=r2,r1,s2,s1,i2,i1
    return r1+r2+('s' if s1==s2 else 'o')

def pos_order(p):
    try:return ['LJ','HJ','CO','BTN','SB','BB','SB_BTN'].index(p)
    except:return 99

def post_pos_order(p):
    # Postflop action order: blinds first, button last. SB_BTN is the HU button/small blind and acts last.
    try:return ['SB','BB','LJ','HJ','CO','BTN','SB_BTN'].index(p)
    except:return 99

def assign_positions(seats,button):
    ss=sorted(seats,key=lambda x:x['seat']); out={}
    bi=next((i for i,s in enumerate(ss) if s['seat']==button),None)
    if bi is None:return out
    ordered=[ss[(bi+i)%len(ss)] for i in range(len(ss))]
    templ={2:['BTN','BB'],3:['BTN','SB','BB'],4:['BTN','SB','BB','CO'],5:['BTN','SB','BB','HJ','CO'],6:['BTN','SB','BB','LJ','HJ','CO']}.get(len(ss),[])
    for i,s in enumerate(ordered): out[s['name']]=templ[i] if i<len(templ) else f"Seat {s['seat']}"
    return out

def norm_pos(p,n):
    p='LJ' if p=='UTG' else p
    return 'SB_BTN' if n==2 and p=='BTN' else p

def family(history,actor):
    if not history:return 'UNOPENED'
    raises=[i for i,x in enumerate(history) if x['action'] in ('RAISE','JAM')]
    limps=[x for x in history if x['action']=='LIMP']
    if not raises:return 'VS_LIMPERS'
    first=raises[0]; callers=[x for x in history[first+1:] if x['action']=='CALL']
    actorRaised=any(x['position']==actor and x['action'] in ('RAISE','JAM') for x in history)
    actorCalled=any(x['position']==actor and x['action'] in ('CALL','LIMP') for x in history)
    if len(raises)==1:
        if limps and first>0:
            actorLimped=any(x['position']==actor and x['action']=='LIMP' for x in history)
            if actorLimped:return 'LIMPER_VS_ISO_CALLERS' if callers else 'LIMPER_VS_ISO'
            return 'VS_ISO_CALLERS' if callers else 'VS_ISO'
        return 'VS_RFI_CALLERS' if callers else 'VS_RFI'
    if len(raises)==2:
        return 'OPENER_OR_ISO_VS_3BET' if actorRaised else ('CALLER_VS_SQUEEZE_OR_3BET' if actorCalled else 'COLD_VS_3BET')
    if len(raises)==3:return 'AGGRESSOR_VS_4BET' if actorRaised else ('CALLER_VS_4BET' if actorCalled else 'COLD_VS_4BET')
    if len(raises)==4:return 'VS_5BET'
    return 'VS_6BET_PLUS'

def board_features(board, prior=None):
    ranks=[RANKS.index(c[0].upper()) for c in board]
    suits=[c[1].lower() for c in board]
    cnt=collections.Counter(ranks); paired=1 if any(v>=2 for v in cnt.values()) else 0; trips=1 if any(v>=3 for v in cnt.values()) else 0
    flush=max(collections.Counter(suits).values(),default=0)/max(1,len(board))
    uniq=sorted(set(ranks)); conn=0
    for i in range(len(uniq)):
        for j in range(i+1,len(uniq)):
            if uniq[j]-uniq[i]<=4:conn=max(conn,j-i+1)
    connectivity=conn/max(1,len(uniq)) if uniq else 0
    high=max(ranks,default=0)/12
    broad=sum(1 for r in ranks if r>=8)/max(1,len(ranks))
    prior=prior or board[:-1]; pr=[RANKS.index(c[0].upper()) for c in prior]
    nr=ranks[-1] if board and len(board)>len(prior) else None
    return {'paired':paired,'trips':trips,'flushiness':flush,'connectivity':connectivity,'high_rank_norm':high,'broadway_norm':broad,
            'new_overcard':1 if nr is not None and pr and nr>max(pr) else 0,'new_pairs_board':1 if nr is not None and ranks.count(nr)>=2 else 0}

def parse_hand(text,source):
    lines=text.replace('\r','').splitlines(); header=lines[0] if lines else ''
    hm=re.search(r'^PokerStars(?: Zoom)? Hand #(\d+):.*? - (\d{4})/(\d{2})/(\d{2}) (\d{1,2}):(\d{2}):(\d{2})',header)
    if not hm:return None
    hid=hm.group(1)
    bm=re.search(r'Seat #(\d+) is the button',text); button=int(bm.group(1)) if bm else None
    seats=[]
    for line in lines:
        m=re.match(r'^Seat (\d+): (.+?) \(([^)]+?) in chips\)\s*$',line)
        if m:seats.append({'seat':int(m.group(1)),'name':m.group(2),'chips':amount(m.group(3))})
    dealt=re.search(r'^Dealt to (.+?) \[([^\]]+)\]',text,re.M)
    if not dealt:return None
    hero=dealt.group(1); known={hero:dealt.group(2).split()}
    seatname={s['seat']:s['name'] for s in seats}
    for line in lines:
        m=re.match(r'^(.+?): shows \[([^\]]+)\]',line)
        if m: known[m.group(1).strip()]=m.group(2).split()
        m=re.match(r'^Seat (\d+): .*?\b(?:showed|mucked) \[([^\]]+)\]',line)
        if m and int(m.group(1)) in seatname: known[seatname[int(m.group(1))]]=m.group(2).split()
    pos=assign_positions(seats,button)
    bbm=re.search(r'\(([^()]*)\)',header); bb=None
    for g in re.findall(r'\(([^()]*)\)',header):
        m=re.search(r'([€$£]?\s*[\d.,]+)\s*/\s*([€$£]?\s*[\d.,]+)',g)
        if m:
            v=amount(m.group(2));
            if math.isfinite(v) and v>0:bb=v;break
    if not bb:return None
    players=[]
    for s in seats: players.append({**s,'pos':pos.get(s['name'],''),'known':known.get(s['name'])})
    by={p['name']:p for p in players}
    # Timeline actions with pot and raw incremental amount, modeled after app parser.
    streets={'preflop':[],'flop':[],'turn':[],'river':[]}; current='preflop'; pot=0.0; paid=collections.defaultdict(float)
    boards={'preflop':[],'flop':[],'turn':[],'river':[]}; full=[]
    for line in lines:
        if line.startswith('*** FLOP ***'):
            current='flop';paid=collections.defaultdict(float);m=re.search(r'\[([^\]]+)\]',line);full=m.group(1).split() if m else [];boards[current]=full.copy();continue
        if line.startswith('*** TURN ***'):
            current='turn';paid=collections.defaultdict(float);m=re.findall(r'\[([^\]]+)\]',line);full=(m[0].split()+m[1].split()) if len(m)>=2 else full;boards[current]=full.copy();continue
        if line.startswith('*** RIVER ***'):
            current='river';paid=collections.defaultdict(float);m=re.findall(r'\[([^\]]+)\]',line);full=(m[0].split()+m[1].split()) if len(m)>=2 else full;boards[current]=full.copy();continue
        if line.startswith('*** SHOW DOWN ***') or line.startswith('*** SUMMARY ***'): continue
        m=re.match(r'^Uncalled bet \(([^)]+)\) returned to (.+)$',line)
        if m:
            a=amount(m.group(1));pl=m.group(2).strip();pot=max(0,pot-a);paid[pl]=max(0,paid[pl]-a);streets[current].append({'player':pl,'type':'return','raw':a,'pot_after':pot,'allin':False});continue
        m=re.match(r'^(.+?): posts (.+?) ([€$£]?\s*[\d.,]+)(?: and is all-in)?$',line)
        if m:
            pl=m.group(1);a=amount(m.group(3));pot+=a
            if 'ante' not in m.group(2).lower():paid[pl]+=a
            streets[current].append({'player':pl,'type':'post','raw':a,'pot_after':pot,'allin':'and is all-in' in line});continue
        m=re.match(r'^(.+?): calls ([€$£]?\s*[\d.,]+)(?: and is all-in)?$',line)
        if m:
            pl=m.group(1);a=amount(m.group(2));pot+=a;paid[pl]+=a;streets[current].append({'player':pl,'type':'call','raw':a,'pot_after':pot,'allin':'and is all-in' in line});continue
        m=re.match(r'^(.+?): bets ([€$£]?\s*[\d.,]+)(?: and is all-in)?$',line)
        if m:
            pl=m.group(1);a=amount(m.group(2));pot+=a;paid[pl]+=a;streets[current].append({'player':pl,'type':'bet','raw':a,'pot_after':pot,'allin':'and is all-in' in line});continue
        m=re.match(r'^(.+?): raises ([€$£]?\s*[\d.,]+) to ([€$£]?\s*[\d.,]+)(?: and is all-in)?$',line)
        if m:
            pl=m.group(1);to=amount(m.group(3));add=max(0,to-paid[pl]);pot+=add;paid[pl]=to;streets[current].append({'player':pl,'type':'raise','raw':add,'pot_after':pot,'allin':'and is all-in' in line});continue
        m=re.match(r'^(.+?): checks\b',line)
        if m:streets[current].append({'player':m.group(1),'type':'check','raw':0,'pot_after':pot,'allin':False});continue
        m=re.match(r'^(.+?): folds\b',line)
        if m:streets[current].append({'player':m.group(1),'type':'fold','raw':0,'pot_after':pot,'allin':False});continue
    return {'id':hid,'source':source,'hero':hero,'bb':bb,'players':players,'by':by,'streets':streets,'boards':boards}

def decision_rows(h):
    rows=[]; n=len(h['players']); by=h['by']; hero=h['hero']; bb=h['bb']; split=split_for(h['id'])
    # preflop
    inhand=set(by); allin=set(); hist=[]; rl=0; pf_paid=collections.defaultdict(float); pf_price=0.0
    for a in h['streets']['preflop']:
        if a['type']=='post':
            paidbb=(a.get('raw') or 0)/bb
            pf_paid[a['player']]+=paidbb; pf_price=max(pf_price,pf_paid[a['player']])
            if a['allin']:allin.add(a['player'])
            continue
        if a['type'] not in ('fold','check','call','raise','bet'):continue
        if a['player'] not in by:continue
        actor=norm_pos(by[a['player']]['pos'],n)
        act='FOLD' if a['type']=='fold' else 'CHECK' if a['type']=='check' else ('LIMP' if a['type']=='call' and rl==0 else 'CALL') if a['type']=='call' else ('JAM' if a['allin'] else 'RAISE')
        live=sorted([norm_pos(by[x]['pos'],n) for x in inhand if x not in allin],key=pos_order)
        ais=sorted([norm_pos(by[x]['pos'],n) for x in allin if x in by],key=pos_order)
        key=f"{n}|{actor}|live={','.join(live)}|allin={','.join(ais)}|hist="+">".join(f"{x['position']}:{x['action']}" for x in hist)
        actor_paid=pf_paid[a['player']]; tocall=max(0,pf_price-actor_paid); free_check=tocall<=1e-9
        fam=family(hist,actor)
        row={'hand_id':h['id'],'split':split,'street':'preflop','player':a['player'],'is_hero':a['player']==hero,'actor_position':actor,'action':act,
             'table_size':n,'raise_level':rl,'family':fam,'live_positions':live,'all_in_positions':ais,'history':hist.copy(),'free_check':free_check,
             'pot_before_bb':max(0,(a['pot_after']-a['raw'])/bb),'to_call_bb':tocall,'current_price_bb':pf_price,
             'action_add_bb':a['raw']/bb,'actor_start_stack_bb':by[a['player']]['chips']/bb,'actor_remaining_bb_before':max(0,by[a['player']]['chips']/bb-actor_paid),
             'known_hand_class':hand_class(by[a['player']].get('known')),'known_cards':by[a['player']].get('known'),
             'structural_key_no_forced':key,'structural_id_no_forced':'PF_'+hashlib.sha1(key.encode()).hexdigest()[:12],
             'v4_canonical_key':f"{n}|{actor}|family={fam}|rl={rl}|free={1 if free_check else 0}|live={','.join(live)}|allin={','.join(ais)}|hist="+">".join(f"{x['position']}:{x['action']}" for x in hist)}
        rows.append(row)
        if act=='FOLD':inhand.discard(a['player']);allin.discard(a['player'])
        else:
            if a['type'] in ('call','raise','bet'):
                pf_paid[a['player']]+=a['raw']/bb; pf_price=max(pf_price,pf_paid[a['player']])
            hist.append({'position':actor,'action':act})
            if act in ('RAISE','JAM'):rl+=1
            if a['allin']:allin.add(a['player'])
    # initialize paid/allin after preflop to determine live postflop
    inhand=set(by); allin=set(); totalpaid=collections.defaultdict(float)
    for a in h['streets']['preflop']:
        if a['type']=='fold':inhand.discard(a['player'])
        if a['type'] in ('post','call','bet','raise'):totalpaid[a['player']]+=a['raw']/bb
        elif a['type']=='return':totalpaid[a['player']]=max(0,totalpaid[a['player']]-a['raw']/bb)
        if a['allin']:allin.add(a['player'])
    # preflop summary roles
    pf_rows=[r for r in rows if r['street']=='preflop']; raises=0;lastagg=''; actionsby=collections.defaultdict(list)
    for r in pf_rows:
        actionsby[r['player']].append(r['action'])
        if r['action'] in ('RAISE','JAM'):raises+=1;lastagg=r['player']
    pottype='LIMPED' if raises==0 else 'SRP' if raises==1 else '3BP' if raises==2 else '4BP_PLUS'
    roles={}
    for p in h['players']:
        acts=actionsby[p['name']]
        roles[p['name']]='PFA' if p['name']==lastagg else 'CALLER' if 'CALL' in acts else 'LIMPER' if 'LIMP' in acts else 'BB_CHECK' if 'CHECK' in acts else 'OTHER'
    for st in ('flop','turn','river'):
        acts=h['streets'][st]; board=h['boards'][st]; streetpaid=collections.defaultdict(float);price=0;hist2=[];street_start=len([x for x in inhand if x not in allin])
        for a in acts:
            if a['type']=='return':
                totalpaid[a['player']]=max(0,totalpaid[a['player']]-a['raw']/bb);streetpaid[a['player']]=max(0,streetpaid[a['player']]-a['raw']/bb);continue
            if a['type'] not in ('fold','check','call','bet','raise'):continue
            if a['player'] not in by:continue
            live=[x for x in inhand if x not in allin]; paid=streetpaid[a['player']];tocall=max(0,price-paid);mode='FACING' if tocall>1e-9 else 'FREE'
            act='FOLD' if a['type']=='fold' else 'CHECK' if a['type']=='check' else 'CALL' if a['type']=='call' else ('JAM' if a['allin'] else ('BET' if a['type']=='bet' else 'RAISE'))
            # relative position
            live_sorted=sorted(live,key=lambda name:post_pos_order(norm_pos(by[name]['pos'],n)))
            idx=live_sorted.index(a['player']) if a['player'] in live_sorted else 0
            rel='ONLY' if len(live_sorted)<=1 else 'OOP' if idx<=0 else 'IP' if idx==len(live_sorted)-1 else 'MIDDLE'
            histstr='>'.join(x for x in hist2 if x!='FOLD')
            pot_after=a['pot_after']/bb; add=a['raw']/bb; pot_before=max(0,pot_after-(add if a['type'] in ('call','bet','raise') else 0))
            start=by[a['player']]['chips']/bb; rem=max(0,start-totalpaid[a['player']]); bf=board_features(board)
            key='|'.join(map(str,[st,street_start,len(live),rel,pottype,roles[a['player']],histstr]))
            row={'hand_id':h['id'],'split':split,'street':st,'player':a['player'],'is_hero':a['player']==hero,'action':act,'mode':mode,
                 'street_start_players':street_start,'active_players':len(live),'relative_position':rel,'pot_type':pottype,'preflop_role':roles[a['player']],
                 'street_history':histstr,'canonical_key':key,'canonical_id':'PO_'+hashlib.sha1(key.encode()).hexdigest()[:12],
                 'board':board,'board_features':bf,'pot_before_bb':pot_before,'to_call_bb':tocall,'facing_price_pot':tocall/pot_before if pot_before>0 else 0,
                 'own_size_pot':add/pot_before if act in ('BET','RAISE','JAM') and pot_before>0 else None,'spr':rem/pot_before if pot_before>0 else 0,
                 'known_hand_class':hand_class(by[a['player']].get('known')),'known_cards':by[a['player']].get('known')}
            rows.append(row)
            if act=='FOLD':inhand.discard(a['player'])
            elif act=='CALL':streetpaid[a['player']]+=add;totalpaid[a['player']]+=add
            elif act in ('BET','RAISE','JAM'):
                streetpaid[a['player']]+=add;totalpaid[a['player']]+=add;price=max(price,streetpaid[a['player']])
            if a['allin']:allin.add(a['player'])
            hist2.append(act)
    return rows

stats={'hands':collections.Counter(),'decisions':collections.Counter(),'population_actions':collections.Counter(),'hero_actions':collections.Counter(),
       'known_population_decisions':collections.Counter(),'preflop_nodes':collections.defaultdict(set),'postflop_nodes':collections.defaultdict(set)}
parse_errors=[]; allrows=[]
with zipfile.ZipFile(SRC) as z:
    for name in z.namelist():
        if name.endswith('/'):continue
        txt=z.read(name).decode('utf-8-sig',errors='replace')
        h=parse_hand(txt,name)
        if not h:parse_errors.append(name);continue
        sp=split_for(h['id']);stats['hands'][sp]+=1
        for r in decision_rows(h):
            allrows.append(r);stats['decisions'][(sp,r['street'], 'hero' if r['is_hero'] else 'population')]+=1
            if r['is_hero']:stats['hero_actions'][(sp,r['street'],r['action'])]+=1
            else:
                stats['population_actions'][(sp,r['street'],r['action'])]+=1
                if r.get('known_hand_class'):stats['known_population_decisions'][(sp,r['street'],r['action'])]+=1
            if r['street']=='preflop':stats['preflop_nodes'][sp].add(r['structural_id_no_forced'])
            else:stats['postflop_nodes'][sp].add(r['canonical_id'])
with open(OUT,'w',encoding='utf-8') as f:
    for r in allrows:f.write(json.dumps(r,ensure_ascii=False,separators=(',',':'))+'\n')
summary={
 'schema':'poker-population-increment-stats/v1','source':os.path.basename(SRC),'parsed_hands':sum(stats['hands'].values()),'parse_errors':parse_errors,
 'hands_by_split':dict(stats['hands']),
 'decision_counts':{'|'.join(map(str,k)):v for k,v in sorted(stats['decisions'].items())},
 'population_actions':{'|'.join(map(str,k)):v for k,v in sorted(stats['population_actions'].items())},
 'hero_actions':{'|'.join(map(str,k)):v for k,v in sorted(stats['hero_actions'].items())},
 'known_population_decisions':{'|'.join(map(str,k)):v for k,v in sorted(stats['known_population_decisions'].items())},
 'distinct_preflop_structural_nodes':{k:len(v) for k,v in stats['preflop_nodes'].items()},
 'distinct_postflop_nodes':{k:len(v) for k,v in stats['postflop_nodes'].items()},
 'rows_total':len(allrows)
}
with open(SUM,'w',encoding='utf-8') as f:json.dump(summary,f,ensure_ascii=False,indent=2)
print(json.dumps(summary,ensure_ascii=False,indent=2))
print('WROTE',OUT,os.path.getsize(OUT),'bytes')
print('WROTE',SUM,os.path.getsize(SUM),'bytes')

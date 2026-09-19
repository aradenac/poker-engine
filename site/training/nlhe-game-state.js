(function(root,factory){
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root)root.PokerNlheGameState=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  const EPS=1e-9,STREETS=['preflop','flop','turn','river'],SNAPSHOT_SCHEMA='nlhe-game-state/v1';
  const r=v=>Math.round((Number(v)+Number.EPSILON)*1e9)/1e9;
  const nonnegative=(v,name)=>{const n=Number(v);if(!Number.isFinite(n)||n<-EPS)throw new Error(name+' must be finite and non-negative');return Math.max(0,n);};
  class RuleError extends Error{constructor(message){super(message);this.name='RuleError';}}
  class NoLimitHoldemState{
    constructor({seats,button,stacks_bb,small_blind_bb=.5,big_blind_bb=1}={}){
      if(!Array.isArray(seats)||seats.length<2)throw new Error('at least two seats are required');
      if(new Set(seats).size!==seats.length)throw new Error('seat names must be unique');
      if(!seats.includes(button))throw new Error('button must be seated');
      if(!stacks_bb||Object.keys(stacks_bb).length!==seats.length||seats.some(p=>!Object.prototype.hasOwnProperty.call(stacks_bb,p)))throw new Error('stacks_bb must cover exactly the seated players');
      this.seats=[...seats];this.button=String(button);
      this.small_blind_bb=nonnegative(small_blind_bb,'small_blind_bb');this.big_blind_bb=nonnegative(big_blind_bb,'big_blind_bb');
      if(this.big_blind_bb<=EPS)throw new Error('big blind must be positive');
      if(this.small_blind_bb>this.big_blind_bb+EPS)throw new Error('small blind cannot exceed big blind');
      this.starting_stacks_bb=Object.fromEntries(this.seats.map(p=>[p,nonnegative(stacks_bb[p],`stack[${p}]`)]));
      this.stacks_bb={...this.starting_stacks_bb};
      this.total_committed_bb=Object.fromEntries(this.seats.map(p=>[p,0]));
      this.street_committed_bb=Object.fromEntries(this.seats.map(p=>[p,0]));
      this.folded=Object.fromEntries(this.seats.map(p=>[p,false]));
      this.all_in=Object.fromEntries(this.seats.map(p=>[p,false]));
      this.street='preflop';this.board=[];this.current_bet_bb=0;this.last_full_raise_bb=this.big_blind_bb;this.full_bet_established=false;
      this.acted_since_full_raise=new Set();this.pending=[];this.action_log=[];this.refunds_bb=Object.fromEntries(this.seats.map(p=>[p,0]));
      if(this.seats.length===2){this.small_blind_player=this.button;this.big_blind_player=this.nextSeat(this.button);}
      else{this.small_blind_player=this.nextSeat(this.button);this.big_blind_player=this.nextSeat(this.small_blind_player);}
      this.commit(this.small_blind_player,Math.min(this.small_blind_bb,this.stacks_bb[this.small_blind_player]));
      this.commit(this.big_blind_player,Math.min(this.big_blind_bb,this.stacks_bb[this.big_blind_player]));
      this.current_bet_bb=this.big_blind_bb;this.full_bet_established=true;this.last_full_raise_bb=this.big_blind_bb;
      this.pending=this.orderedFrom(this.nextSeat(this.big_blind_player),true);this.autoCloseDryAction();
    }
    get pot_bb(){return r(Object.values(this.total_committed_bb).reduce((a,b)=>a+Number(b||0),0));}
    get live_players(){return this.seats.filter(p=>!this.folded[p]);}
    get betting_complete(){return this.pending.length===0;}
    get next_actor(){return this.pending[0]||null;}
    nextSeat(player){const i=this.seats.indexOf(player);if(i<0)throw new Error('unknown seat '+player);return this.seats[(i+1)%this.seats.length];}
    orderedFrom(first,actionableOnly=false,exclude=new Set()){
      const i=this.seats.indexOf(first),ordered=[...this.seats.slice(i),...this.seats.slice(0,i)];
      return actionableOnly?ordered.filter(p=>!exclude.has(p)&&!this.folded[p]&&!this.all_in[p]&&this.stacks_bb[p]>EPS):ordered;
    }
    commit(player,amount){amount=nonnegative(amount,'commit amount');if(amount>this.stacks_bb[player]+EPS)throw new RuleError('cannot commit more than remaining stack');amount=Math.min(amount,this.stacks_bb[player]);this.stacks_bb[player]-=amount;this.total_committed_bb[player]+=amount;this.street_committed_bb[player]+=amount;if(this.stacks_bb[player]<=EPS){this.stacks_bb[player]=0;this.all_in[player]=true;}}
    legalView(player=this.next_actor){
      if(!player)throw new RuleError('no player is pending');if(!this.seats.includes(player))throw new Error('unknown player '+player);
      if(this.folded[player]||this.all_in[player])throw new RuleError('folded/all-in player cannot act');
      if(this.pending.length&&player!==this.pending[0])throw new RuleError(player+' is not next to act');
      const paid=this.street_committed_bb[player],remaining=this.stacks_bb[player],toCallFull=Math.max(0,this.current_bet_bb-paid),callCost=Math.min(toCallFull,remaining),maxTo=paid+remaining;
      const opponentsCanRespond=this.seats.some(q=>q!==player&&!this.folded[q]&&!this.all_in[q]&&this.stacks_bb[q]>EPS);
      const raiseReopened=!this.acted_since_full_raise.has(player)||toCallFull+EPS>=this.last_full_raise_bb;
      const canRaise=raiseReopened&&maxTo>this.current_bet_bb+EPS&&opponentsCanRespond;
      const minRaiseTo=canRaise?(this.full_bet_established?this.current_bet_bb+this.last_full_raise_bb:this.big_blind_bb):null;
      const legal=toCallFull>EPS?['FOLD','CALL']:['CHECK'];if(canRaise)legal.push('RAISE');
      return {street:this.street,actor:player,pot_before_bb:this.pot_bb,actor_sunk_total_bb:r(this.total_committed_bb[player]),actor_street_contribution_bb:r(paid),actor_remaining_bb:r(remaining),current_price_bb:r(this.current_bet_bb),to_call_bb:r(callCost),full_to_call_bb:r(toCallFull),free_check:toCallFull<=EPS,legal_actions:legal,raise_reopened:raiseReopened,min_raise_to_bb:minRaiseTo==null?null:r(minRaiseTo),max_raise_to_bb:r(maxTo),remaining_to_act:this.pending[0]===player?this.pending.slice(1):[]};
    }
    applyAction(player,action,{target_total_bb=null}={}){
      const view=this.legalView(player);action=String(action||'').toUpperCase();if(!view.legal_actions.includes(action))throw new RuleError(action+' is not legal for '+player);
      const beforeTotal=this.total_committed_bb[player];
      if(action==='FOLD'){this.folded[player]=true;this.acted_since_full_raise.add(player);this.pending.shift();}
      else if(action==='CHECK'){this.acted_since_full_raise.add(player);this.pending.shift();}
      else if(action==='CALL'){this.commit(player,view.to_call_bb);this.acted_since_full_raise.add(player);this.pending.shift();}
      else{
        if(target_total_bb==null)throw new RuleError('RAISE requires target_total_bb');
        const target=Number(target_total_bb),maxTo=Number(view.max_raise_to_bb);
        if(!Number.isFinite(target)||target>maxTo+EPS)throw new RuleError('raise target exceeds actor stack');
        if(target<=this.current_bet_bb+EPS)throw new RuleError('raise target must increase the current price');
        const isAllIn=Math.abs(target-maxTo)<=EPS,minTo=view.min_raise_to_bb;
        if(minTo!=null&&target+EPS<Number(minTo)&&!isAllIn)throw new RuleError('raise target below minimum '+minTo);
        const oldPrice=this.current_bet_bb,incremental=target-this.street_committed_bb[player];this.commit(player,incremental);
        const newPrice=this.street_committed_bb[player],raiseInc=newPrice-oldPrice;
        let fullRaise=false;
        if(!this.full_bet_established){fullRaise=newPrice+EPS>=this.big_blind_bb;if(fullRaise){this.full_bet_established=true;this.last_full_raise_bb=newPrice;}}
        else{fullRaise=raiseInc+EPS>=this.last_full_raise_bb;if(fullRaise)this.last_full_raise_bb=raiseInc;}
        this.current_bet_bb=Math.max(this.current_bet_bb,newPrice);
        if(fullRaise)this.acted_since_full_raise=new Set([player]);else this.acted_since_full_raise.add(player);
        this.pending=this.orderedFrom(this.nextSeat(player),true,new Set([player]));
      }
      this.autoCloseDryAction();
      const record={index:this.action_log.length,street:this.street,player,action,target_total_bb:target_total_bb==null?null:r(Number(target_total_bb)),incremental_cost_bb:r(this.total_committed_bb[player]-beforeTotal)};
      this.action_log.push(record);return record;
    }
    advanceStreet(board_cards){
      if(!this.betting_complete)throw new RuleError('cannot advance while betting is pending');if(this.live_players.length<=1)throw new RuleError('hand ended by folds');
      const i=STREETS.indexOf(this.street);if(i<0||i>=STREETS.length-1)throw new RuleError('river is the final street');
      const expected=this.street==='preflop'?3:1;if(!Array.isArray(board_cards)||board_cards.length!==expected)throw new Error('invalid board-card count');
      const cards=board_cards.map(String);if(new Set([...this.board,...cards]).size!==this.board.length+cards.length)throw new Error('duplicate board card');
      this.board.push(...cards);this.street=STREETS[i+1];this.street_committed_bb=Object.fromEntries(this.seats.map(p=>[p,0]));this.current_bet_bb=0;this.last_full_raise_bb=this.big_blind_bb;this.full_bet_established=false;this.acted_since_full_raise=new Set();
      this.pending=this.orderedFrom(this.nextSeat(this.button),true);this.autoCloseDryAction();
    }
    autoCloseDryAction(){
      this.pending=this.pending.filter(p=>!this.folded[p]&&!this.all_in[p]);
      const live=this.live_players;if(live.length<=1){this.pending=[];return;}
      const actionable=live.filter(p=>!this.all_in[p]&&this.stacks_bb[p]>EPS);
      if(actionable.length===1){const p=actionable[0];if(Math.max(0,this.current_bet_bb-this.street_committed_bb[p])<=EPS)this.pending=[];else if(!this.pending.includes(p))this.pending=[p];}
      else if(!actionable.length)this.pending=[];
    }
    toSnapshot({include_log=true}={}){
      const data={schema:SNAPSHOT_SCHEMA,seats:[...this.seats],button:this.button,small_blind_player:this.small_blind_player,big_blind_player:this.big_blind_player,small_blind_bb:r(this.small_blind_bb),big_blind_bb:r(this.big_blind_bb),starting_stacks_bb:{...this.starting_stacks_bb},stacks_bb:Object.fromEntries(this.seats.map(p=>[p,r(this.stacks_bb[p])])),total_committed_bb:Object.fromEntries(this.seats.map(p=>[p,r(this.total_committed_bb[p])])),street_committed_bb:Object.fromEntries(this.seats.map(p=>[p,r(this.street_committed_bb[p])])),folded:{...this.folded},all_in:{...this.all_in},street:this.street,board:[...this.board],current_bet_bb:r(this.current_bet_bb),last_full_raise_bb:r(this.last_full_raise_bb),full_bet_established:!!this.full_bet_established,acted_since_full_raise:this.seats.filter(p=>this.acted_since_full_raise.has(p)),pending:[...this.pending],refunds_bb:{...this.refunds_bb}};
      if(include_log)data.action_log=this.action_log.map(x=>({...x}));return data;
    }
  }
  return {EPS,STREETS,SNAPSHOT_SCHEMA,RuleError,NoLimitHoldemState};
});
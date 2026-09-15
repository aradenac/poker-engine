#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise RuntimeError(f"expected exactly one match in {path}: {old[:100]!r} (found {text.count(old)})")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# ---------------------------------------------------------------------------
# Python contract corrections discovered by the shared fixture design.
# ---------------------------------------------------------------------------
p = ROOT / "tools/preflop/context_contract.py"
replace_once(
    p,
    'POSITION_ORDER_6MAX = ("LJ", "HJ", "CO", "BTN", "SB", "BB")\nPOSITION_ORDER_HU = ("SB_BTN", "BB")\nACTIONS = ("FOLD", "CHECK", "LIMP", "CALL", "RAISE", "JAM")',
    'LEGACY_POSITION_ORDER = ("LJ", "HJ", "CO", "BTN", "SB", "BB", "SB_BTN")\nACTION_ORDER_6MAX = ("LJ", "HJ", "CO", "BTN", "SB", "BB")\nACTION_ORDER_HU = ("SB_BTN", "BB")\nACTIONS = ("FOLD", "CHECK", "LIMP", "CALL", "RAISE", "JAM")',
)
replace_once(
    p,
    'def position_order(table_size: int) -> tuple[str, ...]:\n    return POSITION_ORDER_HU if int(table_size) == 2 else POSITION_ORDER_6MAX\n\n\ndef sort_positions(positions: Iterable[str], table_size: int) -> list[str]:\n    order = position_order(table_size)',
    'def position_order(table_size: int) -> tuple[str, ...]:\n    """Legacy v5 ordering used by persisted live/all-in position arrays."""\n    return LEGACY_POSITION_ORDER\n\n\ndef action_order(table_size: int) -> tuple[str, ...]:\n    """Actual preflop action order; HU SB/BTN acts before BB."""\n    return ACTION_ORDER_HU if int(table_size) == 2 else ACTION_ORDER_6MAX\n\n\ndef sort_positions(positions: Iterable[str], table_size: int) -> list[str]:\n    order = position_order(table_size)',
)
anchor = '''def normalize_history(history: str | Sequence[Mapping[str, Any]] | None) -> list[dict[str, str]]:\n'''
insert = '''def derive_remaining_to_act(\n    *,\n    live_positions: Sequence[str],\n    all_in_positions: Sequence[str],\n    history: str | Sequence[Mapping[str, Any]] | None,\n    actor_position: str,\n    table_size: int,\n) -> list[str]:\n    """Players still pending if the actor does not reopen the betting.\n\n    Folds are absent from structural history but also absent from live_positions,\n    so the pending set can be reconstructed from the last aggression cycle.\n    """\n    actor = normalize_position(actor_position, table_size)\n    live = {normalize_position(p, table_size) for p in live_positions}\n    allin = {normalize_position(p, table_size) for p in all_in_positions}\n    hist = [\n        {"position": normalize_position(x["position"], table_size), "action": x["action"]}\n        for x in normalize_history(history)\n    ]\n    last_raise = max((i for i, x in enumerate(hist) if x["action"] in ("RAISE", "JAM")), default=-1)\n    if last_raise >= 0:\n        aggressor = hist[last_raise]["position"]\n        acted = {aggressor} | {x["position"] for x in hist[last_raise + 1 :]}\n    else:\n        acted = {x["position"] for x in hist}\n    pending = live - allin - acted - {actor}\n    return [p for p in action_order(table_size) if p in pending]\n\n\n'''
text = p.read_text(encoding="utf-8")
if text.count(anchor) != 1:
    raise RuntimeError("normalize_history anchor mismatch")
p.write_text(text.replace(anchor, insert + anchor, 1), encoding="utf-8")
replace_once(
    p,
    '''    if to_call > EPS:\n        legal.append("FOLD")\n        if remaining > EPS:\n            legal.append("CALL")\n    else:\n        legal.append("CHECK")\n        # A voluntary call with zero price is never represented as CALL.\n        if int(raise_level) == 0 and actor_contribution + EPS < max_to:\n            legal.append("LIMP")\n''',
    '''    if to_call > EPS:\n        legal.append("FOLD")\n        if remaining > EPS:\n            legal.append("LIMP" if int(raise_level) == 0 else "CALL")\n    else:\n        # A free option is CHECK; LIMP/CALL always imply paying positive chips.\n        legal.append("CHECK")\n''',
)
replace_once(
    p,
    '''    if pending_positions is None:\n        order = [p for p in position_order(n) if p in live and p not in allin]\n        idx = order.index(actor) if actor in order else -1\n        pending = order[idx + 1 :] if idx >= 0 else []\n    else:\n''',
    '''    if pending_positions is None:\n        pending = derive_remaining_to_act(\n            live_positions=live, all_in_positions=allin, history=hist,\n            actor_position=actor, table_size=n,\n        )\n    else:\n''',
)

# ---------------------------------------------------------------------------
# Browser contract: legacy ordering for v5 arrays, actual order for pending.
# ---------------------------------------------------------------------------
p = ROOT / "site/preflop-contract.js"
replace_once(
    p,
    "  const ORDER6=['LJ','HJ','CO','BTN','SB','BB'];\n  const ORDERHU=['SB_BTN','BB'];",
    "  const LEGACY_ORDER=['LJ','HJ','CO','BTN','SB','BB','SB_BTN'];\n  const ACTION_ORDER6=['LJ','HJ','CO','BTN','SB','BB'];\n  const ACTION_ORDERHU=['SB_BTN','BB'];",
)
replace_once(
    p,
    "  const orderFor=tableSize=>Number(tableSize)===2?ORDERHU:ORDER6;\n  const sortPositions=(positions,tableSize)=>{\n    const order=orderFor(tableSize),rank=new Map(order.map((p,i)=>[p,i]));",
    "  const legacyOrder=()=>LEGACY_ORDER;\n  const actionOrder=tableSize=>Number(tableSize)===2?ACTION_ORDERHU:ACTION_ORDER6;\n  const sortPositions=(positions,tableSize)=>{\n    const order=legacyOrder(),rank=new Map(order.map((p,i)=>[p,i]));",
)
anchor = "  const historyToken=history=>normalizeHistory(history).map(x=>`${x.position}:${x.action}`).join('>');\n"
insert = """  const deriveRemainingToAct=({live_positions,all_in_positions=[],history,actor_position,table_size})=>{\n    const actor=normPos(actor_position,table_size),live=new Set((live_positions||[]).map(p=>normPos(p,table_size))),allin=new Set((all_in_positions||[]).map(p=>normPos(p,table_size)));\n    const hist=normalizeHistory(history).map(x=>({position:normPos(x.position,table_size),action:x.action}));\n    let lastRaise=-1;hist.forEach((x,i)=>{if(['RAISE','JAM'].includes(x.action))lastRaise=i;});\n    const acted=new Set();\n    if(lastRaise>=0){acted.add(hist[lastRaise].position);for(const x of hist.slice(lastRaise+1))acted.add(x.position);}\n    else for(const x of hist)acted.add(x.position);\n    return actionOrder(table_size).filter(p=>live.has(p)&&!allin.has(p)&&!acted.has(p)&&p!==actor);\n  };\n"""
text = p.read_text(encoding="utf-8")
if text.count(anchor) != 1:
    raise RuntimeError("JS historyToken anchor mismatch")
p.write_text(text.replace(anchor, anchor + insert, 1), encoding="utf-8")
replace_once(
    p,
    "    let pending;if(args.pending_positions==null){const order=orderFor(n).filter(p=>live.includes(p)&&!allin.includes(p)),i=order.indexOf(actor);pending=i>=0?order.slice(i+1):[];}else pending=args.pending_positions.map(p=>normPos(p,n)).filter(p=>live.includes(p)&&!allin.includes(p)&&p!==actor);",
    "    let pending;if(args.pending_positions==null)pending=deriveRemainingToAct({live_positions:live,all_in_positions:allin,history:hist,actor_position:actor,table_size:n});else pending=args.pending_positions.map(p=>normPos(p,n)).filter(p=>live.includes(p)&&!allin.includes(p)&&p!==actor);",
)
replace_once(
    p,
    "  return {SCHEMA,PROBABILITY_SCHEMA,STATE_TIMING,normalizePosition:normPos,sortPositions,normalizeHistory,historyToken,familyFromHistory,legalActionsForState,canonicalKey,contextId,buildContext,v5RuntimeSignature,normalizeActionProbabilities};",
    "  return {SCHEMA,PROBABILITY_SCHEMA,STATE_TIMING,normalizePosition:normPos,sortPositions,normalizeHistory,historyToken,deriveRemainingToAct,familyFromHistory,legalActionsForState,canonicalKey,contextId,buildContext,v5RuntimeSignature,normalizeActionProbabilities};",
)

# ---------------------------------------------------------------------------
# Training extraction: attach v1 context while retaining every legacy field.
# ---------------------------------------------------------------------------
p = ROOT / "tools/training/increment_decisions.py"
replace_once(
    p,
    "from tools.datasets.build_hand_history_increment import fingerprint, read_archive, sha256_file, split_for  # noqa: E402",
    "from tools.datasets.build_hand_history_increment import fingerprint, read_archive, sha256_file, split_for  # noqa: E402\nfrom tools.preflop.context_contract import build_context  # noqa: E402",
)
replace_once(
    p,
    '''def decision_rows(h):\n    rows = []; n = len(h["players"]); by = h["by"]; hero = h["hero"]; bb = h["bb"]; split = split_for(h["id"])\n    inhand = set(by); allin = set(); hist = []; rl = 0; pf_paid = collections.defaultdict(float); pf_price = 0.0\n''',
    '''def decision_rows(h):\n    rows = []; n = len(h["players"]); by = h["by"]; hero = h["hero"]; bb = h["bb"]; split = split_for(h["id"])\n    inhand = set(by); allin = set(); hist = []; rl = 0; pf_paid = collections.defaultdict(float); pf_price = 0.0\n    last_full_raise_increment = 1.0\n    stack_by_pos = {norm_pos(p["pos"], n): p["chips"] / bb for p in h["players"]}\n''',
)
old = '''        actor_paid = pf_paid[a["player"]]; tocall = max(0, pf_price - actor_paid); free_check = tocall <= 1e-9; fam = family(hist, actor)\n        row = {\n'''
new = '''        actor_paid = pf_paid[a["player"]]; tocall = max(0, pf_price - actor_paid); free_check = tocall <= 1e-9; fam = family(hist, actor)\n        pot_before_bb = max(0, (a["pot_after"] - a["raw"]) / bb)\n        contribution_by_pos = {}\n        for name in inhand | allin:\n            if name in by:\n                contribution_by_pos[norm_pos(by[name]["pos"], n)] = pf_paid[name]\n        preflop_context = build_context(\n            table_size=n, actor_position=actor, live_positions=live, all_in_positions=ais,\n            history=hist, raise_level=rl, contribution_bb_by_position=contribution_by_pos,\n            stack_bb_by_position=stack_by_pos, pot_before_bb=pot_before_bb,\n            current_price_bb=pf_price, min_raise_to_bb=pf_price + last_full_raise_increment,\n        )\n        target_total_bb = actor_paid + a["raw"] / bb if act in ("RAISE", "JAM") else None\n        row = {\n'''
replace_once(p, old, new)
replace_once(
    p,
    '''            "pot_before_bb": max(0, (a["pot_after"] - a["raw"]) / bb), "to_call_bb": tocall, "current_price_bb": pf_price,\n            "action_add_bb": a["raw"] / bb, "actor_start_stack_bb": by[a["player"]]["chips"] / bb,\n''',
    '''            "pot_before_bb": pot_before_bb, "to_call_bb": tocall, "current_price_bb": pf_price,\n            "action_add_bb": a["raw"] / bb, "actor_start_stack_bb": by[a["player"]]["chips"] / bb,\n            "preflop_context_v1": preflop_context,\n            "action_sizing_v1": {"incremental_cost_bb": a["raw"] / bb, "target_total_bb": target_total_bb},\n''',
)
replace_once(
    p,
    '''        else:\n            if a["type"] in ("call", "raise", "bet"): pf_paid[a["player"]] += a["raw"] / bb; pf_price = max(pf_price, pf_paid[a["player"]])\n            hist.append({"position": actor, "action": act})\n            if act in ("RAISE", "JAM"): rl += 1\n            if a["allin"]: allin.add(a["player"])\n''',
    '''        else:\n            old_price = pf_price\n            if a["type"] in ("call", "raise", "bet"):\n                pf_paid[a["player"]] += a["raw"] / bb\n                pf_price = max(pf_price, pf_paid[a["player"]])\n            hist.append({"position": actor, "action": act})\n            if act in ("RAISE", "JAM"):\n                raise_increment = max(0.0, pf_price - old_price)\n                if raise_increment + 1e-9 >= last_full_raise_increment:\n                    last_full_raise_increment = raise_increment\n                rl += 1\n            if a["allin"]: allin.add(a["player"])\n''',
)

# ---------------------------------------------------------------------------
# Browser runtime: load contract before inline analyser and attach it to every
# preflop decision while preserving incumbent fields used by v5 matching.
# ---------------------------------------------------------------------------
p = ROOT / "site/index.html"
replace_once(p, "\n<script>\n", "\n<script src=\"./preflop-contract.js\"></script>\n<script>\n")
replace_once(
    p,
    '''function normalizePopulationPosition(pos,tableSize){\n  const p=pos==="UTG"?"LJ":String(pos||"");\n  return tableSize===2&&p==="BTN" ? "SB_BTN" : p;\n}\n''',
    '''function normalizePopulationPosition(pos,tableSize){\n  return window.PokerPreflopContract.normalizePosition(pos,tableSize);\n}\n''',
)
# Keep the public helper name but make the common contract authoritative.
pattern = re.compile(r'''function populationFamilyFromHistory\(history,actorPos\)\{.*?\n\}\nfunction replayPreflopDecisionCount''', re.S)
text = p.read_text(encoding="utf-8")
replacement = '''function populationFamilyFromHistory(history,actorPos){\n  return window.PokerPreflopContract.familyFromHistory(history,actorPos);\n}\nfunction replayPreflopDecisionCount'''
text, count = pattern.subn(replacement, text, count=1)
if count != 1:
    raise RuntimeError(f"populationFamilyFromHistory replacement count={count}")
p.write_text(text, encoding="utf-8")

pattern = re.compile(r'''function populationPreflopDecisionTrace\(hand=state\.selectedHand\)\{.*?\n\}\nfunction sameStringArray''', re.S)
text = p.read_text(encoding="utf-8")
new_trace = r'''function populationPreflopDecisionTrace(hand=state.selectedHand){
  if(!hand) return [];
  const preflop=(hand.timeline||[]).find(s=>s.key==="preflop");
  if(!preflop) return [];
  const cacheKey=`${String(hand.id||"")}:${(preflop.actions||[]).length}:pfc1`;
  if(cacheKey&&state.populationTraceCache[cacheKey]) return state.populationTraceCache[cacheKey];

  const contract=window.PokerPreflopContract;
  const tableSize=(hand.players||[]).length;
  const playerByName=new Map((hand.players||[]).map(p=>[p.name,p]));
  const inHand=new Set((hand.players||[]).map(p=>p.name));
  const allIn=new Set();
  const history=[];
  const paidByName=Object.create(null);
  for(const p of (hand.players||[]))paidByName[p.name]=0;
  let currentPriceBB=0,lastFullRaiseIncrementBB=1,raiseLevel=0;
  const out=[];

  for(const a of (preflop.actions||[])){
    const amountBB=Number.isFinite(a.rawAmount)&&Number.isFinite(hand.bigBlind)&&hand.bigBlind>0?a.rawAmount/hand.bigBlind:0;
    if(a.type==="post"){
      if(!/ante/i.test(String(a.text||""))){
        paidByName[a.player]=(paidByName[a.player]||0)+amountBB;
        currentPriceBB=Math.max(currentPriceBB,paidByName[a.player]);
      }
      if(a.allIn) allIn.add(a.player);
      continue;
    }
    if(!["fold","check","call","raise","bet"].includes(a.type)) continue;
    const player=playerByName.get(a.player);
    if(!player) continue;
    const actorPos=normalizePopulationPosition(player.hhPosition,tableSize);
    let action="";
    if(a.type==="fold") action="FOLD";
    else if(a.type==="check") action="CHECK";
    else if(a.type==="call") action=raiseLevel===0?"LIMP":"CALL";
    else if(a.type==="raise"||a.type==="bet") action=a.allIn?"JAM":"RAISE";

    const livePositions=contract.sortPositions([...inHand].filter(name=>!allIn.has(name)).map(name=>normalizePopulationPosition(playerByName.get(name)?.hhPosition,tableSize)).filter(Boolean),tableSize);
    const allInPositions=contract.sortPositions([...allIn].map(name=>normalizePopulationPosition(playerByName.get(name)?.hhPosition,tableSize)).filter(Boolean),tableSize);
    const potAfterBB=Number(a.potAfterBB);
    const potBeforeBB=Number.isFinite(potAfterBB)?Math.max(0,potAfterBB-(a.changesPot?amountBB:0)):0;
    const contributionByPos=Object.create(null),stackByPos=Object.create(null);
    for(const p of (hand.players||[])){
      const pos=normalizePopulationPosition(p.hhPosition,tableSize);
      if(!pos)continue;
      stackByPos[pos]=historyPlayerStackBB(hand,p.name);
      if(inHand.has(p.name)||allIn.has(p.name))contributionByPos[pos]=Number(paidByName[p.name])||0;
    }
    const ctx=contract.buildContext({
      table_size:tableSize,actor_position:actorPos,live_positions:livePositions,all_in_positions:allInPositions,
      history,raise_level:raiseLevel,contribution_bb_by_position:contributionByPos,stack_bb_by_position:stackByPos,
      pot_before_bb:potBeforeBB,current_price_bb:currentPriceBB,min_raise_to_bb:currentPriceBB+lastFullRaiseIncrementBB
    });
    const actorStackBB=historyPlayerStackBB(hand,a.player);
    const targetTotalBB=["RAISE","JAM"].includes(action)?ctx.actor_contribution_bb+amountBB:null;
    out.push({
      ordinal:out.length,player:a.player,actor_position:ctx.actor_position,table_size:ctx.table_size,
      history:ctx.history.map(x=>({...x})),live_positions:ctx.live_positions,all_in_positions:ctx.all_in_positions,
      raise_level:ctx.raise_level,family:ctx.family,free_check:ctx.free_check,to_call_bb:ctx.to_call_bb,
      current_price_bb:ctx.current_price_bb,legal_actions:[...ctx.legal_actions],remaining_to_act_positions:[...ctx.remaining_to_act_positions],
      action,pot_before_bb:potBeforeBB,action_add_bb:amountBB,actor_start_stack_bb:actorStackBB,
      preflop_context_v1:ctx,
      action_sizing_v1:{incremental_cost_bb:amountBB,target_total_bb:targetTotalBB}
    });

    if(action==="FOLD"){
      inHand.delete(a.player);allIn.delete(a.player);
    }else{
      const oldPrice=currentPriceBB;
      if(["LIMP","CALL","RAISE","JAM"].includes(action)){
        paidByName[a.player]=(paidByName[a.player]||0)+amountBB;
        currentPriceBB=Math.max(currentPriceBB,paidByName[a.player]);
      }
      history.push({position:actorPos,action});
      if(action==="RAISE"||action==="JAM"){
        const increment=Math.max(0,currentPriceBB-oldPrice);
        if(increment+1e-9>=lastFullRaiseIncrementBB)lastFullRaiseIncrementBB=increment;
        raiseLevel++;
      }
      if(a.allIn) allIn.add(a.player);
    }
  }
  if(cacheKey) state.populationTraceCache[cacheKey]=out;
  return out;
}
function sameStringArray'''
text, count = pattern.subn(new_trace, text, count=1)
if count != 1:
    raise RuntimeError(f"populationPreflopDecisionTrace replacement count={count}")
p.write_text(text, encoding="utf-8")

# ---------------------------------------------------------------------------
# Release identity must cover the newly functional browser contract file.
# ---------------------------------------------------------------------------
p = ROOT / "tools/write_site_release.py"
replace_once(
    p,
    '''FUNCTIONAL_FILES = (\n    ROOT / "site" / "index.html",\n    ROOT / "site" / "trainer.js",\n    ROOT / "site" / "trainer.css",\n)''',
    '''FUNCTIONAL_FILES = (\n    ROOT / "site" / "index.html",\n    ROOT / "site" / "preflop-contract.js",\n    ROOT / "site" / "trainer.js",\n    ROOT / "site" / "trainer.css",\n)''',
)
replace_once(
    p,
    "The application identity covers site/index.html, site/trainer.js, site/trainer.css\nand the complete site/assets tree.",
    "The application identity covers site/index.html, site/preflop-contract.js,\nsite/trainer.js, site/trainer.css and the complete site/assets tree.",
)

# Remove the one-shot migration machinery before the durable commit.
for rel in ("tools/tmp_issue96_apply.py", ".github/workflows/issue96-apply.yml"):
    target = ROOT / rel
    if target.exists():
        target.unlink()

print("issue #96 integration patch applied")

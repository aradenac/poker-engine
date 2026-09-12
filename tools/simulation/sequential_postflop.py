#!/usr/bin/env python3
"""Repo-native deterministic sequential postflop strategy arena.

Hero decisions are queried from an analyser HTML build (model A lives inside that
analyser plus its loaded population JSON). Opponent actions, ranges and sizings
come only from promoted independent Model B JSON. Scenario cards/profile/runout
are materialized before any policy is evaluated so paired engine/policy comparisons
share the same environment until their trajectories diverge.
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import hashlib
import json
import math
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.simulation.model_b_runtime import (  # noqa: E402
    ModelBEnvironment,
    best,
    hseed,
    rake_net,
    sha256_file,
)
from tools.simulation.scenarios import build_scenario_manifest  # noqa: E402

try:
    from playwright.async_api import async_playwright
except ImportError:  # pragma: no cover - exercised only when running browser arena
    async_playwright = None


SCHEMA = "sequential-independent-arena/v2"


def preflop_prefix(raw: str) -> str:
    markers = ("*** FLOP ***",)
    positions = [raw.find(marker) for marker in markers if raw.find(marker) >= 0]
    return raw[: min(positions)].rstrip() if positions else raw.rstrip()


def action_line(player: str, kind: str, cost_bb: float, street_paid: float, max_paid: float, remaining: float, bb_chips: float) -> str:
    chips = lambda value: str(int(round(value * bb_chips)))
    allin = cost_bb >= remaining - 1e-6 and cost_bb > 0
    suffix = " and is all-in" if allin else ""
    if kind == "CHECK":
        return f"{player}: checks"
    if kind == "FOLD":
        return f"{player}: folds"
    if kind == "CALL":
        return f"{player}: calls {chips(cost_bb)}{suffix}"
    target = street_paid + cost_bb
    if max_paid <= street_paid + 1e-9:
        return f"{player}: bets {chips(cost_bb)}{suffix}"
    raise_inc = max(0.0, target - max_paid)
    return f"{player}: raises {chips(raise_inc)} to {chips(target)}{suffix}"


def finite_value(alt: dict) -> float | None:
    for key in ("policyAdjustedEVBB", "evBB"):
        value = alt.get(key)
        if value is not None:
            try:
                x = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(x):
                return x
    return None


def choose_variant(detail: dict, policy: str, pot_bb: float) -> dict:
    alternatives = [x for x in detail.get("alternatives", []) if finite_value(x) is not None]
    if not alternatives:
        raise RuntimeError("analyser returned no finite alternatives")
    by_label = {x.get("label"): x for x in alternatives}
    current = by_label.get(detail.get("bestLabel"))
    if current is None:
        current = max(alternatives, key=lambda x: finite_value(x) or -1e99)

    def value(x: dict) -> float:
        return float(finite_value(x) if finite_value(x) is not None else -1e99)

    nonjam = [x for x in alternatives if "jam" not in str(x.get("label", "")).lower()]
    best_nonjam = max(nonjam, key=value) if nonjam else current

    if policy == "current":
        return current
    if policy == "no_jam":
        return best_nonjam if "jam" in str(current.get("label", "")).lower() else current
    if policy.startswith("jam_margin_") and "jam" in str(current.get("label", "")).lower():
        threshold = float(policy.rsplit("_", 1)[-1])
        return current if value(current) - value(best_nonjam) >= threshold else best_nonjam
    if policy.startswith("weakjam_") and "jam" in str(current.get("label", "")).lower():
        try:
            threshold = float(policy.rsplit("_", 1)[-1])
        except ValueError:
            threshold = 10.0
        obs = current.get("responseObservationFloor")
        ratio = float(current.get("costBB") or 0.0) / max(pot_bb, 0.01)
        if ratio > 3 and obs is not None and float(obs) < threshold:
            return best_nonjam
        return current
    if policy.startswith("cap_"):
        cap = float(policy.rsplit("_", 1)[-1])
        current_aggr = current.get("kind") == "aggression"
        current_cost = current.get("costBB")
        current_ratio = float(current_cost) / max(pot_bb, 0.01) if current_aggr and current_cost is not None else 0.0
        if not current_aggr or current_ratio <= cap:
            return current
        allowed = [
            x
            for x in alternatives
            if x.get("kind") != "aggression"
            or x.get("costBB") is None
            or float(x["costBB"]) / max(pot_bb, 0.01) <= cap
        ]
        return max(allowed, key=value) if allowed else current
    raise ValueError(f"unknown policy {policy!r}")


class AnalyzerOracle:
    def __init__(
        self,
        *,
        engine_html: Path,
        preflop_model: Path,
        postflop_model: Path,
        trials: int,
        chromium_executable: str | None = None,
    ) -> None:
        self.engine_html = Path(engine_html)
        self.preflop_model = Path(preflop_model)
        self.postflop_model = Path(postflop_model)
        self.trials = int(trials)
        self.chromium_executable = chromium_executable
        self.pw = None
        self.browser = None
        self.page = None
        self.cache: dict[str, dict] = {}

    async def start(self) -> None:
        if async_playwright is None:
            raise RuntimeError("playwright is required to run the analyser oracle")
        self.pw = await async_playwright().start()
        launch_kwargs = {"headless": True, "args": ["--no-sandbox", "--disable-dev-shm-usage"]}
        if self.chromium_executable:
            launch_kwargs["executable_path"] = self.chromium_executable
        self.browser = await self.pw.chromium.launch(**launch_kwargs)
        self.page = await self.browser.new_page()
        html = self.engine_html.read_text(encoding="utf-8")
        if self.trials != 2500:
            html = html.replace("snap.trials=2500", f"snap.trials={self.trials}")
        await self.page.set_content(html, wait_until="domcontentloaded", timeout=30000)
        await self.page.set_input_files("#populationModelInput", str(self.preflop_model))
        await self.page.wait_for_function("state.populationModel&&state.populationModel.nodes.length>0", timeout=30000)
        await self.page.set_input_files("#postflopModelInput", str(self.postflop_model))
        await self.page.wait_for_function("state.postflopModel&&state.postflopModel.nodes.length>0", timeout=30000)
        await self.page.evaluate("scheduleBackgroundReviewScoring=()=>{};")

    async def close(self) -> None:
        if self.browser:
            await self.browser.close()
        if self.pw:
            await self.pw.stop()

    async def decide(self, hand_history: str) -> dict:
        key = hashlib.sha256(hand_history.encode("utf-8")).hexdigest()
        if key in self.cache:
            return self.cache[key]
        synthetic_id = str(800000000000000000 + (int(key[:15], 16) % 100000000000000000))
        hh_state = re.sub(
            r"(PokerStars(?: Zoom)? Hand #)\d+",
            lambda m: m.group(1) + synthetic_id,
            hand_history,
            count=1,
        )
        info = await self.page.evaluate(
            """(txt)=>{
              state.populationTraceCache=Object.create(null);state.populationRangeCache=Object.create(null);
              state.postflopTraceCache=Object.create(null);state.postflopRangeCache=Object.create(null);
              state.actionEquityCache=Object.create(null);state.seatEquityCache=Object.create(null);
              state.replaySteps=[];state.replayIndex=0;state.reviewScores=Object.create(null);
              const h=parsePokerStarsHand(txt,'sim');state.hhHands=[h];state.selectedHand=h;
              const p=buildReviewBatchPlan(h);p.actions=p.actions.filter(a=>a.actor===h.heroName).slice(-1);
              window.__p=p;state.reviewBatchBusy=false;runReviewBatchPlan(p);
              return {id:String(h.id),n:p.actions.length};
            }""",
            hh_state,
        )
        if not info["n"]:
            raise RuntimeError("analyser found no Hero decision in synthetic state")
        await self.page.wait_for_function(
            "!state.reviewBatchBusy && state.reviewScores && Object.keys(state.reviewScores).length>0",
            timeout=30000,
        )
        detail = await self.page.evaluate(
            """()=>{
              const result=state.reviewScores[Object.keys(state.reviewScores)[0]];
              const detail=result?.details?.[result.details.length-1];
              const a=window.__p?.actions?.[0];
              if(!detail||!a)return detail;
              const priorEq=a.values?.[a.sources?.prior],req=a.req,kind=a.actionType;
              if(!['Flop','Turn','River'].includes(a.street)||!Number.isFinite(priorEq)||!req)return detail;
              const alts=[];
              let chosenEV=NaN,chosenSE=0,chosenLabel=String(kind||'').toUpperCase();
              const callEV=()=>{
                const cost=Math.max(0,Number(a.toCallBB)||0);
                if(!(cost>0))return NaN;
                return priorEq*actionRakeInfo(a.hand,(Number(req.potBefore)||0)+cost).netPotBB-cost;
              };
              const checkEV=()=>priorEq*actionRakeInfo(a.hand,Number(req.potBefore)||0).netPotBB;
              if(kind==='fold'){
                chosenEV=0;chosenLabel='FOLD';
                const v=callEV();if(Number.isFinite(v))alts.push({label:'CALL',evBB:v,seBB:0,kind:'call'});
              }else if(kind==='check'){
                chosenEV=checkEV();chosenLabel='CHECK';
              }else if(kind==='call'){
                chosenEV=priorEq*req.netPotAfter-req.cost;chosenLabel='CALL';
                alts.push({label:'FOLD',evBB:0,seBB:0,kind:'fold'});
              }else if(kind==='bet'){
                chosenEV=Number(a.treeValues?.prior?.evBB);chosenSE=Number(a.treeValues?.prior?.evStdErrBB)||0;chosenLabel='BET réel';
                const v=checkEV();if(Number.isFinite(v))alts.push({label:'CHECK',evBB:v,seBB:0,kind:'check'});
              }else if(kind==='raise'){
                chosenEV=Number(a.treeValues?.prior?.evBB);chosenSE=Number(a.treeValues?.prior?.evStdErrBB)||0;chosenLabel='RAISE réel';
                alts.push({label:'FOLD',evBB:0,seBB:0,kind:'fold'});
                const v=callEV();if(Number.isFinite(v))alts.push({label:'CALL',evBB:v,seBB:0,kind:'call'});
              }else{
                return detail;
              }
              annotatePostflopSizingSanity(a.sizingResults||[]);
              for(const c of a.sizingResults||[]){
                if(!c.tree||!Number.isFinite(c.tree.evBB)||c.kind==='actual'||c.tree.sanityInvalid)continue;
                alts.push({
                  label:c.label,
                  evBB:Number(c.tree.evBB),
                  seBB:Number(c.tree.evStdErrBB)||0,
                  kind:'aggression',
                  costBB:Number(c.costBB),
                  responseObservationFloor:c.tree.responseObservationFloor??null,
                  responseConfidence:c.tree.responseConfidence??null,
                  responseConfidenceLabel:c.tree.responseConfidenceLabel??null,
                  responseSource:c.tree.responseSource??null,
                  responseFallbackPath:Array.isArray(c.tree.responseFallbackPath)?[...c.tree.responseFallbackPath]:[],
                  continueRangeQuality:c.tree.continueRangeQuality??null,
                  pAllFold:Number.isFinite(c.tree.pAllFold)?Number(c.tree.pAllFold):null,
                  terminalFoldContributionBB:Number.isFinite(c.tree.terminalFoldContributionBB)?Number(c.tree.terminalFoldContributionBB):null,
                  branchProbabilityMass:Number.isFinite(c.tree.branchProbabilityMass)?Number(c.tree.branchProbabilityMass):null
                });
              }
              if(!Number.isFinite(chosenEV)||!alts.length)return detail;
              alts.push({label:chosenLabel,evBB:chosenEV,seBB:chosenSE,kind:'chosen',chosen:true});
              annotatePostflopPolicyAlternatives(a.street,alts,Number(req.potBefore)||0);
              const rawBest=alts.slice().sort((x,y)=>Number(y.evBB)-Number(x.evBB))[0];
              const best=alts.slice().sort((x,y)=>finalDecisionEV(y)-finalDecisionEV(x))[0]||rawBest;
              return {
                ...detail,
                alternatives:alts,
                reconstructedBestLabel:best?.label??null,
                reconstructedBestEV:best?finalDecisionEV(best):null
              };
            }"""
        )
        if detail is None:
            raise RuntimeError("analyser returned no review detail")
        reconstructed = detail.get("reconstructedBestLabel")
        if reconstructed and detail.get("bestLabel") and reconstructed != detail.get("bestLabel"):
            raise RuntimeError(
                f"v83 recommendation mismatch: detail={detail.get('bestLabel')!r} reconstructed={reconstructed!r}"
            )
        self.cache[key] = detail
        return detail


async def rollout(scenario: dict, policy: str, oracle: AnalyzerOracle, env: ModelBEnvironment) -> dict:
    hero = scenario["hero"]
    opponent = scenario["opponent"]
    profile = int(scenario["profile"])
    hero_cards = list(scenario["hero_cards"])
    opponent_cards = list(scenario["opponent_cards"])
    flop = list(scenario["flop"])
    runout = list(scenario["runout"])
    order = list(scenario["postflop_order"])
    stacks = dict(scenario["stacks_bb"])
    total = dict(scenario["preflop_contributions_bb"])
    pot = float(scenario["flop_pot_bb"])
    bb_chips = float(scenario["big_blind_chips"])
    post_invested = 0.0
    hero_actions: list[dict] = []
    history_lines = [f"*** FLOP *** [{' '.join(flop)}]"]
    street_cards = {"flop": flop, "turn": flop + [runout[0]], "river": flop + runout}
    hero_decision_no = 0
    opponent_action_no = 0

    for street in ("flop", "turn", "river"):
        board = street_cards[street]
        if street == "turn":
            history_lines.append(f"*** TURN *** [{' '.join(board[:3])}] [{board[3]}]")
        elif street == "river":
            history_lines.append(f"*** RIVER *** [{' '.join(board[:4])}] [{board[4]}]")

        street_paid = {hero: 0.0, opponent: 0.0}
        last_raise_inc = 1.0
        pending = list(order)

        while pending:
            actor = pending.pop(0)
            other = opponent if actor == hero else hero
            max_paid = max(street_paid.values())
            to_call = max(0.0, max_paid - street_paid[actor])
            remaining = max(0.0, stacks[actor] - total[actor])
            if remaining <= 1e-9:
                continue

            if actor == hero:
                placeholder = "FOLD" if to_call > 1e-9 else "CHECK"
                placeholder_line = action_line(hero, placeholder, 0.0, street_paid[hero], max_paid, remaining, bb_chips)
                synthetic = preflop_prefix(scenario["raw_hand"]) + "\n" + "\n".join(history_lines + [placeholder_line]) + "\n"
                detail = await oracle.decide(synthetic)
                alt = choose_variant(detail, policy, pot)
                label = str(alt["label"])
                hero_decision_no += 1
                ev_final = finite_value(alt)
                hero_actions.append({
                    "street": street,
                    "label": label,
                    "pot_bb": pot,
                    "to_call_bb": to_call,
                    "ev_final_bb": ev_final,
                    "ev_model_bb": alt.get("evBB"),
                    "cost_bb": alt.get("costBB"),
                    "size_ratio": (float(alt.get("costBB")) / max(pot, 0.01)) if alt.get("costBB") is not None else None,
                    "response_observation_floor": alt.get("responseObservationFloor"),
                    "continue_range_quality": alt.get("continueRangeQuality"),
                    "p_all_fold": alt.get("pAllFold"),
                })
                if label == "FOLD":
                    kind, cost = "FOLD", 0.0
                elif label == "CHECK":
                    kind, cost = "CHECK", 0.0
                elif label == "CALL":
                    kind, cost = "CALL", min(to_call, remaining)
                else:
                    kind = "AGG"
                    proposed = alt.get("costBB")
                    cost = min(float(proposed) if proposed is not None else remaining, remaining)
            else:
                mode = "FACING" if to_call > 1e-9 else "FREE"
                relative = "OOP" if actor == order[0] else "IP"
                can_raise = remaining > to_call + last_raise_inc + 1e-9
                action = env.sample_action(
                    seed_parts=(scenario["environment_seed"], street, opponent_action_no, "action"),
                    profile=profile,
                    street=street,
                    mode=mode,
                    relative_position=relative,
                    pot_type=scenario["pot_type"],
                    preflop_role=scenario["preflop_roles"][opponent],
                    can_raise=can_raise,
                )
                opponent_action_no += 1
                if action == "FOLD":
                    kind, cost = "FOLD", 0.0
                elif action == "CHECK":
                    kind, cost = "CHECK", 0.0
                elif action == "CALL":
                    kind, cost = "CALL", min(to_call, remaining)
                else:
                    kind = "AGG"
                    sizing_action = "RAISE" if mode == "FACING" else "BET"
                    ratio = env.sample_sizing(
                        seed_parts=(scenario["environment_seed"], street, opponent_action_no, "size"),
                        profile=profile,
                        street=street,
                        mode=mode,
                        action=sizing_action,
                        pot_type=scenario["pot_type"],
                    )
                    desired = max(0.005, ratio * pot)
                    if to_call <= 1e-9:
                        cost = min(remaining, desired)
                    else:
                        min_target = max_paid + last_raise_inc
                        min_cost = max(0.0, min_target - street_paid[actor])
                        cost = min(remaining, max(desired, min_cost))
                        if cost <= to_call + 1e-9:
                            kind, cost = "CALL", min(to_call, remaining)

            if kind == "FOLD":
                history_lines.append(action_line(actor, "FOLD", 0.0, street_paid[actor], max_paid, remaining, bb_chips))
                if actor == hero:
                    return {
                        "scenario_id": scenario["scenario_id"],
                        "policy": policy,
                        "utility_bb": -post_invested,
                        "hero_decisions": hero_decision_no,
                        "terminal": "hero_fold",
                        "hero_actions": hero_actions,
                    }
                uncalled = max(0.0, street_paid[hero] - street_paid[opponent])
                final_pot = max(0.0, pot - uncalled)
                effective_invested = max(0.0, post_invested - uncalled)
                return {
                    "scenario_id": scenario["scenario_id"],
                    "policy": policy,
                    "utility_bb": rake_net(final_pot) - effective_invested,
                    "hero_decisions": hero_decision_no,
                    "terminal": "opponent_fold",
                    "uncalled_return_bb": uncalled,
                    "hero_actions": hero_actions,
                }

            if kind == "CHECK":
                history_lines.append(action_line(actor, "CHECK", 0.0, street_paid[actor], max_paid, remaining, bb_chips))
                continue

            if kind == "CALL":
                history_lines.append(action_line(actor, "CALL", cost, street_paid[actor], max_paid, remaining, bb_chips))
                street_paid[actor] += cost
                total[actor] += cost
                pot += cost
                if actor == hero:
                    post_invested += cost
                pending = []
            else:
                old_max = max_paid
                history_lines.append(action_line(actor, "AGG", cost, street_paid[actor], max_paid, remaining, bb_chips))
                street_paid[actor] += cost
                total[actor] += cost
                pot += cost
                if actor == hero:
                    post_invested += cost
                new_max = max(street_paid.values())
                last_raise_inc = max(0.005, new_max - old_max)
                pending = [other]

            if total[hero] >= stacks[hero] - 1e-9 or total[opponent] >= stacks[opponent] - 1e-9:
                if pending:
                    continue
                if total[hero] > total[opponent]:
                    returned = total[hero] - total[opponent]
                    total[hero] -= returned
                    pot -= returned
                    post_invested = max(0.0, post_invested - returned)
                elif total[opponent] > total[hero]:
                    returned = total[opponent] - total[hero]
                    total[opponent] -= returned
                    pot -= returned
                final_board = street_cards["river"]
                hero_score = best(hero_cards + final_board)
                opp_score = best(opponent_cards + final_board)
                net = rake_net(pot)
                share = net if hero_score > opp_score else net / 2.0 if hero_score == opp_score else 0.0
                return {
                    "scenario_id": scenario["scenario_id"],
                    "policy": policy,
                    "utility_bb": share - post_invested,
                    "hero_decisions": hero_decision_no,
                    "terminal": "allin_showdown",
                    "hero_actions": hero_actions,
                }

        if street == "river":
            hero_score = best(hero_cards + board)
            opp_score = best(opponent_cards + board)
            net = rake_net(pot)
            share = net if hero_score > opp_score else net / 2.0 if hero_score == opp_score else 0.0
            return {
                "scenario_id": scenario["scenario_id"],
                "policy": policy,
                "utility_bb": share - post_invested,
                "hero_decisions": hero_decision_no,
                "terminal": "showdown",
                "hero_actions": hero_actions,
            }

    raise RuntimeError("rollout reached no terminal state")


def quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    if len(values) == 1:
        return values[0]
    pos = q * (len(values) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return values[lo]
    frac = pos - lo
    return values[lo] * (1.0 - frac) + values[hi] * frac


def summarize(results: list[dict]) -> dict:
    by_policy: dict[str, list[dict]] = collections.defaultdict(list)
    for row in results:
        by_policy[row["policy"]].append(row)
    out = {}
    for policy, rows in sorted(by_policy.items()):
        utilities = [float(x["utility_bb"]) for x in rows]
        actions = collections.Counter()
        size_ratios: list[float] = []
        terminals = collections.Counter(x["terminal"] for x in rows)
        decisions = 0
        for row in rows:
            decisions += int(row["hero_decisions"])
            for action in row.get("hero_actions", []):
                actions[str(action["label"])] += 1
                if action.get("size_ratio") is not None:
                    size_ratios.append(float(action["size_ratio"]))
        out[policy] = {
            "rollouts": len(rows),
            "mean_utility_bb": statistics.fmean(utilities) if utilities else None,
            "median_utility_bb": statistics.median(utilities) if utilities else None,
            "p10_utility_bb": quantile(utilities, 0.10),
            "p90_utility_bb": quantile(utilities, 0.90),
            "hero_decisions": decisions,
            "mean_decisions_per_rollout": decisions / len(rows) if rows else None,
            "terminal_counts": dict(sorted(terminals.items())),
            "hero_action_counts": dict(sorted(actions.items())),
            "hero_size_ratio": {
                "n": len(size_ratios),
                "p50": quantile(size_ratios, 0.50),
                "p90": quantile(size_ratios, 0.90),
                "p99": quantile(size_ratios, 0.99),
            },
        }
    return out


def default_paths(root: Path) -> dict[str, Path]:
    registry = json.loads((root / "training/registry.json").read_text(encoding="utf-8"))
    return {
        "engine": root / "site/index.html",
        "preflop": root / registry["promoted_model"]["preflop"],
        "postflop": root / registry["promoted_model"]["postflop"],
    }


def load_or_build_manifest(args, env: ModelBEnvironment) -> dict:
    if args.scenario_manifest:
        return json.loads(Path(args.scenario_manifest).read_text(encoding="utf-8"))
    return build_scenario_manifest(
        env=env,
        count=args.n,
        reps=args.reps,
        master_seed=args.seed,
        start=args.start,
        split=args.split,
        hero=args.hero,
        root=ROOT,
    )


async def run(args) -> dict:
    env = ModelBEnvironment.from_registry(ROOT)
    manifest = load_or_build_manifest(args, env)
    scenario_out = Path(args.scenario_out) if args.scenario_out else None
    if scenario_out:
        scenario_out.parent.mkdir(parents=True, exist_ok=True)
        scenario_out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.generate_only:
        return {
            "schema": SCHEMA,
            "mode": "scenario_generation_only",
            "scenario_manifest": manifest,
            "summary": {},
            "results": [],
        }

    defaults = default_paths(ROOT)
    engine = Path(args.engine or defaults["engine"])
    preflop = Path(args.preflop_model or defaults["preflop"])
    postflop = Path(args.postflop_model or defaults["postflop"])
    policies = [x.strip() for x in args.policies.split(",") if x.strip()]
    oracle = AnalyzerOracle(
        engine_html=engine,
        preflop_model=preflop,
        postflop_model=postflop,
        trials=args.trials,
        chromium_executable=args.chromium,
    )
    results: list[dict] = []
    await oracle.start()
    try:
        for index, scenario in enumerate(manifest["scenarios"], start=1):
            print(
                f"scenario {index}/{len(manifest['scenarios'])} {scenario['scenario_id']} hand={scenario['hand_id']} "
                f"profile={scenario['profile']} hero={scenario['hero_cards']} opp={scenario['opponent_cards']} "
                f"flop={scenario['flop']} runout={scenario['runout']}",
                flush=True,
            )
            for policy in policies:
                row = await rollout(scenario, policy, oracle, env)
                row.update({
                    "hand_id": scenario["hand_id"],
                    "rep": scenario["rep"],
                    "profile": scenario["profile"],
                    "hero_cards": scenario["hero_cards"],
                    "opponent_cards": scenario["opponent_cards"],
                    "flop": scenario["flop"],
                    "runout": scenario["runout"],
                })
                results.append(row)
                print(f"  {policy}: utility={row['utility_bb']:.3f} decisions={row['hero_decisions']} {row['terminal']}", flush=True)
    finally:
        await oracle.close()

    metadata = {
        "engine": {"path": engine.relative_to(ROOT).as_posix() if engine.is_relative_to(ROOT) else engine.as_posix(), "sha256": sha256_file(engine)},
        "model_a": {
            "preflop": {"path": preflop.relative_to(ROOT).as_posix() if preflop.is_relative_to(ROOT) else preflop.as_posix(), "sha256": sha256_file(preflop)},
            "postflop": {"path": postflop.relative_to(ROOT).as_posix() if postflop.is_relative_to(ROOT) else postflop.as_posix(), "sha256": sha256_file(postflop)},
        },
        "model_b": {"alias": env.alias, "artifact_sha256": env.artifact_fingerprints()},
        "scenario_fingerprint_sha256": manifest["scenario_fingerprint_sha256"],
        "scenario_split": manifest["split"],
        "master_seed": manifest["master_seed"],
        "trials": int(args.trials),
        "policies": policies,
    }
    return {
        "schema": SCHEMA,
        "metadata": metadata,
        "scenario_manifest": manifest,
        "summary": summarize(results),
        "results": results,
    }


def parse_args() -> argparse.Namespace:
    defaults = default_paths(ROOT)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=6, help="number of base hands")
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--reps", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20260912)
    parser.add_argument("--split", default="TEST", choices=("TRAIN", "VALIDATION", "TEST"))
    parser.add_argument("--hero", default="RoiDePiqueNique")
    parser.add_argument("--trials", type=int, default=1000)
    parser.add_argument("--policies", default="current,no_jam,cap_2,cap_3,cap_4")
    parser.add_argument("--engine", default=defaults["engine"].as_posix())
    parser.add_argument("--preflop-model", default=defaults["preflop"].as_posix())
    parser.add_argument("--postflop-model", default=defaults["postflop"].as_posix())
    parser.add_argument("--chromium", default=None, help="optional Chromium executable path")
    parser.add_argument("--scenario-manifest", default="", help="reuse an existing scenario manifest verbatim")
    parser.add_argument("--scenario-out", default="", help="write generated scenario manifest")
    parser.add_argument("--generate-only", action="store_true", help="materialize scenarios without starting the analyser")
    parser.add_argument("--out", default="artifacts/sequential_arena_v2.json")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    document = await run(args)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"DONE {out}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())

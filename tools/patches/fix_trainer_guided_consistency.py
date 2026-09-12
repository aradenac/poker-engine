#!/usr/bin/env python3
"""Fix Guided trainer recommendation/verdict consistency.

The recommendation shown before Hero acts is the canonical baseline.  A chosen
alternative may need its own EV evaluation, but that second Monte-Carlo run must
never replace the displayed guide's best action/sizing/EV.
"""
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
        '  pauseAfterDecision:false,busy:false,\n',
        '  pauseAfterDecision:false,busy:false,sizingTouched:false,\n',
        'trainer sizing dirty state',
    )

    old = '''function trainerRecommendationMatchesAction(rec,actual){
  if(!rec||rec.error||!actual)return false;
  const label=String(rec.bestLabel||"").toUpperCase(),kind=String(actual.kind||"").toUpperCase();
  if(!label.startsWith(kind))return false;
  if(!["BET","RAISE"].includes(kind))return true;
  const bestCost=Number(rec.bestCostBB),playedCost=Number(actual.cost);
  return Number.isFinite(bestCost)&&Number.isFinite(playedCost)&&Math.abs(bestCost-playedCost)<=0.05;
}
'''
    new = '''function trainerRecommendationKind(hand,rec){
  if(!hand||!rec||rec.error)return "";
  const label=String(rec.bestLabel||"").trim().toUpperCase();
  if(label.startsWith("FOLD"))return "FOLD";
  if(label.startsWith("CHECK"))return "CHECK";
  if(label.startsWith("CALL"))return "CALL";
  if(label.startsWith("BET"))return "BET";
  if(label.startsWith("RAISE"))return "RAISE";
  const cost=Number(rec.bestCostBB);
  if(Number.isFinite(cost)&&cost>1e-8)return trainerToCall(hand,hand.heroSeat)>1e-8?"RAISE":"BET";
  return "";
}
function trainerRecommendationMatchesAction(rec,actual,hand=trainerState.hand){
  if(!rec||rec.error||!actual||!hand)return false;
  const kind=String(actual.kind||"").toUpperCase(),recommended=trainerRecommendationKind(hand,rec);
  if(!recommended||recommended!==kind)return false;
  if(!["BET","RAISE"].includes(kind))return true;
  const bestCost=Number(rec.bestCostBB),playedCost=Number(actual.cost);
  return Number.isFinite(bestCost)&&Number.isFinite(playedCost)&&Math.abs(bestCost-playedCost)<=0.05;
}
function trainerGuideAnchoredDetail(guide,played){
  const d=JSON.parse(JSON.stringify(played||{})),bestEV=Number(guide?.bestEV),chosenEV=Number(d.chosenEV);
  d.bestLabel=guide?.bestLabel;d.bestCostBB=guide?.bestCostBB;d.bestEV=bestEV;
  const loss=Number.isFinite(bestEV)&&Number.isFinite(chosenEV)?Math.max(0,bestEV-chosenEV):Math.max(0,Number(d.lossBB)||0);
  d.lossBB=loss;d.withinNoise=loss<=0.15;return d;
}
function trainerGuidedClickCost(kind){
  const raw=trainerSizingValue(),rec=trainerState.recommendation,hand=trainerState.hand,k=String(kind||"").toUpperCase();
  if(trainerState.mode!=="guided"||trainerState.sizingTouched||!rec||rec.error||!["BET","RAISE"].includes(k))return raw;
  if(trainerRecommendationKind(hand,rec)!==k)return raw;
  const best=Number(rec.bestCostBB);return Number.isFinite(best)?best:raw;
}
'''
    text = replace_once(text, old, new, 'guided recommendation identity helpers')

    old = '''async function trainerHeroAction(kind,cost=0){
  const hand=trainerState.hand;if(!hand||hand.ended||!hand.awaitingHero||trainerState.busy||trainerState.pauseAfterDecision)return;
  trainerState.busy=true;hand.awaitingHero=false;trainerRenderStatus("Évaluation de votre décision…","busy");trainerRender();
  let detail=null,row=null,actual=null;
  try{
    actual=trainerActualLine(hand,kind,cost);
    if(trainerState.mode==="guided"&&trainerRecommendationMatchesAction(trainerState.recommendation,actual)){
      detail=trainerReuseBestAsPlayed(trainerState.recommendation);
    }else{
      detail=await trainerTimedReviewText(trainerBuildReviewHH(hand,actual.line,actual.kind,actual.cost));
    }
    trainerState.recommendation=detail;row=trainerRecordDecision(detail,actual.kind,actual.cost);
  }
'''
    new = '''async function trainerHeroAction(kind,cost=0){
  const hand=trainerState.hand;if(!hand||hand.ended||!hand.awaitingHero||trainerState.busy||trainerState.pauseAfterDecision)return;
  const guide=trainerState.mode==="guided"&&trainerState.recommendation&&!trainerState.recommendation.error?trainerState.recommendation:null;
  trainerState.busy=true;hand.awaitingHero=false;trainerRenderStatus("Évaluation de votre décision…","busy");trainerRender();
  let detail=null,row=null,actual=null;
  try{
    actual=trainerActualLine(hand,kind,cost);
    if(guide&&trainerRecommendationMatchesAction(guide,actual,hand)){
      detail=trainerReuseBestAsPlayed(guide);
    }else{
      const played=await trainerTimedReviewText(trainerBuildReviewHH(hand,actual.line,actual.kind,actual.cost));
      detail=guide?trainerGuideAnchoredDetail(guide,played):played;
    }
    trainerState.recommendation=guide||detail;row=trainerRecordDecision(detail,actual.kind,actual.cost);
  }
'''
    text = replace_once(text, old, new, 'guided hero verdict anchoring')

    text = replace_once(
        text,
        '      hand.awaitingHero=true;hand.decisionNo++;trainerState.feedback=null;trainerState.recommendation=null;\n',
        '      hand.awaitingHero=true;hand.decisionNo++;trainerState.feedback=null;trainerState.recommendation=null;trainerState.sizingTouched=false;\n',
        'reset guided sizing touch per decision',
    )

    old = '''function trainerBestText(rec){
  if(!rec||rec.error)return "—";const label=String(rec.bestLabel||"—"),cost=Number(rec.bestCostBB),size=Number.isFinite(cost)?` · ${trainerFmtBB(cost)}`:"";return `${label}${size}`;
}
'''
    new = '''function trainerBestText(rec){
  if(!rec||rec.error)return "—";
  const label=String(rec.bestLabel||"—"),kind=trainerRecommendationKind(trainerState.hand,rec),upper=label.toUpperCase();
  const action=kind&&!upper.startsWith(kind)?`${kind} · `:"",cost=Number(rec.bestCostBB),size=Number.isFinite(cost)?` · ${trainerFmtBB(cost)}`:"";
  return `${action}${label}${size}`;
}
'''
    text = replace_once(text, old, new, 'explicit guided action display')

    old = '''  trainerControls.querySelectorAll("[data-trainer-action]").forEach(b=>b.addEventListener("click",()=>trainerHeroAction(b.dataset.trainerAction,trainerSizingValue())));
  trainerControls.querySelectorAll("[data-size]").forEach(b=>b.addEventListener("click",()=>{const v=b.dataset.size==="allin"?h.stacks[h.heroSeat]:Math.max(toCall>0?toCall+h.lastRaise:1,Number(b.dataset.size)*h.pot);trainerSetSizing(v);}));
'''
    new = '''  const sizingInput=document.getElementById("trainerSizingInput");sizingInput?.addEventListener("input",()=>{trainerState.sizingTouched=true;});
  trainerControls.querySelectorAll("[data-trainer-action]").forEach(b=>b.addEventListener("click",()=>trainerHeroAction(b.dataset.trainerAction,trainerGuidedClickCost(b.dataset.trainerAction))));
  trainerControls.querySelectorAll("[data-size]").forEach(b=>b.addEventListener("click",()=>{trainerState.sizingTouched=true;const v=b.dataset.size==="allin"?h.stacks[h.heroSeat]:Math.max(toCall>0?toCall+h.lastRaise:1,Number(b.dataset.size)*h.pot);trainerSetSizing(v);}));
'''
    text = replace_once(text, old, new, 'guided exact sizing click')

    old = 'function trainerSetMode(mode){if(!["guided","training","test"].includes(mode))return;trainerState.mode=mode;trainerState.feedback=null;document.querySelectorAll("[data-trainer-mode]").forEach(b=>b.classList.toggle("active",b.dataset.trainerMode===mode));trainerRender();}\n'
    new = 'function trainerSetMode(mode){if(!["guided","training","test"].includes(mode))return;trainerState.mode=mode;trainerState.feedback=null;document.querySelectorAll("[data-trainer-mode]").forEach(b=>b.classList.toggle("active",b.dataset.trainerMode===mode));const needGuide=mode==="guided"&&trainerState.hand?.awaitingHero&&!trainerState.recommendation&&!trainerState.busy;trainerRender();if(needGuide)void trainerComputeRecommendation();}\n'
    text = replace_once(text, old, new, 'guided mode switch computes answer')

    TRAINER.write_text(text, encoding="utf-8")


def patch_smoke() -> None:
    text = SMOKE.read_text(encoding="utf-8")
    old = '''        # Mode switching is independent of the current hand.
        await page.click('[data-trainer-mode="guided"]')
        guided = await page.locator("#trainerRecommendation").inner_text()
        assert "action recommandée" in folded(guided), guided
        await page.click('[data-trainer-mode="training"]')

        # Choose a passive legal action first to keep the smoke deterministic enough.
        for action in ("CHECK", "CALL", "FOLD"):
            loc = page.locator(f'#trainerControls [data-trainer-action="{action}"]')
            if await loc.count():
                await loc.first.click()
                break
        else:
            raise AssertionError("no passive Hero action available")
'''
    new = '''        # Switching to Guided mid-decision must compute a real recommendation.
        await page.click('[data-trainer-mode="guided"]')
        await page.wait_for_function(
            "trainerState.recommendation && !trainerState.recommendation.error && trainerRecommendationKind(trainerState.hand, trainerState.recommendation)",
            timeout=90_000,
        )
        guided = await page.locator("#trainerRecommendation").inner_text()
        assert "action recommandée" in folded(guided) and "ev —" not in folded(guided), guided
        guide = await page.evaluate(
            "() => ({label: trainerState.recommendation.bestLabel, cost: Number(trainerState.recommendation.bestCostBB), ev: Number(trainerState.recommendation.bestEV), kind: trainerRecommendationKind(trainerState.hand, trainerState.recommendation)})"
        )
        assert guide["kind"] in {"FOLD", "CHECK", "CALL", "BET", "RAISE"}, guide
        action = page.locator(f'#trainerControls [data-trainer-action="{guide["kind"]}"]')
        assert await action.count(), f"guided action button missing: {guide}"
        await action.first.click()
'''
    text = replace_once(text, old, new, 'browser guided exact recommendation path')

    old = '''        feedback = await page.locator("#trainerFeedback").inner_text()
        assert "recommandé" in folded(feedback) and "perte ev" in folded(feedback), feedback
        stats = await page.locator("#trainerStats").inner_text()
'''
    new = '''        feedback = await page.locator("#trainerFeedback").inner_text()
        assert "recommandé" in folded(feedback) and "perte ev" in folded(feedback), feedback
        verdict = await page.evaluate(
            "() => ({label: trainerState.feedback?.detail?.bestLabel, cost: Number(trainerState.feedback?.detail?.bestCostBB), ev: Number(trainerState.feedback?.detail?.bestEV), chosen: Number(trainerState.feedback?.detail?.chosenEV), loss: Number(trainerState.feedback?.row?.lossBB), reused: Number(trainerState.perf.reused)})"
        )
        assert verdict["label"] == guide["label"], (guide, verdict)
        if guide["cost"] == guide["cost"]:
            assert abs(verdict["cost"] - guide["cost"]) <= 1e-9, (guide, verdict)
        assert abs(verdict["ev"] - guide["ev"]) <= 1e-9, (guide, verdict)
        assert verdict["loss"] <= 0.15, (guide, verdict, feedback)
        assert verdict["reused"] >= 1, (guide, verdict)
        stats = await page.locator("#trainerStats").inner_text()
'''
    text = replace_once(text, old, new, 'browser guided verdict identity assertions')

    old = '''            "guided": guided,
            "feedback": feedback,
            "stats": stats,
'''
    new = '''            "guided": guided,
            "guide_state": guide,
            "verdict_state": verdict,
            "feedback": feedback,
            "stats": stats,
'''
    text = replace_once(text, old, new, 'browser guided diagnostics')

    SMOKE.write_text(text, encoding="utf-8")


def main() -> None:
    patch_trainer()
    patch_smoke()
    print("guided trainer consistency patch applied")


if __name__ == "__main__":
    main()

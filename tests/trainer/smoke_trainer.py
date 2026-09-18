#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import sys
from playwright.async_api import async_playwright

URL = "http://127.0.0.1:8765/index.html"


def folded(text: str) -> str:
    return text.casefold()


async def main() -> None:
    page_errors: list[str] = []
    console_errors: list[str] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = await browser.new_page(viewport={"width": 1500, "height": 1000})
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        await page.goto(URL, wait_until="domcontentloaded", timeout=45_000)

        # Replayer hand-class helper runs in the real assembled browser application.
        hand_classes = await page.evaluate(
            "() => ({suited:replayHandClass(['As','Ks']), offsuit:replayHandClass(['Ah','Kd']), pair:replayHandClass(['7c','7d']), hidden:replayHandClass(null), backs:replayHandClass([null,null])})"
        )
        assert hand_classes == {"suited": "AKs", "offsuit": "AKo", "pair": "77", "hidden": "", "backs": ""}, hand_classes

        # UX categories may change with uncertainty, but must never mutate the EV values.
        quality_contract = await page.evaluate(
            """() => {
                const near={lossEVBB:0.4,effectiveLossEVBB:0.2,deltaEVBB:-0.4,withinNoise:true};
                const far={...near,withinNoise:false};
                const good={lossEVBB:0,effectiveLossEVBB:0,deltaEVBB:0,withinNoise:false};
                const before=JSON.stringify({near,far,good});
                const out={near:decisionQualityFromEV(near),far:decisionQualityFromEV(far),good:decisionQualityFromEV(good)};
                const after=JSON.stringify({near,far,good});
                return {out,before,after,near_loss:near.lossEVBB,far_loss:far.lossEVBB};
            }"""
        )
        assert quality_contract["out"]["near"]["label"] == "Proche", quality_contract
        assert quality_contract["out"]["far"]["label"] == "Erreur", quality_contract
        assert quality_contract["out"]["good"]["label"] == "Bonne", quality_contract
        assert quality_contract["near_loss"] == quality_contract["far_loss"] == 0.4, quality_contract
        assert quality_contract["before"] == quality_contract["after"], quality_contract

        # Revealed-card changes must never alter the historical a-priori recommendation.
        information_boundary = await page.evaluate(
            """() => {
                const saved={
                    actionEquityKey:window.actionEquityKey,
                    requiredEquityInfo:window.requiredEquityInfo,
                    actionVerdictSourceKeys:window.actionVerdictSourceKeys,
                    postflopDecisionAlternativeSummary:window.postflopDecisionAlternativeSummary,
                    cache:state.actionEquityCache
                };
                try{
                    window.actionEquityKey=()=>"__boundary__";
                    window.requiredEquityInfo=()=>({kind:"call",cost:2,potBefore:10,actorRequired:0.4});
                    window.actionVerdictSourceKeys=()=>({prior:"range_ranges",post:"range_real",actorKnown:true});
                    window.postflopDecisionAlternativeSummary=()=>{
                        const chosen={label:"CALL",evBB:0.5,policyAdjustedEVBB:0.5,seBB:0.02,chosen:true,costBB:2};
                        const best={label:"FOLD",evBB:0.8,policyAdjustedEVBB:0.8,seBB:0.02,chosen:false,costBB:0};
                        return {alternatives:[best,chosen],best,chosenPolicyEV:0.5,bestPolicyEV:0.8,effectiveGap:0.2,rawGap:0.3,withinNoise:false,score:4};
                    };
                    const step={street:"Flop",actionType:"call"};
                    const sources={prior:"range_ranges",post:"range_real",actorKnown:true};
                    const render=post=>{
                        const cached={status:"done",equities:{range_ranges:0.42,range_real:post}};
                        state.actionEquityCache={__boundary__:cached};
                        const summary=decisionCanonicalSummary(0,step,cached);
                        const retrospective=actionRetrospectivePanelHtml({
                            req:{kind:"call",actorRequired:0.4},
                            postMetrics:{evBB:post*10-2},
                            sources,postflopTree:false,postflopCheck:false,
                            postEq:post,postTree:null,eq:cached.equities,stepIndex:0
                        });
                        return {recommended:summary?.recommended?.label,delta:summary?.deltaEVBB,loss:summary?.lossEVBB,retrospective};
                    };
                    const low=render(0.10),high=render(0.90);
                    return {
                        low,high,
                        same_recommendation:low.recommended===high.recommended,
                        same_delta:low.delta===high.delta,
                        same_loss:low.loss===high.loss,
                        retrospective_changed:low.retrospective!==high.retrospective
                    };
                } finally {
                    window.actionEquityKey=saved.actionEquityKey;
                    window.requiredEquityInfo=saved.requiredEquityInfo;
                    window.actionVerdictSourceKeys=saved.actionVerdictSourceKeys;
                    window.postflopDecisionAlternativeSummary=saved.postflopDecisionAlternativeSummary;
                    state.actionEquityCache=saved.cache;
                }
            }"""
        )
        assert information_boundary["same_recommendation"], information_boundary
        assert information_boundary["same_delta"], information_boundary
        assert information_boundary["same_loss"], information_boundary
        assert information_boundary["retrospective_changed"], information_boundary
        assert information_boundary["low"]["recommended"] == "FOLD", information_boundary

        # HH import keeps the primary path compact while preserving advanced controls.
        hh_import_ux = await page.evaluate(
            """() => ({
                primary: document.querySelector('label[for="hhFileInput"]')?.textContent?.trim(),
                watch: document.querySelector('#hhWatchBtn')?.textContent?.trim(),
                advanced_open: !!document.querySelector('.hh-import-advanced')?.open,
                default_mode: state.hhImportMode,
                effect: document.querySelector('#hhImportEffect')?.textContent?.trim(),
                summary: hhImportSummaryText({
                    files:3, recognized:2, hands:47, errors:1, mode:"replace",
                    at:new Date(2000,0,1,12,34,0)
                })
            })"""
        )
        assert hh_import_ux["primary"] == "Importer mes mains", hh_import_ux
        assert hh_import_ux["watch"] == "Surveiller mes HH", hh_import_ux
        assert hh_import_ux["advanced_open"] is False, hh_import_ux
        assert hh_import_ux["default_mode"] == "replace", hh_import_ux
        assert "remplacera" in folded(hh_import_ux["effect"]), hh_import_ux
        assert "2/3 fichiers reconnus" in folded(hh_import_ux["summary"]), hh_import_ux
        assert "47 mains" in folded(hh_import_ux["summary"]), hh_import_ux
        assert "1 erreur de lecture/parsing" in folded(hh_import_ux["summary"]), hh_import_ux
        assert "mise à jour" in folded(hh_import_ux["summary"]), hh_import_ux
        assert not await page.locator("#hhBenchmarkExportBtn").is_visible()
        await page.click(".hh-import-advanced > summary")
        assert await page.locator("#hhBenchmarkExportBtn").is_visible()
        await page.click(".hh-import-advanced > summary")

        # Review is entered by explicit HH selection and leaving it restores Equity Lab
        # without clearing the selected hand or imported HH collection.
        review_context = await page.evaluate(
            """() => {
                const saved={
                    hhHands:state.hhHands, selectedHand:state.selectedHand, hhMode:state.hhMode,
                    appView:state.appView, replaySteps:state.replaySteps, replayIndex:state.replayIndex,
                    saveManualSnapshot:window.saveManualSnapshot,
                    cancelReplayBackgroundComputation:window.cancelReplayBackgroundComputation,
                    stopReplayTimer:window.stopReplayTimer,
                    schedulePersistPrefs:window.schedulePersistPrefs,
                    loadSelectedHistoryHand:window.loadSelectedHistoryHand,
                    openReplayerPage:window.openReplayerPage,
                    leaveHistoryMode:window.leaveHistoryMode,
                    requestAnimationFrame:window.requestAnimationFrame
                };
                const calls=[];
                try{
                    const hand={id:"__review_context_smoke__"};
                    state.hhHands=[hand];state.selectedHand=null;state.hhMode=false;state.appView="main";
                    window.saveManualSnapshot=()=>calls.push("save");
                    window.cancelReplayBackgroundComputation=()=>{};
                    window.stopReplayTimer=()=>{};
                    window.schedulePersistPrefs=()=>{};
                    window.loadSelectedHistoryHand=()=>calls.push("load");
                    window.openReplayerPage=()=>{state.appView="replayer";calls.push("open");};
                    window.requestAnimationFrame=()=>0;
                    selectHistoryHandById(hand.id);
                    const afterSelect={
                        hhMode:state.hhMode,appView:state.appView,
                        selectedId:state.selectedHand?.id||null,handCount:state.hhHands.length,
                        calls:[...calls]
                    };
                    window.leaveHistoryMode=()=>{
                        state.hhMode=false;state.appView="main";calls.push("leave");
                    };
                    returnToHandsPage();
                    const afterBack={
                        hhMode:state.hhMode,appView:state.appView,
                        selectedId:state.selectedHand?.id||null,handCount:state.hhHands.length,
                        calls:[...calls]
                    };
                    return {
                        togglePresent:!!document.querySelector("#hhModeBtn"),
                        afterSelect,afterBack
                    };
                } finally {
                    state.hhHands=saved.hhHands;state.selectedHand=saved.selectedHand;state.hhMode=saved.hhMode;
                    state.appView=saved.appView;state.replaySteps=saved.replaySteps;state.replayIndex=saved.replayIndex;
                    window.saveManualSnapshot=saved.saveManualSnapshot;
                    window.cancelReplayBackgroundComputation=saved.cancelReplayBackgroundComputation;
                    window.stopReplayTimer=saved.stopReplayTimer;
                    window.schedulePersistPrefs=saved.schedulePersistPrefs;
                    window.loadSelectedHistoryHand=saved.loadSelectedHistoryHand;
                    window.openReplayerPage=saved.openReplayerPage;
                    window.leaveHistoryMode=saved.leaveHistoryMode;
                    window.requestAnimationFrame=saved.requestAnimationFrame;
                }
            }"""
        )
        assert review_context["togglePresent"] is False, review_context
        assert review_context["afterSelect"]["hhMode"] is True, review_context
        assert review_context["afterSelect"]["appView"] == "replayer", review_context
        assert review_context["afterSelect"]["selectedId"] == "__review_context_smoke__", review_context
        assert review_context["afterSelect"]["handCount"] == 1, review_context
        assert review_context["afterSelect"]["calls"][:3] == ["save", "load", "open"], review_context
        assert review_context["afterBack"]["hhMode"] is False, review_context
        assert review_context["afterBack"]["appView"] == "main", review_context
        assert review_context["afterBack"]["selectedId"] == "__review_context_smoke__", review_context
        assert review_context["afterBack"]["handCount"] == 1, review_context
        assert "leave" in review_context["afterBack"]["calls"], review_context

        # Local persistence stays compact in the normal path; details are opt-in,
        # retry performs a real write, and erase cannot proceed without confirmation.
        local_persistence = await page.evaluate(
            """async () => {
                const details=document.querySelector('#localPersistenceDetails');
                const initial={
                    chip:document.querySelector('#localPersistenceStatus')?.textContent?.trim(),
                    open:!!details?.open,
                    detailsText:document.querySelector('#localPersistenceDetail')?.textContent?.trim()
                };
                persistenceStatus("Smoke save in progress",false,true);
                const busy=document.querySelector('#localPersistenceStatus')?.textContent?.trim();
                persistenceStatus("Smoke saved",false,false);
                const saved=document.querySelector('#localPersistenceStatus')?.textContent?.trim();
                const retryOk=await retryLocalPersistence();
                const afterRetry=document.querySelector('#localPersistenceStatus')?.textContent?.trim();
                const realConfirm=window.confirm;
                try{
                    window.confirm=()=>false;
                    const eraseResult=await clearLocalPersistenceWithConfirmation();
                    return {
                        initial,busy,saved,retryOk,afterRetry,
                        eraseResult,
                        eraseStatus:document.querySelector('#localPersistenceActionStatus')?.textContent?.trim(),
                        detailsOpenAfterCancel:!!details?.open
                    };
                } finally {
                    window.confirm=realConfirm;
                }
            }"""
        )
        assert local_persistence["initial"]["open"] is False, local_persistence
        assert "restent" in folded(local_persistence["initial"]["detailsText"]), local_persistence
        assert local_persistence["busy"] == "Sauvegarde…", local_persistence
        assert local_persistence["saved"] == "Sauvegardé localement", local_persistence
        assert local_persistence["retryOk"] is True, local_persistence
        assert local_persistence["afterRetry"] == "Sauvegardé localement", local_persistence
        assert local_persistence["eraseResult"] is False, local_persistence
        assert "annulé" in folded(local_persistence["eraseStatus"]), local_persistence
        assert local_persistence["detailsOpenAfterCancel"] is False, local_persistence

        await page.wait_for_selector("#trainerOpenBtn", timeout=10_000)
        await page.click("#trainerOpenBtn")

        await page.wait_for_function(
            "document.querySelector('#trainerStatus')?.textContent.includes('Trainer prêt') || document.querySelector('#trainerStatus')?.textContent.includes('À vous de jouer') || document.querySelector('#trainerStatus')?.textContent.includes('Nouvelle main')",
            timeout=90_000,
        )
        await page.wait_for_selector("#trainerPage:not(.mode-hidden)", timeout=10_000)
        await page.wait_for_selector("#trainerTable .poker-table", timeout=30_000)
        seats = await page.locator("#trainerTable .seat").count()
        assert seats == 6, f"expected 6 trainer seats, got {seats}"
        assert await page.locator("#trainerTable .seat.hero").count() == 1

        # Hero must be dealt from the persisted Custom range for this exact role/position.
        hero_range = await page.evaluate(
            "() => { const h=trainerState.hand, p=h.positions[h.heroSeat], n=cardsToNotation(h.hole[h.heroSeat]); return {role:h.heroRole, position:p, notation:n, frequency:Number(trainerState.heroRanges?.ranges?.[h.heroRole]?.[p]?.[n]||0)}; }"
        )
        assert hero_range["frequency"] > 0, hero_range
        assert not (hero_range["role"] == "CALLER" and hero_range["position"] == "BB"), hero_range

        # Wait until Model A has produced the pending Hero recommendation and the action UI is live.
        await page.wait_for_function(
            "document.querySelector('#trainerStatus')?.textContent.includes('À vous de jouer') && document.querySelectorAll('#trainerControls [data-trainer-action]').length > 0",
            timeout=90_000,
        )

        # Default Training mode must hide the answer until Hero acts.
        rec_text = await page.locator("#trainerRecommendation").inner_text()
        assert "réponse masquée" in folded(rec_text), rec_text

        # Switching to Guided mid-decision must compute a real recommendation.
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

        await page.wait_for_function(
            "document.querySelector('#trainerFeedback .trainer-feedback-title') && !document.querySelector('#trainerFeedback .trainer-feedback-title').textContent.includes('Feedback')",
            timeout=90_000,
        )
        feedback = await page.locator("#trainerFeedback").inner_text()
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
        assert "décisions" in folded(stats)
        decision_value = await page.locator("#trainerStats .trainer-stat").nth(1).locator(".v").inner_text()
        assert int(decision_value.strip()) >= 1

        # Trainer must not destroy the analyser navigation when returning.
        await page.click("#trainerBackBtn")
        assert await page.locator("#mainPage").is_visible()
        assert await page.locator("#trainerPage").is_hidden()

        snapshot = {
            "replayer_hand_classes": hand_classes,
            "delta_ev_quality_contract": quality_contract,
            "prior_posterior_information_boundary": information_boundary,
            "hh_import_ux": hh_import_ux,
            "review_context": review_context,
            "local_persistence": local_persistence,
            "seats": seats,
            "hero_range": hero_range,
            "guided": guided,
            "guide_state": guide,
            "verdict_state": verdict,
            "feedback": feedback,
            "stats": stats,
            "page_errors": page_errors,
            "console_errors": console_errors,
        }
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
        if page_errors:
            raise AssertionError(f"page errors: {page_errors}")
        await browser.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"trainer smoke failed: {exc}", file=sys.stderr)
        raise

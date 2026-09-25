#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from playwright.async_api import async_playwright

URL = "http://127.0.0.1:8765/index.html"
ROOT = Path(__file__).resolve().parents[2]
# #409: the Trainer browser smoke must be deterministic. The Trainer RNG
# (`trainerRandom()` in site/trainer.js) is seeded explicitly in the page before
# the first hand so that a red run is reproducible from the printed seed alone.
# `TRAINER_SMOKE_SEED` is the calibrated seed; override it for a local bisect
# with `TRAINER_SMOKE_SEED=123 python3 tests/trainer/smoke_trainer.py`.
# Full determinism/reproduction contract and the distinction between the
# terminal `Recommandation` placeholder and the Mode Test invariant:
# docs/trainer-smoke-determinism.md (#409).
# Calibration: the seeded first hand must expose a live, non-terminal Hero
# decision (`trainerState.hand.awaitingHero === true`); the value below yields a
# canonical VS-RFI CALLER spot (Hero HJ facing a LJ open), i.e. the spot covered
# by the retained #108 CALL/FOLD reference.
TRAINER_SMOKE_SEED = int(os.environ.get("TRAINER_SMOKE_SEED", "39"))
KTS_ISO_FIXTURE = ROOT / "tests/fixtures/repro/kts_sb_two_limp_iso4_three_calls.hand.txt"
RANGE_NUMERIC_FIXTURE = ROOT / "tests/fixtures/opponent-range/numeric_scenarios.json"
# Numeric browser smokes driven from this script so that the frozen browser-smoke
# workflow can exercise #391 without adding a workflow step. Each stays a
# standalone module (own static guards, own browser session); the opponent-range
# and D6 render-matrix scripts connect to the already-served 127.0.0.1:8765,
# while the scale-invariance script starts its own ephemeral local server.
DRIVER_SMOKES = (
    Path(__file__).resolve().parent / "smoke_opponent_range_numeric.py",
    Path(__file__).resolve().parent / "smoke_equity_scale_invariance.py",
    Path(__file__).resolve().parent / "smoke_trainer_d6_render_matrix.py",
    # #394 T4: desktop modes smoke + per-mode overflow audit (Accueil → Review →
    # Replayer → Review, Spot Lab without any imported hand, Training, Stratégie
    # Hero and the Replayer right-panel keyboard/focus control). It serves its own
    # ephemeral copy of `site/` at the two reference viewports.
    Path(__file__).resolve().parent / "smoke_modes_desktop.py",
)


def run_driver_smokes() -> None:
    for script in DRIVER_SMOKES:
        print(f"running driver smoke: {script}", flush=True)
        subprocess.run([sys.executable, str(script)], check=True)


def folded(text: str) -> str:
    return text.casefold()


async def main() -> None:
    kts_iso_raw = KTS_ISO_FIXTURE.read_text(encoding="utf-8")
    range_numeric_cfg = json.loads(RANGE_NUMERIC_FIXTURE.read_text(encoding="utf-8"))
    page_errors: list[str] = []
    console_errors: list[str] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = await browser.new_page(viewport={"width": 1500, "height": 1000})
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        await page.goto(URL, wait_until="domcontentloaded", timeout=45_000)

        # #390 browser contract: exercise the real global scheduler under concurrent
        # production worker load while injecting user interactions.
        await page.evaluate(
            """() => {
                window.__computeSchedulerSmokeDone=false;
                const snapshot={
                    hero:[8,24],board:[41,19,25],method:"mc",trials:20000,
                    opponents:[{hands:[{hand:"AA",frequency:100},{hand:"76s",frequency:100}]}]
                };
                const kinds=["background","prefetch","explicit","replayer","explicit","background"];
                window.__computeSchedulerSmokePromise=Promise.all(kinds.map(kind=>new Promise((resolve,reject)=>{
                    const worker=createCalcWorker({kind});
                    worker.onmessage=e=>{
                        if(e.data?.type==="progress")return;
                        cleanupReplayWorker(worker);
                        if(e.data?.type==="error")reject(Error(e.data.message));else resolve(e.data.out);
                    };
                    worker.onerror=e=>reject(Error(e?.message||"worker error"));
                    worker.postMessage(snapshot);
                }))).then(results=>{
                    window.__computeSchedulerSmokeResults=results;
                    window.__computeSchedulerSmokeDone=true;
                });
            }"""
        )
        for _ in range(10):
            await page.keyboard.press("Tab")
            await page.wait_for_timeout(25)
        await page.wait_for_function("window.__computeSchedulerSmokeDone === true", timeout=60_000)
        scheduler_metrics = await page.evaluate("window.pokerComputeScheduler.snapshot()")
        assert scheduler_metrics["maxConcurrency"] <= 2, scheduler_metrics
        assert scheduler_metrics["workersActive"] == 0, scheduler_metrics
        assert scheduler_metrics["interactionMs"], scheduler_metrics
        assert max(scheduler_metrics["interactionMs"]) < 250, scheduler_metrics
        print(json.dumps({"compute_scheduler_smoke": scheduler_metrics}, indent=2))

        shared_presentation = await page.evaluate(
            """() => {
                const api=window.PokerActionSizingEV;
                const summary={
                    schema:"decision-summary/v1",
                    played:{label:"CALL",sizing:"call 2 BB",evBB:1.5},
                    recommended:{label:"RAISE",sizing:"ajoute 5 BB",evBB:2.2},
                    deltaEVBB:-0.7,lossEVBB:0.7,effectiveLossEVBB:0.65,withinNoise:false,
                    alternatives:[
                        {label:"RAISE",sizing:"ajoute 5 BB",evBB:2.2,recommended:true},
                        {label:"CALL",sizing:"call 2 BB",evBB:1.5,recommended:false}
                    ]
                };
                return {
                    present:!!api,
                    script:[...document.scripts].some(s=>String(s.getAttribute("src")||"").endsWith("action-sizing-ev.js")),
                    semantics:api?.semantics||null,
                    primary:api?.primarySummaryHtml(summary,{compact:true,escapeHtml,formatBB})||"",
                    alternatives:api?.alternativesStripHtml(summary,{limit:2,escapeHtml,formatBB})||""
                };
            }"""
        )
        assert shared_presentation["present"] and shared_presentation["script"], shared_presentation
        assert shared_presentation["semantics"]["selects_action"] is False, shared_presentation
        assert shared_presentation["semantics"]["recomputes_ev"] is False, shared_presentation
        assert shared_presentation["semantics"]["validator"] == "#299", shared_presentation
        assert "Recommandé" in shared_presentation["primary"] and "RAISE" in shared_presentation["primary"], shared_presentation
        assert "EV" in shared_presentation["alternatives"] and "CALL" in shared_presentation["alternatives"], shared_presentation

        # #341 browser contract: one deterministic covered CALL/FOLD context and one
        # explicit VS_LIMPERS fail-closed context, both on the retained #108 reference.
        preflop_runtime = await page.evaluate(
            """() => {
                const seats=["BTN","SB","BB","LJ","HJ","CO"],stacks=Object.fromEntries(seats.map(x=>[x,100]));
                const coveredCore=new PokerNlheGameState.NoLimitHoldemState({seats,button:"BTN",stacks_bb:stacks});
                coveredCore.applyAction("LJ","FOLD");
                coveredCore.applyAction("HJ","RAISE",{target_total_bb:2.5});
                coveredCore.applyAction("CO","FOLD");
                const covered=PokerPreflopRuntime.buildCallFold({
                    public_state:{snapshot:coveredCore.toSnapshot(),legal_view:coveredCore.legalView("BTN")},
                    context_id:"smoke-covered-vs-rfi",
                    preflop_context:{context_id:"smoke-covered-vs-rfi",family:"VS_RFI",actor_position:"BTN"},
                    hero_position:"BTN",hand_id:"smoke-covered",call_ev_bb:.42,
                    played_action:{action:"CALL",target_total_bb:2.5},samples:2000
                });
                const surfaces=PokerPreflopRuntime.surfaceBundle(covered);

                const uncoveredCore=new PokerNlheGameState.NoLimitHoldemState({seats,button:"BTN",stacks_bb:stacks});
                uncoveredCore.applyAction("LJ","FOLD");
                uncoveredCore.applyAction("HJ","CALL");
                uncoveredCore.applyAction("CO","FOLD");
                uncoveredCore.applyAction("BTN","CALL");
                const unsupported=PokerPreflopRuntime.buildUnsupported({
                    public_state:{snapshot:uncoveredCore.toSnapshot(),legal_view:uncoveredCore.legalView("SB")},
                    context_id:"smoke-kts-sb-two-limp",
                    preflop_context:{context_id:"smoke-kts-sb-two-limp",family:"VS_LIMPERS",actor_position:"SB"},
                    hero_position:"SB",hand_id:"smoke-uncovered",
                    played_action:{action:"RAISE",target_total_bb:4},reason:"SPOT_NON_COUVERT"
                });
                return {
                    reference:PokerPreflopRuntime.REFERENCE,
                    covered:{
                        schema:covered.schema,admissible:covered.recommendation_admissibility.admissible,
                        action:covered.recommended_action,target:covered.recommended_target_sizing?.target_total_bb,
                        cost:covered.incremental_cost_bb,ev:covered.recommended_ev_bb,
                        support:covered.support?.observations,alternatives:covered.alternatives.length,
                        sameSurface:surfaces.feed===surfaces.detail&&surfaces.detail===surfaces.trainer&&surfaces.trainer===surfaces.review
                    },
                    unsupported:{
                        schema:unsupported.schema,admissible:unsupported.recommendation_admissibility.admissible,
                        coverage:unsupported.coverage_state,action:unsupported.recommended_action,
                        ev:unsupported.recommended_ev_bb,target:unsupported.recommended_target_sizing,
                        cost:unsupported.incremental_cost_bb,alternatives:unsupported.alternatives.length,
                        reasons:unsupported.reason_codes
                    }
                };
            }"""
        )
        assert preflop_runtime["reference"]["decision"] == "RETAIN_REFERENCE", preflop_runtime
        assert preflop_runtime["reference"]["candidate_activated"] is False, preflop_runtime
        assert preflop_runtime["covered"]["schema"] == "poker-preflop-decision/v1", preflop_runtime
        assert preflop_runtime["covered"]["admissible"] is True and preflop_runtime["covered"]["action"] == "CALL", preflop_runtime
        assert preflop_runtime["covered"]["target"] == 2.5 and preflop_runtime["covered"]["cost"] == 2.5, preflop_runtime
        assert abs(preflop_runtime["covered"]["ev"] - 0.42) < 1e-9 and preflop_runtime["covered"]["support"] == 2000, preflop_runtime
        assert preflop_runtime["covered"]["alternatives"] == 2 and preflop_runtime["covered"]["sameSurface"], preflop_runtime
        assert preflop_runtime["unsupported"]["schema"] == "poker-preflop-decision/v1", preflop_runtime
        assert preflop_runtime["unsupported"]["admissible"] is False and preflop_runtime["unsupported"]["coverage"] == "UNSUPPORTED", preflop_runtime
        assert preflop_runtime["unsupported"]["action"] is None and preflop_runtime["unsupported"]["ev"] is None, preflop_runtime
        assert preflop_runtime["unsupported"]["target"] is None and preflop_runtime["unsupported"]["cost"] is None, preflop_runtime
        assert preflop_runtime["unsupported"]["alternatives"] == 0 and "SPOT_NON_COUVERT" in preflop_runtime["unsupported"]["reasons"], preflop_runtime

        # Product architecture: the App shell mounts one view at a time, driven by
        # state.appView; Home is the landed mode screen and lists the mode cards.
        product_architecture = await page.evaluate(
            """() => ({
                nav:[...document.querySelectorAll('#quickNav a')].map(a=>({
                    text:a.textContent.trim(),
                    href:a.getAttribute('href'),
                    domain:a.dataset.productDomain||''
                })),
                homeModes:[...document.querySelectorAll('.mode-card .mode-card-title')].map(x=>x.textContent.trim()),
                homeShell:document.querySelector('#homePage')?.dataset.viewShell||'',
                shells:['home','review','spotlab','strategy','training','replayer'].filter(v=>!!document.querySelector(`[data-view-shell="${v}"]`)),
                appViews:[...APP_VIEWS],
                appView:state.appView,
                mounted:[...document.querySelectorAll('[data-view-shell]')].filter(el=>!el.classList.contains('mode-hidden')).map(el=>el.dataset.viewShell),
                packsInSettings:!!document.querySelector('#settingsSection a[href="./packs.html"]'),
                advancedImportInSettings:document.querySelector('#advancedManualImportLink')?.getAttribute('href')||'',
                legacyImportsHidden:!!document.querySelector('#rangesSection[hidden][data-legacy-import-surface="advanced-only"]'),
                replayerPresent:!!document.querySelector('#replayerSection'),
                equityComponents:['opponentsSection','cardsSection','rangeDisplaySection','equitySection'].every(id=>!!document.getElementById(id))
            })"""
        )
        assert [x["text"] for x in product_architecture["nav"]] == ["Review", "Training", "Strategy", "Equity Lab", "Settings"], product_architecture
        assert [x["domain"] for x in product_architecture["nav"]] == ["review", "training", "strategy", "equity-lab", "settings"], product_architecture
        # #394 — the Strategy nav entry is an in-app navigation to the embedded
        # shell; the standalone editor keeps its own real link on the Accueil mode
        # card and on `#strategyPageEditorLink`.
        assert product_architecture["nav"][2]["href"] == "#strategyPage", product_architecture
        assert product_architecture["homeModes"] == ["Review", "Training", "Stratégie Hero", "Spot Lab", "Packs/paramètres"], product_architecture
        assert product_architecture["homeShell"] == "home", product_architecture
        assert product_architecture["shells"] == ["home", "review", "spotlab", "strategy", "training", "replayer"], product_architecture
        assert product_architecture["appViews"] == ["home", "review", "replayer", "spotlab", "training", "strategy"], product_architecture
        assert product_architecture["appView"] in product_architecture["appViews"], product_architecture
        assert len(product_architecture["mounted"]) == 1, product_architecture
        assert product_architecture["packsInSettings"], product_architecture
        assert product_architecture["advancedImportInSettings"] == "./manual-import.html", product_architecture
        assert product_architecture["legacyImportsHidden"], product_architecture
        assert product_architecture["replayerPresent"] and product_architecture["equityComponents"], product_architecture

        # #217 CENTRAL-UI consumes the merged advanced-import contract without duplicating it.
        advanced_import_ui = await page.evaluate(
            """async () => {
                const API=window.PokerManualOverrides;
                const clean=await API.inspect();
                await refreshCentralManualOverrideState(clean);
                const standard={
                    cleanSchema:clean?.schema,
                    active:clean?.active,
                    status:clean?.configuration_status,
                    restore:clean?.restore_action,
                    noticeHidden:centralOverrideNotice.hidden
                };
                const active={
                    schema:"poker-manual-override/v1",
                    active:true,
                    classification:"MANUAL_OVERRIDE",
                    configuration_status:"NON_STANDARD",
                    compatibility_status:"COMPATIBLE",
                    roles_overridden:["model_a_preflop","model_a_postflop"],
                    base_active_pack:{
                        id:"smoke-pack-id",source:"ACTIVE_PACK",pack_id:"smoke-pack",
                        pack_version:"2026.09.19.1",population_id:"smoke-pop",
                        runtime_revision:"smoke-revision",engine_version:"v83"
                    },
                    restore_action:"RESTORE_ACTIVE_PACK"
                };
                await refreshCentralManualOverrideState(active);
                const shown={
                    hidden:centralOverrideNotice.hidden,
                    badge:centralOverrideBadge.textContent,
                    text:centralOverrideText.textContent,
                    href:centralManualImportLink.getAttribute("href"),
                    restoreDisabled:centralRestorePackBtn.disabled,
                    loadAllowed:centralManualOverrideLoadAllowed(active)
                };
                const stale={...active,compatibility_status:"STALE_BASE_PACK"};
                await refreshCentralManualOverrideState(stale);
                const staleState={
                    hidden:centralOverrideNotice.hidden,
                    text:centralOverrideText.textContent,
                    loadAllowed:centralManualOverrideLoadAllowed(stale)
                };

                const originalInspect=API.inspect,originalRestore=API.restoreActivePack;
                let restoreCalls=0,current=active;
                try{
                    API.inspect=async()=>current;
                    API.restoreActivePack=async()=>{
                        restoreCalls++;
                        current={...clean,active:false,classification:null,configuration_status:"STANDARD",compatibility_status:"COMPATIBLE",restore_action:"RESTORE_ACTIVE_PACK"};
                        return current;
                    };
                    await refreshCentralManualOverrideState(active);
                    const restored=await centralRestoreActivePack({reload:false});
                    return {
                        api:{schema:API.CONTRACT_SCHEMA,restoreAction:API.RESTORE_ACTION},
                        standard,shown,staleState,
                        restore:{
                            calls:restoreCalls,active:restored.active,
                            noticeHidden:centralOverrideNotice.hidden,
                            status:centralOverrideStatus.textContent
                        }
                    };
                } finally {
                    API.inspect=originalInspect;
                    API.restoreActivePack=originalRestore;
                    await refreshCentralManualOverrideState(clean);
                }
            }"""
        )
        assert advanced_import_ui["api"] == {
            "schema":"poker-manual-override/v1",
            "restoreAction":"RESTORE_ACTIVE_PACK",
        }, advanced_import_ui
        assert advanced_import_ui["standard"]["cleanSchema"] == "poker-manual-override/v1", advanced_import_ui
        assert advanced_import_ui["standard"]["active"] is False and advanced_import_ui["standard"]["status"] == "STANDARD", advanced_import_ui
        assert advanced_import_ui["standard"]["restore"] == "RESTORE_ACTIVE_PACK" and advanced_import_ui["standard"]["noticeHidden"], advanced_import_ui
        assert advanced_import_ui["shown"]["hidden"] is False, advanced_import_ui
        assert advanced_import_ui["shown"]["badge"] == "MANUAL_OVERRIDE / NON_STANDARD", advanced_import_ui
        assert "model_a_preflop" in advanced_import_ui["shown"]["text"] and "smoke-pack" in advanced_import_ui["shown"]["text"], advanced_import_ui
        assert advanced_import_ui["shown"]["href"] == "./manual-import.html" and not advanced_import_ui["shown"]["restoreDisabled"], advanced_import_ui
        assert advanced_import_ui["shown"]["loadAllowed"] is True, advanced_import_ui
        assert advanced_import_ui["staleState"]["hidden"] is False and advanced_import_ui["staleState"]["loadAllowed"] is False, advanced_import_ui
        assert "non appliqué au runtime" in advanced_import_ui["staleState"]["text"], advanced_import_ui
        assert advanced_import_ui["restore"]["calls"] == 1 and advanced_import_ui["restore"]["active"] is False, advanced_import_ui
        assert advanced_import_ui["restore"]["noticeHidden"] is True and "Pack actif restauré" in advanced_import_ui["restore"]["status"], advanced_import_ui

        # Review Inbox consumes the merged backend contract and exposes fail-closed deep-link resolution.
        review_inbox_ui = await page.evaluate(
            """() => {
                const exact=resolveReviewInboxDeepLink(
                    {schema:PokerReviewInbox.DEEP_LINK_SCHEMA,hand_id:"42",decision_id:"review:42:3",step_index:3},
                    "42",
                    [{},{},{},{actionType:"call"}],
                    {details:[{stepIndex:3}]}
                );
                const stale=resolveReviewInboxDeepLink(
                    {schema:PokerReviewInbox.DEEP_LINK_SCHEMA,hand_id:"42",decision_id:"review:42:3",step_index:3},
                    "42",
                    [{},{},{},{actionType:"call"}],
                    {details:[{stepIndex:2}]}
                );
                return {
                    schema:PokerReviewInbox?.INBOX_SCHEMA,
                    metadataSchema:PokerReviewInbox?.USER_METADATA_SCHEMA,
                    exact,stale,
                    filters:["reviewStatusFilter","reviewCoverageFilter","reviewStreetFilter","reviewPositionFilter","reviewSpotFilter","reviewPlayedFilter","reviewRecommendedFilter","reviewSizingFilter","reviewJamFilter","reviewOverbetFilter"].every(id=>!!document.getElementById(id)),
                    summary:!!document.getElementById("reviewInboxSummary"),
                    secondaryCollapsed:!document.querySelector(".review-inbox-filters")?.open
                };
            }"""
        )
        assert review_inbox_ui["schema"] == "poker-review-inbox/v1", review_inbox_ui
        assert review_inbox_ui["metadataSchema"] == "poker-review-inbox-user-metadata/v1", review_inbox_ui
        assert review_inbox_ui["exact"]["exact"] is True and review_inbox_ui["exact"]["stepIndex"] == 3, review_inbox_ui
        assert review_inbox_ui["stale"]["exact"] is False and review_inbox_ui["stale"]["reason"] == "DECISION_NOT_FOUND", review_inbox_ui
        assert review_inbox_ui["filters"] and review_inbox_ui["summary"] and review_inbox_ui["secondaryCollapsed"], review_inbox_ui

        # #311 Review surfaces Hero cards and actual settled result, never EV-derived.
        review_actual_result = await page.evaluate(
            """() => {
                const cards=[parseCardCode("Ks"),parseCardCode("Ts")];
                const won={id:"42",heroCards:cards,bigBlind:2,heroResult:{net:37}};
                const lost={id:"43",heroCards:cards,bigBlind:2,heroResult:{net:-14}};
                const unavailable={id:"44",heroCards:cards,bigBlind:null,heroResult:{net:9}};
                const wonMeta=reviewHandDisplayMeta(won),lostMeta=reviewHandDisplayMeta(lost),unavailableMeta=reviewHandDisplayMeta(unavailable);
                const savedHands=state.hhHands;
                try{
                    state.hhHands=[won];
                    renderReviewDashboardModel({
                        schema:PokerReviewDashboard.DASHBOARD_SCHEMA,state:"READY",scope_key:"smoke-311",
                        metrics:{hands_loaded:1,decisions_to_review:1,total_ev_loss_bb:1.25,decisions_analyzed:1,source_refs:[]},
                        top_leaks:[],
                        priority:{
                            hand:{hand_id:"42",total_loss_bb:1.25,status:"TO_REVIEW",status_label:"À revoir"},
                            decision:{decision_id:"review:42:3",step_index:3,street:"FLOP",position:"BTN",spot_family:"SRP",action_played:"CALL",action_recommended:"RAISE",loss_bb:1.25}
                        },
                        ctas:{review:{enabled:false},leak:{enabled:false},training:{enabled:false}}
                    });
                    return {
                        won:wonMeta,lost:lostMeta,unavailable:unavailableMeta,
                        dashboard:{priority:reviewDashboardPriority.textContent,meta:reviewDashboardPriorityMeta.textContent}
                    };
                } finally {
                    state.hhHands=savedHands;
                    renderReviewDashboard();
                }
            }"""
        )
        assert review_actual_result["won"]["hero_cards"] == "K♠ T♠", review_actual_result
        assert review_actual_result["won"]["result"]["state"] == "win" and "Gagné" in review_actual_result["won"]["result"]["text"], review_actual_result
        assert review_actual_result["won"]["result"]["amount"].startswith("+") and ("18,50" in review_actual_result["won"]["result"]["amount"] or "18.50" in review_actual_result["won"]["result"]["amount"]), review_actual_result
        assert review_actual_result["lost"]["result"]["state"] == "loss" and "Perdu" in review_actual_result["lost"]["result"]["text"], review_actual_result
        assert "7,00" in review_actual_result["lost"]["result"]["amount"] or "7.00" in review_actual_result["lost"]["result"]["amount"], review_actual_result
        assert review_actual_result["unavailable"]["result"]["state"] == "unavailable", review_actual_result
        assert review_actual_result["unavailable"]["result"]["text"] == "Résultat réel indisponible", review_actual_result
        assert all(x in review_actual_result["dashboard"]["priority"] for x in ["Main #42","K♠ T♠","Gagné","FLOP","BTN"]), review_actual_result
        assert "perte EV" in review_actual_result["dashboard"]["meta"] and "CALL" in review_actual_result["dashboard"]["meta"] and "RAISE" in review_actual_result["dashboard"]["meta"], review_actual_result

        # #323 Actor-aware replayer comment states consume existing contracts/support only.
        replayer_comment_states = await page.evaluate(
            """() => {
                const evidence={
                    phase:"PREFLOP",
                    decision:{
                        action:"RAISE",family:"VS_LIMPERS",
                        preflop_context_v1:{schema:PokerPreflopContract.SCHEMA,family:"VS_LIMPERS"}
                    }
                };
                const analyzed=replayOpponentCommentStateFromEvidence(evidence,{actionType:"raise"},{
                    quality:"exact",node:{coverage:{population_decisions:37},context:{family:"VS_LIMPERS"}}
                });
                const insufficient=replayOpponentCommentStateFromEvidence(evidence,{actionType:"raise"},{
                    quality:"exact",node:{coverage:{population_decisions:0},context:{family:"VS_LIMPERS"}}
                });
                const unavailable=replayOpponentCommentStateFromEvidence(evidence,{actionType:"raise"},null);
                const heroCovered=replayHeroCommentState(0,{street:"Flop"},null,{
                    canonicalDecision:{schema:"decision-summary/v1",coverage_state:"COVERED",recommendation_admissibility:{admissible:true},ev_comparability:{comparable:true}}
                });
                const heroUncovered=replayHeroCommentState(0,{street:"Préflop"},null,{
                    req:{kind:"aggression"},priorMetrics:{},decisionSummary:null,observedEvidence:evidence
                });
                return {analyzed,insufficient,unavailable,heroCovered,heroUncovered};
            }"""
        )
        assert replayer_comment_states["analyzed"]["actor_role"] == "OPPONENT", replayer_comment_states
        assert replayer_comment_states["analyzed"]["state"] == "ANALYSE_DISPONIBLE" and replayer_comment_states["analyzed"]["support"] == 37, replayer_comment_states
        assert replayer_comment_states["analyzed"]["actor_state"] == "OPPONENT_ANALYZABLE", replayer_comment_states
        assert replayer_comment_states["analyzed"]["source_contract"] == "poker-preflop-context/v1", replayer_comment_states
        assert replayer_comment_states["insufficient"]["state"] == "DONNEES_INSUFFISANTES", replayer_comment_states
        assert replayer_comment_states["insufficient"]["actor_state"] == "OPPONENT_SUPPORT_INSUFFICIENT", replayer_comment_states
        assert "Support insuffisant" in replayer_comment_states["insufficient"]["text"], replayer_comment_states
        assert replayer_comment_states["unavailable"]["state"] == "SPOT_NON_SUPPORTE", replayer_comment_states
        assert replayer_comment_states["unavailable"]["actor_state"] == "OPPONENT_NODE_ABSENT", replayer_comment_states
        assert "Aucun nœud de population" in replayer_comment_states["unavailable"]["text"], replayer_comment_states
        assert replayer_comment_states["heroCovered"]["actor_role"] == "HERO" and replayer_comment_states["heroCovered"]["state"] == "ANALYSE_DISPONIBLE", replayer_comment_states
        assert replayer_comment_states["heroCovered"]["actor_state"] == "HERO_COVERED", replayer_comment_states
        assert replayer_comment_states["heroUncovered"]["actor_role"] == "HERO" and replayer_comment_states["heroUncovered"]["state"] == "SPOT_NON_SUPPORTE", replayer_comment_states
        assert replayer_comment_states["heroUncovered"]["actor_state"] == "SPOT_NON_COUVERT", replayer_comment_states
        assert replayer_comment_states["heroUncovered"]["family"] == "VS_LIMPERS", replayer_comment_states
        assert "Aucune recommandation EV validée" in replayer_comment_states["heroUncovered"]["text"], replayer_comment_states

        # #323 canonical #321 KTs SB / 2 limpers / iso 4 BB / 3 calls browser smoke.
        kts_replayer_comment = await page.evaluate(
            """(raw) => {
                const saved={
                    selectedHand:state.selectedHand,replaySteps:state.replaySteps,hhMode:state.hhMode,
                    populationTraceCache:state.populationTraceCache,postflopTraceCache:state.postflopTraceCache,
                    populationRangeCache:state.populationRangeCache,postflopRangeCache:state.postflopRangeCache,
                    preflopRuntimeDecisionCache:state.preflopRuntimeDecisionCache
                };
                try{
                    const hand=parsePokerStarsHand(raw,"kts_sb_two_limp_iso4_three_calls.hand.txt");
                    if(!hand)throw new Error("fixture #321 non parsée");
                    const steps=makeReplaySteps(hand);
                    state.selectedHand=hand;state.replaySteps=steps;state.hhMode=true;
                    state.populationTraceCache=Object.create(null);state.postflopTraceCache=Object.create(null);
                    state.populationRangeCache=Object.create(null);state.postflopRangeCache=Object.create(null);
                    state.preflopRuntimeDecisionCache=Object.create(null);
                    const heroIndex=steps.findIndex(s=>s.street==="Préflop"&&s.activePlayer===hand.heroName&&s.actionType==="raise");
                    const bbIndex=steps.findIndex((s,i)=>i>heroIndex&&s.street==="Préflop"&&s.activePlayer==="BB"&&s.actionType==="call");
                    if(heroIndex<0||bbIndex<0)throw new Error("steps #321 attendus introuvables");
                    const heroStep=steps[heroIndex],bbStep=steps[bbIndex];
                    const heroEvidence=replayObservedDecisionEvidence(heroIndex,heroStep);
                    const bbEvidence=replayObservedDecisionEvidence(bbIndex,bbStep);
                    const canonical=preflopRuntimeDecisionForStep(heroIndex,heroStep,null,{observedEvidence:heroEvidence});
                    const heroState=replayHeroCommentState(heroIndex,heroStep,null,{
                        req:{kind:"aggression"},priorMetrics:{},decisionSummary:null,canonicalDecision:canonical,
                        observedEvidence:heroEvidence
                    });
                    const bbUnavailable=replayOpponentCommentStateFromEvidence(bbEvidence,bbStep,null);
                    const bbFeed=actionAnalysisHtml(bbIndex,bbStep);
                    const bbDetail=actionDetailModalInnerHtml(bbIndex,bbStep);
                    return {
                        hand:{id:hand.id,hero:hand.heroName,cards:reviewHeroCardsText(hand)},
                        hero:{index:heroIndex,actor:heroStep.activePlayer,action:heroStep.actionType,evidence:heroEvidence,state:heroState,
                            canonical:{schema:canonical?.schema,coverage:canonical?.coverage_state,admissible:canonical?.recommendation_admissibility?.admissible,
                                recommended:canonical?.recommended_action,ev:canonical?.recommended_ev_bb,alternatives:canonical?.alternatives?.length,
                                reasons:canonical?.reason_codes,reference:canonical?.identity?.strategy_id}},
                        bb:{index:bbIndex,actor:bbStep.activePlayer,action:bbStep.actionType,evidence:bbEvidence,state:bbUnavailable,feed:bbFeed,detail:bbDetail}
                    };
                } finally {
                    state.selectedHand=saved.selectedHand;state.replaySteps=saved.replaySteps;state.hhMode=saved.hhMode;
                    state.populationTraceCache=saved.populationTraceCache;state.postflopTraceCache=saved.postflopTraceCache;
                    state.populationRangeCache=saved.populationRangeCache;state.postflopRangeCache=saved.postflopRangeCache;
                    state.preflopRuntimeDecisionCache=saved.preflopRuntimeDecisionCache;
                }
            }""",
            kts_iso_raw,
        )
        assert kts_replayer_comment["hand"] == {"id":"3210001","hero":"Hero","cards":"K♠ T♠"}, kts_replayer_comment
        assert kts_replayer_comment["hero"]["actor"] == "Hero" and kts_replayer_comment["hero"]["action"] == "raise", kts_replayer_comment
        assert kts_replayer_comment["hero"]["evidence"]["decision"]["family"] == "VS_LIMPERS", kts_replayer_comment
        assert kts_replayer_comment["hero"]["state"]["state"] == "SPOT_NON_SUPPORTE", kts_replayer_comment
        assert kts_replayer_comment["hero"]["state"]["actor_state"] == "SPOT_NON_COUVERT", kts_replayer_comment
        assert "Aucune recommandation EV validée" in kts_replayer_comment["hero"]["state"]["text"], kts_replayer_comment
        assert kts_replayer_comment["hero"]["canonical"]["schema"] == "poker-preflop-decision/v1", kts_replayer_comment
        assert kts_replayer_comment["hero"]["canonical"]["coverage"] == "UNSUPPORTED" and kts_replayer_comment["hero"]["canonical"]["admissible"] is False, kts_replayer_comment
        assert kts_replayer_comment["hero"]["canonical"]["recommended"] is None and kts_replayer_comment["hero"]["canonical"]["ev"] is None, kts_replayer_comment
        assert kts_replayer_comment["hero"]["canonical"]["alternatives"] == 0 and "SPOT_NON_COUVERT" in kts_replayer_comment["hero"]["canonical"]["reasons"], kts_replayer_comment
        assert kts_replayer_comment["bb"]["actor"] == "BB" and kts_replayer_comment["bb"]["action"] == "call", kts_replayer_comment
        assert kts_replayer_comment["bb"]["evidence"]["decision"]["family"] == "VS_ISO", kts_replayer_comment
        assert kts_replayer_comment["bb"]["state"]["state"] == "SPOT_NON_SUPPORTE", kts_replayer_comment
        assert kts_replayer_comment["bb"]["state"]["actor_state"] == "OPPONENT_NODE_ABSENT", kts_replayer_comment
        assert 'data-comment-actor="OPPONENT"' in kts_replayer_comment["bb"]["feed"], kts_replayer_comment
        assert "Aucune alternative EV validée" not in kts_replayer_comment["bb"]["feed"], kts_replayer_comment
        assert "alternative EV Hero" in kts_replayer_comment["bb"]["detail"], kts_replayer_comment
        assert "Aucune alternative EV validée" not in kts_replayer_comment["bb"]["detail"], kts_replayer_comment

        # #391 Replayer range modal browser rendering: open the real modal on a
        # public fixture that yields a uniform prior (explicit non-informative
        # state, no numeric 169 grid) and on a conditioned posterior (canonical
        # sum-normalized 169 mass grid). Only public hero/board cards and the
        # a priori 169 policy from the numeric fixture are consumed.
        opponent_range_modal = await page.evaluate(
            """async (payload) => {
                const {ktsRaw,policy}=payload;
                const parseFreq=text=>{
                    const s=String(text||"").replace(/\\s*%\\s*$/,"").replace(",",".").trim();
                    const v=Number(s);return Number.isFinite(v)?v:null;
                };
                const saved={
                    selectedHand:state.selectedHand,replaySteps:state.replaySteps,replayIndex:state.replayIndex,
                    hhMode:state.hhMode,postflopRangeCache:state.postflopRangeCache,populationRangeCache:state.populationRangeCache,
                    populationTraceCache:state.populationTraceCache,postflopTraceCache:state.postflopTraceCache,
                    opponents:state.opponents,ranges:state.ranges,rangeEdition:state.rangeEdition,
                    populationModel:state.populationModel,populationNodeIndex:state.populationNodeIndex,
                    populationPolicyCache:state.populationPolicyCache
                };
                try{
                    const hand=parsePokerStarsHand(ktsRaw,"kts_sb_two_limp_iso4_three_calls.hand.txt");
                    if(!hand)throw new Error("fixture modale range non parsée");
                    const steps=makeReplaySteps(hand);
                    state.selectedHand=hand;state.replaySteps=steps;state.hhMode=true;
                    state.postflopRangeCache=Object.create(null);state.populationRangeCache=Object.create(null);
                    state.populationTraceCache=Object.create(null);state.postflopTraceCache=Object.create(null);
                    state.populationModel=null;state.populationNodeIndex=null;state.populationPolicyCache=Object.create(null);
                    state.opponents=[];state.ranges=[];state.rangeEdition=false;
                    const player=currentHandPlayer("CO");
                    if(!player)throw new Error("joueur CO introuvable dans la fixture");
                    const coIndex=steps.findIndex(s=>s.street==="Préflop"&&s.activePlayer==="CO"&&s.actionType==="call");
                    if(coIndex<0)throw new Error("action CO de la fixture introuvable");
                    const policyFor=h=>Object.prototype.hasOwnProperty.call(policy,h)?Number(policy[h]):Number(policy.__default__??1);

                    // (1) Uniform prior: no population model and no imported
                    // legacy range => the untouched prior is uniform and the
                    // posterior state is explicitly non-informative.
                    state.replayIndex=0;
                    const uniformEstimate=populationRangeEstimateForPlayer(player,0);
                    openPopulationRangeModal("CO");
                    const uniformBody=populationRangeModalBody;
                    const uniform={
                        open:populationRangeModal.classList.contains("open"),
                        ariaHidden:populationRangeModal.getAttribute("aria-hidden"),
                        state:uniformEstimate?.posteriorState,
                        uniformPrior:uniformEstimate?.uniformPrior===true,
                        informativeActions:Number(uniformEstimate?.informativeActions)||0,
                        gridTitle:uniformBody.querySelector(".section-title")?.textContent||"",
                        gridCount:uniformBody.querySelectorAll(".population-modal-grid").length,
                        cellCount:uniformBody.querySelectorAll(".population-modal-cell").length,
                        warningText:uniformBody.querySelector(".population-modal-warning")?.textContent||"",
                        text:uniformBody.textContent
                    };
                    closePopulationRangeModal();

                    // (2) Conditioned posterior: apply one a priori 169 policy to
                    // the uniform exact-combo prior (public hero blockers only),
                    // then render the modal over the same sum-normalized mass
                    // estimate the equity consumers are fed.
                    state.replayIndex=coIndex;
                    const combos=uniformExactComboPrior([...(hand.heroCards||[])]);
                    for(const c of combos)c.weight*=Math.max(0,policyFor(cardsToNotation(c.cards)));
                    if(!normalizeComboWeightsToMass(combos))throw new Error("normalisation de masse conditionnée échouée");
                    const conditionedEstimate=exactComboRangeResult(combos,{informativeActions:1});
                    if(!conditionedEstimate)throw new Error("estimate conditionnée indisponible");
                    const preCount=replayPreflopDecisionCount(coIndex),postCount=replayPostflopDecisionCount(coIndex);
                    state.postflopRangeCache[`dyn47:${hand.id}:CO:${coIndex}:${preCount}:${postCount}`]=conditionedEstimate;
                    openPopulationRangeModal("CO");
                    const conditionedBody=populationRangeModalBody;
                    const cells=[...conditionedBody.querySelectorAll(".population-modal-cell")];
                    const displayed=cells.map(c=>parseFreq(c.querySelector(".freq")?.textContent));
                    const numeric=displayed.filter(v=>v!==null);
                    const aaCell=cells.find(c=>c.querySelector(".hand")?.textContent.trim()==="AA");
                    const conditioned={
                        open:populationRangeModal.classList.contains("open"),
                        ariaHidden:populationRangeModal.getAttribute("aria-hidden"),
                        state:conditionedEstimate.posteriorState,
                        informativeActions:Number(conditionedEstimate.informativeActions)||0,
                        gridTitle:conditionedBody.querySelector(".section-title")?.textContent||"",
                        gridCount:conditionedBody.querySelectorAll(".population-modal-grid").length,
                        cellCount:cells.length,
                        displayedSum:displayed.reduce((s,v)=>s+(v??0),0),
                        displayedMax:numeric.length?Math.max(...numeric):0,
                        displayedAt100:numeric.filter(v=>Math.abs(v-100)<1e-9).length,
                        gridEstimateSum:(conditionedEstimate.gridEntries||[]).reduce((s,e)=>s+Math.max(0,Number(e.frequency)||0),0),
                        gridEstimateLen:(conditionedEstimate.gridEntries||[]).length,
                        aaDisplayed:aaCell?parseFreq(aaCell.querySelector(".freq")?.textContent):null,
                        aaMass:Number((conditionedEstimate.gridEntries||[]).find(e=>e.hand==="AA")?.frequency)||0,
                        deltaPresent:!!conditionedBody.querySelector(".population-delta-grid")
                    };
                    closePopulationRangeModal();
                    return {uniform,conditioned};
                }finally{
                    state.selectedHand=saved.selectedHand;state.replaySteps=saved.replaySteps;state.replayIndex=saved.replayIndex;
                    state.hhMode=saved.hhMode;state.postflopRangeCache=saved.postflopRangeCache;state.populationRangeCache=saved.populationRangeCache;
                    state.populationTraceCache=saved.populationTraceCache;state.postflopTraceCache=saved.postflopTraceCache;
                    state.opponents=saved.opponents;state.ranges=saved.ranges;state.rangeEdition=saved.rangeEdition;
                    state.populationModel=saved.populationModel;state.populationNodeIndex=saved.populationNodeIndex;
                    state.populationPolicyCache=saved.populationPolicyCache;
                }
            }""",
            {"ktsRaw": kts_iso_raw, "policy": range_numeric_cfg["preflop_policy"]},
        )
        # The non-informative prior is rendered as an explicit state, never as a
        # numeric 100 % grid, and the modal is genuinely open.
        assert opponent_range_modal["uniform"]["open"] is True, opponent_range_modal
        assert opponent_range_modal["uniform"]["ariaHidden"] == "false", opponent_range_modal
        assert opponent_range_modal["uniform"]["state"] == "prior_uninformative", opponent_range_modal
        assert opponent_range_modal["uniform"]["uniformPrior"] is True, opponent_range_modal
        assert opponent_range_modal["uniform"]["informativeActions"] == 0, opponent_range_modal
        assert "Prior non informatif" in opponent_range_modal["uniform"]["gridTitle"], opponent_range_modal
        assert opponent_range_modal["uniform"]["gridCount"] == 0, opponent_range_modal
        assert opponent_range_modal["uniform"]["cellCount"] == 0, opponent_range_modal
        assert "Aucune grille 169" in opponent_range_modal["uniform"]["text"], opponent_range_modal
        # The conditioned posterior renders the canonical sum-normalized mass
        # grid: 169 classes, values summing to ~100, none pinned at 100 %.
        assert opponent_range_modal["conditioned"]["open"] is True, opponent_range_modal
        assert opponent_range_modal["conditioned"]["ariaHidden"] == "false", opponent_range_modal
        assert opponent_range_modal["conditioned"]["state"] == "conditioned", opponent_range_modal
        assert opponent_range_modal["conditioned"]["informativeActions"] == 1, opponent_range_modal
        assert "projection 169 (masse)" in opponent_range_modal["conditioned"]["gridTitle"], opponent_range_modal
        assert opponent_range_modal["conditioned"]["gridCount"] == 1, opponent_range_modal
        assert opponent_range_modal["conditioned"]["cellCount"] == 169, opponent_range_modal
        assert abs(opponent_range_modal["conditioned"]["gridEstimateSum"] - 100.0) < 1e-6, opponent_range_modal
        assert opponent_range_modal["conditioned"]["gridEstimateLen"] == 169, opponent_range_modal
        assert abs(opponent_range_modal["conditioned"]["displayedSum"] - 100.0) < 3.0, opponent_range_modal
        assert opponent_range_modal["conditioned"]["displayedMax"] < 100.0, opponent_range_modal
        assert opponent_range_modal["conditioned"]["displayedAt100"] == 0, opponent_range_modal
        assert abs(opponent_range_modal["conditioned"]["aaDisplayed"] - opponent_range_modal["conditioned"]["aaMass"]) < 0.1, opponent_range_modal
        assert opponent_range_modal["conditioned"]["deltaPresent"] is True, opponent_range_modal

        exact_review_open = await page.evaluate(
            """() => {
                const saved={
                    hhHands:state.hhHands, reviewScores:state.reviewScores, replaySteps:state.replaySteps,
                    replayIndex:state.replayIndex, selectedHand:state.selectedHand, hhMode:state.hhMode,
                    select:window.selectHistoryHandById, setIndex:window.setReplayIndexAndRecalculate,
                    open:window.openReplayerPage, exportText:replayerExportStatus?.textContent||""
                };
                const calls=[];
                try{
                    state.hhHands=[{id:"42"}];
                    state.reviewScores={"42":{details:[{stepIndex:3}]}};
                    state.replaySteps=[];state.replayIndex=0;state.selectedHand=null;state.hhMode=false;
                    window.selectHistoryHandById=(id,opts)=>{
                        calls.push(["select",id,opts?.open]);
                        state.selectedHand=state.hhHands[0];state.hhMode=true;
                        state.replaySteps=[{},{},{},{actionType:"call"}];
                    };
                    window.setReplayIndexAndRecalculate=(idx)=>{state.replayIndex=idx;calls.push(["step",idx]);};
                    window.openReplayerPage=(opts)=>calls.push(["open",opts?.scrollTop]);
                    const result=openReviewInboxDeepLink({
                        schema:PokerReviewInbox.DEEP_LINK_SCHEMA,
                        hand_id:"42",decision_id:"review:42:3",step_index:3
                    });
                    return {result,calls,replayIndex:state.replayIndex};
                } finally {
                    state.hhHands=saved.hhHands;state.reviewScores=saved.reviewScores;state.replaySteps=saved.replaySteps;
                    state.replayIndex=saved.replayIndex;state.selectedHand=saved.selectedHand;state.hhMode=saved.hhMode;
                    window.selectHistoryHandById=saved.select;window.setReplayIndexAndRecalculate=saved.setIndex;
                    window.openReplayerPage=saved.open;
                    if(replayerExportStatus)replayerExportStatus.textContent=saved.exportText;
                }
            }"""
        )
        assert exact_review_open["result"]["exact"] is True, exact_review_open
        assert exact_review_open["replayIndex"] == 3, exact_review_open
        assert exact_review_open["calls"] == [["select", "42", False], ["step", 3], ["open", True]], exact_review_open

        # Review Dashboard is the useful home and renders only backend-provided metrics/CTAs.
        dashboard_ui = await page.evaluate(
            """() => {
                const savedView=state.reviewDashboardView;
                const savedFilters={...state.reviewInboxFilters};
                try{
                    const base={
                        schema:PokerReviewDashboard.DASHBOARD_SCHEMA,
                        scope_key:"scope-smoke",
                        metrics:{
                            hands_loaded:12,decisions_to_review:4,total_ev_loss_bb:6.5,
                            decisions_analyzed:20,review_coverage_pct:90,
                            source_refs:[{hand_id:"42",decision_id:"review:42:3"}]
                        },
                        top_leaks:[{dimension:"spot_family",key:"SRP|PFR|IP",decisions:3,hands:2,total_loss_bb:4.2}],
                        priority:{
                            hand:{hand_id:"42",total_loss_bb:3,status:"TO_REVIEW",status_label:"À revoir"},
                            decision:{decision_id:"review:42:3",step_index:3,street:"FLOP",position:"BTN",spot_family:"SRP|PFR|IP",action_played:"CHECK",action_recommended:"BET",loss_bb:3}
                        },
                        ctas:{
                            review:{enabled:true,target:{schema:PokerReviewInbox.DEEP_LINK_SCHEMA,hand_id:"42",decision_id:"review:42:3",step_index:3}},
                            leak:{enabled:true,target:{scope_key:"scope-smoke",dimension:"spot_family",key:"SRP|PFR|IP"}},
                            training:{enabled:true,reason:"TOP_LEAK_TARGET",target:{target_id:"leak-target:smoke"}}
                        }
                    };
                    renderReviewDashboardModel({...base,state:"READY"});
                    const ready={
                        schema:PokerReviewDashboard.DASHBOARD_SCHEMA,
                        state:reviewDashboardState.textContent,
                        hands:reviewDashboardHands.textContent,
                        decisions:reviewDashboardDecisions.textContent,
                        loss:reviewDashboardLoss.textContent,
                        leak:reviewDashboardLeak.textContent,
                        priority:reviewDashboardPriority.textContent,
                        priorityMeta:reviewDashboardPriorityMeta.textContent,
                        reviewVisible:!reviewDashboardReviewBtn.hidden,
                        leakVisible:!reviewDashboardLeakBtn.hidden,
                        trainingVisible:!reviewDashboardTrainingBtn.hidden,
                        importVisible:!reviewDashboardImportBtn.hidden,
                        trace:reviewDashboardTrace.textContent
                    };
                    renderReviewDashboardModel({...base,state:"READY",ctas:{...base.ctas,training:{enabled:false,reason:"INSUFFICIENT_SOURCE_SUPPORT",target:{target_id:"leak-target:smoke"}}}});
                    const gatedTrainingHidden=reviewDashboardTrainingBtn.hidden;
                    const messages={};
                    for(const stateName of ["NO_HANDS","ANALYSIS_PENDING","ANALYSIS_INCOMPLETE","NO_SIGNIFICANT_LOSS","READY"]){
                        messages[stateName]=reviewDashboardStateMessage({state:stateName});
                    }
                    state.reviewDashboardView={...base,state:"READY"};
                    const leakOpen=openReviewDashboardLeak();
                    const leakFilter=state.reviewInboxFilters.spot_family;
                    state.reviewDashboardView={...base,state:"READY",ctas:{...base.ctas,leak:{enabled:true,target:{scope_key:"scope-smoke",dimension:"position",key:"BTN"}}}};
                    const unsupported=openReviewDashboardLeak();
                    return {ready,gatedTrainingHidden,messages,leakOpen,leakFilter,unsupported};
                } finally {
                    state.reviewInboxFilters=savedFilters;
                    state.reviewDashboardView=savedView;
                    renderReviewDashboard();
                }
            }"""
        )
        assert dashboard_ui["ready"]["schema"] == "poker-review-dashboard/v1", dashboard_ui
        assert dashboard_ui["ready"]["state"] == "READY", dashboard_ui
        assert dashboard_ui["ready"]["hands"] == "12" and dashboard_ui["ready"]["decisions"] == "4", dashboard_ui
        assert "6,50" in dashboard_ui["ready"]["loss"] or "6.50" in dashboard_ui["ready"]["loss"], dashboard_ui
        assert dashboard_ui["ready"]["leak"] == "SRP|PFR|IP", dashboard_ui
        assert "Main #42" in dashboard_ui["ready"]["priority"] and "FLOP" in dashboard_ui["ready"]["priority"], dashboard_ui
        assert "CHECK" in dashboard_ui["ready"]["priorityMeta"] and "BET" in dashboard_ui["ready"]["priorityMeta"], dashboard_ui
        assert dashboard_ui["ready"]["reviewVisible"] and dashboard_ui["ready"]["leakVisible"] and dashboard_ui["ready"]["trainingVisible"], dashboard_ui
        assert not dashboard_ui["ready"]["importVisible"], dashboard_ui
        assert "1 décision" in dashboard_ui["ready"]["trace"], dashboard_ui
        assert dashboard_ui["gatedTrainingHidden"] is True, dashboard_ui
        assert all(dashboard_ui["messages"][name] for name in ["NO_HANDS","ANALYSIS_PENDING","ANALYSIS_INCOMPLETE","NO_SIGNIFICANT_LOSS","READY"]), dashboard_ui
        assert dashboard_ui["leakOpen"]["opened"] is True and dashboard_ui["leakFilter"] == "SRP|PFR|IP", dashboard_ui
        assert dashboard_ui["unsupported"]["opened"] is False and dashboard_ui["unsupported"]["reason"] == "UNSUPPORTED_LEAK_DIMENSION", dashboard_ui

        # Model-B robustness UI consumes #260 summaries only and fails closed on identity/support mismatch.
        robustness_ui = await page.evaluate(
            """() => {
                const UI=window.PokerModelBRobustnessUI;
                const identity={...reviewInboxScopeInput()};
                const decisionId="review:42:3";
                const makeSummary=(status="robust")=>({
                    schema:UI.SUMMARY_SCHEMA,
                    decision_id:decisionId,
                    status,
                    nominal:{
                        action:"JAM",sizing:1.6,ev_bb:2.4,advantage_bb:0.35,
                        mc_ci95:[2.2,2.6],mc_ci95_width_bb:0.4
                    },
                    model_environment:{
                        comparable:true,ev_span_bb:[1.7,2.4],max_regret_bb:0.05,
                        worst_environment_regret:{environment_id:"fold-high",regret_bb:0.05},
                        environment_count:3,missing_environment_ids:[],noncomparable_environment_ids:[],weighted:false
                    },
                    stability:{action:true,sizing:true,ranking:true},
                    support:{all_environments_supported:true,unsupported_environment_count:0},
                    shove_fragility:{applicable:true,kind:"SHOVE",fragile:false,affected_environments:[],nominal_advantage_bb:0.35,worst_environment_regret:{environment_id:"fold-high",regret_bb:0.05}},
                    overbet_fragility:{applicable:true,kind:"OVERBET",fragile:false,affected_environments:[],nominal_advantage_bb:0.35,worst_environment_regret:{environment_id:"fold-high",regret_bb:0.05}},
                    aggressive_fragility:null,
                    detail_available:true
                });
                const envelope=summary=>({schema:UI.ENVELOPE_SCHEMA,identity:{...identity},summary});
                const robust=UI.consumeEnvelope(envelope(makeSummary("robust")),{decision_id:decisionId,identity});

                const sensitiveSummary=makeSummary("sensitive");
                sensitiveSummary.stability={action:false,sizing:false,ranking:false};
                sensitiveSummary.model_environment.max_regret_bb=0.65;
                sensitiveSummary.model_environment.ev_span_bb=[0.9,2.4];
                sensitiveSummary.shove_fragility={...sensitiveSummary.shove_fragility,fragile:true,affected_environments:["fold-high"]};
                sensitiveSummary.overbet_fragility={...sensitiveSummary.overbet_fragility,fragile:true,affected_environments:["fold-low"]};
                const sensitiveEnvelope=envelope(sensitiveSummary);
                const sensitive=UI.consumeEnvelope(sensitiveEnvelope,{decision_id:decisionId,identity});

                const falseRobustSummary=makeSummary("robust");
                falseRobustSummary.support={all_environments_supported:false,unsupported_environment_count:1};
                const falseRobust=UI.consumeEnvelope(envelope(falseRobustSummary),{decision_id:decisionId,identity});
                const missing=UI.consumeEnvelope(null,{decision_id:decisionId,identity});
                const mismatch=UI.consumeEnvelope(
                    {schema:UI.ENVELOPE_SCHEMA,identity:{...identity,strategy_version:"wrong-version"},summary:makeSummary("robust")},
                    {decision_id:decisionId,identity}
                );
                const wrongDecision=UI.consumeEnvelope(
                    {schema:UI.ENVELOPE_SCHEMA,identity,summary:{...makeSummary("robust"),decision_id:"review:42:2"}},
                    {decision_id:decisionId,identity}
                );

                const compact=modelBRobustnessCompactHtml(sensitive);
                const detail=modelBRobustnessDetailHtml(sensitive);

                const savedScores=state.reviewScores;
                const savedMap=state.modelBRobustnessByDecision;
                try{
                    state.reviewScores={"42":{details:[{stepIndex:3}]}};
                    state.modelBRobustnessByDecision=Object.create(null);
                    const accepted=setModelBRobustnessEnvelope("42",3,sensitiveEnvelope);
                    const stored=state.reviewScores["42"].details[0].model_b_robustness;
                    const reviewView=modelBRobustnessViewForDecision("42",3);
                    const rejected=setModelBRobustnessEnvelope("42",3,{
                        schema:UI.ENVELOPE_SCHEMA,
                        identity:{...identity,population_id:"other-pop"},
                        summary:sensitiveSummary
                    });
                    return {
                        schemas:{summary:UI.SUMMARY_SCHEMA,envelope:UI.ENVELOPE_SCHEMA,view:UI.VIEW_SCHEMA},
                        robust:{status:robust.status,label:UI.statusLabel(robust)},
                        sensitive:{status:sensitive.status,label:UI.statusLabel(sensitive),affected:UI.affectedEnvironmentIds(sensitive)},
                        falseRobust:{status:falseRobust.status,failClosed:falseRobust.fail_closed,reason:falseRobust.reason},
                        missing:{evidence:missing.evidence_status,status:missing.status,failClosed:missing.fail_closed},
                        mismatch:{evidence:mismatch.evidence_status,reason:mismatch.reason},
                        wrongDecision:{evidence:wrongDecision.evidence_status,reason:wrongDecision.reason},
                        html:{compact,detail},
                        setter:{
                            accepted:accepted.accepted,
                            storedSchema:stored?.schema,
                            reviewStatus:reviewView.status,
                            rejected:rejected.accepted,
                            rejectReason:rejected.reason
                        }
                    };
                } finally {
                    state.reviewScores=savedScores;
                    state.modelBRobustnessByDecision=savedMap;
                }
            }"""
        )
        assert robustness_ui["schemas"] == {
            "summary": "hero-model-b-robustness-summary/v1",
            "envelope": "hero-model-b-robustness-ui-envelope/v1",
            "view": "hero-model-b-robustness-ui-view/v1",
        }, robustness_ui
        assert robustness_ui["robust"]["status"] == "robust" and "Robuste" in robustness_ui["robust"]["label"], robustness_ui
        assert robustness_ui["sensitive"]["status"] == "sensitive" and "Sensible" in robustness_ui["sensitive"]["label"], robustness_ui
        assert {"fold-high", "fold-low"}.issubset(set(robustness_ui["sensitive"]["affected"])), robustness_ui
        assert robustness_ui["falseRobust"]["status"] == "insufficiently_supported" and robustness_ui["falseRobust"]["failClosed"], robustness_ui
        assert robustness_ui["falseRobust"]["reason"] == "SUPPORT_OR_COMPARABILITY_INCOMPLETE", robustness_ui
        assert robustness_ui["missing"] == {"evidence":"unavailable","status":"insufficiently_supported","failClosed":True}, robustness_ui
        assert robustness_ui["mismatch"]["evidence"] == "unavailable" and robustness_ui["mismatch"]["reason"] == "IDENTITY_MISMATCH", robustness_ui
        assert robustness_ui["wrongDecision"]["evidence"] == "unavailable" and robustness_ui["wrongDecision"]["reason"] == "DECISION_ID_MISMATCH", robustness_ui
        assert "Sensible aux variantes Model B" in robustness_ui["html"]["compact"], robustness_ui
        assert all(text in robustness_ui["html"]["detail"] for text in ["EV nominale","Incertitude Monte-Carlo","Incertitude Model B","Shove","Overbet","fold-high","pas un verdict de stratégie"]), robustness_ui
        assert robustness_ui["setter"]["accepted"] is True and robustness_ui["setter"]["storedSchema"] == "hero-model-b-robustness-ui-envelope/v1", robustness_ui
        assert robustness_ui["setter"]["reviewStatus"] == "sensitive", robustness_ui
        assert robustness_ui["setter"]["rejected"] is False and robustness_ui["setter"]["rejectReason"] == "IDENTITY_MISMATCH", robustness_ui

        # Leak -> Training consumes the merged target + selector contracts and fails closed.
        targeted_training = await page.evaluate(
            """() => {
                const saved={
                    targeted:trainerTargetClone(trainerState.targeted),
                    mode:trainerState.mode,
                    dashboard:state.reviewDashboardView,
                    openTarget:window.trainerOpenTargetedSession
                };
                try{
                    const identity={
                        population_id:"smoke-pop",
                        pack_id:"smoke-pack@1",
                        strategy_id:"hero-custom",
                        strategy_version:"app-v83@smoke",
                        ev_reference:"review_score_policy_adjusted_incremental_bb"
                    };
                    const target=PokerLeakTrainingTarget.buildTrainingTarget({
                        identity,
                        context:{position:"BTN",street:"FLOP",spot_family:"SRP|PFA|IP"},
                        source_pattern:{played_action:"CHECK",recommended_action:"BET"},
                        source_leak:{
                            dimension:"spot_family",key:"SRP|PFA|IP",decisions:3,total_loss_bb:4.2,
                            source_refs:[{hand_id:"42",decision_id:"review:42:3"}]
                        },
                        minimum_support:{decisions:1,scenarios:1}
                    });
                    const hand={
                        id:991,heroSeat:5,activeOppSeat:4,heroRole:"PFA",
                        positions:["SB","BB","LJ","HJ","CO","BTN"],
                        stacks:[100,100,100,100,97.5,97.5],streetPaid:[0,0,0,0,0,0],
                        pot:6,currentBet:0,lastRaise:1,raises:0,street:"flop",boardCount:3,
                        runout:[0,1,2,3,4],decisionNo:1
                    };
                    const detail={
                        bestLabel:"BET",bestCostBB:3,chosenEV:0,bestEV:1,rawLossBB:1,lossBB:1,
                        comparable:true,withinNoise:false,
                        simContext:{potType:"SRP",preflopRole:"PFA",relativePosition:"IP"}
                    };
                    const descriptor=trainerTargetDescriptor(target,hand,detail,1);
                    const plan=PokerLeakScenarioSelector.buildSessionPlan(target,[descriptor],{
                        session_size:1,seed:"smoke-target",identity
                    });
                    const fallback=PokerLeakScenarioSelector.buildSessionPlan(target,[],{
                        session_size:1,seed:"smoke-fallback",identity
                    });

                    trainerState.targeted.active=true;
                    trainerState.targeted.baseTarget=trainerTargetClone(target);
                    trainerState.targeted.target=trainerTargetClone(target);
                    trainerState.targeted.requestedSize=1;
                    trainerTargetHydrate(target);
                    trainerTargetPosition.value="CO";
                    trainerTargetAction.value="CHECK";
                    trainerTargetSessionSize.value="1";
                    const edited=trainerTargetBuildFromControls();

                    const event=PokerLeakAnalyzer.buildDecisionEvent({
                        hand_id:"trainer-smoke-1",decision_id:"trainer-smoke-d1",timestamp:"2026-09-19T00:00:00Z",
                        ...identity,position:"BTN",street:"FLOP",spot_family:"SRP|PFA|IP",
                        action_played:"CHECK",action_recommended:"BET",played_ev_bb:-1,best_ev_bb:0,
                        support:{covered:true,source:"smoke"},comparability:{comparable:true}
                    });
                    trainerState.targeted.plan=plan;
                    trainerState.targeted.fallback=null;
                    trainerState.targeted.events=[event];
                    trainerState.targeted.summary=PokerLeakScenarioSelector.summarizePlannedSession(
                        plan,[event],{minimum_trend_decisions:2,minimum_long_term_spots:50}
                    );
                    trainerTargetRenderSummary();
                    const summaryText=trainerTargetSummary.textContent;

                    const calls=[];
                    window.trainerOpenTargetedSession=t=>{calls.push(t);return Promise.resolve(null);};
                    state.reviewDashboardView={ctas:{training:{enabled:true,reason:"TOP_LEAK_TARGET",target}}};
                    const ctaResult=openReviewDashboardTraining();

                    const modes=[];
                    for(const mode of ["guided","training","test"]){trainerSetMode(mode);modes.push(trainerState.mode);}

                    return {
                        schemas:{
                            target:target.schema,
                            criteria:PokerLeakTrainingTarget.compileScenarioCriteria(target).schema,
                            plan:plan.schema,
                            runtimeSummary:trainerState.targeted.summary.schema
                        },
                        descriptor:{
                            context:descriptor.context,policy:descriptor.policy,focus:descriptor.focus,
                            identity:descriptor.identity,supported:descriptor.supported
                        },
                        plan:{ready:plan.ready,selected:plan.selection.length,target_id:plan.target_id},
                        fallback:{ready:fallback.ready,code:fallback.fallback,selected:fallback.selection.length},
                        edited:{position:edited.context.position,action:edited.source_pattern.recommended_action,target_id:edited.target_id},
                        summaryText,
                        cta:{result:ctaResult,calls:calls.map(t=>t.target_id)},
                        modes,
                        fields:["trainerTargetPosition","trainerTargetStreet","trainerTargetSpot","trainerTargetAction","trainerTargetSizing","trainerTargetJam","trainerTargetOverbet","trainerTargetSessionSize"].every(id=>!!document.getElementById(id))
                    };
                } finally {
                    trainerState.targeted=saved.targeted;
                    trainerState.mode=saved.mode;
                    state.reviewDashboardView=saved.dashboard;
                    window.trainerOpenTargetedSession=saved.openTarget;
                    trainerRender();
                }
            }"""
        )
        assert targeted_training["schemas"]["target"] == "poker-leak-training-target/v1", targeted_training
        assert targeted_training["schemas"]["criteria"] == "poker-training-scenario-criteria/v1", targeted_training
        assert targeted_training["schemas"]["plan"] == "poker-leak-training-session-plan/v1", targeted_training
        assert targeted_training["schemas"]["runtimeSummary"] == "poker-leak-training-runtime-summary/v1", targeted_training
        assert targeted_training["descriptor"]["context"] == {"position":"BTN","street":"FLOP","spot_family":"SRP|PFA|IP"}, targeted_training
        assert targeted_training["descriptor"]["policy"]["recommended_action"] == "BET", targeted_training
        assert targeted_training["descriptor"]["identity"]["strategy_version"] == "app-v83@smoke", targeted_training
        assert targeted_training["descriptor"]["supported"] is True, targeted_training
        assert targeted_training["plan"]["ready"] is True and targeted_training["plan"]["selected"] == 1, targeted_training
        assert targeted_training["fallback"] == {"ready":False,"code":"INSUFFICIENT_SUPPORTED_SCENARIOS","selected":0}, targeted_training
        assert targeted_training["edited"]["position"] == "CO" and targeted_training["edited"]["action"] == "CHECK", targeted_training
        assert targeted_training["edited"]["target_id"] != targeted_training["plan"]["target_id"], targeted_training
        assert "1/1" in targeted_training["summaryText"] and "perte ΔEV ciblée" in targeted_training["summaryText"], targeted_training
        assert "progression long terme non inférée" in targeted_training["summaryText"], targeted_training
        assert targeted_training["cta"]["result"]["reason"] == "TARGET_RUNTIME_REQUESTED", targeted_training
        assert targeted_training["cta"]["calls"] == [targeted_training["plan"]["target_id"]], targeted_training
        assert targeted_training["modes"] == ["guided","training","test"], targeted_training
        assert targeted_training["fields"], targeted_training

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

        # The App lands on the Home mode screen: enter Review before exercising the
        # HH import surface, then leave the trainer back on Home.
        await page.click('.mode-card[data-app-view="review"]')
        await page.wait_for_selector("#mainPage:not(.mode-hidden)", timeout=10_000)

        # #394 T1 — Review lands on its Pilotage pane and the import surface lives in
        # its own pane, so the import block is reached by a real click on the Import
        # tab before any interaction with `.hh-import-advanced`: the file input and
        # the advanced options are never clicked while their pane is `hidden`.
        assert await page.locator("#reviewDashboard").is_visible()
        assert await page.locator("#historiesSection").is_hidden()
        await page.click("#reviewImportTab")
        assert await page.locator("#historiesSection").is_visible()
        assert await page.locator("#reviewDashboard").is_hidden()

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

        # The shell lands on Home: return there so the shared chrome trigger is
        # mounted/visible for the focus-return assertion below.
        await page.evaluate("() => goHome()")
        await page.wait_for_selector("#homePage:not(.mode-hidden)", timeout=10_000)

        # Desktop modal accessibility: focus enters the dialog, wraps on Tab/Shift+Tab,
        # Escape closes it, and focus returns to the trigger.
        await page.evaluate(
            """() => {
                const trigger=document.querySelector('#trainerOpenBtn');
                const body=document.querySelector('#actionDetailModalBody');
                trigger.focus();
                body.innerHTML='<button id="a11yFirst" type="button">Premier</button><button id="a11yLast" type="button">Dernier</button>';
                openAccessibleModal(actionDetailModal,{initialFocus:()=>actionDetailModalClose});
            }"""
        )
        await page.wait_for_function("document.activeElement?.id === 'actionDetailModalClose'")
        accessibility = await page.evaluate(
            """() => ({
                initial:document.activeElement?.id,
                open:actionDetailModal.classList.contains('open'),
                ariaHidden:actionDetailModal.getAttribute('aria-hidden')
            })"""
        )
        assert accessibility["initial"] == "actionDetailModalClose", accessibility
        assert accessibility["open"] is True and accessibility["ariaHidden"] == "false", accessibility

        await page.keyboard.press("Shift+Tab")
        assert await page.evaluate("document.activeElement?.id") == "a11yLast"
        await page.keyboard.press("Tab")
        assert await page.evaluate("document.activeElement?.id") == "actionDetailModalClose"
        await page.keyboard.press("Escape")
        await page.wait_for_function("!document.querySelector('#actionDetailModal').classList.contains('open')")
        await page.wait_for_function("document.activeElement?.id === 'trainerOpenBtn'")
        assert await page.evaluate("document.activeElement?.id") == "trainerOpenBtn"

        desktop_font = await page.evaluate(
            """() => {
                const host=document.createElement('div');
                host.className='decision-primary-card';
                host.innerHTML='<span class="k" id="a11yFontProbe">Probe</span>';
                document.body.appendChild(host);
                const size=parseFloat(getComputedStyle(host.querySelector('#a11yFontProbe')).fontSize);
                host.remove();
                return size;
            }"""
        )
        assert desktop_font >= 10, desktop_font

        # #409: inject the explicit Trainer RNG seed BEFORE the trainer is opened
        # (and therefore before the first hand is dealt). `trainerSetSeed` resets
        # the single seeded source, so the whole scripted session below is a pure
        # function of TRAINER_SMOKE_SEED. The seed is journalised and printed in
        # the snapshot so any failure can be reproduced: TRAINER_SMOKE_SEED=<seed>.
        seeded = await page.evaluate("(seed) => window.trainerSetSeed(seed)", TRAINER_SMOKE_SEED)
        assert seeded == TRAINER_SMOKE_SEED, (seeded, TRAINER_SMOKE_SEED)
        print(f"trainer smoke seed: {TRAINER_SMOKE_SEED}", flush=True)

        await page.wait_for_selector('#quickNav [data-product-domain="training"]', timeout=10_000)
        await page.click('#quickNav [data-product-domain="training"]')

        await page.wait_for_function(
            "document.querySelector('#trainerStatus')?.textContent.includes('Trainer prêt') || document.querySelector('#trainerStatus')?.textContent.includes('À vous de jouer') || document.querySelector('#trainerStatus')?.textContent.includes('Nouvelle main')",
            timeout=90_000,
        )
        await page.wait_for_selector("#trainerPage:not(.mode-hidden)", timeout=10_000)
        await page.wait_for_selector("#trainerTable .poker-table", timeout=30_000)
        seats = await page.locator("#trainerTable .seat").count()
        assert seats == 6, f"expected 6 trainer seats, got {seats}"
        assert await page.locator("#trainerTable .seat.hero").count() == 1

        # #409: no silent hand regeneration and no retry that could mask a
        # regression. Wait for the seeded hand to settle (Hero decision reached or
        # hand ended) then fail LOUD if the calibrated seed no longer exposes a
        # live, non-terminal Hero decision. The seed is printed so the failure is
        # reproducible.
        await page.wait_for_function(
            "() => { const h=trainerState.hand; return !!h && (h.awaitingHero || h.ended); }",
            timeout=90_000,
        )
        seeded_hand = await page.evaluate(
            """() => {
                const h=trainerState.hand;
                return {
                    awaitingHero:!!h?.awaitingHero, ended:!!h?.ended, street:h?.street||null,
                    handNo:trainerState.handNo, handId:h?.id??null,
                    dealerSeat:h?.dealerSeat??null, heroSeat:h?.heroSeat??null,
                    heroRole:h?.heroRole||null, heroPosition:h?.positions?.[h?.heroSeat]||null,
                    preflopHistory:(h?.preflopHistory||[]).map(x=>({...x})),
                    preflopRaiseLevel:h?.preflopRaiseLevel??null
                };
            }"""
        )
        assert seeded_hand["awaitingHero"] is True and seeded_hand["ended"] is False, (
            f"seeded smoke hand (TRAINER_SMOKE_SEED={TRAINER_SMOKE_SEED}) does not expose a live, "
            f"non-terminal Hero decision; recalibrate the seed: {seeded_hand}"
        )

        # Hero must be dealt from the persisted Custom range for this exact role/position.
        hero_range = await page.evaluate(
            "() => { const h=trainerState.hand, p=h.positions[h.heroSeat], n=cardsToNotation(h.hole[h.heroSeat]); return {role:h.heroRole, position:p, notation:n, frequency:Number(trainerState.heroRanges?.ranges?.[h.heroRole]?.[p]?.[n]||0), street:h.street, boardCount:h.boardCount}; }"
        )
        assert hero_range["frequency"] > 0, hero_range
        assert not (hero_range["role"] == "CALLER" and hero_range["position"] == "BB"), hero_range
        assert hero_range["street"] == "preflop" and hero_range["boardCount"] == 0, hero_range

        await page.wait_for_function(
            "document.querySelector('#trainerStatus')?.textContent.includes('À vous de jouer') && document.querySelectorAll('#trainerControls [data-trainer-action]').length > 0",
            timeout=90_000,
        )

        # Default Training mode hides the answer until Hero acts.
        rec_text = await page.locator("#trainerRecommendation").inner_text()
        assert "réponse masquée" in folded(rec_text), rec_text

        # #409: the "Training/Test modes remain reachable" invariant MUST be
        # asserted on the LIVE, non-terminal Hero decision (awaitingHero &&
        # !ended), BEFORE any Hero action. Switching modes never acts on the hand,
        # so the decision stays live while both hidden-answer surfaces are proven.
        assert await page.evaluate(
            "() => !!(trainerState.hand && !trainerState.hand.ended && trainerState.hand.awaitingHero)"
        ) is True, "Mode Test invariant must run on a live Hero decision"
        await page.click('[data-trainer-mode="guided"]')
        await page.wait_for_function(
            "trainerState.recommendation && !trainerState.recommendation.error && trainerState.recommendation.preflopDecision",
            timeout=90_000,
        )
        assert await page.evaluate(
            "() => !!(trainerState.hand && !trainerState.hand.ended && trainerState.hand.awaitingHero)"
        ) is True, "Hero decision became terminal before the Mode Test invariant"
        await page.click('[data-trainer-mode="test"]')
        test_mode = await page.locator("#trainerRecommendation").inner_text()
        assert "mode test" in folded(test_mode) and "réponse masquée" in folded(test_mode), test_mode
        await page.click('[data-trainer-mode="training"]')
        training_mode = await page.locator("#trainerRecommendation").inner_text()
        assert "décidez" in folded(training_mode) and "réponse masquée" in folded(training_mode), training_mode

        # Back to guided to consume the canonical preflop object. Depending on the
        # real history, the decision is either covered by retained CALL/FOLD or
        # explicitly fail-closed.
        await page.click('[data-trainer-mode="guided"]')
        await page.wait_for_function(
            "trainerState.recommendation && !trainerState.recommendation.error && trainerState.recommendation.preflopDecision",
            timeout=90_000,
        )
        guided = await page.locator("#trainerRecommendation").inner_text()
        guide = await page.evaluate(
            """() => {
                const r=trainerState.recommendation,d=r?.preflopDecision;
                const view=d?trainerPreflopDecisionView(d):null;
                return {
                    schema:d?.schema,covered:!!PokerPreflopRuntime.isCovered(d),
                    show_ev:!!view?.show_ev,taxonomy_state:view?.taxonomy_state||null,
                    family:d?.facing_context||"",label:r?.bestLabel,
                    cost:Number(r?.bestCostBB),ev:Number(r?.bestEV),
                    kind:trainerRecommendationKind(trainerState.hand,r),
                    latencyMs:Number(trainerState.perf.lastMs),
                    candidateActive:PokerPreflopRuntime.REFERENCE.candidate_activated
                };
            }"""
        )
        assert guide["schema"] == "poker-preflop-decision/v1" and guide["candidateActive"] is False, guide
        assert guide["latencyMs"] >= 0, guide

        if guide["show_ev"]:
            # Rule D6 (admissible AND comparable): the recommendation/sizing/EV
            # may be exposed.
            assert "action recommandée" in folded(guided) and "ev —" not in folded(guided), guided
            assert guide["kind"] in {"FOLD", "CALL"}, guide
            action = page.locator(f'#trainerControls [data-trainer-action="{guide["kind"]}"]')
            assert await action.count(), f"guided action button missing: {guide}"
        elif guide["covered"]:
            # The reference is admissible/covered but the pre-action decision has
            # no comparable played EV yet, so D6 keeps the recommendation hidden.
            # The panel stays visible with the canonical taxonomy label and a
            # precise cause instead of a generic message or hidden-answer.
            assert "action recommandée" not in folded(guided), guided
            assert "réponse masquée" not in folded(guided), guided
            assert "analyse partielle" in folded(guided), guided
            assert guide["kind"] in {"FOLD", "CALL"}, guide
            action = page.locator(f'#trainerControls [data-trainer-action="{guide["kind"]}"]')
            assert await action.count(), f"guided action button missing: {guide}"
        else:
            # #393 T5: the primary label is the shared taxonomy state; the raw
            # reason code stays out of the primary recommendation panel.
            assert "spot non support" in folded(guided), guided
            assert "spot_non_couvert" not in folded(guided), guided
            assert guide["kind"] == "", guide
            action = page.locator('#trainerControls [data-trainer-action="CHECK"], #trainerControls [data-trainer-action="FOLD"], #trainerControls [data-trainer-action="CALL"]').first
            assert await action.count(), f"no legal fail-closed action: {guide}"

        await action.click()
        await page.wait_for_function(
            "document.querySelector('#trainerFeedback .trainer-feedback-title') && !document.querySelector('#trainerFeedback .trainer-feedback-title').textContent.includes('Feedback')",
            timeout=90_000,
        )
        feedback = await page.locator("#trainerFeedback").inner_text()
        verdict = await page.evaluate(
            """() => {
                const d=trainerState.feedback?.detail?.preflopDecision;
                return {
                    schema:d?.schema,covered:!!PokerPreflopRuntime.isCovered(d),
                    label:trainerState.feedback?.detail?.bestLabel,
                    cost:Number(trainerState.feedback?.detail?.bestCostBB),
                    ev:Number(trainerState.feedback?.detail?.bestEV),
                    chosen:Number(trainerState.feedback?.detail?.chosenEV),
                    loss:Number(trainerState.feedback?.row?.lossBB),
                    comparable:!!d?.ev_comparable,
                    reused:Number(trainerState.perf.reused),
                    latencyMs:Number(trainerState.perf.lastMs)
                };
            }"""
        )
        assert verdict["schema"] == "poker-preflop-decision/v1", verdict
        if guide["covered"]:
            assert verdict["covered"] is True, (guide, verdict)
            if guide["show_ev"]:
                assert verdict["label"] == guide["label"], (guide, verdict)
                if guide["cost"] == guide["cost"]:
                    assert abs(verdict["cost"] - guide["cost"]) <= 1e-9, (guide, verdict)
                assert abs(verdict["ev"] - guide["ev"]) <= 1e-9, (guide, verdict)
            else:
                # T3/D6: the pre-action recommendation carried no comparable
                # played EV, so bestLabel/EV/sizing were unavailable. Once the
                # played action is comparable the canonical gate opens and the
                # recommended action label is exposed.
                assert verdict["comparable"] is True, (guide, verdict)
                assert verdict["label"] == guide["kind"], (guide, verdict)
                assert verdict["ev"] == verdict["ev"], (guide, verdict)
            assert verdict["loss"] <= 0.15, (guide, verdict, feedback)
            assert verdict["reused"] >= 1, (guide, verdict)
            assert "recommandé" in folded(feedback), feedback
        else:
            assert verdict["covered"] is False and verdict["comparable"] is False, verdict
            # #393 T5: taxonomy label in the feedback headline; the concrete
            # reason code and the separated dimensions are only exposed in the
            # secondary technical detail, rendered after the primary label.
            assert "spot non support" in folded(feedback), feedback
            assert "aucune recommandation ev" in folded(feedback), feedback
            assert "détails techniques" in folded(feedback), feedback
            assert folded(feedback).index("spot non support") < folded(feedback).index("détails techniques"), feedback

        stats = await page.locator("#trainerStats").inner_text()
        assert "décisions" in folded(stats)
        decision_value = await page.locator("#trainerStats .trainer-stat").nth(1).locator(".v").inner_text()
        assert int(decision_value.strip()) >= 1

        # #409 terminal case, kept strictly SEPARATE from the Mode Test invariant:
        # on an ENDED hand the recommendation panel renders the neutral terminal
        # placeholder (`Recommandation` / `—`) instead of the hidden-answer text.
        # Asserted on a synthetic ended state so it can never be confused with
        # "Mode Test" + "Réponse masquée".
        # Rationale + seed API/repro procedure: docs/trainer-smoke-determinism.md.
        terminal_recommendation = await page.evaluate(
            """() => {
                const h=trainerState.hand;
                const prevEnded=!!h.ended, prevMode=trainerState.mode, prevRecommendation=trainerState.recommendation;
                h.ended=true; trainerState.mode="guided"; trainerState.recommendation=null; trainerState.busy=false;
                trainerRender();
                const el=document.querySelector('#trainerRecommendation');
                const out={
                    label:(el.querySelector('.trainer-rec-label')?.textContent||'').trim(),
                    main:(el.querySelector('.trainer-rec-main')?.textContent||'').trim(),
                    cls:el.className, text:(el.textContent||'').trim()
                };
                h.ended=prevEnded; trainerState.mode=prevMode; trainerState.recommendation=prevRecommendation; trainerRender();
                return out;
            }"""
        )
        assert terminal_recommendation["label"] == "Recommandation", terminal_recommendation
        assert terminal_recommendation["main"] == "—", terminal_recommendation
        assert "hidden-answer" in terminal_recommendation["cls"], terminal_recommendation
        assert "mode test" not in folded(terminal_recommendation["text"]), terminal_recommendation
        assert "réponse masquée" not in folded(terminal_recommendation["text"]), terminal_recommendation

        # #409 same-seed / same-scenario probe. Re-seeding and rebuilding the hand
        # twice MUST yield an identical scenario (dealer/hero seats, positions,
        # hole cards, Hero role, preflop history); a different seed is reported
        # (never asserted) so the calibration stays observable in the snapshot.
        scenario_probe = await page.evaluate(
            """(seed) => {
                const fingerPrint=()=>{
                    const h=trainerBuildHand();
                    return JSON.stringify({
                        dealerSeat:h.dealerSeat, heroSeat:h.heroSeat, positions:h.positions.slice(),
                        hole:h.hole.map(c=>c.slice()), heroRole:h.heroRole,
                        preflopHistory:h.preflopHistory.map(x=>({...x}))
                    });
                };
                const otherSeed=(Number(seed)+1)>>>0;
                trainerSetSeed(seed); const first=fingerPrint();
                trainerSetSeed(seed); const second=fingerPrint();
                trainerSetSeed(otherSeed); const other=fingerPrint();
                return {seed, otherSeed, sameSeedIdentical:first===second, first, second, other, otherSeedDiffers:first!==other};
            }""",
            TRAINER_SMOKE_SEED,
        )
        assert scenario_probe["sameSeedIdentical"] is True, scenario_probe

        # Trainer must not destroy the analyser navigation when returning.
        await page.click("#trainerBackBtn")
        assert await page.locator("#homePage").is_visible()
        assert await page.locator("#trainerPage").is_hidden()

        snapshot = {
            "trainer_seed": TRAINER_SMOKE_SEED,
            "trainer_seed_env_override": os.environ.get("TRAINER_SMOKE_SEED"),
            "seeded_hand": seeded_hand,
            "scenario_probe": scenario_probe,
            "terminal_recommendation": terminal_recommendation,
            "product_architecture": product_architecture,
            "replayer_hand_classes": hand_classes,
            "delta_ev_quality_contract": quality_contract,
            "prior_posterior_information_boundary": information_boundary,
            "opponent_range_modal": {
                "uniform": {k: v for k, v in opponent_range_modal["uniform"].items() if k != "text"},
                "conditioned": opponent_range_modal["conditioned"],
            },
            "hh_import_ux": hh_import_ux,
            "review_context": review_context,
            "local_persistence": local_persistence,
            "desktop_accessibility": accessibility,
            "desktop_font_px": desktop_font,
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
        if console_errors:
            raise AssertionError(f"console errors: {console_errors}")
        await browser.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
        run_driver_smokes()
    except Exception as exc:
        print(f"trainer smoke failed: {exc}", file=sys.stderr)
        raise

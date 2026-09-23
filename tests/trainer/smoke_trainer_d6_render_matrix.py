#!/usr/bin/env python3
"""Render-level D6 regression matrix (Cases A-E) on the real Trainer render path.

Rule D6 says the Training preflop surface may only expose a Hero recommendation
(action, sizing, EV and alternative EVs) when the canonical analysis-state view
is both admissible **and** comparable (`trainerPreflopDecisionView().show_ev`).

The existing ``tests/trainer/test_trainer_analysis_state_contract.py`` proves the
gate on ``trainerPreflopDecisionView().show_ev`` and on a hand-built panel
element. This browser smoke closes the remaining gap: it drives the **real
assembled application** and reads the **actual rendered DOM** produced by
``trainerRenderRecommendation()`` (the primary ``#trainerRecommendation`` panel)
and ``trainerPreflopDecisionSummaryHtml()`` reached through the real
``trainerRenderFeedback()`` (the ``#trainerFeedback`` panel). No jsdom is used.

The five canonical cases of the fixture (``fixtures/d6_render_matrix.json``) are
injected as raw ``poker-preflop-decision/v1`` inputs:

* **A** admissible / not comparable / covered  -> ``ANALYSE_PARTIELLE``, gate
  closed, no recommended-action token, no formatted recommended EV and no
  alternative EV, the non-comparability reason stays visible;
* **B** not admissible / comparable / covered  -> gate closed, no
  action/sizing/EV, the admissibility reason stays visible in the secondary
  technical/detail layer;
* **C** not admissible / not comparable / covered -> no Hero recommendation or
  EV anywhere in the rendered Training surfaces;
* **D** admissible / comparable / covered -> the valid display is preserved
  (recommended action, sizing and EV still rendered);
* **E** unsupported / not covered -> fail-closed behaviour unchanged, the shared
  taxonomy label is still shown and no recommendation/EV leaks.

Representation/render only: the model/fit and every contract are untouched.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

URL = "http://127.0.0.1:8765/index.html"
ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "tests/trainer/fixtures/d6_render_matrix.json"
TRAINER_SOURCE = (ROOT / "site/trainer.js").read_text(encoding="utf-8")


def folded(text: str) -> str:
    return str(text or "").casefold()


def load_matrix() -> list[dict]:
    payload = json.loads(MATRIX.read_text(encoding="utf-8"))
    assert payload["schema"] == "trainer-d6-render-matrix/v1", payload.get("schema")
    cases = payload["cases"]
    assert [c["name"][0] for c in cases] == ["A", "B", "C", "D", "E"], [c["name"] for c in cases]
    return cases


# Static side of the guard: the real render path must keep the D6 gate and the
# precise fail-closed cause. A local covered-only recombination would fail here.
def static_guards() -> None:
    recommendation = TRAINER_SOURCE.split("function trainerRenderRecommendation(", 1)[1].split(
        "function trainerRenderFeedback(", 1
    )[0]
    summary = TRAINER_SOURCE.split("function trainerPreflopDecisionSummaryHtml(", 1)[1].split(
        "function trainerBestText(", 1
    )[0]
    assert "const view=trainerPreflopDecisionView(d);" in recommendation
    assert "if(view.show_ev){" in recommendation
    assert "isCovered" not in recommendation, "covered alone must never gate the recommendation panel"
    assert "trainerPreflopTaxonomyLabel(d)" in recommendation
    assert "trainerPreflopRecommendationCause(view)" in recommendation
    assert "const view=trainerPreflopDecisionView(decision);" in summary
    assert "if(!view.show_ev){" in summary
    assert "trainerAnalysisDimensionsHtml(view.analysis)" in summary
    # The raw reason codes stay in the secondary detail layer, never in the
    # primary recommendation panel.
    assert "reason_codes" not in recommendation


# The whole matrix is executed in-page against the real functions and the real
# DOM nodes, then returned as plain JSON.
MATRIX_JS = r"""
(cases) => {
    const fmt = v => (v === null || v === undefined || !Number.isFinite(Number(v))) ? null : trainerFmtBB(v);
    const snapshot = {
        mode: trainerState.mode,
        busy: trainerState.busy,
        hand: trainerState.hand,
        recommendation: trainerState.recommendation,
        feedback: trainerState.feedback,
        pauseAfterDecision: trainerState.pauseAfterDecision
    };
    const out = {};
    try {
        trainerState.mode = "guided";
        trainerState.busy = false;
        trainerState.pauseAfterDecision = false;
        trainerState.hand = { ended: false };
        for (const testCase of cases) {
            const decision = testCase.decision;
            // 1) Real primary recommendation panel.
            trainerState.recommendation = { preflopDecision: decision };
            trainerRenderRecommendation();
            const recEl = document.getElementById("trainerRecommendation");
            const recommendation = { className: recEl.className, html: recEl.innerHTML, text: recEl.textContent };
            // 2) Real secondary feedback summary, which renders
            //    trainerPreflopDecisionSummaryHtml() through trainerRenderFeedback().
            const summaryDirect = trainerPreflopDecisionSummaryHtml(decision);
            const summaryProbe = document.createElement("div");
            summaryProbe.innerHTML = summaryDirect;
            const summaryText = summaryProbe.textContent;
            trainerState.feedback = {
                detail: { preflopDecision: decision },
                row: { cls: "close", cost: 2.5, lossBB: 0, played: decision.played_action || "CALL" }
            };
            trainerRenderFeedback();
            const fbEl = document.getElementById("trainerFeedback");
            const feedback = { className: fbEl.className, html: fbEl.innerHTML, text: fbEl.textContent };
            const view = trainerPreflopDecisionView(decision);
            out[testCase.name] = {
                view: { show_ev: view.show_ev, taxonomy_state: view.taxonomy_state, taxonomy_label: view.taxonomy_label },
                cause: trainerPreflopRecommendationCause(view),
                summaryDirect,
                summaryText,
                recommendation,
                feedback,
                tokens: {
                    recommended_action: decision.recommended_action == null ? null : String(decision.recommended_action),
                    recommended_ev: fmt(decision.recommended_ev_bb),
                    played_ev: fmt(decision.played_ev_bb),
                    incremental_cost: fmt(decision.incremental_cost_bb),
                    recommended_target: decision.recommended_target_sizing
                        ? fmt(decision.recommended_target_sizing.target_total_bb) : null,
                    alternatives: (decision.alternatives || []).map(a => ({ action: a.action, ev: fmt(a.ev_bb) }))
                }
            };
        }
    } finally {
        trainerState.mode = snapshot.mode;
        trainerState.busy = snapshot.busy;
        trainerState.hand = snapshot.hand;
        trainerState.recommendation = snapshot.recommendation;
        trainerState.feedback = snapshot.feedback;
        trainerState.pauseAfterDecision = snapshot.pauseAfterDecision;
    }
    return out;
}
"""


def assert_fail_closed(result: dict, expect: dict) -> None:
    assert result["view"]["show_ev"] is False, result
    assert result["view"]["taxonomy_state"] == expect["taxonomy_state"], result
    assert result["view"]["taxonomy_label"] == expect["taxonomy_label"], result
    # The fail-closed panel must stay visible (never the hidden-answer placeholder).
    assert result["recommendation"]["className"] == "trainer-recommendation", result
    rec_folded = folded(result["recommendation"]["text"])
    fb_folded = folded(result["feedback"]["text"])
    # The shared taxonomy label is the primary label, never a raw enum/reason code.
    assert folded(expect["taxonomy_label"]) in rec_folded, result
    assert folded(expect["taxonomy_label"]) in fb_folded, result
    cause = expect.get("cause_phrase")
    if cause:
        assert folded(cause) in folded(result["cause"]), result
        assert folded(cause) in rec_folded, result
        assert folded(cause) in fb_folded, result
    technical = expect.get("technical_phrase")
    if technical:
        assert 'data-analysis-detail="1"' in result["feedback"]["html"], result
        assert technical in result["feedback"]["html"], result
        # The raw code only lives in the secondary detail layer.
        assert technical not in result["recommendation"]["html"], result
    # No Hero recommendation anywhere in the rendered surfaces.
    assert "action recommandée" not in rec_folded, result
    assert "action recommandée" not in fb_folded, result
    surfaces = result["recommendation"]["html"] + "\n" + result["feedback"]["html"]
    folded_surfaces = folded(surfaces)
    action = result["tokens"]["recommended_action"]
    if action:
        assert folded(action) not in folded_surfaces, (action, result)
    for key in ("recommended_ev", "played_ev", "incremental_cost", "recommended_target"):
        token = result["tokens"][key]
        if token:
            assert token not in surfaces, (key, token, result)
    for alternative in result["tokens"]["alternatives"]:
        if alternative["ev"]:
            assert alternative["ev"] not in surfaces, (alternative, result)


def assert_open_case(result: dict, expect: dict) -> None:
    assert result["view"]["show_ev"] is True, result
    assert result["view"]["taxonomy_state"] == expect["taxonomy_state"], result
    assert result["view"]["taxonomy_label"] == expect["taxonomy_label"], result
    rec = result["recommendation"]
    assert rec["className"] == "trainer-recommendation", result
    assert "action recommandée" in folded(rec["text"]), result
    assert result["tokens"]["recommended_action"] in rec["html"], result
    assert result["tokens"]["recommended_ev"] in rec["html"], result
    assert result["tokens"]["recommended_target"] in rec["html"], result
    fb = result["feedback"]
    assert "recommandé" in folded(fb["text"]), result
    assert result["tokens"]["recommended_ev"] in fb["html"], result
    if result["tokens"]["played_ev"]:
        assert result["tokens"]["played_ev"] in fb["html"], result
    alternative_evs = [a["ev"] for a in result["tokens"]["alternatives"] if a["ev"]]
    assert alternative_evs, result
    assert any(ev in fb["html"] for ev in alternative_evs), result


def check_case(name: str, result: dict, expect: dict) -> None:
    # The direct function output must be the exact fragment rendered by the real
    # feedback path (proves trainerPreflopDecisionSummaryHtml is actually used).
    assert result["summaryDirect"], (name, result)
    assert result["summaryText"], (name, result)
    assert result["summaryText"] in result["feedback"]["text"], (name, result)
    if expect["preserve_recommendation"]:
        assert_open_case(result, expect)
    else:
        assert_fail_closed(result, expect)


async def main() -> None:
    static_guards()
    cases = load_matrix()
    page_errors: list[str] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = await browser.new_page(viewport={"width": 1500, "height": 1000})
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        await page.goto(URL, wait_until="domcontentloaded", timeout=45_000)
        await page.wait_for_function(
            "typeof trainerRenderRecommendation === 'function'"
            " && typeof trainerPreflopDecisionSummaryHtml === 'function'"
            " && typeof trainerRenderFeedback === 'function'"
            " && typeof trainerState === 'object'"
            " && !!document.getElementById('trainerRecommendation')"
            " && !!document.getElementById('trainerFeedback')",
            timeout=45_000,
        )
        rendered = await page.evaluate(MATRIX_JS, cases)
        await browser.close()

    assert set(rendered.keys()) == {c["name"] for c in cases}, rendered.keys()
    for case in cases:
        check_case(case["name"], rendered[case["name"]], case["expect"])

    if page_errors:
        raise AssertionError(f"page errors: {page_errors}")

    evidence = {
        name: {
            "show_ev": row["view"]["show_ev"],
            "taxonomy_state": row["view"]["taxonomy_state"],
            "recommendation_class": row["recommendation"]["className"],
            "recommendation_excerpt": row["recommendation"]["text"][:120],
        }
        for name, row in rendered.items()
    }
    print(json.dumps({"status": "PASS", "matrix": evidence}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:  # pragma: no cover - surfaced for the CI log
        print(f"D6 render matrix smoke failed: {exc}", file=sys.stderr)
        raise

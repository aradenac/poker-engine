#!/usr/bin/env python3
"""Replayer opponent analysis-state contract (#393 T6 / rule D5).

The adversary surface must derive its user-facing state from the shared
`poker-analysis-state/v1` module (#393 T2/T5) and expose only:

- the observed action;
- the support/likelihood (`statistical_support` + `model_support_status`);
- the opponent range availability before/after the action, derived from the
  #391 posterior states (`conditioned` / `prior_uninformative` /
  `source_prior_unconditioned` / `degenerate`, or `unavailable`).

It must never promise an "optimal EV alternative" nor a Hero EV recommendation.

The three precise causes are distinct and mapped onto the taxonomy:

    OPPONENT_ANALYZABLE          -> ANALYSE_DISPONIBLE
    OPPONENT_SUPPORT_INSUFFICIENT-> DONNEES_INSUFFISANTES
    OPPONENT_NODE_ABSENT         -> SPOT_NON_SUPPORTE

`OPPONENT_ANALYSIS_UNAVAILABLE` is kept only for a genuinely unknown cause (no
evidence at all) and falls back to the safe `DONNEES_INSUFFISANTES` state.

The runtime half (`tests/trainer/opponent_analysis_state_runtime.js`) extracts
the real functions from `site/index.html` and proves each transition plus the
before/after range derivation.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX = (ROOT / "site/index.html").read_text(encoding="utf-8")
MODULE = (ROOT / "src/analytics/analysis-state.js").read_text(encoding="utf-8")


def section(start: str, end: str) -> str:
    assert start in INDEX, f"missing section start: {start}"
    body = INDEX.split(start, 1)[1]
    assert end in body, f"missing section end: {end}"
    return body.split(end, 1)[0]


def main() -> None:
    # 1. The shared module is the single source of the six canonical states.
    assert '<script src="./analytics/analysis-state.js"></script>' in INDEX
    for state in (
        "ANALYSE_DISPONIBLE",
        "ANALYSE_PARTIELLE",
        "CALCUL_EN_COURS",
        "DONNEES_INSUFFISANTES",
        "SPOT_NON_SUPPORTE",
        "ERREUR_CALCUL",
    ):
        assert state in MODULE, state

    block = section("const OPPONENT_ACTOR_ANALYSIS_INPUT=", "function heroCommentView(")
    from_evidence = section(
        "function replayOpponentCommentStateFromEvidence(",
        "function replayOpponentCommentState(stepIndex,step)",
    )
    html = section("function replayOpponentCommentHtml(", "function actionDetailKeyPointsHtml(")

    # 2. The three precise actor causes are distinct and mapped to the taxonomy
    #    through the shared module (never an invented local label).
    assert 'OPPONENT_ANALYZABLE:{coverage_state:"COVERED"}' in block
    assert 'OPPONENT_SUPPORT_INSUFFICIENT:{reason_codes:["INSUFFICIENT_SUPPORT"]}' in block
    assert 'OPPONENT_NODE_ABSENT:{reason_codes:["NODE_ABSENT"]}' in block
    assert "OPPONENT_ANALYSIS_UNAVAILABLE" in block
    assert "function opponentCommentAnalysisState(actorState" in block
    assert "const Module=heroAnalysisModule();" in block
    assert "Module.mapAnalysisState(input)" in block
    assert "const state=analysis?.state||actorState;" in block
    assert "actor_state:actorState" in block
    # The unknown cause keeps an explicit code and a safe fallback state.
    assert 'state:"DONNEES_INSUFFISANTES",reason_codes:["OPPONENT_ANALYSIS_UNAVAILABLE"]' in block

    # 3. The generic message only appears for a genuinely unknown cause; the
    #    no-node branch has its own explicit message.
    assert from_evidence.count("Analyse adverse non disponible pour ce contexte") == 1
    assert from_evidence.index("Analyse adverse non disponible pour ce contexte") < from_evidence.index("if(!match)")
    assert "Analyse adverse non disponible pour ce contexte" in INDEX
    assert "Aucun nœud de population pour cette action observée" in from_evidence
    assert "Support insuffisant pour estimer cette action" in from_evidence
    assert "Analyse adverse disponible" in from_evidence

    # 4. Range availability before/after is derived from the #391 posterior
    #    representation (cached estimate), and exposed on every returned view.
    availability = section(
        "function replayOpponentRangeAvailability(stepIndex,step)",
        "function replayOpponentCommentStateFromEvidence(",
    )
    assert "populationRangeEstimateForPlayer(player,Math.max(0,Number(idx)||0))" in availability
    assert 'posteriorState||"unavailable"' in availability
    assert "read(idx-1)" in availability and "read(idx)" in availability
    assert "function replayOpponentRangeAvailability(stepIndex,step){" in block
    assert "const read=idx=>" in availability
    assert "input.posterior_availability=posterior" in block
    assert "range_before:availability.before" in block
    assert "range_after:availability.after" in block
    assert "posterior_availability:analysis?.posterior_availability" in block
    # The caller computes the availability at the current step index.
    caller = section(
        "function replayOpponentCommentState(stepIndex,step)",
        "function heroCommentView(",
    )
    assert "replayOpponentRangeAvailability(stepIndex,step)" in caller
    assert "rangeAvailability" in caller

    # 5. The message exposes action observée + support + range avant/après.
    assert "action observée" in html
    assert "support " in html
    assert "range avant" in html and "après" in html
    assert "support_status" in html

    # 6. Rule D5: no EV alternative / Hero EV recommendation is promised to the
    #    opponent, and no EV is recomputed in the comment path.
    for forbidden in (
        "finalDecisionEV(",
        "postflopDecisionAlternativeSummary(",
        "recommended_ev_bb",
        "recommended_action",
        "EV optimale",
        "meilleure EV",
    ):
        assert forbidden not in block, forbidden
        assert forbidden not in html, forbidden
    # Only the explicit negation survives in the rendered detail.
    assert "alternative EV Hero" in html
    assert "Aucune recommandation ni alternative EV Hero n’est appliquée" in html
    assert "Aucune alternative EV validée" not in INDEX

    # 7. The runtime half proves each transition and the before/after range.
    proc = subprocess.run(
        ["node", "tests/trainer/opponent_analysis_state_runtime.js"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert '"status":"PASS"' in proc.stdout, proc.stdout + proc.stderr
    for state in ("ANALYSE_DISPONIBLE", "DONNEES_INSUFFISANTES", "SPOT_NON_SUPPORTE"):
        assert state in proc.stdout, proc.stdout

    print("opponent analysis-state contract: PASS")


if __name__ == "__main__":
    main()

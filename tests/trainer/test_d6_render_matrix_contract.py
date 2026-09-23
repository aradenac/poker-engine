#!/usr/bin/env python3
"""Contract for the D6 render-level regression matrix (#393 · task-backlog-2zi).

The real render-path checks live in ``tests/trainer/smoke_trainer_d6_render_matrix.py``
(Playwright, driven through ``smoke_trainer.py``). This module is the static
side of the guard:

- the five-case fixture stays the single source of the matrix and covers Cases
  A-E with the expected canonical state/gate;
- the driver is registered in ``smoke_trainer.py``'s ``DRIVER_SMOKES`` (so the
  frozen ``Validate interactive trainer`` browser-smoke job executes it) and the
  workflow keeps both its single entrypoint and the ``tests/trainer/**`` path
  trigger;
- the driver actually drives the real ``trainerRenderRecommendation()`` /
  ``trainerPreflopDecisionSummaryHtml()`` / ``trainerRenderFeedback()`` path and
  reads the ``#trainerRecommendation`` / ``#trainerFeedback`` DOM;
- a node dry-run maps every fixture decision through the real shared module and
  checks the expected gate/state before the browser smoke ever runs.

It is a representation/render contract only: no model/fit is touched.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / "tests/trainer/smoke_trainer_d6_render_matrix.py"
DRIVER_SOURCE = DRIVER.read_text(encoding="utf-8")
SMOKE_TRAINER = (ROOT / "tests/trainer/smoke_trainer.py").read_text(encoding="utf-8")
WORKFLOW = (ROOT / ".github/workflows/trainer-smoke.yml").read_text(encoding="utf-8")
FIXTURE = json.loads((ROOT / "tests/trainer/fixtures/d6_render_matrix.json").read_text(encoding="utf-8"))

NODE_SCRIPT = r"""
const fs=require('fs');
const src=fs.readFileSync('site/trainer.js','utf8');
const start=src.indexOf('function trainerAnalysisModule(');
const end=src.indexOf('function trainerDetailFromPreflopDecision(');
if(start<0||end<0)throw new Error('trainer analysis helpers missing');
const helpers=src.slice(start,end);
const State=require('./src/analytics/analysis-state.js');
const LABELS={
  ANALYSE_DISPONIBLE:'Analyse disponible',ANALYSE_PARTIELLE:'Analyse partielle',
  CALCUL_EN_COURS:'Calcul en cours',DONNEES_INSUFFISANTES:'Données insuffisantes',
  SPOT_NON_SUPPORTE:'Spot non supporté',ERREUR_CALCUL:'Erreur de calcul'
};
const window={PokerAnalysisState:State,PokerReviewInbox:{analysisStateLabel:state=>LABELS[String(state||'').toUpperCase()]||'Analyse indisponible'}};
const factory=new Function('window',helpers+'\nreturn {trainerPreflopDecisionView,trainerPreflopTaxonomyLabel};');
const api=factory(window);
const fixture=JSON.parse(fs.readFileSync('tests/trainer/fixtures/d6_render_matrix.json','utf8'));
const result={};
for(const c of fixture.cases){
  const view=api.trainerPreflopDecisionView(c.decision);
  if(view.show_ev!==c.expect.show_ev)throw new Error(c.name+' show_ev '+view.show_ev);
  if(view.taxonomy_state!==c.expect.taxonomy_state)throw new Error(c.name+' state '+view.taxonomy_state);
  if(api.trainerPreflopTaxonomyLabel(c.decision)!==c.expect.taxonomy_label)throw new Error(c.name+' label');
  result[c.name]={show_ev:view.show_ev,state:view.taxonomy_state,label:view.taxonomy_label};
}
console.log(JSON.stringify({status:'PASS',schema:State.SCHEMA,cases:result}));
"""


def main() -> None:
    # 1. Single matrix fixture, five ordered cases A-E.
    assert FIXTURE["schema"] == "trainer-d6-render-matrix/v1", FIXTURE.get("schema")
    cases = FIXTURE["cases"]
    assert [c["name"][0] for c in cases] == ["A", "B", "C", "D", "E"], [c["name"] for c in cases]
    for case in cases:
        expect = case["expect"]
        assert isinstance(expect["show_ev"], bool), case["name"]
        assert expect["taxonomy_state"] in {
            "ANALYSE_DISPONIBLE", "ANALYSE_PARTIELLE", "CALCUL_EN_COURS",
            "DONNEES_INSUFFISANTES", "SPOT_NON_SUPPORTE", "ERREUR_CALCUL",
        }, case["name"]

    # 2. Only Cases D exposes the recommendation; A-C/E fail closed.
    assert [c["expect"]["preserve_recommendation"] for c in cases] == [False, False, False, True, False], cases

    # 3. The driver drives the real render path and reads the real DOM, and
    #    covers both the fail-closed and the preserved Case D branches.
    for needle in (
        "def static_guards()",
        "trainerRenderRecommendation()",
        "trainerPreflopDecisionSummaryHtml(decision)",
        "trainerRenderFeedback()",
        "#trainerRecommendation",
        "#trainerFeedback",
        "data-analysis-detail",
        "def assert_fail_closed(",
        "def assert_open_case(",
        "action recommandée",
    ):
        assert needle in DRIVER_SOURCE, needle
    # A local covered-only recombination is explicitly rejected by the driver.
    assert 'assert "isCovered" not in recommendation' in DRIVER_SOURCE
    assert "covered alone must never gate" in DRIVER_SOURCE

    # 4. Orchestration: the driver runs from smoke_trainer.py, which the frozen
    #    workflow invokes, and tests/trainer/** stays a path trigger.
    driver_block = SMOKE_TRAINER.split("DRIVER_SMOKES = (", 1)[1].split("\n)", 1)[0]
    assert "smoke_trainer_d6_render_matrix.py" in driver_block
    main_block = SMOKE_TRAINER.split('if __name__ == "__main__":', 1)[1]
    assert "run_driver_smokes()" in main_block
    assert "run: python3 tests/trainer/smoke_trainer.py" in WORKFLOW
    assert WORKFLOW.count("'tests/trainer/**'") == 2, "tests/trainer/** must stay in push and pull_request triggers"

    # 5. Node dry-run: every fixture decision maps to the declared gate/state
    #    through the real shared module, before the browser smoke runs.
    proc = subprocess.run(
        ["node", "-e", NODE_SCRIPT],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["status"] == "PASS", payload
    assert payload["schema"] == "poker-analysis-state/v1", payload
    for case in cases:
        row = payload["cases"][case["name"]]
        assert row["show_ev"] is case["expect"]["show_ev"], payload
        assert row["state"] == case["expect"]["taxonomy_state"], payload
        assert row["label"] == case["expect"]["taxonomy_label"], payload

    print("D6 render matrix contract: PASS")


if __name__ == "__main__":
    main()

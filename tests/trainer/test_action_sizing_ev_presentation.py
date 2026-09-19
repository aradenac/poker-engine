#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


def main() -> int:
    audit=json.loads((ROOT/"audit/action-sizing-ev-render-duplication.json").read_text(encoding="utf-8"))
    assert audit["schema"]=="central-ui-action-sizing-ev-duplication-audit/v1"
    assert audit["decision"]=="EXTRACTION_JUSTIFIED"
    assert audit["findings"]["shared_rendering"]["primary_summary"]["real_consumer_count"]>=2
    assert audit["findings"]["shared_rendering"]["alternatives_strip"]["real_consumer_count"]>=2
    assert audit["extraction"]["asset"]=="site/action-sizing-ev.js"
    assert audit["scientific_effect"]=="NONE_CENTRAL_UI_REFACTOR_ONLY"

    index=(ROOT/"site/index.html").read_text(encoding="utf-8")
    trainer=(ROOT/"site/trainer.js").read_text(encoding="utf-8")
    shared=(ROOT/"site/action-sizing-ev.js").read_text(encoding="utf-8")
    assert '<script src="./action-sizing-ev.js"></script>' in index
    assert "DecisionActionSizingEV.primarySummaryHtml" in index
    assert "DecisionActionSizingEV.alternativesStripHtml" in index
    assert "TrainerActionSizingEV.primarySummaryHtml" in trainer
    assert "TrainerActionSizingEV.alternativesStripHtml" in trainer
    assert "TrainerActionSizingEV.qualityFromEV" in trainer
    assert "selects_action:false" in shared
    assert "recomputes_ev:false" in shared
    assert "recomputes_sizing:false" in shared
    assert "recomputes_incremental_cost:false" in shared
    assert "validator:'#299'" in shared

    subprocess.run(["node","--check","site/action-sizing-ev.js"],cwd=ROOT,check=True)
    subprocess.run(["node","tests/trainer/action_sizing_ev_parity.js"],cwd=ROOT,check=True)
    subprocess.run(["node","tests/analytics/test_recommendation_consistency.js"],cwd=ROOT,check=True)
    print("action+sizing+EV CENTRAL-UI extraction contract: PASS")
    return 0


if __name__=="__main__":
    raise SystemExit(main())

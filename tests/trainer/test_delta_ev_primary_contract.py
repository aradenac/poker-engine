#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX = (ROOT / "site/index.html").read_text(encoding="utf-8")
TRAINER = (ROOT / "site/trainer.js").read_text(encoding="utf-8")
SHARED = (ROOT / "site/action-sizing-ev.js").read_text(encoding="utf-8")


def main() -> None:
    # Primary decision UX is explicitly EV-loss first.
    assert 'function qualityFromEV(summary)' in SHARED
    primary = SHARED.split('function primarySummaryHtml', 1)[1].split('function alternativesStripHtml', 1)[0]
    assert primary.index("card('Perte EV'") < primary.index("card('Joué'")
    assert '`ΔEV ${deltaText} · ${qualityText}`' in primary
    assert 'withinNoise' in SHARED.split('function qualityFromEV', 1)[1].split('function primarySummaryHtml', 1)[0]

    # No heuristic /10 badge is rendered by feed or modal primary/advanced surfaces.
    feed = INDEX.split('function actionAnalysisHtml', 1)[1].split('function safeActionAnalysisHtml', 1)[0]
    modal = INDEX.split('function actionDetailModalInnerHtml', 1)[1].split('function openActionDetailModal', 1)[0]
    assert 'formatScore(' not in feed
    assert 'actionScoreMeta(' not in feed
    assert 'actionDecisionSummaryBadge(' not in modal
    assert 'actionVerdictBadge(' not in modal
    assert 'scoreGrid' not in modal

    # History review no longer applies arbitrary high/medium/low EV-loss bands.
    assert 'function reviewLossClass(r)' in INDEX
    assert 'r.totalLossBB>=5' not in INDEX
    assert 'r.totalLossBB>=1.5' not in INDEX
    assert 'Perte EV cumulée' in INDEX

    # Trainer qualitative labels are derived from the shared EV/uncertainty helper.
    trainer_class = TRAINER.split('function trainerDecisionClass', 1)[1].split('function trainerRecordDecision', 1)[0]
    assert 'TrainerActionSizingEV.qualityFromEV' in trainer_class
    assert 'loss<=.15' not in TRAINER
    assert 'loss<=.5' not in TRAINER
    assert 'loss<=0.15' not in TRAINER
    assert 'd.withinNoise=!!played?.withinNoise' in TRAINER

    # Scientific/raw analysis stays intact: UX changes do not delete score or export payloads.
    assert 'score:Number(raw.score)' in INDEX
    assert 'decision_summary:aiExportPlain(decisionSummary)' in INDEX
    assert 'review_value:aiExportPlain(review)' in INDEX

    print("delta EV primary UX contract checks: OK")


if __name__ == "__main__":
    main()

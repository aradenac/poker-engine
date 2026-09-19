#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX = (ROOT / "site/index.html").read_text(encoding="utf-8")
TRAINER = (ROOT / "site/trainer.js").read_text(encoding="utf-8")
SHARED = (ROOT / "site/action-sizing-ev.js").read_text(encoding="utf-8")


def main() -> None:
    # Feed, modal and trainer must all speak the same compact decision contract.
    assert 'function decisionCanonicalSummary(stepIndex,step,cached=null)' in INDEX
    assert 'schema:"decision-summary/v1"' in INDEX
    assert '<script src="./action-sizing-ev.js"></script>' in INDEX
    assert 'data-decision-summary-schema="${SUMMARY_SCHEMA}"' in SHARED
    assert 'decisionPrimarySummaryHtml(canonicalDecision,{compact:true})' in INDEX
    assert 'decisionPrimarySummaryHtml(canonicalDecision)' in INDEX
    assert 'function trainerDecisionCanonical(detail,row)' in TRAINER
    assert 'TrainerActionSizingEV.primarySummaryHtml(summary,{compact:true,escapeHtml,formatBB})' in TRAINER

    # Primary hierarchy: played/recommended/sizing/EV/delta before diagnostics.
    for label in ('Perte EV', 'Joué', 'Recommandé', 'EV jouée', 'Meilleure EV'):
        assert label in SHARED, f"missing primary decision label: {label}"
    assert '`ΔEV ${deltaText} · ${qualityText}`' in SHARED
    assert '<summary>Pourquoi ? / Détails avancés</summary>' in INDEX
    assert '<summary>Pourquoi ? / Détails avancés</summary>' in TRAINER
    assert '<details class="action-advanced" open>' not in INDEX
    assert '<details class="action-advanced" open>' not in TRAINER

    # Alternatives keep their own sizing and are shown in descending EV order.
    assert 'sort((a,b)=>finalDecisionEV(b)-finalDecisionEV(a)).map(a=>' in INDEX
    assert 'actionSizingAmountLabel(a,raw)' in INDEX
    assert 'Alternatives · meilleure EV d’abord' in INDEX

    # Review records expose recommendation sizing to the trainer instead of
    # losing it when the analyzer detail is copied out of the replayer.
    assert 'bestCostBB:Number.isFinite(Number(summary.best?.costBB))' in INDEX
    assert 'decisionSummary:decisionCanonicalSummary(stepIndex,step,cached)' in INDEX
    assert 'Perte EV effective après incertitude' in TRAINER

    print("decision summary contract checks: OK")


if __name__ == "__main__":
    main()

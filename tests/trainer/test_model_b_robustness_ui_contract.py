#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def main() -> None:
    index = (ROOT / "site/index.html").read_text(encoding="utf-8")
    adapter = (ROOT / "site/analytics/model-b-robustness.js").read_text(encoding="utf-8")

    assert 'hero-model-b-robustness-summary/v1' in adapter
    assert 'hero-model-b-robustness-ui-envelope/v1' in adapter
    assert '["robust","sensitive","insufficiently_supported"]' in adapter
    assert 'weighted!==false' in adapter
    assert 'SUPPORT_OR_COMPARABILITY_INCOMPLETE' in adapter
    assert 'IDENTITY_MISMATCH' in adapter
    assert 'DECISION_ID_MISMATCH' in adapter

    for field in ("population_id", "pack_id", "strategy_id", "strategy_version", "ev_reference"):
        assert field in adapter

    # This UI adapter consumes the backend classification and must not re-run Model B.
    for forbidden in (
        "evaluate_robustness",
        "response_to_price_context_environment_sets",
        "quasi_dominant_regret_bb",
        "probability",
        "posterior_probability",
    ):
        assert forbidden not in adapter, forbidden

    script = '<script src="./analytics/model-b-robustness.js"></script>'
    assert script in index
    assert index.index(script) < index.index('<script src="./preflop-contract.js"></script>')

    # CENTRAL-UI surfaces: feed/replayer detail, Review Inbox, export.
    assert 'modelBRobustnessCompactHtml(robustness)' in index
    assert 'modelBRobustnessDetailHtml(robustness)' in index
    assert 'robustnessText=modelBRobustnessStatusText(robustness)' in index
    assert 'model_b_robustness:aiExportPlain(modelBRobustnessEnvelopeForDecision' in index
    assert 'model_b_robustness_identity:aiExportPlain(reviewInboxScopeInput())' in index

    # UI must distinguish nominal value, MC uncertainty and Model-B uncertainty.
    assert "EV nominale" in index
    assert "Incertitude Monte-Carlo" in index
    assert "Incertitude Model B" in index
    assert "Enveloppe non pondérée" in index

    # Fragile aggression is diagnostic, not a strategy verdict.
    assert 'modelBRobustnessFragilityLine("Shove"' in index
    assert 'modelBRobustnessFragilityLine("Overbet"' in index
    assert "Diagnostic de sensibilité uniquement, pas un verdict de stratégie." in index

    # Missing evidence is explicitly fail-closed rather than silently robust.
    assert "Robustesse Model B non établie" in adapter
    assert "Support Model B insuffisant" in adapter
    assert "L’interface ne conclut donc pas à la robustesse." in index

    # Evidence survives review refresh without recomputation.
    assert "modelBRobustnessAttachExisting(String(hand.id),reg,i)" in index
    assert "modelBRobustnessAttachExisting(String(hand.id),reg,a.stepIndex)" in index

    # Exact backend envelope ingestion is available to the product/runtime.
    assert "window.setModelBRobustnessEnvelope=setModelBRobustnessEnvelope" in index
    assert 'reason:"EXACT_IDENTITY_AND_DECISION"' in index

    print("Model B robustness CENTRAL-UI contract checks: OK")

if __name__ == "__main__":
    main()

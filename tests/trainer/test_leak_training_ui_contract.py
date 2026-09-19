#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def main() -> None:
    source = (ROOT / "src/training/leak-scenario-selector.js").read_text(encoding="utf-8")
    runtime = (ROOT / "site/training/leak-scenario-selector.js").read_text(encoding="utf-8")
    assert runtime == source

    index = (ROOT / "site/index.html").read_text(encoding="utf-8")
    trainer = (ROOT / "site/trainer.js").read_text(encoding="utf-8")

    target_script = '<script src="./analytics/leak-training-target.js"></script>'
    selector_script = '<script src="./training/leak-scenario-selector.js"></script>'
    trainer_script = '<script src="./trainer.js"></script>'
    assert target_script in index and selector_script in index and trainer_script in index
    assert index.index(target_script) < index.index(selector_script) < index.index(trainer_script)

    assert "S’entraîner sur ce leak" in index
    for element_id in (
        "trainerTargetPanel", "trainerTargetPosition", "trainerTargetStreet", "trainerTargetSpot",
        "trainerTargetAction", "trainerTargetSizing", "trainerTargetJam", "trainerTargetOverbet",
        "trainerTargetSessionSize", "trainerTargetApplyBtn", "trainerTargetClearBtn",
        "trainerTargetSupport", "trainerTargetSummary",
    ):
        assert f'id="{element_id}"' in index, element_id

    # UI/runtime calls the merged contracts; selector/aggregation semantics are not copied here.
    assert "Target.buildTrainingTarget" in trainer
    assert "Target.compileScenarioCriteria" in trainer
    assert "Target.scenarioMatchesCriteria" in trainer
    assert "Selector.buildSessionPlan" in trainer
    assert "Selector.summarizePlannedSession" in trainer
    assert "function buildSessionPlan(" not in trainer
    assert "function summarizePlannedSession(" not in trainer
    assert "function scenarioMatchesCriteria(" not in trainer

    # Exact identity is propagated into the runtime selector.
    assert 'identity:trainerTargetClone(target.identity)' in trainer
    assert 'trainerTargetAssertCurrentIdentity(target)' in trainer
    for identity_field in ("population_id", "pack_id", "strategy_id", "strategy_version", "ev_reference"):
        assert identity_field in trainer

    # Fail closed: unsupported exact context gets no alternate selection.
    assert "INSUFFICIENT_SUPPORTED_SCENARIOS" in trainer
    assert "aucune substitution silencieuse" in trainer
    assert "PREFLOP_NOT_MATERIALIZED_BY_CURRENT_TRAINER" in trainer
    assert "SPOT_FAMILY_NOT_MATERIALIZED_BY_CURRENT_TRAINER" in trainer

    # Guided / Training / Test stay first-class modes.
    assert '["guided","training","test"]' in trainer
    assert 'data-trainer-mode="guided"' in index
    assert 'data-trainer-mode="training"' in index
    assert 'data-trainer-mode="test"' in index

    # Targeted session uses backend summary and exposes spots + DeltaEV without long-term claims.
    assert "spots_played" in trainer
    assert "total_delta_ev_loss_bb" in trainer
    assert "within_session_change" in trainer
    assert "progression long terme non inférée" in trainer
    assert "trainerTargetEvent(detail,row,actual)" in trainer

    # Review Dashboard CTA forwards the exact target descriptor to the Trainer runtime.
    assert 'window.trainerOpenTargetedSession(cta.target)' in index
    assert "window.trainerOpenTargetedSession=trainerOpenTargetedSession" in trainer

    print("leak-to-training UI/runtime contract checks: OK")

if __name__ == "__main__":
    main()

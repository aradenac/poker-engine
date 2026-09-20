#!/usr/bin/env python3
"""String contract for the #391 smoke orchestration.

The numeric browser smokes of #391 must be driven by
``tests/trainer/smoke_trainer.py`` (via ``run_driver_smokes``) and must NOT
come back as dedicated steps in ``.github/workflows/trainer-smoke.yml``. The
frozen workflow runs every ``tests/trainer/test_*.py`` in its static-contract
job, so this module is the guard that keeps the single-entrypoint shape:

- no step (nor any other reference) to ``smoke_opponent_range_numeric.py`` or
  ``smoke_equity_scale_invariance.py`` may exist in the workflow;
- ``smoke_trainer.py`` must list both scripts in ``DRIVER_SMOKES`` and actually
  execute them from its ``__main__`` entry point.

It is a representation/orchestration contract only: no model/fit, no equity
semantics and no immutable repro evidence is touched.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = (ROOT / ".github/workflows/trainer-smoke.yml").read_text(encoding="utf-8")
SMOKE_TRAINER = (ROOT / "tests/trainer/smoke_trainer.py").read_text(encoding="utf-8")
DOC = (ROOT / "docs/opponent-range-display-contract.md").read_text(encoding="utf-8")

# The two numeric browser smokes that smoke_trainer.py must orchestrate.
ORCHESTRATED_SMOKES = (
    "tests/trainer/smoke_opponent_range_numeric.py",
    "tests/trainer/smoke_equity_scale_invariance.py",
)


def flat(text: str) -> str:
    """Collapse line wrapping so phrase assertions are stable."""
    return " ".join(text.split())


def main() -> None:
    # The workflow stays frozen: neither script is referenced, as a `run:` step
    # or anywhere else. Reintroducing a step that calls one of them fails here.
    for script in ORCHESTRATED_SMOKES:
        assert script not in WORKFLOW, script
    for script_name in ("smoke_opponent_range_numeric.py", "smoke_equity_scale_invariance.py"):
        assert script_name not in WORKFLOW, script_name

    # The single frozen entrypoint that drives them is still exercised.
    assert "run: python3 tests/trainer/smoke_trainer.py" in WORKFLOW

    # smoke_trainer.py owns the orchestration: both scripts are registered as
    # driver smokes...
    driver_block = SMOKE_TRAINER.split("DRIVER_SMOKES = (", 1)[1].split("\n)", 1)[0]
    for script_name in ("smoke_opponent_range_numeric.py", "smoke_equity_scale_invariance.py"):
        assert script_name in driver_block, script_name
    assert "def run_driver_smokes() -> None:" in SMOKE_TRAINER
    assert "subprocess.run([sys.executable, str(script)], check=True)" in SMOKE_TRAINER

    # ...and they are actually launched from the script entry point, so a
    # registered-but-never-run driver smoke fails here too.
    main_block = SMOKE_TRAINER.split('if __name__ == "__main__":', 1)[1]
    assert "run_driver_smokes()" in main_block

    # The display-contract verification section documents that orchestration.
    doc_flat = flat(DOC)
    assert "tests/trainer/smoke_trainer.py" in doc_flat
    assert "orchestrated by" in doc_flat
    assert "tests/trainer/smoke_opponent_range_numeric.py" in doc_flat
    assert "tests/trainer/smoke_equity_scale_invariance.py" in doc_flat

    print("smoke orchestration contract checks: OK")


if __name__ == "__main__":
    main()

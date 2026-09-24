#!/usr/bin/env python3
"""String contract for the #391 / #394 smoke orchestration.

The numeric browser smokes of #391 and the desktop modes smoke of #394 must be
driven by ``tests/trainer/smoke_trainer.py`` (via ``run_driver_smokes``) and
must NOT come back as dedicated steps in
``.github/workflows/trainer-smoke.yml``. The frozen workflow runs every
``tests/trainer/test_*.py`` in its static-contract job, so this module is the
guard that keeps the single-entrypoint shape:

- no step (nor any other reference) to ``smoke_opponent_range_numeric.py``,
  ``smoke_equity_scale_invariance.py`` or ``smoke_modes_desktop.py`` may exist in
  the workflow;
- ``smoke_trainer.py`` must list the three scripts in ``DRIVER_SMOKES`` and
  actually execute them from its ``__main__`` entry point.

It is a representation/orchestration contract only: no model/fit, no equity
semantics and no immutable repro evidence is touched.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = (ROOT / ".github/workflows/trainer-smoke.yml").read_text(encoding="utf-8")
SMOKE_TRAINER = (ROOT / "tests/trainer/smoke_trainer.py").read_text(encoding="utf-8")
MODES_SMOKE = (ROOT / "tests/trainer/smoke_modes_desktop.py").read_text(encoding="utf-8")
DOC = (ROOT / "docs/opponent-range-display-contract.md").read_text(encoding="utf-8")
# #394 T7: the desktop modes fit evidence. The frozen browser job can only run
# in CI, so this versioned artefact is what a reviewer reads; it must stay
# present and keep carrying the measured contract.
FIT_EVIDENCE = ROOT / "docs/desktop-modes-fit-evidence.md"

# The browser smokes that smoke_trainer.py must orchestrate: the two numeric
# smokes of #391 and the desktop modes smoke / overflow audit of #394.
ORCHESTRATED_SMOKES = (
    "tests/trainer/smoke_opponent_range_numeric.py",
    "tests/trainer/smoke_equity_scale_invariance.py",
    "tests/trainer/smoke_modes_desktop.py",
)

ORCHESTRATED_SMOKE_NAMES = tuple(Path(script).name for script in ORCHESTRATED_SMOKES)


def flat(text: str) -> str:
    """Collapse line wrapping so phrase assertions are stable."""
    return " ".join(text.split())


def main() -> None:
    # The workflow stays frozen: neither script is referenced, as a `run:` step
    # or anywhere else. Reintroducing a step that calls one of them fails here.
    for script in ORCHESTRATED_SMOKES:
        assert script not in WORKFLOW, script
    for script_name in ORCHESTRATED_SMOKE_NAMES:
        assert script_name not in WORKFLOW, script_name

    # The single frozen entrypoint that drives them is still exercised.
    assert "run: python3 tests/trainer/smoke_trainer.py" in WORKFLOW

    # smoke_trainer.py owns the orchestration: every script is registered as a
    # driver smoke...
    driver_block = SMOKE_TRAINER.split("DRIVER_SMOKES = (", 1)[1].split("\n)", 1)[0]
    for script_name in ORCHESTRATED_SMOKE_NAMES:
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
    for script in ORCHESTRATED_SMOKES:
        assert script in doc_flat, script

    # The #394 desktop modes smoke is not a stub: it measures both reference
    # viewports for the six modes, fails explicitly on an overflow with the
    # measured values, drives the transition journeys from the real UI and fails
    # (instead of skipping) when Playwright is unavailable.
    assert 'MODES = ("home", "spotlab", "review", "replayer", "training", "strategy")' in MODES_SMOKE
    assert "VIEWPORTS = ((1500, 1000), (1366, 768))" in MODES_SMOKE
    assert 'result["scrollHeight"] <= result["clientHeight"]' in MODES_SMOKE
    assert "mode={mode} viewport={width}x{height}" in MODES_SMOKE
    assert "smoke_modes_desktop: Playwright is unavailable" in MODES_SMOKE
    for marker in (
        "#hhFileInput",  # the repro fixture goes through the real HH import
        "#hhHands .review-inbox-open",  # the hand is opened from the Review inbox
        "#replayerBackBtn",  # Replayer → Review
        'button.mode-card[data-app-view="spotlab"]',
        'button.mode-card[data-app-view="training"]',
        '#quickNav a[data-product-domain="strategy"]',  # embedded #strategyPage shell
        'a.mode-card[data-app-view="strategy"]',  # navigation to ./hero-ranges.html
        'page.keyboard.press("Tab")',
        'page.keyboard.press("ArrowRight")',
        'page.keyboard.press("Enter")',
    ):
        assert marker in MODES_SMOKE, marker

    # #394 T2 — the Review import surface reachability is contractual, not an
    # implementation detail: the smoke measures each import target with
    # `document.elementFromPoint` at the centre of its box (target or descendant
    # must receive the point) and confirms it with a Playwright
    # `locator.click(trial=True)` hit-test, at empty hands and at both reference
    # viewports, before the fixture import. This guard is additive: it only adds
    # required tokens, so none of the checks above (nor the T7 fit evidence
    # below) is removed or weakened.
    for token in ("reachability", "hit-test"):
        assert token in MODES_SMOKE, token
    # The vocabulary alone is not enough (a comment could keep it alive): the
    # measured hit-test and the Playwright click trial must be the real calls.
    assert "document.elementFromPoint(x, y)" in MODES_SMOKE
    assert ".click(trial=True" in MODES_SMOKE
    assert "def _assert_import_surface_hit_testable(" in MODES_SMOKE
    assert "def _assert_import_surface_click_trial(" in MODES_SMOKE
    assert "await _assert_import_surface_click_trial(" in MODES_SMOKE
    import_surface_block = MODES_SMOKE.split("IMPORT_SURFACE_SELECTORS = (", 1)[1].split(")", 1)[0]
    for selector in (
        "#reviewImportTab",
        'label[for="hhFileInput"]',
        ".hh-import-advanced > summary",
        "#hhWatchBtn",
    ):
        assert selector in import_surface_block, selector
    # The verdict is measured in the Review step of the two-viewport journey,
    # twice (closed details, then advanced details open), and the Import tab is
    # activated by a real click whose `aria-selected` flip is asserted.
    import_measurements = MODES_SMOKE.count("await _assert_import_surface_hit_testable(")
    assert import_measurements >= 2, import_measurements
    assert 'await page.click("#reviewImportTab")' in MODES_SMOKE
    assert 'await page.get_attribute("#reviewImportTab", "aria-selected")' in MODES_SMOKE
    assert "state.hhHands.length === 0" in MODES_SMOKE
    # Both measurements live in the per-viewport journey, and that journey is
    # still driven for each reference viewport.
    run_viewport_block = MODES_SMOKE.split("async def run_viewport(", 1)[1]
    assert run_viewport_block.count("await _assert_import_surface_hit_testable(") >= 2
    run_block = MODES_SMOKE.split("async def run() -> None:", 1)[1]
    assert "for width, height in VIEWPORTS:" in run_block
    assert "run_viewport(browser, url, width, height, audit)" in run_block

    # The verdict must stay *measured*: the JS hit-test has to expose the
    # individual conditions (viewport, shell, hit, who received the point) and the
    # raised assertion has to print them, so a failure is always actionable and
    # "explicit with the measured values" cannot decay into a bare boolean.
    measured_blocks = flat(MODES_SMOKE)
    for js_field in ("const inViewport", "const inShell", "hit:", "reachable:", "atTag:"):
        assert js_field in measured_blocks, js_field
    for reported in ("rect=", "innerViewport=", "elementFromPoint=", "point=", "shellBox="):
        assert reported in measured_blocks, reported

    # The #394 T7 fit evidence is versioned and contractual: since the frozen
    # browser job only runs in CI, this artefact is what a reviewer reads. It
    # must document the exact commands, the real HEAD, both reference viewports,
    # the per-mode scrollHeight/clientHeight audit, a verdict, and the explicit
    # note that ./hero-ranges.html is navigated but out of the shell contract
    # (no no-scroll assertion there).
    assert FIT_EVIDENCE.is_file(), FIT_EVIDENCE
    evidence_flat = flat(FIT_EVIDENCE.read_text(encoding="utf-8"))
    assert "python3 tests/trainer/smoke_modes_desktop.py" in evidence_flat
    assert "python3 tests/trainer/smoke_trainer.py" in evidence_flat
    assert "git rev-parse HEAD" in evidence_flat
    assert "1500x1000" in evidence_flat and "1366x768" in evidence_flat
    assert "scrollHeight" in evidence_flat and "clientHeight" in evidence_flat
    for mode in ("home", "spotlab", "review", "replayer", "training", "strategy"):
        assert mode in evidence_flat, mode
    assert "verdict" in evidence_flat.casefold()
    assert "hero-ranges.html" in evidence_flat
    assert "hors contrat" in evidence_flat.casefold()

    print("smoke orchestration contract checks: OK")


if __name__ == "__main__":
    main()

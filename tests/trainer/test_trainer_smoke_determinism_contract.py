#!/usr/bin/env python3
"""Deterministic guard contract for the #409 Trainer browser smoke.

The Trainer smoke used to be non-reproducible: the hand was drawn from an
uncontrolled source, so a red run could not be replayed, and the "Mode Test"
hidden-answer invariant could be satisfied by an unrelated, already-ended hand.
#409 pins the whole scripted session to a printed seed and keeps the two
invariants strictly separated.

This module is the source-level guard for that contract. It is picked up by the
frozen ``static-contract`` job of ``.github/workflows/trainer-smoke.yml`` (which
runs every ``tests/trainer/test_*.py``) and fails if any of the following
regresses:

1. ``tests/trainer/smoke_trainer.py`` loses the ``TRAINER_SMOKE_SEED`` constant
   (including its ``TRAINER_SMOKE_SEED`` environment override), the
   ``window.trainerSetSeed(...)`` injection performed before the first hand is
   dealt, or the printed / snapshotted seed.
2. A bypass is reintroduced: ``if hand.ended: trainerNewHand()`` or a silent
   hand-regeneration / retry loop between the seed injection and the Mode Test
   assertion.
3. The Mode Test / ``Réponse masquée`` invariant stops being asserted on a LIVE,
   non-terminal Hero decision, or the separate terminal ``Recommandation`` /
   ``—`` assertion is removed or merged into it.
4. ``.github/workflows/trainer-smoke.yml`` stops running the smoke exactly once
   through ``run: python3 tests/trainer/smoke_trainer.py`` (a retry wrapper or a
   second entrypoint would silently mask a red run).
5. ``site/trainer.js`` loses the #409 RNG block (``trainerSetSeed`` /
   ``trainerSetRandomSource`` / ``trainerResetRandomSource`` /
   ``trainerRandomSeed`` exposed on ``window``) or a direct ``Math.random()``
   reappears in the Trainer logic.
6. The reproducibility documentation disappears or stops mentioning the seed
   and its override.

Source contract only: no browser, no network, no model/fit/equity semantics.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SMOKE_PATH = ROOT / "tests/trainer/smoke_trainer.py"
TRAINER_PATH = ROOT / "site/trainer.js"
WORKFLOW_PATH = ROOT / ".github/workflows/trainer-smoke.yml"
DOC_PATH = ROOT / "docs/trainer-smoke-determinism.md"

CONTRACT_VERSION = "poker-trainer-smoke-determinism-contract/v1"

# ---------------------------------------------------------------------------
# (a) Seed contract inside tests/trainer/smoke_trainer.py
# ---------------------------------------------------------------------------
# The calibrated seed, overridable from the environment so a red CI run can be
# replayed locally without editing the code.
SEED_CONSTANT = 'TRAINER_SMOKE_SEED = int(os.environ.get("TRAINER_SMOKE_SEED", "39"))'
# The injection: the page must be seeded BEFORE the trainer is opened, hence
# before the first hand is dealt.
SEED_INJECTION = 'seeded = await page.evaluate("(seed) => window.trainerSetSeed(seed)", TRAINER_SMOKE_SEED)'
SEED_INJECTION_RETURN = "assert seeded == TRAINER_SMOKE_SEED, (seeded, TRAINER_SMOKE_SEED)"
SEED_LOG = 'print(f"trainer smoke seed: {TRAINER_SMOKE_SEED}", flush=True)'
SEED_SNAPSHOT = '"trainer_seed": TRAINER_SMOKE_SEED,'
SEED_OVERRIDE_SNAPSHOT = '"trainer_seed_env_override": os.environ.get("TRAINER_SMOKE_SEED"),'
# The trainer entry point (opening the Training domain) must come after the
# injection.
TRAINER_ENTRYPOINT = """await page.click('#quickNav [data-product-domain="training"]')"""

# ---------------------------------------------------------------------------
# (b) No bypass / silent regeneration before the Mode Test assertion
# ---------------------------------------------------------------------------
MODE_TEST_SELECTOR = '[data-trainer-mode="test"]'
MODE_TEST_CLICK = f"await page.click('{MODE_TEST_SELECTOR}')"
# The Mode Test invariant must be proven on a live, non-terminal Hero decision.
LIVE_HAND_GUARD = (
    "() => !!(trainerState.hand && !trainerState.hand.ended && trainerState.hand.awaitingHero)"
)
LIVE_GUARD_MESSAGES = (
    "Mode Test invariant must run on a live Hero decision",
    "Hero decision became terminal before the Mode Test invariant",
)
# Primitives that would silently regenerate the hand (or the seed) instead of
# failing loud when the calibrated seed stops exposing the expected spot.
FORBIDDEN_REGENERATION = (
    (r"trainerNewHand", "silent hand regeneration (trainerNewHand)"),
    (r"trainerBuildHand", "silent hand rebuild (trainerBuildHand)"),
    (r"trainerResetRandomSource", "seed reset inside the seeded session"),
    (r"^\s*while\s", "retry/regeneration loop (while)"),
    (r"^\s*for\s", "retry/regeneration loop (for)"),
    (r"location\.reload", "page reload used as a silent retry"),
    (r"ended\s*=\s*true", "hand forced terminal before the live invariant"),
)
# `if hand.ended: trainerNewHand()`-style bypasses, in Python or in-page JS.
BYPASS_PATTERNS = (
    r"(?:hand|h)\.ended[^\n]{0,160}trainerNewHand",
    r"trainerNewHand[^\n]{0,160}(?:hand|h)\.ended",
    r"if\s+(?:h|hand|trainerState\.hand)\.ended\s*:",
    r"if\s*\(\s*(?:trainerState\.)?hand\.ended\s*\)",
)

# ---------------------------------------------------------------------------
# (c) Terminal `Recommandation` / `—` assertion, kept separate
# ---------------------------------------------------------------------------
TERMINAL_EVALUATION = "terminal_recommendation = await page.evaluate("
# The section that follows the terminal case (the same-seed scenario probe), used
# to bound the terminal block without depending on its exact length.
TERMINAL_SECTION_END = "# #409 same-seed / same-scenario probe"
TERMINAL_ASSERTIONS = (
    'assert terminal_recommendation["label"] == "Recommandation", terminal_recommendation',
    'assert terminal_recommendation["main"] == "—", terminal_recommendation',
    'assert "hidden-answer" in terminal_recommendation["cls"], terminal_recommendation',
    'assert "mode test" not in folded(terminal_recommendation["text"]), terminal_recommendation',
    'assert "réponse masquée" not in folded(terminal_recommendation["text"]), terminal_recommendation',
)

# ---------------------------------------------------------------------------
# (d) Frozen workflow: single entrypoint, no retry wrapper
# ---------------------------------------------------------------------------
SINGLE_ENTRYPOINT_STEP = (
    "- name: Exercise Training view\n"
    "        run: python3 tests/trainer/smoke_trainer.py\n"
)
RETRY_TOKENS = (
    "continue-on-error",
    "retry",
    "--attempts",
    "max-attempts",
    "attempts:",
)
STATIC_CONTRACT_GLOB = "for test in tests/trainer/test_*.py; do"
STATIC_CONTRACT_RUNNER = 'python3 "$test"'

# ---------------------------------------------------------------------------
# (e) site/trainer.js RNG surface
# ---------------------------------------------------------------------------
SMOKE_SEED_START_MARKER = "/* #409-RNG-BLOCK-START */"
SMOKE_SEED_END_MARKER = "/* #409-RNG-BLOCK-END */"
SMOKE_SEED_API = (
    "const trainerDefaultRandom=()=>Math.random();",
    "function trainerRandom(){",
    "function trainerSetRandomSource(",
    "function trainerSetSeed(",
    "function trainerResetRandomSource(",
    "function trainerRandomSeed(",
)
SMOKE_SEED_WINDOW_EXPORTS = (
    "window.trainerSetRandomSource=trainerSetRandomSource;",
    "window.trainerSetSeed=trainerSetSeed;",
    "window.trainerResetRandomSource=trainerResetRandomSource;",
    "window.trainerRandomSeed=trainerRandomSeed;",
)

# ---------------------------------------------------------------------------
# (f) Reproducibility documentation
# ---------------------------------------------------------------------------
DOC_REQUIREMENTS = (
    "TRAINER_SMOKE_SEED",
    "TRAINER_SMOKE_SEED=",
    "trainerSetSeed",
    "Seed retenue",
    "tests/trainer/smoke_trainer.py",
)


def flat(text: str) -> str:
    """Collapse line wrapping so phrase assertions are stable."""
    return " ".join(text.split())


def rng_block(text: str) -> str:
    """Return the delimited #409 RNG block, markers included."""
    start = text.index(SMOKE_SEED_START_MARKER)
    end = text.index(SMOKE_SEED_END_MARKER, start + len(SMOKE_SEED_START_MARKER))
    return text[start : end + len(SMOKE_SEED_END_MARKER)]


def check(smoke: str, workflow: str, trainer: str, doc: str) -> None:
    smoke_flat = flat(smoke)

    # ------------------------------------------------------------------
    # (a) The seed constant, its override, the injection and its logging.
    # ------------------------------------------------------------------
    assert SEED_CONSTANT in smoke, "the calibrated TRAINER_SMOKE_SEED constant (with env override) is required"
    assert "import os" in smoke, "the seed env override requires `import os`"
    assert SEED_INJECTION in smoke, "the smoke must inject the seed through window.trainerSetSeed(...)"
    assert SEED_INJECTION_RETURN in smoke, SEED_INJECTION_RETURN
    assert SEED_LOG in smoke, "the smoke must print the seed so a failure is reproducible"
    assert SEED_SNAPSHOT in smoke, "the snapshot must journal the seed"
    assert SEED_OVERRIDE_SNAPSHOT in smoke, "the snapshot must journal the TRAINER_SMOKE_SEED override"
    # No bare literal seed may be injected instead of the constant.
    assert re.search(r"trainerSetSeed\(\s*\d", smoke) is None, "trainerSetSeed must receive TRAINER_SMOKE_SEED, not a literal"

    seed_idx = smoke.index(SEED_INJECTION)
    entry_idx = smoke.index(TRAINER_ENTRYPOINT)
    assert seed_idx < entry_idx, "the seed must be injected before the trainer is opened"

    # ------------------------------------------------------------------
    # (b) No silent regeneration / retry before the Mode Test assertion.
    # ------------------------------------------------------------------
    assert MODE_TEST_CLICK in smoke, "the Mode Test invariant must still switch to the test mode"
    test_mode_idx = smoke.index(MODE_TEST_CLICK)
    pre_invariant = smoke[seed_idx:test_mode_idx]

    for pattern, label in FORBIDDEN_REGENERATION:
        assert re.search(pattern, pre_invariant, re.MULTILINE) is None, f"forbidden in the seeded session: {label}"
    for pattern in BYPASS_PATTERNS:
        assert re.search(pattern, smoke) is None, f"forbidden bypass pattern: {pattern}"

    # ------------------------------------------------------------------
    # (c) The live-hand Mode Test invariant, THEN the separate terminal case.
    # ------------------------------------------------------------------
    for message in LIVE_GUARD_MESSAGES:
        assert message in smoke, message
    assert smoke.count(LIVE_HAND_GUARD) >= 2, "the live Hero decision must be guarded before both mode switches"
    assert smoke[:test_mode_idx].count(LIVE_HAND_GUARD) >= 1, "the Mode Test must run on a live, non-terminal Hero decision"
    assert "réponse masquée" in smoke_flat and "mode test" in smoke_flat, "the hidden-answer surfaces must stay asserted"

    assert TERMINAL_EVALUATION in smoke, "the terminal `Recommandation` / `—` assertion must exist"
    terminal_idx = smoke.index(TERMINAL_EVALUATION)
    assert terminal_idx > test_mode_idx, "the terminal case must stay separate from (and after) the Mode Test invariant"
    for assertion in TERMINAL_ASSERTIONS:
        assert assertion in smoke, assertion
    # The terminal placeholder is asserted on an explicit synthetic ended state,
    # never by replaying the invariant on an ended hand.
    assert TERMINAL_SECTION_END in smoke, TERMINAL_SECTION_END
    terminal_block = smoke[terminal_idx : smoke.index(TERMINAL_SECTION_END, terminal_idx)]
    assert "h.ended=true" in terminal_block, "the terminal case must use an explicit synthetic ended hand"
    assert MODE_TEST_CLICK not in terminal_block, "the terminal case must not re-run the Mode Test switch"

    # ------------------------------------------------------------------
    # (d) Frozen workflow: one entrypoint, no retry wrapper, still globbed.
    # ------------------------------------------------------------------
    assert workflow.count("run: python3 tests/trainer/smoke_trainer.py") == 1, (
        "trainer-smoke.yml must keep exactly one smoke entrypoint"
    )
    assert SINGLE_ENTRYPOINT_STEP in workflow, SINGLE_ENTRYPOINT_STEP
    assert len(re.findall(r"run:.*smoke_trainer", workflow)) == 1, "no second run step may invoke the smoke"
    for token in RETRY_TOKENS:
        assert token not in workflow, f"no retry wrapper is allowed around the smoke: {token}"
    # This contract itself must stay executed by the static-contract job.
    assert STATIC_CONTRACT_GLOB in workflow, STATIC_CONTRACT_GLOB
    assert STATIC_CONTRACT_RUNNER in workflow, STATIC_CONTRACT_RUNNER
    rel = Path(__file__).resolve().relative_to(ROOT).as_posix()
    assert re.fullmatch(r"tests/trainer/test_[^/]*\.py", rel), rel

    # ------------------------------------------------------------------
    # (e) site/trainer.js: seedable RNG surface, no direct Math.random.
    # ------------------------------------------------------------------
    assert trainer.count(SMOKE_SEED_START_MARKER) == 1, "exactly one RNG block start marker is required"
    assert trainer.count(SMOKE_SEED_END_MARKER) == 1, "exactly one RNG block end marker is required"
    block = rng_block(trainer)
    logic = trainer.replace(block, "", 1)
    for api in SMOKE_SEED_API:
        assert api in block, api
    for export in SMOKE_SEED_WINDOW_EXPORTS:
        assert export in block, export
    assert len(re.findall(r"Math\.random\s*\(", block)) == 1, "the block must call Math.random exactly once (default source)"
    assert len(re.findall(r"Math\.random\s*\(", trainer)) == 1, "Math.random() must not be called outside the RNG block"
    assert logic.count("Math.random") == 0, "no direct Math.random may be reintroduced in the Trainer logic"
    assert "trainerRandom()" in logic, "Trainer logic must draw through the single trainerRandom() entry point"

    # ------------------------------------------------------------------
    # (f) Reproducibility documentation (seed + override + pointer).
    # ------------------------------------------------------------------
    doc_flat = flat(doc)
    for requirement in DOC_REQUIREMENTS:
        assert requirement in doc_flat or requirement in doc, requirement
    assert "39" in doc, "the calibrated seed value must be documented"
    assert "docs/trainer-smoke-determinism.md" in smoke_flat, "the smoke must point at the reproduction documentation"


def main() -> None:
    assert SMOKE_PATH.exists(), SMOKE_PATH
    assert TRAINER_PATH.exists(), TRAINER_PATH
    assert WORKFLOW_PATH.exists(), WORKFLOW_PATH
    assert DOC_PATH.exists(), f"the reproducibility documentation is required: {DOC_PATH}"
    check(
        smoke=SMOKE_PATH.read_text(encoding="utf-8"),
        workflow=WORKFLOW_PATH.read_text(encoding="utf-8"),
        trainer=TRAINER_PATH.read_text(encoding="utf-8"),
        doc=DOC_PATH.read_text(encoding="utf-8"),
    )
    print(f"{CONTRACT_VERSION} checks: OK")


if __name__ == "__main__":
    main()

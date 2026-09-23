#!/usr/bin/env python3
"""Static + runtime contract for the #409 seedable Trainer randomness source.

The Trainer used to draw randomness with a bare ``Math.random()`` scattered
across its logic, which made a session impossible to replay. #409 funnels every
draw through a single, seedable ``trainerRandom()`` entry point and exposes an
injection surface (``trainerSetRandomSource`` / ``trainerSetSeed`` /
``trainerResetRandomSource`` / ``trainerRandomSeed``) so tests and reproductions
can pin the sequence without monkey-patching the global ``Math.random``.

This module is the versioned regression contract for that surface:

1. Source contract. The ``site/trainer.js`` RNG block is delimited by the
   explicit ``#409-RNG-BLOCK-START`` / ``#409-RNG-BLOCK-END`` markers, defines
   the four documented APIs plus ``trainerRandom`` / ``trainerMulberry32`` /
   ``trainerNormalizeSeed``, exposes them on ``window``, and is the *only* place
   ``Math.random`` may appear. Any reappearance of ``Math.random`` outside the
   block (a direct draw reintroduced in the Trainer logic) fails the contract,
   and every converted consumer must keep routing through ``trainerRandom()``.
2. Runtime contract. ``tests/trainer/trainer_rng_determinism.js`` extracts that
   block verbatim and executes it in Node (no DOM) to prove same-seed
   determinism, distinct-seed divergence, injection through
   ``trainerSetRandomSource`` and restoration through
   ``trainerResetRandomSource``.

``node --check`` is run on the production bundle and the runtime script so a
syntax regression is caught before the CI static-contract job fails at the
JavaScript syntax step.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRAINER_PATH = ROOT / "site" / "trainer.js"
TRAINER = TRAINER_PATH.read_text(encoding="utf-8")

CONTRACT_VERSION = "poker-trainer-rng-determinism-contract/v1"

START_MARKER = "/* #409-RNG-BLOCK-START */"
END_MARKER = "/* #409-RNG-BLOCK-END */"

# The complete #409 API surface, defined inside the delimited block.
RNG_API = (
    "function trainerMulberry32(",
    "function trainerNormalizeSeed(",
    "const trainerDefaultRandom=()=>Math.random();",
    "function trainerRandom(){",
    "function trainerSetRandomSource(",
    "function trainerSetSeed(",
    "function trainerResetRandomSource(",
    "function trainerRandomSeed(",
)

# The same surface stays exposed to the page so tests/reproductions can inject a
# deterministic generator through `window`.
RNG_WINDOW_EXPORTS = (
    "window.trainerSetRandomSource=trainerSetRandomSource;",
    "window.trainerSetSeed=trainerSetSeed;",
    "window.trainerResetRandomSource=trainerResetRandomSource;",
    "window.trainerRandomSeed=trainerRandomSeed;",
)

# Trainer consumers must draw through `trainerRandom()`; these are the call
# sites that used to call `Math.random()` directly and must not regress.
RNG_CONSUMERS = (
    "function trainerRandomInt(n){return Math.floor(trainerRandom()*n);}",
    '(trainerRandom()<.5?"PFA":"CALLER")',
    "let x=trainerRandom()*total;",
)

RUNTIME_SCRIPT = "tests/trainer/trainer_rng_determinism.js"


def rng_block(text: str) -> str:
    """Return the delimited #409 RNG block, including both markers."""
    start = text.index(START_MARKER)
    end = text.index(END_MARKER, start + len(START_MARKER))
    return text[start : end + len(END_MARKER)]


def main() -> None:
    # The block must be uniquely delimited so the runtime extraction is stable.
    assert TRAINER.count(START_MARKER) == 1, "exactly one RNG block start marker is required"
    assert TRAINER.count(END_MARKER) == 1, "exactly one RNG block end marker is required"
    block = rng_block(TRAINER)
    # Everything outside the block is the Trainer logic that must never draw
    # randomness directly. Removing the block once leaves `logic` byte-for-byte
    # equal to the surrounding Trainer source.
    logic = TRAINER.replace(block, "", 1)

    # ------------------------------------------------------------------
    # 1. The #409 API is present, defined inside the block and exported.
    # ------------------------------------------------------------------
    for api in RNG_API:
        assert api in block, api
    for export in RNG_WINDOW_EXPORTS:
        assert export in block, export

    # The default production source is the single, explicit `Math.random`
    # wrapper; it is also the documented reset target.
    assert "trainerResetRandomSource(){trainerRandomSource=trainerDefaultRandom;" in block

    # ------------------------------------------------------------------
    # 2. No direct `Math.random()` in the Trainer logic.
    # ------------------------------------------------------------------
    # The only `Math.random()` *call* in the whole bundle is the default source
    # inside the delimited block; prose may mention the name, a call may not.
    assert "const trainerDefaultRandom=()=>Math.random();" in block
    assert len(re.findall(r"Math\.random\s*\(", block)) == 1, "the block must call Math.random exactly once (its default source)"
    assert len(re.findall(r"Math\.random\s*\(", TRAINER)) == 1, "Math.random() must not be called anywhere but the default source"
    # Any mention of `Math.random` outside the block, comment or call, fails the
    # contract: a direct draw reintroduced in the Trainer logic.
    assert logic.count("Math.random") == 0, "Math.random must not be reintroduced in the Trainer logic"
    assert "Math.random(" not in logic

    # Converted consumers keep drawing through the single `trainerRandom`.
    for consumer in RNG_CONSUMERS:
        assert consumer in logic, consumer
    assert "trainerRandom()" in logic

    # ------------------------------------------------------------------
    # 3. Runtime proof: node --check and execute the extracted RNG block.
    # ------------------------------------------------------------------
    for script in ("site/trainer.js", RUNTIME_SCRIPT):
        subprocess.run(["node", "--check", script], cwd=ROOT, check=True)

    proc = subprocess.run(
        ["node", RUNTIME_SCRIPT],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    assert "trainer rng determinism: PASS" in proc.stdout, proc.stdout

    print(f"{CONTRACT_VERSION} checks: OK")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]

for src, site in (
    ("src/training/nlhe-game-state.js", "site/training/nlhe-game-state.js"),
    ("src/training/preflop-runtime.js", "site/training/preflop-runtime.js"),
    ("src/training/preflop-decision-adapter.js", "site/training/preflop-decision-adapter.js"),
    ("src/preflop/decision.js", "site/preflop-decision.js"),
    ("src/preflop/guidance.js", "site/preflop-guidance.js"),
):
    assert (ROOT / src).read_bytes() == (ROOT / site).read_bytes(), f"browser copy drift: {src} != {site}"

proc = subprocess.run(
    ["node", "tests/trainer/preflop_runtime_contract.js"],
    cwd=ROOT, text=True, capture_output=True
)
assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
assert '"status":"PASS"' in proc.stdout, proc.stdout
print(proc.stdout.strip())

#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / ".project" / "STATUS.md"
MARKER = "## Production opponent model A — integrated analyzer population model"
SECTION = r'''## Trainer performance optimization

Issues #21–#24 are completed and merged. The optimization intentionally preserves v83 recommendation semantics, candidate sets, Monte-Carlo trial counts and Model A/B data.

Implemented changes:

- #21 / PR #25 / `4c1027b6e6e7372c9a77ad7ee7ef1788986b5c74`: Training/Test no longer perform a hidden Model A evaluation before Hero can act; those modes evaluate once after the action. Guided still evaluates before action and reuses the already-computed verdict when Hero plays the exact recommended action/sizing.
- #24 / PR #26 / `948490fccc033d4434d68468cfa73c78e74611dc`: Model A/B trainer assets are fetched/parsed during browser idle time without activating them in analyser state, and deliberate UI waits were reduced from 160/220/180 ms to configurable 20/35/25 ms delays.
- #22 / PR #27 / `a060e8f83dd71860d0f2d5d39f1fe7ab26a195e2`: a bounded 96-entry trainer-local LRU caches exact completed verdicts, deep-copies entries, normalizes only the synthetic evaluation hand ID, and invalidates when either promoted Model A object identity changes.
- #23 / PR #28 / `ce77ca4de84dc37f4177e2c4412ad905dc7b45dd`: the existing v83 Web-Worker review path is now parallelized only while Training is open: 1 worker below 4 logical CPUs, 2 from 4, 3 from 8; outside Training it remains strictly sequential. Sizing results are restored to deterministic task order before finalization.

Performance instrumentation now records evaluation count/reuse, last/total evaluation time, model-load/warmup timing and verdict-cache hits/misses. If latency remains problematic, measure these counters first before considering any reduction in EV accuracy or Monte-Carlo trials.

Permanent regression coverage includes:

- `tests/trainer/test_trainer_latency_contract.py`;
- `tests/trainer/test_trainer_preload_contract.py`;
- `tests/trainer/test_trainer_result_cache_contract.py`;
- `tests/trainer/test_trainer_parallel_review_contract.py`;
- `.github/workflows/trainer-smoke.yml` browser smoke.

'''

text = PATH.read_text(encoding="utf-8")
if SECTION in text:
    print("status already patched")
    raise SystemExit(0)
if text.count(MARKER) != 1:
    raise SystemExit("status insertion marker not unique")
text = text.replace(MARKER, SECTION + MARKER, 1)
PATH.write_text(text, encoding="utf-8")
print("trainer performance status recorded")

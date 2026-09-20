# Global compute scheduler — implementation benchmark

Reproduce from the repository root (Node >=22; measured with v24.21.0):

```sh
git show HEAD:site/index.html > /tmp/compute-before.html
node --test --test-isolation=none tests/compute/scheduler.test.cjs
python3 tests/compute/mutations.py
node tests/compute/benchmark.cjs /tmp/compute-before.html
```

The baseline file should be taken from the parent revision of this implementation.
Raw measurements: `analysis/performance/compute-scheduler-node.json`.

The harness uses the production main-equity worker kernel, byte-compares it with
that baseline, and dispatches eight jobs from five priority classes. Inputs use
hero cards and preflop/flop boards from two checked-in PokerStars HH fixtures
(`hand_262024556922`, `kts_sb_two_limp_iso4_three_calls`), with a fixed small
opponent range and 2,000 trials. Seed 390 is injected into the **test worker only**.
This is a small orchestration benchmark, not a full imported-history UI benchmark
or a scientific model test. The baseline dispatches the same eight jobs without
admission control; it does not reproduce every old UI pool's launch timing.

| Metric | Uncoordinated baseline | Global scheduler |
|---|---:|---:|
| Maximum admitted workers | 8 | 2 |
| Batch elapsed | 92.42 ms | 203.24 ms |
| Maximum Node timer delay | 0.67 ms | 0.91 ms |
| Node timer delays >50 ms | 0 | 0 |

All eight numerical outputs were identical. Seven logical preemptions occurred,
with one background pause/resume. Completion takes longer under the conservative
CPU budget. Node timer delays are **not browser Long Tasks**.

Six regression tests pass. Four mutations (remove global cap, remove background
cap, reverse priorities, ignore Training hold) are killed by behavioral tests.
The Training regression exercises the real batch function with the Training
hold active and verifies its explicit computation completes.

Browser smoke is provided in `tests/compute/smoke_browser.py`: serve `site/` on
port 8765, then run it with Python Playwright and Chromium installed. It submits
concurrent production worker jobs while dispatching keyboard interactions and
reports runtime metrics. Execution was blocked here: no installed Playwright or
Chromium; npm installation failed with `EAI_AGAIN registry.npmjs.org`.
Browser long-task statistics and full realistic-history navigation latency remain
unmeasured; this change is not validated for browser acceptance yet.

## Runtime contract and limits

`window.POKER_COMPUTE_CONFIG = {maxWorkers: 2}` may be set before loading
`compute-scheduler.js` (bounded to 1–8). Two is the global total, including at most
one background worker. Every production worker factory uses the singleton.
`window.pokerComputeScheduler.snapshot()` exposes queue lengths per class, active
workers, maximum concurrency, wait/duration samples, cancellations, preemptions,
background transitions, browser Long Tasks >50 ms and input-to-next-frame timing.
Samples retain the latest 512 observations to bound memory.

A higher-priority job can terminate and restart lower-priority work using its
unchanged payload. Obsolete replay jobs use the existing cancellation path;
changing hands also cancels the historical batch. Training uses explicit priority,
while its view holds background scoring. Review automatically considers only the
selected and currently visible hands; scrolling requests the newly visible rows.
“Analyser tout” explicitly opts into traversing the loaded history, still at
background priority and with the same suspension rules.

Review preparation yields between decisions, restoring shared UI state before
each yield. Training prepares only its last Hero decision. A single decision's
snapshot construction and the existing replay preparation can still exceed the
50 ms target on a large model; browser profiling is required to establish whether
finer subdivision/off-thread preparation is necessary. Existing production kernels
use `Math.random` without a seed API; seeded equality is demonstrated by the test
harness, not claimed as a new runtime seeded reproducibility contract.

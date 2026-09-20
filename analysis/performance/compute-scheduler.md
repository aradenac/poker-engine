# Global compute scheduler — implementation benchmark

Reproduce from the repository root (Node >=22; measured with v24.21.0):

```sh
git archive --format=tar --output=/tmp/issue-390-baseline.tar 441327e8a5b78fc54cedfd3f49c275f9e65071ff site/index.html
mkdir -p /tmp/issue-390-baseline
tar -xf /tmp/issue-390-baseline.tar -C /tmp/issue-390-baseline
node --test --test-isolation=none tests/compute/scheduler.test.cjs
python3 tests/compute/mutations.py
node tests/compute/benchmark.cjs /tmp/issue-390-baseline/site/index.html
```

The pinned baseline revision is the integrated parent immediately before #390.
Raw measurements: `analysis/performance/compute-scheduler-node.json`.

The harness uses the production main-equity worker kernel, byte-compares it with
that baseline, and dispatches sixteen jobs from five priority classes. Inputs use
hero cards and flop boards from sixteen real PokerStars HHs extracted from the
checked-in certified increment archive; the derived manifest is persisted as
`analysis/performance/compute-scheduler-corpus.json`. Each job uses a fixed small
opponent range and 4,000 trials. Seed 390 is injected into the **test worker only**.
This is an orchestration benchmark, not a scientific model test. The baseline dispatches the same sixteen jobs without
admission control; it does not reproduce every old UI pool's launch timing.

| Metric | Uncoordinated baseline | Global scheduler |
|---|---:|---:|
| Maximum admitted workers | 16 | 2 |
| Batch elapsed | 260.71 ms | 484.34 ms |
| Maximum Node timer delay | 5.14 ms | 1.06 ms |
| Node timer delays >50 ms | 0 | 0 |

All sixteen numerical outputs were identical. Four logical preemptions occurred,
with one background pause/resume. Completion takes longer under the conservative
CPU budget. Node timer delays are **not browser Long Tasks**.

Twelve regression tests pass. Four mutations (remove global cap, remove background
cap, reverse priorities, ignore Training hold) are killed by behavioral tests.
The Training regression exercises the real batch function with the Training
hold active and verifies its explicit computation completes.

Browser smoke is provided in `tests/compute/smoke_browser.py`: serve `site/` on
port 8765, then run it with Python Playwright and Chromium installed. It submits
concurrent production worker jobs while dispatching keyboard interactions and
reports runtime metrics. Execution was blocked here: no installed Playwright or
Chromium. `python3 tests/compute/smoke_browser.py` fails at import with
`ModuleNotFoundError: No module named 'playwright'`; the locked-environment check
`python3 tools/repro_ci_browser.py verify` also reports both Playwright 1.55.0 and
Chromium 140.0.7339.16/revision 1187 absent. Structured evidence is persisted in
`analysis/performance/compute-scheduler-browser.json`.
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

A higher-priority job can terminate and restart one lower-priority work item per
waiting candidate, only when the global worker budget is full. Interaction holds
stop new background admission without restarting a background worker already in
flight. Obsolete replay jobs use the existing cancellation path;
changing hands also cancels the historical batch. Training uses explicit priority,
while its view holds background scoring. Review automatically considers only the
selected and currently visible hands; scrolling requests the newly visible rows.
“Analyser tout” explicitly opts into traversing the loaded history, still at
background priority and with the same suspension rules.

Review preparation builds replay steps and opponents once, then yields between
decisions and restores shared UI state before each yield. Holds resume at the
same decision instead of discarding the plan. Training prepares only its last Hero decision. A single decision's
snapshot construction and the existing replay preparation can still exceed the
50 ms target on a large model; browser profiling is required to establish whether
finer subdivision/off-thread preparation is necessary. Existing production kernels
use `Math.random` without a seed API; seeded equality is demonstrated by the test
harness, not claimed as a new runtime seeded reproducibility contract.

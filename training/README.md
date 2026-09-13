# Continuous Training and Calibration

This directory stores the reproducible learning state of the poker engine.

## Goals

- accumulate evidence instead of replacing it;
- make every promoted model reproducible;
- distinguish raw data, derived datasets, runs, evaluation and promoted models;
- allow rollback and comparison between generations.

## Structure

- `datasets/` — immutable dataset manifests and curated dataset versions.
- `runs/` — one directory per training/calibration run.
- `models/` — promoted or candidate model artifacts and metadata.
- `evaluations/` — benchmark results, holdout results and comparison reports.
- `gates/` — normalized evidence snapshots for promotion/non-regression decisions.
- `PROMOTION_GATE_CONTRACT.json` — versioned, pre-specified thresholds and holdout rules used before any promoted pointer may advance.
- `registry.json` — small source-of-truth index pointing to the active/promoted state.

## Run contract

Every run should record at least:

- `run_id`;
- creation date/time;
- input dataset IDs and exact versions/checksums;
- parent model/run, when incremental;
- code/application version or commit SHA;
- algorithm/calibration version;
- parameters/hyperparameters;
- random seed when applicable;
- sample counts and filtering rules;
- metrics before/after;
- regression-suite result;
- produced artifacts;
- promotion decision and rationale.

## Promotion gate contract

`tools/evaluate_promotion_gates.py` consumes a normalized `poker-promotion-evidence/v1` document and emits `poker-promotion-gate-report/v1`.

The gate vocabulary is deliberately strict:

- `PASS` — required evidence exists and satisfies the pre-specified contract;
- `FAIL` — evidence exists and violates a required gate;
- `BLOCKED` — required evidence does not yet exist;
- `NOT_APPLICABLE` — the check is outside this transition, for example deployment verification before a new site release is attempted.

A rejected candidate is not itself a failed training cycle. `RETAIN_BASELINE` is a valid explicit outcome when the candidate and comparison evidence are persisted. Conversely, missing candidate artifacts, missing paired comparisons, missing strategy baselines or reuse of TEST for selection must never be interpreted as a pass.

Use `--require-ready` only at the actual promotion boundary. It returns a non-zero exit code unless the aggregate gate is `PASS`; `registry.json` must remain unchanged before that point. The current cycle evidence is kept under `gates/` so outstanding blockers remain machine-readable rather than living only in issue prose.

Strategy TEST is a final confirmation holdout. Selection and retuning use VALIDATION; after the finalist is frozen, TEST may confirm or reject it but must not be used to choose another candidate in the same cycle.

## Continuous-improvement rule

A new run may learn from all approved historical data plus newly added evidence. It must not silently mutate a previous run or promoted model. Promotion is explicit: candidate results are compared with the current reference on stable regression and holdout sets before `registry.json` is advanced.

## Data-volume note

Git is appropriate for code, manifests, compact JSON/CSV outputs and moderate datasets. If raw hand histories or generated artifacts become large, store immutable manifests/checksums in Git and move bulk payloads to a suitable large-file/object store rather than bloating repository history.

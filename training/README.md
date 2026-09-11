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

## Continuous-improvement rule

A new run may learn from all approved historical data plus newly added evidence. It must not silently mutate a previous run or promoted model. Promotion is explicit: candidate results are compared with the current reference on stable regression and holdout sets before `registry.json` is advanced.

## Data-volume note

Git is appropriate for code, manifests, compact JSON/CSV outputs and moderate datasets. If raw hand histories or generated artifacts become large, store immutable manifests/checksums in Git and move bulk payloads to a suitable large-file/object store rather than bloating repository history.

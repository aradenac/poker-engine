# Prospective temporal validation

Issue #202 adds an evaluation layer beyond the historical TRAIN / VALIDATION / TEST split: freeze one candidate and its fit provenance first, then evaluate it later on hand histories that provably did not participate in that fit.

This tranche defines protocol infrastructure only. It does not freeze the current #107/#108 candidate, create a real holdout generation, admit real hand histories, run a prospective evaluation, or consume any existing TEST/VALIDATION ledger.

## Lifecycle

`training/prospective/PROTOCOL.json` defines four states:

1. `UNCONSUMED` — candidate, pack, models, strategy, code, fit dataset, fit hand-ID universe, metrics, thresholds and temporal boundary are fingerprinted. Prospective HH may be appended, but none is consumed by evaluation or TRAIN.
2. `EVALUATING` — the hand ledger is frozen. Evaluation may read exactly that ledger under the precommitted metrics and thresholds; every hand remains ineligible for TRAIN.
3. `CLOSED` — evaluation is immutable and content-addressed. Its report separately classifies population drift, coverage and performance.
4. `RELEASED_TO_FUTURE_TRAIN` — only after closure may the same HH become eligible for a separately identified future TRAIN cycle.

The prospective holdout can therefore never train the candidate it evaluates.

## Candidate and fit precommit

Before the admission boundary, the manifest freezes:

- source commit;
- candidate ID, artifact hash and pack hash;
- Model A/B and strategy hashes;
- candidate-fit dataset hash and candidate-fit hand-ID fingerprint;
- fingerprint of the complete prior known hand-ID universe;
- protocol, metrics and threshold hashes;
- `fit.completed_at`, `frozen_at`, `cutoff_utc` and `admission_not_before_utc`.

The validator enforces:

`fit.completed_at <= frozen_at <= cutoff_utc < admission_not_before_utc`

The protocol hash must also equal the canonical hash of the versioned protocol file, so a manifest cannot claim an unrelated digest.

## Append-only prospective ledger

Each HH records an immutable `hand_id`, payload SHA-256, observed timestamp, first-seen timestamp and a content-addressed novelty proof.

That novelty proof must bind to both:

- the frozen prior hand-ID universe, with `absent_from_prior_hand_ids=true`;
- the frozen candidate-fit hand-ID universe, with `absent_from_candidate_fit_hand_ids=true`.

This explicitly proves that a prospective HH is not merely new to the ledger; it is absent from the fit of the candidate it evaluates.

While `UNCONSUMED`, new HH may only be appended and existing rows cannot be rewritten. Transition to `EVALUATING` freezes the ledger completely. No hand can be added, removed or mutated during evaluation/closure.

Every non-initial manifest links to the exact canonical previous object through `previous_manifest_sha256`.

## Temporal provenance

A prospective HH fails validation when:

- its observed time predates `admission_not_before_utc`;
- its first-seen time predates the admission boundary;
- its first-seen time predates its observed time;
- its novelty proof is not tied to the frozen prior and fit fingerprints;
- evaluation starts before all admitted HH have been first seen.

This establishes the auditable order:

`fit complete -> candidate frozen -> cutoff -> admission -> HH observed/first seen -> evaluation -> closure -> future TRAIN release`

## Fail-closed evaluation report

`EVALUATING` contains a start timestamp but no result. `CLOSED` requires a content-addressed report with exactly three independent classifications:

- `population_drift`;
- `coverage`;
- `performance`.

The metric and threshold definitions are part of the immutable precommit, so reading the holdout cannot silently redefine the gate.

## Release to a future TRAIN

Before release, every hand must have `train_eligible=false`.

`CLOSED -> RELEASED_TO_FUTURE_TRAIN` requires:

- persisted `evaluation.closed_at`;
- `training_transition.released_at >= evaluation.closed_at`;
- a non-empty `next_training_cycle_id`;
- no hand-set changes;
- the only allowed row mutation: `train_eligible: false -> true`.

The later TRAIN is a new scientific cycle with a different candidate identity. Nothing retroactively changes the fit of the evaluated candidate.

## Commands

Validate one ledger snapshot:

    python3 tools/validate_prospective_holdout.py path/to/manifest.json

Validate an append-only transition:

    python3 tools/validate_prospective_holdout.py current.json --previous previous.json

Run the fail-closed protocol tests:

    python3 tests/training/test_prospective_holdout.py

## Concurrency boundary

This tranche owns only the new `training/prospective/` protocol, its validator, tests and documentation. It does not edit lane-A #107/#108 contracts/workflows/holdout ledgers, lane-H runtime/UI files, population promotion pointers or any existing TEST data.

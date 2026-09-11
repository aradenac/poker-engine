# Persistence conventions

## Source of truth

GitHub `main` is the durable project state. Chat attachments and sandbox files are temporary until committed here.

## Audience separation

- `user/`: directly useful to the user.
- `.project/`: assistant/tool continuity and internal working state.
- `tools/`: reusable technical utilities.
- `training/`: reproducible learning evidence and model state.
- `tests/`: assertions and permanent regression evidence.

## Versioning

Application releases: `poker_range_equity_offline_multiway_vNN.html`.

Training run IDs: `YYYYMMDD-HHMM_<purpose>_<short-id>` when time precision is useful, or `YYYYMMDD_<purpose>_<short-id>` otherwise.

Dataset IDs: descriptive immutable name plus version, e.g. `nlhe_100_200_population_v1`.

## Training immutability

A completed run directory is immutable. Corrections create a new run. A promoted model is never overwritten in place.

## Required training provenance

Each run must identify:

- exact input dataset versions/checksums;
- parent run/model if incremental;
- Git commit SHA or application version;
- parameters and filters;
- sample counts;
- evaluation metrics;
- generated artifacts;
- promotion/rejection decision.

## Status discipline

`.project/STATUS.md` describes what is true now.
`.project/PLAN.md` describes what should happen next.
`.project/HANDOFF.md` describes how another session resumes safely.

Do not use those files as historical logs. Durable history belongs in Git commits, decision records and training run artifacts.

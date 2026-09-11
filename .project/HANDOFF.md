# Handoff Protocol

This file is intentionally tool-oriented. It tells a future assistant/session how to resume work without relying on chat history.

## Resume sequence

1. Read `.project/STATUS.md` for the current baseline and validated findings.
2. Read `.project/PLAN.md` for the ordered work plan.
3. Read `training/registry.json` for the active dataset/model/run references.
4. Inspect the latest files under `user/releases/`, `training/runs/`, and `tests/regression/`.
5. Do not assume a newer chat attachment is authoritative unless it has been persisted and referenced by `STATUS.md` or the training registry.

## State update rule

At every meaningful milestone:

- update `.project/STATUS.md`;
- update `.project/PLAN.md` if priorities/order changed;
- append or update the relevant training registry entry;
- persist generated artifacts that are needed to reproduce or continue the work;
- record material design/calibration decisions under `.project/decisions/` when they are not obvious from code.

## User/tool separation

User-facing artifacts belong under `user/`.
Tool-only working state, diagnostics and continuity metadata belong under `.project/` or `tools/`.
Training evidence belongs under `training/` even when it is primarily consumed by tools, because it is part of the reproducible scientific state of the engine.

## Do not persist

- transient caches;
- duplicated exports that can be regenerated exactly;
- secrets, credentials or tokens;
- huge raw binaries without an explicit storage strategy;
- speculative results not tied to a reproducible run.

## Naming

Use immutable/versioned names for releases and training runs. Prefer ISO dates and explicit version identifiers over ambiguous names such as `latest2` or `final_final`.

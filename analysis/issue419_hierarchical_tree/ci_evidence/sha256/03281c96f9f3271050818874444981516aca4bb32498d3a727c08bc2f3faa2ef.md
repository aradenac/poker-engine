# #419 — CI evidence bundle (`poker-issue419-ci-evidence/v1`)

**`ci_observation.status = NOT_OBSERVED`.** This bundle records what the
authoritative GitHub Actions run must prove; it does **not** claim any green run
of `Execute issue 419 hierarchical exact tree`.

Every fact here was re-verified at source on 2026-09-26 (the local git object
store and the GitHub read API). It supersedes the uncommitted `task-backlog-zlb`
(T3) draft, which had no content-addressed layer and asserted a PR-body
correction that never happened.

## Why no run can exist yet

The workflow `.github/workflows/issue-419-hierarchical-exact-tree.yml`
(`blob a1ac5061…`, `sha256 375a0cda…`, 12705 bytes) is present at the worktree
HEAD `5be7239` but **absent** at the current remote PR head `d087b5c`
(`git cat-file -e d087b5c:.github/workflows/issue-419-hierarchical-exact-tree.yml`
→ `ABSENT`). The branch is 11 commits ahead of `origin/…` and has not been
pushed, so neither the `push`/`synchronize` event nor the `workflow_dispatch`
fallback is reachable from this worker. There is no run of this workflow at any
head.

## The runs actually recorded at the reviewed PR head `d087b5c`

These are the four **pull_request**-triggered runs at `d087b5c` — all
`success`, and **none** executes a #419 suite:

| workflow | run | conclusion | URL |
| --- | --- | --- | --- |
| Project state consistency | #153 | success | https://github.com/aradenac/poker-engine/actions/runs/36196040214 |
| Validate preflop context contract | #257 | success | https://github.com/aradenac/poker-engine/actions/runs/36196040196 |
| Validate sequential independent arena | #977 | success | https://github.com/aradenac/poker-engine/actions/runs/36196040257 |
| Persisted dataset integrity | #627 | success | https://github.com/aradenac/poker-engine/actions/runs/36196040256 |

The same SHA carries one further `push`-triggered run — Validate sequential
independent arena #976 (https://github.com/aradenac/poker-engine/actions/runs/36196031300)
— which also does not run the #419 suites. The missing coverage is the blocker
raised by the independent review.

## Post-push verification checklist (only then → `PASS`)

1. PR #420 `head.sha != d087b5c72619b5279a674045e18dda2c3807e1b5`.
2. The new head carries `.github/workflows/issue-419-hierarchical-exact-tree.yml`.
3. A run named `Execute issue 419 hierarchical exact tree` exists for that head
   with `conclusion=success`.
4. Its no-op-guard step prints `#419 no-op guard: 15/15 suites executed`.

No local replay, declarative file, PR body or PR comment may promote the status.

## Failure mode → suite that executes it

| failure mode | executed by |
| --- | --- |
| frozen protocol / hash drift | `tests/training/test_frozen_validation_protocol.py` + `_v2` |
| TRAIN / VALIDATION / TEST boundary | the same two suites + `tools/training/validation_order_guard.py` |
| support laundering | `tests/simulation/test_issue419_exact_tree_preflight.py` + `tests/preflop/test_model_a_sizing_hierarchical.py` |
| nearest-price / nearest-context | `tests/simulation/test_issue419_exact_tree_preflight.py` + `tests/test_github_workflow_audit.py` (drift / substitution / rename negatives) |
| candidate / pointer identity | `tests/training/test_hierarchical_candidate_contract.py` |
| preflight semantics | `tests/simulation/test_issue419_exact_tree_preflight.py` |
| terminal decision incoherence | `tests/training/test_hierarchical_terminal_decision.py` |

## Local replay — NON AUTHORITATIVE

All 15 suites plus the compile step, the workflow-inventory regeneration, the
active-workflow DAG check, the terminal-decision check and
`issue419_exact_tree_preflight.py --check` return `0` in this sandbox. Those
results are a **non-authoritative** local replay: they are not merge evidence and
are never a substitute for the GitHub Actions run at the pushed head.

## Frozen-evidence correction and PR body

The 13 frozen digests are re-verified unchanged at HEAD (see
`frozen_digests_reverified_at_head`), with `issue419_exact_tree_preflight.py
--check` → `PASS` and the v2 bundle still reproducible. The frozen-evidence
integrity correction is recorded in
`analysis/issue419_hierarchical_tree/evidence_integrity_correction/` (`f601d619…`)
and in `.project/decisions/20260926-hierarchical-frozen-evidence-correction.md`.

The PR #420 body **still** announces `Independent review status: PASS` while the
independent review of `d087b5c` is `NEEDS_FIXES`. That is the verified state; the
correction is owned by **T2** (`backlog-1vz`) and is **not** applied here. This
bundle makes no claim that the body was corrected.

Entry point: `python3 tools/simulation/issue419_exact_tree_preflight.py --check`.
Artifact digests are in `ARTIFACTS.json` and `CI_EVIDENCE.sha256`.

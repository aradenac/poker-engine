# Machine-readable project state

Issue #206 separates administrative completion from capability delivery. A closed issue, a successful build, or publication metadata is not sufficient evidence that a capability is scientifically selected, integrated, promoted, or live.

## Canonical delivery states

The ordered states are:

1. `CONTRACT_READY` — contract, schema, infrastructure, or reproducible boundary exists.
2. `SCIENTIFICALLY_SELECTED` — a candidate/artifact has been selected under its declared scientific gate.
3. `PRODUCT_INTEGRATED` — the selected capability is wired into the user-facing/runtime product.
4. `PROMOTED` — the integrated artifact is the promoted/default repository or release identity.
5. `LIVE` — the exact promoted identity has explicit canonical-production proof.

`.project/capabilities.json` is the machine-readable inventory. Each capability declares its current state, versioned evidence, optional higher-state blockers, and optional administrative mismatch metadata.

## Deterministic STATUS

`.project/STATUS.md` is generated from the manifest plus the current versioned evidence. It contains no manual roadmap, chat-derived state, or generated timestamp.

Commands:

    python3 tools/validate_project_state.py
    python3 tools/validate_project_state.py --render-status
    python3 tools/validate_project_state.py --check-status
    python3 tools/validate_project_state.py --write-status
    python3 tests/test_project_state.py

`--render-status` prints the deterministic Markdown view.

`--check-status` regenerates the view in memory and fails if `.project/STATUS.md` differs byte-for-byte from it. This catches stale or manually edited recovery documentation.

`--write-status` is the safe repository update path. It refuses to write when versioned evidence validation is `FAIL`; `PASS` and explicitly acknowledged `WARN` states may be rendered.

Use `--status-path` only when testing or intentionally targeting another path inside the repository root. `--strict-warnings` preserves the phase-1 behavior where an acknowledged warning can be promoted to exit code 2.

## Contradictions stay visible

The generated view contains both higher-state blockers and acknowledged historical contradictions. They are not normalized away merely because an issue is closed.

Current examples include:

- #109 is closed with a historical `PRODUCT_INTEGRATED` claim, while the current trainer still contains the explicit flop-only Hero-decision boundary. The capability therefore remains `CONTRACT_READY` and the mismatch is tracked by #206.
- the legacy mixed v83 engine and assembled static application are `PROMOTED`, but `site/RELEASE.json` still records `UNVERIFIED_LIVE` / issue #45, so neither is represented as `LIVE`.

The validator never reopens historical issues and never infers state from GitHub or chat context.

## Remaining DoD gap

The repository now has deterministic generation and stale-file checking, but no dedicated CI workflow invokes `--check-status` yet. Under #225 that integration is intentionally left separate while lanes A/F own or audit workflow-sensitive areas. Until that final integration exists, #206 should remain open.

## Deterministic recovery state

The non-CI recovery layer closes the local/session handoff gap without treating chat history as project state. `.project/recovery-state.schema.json` defines `poker-recovery-state/v1`, and `tools/build_recovery_state.py` aggregates existing sources instead of reimplementing their rules:

- capability state and evidence are delegated to `tools/validate_project_state.py`;
- lane claims/releases/worklogs and FILES_INTENT validation are delegated to `tools/check_parallel_claims.py`;
- lane ownership/conflict groups come from `.project/parallel-agents.json`;
- GitHub issues, PRs and comments are read-only inputs.

Offline deterministic fixture:

    python3 tools/build_recovery_state.py \
      --github-export tests/fixtures/project-state/recovery/github-export.json \
      --render

Human recovery view:

    python3 tools/build_recovery_state.py \
      --github-export tests/fixtures/project-state/recovery/github-export.json \
      --human

Read-only live GitHub view:

    python3 tools/build_recovery_state.py \
      --repo aradenac/poker-engine \
      --human

The live adapter performs GET requests only. It reuses the comment reader from `check_parallel_claims.py`, reads `GITHUB_TOKEN` or `GH_TOKEN` only from the environment when available, and never embeds or writes a token.

A generated snapshot contains no generated timestamp. It records coverage explicitly. If comment coverage is incomplete, absence of a claim cannot prove a lane free and the lane becomes `UNKNOWN`. An open PR without a matching active claim also prevents a `FREE` conclusion.

Likewise, the tool does not infer that an open issue is safe merely because it appears in a lane's `typical_issues`. `next_safe_action` is:
- `CONTINUE_ACTIVE_CLAIM` when a unique active claim is proven;
- `CLAIM_OPEN_ISSUE` only when an offline/persistent export explicitly marks that issue `recovery_ready: true`;
- otherwise `UNKNOWN` with candidate issues shown for human review against #225.

Only explicit dependency data (`blocked_by`) or explicit blocked labels are rendered as GitHub blockers. Capability blockers remain those already proven by the project-state validator.

Snapshots are intentionally generated on demand rather than committed as a live-state file: a committed claim/PR snapshot would become stale immediately when an agent posts `RELEASED` or a PR merges. For persisted/offline evidence, use a captured export plus `--write <path>`, then verify it byte-for-byte with the same inputs using `--check <path>`.

The versioned fixture under `tests/fixtures/project-state/recovery/` is the deterministic proof input. No `.github/workflows/**` integration is part of this tranche.

## Backlog / evidence reconciliation

The backlog reconciliation layer compares GitHub administrative state with the same versioned evidence used by project-state and recovery. It does not close, reopen, merge, assign, or comment automatically.

Versioned inputs:
- `.project/capabilities.json` — capability state/evidence, validated by `tools/validate_project_state.py`;
- `.project/backlog-evidence.json` — only explicit issue-to-capability targets and explicit remaining gaps that cannot be derived safely;
- `.project/parallel-agents.json` + persistent claim/worklog comments — parsed by `tools/check_parallel_claims.py`;
- recovery reconstruction — delegated to `tools/build_recovery_state.py`;
- GitHub issues, PRs, branches and comments — read-only export or GET-only live adapter.

Offline report:

    python3 tools/reconcile_backlog_evidence.py \
      --github-export tests/fixtures/project-state/backlog-evidence/github-export.json \
      --render

Human report:

    python3 tools/reconcile_backlog_evidence.py \
      --github-export tests/fixtures/project-state/backlog-evidence/github-export.json \
      --human

Read-only live audit:

    python3 tools/reconcile_backlog_evidence.py \
      --repo aradenac/poker-engine \
      --human

Categories are deliberately advisory:
- `CLOSE_CANDIDATE` — persistent machine-verifiable evidence is satisfied, or merged PR + worklog + RELEASED are proven, with no explicit remaining gap;
- `KEEP_OPEN` — active work, an OPEN/IN_PROGRESS declared gap, or capability state below the declared target;
- `BLOCKED` — every declared remaining gap is explicitly BLOCKED/DEFERRED;
- `CONTRADICTION` — GitHub/recovery/claim/capability evidence conflicts;
- `UNKNOWN` — evidence is insufficient for a stronger conclusion.

The tool never converts absence of evidence into a close recommendation. A closed issue whose declared DoD state is above the proven capability state is reported as a contradiction, not reopened. An active claim whose branch or referenced PR is gone/non-open, or which is followed by a later RELEASED event, is also reported as a contradiction.

The current backlog manifest intentionally keeps duplication minimal:
- issue #45 declares the explicit remaining LIVE verification gap for `assembled_static_application`;
- issue #206 declares only the mandatory CI check that remains explicitly deferred;
- issue #109 is not copied into the backlog manifest because its historical claimed state is already present in `.project/capabilities.json` and is derived from there.

No timestamp generated by the reconciliation tool is persisted. The JSON output is deterministic for identical versioned evidence and GitHub export input. No `.github/workflows/**` integration is part of this tranche.

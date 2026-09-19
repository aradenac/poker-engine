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

The non-mutating backlog audit complements recovery-state reconstruction by comparing administrative issue/PR state with persistent delivery evidence. It is intentionally advisory: it never closes, reopens, merges, labels or comments on GitHub.

`.project/backlog-evidence-report.schema.json` defines `poker-backlog-evidence-report/v1`. `tools/audit_backlog_evidence.py` reuses:

- `tools/validate_project_state.py` for capability/evidence state;
- `tools/check_parallel_claims.py` for claim, worklog and RELEASED parsing;
- `tools/build_recovery_state.py` for recovery-state reconciliation and the existing GET-only GitHub readers.

The report categories are conservative:

- `CLOSE_CANDIDATE` — positive machine evidence supports closure, for example a merged PR + persisted `RELEASED` + latest worklog explicitly declaring no remaining gap, or a capability reaching its declared administrative state;
- `KEEP_OPEN` — persistent evidence still shows an active claim or actionable remaining gap;
- `BLOCKED` — all machine-readable remaining gaps/blockers are explicitly blocked or deferred;
- `CONTRADICTION` — administrative state conflicts with capability evidence, or claims/recovery state conflict with live branch/PR/issue state;
- `UNKNOWN` — proof is incomplete or not machine-readable. Missing proof never becomes a close recommendation.

Offline deterministic audit:

    python3 tools/audit_backlog_evidence.py \
      --github-export tests/fixtures/project-state/backlog/github-export.json \
      --render

Human view:

    python3 tools/audit_backlog_evidence.py \
      --github-export tests/fixtures/project-state/backlog/github-export.json \
      --human

Read-only live audit:

    python3 tools/audit_backlog_evidence.py \
      --repo aradenac/poker-engine \
      --human

The live adapter only reuses GET readers. It reads all issue, PR and branch state plus the existing recovery comment export. It performs no GitHub mutation. A report can be persisted locally with `--write` and checked byte-for-byte with `--check`; no volatile generation timestamp is included.

The audit deliberately does not interpret free-form issue DoD as proof. A closed issue is compared to a capability state only when the capability manifest declares an administrative issue/claimed-state relationship. Likewise, an open issue becomes a close candidate only with explicit positive evidence. This keeps historical contradictions visible without rewriting GitHub history.

The mandatory CI invocation for #206 remains the only deferred criterion and is outside this non-CI tranche; no `.github/workflows/**` file is modified here.


# Parallel agent coordination

Human dispatch source of truth: GitHub issue **#225**.

`.project/parallel-agents.json` is a versioned machine-readable mirror used to check file scope before an agent opens or merges a PR. It does **not** replace #225, parse live claims, assign work, merge PRs, close issues, or mutate GitHub comments.

## Machine-readable lanes

| Lane | Conflict group | Primary protected area |
|---|---|---|
| A | SCIENCE-FROZEN | #107/#108 frozen scientific contracts/runs/evidence |
| B | MODEL-B | Model B response-to-price/evaluators/runs |
| C | ANALYTICS | analytics contracts/modules/tests |
| D | HERO-EDITOR | Hero/preflop editor family |
| E | PACKS-UX | pack UX/runtime helper family |
| F | REPRO | reproducibility + general workflow audit |
| G | PROJECT-STATE | project-state/coordination contracts and validators |
| H | CENTRAL-UI | central UI, especially `site/index.html` and `site/trainer.js` |

Exclusive hotspot ownership takes precedence over broad reserved areas:

- `site/index.html` and `site/trainer.js` -> H;
- `site/hero-ranges*` -> D;
- `site/packs*` and `site/population-packs.js` -> E;
- frozen #108 PFPC/preflop-benchmark contracts, runs and workflows -> A;
- Model B dedicated evaluator/run/workflow paths -> B;
- other GitHub workflow files fall under F's workflow-audit scope unless a more specific A/B hotspot owns them.

## Local pre-PR scope check

Explicit files:

    python3 tools/check_parallel_scope.py \
      --slot C \
      --files src/analytics/review-inbox.js contracts/analytics/review-inbox.schema.json

Complete branch diff:

    python3 tools/check_parallel_scope.py \
      --slot C \
      --base origin/main \
      --head HEAD

Stable JSON:

    python3 tools/check_parallel_scope.py \
      --slot C \
      --base origin/main \
      --head HEAD \
      --json

The git-range mode uses a three-dot diff and disables rename collapsing, so both sides of a rename remain visible.

## Result semantics

- `PASS`: every classified file belongs to the selected lane or an explicitly shared path.
- `WARN`: no violation was found, but at least one path is unclassified. This is a coordination prompt, not silent authorization.
- `FAIL`: another lane owns a file/hotspot, the lane forbids the path, or the change set spans multiple conflict groups.

Every violation includes file, expected owner, rule and #225/#108/#197 reference when available. Output ordering is deterministic for future CI and `agent-worklog:v1`.

## Claim/release protocol

The checker validates file scope only. Agents still follow #225 manually:

1. read #225 and the target issue;
2. inspect live claims and open PRs;
3. post `parallel-claim:v1`;
4. branch from current `main`;
5. run the scope checker before PR/merge;
6. post `agent-worklog:v1` when requested;
7. post `STATUS: RELEASED`.

Live claim parsing is implemented by the offline-first checker below; #225 still remains authoritative for dispatch.

## Safety boundary

This coordination layer changes no scientific/runtime behavior. It does not edit `.github/workflows/**`, #108 artifacts, TEST ledgers, or product runtime files. Optional CI wiring may invoke this checker later when workflow-sensitive lanes permit it.

## Live claim/worklog reconstruction

`tools/check_parallel_claims.py` reconstructs coordination state from comment text while keeping #225 as the human source of truth. The business parser is offline and deterministic; GitHub access is only an optional read-only adapter.

Offline JSON:

    python3 tools/check_parallel_claims.py \
      --comments-json tests/fixtures/parallel/comments.json

Stable JSON:

    python3 tools/check_parallel_claims.py \
      --comments-json tests/fixtures/parallel/comments.json \
      --json

Optional GitHub REST read:

    python3 tools/check_parallel_claims.py \
      --repo aradenac/poker-engine \
      --issue 225

The REST adapter performs GET requests only. It uses `GITHUB_TOKEN` or `GH_TOKEN` from the environment when available and never embeds a token. A JSON file may aggregate comments from several issues; the parser uses event timestamps/IDs rather than file order.

The reconstructed state contains A-H slot status, active issue, branch, base, conflict group, files intent, PR, last worklog/release and a stable event timeline. Claim `FILES_INTENT` is checked with the exact same scope engine as `check_parallel_scope.py`.

Detected coordination diagnostics include:

- `DOUBLE_ACTIVE_CLAIM`, `SLOT_ALREADY_CLAIMED`, `ISSUE_CLAIMED_BY_MULTIPLE_SLOTS`;
- `CLAIM_WITHOUT_RELEASE` for currently open lifecycle records;
- `RELEASE_WITHOUT_CLAIM`, `WORKLOG_WITHOUT_CLAIM`, `WORKLOG_AFTER_RELEASE`;
- `BRANCH_ISSUE_MISMATCH`, `CONFLICT_GROUP_MISMATCH`, `ISSUE_LANE_MISMATCH`;
- `FILES_INTENT_SCOPE_VIOLATION` and `HOTSPOT_CLAIM_VIOLATION`;
- `CLAIM_INCOMPLETE`;
- `CLEAN_RECLAIM_AFTER_RELEASE` as a non-error warning documenting a clean replacement.

This checker never comments on GitHub, assigns work, mutates issues, merges/ closes PRs, or replaces #225.

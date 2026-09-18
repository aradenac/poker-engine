# Parallel agent coordination

Source of truth: GitHub issue #225.

This repository may be worked on by up to 8 concurrent ChatGPT web conversations. Parallelism is organized by **conflict group**, not only by issue priority.

## Active lanes

| Lane | Conflict group | Start now | Reserved area |
|---|---|---|---|
| A | SCIENCE-FROZEN | #107 then #108 | immutable #107/#108 runs, evidence, frozen workflows/contracts |
| B | MODEL-B | #197 | Model B response-to-price and its tests |
| C | ANALYTICS | #200 | leak/EV aggregation modules and tests |
| D | HERO-EDITOR | #215 | `site/hero-ranges.*` and Hero editor tests |
| E | PACKS-UX | #216 | `site/packs.*`, `site/population-packs.js` |
| F | REPRO | #203 phase 1 | dependency manifests/locks/setup; no frozen science workflow edits |
| G | PROJECT-STATE | #206 phase 1 | project-state validators/docs; avoid #107/#108 workflows |
| H | CENTRAL-UI | #211 | exclusive owner of `site/index.html` and `site/trainer.js` during this wave |

See #225 for full queue, dependencies and deferred work.

## Claim protocol

Before editing:

1. Read #225.
2. Read the target issue and latest comments.
3. Check open PRs and branches mentioning the issue.
4. Comment on the issue:

```text
<!-- parallel-claim:v1 -->
AGENT_SLOT: H
ISSUE: #211
STATUS: CLAIMED
BASE: <main sha>
BRANCH: agent-H/issue-211-<slug>
CONFLICT_GROUP: CENTRAL-UI
FILES_INTENT:
- site/index.html
- tests/...
NOTES: ...
```

5. Create one branch per issue from current `main`.
6. Open a PR as soon as a coherent first commit exists.
7. Prefix PR titles with `[<slot>][#<issue>]`.

Release with another comment using `STATUS: RELEASED`, the PR number and next target.

## Rules

- Never push agent work directly to `main`.
- Never keep one long-lived branch for several issues.
- Never modify another lane's reserved files without coordination.
- If an open PR already touches intended files, avoid competing work.
- Start the next issue from fresh `main` after the previous issue is released/merged.
- Keep one conflict group single-writer even if several issues in it are independently valuable.
- Lane A alone may trigger or alter #107/#108 evidence/VALIDATION/TEST state.
- Future Model B / Monte Carlo work must not retroactively change the frozen #108 protocol.

## Deferred/high-conflict work

- #204: defer until #107/#108 are finished; high overlap with GitHub Actions.
- #205: defer until central UX wave stabilizes; broad frontend refactor.
- #198: branch-safe only; merge after frozen #107/#108 result.
- #196: final implementation after #107/#108 and preferably #198.
- #195/#201: promotion/integration gated by #108.
- #219: gated by #200 and benefits from #195/#196.
- #208: integrated by lane H after localized D/E/H work to reduce cross-page conflicts.

## Recommended chat bootstrap

> You are agent X on `aradenac/poker-engine`. Read issue #225 first and strictly follow lane X, its conflict group and claim protocol. Check concurrent claims/open PRs before editing. Work the first READY issue in your lane through a clean tested PR, then take the next issue only after releasing the previous one. Never touch files reserved to another lane.

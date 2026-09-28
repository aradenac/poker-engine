# n8n v8 review hardening

This directory is the versioned source of truth for the PR-review ingestion,
safe state transitions and bounded rebase resolution used by the local n8n v8
orchestrator.

Dry-run and deploy from an interactive shell that exports `N8N_API_KEY`:

```sh
python3 ops/n8n/deploy.py
python3 ops/n8n/deploy.py --apply
python3 ops/n8n/validate.py
```

`deploy.py` snapshots every changed live workflow under
`/home/abel/n8n-backups/review-hardening-<UTC timestamp>/` before updating it.
The helpers are installed into `/home/abel/.config/poker-engine-orchestrator/`
because workflows must not depend on the currently checked-out product branch.
Deployment also upgrades the installed fail-closed contract validator so it
recognizes the shell-safe state helper; rerunning a dry-run must report no
workflow or validator drift.

Corrective work is driven only by actionable PR reviews and unresolved inline
review threads. General issue and PR comments are not corrective inputs.
Processed events are recorded atomically using the
`review-event-ledger.schema.json` v1 contract; an event is acknowledged only
after its corrective plan has been persisted.

Integration rebases run in the managed issue worktree, create a recovery ref,
and allow an agent to edit only the conflicted paths. Files already staged by
Git as the non-conflicting part of the rebased commit are preserved and hashed
so the agent cannot alter them. The workflow, not the agent, stages and
continues the rebase. A push is permitted only for the branch and HEAD returned
by that verified step, and only with the previously observed remote HEAD as a
`--force-with-lease` expectation.

Terminal CI or integration failures remain explicit. `state_ops.py resume`
turns a reviewed CI failure into `CI_PENDING`, or an integration failure into
`INTEGRATION_RETRY`; the reconciliation sweep is the only component that
re-enters the corresponding workflow.

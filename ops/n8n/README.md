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

Corrective work is driven only by actionable PR reviews and unresolved inline
review threads. General issue and PR comments are not corrective inputs.
Processed events are recorded atomically using the
`review-event-ledger.schema.json` v1 contract; an event is acknowledged only
after its corrective plan has been persisted.

# Source

Application and engine source files belong here when they are split out of the historical single-file HTML application.

## Shared preflop contract

`src/preflop/contract.js` is the canonical JavaScript implementation of the `poker-preflop-context/v1` and `poker-preflop-action-probabilities/v1` contracts introduced by #96. Node-based tooling and tests must import this source directly rather than treating a deployed site artifact as source code.

The browser continues to load `site/preflop-contract.js`. That file is a generated static copy and must remain byte-identical to the canonical source. Run:

```bash
python3 tools/sync_shared_site_assets.py
python3 tools/sync_shared_site_assets.py --check
```

The extraction is intentionally behavior-neutral: changing the contract still requires the existing cross-runtime fixtures, incumbent-v5 compatibility checks, release-identity checks and the appropriate scientific gates. It does not couple Model A and Model B policies and does not imply any strategic promotion.

Until further targeted extractions exist, complete runnable builds remain under `user/releases/` and migration/build utilities under `tools/`. Do not turn this directory into a prerequisite for a global frontend rewrite.

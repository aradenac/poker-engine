# Source

Shared application and engine source files live here when they are extracted from the historical single-file/static application.

## Current extracted modules

`src/preflop/contract.js` is the canonical JavaScript source for the preflop context/probability contract introduced by issue #96. The browser still loads `site/preflop-contract.js`; that file is a generated static copy so the production application keeps the same no-bundler deployment shape.

Edit the source file, then synchronize the runnable artifact with:

```bash
python3 tools/sync_shared_modules.py --write
```

CI runs `python3 tools/sync_shared_modules.py --check` and rejects source/site drift. The extracted source and the served copy are intentionally byte-identical, so this ownership move does not change poker decisions, model inputs, workers, caches, or release behavior.

Further extraction should remain incremental: only move code that has a concrete second consumer or whose duplication blocks a tested feature. Complete historical runnable builds remain under `user/releases/`, while migration/build utilities remain under `tools/`.

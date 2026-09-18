# Reproducible environment contract

Issue #203 phase 1 defines a repository-level environment contract without changing
the scientific workflows frozen by #107/#108.

## Pinned runtimes

- Python: `3.11.9`
- Node.js: `22.14.0`
- Playwright for Python: `1.55.0`
- Chromium distributed for that Playwright line: `140.0.7339.16`

The canonical machine-readable contract is
`reproducibility/environment.lock.json`. Runtime version files and dependency
locks must agree with it.

## Clean-checkout setup

Using version managers of your choice, install the exact Python and Node versions
from `.python-version` and `.node-version`, then run:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.lock.txt
python -m playwright install --with-deps chromium
npm ci
python tools/repro_environment.py --check-contract
python tools/repro_environment.py --verify-runtime
```

To attach environment identity to a scientific artifact:

```bash
python tools/repro_environment.py --manifest /tmp/environment-manifest.json
```

The manifest records the contract hash plus observed Python, Node, Playwright,
Chromium and platform identities. This makes an artifact diagnosable even before
phase 2 wires the contract into every scientific workflow.

## Lock update procedure

1. Open a dedicated reproducibility issue/PR; never rewrite a historical run or
   immutable scientific artifact.
2. Change the direct dependency or runtime version in the canonical inputs.
3. Regenerate the complete transitive lock, update
   `reproducibility/environment.lock.json`, and keep `.python-version`,
   `.node-version`, `package.json` and `package-lock.json` consistent.
4. Run:
   ```bash
   python tools/repro_environment.py --check-contract
   python tests/test_repro_environment.py
   ```
5. Re-run the representative scientific regression suite before merge and record
   any numerical or browser-behavior change caused by the environment update.
6. Treat a Playwright/Chromium change as an environment change requiring explicit
   review; update both versions together.

## Phase-1 boundary

This change deliberately does **not** edit `.github/workflows/**`, #107/#108
contracts, holdout ledgers, or immutable run artifacts. Workflow enforcement,
container/OS package pinning and automatic manifest attachment belong to phase 2
after the scientific freeze is released.

# Machine-readable project state

Issue #206 introduces a repository-owned distinction between administrative completion and delivered capability. A closed issue is not, by itself, evidence that a feature is active in the current runtime.

## Delivery states

The canonical order is:

1. CONTRACT_READY — the contract, schema, infrastructure or reproducible boundary exists.
2. SCIENTIFICALLY_SELECTED — a candidate/artifact has been selected under its declared scientific gate.
3. PRODUCT_INTEGRATED — the selected capability is wired into the product/runtime used by the user.
4. PROMOTED — the integrated artifact is the promoted/default repository or release identity.
5. LIVE — the exact promoted identity has been verified on the canonical production surface.

The order is intentional: publication metadata, a closed ticket, or a successful CI run cannot silently skip missing scientific, integration, promotion or live-deployment evidence.

## Sources of truth

.project/capabilities.json is the machine-readable inventory for capabilities tracked by this first phase. Each capability declares its current delivery state, versioned evidence, optional higher-state blockers, and optional administrative metadata.

tools/validate_project_state.py evaluates only repository files. It does not call GitHub, mutate issues, rewrite history, or infer a feature state from chat context.

Run:

    python3 tools/validate_project_state.py
    python3 tests/test_project_state.py

A report is PASS, WARN, or FAIL:

- PASS: all declared evidence is present and no administrative gap exists.
- WARN: evidence is valid, but a higher administrative claim is explicitly acknowledged and linked to a successor issue.
- FAIL: evidence is missing/stale, the manifest is malformed, or a higher administrative claim is not traceably acknowledged.

Use --strict-warnings when a later CI phase should treat acknowledged gaps as non-zero (exit code 2). Ordinary validation returns zero for PASS and WARN, and one for FAIL.

## Current deliberate gaps

The manifest records two important boundaries rather than hiding them:

- issue #109 is closed, but site/trainer.js explicitly says that Hero training decisions begin on the flop; the capability therefore remains CONTRACT_READY until versioned runtime evidence proves integration;
- site/RELEASE.json has a promoted repository/build identity, but publication_verification.status is UNVERIFIED_LIVE; the application must not be represented as LIVE until issue #45 supplies exact canonical-production proof.

The validator never reopens historical issues. A contradiction is either linked to a successor issue or reported as a failure.

## Phase-1 scope

This phase deliberately does not rewrite .project/STATUS.md or .project/PLAN.md and does not edit scientific workflows owned by #107/#108. The validator provides the stable machine-readable layer that later work can use to generate/check human status documents and wire an appropriate CI job without competing with the frozen scientific lanes.

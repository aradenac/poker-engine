# Project Status

Last update: 2026-09-11

## Persistence bootstrap

- GitHub repository `aradenac/poker-engine` is the durable project source of truth.
- User-facing artifacts are separated under `user/`; tool/session state under `.project/` and `tools/`; training state under `training/`; permanent validation under `tests/`.
- Cross-session resume protocol, plan, conventions, training registry and run-manifest template are committed on `main`.
- Open issue #1 tracks import of existing project artifacts.
- Open issue #2 tracks implementation of the versioned continuous-training pipeline.

## Artifact import in progress

Branch: `artifact-import-20260911`.

Five authoritative source artifacts were explicitly re-uploaded on 2026-09-11 and verified locally:

- application v78 — SHA-256 `352eabe2b2e6245f6442e79c1ced8dd0b53c5e655d3c5cff52311cdac5b42050`
- preflop population model v5 — SHA-256 `ff952055ca4ee051a3ac9607d513fdecac0a320a31f658ecfd8a11d8448975ca`
- postflop population model v5 — SHA-256 `6d948f30f6c276ce41e70e83ac35275e30e7841e93e5b1da11782648c6b4d8ae`
- sequential postflop population simulator v4 — SHA-256 `adf948126fe72c137e4a03e843fbe25d8654b6348b352f50e76d50efb8d6cabe`
- NLHE 100-200 source archive — SHA-256 `6effd27d6e9f8257f3e87c68f0218b8edc72a2b487cb57da2c37ff85bc8ce4c6`

See `artifacts/IMPORT_MANIFEST_20260911.md` for canonical target paths and source filenames.

The active GitHub connector does not expose a raw mounted-file upload argument. Therefore large JSON and ZIP artifacts are currently registered as `pending_import` rather than falsely marked committed. Do not promote the models or dataset until committed repository objects are verified against the hashes above.

## Current baseline

- Current application baseline: `poker_range_equity_offline_multiway_v78.html` (authoritative uploaded source; exact raw transfer into GitHub pending).
- Prepared patch: v78 -> v79.
- v79 objective: remove demonstrated JAM bias and make recommendation selection consistently use the final comparable EV.

## Validated findings

- Artificial JAM calibration bonuses were identified as a structural source of overly aggressive recommendations.
- Very small empirical nodes can generate implausibly high EVs for raises/JAMs.
- Recommendation logic and sizing panels must use the same validity filters and the same final EV ordering.
- Existing P99.5 support guard should be preserved.

## v79 guardrails

- `very_low` node with <5 observations: hypothetical aggression cannot be recommended.
- 5-9 observations: ordinary sizing may remain eligible when supported, but JAM/overbet is not recommendable.
- For `very_low` nodes with >=5 observations, sizing outside local support is rejected.
- `sanityInvalid` sizing must remain invalid everywhere; no permissive fallback.
- Artificial JAM bonuses removed.
- Final recommendation = argmax(final comparable EV).

## Immediate next milestone

1. Complete exact-byte import of the five received artifacts.
2. Materialize v79 as a complete HTML/application version.
3. Run regression tests on previously pathological hands.
4. Audit ordinary sizing calibration offsets.
5. Benchmark global action/sizing frequencies.
6. Promote new training artifacts only after regression and held-out evaluation pass.

## Continuous-training contract

- Never overwrite completed training runs.
- Every run references immutable dataset fingerprint(s), parent run/model, code commit, parameters, metrics and regression results.
- Candidate models are not promoted automatically merely because they are newer.
- Promotion requires reproducible improvement without unacceptable regression.
- `training/registry.json` is the authoritative pointer to active/promoted artifacts; history remains append-only.

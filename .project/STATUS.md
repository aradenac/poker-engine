# Project Status

Last update: 2026-09-11

## Persistence

- GitHub repository `aradenac/poker-engine` is the durable project source of truth.
- User-facing artifacts live under `user/`; tool/session state under `.project/` and `tools/`; training state under `training/`; permanent validation under `tests/`.
- Cross-session resume protocol, plan, conventions, training registry and run-manifest template are committed on `main`.
- Open issue #1 tracks remaining exact-byte import of large historical artifacts.
- Open issue #2 tracks the versioned continuous-training pipeline.

## Authoritative received source artifacts

The following source artifacts were explicitly re-uploaded on 2026-09-11 and verified locally:

- application v78 — SHA-256 `352eabe2b2e6245f6442e79c1ced8dd0b53c5e655d3c5cff52311cdac5b42050`
- preflop population model v5 — SHA-256 `ff952055ca4ee051a3ac9607d513fdecac0a320a31f658ecfd8a11d8448975ca`
- postflop population model v5 — SHA-256 `6d948f30f6c276ce41e70e83ac35275e30e7841e93e5b1da11782648c6b4d8ae`
- sequential postflop population simulator v4 — SHA-256 `adf948126fe72c137e4a03e843fbe25d8654b6348b352f50e76d50efb8d6cabe`
- NLHE 100-200 source archive — SHA-256 `6effd27d6e9f8257f3e87c68f0218b8edc72a2b487cb57da2c37ff85bc8ce4c6`

Large exact-byte artifacts are still `pending_import` because the current connector cannot directly upload mounted binary/large-file bytes. Do not falsely mark them committed. The transformation patches and validation reports are persisted on `main`.

## Current engine baseline: v83

Local full artifact: `poker_range_equity_offline_multiway_v83.html`
SHA-256: `2690a82ffe363017b495a1aef60657b12db1b52eb402c36a1ff87f723c5d1bd4`

Reproducible patch chain committed on GitHub:

- v78 -> v79: final-EV recommendation guard, sparse-node protection, JAM bonus removal
- v79 -> v80: pot-scaled residual calibration
- v80 -> v81: effective response-pot correction for unmatched shove amounts
- v81 -> v82: low-confidence extreme local-P90 support guard + effective aggressor-ratio propagation
- v82 -> v83: effective opponent all-in sizing candidate instead of irrelevant full Hero-stack JAM when Hero covers

## Key validated findings

- Artificial JAM calibration bonuses were a structural source of over-aggressive recommendations and remain disabled.
- Fixed additive BB calibration biased rankings toward larger sizings; v80 scales residual coefficients down in small pots.
- When Hero's nominal shove exceeds the opponent's effective stack, the unmatched portion must not enter the responder price-to-pot calculation; v81 fixes this.
- Low/very-low confidence extreme aggression beyond local P90 support should not be recommended; v82 enforces this.
- A full Hero-stack JAM while covering a shorter opponent is a misleading sizing label. v83 recommends the exact effective amount needed to put the opponent all-in.

## v83 behavior benchmark

Deterministic 48-decision HU postflop sample:

- true Hero JAM: 1 / 48 = 2.1%
- effective opponent all-in sizing: 7 / 48 = 14.6%
- BET: 23 / 48 = 47.9%
- CALL: 7 / 48 = 14.6%
- RAISE: 3 / 48 = 6.2%
- CHECK: 4 / 48 = 8.3%
- FOLD: 3 / 48 = 6.2%

The true JAM frequency is now in the same order of magnitude as the observed population JAM rate (~1.3% flop, ~1.4% turn, ~2.5% river). Effective all-ins are reported separately because Hero is not risking their full stack.

Historical pathological hand `#262024556922` on v83:

- flop: best `25% pot` (check within noise)
- turn: best `125% pot`
- river before bet: best `100% pot`
- river facing bet: best `CALL`
- no absurd JAM recommendation

See `tests/regression/v81_effective_pot_audit.md` and `tests/regression/v83_style_and_effective_allin.md`.

## Immediate next milestone

1. Audit the seven v83 `all-in effectif` recommendations: hand strength, EV gap, response support and effective sizing.
2. Simplify user-facing recommendation display to exactly: action, effective sizing, final EV; keep raw/model diagnostics secondary.
3. Expand regression sample beyond 48 deterministic decisions and preserve all pathological cases.
4. Audit remaining ordinary sizing distribution after v83.
5. Resume continuous-training work only after the recommendation engine behavior is stable.

## Continuous-training contract

- Never overwrite completed training runs.
- Every run references immutable dataset fingerprint(s), parent run/model, code commit, parameters, metrics and regression results.
- Candidate models are not promoted automatically merely because they are newer.
- Promotion requires reproducible improvement without unacceptable regression.
- `training/registry.json` is the authoritative pointer to active/promoted artifacts; history remains append-only.

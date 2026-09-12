# Project Plan

## Current focus — Reproducible independent strategy arena

The project operates as a continuous-learning system with three separate layers:

1. **Opponent model A — integrated population model** used by the analyzer itself.
2. **Opponent model B — independent profile-based model** used as an external simulation/evaluation environment and not as the analyzer's own EV model.
3. **Engine strategy** evaluated against model B before a new application version is promoted.

Keeping model B independent is essential: strategy evaluation must not simply confirm the same assumptions already embedded in the analyzer.

### Current milestone

Issue **#8 is complete in implementation**: Model B v2 is rebuilt from repository hand histories, selected on VALIDATION only, evaluated on untouched TEST, and promoted under alias `independent_model_b_v2` with an immutable promotion record.

The active implementation target is now **#9 — Make sequential independent simulation harness reproducible**. The old simulator still depends on `/mnt/data`, historical pickle inputs, and `independent_decision_arena_seq_v2`; those dependencies must be replaced by repository-relative JSON Model B inputs and deterministic scenario generation.

## Phase 1 — Reproducible independent arena

Completed Model B foundation:

- deterministic TRAIN-only player-feature pipeline;
- deterministic profile clustering and prevalence weights;
- profile-conditioned preflop ranges;
- hierarchical postflop action tables;
- empirical postflop sizing distributions;
- prediction contract and holdout evaluation;
- validation-only K selection (K=3 selected from K=3..8);
- promotion record and registry pointer.

Remaining #9 work:

- persist/refactor arena code under `tools/simulation/`;
- remove all `/mnt/data` and untracked-pickle dependencies;
- make the simulator consume `training/registry.json` and the promoted Model B JSON artifacts;
- consume the promoted analyzer release from repository paths;
- define and persist a deterministic simulation seed/scenario contract;
- add regression tests proving identical scenarios/results are reproducible from a clean checkout;
- preserve exact effective-stack/pot accounting and sequential postflop state transitions.

## Phase 2 — Dual opponent-model contract

### Model A — integrated analyzer population model

Maintain the current preflop/postflop lineage:

- structural/contextual population nodes;
- hierarchical backoff;
- continuous context adjustment;
- revealed-hand/action-composition information where allowed;
- explicit TRAIN / VALIDATION / TEST separation.

This model is allowed to drive analyzer EV calculations.

### Model B — independent profile model

Promoted alias: `independent_model_b_v2`.

Maintain a separate opponent representation based on behavioral profiles:

- player/profile assignment learned from TRAIN only;
- profile-conditioned preflop ranges;
- marginal action probabilities by street/context;
- empirical bet/raise sizing distributions;
- profile prevalence weights;
- explicit cold-start and hierarchical-backoff prediction contract.

This model is **not** used by the analyzer to choose its recommendation. It is the external environment used to test whether analyzer recommendations remain coherent and profitable under independently learned behavior.

## Phase 3 — Continuous hand-history ingestion

Whenever new hand histories are pushed:

1. Audit the archive and preserve it as an immutable snapshot.
2. Deduplicate by PokerStars hand ID against known historical data; do not rely only on timestamps.
3. Assign every new hand with the deterministic split contract already used by the population lineage.
4. Materialize a versioned run containing the exact delta and provenance.
5. Update candidate model A from historical approved evidence + the new TRAIN delta.
6. Update candidate model B from the same approved TRAIN evidence, independently of model A.
7. Never overwrite an existing promoted model or completed run.

## Phase 4 — Opponent-model evaluation and promotion

Evaluate model A and model B independently. Preserve at least:

- marginal-action log-loss / cross-entropy;
- calibration error by action and probability bucket;
- results by street, mode, position, pot type and sample-confidence bucket;
- range prediction metrics where known cards exist;
- profile stability;
- performance on VALIDATION and untouched TEST;
- sizing-distribution coverage/tail diagnostics;
- exact dataset/model fingerprints and promotion/rejection record.

A candidate may be rejected while its evidence is retained for later runs.

## Phase 5 — Independent strategy arena

For every meaningful engine candidate:

- replay/simulate a deterministic scenario set against promoted Model B;
- sample opponents according to learned profile prevalence and also report each profile separately;
- simulate sequential postflop behavior rather than only one-step decisions;
- use the analyzer only for Hero's decisions;
- compute actual effective all-in amounts and stack/pot evolution exactly;
- compare current promoted engine and candidate on the exact same random seeds/scenarios.

Primary strategy metrics:

- simulated EV / hand and EV / decision;
- regret versus independently evaluated alternatives where available;
- frequency of large-regret recommendations;
- action distribution: fold/check/call/bet/raise/jam;
- sizing distribution and extreme overbet/jam rate;
- results by opponent profile;
- results by street, SPR, pot type, relative position and hand-strength/equity buckets.

Population frequencies are diagnostics, not imitation targets.

## Phase 6 — Non-regression gates for engine promotion

A new analyzer release may be promoted only when all applicable gates pass:

1. **Permanent pathological-hand suite** — previously fixed recommendation bugs stay fixed.
2. **Integrated-model consistency** — recommendation, sizing and displayed final EV are the same decision tuple everywhere.
3. **Independent-arena benchmark** — no material degradation in aggregate EV/regret and no unexplained profile-specific collapse.
4. **Behavior/style benchmark** — no structural resurgence of unsupported jams, overbets or other pathological action frequencies.
5. **Predictive-model gates** — promoted opponent-model candidates pass their own VALIDATION/TEST criteria.
6. **Reproducibility** — exact datasets, models, code version, seeds and metrics are persisted in the run.

Opponent-model promotion and application/strategy promotion are separate decisions.

## Phase 7 — Release and deployment

- Promoted user build: `user/releases/poker_range_equity_offline_multiway_vNN.html`.
- Deployed static build: `site/index.html`.
- `site/index.html` changes only when an application version is explicitly promoted.
- Training/model commits do not imply a new promoted application.

## GitHub execution backlog

Epic: **#2 Build versioned continuous-training pipeline**.

Implementation order/status:

1. **#6 Continuous data ingestion and deterministic hand splits** — implemented foundation.
2. **#7 Continuous training for integrated population model A** — partially implemented; further automation remains.
3. **#8 Rebuild and version independent opponent-profile model B** — implemented and promoted as `independent_model_b_v2`.
4. **#9 Make sequential independent simulation harness reproducible** — **current focus**.
5. **#10 Establish deterministic v83 strategic baseline against independent profiles**.
6. **#11 Evaluate v84 and future strategy candidates on the independent benchmark**.
7. **#12 Define unified non-regression and promotion gates for models and engine**.
8. **#13 Automate end-to-end continuous training and site promotion**.

Dependency graph:

`#6 -> (#7, #8) -> #9 -> #10 -> #11`

and

`#7 + #8 + #10 -> #12 -> #13`.

## Working rules

- GitHub is the durable source of truth.
- New evidence accumulates; historical approved data is not silently replaced.
- Completed runs and promotion records are immutable.
- A surprising recommendation is diagnosed before calibration is changed: data scarcity, extrapolation, implementation bug, model mismatch or genuine exploitative EV must be distinguished.
- The independent arena must remain genuinely independent of the analyzer's own population-EV implementation.

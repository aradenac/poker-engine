# Project Plan

## Current focus — Continuous training with independent strategy validation

The project now operates as a continuous-learning system with three separate layers:

1. **Opponent model A — integrated population model** used by the analyzer itself.
2. **Opponent model B — independent profile-based model** used as an external simulation/evaluation environment and not as the analyzer's own EV model.
3. **Engine strategy** evaluated against model B before a new application version is promoted.

Keeping model B independent is essential: strategy evaluation must not simply confirm the same assumptions already embedded in the analyzer.

## Phase 1 — Make the independent arena reproducible

- Persist/rebuild the independent profile-model pipeline and remove `/mnt/data` dependencies.
- Persist the arena code under `tools/simulation/`.
- Persist versioned independent-model artifacts under `training/models/independent_profiles/`.
- Rebuild from the authoritative NLHE 100-200 dataset rather than relying on unversioned historical pickles.
- Record profile definitions, clustering/mapping, marginal action models, composition/continuation models, preflop range tables and empirical sizing distributions.
- Make the sequential simulator consume repository-relative inputs and the promoted analyzer release.
- Establish a deterministic simulation seed contract so candidate strategies can be compared on identical scenarios.

## Phase 2 — Establish the dual opponent-model contract

### Model A — integrated analyzer population model

Maintain the current preflop/postflop lineage:

- structural/contextual population nodes;
- hierarchical backoff;
- continuous context adjustment;
- revealed-hand/action-composition information where allowed;
- explicit TRAIN / VALIDATION / TEST separation.

This model is allowed to drive analyzer EV calculations.

### Model B — independent profile model

Maintain a separate opponent representation based on behavioral profiles:

- player/profile assignment learned from TRAIN only;
- profile-conditioned preflop ranges;
- marginal action probabilities by street/context;
- continuing-range/action-composition models;
- empirical bet/raise sizing distributions;
- profile prevalence weights.

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

Evaluate model A and model B independently.

For each candidate, preserve at least:

- marginal-action log-loss / cross-entropy;
- calibration error by action and probability bucket;
- results by street, mode, position, pot type and sample-confidence bucket;
- revealed-hand/composition metrics where applicable;
- stability on the historical holdout;
- performance on the newest VALIDATION and TEST samples;
- bootstrap uncertainty where useful.

A candidate may be rejected while its additive evidence/overlay is retained for later runs, as already done with the rejected postflop v6 candidate.

## Phase 5 — Independent strategy arena

For every meaningful engine candidate:

- replay/simulate a deterministic scenario set against model B;
- sample opponents according to learned profile prevalence and also report each profile separately;
- simulate sequential postflop behavior rather than only one-step decisions;
- use the analyzer only for Hero's decisions;
- compute actual effective all-in amounts and stack/pot evolution exactly;
- compare current promoted engine and candidate on the exact same random seeds/scenarios.

Primary strategy metrics:

- simulated EV / hand and EV / decision;
- regret versus the independent arena's locally evaluated alternatives;
- frequency of large-regret recommendations;
- action distribution: fold/check/call/bet/raise/jam;
- sizing distribution and extreme overbet/jam rate;
- results by opponent profile;
- results by street, SPR, pot type, relative position and hand-strength/equity buckets.

The goal is not to force the engine to imitate observed action frequencies. Population frequencies are diagnostics; the strategy should exploit population behavior without depending on unsupported extrapolation.

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
- Cloudflare deployment is expected to rebuild automatically from GitHub commits; training/model commits do not imply a new promoted application even if a deployment job runs.

## GitHub execution backlog

Epic: **#2 Build versioned continuous-training pipeline**.

Implementation order:

1. **#6 Continuous data ingestion and deterministic hand splits** — canonical hand-ID deduplication and immutable increments.
2. **#7 Continuous training for integrated population model A** — incremental preflop/postflop candidates and predictive promotion decisions.
3. **#8 Rebuild and version independent opponent-profile model B** — clean reconstruction of the independent environment from repository data.
4. **#9 Make sequential independent simulation harness reproducible** — remove local-only dependencies and freeze deterministic scenario generation.
5. **#10 Establish deterministic v83 strategic baseline against independent profiles** — reference strategy benchmark.
6. **#11 Evaluate v84 and future strategy candidates on the independent benchmark** — paired strategy optimization and candidate decisions.
7. **#12 Define unified non-regression and promotion gates for models and engine** — machine-readable promotion contract.
8. **#13 Automate end-to-end continuous training and site promotion** — GitHub-driven orchestration and safe Cloudflare-facing release updates.

Dependency graph:

`#6 -> (#7, #8) -> #9 -> #10 -> #11`

and

`#7 + #8 + #10 -> #12 -> #13`.

PR policy:

- one implementation issue should normally map to one focused PR or a short sequence of explicitly linked PRs;
- training/model generation and engine-strategy changes should not be mixed in the same PR;
- generated candidate artifacts may be committed in their originating training PR/run, but promotion pointer changes should remain reviewable and explicit;
- every PR affecting training or strategy must state dataset/model versions, reproducibility inputs and regression results.

## Working rules

- GitHub is the durable source of truth.
- New evidence accumulates; historical approved data is not silently replaced.
- Completed runs are immutable.
- A surprising recommendation is diagnosed before calibration is changed: data scarcity, extrapolation, implementation bug, model mismatch or genuine exploitative EV must be distinguished.
- The independent arena must remain genuinely independent of the analyzer's own population-EV implementation.

# Project Plan

## Current focus — Reproducible evidence before strategy promotion

The project operates as a continuous-learning system with three separate layers:

1. **Opponent model A — integrated population model** used by the analyzer itself.
2. **Opponent model B — independent profile-based model** used as an external simulation/evaluation environment and not as the analyzer's own EV model.
3. **Engine strategy** evaluated against model B before a new application version is promoted.

Keeping model B independent is essential: strategy evaluation must not simply confirm the same assumptions already embedded in the analyzer.

### Current milestone — audit 2026-09-12

Historical audit base: main `caaff599707006fab3daa0f39b90b67c37fdaac1`; PR #44 head `899015dd4d29ffcdb9130ddb10d74347b856a0c1`. User-facing assessment: `user/reports/etat-des-lieux-2026-09-12.md`.

Model B v2 (#8) and the ingestion foundation (#6) are complete. The trainer feature and performance/Guided/custom-range corrections are merged. Current promoted recommendations still use engine v83 and Model A preflop/postflop v5.

#35 was delivered by PR #48: exact source, materialized increment and mandatory integrity gate. The remaining P0 blocker is #45 (intermittent Cloudflare builds and unverified public deployment). The #36/#37 candidate rejection decisions remain closed; reconstruction debt is tracked under #7. The #38 candidate has a branch report but needs full artifacts and a paired incumbent comparison.

### Ordered execution backlog

Delivery 2026-09-13: #35 and #9 are complete (PR #48/#44). PR #49 wires all six trainer contracts; PR #50 eliminates derived ZIP timestamp churn. All relevant CI gates passed and these changes are merged. Cloudflare remains intermittent and public deployment identity remains unverified (#45).

P0: unblock source/reproducibility/publication. P1: validate models, environment and benchmark. P2: select/promote/automate after the prerequisites. P3: historical cleanup. Epics #2 and #43 coordinate these tasks; they are not additional deliveries.

| Rank | Priority | Issue | Next deliverable |
|---:|:---:|---|---|
| 3 | P0 | #45 | Restore a verified deployment of the intended site. Main and PR #44 Cloudflare builds fail; current public application availability was not checked. |
| 4 | P1 | #12 | Specify promotion criteria before strategy selection; wire missing regression checks now. The complete gate can become green only after model/baseline evidence exists. |
| 5 | P1 | #7 | Finish repo-native Model A reconstruction and persist rejected-candidate evidence. Keep #36/#37 closed as rejection decisions; track their remaining reproducibility debt here instead of retraining blindly. |
| 6 | P1 | #10 | Freeze a scoped v83 + promoted Model B v2 diagnostic baseline after #9. It can run without waiting for #35/#38. Report the heads-up postflop scope and Model B limitations. |
| 7 | P1 | #38 | After #35, persist the refreshed candidate and features, then compare incumbent and candidate on exactly the same enlarged holdout. The inspected branch contains a selection report and export workflow, not the full new candidate. |
| 8 | P1 | #46 | Validate response realism and sensitivity before using the independent environment as the sole sizing-strategy promotion gate. |
| 9 | P1 | #39 | Build the refreshed baseline after the Model B decision and the old-environment reference. Separate changed data/environment from changed Hero policy. |
| 10 | P2 | #11 | Evaluate policy candidates only once the baseline and promotion criteria are ready. Coordinate the current-cycle execution with #40; do not count the same benchmark twice. |
| 11 | P2 | #40 | Current-cycle strategy search, executed jointly with the #11 capability work after #39 and environment-validity/gate prerequisites. |
| 12 | P2 | #41 | Run the complete pre-specified gate across data, models, strategy, replay and trainer; this is the execution of the contract defined under #12. |
| 13 | P2 | #42 | Record independent promotion/rejection decisions and complete immutable cycle evidence after #41. Verify site assets, release provenance and rollback pointers together. |
| 14 | P2 | #13 | Automate the chain after one end-to-end cycle is reproducible and its gates are meaningful; validate rejection leaves promoted pointers unchanged. |
| 15 | P3 | #1 | Historical bootstrap cleanup. Current v83, production models and the two older raw archives are present; the documented remaining gap is historical v78. This does not block current engine work. |

### Dependency and validation rules

- #35 unlocks new-data reconstruction and #38. It does not block #9 or an old-corpus reference under #10.
- #9 is delivered: CI checks full fresh-browser reproduction, actual worker seeds/budgets and betting fixtures. #10/#39 must now supply statistical benchmark evidence beyond smoke coverage.
- Start #12 gate specification/wiring before policy selection; final PASS still requires the completed model and benchmark evidence.
- #10 freezes v83 + Model B v2 as a scoped HU postflop reference. #38 produces an independent retain/promote decision; #46 addresses response realism before promotion-grade sizing conclusions.
- #39 holds v83/Model A fixed to measure environment drift, then #11/#40 hold that selected environment fixed to compare engine candidates. #11 and #40 share one cycle deliverable.
- Use strategy VALIDATION scenarios for tuning and a protected final TEST set. Record effective worker trial budgets and seeds, code/model/data hashes, paired uncertainty and context coverage.
- #41 executes the pre-specified #12 gates; #42 records independent outcomes and verifies assembled site/model identities; #13 automates the already reproducible cycle.
- The arena only generates HU postflop states. Its utility is conditional from the flop, not an overall session win rate. Current marginal Model B alone is insufficient evidence of sizing optimality; see #46.

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

The ranked list is at the start of this plan and in the issue priority/rank blocks. Capability epic: #2. Current cycle umbrella: #43. Completed capabilities #6/#8 and trainer issues are outside the active queue.

Distinguish capability work (#7/#9/#10/#11/#12/#13) from cycle execution (#35–#42); one implementation/benchmark may satisfy both linked tickets. Historical v78 import (#1) remains P3.

## Working rules

- GitHub is the durable source of truth.
- New evidence accumulates; historical approved data is not silently replaced.
- Completed runs and promotion records are immutable.
- A surprising recommendation is diagnosed before calibration is changed: data scarcity, extrapolation, implementation bug, model mismatch or genuine exploitative EV must be distinguished.
- The independent arena must remain genuinely independent of the analyzer's own population-EV implementation.

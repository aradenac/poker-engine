# Project Plan

## Operating model

The project is a continuous-learning poker analyser/trainer with deliberately separated layers:

1. **Model A** — integrated population model used by the analyser to compute Hero recommendations/EV.
2. **Model B** — independent opponent model used to simulate/evaluate strategy and generate trainer opponents; it must not feed its own conclusions back into Model A EV.
3. **Engine strategy** — Hero action/sizing policy evaluated against an independent Model B environment before any engine promotion.
4. **Static product** — analyser/replayer/trainer assembled under `site/` and released independently from model-training decisions.

Every training cycle must preserve deterministic TRAIN / VALIDATION / TEST assignment, immutable evidence, explicit retain/promote decisions, exact artifact identities and a rollback path. A valid cycle may end with no production change.

## Current milestone

The 2026-09-12 `NLHE 100-200` cycle is complete and reproducible.

- 3,268 unseen hands were materialized from the verified September 12 snapshot;
- resulting scoped union: 31,003 hands;
- Model A preflop/postflop candidates: rejected / v5 retained;
- refreshed same-structure Model B candidate: rejected / promoted v2 retained;
- strategy candidates `cap_3` / `cap_4`: inconclusive under the pre-specified paired CI gate / v83 retained;
- protected strategy TEST: not consumed;
- unified gate: `PASS`, `promotion_ready=true`;
- final production transition: `NO_OP_RETAIN_ALL`;
- authoritative closure: `training/runs/20260912_population_increment_cycle/FINAL_STATE.json`.

The completed cycle is now the reference implementation for automation under #13.

## Execution order

### Lane A — user-facing deliverables

**1. #74 — publish a coherent `NLHE 100-200` user artifact bundle.**

Build the first immutable package directly from the verified final state. The bundle must include:

- the user's source-semantics `custom.json` (source SHA-256 `1248258112562757e49df545e97f9e54b2dde163fdc755adf0029e89e580e8cb`);
- promoted `preflop_population_model_v5.json`;
- promoted `postflop_population_model_v5.json`;
- `MANIFEST.json` with bundle ID, population, source commit/final-state identity, exact artifact hashes/roles/schema versions and engine compatibility;
- README and checksums.

Generate the package reproducibly in GitHub Actions. Prefer an immutable GitHub Release asset or versioned package. Publication must fail if the registry/final-state identities do not match or if a rejected/experimental artifact is substituted.

**2. #73 — display player hand classes in the replayer.**

Add canonical 169-class notation next to visible/known hole cards only:

- pair: `77`;
- suited: `AKs`;
- offsuit: `QJo`;
- never infer/reveal hidden opponent cards before the history reveals them.

Implement on the mutable application/release path, not by silently rewriting immutable v83. Preserve exact card rendering and all ACTION / sizing / EV replay behavior. Add deterministic browser regression coverage.

### Lane B — continuous-learning automation

**3. #13 — automate the completed cycle.**

Turn the proven manual/repo-native sequence into an orchestrated workflow:

1. ingest/persist raw source;
2. exact hand-ID audit/deduplication;
3. deterministic split assignment;
4. materialize normalized increment;
5. train/rebuild Model A candidate(s);
6. train/rebuild independent Model B candidate(s);
7. run VALIDATION-only selection gates;
8. evaluate strategy only against an explicitly valid independent environment;
9. reserve TEST for frozen finalists according to each contract;
10. execute unified gate;
11. atomically promote only authorized artifacts, otherwise retain pointers unchanged;
12. generate immutable final state and user bundle candidate.

Automation must prove the retain-all case as strongly as a promotion case: rejected candidates must not alter registry, model assets, engine release or site.

### Lane C — next statistical improvement

**4. #61 — targeted preflop topology experiment.**

Use the TRAIN-only audit of the 4,727 unseen rows to define a bounded candidate rather than expanding all 1,017 missing contexts. The initial candidate boundary should focus on pre-specified high-support contexts (notably the 51 contexts with n>=20) and dominant structural families such as `VS_LIMPERS`, `VS_ISO` and `VS_RFI_CALLERS`.

Choose any support threshold/backoff/topology hyperparameter on VALIDATION only. TEST remains reserved until one frozen candidate exists. Promotion requires non-regression against current Model A v5 and the unified gate contract.

### Lane D — publication verification

**5. #45 — verify actual production deployment.**

Cloudflare preview/build success is not equivalent to a verified production deployment. Close #45 only after recording:

- canonical production public URL;
- exact deployed Git commit/build/version identity;
- successful live smoke of analyser, trainer and required static model assets;
- agreement between deployment metadata and repository release identity.

This lane is independent of retain-all training-cycle closure unless a future cycle actually changes the site/application artifact.

## Promotion rules

### Data

- Exact hand-ID deduplication is mandatory.
- Source archives and generated increments remain immutable.
- TRAIN / VALIDATION / TEST must remain disjoint and reproducible.
- Parser/language fixes require revalidation of evidence materially affected by the parser defect.

### Model A

- Model A is the only population model allowed to drive analyser Hero EV.
- Candidate topology/weights are selected on VALIDATION only.
- A rejected candidate remains persisted/rebuildable as evidence and cannot leak into `training/models/` or trainer Model A assets.

### Model B

- Production Model B remains independent from Model A outputs.
- Same-structure production refreshes require paired holdout evidence and their own explicit decision.
- Richer response-conditioned candidates may be used as strategy-evaluation environments only when their validity/scope has been proven; this does not implicitly promote them to production Model B.

### Strategy

- Strategy comparisons must use matched deterministic scenarios/seeds and the same independent environment.
- Tune/select on VALIDATION; protected TEST is used only for a frozen finalist when the contract authorizes it.
- Positive mean EV alone is insufficient. The pre-specified uncertainty/non-regression gate controls promotion.
- Keep implementation/parser fixes separate from deliberate strategy changes.
- Scope claims must match the benchmark: current promotion evidence is heads-up postflop, not overall cash-game win rate or multiway/preflop strategy.

### Product/release

- `user/releases/` engine identity and `site/index.html` assembled-product identity are distinct.
- Do not modify the site merely because a training run completed.
- A rejected/retain-all cycle must leave production pointers and site assets unchanged.
- User-facing bundles must be derived from an accepted/final production state and versioned immutably.

## Current source-of-truth files

- registry: `training/registry.json`;
- final cycle state: `training/runs/20260912_population_increment_cycle/FINAL_STATE.json`;
- unified promotion contract: `training/PROMOTION_GATE_CONTRACT.json`;
- final gate evidence/report: `training/gates/20260912_evidence.json`, `training/gates/20260912_report.json`;
- promoted Model A: `training/models/preflop_population_model_v5.json`, `training/models/postflop_population_model_v5.json`;
- promoted Model B v2: `training/runs/20260912_independent_profiles_v2/model/`;
- promoted engine: `user/releases/poker_range_equity_offline_multiway_v83.html`;
- assembled application: `site/index.html`;
- final-state verifier: `tools/finalize_training_cycle.py`.

## Lower-priority historical work

Historical bootstrap cleanup (#1 and related archival debt) is non-blocking. Preserve it for provenance work, but do not destabilize the verified v83 / Model A v5 / Model B v2 production state to reconstruct obsolete artifacts unless a concrete regression or reproducibility requirement depends on them.

# Project Plan

## Operating model

The project is a continuous-learning poker analyser/trainer with deliberately separated layers:

1. **Population data** — hand histories and derived datasets scoped to one explicit poker population.
2. **Model A** — population model consumed by the analyser for Hero recommendations/EV.
3. **Model B** — independent opponent environment for simulation/evaluation/trainer opponents; it must not be trained from Model A outputs.
4. **Hero strategy** — action/sizing policy evaluated against an independent environment before promotion.
5. **Static application** — analyser/replayer/trainer under `site/`, versioned independently from engine/model promotions.
6. **Distribution/deployment** — immutable user packs and the Cloudflare-served application, whose live identity must be verified separately.

Every scientific cycle must preserve deterministic TRAIN / VALIDATION / TEST assignment, immutable evidence, explicit retain/promote decisions, exact artifact identities and rollback. A valid cycle may end with no production change.

## Master plan

The active backlog is governed by **issue #92**. The dependency graph below replaces the obsolete pre-#92 execution plan. Closed tickets remain historical evidence and must not be reactivated unless a new defect is demonstrated.

| Rank | Priority | Issue | Required before closure |
|---:|:---:|---|---|
| 1 | P0 | #93 — reconcile handoff documentation and release identity | none |
| 2 | P0 | #94 — certify PokerStars NLHE 100/200 Zoom play-money corpus | none |
| 3 | P0 | #95 — isolate datasets/models/strategies by population | #94 |
| 4 | P0 | #96 — unify preflop context and probability contracts | #95 |
| 5 | P1 | #97 — Hero range repository/editor | #96 |
| 6 | P1 | #98 — Hero range compliance in replayer | #97 |
| 7 | P1 | #99 — define preflop/full-hand evaluation gates | #96 |
| 8 | P1 | #100 — full-hand and multiway game core | #96 |
| 9 | P1 | #101 — real Model A preflop range/response refit | #99 |
| 10 | P1 | #102 — Model A postflop continuation refit | #99 |
| 11 | P1 | #103 — independent Model B latent ranges / reveal bias | #99 |
| 12 | P1 | #104 — card/price/sequence-conditioned Model B behavior | #103 |
| 13 | P1 | #105 — complete multiway hand simulation against B | #100, #104 |
| 14 | P1 | #106 — preflop action/sizing/EV with multiway continuation | #100, #101, #102 |
| 15 | P1 | #107 — generate exploitative Hero ranges from preflop engine | #106, #97 |
| 16 | P1 | #108 — select preflop strategy on complete benchmark | #105, #107 |
| 17 | P1 | #109 — preflop guidance in replayer/trainer | #98, #108 |
| 18 | P1 | #110 — version complete packs and GitHub Release ZIPs | #95, #97 |
| 19 | P1 | #111 — Cloudflare pack catalogue/load/update | #110 |
| 20 | P1 | #112 — generic complete training/evaluation cycle from snapshot | #108 |
| 21 | P1 | #113 — one-prompt path through release and verified production | #112, #111, #109, #45 |
| 22 | P2 | #114 — targeted shared-component extraction | #96 |
| parallel | P1 | #45 — verify production Cloudflare URL/identity/live smoke | #93 only if metadata correction is required |
| non-blocking | P3 | #1 — historical provenance archive cleanup | none |

## Milestones

### M0 — certified population and trustworthy baseline

Close #93, #94, #95 and #96. The result must be an unambiguous target-population identity, isolated population state and one shared preflop context/probability contract.

### M1 — first user-facing Hero range delivery

Close #97 and #98. The user can inspect/edit/import/export personal ranges and see compliance in the replayer without waiting for a newly optimized strategy.

### M2 — valid models and simulator for the target problem

Close #99–#105. Model parameters must be those actually consumed by runtime; Model B remains independent; full-hand/multiway accounting and behavior become reproducible enough for strategy evaluation.

### M3 — guided preflop strategy

Close #106–#109. Advice must expose **action + evaluated sizing + EV tied to that sizing**, and the promoted/default policy must be selected under the precommitted full-hand benchmark rather than by intuition or a jam cap.

### M4 — practical distribution

Close #110, #111 and #45. A compatible pack is identifiable, immutable, downloadable/loadable and the live Cloudflare application identity is independently proven.

### M5 — new hands to reproducible decision/release

Close #112 and #113. A later snapshot must trigger actual refits/evaluation, produce `PROMOTE`, `RETAIN_BASELINE`, `NO_OP` or `BLOCKED` with durable evidence, and complete publication only when authorized.

## Immediate execution rules

### Population isolation

Do not treat `NLHE 100-200` blind matching as proof of PokerStars Zoom/play-money identity. #94 must measure the corpus before #95 creates the durable population namespace. Future populations such as 250/500 or NL5 must never share active pointers, caches or strategy state by accident.

### Preflop parity decision from #88

#88 is closed. Historical key separators were shown to be semantically equivalent under the retained v5 matcher. Do not re-run a mass topology expansion simply because strings differ. Any future behavior change is a new candidate and must pass the new contracts/gates.

### Hero ranges versus opponent ranges

Hero personal/calculated ranges and estimated opponent ranges are different artifacts with different provenance. Never use an opponent imitation as a Hero strategy merely because both are represented on a 169-class grid.

### Decision contract

For every covered recommendation, converge on one before-action object shared by engine, feed, details, exports and trainer:

- legal action;
- total target amount (`bet_to`/raise-to);
- incremental cost;
- EV associated with that exact evaluated action/amount;
- useful alternatives;
- support/confidence/coverage status.

A display must not pair an action with the EV of another sizing.

### Model A

- Parameters claimed as retrained must affect the runtime function actually consumed by the analyser.
- Candidate fitting/selection occurs under #99 and never on protected TEST before a finalist is frozen.
- Existing v5 artifacts remain immutable when a candidate is rejected.

### Model B

- Model B may consume observed decisions/reveals but not Model A recommendations, EVs or pseudo-labels.
- Unknown folded cards remain unknown; revelation bias must be explicit.
- Production promotion of B, use of B as an experimental environment and promotion of Hero strategy are three separate decisions.

### Strategy

- Compare policies on matched scenarios/seeds and a declared independent environment.
- Use complete-hand outcomes once #105 is available, including preflop folds/wins, multiway pots and all-ins.
- Positive sample mean is insufficient when the precommitted uncertainty gate is not met.
- `RETAIN_BASELINE` is a successful scientific outcome when evidence is insufficient for promotion.

### Product/release identity

`site/RELEASE.json` identifies engine and assembled application separately. `tools/write_site_release.py --check` must remain green whenever functional site bytes change. `published=true` and a repository/build identity are not live-production proof; #45 owns that proof.

### Continuous workflow

Do not equate successful ingestion with successful training, and do not equate CI success with scientific promotion. #112/#113 must retain separate states for ingestion, fit, evaluation, decision, persistence, publication and rollback/recovery.

## Current source-of-truth files

- master backlog: GitHub issue #92;
- status: `.project/STATUS.md`;
- handoff protocol: `.project/HANDOFF.md`;
- registry: `training/registry.json`;
- final 2026-09-12 state: `training/runs/20260912_population_increment_cycle/FINAL_STATE.json`;
- promotion contract: `training/PROMOTION_GATE_CONTRACT.json`;
- promoted Model A: `training/models/preflop_population_model_v5.json`, `training/models/postflop_population_model_v5.json`;
- promoted Model B v2: `training/runs/20260912_independent_profiles_v2/model/`;
- promoted engine: `user/releases/poker_range_equity_offline_multiway_v83.html`;
- assembled application: `site/`;
- application identity: `site/RELEASE.json` generated/verified by `tools/write_site_release.py`.

## Historical work that is already acquired

Earlier trainer/replayer, custom-range, bundle, automation, atomic-promotion, topology-audit and parity tickets remain closed. Their code and evidence are inputs to the issues above. Do not duplicate them merely because an old plan named #13, #61, #73 or #74 as future work.

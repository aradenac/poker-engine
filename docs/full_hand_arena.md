# Full-hand multiway arena (#105)

The full-hand arena extends the historical heads-up postflop harness without changing it. It separates scenario generation, rules/accounting, opponent behavior, and Hero policy so each component can be selected and audited independently.

- `tools/simulation/full_hand_scenarios.py`: selects only pre-deal table geometry and freshly deals every simulated hand.
- `tools/simulation/full_hand_arena.py`: plays a trusted scenario from blinds through settlement using the shared `NoLimitHoldemState` from #100.
- `tools/simulation/model_b_public_reference.py`: fail-closed loader for the exact public-only behavior reference retained by #104.
- `tools/simulation/full_hand_benchmark.py`: reproducible benchmark wrapper for certified population scenarios.

## No conditioning on reaching the flop

The old `scenarios.py` remains a deliberately limited HU-postflop benchmark. Its filters (known Hero cards, observed flop, exactly two active players, no preflop all-in) must not be used for the full-hand benchmark.

`eligible_table_templates()` keeps only information available before the deal: seats, button, stake, starting stacks and position labels. Historical actions, shown cards, board cards and outcomes are not eligibility criteria. Once a table template is selected, all hole cards and the five-card runout are dealt again from a complete deck with a deterministic seed.

For the certified Zoom population used by #104, the benchmark additionally filters source-hand IDs through `population_certification.json`; matching the stake alone is not enough because the source archives also contain excluded regular-format hands.

This lets the simulated distribution naturally contain folds before the flop, pots won without a flop, limped multiway pots, raises/3-bets/4-bets, short and full-stack all-ins, main/side pots and uncalled refunds.

## Randomness and paired comparisons

Every scenario persists independent deterministic namespaces for deck materialization, opponent decisions, Hero-policy randomness, and Monte-Carlo work. The complete deal is materialized before either policy is evaluated. Candidate/baseline comparisons reuse the exact same `scenario_id`.

Repeated deals based on the same historical table template share a `cluster_id`. Reports expose both total simulated hands and independent source-hand clusters and compute uncertainty from cluster means rather than treating repetitions of one template as unrelated observations.

## Policy and information contract

A policy exposes:

```python
decide(public_state, *, seed_parts, actor, hole_cards, profile,
       relative_position, pot_type, preflop_role) -> dict
```

The returned mapping uses canonical actions (`FOLD`, `CHECK`, `CALL`, `RAISE`) and `target_total_bb` for raises. `BET` and `ALL_IN` are convenience labels normalized against the #100 legal-action contract.

Before every decision the arena rebuilds a detached `NoLimitHoldemState` from its public snapshot. It passes that state plus **only the actor's two hole cards**. Neither Hero nor an opponent can obtain another player's cards or an unrevealed board card through the arena API. The full trusted deal remains outside the public game state.

### Exact #104 public-feature semantics

The arena must pass the same public labels that were used to fit #104. This is intentionally regression-tested.

- `relative_position` keeps the historical field name but contains the actor's canonical table position (`BTN`, `SB`, `BB`, `LJ`, `HJ`, `CO`, etc.) on every street.
- Before a preflop decision, `pot_type` is one of `UNOPENED`, `LIMPED`, `SINGLE_RAISED`, `THREE_BET`, `FOUR_BET_PLUS`; `preflop_role` describes the actor's prior action (`NO_PRIOR_ACTION`, `AGGRESSOR`, `LIMPER`, `CALLER`, `CHECKER`, `OTHER`).
- Postflop, the preserved preflop summary uses the historical Model-B labels `LIMPED`, `SRP`, `3BP`, `4BP_PLUS` and roles `PFA`, `CALLER`, `LIMPER`, `BB_CHECK`, `OTHER`.

Using OOP/IP in the `relative_position` field, or using postflop pot labels preflop, would silently push #104 into unnecessary hierarchy backoff and therefore evaluate a different model.

## #104 selection boundary

#104 fitted a card-aware candidate and a public-only reference from the same certified TRAIN decisions. The frozen VALIDATION result rejected the card-aware candidate:

- action log-loss delta candidate minus reference: `+0.0059921`, paired 95% CI `[+0.0035418, +0.0084921]`;
- sizing absolute-log-error delta: `+0.0011345`, 95% CI `[-0.0084411, +0.0103784]`;
- decision: `RETAIN_PUBLIC_ONLY_REFERENCE_FOR_BEHAVIOR_COMPONENT`;
- TEST consumed: `false`;
- production Model B effect: `NONE`; Hero strategy effect: `NONE`.

`RetainedPublicModelBPolicy` therefore refuses to load anything except the artifact hash and size recorded for `public_reference_behavior.json` in the persisted #104 result. It also rejects any supposedly public reference whose action or sizing hierarchy contains `hand_bucket`. The large fitted artifact stays in the immutable GitHub Actions evidence from run `34993837824`; it is not copied into a production pointer or silently substituted for the existing promoted Model B.

## Accounting and output

All blinds, action legality, street transitions, refunds, side pots, ties and settlement come from `tools/simulation/game_core.py`. Showdown ranking reuses the independent seven-card evaluator from `model_b_runtime.py`. The current benchmark injects the historical arena rake function explicitly and labels that contract; it does not claim a newly certified external rake schedule.

Each result persists a public decision trace, Hero net BB, settlement and coverage diagnostics. `summarize_results()` reports mean BB per simulated hand and BB/100 simulated hands, simulated-hand count, independent `cluster_id` count, cluster standard error and 95% interval, coverage counts, and context distributions. BB/100 is explicitly an estimate **inside the simulated environment**, not an observed real-world winrate.

## Reproducible retained-B smoke

The dedicated GitHub Actions workflow downloads the immutable #104 artifact, verifies its SHA-256 against the committed #104 evidence, filters source hands through the certified Zoom population, and runs complete multiway hands with a deterministic passive Hero smoke policy. That Hero policy is deliberately marked `SMOKE_REFERENCE_NOT_PROMOTED`; later strategy comparison/selection belongs to the downstream benchmark tickets.

Equivalent command once the #104 artifact has been downloaded:

```sh
PYTHONPATH=. python3 -m tools.simulation.full_hand_benchmark \
  --population pokerstars_nlhe_100-200_zoom_play_6max_v1 \
  --profiles training/runs/20260912_independent_profiles_v2/model/profiles.json \
  --reference-behavior /tmp/model-b-104/public_reference_behavior.json \
  --issue-104-result training/runs/20260915_model_b_card_aware_v1/RESULT.json \
  --archive 'training/datasets/NLHE_100-200/source/NLHE 100-200.zip' \
  --archive 'training/datasets/NLHE_100-200/snapshots/20260912/source/RoiDePiqueNique.zip' \
  --certification training/datasets/NLHE_100-200/population_certification.json \
  --split TRAIN --count 4 --reps 1 --seed 20260915 \
  --output /tmp/full-hand-model-b-smoke.json
```

## Validation

Run locally for deterministic contracts:

```sh
PYTHONPATH=. python3 tests/simulation/test_full_hand_arena.py
PYTHONPATH=. python3 tests/simulation/test_full_hand_arena_seeds.py
PYTHONPATH=. python3 tests/simulation/test_full_hand_model_b_contract.py
PYTHONPATH=. python3 tests/simulation/test_full_hand_scenarios_population.py
PYTHONPATH=. python3 tests/simulation/test_game_core.py
PYTHONPATH=. python3 tests/simulation/test_game_core_consolidated_regressions.py
```

The suites cover preflop fold termination, 3-way limps, a 3-bet line, four-player all-in side pots, exact replay, hidden/future-card isolation, seed separation, #104 feature-label compatibility, fail-closed retained-reference identity, fresh population-backed deals and clustered/paired reporting.

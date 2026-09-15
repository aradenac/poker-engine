# Full-hand multiway arena (#105)

The full-hand arena extends the historical heads-up postflop harness without changing it. It is split into two policy-neutral modules:

- `tools/simulation/full_hand_scenarios.py`: selects only pre-deal table geometry from the requested population and freshly deals every simulated hand;
- `tools/simulation/full_hand_arena.py`: plays that trusted scenario from blinds through settlement using the shared `NoLimitHoldemState` from #100.

## No conditioning on reaching the flop

The old `scenarios.py` remains a deliberately limited HU-postflop benchmark. Its filters (known Hero cards, observed flop, exactly two active players, no preflop all-in) must not be used for the full-hand benchmark.

`eligible_table_templates()` keeps only information available before cards/actions: seats, button, stake, starting stacks and position labels. Historical actions, shown cards, board cards and outcomes are not eligibility criteria. Once a table template is selected, all hole cards and the five-card runout are dealt again from a complete deck with a deterministic seed.

This lets the simulated distribution naturally contain:

- folds before the flop and pots won without a flop;
- limped multiway pots;
- raises, 3-bets/4-bets and squeezes when policies choose them;
- short and full-stack all-ins;
- main/side pots and uncalled refunds through the #100 accounting core.

## Randomness and paired comparisons

Every scenario persists independent deterministic namespaces for:

- deck materialization;
- opponent decisions;
- Hero-policy randomness;
- Monte-Carlo work performed by a policy/oracle.

The complete deal is materialized before either policy is evaluated. Candidate/baseline comparisons reuse the exact same `scenario_id`. Opponent decision seeds do not contain a Hero policy name, so paired policies see the same opponent random draws until their public trajectories diverge.

Repeated deals based on the same historical table template share a `cluster_id`. Reports therefore expose both total simulated hands and the number of independent source-hand clusters and compute uncertainty from cluster means instead of treating repetitions of one template as unrelated observations.

## Policy and information contract

A policy exposes:

```python
decide(public_state, *, seed_parts, actor, hole_cards, profile,
       relative_position, pot_type, preflop_role) -> dict
```

The returned mapping uses canonical actions (`FOLD`, `CHECK`, `CALL`, `RAISE`) and `target_total_bb` for raises. `BET` and `ALL_IN` are accepted only as convenience labels and normalized against the legal actions from #100.

Before every decision the arena rebuilds a detached `NoLimitHoldemState` from its public snapshot. It passes that state plus **only the actor's two hole cards**. The opponent policy therefore has no Model-A/Hero recommendation input, and neither Hero nor an opponent can obtain another player's cards or an unrevealed board card through the arena API. The full trusted deal stays in the scenario envelope, outside the shared game state.

The intended concrete opponent is the card-aware independent Model B from #104. #105 deliberately does not duplicate that runtime while #104 is active; its `CardAwareModelBPolicy.decide(...)` contract is directly compatible with this arena.

## Accounting and output

All blinds, action legality, street transitions, refunds, side pots, ties and settlement come from `tools/simulation/game_core.py`. Showdown ranking reuses the independent seven-card evaluator from `model_b_runtime.py`. A population-specific rake function is injected at settlement; the arena does not hard-code a new rake rule.

Each result persists a public decision trace, Hero net BB, settlement and coverage diagnostics. `summarize_results()` reports:

- mean BB per simulated hand and BB/100 simulated hands;
- simulated-hand count and independent `cluster_id` count;
- cluster-robust standard error and 95% interval when at least two clusters exist;
- coverage counts for flop reach, multiway flops, all-ins, side pots and refunds;
- context distributions by table size, preflop raise bucket and terminal state.

The report explicitly labels BB/100 as an estimate **inside the simulated environment**, not an observed real-world winrate.

## Validation

Run:

```sh
python3 tests/simulation/test_full_hand_arena.py
python3 tests/simulation/test_game_core.py
python3 tests/simulation/test_game_core_consolidated_regressions.py
```

The deterministic tests include preflop fold termination, 3-way limps, a 3-bet line, a four-player preflop all-in with three pot layers, exact replay, hidden/future-card isolation, fresh-deal materialization and clustered/paired reporting.

## Dependency status

#100 is complete and is the sole accounting/rules core. #104 remains the source of the real card-aware Model-B policy and its fitted behavior artifact. Until #104 is merged and its accepted artifact is wired into a population, this arena is an executable policy-neutral foundation and #105 must not be represented as a completed independent-B benchmark.

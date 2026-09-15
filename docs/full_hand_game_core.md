# Full-hand NLHE game core (#100)

`tools/simulation/game_core.py` is the policy-free rules and accounting core for full no-limit hold'em hands. It is deliberately separate from Model A, Model B, card equity and recommendation code so the same chip ledger can be reused by training, replay and simulation.

## State and action contract

`NoLimitHoldemState` receives seats in clockwise order, the button and starting stacks in BB. It posts blinds, tracks the public board, per-street and lifetime contributions, folds/all-ins, the live price and the exact pending action order from preflop through river.

`legal_view()` is a **before-action** view. It distinguishes:

- `actor_sunk_total_bb`: chips committed earlier in the hand;
- `to_call_bb`: incremental cost of calling now, capped by the actor's remaining stack;
- `full_to_call_bb`: uncapped price gap;
- `min_raise_to_bb` / `max_raise_to_bb`: total-contribution targets, matching the target-versus-increment semantics introduced by #96;
- `raise_reopened`: whether the actor is still entitled to raise after prior short all-ins.

A short all-in raise does not reopen betting for players who already acted after the last full raise. A later full raise does. A short all-in big blind does not reduce the nominal one-BB preflop bring-in.

## Pots, refunds and settlement

Actual contributions determine pot layers. Folded players continue to fund the layers they reached but are never eligible to win them. A unique unmatched top contribution is returned before settlement. Main and side pots therefore preserve both contribution caps and eligibility.

Showdown ranks are passed into `settle_showdown()` by the caller; hole cards are never stored by the game state. Showdown settlement requires the public runout through river. Ties split every eligible layer. Rake is injected as a `net_pot_fn(gross_bb)` callback, so the rules core is not coupled to one population's rake schedule. Settlement checks conservation of starting chips after payouts plus rake.

The historical heads-up postflop arena remains a compatibility harness. New full-hand/multiway work (#105 and downstream) should consume this core rather than duplicate its accounting.

## Deterministic snapshots and hand-history replay

`to_snapshot()` / `from_snapshot()` serialize resumable **public** state only. The snapshot schema is `nlhe-game-state/v1`; no hole cards or future board cards are present.

`tools/simulation/hand_history_state.py` replays public PokerStars EN and historical FR action wording into the same core and records a snapshot immediately before each voluntary action. It validates PokerStars raise syntax (`raises X to Y` / `relance X à Y`) correctly: `X` is the raise increment above the prior price, while `Y` is the total target. The parser also derives nominal blind units from the header so an all-in blind posted short does not corrupt BB normalization.

## Validation

Run the deterministic rule/accounting suite with:

```sh
python3 tests/simulation/test_game_core.py
python3 tests/simulation/test_hand_history_state.py
python3 tests/simulation/test_rollout_accounting.py
```

Fixtures cover the BB option after limps, short/full raise reopening, all-in calls, multiway side pots, dead folded contributions, uncalled overbets, ties, pluggable rake, four-street order, snapshot/resume, sunk-versus-incremental costs, EN/FR parity and future-card leakage.

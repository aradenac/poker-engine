# Full-hand multiway NLHE core

Issue: #100

## Scope

`tools/simulation/full_hand_core.py` is a policy-free no-limit hold'em state machine for the cash-game simulator. It owns only betting order, legal wagers, chip accounting, street progression, pots and settlement. Model A/B policies and hand-strength/oracle code remain outside this module.

The core starts before the blinds and can run through settlement. It supports heads-up and multiway hands, short blinds, short all-ins, incomplete bets, minimum raises, cumulative short raises that reopen action, folds, checks/calls/bets/raises, uncontested returns, main/side pots, ties, and a caller-supplied population rake function.

## Accounting invariants

All amounts are expressed in big blinds. For every player and after every accepted action:

- `stack_bb + total_contribution_bb == starting_stack_bb`;
- street contribution is non-negative and cannot exceed total contribution;
- the current wager is never below a player's street contribution;
- a player flagged all-in has zero remaining stack.

`build_pots()` slices contributions by contribution level. A level with one contributor is an uncalled amount and is refunded; folded chips remain in the pot but the folded player is removed from eligibility. `settle()` applies rake once to the total contested amount, then allocates the net amount proportionally to pots before winner/tie splitting. The settlement checks `payouts + refunds + rake == gross contributions`.

`Settlement.net_by_player_bb` is the full-hand result and therefore includes forced blinds. At a decision point, `incremental_cost_to_bb()` reports only chips that would be committed from that point onward; prior blinds and bets are sunk.

## Betting details

Preflop uses the nominal big blind as the bring-in even when the posted big blind is a short all-in. Postflop, an opening all-in below one big blind is an incomplete bet and may be completed to one full bet. A short raise does not by itself reopen betting for a player who has already acted; cumulative short raises do reopen once the increase faced since that player's previous action reaches the last full raise size.

When only one non-all-in player remains, further aggression is disabled. If that player still owes chips to an all-in wager, only call/fold (or an all-in call when short) remains possible.

## Snapshots and hidden information

Two snapshot surfaces deliberately have different trust boundaries:

- `checkpoint()` is the **trusted engine checkpoint**. It is sufficient for deterministic stop/resume and may contain pre-sampled private hole cards and a pre-sampled future board runout. It must not be supplied to a strategy policy.
- `decision_snapshot(player)` / `player_view(player)` is the **policy input**. It contains only that player's hole cards, the currently revealed board, public stacks/contributions and legal actions. Opponent cards and unrevealed board cards are omitted.

A JSON round-trip of `checkpoint()` is tested to reproduce the exact subsequent state.

## PokerStars EN/FR reconstruction

`tools/simulation/pokerstars_prefix.py` reconstructs the core from a strict PokerStars hand-history prefix. The function intentionally accepts a prefix, not a completed hand, so future streets/actions cannot enter the reconstructed state. It normalizes the English and French action grammars used by the repository, including French button/seat/blind/action forms.

The reference fixture `tests/fixtures/full_hand_core_reference_hh.json` contains semantically equivalent EN/FR histories and the line boundaries immediately before every decision. Tests reconstruct each prefix independently and require byte-equivalent core checkpoints and the expected next actor.

The parser fails closed outside the current population scope: one small blind, one big blind, no ante/dead-blind accounting. Expanding that scope should add explicit accounting rather than silently treating extra forced bets as ordinary actions.

## Verification

Run:

```bash
python -m unittest -v tests/simulation/test_full_hand_core.py
```

The focused suite covers:

- BB option after limps and nominal bring-in with a short all-in BB;
- preflop minimum reraises;
- short all-in raises, cumulative reopening, and incomplete postflop all-in completion;
- preflop multiway all-ins, main/side pots and uncalled refunds;
- folded contributors, ties, rake and chip conservation;
- an uncontested hand whose full result includes blinds;
- separation of sunk contributions from incremental decision cost;
- deterministic checkpoint/resume and redacted policy snapshots;
- staged board revelation;
- EN/FR PokerStars reference prefixes reconstructed before every decision.

No scientific model, calibration input, random budget or population parameter is changed by this issue, so no new scientific run manifest is required. The new reference-HH fixture is the deterministic replay evidence for this rules-engine change.

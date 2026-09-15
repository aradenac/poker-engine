# Canonical preflop decision contract

Issue #106 needs one object shared by the future feed, detail view, export and trainer so an action recommendation cannot become detached from the exact sizing and EV that were evaluated.

This document freezes only that **representation and validation boundary**. It does not claim that the current engine already performs the full multiway search from #106, and it does not authorize a production strategy change. Model A preflop/postflop work from #101/#102 remains a dependency for the scientific implementation.

## Schema

`src/preflop/decision.js` owns `poker-preflop-decision/v1`.

A decision contains:

- the canonical `context_id` and optional `population_id`;
- the actor contribution before acting;
- the normalized strategic actions that were legal for this search;
- every **evaluated alternative** with action, `target_total_bb`, incremental cost and its own `ev_bb`;
- support, confidence and two separate uncertainty channels;
- the selected alternative ID plus a denormalized top-level action/sizing/cost/EV copied from that alternative;
- an explicit search record containing candidate IDs, sizing-grid provenance, budget and seed.

`bet_to_bb` is an alias of `target_total_bb` in the canonical output. Integration code may convert BB to table chips using the hand's blind scale, but it must not recompute a different strategic amount.

## EV reference

All EVs use:

`decision_point_incremental_bb`

Past contributions are sunk at the decision boundary. Therefore:

- `FOLD` has incremental cost `0`, no target-total amount and EV `0` under this reference;
- `CHECK` has incremental cost `0` and no target-total amount, but its EV may be non-zero because future continuation still has value;
- chip-committing alternatives use `incremental_cost_bb = target_total_bb - actor_contribution_bb`.

This prevents a previously committed blind/call from being charged a second time when comparing alternatives.

## Sizing and EV identity

An EV belongs to one exact evaluated alternative, not merely to an action family. A search may therefore contain, for example, three `3BET` alternatives at 6.5, 7.5 and 9 BB, each with a different EV.

The selected alternative must:

1. exist among the alternatives actually evaluated;
2. be included in the declared search candidates;
3. have maximal EV among the alternatives supplied to the contract.

The top-level `action`, `target_total_bb`, `bet_to_bb`, `incremental_cost_bb` and `ev_bb` are derived from that selected row. `validateDecision()` rejects an exported/feed object whose top-level values were later changed independently.

This is the contract that future feed/detail/export/trainer integration must consume rather than separately reconstructing action, sizing or EV.

## Legal actions

The representation currently names the strategic actions required by #106:

- `FOLD`, `CHECK`;
- `LIMP`, `OVERLIMP`, `CALL`;
- `OPEN`, `ISO`, `SQUEEZE`, `3BET`, `4BET`;
- `SHOVE`, `CALL_SHOVE`.

These are decision labels, not a replacement for the lower-level #100 game-core legality rules. Future integration must map the game state's legal `CALL/RAISE/JAM` mechanics to these strategic labels before constructing the decision object. The contract rejects alternatives outside the supplied normalized legal-action set.

## Support and uncertainty

Each alternative carries its own evidence metadata:

- `support.observations`, `support.backoff_level`, `support.source`;
- `confidence`, which may be `null` when no calibrated confidence exists;
- `uncertainty.monte_carlo` for sampling error (`standard_error_bb`, sample count, method);
- `uncertainty.model` for model/data uncertainty (interval, method, status).

The two uncertainty channels are deliberately distinct. A large Monte-Carlo budget cannot be presented as high model confidence in a sparse or backed-off context.

## Search provenance

`search` records:

- `candidate_ids` — the evaluated grid visible to the selector;
- `sizing_grid_source` — e.g. observed sizings plus a local grid;
- `budget` — evaluator-specific non-negative integer budget;
- `seed` — deterministic identifier when applicable;
- free-form notes.

The scientific implementation under #106 still has to define the actual grid construction, continuation budget and multiway evaluator after #101/#102 stabilize. This contract only prevents that future search from returning an ambiguous `(action, EV)` pair with the sizing lost.

## Fail-closed behavior

The contract throws instead of silently repairing:

- missing/unknown/illegal actions;
- duplicate alternative IDs;
- negative or inconsistent incremental costs;
- a target amount attached to fold/check;
- non-zero fold EV under the declared reference;
- malformed support or uncertainty values;
- inverted model uncertainty intervals;
- selection of an unevaluated, out-of-grid or non-maximal alternative;
- a top-level exported decision that no longer matches its selected alternative.

Uncovered model contexts are not given invented support or confidence. Upstream evaluators should either omit such alternatives or carry `null` confidence / explicit backoff metadata and keep the candidate experimental until the independent benchmark required by #106/#108.

## Current scope

This tranche intentionally does **not** copy `decision.js` into `site/` and does not alter `site/RELEASE.json`: no browser feature consumes the module yet. Site integration belongs to the later #106 implementation once #101/#102 are stable and must update the release identity at that time.

`tests/preflop/test_decision_contract.js` covers the representation invariants independently of the unfinished scientific evaluator.

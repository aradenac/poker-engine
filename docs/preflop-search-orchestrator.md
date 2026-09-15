# Preflop action / sizing search orchestrator (#106)

`src/preflop/search.js` is the model-agnostic search layer between the canonical before-action context from #96 and the canonical decision object from #106 (`poker-preflop-decision/v1`). It does **not** claim that any hard-coded sizing is optimal and it does not promote a Hero strategy.

## Search contract

The caller supplies:

- one `poker-preflop-context/v1` before-action context;
- Hero's hand class and population identity when known;
- an explicit raise sizing grid, normally derived from observed sizes or a separately versioned candidate grid;
- a total search budget and seed;
- an asynchronous continuation evaluator.

The continuation evaluator is called once for every non-fold candidate with:

- the exact semantic action and `target_total_bb` being evaluated;
- the incremental cost implied by the actor's contribution;
- the complete canonical context and `remaining_to_act_positions`;
- its deterministic share of the declared search budget;
- the hand class, population and search seed.

It returns `ev_bb`, support, confidence and separate Monte-Carlo/model uncertainty. Those fields are copied into the corresponding alternative before `src/preflop/decision.js` selects the maximum-EV decision. Consequently an EV cannot silently migrate from one sizing to another.

`FOLD` is the only candidate not sent to the continuation evaluator: under the frozen `decision_point_incremental_bb` reference its EV is exactly `0 BB` by definition.

## Semantic actions

The structural #96 actions are projected into the Hero vocabulary only when the mapping is unambiguous:

| Structural state | Hero action |
| --- | --- |
| fold / free check | `FOLD` / `CHECK` |
| first limp / existing limpers | `LIMP` / `OVERLIMP` |
| call / call of the last jam | `CALL` / `CALL_SHOVE` |
| first raise, no limpers / with limpers | `OPEN` / `ISO` |
| raise facing one raise / one raise plus caller(s) | `3BET` / `SQUEEZE` |
| raise facing a 3-bet | `4BET` |
| canonical jam | `SHOVE` |

A non-all-in raise beyond the current semantic 4-bet vocabulary fails closed. It is not mislabeled as a shove or silently dropped.

## Sizing grid

The orchestrator never invents a default raise size. If `RAISE` is legal, at least one explicit candidate must survive the canonical bounds:

- above the current price;
- at or above `min_raise_to_bb`;
- strictly below `max_raise_to_bb` because the stack cap is represented separately by `SHOVE`.

Duplicate/out-of-bounds points are removed deterministically. The declared `sizing_grid_source` is persisted in the decision search provenance.

## Determinism and budget

The non-fold continuation candidates split the declared integer budget deterministically in candidate order; any remainder is assigned to the earliest candidates. The same context, grid, evaluator, budget and seed therefore receive the same requests.

Maximum EV is the primary selector. Exact EV ties use lower incremental cost, then stable candidate ID order. This tie-break changes no EV and exists only to make replay deterministic.

## Current boundary

This tranche is deliberately independent from the active #101/#102 fits. It proves the action/sizing search and result identity without freezing their interfaces prematurely. Completing #106 still requires a real continuation evaluator backed by the accepted Model-A preflop/postflop components and full-hand multiway continuation, then the independent benchmark required by #92/#108.

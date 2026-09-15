# Canonical preflop context and probability contract

Issue #96 defines the shared preflop decision boundary used by new training, replayer, evaluation and strategy work.

## Timing and information boundary

`poker-preflop-context/v1` describes the table **immediately before one voluntary action**.

The structural context is deliberately card-free. It must not contain hole cards, board cards, showdown reveals or future actions. A hand class may be supplied separately to a probability consumer that evaluates:

`P(action, sizing | hand, context)`

This separation is the no-lookahead guarantee used by the replayer and future evaluators.

## Context fields

The canonical context includes:

- `table_size`, `actor_position`;
- ordered prior voluntary `history` as `(position, action)` pairs;
- `family` and `raise_level`;
- `live_positions`, `all_in_positions`, `remaining_to_act_positions`;
- `limper_positions`, `caller_positions`;
- `contribution_bb_by_position` and `actor_contribution_bb`;
- `current_price_bb`, `to_call_bb`, `free_check`;
- `pot_before_bb`;
- `actor_remaining_bb`, `effective_stack_bb`;
- `legal_actions`;
- `min_raise_to_bb`, `max_raise_to_bb`, `raise_reopened`;
- a deterministic canonical key / context id.

Amounts are expressed in big blinds.

## Amount semantics

Do not conflate the chips committed now with the total target of a raise.

- `incremental_cost_bb`: additional chips committed by this action now;
- `target_total_bb`: total street/preflop contribution after a raise/jam;
- check/fold incremental cost: `0`.

The training extractor exposes these as `action_sizing_v1` when v1 enrichment is enabled.

## Historical extraction compatibility

Closed historical runs are immutable evidence. Therefore `tools/training/increment_decisions.py` keeps its historical output by default.

New work that requires the richer context must opt in:

```bash
python3 tools/training/build_incremental_decisions_v2.py \
  --source <snapshot-or-increment.zip> \
  --out <decisions.jsonl> \
  --summary <summary.json> \
  --preflop-contract-v1
```

CI rebuilds the closed 2026-09-09 JSONL without the option and compares it byte-for-byte with persisted evidence.

## History normalization and issue #88

Historical v5 canonical keys used commas between multiple history tokens while repo-native keys use `>`. These separators are representation-only. New diagnostics normalize both to the same ordered sequence.

Persisted v5 keys are not rewritten.

The incumbent v5/v83 exact-match projection remains:

1. actor position;
2. table size;
3. raise level;
4. family;
5. live-position array;
6. all-in-position array;
7. ordered `(position, action)` history.

`free_check`, remaining-to-act, prices, stacks and sizing bounds are intentionally **not** added to the incumbent exact predicate. Issue #88 retained that behavior on held-out VALIDATION evidence.

The richer context is therefore not permission to change production matching. A future matcher change is a candidate and must pass the evaluation gate.

## Position ordering

Two concepts are intentionally separate:

- persisted v5 live/all-in arrays use the historical compatibility order;
- actual action order is used for `remaining_to_act_positions`, including heads-up `SB_BTN -> BB` preflop order.

Do not rewrite historical arrays merely to make the two orders visually identical.

## Legal actions

The contract distinguishes:

- unopened/pre-raise payment of the BB as `LIMP`;
- post-raise payment as `CALL`;
- a zero-price BB option as `CHECK`;
- `RAISE` when a full legal raise-to target exists;
- `JAM` when an all-in increases the price, including a short all-in that cannot complete a full raise.

A player already all-in cannot be the actor of another voluntary decision.

## Probability responses

`poker-preflop-action-probabilities/v1` has two explicit behavior modes.

### `strict_legal_normalized`

For future candidates. Illegal actions are removed and the remaining legal action weights are normalized. This may change probabilities and is therefore candidate behavior, not a compatibility view.

### `incumbent_v5_passthrough`

For the promoted v5/v83 path. It:

- preserves every incumbent probability exactly;
- does not filter or renormalize because of the richer legal-action contract;
- reports `legal_actions` and `model_actions` separately;
- reports `action_set_compatible`, positive illegal model actions and missing legal model actions;
- records `source`, `backoff_level`, `confidence` and `support`;
- records that the v5/v83 matcher ignores `free_check`.

This allows the replayer/evaluator to expose incompatibilities without silently changing range conditioning.

## Backoff and confidence

Consumers must make node-selection quality observable:

- `backoff_level=exact` when the incumbent exact predicate matches;
- `backoff_level=closest` when the existing nearest-node fallback is used;
- `confidence` comes from the selected model node when available;
- `support` is the population decision count of the selected node.

Backoff metadata is diagnostic. It must not be treated as a probability that the estimated range is true.

## Shared fixtures and CI

`tests/fixtures/preflop_contract_cases.json` covers:

- unopened pot;
- 1, 2 and 3+ limpers;
- iso raise;
- open + caller / squeeze spot;
- 3-bet;
- 4-bet;
- jam;
- free BB check.

Python and JavaScript consume the same fixture inputs. `tests/preflop/test_increment_decisions_contract.py` additionally sends a synthetic PokerStars HH through the training parser. `.github/workflows/preflop-contract.yml` is the permanent cross-runtime guard.

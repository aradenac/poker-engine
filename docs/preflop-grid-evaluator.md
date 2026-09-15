# Generic preflop action/sizing evaluator (#106)

This tranche implements the policy/model-independent search seam between the shared NLHE rules core (#100), the future fitted Model-A continuation (#101/#102), and the canonical `poker-preflop-decision/v1` object already frozen by #106.

It does **not** contain population weights, infer hidden cards, promote a Hero policy, or replace the still-pending scientific integration with #101/#102.

## Decision-point EV semantics

`tools/simulation/preflop_grid_evaluator.py` evaluates a detached copy of the same `NoLimitHoldemState` for every candidate.

The continuation callback is invoked **after** the candidate action is applied and returns Hero's ending stack in BB. The evaluator computes:

```text
EV(candidate) = E[ending_stack_bb] - stack_remaining_at_decision_point
```

Therefore:

- contributions already paid before the decision are sunk;
- the current candidate's exact incremental cost is included because the rules core applies it before continuation;
- future calls/raises, refunds, rake, main pots and side pots can be reflected by the injected continuation;
- FOLD has EV 0 under `decision_point_incremental_bb`;
- CHECK has zero current incremental cost but may have non-zero continuation EV.

The evaluator never accepts a callback that directly supplies an arbitrary EV number. Requiring an ending stack makes the chip cost applied by #100 part of every non-fold sample.

## Candidate grid

The rules core remains authoritative for legal actions, minimum raise and maximum stack. The caller supplies semantic labels from the shared preflop context (`LIMP`, `OVERLIMP`, `CALL`, `OPEN`, `ISO`, `SQUEEZE`, `3BET`, `4BET`) plus a candidate raise-to grid.

The evaluator:

- adds FOLD or CHECK when legal;
- materializes the exact rule-implied call target and labels an all-in call `CALL_SHOVE`;
- filters non-all-in raise targets below the legal minimum or above stack;
- optionally adds the exact max-stack `SHOVE` boundary once;
- preserves the grid provenance on every sizing;
- applies every candidate on an independent snapshot of the same state.

The current tranche deliberately requires the caller to classify the shared preflop context rather than maintaining a second context parser.

## Continuation contract

A rollout callback receives:

```python
rollout(
    state_after_candidate,
    actor=actor,
    seed=deterministic_seed,
    sample_index=i,
    candidate={...},
) -> {"ending_stack_bb": ...}
```

Returning `{"supported": false, "reason": ...}` or raising `UnsupportedAlternative` aborts the whole decision. A partial grid is never ranked as if missing alternatives had been evaluated.

This is the seam that #101/#102 must later implement with real range evolution and postflop continuation. It can also use the full-hand rules/accounting components from #100/#105 without changing this evaluator.

## Uncertainty and support

Monte-Carlo uncertainty is computed by the evaluator from independent rollout values:

- sample count;
- standard error of the sample mean;
- deterministic seed namespace derived from base seed + candidate ID + sample index.

Model uncertainty is a separate caller-supplied object (`lower_bb`, `upper_bb`, method, status). Support and confidence are likewise injected per candidate. The evaluator does not convert Monte-Carlo noise into model confidence or vice versa.

## Output

The result uses `poker-preflop-decision/v1` fields:

- selected action;
- exact `target_total_bb` / `bet_to_bb`;
- exact incremental cost applied by the rules core;
- EV associated with that exact candidate;
- all evaluated alternatives;
- support/confidence;
- Monte-Carlo and model uncertainty separately;
- sizing-grid source;
- actual rollout budget and deterministic base seed.

The evaluator refuses `status=PROMOTED`. Selection/promotion still belongs to the independent #108 benchmark.

## Deterministic coverage

`tests/simulation/test_preflop_grid_evaluator.py` covers:

- unopened limp/open with multiple raise sizes and jam;
- two limpers → overlimp/iso;
- open + caller → call/squeeze;
- short all-in call → `CALL_SHOVE`;
- free check;
- exact action/sizing/cost/EV identity;
- separate Monte-Carlo and model uncertainty;
- fold reference EV;
- sunk-contribution semantics;
- fail-closed unsupported continuation;
- reproducible candidate-specific seed streams;
- rejection of self-promotion and invalid confidence.

Run:

```sh
PYTHONPATH=. python3 tests/simulation/test_preflop_grid_evaluator.py
python3 -m py_compile tools/simulation/preflop_grid_evaluator.py tests/simulation/test_preflop_grid_evaluator.py
```

#106 remains open after this tranche. Completion requires real #101/#102 continuations, product integration (feed/detail/export/trainer), and the independent full-hand strategy decision.

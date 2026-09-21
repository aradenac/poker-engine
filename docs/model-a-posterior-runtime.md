# Model A preflop posterior runtime adapter

Issue #312 connects the existing Model A continuation posterior reconstruction to the runtime contract introduced by #320.

## Scope

The adapter is `src/ranges/model_a_posterior_runtime.py`.

It is intentionally a thin integration layer:

- exact-combo reconstruction stays in `ModelAContinuationPolicy._posterior_from_history()`;
- exact-node lookup stays in `model_a_continuation.exact_preflop_node()`;
- combo-to-169 projection, normalization, blocker semantics and fail-closed validation stay in `src/ranges/posterior_range.py`;
- no Model A fitting, parameter tuning, candidate selection or promotion is performed.

## API

`ModelAPosteriorRuntime.posterior_record()` accepts a public `NoLimitHoldemState`, target opponent, timeline moment, hand/step identity and optional canonical public fingerprint.

The result always uses:

    poker-opponent-posterior-range/v1

Supported timeline moments:

- `BEFORE_ACTION`: the target player must be the next actor; the target action is not present in the posterior history and `public_action` is null.
- `AFTER_ACTION`: the immediately preceding public action must belong to the target player; that action is included in the history and serialized into `public_action`.

For calls/limps the sizing envelope records incremental cost, target price, pot before action and price/pot. Raises use target-total semantics. This remains compatible with later sizing-aware likelihood work without changing this adapter's reconstruction algorithm.

## Model A provenance and support

For every public action by the target opponent that contributes to the posterior, the adapter requires:

- an exact preflop Model A node;
- positive `coverage.population_decisions`;
- the observed semantic action in the node's supported action set;
- a stable node id.

The #320 record contains population/model/source identity, conservative source support (minimum population decisions among conditioning nodes), exact node ids in provenance and a deterministic source fingerprint.

Before an opponent has taken any public action, `_posterior_from_history()` exposes its existing unconditioned exact-combo prior. This is labelled `UNCONDITIONED_COMBO_PRIOR`, has source observations 0, and is projected as normalized combo probability. It is not represented as 169 cells at 100%.

## Fail closed

Missing exact node, missing positive support or unsupported observed action returns a contract-valid `UNSUPPORTED` record with probability mass 0, no exact combo weights, zero probability in all 169 classes and an explicit reason.

Invalid timeline usage returns `INVALID`. The #312 adapter is preflop-only and refuses flop/turn/river state. No hole-card argument exists in the API, so unrevealed opponent cards cannot enter reconstruction.

## Displayed semantics and Replayer hand-off

The adapter emits backend records only; the display layer derives its own
`posteriorState`. The mapping is:

| Adapter output | Display `posteriorState` |
|---|---|
| `status = AVAILABLE` with `support.source_observations > 0` and `support.backoff.level = EXACT_NODE_HISTORY` | `conditioned` |
| `status = AVAILABLE` with `support.source_observations = 0` / `support.backoff.level = UNCONDITIONED_COMBO_PRIOR` | `prior_uninformative` |
| `status = AVAILABLE` with no matched conditioning action while the kept imported/source prior is non-uniform | `source_prior_unconditioned` |
| `status ∈ {UNSUPPORTED, INVALID}` | `degenerate` |

The unconditioned `UNCONDITIONED_COMBO_PRIOR` is a uniform distribution over
the legal exact combos (`1/N`): it is notion (d) `non_informative_prior` of
`docs/opponent-range-display-contract.md`, not an estimated range. Its
`projection_169` is the normalized exact-combo probability mass sum, and the
Replayer renders it as the explicit « Prior non informatif · range non estimée »
state rather than a numeric 169 grid or an all-`100 %` range. When no public
action is matched but the kept source prior is non-uniform, the state is the
distinct `source_prior_unconditioned`, labelled « Prior source non conditionné ·
range importée non conditionnée »: a genuine a priori distribution, never
assimilated to the uniform prior nor to a conditioned posterior and never shown
as a `100 %` grid. A conditioned
`AVAILABLE` record renders as the estimated range; an
`UNSUPPORTED`/`INVALID` record renders as the fail-closed
« Posterior dégénéré · masse nulle après blockers publics » state. The known-hand
override is a separate surface and is never merged with either.

The adapter does not emit notion (b) `relative_weight` (a display-only
max-normalization) or notion (c) `inclusion_frequency` (an imported-range
input). The "Displayed semantics and Replayer UI mapping" section of
`docs/posterior-range-contract.md` carries the full four-notion table, the
mass-sum 169 projection and the Replayer surface names
(`populationRangeEstimateForPlayer`, `gridFreqMapFromEstimate`,
`openPopulationRangeModal`, `aiExportRangeSnapshot`).

## #321 acceptance scenario

Tests consume the canonical fixture:

    tests/fixtures/repro/kts_sb_two_limp_iso4_three_calls.snapshots.json

The synthetic informative Model A policy is test-only; it is not a fitted model or strategic result.

The acceptance test verifies CO and BTN after limp, BB before/after call, CO and BTN after their second call, #320 validation, canonical #321 fingerprints, fail-closed missing support, and the public-only boundary.

Run:

    python3 tests/ranges/test_model_a_posterior_runtime.py

No CENTRAL-UI, Model A refit, #108, VALIDATION or scientific TEST data is consumed or modified.

# Calculated Hero range candidate contract (#107)

This tranche defines the deterministic boundary between the preflop decision object from #106 and the Hero range repository from #97. It does **not** implement the final #106 search, select a strategy in #108, or promote any Hero policy.

## Artifact

`src/preflop/hero_range_export.js` produces `poker-hero-calculated-range-candidate/v1`.

A candidate contains:

- one exact Hero context: population, table size, position, effective stack and spot;
- a versioned `calculated` layer in a valid `poker-hero-range-repository/v1` document;
- one normalized `poker-preflop-decision/v1` evidence object for every exported hand class;
- the policy origin for every hand (`EXPLICIT_POLICY` or `SELECTED_DECISION_ONE_HOT`);
- the repository action used for every hand when the repository taxonomy is coarser than the canonical decision taxonomy;
- coverage metadata over the 169 canonical hand classes;
- caller-supplied provenance for model identities, code identity, search budget and selection state;
- `promotion_authorized: false` unconditionally.

The repository portion is directly compatible with the #97 editor/replayer contract. EV, support, confidence and uncertainty remain in the decision evidence instead of being invented as range fields.

## Completeness and contexts

A normal candidate requires all 169 classes for exactly one repository context. Partial candidates are possible only with `require_complete: false` and are diagnostic; the verifier rejects them when complete coverage is required.

Population identity must match between the exact Hero context and every decision that declares a population. The exporter does not guess another position, stack depth, spot or population.

Building over an existing repository preserves the `personal` layer. The `calculated` hands for the target context are replaced, not merged, so stale calculated rows cannot survive a new generation.

## Actions, mixes and sizings

The exporter never creates a synthetic mix from EV closeness or uncertainty.

If a row supplies an explicit `policy`, the #97 repository normalizer validates its action probabilities and sizing distributions. The selected #106 action must retain positive policy mass; when it has a `target_total_bb`, that exact selected sizing must also retain positive mass.

If no explicit policy is supplied, the exporter creates a one-hot projection of the selected #106 decision:

- selected action probability = 1;
- selected `target_total_bb`, when present, probability = 1;
- no alternative action or sizing is assigned probability merely because it was evaluated.

This distinction prevents search alternatives from being misrepresented as a mixed Hero strategy.

### SQUEEZE representation

`poker-preflop-decision/v1` distinguishes the canonical action `SQUEEZE`, while `poker-hero-range-repository/v1` intentionally keeps the coarser action key `3BET`. The exporter resolves that taxonomy mismatch narrowly:

- canonical decision evidence remains `SQUEEZE`, including its exact `target_total_bb`, incremental cost and EV;
- only in the exact repository spot `VS_RFI_CALLERS`, the calculated range layer represents canonical `SQUEEZE` as repository action `3BET`;
- an explicit policy containing `SQUEEZE` is projected to the same `3BET` key without changing probability or sizing distribution;
- supplying both `SQUEEZE` and `3BET` in one explicit policy is rejected as ambiguous instead of merging probabilities;
- `SQUEEZE` in any repository spot other than `VS_RFI_CALLERS` fails closed.

The candidate records the resulting repository action per hand in `repository_actions`, and the calculated-layer provenance records the projection semantics. Therefore the range repository round-trips with its stable taxonomy while the decision evidence retains the exact poker semantics needed by #106/#108.

## Parity and evidence

`verifyCandidate()` revalidates every #106 decision and the complete #97 repository. For each hand it checks that:

- the repository contains the selected action or its documented context-specific projection;
- the selected sizing is present when applicable;
- one-hot projections have not gained extra actions or sizing probability;
- the recorded repository action matches the deterministic decision/context projection;
- decision evidence and repository hand coverage are identical;
- layer version and population/context remain consistent.

The full normalized decision evidence keeps the exact EV, evaluated alternatives, support, confidence, uncertainty, sizing-grid origin, budget and seed attached to the hand decision. A later #106/#108 implementation can therefore prove that feed/detail/grid/trainer consume the same evaluated action and amount.

## Promotion boundary

This exporter cannot mark a strategy `PROMOTED`. Candidate construction with status `PROMOTED` is rejected and every artifact records `promotion_authorized: false`.

Promotion remains a separate #108 decision after the full-hand benchmark. Until that gate exists, these artifacts are experimental candidates only.

## Validation

Run:

```sh
node --check src/preflop/hero_range_export.js
node tests/preflop/test_decision_contract.js
node tests/hero_ranges/test_hero_range_repository.mjs
node tests/hero_ranges/test_calculated_range_export.mjs
node tests/hero_ranges/test_squeeze_export.mjs
```

The export regressions cover 169-class completeness, preservation of explicit mixes, exact sizing parity, one-hot fallback without fabricated mixes, preservation of the personal layer, stale-calculated replacement, population mismatch, missing hand coverage, invalid selected-action/sizing policy, self-promotion rejection, post-build repository tampering, canonical `SQUEEZE` projection to repository `3BET` in `VS_RFI_CALLERS`, round-trip stability, explicit squeeze mixes and fail-closed incompatible contexts.

# Hierarchical Model A candidate — frozen VALIDATION protocol — 2026-09-25

Decision owner: issue #419. The machine-readable source of truth is
`analysis/issue419_hierarchical_tree/FROZEN_VALIDATION_PROTOCOL.json`, written,
content-addressed and timestamped by
`tools/training/write_frozen_validation_protocol.py` before any VALIDATION
decision is read. This record states the decisions a reader should not have to
reconstruct from the JSON.

## Decision 1 — the freeze must precede the holdout

A VALIDATION read before the freeze would let thresholds, comparators and pooling
limits be tuned on the observed holdout score. `VALIDATION_ORDER_GUARD` in
`tools/training/validation_order_guard.py` therefore fails the freeze when a
VALIDATION result for this candidate already exists, and the evaluation command
must re-verify the pinned protocol bytes before opening a single VALIDATION hand.
The protocol records `frozen_at` `2026-09-25T00:00:00Z`,
`validation_consumed_for_authoring=false` and `validation_decisions_read=0`.

The #352 exact-price candidate already consumed the VALIDATION split for its own
candidate under its own frozen protocol. That precedent is recorded in
`holdout_boundary.predecessor_validation_reads` as a different candidate under a
different protocol: it is neither repaired nor double-counted, and it neither
violates nor satisfies this candidate's ordering rule.

## Decision 2 — three explicit comparators

The active reference `active-model-a-preflop-v5`
(`ff952055ca4ee051a3ac9607d513fdecac0a320a31f658ecfd8a11d8448975ca`), the
admitted #352 exact-price candidate `model-a-preflop-sizing-aware-candidate-v2`
(`9115165c3141d16152946dd1ee7a049f219fef1a1d79c0e1c7b1249c45326f19`, with its
fit/protocol/validation evidence pinning) and the new hierarchical candidate
`model-a-preflop-sizing-hierarchical-candidate-v1` under test are listed
explicitly. No comparator is implicit and the active pointer is never mutated.

## Decision 3 — thresholds and pooling limits are frozen, not negotiable

Thresholds stay at 20 marginal observations / 20 distinct hands, with frozen
VALIDATION gates: at least 200 identifiable decisions and 100 distinct hands,
paired 95% CI upper bound `<= 0` against both comparators, pooled ECE `<= 0.05`,
ECE delta versus active `<= 0.02`. Abstention is correctness, not a defect: a
lower coverage than the active reference never justifies relaxing a frozen
threshold.

`SUPPORT_ISOLATION_NO_KEY_BORROWS_SUPPORT` bounds pooling: `L0_EXACT_KEY` is the
only support source and the deepest exact-support claim, `L4_POSITION_PRICE_PRIOR`
the deepest reported estimate, `kappa0 = 16` with `alpha = 0.5`. `thresholds` and
`pooling_limits` carry `immutable_after_freeze = true`; the pinned protocol digest
is what makes the claim enforceable.

## Decision 4 — the 38-node requirement manifest is part of the freeze

All 38 nodes of the #388 required tree, including the 7 unresolved raise-sizing
frontiers, are pinned to `required_tree_sha256`
`0ab232ae44e4157e2a47d4d3d611ac8ca9c2cdb54caf2568f256f6df35643a25`, with each
node's runtime/audit/node keys and a manifest digest. A node unanswered after the
evaluation stays `EXACT_UNRESOLVED`: that is reported, never repaired by lowering
a threshold or borrowing another key's support.

## Decision 5 — #367 stays forbidden until admission

`ISSUE367_CONSUMES_ONLY_AN_ADMITTED_CANDIDATE`. At freeze time a #367 consumption
of this candidate is forbidden: no real ISO EV run, no exact-support grid
extension, no provider wiring. It becomes authorized only by an `ADMIT_CANDIDATE`
VALIDATION result whose evidence is content-addressed with its embedded
`protocol_byte_sha256` and pinned in a new #367 protocol revision naming this
candidate. Until then #367 keeps `model-a-preflop-sizing-aware-candidate-v2`
unchanged.

## Successor work

- The evaluation command must call
  `assert_protocol_frozen_before_validation()` before it opens its first
  VALIDATION hand and must emit `poker-hierarchical-validation-result/v1` at the
  declared path.
- A #367 revision may reference this candidate only after an `ADMIT_CANDIDATE`
  outcome exists.

This protocol admits nothing: no fit, no candidate admission, no promotion, no
production effect, and no change to the active Model A pointer.

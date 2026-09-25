# Hierarchical exact-context Model A spec — 2026-09-25

Decision owner: issue #419. The machine-readable source of truth is
`analysis/issue419_hierarchical_tree/HIERARCHICAL_MODEL_SPEC.json`, written and
content-addressed by `tools/training/write_hierarchical_model_spec.py` before any
VALIDATION decision is read. This record states the decisions that a reader
should not have to reconstruct from the JSON.

## Decision 1 — identity granularity is the fine key

The open risk `RUNTIME_SUPPORT_CONTEXT_COARSE_MERGE` is real: the implemented
`resolve_support_likelihood` key drops history, pot, effective-stack bucket,
live/all-in sets, table size and raise level, merging 38 fine keys into 30 on the
38 required nodes (8 collision groups).

The spec therefore adopts `hierarchical_exact_key` (the #388/#419 `audit_exact_key`
composition) as the identity **and support** granularity, and keeps
`runtime_support_context_key` as pooling level `L3_RUNTIME_SUPPORT_CONTEXT` used
for parameter shrinkage only.

Consequence, accepted deliberately: the 3 nodes that currently qualify at L3 can
only be reported as `EXACT_HIERARCHICAL_ESTIMATE`; none can be
`EXACT_EMPIRICAL_STRONG` until #367 exposes per-member fine-key counts. The
canonical CO after SB ISO@5 / BB FOLD cell stays `EXACT_UNRESOLVED` at 14/14
runtime and 4/4 fine observations, and the 20/20 thresholds are not lowered to
close the tree.

## Decision 2 — support is isolated per key

Rule `SUPPORT_ISOLATION_NO_KEY_BORROWS_SUPPORT`: a key A may never be declared
supported by observations of a different key B. Support quantities
(observations, distinct hands, effective sample size) are computed only from rows
whose `hierarchical_exact_key` equals the requested key. Pooling may change a
prior or a posterior, never a support count. The runtime invariant is
`support.source_key == requested_key`; a violation raises
`COARSE_KEY_SUPPORT_LAUNDERING` instead of emitting an answer.

## Decision 3 — pooling axes

Mutualizable in the parameters only: `effective_stack_bucket`, `pot_before_bb`,
`history`, `live_positions`, `all_in_positions`, `table_size`, `raise_level`,
`limper_count`, `caller_count`, `family`.

Never mutualizable, at any level and for support or parameters: the requested key
identity, the exact prices `target_total_bb`/`to_call_bb`, and the positions
`actor_position`/`aggressor_position`.

## Decision 4 — shrinkage and thresholds stay anchored to pinned evidence

`kappa0 = 16` with `alpha = 0.5` per legal marginal action reproduces the pinned
#352/#388 `prospective_shrinkage`; that rule's parent is now the explicit L3
level. Thresholds stay 20 marginal observations / 20 distinct hands, applied at
the level used to report the estimate, with the exact claim reserved for L0.

## Decision 5 — sizing and outputs

RAISE/JAM outputs are per exact `target_total_bb` from the #367 exact-reference
translator, with no representative, legal-minimum, nearest or interpolated
price. Unresolved sizing frontiers (7 in #388/#419) and their descendants stay
explicitly unresolved. Every legal marginal action is enumerated; zero counts
never prune.

## Successor work

- #367: expose fine-key per-member counts, or resolve at the fine key, before any
  `EXACT_EMPIRICAL_STRONG` claim.
- A future hierarchical fit must produce its own immutable run artifact, consume
  this spec by digest, and freeze its VALIDATION protocol before reading
  VALIDATION.

This spec admits nothing: no fit, no candidate, no promotion, no production
effect, and no runtime provider change.

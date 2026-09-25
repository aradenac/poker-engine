# Hierarchical Model A candidate — versioned VALIDATION protocol revision v2 — 2026-09-26

Decision owner: issue #419. The machine-readable source of truth for this
revision is
`analysis/issue419_hierarchical_tree/validation_protocol_v2/FROZEN_VALIDATION_PROTOCOL_V2.json`
(`poker-hierarchical-frozen-validation-protocol/v2`), written and content-addressed
by `tools/training/write_frozen_validation_protocol_v2.py`. It revises the v1
protocol (`69c99a8b37589f1687b7e980344c9a79d69bbcd45be0a53ffd59bfea0ab583b3`,
canonical `f283ce8dac9fbcfb5485eeb360217af4425fe947f249de652b03d96a13d40db5`).

## Decision 1 — the revision is additive, never a re-freeze

The v1 bytes stay byte-identical and remain the source of record for every
threshold, gate and comparator. The revision records the v1 byte digest, its
canonical payload digest, the v1 generator digest and every frozen v1 surface
digest (digest sidecar, `validation_protocol/` bundle, consumed
`VALIDATION_RESULT.json`, T8 preflight, terminal decision), and re-derives all of
them from the persisted bytes on every build and every `--check`.

Because the v1 payload pins the digest of
`tools/training/write_frozen_validation_protocol.py`, the revision has its own
generator. Editing the v1 tool would change a pinned digest and break the v1
pre-registration, so the revision reads the v1 bytes and never rewrites them.

## Decision 2 — two explicit layers

* **Layer A, exact empirical support.** `EXACT_EMPIRICAL_STRONG` is unchanged:
  the label, the `L0_EXACT_KEY`-only condition, both frozen thresholds (20
  marginal observations and 20 distinct hands) and the no-borrowing rule
  (`SUPPORT_ISOLATION_NO_KEY_BORROWS_SUPPORT`, `support.source_key ==
  requested_key`). No pooled estimate may be relabelled as exact support.
* **Layer B, exact-context estimate admissibility.** `EXACT_HIERARCHICAL_
  ESTIMATE` answers for the same exact requested key: identity preserved, support
  counts that key's own rows (possibly zero), pooling strictly parametric over
  `L1..L4` (`kappa0 = 16`, `alpha = 0.5` per legal marginal action), mandatory
  effective sample size, uncertainty at the level actually used and pooling
  provenance, gated on calibration, pooling and sizing.

No threshold moves, no gate is re-frozen, and the gate list is carried over
verbatim (`gates.gates_sha256` equals the v1 gate digest).

## Decision 3 — the node consumption rule is explicit

`CONSUME_ONLY_AN_ADMISSIBLE_NODE_ANSWER`. An exact-support answer is consumable
as exact support only at `L0_EXACT_KEY` with both thresholds met; a hierarchical
estimate is consumable only as an estimate with its pooling level, effective
sample size and uncertainty shown, never as exact support; an
`EXACT_UNRESOLVED` node is consumable as nothing and is never replaced by FOLD,
zero mass, a pruned branch or a nearest/representative price. Consuming an
estimate does not close the node: `required_tree_complete` still requires an
admissible exact answer at `L0_EXACT_KEY` for every required node, and
`ISSUE367_CONSUMES_ONLY_AN_ADMITTED_CANDIDATE` is unchanged.

## Boundaries

The revision admits nothing: no admission, no promotion, no provider change, no
production effect, no change to the active Model A v5 pointer and no re-opening
of the consumed VALIDATION split or of TEST. The frozen VALIDATION outcome stays
`RETAIN_ACTIVE_REFERENCE` and the #367 authorization state is unchanged.

Reproduce: `python3 tools/training/write_frozen_validation_protocol_v2.py`.
Verify: `python3 tools/training/write_frozen_validation_protocol_v2.py --check`.

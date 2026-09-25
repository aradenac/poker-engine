# #419 exact-tree #367 preflight — 2026-09-25

Decision owner: issue #419. The machine-readable source of truth is
`analysis/issue419_hierarchical_tree/exact_tree_preflight/EXACT_TREE_PREFLIGHT.json`,
produced by `tools/simulation/issue419_exact_tree_preflight.py`. This record
states what a reader should not have to reconstruct from the JSON.

## Decision 1 — a preflight, not a #367 run

`ISSUE367_CONSUMES_ONLY_AN_ADMITTED_CANDIDATE` keeps #367 forbidden at freeze
time (`issue367_rule.authorized_at_freeze = false`), so this command resolves
provider keys only. It never imports or executes
`tools/simulation/run_issue367_real_iso_ev.py`, never builds a rollout, an EV or a
recommendation, and never consumes Model B. The claim is enforced twice: an AST
scan of the command's own source plus a `sys.modules` scan for the runner and
every rollout/EV surface, and it is re-asserted on the artifact in a regression
test that fails if any EV/recommendation field appears in the payload.

## Decision 2 — exact keys only, with the refusals traced

The preflight walks the 38 required nodes of the #388 tree and the 7 unresolved
raise-sizing frontiers, and answers each node by exact string equality on its own
`hierarchical_exact_key` (byte-identical to the #388 `audit_exact_key`), bound to
the pinned candidate `model-a-preflop-sizing-hierarchical-candidate-v1`
(`637302885b8119e6b0246d827462c36eb707c6e234d0b652483c956f03360999`). Per node it
records the exact key, the node identity, the empirical support, the pooling
provenance, the uncertainty band and the posterior identity.

Six substitution classes are refused and recorded per node: `NEAREST_PRICE`,
`NEAREST_CONTEXT`, `REPRESENTATIVE_PRICE`, `LEGAL_MINIMUM_FALLBACK`,
`INTERPOLATED_PRICE` and `CROSS_KEY_SUPPORT_BORROWING`. Three executable
key-separation probes show that a changed price or context produces a *different*
requested key with its own (zero) exact support instead of the base key's counts,
and `support.source_key == requested_key` is asserted for every query, so no key
is ever supported by another key's observations.

## Decision 3 — `required_tree_complete` follows strict admissibility

The flag is true only when every frozen condition holds: every required node is
`EXACT_EMPIRICAL_STRONG` at `L0_EXACT_KEY` with both the 20-observation and the
20-distinct-hands thresholds met, no raise-sizing frontier stays unresolved, the
#388 enumeration is complete, no substitution was applied and no Hero EV was
computed. At this revision 0 of 38 nodes qualifies and the 7 RAISE frontiers stay
open, so the preflight reports `required_tree_complete = false` with the failing
conditions enumerated. Abstention is correctness: nothing lowers a threshold,
borrows a coarser key's support, or prunes an unresolved branch as zero mass.

## Decision 4 — TRAIN-only, no holdout, no pointer mutation

The command opens no hand history at all (a `pathlib` open tripwire fails the
build on any dataset archive, JSONL or fixture snapshot, and the recorded open
set is part of the evidence), declares `split_consumed = TRAIN`,
`validation_consumed = false`, `test_consumed = false` and
`active_model_pointer_mutated = false`, and re-verifies the protected registry,
model and frozen-protocol hashes before/after. The frozen protocol bytes
(`69c99a8b37589f1687b7e980344c9a79d69bbcd45be0a53ffd59bfea0ab583b3`), its
canonical payload digest and the 38-node requirement manifest are re-derived, not
taken on trust.

## Successor work

- A #367 revision may reference this candidate only after an `ADMIT_CANDIDATE`
  VALIDATION result exists and names it; until then the preflight stays
  evidence-only and the 7 raise-sizing frontiers keep the tree open.

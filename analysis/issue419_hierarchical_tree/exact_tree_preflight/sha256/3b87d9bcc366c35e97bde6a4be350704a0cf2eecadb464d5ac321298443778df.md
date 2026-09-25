# #419 - exact-tree #367 preflight (no Hero EV)

Required nodes walked: **38**; sizing frontiers walked: **7**. Every node was answered by exact string equality on its own exact key (`hierarchical_exact_key`, byte-identical to the #388 `audit_exact_key`).

`required_tree_complete = false` - 0 of 38 required nodes carry an admissible exact answer (`EXACT_EMPIRICAL_STRONG` at `L0_EXACT_KEY` with both the 20-observation and 20-distinct-hands thresholds met).

- `every_required_node_has_an_admissible_exact_answer`: NOT satisfied
- `no_unresolved_raise_sizing_frontier`: NOT satisfied
- `required_tree_fully_enumerated`: NOT satisfied
- `no_nearest_or_borrowed_substitution_applied`: satisfied
- `no_hero_ev_or_recommendation_computed`: satisfied

Status counts over the 38 nodes: `EXACT_UNRESOLVED`=38.

Abstention reasons: `NO_ADMISSIBLE_POOLING_LEVEL`=31, `RAISE_SIZING_UNRESOLVED_NO_NEAREST_PRICE`=7.

No nearest-price, nearest-context, representative-price, interpolated-price, legal-minimum or cross-key-support substitution was applied: 256 refusals were recorded and 4 executable key-separation probes confirmed that a changed price or context yields a different exact key instead of another key's support.

The #367 Hero EV runner was neither imported nor executed (`hero_ev_executed=false`, `recommendation_computed=false`, `rollouts_executed=0`, `ev_values_computed=0`). VALIDATION and TEST stay unconsumed (`split_consumed=TRAIN`, `validation_consumed=false`, `test_consumed=false`), no hand history was opened, and no active registry, model pointer or frozen protocol byte changed before/after.

Provider: `tools.preflop.model_a_sizing_hierarchical.resolve_exact_context` bound to candidate `model-a-preflop-sizing-hierarchical-candidate-v1` (`637302885b8119e6b0246d827462c36eb707c6e234d0b652483c956f03360999`), not authorized for #367 consumption at freeze time.

Frozen protocol: `69c99a8b37589f1687b7e980344c9a79d69bbcd45be0a53ffd59bfea0ab583b3`; required tree: `0ab232ae44e4157e2a47d4d3d611ac8ca9c2cdb54caf2568f256f6df35643a25`.

Reproduce: `python3 tools/simulation/issue419_exact_tree_preflight.py`; verify: `python3 tools/simulation/issue419_exact_tree_preflight.py --check`. This preflight records evidence only; it admits nothing.

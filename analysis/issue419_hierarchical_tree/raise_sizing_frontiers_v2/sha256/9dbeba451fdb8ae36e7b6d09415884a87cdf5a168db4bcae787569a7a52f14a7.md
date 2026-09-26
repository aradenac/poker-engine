# #419 — raise-sizing frontier resolution v2 (TRAIN only)

This is the **v2** revision (`schema=poker-raise-sizing-frontier-resolution/v2`), written to `analysis/issue419_hierarchical_tree/raise_sizing_frontiers_v2/`. The superseded v1 bundle (`raise_sizing_frontiers/RAISE_SIZING_FRONTIER_RESOLUTION.json`, byte SHA256 `93e7e3ede0a69e6b3e35f40217bd53ff95d1fbbb847ca3fbc9181c0689d0152e`) is frozen, consumed evidence: it is re-verified byte-for-byte and never rewritten. The per-frontier blocker below was added after v1 was frozen and therefore lives only here.

**7 of 7 raise-sizing frontiers remain UNRESOLVED**; the required #388 tree stays open and no candidate is admitted.

Each of the 7 `EXACT_REFERENCE_RAISE_SIZING_UNAVAILABLE` frontiers was re-derived individually from the canonical fixture, and its certified-TRAIN exact structural support was recounted. Every frontier selects exactly one active reference node at its `runtime_exact_preflop_node_key`, but that node carries no translatable raise-size statistic, so the #367 exact translator returns `LEGAL_MIN_FALLBACK` — which the frozen rule does not admit.

The pinned active reference has 0 of 4554 nodes carrying any translatable raise sizing (`target_total_bb`, `raise_to_bb`, `action_add_bb`, `raise_add_bb`, `own_size_pot`, `raise_size_pot`, `action_size_pot`). The structural node key is price-independent (it never consumes the raise amount), so no unsearched target could unlock exact support, and every downstream RAISE edge in any descendant closure would fall back as well. Descendants therefore stay `REQUIRED_UNRESOLVED_NOT_PRUNED_AS_ZERO_MASS`.

No representative price, nearest price, nearest context, target drift, observed empirical raise target, or legal-minimum substitution is introduced: every frontier persists `exactly_supported_target_bb=null` and `admitted_target_bb=null`. TRAIN RAISE actions observed at some structural keys are recorded as counts only, never as a price.

Every frontier is exposed as a distinct blocker `RAISE_SIZING_UNRESOLVED_NO_NEAREST_PRICE` (blocker id `UNRESOLVED_RAISE_SIZING_FRONTIER`, class `RAISE_SIZING_EXACT_SUPPORT`) with `independent_of_the_response_model=true`: it is necessary but not sufficient for tree closure and it forces `required_tree_complete=false` while it stays open. The same reference nodes already carry response likelihoods (`population_model`, `response_model_key`, `policy169_q_b64`) while carrying no raise sizing.

No VALIDATION or TEST decision was parsed or evaluated (`split_consumed=TRAIN`, `validation_consumed=false`, `test_consumed=false`); active registries and the active reference are unchanged before/after. This artifact records evidence only; it admits nothing.

Reproduce: `python3 tools/training/resolve_raise_sizing_frontiers.py`. Unresolved frontiers: `a2d5046ff291`, `060b2ee879f1`, `4a394bbb62e4`, `6640a5aa54a3`, `eb6478a3a92d`, `1b9af07db202`, `e5aa7850b80d`.

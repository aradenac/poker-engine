# #388 — exact response-tree TRAIN feasibility

**UNRESOLVED_EXACT_TREE_GAP**; no candidate created or admitted.

Certified TRAIN hands parsed: 19016. Explicit public decision nodes: 38; unresolved raise-sizing frontiers: 7.

Three identities are kept separate. `support_context_key` is the exact key actually consumed by `resolve_support_likelihood` and therefore classifies #367 feasibility. `exact_preflop_node` uses history/live/all-in/family/actor/table-size/raise-level to select structural raise sizing. The audit-only `audit_exact_key` is strictly finer than both: it additionally exposes exact price, pot and the existing effective-stack bucket. That finer partition is diagnostic and is not presented as the provider lookup contract.

BB facing SB ISO@5 reconciles exactly with #367: 45 observations and 45 hands at the runtime support key, versus 6 in the finer history/pot/stack audit partition. BB therefore qualifies 20/20 and is not a blocker. Canonical CO after SB ISO@5 / BB FOLD has 14 runtime-key observations (12 CALL, 2 FOLD), versus 4 in the finer audit partition. This reconciles #319 and remains below the frozen 20 observations / 20 hands rule, so the CO cell remains a real #367 data blocker. The threshold is not lowered to close the tree.

At the runtime-key granularity, 3 of 38 tree nodes qualify; 35 do not. The machine-readable #319 diagnostic enumerates all 30 required runtime keys, including zero-support keys.

Every legal FOLD/CALL/RAISE/JAM continuation is retained. Empirical zero counts never prune a branch. Raise sizes use only the #367 exact reference-node translator; missing sizing remains an explicit unresolved frontier, including its required descendants. Thus the enumerated tree is not claimed complete where sizing cannot be established. No legal-minimum, nearest-price, or nearest-context substitution is made.

The current likelihood runtime key intentionally preserves family, actor, aggressor, limpers/callers and exact price. It nevertheless merges differing history/pot/stack/live/table contexts. This latent coarse-merge risk is recorded as `RUNTIME_SUPPORT_CONTEXT_COARSE_MERGE` for #367; this audit reports it and does not silently redefine the provider. Reveals are descriptive labels, never features.

VALIDATION and TEST decisions were not parsed or evaluated. The certified loader checks shared archive hashes and hand IDs before allowing only TRAIN hands across the decision-parser boundary, as in #319. No fit, posterior candidate, validation protocol/result, or preflight is fabricated for this infeasible tree. Active registries/reference hashes are unchanged. No Hero EV or recommendation; #367 was not run.

The historical #352 fit self-reported digest differs from the recomputed persisted payload digest. Both are recorded separately and the persisted bytes are pinned; this audit neither repairs that evidence nor uses it to infer a new admission.

Reproduce: `python3 tools/training/audit_model_a_exact_tree.py`. Artifact byte hashes and content-addressed copies are in ARTIFACTS.json; internal links use canonical payload SHA256.

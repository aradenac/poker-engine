# #388 — exact response-tree TRAIN feasibility

**UNRESOLVED_EXACT_TREE_GAP**; no candidate created or admitted.

Certified TRAIN hands parsed: 19016. Explicit public decision nodes: 38; unresolved raise-sizing frontiers: 7.

Canonical CO after SB ISO@5 / BB FOLD: 14 coarse #319 observations (12 CALL, 2 FOLD), versus 4 with the declared exact public context and stack bucket. The v2 absence is a support-threshold rejection, not absence of all TRAIN observations. The predeclared minimum remains 20 observations and 20 distinct hands; it is not lowered to close the tree.

Every legal FOLD/CALL/RAISE/JAM continuation is retained. Empirical zero counts never prune a branch. Raise sizes use only the #367 exact reference-node translator; missing sizing remains an explicit unresolved frontier, including its required descendants. Thus the enumerated tree is not claimed complete where sizing cannot be established. No legal-minimum, nearest-price, or nearest-context substitution is made.

Keys preserve public history, active/all-in positions, aggressor, limpers/callers, exact price/pot, table size, raise level, and the existing effective-stack bucket. The only declared aggregation is within that stack bucket. Reveals are descriptive labels, never features. #319 coarse counts are diagnostics only.

VALIDATION and TEST decisions were not parsed or evaluated. The certified loader checks shared archive hashes and hand IDs before allowing only TRAIN hands across the decision-parser boundary, as in #319. No fit, posterior candidate, validation protocol/result, or preflight is fabricated for this infeasible tree. Active registries/reference hashes are unchanged. No Hero EV or recommendation; #367 was not run.

The historical #352 fit self-reported digest differs from the recomputed persisted payload digest. Both are recorded separately and the persisted bytes are pinned; this audit neither repairs that evidence nor uses it to infer a new admission.

Reproduce: `python3 tools/training/audit_model_a_exact_tree.py`. Artifact byte hashes and content-addressed copies are in ARTIFACTS.json; internal links use canonical payload SHA256.

# FROZEN_VALIDATION_PROTOCOL_v2 (hierarchical exact-context, #419)

`poker-hierarchical-frozen-validation-protocol/v2` (`FROZEN_VALIDATION_PROTOCOL_REVISION`), revision 2, issue 419, authored `2026-09-26T00:00:00Z` (`AUTHORED_AFTER_VALIDATION_READ_NO_THRESHOLD_CHANGE`). Content-addressed here; the payload digest is `508a31ec8072a72ca573f65ac6b748e1ce5e67c639fd4388e472153b7ffa4320` (canonical payload `a97391d2678d66a46cc7a8d2d0893a509c9c2564a5c420f4519d21c05216dd16`).

It revises `poker-hierarchical-frozen-validation-protocol/v1` (`69c99a8b37589f1687b7e980344c9a79d69bbcd45be0a53ffd59bfea0ab583b3`, canonical `f283ce8dac9fbcfb5485eeb360217af4425fe947f249de652b03d96a13d40db5`) additively: the v1 bytes are unchanged and stay the source of record for thresholds, gates and comparators.

Layer A (`EXACT_EMPIRICAL_SUPPORT`) is the exact empirical support layer: `EXACT_EMPIRICAL_STRONG` (unchanged) at `L0_EXACT_KEY`, both thresholds (20 observations / 20 distinct hands), support never borrowed (`SUPPORT_ISOLATION_NO_KEY_BORROWS_SUPPORT`).

Layer B (`EXACT_CONTEXT_ESTIMATE_ADMISSIBILITY`) is the exact-context estimate admissibility layer: `EXACT_HIERARCHICAL_ESTIMATE` for the same exact requested key, identity preserved, `support.source_key == requested_key`, pooling strictly parametric over `L4_POSITION_PRICE_PRIOR` with mandatory effective sample size, uncertainty and pooling provenance, gated on calibration, pooling and sizing.

Statuses: EXACT_EMPIRICAL_STRONG, EXACT_HIERARCHICAL_ESTIMATE, EXACT_UNRESOLVED. The node consumption rule is `CONSUME_ONLY_AN_ADMISSIBLE_NODE_ANSWER`: an estimate is consumable as an estimate, an unresolved node is consumable as nothing, and closing the tree still requires an admissible exact answer at L0_EXACT_KEY for every required node.

Reproduce: `python3 tools/training/write_frozen_validation_protocol_v2.py`; verify: `python3 tools/training/write_frozen_validation_protocol_v2.py --check`. This revision admits nothing.

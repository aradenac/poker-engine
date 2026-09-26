# #419 — hierarchical-tree TRAIN sparsity baseline

Re-derived on certified TRAIN only (19016 hands parsed, 101848 non-Hero preflop decision rows). Required tree nodes: 38; unresolved raise-sizing frontiers: 7.

Both granularities are reproduced and pinned: `runtime_support_context_key` (the exact #367 `resolve_support_likelihood` contract) and the strictly finer audit-only `audit_exact_key`. Every cell and both node keys match the persisted #388 matrix byte-for-byte at the canonical-payload level.

Runtime-support qualification reproduces 3 of 38 nodes; the audit-exact partition qualifies 0. BB facing SB ISO@5 = 45 obs / 45 hands; CO after SB ISO@5 / BB FOLD = 14 obs / 14 hands. Both reconcile exactly with #388 and #319; the CO cell remains a real data blocker.

No VALIDATION or TEST decision was parsed or evaluated (`split_consumed=TRAIN`, `validation_consumed=false`, `test_consumed=false`). Active registries and the reference fixture are unchanged before/after, and the #388 artifacts are byte-verified against their content addresses. This baseline records evidence only; it admits nothing.

The #352 digest gap is recorded, not repaired: historical self-reported `cacf97c80f44856da6e787b230ab1b564d5c0c83821a894e57b70aba92145738` vs recomputed persisted payload `ec96d6da20aca0ecb12717ed864ab2df8322a2e28bcb565b8cce9d94a106f367`, `historical_digest_recomputed_match=false`.

Reproduce: `python3 tools/training/audit_hierarchical_tree_sparsity.py`. Baseline byte SHA256: `ef3995daaf5bc48a09f0785d574f7494754ad3904b87ecd2aa089b5be1b24a36`.

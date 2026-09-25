# #419 — hierarchical exact-context model spec (TRAIN-only)

`HIERARCHICAL_MODEL_SPEC.json` byte SHA256: `5be122e54e9ee07313a7efa0e0a6dbf4e195eceacf78287a9ac5a448964d105c`. The canonical payload hash and the content-addressed copies are in `model_spec/ARTIFACTS.json`.

Identity granularity is the fine `hierarchical_exact_key` (L0); the current provider key `runtime_support_context_key` is pooling level L3 only. The open `RUNTIME_SUPPORT_CONTEXT_COARSE_MERGE` risk is addressed explicitly: 8 collision groups merge 38 fine keys into 30 coarse keys, so a coarse lookup can never be reported above `EXACT_HIERARCHICAL_ESTIMATE`.

Mutualizable parameter axes and the never-mutualizable axes (requested key identity, exact price `target_total_bb`/`to_call_bb`, and the actor/aggressor positions) are enumerated in `parameter_pooling.axes`. Rule `SUPPORT_ISOLATION_NO_KEY_BORROWS_SUPPORT` states that a key A may never be declared supported by observations of a different key B; support counts are exact, pooling only feeds the prior.

The spec was written and hashed from TRAIN-only and structural evidence before any VALIDATION decision was read: `validation_consumed=false`, `validation_decisions_read=0`, the generator parses no hand history and refuses the known holdout loaders. Thresholds stay frozen at 20 observations / 20 distinct hands; raise sizing is exact-support-only with no representative price. This artifact admits nothing.

Reproduce: `python3 tools/training/write_hierarchical_model_spec.py --check`.

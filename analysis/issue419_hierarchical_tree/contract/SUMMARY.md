# #419 -- hierarchical Model-A sizing candidate contract

Candidate `model-a-preflop-sizing-hierarchical-candidate-v1` (model-a-preflop-sizing-hierarchical-candidate-v1), statuses EXACT_EMPIRICAL_STRONG, EXACT_HIERARCHICAL_ESTIMATE, EXACT_UNRESOLVED.

The contract is declared by the hierarchical schema `contracts/training/model-a-preflop-sizing-hierarchical-likelihood.schema.json` and the exact-price schema `contracts/training/model-a-preflop-sizing-likelihood.schema.json`. The mandatory hierarchical fields (status, exact empirical observations, effective sample size, pooling level/source, uncertainty, reason codes) are present at their required locations, and every frozen provider constant equals the schema const/enum that publishes it (parity mismatches: 0).

Real provider outputs at all three statuses validate against the schema: exact_empirical_strong=EXACT_EMPIRICAL_STRONG (obs=20, ess=20.0, pooling=L0_EXACT_KEY, reason=EXACT_EMPIRICAL_STRONG), hierarchical_estimate=EXACT_HIERARCHICAL_ESTIMATE (obs=1, ess=1.0, pooling=L1_STACK_POOL, reason=EXACT_HIERARCHICAL_ESTIMATE), unresolved=EXACT_UNRESOLVED (obs=0, ess=0.0, pooling=None, reason=NO_ADMISSIBLE_POOLING_LEVEL).

Active pointer unchanged: `training/registry.json` still promotes `training/models/preflop_population_model_v5.json` (sha256 `ff952055ca4ee051a3ac9607d513fdecac0a320a31f658ecfd8a11d8448975ca`), the pinned reference matches (True), the candidate is never registered (mentioned=False, promoted=False), and the protected files are byte-identical before/after the audit.

Exact-price v1/v2 non-regression: v1 present=True, v2 present=True, both validate=True.

Reproduce: `python3 tools/training/audit_hierarchical_candidate_contract.py`. Contract byte SHA256: `5d0fbcaf092f6ebb798df612b10a7e1b15940223b95f071281302b00c4f46a98`.

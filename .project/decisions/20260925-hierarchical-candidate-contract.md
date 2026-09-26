# Hierarchical Model A candidate — contract/schema and active-pointer invariance — 2026-09-25

Decision owner: issue #419. The machine-readable source of truth is
`analysis/issue419_hierarchical_tree/contract/CANDIDATE_CONTRACT.json`
(`poker-hierarchical-candidate-contract/v1`), produced by
`tools/training/audit_hierarchical_candidate_contract.py` and content-addressed
with its byte digest, its canonical payload digest and the copied `sha256/`
objects. This record states what the reader must not have to reconstruct from the
JSON.

## Decision 1 — the candidate identity and fields are published by the schema

The new identity `model-a-preflop-sizing-hierarchical-candidate-v1` is declared
by `contracts/training/model-a-preflop-sizing-hierarchical-likelihood.schema.json`
(`$defs.identity.properties.candidate_id.const`) and is registered in the
exact-price identity enum of
`contracts/training/model-a-preflop-sizing-likelihood.schema.json` so one list
covers every Model-A preflop sizing candidate. The mandatory hierarchical
provenance fields are declared at their required locations and are required
properties of the response: the estimated status
(`EXACT_HIERARCHICAL_ESTIMATE`), the exact empirical observations
(`support.observations`), the effective sample size
(`support.effective_sample_size`), the pooling level and source
(`pooling.level`, `pooling.source_key`, `pooling.support_source_key`), the
mandatory uncertainty band (`uncertainty`) and the reason codes
(`reason_code`, `reason_detail`, `unresolved_reason`). An `EXACT_UNRESOLVED`
response now carries an explicit `$defs.reasonCode` enum
(`NO_ADMISSIBLE_POOLING_LEVEL`, `RAISE_SIZING_UNRESOLVED_NO_NEAREST_PRICE`,
`NO_EXACT_SUPPORT_AND_NO_CONTEXT`); the support-laundering code
`COARSE_KEY_SUPPORT_LAUNDERING` is deliberately *not* a response code because a
support borrowing raises instead of emitting an answer. The audit fails closed if
any of those locations disappears.

## Decision 2 — provider/schema parity is machine-verified

Every frozen provider constant (`CANDIDATE_ID`, `STATUSES`, `POOLING_LEVELS`,
`KAPPA0`, `ALPHA_PER_LEGAL_ACTION`, the 20/20 thresholds, the support isolation
rule, the granularity) is compared to the schema `const`/`enum` that publishes
it, and real provider outputs are validated against the schema at all three
statuses with a self-contained stdlib JSON-Schema subset validator. The
candidate contract gate therefore never depends on an unpinned third-party
package, and a schema/const drift cannot pass unnoticed.

## Decision 3 — the active pointer stays on the pinned reference

`training/registry.json` still promotes
`training/models/preflop_population_model_v5.json`
(sha256 `ff952055ca4ee051a3ac9607d513fdecac0a320a31f658ecfd8a11d8448975ca`), the
candidate is never mentioned in the registry and never registered as promoted,
and the protected files (`training/registry.json`,
`training/populations/registry.json`, the reference model and both schemas) are
byte-identical before/after the audit. The hierarchical candidate is
candidate-only (`active_model_replaced=false`, `CANDIDATE_ONLY_NOT_ACTIVE`).

## Decision 4 — exact-price v1/v2 do not regress

The exact-price identity enum still contains both
`model-a-preflop-sizing-aware-candidate-v1` and `...-v2`, the exact-price
backoff policy and no-nearest-price flags are unchanged, and both exact-price
candidates still validate against their schema and resolve. The hierarchical
work adds a candidate; it does not replace or weaken the exact-price contracts.

## Tests

`tests/training/test_hierarchical_candidate_contract.py` verifies the
content-addressing and byte-stability of the artifact, the declared candidate
identity and mandatory fields, provider/schema parity, live validation at every
status, active-pointer invariance and exact-price v1/v2 non-regression, plus
negative controls proving the schema gate is not vacuous.

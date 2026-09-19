# Opponent posterior range runtime contract

Issue #320 defines the stable runtime boundary between a posterior producer and downstream reviewer/EV consumers. It does not fit Model A, select a scientific artifact, or modify UI.

## Schema

Runtime records use:

    poker-opponent-posterior-range/v1

The JSON schema is 'contracts/posterior-range.schema.json'.

A record is tied to one exact point in the public timeline through:

- hand_id
- step_id
- public_state_fingerprint
- player / position
- moment: BEFORE_ACTION or AFTER_ACTION

AFTER_ACTION requires the public action that was used to condition the posterior. The action already contains an optional stable sizing envelope (observed_size_bb, target_total_bb, pot_before_bb, pot_fraction, semantic), so #312/#313 can later supply a sizing-dependent likelihood without a schema-major change.

## Identity and provenance

Every record requires:

- population identity
- model identity + version
- source identity
- producer
- contract version
- source artifact
- source fingerprint

A downstream consumer must not interpret an anonymous grid as an estimated range.

## Exact combos are authoritative

exact_combo_weights is the authoritative probability distribution.

src/ranges/posterior_range.py reuses the repository card/class mapping from tools/simulation/model_b_runtime.py and performs:

1. exact-card blocker filtering;
2. positive-mass check;
3. normalization;
4. deterministic exact combo ordering;
5. projection by summing exact combo probability into the 169 canonical classes;
6. effective support and entropy calculation;
7. deterministic content fingerprinting.

The 169 projection includes both:

- canonical full-deck combo multiplicity (1326 total);
- legal combo multiplicity after the declared blockers.

This prevents a class-level projection from silently ignoring blocker-dependent multiplicity.

## Information boundary

Only blockers with:

    knowledge_scope = PUBLIC

are accepted by this contract.

Opponent hole cards that have not been revealed at step_id, future board cards, or any field that attempts to inject future/private information are invalid. The validator uses an allow-list at the top level and for action/blocker records.

BEFORE_ACTION requires public_action = null, so the target action cannot leak into its own prior.

AFTER_ACTION requires the observed public action and may carry its public sizing fields.

## Fail-closed states

status is one of:

- AVAILABLE
- UNSUPPORTED
- INVALID

AVAILABLE requires normalized positive exact-combo mass and a matching 169 projection.

UNSUPPORTED and INVALID must contain:

- zero probability mass;
- no exact combo weights;
- an all-zero 169 probability projection;
- an explicit reason.

They still retain the canonical/legal multiplicity metadata, identity, support source and provenance. Missing support therefore never becomes an all-hands-100-percent range.

## Existing posterior compatibility

The current training-side ComboPosterior in tools/training/model_a_latent_ranges.py already exposes exact combos and weights.

record_from_combo_posterior() accepts any object exposing those two attributes and serializes it through the same validator/projector without importing or duplicating Model A fitting logic.

This is the intended bridge for #312.

## Synthetic verification

Run:

    python3 tests/ranges/test_posterior_range.py

Coverage includes:

- 1326 -> 169 multiplicity;
- non-uniform posterior preservation;
- blockers and post-block normalization;
- duplicate/negative/zero-mass rejection;
- public-only information boundary;
- BEFORE/AFTER action timing;
- sizing envelope compatibility;
- mandatory identity/provenance;
- deterministic distribution fingerprint;
- projection mismatch rejection;
- explicit UNSUPPORTED zero-mass state;
- rejection of an all-100-percent grid.

No #108, VALIDATION, TEST, Model-A fit, Model-B fit, or CENTRAL-UI surface is touched by this contract.

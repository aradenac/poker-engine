# Hero -> Model B robustness consumer (#425)

## Purpose

This document is the contractual companion of
`contracts/training/model-b-hero-robustness-input.schema.json`
(`$schema` draft 2020-12, `$id = hero-model-b-robustness-input/v1`).

It fixes the *input* contract a Model B robustness consumer reads before the
real upstream evidence exists, so a consumer can be built and reviewed against a
stable, fail-closed shape instead of an ad-hoc payload. The contract is
deliberately shaped like post-evaluation robustness evidence (a Hero entry, its
public EV envelope, a route/source label, a support verdict and the candidate
alternatives) but every value is **synthetic**: the input never claims a
robustness result, never carries a real `#367` result, and never consumes a
VALIDATION or TEST hand.

The parent issue #315 stays **open**: this contract standardizes the input
shape only and does not run the real Model B sensitivity evaluation.

## Input contract

A document is valid only if it carries these five top-level blocks, with
`additionalProperties: false` on every object (fail-closed: an incomplete or
unknown field is rejected, never repaired, defaulted or enriched):

- `schema` — `const "hero-model-b-robustness-input/v1"`;
- `source_kind` — `const "SYNTHETIC_ROBUSTNESS_SHAPED"`;
- `provenance` — see below;
- `information_boundary` — see below;
- `hero_entry` — the single Hero robustness entry.

### `hero_entry`

`hero_entry` carries every field of the scope. Each value field is **present but
nullable**: `null` means *unavailable / not evaluated* and must never be coerced
to `0`, and a consumer must fail closed on a missing value instead of inventing
one.

| Field | Type | Nullability |
|---|---|---|
| `action` | `FOLD` \| `OVERLIMP` \| `ISO` | nullable when the fixture does not provide it |
| `sizing` | number >= 0 (target total, bb) | nullable when the action has no sizing (e.g. `FOLD`) or is unavailable |
| `ev` | number (public EV, bb) | nullable = not evaluated, never `0` |
| `uncertainty` | `{ ci95: [low, high], width_bb, source }` | nullable = not measured |
| `paired_delta` | number (bb, versus the best alternative) | nullable = no paired comparison |
| `route_source` | string (provenance label) | nullable = unlabelled |
| `support` | `{ status, tier, ood }` | nullable = not declared (consumer fails closed) |
| `posterior_refs` | array of non-empty strings | nullable = not computed |
| `alternatives` | array (minItems 1) of alternative entries | nullable = no comparison set |

Each `alternatives[]` entry repeats the same public action/sizing identity plus
its own nullable `ev`, `uncertainty`, `paired_delta`, `route_source`, `support`
and `posterior_refs`. `decision_id`, `context_id` and `hero_position` are
optional public Hero-side identity and carry no private or predictive signal.

Until the real evidence exists, the `uncertainty` envelope of the Hero entry
**and of every compared alternative** is read strictly and fail-closed: `ci95`
must be two finite numbers with `low <= high`, `width_bb` must be a finite
non-negative number, and the declared width must agree with `high - low` within a
small, explicit numerical tolerance (`1e-9` bb) that only absorbs float
rounding (`1.45 - 1.39` is `0.06000000000000005`, not `0.06`). A contradiction
(`ci95 = [-10, 10]` declared as `width_bb = 0.06`) is invalid: the width is never
re-derived or shrunk to make a claim look supported, and the width compared to
the `MAX_CI95_WIDTH_BB` policy is always the one derived from the bounds. A
present-but-null envelope stays legal and means *not measured*: it is classified
`INSUFFICIENT_SUPPORT` and can never produce `CONSISTENT`.

`support.tier` (e.g. `LOW` / `MEDIUM` / `HIGH` / `VERY_HIGH` / `UNKNOWN`) is
descriptive only: a tier never upgrades an unsupported status and a high tier is
never a robustness proof.

### `provenance`

`provenance` is required and pinned fail-closed, so the document can never be
read as real evidence:

| Field | Constraint |
|---|---|
| `synthetic_fixture` | `const true` |
| `real_issue_367_consumed` | `const false` |
| `validation_consumed` | `const false` |
| `test_consumed` | `const false` |

Synthetic probabilities or EVs validated through this contract must not be
reused as evidence about real Hero strategy.

## Information boundary

`information_boundary` is required and pins every flag `false`; a document that
tries to open the boundary is invalid by construction.

| Flag | Boundary it enforces |
|---|---|
| `hero_ev_consumed` | The input carries no Hero EV; the consumer must not read one to rank alternatives. |
| `model_a_consumed` | No Model A output, parameter or posterior may enter this input. |
| `recommendation_consumed` | No selected/recommended alternative may be carried in or read from the input. |
| `future_cards_consumed` | No future street card may condition the decision. |
| `opponent_hole_cards_consumed` | No unrevealed opponent hole cards may enter the input. |
| `route_as_predictive_target` | Optional (when present, `const false`): `route_source` is a provenance label only and must never be used as a predictive target nor as an environment weight. |

Model B uncertainty is represented only by the unweighted cross-environment
envelope; the input must never synthesize a probability (a "weight") over
environments.

## Status vocabulary (#425)

`support.status` uses exactly five values, with a fixed, fail-closed precedence
when a consumer collapses one input to a single verdict
(`OOD_UNTESTABLE` > `INSUFFICIENT_SUPPORT` > `TOO_CLOSE` > `SENSITIVE` >
`CONSISTENT`):

| Status | Meaning |
|---|---|
| `CONSISTENT` | Across the declared Model B environments the alternative keeps its standing (same best alternative, ranking and sizing within tolerance). |
| `SENSITIVE` | A declared environment changes the best alternative, the ranking or the sizing, so the standing is not robust to Model B variation. |
| `TOO_CLOSE` | The comparison is complete but the gap to the best alternative is within tolerance, so no ordering can be asserted. |
| `INSUFFICIENT_SUPPORT` | Evidence is missing or unsupported: no robustness claim is allowed. |
| `OOD_UNTESTABLE` | The relevant environment is out of distribution (`support.ood = true`), so it can be reported but cannot be tested against. |

`INSUFFICIENT_SUPPORT` and `OOD_UNTESTABLE` are fail-closed outcomes and must be
surfaced as "not established", never as a weak positive.

## Mapping to #199

The #199 backend (`tools/simulation/model_b_robustness.py`, report schema
`hero-model-b-robustness/v1`, summary schema
`hero-model-b-robustness-summary/v1`) keeps its own, coarser three-value
classification: `robust` / `sensitive` / `insufficiently_supported`. #425 is
**additive**: it does not change #199 or its consumer (`site/analytics/model-b-robustness.js`),
it only documents how the finer #425 verdict projects onto it. The mapping is
conservative and must never upgrade: only `CONSISTENT` can become `robust`.

| #425 status | #199 classification | Rationale |
|---|---|---|
| `CONSISTENT` | `robust` | The alternative keeps its standing across environments. |
| `SENSITIVE` | `sensitive` | The standing is not robust to Model B variation. |
| `TOO_CLOSE` | `insufficiently_supported` | No ordering can be asserted, so no robustness claim is allowed; it must never be promoted to `robust`. |
| `INSUFFICIENT_SUPPORT` | `insufficiently_supported` | #199 already treats missing/unsupported evidence as `insufficiently_supported`. |
| `OOD_UNTESTABLE` | `insufficiently_supported` | #199 has no in-distribution OOD bucket; an untestable environment yields no claim, so it maps to the no-claim bucket rather than to `robust`. |

When several alternatives are present, the mapping is applied to the collapsed
#425 verdict, not per alternative, and the fail-closed statuses above always win
over `robust`.

## Additive reuse of the #344 harness

The consumer reuses the synthetic preflop sensitivity harness of #344
(`tools/simulation/model_b_preflop_sensitivity_harness.py`) **additively**,
through its public API only:

- the harness files (module, request contract
  `contracts/training/model-b-preflop-sensitivity-harness-request.schema.json`
  and its tests) are never edited, and its default `source_kind`
  `SYNTHETIC_HARNESS_ONLY` is unchanged;
- the projected request is the single accepted #344 format: it reuses that
  unchanged `SYNTHETIC_HARNESS_ONLY` source kind, so there is no second
  `source_kind` extension and no alternate harness entry point;
- a projected request copies only the public alternative identity
  (`alternative_id`, `action`, `target_total_bb`, `incremental_cost_bb`) derived
  from `hero_entry.alternatives`; `ev`, `uncertainty`, `paired_delta`,
  `route_source`, `support` and `posterior_refs` are classification/provenance
  inputs only and are **never** projected as Model B features;
- the emitted request keeps an all-false `information_boundary` and a synthetic
  `synthetic_fixture = true`, and is validated by the harness
  (`validate_request`) before execution.

Reusing the harness keeps the Model A / Model B independence guarantee: no
Model A output, no recommendation and no route/source-as-target can reach the
Model B request.

## Out of scope

`contracts/analytics/*` belongs to a different scope (#423) and is not modified
by this contract. #315 remains open and is not closed by this document.

# Model B robustness consumer (#425)

## Purpose

This document specifies how a consumer reads the versioned contract
`contracts/training/model-b-hero-robustness-input.schema.json`
(`$id = hero-model-b-hero-robustness-input/v1`).

The contract is a *robustness-shaped* input: it carries one Hero decision, at
least one candidate alternative, each alternative's public EV envelope
(`ev_bb`, `uncertainty`, `paired_delta_vs_best_bb`), its `support` verdict and a
`provenance` / `information_boundary` block. Its `source_kind` is
`SYNTHETIC_ROBUSTNESS_SHAPED` and `synthetic_fixture` is `true`.

The purpose is to let a Model B robustness consumer be built and reviewed
against a stable, fail-closed input contract **before** the real upstream
evidence exists. The input never claims a robustness result; it only fixes the
shape and the admissible vocabulary so a later real input cannot silently add
fields or private signals.

## Fail-closed reading

The schema sets `additionalProperties: false` on every object and requires every
declared block:

- `schema`, `source_kind`, `synthetic_fixture`;
- `decision`;
- `alternatives` (at least one entry, each with all ten fields);
- `provenance`;
- `information_boundary`.

A document that is missing a block, carrying an unknown field, or using an
out-of-vocabulary `action` / `support.status` is invalid by construction. A
consumer must reject such a document rather than repairing, defaulting or
enriching it. In particular a `null` `ev_bb` or `null` `uncertainty` means *not
evaluated*; it must never be coerced to `0`.

## Status vocabulary

`alternatives[].support.status` uses exactly five values. The consumer treats
them as distinct, non-interchangeable verdicts:

| Status | Meaning |
|---|---|
| `CONSISTENT` | Across the declared Model B environments the alternative keeps its standing (same best alternative, ranking and sizing within tolerance, regret inside the quasi-dominant limit). |
| `SENSITIVE` | A declared environment changes the best alternative, the ranking, the sizing or pushes regret past the limit: the alternative's standing is not robust to Model B variation. |
| `TOO_CLOSE` | The comparison is complete but the gap to the best alternative is within tolerance, so no ordering can be asserted from this input. |
| `INSUFFICIENT_SUPPORT` | Evidence is missing or unsupported (missing environment, missing alternative, `ev_bb = null`, unsupported tier): no robustness claim is allowed. |
| `OOD_UNTESTABLE` | The relevant environment is out of distribution (`support.ood = true`), so it can be reported but cannot be tested against. |

`support.tier` is a support tier label (for example `LOW`, `MEDIUM`, `HIGH`,
`VERY_HIGH`, `UNKNOWN`). A tier is descriptive only: it never upgrades an
unsupported status, and a high tier must never be read as a robustness proof.

`INSUFFICIENT_SUPPORT` and `OOD_UNTESTABLE` are fail-closed outcomes. The
consumer must surface them as "not established", never as a weak positive.

## Information boundary

The `information_boundary` block pins six flags and all of them are `false`:

| Flag | Boundary it enforces |
|---|---|
| `hero_ev_consumed` | The input carries no Hero EV; the consumer must not read one to rank alternatives. |
| `model_a_consumed` | No Model A output, parameter or posterior may enter this input. |
| `recommendation_consumed` | No selected/recommended alternative may be carried in or read from the input. |
| `route_as_predictive_target` | `alternatives[].route` is a provenance label only; it must never be used as a predictive target nor as an environment weight. |
| `future_cards_consumed` | No future street card may condition the decision. |
| `opponent_hole_cards_consumed` | No unrevealed opponent hole cards may enter the input. |

Model B uncertainty is represented only by the unweighted cross-environment
envelope; the input must never synthesize a probability (a "weight") over
environments.

## Provenance

The `provenance` block pins `parent_issue = 314`,
`upstream_result_schema = "poker-issue367-real-iso-ev-result/v1"`,
`synthetic_fixture = true`, and keeps `real_issue_367_consumed`,
`real_issue_314_consumed`, `validation_consumed` and `test_consumed` all
`false`. This makes the synthetic input self-describing: it is compatible in
shape with the future real upstream result, but it is not that result.

Synthetic probabilities or EVs validated through this contract must not be
reused as evidence about real Hero strategy.

## Issue #315 status

Issue **#315 remains open**. This contract only standardizes the robustness
input shape for consumers. It does not consume the still-unavailable real #314
output, does not run the real Model B sensitivity evaluation, and does not close
the remaining sensitivity DoD of #315. Closing #315 still requires the real
post-#314 execution described in `docs/model-b-preflop-sensitivity-harness.md`.

## Out of scope

`contracts/analytics/*` belongs to a different scope (#423) and is not modified
by this contract.

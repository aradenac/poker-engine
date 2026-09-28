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

## Preserved chain, parent and upstream

The two documents of issue `#425` describe **one** preserved chain (this
contract document and its companion run book
`docs/model-b-robustness-consumer.md`). The chain has exactly one implementation
per step:

| Step | Artifact | Role |
|---|---|---|
| T1 | `contracts/training/model-b-hero-robustness-input.schema.json` (`$id = hero-model-b-robustness-input/v1`) | fail-closed input contract |
| T2 | `tests/fixtures/model_b_hero_robustness/` | synthetic robustness-shaped fixtures |
| T3 | `tools/simulation/model_b_hero_robustness_contract.py` | contract bridge and projection to the #344 request |
| T4 | `tools/simulation/model_b_hero_robustness_classify.py` | deterministic #425 classifier |
| T5 | `tools/simulation/model_b_hero_robustness_adapter.py` | runner CLI, the single callable entry point |
| T6 | `tests/simulation/test_model_b_hero_robustness_consumer.py` | consumer integration suite |
| T7 | `tools/simulation/build_model_b_hero_robustness_consumer_run.py` | canonical run bundle builder/regenerator |

The parent and upstream references are pinned, never inferred:

- **parent**: issue `#315` stays open and is never closed by this chain
  (`RUN_PROVENANCE.json` carries `parent_issue = 315`, `next_issue = 315` and
  `parent_closed = false`);
- **upstream consumed**: the persisted `#340` run
  (`training/runs/20260919_model_b_preflop_response_to_price_2a/`: candidate,
  price-agnostic reference, `SUMMARY.json`, `RESULT.json`, `RUN_PROVENANCE.json`)
  reused read-only through the public `#344` harness API — no refit, no
  promotion, the active Model B pointer is untouched;
- **upstream never consumed**: the real ISO EV run of `#367`, the real `#314`
  output, the VALIDATION hand and the TEST hand
  (`real_issue_367_consumed = false`, `real_issue_314_consumed = false`,
  `validation_consumed = false`, `test_consumed = false`);
- the emitted report binds its **producing** issue and the reused harness
  (`provenance.issue = 425`, `provenance.harness_issue = 344`); the chain
  *parent* reference lives in the run provenance only, so a report can never be
  read as a parent-closing artifact.

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
| `paired_delta` | number (bb, **Hero versus the best alternative**) | nullable = no paired comparison |
| `route_source` | string (provenance label) | nullable = unlabelled |
| `support` | `{ status, tier, ood }` | nullable = not declared (consumer fails closed) |
| `posterior_refs` | array of non-empty strings | nullable = not computed |
| `alternatives` | array (minItems 1) of alternative entries | nullable = no comparison set |

Each `alternatives[]` entry repeats the same public action/sizing identity plus
its own nullable `ev`, `uncertainty`, `paired_delta`, `route_source`, `support`
and `posterior_refs`. `decision_id`, `context_id` and `hero_position` are
optional public Hero-side identity and carry no private or predictive signal.

The two `paired_delta` fields are **not** the same comparison, and a consumer
must never treat them as interchangeable:

| Field | Compared with | Meaning for the Hero standing |
|---|---|---|
| `hero_entry.paired_delta` | the **best** alternative | the only paired signal about Hero: a near-zero value (or a paired CI covering zero) is evidence that Hero is tied with the best alternative |
| `alternatives[].paired_delta` | the **best** alternative | that alternative's own standing. For the best-ranked alternative it is a self-comparison, ~0 by construction, and says *nothing* about where Hero stands |

The `#425` classifier therefore reads only `hero_entry.paired_delta` (and its
optional paired CI, when a producer supplies one) as paired evidence: reading the
best alternative's trivially zero auto-comparison would fabricate a quasi-equality
that the measured EVs contradict.

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

## Metadata versus Model B features

`#425` separates **metadata** from **features**. The metadata is read for
classification and provenance only; it never becomes a Model B feature:

| Classification / provenance metadata (never a feature) | Public identity (allowed to cross) |
|---|---|
| `hero_entry.ev`, `hero_entry.uncertainty`, `hero_entry.paired_delta` | `hero_entry.decision_id`, `hero_entry.context_id`, `hero_entry.hero_position` |
| `hero_entry.route_source` (provenance label, never a predictive target) | `hero_entry.action`, `hero_entry.sizing` |
| `hero_entry.support` (`status`, `tier`, `ood`), `hero_entry.posterior_refs` | the public context fixture (`#344`) supplied to `run_harness` |
| the same six fields of every `alternatives[]` entry | `alternatives[].alternative_id`, `.action`, `.sizing` |

Only the allowed public identity is projected: every projected alternative is
reduced to exactly `{alternative_id, action, target_total_bb, incremental_cost_bb}`
(`target_total_bb` from the declared `sizing`, `incremental_cost_bb` derived from
the public Hero contribution), and the request keeps
`source_kind = SYNTHETIC_HARNESS_ONLY`, `synthetic_fixture = true` and an
all-false `information_boundary`. The EV envelope, uncertainty, paired delta,
route/source label, support verdict and posterior references are dropped, never
copied and never defaulted.

That boundary has a testable consequence: **changing only the metadata, at
constant public identity, leaves the projected request byte-identical** (same
`harness_request_sha256`) while the #425 verdict may move. The invariance is
asserted by the contract suite and by the consumer integration suite; the
counterpart (a public sizing or decision-id change *does* change the request) is
asserted too, so a frozen projection cannot pass as invariance.

## Status vocabulary (#425)

`support.status` uses exactly five values, with a fixed, fail-closed precedence
when a consumer collapses one input to a single verdict
(`OOD_UNTESTABLE` > `INSUFFICIENT_SUPPORT` > `TOO_CLOSE` > `SENSITIVE` >
`CONSISTENT`):

| Status | Meaning |
|---|---|
| `CONSISTENT` | Across the declared Model B environments the alternative keeps its standing (same best alternative, ranking and sizing within tolerance). |
| `SENSITIVE` | A declared environment changes the best alternative, the ranking or the sizing, or the best alternative is *clearly superior* to Hero (more than the close band below it, `BEST_ALTERNATIVE_CLEARLY_SUPERIOR`), so the standing is not robust to Model B variation. |
| `TOO_CLOSE` | The comparison is complete but the **absolute** gap to the best alternative is within tolerance (in either direction), so the two are quasi ex-aequo and no ordering can be asserted. |
| `INSUFFICIENT_SUPPORT` | Evidence is missing or unsupported: no robustness claim is allowed. |
| `OOD_UNTESTABLE` | The relevant environment is out of distribution (`support.ood = true`), so it can be reported but cannot be tested against. |

`INSUFFICIENT_SUPPORT` and `OOD_UNTESTABLE` are fail-closed outcomes and must be
surfaced as "not established", never as a weak positive.

The numeric `TOO_CLOSE` test is reserved for a gap inside the close band, and it
is a **magnitude-only** test: the standing is quasi ex-aequo while
`abs(hero_ev - best_ev) <= TOO_CLOSE_DELTA_BB`, in either direction. A gap that
merely points downwards is therefore *not* a quasi-equality beyond that band --
an alternative evaluated clearly above Hero is reported `SENSITIVE` with the
dedicated `BEST_ALTERNATIVE_CLEARLY_SUPERIOR` reason. That corrected case is
never weakened by the best alternative's own `paired_delta`: the best-ranked
alternative compares itself with itself, so its ~0 auto-comparison is not a
close-band proof (fixture
`tests/fixtures/model_b_hero_robustness/best_alternative_clearly_superior.json`).

The comparison set is read with an explicit relevance rule: the classified
standing is Hero versus the **best-ranked** alternative, so only signals about
*that* comparison may speak about it: `hero_entry.paired_delta` (Hero versus the
best alternative) with its optional paired CI, and the best-ranked alternative's
declared `TOO_CLOSE`/`SENSITIVE` support status. The alternative-level
`paired_delta` is never read as Hero evidence -- for the best-ranked alternative
it is the ~0 self-comparison described above, and a lower-ranked alternative's
value describes its own standing against the best, so neither can mask the Hero
standing. Evidence-level signals (`ood`, `INSUFFICIENT_SUPPORT`, a sparse tier, a
missing or malformed `uncertainty` envelope) keep being folded for the Hero entry
and for **every** compared alternative.

The verdict is a status only: neither the classifier nor the report ever selects
an alternative, emits a recommendation or names a best sizing.

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

## Commands

Every command below runs the preserved chain and succeeds on the committed
synthetic fixtures. They are the commands recorded by the consolidation
evidence (`TEST_REPORT.json`).

```
# T5 runner CLI: one fixture, the deterministic report on stdout
PYTHONPATH=. python3 tools/simulation/model_b_hero_robustness_adapter.py \
  --fixture tests/fixtures/model_b_hero_robustness/robust_consistent.json

# T7 run bundle: verify the versioned bundle, regenerate, prove determinism
PYTHONPATH=. python3 tools/simulation/build_model_b_hero_robustness_consumer_run.py --check
PYTHONPATH=. python3 tools/simulation/build_model_b_hero_robustness_consumer_run.py
PYTHONPATH=. python3 tools/simulation/build_model_b_hero_robustness_consumer_run.py --verify-determinism

# #425 suites (T1 -> T6), the reused #344 suite and the #199 non-regression
PYTHONPATH=. python3 tests/simulation/test_model_b_hero_robustness_contract.py
PYTHONPATH=. python3 tests/simulation/test_model_b_hero_robustness_classify.py
PYTHONPATH=. python3 tests/simulation/test_model_b_hero_robustness_adapter.py
PYTHONPATH=. python3 tests/simulation/test_model_b_hero_robustness_consumer.py
PYTHONPATH=. python3 tests/simulation/test_model_b_hero_robustness_consumer_run.py
PYTHONPATH=. python3 tests/simulation/test_model_b_preflop_sensitivity_harness.py
PYTHONPATH=. python3 tests/simulation/test_model_b_robustness.py
```

All commands are dependency-free (`python3` only; the repository does not use
`pytest`), read only the committed synthetic fixtures, the synthetic `#344`
context and the persisted `#340` evidence, and perform no network I/O.

## Run bundle and consolidation evidence

The canonical bundle is
`training/runs/20260927_model_b_hero_robustness_consumer_v1/`:

| File | Content |
|---|---|
| `INPUT_SCHEMA_REF.json` | the T1 `$id`/sha256, the pinned inputs and the T1->T7 chain |
| `<fixture>.report.json` | one report per synthetic fixture, emitted verbatim by the T5 runner |
| `INDEPENDENCE_PROOF.json` | forbidden-feature scan of every projected request, all-false boundary |
| `RUN_PROVENANCE.json` | non-consumption flags, parent `#315`, `next_issue 315`, `parent_closed=false` |
| `SUMMARY.json` | per-report sha256 and the expected/observed statuses |
| `TEST_REPORT.json` | executed #425/#344/#199 suites, documented commands, bundle checks, honest limits |
| `N8N_TASK_RESULT.json` | the task result derived from those checks (`issue=425`, `next_issue=315`) |

`TEST_REPORT.json` and `N8N_TASK_RESULT.json` are versioned by their own
regenerable command:

```
PYTHONPATH=. python3 tools/simulation/build_model_b_hero_robustness_consumer_evidence.py
PYTHONPATH=. python3 tools/simulation/build_model_b_hero_robustness_consumer_evidence.py --check
```

## Out of scope

`contracts/analytics/*` belongs to a different scope (#423) and is not modified
by this contract. `tools/simulation/model_b_robustness.py` and its consumer
`site/analytics/model-b-robustness.js` (#199) are not modified. No removed
consumer entry point, fixture folder or evidence bundle is referenced any more:
the chain above is the only one, and #315 remains open.

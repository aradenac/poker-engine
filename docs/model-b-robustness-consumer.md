# Model B robustness consumer (#425) -- run book

## Purpose

This is the run book of the preserved `#425` Hero -> Model B robustness consumer
chain. It documents the single entry point, the canonical evidence bundle and
every command used to reproduce them. The *semantics* of the contract (input
shape, fail-closed rules, status vocabulary, mapping to `#199`) are specified in
the companion document
`docs/model-b-hero-robustness-consumer.md`; both documents describe the same
chain and nothing else.

The chain is synthetic-only: it is built and reviewed **before** the real Hero
robustness evidence exists, and it never claims a robustness result.

## Identifiers

| Role | Identifier |
|---|---|
| Input contract | `contracts/training/model-b-hero-robustness-input.schema.json`, `$id = hero-model-b-robustness-input/v1` |
| Input source kind | `SYNTHETIC_ROBUSTNESS_SHAPED` |
| Emitted report | `contracts/training/hero-model-b-robustness-consumer-report.schema.json`, `$id = hero-model-b-hero-robustness-consumer-report/v1` |
| Reused harness request (#344) | `contracts/training/model-b-preflop-sensitivity-harness-request.schema.json`, `$id = model-b-preflop-sensitivity-harness-request/v1`, `source_kind = SYNTHETIC_HARNESS_ONLY` |
| Canonical run bundle | `training/runs/20260927_model_b_hero_robustness_consumer_v1/` |

## Parent and upstream

- **parent**: issue `#315` stays open. `RUN_PROVENANCE.json` pins
  `parent_issue = 315`, `next_issue = 315`, `parent_closed = false`; nothing in
  this chain closes it.
- **upstream consumed**: the persisted `#340` run
  (`training/runs/20260919_model_b_preflop_response_to_price_2a/`) reused
  read-only through the public `#344` harness API. No refit, no promotion, the
  active Model B pointer is untouched (`active_model_b_changed = false`).
- **upstream never consumed**: the real ISO EV run of `#367`, the real `#314`
  output, the VALIDATION hand and the TEST hand
  (`real_issue_367_consumed = false`, `real_issue_314_consumed = false`,
  `validation_consumed = false`, `test_consumed = false`).
- the emitted report binds its producing issue and the reused harness
  (`provenance.issue = 425`, `provenance.harness_issue = 344`); the parent
  reference lives in the run provenance only.

## Metadata versus Model B features

`#425` metadata is read for classification and provenance only; it never becomes
a Model B feature. Only the public action identity is projected into the `#344`
request:

| Metadata (classification/provenance only, never projected) | Public identity (projected) |
|---|---|
| `ev`, `uncertainty`, `paired_delta` | `decision_id`, `context_id`, `hero_position` |
| `route_source` (provenance label, never a predictive target) | `action`, `sizing` |
| `support` (`status`/`tier`/`ood`), `posterior_refs` | `alternative_id`, `action`, `sizing` of every alternative |

Every projected alternative carries exactly
`{alternative_id, action, target_total_bb, incremental_cost_bb}`; the request
keeps `source_kind = SYNTHETIC_HARNESS_ONLY`, `synthetic_fixture = true` and an
all-false `information_boundary`. Changing only the metadata, at constant public
identity, leaves the projected request byte-identical (same
`harness_request_sha256`) while the `#425` verdict may move -- that invariance is
covered by the contract suite and by the consumer integration suite.

## Single entry point (T5 runner CLI)

```
# one synthetic fixture, the deterministic report on stdout
PYTHONPATH=. python3 tools/simulation/model_b_hero_robustness_adapter.py \
  --fixture tests/fixtures/model_b_hero_robustness/robust_consistent.json
```

The runner validates the fixture fail-closed (a schema/source-kind mismatch, a
missing provenance/support block, an unknown field or an opened information
boundary is refused with an explicit `reason_code`, exit code `2` and **no**
report), projects it onto the `#344` request, classifies it and executes the
`#344` harness against the persisted `#340` evidence. The emitted report carries
`input_schema_ref`, the single `status`, its sorted `reason_codes`, the all-false
information boundary, the synthetic provenance, and the two content hashes
`harness_request_sha256` / `harness_report_sha256`. It embeds no timestamp and
no host path, so two runs over the same fixture are byte-identical.

`--context`, `--model-b-run`, `--candidate`, `--reference`, `--summary`,
`--result` and `--provenance` override the synthetic `#344` context and the
persisted `#340` evidence. A source path inside the real `#367` ISO EV run is
refused before the file is opened.

The classifier (T4) collapses one fixture to exactly one of five statuses, with
the fail-closed precedence
`OOD_UNTESTABLE > INSUFFICIENT_SUPPORT > TOO_CLOSE > SENSITIVE > CONSISTENT` and
three corrected human-review findings:

1. the effective CI95 width is **derived from the `ci95` bounds**; a `width_bb`
   that contradicts them is refused (`UNCERTAINTY_WIDTH_MISMATCH`), and a
   coherent width above policy is `INSUFFICIENT_SUPPORT`;
2. **every** compared alternative's uncertainty is checked before `CONSISTENT`
   can be emitted (a secondary alternative without a measured envelope is
   `INSUFFICIENT_SUPPORT`, never `CONSISTENT`);
3. the numeric `TOO_CLOSE` test is the **absolute** gap inside the close band; an
   alternative clearly superior to Hero is `SENSITIVE` with
   `BEST_ALTERNATIVE_CLEARLY_SUPERIOR`. No output selects or recommends a sizing.

## Canonical run bundle

| File | Content |
|---|---|
| `INPUT_SCHEMA_REF.json` | the T1 `$id`/sha256, the pinned fixtures/context/#340 digests and the T1->T7 chain |
| `<fixture>.report.json` | one report per synthetic fixture, written verbatim by the T5 runner |
| `INDEPENDENCE_PROOF.json` | forbidden-feature scan of every projected request and the all-false boundary |
| `RUN_PROVENANCE.json` | non-consumption flags, `parent_issue 315`, `next_issue 315`, `parent_closed false` |
| `SUMMARY.json` | per-report sha256, expected/observed statuses, determinism command |
| `TEST_REPORT.json` | executed suites, documented commands, bundle checks and honest limits |
| `N8N_TASK_RESULT.json` | the task result derived from those checks |

```
# verify the versioned bundle, regenerate it, prove determinism
PYTHONPATH=. python3 tools/simulation/build_model_b_hero_robustness_consumer_run.py --check
PYTHONPATH=. python3 tools/simulation/build_model_b_hero_robustness_consumer_run.py
PYTHONPATH=. python3 tools/simulation/build_model_b_hero_robustness_consumer_run.py --verify-determinism
```

The builder refuses to write anything unless its two passes are byte-identical,
never embeds a timestamp, a host path or a running commit, and consumes only the
committed synthetic fixtures, the synthetic `#344` context and the persisted
`#340` evidence.

## Consolidation evidence

```
PYTHONPATH=. python3 tools/simulation/build_model_b_hero_robustness_consumer_evidence.py
PYTHONPATH=. python3 tools/simulation/build_model_b_hero_robustness_consumer_evidence.py --check
```

The evidence command records:

- one entry per executed suite: the preserved `#425` suites (contract, classify,
  adapter, consumer integration, run bundle), the reused `#344` harness suite and
  the `#199` backend non-regression suite;
- the exit code and observation of every documented command above;
- that the removed consumer entry point, fixture folder and evidence bundle are
  absent and that these two documents no longer reference them;
- the bundle `--check`, the two-pass regeneration and the sha256 of every
  artifact (so `--check` of the bundle proves there is no drift);
- a traceability list from every ticket acceptance item to the test that proves
  it (`acceptance_evidence`); a renamed or deleted regression makes the evidence
  fail (`acceptance_evidence_check`) instead of leaving a stale claim;
- the honest limits of the local run. CI gate status is `NOT_OBSERVED` from the
  worker sandbox (no network); `jsonschema` is not a locked dependency, so when
  it is absent the adapter suite's schema cross-check is reported as *skipped*
  and the shipped schema is still enforced by the adapter's built-in walker; a
  skipped test is never reported as a pass.

`N8N_TASK_RESULT.json` is derived from those checks and carries `issue = 425`,
`parent_issue = 315`, `next_issue = 315`, `parent_closed = false`,
`real_hero_results_consumed = false`, `validation_consumed = false`,
`test_consumed = false`, `active_model_b_changed = false`,
`automatic_promotion = false` and `production_effect = "NONE"`.

## Out of scope

`contracts/analytics/*` (#423) and the `#199` backend
`tools/simulation/model_b_robustness.py` plus its consumer
`site/analytics/model-b-robustness.js` are not modified. The real sensitivity
evaluation of `#315` is not executed, and `#315` is not closed here.

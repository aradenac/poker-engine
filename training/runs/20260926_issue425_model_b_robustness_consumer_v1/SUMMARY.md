# Run 20260926_issue425_model_b_robustness_consumer_v1 (issue #425, parent #315)

## What this run is

Synthetic, versioned proof that the fail-closed **CLI T5** Hero -> Model B robustness consumer (`tools/simulation/model_b_hero_robustness_consumer.py`) consumes the whole T2 fixture folder end to end and emits one `hero-model-b-robustness-consumer-report/v1` per fixture, with an all-false Model A / EV / recommendation / route independence boundary.

Run status: `READY_FOR_INTEGRATION` (see `RESULT.json`).

This run is synthetic only: **no real sensitivity was executed**.

## Deterministic (re)generation

```sh
PYTHONPATH=. python3 tools/simulation/build_issue425_robustness_consumer_run.py --out-dir training/runs/20260926_issue425_model_b_robustness_consumer_v1
```

The builder invokes the CLI T5 consumer in batch mode twice, independently, and refuses to persist anything unless both passes produce byte-identical artifacts; it then assembles `PROVENANCE.json`, `FIXTURE_OUTPUTS.json`, `INDEPENDENCE_PROOF.json`, `RESULT.json` and this `SUMMARY.md`. No timestamp and no host path is embedded, so two regenerations over the same inputs produce identical sha256. Verify the committed bytes with:

```sh
PYTHONPATH=. python3 tools/simulation/build_issue425_robustness_consumer_run.py --check
PYTHONPATH=. python3 tools/simulation/build_issue425_robustness_consumer_run.py --verify-determinism
```

## Fixture outcomes

| fixture | decision_id | status | reason_codes | request_sha256 | report_sha256 |
| --- | --- | --- | --- | --- | --- |
| `multiple_sizings.json` | `synthetic-robustness-multiple-sizings-001` | `SENSITIVE` | SUPPORT_STATUS_SENSITIVE | `5ab4af636a375cd8190e69214dcd036941307a810d26a97d8b2a2e4dac6b3e37` | `cad8e759bc30076216261b7e5deaa193d7afc53668c7de70a75cdd74d1c54936` |
| `ood_unsupported.json` | `synthetic-robustness-ood-unsupported-001` | `OOD_UNTESTABLE` | SUPPORT_OOD, SUPPORT_STATUS_OOD | `5a565574356ee04fc5a782c03425f1ab060dca98823229ed9f1a0f6d04da38b3` | `5dd1e6e9f5c8edc85b4424a8a344458d22c04833c78addd9796e7eabb82565a4` |
| `robust_recommendation.json` | `synthetic-robustness-robust-recommendation-001` | `CONSISTENT` | CONSISTENT_ACROSS_ENVIRONMENTS | `36961522662dcc36e6f38ba9379ab012b8d6a0e6b7c49ccc805b7f1c0b7e5d14` | `c32f336714e323ba809119ebcecb253c9fba5aa8b92a138a18e434923c2aff50` |
| `sparse_high_uncertainty.json` | `synthetic-robustness-sparse-high-uncertainty-001` | `INSUFFICIENT_SUPPORT` | CI95_WIDTH_EXCEEDS_POLICY, SUPPORT_STATUS_INSUFFICIENT | `32f938f2180f7645fa515c2ae39c821067b8f7c981bc1347a830807fc8c37d62` | `8398c5b6c66add2ed9ec170b5c2be68bbdbffc4e637794c68dc1cdcb93fc7c5d` |
| `too_close.json` | `synthetic-robustness-too-close-001` | `TOO_CLOSE` | ADVANTAGE_WITHIN_TOLERANCE, PAIRED_DELTA_WITHIN_TOLERANCE, SUPPORT_STATUS_TOO_CLOSE | `ee13b3263c65a562360aa830a447d7e36bae519fc2e6213406ea4221417c1e18` | `572981c40bc55977b8099e6110f8069d38643df43335b3b718bc2d57db7e379c` |

`statuses` histogram: `CONSISTENT`=1, `INSUFFICIENT_SUPPORT`=1, `OOD_UNTESTABLE`=1, `SENSITIVE`=1, `TOO_CLOSE`=1.

## Independence proof (`INDEPENDENCE_PROOF.json`)

- `forbidden_hits = []` (no Model A / EV / recommendation / route field crossed the boundary);
- `information_boundary_all_false = true`;
- the sha256 of every projected `#344` request is pinned per fixture.

## Boundaries (nothing real was consumed)

| flag | value |
| --- | --- |
| `real_hero_results_consumed` | `false` |
| `validation_consumed` | `false` |
| `test_consumed` | `false` |
| `parent_closed` | `false` |
| `real_sensitivity_executed` | `false` |
| `real_issue_314_consumed` | `false` |
| `real_issue_367_consumed` | `false` |
| `model_a_consumed` | `false` |
| `hero_ev_consumed` | `false` |
| `recommendation_consumed` | `false` |
| `automatic_promotion` | `false` |
| `active_model_b_changed` | `false` |
| `production_effect` | `NONE` |
| `next_issue` | `315` |

## Issue #315 status

**Issue #315 remains open.** This run only standardizes and exercises the *synthetic* robustness consumer; it does not consume the still-unavailable real `#314` output, does not run the real Model B sensitivity evaluation and does not close the remaining sensitivity DoD of #315. **No real sensitivity evaluation was executed**, no real Hero/EV result was read, no VALIDATION/TEST hand was opened and nothing was promoted.

## Out of scope

`contracts/analytics/*` belongs to a different scope and is not modified by this run.

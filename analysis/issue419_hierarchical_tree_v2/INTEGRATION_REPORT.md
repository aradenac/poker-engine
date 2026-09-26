# #419 — integration report v2 (T7): hierarchical exact-tree evidence bundle

Schema `poker-hierarchical-integration-report/v2`, bundle `analysis/issue419_hierarchical_tree_v2`, task `backlog-oso` (`T7`), issue #419 (source issue #388, scenario #321), next issue #367.

This report consolidates the terminal #419 evidence into one content-addressed bundle. Every member is either a byte-identical copy of a T1/T3/T4 authority or a digest reference whose bytes are never duplicated. Nothing outside `analysis/issue419_hierarchical_tree_v2/` is written; no holdout is re-opened; #367 is never run.

## 1. Verdict (n8n)

```
N8N_TASK_RESULT
active_pointer_mutated: false
admitted: false
blockers: NO_ADMISSIBLE_POOLING_LEVEL,UNRESOLVED_RAISE_SIZING_FRONTIER,REFUSED_CALIBRATION,REFUSED_COVERAGE_FLOOR
bundle: analysis/issue419_hierarchical_tree_v2
candidate_id: model-a-preflop-sizing-hierarchical-candidate-v1
candidate_sha256: 637302885b8119e6b0246d827462c36eb707c6e234d0b652483c956f03360999
ci_status: NOT_OBSERVED
decision: UNRESOLVED_HIERARCHICAL_TREE_GAP
hero_ev_executed: false
integration_ready: false
issue: 419
issue367_run: false
next_issue: 367
primary_blocker: NO_ADMISSIBLE_POOLING_LEVEL
required_tree_complete: false
required_tree_sha256: 0ab232ae44e4157e2a47d4d3d611ac8ca9c2cdb54caf2568f256f6df35643a25
status: BLOCKED_SCIENTIFIC
test_consumed: false
validation_consumed: true
validation_outcome: RETAIN_ACTIVE_REFERENCE
validation_reference_sha256: 0b92e5a78ab3ee4cb581c33be351d6b52bcf4fcd8741ab907ebd6dd32ec6ef68
```

`BLOCKED_SCIENTIFIC` / `UNRESOLVED_HIERARCHICAL_TREE_GAP`. Admission is never forced: it requires `required_tree_complete=true` **and** a VALIDATION outcome of `ADMIT_CANDIDATE` with every frozen gate passing. Neither holds — `0` of `38` required nodes carry an admissible answer, and the consumed VALIDATION result published `RETAIN_ACTIVE_REFERENCE`.

Blockers: `NO_ADMISSIBLE_POOLING_LEVEL`, `UNRESOLVED_RAISE_SIZING_FRONTIER`, `REFUSED_CALIBRATION`, `REFUSED_COVERAGE_FLOOR`.

## 2. Bundle inventory (content-addressed)

| member | mode | role | byte sha256 | canonical payload |
| --- | --- | --- | --- | --- |
| HIERARCHICAL_MODEL_SPEC.json | BYTE_IDENTICAL_COPY | T2_HIERARCHICAL_MODEL_SPEC | 5be122e54e9ee07313a7efa0e0a6dbf4e195eceacf78287a9ac5a448964d105c | d4885e9d148e3a0246968168e246644d4dc81965383447bc74b3c8ca3c3541d4 |
| TRAIN_FIT_REPORT.json | BYTE_IDENTICAL_COPY | T3_TRAIN_FIT_REPORT | ae5b7cc84a8a7a38cd5d832810bf90ecc82aa03cfc4915fc9b33162dbad056b5 | 1a27b69e554b7fffcc734f3a8f7f8d6684e057e665feb7c64d43db930ae0f903 |
| CANDIDATE_MANIFEST.json | BYTE_IDENTICAL_COPY | T4_CANDIDATE_MANIFEST | d6801eb15810ecfc3096d643e721f914cf2a34264e79eee2daaf7e413279303c | cec63b6e2d44b307e27353828dd442503e07f242188df98637d1a05c148a05c1 |
| EXACT_TREE_PREFLIGHT_V2.json | BYTE_IDENTICAL_COPY | T8_EXACT_TREE_PREFLIGHT_V2 | 2c07ae3279d10ec3e3bbdbe81cdb0d0f1f23e6bbb91cbdadddae113d1a9ea691 | c25afda4d1fd56608b5041ba3cd63749b8229f10ea980a6f8957d02d52d24bcb |
| DECISION_V2.json | BYTE_IDENTICAL_COPY | T7_TERMINAL_DECISION_V2 | ac291b9ed363080401e9649a30b157eec7f7b79d5d2dc6df70390ccebc67c4b5 | c6accf274293dc60f7df016bb4f4d5e5ff62a86b91e63f719187424ff803f037 |
| FROZEN_VALIDATION_PROTOCOL_V2.json | DIGEST_REFERENCE_NO_BYTES | T1_FROZEN_VALIDATION_PROTOCOL_V2 | 74b8a006ae84f8b9b22913ef76977e95f08992feb9765639a46d1ac49eb87350 | cb598a9fc2353aa78f19a7263a62a8ccbdba60eb400264787e896d0c232f19de |
| VALIDATION_RESULT.json | DIGEST_REFERENCE_NO_BYTES | T6_CONSUMED_VALIDATION_RESULT_V1 | 0b92e5a78ab3ee4cb581c33be351d6b52bcf4fcd8741ab907ebd6dd32ec6ef68 | b05012719388ec803481adaebe281e70982654f55153a81679f51555e9124ba6 |
| INTEGRATION_REPORT.json | GENERATED | see `ARTIFACTS.json` | — | — |
| INTEGRATION_REPORT.md | GENERATED | see `ARTIFACTS.json` | — | — |
| SUMMARY.md | GENERATED | see `ARTIFACTS.json` | — | — |
| N8N_TASK_RESULT.txt | GENERATED | see `ARTIFACTS.json` | — | — |

`INTEGRATION_REPORT.json` is the machine-readable source of this document; `INTEGRATION_REPORT.md` is rendered from it. `ARTIFACTS.json` binds all eleven members by byte digest and content-addressed object, and `INTEGRATION_REPORT.sha256` pins the report itself.

## 3. What is proven by a real CI run ID, and what is only local

This section is the point of the report, so it is stated without decoration.

### 3.1 Proven by a real CI run ID

**None.** `ci_proven_claims` has 0 entries. The authoritative workflow « Execute issue 419 hierarchical exact tree » has never produced a run: the T5 evidence bundle records `ci_observation.status = NOT_OBSERVED`, `run_name_recorded = null`, `run_url = null`, and the workflow is `present_at_remote_pr_head = false`.

The 5 real CI run IDs that do exist at the reviewed PR head `d087b5c72619b5279a674045e18dda2c3807e1b5` are recorded here because they are real, and every one of them executes **none** of the #419 suites:

| workflow | run | event | conclusion | executes #419 suites | url |
| --- | --- | --- | --- | --- | --- |
| Project state consistency | #153 | pull_request | success | no | https://github.com/aradenac/poker-engine/actions/runs/36196040214 |
| Validate preflop context contract | #257 | pull_request | success | no | https://github.com/aradenac/poker-engine/actions/runs/36196040196 |
| Persisted dataset integrity | #627 | pull_request | success | no | https://github.com/aradenac/poker-engine/actions/runs/36196040256 |
| Validate sequential independent arena | #977 | pull_request | success | no | https://github.com/aradenac/poker-engine/actions/runs/36196040257 |
| Validate sequential independent arena | #976 | push | success | no | https://github.com/aradenac/poker-engine/actions/runs/36196031300 |

`none_executes_the_issue419_suites = true`. The status may not be promoted by any of: `a local replay of the workflow steps`, `an asserted or declarative evidence file`, `the PR body or a PR comment`.

### 3.2 Verified locally from persisted bytes by this tool (authoritative only for byte identity)

* the T1/T2/T3/T4/T5/T6/T7/T8 authority digests
* every upstream content-addressed index and its object copies
* the root ARTIFACTS.json / SUMMARY.md frozen bytes
* the active Model A v5 reference and both registries
* no holdout / hand-history file was opened (runtime tripwire)
* no holdout loader symbol or module is referenced (AST scan)
* no #367 Hero EV runner symbol is referenced (AST scan)
* the v1 preflight pin/bytes mismatch that keeps its --check RED

### 3.3 Recorded local observations (NON-AUTHORITATIVE, never merge evidence)

recorded by the task worker inside the isolated worktree sandbox on 2026-09-26; they are NON-AUTHORITATIVE, were not re-executed by this tool and are never merge evidence

| command | observed | exit | explained by |
| --- | --- | --- | --- |
| `python3 tools/training/finalize_hierarchical_exact_tree_decision.py --check` | PASS | 0 | — |
| `python3 tools/training/write_frozen_validation_protocol_v2.py --check` | PASS (v1_surfaces_verified=10) | 0 | — |
| `python3 tools/training/fit_model_a_preflop_sizing_hierarchical.py --check` | OK (status=BLOCKED_SCIENTIFIC, next_issue=367) | 0 | — |
| `python3 tools/training/audit_hierarchical_candidate_contract.py` | PASS (active_pointer_unchanged=true) | 0 | — |
| `python3 tools/simulation/issue419_exact_tree_preflight.py --check` | FAIL: the frozen v1 preflight artifact drifted: EXACT_TREE_PREFLIGHT.json 456d85be57b910d3a56cb0160ba0ba35c988f7f69da9f965f0a887aaac473ae6 != e86b7c6b57d170c0885f46734c41302dcc15608252dfbbd66bff62c258d5c65f | 1 | V1_PREFLIGHT_PIN_STALE |
| `python3 tools/training/write_frozen_validation_protocol.py --check` | FAIL (expected): ValidationOrderError: VALIDATION was already read for the hierarchical candidate; the frozen protocol must be authored before any evaluation | 1 | EXPECTED_AFTER_THE_SINGLE_FROZEN_READ |
| `PYTHONPATH=. python3 tests/simulation/test_issue419_exact_tree_preflight.py` | FAIL: 5 failures, 7 errors; the suite re-derives the pre-correction v1 preflight and protocol v2 digests the tool still pins | 1 | V1_PREFLIGHT_PIN_STALE,PROTOCOL_V2_PREFLIGHT_PIN_STALE |

## 4. Supersession ledger

### SUPERSEDED_V2_PROTOCOL_PAYLOAD_508A31EC

* superseded: `508a31ec8072a72ca573f65ac6b748e1ce5e67c639fd4388e472153b7ffa4320` (canonical `a97391d2678d66a46cc7a8d2d0893a509c9c2564a5c420f4519d21c05216dd16`, kept at `analysis/issue419_hierarchical_tree/validation_protocol_v2/history/508a31ec8072a72ca573f65ac6b748e1ce5e67c639fd4388e472153b7ffa4320.json`)
* superseding: `74b8a006ae84f8b9b22913ef76977e95f08992feb9765639a46d1ac49eb87350` (canonical `cb598a9fc2353aa78f19a7263a62a8ccbdba60eb400264787e896d0c232f19de`, `analysis/issue419_hierarchical_tree/validation_protocol_v2/FROZEN_VALIDATION_PROTOCOL_V2.json`)
* mechanism: `V2_AMENDMENT_1_CONDITIONAL_NODE_CLOSURE`; thresholds moved: `false`; gates relaxed: `false`

Claim: the flat counts_as_a_closed_exact_tree_node=false was replaced by NODE_CLOSES_IFF_ALL_FROZEN_LAYER_B_GATES_PASS; no threshold and no gate value moved and every gate is equal to or stricter than its v1 homologue

### V1_EXACT_TREE_PREFLIGHT_REGENERATION

* mutant commit `871e0bd9e66c978932face1accf1aaf22ac9fa1a` (backlog-sd5) rewrote `EXACT_TREE_PREFLIGHT.json` to `e86b7c6b57d170c0885f46734c41302dcc15608252dfbbd66bff62c258d5c65f` (canonical `d027391f636b1ccc41c82b9a6b5d9a332ce44dba8ae2fb1c1ae2419eb340c217`) and re-registered the index as `4fea09fc5713b9fa490effb39c557962ae1d06146710d954fb21bfd39ef25743`
* correction `c904524` (`issue419-evidence-integrity-correction-v1`, `analysis/issue419_hierarchical_tree/evidence_integrity_correction/EVIDENCE_INTEGRITY_CORRECTION.json`, `f601d6195ccc4b71a36c5e5729c07c3277bc910bce254c39028485181e8a8803`) restored `EXACT_TREE_PREFLIGHT.json` to `456d85be57b910d3a56cb0160ba0ba35c988f7f69da9f965f0a887aaac473ae6` (canonical `fc08988f0a677b462e484d1964a47967783e10cd1871fe810097b7c7265a9bbd`) and the index to `97e90eac0a9302f1d0b304fa698f5179c7c0ee98ad52ebe307a911d9ccbfa5be`, without touching a pin and without rewriting a frozen byte to fit a digest
* superseded by `analysis/issue419_hierarchical_tree/exact_tree_preflight_v2/EXACT_TREE_PREFLIGHT_V2.json`; residual finding `V1_PREFLIGHT_PIN_STALE`

Claim: commit 871e0bd rewrote the frozen v1 preflight in place and re-registered its digests; commit c904524 reversed exactly that surface, byte for byte, without touching the pins. The regenerated (restored) bytes are the authority; the duplicate e86b7c6b object no longer exists

### Other declared supersessions

* `EXACT_TREE_PREFLIGHT_V1_SUPERSEDED_BY_V2`: `analysis/issue419_hierarchical_tree/exact_tree_preflight/EXACT_TREE_PREFLIGHT.json` → `analysis/issue419_hierarchical_tree/exact_tree_preflight_v2/EXACT_TREE_PREFLIGHT_V2.json` — the v1 payload embeds code.preflight_tool.sha256 of the superseded v1 tool, which no longer exists on disk; v1 is byte-pinned, re-verified and never rewritten, and --revision v1 is refused
* `TERMINAL_DECISION_V1_SUPERSEDED_BY_V2`: `analysis/issue419_hierarchical_tree/terminal_decision/DECISION.json` → `analysis/issue419_hierarchical_tree/terminal_decision_v2/DECISION_V2.json` — the v1 decision is byte-pinned and re-verified on every build; v2 is an additive revision composed of the TRAIN-only preflight v2 and the digest-referenced consumed v1 VALIDATION bytes

## 5. Residual findings

| finding | blocks READY_FOR_INTEGRATION | detail |
| --- | --- | --- |
| CI_NOT_OBSERVED | true | no run of « Execute issue 419 hierarchical exact tree » exists at any head; the five real CI runs at the reviewed PR head execute none of the #419 suites |
| V1_PREFLIGHT_PIN_STALE | true | the preflight tool pins the pre-correction v1 preflight bytes, which the evidence-integrity correction restored to a different (authoritative) digest, so issue419_exact_tree_preflight.py --check fails closed on its own frozen surface |
| PROTOCOL_V2_PREFLIGHT_PIN_STALE | true | the same preflight tool also pins the pre-correction protocol v2 bytes, so the protocol-v2 custody check inside the preflight suite fails even after the v1 pin is repaired |
| WORKFLOW_BYTES_CHANGED_BY_THIS_TASK | false | this task adds the analysis/issue419_hierarchical_tree_v2/** trigger glob so the new bundle surface re-runs the authoritative workflow (the #419 path-coverage guard fails otherwise); the workflow bytes therefore differ from the bytes T5 recorded |

`V1_PREFLIGHT_PIN_STALE` in detail: the preflight tool pins `V1_PREFLIGHT_SHA256=e86b7c6b57d170c0885f46734c41302dcc15608252dfbbd66bff62c258d5c65f` and `V1_INDEX_SHA256=4fea09fc5713b9fa490effb39c557962ae1d06146710d954fb21bfd39ef25743`, while the restored authority on disk is `456d85be57b910d3a56cb0160ba0ba35c988f7f69da9f965f0a887aaac473ae6` / `97e90eac0a9302f1d0b304fa698f5179c7c0ee98ad52ebe307a911d9ccbfa5be` (`pin_matches_on_disk_bytes=false`). The pin was re-pointed by `887e46a (task backlog-agg)` after the correction `c904524` restored the bytes, so `python3 tools/simulation/issue419_exact_tree_preflight.py --check` is red. It is **not** repaired here (the preflight tool digest is pinned by the T8 preflight payload and by the T9 terminal decision, so editing it would rewrite frozen evidence this task may not touch); it is owned by the exact-tree preflight task; repairing it here would move a frozen surface.

`PROTOCOL_V2_PREFLIGHT_PIN_STALE` in detail: the same tool pins `PROTOCOL_V2_BYTE_SHA256=db1b1ab60224eb76e7a271de6a9544c89ac9676036e725935d0fb47105b9f6f1` and `PROTOCOL_V2_CANONICAL_PAYLOAD_SHA256=e80732c4ea5512863c448497b89896799f24c942f744193832dabd5c568579f0`, while the amended protocol v2 authority on disk is `74b8a006ae84f8b9b22913ef76977e95f08992feb9765639a46d1ac49eb87350` / `cb598a9fc2353aa78f19a7263a62a8ccbdba60eb400264787e896d0c232f19de` (`pin_matches_on_disk_bytes=false`). This is the pin the preflight suite trips first (`PYTHONPATH=. python3 tests/simulation/test_issue419_exact_tree_preflight.py`), and it is the same staleness as the v1 pin: `887e46a (task backlog-agg)` re-pointed both to the pre-correction digests. It is not repaired here either, for the same reason.

## 6. Coherence with the T1/T3/T4 authorities

| cross-check | value |
| --- | --- |
| upstream_bundles_verified | 14 |
| candidate_id_matches_t4_manifest_and_contract | true |
| candidate_sha256_matches_t4_manifest_and_terminal_decision_v2 | true |
| required_tree_sha256_matches_decision_v1_v2_and_preflight_v2 | true |
| protocol_v2_declares_the_superseded_digest_it_replaced | true |
| root_artifacts_index_and_summary_bytes_unchanged | true |
| t1_sparsity_baseline_digest | ef3995daaf5bc48a09f0785d574f7494754ad3904b87ecd2aa089b5be1b24a36 |
| t2_model_spec_digest | 5be122e54e9ee07313a7efa0e0a6dbf4e195eceacf78287a9ac5a448964d105c |
| t3_train_fit_report_digest | ae5b7cc84a8a7a38cd5d832810bf90ecc82aa03cfc4915fc9b33162dbad056b5 |
| t4_candidate_manifest_digest | d6801eb15810ecfc3096d643e721f914cf2a34264e79eee2daaf7e413279303c |
| t4_candidate_digest | 637302885b8119e6b0246d827462c36eb707c6e234d0b652483c956f03360999 |
| frozen_protocol_v1_digest | 69c99a8b37589f1687b7e980344c9a79d69bbcd45be0a53ffd59bfea0ab583b3 |
| frozen_protocol_v2_digest | 74b8a006ae84f8b9b22913ef76977e95f08992feb9765639a46d1ac49eb87350 |
| validation_result_digest | 0b92e5a78ab3ee4cb581c33be351d6b52bcf4fcd8741ab907ebd6dd32ec6ef68 |
| terminal_decision_v1_digest | 9425f30163dcfa5e0a72ca8f6dd1bb4b6a25ce270b4a894aaa57e898a74bd0bc |
| terminal_decision_v2_digest | ac291b9ed363080401e9649a30b157eec7f7b79d5d2dc6df70390ccebc67c4b5 |
| exact_tree_preflight_v1_digest | 456d85be57b910d3a56cb0160ba0ba35c988f7f69da9f965f0a887aaac473ae6 |
| exact_tree_preflight_v2_digest | 2c07ae3279d10ec3e3bbdbe81cdb0d0f1f23e6bbb91cbdadddae113d1a9ea691 |

Candidate `model-a-preflop-sizing-hierarchical-candidate-v1` (`637302885b8119e6b0246d827462c36eb707c6e234d0b652483c956f03360999`) is the T4 candidate: the T4 manifest, the candidate contract and the terminal decision v2 all name the same id and the same canonical digest, and the required tree `0ab232ae44e4157e2a47d4d3d611ac8ca9c2cdb54caf2568f256f6df35643a25` is the one both decisions and the preflight v2 walk.

## 7. Boundaries

* `validation_consumed=true` — exactly one frozen read, performed by T6; this bundle reads the published result **by digest only** (`0b92e5a78ab3ee4cb581c33be351d6b52bcf4fcd8741ab907ebd6dd32ec6ef68`)
* `holdout_reopened_by_this_bundle=false`, `decision_rows_read_by_this_bundle=0`, `metrics_recomputed_by_this_bundle=0`, `thresholds_re_selected_by_this_bundle=false`
* `test_consumed=false`, `test_authorized=false` — TEST is untouched
* `active_pointer_mutated=false` — the active Model A v5 reference stays `ff952055ca4ee051a3ac9607d513fdecac0a320a31f658ecfd8a11d8448975ca`
* `hero_ev_executed=false`, `rollouts_executed=0`, `issue367_run=false` — #367 is never run by #419
* no hand history, decision row or dataset file was opened: `dataset_or_hand_history_opens = []` over 90 benign evidence files opened
* every frozen input is re-verified byte-for-byte before and after the build: `protected_files_unchanged=true` over 32 files

## 8. Reproduction

```bash
python3 tools/training/build_hierarchical_integration_bundle_v2.py
python3 tools/training/build_hierarchical_integration_bundle_v2.py --check
PYTHONPATH=. python3 tests/training/test_issue419_hierarchical_exact_tree.py
```

## 9. Why the status is BLOCKED_SCIENTIFIC, and what READY_FOR_INTEGRATION would take

The verdict is `BLOCKED_SCIENTIFIC` because the required #388/#419 response tree is not complete: `0` of `38` required nodes carry an admissible answer, the primary blocker is `NO_ADMISSIBLE_POOLING_LEVEL`, and the seven raise-sizing frontiers stay unresolved. The consumed VALIDATION result fails `calibration_absolute` and `coverage_floor`. A fail-closed node is never repaired by lowering a frozen threshold, so no adjustment is available here.

`READY_FOR_INTEGRATION` would additionally require, in this order:

1. the `V1_PREFLIGHT_PIN_STALE` and `PROTOCOL_V2_PREFLIGHT_PIN_STALE` defects fixed by their owner task, so `issue419_exact_tree_preflight.py --check` and the preflight suite are green again without moving a frozen surface;
2. the branch pushed past the reviewed head so `« Execute issue 419 hierarchical exact tree »` can run, and a real run ID recorded with `conclusion=success` and the no-op guard reporting every declared suite executed;
3. a scientific resolution of `NO_ADMISSIBLE_POOLING_LEVEL` and of the seven raise-sizing frontiers, which is a #367/#388 question and not something #419 may simulate.

Nothing in this bundle admits the candidate, promotes it, wires the provider or moves a pointer. It records evidence only.

# Hierarchical exact tree — integration bundle v2 re-bound to the repaired revisions — 2026-09-26

Decision owner: issue #419 (source issue #388, scenario #321, next issue #367).
This record documents the regeneration of
`analysis/issue419_hierarchical_tree_v2/` (the T7 integration bundle) so that it
binds the **repaired** `EXACT_TREE_PREFLIGHT_V2.json` and `DECISION_V2.json`
revisions, and closes the residual finding the evidence-integrity correction v2
record had explicitly deferred to this task.

Reproduce:
`python3 tools/training/build_hierarchical_integration_bundle_v2.py`;
verify:
`python3 tools/training/build_hierarchical_integration_bundle_v2.py --check`.

## Decision 1 — the bundle was stale, not the frozen evidence

The bundle was authored when the pre-repair revisions were on disk, so it bound
`EXACT_TREE_PREFLIGHT_V2.json` to `2c07ae32…` and `DECISION_V2.json` to
`ac291b9e…`. Commits `9859c46` (task `backlog-911`) and `0f9a6eb` (task
`backlog-i8v`) then regenerated those two bundles, so the recorded pins no longer
described the bytes on disk and `--check` failed closed on its own members. The
fix belongs in the bundle, which is the only writer of
`analysis/issue419_hierarchical_tree_v2/`; no frozen byte is touched.

| bundle member | before (pre-repair) | after (repaired, at HEAD) |
| --- | --- | --- |
| `EXACT_TREE_PREFLIGHT_V2.json` | `2c07ae3279d10ec3e3bbdbe81cdb0d0f1f23e6bbb91cbdadddae113d1a9ea691` | `9b924077b286ef8c7c57e8a6e757cfb22a9784d2b44e8b328b11a55ba27abfc2` |
| `DECISION_V2.json` | `ac291b9ed363080401e9649a30b157eec7f7b79d5d2dc6df70390ccebc67c4b5` | `4e220ecee2a8e3ac957c6b5d89ee79dd4f1920503de7442ea6b2e2e06ac7c882` |

The two canonical payloads move with them: the preflight v2 canonical payload is
now `d88d1dba290f9a86033db7a875f8013b813472c24390c8a2736a09b7670b3a5b` (was
`c25afda4d1fd56608b5041ba3cd63749b8229f10ea980a6f8957d02d52d24bcb`) and the
terminal decision v2 canonical payload is now
`2eb8b3824023b16566d662d63eb5f830368d483ff30e4ee90210b8c2607167d0` (was
`c6accf274293dc60f7df016bb4f4d5e5ff62a86b91e63f719187424ff803f037`).

## Decision 2 — the repaired members are the ones the decisions themselves bind

The regeneration is not "adjusted to fit": the copied authorities were required
to agree with the terminal decision v2 that references them.
`DECISION_V2.json` binds `exact_tree_preflight_v2_sha256 = 9b924077…`, it is on
the v2 raise-sizing frontier revision (`v2_raise_sizing_frontier_sha256 =
9df16dbb…`), and the bundle now records a third digest reference —
`RAISE_SIZING_FRONTIER_RESOLUTION.json` (v2,
`9df16dbb741659a8f6983e7ce243e3f1796b9fbf6b71be742fd0bc0b5c05540b`, schema
`poker-raise-sizing-frontier-resolution/v2`) — whose frozen v1 custody bytes
`93e7e3ed…` are re-verified on every build and never rewritten. The v2 revision
supersedes the v1 with no threshold moved and no gate relaxed.

## Decision 3 — the two pre-repair pin findings are RESOLVED, and the deferred finding is CLOSED

`9859c46` restored the preflight tool's four pins
(`V1_PREFLIGHT_SHA256` / `V1_INDEX_SHA256` / `PROTOCOL_V2_BYTE_SHA256` /
`PROTOCOL_V2_CANONICAL_PAYLOAD_SHA256`) to the custody digests without moving one
frozen byte. The bundle therefore recomputes `pin_matches_on_disk_bytes = true`
for both `V1_PREFLIGHT_PIN_STALE` and `PROTOCOL_V2_PREFLIGHT_PIN_STALE` and
records them as **RESOLVED** history rather than residual defects:

* `python3 tools/simulation/issue419_exact_tree_preflight.py --check` → `PASS`;
* `PYTHONPATH=. python3 tests/simulation/test_issue419_exact_tree_preflight.py` → `OK (24 tests)`.

The evidence-integrity correction v2 record recorded (and deferred to this task)
the finding `INTEGRATION_BUNDLE_V2_PINS_PRE_REPAIR_REVISIONS`. Re-binding the two
copies above closes it: the bundle's own `resolved_findings` carries the closure,
with the before/after digests, status `CLOSED_BY_THIS_REGENERATION` and
`touches_a_frozen_byte = false`. Nothing frozen was rewritten to produce it.

## Decision 4 — the 17 frozen digests are unchanged (re-verified on disk)

Every digest below was re-read with `hashlib.sha256` at this HEAD; each equals the
value recorded before the regeneration, so no `gelé v1/v2` byte moved.

| frozen path | byte sha256 (before = after) |
| --- | --- |
| `analysis/issue419_hierarchical_tree/exact_tree_preflight/EXACT_TREE_PREFLIGHT.json` | `456d85be57b910d3a56cb0160ba0ba35c988f7f69da9f965f0a887aaac473ae6` |
| `analysis/issue419_hierarchical_tree/exact_tree_preflight/ARTIFACTS.json` | `97e90eac0a9302f1d0b304fa698f5179c7c0ee98ad52ebe307a911d9ccbfa5be` |
| `analysis/issue419_hierarchical_tree/exact_tree_preflight/SUMMARY.md` | `3b87d9bcc366c35e97bde6a4be350704a0cf2eecadb464d5ac321298443778df` |
| `analysis/issue419_hierarchical_tree/terminal_decision/DECISION.json` | `9425f30163dcfa5e0a72ca8f6dd1bb4b6a25ce270b4a894aaa57e898a74bd0bc` |
| `analysis/issue419_hierarchical_tree/terminal_decision/ARTIFACTS.json` | `08530e37f8ecf232fc032612021f74459e6af771f15fc4097748c0d73f86b7e4` |
| `analysis/issue419_hierarchical_tree/terminal_decision/SUMMARY.md` | `bb9c1b6f15695bb94b287a940ffd0e542ba575c586725fcea4dad4ecc235ed8f` |
| `analysis/issue419_hierarchical_tree/terminal_decision/N8N_TASK_RESULT.txt` | `4fd1ab14ef254dd2ac250f5ab0ead1c54c5d0fe2e289921e326954d0c1d28333` |
| `analysis/issue419_hierarchical_tree/validation_protocol_v2/FROZEN_VALIDATION_PROTOCOL_V2.json` | `74b8a006ae84f8b9b22913ef76977e95f08992feb9765639a46d1ac49eb87350` |
| `analysis/issue419_hierarchical_tree/validation_protocol/FROZEN_VALIDATION_PROTOCOL.json` | `69c99a8b37589f1687b7e980344c9a79d69bbcd45be0a53ffd59bfea0ab583b3` |
| `analysis/issue419_hierarchical_tree/validation/VALIDATION_RESULT.json` | `0b92e5a78ab3ee4cb581c33be351d6b52bcf4fcd8741ab907ebd6dd32ec6ef68` |
| `analysis/issue419_hierarchical_tree/ARTIFACTS.json` | `1650cdd96adb70a47e7711eb44820bc46a9afc46f290b9023c60d101d903d768` |
| `analysis/issue419_hierarchical_tree/SUMMARY.md` | `737d315c6fde5d4863830952ab5bf396483bbefc47f3a4cdfcc7fe12508616e8` |
| `analysis/issue419_hierarchical_tree/fit/TRAIN_FIT_REPORT.json` | `ae5b7cc84a8a7a38cd5d832810bf90ecc82aa03cfc4915fc9b33162dbad056b5` |
| `analysis/issue419_hierarchical_tree/fit/CANDIDATE_MANIFEST.json` | `d6801eb15810ecfc3096d643e721f914cf2a34264e79eee2daaf7e413279303c` |
| `analysis/issue419_hierarchical_tree/contract/CANDIDATE_CONTRACT.json` | `d62b2dca4a6673531c764b283de369f1192fe748eabcb4040f7ae0eda1823cd3` |
| `analysis/issue419_hierarchical_tree/raise_sizing_frontiers/RAISE_SIZING_FRONTIER_RESOLUTION.json` | `93e7e3ede0a69e6b3e35f40217bd53ff95d1fbbb847ca3fbc9181c0689d0152e` |
| `analysis/issue419_hierarchical_tree/ci_evidence/CI_EVIDENCE.json` | `764b7f6daf111ef949471a69f7652d7d9ffba2cc0be09eff2a39a2c144327018` |

## Decision 5 — no mutant digest stays active, and the history is not rewritten

After the regeneration the pre-repair preflight v2 copy that carried the mutant
mentions `b1f7f5a9…` / `ee5907f3…` is gone from
`analysis/issue419_hierarchical_tree_v2/` (the whole pre-repair object set, e.g.
`2c07ae32….json` and `ac291b9e….json`, is dropped and the content-addressed
object set is closed over the twelve current members). The remaining mentions of
the earlier mutant digests (`e86b7c6b…`, `4fea09fc…`, `db1b1ab6…`) survive only
as **recorded history** — in the tool's supersession ledger, in this record's
predecessors and in the bundle's own supersession section — never as a custody
pin, a checked digest or a content-addressed object. No history is rewritten and
no supersession is denied; the bundle keeps the v1 `EXACT_TREE_PREFLIGHT`
regeneration, the v1→v2 raise-sizing frontier revision and the superseded v2
protocol payload `508a31ec…` on the record.

## Decision 6 — one authoring-time snapshot re-derives differently (recorded, not hidden)

The evidence-integrity correction v2 record is a HEAD-pinned snapshot whose own
`--check` re-derives a mutant-name survey from the live tree. Re-binding the
integration bundle removes two mutant-name mention paths from that survey, so
`python3 tools/training/build_hierarchical_evidence_integrity_correction_v2.py --check`
now reports `bundle member is stale: EVIDENCE_INTEGRITY_CORRECTION_V2.json`. The
drift is **bookkeeping only** — the record's digest table, tool-pin table,
frozen-byte re-verification and order-guard results are unchanged, and no frozen
byte moved. This task may not rewrite a v2 record (its static residual finding is
a truthful statement about its own HEAD), so the coupling is recorded here and as
the bundle's `EVIDENCE_INTEGRITY_CORRECTION_V2_SNAPSHOT_REDERIVATION_DRIFT`
finding instead of editing the record. The record's deferred finding
`INTEGRATION_BUNDLE_V2_PINS_PRE_REPAIR_REVISIONS` is closed above.

## Outcome

`python3 tools/training/build_hierarchical_integration_bundle_v2.py --check`
returns `rc=0`, the v2 preflight check and the terminal-decision v2 check stay
`rc=0`, and `PYTHONPATH=. python3 tests/training/test_issue419_hierarchical_exact_tree.py`
is `OK (24 tests)` — the two faulty assertions
(`9b924077 != 2c07ae32`, `4e220ece != ac291b9e`) no longer reproduce. The verdict
is unchanged and never forced: `BLOCKED_SCIENTIFIC` /
`UNRESOLVED_HIERARCHICAL_TREE_GAP`, `required_tree_complete=false`,
`validation_consumed=true` (one frozen read, not re-opened), `test_consumed=false`,
`active_pointer_mutated=false`, `hero_ev_executed=false`, `issue367_run=false`,
`next_issue=367`. No candidate is admitted, no pointer moves, and CI is still
`NOT_OBSERVED` until the authoritative workflow runs at a pushed head.

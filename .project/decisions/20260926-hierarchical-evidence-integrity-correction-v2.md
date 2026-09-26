# Hierarchical exact tree — evidence integrity correction v2 — 2026-09-26

Decision owner: issue #419 (source issue #388, scenario #321, next issue #367).
This record points at the machine-readable source of truth for the **second**
evidence-integrity incident and states what a reader must not have to
reconstruct from the JSON.

## Decision 1 — the v1 record stays byte-frozen, the second incident is additive

The recorded correction v1
(`analysis/issue419_hierarchical_tree/evidence_integrity_correction/`, byte
`f601d6195ccc4b71a36c5e5729c07c3277bc910bce254c39028485181e8a8803`) reversed
the in-place rewrite of `871e0bd` and closed with the declaration that no active
reference to the mutant digests `e86b7c6b…` / `4fea09fc…` / `ec010a54…` /
`db1b1ab6…` survived. That declaration stopped being true afterwards. The
machine-readable account of the two later incidents, of their repair and of the
before/after digests therefore lives in a **new, standalone** content-addressed
directory:
`analysis/issue419_hierarchical_tree/evidence_integrity_correction_v2/EVIDENCE_INTEGRITY_CORRECTION_V2.json`
(`poker-issue419-evidence-integrity-correction/v2`). Not one byte of the v1
record is edited; only its digest is re-verified.

## Decision 2 — a re-pinned custody digest is the same violation as a rewritten byte

Commit `887e46afc34cae4334ffb279449c87a9b12bde71` (*task backlog-agg*) re-pointed
the exact-tree preflight tool onto the **pre-correction** custody digests:
`V1_PREFLIGHT_SHA256` / `V1_INDEX_SHA256` (`e86b7c6b…` / `4fea09fc…`) and
`PROTOCOL_V2_BYTE_SHA256` / `PROTOCOL_V2_CANONICAL_PAYLOAD_SHA256` (`db1b1ab6…` /
`e80732c4…`), while the bytes persisted on disk are the restored ones
(`456d85be…` / `97e90eac…` / `74b8a006…` / `cb598a9f…`). A pin that names a byte
the frozen bundle no longer carries is a false witness: it re-introduces the
mutant digests as *active* references and makes
`python3 tools/simulation/issue419_exact_tree_preflight.py --check` fail closed.
That check is the detector, and it was red from `887e46a` until
`9859c46ede94646a7547871369bb257b8510114d` (*task backlog-911*) restored the four
pins to the custody digests without rewriting one frozen byte.

## Decision 3 — `4e16a60` rewrote frozen evidence in place and re-registered it

Commit `4e16a60ac1c58b56429c0eda8ce36778dcea8971` (*task backlog-txu*) rewrote
`analysis/issue419_hierarchical_tree/raise_sizing_frontiers/RAISE_SIZING_FRONTIER_RESOLUTION.json`
(`93e7e3ed…` → `6a8cfcd1…`) and
`analysis/issue419_hierarchical_tree/terminal_decision/DECISION.json`
(`9425f301…` → `70a0d809…`) in place, together with
`terminal_decision/ARTIFACTS.json` (`08530e37…` → `1c433e7a…`), their
content-addressed objects and the two owning tools. Re-registering a digest from
the commit that moved the byte makes the mutant commit the only witness of its
own claim. `0f9a6eb0e53a5191a2302d5eabb175ae267f7c24` (*task backlog-i8v*)
restored the pre-mutant bytes and moved the mutant objects aside; the record
re-verifies that result rather than rewriting it.

| path (short) | mutant (`4e16a60`) | restored (at HEAD) |
| --- | --- | --- |
| `raise_sizing_frontiers/RAISE_SIZING_FRONTIER_RESOLUTION.json` | `6a8cfcd1…` | `93e7e3ed…` |
| `terminal_decision/DECISION.json` | `70a0d809…` | `9425f301…` |
| `terminal_decision/ARTIFACTS.json` | `1c433e7a…` | `08530e37…` |

## Decision 4 — nothing frozen moved to produce this record

Re-verified at HEAD with `sha256sum`: the 13 frozen digests are unchanged
(`exact_tree_preflight/EXACT_TREE_PREFLIGHT.json`
`456d85be…`, `terminal_decision/DECISION.json` `9425f301…`,
`validation_protocol_v2/FROZEN_VALIDATION_PROTOCOL_V2.json` `74b8a006…`,
`validation/VALIDATION_RESULT.json` `0b92e5a7…`, the root
`analysis/issue419_hierarchical_tree/ARTIFACTS.json` `1650cdd9…`, its
`SUMMARY.md` `737d315c…`, …), the v1 correction record is still `f601d619…`, no
mutant digest survives as a content-addressed object, and
`tools/training/validation_order_guard.validation_result_artifacts()` still
returns only the two frozen VALIDATION artifacts. The record is **not**
registered in the root index nor in any sibling index, so every other `--check`
keeps its own closed artifact set; a note is never written into a frozen artifact
to explain a frozen artifact.

## Decision 5 — the pre-push evidence is local, and CI is still unobserved

The pre-push preparation record of the CI-evidence bundle is
`analysis/issue419_hierarchical_tree/ci_evidence/PRE_PUSH_PREPARATION.json`
(`poker-issue419-pre-push-preparation/v1`). It separates explicitly the **local**
replay of the frozen HEAD (non-authoritative, never merge evidence) from the
**CI** evidence, which stays absent: `ci_observation.status` remains
`NOT_OBSERVED` because the authoritative workflow has never produced a run at a
pushed head. No local replay, declarative file, PR body or PR comment may promote
that status.

Reproduce:
`python3 tools/training/build_hierarchical_evidence_integrity_correction_v2.py`;
verify:
`python3 tools/training/build_hierarchical_evidence_integrity_correction_v2.py --check`.

## Decision 6 — one pre-existing red suite is recorded, not silently repaired

The pre-push replay of the frozen HEAD is **20 green / 1 red**. The red one is
`PYTHONPATH=. python3 tests/training/test_issue419_hierarchical_exact_tree.py`
(`FAILED (failures=2, errors=1)`): the integration bundle
`analysis/issue419_hierarchical_tree_v2/` still binds
`EXACT_TREE_PREFLIGHT_V2.json` to `2c07ae32…` and `DECISION_V2.json` to
`ac291b9e…`, the revisions that existed when it was authored, while `9859c46`
and `0f9a6eb` later regenerated those bundles. Its two local observations
(`V1_PREFLIGHT_PIN_STALE`, `PROTOCOL_V2_PREFLIGHT_PIN_STALE`) describe a pin
state that the repairs already closed, so the whole aggregate contract is stale.
That is a **separate consumer** of these surfaces and it touches no frozen byte;
it is owned by the integration-bundle task (`backlog-oso` / T7). It is recorded
as the residual finding `INTEGRATION_BUNDLE_V2_PINS_PRE_REPAIR_REVISIONS` in the
correction record and as the single red row in
`analysis/issue419_hierarchical_tree/ci_evidence/PRE_PUSH_PREPARATION.json`
rather than being papered over or repaired out of scope here.

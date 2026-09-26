# #419 — evidence integrity correction v2 (re-pin `887e46a`, in-place mutation `4e16a60`)

Schema `poker-issue419-evidence-integrity-correction/v2`, bundle `analysis/issue419_hierarchical_tree/evidence_integrity_correction_v2`, task `backlog-g95` (`T3`), issue #419, recorded against `n8n/issue-419/task-backlog-g95` at `0f9a6eb0e53a5191a2302d5eabb175ae267f7c24`.

The v1 record (`analysis/issue419_hierarchical_tree/evidence_integrity_correction/EVIDENCE_INTEGRITY_CORRECTION.json`, byte `f601d6195ccc4b71a36c5e5729c07c3277bc910bce254c39028485181e8a8803`) reversed `871e0bd` and closed with the declaration that no active reference to the mutant digests survived. Two later commits broke that declaration; this record documents both, the repair, and the before/after digests. It writes no frozen byte and edits no predecessor record.

## Incident 1 — re-pinned custody digests (`887e46a`, task `backlog-agg`)

The exact-tree preflight tool was re-pinned onto the pre-correction digests while the bytes persisted on disk stayed the restored ones, so the pin and the byte disagreed and the check failed closed. `9859c46` (task `backlog-911`) restored the pins.

| pin | restored custody digest (at HEAD) | re-pinned by `887e46a` |
| --- | --- | --- |
| `V1_PREFLIGHT_SHA256` | `456d85be57b910d3a56cb0160ba0ba35c988f7f69da9f965f0a887aaac473ae6` | `e86b7c6b57d170c0885f46734c41302dcc15608252dfbbd66bff62c258d5c65f` |
| `V1_INDEX_SHA256` | `97e90eac0a9302f1d0b304fa698f5179c7c0ee98ad52ebe307a911d9ccbfa5be` | `4fea09fc5713b9fa490effb39c557962ae1d06146710d954fb21bfd39ef25743` |
| `PROTOCOL_V2_BYTE_SHA256` | `74b8a006ae84f8b9b22913ef76977e95f08992feb9765639a46d1ac49eb87350` | `db1b1ab60224eb76e7a271de6a9544c89ac9676036e725935d0fb47105b9f6f1` |
| `PROTOCOL_V2_CANONICAL_PAYLOAD_SHA256` | `cb598a9fc2353aa78f19a7263a62a8ccbdba60eb400264787e896d0c232f19de` | `e80732c4ea5512863c448497b89896799f24c942f744193832dabd5c568579f0` |

## Incident 2 — frozen evidence rewritten in place (`4e16a60`, task `backlog-txu`)

The raise-sizing frontier resolution and the terminal decision were rewritten in place and their resulting digests re-registered. `0f9a6eb` (task `backlog-i8v`) restored the bytes and moved the mutant objects aside.

## Before / after digest table

`reverted` = the repair put the parent bytes back; `rewritten` = the repair is a new revision that restores the pin, not the file; `retained` = the repair kept the offender's bytes.

| surface | path | before (parent) | mutant (offending) | at HEAD | disposition |
| --- | --- | --- | --- | --- | --- |
| `REGRESSION_887E46A` | `tools/simulation/issue419_exact_tree_preflight.py` | `c8f7538464d3a4df…` | `dfc405abf482c574…` | `c5d34a3dc03c418a…` | rewritten |
| `REGRESSION_887E46A` | `tests/simulation/test_issue419_exact_tree_preflight.py` | `933c35a4333500f4…` | `421303847833ca61…` | `47407185d5206a59…` | rewritten |
| `REGRESSION_887E46A` | `analysis/issue419_hierarchical_tree/exact_tree_preflight_v2/EXACT_TREE_PREFLIGHT_V2.json` | `9d9cede166983a67…` | `2c07ae3279d10ec3…` | `9b924077b286ef8c…` | rewritten |
| `REGRESSION_887E46A` | `analysis/issue419_hierarchical_tree/exact_tree_preflight_v2/SUMMARY.md` | `7706c3421baf312e…` | `29a560cbfe69cf83…` | `ae130aaf4e1f9e42…` | rewritten |
| `REGRESSION_887E46A` | `analysis/issue419_hierarchical_tree/exact_tree_preflight_v2/ARTIFACTS.json` | `01797e314b3a7113…` | `22ef95ca14743ab1…` | `8738385f059bab20…` | rewritten |
| `MUTATION_4E16A60` | `analysis/issue419_hierarchical_tree/raise_sizing_frontiers/RAISE_SIZING_FRONTIER_RESOLUTION.json` | `93e7e3ede0a69e6b…` | `6a8cfcd1dbea6203…` | `93e7e3ede0a69e6b…` | reverted |
| `MUTATION_4E16A60` | `analysis/issue419_hierarchical_tree/raise_sizing_frontiers/ARTIFACTS.json` | `86ab23239979b9ee…` | `a7dd833e377beb2c…` | `86ab23239979b9ee…` | reverted |
| `MUTATION_4E16A60` | `analysis/issue419_hierarchical_tree/raise_sizing_frontiers/SUMMARY.md` | `cf092d67b1b09d60…` | `4aabb5ec2e566532…` | `cf092d67b1b09d60…` | reverted |
| `MUTATION_4E16A60` | `analysis/issue419_hierarchical_tree/terminal_decision/DECISION.json` | `9425f30163dcfa5e…` | `70a0d8097c9629c6…` | `9425f30163dcfa5e…` | reverted |
| `MUTATION_4E16A60` | `analysis/issue419_hierarchical_tree/terminal_decision/ARTIFACTS.json` | `08530e37f8ecf232…` | `1c433e7a1bf78db8…` | `08530e37f8ecf232…` | reverted |
| `MUTATION_4E16A60` | `analysis/issue419_hierarchical_tree/terminal_decision/DECISION.sha256` | `7a7169d03f7bc43d…` | `9c5aa225ba2df7e0…` | `7a7169d03f7bc43d…` | reverted |
| `MUTATION_4E16A60` | `tools/training/resolve_raise_sizing_frontiers.py` | `307fb62490368e51…` | `7e856e11a1141561…` | `91ebba7897eb6d6c…` | rewritten |
| `MUTATION_4E16A60` | `tools/training/finalize_hierarchical_exact_tree_decision.py` | `80764cbe69da712f…` | `80764cbe69da712f…` | `2f6dacac0d165344…` | unchanged |
| `MUTATION_4E16A60` | `tests/training/test_raise_sizing_frontier_resolution.py` | `d1d3a7e5bec1a3d7…` | `c2c020c9efedb474…` | `751a55f005a8e6cb…` | rewritten |
| `MUTATION_4E16A60` | `tests/training/test_hierarchical_terminal_decision.py` | `61135652c3f36df2…` | `61135652c3f36df2…` | `34f2d8c45df8f28a…` | unchanged |
| `MUTATION_4E16A60_RETAINED` | `tests/training/test_hierarchical_candidate_contract.py` | `90cdc9f63d43541d…` | `36d3b3d1d090a25a…` | `36d3b3d1d090a25a…` | retained |
| `MUTATION_4E16A60_RETAINED` | `tests/training/test_hierarchical_tree_sparsity_parity.py` | `6a0ed3b48c45eb0c…` | `c61526387815a460…` | `c61526387815a460…` | retained |

## What is verified at HEAD

Every digest in the table is re-derived from the bytes persisted at HEAD, every parent and offending revision is cross-checked against the local git object store, every reverted row carries the parent bytes again, no mutant digest survives as a content-addressed object, the four preflight custody pins equal the restored digests, the root #419 index and summary are unmoved (`1650cdd9…` / `737d315c…`), the v1 record is byte-identical, and `tools/training/validation_order_guard.validation_result_artifacts()` still returns only the two frozen VALIDATION artifacts.

## Deliberately not done here

* `INTEGRATION_BUNDLE_V2_PINS_PRE_REPAIR_REVISIONS` — analysis/issue419_hierarchical_tree_v2/ still binds EXACT_TREE_PREFLIGHT_V2.json to 2c07ae32 and DECISION_V2.json to ac291b9e, the revisions that existed when it was authored; 9859c46 and 0f9a6eb later regenerated those bundles, so PYTHONPATH=. python3 tests/training/test_issue419_hierarchical_exact_tree.py is red at HEAD (2 failures, 1 error)
* `MUTANT_NAMES_SURVIVE_AS_RECORDED_HISTORY` — e86b7c6b, 4fea09fc, db1b1ab6 and e80732c4 still appear as recorded history in the v1 correction record, the integration report and the validation-protocol document; none of them is a custody pin, a checked digest or an object on disk

Reproduce: `python3 tools/training/build_hierarchical_evidence_integrity_correction_v2.py`; verify: `python3 tools/training/build_hierarchical_evidence_integrity_correction_v2.py --check`. This directory is outside every other index; its own digests are in `EVIDENCE_INTEGRITY_CORRECTION_V2.sha256` and `ARTIFACTS.json`.

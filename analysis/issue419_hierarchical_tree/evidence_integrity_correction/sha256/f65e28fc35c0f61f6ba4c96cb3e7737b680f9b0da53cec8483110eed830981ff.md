# #419 — evidence integrity correction (mutant commit `871e0bd`)

Commit `871e0bd` (*task backlog-sd5*, `chore(n8n): task backlog-sd5 for issue #419`) rewrote the frozen #419 evidence **in place** and re-registered the resulting digests. That is exactly what the review forbids: a frozen byte is evidence, and a digest re-registered by the commit that moved the byte stops being an independent witness. The correction reverses the surface of that single commit — nothing else — and records the before/after digests here, in a fresh content-addressed directory that no other index references.

## What was detected, and when

`python3 tools/simulation/issue419_exact_tree_preflight.py --check` raised

```
PreflightError: the frozen v1 preflight artifact drifted: EXACT_TREE_PREFLIGHT.json
e86b7c6b57d170c0885f46734c41302dcc15608252dfbbd66bff62c258d5c65f
!= 456d85be57b910d3a56cb0160ba0ba35c988f7f69da9f965f0a887aaac473ae6
```

The pins in the tool (`V1_PREFLIGHT_SHA256`, `V1_SUMMARY_SHA256`, `V1_INDEX_SHA256`, `V1_BYTE_SHA256`, `PROTOCOL_V2_BYTE_SHA256`, `PROTOCOL_V2_CANONICAL_PAYLOAD_SHA256`) were **never** changed by the mutant; only the bytes on disk moved away from them. The correction therefore restores the bytes and leaves the pins alone.

## Restoration (mutant digest → restored digest)

The surface of `871e0bd` was reversed file by file against its parent `f9c1834b386c98e2beba648ac1b1ad6fbe0326ae`. Every frozen artifact now reads back byte-identical to its pre-mutant revision, so no digest had to be "re-registered" to close a check.

| frozen artifact | mutant (`871e0bd`) | restored (on disk) |
| --- | --- | --- |
| `exact_tree_preflight/EXACT_TREE_PREFLIGHT.json` | `e86b7c6b…c65f` | `456d85be…3ae6` |
| `exact_tree_preflight/ARTIFACTS.json` | `4fea09fc…5743` | `97e90eac…a5be` |
| `exact_tree_preflight/SUMMARY.md` | `3b87d9bc…78df` (unchanged) | `3b87d9bc…78df` |
| `terminal_decision/DECISION.json` | `ec010a54…8cff` | `9425f301…bd0bc` |
| `terminal_decision/ARTIFACTS.json` | `ea5b385d…f102` | `08530e37…b7e4` |
| `validation_protocol_v2/FROZEN_VALIDATION_PROTOCOL_V2.json` | `db1b1ab6…f6f1` | `74b8a006…7350` |
| `validation_protocol_v2/ARTIFACTS.json` | `5b698d5e…d629` | `97acf64d…44cb` |
| `validation_protocol_v2/SUMMARY.md` | `c8d52e03…868e` | `44cdc191…e36c` |
| `fit/TRAIN_FIT_REPORT.json` | `b1f7f5a9…2dd5` | `ae5b7cc8…56b5` |
| `fit/CANDIDATE_MANIFEST.json` | `ee5907f3…664c` | `d6801eb1…303c` |
| `contract/CANDIDATE_CONTRACT.json` | `5d0fbcaf…6a98` | `d62b2dca…23cd3` |

The corresponding content-addressed objects moved back with them: `sha256/e86b7c6b…json`, `ec010a54…json`, `db1b1ab6…json`, `c8d52e03…md`, `b1f7f5a9…json`, `ee5907f3…json`, `5d0fbcaf…json` and `4bb90dfe…md` are gone, and `456d85be…json`, `9425f301…json`, `74b8a006…json`, `44cdc191…md`, `ae5b7cc8…json`, `d6801eb1…json`, `d62b2dca…json` and `bc03a758…md` are restored. No active reference to `e86b7c6b`, `4fea09fc`, `ec010a54` or `db1b1ab6` remains in `tools/`, `docs/`, `tests/` or `contracts/`; the four hexes survive only as the mutant names recorded here.

The code and documentation half of the same commit is reversed too: `tools/preflop/model_a_sizing_hierarchical.py`, `contracts/training/model-a-preflop-sizing-hierarchical-likelihood.schema.json`, `tests/preflop/test_model_a_sizing_hierarchical.py`, `tools/training/write_frozen_validation_protocol_v2.py`, `docs/hierarchical-exact-context-validation-protocol.md` and `docs/hierarchical-exact-context-runtime-contract.md` all match their pre-mutant bytes, so the documents quote `74b8a006` again and the protocol writer publishes the frozen v2 payload.

## What this correction did **not** touch

* `FROZEN_VALIDATION_PROTOCOL.json` stays `69c99a8b37589f1687b7e980344c9a79d69bbcd45be0a53ffd59bfea0ab583b3`.
* `validation/VALIDATION_RESULT.json` stays `0b92e5a78ab3ee4cb581c33be351d6b52bcf4fcd8741ab907ebd6dd32ec6ef68`: the single consumed VALIDATION read is untouched.
* `validation_protocol_v2/history/508a31ec…json` remains the declared superseded v2 revision.
* The later useful commits — the v2 preflight bundle (`backlog-jf0`), the suites (`backlog-utj`), the workflow/audit work (`backlog-fgj`, `backlog-ydy`, `backlog-3hk`) — are untouched.
* No threshold, prior, pooling limit, calibration gate or admission rule was changed; no frozen byte was rewritten to make a digest agree.

## Checks after the correction

`python3 tools/simulation/issue419_exact_tree_preflight.py --check` → `PASS` (frozen v1 preflight custody green, v2 bundle reproducible). The terminal decision, protocol v2, candidate contract and train-fit checks are green, and the #419 suites (`test_issue419_exact_tree_preflight`, `test_model_a_sizing_hierarchical`, `test_frozen_validation_protocol` v1/v2, `test_hierarchical_*`, `test_raise_sizing_frontier_resolution`, `test_issue419_hierarchical_exact_tree`, `test_github_workflow_audit`) pass.

This directory is deliberately **outside** every existing content-addressed index: no sibling `ARTIFACTS.json` lists it, so adding it cannot widen another evidence set. Its own digests are in `EVIDENCE_INTEGRITY_CORRECTION.sha256` and `ARTIFACTS.json`.

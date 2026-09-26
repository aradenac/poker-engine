# Hierarchical exact tree — frozen-evidence integrity correction — 2026-09-26

Decision owner: issue #419. This short record points at the machine-readable
source of truth for the frozen-evidence incident and states what a reader must
not have to reconstruct from the JSON.

## Decision 1 — the mutant surface was reversed, not re-registered

Commit `871e0bd9e66c978932face1accf1aaf22ac9fa1a` (*task backlog-sd5*) rewrote
the frozen #419 evidence in place and re-registered the resulting digests. A
frozen byte is evidence: once the commit that moved it also re-registers its
digest, the digest stops being an independent witness. The surface of that one
commit was therefore reversed file by file against its parent `f9c1834b…` by
`c904524` (*task backlog-s19*), and the machine-readable record lives in
`analysis/issue419_hierarchical_tree/evidence_integrity_correction/EVIDENCE_INTEGRITY_CORRECTION.json`
(`poker-issue419-evidence-integrity-correction/v1`, byte
`f601d6195ccc4b71a36c5e5729c07c3277bc910bce254c39028485181e8a8803`). No frozen
byte was rewritten or re-registered to close a check.

## Decision 2 — the frozen bytes are byte-identical to their pins at HEAD

Re-verified at HEAD with `sha256sum`: `exact_tree_preflight/EXACT_TREE_PREFLIGHT.json`
`456d85be…`, its `SUMMARY.md` `3b87d9bc…`, `exact_tree_preflight/ARTIFACTS.json`
`97e90eac…`, `terminal_decision/DECISION.json` `9425f301…`,
`terminal_decision/ARTIFACTS.json` `08530e37…`,
`validation_protocol_v2/FROZEN_VALIDATION_PROTOCOL_V2.json` `74b8a006…`,
`FROZEN_VALIDATION_PROTOCOL.json` `69c99a8b…`,
`validation/VALIDATION_RESULT.json` `0b92e5a7…`, the root
`analysis/issue419_hierarchical_tree/ARTIFACTS.json` `1650cdd9…`, its
`SUMMARY.md` `737d315c…`, `fit/TRAIN_FIT_REPORT.json` `ae5b7cc8…`,
`fit/CANDIDATE_MANIFEST.json` `d6801eb1…` and
`contract/CANDIDATE_CONTRACT.json` `d62b2dca…`.
`python3 tools/simulation/issue419_exact_tree_preflight.py --check` returns
`check=PASS`, and the v2 preflight bundle stays reproducible.

## Decision 3 — the record is additive and outside every pinned index

The correction is a standalone content-addressed directory; it is **not** added
to the root `analysis/issue419_hierarchical_tree/ARTIFACTS.json` (hard pin
`1650cdd9…`) nor to any sibling index, so every other `--check` keeps its own
closed artifact set. The pinned root `SUMMARY.md` (`737d315c…`) is unchanged: a
note is never written into a frozen artifact to explain a frozen artifact.

## Decision 4 — the CI evidence and the PR body belong to their own tasks

The companion record of what the authoritative CI run must prove is
`analysis/issue419_hierarchical_tree/ci_evidence/CI_EVIDENCE.json`
(`poker-issue419-ci-evidence/v1`, `ci_observation.status = NOT_OBSERVED`); it
claims no green run of `Execute issue 419 hierarchical exact tree`. The PR #420
body still announces `Independent review status: PASS` while the review of
`d087b5c` is `NEEDS_FIXES`; correcting that body is owned by **T2**
(`backlog-1vz`), not by this record, and the local sandbox replays are explicitly
non-authoritative.

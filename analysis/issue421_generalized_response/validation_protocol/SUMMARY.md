# #421 — candidate manifest and frozen VALIDATION protocol

`FROZEN_VALIDATION_PROTOCOL.json` byte SHA256: `ff91421b372dab869b8603fac04e7cb15b4b810f4c742c0fff4139786d97cdd5`; frozen at `2026-09-26T00:00:00Z` (`FROZEN_BEFORE_VALIDATION`).

Candidate `generalized-adverse-response-candidate-v1` (regularized_multinomial_spline) canonical payload `c3f3573f3e80b3f7889dc8b1fd6f1948daeea95effc5a41a5d707385c4eed7dc`, byte `ea93e8c35e2604debd943495474cdb9262d724efb4a5caefe3723b53f23a59e7`. Manifest `CANDIDATE_MANIFEST.json` byte SHA256 `06f8380ea898d41efc9f7dbe65968292fd1277fe750229e0059b4df5918f8fea`.

Frozen gates: minimum product coverage `>= 0.5`, non-inferiority CI upper bound `<= 0.0`, maximum absolute ECE `<= 0.05`, raise-sizing illegal-generation rate `<= 0.0`. Every threshold is immutable after the freeze and a fresh rebuild is compared byte-for-byte before any VALIDATION row is read; any candidate/manifest/protocol drift is fail-closed.

Reproduce: `python3 tools/training/freeze_generalized_validation_protocol.py --check`.

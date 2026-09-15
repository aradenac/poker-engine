# Artifact import manifest — 2026-09-11

Source: files explicitly uploaded in the ChatGPT project conversation, plus the user's direct GitHub bootstrap on 2026-09-12. Historical status was reconciled by issue #1 on 2026-09-15; see `artifacts/HISTORICAL_PROVENANCE_AUDIT_20260915.md`.

| Canonical target | Uploaded source | Size | Integrity identity | Status |
|---|---|---:|---|---|
| `user/releases/poker_range_equity_offline_multiway_v78.html` | `poker_range_equity_offline_multiway_v78.html` | 415744 B | SHA-256 `352eabe2b2e6245f6442e79c1ced8dd0b53c5e655d3c5cff52311cdac5b42050` | **external historical identity recorded; raw bytes not in repository; non-blocking** |
| `tools/patch_v78_to_v79.py` | `patch_v78_to_v79.py` | 17981 B | Git blob `38bd82572c7434bf54d1905dea323b54f0719c90` | **imported 2026-09-15; historical transformation provenance** |
| `training/models/preflop_population_model_v5.json` | `preflop_population_model_v5.json` | 16247726 B | SHA-256 `ff952055ca4ee051a3ac9607d513fdecac0a320a31f658ecfd8a11d8448975ca` | **imported** |
| `training/models/postflop_population_model_v5.json` | `postflop_population_model_v5(2).json` | 5046315 B | SHA-256 `6d948f30f6c276ce41e70e83ac35275e30e7841e93e5b1da11782648c6b4d8ae` | **imported** |
| `tools/sequential_postflop_population_sim_v4.py` | `sequential_postflop_population_sim_v4.py` | 22136 B | SHA-256 `adf948126fe72c137e4a03e843fbe25d8654b6348b352f50e76d50efb8d6cabe` | **imported** |
| `training/datasets/NLHE_100-200/source/NLHE 100-200.zip` | `NLHE 100-200.zip` | 5574861 B | SHA-256 `6effd27d6e9f8257f3e87c68f0218b8edc72a2b487cb57da2c37ff85bc8ce4c6` | **imported and audited** |

## Additional persisted artifacts

- Promoted v83 application is committed at `user/releases/poker_range_equity_offline_multiway_v83.html` and mirrored at `site/index.html`.
- v83 SHA-256: `2690a82ffe363017b495a1aef60657b12db1b52eb402c36a1ff87f723c5d1bd4`.
- The source-level historical patch chain is now continuous from v78 through v84 via `tools/patch_v78_to_v79.py` and the existing `tools/patch_v79_to_v80.py` … `tools/patch_v83_to_v84.py` scripts.
- The 2026-09-09 incremental population update is preserved under `training/runs/20260909_population_increment_v2/`.
- The full 2026-09-09 hand-history snapshot is stored at `training/datasets/NLHE_100-200/snapshots/20260909/source/RoiDePiqueNique_training2.zip` with audit manifest alongside it.

## Canonicalization rules

- User-upload suffixes such as `(1)` and `(2)` are removed from canonical repository names.
- Original SHA-256 values are retained when available to verify byte identity; restored text-only historical sources may additionally use their immutable Git blob identity.
- An externally identified artifact is never reconstructed from snippets merely to make an import appear complete. Exact raw bytes are required before creating its canonical binary path.
- Raw hand-history archives stay compressed; reproducible audit manifests record corpus identity and statistics.
- Training outputs are stored by immutable run rather than left at repository root.
- Rejected model candidates remain persisted under their originating run for reproducibility.

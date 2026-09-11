# Artifact import manifest — 2026-09-11

Source: files explicitly uploaded in the ChatGPT project conversation.

| Canonical target | Uploaded source | Size | SHA-256 | Status |
|---|---|---:|---|---|
| `user/releases/poker_range_equity_offline_multiway_v78.html` | `poker_range_equity_offline_multiway_v78.html` | 415744 B | `352eabe2b2e6245f6442e79c1ced8dd0b53c5e655d3c5cff52311cdac5b42050` | received, pending binary/text transfer |
| `training/models/preflop_population_model_v5.json` | `preflop_population_model_v5.json` | 16247726 B | `ff952055ca4ee051a3ac9607d513fdecac0a320a31f658ecfd8a11d8448975ca` | received, pending large-file transfer |
| `training/models/postflop_population_model_v5.json` | `postflop_population_model_v5(2).json` | 5046315 B | `6d948f30f6c276ce41e70e83ac35275e30e7841e93e5b1da11782648c6b4d8ae` | received, pending large-file transfer |
| `tools/sequential_postflop_population_sim_v4.py` | `sequential_postflop_population_sim_v4.py` | 22136 B | `adf948126fe72c137e4a03e843fbe25d8654b6348b352f50e76d50efb8d6cabe` | received, pending transfer |
| `training/datasets/NLHE_100-200/source/NLHE 100-200.zip` | `NLHE 100-200(1).zip` | 5653868 B | `6effd27d6e9f8257f3e87c68f0218b8edc72a2b487cb57da2c37ff85bc8ce4c6` | received, pending binary transfer |

## Canonicalization rules

- User-upload suffixes such as `(1)` and `(2)` are removed from canonical repository names.
- Original SHA-256 values are retained so a later transfer can be verified bit-for-bit.
- Do not mark an artifact as imported until the committed repository object hashes back to the SHA-256 listed above.

## Current connector limitation

The active GitHub connector can create UTF-8 files and Git blobs from inline content, but it does not expose a file-parameter upload action that accepts the mounted uploaded file directly. Large and binary artifacts therefore require a transfer mechanism that preserves their raw bytes; until that transfer is completed, this manifest is the authoritative receipt/provenance record.

# #419 — frozen VALIDATION protocol (authored before any holdout read)

`FROZEN_VALIDATION_PROTOCOL.json` byte SHA256: `69c99a8b37589f1687b7e980344c9a79d69bbcd45be0a53ffd59bfea0ab583b3`; frozen at `2026-09-25T00:00:00Z` (`FROZEN_BEFORE_VALIDATION`). The canonical payload hash and the content-addressed copies are in `validation_protocol/ARTIFACTS.json`.

Comparators are listed explicitly: the active reference `active-model-a-preflop-v5` (`ff952055ca4ee051a3ac9607d513fdecac0a320a31f658ecfd8a11d8448975ca`), the admitted #352 exact-price candidate `model-a-preflop-sizing-aware-candidate-v2` (`9115165c3141d16152946dd1ee7a049f219fef1a1d79c0e1c7b1249c45326f19`, fit/validation evidence pinned), and the new candidate under test `model-a-preflop-sizing-hierarchical-candidate-v1` (`637302885b8119e6b0246d827462c36eb707c6e234d0b652483c956f03360999`).

The requirement manifest pins all 38 #388 tree nodes to `0ab232ae44e4157e2a47d4d3d611ac8ca9c2cdb54caf2568f256f6df35643a25`, including the 7 unresolved raise-sizing frontiers. Thresholds (20 observations / 20 distinct hands, non-inferiority CI upper bound <= 0, ECE <= 0.05) and the acceptable pooling limits (L0 is the only support source, L4 the deepest parameter prior) are frozen and immutable after the freeze.

The order guard is enforced by `tools/training/validation_order_guard.py`: the freeze aborts if a VALIDATION result for this candidate already exists, and the evaluation command must re-verify the pinned protocol bytes before opening a single VALIDATION hand. The #352 split consumption is recorded as a different candidate under its own frozen protocol, never repaired or double-counted. No VALIDATION or TEST decision was parsed while authoring this protocol. It admits nothing.

Reproduce: `python3 tools/training/write_frozen_validation_protocol.py --check`.

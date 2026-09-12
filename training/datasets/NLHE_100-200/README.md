# NLHE 100-200 hand-history dataset

This directory contains immutable raw PokerStars hand-history archives used to train and validate the NLHE 100/200 population models.

## Layout

- `source/NLHE 100-200.zip`: historical baseline archive used by the v4/v5 model lineage.
- `source/manifest.json`: reproducible audit generated from the baseline ZIP.
- `snapshots/20260909/source/RoiDePiqueNique_training2.zip`: later full snapshot containing historical overlap plus newer hands through 2026-09-09.
- `snapshots/20260909/manifest.json`: reproducible audit of that snapshot.
- `increments/20260909/manifest.json`: canonical ID-based comparison of the 2026-09-09 snapshot against the baseline, scoped to stake `100/200`.

## Important: raw archives may contain multiple stakes

The raw ZIP names do not guarantee that every contained hand belongs to 100/200. Continuous ingestion therefore parses the stake from each PokerStars hand header and applies the `100/200` filter **before** overlap/deduplication and TRAIN / VALIDATION / TEST assignment.

For the currently persisted archives:

- the historical ZIP contains 27,164 unique hands in total, of which 26,560 are `100/200`;
- the 2026-09-09 snapshot contains 27,677 unique hands across several stakes, of which 11,709 are `100/200`;
- 10,534 of those `100/200` snapshot hands already exist in the baseline;
- 1,175 are unseen `100/200` hands, all chronologically newer than the baseline cutoff;
- their deterministic split is 929 TRAIN / 123 VALIDATION / 123 TEST.

The previously persisted run `training/runs/20260909_population_increment_v2/` used a 1,000-hand delta. Exact hand-ID comparison shows that those 1,000 hands are a subset of the 1,175 newly discovered `100/200` hands, so the new continuous-ingestion pipeline recovers 175 additional valid observations.

## Continuous-ingestion rule

New snapshots are never treated as blind replacements for older archives. `tools/datasets/build_hand_history_increment.py`:

1. parses EN and FR PokerStars hand headers;
2. filters to the target stake;
3. deduplicates by exact PokerStars hand ID across known archives;
4. preserves the deterministic `poker-population-split-v1` split for every hand ID;
5. records immutable scope, overlap, selected-ID fingerprints, split counts and time coverage.

Timestamp classification is diagnostic only. Membership in an increment is decided by exact hand ID, not by date.

## Why ZIP files remain compressed

Raw archives are kept compressed to avoid duplicating tens of megabytes of hand-history text in Git. Training and audit tools read or extract them at runtime. Small manifests remain in Git so archive identity, hand counts, duplicate detection, date coverage and sorted-hand-ID fingerprints are directly inspectable.

Do not modify an existing archive in place. A new import must be stored as a new immutable snapshot and referenced by a versioned training run.

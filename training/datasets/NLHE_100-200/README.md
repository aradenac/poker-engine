# NLHE 100-200 hand-history dataset

This directory contains immutable raw PokerStars hand-history archives used to train and validate the NLHE 100/200 population models.

## Layout

- `source/NLHE 100-200.zip`: historical baseline archive used by the v4/v5 model lineage.
- `source/manifest.json`: reproducible audit generated from the baseline ZIP.
- `snapshots/20260909/source/RoiDePiqueNique_training2.zip`: full snapshot through 2026-09-09, containing multiple stakes.
- `snapshots/20260909/manifest.json`: reproducible audit of that snapshot.
- `increments/20260909/manifest.json`: canonical ID-based 100/200 increment discovered from that snapshot.
- `snapshots/20260912/source/RoiDePiqueNique.zip`: canonical target for the complete user inventory supplied on 2026-09-12.
- `snapshots/20260912/README.md`: source identity and exact lineage triage for that complete inventory.
- `increments/20260912/manifest.json`: canonical exact-ID triage of the 2026-09-12 inventory against the already-known lineage.
- `increments/20260912/source/selected_100_200.zip`: generated deduplicated training contribution once the 2026-09-12 raw source is persisted.

## Current 100/200 lineage

The historical baseline contains 27,164 unique hands in total, of which **26,560** are `100/200`.

The 2026-09-09 snapshot contains 27,677 unique hands across several stakes, of which **11,709** are `100/200`. Of those, 10,534 already exist in the historical baseline and **1,175** are genuinely new 100/200 hands. Their deterministic split is 929 TRAIN / 123 VALIDATION / 123 TEST.

The complete 2026-09-12 user inventory contains **11,896 unique hands**, all `100/200`, with no duplicate hand ID inside the archive. Exact comparison gives:

- 7,453 hands already present in the historical baseline;
- 1,175 further hands equal to the already-known 2026-09-09 increment;
- **3,268 genuinely unseen hands** against the complete approved lineage;
- deterministic split: **2,606 TRAIN / 320 VALIDATION / 342 TEST**;
- 406 historical-backfill hands and 2,862 chronologically newer hands;
- no normalized-payload conflict among the 7,453 baseline-overlap hand IDs.

The resulting historical baseline + complete 2026-09-12 inventory union is **31,003 unique 100/200 hands**.

The selected 3,268-hand fingerprint is:

`9eb753baed592b48d697ad6d00652612de6153e5033448f41983bccc9e31be2b`

## Important: raw snapshots are evidence, increments are training contributions

A newer snapshot is never appended blindly to older data. Its overlapping hands remain useful as immutable source evidence, but they contribute **zero additional training observations**.

`tools/datasets/build_hand_history_increment.py`:

1. parses EN and FR PokerStars hand headers;
2. filters to the requested stake before comparison;
3. deduplicates by exact PokerStars hand ID across all supplied known archives;
4. preserves the deterministic `poker-population-split-v1` split for every hand ID;
5. records overlap, selected-ID fingerprints, split counts and time coverage;
6. can materialize a selected ZIP containing only genuinely unseen hands.

Timestamp classification is diagnostic only. Membership in an increment is decided by exact hand ID, not by date.

## Why ZIP files remain compressed

Raw archives are kept compressed to avoid duplicating tens of megabytes of hand-history text in Git. Training and audit tools read or extract them at runtime. Manifests remain directly inspectable so archive identity, hand counts, duplicate detection, date coverage and sorted-hand-ID fingerprints are reproducible.

Do not modify an existing archive in place. Every complete new inventory is stored as a new immutable snapshot; only its exact-ID deduplicated increment is allowed to contribute new observations to a training run.

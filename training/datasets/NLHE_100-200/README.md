# NLHE 100-200 hand-history dataset

This directory contains immutable raw PokerStars NLHE 100/200 hand-history archives used to train and validate the population models.

## Layout

- `source/NLHE 100-200.zip`: historical baseline archive used by the v4/v5 model lineage.
- `source/manifest.json`: reproducible audit generated from the baseline ZIP.
- `snapshots/20260909/source/RoiDePiqueNique_training2.zip`: later full snapshot containing historical overlap plus newer hands through 2026-09-09.
- `snapshots/20260909/manifest.json`: reproducible audit of that snapshot.

The September snapshot is not treated as a blind replacement for the historical baseline. The persisted run `training/runs/20260909_population_increment_v2/` selected 1,000 hands strictly newer than the previous cutoff and preserved deterministic TRAIN / VALIDATION / TEST assignment.

## Why ZIP files remain compressed

Raw archives are kept compressed to avoid duplicating tens of megabytes of hand-history text in Git. Training and audit tools read or extract them at runtime. Small manifests remain in Git so archive identity, hand counts, duplicate detection, date coverage and sorted-hand-ID fingerprints are directly inspectable.

Do not modify an existing archive in place. A new import must be stored as a new immutable snapshot and referenced by a versioned training run.

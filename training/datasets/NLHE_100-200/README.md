# NLHE 100-200 hand-history dataset

This directory contains immutable raw PokerStars hand-history archives used by the historical NLHE 100/200 model lineage. The directory name is a legacy blind-scoped label; it must not be interpreted as proof that every hand belongs to the target Zoom population.

## Certified target population — issue #94

The target population is:

- platform: **PokerStars**;
- variant: **NLHE cash**;
- blinds: **100/200** play-money chips;
- format: **Zoom**;
- table size: **6-max**.

`tools/datasets/certify_population.py` audits the immutable historical baseline together with the complete 2026-09-12 inventory and deduplicates by exact PokerStars hand ID. A target-defining property that cannot be established is classified `AMBIGUOUS`; it is never silently admitted.

The measured union contains **31,607 unique raw hand IDs** across all stakes represented by these two authoritative archives. Classification gives:

- **23,789 ADMISSIBLE** target hands: PokerStars NLHE cash, 100/200, Zoom, play money, 6-max;
- **7,818 EXCLUDED** hands;
- **0 AMBIGUOUS** hands.

The exclusions are exact and non-overlapping in this corpus:

- **7,214** hands are 100/200 play-money 6-max **regular/classic tables**, not Zoom;
- **604** hands are Zoom play-money 6-max at **100000/200000**, not 100/200.

Consequently, the previously documented **31,003** count is correctly the blind-scoped `100/200` union, but it is **not** the target Zoom population. Of those 31,003 100/200 hands, 23,789 are target Zoom hands and 7,214 are regular-table hands.

Certified target identity:

- target population ID: `pokerstars_nlhe_100-200_zoom_play_6max_v1`;
- target unique hands: **23,789**;
- target hand-ID fingerprint SHA-256: `4661c200fab5a24ce67a45f0801acd0238c701f55e8dbeeaf3e8299fa250119c`;
- deterministic split: **19,016 TRAIN / 2,324 VALIDATION / 2,449 TEST**;
- all raw unique-ID fingerprint SHA-256: `316ae5b58630d852bac54bfc9af0fb53c83c37053677230328f3120ddacd98fb`.

The audit observed no duplicate population-metadata conflict, no same-language content conflict and no unparsed PokerStars hand header. All 31,607 unique raw hands are classified as PokerStars NLHE cash, play money and 6-max; format and stake account for the exclusions above.

The durable full report is `population_certification.json`. `.github/workflows/population-certification.yml` regenerates it from the immutable sources and checks that the persisted evidence remains byte-identical.

This certification does **not** retroactively relabel the promoted v5/v83 lineage as Zoom-only. Those historical models were built from the broader blind-scoped corpus. Population-isolated datasets, model/strategy pointers and migration are handled by issue #95.

## Layout

- `source/NLHE 100-200.zip`: historical baseline archive used by the v4/v5 model lineage.
- `source/manifest.json`: reproducible audit generated from the baseline ZIP.
- `snapshots/20260909/source/RoiDePiqueNique_training2.zip`: full snapshot through 2026-09-09, containing multiple stakes.
- `snapshots/20260909/manifest.json`: reproducible audit of that snapshot.
- `increments/20260909/manifest.json`: canonical ID-based 100/200 increment discovered from that snapshot.
- `snapshots/20260912/source/RoiDePiqueNique.zip`: canonical target for the complete user inventory supplied on 2026-09-12.
- `snapshots/20260912/README.md`: source identity and exact lineage triage for that complete inventory.
- `increments/20260912/manifest.json`: canonical exact-ID triage of the 2026-09-12 inventory against the already-known lineage.
- `increments/20260912/source/selected_100_200.zip`: generated deduplicated blind-scoped training contribution.
- `population_certification.json`: reproducible target-population certification from the baseline + complete 2026-09-12 inventory.

## Historical blind-scoped 100/200 lineage

The historical baseline contains 27,164 unique hands in total, of which **26,560** are `100/200`.

The 2026-09-09 snapshot contains 27,677 unique hands across several stakes, of which **11,709** are `100/200`. Of those, 10,534 already exist in the historical baseline and **1,175** are genuinely new 100/200 hands. Their deterministic split is 929 TRAIN / 123 VALIDATION / 123 TEST.

The complete 2026-09-12 user inventory contains **11,896 unique hands**, all `100/200`, with no duplicate hand ID inside the archive. Exact comparison gives:

- 7,453 hands already present in the historical baseline;
- 1,175 further hands equal to the already-known 2026-09-09 increment;
- **3,268 genuinely unseen hands** against the complete approved blind-scoped lineage;
- deterministic split: **2,606 TRAIN / 320 VALIDATION / 342 TEST**;
- 406 historical-backfill hands and 2,862 chronologically newer hands;
- no normalized-payload conflict among the 7,453 baseline-overlap hand IDs.

The resulting historical baseline + complete 2026-09-12 inventory union is **31,003 unique 100/200 hands**. This is historical lineage evidence, not a Zoom certification.

The selected 3,268-hand fingerprint is:

`9eb753baed592b48d697ad6d00652612de6153e5033448f41983bccc9e31be2b`

## Important: raw snapshots are evidence, increments are training contributions

A newer snapshot is never appended blindly to older data. Its overlapping hands remain useful as immutable source evidence, but they contribute **zero additional training observations**.

`tools/datasets/build_hand_history_increment.py` preserves the historical exact-ID blind-scoped lineage. `tools/datasets/certify_population.py` adds the stricter population identity classification required by #94. They serve different purposes.

Timestamp classification is diagnostic only. Membership in an increment is decided by exact hand ID, not by date. Target-population admissibility additionally requires all target identity fields to match.

## Why ZIP files remain compressed

Raw archives are kept compressed to avoid duplicating tens of megabytes of hand-history text in Git. Training and audit tools read or extract them at runtime. Manifests remain directly inspectable so archive identity, hand counts, duplicate detection, date coverage and sorted-hand-ID fingerprints are reproducible.

Do not modify an existing archive in place. Every complete new inventory is stored as a new immutable snapshot. Population certification and future population-specific increments must be derived reproducibly from those immutable sources.

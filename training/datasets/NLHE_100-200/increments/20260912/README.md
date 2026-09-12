# 2026-09-12 increment

Source user archive: `RoiDePiqueNique.zip`.

Verified local audit with the repository PokerStars parser:

- SHA-256: `374f8dedf5eeeee26b2cd049b1729f80bd2877c6f7ccef806c580019c5f94fcb`
- size: 2,509,906 bytes
- 71 archive entries
- 11,896 unique PokerStars hands
- 100% stake `100/200`
- EN only
- date coverage: 2026-07-22 22:02:31 through 2026-09-12 17:56:33

Against the complete already-approved lineage (historical baseline + exact 2026-09-09 increment):

- 7,453 hands overlap the historical baseline;
- 1,175 additional hands exactly match the already persisted 2026-09-09 increment (`6142a129...`);
- 3,268 hand IDs are genuinely unseen;
- unseen split: 2,606 TRAIN / 320 VALIDATION / 342 TEST;
- 406 are historical backfill;
- 2,862 are chronological additions after the 2026-09-09 cutoff.

`manifest.json` records the exact fingerprints and split counts. It remains marked `source_archive_persisted=false` until the exact source ZIP is stored in GitHub and the stored bytes re-verify to the source SHA-256 above.

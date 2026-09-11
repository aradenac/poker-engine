# Datasets

Dataset versions are immutable inputs to training/calibration runs.

For each dataset version, keep a small manifest containing:

- dataset ID and version;
- origin/provenance;
- creation/import date;
- record/hand counts;
- filtering/deduplication rules;
- schema version;
- checksum(s);
- storage location when bulk raw data is kept outside Git.

Derived/curated datasets must reference their parent raw dataset versions so the transformation chain remains reproducible.

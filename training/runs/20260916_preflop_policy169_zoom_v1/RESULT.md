# Certified Zoom policy169 refit result

- Population: `pokerstars_nlhe_100-200_zoom_play_6max_v1`
- TRAIN / VALIDATION / TEST: 19,016 / 2,324 / 2,449 hands
- Candidate SHA-256 (uncompressed): `9ca954a8653fd7bff0e0597b9af47a2b9a852926d62c177f86957a9856dfcc31`
- Candidate archive SHA-256: `7ffa13969868ea25b207aa2cb51ddc3829f22ab76baf20c20f323a914096194b`
- Decision: `RETAIN_PRIOR`
- TEST consumed: no

The candidate improved the all-row VALIDATION log loss by 0.001013, with a
paired-hand 95% interval of [-0.001853, -0.000151]. It degraded the required
revealed-hand conditional log loss by 0.045983, with a 95% interval of
[0.031519, 0.059805]. The frozen dual gate therefore rejected the candidate.
The historical v5 model and production pointers remain unchanged.

`candidate.json.gz` is the immutable candidate JSON compressed with gzip.
`VALIDATION.json` contains the complete gate evidence. `DATASET.json` records
the certified materialization used by the experiment.

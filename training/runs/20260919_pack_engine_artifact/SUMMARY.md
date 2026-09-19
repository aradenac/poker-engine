# #370 — Fresh distributable engine artifact

- Artifact: `training/artifacts/pack-engine/poker-pack-engine-runtime-v1-15bfa1ba78b463b63b5b9b8ee47a98fd9b29c2a9b79fa455b791a9781c7d7e08.js`
- Artifact SHA-256: `15bfa1ba78b463b63b5b9b8ee47a98fd9b29c2a9b79fa455b791a9781c7d7e08`
- Source subset: exact #360 subset at `5058c463cd5ed07596115153c2e95b2d7d8c949e`, aggregate `b7f61710817e7bfa391d269bc1452242601c9a4bf10e8f4823e358bd6136b81b`
- Runtime dependency closure: self-contained; `src/analytics/leak-analyzer.js` vendored only to close the adapter dependency.
- Legacy reuse/relabel: none.
- Target compatibility: explicit for `pokerstars_nlhe_100-200_zoom_play_6max_v1` / ZOOM.
- Resolver expectation: engine `ADMISSIBLE`; whole candidate remains blocked because other pack roles are outside #370.
- Preflight expectation: read-only `BLOCKED`; engine artifact available, application release absent and population not promoted.
- Scientific TEST consumed: false.
- Production effect: NONE.

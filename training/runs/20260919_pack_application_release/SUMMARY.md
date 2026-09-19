# #377 - Fresh Zoom application_release candidate

- Release artifact: `training/artifacts/application-release/poker-site-release-zoom-100-200-candidate-v1-25afc20cce834fc93ff140f56723548e806034cd892a8b222de21f916d162984.json`
- Release SHA-256: `25afc20cce834fc93ff140f56723548e806034cd892a8b222de21f916d162984`
- Boot contract: `training/artifacts/application-release/pack-scoped-boot-v1-4af0faa262931e91e49d4e028bf93eed14d508120cfafc29746fbc917f73c38c.js`
- Boot SHA-256: `4af0faa262931e91e49d4e028bf93eed14d508120cfafc29746fbc917f73c38c`
- Engine binding: exact #370 artifact `15bfa1ba78b463b63b5b9b8ee47a98fd9b29c2a9b79fa455b791a9781c7d7e08`
- Explicit Zoom mode: fail-closed; no legacy engine, Model A v5 or retained-reference fallback.
- Legacy/default mode: passthrough; production site files are unchanged.
- Resolver expectation: engine and application_release ADMISSIBLE; whole candidate remains blocked on scientific roles.
- Preflight expectation: BLOCKED/read-only because candidate release is intentionally not promoted and population remains CERTIFIED_DATA_ONLY.
- TEST_CONSUMED=false; production_effect=NONE; #201 remains open.

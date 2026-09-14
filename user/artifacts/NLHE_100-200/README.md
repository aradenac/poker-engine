# NLHE 100-200 user artifact bundle

This directory is the source contract for the coherent user-facing `NLHE 100-200` artifact bundle tracked by #74.

The generated ZIP contains exactly one compatible set of:

- `custom.json` — the user's original range-folder export;
- `preflop_population_model_v5.json` — the promoted integrated preflop population model recorded by the closed training state;
- `postflop_population_model_v5.json` — the matching promoted integrated postflop population model;
- `MANIFEST.json`, `README.md` and `CHECKSUMS.sha256`.

`custom.json.gz.b64` is a deterministic compact repository representation of the exact user export. It must decompress to SHA-256 `1248258112562757e49df545e97f9e54b2dde163fdc755adf0029e89e580e8cb`. It is not the reduced trainer-only range JSON.

`bundle.json` pins the bundle version, source encoding/hashes and closed training state. `tools/build_user_artifact_bundle.py` refuses to build if the registry, engine or promoted Model A files differ from the identities recorded by `FINAL_STATE.json`.

The GitHub Actions workflow `NLHE 100-200 user artifact bundle` builds the archive twice from the same commit, requires byte-identical ZIPs, validates every checksum and uploads the ZIP as a downloadable workflow artifact. A future Release attachment may publish those exact ZIP bytes without rebuilding or changing their contents.

Do not mix population-model JSON files from different bundle versions.

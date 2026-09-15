# Population pack v1

Issue #110 defines the durable distribution unit used by the application and by future Cloudflare catalog work.

## Contract

`poker-population-pack/v1` is an **inseparable population pack**. A complete pack contains the accepted population identity plus every runtime role needed to use that reference coherently:

- Model A preflop;
- Model A postflop;
- Model B runtime files required by the trainer;
- Hero strategy identity;
- Hero range source;
- recommendation engine;
- application release compatibility identity.

Every packaged file has a SHA-256, source path, size and role list in `MANIFEST.json`. `CHECKSUMS.sha256` covers all extracted payload files. The ZIP uses fixed timestamps and deterministic ordering, so two builds from identical inputs and source commit are byte-identical.

The manifest records both the engine identity and the assembled site identity from `site/RELEASE.json`. This does **not** claim the Cloudflare live deployment is verified; #45 owns that proof.

## Population safety

The builder resolves models only through `training/populations/registry.json`. It accepts only `PROMOTED` or `PROMOTED_LEGACY` population states and requires non-null promoted pointers for Model A, Model B, Hero strategy and engine.

Consequently `pokerstars_nlhe_100-200_zoom_play_6max_v1`, currently `CERTIFIED_DATA_ONLY`, is deliberately rejected. The legacy pack is explicitly named `legacy_pokerstars_nlhe_100-200_play_6max_mixed_v1` and must never be advertised as Zoom-only.

The initial pack preserves `custom.json` from the accepted historical user range-folder source. It is labelled as Hero ranges, not as an optimized strategy. Future calculated Hero ranges can replace that role only through a new immutable pack version after their own promotion decision.

No raw HH archive, dataset snapshot, rejected candidate or experimental run is copied into the user pack.

## Build and validation

```sh
python3 tools/build_population_pack.py --out-dir dist/population-packs
python3 tools/validate_population_pack.py dist/population-packs/*.zip
```

The builder also emits a sidecar manifest and ZIP checksum for publication. CI builds the pack twice and compares the ZIP bytes before accepting it.

## Immutable GitHub Release publication

`.github/workflows/population-pack.yml` validates every PR touching the pack contract. After merge to `main`, an authorized user can run the workflow manually with `publish=true`.

Publication reads the release tag and asset names from the generated manifest. If the tag does not exist, the workflow creates the GitHub Release and uploads the ZIP, sidecar manifest and ZIP checksum. If the tag already exists, the workflow downloads its assets and requires byte-for-byte equality. It never replaces different bytes under an existing pack version.

A new generation therefore requires a new `pack_version` and `release_tag`; existing releases are immutable.

## Relationship to the legacy bundle

`tools/build_user_artifact_bundle.py` and `user/artifacts/NLHE_100-200/bundle.json` remain unchanged for backward compatibility. The new builder reuses their hashing conventions and the preserved range-folder source, but distribution decisions are population-scoped and no longer derive scientific identity from the unscoped legacy training registry.

# Population-scoped training state

`training/populations/registry.json` is the authoritative selector for **new** scientific work. Every training, simulation, evaluation, cache or promotion operation must name a `population_id`; stake or dataset-name inference is not an acceptable substitute.

## Migration rule

`training/registry.json` remains the immutable anchor of the closed historical 100/200 cycle. It is intentionally not rewritten during this migration. Its promoted Model A v5, independent Model B v2 and v83 strategy are represented in the population registry under:

`legacy_pokerstars_nlhe_100-200_play_6max_mixed_v1`

That identity is deliberately **MIXED_ZOOM_REGULAR**. Issue #94 proved that the historical 100/200 lineage contains both Zoom and regular-table hands, so those historical artifacts must not be relabelled as Zoom-only.

## Certified target and future populations

`pokerstars_nlhe_100-200_zoom_play_6max_v1` is the certified 23,789-hand Zoom/play-money/6-max target from issue #94. Its promoted artifact pointers are intentionally empty: the legacy mixed-population models and strategy are not inherited implicitly.

`pokerstars_nlhe_250-500_zoom_play_6max_v1` and `pokerstars_nlhe_nl5_zoom_real_eur_6max_v1` are declarative empty populations. Their platform, game, stake, money type, currency, format, table size and rake-policy status are explicit so they can be populated later without changing business logic. Declaring them does not claim that training has occurred.

## Isolation contract

Each population owns independent dataset/snapshot/increment roots, run roots and cache namespaces. Promoted roles are population-local: Model A preflop, Model A postflop, Model B, Hero strategy, engine and user pack. A consumer must reject a missing or cross-population artifact rather than falling back to a global pointer.

Historical unscoped artifacts are accepted only for the explicitly marked legacy compatibility population. New populations require population-scoped provenance.

## Invocation examples

Plan an ingested snapshot for the historical compatibility population:

```bash
python3 -m tools.training.plan_snapshot_cycle \
  --population legacy_pokerstars_nlhe_100-200_play_6max_mixed_v1
```

Generate deterministic arena scenarios for that same population:

```bash
python3 -m tools.simulation.sequential_postflop \
  --population legacy_pokerstars_nlhe_100-200_play_6max_mixed_v1 \
  --generate-only --n 4 --reps 2
```

List declared populations:

```bash
python3 -m tools.populations.registry --list
```

For an explicit candidate Model B directory, the arena additionally requires `--model-b-population`; it must equal the selected arena population.

## Promotion rule

Population declaration and candidate creation do not imply promotion. Promotion history and active artifact pointers are independent for each population. A future population may therefore be trained, evaluated and promoted without replacing the historical 100/200 state or another population's caches/runs.

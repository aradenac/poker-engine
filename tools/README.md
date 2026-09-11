# Tooling

Technical utilities used to build, migrate, inspect or validate the engine.

Suggested subdirectories:

- `patches/` — one-off migration scripts between historical versions when they remain useful for reproducibility.
- `diagnostics/` — reusable analysis scripts.
- `import/` — converters/importers for hand histories or datasets.
- `benchmarks/` — benchmark runners and report generators.

Tool outputs should normally be written to `training/runs/`, `training/evaluations/`, `.project/`, or `user/exports/` depending on their audience and persistence value.

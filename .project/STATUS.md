# Project Status

Last update: 2026-09-11

## Current baseline

- Repository initialized as persistent source of truth.
- Current application baseline outside GitHub: `poker_range_equity_offline_multiway_v78.html`.
- Prepared patch: v78 -> v79.
- v79 objective: remove demonstrated JAM bias and make recommendation selection consistently use the final comparable EV.

## Validated findings

- Artificial JAM calibration bonuses were identified as a structural source of overly aggressive recommendations.
- Very small empirical nodes can generate implausibly high EVs for raises/JAMs.
- Recommendation logic and sizing panels must use the same validity filters and the same final EV ordering.
- Existing P99.5 support guard should be preserved.

## v79 guardrails

- `very_low` node with <5 observations: hypothetical aggression cannot be recommended.
- 5-9 observations: ordinary sizing may remain eligible when supported, but JAM/overbet is not recommendable.
- For `very_low` nodes with >=5 observations, sizing outside local support is rejected.
- `sanityInvalid` sizing must remain invalid everywhere; no permissive fallback.
- Artificial JAM bonuses removed.
- Final recommendation = argmax(final comparable EV).

## Immediate next milestone

1. Persist the current executable/application files in GitHub.
2. Materialize v79 as a complete HTML/application version.
3. Run regression tests on previously pathological hands.
4. Audit ordinary sizing calibration offsets.
5. Benchmark global action/sizing frequencies.

## Known gap

The repository structure is initialized, but the historical application/training artifacts still need to be imported from the prior working files.

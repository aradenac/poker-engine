# Issue #367 — real #314 canonical KTs ISO EV

- Status: **FAIL_CLOSED_EXACT_SUPPORT_UNAVAILABLE**.
- Recommendation: **none**; the exact-support comparison set is incomplete.
- Model A: admitted sizing-aware v2 from #352, explicit identity binding.
- Active Model A pointer: unchanged.
- TEST: unconsumed / unauthorized.
- Nearest-price/interpolation: forbidden / unused.

## Exact support blocker

- Position: **CO**.
- Family: **LIMPER_VS_ISO**.
- Target: **5 BB**; to-call **4 BB**.
- Limper/caller state: **2 / 0**.
- Reason: required admitted sizing-aware v2 exact-price support missing: MAPSUP_c5df641ca5d3558356e8:family=LIMPER_VS_ISO|actor=CO|aggressor=SB|limpers=2|callers=0|target=5|call=4

The missing branch is reachable after Hero ISO 5 BB and BB folds. No EV, caller diagnostics, posterior refs, or recommendation are manufactured.

# #350 real Zoom 100/200 pack admission audit

- Population: `pokerstars_nlhe_100-200_zoom_play_6max_v1`
- Assembly: **NOT_READY**
- Preflight: **BLOCKED**
- Admission counts: `{"ADMISSIBLE": 0, "INCOMPATIBLE": 3, "REJECTED": 0, "RETAIN_REFERENCE": 2, "UNRESOLVED": 2}`
- TEST consumed: **false**
- Production effect: **NONE**

| Role | Admission | Source decision | Next evidence |
|---|---|---|---|
| model_a_preflop | INCOMPATIBLE | RETAIN_ACTIVE_REFERENCE | target-scoped Model A preflop artifact with an explicit persisted pack-admission decision; legacy v5 cannot be silently reused |
| model_a_postflop | UNRESOLVED | PROMOTE_STAGE_B_SCIENTIFICALLY | explicit persisted ADMISSIBLE_FOR_PACK decision for the #102 target-scoped selected overlay plus final compatibility binding |
| model_b | UNRESOLVED | VALIDATION_SUPPORTS_PRICE_AWARE_CANDIDATE__NO_PROMOTION | post-#314 real sensitivity and an explicit promotion/pack-admission decision; #340 NO_PROMOTION is insufficient |
| hero_strategy | RETAIN_REFERENCE | RETAIN_REFERENCE | new/final Hero strategy evidence that supersedes #108 RETAIN_REFERENCE and is explicitly admitted for the Zoom pack |
| engine | INCOMPATIBLE | UNRESOLVED_NO_PACK_ADMISSION | target-scoped engine or explicit persisted cross-population fallback authorization plus ADMISSIBLE_FOR_PACK decision |
| hero_ranges | RETAIN_REFERENCE | RETAIN_REFERENCE | final target-scoped Hero range repository with explicit pack admission; #108-retained candidate cannot be promoted |
| application_release | INCOMPATIBLE | UNRESOLVED_NO_PACK_ADMISSION | target-scoped application release binding the admitted engine with an explicit pack-admission decision |

No publication, activation, promotion, registry/pointer mutation, catalogue mutation or TEST was performed.
#201 remains open.

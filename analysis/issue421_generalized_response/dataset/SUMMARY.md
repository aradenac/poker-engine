# #421 — generalized public-only adverse-response preflop dataset

Versioned, byte-reproducible dataset of **adverse (non-Hero)** preflop
responses over the action space `FOLD/CALL/RAISE/JAM`, restricted to the
certified **TRAIN + VALIDATION** folds. `TEST` is refused by the loader (fail-closed).

## Scope

- Certified admissible hands: **23,789** (TRAIN 19,016 + VALIDATION 2,324 + TEST 2,449)
- Consumed folds: **TRAIN, VALIDATION** — certified TEST hands present but never consumed: **2,449**
- Hands parsed: **21,340** across **21,340** hand IDs (one fold per hand ID)
- Adverse preflop decisions: **114,293**
- Emitted response rows: **105,698**
- Hero decisions excluded: **21,787**
- Free-check (non-response) rows excluded: **8,595**

Every emitted row carries only public information available immediately
before the observed action; no hole card, board card, opponent hand class,
raw history or future action enters the projection.

Information boundary: `hand_id`, `split`, `table_size`, `family`,
`actor_position`, `aggressor_position`, `limper_count`, `caller_count`,
`live_positions`, `raise_level`, `to_call_bb`, `pot_before_bb`, `pot_odds`,
`price_to_pot` and `effective_stack_bb` describe the public state immediately
before the action; `action` plus `target_total_bb` / `observed_sizing_bb`
describe the observed response itself.

## Artifacts

- `GENERALIZED_RESPONSE_DATASET.jsonl` — 105,698 canonical JSON Lines rows, 41,279,660 bytes, SHA256 `4c18872fac5fc443e68e6f99feb0036509999f67f952c02e118671c7c72330a2`
- `GENERALIZED_RESPONSE_DATASET.json` — scope, contract link, corpus/loader evidence and accounting
- `CORPUS_HASHES.json` — certification and archive hashes plus per-split hand-ID fingerprints
- `contracts/training/generalized-response-dataset.schema.json` — row/manifest/corpus feature contract

## Corpus hashes

- Certification: `training/datasets/NLHE_100-200/population_certification.json` SHA256 `6b3c967b982a712ab0da3fd2bc21c242b1b08a802222f7d4b6587a0dfa2dace6`
- Population fingerprint: `4661c200fab5a24ce67a45f0801acd0238c701f55e8dbeeaf3e8299fa250119c`
- Archive `training/datasets/NLHE_100-200/source/NLHE 100-200.zip` SHA256 `6effd27d6e9f8257f3e87c68f0218b8edc72a2b487cb57da2c37ff85bc8ce4c6`
- Archive `training/datasets/NLHE_100-200/snapshots/20260912/source/RoiDePiqueNique.zip` SHA256 `374f8dedf5eeeee26b2cd049b1729f80bd2877c6f7ccef806c580019c5f94fcb`

## Per-split identity

| Split | Hands | Hand-ID fingerprint SHA256 | Response rows |
|---|---:|---|---:|
| TRAIN | 19,016 | `4b4739d11c30455085e14e040f21a1ed70068403825d38dd1cc1b3ecbf9db5a8` | 94,160 |
| VALIDATION | 2,324 | `e0980444de231d5e38d07980ffdc238a48b6261691575715a5f458a8ebcd03ba` | 11,538 |

## Reproduction

```
python3 tools/training/build_generalized_response_dataset.py
python3 tools/training/build_generalized_response_dataset.py --verify
```

The builder re-verifies certification and archive SHA256 identities, filters
to certified TRAIN/VALIDATION hand IDs before normalization, and writes
canonical JSON Lines, so a regeneration is byte-identical.

The guard suite `tests/training/test_build_generalized_response_dataset.py`
verifies the contract, the fail-closed TEST refusal and the persisted hashes;
set `POKER_GENERALIZED_RESPONSE_FULL_REGEN=1` to also re-parse the whole
certified corpus and assert byte-identical regeneration.

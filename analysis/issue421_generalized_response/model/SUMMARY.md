# #421 - generalizing adverse-response model library

Two comparable architectures trained on the public-only adverse-response
dataset, sharing one API, one legal-distribution contract and one direct
price/sizing recalculation path. Standard library only.

## Provenance

- dataset: `analysis/issue421_generalized_response/dataset/GENERALIZED_RESPONSE_DATASET.jsonl` (sha256 `4c18872fac5fc443e68e6f99feb0036509999f67f952c02e118671c7c72330a2`)
- train split: **TRAIN**, evaluation split: **VALIDATION**
- seed: **421**
- module sha256: `a224a99300ed78fadf072ad2161f6bb9b5c6310c0e84da4149d2ae149135f31f`
- contract sha256: `878ca051069342fdff07be2a1b905119ab534ba77076c272cdbe2f75e0ce5c83`

## Candidates

| architecture | rows | hands | holdout LL (bits/decision) | baseline | gain | tuned scale | canonical hash |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `regularized_multinomial_spline` | 94160 | 19016 | 1.252388 | 1.329203 | 0.076815 | 4.0 | `c3f3573f3e80b3f7889dc8b1fd6f1948daeea95effc5a41a5d707385c4eed7dc` |
| `hierarchical_empirical_bayes_dirichlet` | 94160 | 19016 | 1.269664 | 1.329203 | 0.059539 | 0.25 | `7eb7b4794d9e42bcf151f7e1cf21c337a7f2393bfaf4a1ecc6b310793d2c302f` |

## Direct evaluation on the evaluation split

- `hierarchical_empirical_bayes_dirichlet:7eb7b4794d9e`: n=11538, log loss 1.281829 bits/decision, baseline 1.335673, accuracy 0.58823, probability-sum error 0.0, illegal mass 0.0
- `regularized_multinomial_spline:c3f3573f3e80`: n=11538, log loss 1.268983 bits/decision, baseline 1.335673, accuracy 0.591697, probability-sum error 0.0, illegal mass 0.0
- best: `regularized_multinomial_spline:c3f3573f3e80`

## Guarantees exercised by the tests

- both architectures are trainable and comparable on the same dataset;
- same rows + seed + config => byte-identical candidate hash and identical predictions;
- the returned distribution is legal, sums to exactly 1.0 and masks illegal actions before
  the final normalization;
- a variation of `target_total_bb` is recomputed directly through the partition-of-unity
  sizing spline (no neighbouring-cell substitution);
- no dependency outside the Python standard library.

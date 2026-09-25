# Hierarchical exact-context Model A spec (TRAIN-only)

Issue #419. The machine-readable source of truth is
`analysis/issue419_hierarchical_tree/HIERARCHICAL_MODEL_SPEC.json`
(`poker-hierarchical-exact-context-model-spec/v1`), content-addressed in
`analysis/issue419_hierarchical_tree/model_spec/` and pinned by
`analysis/issue419_hierarchical_tree/HIERARCHICAL_MODEL_SPEC.sha256`.

Frozen digest at this revision:
`5be122e54e9ee07313a7efa0e0a6dbf4e195eceacf78287a9ac5a448964d105c`
(canonical payload `d4885e9d148e3a0246968168e246644d4dc81965383447bc74b3c8ca3c3541d4`).
Reproduce with `python3 tools/training/write_hierarchical_model_spec.py --check`.
The spec pins the generator's own file hash, so editing the generator changes the
spec digest: regenerate and update the digest above (a test enforces the match).

This document explains the spec; it is not itself normative. The JSON wins.
The spec **admits nothing**: no fit, no candidate, no promotion, no production
effect, and no change to the runtime provider.

## 1. Exact public factorization

The requested key is `hierarchical_exact_key`, the L0 granularity. It is the
byte-identical composition already used by #388/#419:

`support_context_key(context) + '|public=' + stable_hash(public_whitelist)`

Its axes are `family`, `actor_position`, `aggressor_position`, `limper_count`,
`caller_count`, `target_total_bb`, `to_call_bb`, `table_size`, `raise_level`,
`live_positions`, `all_in_positions`, `history`, `pot_before_bb` and
`effective_stack_bucket`. Lookup is exact string equality: no nearest price, no
nearest context, no rounding onto a sizing grid. Revealed hole cards are labels,
never key material.

## 2. Mutualizable axes, 3. never-mutualizable axes

Both lists are explicit and disjoint (`parameter_pooling.axes`). Every exported
axis is also in an `axis_table` row that repeats its role, so the two lists
cannot drift from the per-field truth.

Mutualizable **inside the parameters only** (`mutualizable`):
`effective_stack_bucket`, `pot_before_bb`, `history`, `live_positions`,
`all_in_positions`, `table_size`, `raise_level`, `limper_count`,
`caller_count`, `family`. These may only change the prior used for shrinkage.

Never mutualizable (`never_mutualizable`): the requested key identity itself,
the exact prices `target_total_bb` and `to_call_bb`, and the positions
`actor_position` and `aggressor_position`. A test asserts that every hierarchy
level retains all of them and drops none.

`limper_positions` and `caller_positions` are deliberately not axes at all: the
requested key counts limpers and callers, and the spec does not invent new ones.

## 4. Hierarchy, prior and shrinkage

Five nested levels, finest first: `L0_EXACT_KEY` (support and identity),
`L1_STACK_POOL`, `L2_POT_POOL`, `L3_RUNTIME_SUPPORT_CONTEXT`,
`L4_POSITION_PRICE_PRIOR`. Only L0 is allowed to be a support source.

The estimator is `hierarchical_dirichlet_shrinkage` with a weak base Dirichlet
(`alpha = 0.5` per legal marginal action) and hierarchical strength
`kappa0 = 16`, which reproduces the already pinned #352/#388
`prospective_shrinkage` rule. That rule's "same `support_context_key`
marginal" parent is the explicit level L3. The blend is
`p_hat(L_j) = (n_j * phat_j + kappa0 * p_hat(L_{j+1})) / (n_j + kappa0)`, so
the exact-level weight `w = n0 / (n0 + kappa0)` grows with support instead of
collapsing sparse cells to zero.

## 5. Rare hand classes

A hand class with fewer than 10 observations at the requested key inherits from
the hand-class marginal of **that same key** and then from that key's declared
levels. Cross-key hand-class transfer, conditioning on revealed cards, and using
reveal frequency as a feature are forbidden. Reveals describe the observed
sample; they never become inputs.

## 6. Outputs, 7. raise sizing

Outputs are a probability distribution over the legal marginal action set:
`FOLD`, `CALL`, `RAISE`, `JAM`, plus `CHECK` when the free option is legal.
Observed zero counts never prune a branch and never prove zero probability.

RAISE/JAM outputs are per exact `target_total_bb`, never one representative
size. Sizing is exact-support-only: only targets empirically present at the
exact structural node exist, and a missing node stays an explicit
`UNRESOLVED_SIZING_FRONTIER`. No legal-minimum, nearest-price, representative or
interpolated price is permitted. #388/#419 leave 7 such frontiers and the tree
is not claimed complete; the spec preserves that.

## 8. Calibration and log-loss, 9. decision thresholds

Primary metric is multiclass log loss with an epsilon clip of `1e-12`;
secondary metrics are Brier, ECE (10 bins per action class), coverage and mean
effective sample size. Every metric is stratified by `reason_code`, pooling
level and support buckets. A pooled estimate is never scored without its pooling
level. Fit and calibration evidence is TRAIN-only; VALIDATION requires a
separately frozen protocol pinned before running; TEST is never consumed.

Thresholds stay frozen at **20 marginal observations and 20 distinct hands**,
applied at the level used to report the estimate, with the exact claim reserved
for L0. The decision is the posterior argmax with a lowest-incremental-cost
tie-break; below threshold the contract abstains rather than defaulting to FOLD.

## 10. Runtime support contract

Every response carries the requested key; exact empirical
`support.observations`, `support.distinct_hands` and
`support.effective_sample_size` (credited at hand level, because several
decisions in one hand are correlated); the `pooling.level`, `pooling.source_key`
and per-level counts actually used; Dirichlet credible intervals and standard
errors reflecting the level used; `raise_sizing` targets or the unresolved
frontier; and a `reason_code`.

Reason codes:

- `EXACT_EMPIRICAL_STRONG` — L0 itself meets both thresholds; support comes from
  the requested key only and no pooling is used for the reported estimate.
- `EXACT_HIERARCHICAL_ESTIMATE` — L0 is below threshold but a declared parent
  level qualifies; the estimate is shrunk toward that parent, the pooling level
  is reported, and the support counts still belong to the requested key alone.
- `EXACT_UNRESOLVED` — no level qualifies, the branch's raise sizing is
  unresolved, or the support isolation rule would be violated. No action is
  emitted.

## Granularity decision against `RUNTIME_SUPPORT_CONTEXT_COARSE_MERGE`

The implemented likelihood key drops `history`, `pot_before_bb`,
`effective_stack_bucket`, live/all-in sets, table size and raise level. On the
38 required nodes that merges 38 fine keys into 30 coarse keys in 8 collision
groups. Declaring support at that coarse key would let one key's rows support a
different key's claim, so the spec adopts the **fine** key as the identity and
support granularity and keeps `runtime_support_context_key` as pooling level L3
only.

Consequence: the 3 nodes that currently qualify do so at L3 and can therefore
only ever be reported as `EXACT_HIERARCHICAL_ESTIMATE`; they can never be
`EXACT_EMPIRICAL_STRONG`. The canonical BB facing SB ISO@5 cell (45 observations
/ 45 hands at L3, 6 / 6 at L0) is a hierarchical estimate. The canonical CO
after SB ISO@5 / BB FOLD cell (14 / 14 at L3, 4 / 4 at L0) fails every level and
stays `EXACT_UNRESOLVED`; the 20/20 threshold is not lowered to close the tree.

Obtaining `EXACT_EMPIRICAL_STRONG` requires #367 to expose per-member fine-key
counts or to resolve at the fine key. That is recorded as a prerequisite; this
spec changes no provider.

## A key A may never be supported by a key B

Rule `SUPPORT_ISOLATION_NO_KEY_BORROWS_SUPPORT`: support quantities are computed
exclusively from rows whose `hierarchical_exact_key` equals the requested key.
Pooling may move a posterior, never a support count. The runtime invariant is
`support.source_key == requested_key`; violating it must raise
`COARSE_KEY_SUPPORT_LAUNDERING` instead of silently emitting an answer.

## Written and hashed without reading VALIDATION

`holdout_boundary` records `split_consumed=TRAIN`,
`validation_consumed=false`, `test_consumed=false`,
`validation_decisions_read=0`, `validation_hands_parsed=0` and
`spec_frozen_before_holdout_read=true`, with four machine checks:

1. every consumed evidence artifact declares TRAIN-only, enforced by a tripwire
   that aborts the build on any other declaration;
2. the generator parses no hand-history archive and no decision JSONL: the
   build runs under a filesystem tripwire that aborts on any open under
   `training/datasets/` or of a `.zip`/`.jsonl` file, and the observed open set
   is recorded in the spec as exactly the declared inputs plus the pinned #388
   bundle, with `undeclared_files_opened` empty;
3. an AST scan proves the generator uses no holdout loader symbol, imports no
   validation/holdout module and contains no holdout data path literal;
4. the #388 artifacts are byte-verified against their content addresses and the
   #419 baseline is bound by canonical payload hash before serialization.

Only certified split *cardinalities* are read as population provenance metadata;
no VALIDATION hand, decision, feature, label or metric is touched.

## Tests

`tests/training/test_hierarchical_model_spec.py` covers the ten points, the
disjoint axis lists, per-level retention of the never-mutualizable axes, the
support isolation rule, the granularity decision, the reason-code semantics, the
holdout proofs, tripwire rejection, byte-identical regeneration and the frozen
thresholds. `tests/training/test_hierarchical_tree_sparsity_parity.py` continues
to guard the #388 reproduction that the spec binds to.

## Contract and active-pointer invariance

`tools/training/audit_hierarchical_candidate_contract.py` pins the candidate
contract in
`analysis/issue419_hierarchical_tree/contract/CANDIDATE_CONTRACT.json`: the new
`candidate_id`, the mandatory hierarchical fields (estimated status, exact
empirical observations, effective sample size, pooling level/source, uncertainty,
reason codes), provider/schema parity for every frozen constant, and live
validation of provider outputs at all three statuses. The same artifact records
that `training/registry.json` still promotes the pinned
`training/models/preflop_population_model_v5.json` reference
(`ff952055...`) and that the candidate is never registered, never set active and
never replaces the exact-price v1/v2 contracts.
`tests/training/test_hierarchical_candidate_contract.py` re-derives and verifies
all of it.

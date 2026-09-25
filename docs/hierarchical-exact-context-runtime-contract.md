# Hierarchical exact-context runtime contract (normative)

Issue #419 (task `T12`). This document is the **normative** contract for what a
hierarchical exact-context answer means on every consumer surface, and for the
exact conditions that would close the #367 tree. It is normative for
*interpretation*: the machine-readable artifacts listed below stay the
authoritative source, and a disagreement between this text and an artifact is
resolved in favour of the artifact plus a correction of this text.

This contract adds no model, no fit, no candidate, no promotion, no provider
change and no production effect. It records semantics, not an admission.

## 0. Sources of truth and scope

| Artifact | Schema | Role |
| --- | --- | --- |
| `analysis/issue419_hierarchical_tree/HIERARCHICAL_MODEL_SPEC.json` | `poker-hierarchical-exact-context-model-spec/v1` | identity axes, pooling levels, thresholds, reason codes, support-isolation rule, granularity decision |
| `analysis/issue419_hierarchical_tree/contract/CANDIDATE_CONTRACT.json` + `contracts/training/model-a-preflop-sizing-hierarchical-likelihood.schema.json` | `poker-model-a-preflop-sizing-hierarchical-likelihood/v1` | candidate-only provider contract and the three reported statuses |
| `analysis/issue419_hierarchical_tree/exact_tree_preflight/EXACT_TREE_PREFLIGHT.json` | `poker-issue419-exact-tree-preflight/v1` | `required_tree_complete` and its admissibility conditions |
| `analysis/issue419_hierarchical_tree/raise_sizing_frontiers/RAISE_SIZING_FRONTIER_RESOLUTION.json` | `poker-raise-sizing-frontier-resolution/v1` | unresolved RAISE sizing frontiers |
| `analysis/issue419_hierarchical_tree/validation/VALIDATION_RESULT.json` | `poker-hierarchical-validation-result/v1` | frozen VALIDATION verdict |
| `analysis/issue419_hierarchical_tree/validation_protocol_v2/FROZEN_VALIDATION_PROTOCOL_V2.json` | `poker-hierarchical-frozen-validation-protocol/v2` | versioned revision splitting exact empirical support from exact-context estimate admissibility; references the v1 digests |
| `analysis/issue419_hierarchical_tree/terminal_decision/DECISION.json` | `poker-hierarchical-exact-tree-terminal-decision/v1` | terminal decision, blockers and admission rule |

Frozen identities used by this contract:

| Identity | Value |
| --- | --- |
| model spec byte SHA256 | `5be122e54e9ee07313a7efa0e0a6dbf4e195eceacf78287a9ac5a448964d105c` |
| model spec canonical payload | `d4885e9d148e3a0246968168e246644d4dc81965383447bc74b3c8ca3c3541d4` |
| required #388 tree | `0ab232ae44e4157e2a47d4d3d611ac8ca9c2cdb54caf2568f256f6df35643a25` |
| candidate | `model-a-preflop-sizing-hierarchical-candidate-v1` = `637302885b8119e6b0246d827462c36eb707c6e234d0b652483c956f03360999` |
| active Model A pointer (unchanged) | `training/models/preflop_population_model_v5.json` = `ff952055ca4ee051a3ac9607d513fdecac0a320a31f658ecfd8a11d8448975ca` |

The consumers of this contract are the runtime provider response, the Model A
posterior adapter ([docs/model-a-posterior-runtime.md](model-a-posterior-runtime.md))
and the Reviewer/Replayer analysis surfaces described by the product need
([docs/reviewer-preflop-iso-analysis.md](reviewer-preflop-iso-analysis.md)). The
evidence bundle is
[analysis/issue419_hierarchical_tree/SUMMARY.md](../analysis/issue419_hierarchical_tree/SUMMARY.md).

The alignment between this document and the artifacts above is re-derived by
`tests/training/test_hierarchical_exact_context_contract_doc.py`; editing the
text without editing the artifacts (or the reverse) fails that guard.

## 1. Normative meaning of the three statuses

Every hierarchical exact-context response carries exactly one `reason_code`,
from a closed enum of three values. There is no fourth status and no implicit
default: an answer that cannot be one of the three is `EXACT_UNRESOLVED`, never
a silent downgrade to FOLD, to a zero vector, or to another key's support.

| `reason_code` | Normative condition | What it permits | What it forbids |
| --- | --- | --- | --- |
| `EXACT_EMPIRICAL_STRONG` | the requested fine key `hierarchical_exact_key` (`L0_EXACT_KEY`) itself meets **both** frozen thresholds — at least 20 marginal observations **and** at least 20 distinct hands — and the reported estimate uses `pooling.level == L0_EXACT_KEY` | an exact empirical support claim for this exact context | emitting it when the reported estimate consumed any parent level `L1..L4`; borrowing support from a coarse key |
| `EXACT_HIERARCHICAL_ESTIMATE` | the requested fine key is **below** threshold but a declared parent level meets both thresholds; `pooling.level` and `pooling.source_key` are reported | an estimate for the exact requested context whose parameters were shrunk toward that declared parent | calling it exact support; counting it as a closed tree node; omitting the pooling provenance; attributing the parent's counts to the requested key |
| `EXACT_UNRESOLVED` | no level meets both thresholds, **or** the raise sizing of the branch is unresolved, **or** the requested key would violate the support-isolation rule | nothing: no action, no probability vector and no raise target is emitted | replacing the abstention with FOLD, with zero probability mass, with a pruned branch, or with a nearest/representative price |

Thresholds are frozen at **20 marginal observations and 20 distinct hands**,
applied at the level used to report the estimate. The exact claim itself is
reserved to `L0_EXACT_KEY`. The thresholds are never lowered, and the
`EXACT_UNRESOLVED` case is always reported with its blocker as `reason_detail`
(`NO_ADMISSIBLE_POOLING_LEVEL` or `RAISE_SIZING_UNRESOLVED_NO_NEAREST_PRICE`).

Three derived rules follow and are normative:

1. **The status describes the reported estimate, not the identity.** A shrunk
   estimate is still an estimate for the requested exact context; it is not an
   exact-support claim for that context.
2. **The status never propagates upward.** A parent level's support never makes
   a child node exact, and one exact node never certifies its neighbours.
3. **The posterior never changes a support count.** Pooling may move a prior or
   a posterior; the observations, distinct hands and effective sample size
   reported for the requested key stay exactly what that key contains.

### 1.1 Explicitly versioned protocol revision v2 (two layers, no threshold moved)

The single frozen protocol is split into two explicitly named layers by a
separately versioned, content-addressed revision:

`analysis/issue419_hierarchical_tree/validation_protocol_v2/FROZEN_VALIDATION_PROTOCOL_V2.json`
(`poker-hierarchical-frozen-validation-protocol/v2`, byte digest
`508a31ec8072a72ca573f65ac6b748e1ce5e67c639fd4388e472153b7ffa4320`, canonical
payload `a97391d2678d66a46cc7a8d2d0893a509c9c2564a5c420f4519d21c05216dd16`),
written by `tools/training/write_frozen_validation_protocol_v2.py`. It revises
`poker-hierarchical-frozen-validation-protocol/v1`
(`69c99a8b37589f1687b7e980344c9a79d69bbcd45be0a53ffd59bfea0ab583b3`, canonical
`f283ce8dac9fbcfb5485eeb360217af4425fe947f249de652b03d96a13d40db5`) additively:
the v1 bytes are byte-identical, v1 stays the source of record for every
threshold, gate and comparator, and the revision admits nothing. Because the v1
payload pins the digest of the v1 generator, the revision has its own generator
— editing the v1 tool would break the pre-registration.

* **Layer A, exact empirical support** (`EXACT_EMPIRICAL_SUPPORT`). The
  `EXACT_EMPIRICAL_STRONG` label is unchanged, is claimed only at
  `L0_EXACT_KEY`, requires both frozen thresholds (20 marginal observations and
  20 distinct hands), and never borrows support.
* **Layer B, exact-context estimate admissibility**
  (`EXACT_CONTEXT_ESTIMATE_ADMISSIBILITY`). `EXACT_HIERARCHICAL_ESTIMATE`
  answers for the same exact requested key with its identity preserved, its own
  support counts (possibly zero), strictly parametric pooling over `L1..L4`, and
  mandatory effective sample size, uncertainty at the level actually used and
  pooling provenance, gated on calibration, pooling and sizing.

The rule for consuming a node's answer is
`CONSUME_ONLY_AN_ADMISSIBLE_NODE_ANSWER`:

| Node answer | Consumable | As |
| --- | --- | --- |
| `EXACT_EMPIRICAL_STRONG` | yes | exact empirical support (pooling level must be `L0_EXACT_KEY`) |
| `EXACT_HIERARCHICAL_ESTIMATE` | yes | an estimate with its declared pooling level, never as exact support |
| `EXACT_UNRESOLVED` | no | nothing; the blocker is reported and never repaired |

A node answering `EXACT_HIERARCHICAL_ESTIMATE` is consumable as an estimate but
does not close the node: `required_tree_complete` still requires an admissible
exact answer at `L0_EXACT_KEY` for every required node. The #367 rule is
unchanged by the revision (`ISSUE367_CONSUMES_ONLY_AN_ADMITTED_CANDIDATE`), and
no single admissible node authorizes a #367 consumption.

## 2. Strict identity / pooling separation

The identity and support granularity is the fine key `hierarchical_exact_key`
(`L0_EXACT_KEY`). It is the byte-identical composition already used by #388 and
#419: `support_context_key(context) + '|public=' + stable_hash(public_whitelist)`.
Lookup is exact string equality — no nearest price, no nearest context, no
rounding onto a sizing grid, and revealed hole cards are labels, never key
material.

Pooling is a **parameter-only** mechanism over five nested levels, finest
first: `L0_EXACT_KEY` (support and identity), `L1_STACK_POOL`, `L2_POT_POOL`,
`L3_RUNTIME_SUPPORT_CONTEXT`, `L4_POSITION_PRICE_PRIOR`. Only `L0` may be a
support source; `L1..L4` may only supply a parent prior in the Dirichlet
shrinkage (`kappa0 = 16`, `alpha = 0.5` per legal marginal action).

The axes are split explicitly and disjointly:

- **never mutualizable, retained at every level**: the requested key identity
  itself (`requested_key_identity`) and the exact prices `target_total_bb`,
  `to_call_bb`, plus the positions `actor_position` and `aggressor_position`;
- **mutualizable inside the parameters only**: `effective_stack_bucket`,
  `pot_before_bb`, `history`, `live_positions`, `all_in_positions`,
  `table_size`, `raise_level`, `limper_count`, `caller_count`, `family`.

`SUPPORT_ISOLATION_NO_KEY_BORROWS_SUPPORT` is the normative invariant:

> A key A may never be declared supported by observations of a different key B.
> Support quantities (observations, distinct hands, effective sample size) are
> computed exclusively from rows whose `hierarchical_exact_key` equals A.

At runtime the invariant is `support.source_key == requested_key`. A response
whose support source differs from the requested key MUST raise
`COARSE_KEY_SUPPORT_LAUNDERING` instead of emitting an answer; the response is
never silently re-labelled as an exact claim. A coarse provider key may seed a
prior; it may never certify support for a finer requested key. A finer key never
borrows observations from its siblings, and zero observations of key A stay zero
even when a parent level is dense.

## 3. `RUNTIME_SUPPORT_CONTEXT_COARSE_MERGE`: contained, not resolved

The implemented provider likelihood key omits `history`, `pot_before_bb`,
`effective_stack_bucket`, the live/all-in sets, `table_size` and `raise_level`.
At this revision that merges the 38 fine keys of the required tree into 30
coarse `runtime_support_context_key` values across **8 collision groups**, so
one fitted node is reusable across public states that the fine key keeps
distinct. At this revision 3 of the 38 required nodes qualify at the coarse
`L3` key and 0 qualify at the audit-exact `L0` key.

The disposition is explicit and recorded in the spec's granularity decision
`EXACT_KEY_IDENTITY_IS_FINER_THAN_RUNTIME_PROVIDER_KEY`, with status
`OPEN_FOR_367_SPEC_DOES_NOT_CHANGE_PROVIDER`. The risk is **contained** — the
fine key stays the identity and support granularity, and
`runtime_support_context_key` is used as pooling level `L3` only — but it is
**not resolved**, and it is never resolved by renaming: the coarse key is not
silently promoted to an identity.

Normative consequences:

- A node whose only qualifying support is at `L3_RUNTIME_SUPPORT_CONTEXT` can
  only ever report `EXACT_HIERARCHICAL_ESTIMATE`; it can never be
  `EXACT_EMPIRICAL_STRONG`.
- The canonical BB facing SB `ISO@5` cell (45 observations / 45 distinct hands
  at `L3`, 6 / 6 at `L0`) is a hierarchical estimate, not an exact-support
  claim. The canonical CO after SB `ISO@5` / BB `FOLD` cell (14 / 14 at `L3`,
  4 / 4 at `L0`) fails every level and stays `EXACT_UNRESOLVED`.
- Declaring support at the coarse key, relabelling the coarse result "exact",
  lowering the 20/20 thresholds so the tree closes, and filling a frontier with
  a representative price are all rejected; each is recorded as a rejected
  option in the spec.

The risk closes only under the spec's prerequisite for exact claims:
`#367 must expose per-member (fine-key) counts, or resolve at the fine key,
before any node may be reported EXACT_EMPIRICAL_STRONG`. Until then every
response carries its requested key, its exact support counts and the pooling
level actually used, and the risk stays open.

## 4. Precise conditions of closing the #367 tree

Closing the required tree is a **conjunction**: one fail-closed node keeps the
tree open. The normative rule is the T8 preflight, whose
`required_tree_complete` is true only when every condition holds:

| Condition | Rule | State at this revision |
| --- | --- | --- |
| `every_required_node_has_an_admissible_exact_answer` | each of the 38 required nodes resolves `EXACT_EMPIRICAL_STRONG` at `L0_EXACT_KEY` with both the 20-observation and the 20-distinct-hands thresholds met | **not satisfied** — 0 of 38 admissible |
| `no_unresolved_raise_sizing_frontier` | no RAISE frontier stays without an exactly supported target | **not satisfied** — 7 unresolved frontiers |
| `required_tree_fully_enumerated` | the #388 enumeration is complete, not only its node list | **not satisfied** |
| `no_nearest_or_borrowed_substitution_applied` | no nearest-price, nearest-context, representative, interpolated, legal-minimum or borrowed-support substitution | satisfied |
| `no_hero_ev_or_recommendation_computed` | the #367 real ISO EV runner is neither imported nor executed | satisfied |

Beyond the preflight, a #367 consumption of the candidate is governed by
`ISSUE367_CONSUMES_ONLY_AN_ADMITTED_CANDIDATE`. It becomes **authorized** only
when all of the following hold:

1. `required_tree_complete = true` from the exact-tree preflight;
2. the frozen VALIDATION evaluation returns `ADMIT_CANDIDATE` with **every**
   frozen gate passing — the coverage floor, the paired non-inferiority bounds
   and the absolute/relative calibration gates;
3. the VALIDATION result is content-addressed
   (`poker-hierarchical-validation-result/v1` with its embedded
   `protocol_byte_sha256`) and pinned in a new explicit #367 protocol revision;
4. that #367 protocol revision names
   `model_a.candidate_id = model-a-preflop-sizing-hierarchical-candidate-v1`
   and its canonical payload digest.

Until then the consequence is fixed: no #367 real ISO EV run, no exact-support
grid extension and no provider wiring may consume this candidate, and #367 keeps
`model-a-preflop-sizing-aware-candidate-v2` as its admitted model.

The following are forbidden substitutes for a real closure. They MUST NOT be
used to make `required_tree_complete` true:

- lowering, reinterpreting or re-freezing a threshold, a pooling limit or a
  comparator after a holdout read;
- declaring support at the coarse `runtime_support_context_key`;
- filling a raise-sizing frontier with a representative, nearest, interpolated
  or legal-minimum price;
- pruning an unresolved branch as zero mass, or answering an
  `EXACT_UNRESOLVED` node with FOLD;
- borrowing another key's support, or forcing an admission.

## 5. Terminal state at this revision

The T8 preflight records `required_tree_complete = false`: 0 of 38 nodes are
admissible and all 38 stay `EXACT_UNRESOLVED` (31
`NO_ADMISSIBLE_POOLING_LEVEL`, 7
`RAISE_SIZING_UNRESOLVED_NO_NEAREST_PRICE`). The T9/T10 raise-sizing work leaves
7 of 7 frontiers unresolved. The T7 frozen VALIDATION verdict is
`RETAIN_ACTIVE_REFERENCE`, failing the frozen `coverage_floor` and
`calibration_absolute` gates.

The terminal decision is `UNRESOLVED_HIERARCHICAL_TREE_GAP` with status
`BLOCKED_SCIENTIFIC`, `admitted = false`, `issue367_authorized = false`,
`hero_ev_executed = false` and `active_pointer_mutated = false`; `next_issue` is
`367`. A valid terminal outcome of #419 may be "no admission": admission is
never forced, and #419 never runs #367.

## 6. Consumer obligations

**Runtime provider and Model A posterior adapter**
([docs/model-a-posterior-runtime.md](model-a-posterior-runtime.md)). The adapter
keeps emitting `poker-opponent-posterior-range/v1` records. It MUST NOT upgrade
an `L1..L4`-shrunk parameter estimate into exact support, MUST NOT display a
coarse key's counts on a finer requested context, and MUST fail closed
(`UNSUPPORTED`, `degenerate` display) rather than silently substitute a default
range when the exact context is unresolved. `EXACT_UNRESOLVED` from the
hierarchical contract is a fail-closed state, not an empty-but-available range.

**Reviewer / Replayer analysis surfaces**
([docs/reviewer-preflop-iso-analysis.md](reviewer-preflop-iso-analysis.md)).
Per-context support and the pooling level actually used MUST be visible wherever
an estimate is shown, so a player can tell an exact empirical claim from a
shrunk estimate. No EV and no Hero recommendation may be exposed on an
`EXACT_UNRESOLVED` node, and an unresolved context MUST NOT be rendered as a
169-cell grid held at `100 %`.

**#367.** Consumes nothing from this candidate until the tree closes and the
frozen VALIDATION evaluation admits it under a new explicit #367 protocol
revision. The current admitted model for #367 stays
`model-a-preflop-sizing-aware-candidate-v2`.

## 7. Guards and reproduction

| Guard | What it pins |
| --- | --- |
| `tests/training/test_hierarchical_model_spec.py` | the frozen spec, the disjoint axis lists, the granularity decision and the reason-code semantics |
| `tests/training/test_hierarchical_candidate_contract.py` | the candidate contract and live provider outputs at all three statuses |
| `tests/training/test_hierarchical_train_fit.py` | the TRAIN-only fit |
| `tests/simulation/test_issue419_exact_tree_preflight.py` | `required_tree_complete`, the refused substitutions and the absence of Hero EV |
| `tests/training/test_hierarchical_terminal_decision.py` | the terminal decision, the blockers and the untouched frozen inputs |
| `tests/training/test_hierarchical_exact_context_contract_doc.py` | this normative document, re-derived against the artifacts above |
| `tests/training/test_frozen_validation_protocol_v2.py` | the versioned v2 revision, the two layers and the immutability of every frozen v1 surface |

Reproduce the artifacts with
`python3 tools/training/write_hierarchical_model_spec.py`,
`python3 tools/training/fit_model_a_preflop_sizing_hierarchical.py`,
`python3 tools/simulation/issue419_exact_tree_preflight.py`,
`python3 tools/training/resolve_raise_sizing_frontiers.py` and
`python3 tools/training/finalize_hierarchical_exact_tree_decision.py`, and the
protocol revision with
`python3 tools/training/write_frozen_validation_protocol_v2.py`; each supports
`--check`.

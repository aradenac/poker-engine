# Opponent range display contract

This document fixes the vocabulary and normalizations used by any surface that
renders an opponent range. It is a **representation contract only**: it does not
fit Model A, tune Model B, select a candidate, or change any equity computation.
It is the display-side companion to the runtime backend contract owned by
`src/ranges/posterior_range.py` and `contracts/posterior-range.schema.json`.

The desktop shell the replayer/matrix surfaces are mounted in (`100dvh` / no
global scroll, the mode → view → sub-view mapping, the allowed overflow zones
and the navigation / deep-link contract) is owned by
`docs/ux-desktop-view-shell.md`; it never changes the range semantics defined
below.

The versioned identifier is

    poker-opponent-range-display/v1

and the exported constant is

    OPPONENT_RANGE_DISPLAY_CONTRACT        (site/index.html, also on window)

The canonical names below are the identifiers that a consumer may rely on. UI
labels are French because the static application is French-facing.

## 1. The four notions

The four notions are distinct and must never be conflated, relabelled, or
rendered with the same unit.

| # | Notion (canonical) | UI label | Unit | Normalization | Backend key |
|---|---|---|---|---|---|
| a | `posterior_combo_probability` | « masse probabiliste », « probabilité » | probability `p` in `[0,1]`, displayed as `%` | **sum-normalized**: the mass over the legal exact combos sums to `1` | `exact_combo_weights[].weight`, `probability_mass`, `normalization.output_mass` |
| b | `relative_weight` | « poids relatif » (grille matrice et exports) | dimensionless ratio, `max = 1`; the strongest legal weight is the top of the diagnostic heat scale | **max-normalized**: the largest legal weight becomes `1`; the values do **not** sum to `1` | display-only; backend does not emit it |
| c | `inclusion_frequency` | « fréquence d'inclusion » / « Position dans la range source » | percent, integer/real in `[0,100]`, per hand class | **a priori input**: not normalized to `1` and not conditioned on observed actions | imported range `positions[].hands[].frequency` |
| d | `non_informative_prior` | « prior non informatif » | probability per legal exact combo | **uniform**: every legal exact combo after PUBLIC blockers gets the same probability `1/N` | `UNCONDITIONED_COMBO_PRIOR` (see `docs/model-a-posterior-runtime.md`), projected as normalized combo probability |

### (a) Posterior combo probability — `posterior_combo_probability`

The authoritative distribution. It is defined over **exact combos**, not over
hand classes. After PUBLIC blocker filtering and normalization, the probability
of each retained exact combo is its non-negative weight divided by the retained
mass, so the sum over all retained combos equals `1`.

- Unit: probability, `[0,1]`; UI rendering uses `%` but the value is a true
  probability and the mass sums to `100 %`.
- Backend: `src/ranges/posterior_range.py::project_exact_combo_weights` stores it
  in `exact_combo_weights` and asserts `probability_mass == 1` for `AVAILABLE`.
- Frontend: `aiExportRangeSnapshot` writes per-combo `probability_pct` with
  `p = weight / total`, and the 169 class projection as `grid_169_probability_pct`
  (see §2).

### (b) Relative weight / diagnostic likelihood — `relative_weight`

A **diagnostic** quantity used for the matrix heat map and visual comparison. It
is obtained by dividing every legal exact-combo weight by the maximum weight, so
the strongest legal weight is `1` and everything else is a ratio in `[0,1]`. It
is a likelihood-like score, **never a probability**:

- it does not sum to `1`;
- it must never be labelled `%` as if it were a probability;
- its strongest value is shown at the top of the diagnostic heat scale, and the
  scale is always labelled as a diagnostic ratio rather than a probability.

The conditioned exact-combo engine `exactComboRangeResult` in `site/index.html`
computes this diagnostic per combo in the dedicated `entries[].relativeWeightPct`
field (the same definition is carried by the helper
`normalizeComboWeightsInPlace`); `grid_169_relative_weight_pct` and the matrix
diagnostic consume only that field. The canonical, sum-normalized mass of notion
(a) lives in the sibling `entries[].frequency` field and is never stored in
`relativeWeightPct`. The replayer range modal does **not** use the diagnostic: it
renders the canonical mass projection of §2 (grid, combo list and delta) so every
legend describes the same probability value. In the backend contract there is no
equivalent field, because the backend only serializes normalized probabilities.

The diagnostic is defined only for a **conditioned** posterior whose legal
weights are not uniform. For every non-conditioned state — the non-informative
prior `prior_uninformative`, an unconditioned imported/source prior
`source_prior_unconditioned` (non-uniform, or uniform over a strict subset of the
legal combos), and the degenerate posterior — it is undefined rather than
informative: `aiExportRangeSnapshot` exports each exact combo's
`relative_weight_pct` as `null`, exports `grid_169_relative_weight_pct` as `null`
(or empty), and retains its canonical `probability_pct` /
`grid_169_probability_pct`. This prevents max normalization from representing
every uniform-prior combo or hand class as 100 %: the diagnostic is never derived
from the canonical mass.

The matrix and the replayer modal render both unconditioned priors textually (no
numeric 169 grid and no heat grid), so an a priori source range can never read as
a conditioned posterior nor surface a `100 %` diagnostic. Only the conditioned
state carries the per-combo `relativeWeightPct` and the derived
`grid_169_relative_weight_pct`.

### (c) Inclusion frequency of a range — `inclusion_frequency`

The a priori value attached to each hand class of an imported/source range
(« range source importée »). It answers “how often does this hand class belong to
the range before any action is observed”, on a `0–100` percent scale.

- Unit: percent `[0,100]`, per **hand class** (169 scale).
- It is an input, not an output: it is not normalized to a probability and it is
  not conditioned on observed actions.
- It is expanded to exact combos by `exactComboPriorFromEntries`, which assigns
  each legal combo of the class the weight `frequency / 100`. That weight is a
  pseudo-count / inclusion weight, not a probability; normalization happens later.
- Vocabulary hazard: the numeric field `entries[].frequency` is reused by the
  conditioned exact-combo engine in `exactComboRangeResult`, where it carries the
  **sum-normalized probability mass** semantics of notion (a) (`100 * weight /
  total`, summing to `100` over the legal combos), **not** the a priori inclusion
  semantics of (c). The max-normalized `relative_weight` diagnostic of notion (b)
  travels separately in `entries[].relativeWeightPct` (absent/`null` for a uniform
  prior). The contract distinguishes the producers by *notion*: an imported/source
  range supplies (c) in `frequency`; the estimated/conditioned engine supplies (a)
  in `frequency` and (b) in `relativeWeightPct`. No consumer may infer inclusion
  frequency from a conditioned estimate, nor read `relativeWeightPct` as a
  probability.

### (d) Non-informative prior — `non_informative_prior`

The explicit “no information” starting point: a uniform distribution over all
legal exact combos after PUBLIC blockers, each with the same weight
(`uniformExactComboPrior`). It is a probability distribution (notion (a)
normalization applies), distinct from:

- an imported range (c), which is a priori but generally non-uniform;
- a conditioned posterior, which has consumed at least one public action.

The trigger is **full support**: the kept prior is the non-informative prior only
when its positive weights are uniform **and** its support covers every exact combo
that is legal after the PUBLIC hero/board blockers (`priorIsNonInformative`). A
uniform distribution over a strict subset of the legal combos — a single hand
class, an imported sub-range, or a support reduced by public blockers — is a
genuine a priori source range, not the non-informative prior.

The Model A adapter labels its unconditioned prior `UNCONDITIONED_COMBO_PRIOR`
with `source_observations: 0` and projects it as normalized combo probability.
It must never be displayed as “all 169 classes at 100 %”; `100 %` is reserved
for `relative_weight` (b) and would be wrong for a prior or a posterior.

### (e) Known-hand override — `knownHandOverride`

A separate mechanism, **not** a fifth range notion: when `useKnownHand` is active
for an opponent whose exact cards are revealed in the hand history,
`effectiveEntriesForOpponent` / `exactEntriesFromCards` return a single entry
tagged with the additive flag

    {hand, frequency:100, exact:true, knownHandOverride:true}

Consequences:

- it is the **only** legitimate representation in which a single hand class may
  be displayed at `100 %`; a posterior or a non-informative prior never is;
- it must **never** be merged with the posterior mass projection of
  `populationRangeEstimateForPlayer` / `posterior_range.py`: display surfaces
  (opponent row, range modal) render it as its own banner, distinct from the
  posterior grid;
- the flag is metadata only. `useKnownHand` is unchanged and every equity
  consumer (`legalCombosForOpponent`, `exactComboPriorFromEntries`,
  `buildSeatEquityPlayers`, `postflopRaiseTreeSnapshot`) keeps reading the same
  `hand`/`frequency` pair at the same scale.

## 2. The 169 projection is a mass sum

The canonical projection from exact combos to the 169 hand classes is the
**sum of the combo probabilities** belonging to each class:

    projection_169.classes[hand_class] = Σ posterior_combo_probability(combo)
                                          for combo in legal_combos(hand_class)

Consequences that the contract enforces:

- it is **not** a mean over the combos of the class;
- it is **not** a max over the combos of the class;
- because the per-combo probabilities sum to `1`, the 169 class masses also sum
  to `1`;
- a class value is a **mass**, not a per-combo density. Two classes with the same
  mass but different `legal_combo_multiplicity` do not have the same probability
  per combo. `full_combo_multiplicity` (1326) and `legal_combo_multiplicity`
  (post-blocker) are carried alongside `classes` precisely so the projection is
  never silently read as uniform over combos.

This matches:

- `src/ranges/posterior_range.py`, where the projector accumulates
  `classes[combo_class_ids(*combo)] += weight` over normalized exact combos and
  asserts the output mass is `1`;
- `contracts/posterior-range.schema.json`, whose `projection_169.classes`
  enumerates exactly the 169 classes with values in `[0,1]`;
- `site/index.html::aiExportRangeSnapshot`, where `grid_169_probability_pct` is
  built as `classMass[cls] += p` with `p = weight / total`.

The separate 169 **relative-weight heat grid** (notion (b)) aggregates the
max-normalized combo weights per class by mean so that classes with different
combo counts stay visually comparable. That diagnostic aggregation is *not* the
posterior projection: it is exported only under the explicit relative-weight
field `grid_169_relative_weight_pct` (and per combo `relative_weight_pct`) and
must never be exported, cited, or labelled as a probability. Only the mass sum
above is the probability projection. The relative-weight heat grid is defined
only for a **conditioned** posterior with non-uniform weights; for
`prior_uninformative` and `source_prior_unconditioned` it is `null`/empty and the
canonical mass sum above remains the only exported 169 grid.

### 2.1 Replayer surfaces

The reference UI is the Replayer range modal and its exports in
`site/index.html`; each contract element maps to a concrete surface:

| Contract element | Replayer surface |
|---|---|
| (a) `posterior_combo_probability` | grid, combo list and delta of `openPopulationRangeModal`, fed by `massGridFreqMapFromEstimate` → `estimate.gridEntries` = `projectCombosTo169Mass`; export `grid_169_probability_pct` and `exact_combos[].probability_pct` |
| (b) `relative_weight` | diagnostic matrix heat grid and export `grid_169_relative_weight_pct` / `relative_weight_pct`; never the modal grid, defined only for a `conditioned` posterior and `null` for every non-conditioned state (`prior_uninformative`, `source_prior_unconditioned`, `degenerate`) |
| (c) `inclusion_frequency` | imported range editor and « Position dans la range source »; expanded to combos by `exactComboPriorFromEntries` |
| (d) `non_informative_prior` | explicit « Prior non informatif · range non estimée » state; `gridFreqMapFromEstimate` returns an empty map so no numeric grid is drawn |
| `source_prior_unconditioned` | explicit « Prior source non conditionné · range importée non conditionnée » state; imported/source prior that is not the full-support uniform prior (non-uniform weights, or uniform over a strict subset) kept with zero matched public action; empty map so no numeric grid and never a `100 %` range |
| `conditioned` | the numeric 169 mass grid and the estimated-range title |
| `degenerate` | explicit « Posterior dégénéré · masse nulle après blockers publics » state; empty map and a fail-closed `aiExportRangeSnapshot` (`posterior_state:"degenerate"`) |
| known-hand override | separate `data-known-hand-override="true"` banner, never merged into the grid |

The Python string-contracts `tests/trainer/test_prior_posterior_ui_contract.py`
and `tests/trainer/test_range_vocabulary_contract.py` pin these surfaces; the
mass-sum projection also feeds `aiExportRangeSnapshot` as described in §2.

## 3. `posteriorState`

Every rendered opponent distribution carries exactly one `posteriorState`. The
state is derived from the representation layer only (blocker filtering,
normalization, support), never from the model fit.

| `posteriorState` | Meaning | Mass | UI behaviour |
|---|---|---|---|
| `prior_uninformative` | No public conditioning action has been applied **and the kept prior is the full-support uniform prior over the legal exact combos** (uniform weights and a support covering every exact combo still legal after the PUBLIC hero/board blockers), or the engine is explicitly rendering the uniform/non-informative prior. | prior (unnormalized as a likelihood; normalized only when projected) | explicit state « prior non informatif · range non estimée »; no numeric 169 grid, never a 100 % range, and the diagnostic `grid_169_relative_weight_pct` is `null`/empty rather than the canonical mass |
| `source_prior_unconditioned` | No public conditioning action matched **and the kept imported/source prior is not the full-support uniform prior** (non-uniform weights, or uniform over a strict subset such as a single class or a support reduced by public blockers), so it is a real (a priori) distribution but not a conditioned posterior. | prior (unnormalized as a likelihood; normalized only when projected) | explicit state « Prior source non conditionné · range importée non conditionnée »; no numeric 169 grid (the matrix keeps the state textual rather than deriving a grid from the mass), never a 100 % range, never assimilated to the `conditioned` posterior, and its diagnostic `relativeWeightPct` / `grid_169_relative_weight_pct` is `null`/empty |
| `conditioned` | At least one public conditioning action matched, retained positive mass exists, and the output mass normalizes to `1`. | `1` | full posterior display; the **only** state whose max-normalized relative diagnostic (`entries[].relativeWeightPct`, `grid_169_relative_weight_pct`) is defined, and only when its legal weights are non-uniform |
| `degenerate` | No positive support survives, all positive mass was blocked, or the record is invalid. | `0` | fail-closed; no combos, no positive 169 mass, explicit reason |

### Triggers

`prior_uninformative`

- the target has no voluntary public action at the replay step
  (`playerActions.length === 0`) **and** the kept prior is the full-support
  uniform prior over the legal exact combos: `priorIsNonInformative` is true, i.e.
  `comboWeightsAreUniform` is true **and** the support covers every exact combo
  still legal after the PUBLIC hero/board blockers;
- the first observed action matched no usable population node, so no conditioning
  was applied, and the kept prior is that full-support uniform prior;
- an explicit `uniformExactComboPrior` / `UNCONDITIONED_COMBO_PRIOR` is being
  rendered (`source_observations = 0` in the backend runtime);
- its diagnostic relative weight is undefined: `relativeWeightPct` and
  `grid_169_relative_weight_pct` are `null`/empty instead of a max-normalized
  all-`100 %` grid, and the canonical mass is never substituted for them.

`source_prior_unconditioned`

- the target has no matched public action at the replay step
  (`informativeActions === 0`) **and** the kept imported/source prior is not the
  full-support uniform prior (`priorIsNonInformative` is false): either its
  weights are non-uniform (`comboWeightsAreUniform` is false) or they are uniform
  over a strict subset of the legal combos (a single class, an imported
  sub-range, or a support reduced by public blockers). It is a genuine a priori
  distribution, but the representation never conditions it and never assimilates
  it to the conditioned posterior nor to the uniform non-informative prior;
- it is rendered as an explicit state with its own label, no numeric 169 mass
  grid and no derived diagnostic relative grid, so it can never read as a 100 %
  range;
- its diagnostic relative weight is undefined: `relativeWeightPct` and
  `grid_169_relative_weight_pct` are `null`/empty, and the canonical mass is
  never substituted for them.

`conditioned`

- at least one public action matched (`matchedActions > 0`);
- normalization succeeds with strictly positive retained mass;
- backend: `status = AVAILABLE`, `probability_mass = 1`, positive
  `exact_combo_support`, `AVAILABLE` requires a recomputed matching projection;
- it is the **only** state whose max-normalized relative diagnostic is defined
  (`relativeWeightPct`, `grid_169_relative_weight_pct`), and only when its legal
  weights are non-uniform; the two unconditioned priors expose `null`/empty.

`degenerate`

- retained public mass is zero or below the contract tolerance
  (`project_exact_combo_weights` raises `UnsupportedPosteriorRange` when the
  blockers/support remove all positive mass, when there are no exact combos, or
  when there is no positive support);
- the record fails validation and is serialized fail-closed as `UNSUPPORTED` or
  `INVALID` with `probability_mass = 0`, no `exact_combo_weights`, an all-zero
  169 projection, and a non-empty `reason`;
- frontend equivalent: a normalization attempt returns no positive maximum
  (`maxWeight <= 0`) or blocker filtering empties the support.

A concentrated but valid posterior is **not** `degenerate`; low
`support.effective_support` is reported separately and does not by itself change
the state.

## 4. Alignment with the backend contract

`src/ranges/posterior_range.py` and `contracts/posterior-range.schema.json`
remain the semantic reference; this display contract aligns to them and does not
rewrite them:

- schema identifier `poker-opponent-posterior-range/v1`;
- `status ∈ {AVAILABLE, UNSUPPORTED, INVALID}` maps to
  `conditioned` / `degenerate`;
- `exact_combo_weights[].weight` is the sum-normalized
  `posterior_combo_probability` (a);
- `projection_169.classes` is the mass sum of §2, with
  `full_combo_multiplicity` / `legal_combo_multiplicity` metadata;
- `normalization.{input_mass,blocked_mass,retained_mass,output_mass,tolerance}`
  carries the PUBLIC-blocker bookkeeping;
- `support.{source_observations,exact_combo_support,effective_support,entropy_nats,backoff}`
  carries support diagnostics (`effective_support`/`entropy_nats` are not
  probabilities and are not the relative weight of (b));
- only `knowledge_scope = PUBLIC` blockers are legal; unrevealed opponent cards,
  future board cards, and any future/private information are forbidden
  (`test_prior_posterior_ui_contract.py` keeps the UI verdict prior-only);
- `moment ∈ {BEFORE_ACTION, AFTER_ACTION}` fixes which public action may condition
  the posterior; `BEFORE_ACTION` keeps `public_action = null`.

The backend has no notion (b) `relative_weight` and no notion (c)
`inclusion_frequency` field; those are display/input notions. The backend has no
`posteriorState` field, but `status` plus
`support.source_observations`/`exact_combo_support` determine it as in §3.

## 5. Postflop extension (no backend contract)

`populationRangeEstimateForPlayer` in `site/index.html` extends the same
representation to flop/turn/river by conditioning exact combos on postflop
population response models (`calibratedPostflopObservedProbabilities`,
`postflopTargetFrequencies`) and by filtering public board/hero blockers at the
current replay step.

This postflop path is an explicit **browser-only extension**: there is no
`posterior_range.py` equivalent and no JSON schema for postflop records. It must
therefore:

- obey the same four notions and the same mass-sum 169 projection as preflop;
- obey the same `posteriorState` triggers: the state is computed from the number
  of exploited public actions (`informativeActions = preMatched + postMatched`)
  and from whether the kept prior is the full-support uniform prior
  (`priorIsNonInformative`), so at least one exploited action is `conditioned`,
  zero actions over a full-support uniform prior is `prior_uninformative`, and
  zero actions over any other imported/source prior (non-uniform, or uniform over
  a strict subset) is the distinct `source_prior_unconditioned`;
- fail closed on zero surviving mass: a normalization step or a public
  hero/board blocker filter that removes all positive mass yields an explicit
  `degenerate` result (no combos, no positive 169 mass, explicit reason), never a
  silent re-seed from the imported legacy range and never a 100 % grid;
- use only public information available at the replay step (board cards and hero
  cards are public; unrevealed opponent cards are not);
- not claim backend-contract provenance (`identity`, `provenance`,
  `distribution_fingerprint`, `public_state_fingerprint`) that only
  `posterior_range.py` can produce. A postflop estimate is a display estimate,
  not a serialized `poker-opponent-posterior-range/v1` record.

## 6. Non-goals

- No change to Model A or Model B fitting, calibration, candidate selection, or
  promotion.
- No change to the preflop probability contract
  (`poker-preflop-action-probabilities/v1`).
- No change to equity consumers (`exactComboPriorFromEntries`, `combos`,
  `buildSeatEquityPlayers`, `postflopRaiseTreeSnapshot`): they stay invariant
  under the chosen normalization because they consume the same weights at the
  same scale.
- No reference to future/private information.

## 7. Verification

- `python3 tests/ranges/test_posterior_range.py` — backend projection, blockers,
  normalization and fail-closed states.
- `python3 tests/trainer/test_prior_posterior_ui_contract.py` — prior/posterior
  UI boundary.
- `python3 tests/trainer/test_opponent_range_display_contract.py` — this
  document, the exported constant, the four notions and the mass-sum projection.
- `python3 tests/trainer/test_replayer_modal_prior_states.py` — the replayer
  range modal, its explicit `prior_uninformative`/`degenerate` states and its
  unified mass legends.
- `python3 tests/trainer/smoke_opponent_range_numeric.py` — numeric browser
  proof of the ten opponent-range scenarios (sum-normalized 169 mass grid and
  the explicit `prior_uninformative`/`source_prior_unconditioned`/`degenerate`
  states; a non-uniform imported source range with zero matched action stays
  distinct with no 100 % cell, and the degenerate posterior never falls back to
  the legacy imported range).
- `python3 tests/trainer/smoke_equity_scale_invariance.py` — numeric browser
  proof that `buildSeatEquityPlayers`, `tableEquitySnapshotForStep`,
  `postflopRaiseTreeSnapshot` and `aiExportRangeSnapshot` stay invariant under a
  constant rescaling of the input weights, with a sum-normalized
  `grid_169_probability_pct` and a distinct `relative_weight_pct`.
- Both numeric browser smokes above are orchestrated by
  `python3 tests/trainer/smoke_trainer.py` (via `run_driver_smokes`), not by
  dedicated steps in `.github/workflows/trainer-smoke.yml`; the workflow stays
  frozen and exercises them through its single Training-view step.

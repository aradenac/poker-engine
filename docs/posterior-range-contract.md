# Opponent posterior range runtime contract

Issue #320 defines the stable runtime boundary between a posterior producer and downstream reviewer/EV consumers. It does not fit Model A, select a scientific artifact, or modify UI.

## Schema

Runtime records use:

    poker-opponent-posterior-range/v1

The JSON schema is 'contracts/posterior-range.schema.json'.

A record is tied to one exact point in the public timeline through:

- hand_id
- step_id
- public_state_fingerprint
- player / position
- moment: BEFORE_ACTION or AFTER_ACTION

AFTER_ACTION requires the public action that was used to condition the posterior. The action already contains an optional stable sizing envelope (observed_size_bb, target_total_bb, pot_before_bb, pot_fraction, semantic), so #312/#313 can later supply a sizing-dependent likelihood without a schema-major change.

## Identity and provenance

Every record requires:

- population identity
- model identity + version
- source identity
- producer
- contract version
- source artifact
- source fingerprint

A downstream consumer must not interpret an anonymous grid as an estimated range.

## Exact combos are authoritative

exact_combo_weights is the authoritative probability distribution.

src/ranges/posterior_range.py reuses the repository card/class mapping from tools/simulation/model_b_runtime.py and performs:

1. exact-card blocker filtering;
2. positive-mass check;
3. normalization;
4. deterministic exact combo ordering;
5. projection by summing exact combo probability into the 169 canonical classes;
6. effective support and entropy calculation;
7. deterministic content fingerprinting.

The 169 projection includes both:

- canonical full-deck combo multiplicity (1326 total);
- legal combo multiplicity after the declared blockers.

This prevents a class-level projection from silently ignoring blocker-dependent multiplicity.

## Information boundary

Only blockers with:

    knowledge_scope = PUBLIC

are accepted by this contract.

Opponent hole cards that have not been revealed at step_id, future board cards, or any field that attempts to inject future/private information are invalid. The validator uses an allow-list at the top level and for action/blocker records.

BEFORE_ACTION requires public_action = null, so the target action cannot leak into its own prior.

AFTER_ACTION requires the observed public action and may carry its public sizing fields.

## Fail-closed states

status is one of:

- AVAILABLE
- UNSUPPORTED
- INVALID

AVAILABLE requires normalized positive exact-combo mass and a matching 169 projection.

UNSUPPORTED and INVALID must contain:

- zero probability mass;
- no exact combo weights;
- an all-zero 169 probability projection;
- an explicit reason.

They still retain the canonical/legal multiplicity metadata, identity, support source and provenance. Missing support therefore never becomes an all-hands-100-percent range.

## Existing posterior compatibility

The current training-side ComboPosterior in tools/training/model_a_latent_ranges.py already exposes exact combos and weights.

record_from_combo_posterior() accepts any object exposing those two attributes and serializes it through the same validator/projector without importing or duplicating Model A fitting logic.

This is the intended bridge for #312.

## Displayed semantics and Replayer UI mapping

Rendering surfaces must not relabel the backend quantities. The versioned
display companion is `docs/opponent-range-display-contract.md`
(`poker-opponent-range-display/v1`, exported as
`OPPONENT_RANGE_DISPLAY_CONTRACT` from `site/index.html`). It is a
representation contract and introduces no fit or model change. This backend
document and that display contract are aligned; where they name the same value
they use the same unit and normalization.

### The four notions stay separate

| Notion | Canonical name | Unit and normalization | Backend field |
|---|---|---|---|
| (a) posterior combo probability | `posterior_combo_probability` | probability in `[0,1]`, **sum-normalized** over legal exact combos so the mass is `1`; displayed as `%` | `exact_combo_weights[].weight`, `probability_mass`, `normalization.output_mass` |
| (b) diagnostic relative weight | `relative_weight` | dimensionless ratio in `[0,1]`, **max-normalized** (the strongest legal weight becomes `1`); never a probability and never a sum to `1` | none — display-only, no backend field |
| (c) a priori inclusion frequency | `inclusion_frequency` | percent in `[0,100]` per hand class; an **input** from an imported/source range, not conditioned on observed actions | none in this contract; imported range `positions[].hands[].frequency` |
| (d) non-informative prior | `non_informative_prior` | probability, **uniform** over the legal exact combos after PUBLIC blockers (`1/N` each) | `UNCONDITIONED_COMBO_PRIOR` from the Model A adapter (`support.source_observations = 0`, `support.backoff.level = UNCONDITIONED_COMBO_PRIOR`), projected as normalized combo probability |

Only (a) and (d) are probabilities, and only (a) is the conditioned posterior
output of `project_exact_combo_weights`. (b) is a display-only diagnostic
normalization; (c) is an imported-range input. No surface may render (b) or (c)
with the unit or label of (a), and a uniform prior must never be displayed as a
`100 %` range. The single-class `100 %` display belongs exclusively to the
separate known-hand override, which is not a posterior.

### The 169 projection is a mass sum

`projection_169.classes[hand_class]` is the **sum of the exact-combo
probabilities** belonging to that class:

    classes[hand_class] = Σ posterior_combo_probability(combo)
                          for combo in legal_combos(hand_class)

- it is not a mean and not a max over the combos of the class;
- because the exact-combo probabilities sum to `1`, the 169 class masses also
  sum to `1` (display surfaces show them as `%`, summing to `100 %`);
- `full_combo_multiplicity` (canonical 1326) and `legal_combo_multiplicity`
  (post-PUBLIC-blocker) travel with `classes`, so a class mass is never read as
  a per-combo probability;
- the separate 169 **relative-weight** heat grid (notion (b)) aggregates
  max-normalized combo weights per class (by mean in the browser) for visual
  comparison only. It is not this projection: it is exported only under the
  explicit relative-weight field `grid_169_relative_weight_pct` (and per combo
  `relative_weight_pct`) and must never be exported, cited or labelled as a
  probability.

### posteriorState

The backend serializes `status ∈ {AVAILABLE, UNSUPPORTED, INVALID}`. The
display layer derives exactly one `posteriorState` for every rendered
distribution; the state comes from the representation layer (blockers,
normalization, support, conditioning actions), never from the model fit.

| `posteriorState` | Backend correspondence | Mass | Replayer rendering |
|---|---|---|---|
| `prior_uninformative` | no conditioning action matched and the kept prior is the full-support uniform prior over the legal exact combos (uniform weights and a support covering every exact combo still legal after the PUBLIC hero/board blockers), or `UNCONDITIONED_COMBO_PRIOR` with `source_observations = 0`; a positive-mass prior may still be `AVAILABLE` | prior (normalized only when projected) | explicit « Prior non informatif · range non estimée » state; no numeric 169 grid |
| `source_prior_unconditioned` | no conditioning action matched while the kept imported/source prior is not the full-support uniform prior (non-uniform weights, or uniform over a strict subset such as a single class or a support reduced by public blockers), so it is a genuine a priori distribution that is not a conditioned posterior | prior (normalized only when projected) | explicit « Prior source non conditionné · range importée non conditionnée » state; no numeric 169 grid, never a 100 % range and never assimilated to `conditioned` |
| `conditioned` | `status = AVAILABLE`, `probability_mass = 1`, positive `exact_combo_support`, and at least one matched public action | `1` | full posterior display |
| `degenerate` | `status ∈ {UNSUPPORTED, INVALID}` (`probability_mass = 0`, no `exact_combo_weights`, all-zero 169 projection, non-empty `reason`), or the browser removed all positive mass | `0` | fail-closed; no combos, no positive 169 mass, explicit reason, never a silent re-seed from the imported range and never a `100 %` grid |

A concentrated but `AVAILABLE` posterior is not `degenerate`: low
`support.effective_support` and `support.entropy_nats` are diagnostics only,
are not probabilities, and are not the notion (b) relative weight.

### Replayer UI mapping

`site/index.html` is a static vanilla-JS application; its Replayer surfaces
consume exactly the values above:

- `populationRangeEstimateForPlayer` builds the estimate and derives
  `posteriorState`: at least one exploited public action
  (`informativeActions = preMatched + postMatched > 0`) is `conditioned`;
  otherwise it checks whether the kept prior is the full-support uniform prior
  over the legal exact combos (`priorIsNonInformative`: uniform weights **and** a
  support covering every exact combo still legal after the PUBLIC hero/board
  blockers): a full-support uniform prior is `prior_uninformative`, while any
  other imported/source prior (non-uniform, or uniform over a strict subset such
  as a single class or a support reduced by public blockers) is the distinct
  `source_prior_unconditioned`. It returns
  `gridEntries = projectCombosTo169Mass(combos)` — the canonical 169
  mass sum. `projectCombosTo169Mass` divides each retained weight by the total
  and accumulates `w / total` per hand class.
- `gridFreqMapFromEstimate` returns an empty map for `degenerate`,
  `prior_uninformative` and `source_prior_unconditioned`, so no numeric grid is
  drawn for those states (and none can read as a `100 %` range);
  `massGridFreqMapFromEstimate` otherwise reads `estimate.gridEntries` unchanged.
- `openPopulationRangeModal` renders the explicit state titles
  « Prior non informatif · range non estimée »,
  « Prior source non conditionné · range importée non conditionnée » and
  « Posterior dégénéré · masse nulle après blockers publics ». The legends
  « projection 169 (masse) » and « Chaque classe = somme des probabilités de ses
  combos légaux (masse probabiliste, somme = 100 %) », the combo list
  « masse probabiliste après normalisation » and the delta panel (variation in
  mass points) all describe notion (a). Display surfaces never relabel it as a
  max-normalized ratio.
- the known-hand override is a **separate banner**
  (`data-known-hand-override="true"`, `knownHandOverride:true`) and is never
  merged into the posterior grid; it is the only legitimate single-class
  `100 %` display.
- `aiExportRangeSnapshot` exports `posterior_state`,
  `exact_combos[].probability_pct = 100 * weight / total` and
  `grid_169_probability_pct` (the 169 mass sum). It additionally exports the
  diagnostic `grid_169_relative_weight_pct` and per-combo `relative_weight_pct`
  (max-normalized notion (b)) **only for a `conditioned` posterior with
  non-uniform weights**; for `prior_uninformative` and
  `source_prior_unconditioned` those diagnostics are `null` (or an empty grid)
  while the canonical `probability_pct` is retained. The conditioned engine's
  `entries[].frequency` carries the same sum-normalized mass of notion (a) and
  its `entries[].relativeWeightPct` the same separate diagnostic of notion (b),
  defined only for the conditioned state.
- the equity consumers (`combos`/sampler, `buildSeatEquityPlayers`,
  `postflopRaiseTreeSnapshot`) keep reading `hand`/`frequency` at the same
  scale: the display normalization above never rescales their inputs.

The postflop path (`populationRangeEstimateForPlayer` on flop/turn/river) is a
browser-only extension: it obeys the same four notions, the same mass-sum 169
projection and the same `posteriorState` triggers, but has no
`posterior_range.py` equivalent and no JSON schema. It never consumes an
unrevealed opponent card; only PUBLIC blockers (board and hero cards) are
applied.

## Synthetic verification

Run:

    python3 tests/ranges/test_posterior_range.py

Coverage includes:

- 1326 -> 169 multiplicity;
- non-uniform posterior preservation;
- blockers and post-block normalization;
- duplicate/negative/zero-mass rejection;
- public-only information boundary;
- BEFORE/AFTER action timing;
- sizing envelope compatibility;
- mandatory identity/provenance;
- deterministic distribution fingerprint;
- projection mismatch rejection;
- explicit UNSUPPORTED zero-mass state;
- rejection of an all-100-percent grid.

No #108, VALIDATION, TEST, Model-A fit, Model-B fit, or CENTRAL-UI surface is touched by this contract.

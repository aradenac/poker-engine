# Population-bound Hero strategy (#392)

Issue #392 makes the default Hero strategy **population-bound**: a Hero strategy
only exists for one explicit `population_id`, and the runtime refuses to present,
edit, score or replay one population's ranges under another population's identity.

This document is the normative description of:

- the resolver contract `poker-hero-strategy-resolution/v1`
  (`site/hero-strategy-resolver.js`);
- the storage migration contract `poker-hero-range-migration/v1` and the
  personal-override artifact `poker-hero-personal-override/v1`
  (`site/hero-range-migration.js`);
- the population binding of the range repository
  `poker-hero-range-repository/v1` (`site/hero-ranges.js`, see
  `docs/hero-range-repository.md`);
- how the resolver consumes the scientific component admission vocabulary of
  #201/#305 and the inactive #358 candidate metadata.

The three invariants that motivate the whole design are:

1. **No admissible artifact, no active strategy.** An artifact that is absent,
   un-admitted, retained-only, unresolved, rejected, incompatible, malformed or
   inactive never becomes the active Hero strategy.
2. **No silent relabel.** A legacy `MIXED` repository, context, override or
   candidate is never relabelled to the active (for example Zoom) population, and
   the inactive #358 candidate is never auto-activated.
3. **No fallback identity.** When the final #196 strategy does not exist or is not
   admissible, the runtime reports an explicit `PARTIAL`/`UNAVAILABLE` state. The
   generic label `Custom` is never a default strategy identity.

## Population binding

`population_id` is the single required scope of a Hero strategy. The resolver
requires an `activePopulation` and compares it against **every** population
binding it can observe. A binding that declares a different population is a hard
failure, not a warning.

Bindings checked by the resolver:

| Source token | Observed on |
| --- | --- |
| `REPOSITORY_DEFAULTS` | `repository.defaults.population_id` |
| `CALCULATED_CONTEXT` | `context.population_id` of every materialized `calculated` layer |
| `CANDIDATE` / `CANDIDATE_CONTEXT` | calculated candidate root and its exact context |
| `TRAINER_MANIFEST` | `trainer-population-pack/v1` manifest (`site/assets/trainer/population.json`) |
| `PACK_IDENTITY` | active pack descriptor, including a nested `entry` descriptor |
| `ADMISSION` / `ADMISSION_HERO_STRATEGY` / `ADMISSION_HERO_RANGES` | persisted `poker-scientific-component-admission/v1` |
| `RETAINED_REFERENCE` | retained reference provenance |
| `CONTEXT` | the requested Hero context |

Both Hero roles are population-bound: a foreign `hero_ranges` admission fails
closed even when `hero_strategy` itself is compatible.

The repository carries the same guarantee independently of the resolver:
`populationBound(repository, context)` returns
`{population_id, repository_population_id, compatible}` and the editor refuses to
read or write a context whose population does not match
`repository.defaults.population_id`. Editing is not allowed to create a context
under a foreign population, so an override cannot smuggle one identity into
another.

## Resolver contract surface

`site/hero-strategy-resolver.js` exports:

- `SCHEMA = poker-hero-strategy-resolution/v1`;
- `STATUSES = ADMISSIBLE_CALCULATED | RETAIN_REFERENCE | PARTIAL | UNAVAILABLE | POPULATION_INCOMPATIBLE`;
- `SOURCES = POPULATION | PERSONAL_OVERRIDE | NONE`;
- `ADMISSION_STATUSES = ADMISSIBLE | RETAIN_REFERENCE | UNRESOLVED | REJECTED | INCOMPATIBLE`;
- `resolveHeroStrategy(input)` — the pure, read-only, no-promotion decision;
- `identity(resolution)` — the normalized identity accessor that downstream
  consumers must use instead of re-reading manifests or inventing a label.

The output is deterministic: reason codes are unique and sorted, context keys are
sorted, and provenance is built from explicit tokens only. Re-running the same
input yields byte-identical JSON.

### States, sources and fail-close

`fail_closed: true` means "no strategy identity may be used". A non-null
`strategy_id` is only ever returned together with `fail_closed: false`.

| `status` | `source` | `fail_closed` | Meaning |
| --- | --- | --- | --- |
| `ADMISSIBLE_CALCULATED` | `POPULATION` | `false` | An explicit `ADMISSIBLE` admission covers a complete calculated population strategy (169 hand classes per active calculated context). |
| `PARTIAL` | `POPULATION` | `true` | An `ADMISSIBLE` calculated layer exists but its coverage is incomplete. Identity/provenance are reported, but the strategy is not usable. |
| `RETAIN_REFERENCE` | `POPULATION` | `false` | The admission is `RETAIN_REFERENCE`: a population-bound reference is kept as provenance only. It is not an admissible calculated strategy. |
| `PARTIAL` | `PERSONAL_OVERRIDE` | `true` | No population strategy is available; only a personal override exists for the active population. |
| `UNAVAILABLE` | `NONE` | `true` | No admissible strategy: missing, retained-without-identity, unresolved, rejected, un-admitted, inactive or malformed. |
| `POPULATION_INCOMPATIBLE` | `NONE` | `true` | The active population is missing, a binding mismatches, or the admission role is `INCOMPATIBLE`. |

Note that `RETAIN_REFERENCE` is deliberately **not** fail-closed at the resolver
level, because a retained reference is legitimate provenance. Consumers that need
an executable strategy must still require `status === "ADMISSIBLE_CALCULATED"`
(see the Trainer below); `fail_closed` alone is not sufficient there.

### Reason codes

The resolver reports the following deterministic codes (non-exhaustive for the
generic path):

- population: `POPULATION_ID_MISSING`, `POPULATION_ID_MISMATCH`, plus one
  `<SOURCE>_POPULATION_MISMATCH` per offending binding;
- admission: `ADMISSION_INCOMPATIBLE`, `HERO_STRATEGY_ADMISSION_INCOMPATIBLE`,
  `HERO_RANGES_ADMISSION_INCOMPATIBLE`, `ADMISSION_MISSING`;
- calculated strategy: `ADMITTED_CALCULATED_STRATEGY`,
  `STRATEGY_PARTIAL_COVERAGE`, `STRATEGY_NOT_ADMITTED`, `STRATEGY_REJECTED`,
  `STRATEGY_UNRESOLVED`, `NO_ADMISSIBLE_STRATEGY`, `REPOSITORY_INVALID`;
- retained reference: `RETAINED_REFERENCE`, `RETAINED_REFERENCE_IDENTITY_MISSING`;
- personal override: `PERSONAL_OVERRIDE_NOT_POPULATION_STRATEGY`;
- inactive candidate: `INACTIVE_CANDIDATE_NOT_ACTIVATED`;
- candidate self-promotion: `CANDIDATE_SCHEMA_MISMATCH`,
  `CANDIDATE_PROMOTION_FORBIDDEN`, `CANDIDATE_SELF_PROMOTED`;
- label hygiene: `CUSTOM_LABEL_REJECTED`.

## Admission states (#201/#305)

The runtime admission vocabulary is the one produced by the #201 assembly gate
and its read-only #305 resolver (`tools/population_pack_admission.py`,
`poker-scientific-component-admission/v1`). The Hero resolver consumes it as
follows:

| Admission status | Resolver outcome |
| --- | --- |
| `ADMISSIBLE` | `ADMISSIBLE_CALCULATED` when the active calculated layer is complete; otherwise `PARTIAL`. An `ADMISSIBLE` admission over an empty layer authorizes nothing. |
| `RETAIN_REFERENCE` | `RETAIN_REFERENCE` with `source: POPULATION`; reference identity only. |
| `UNRESOLVED` | `UNAVAILABLE` with `STRATEGY_UNRESOLVED`. |
| `REJECTED` | `UNAVAILABLE` with `STRATEGY_REJECTED`. |
| `INCOMPATIBLE` | `POPULATION_INCOMPATIBLE` with `ADMISSION_INCOMPATIBLE`. |
| absent | `UNAVAILABLE` or `POPULATION_INCOMPATIBLE` with `ADMISSION_MISSING`, depending on the branch. |

A malformed repository (`REPOSITORY_INVALID`) fails closed even when an admission
claims `ADMISSIBLE`. Both `hero_strategy` and `hero_ranges` roles must be
compatible; a role map may be flat or nested under
`poker-scientific-component-admission/v1.admissions`.

## Precedence

Resolution is a strict ordered decision. The first matching branch wins:

1. **Missing active population** → `POPULATION_INCOMPATIBLE`, no identity.
2. **Any population binding mismatch** → `POPULATION_INCOMPATIBLE`, no identity.
3. **`INCOMPATIBLE` admission** (either Hero role) → `POPULATION_INCOMPATIBLE`.
4. **Admitted + not blocked candidate + complete calculated** →
   `ADMISSIBLE_CALCULATED`.
5. **Admitted + calculated present but incomplete** → `PARTIAL` (population
   source).
6. **Retained reference** → `RETAIN_REFERENCE`.
7. **Blocked candidate, or any materialized active calculated layer that is not
   admissible** → `UNAVAILABLE`. This branch deliberately precedes the personal
   layer so an override can never mask an un-admitted calculated strategy.
8. **Inactive/metadata-only calculated layer** → `UNAVAILABLE`
   (`INACTIVE_CANDIDATE_NOT_ACTIVATED`).
9. **Personal override only** → `PARTIAL` / `PERSONAL_OVERRIDE`.
10. **Otherwise** → `UNAVAILABLE`.

Within a repository context, the per-hand layer precedence is unchanged: a
`personal` hand wins over the `calculated` hand for that hand class. That
precedence governs *which hand strategy is read*; it does **not** change the
strategy identity or source. When an admissible calculated strategy exists, the
resolver still reports `source: POPULATION` even if the user has personal
overrides on top of it.

## Personal override is distinct from the population strategy

The personal layer is a user plan, never a claim of the population strategy, and
the two are kept distinct end to end:

- **Storage.** Overrides live in `layers.personal.hands`, one context per
  population/table/position/stack/spot. The editor labels them "override
  personnel" and shows the population source separately.
- **Resolver.** With only personal hands, the resolver returns
  `status: PARTIAL`, `source: PERSONAL_OVERRIDE`, `strategy_id: null`,
  `fail_closed: true` and the code `PERSONAL_OVERRIDE_NOT_POPULATION_STRATEGY`.
  It never reports the override as `POPULATION`.
- **Migration.** `extractPersonalOverride` / `extractPersonalOverrides` emit a
  `poker-hero-personal-override/v1` artifact with explicit provenance:
  `origin/source: PERSONAL_OVERRIDE`, `layer: personal`, `population_id`,
  `context_key`, `repository_schema`, `repository_version`, `layer_version`,
  `active_population_id`, `population_match` and `inherited`.
- **Foreign overrides.** An override whose `population_id` differs from the active
  one is retained verbatim with `inherited: true` and `population_match: false`.
  It is never relabelled; callers may filter it with
  `requireCompatible: true`.

An override therefore cannot masquerade as the population strategy in any
consumer: resolver, editor, migration, Trainer, Review or compliance.

## Partial and unavailable #196 state

The final full-hand Hero strategy (#196) is not promoted yet. Until it exists and
is admitted, the runtime must remain explicitly partial/unavailable rather than
invent a default strategy:

- no calculated layer, or an `ADMISSIBLE` layer with incomplete coverage, yields
  `UNAVAILABLE` / `PARTIAL` with an explicit reason;
- the identity accessor returns `null` identity tokens and the real status
  (`UNAVAILABLE@…` downstream), never a placeholder;
- the literal label `Custom` is rejected as an identity token
  (`CUSTOM_LABEL_REJECTED`) and scrubbed from provenance. If a generated
  identity is needed it is derived from the explicit population
  (`hero-population:<population_id>`) or stays `null`;
- the product header, Trainer, Review and compliance surfaces display an explicit
  unavailable/partial state instead of "Custom".

The legacy trainer range-folder source is also `RETAIN_REFERENCE`
(`admissible: false`, `promotable: false`, `calculated: false`), so the historical
presence of a `Custom` folder name is preserved only as source metadata, never as
the default strategy identity.

## Non-promotion of the inactive #358 candidate

The #358 non-ISO Hero generation is metadata-only and must never be activated by
this tranche. The resolver:

- treats the activation states `INACTIVE`,
  `INACTIVE_CANDIDATE_METADATA_ONLY`, `SYNTHETIC_PLACEHOLDER` and
  `SYNTHETIC_PLACEHOLDER_METADATA_ONLY` as inactive;
- excludes inactive layers from the active calculated set and reports
  `UNAVAILABLE` with `INACTIVE_CANDIDATE_NOT_ACTIVATED`;
- never auto-activates a candidate: `promotion_authorized: true` yields
  `CANDIDATE_PROMOTION_FORBIDDEN`, a `PROMOTED` candidate status yields
  `CANDIDATE_SELF_PROMOTED`, and a wrong candidate schema yields
  `CANDIDATE_SCHEMA_MISMATCH`. Any of these blocks the `ADMISSIBLE_CALCULATED`
  and `PARTIAL` calculated branches.

A candidate may be *evaluated*, but only an explicit, separately granted
admission makes a complete calculated layer usable.

## Storage migration

`site/hero-range-migration.js` migrates the repository persisted under
`localStorage["poker.hero.range.repository.v1"]`. It is a pure planner plus a thin
storage adapter: it never edits a range source and never rewrites a population
identity.

| Status | Meaning |
| --- | --- |
| `MIGRATED` | A schema-valid repository received the additive `migration` block. |
| `MIGRATED_IMPORTED` | A legacy range-folder payload was losslessly imported first, then migrated. |
| `UNCHANGED` | Already migrated; byte-identical no-op (`ALREADY_MIGRATED`). |
| `EMPTY` | Nothing stored. |
| `UNAVAILABLE` | Unreadable/invalid storage or repository; never invents a repository. |
| `ROLLED_BACK` | The exact previous payload was restored. |
| `ROLLBACK_UNAVAILABLE` | No previous copy exists; reported explicitly. |

Guarantees:

- **Additive.** Existing contexts, layers and the verbatim range source are
  preserved untouched; only a `migration` provenance block is added
  (`source_verbatim_preserved: true`, `MIGRATION_ADDITIVE`).
- **Idempotent.** A second migration is a byte-identical no-op and never
  re-snapshots the rollback copy.
- **Reversible.** The exact pre-migration payload is copied to
  `poker.hero.range.repository.v1.previous` and restored byte-for-byte by
  `rollbackStorage`; the previous copy is retained after rollback.
- **No relabel.** `relabeled_population_ids` is always empty. Foreign populations
  are reported as `inherited_population_ids` and flagged with
  `INHERITED_POPULATION_RETAINED`; a fully foreign repository adds
  `NO_COMPATIBLE_POPULATION`. A `MIXED` repository is never relabelled to the
  active Zoom population.
- **Legacy import.** A bare range-folder document is imported losslessly via
  `poker-hero-range-repository/v1` and flagged `LEGACY_SOURCE_IMPORTED`.

Migration runs safely at editor load and on the Trainer path; the migrated
repository is what the runtime reloads, and it stays schema-valid after migration.

## Downstream consumers

- **Shared accessor.** `identity(resolution)` is the single read surface for
  `population_id`, `strategy_id`, `strategy_version`, `strategy_sha256`, `status`,
  `source`, `fail_closed` and `reason_codes`.
- **Review scope** (`src/analytics/review-score-adapter.js`, `site/leaks.js`)
  builds a `poker-review-resolution-scope/v1` from the resolver. Only
  `ADMISSIBLE_CALCULATED` with a non-`Custom` id/version yields a real scope;
  every other state becomes an explicit `UNAVAILABLE_STRATEGY` /
  `UNAVAILABLE@<status>` token that still carries the population identity, so the
  scope stays selectable and never falls back to "Custom".
- **Trainer** (`site/trainer.js`) resolves the Hero identity from the population
  manifest, repository, active pack, admission and retained reference. It requires
  `resolution.status === "ADMISSIBLE_CALCULATED"`, independently of
  `fail_closed`, otherwise it shows `Stratégie indisponible pour cette
  population`. Retained references stay provenance only.
- **Product header** (`site/index.html`) shows the population, the resolved Hero
  strategy source/version, a dedicated fail-close chip and a separate personal
  override chip.
- **Compliance/replayer** (`site/hero-compliance.js`,
  `site/hero-compliance-replayer.js`) only authorize a population verdict for an
  `ADMISSIBLE_CALCULATED`, non-fail-closed, population-compatible resolution.
  Retained references, partial coverage and unresolved artifacts never do, and a
  mismatching population is a hard boundary.

## Validation

```sh
node --check site/hero-strategy-resolver.js
node --check site/hero-range-migration.js
node --check site/hero-ranges.js
node tests/hero_ranges/test_hero_strategy_resolver.mjs
node tests/hero_ranges/test_hero_range_migration.mjs
node tests/hero_ranges/test_population_bound_hero_strategy.mjs
node tests/analytics/test_review_score_adapter.js
python3 tools/write_site_release.py --check
```

`.github/workflows/hero-population-strategy.yml` runs the resolver, migration and
end-to-end contracts plus the release-identity check. The end-to-end suite walks
nine scenarios: population compatible, population incompatible, no strategy,
personal override, pack change, rollback, persistence, provenance and fail-closed
activation.

## Related documents

- `docs/hero-range-repository.md` — the population-bound repository and layers.
- `docs/hero-calculated-range-candidate.md` — the no-promotion calculated
  candidate boundary (`promotion_authorized: false`).
- `docs/population-pack-v1.md` — population-packs and promoted pointers.

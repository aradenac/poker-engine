---
schema: poker-hero-strategy-population-binding-ci-report/v1
issue: 392
task: task-kch
report_date: 2026-09-21
status: PASS
head_sha: a1b19991c160c27e440097fc06dc63afb0cc5f73
branch: n8n/issue-392-population-bound-hero-strategy
pull_request: 399
merged: false
admission_binding: PASS
coverage_completeness: PASS
contextual_override: PASS
release_anchor_check: PASS
red_workflows: []
---

# Rapport CI — Stratégie Hero population-bound (#392, task-kch)

Rapport de validation locale du rework #392 (PR #399). Aucun merge, aucun push,
aucun rebasage : la branche existante `n8n/issue-392-population-bound-hero-strategy`
est conservée telle quelle.

## Statut

| Champ | Valeur |
| --- | --- |
| Statut global | **PASS** |
| Nouveau HEAD SHA | `a1b19991c160c27e440097fc06dc63afb0cc5f73` |
| Branche | `n8n/issue-392-population-bound-hero-strategy` |
| PR | #399 (`OPEN`, `MERGEABLE`) |
| Merge effectué | **non** (STOP_AFTER_CLAUDE_REVIEW_AND_PR) |
| HEAD distant PR au moment du rapport | `b2856afae1e710d1fc57bc74610498a252699e9d` (les 6 commits locaux ne sont pas encore poussés) |
| `site/RELEASE.json` régénéré | oui (aucun delta : ancre canonique déjà à jour) |
| `python3 tools/write_site_release.py --check` | **PASS** |

### Verdicts exigés

| Vérification | Verdict | Preuve principale |
| --- | --- | --- |
| Admission binding (#task-fnc) | **PASS** | `tests/hero_ranges/test_hero_strategy_resolver.mjs` (binding rôle/hash/provenance/candidate/generation/binding_sha256), `tests/hero_ranges/test_population_bound_hero_strategy.mjs` scénario « runtime admission wiring » |
| Coverage completeness (#task-ewo) | **PASS** | `tests/hero_ranges/test_hero_strategy_resolver.mjs` (`REQUIRED_CONTEXT_KEYS`, `coverage.authoritative/required/covered/missing`, `REQUIRED_CONTEXT_SET_UNKNOWN`), scénarios PARTIAL/UNAVAILABLE du E2E |
| Contextual override (#task-8zr) | **PASS** | `tests/hero_ranges/test_hero_range_migration.mjs` (statut `available` vs `active` par `context_key`), `tests/analytics/test_review_scope_resolution.js` (override disponible mais inactif sur un autre contexte) |

## Régénération de l'identité release

- `python3 tools/write_site_release.py` → `wrote site/RELEASE.json` (aucun changement
  de byte : l'ancre versionnée correspond déjà aux octets fonctionnels).
- `python3 tools/write_site_release.py --check` →
  `release source anchor verified: site/RELEASE.json; assembled identity can be materialized` (EXIT=0).
- `site/RELEASE.json` embarque bien les modules du rework dans
  `identity.assembled_site.functional_files` :
  - `site/hero-strategy-resolver.js` → `161cb59a4e6db30a6c0dfc93c7e3c12f582ae84a` ;
  - `site/hero-range-migration.js` → `98ff74011c1b425c2664627a29032a3427af4cbb`.
- Schéma ancre : `poker-site-release/v3` ; `assets_tree_git_sha` inchangé.

## CI locale — contrats exécutés (tous PASS)

### Syntaxe JavaScript

`node --check` : `site/hero-ranges.js`, `site/hero-range-migration.js`,
`site/hero-strategy-resolver.js`, `site/hero-compliance.js`,
`site/hero-compliance-replayer.js`, `site/hero-ranges-app.js`, `site/trainer.js`,
plus `src/preflop/decision.js`, `src/preflop/hero_range_export.js`,
`tools/training/export_calculated_hero_candidate.mjs`,
`tests/hero_ranges/test_calculated_range_export.mjs`,
`tests/hero_ranges/test_squeeze_range_export.mjs` → tous OK.

### Contrats Hero ranges

| Contrat | Résultat |
| --- | --- |
| `tests/hero_ranges/test_hero_strategy_resolver.mjs` | PASS |
| `tests/hero_ranges/test_hero_range_migration.mjs` | PASS |
| `tests/hero_ranges/test_population_bound_hero_strategy.mjs` | PASS (10 scénarios) |
| `tests/hero_ranges/test_calculated_range_export.mjs` | PASS |
| `tests/hero_ranges/test_squeeze_range_export.mjs` | PASS |
| `tests/hero_ranges/test_hero_compliance.mjs` | PASS |
| `tests/hero_ranges/test_hero_range_repository.mjs` | PASS (2 ranges legacy, 3 contextes) |
| `tests/preflop/test_decision_contract.js` | PASS |

### Contrats analytics

| Contrat | Résultat |
| --- | --- |
| `tests/analytics/test_review_score_adapter.js` | PASS |
| `tests/analytics/test_review_scope_resolution.js` | PASS |
| `tests/analytics/test_leaks_page.py` (leaks page) | PASS |
| `tests/analytics/test_analysis_coverage.js` | PASS |
| `tests/analytics/test_hero_recommendation_distribution.js` | PASS |
| `tests/analytics/test_leak_analyzer.js` | PASS |
| `tests/analytics/test_leak_training_target.js` | PASS |
| `tests/analytics/test_population_drift.js` | PASS |
| `tests/analytics/test_prospective_report.js` | PASS |
| `tests/analytics/test_recommendation_consistency.js` | PASS |
| `tests/analytics/test_review_dashboard.js` | PASS |
| `tests/analytics/test_review_inbox.js` | PASS |

### Contrats trainer

`tests/trainer/test_*.py` exécutés intégralement (37 fichiers) → **tous PASS**,
dont `test_product_identity_ux_contract.py`, `test_range_vocabulary_contract.py`,
`test_site_release_identity.py`.

### Population-pack

| Étape | Résultat |
| --- | --- |
| `py_compile tools/build_population_pack.py tools/validate_population_pack.py` | PASS |
| `python3 -m unittest tests/packs/test_population_pack.py` | PASS |
| Build deux fois depuis entrées identiques + `cmp` | PASS (déterministe) |
| `tools/validate_population_pack.py <zip>` | PASS (`legacy_..._mixed_v1@2026.09.15.1`) |
| Rejet population Zoom-only incomplète | PASS (`CERTIFIED_DATA_ONLY ... not an accepted promoted distribution state`) |
| `tests/ci/test_repro_population_pack_catalog.py` | PASS |
| `tests/packs/test_pack_catalog_runtime.py` | PASS |

### Garde anti-bypass REPRO et idempotence des patches

| Étape | Résultat |
| --- | --- |
| `tests/ci/test_repro_workflow_batch1.py` | PASS (9 tests) |
| `tests/ci/test_repro_workflow_batch2.py` | PASS |
| `tests/ci/test_repro_current_core_batch.py` | PASS |
| `tests/ci/test_repro_composite_factorization.py` | PASS (9 tests) |
| `apply_hero_range_editor.py` (idempotence `site/index.html`) | PASS |
| `apply_trainer_mvp.py` (idempotence `site/index.html`, `site/trainer.js`) | PASS |
| `patch_hero_compliance_replayer_v1.py --check` | PASS (`current`) |
| `patch_hero_compliance_release_v1.py --check` | PASS (`current`) |
| `tests/hero_ranges/smoke_hero_compliance.py` (smoke statique) | PASS |

### Calculated range export (workflow `hero-calculated-range-export`)

`node --check` + `test_decision_contract.js` + `test_hero_range_repository.mjs` +
`test_calculated_range_export.mjs` + `test_squeeze_range_export.mjs` +
`test_generate_hero_range_decisions.py` + `test_certified_preflop_sizing_evidence.py`
+ `test_bridge_paired_ev_to_hero_generation.py` + `test_issue358_generation_contract.py`
→ **tous PASS**.

## Correspondance workflows CI ciblés

| Workflow | Étapes contrat rejouées localement | Verdict |
| --- | --- | --- |
| `hero-population-strategy.yml` | syntaxe, resolver, migration, E2E population-bound, scope identity, score adapter, `write_site_release --check` | **PASS** |
| `hero-range-editor.yml` | batch-1 anti-bypass, syntaxe, `test_hero_range_repository.mjs`, idempotence `apply_hero_range_editor.py`, release identity | **PASS** (job `contract`) |
| `hero-range-compliance.yml` | batch-1, syntaxe compliance, `test_hero_compliance.mjs`, patches `--check`, smoke statique, release identity, repository | **PASS** (job `contract`) |
| `trainer-smoke.yml` | batch-1, syntaxe `trainer.js`, release identity, tous `tests/trainer/test_*.py`, idempotence `apply_trainer_mvp.py` | **PASS** (job `static-contract`) |
| `population-pack.yml` | `py_compile`, unittest pack, double build déterministe + validation, rejet Zoom-only | **PASS** (job `validate`) |

## Workflows CI encore rouges

- **Aucun** workflow observé rouge sur la PR #399 au SHA distant `b2856af`.
  `gh pr checks 399` : 0 échec (checks en `pass` ou `skipping`, dont
  `Validate population-bound Hero strategy`, `Validate Hero range repository and editor`,
  `Validate Hero range compliance`, `Validate interactive trainer`,
  `Validate and publish population pack`, `Validate calculated Hero range export`).
- Les 6 commits locaux (`c892dee..a1b1999`) ne sont pas encore poussés ; leurs étapes
  CI ont été rejouées localement ci-dessus et passent toutes.
- **Failures locales non câblées à un workflow** (préexistantes, indépendantes de
  task-kch) : `tests/ci/test_repro_current_mixed_batch.py`,
  `tests/ci/test_residual_repro_dag.py`, `tests/ci/test_historical_workflow_quarantine.py`
  et `python3 tools/audit_active_workflow_dag.py --check`
  (« generated DAG evidence/docs are stale »). Ces audits de périmètre échouent
  parce que la branche #392 modifie légitimement des fichiers hors de leur
  allowlist / de leur DAG figé respectif ; aucun workflow `.github/workflows/*`
  ne les exécute (vérifié par recherche `tests/ci/` et `audit_active_workflow_dag`).
  Ils ne rendent donc aucun workflow rouge.
- **Limitations d'environnement local** (à couvrir par la CI distante) :
  ce sandbox ne dispose que de Python 3.14.4 sans `playwright` ni réseau PyPI ;
  `tools/repro_ci_environment.py verify` signale `PYTHON_VERSION_MISMATCH`
  (attendu `3.11.9`). En conséquence les jobs `browser-smoke`
  (`smoke_hero_ranges.py`, `smoke_hero_compliance_browser.py`, `smoke_trainer.py`,
  `smoke_engine_regressions.py`) et le job `repro-environment` n'ont pas pu être
  rejoués localement. Ils sont verts sur la CI distante (`browser-smoke` PASS,
  `repro-environment / guard` PASS) et leurs étapes statiques/sans navigateur
  passent localement.

## Conformité aux contraintes globales

- Pas d'activation #358 : aucun code/état #358 modifié par cette tâche.
- Pas de relabel MIXED → Zoom ; `Custom` reste une provenance historique.
- Aucun changement Model A/B, aucun fit, aucun TEST scientifique.
- #201/#305 préservés : statuts et sémantique inchangés (vérifiés par contrat).
- Fail-close : identité `null` et `fail_closed: true` sur les branches non admises.
- Stratégie par défaut population-bound : population activée requise et comparée.
- Sortie déterministe : `reason_codes` uniques et triés, provenance par tokens.
- Aucun merge ; aucun commit/push effectué par ce worker.

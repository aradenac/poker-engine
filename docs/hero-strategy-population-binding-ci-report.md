---
schema: poker-hero-strategy-population-binding-ci-report/v1
issue: 392
task: task-28g
report_date: 2026-09-21
status: PASS
head_sha: 523e614f9c870d2a7b61190cbb4b84a48f767871
branch: n8n/issue-392-population-bound-hero-strategy
pull_request: 399
merged: false
admission_binding: PASS
coverage_completeness: PASS
contextual_override: PASS
release_anchor_check: PASS
red_workflows: []
report_self_delta: "réconciliation task-28g : le rapport est mis à jour par un commit documentation-only au-dessus du HEAD validé et poussé 523e614 (CI GitHub verte) ; ce delta ne modifie aucun octet fonctionnel ni site/RELEASE.json, il n'invalide donc pas la preuve CI de 523e614"
---

# Rapport CI — Stratégie Hero population-bound (#392, task-28g)

Rapport de validation du rework #392 (PR #399). Aucun merge, aucun rebasage : la
branche existante `n8n/issue-392-population-bound-hero-strategy` est conservée
telle quelle. Le HEAD validé `523e614f9c870d2a7b61190cbb4b84a48f767871` est
poussé sur `origin` et correspond au `headRefOid` de la PR #399.

> **Delta du rapport lui-même (auto-référence).** Cette réconciliation remplace la
> version task-kch précédente, qui portait un `head_sha` obsolète (`5f34152`) et un
> `report_self_delta` inexact. Le HEAD validé **et poussé** est
> `523e614f9c870d2a7b61190cbb4b84a48f767871` : `git ls-remote origin` renvoie ce
> SHA et `gh pr view 399 --json headRefOid` renvoie ce même SHA, dont la CI
> GitHub est verte. La présente réconciliation est un commit **documentation-only**
> (ce seul fichier `docs/`) au-dessus de `523e614` : il ne modifie aucun octet
> fonctionnel ni `site/RELEASE.json`, donc il n'invalide pas la preuve CI obtenue
> sur `523e614`. Le SHA de ce commit de réconciliation ne peut pas être cité dans
> son propre contenu — c'est le seul point d'auto-référence, documenté ici.

## Statut

| Champ | Valeur |
| --- | --- |
| Statut global | **PASS** |
| HEAD validé (poussé, CI GitHub verte) | `523e614f9c870d2a7b61190cbb4b84a48f767871` |
| SHA obsolètes remplacés | `5f341524429d031ef72ce20497b015614dccf579` (obsolète), `b2856afae1e710d1fc57bc74610498a252699e9d` (ancienne tête distante, obsolète), `a1b19991c160c27e440097fc06dc63afb0cc5f73` (ancienne ancre de rapport, obsolète) |
| Branche | `n8n/issue-392-population-bound-hero-strategy` |
| PR | #399 (`OPEN`, `MERGEABLE`) |
| Merge effectué | **non** |
| Tête distante de la PR (`headRefOid`) | `523e614f9c870d2a7b61190cbb4b84a48f767871` (= `origin/n8n/issue-392-population-bound-hero-strategy`, poussé) |
| `site/RELEASE.json` | inchangé : ancre déjà alignée sur le HEAD validé (aucun delta d'octets) |
| `python3 tools/write_site_release.py --check` | **PASS** (EXIT=0) |

### Périmètre de commits effectif

- **Tous les commits locaux sont poussés** :
  `origin/n8n/issue-392-population-bound-hero-strategy` == HEAD == `523e614`
  (vérifié par `git ls-remote origin` et par `gh pr view 399 --json headRefOid`).
- Depuis l'ancienne tête distante `b2856af` (désormais obsolète) :
  `b2856af..523e614` = **11 commits**, tous poussés et couverts par la CI GitHub
  distante (voir § Statut réel des workflows GitHub).
- Depuis l'ancienne ancre de rapport `a1b1999` (obsolète) :
  `a1b1999..523e614` = **5 commits**, tous poussés :
  - `3b7a02d` — task-kch : régénération RELEASE.json, CI réelle, rapport PASS/FAIL ;
  - `fb309d7` — task-iuz : admission #305 canonique liée à l'artefact runtime exact ;
  - `38ecf53` — task-otm : complétude bornée par identités requises (jamais un compte) ;
  - `5f34152` — task-y47 : doc normative du contrat d'admission #305 et complétude par identité ;
  - `523e614` — task-u6i : RELEASE.json, CI réelle complète et rapport PASS/FAIL au HEAD réel.
- Fichiers modifiés par le périmètre `a1b1999..523e614` :
  `site/hero-strategy-resolver.js` (SHA blob git
  `211bf60f5dbc8b14794554cc763059fabf58948d`),
  `tests/hero_ranges/test_hero_strategy_resolver.mjs`,
  `docs/hero-strategy-population-binding.md`, `site/RELEASE.json`,
  `docs/hero-strategy-population-binding-ci-report.md`.
- Aucun commit « vide » : le delta `site/RELEASE.json` de ces commits est
  l'actualisation de `assets_tree_git_sha` (`7b8dc481d21a94e8e05fe8d7abae39e0d78b56a9`)
  et des SHA blob du resolver/migration après rework ; ces SHA sont ceux portés par
  `site/RELEASE.json` au HEAD validé.

### Verdicts exigés

| Vérification | Verdict | Preuve principale |
| --- | --- | --- |
| Admission binding (#task-fnc / #task-iuz) | **PASS** | `tests/hero_ranges/test_hero_strategy_resolver.mjs` : admission liée par `role`/hash contenu/provenance explicite/`candidate_id`/`generation_id`/`binding_sha256`, plus rejet `REPOSITORY_NOT_BOUND_TO_ADMISSION` pour toute couche partiellement identifiée ; `tests/hero_ranges/test_population_bound_hero_strategy.mjs` scénario 10 « runtime admission wiring » |
| Coverage completeness (#task-ewo / #task-otm) | **PASS** | `tests/hero_ranges/test_hero_strategy_resolver.mjs` : `REQUIRED_CONTEXT_KEYS`, `coverage.authoritative/required/covered/missing`, `required_context_keys`, `REQUIRED_CONTEXT_SET_UNKNOWN` (un simple compte ne suffit jamais) ; scénarios PARTIAL/UNAVAILABLE du E2E population-bound |
| Contextual override (#task-8zr / #task-a0n) | **PASS** | `tests/hero_ranges/test_hero_range_migration.mjs` (statut `available` vs `active` par `context_key`) ; `tests/analytics/test_review_scope_resolution.js` (`override:["available","active"]`, portée calculée jamais remplacée par l'override personnel) ; `tests/analytics/test_review_score_adapter.js` |
| Release anchor | **PASS** | `python3 tools/write_site_release.py --check` (EXIT=0) |

## Régénération de l'identité release

- `python3 tools/write_site_release.py` → `wrote site/RELEASE.json` (arbre de travail
  propre : aucun changement de byte, l'ancre versionnée correspond déjà aux octets
  fonctionnels au HEAD validé `523e614`).
- `python3 tools/write_site_release.py --check` →
  `release source anchor verified: site/RELEASE.json; assembled identity can be materialized` (EXIT=0).
- `site/RELEASE.json` embarque bien les nouveaux octets du rework dans
  `identity.assembled_site.functional_files` :
  - `site/hero-strategy-resolver.js` → `211bf60f5dbc8b14794554cc763059fabf58948d` ;
  - `site/hero-range-migration.js` → `98ff74011c1b425c2664627a29032a3427af4cbb`.
- Schéma ancre `poker-site-release/v3` ; `assets_tree_git_sha`
  `7b8dc481d21a94e8e05fe8d7abae39e0d78b56a9`.

## CI locale — contrats exécutés (tous PASS)

### Syntaxe JavaScript

`node --check` (Node v24.21.0) : `site/hero-ranges.js`, `site/hero-range-migration.js`,
`site/hero-strategy-resolver.js`, `site/hero-compliance.js`,
`site/hero-compliance-replayer.js`, `site/hero-ranges-app.js`, `site/trainer.js`,
`site/preflop-contract.js`, `src/preflop/contract.js`, `src/preflop/decision.js`,
`src/preflop/guidance.js`, `src/preflop/hero_range_export.js`,
`tools/training/export_calculated_hero_candidate.mjs`,
`tests/hero_ranges/test_calculated_range_export.mjs`,
`tests/hero_ranges/test_squeeze_range_export.mjs`,
`site/population-packs.js`, `site/population-pack-sw.js`, `site/packs-app.js` → tous OK.

### Contrats Hero ranges

| Contrat | Résultat |
| --- | --- |
| `tests/hero_ranges/test_hero_strategy_resolver.mjs` | PASS (`Hero strategy resolution contract: PASS`) |
| `tests/hero_ranges/test_hero_range_migration.mjs` | PASS (`Hero range storage migration contract: PASS`) |
| `tests/hero_ranges/test_population_bound_hero_strategy.mjs` | PASS (10 scénarios : compatible, incompatible, aucune stratégie, override personnel, changement de pack, rollback, persistence, provenance, fail-closed, runtime admission wiring) |
| `tests/hero_ranges/test_calculated_range_export.mjs` | PASS |
| `tests/hero_ranges/test_squeeze_range_export.mjs` | PASS |
| `tests/hero_ranges/test_hero_compliance.mjs` | PASS (`Hero range compliance contract: PASS`) |
| `tests/hero_ranges/test_hero_range_repository.mjs` | PASS (2 ranges legacy, 3 contextes) |
| `tests/preflop/test_decision_contract.js` | PASS |
| `tests/preflop/test_guidance_contract.js` | PASS |
| `tests/preflop/test_search.js` | PASS |

### Contrats analytics

| Contrat | Résultat |
| --- | --- |
| `tests/analytics/test_review_score_adapter.js` | PASS (`{"status":"PASS",...}`) |
| `tests/analytics/test_review_scope_resolution.js` | PASS (`override:["available","active"]`) |
| `tests/analytics/test_leaks_page.py` (unittest) | PASS (4 tests) |

### Contrats trainer

`tests/trainer/test_*.py` exécutés intégralement (**37 fichiers**) → **tous PASS**,
dont `test_product_identity_ux_contract.py`, `test_range_vocabulary_contract.py`,
`test_site_release_identity.py`.

### Smoke Hero ranges / compliance

| Smoke | Résultat |
| --- | --- |
| `tests/hero_ranges/smoke_hero_compliance.py` (statique) | PASS (`Hero compliance replayer integration: PASS`) |
| `tests/hero_ranges/smoke_hero_ranges.py` (assertions statiques) | PASS (vérifiées en isolant la partie statique ; le lancement navigateur nécessite `playwright`, absent du sandbox) |
| `tests/hero_ranges/smoke_hero_compliance_browser.py` | non rejouable localement (playwright absent) — couvert par la CI distante `browser-smoke` |

### Population-pack

| Étape | Résultat |
| --- | --- |
| `py_compile tools/build_population_pack.py tools/validate_population_pack.py` | PASS |
| `python3 -m unittest tests.packs.test_population_pack` | PASS (44 tests) |
| Build deux fois depuis entrées identiques + `cmp` | PASS (déterministe) |
| `tools/validate_population_pack.py <zip>` | PASS (`legacy-pokerstars-nlhe-100-200-play-6max-mixed-2026.09.15.1`) |
| Rejet population Zoom-only incomplète | PASS (`CERTIFIED_DATA_ONLY, not an accepted promoted distribution state`) |
| `tests/ci/test_repro_population_pack_catalog.py` | PASS |
| `tests/packs/test_pack_catalog_runtime.py` | PASS |
| `tests/ci/test_repro_population_pack_catalog.py` + idempotence `apply_pack_manager_link.py` / `write_pack_catalog.py` | PASS (arbre de travail propre) |

### Garde anti-bypass REPRO et idempotence des patches

| Étape | Résultat |
| --- | --- |
| `tests/ci/test_repro_workflow_batch1.py` | PASS |
| `tests/ci/test_repro_workflow_batch2.py` | PASS |
| `tests/ci/test_repro_current_core_batch.py` | PASS |
| `tests/ci/test_repro_composite_factorization.py` | PASS |
| `apply_hero_range_editor.py` (idempotence `site/index.html`) | PASS |
| `apply_trainer_mvp.py` (idempotence `site/index.html`, `site/trainer.js`) | PASS |
| `patch_hero_compliance_replayer_v1.py --check` | PASS (`current`) |
| `patch_hero_compliance_release_v1.py --check` | PASS (`current`) |

### Workflows déclenchés par les fichiers modifiés — contrats rejoués

Les commits du périmètre `a1b1999..523e614` modifient `site/hero-strategy-resolver.js`,
`site/RELEASE.json` et `tests/hero_ranges/test_hero_strategy_resolver.mjs`. Les
workflows suivants se déclenchent sur ces chemins et leurs contrats ont été rejoués
localement :

| Workflow | Contrats rejoués | Verdict |
| --- | --- | --- |
| `hero-population-strategy.yml` | syntaxe, resolver, migration, E2E population-bound (10 scénarios), scope identity, score adapter, `write_site_release --check` | **PASS** |
| `hero-range-editor.yml` | batch-1 anti-bypass, syntaxe, `test_hero_range_repository.mjs`, idempotence `apply_hero_range_editor.py`, release identity, smoke statique | **PASS** (job `contract` ; étape navigateur = CI distante) |
| `hero-range-compliance.yml` | batch-1, syntaxe, `test_hero_compliance.mjs`, patches `--check`, smoke statique, release identity, repository | **PASS** (job `contract`) |
| `hero-calculated-range-export.yml` | syntaxe, `test_decision_contract.js`, `test_hero_range_repository.mjs`, `test_calculated_range_export.mjs`, `test_squeeze_range_export.mjs`, `test_generate_hero_range_decisions.py`, `test_certified_preflop_sizing_evidence.py`, `test_bridge_paired_ev_to_hero_generation.py`, `test_issue358_generation_contract.py` | **PASS** |
| `preflop-search.yml` | `test_search.js`, `test_decision_contract.js`, `test_calculated_range_export.mjs` | **PASS** |
| `hero-range-pfc-context.yml` | `test_context_contract.py`, `test_hero_policy_context_sources.py`, `test_hero_range_repository.mjs`, `test_enrich_hero_range_context.py`, `test_persisted_hero_pfc_binding.py` | **PASS** |
| `preflop-contract.yml` | current-core anti-bypass, `sync_shared_modules --check`, syntaxe py/node, contrats preflop, release identity | **PASS** |
| `trainer-smoke.yml` | batch-1, syntaxe `trainer.js`, release identity, 37 `tests/trainer/test_*.py`, idempotence `apply_trainer_mvp.py` | **PASS** (job `static-contract` ; smoke navigateur = CI distante) |
| `population-pack.yml` | `py_compile`, unittest pack, double build déterministe + validation, rejet Zoom-only | **PASS** (job `validate`) |
| `population-pack-catalog.yml` | repro catalog, idempotence patches/catalogue, syntaxe node, release identity | **PASS** |
| `sequential-arena.yml` | `py_compile` simulation, gates de promotion, oracle/rollout, registry/populations, scénarios, baseline report | **PASS** (étapes déterministes ; rollouts navigateur = CI distante) |

## Statut réel des workflows GitHub sur 523e614

Source autoritaire : la CLI `gh` (authentifiée, compte `aradenac`) exécutée dans
ce dépôt, sur le HEAD validé et poussé.

- `gh pr view 399 --json headRefOid` →
  `523e614f9c870d2a7b61190cbb4b84a48f767871`.
- `git ls-remote origin refs/heads/n8n/issue-392-population-bound-hero-strategy`
  → `523e614f9c870d2a7b61190cbb4b84a48f767871` (le commit est bien poussé).
- `gh run list --branch n8n/issue-392-population-bound-hero-strategy` : **16 runs**
  associés au SHA `523e614` (11 `pull_request` + 5 `push`), **tous `success`**,
  aucun `failure` ni `cancelled`. Workflows concernés (libellés affichés par
  `gh`) : Project state consistency ; Validate population-bound Hero strategy ;
  Validate Hero range repository and editor ; Validate Hero range compliance ;
  Validate and publish population pack ; Validate population pack catalogue ;
  Validate sequential independent arena ; Validate calculated Hero range export ;
  Validate preflop context contract ; Validate Hero range PFC/PFPC context
  binding ; Validate interactive trainer.
- `gh pr checks 399` : 0 échec ; uniquement des `pass`, plus les `skipping`
  attendus (`v83-baseline-test`, `v83-baseline-validation`, `publish`).
- **Aucun workflow rouge** : `red_workflows: []` reste exact pour `523e614`.
- Le commit de réconciliation documentation-only produit par task-28g se place
  au-dessus de `523e614` et n'est donc pas décrit par ces runs ; il ne touche ni
  code, ni contrat, ni `site/RELEASE.json`.
- **Failures locales non câblées à un workflow** (préexistantes, indépendantes du
  rework #392) : `tests/ci/test_repro_current_mixed_batch.py`,
  `tests/ci/test_residual_repro_dag.py`, `tests/ci/test_historical_workflow_quarantine.py`
  et `python3 tools/audit_active_workflow_dag.py --check`
  (« generated DAG evidence/docs are stale »). Ces audits échouent parce que la
  branche #392 modifie légitimement des fichiers hors de leur allowlist / de leur
  DAG figé respectif. Vérification : aucune occurrence de ces scripts dans
  `.github/**` (recherche `grep -rn` → aucune référence) ; aucun workflow
  `.github/workflows/*` ne les exécute. Ils ne rendent donc aucun workflow rouge.
- **Limitations d'environnement local** (couvertes par la CI distante, vérifiée
  verte via `gh` sur `523e614`) : ce sandbox ne dispose que de Python 3.14.4
  (Node v24.21.0) sans `playwright` ni réseau PyPI. En conséquence les jobs
  navigateur (`browser-smoke` : `smoke_hero_ranges.py`,
  `smoke_hero_compliance_browser.py`, `smoke_trainer.py`,
  `smoke_engine_regressions.py`, `smoke_population_packs.py`) et les portions
  browser des jobs `deterministic-core`/rollout n'ont pas pu être rejoués
  localement. Ils sont verts sur la CI distante (`browser-smoke` `pass`,
  `repro-environment / guard` `pass`) et leurs étapes statiques/sans navigateur
  passent localement.

## Conformité aux contraintes globales

- Pas d'activation #358 : aucun code/état #358 modifié par cette tâche.
- Pas de relabel MIXED → Zoom ; `Custom` reste une provenance historique.
- Aucun changement Model A/B, aucun fit, aucun TEST scientifique.
- #201/#305 préservés : statuts et sémantique inchangés (vérifiés par contrat :
  `ADMISSIBLE/RETAIN_REFERENCE/UNRESOLVED/REJECTED/INCOMPATIBLE`).
- Fail-close : identité `null` et `fail_closed: true` sur les branches non admises ;
  aucun fallback silencieux.
- Stratégie par défaut population-bound : population activée requise et comparée.
- Sortie déterministe : `reason_codes` uniques et triés, provenance par tokens.
- Aucun merge ; aucun rebasage ; le commit de réconciliation est
  **documentation-only** (ce seul fichier `docs/`) et est poussé sur la branche
  existante `n8n/issue-392-population-bound-hero-strategy` — aucune nouvelle PR.

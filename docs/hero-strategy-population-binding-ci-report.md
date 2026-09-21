---
schema: poker-hero-strategy-population-binding-ci-report/v1
issue: 392
task: task-kch
report_date: 2026-09-21
status: PASS
head_sha: 5f341524429d031ef72ce20497b015614dccf579
branch: n8n/issue-392-population-bound-hero-strategy
pull_request: 399
merged: false
admission_binding: PASS
coverage_completeness: PASS
contextual_override: PASS
release_anchor_check: PASS
red_workflows: []
report_self_delta: "le rapport a1b1999 est remplacé par la présente version ; cet unique fichier est un delta de working-tree non commité au-dessus du HEAD réel 5f34152 (STOP_AFTER_CLAUDE_REVIEW_AND_PR : aucun commit/push)"
---

# Rapport CI — Stratégie Hero population-bound (#392, task-kch)

Rapport de validation locale du rework #392 (PR #399). Aucun merge, aucun push,
aucun rebasage : la branche existante `n8n/issue-392-population-bound-hero-strategy`
est conservée telle quelle.

> **Delta du rapport lui-même.** Le SHA de tête réel du rework est
> `5f341524429d031ef72ce20497b015614dccf579`. Le présent fichier est la seule
> modification de working-tree non commitée au-dessus de ce SHA : le worker
> s'arrête à `STOP_AFTER_CLAUDE_REVIEW_AND_PR` et n'effectue ni commit ni push.
> Le commit qui *contiendra* définitivement ce rapport sera le prochain commit de
> la branche ; il n'existe pas encore. Le delta est donc documenté explicitement
> ici plutôt que référencé par un SHA inexistant.

## Statut

| Champ | Valeur |
| --- | --- |
| Statut global | **PASS** |
| HEAD SHA réel (fin de rework) | `5f341524429d031ef72ce20497b015614dccf579` |
| SHA obsolète remplacé | `a1b19991c160c27e440097fc06dc63afb0cc5f73` |
| Branche | `n8n/issue-392-population-bound-hero-strategy` |
| PR | #399 (`OPEN`, `MERGEABLE`) |
| Merge effectué | **non** (STOP_AFTER_CLAUDE_REVIEW_AND_PR) |
| HEAD distant de la PR | `b2856afae1e710d1fc57bc74610498a252699e9d` (`headRefOid` de #399 ; les 10 commits locaux ne sont pas poussés) |
| `site/RELEASE.json` régénéré | oui, octets inchangés (`wrote site/RELEASE.json`, arbre propre) |
| `python3 tools/write_site_release.py --check` | **PASS** |

### Périmètre de commits effectif

- Depuis le HEAD distant de la PR : `b2856af..5f34152` = **10 commits locaux**
  (aucun poussé).
- Depuis l'ancre du rapport précédent `a1b1999` : `a1b1999..5f34152` = **4 commits**,
  qui sont précisément le périmètre nouveau couvert par cette révision :
  - `3b7a02d` — task-kch : régénération RELEASE.json, CI réelle, rapport PASS/FAIL ;
  - `fb309d7` — task-iuz : admission #305 canonique liée à l'artefact runtime exact ;
  - `38ecf53` — task-otm : complétude bornée par identités requises (jamais un compte) ;
  - `5f34152` — task-y47 : doc normative du contrat d'admission #305 et complétude par identité.
- Fichiers fonctionnels modifiés par ces 4 commits : `site/hero-strategy-resolver.js`
  (SHA blob git `211bf60f5dbc8b14794554cc763059fabf58948d`),
  `tests/hero_ranges/test_hero_strategy_resolver.mjs`,
  `site/RELEASE.json`, `docs/hero-strategy-population-binding.md`,
  `docs/hero-strategy-population-binding-ci-report.md`.
- Aucun commit « vide » : le delta `site/RELEASE.json` de ces 4 commits est
  l'actualisation de `assets_tree_git_sha` (`7b8dc481d21a94e8e05fe8d7abae39e0d78b56a9`)
  et des SHA blob du resolver/migration après rework.

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
  fonctionnels au HEAD réel).
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

Les 4 commits nouveaux modifient `site/hero-strategy-resolver.js`, `site/RELEASE.json`
et `tests/hero_ranges/test_hero_strategy_resolver.mjs`. Les workflows suivants se
déclenchent sur ces chemins et leurs contrats ont été rejoués localement :

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

## Workflows CI encore rouges

- **Aucun workflow câblé observé rouge.** Au HEAD distant de la PR
  (`b2856af`, correspondant aux 10 commits locaux), `gh run list --branch
  n8n/issue-392-population-bound-hero-strategy` ne renvoie que des `success`
  (`gh pr checks 399` : 0 échec, seuls des `pass`/`skipping`).
- Les 10 commits locaux (`b2856af..5f34152`) ne sont pas poussés : la CI distante
  ne les a donc pas encore exécutés. Tous leurs contrats ont été rejoués
  localement ci-dessus et passent ; le seul delta non poussé au-dessus de `b2856af`
  qui touche des workflows est le rework resolver + RELEASE.json, entièrement
  couvert par `hero-population-strategy.yml` (+ déclenchements secondaires listés
  ci-dessus), tous PASS.
- **Failures locales non câblées à un workflow** (préexistantes, indépendantes de
  task-kch) : `tests/ci/test_repro_current_mixed_batch.py`,
  `tests/ci/test_residual_repro_dag.py`, `tests/ci/test_historical_workflow_quarantine.py`
  et `python3 tools/audit_active_workflow_dag.py --check`
  (« generated DAG evidence/docs are stale »). Ces audits échouent parce que la
  branche #392 modifie légitimement des fichiers hors de leur allowlist / de leur
  DAG figé respectif. Vérification : aucune occurrence de ces scripts dans
  `.github/**` (recherche `grep -rn` → aucune référence) ; aucun workflow
  `.github/workflows/*` ne les exécute. Ils ne rendent donc aucun workflow rouge.
- **Limitations d'environnement local** (à couvrir par la CI distante) :
  ce sandbox ne dispose que de Python 3.14.4 (Node v24.21.0) sans `playwright` ni
  réseau PyPI. En conséquence les jobs navigateur (`browser-smoke` :
  `smoke_hero_ranges.py`, `smoke_hero_compliance_browser.py`, `smoke_trainer.py`,
  `smoke_engine_regressions.py`, `smoke_population_packs.py`) et les portions
  browser des jobs `deterministic-core`/rollout n'ont pas pu être rejoués
  localement. Ils sont verts sur la CI distante (`browser-smoke` PASS,
  `repro-environment / guard` PASS) et leurs étapes statiques/sans navigateur
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
- Aucun merge ; aucun commit/push effectué par ce worker.

# Rapport de clôture #204 — Audit final et consolidation GitHub Actions

Ce document est le **rapport de clôture** de #204. Il mappe explicitement :

- les **6 critères d'acceptation** du corps d'issue #204 (section 2) ;
- les **10 items** de la section autoritative « Remaining N8N work » (section 3) ;

chacun vers un **chemin de preuve versionné** et la **commande exécutée** au HEAD du PR (section 4).

> Autorité : le corps d'issue #204 et sa section « Remaining N8N work » sont autoritatifs.
> Cette tranche est **audit/evidence only** : aucun fichier `.github/workflows/**` n'est modifié,
> aucun trigger ni bloc `concurrency` n'est changé. #204 sera **clôturée par n8n après merge** du PR
> de cette tranche (section 7).

## 1. Périmètre et état

- HEAD de travail où les guards ont été exécutés : `a49819695cc5427eb33710d908e015394ec4ae8c`
  (dernier commit de la tranche avant le commit de clôture T5 ; les seules modifications T5 sont ce
  rapport, le scope-guard de `tools/audit_historical_workflow_quarantine.py` et la régénération de
  `analysis/workflow_audit/historical_workflow_quarantine_v2.json`).
- Base de comparaison : `origin/main` = `4559315b08fd224409c5469a4073e07ee89225b3`.
- Inventaire audité : **69** fichiers `.github/workflows/*.yml`, dont **54** à trigger automatique et
  **15** manual-only (`workflow_dispatch` seul).
- Aucun fichier `.github/workflows/**` dans le diff de la tranche
  (`git diff --name-only 4559315b08fd224409c5469a4073e07ee89225b3 HEAD -- .github/workflows` → 0 ligne).

## 2. Matrice des 6 critères d'acceptation #204

| # | Critère d'acceptation (#204) | Statut | Chemin de preuve principal | Commande exécutée |
|---|---|---|---|---|
| a | Une matrice documente chaque workflow actif et sa raison d'exister | **Satisfait** | `analysis/workflow_audit/workflows.json` (69 `role/triggers/path_scopes/concurrency/artifacts/cost_proxy`), `docs/ci-workflow-audit.md` section « Matrice des workflows » (69 lignes), rôle par bandeau (`role_counts`) | `python3 tools/audit_github_workflows.py --inventory analysis/workflow_audit/workflows.json` |
| b | Les séquences techniques répétées principales sont factorisées | **Satisfait (partiel, fail-closed)** | Composite actions `.github/actions/repro-runtime/action.yml` + `.github/actions/repro-browser/action.yml` ; preuve d'adoption `analysis/workflow_audit/repro_composite_adoption_v1.json` (16 consommateurs, 20/21 jobs sur composite, 1 exception enregistrée) ; transition gelée `analysis/workflow_audit/repro_composite_factorization_v1.json` | `python3 tools/audit_repro_composite_factorization.py --check-adoption` (PASS) |
| c | Aucun gate scientifique supprimé ou rendu optionnel par la factorisation | **Satisfait** | Garde fail-closed par consommateur (job names/artefacts/gates figés) dans `repro_composite_adoption_v1.json` ; liste des workflows gelés conservée dans `workflows.json` (`frozen_current`, 8) et `docs/ci-workflow-audit.md` section « Workflows gelés actuels » ; tests de mutation `tests/ci/test_repro_composite_factorization.py` (14 tests) | `python3 tests/ci/test_repro_composite_factorization.py` (OK) |
| d | Les changements ciblés déclenchent uniquement les workflows pertinents | **Satisfait (mesuré, aucun changement appliqué)** | `analysis/workflow_audit/workflows.json` (`path_scopes` exacts) ; `analysis/workflow_audit/consolidation_decision_v1.json` (`NO_FURTHER_CONSOLIDATION_JUSTIFIED`, 14 scénarios, 11 blockers `blocked_not_applied`, 15 `safe_candidate_not_applied`) | `python3 tools/audit_active_workflow_dag.py --check` (PASS) |
| e | Les preuves historiques restent référencées et non réécrites | **Satisfait** | `tools/audit_github_workflows.py::HISTORICAL_EVIDENCE_SHA256` (9 fichiers figés) + `tests/test_github_workflow_audit.py` ; quarantaine frozen-rewrite-proof `analysis/workflow_audit/historical_workflow_quarantine_v1.json` (`--check-v1`) | `PYTHONPATH=. python3 tests/test_github_workflow_audit.py` (6 tests OK) ; `python3 tools/audit_historical_workflow_quarantine.py --check-v1` (PASS) |
| f | Une métrique avant/après mesure les runs/jobs sur un jeu représentatif | **Satisfait (proxy statique, non facturé)** | `analysis/workflow_audit/consolidation_decision_v1.json` (`totals.before == totals.after` = 96 runs / 121 jobs / 625 cost proxy ; 14 scénarios chiffrés) ; baseline d'observation `analysis/workflow_audit/baseline_metrics.json` (échantillon #242 gelé) | `python3 tools/audit_active_workflow_dag.py --check` (PASS) ; `python3 tests/ci/test_consolidation_decision.py` (12 tests OK) |

### 2.1 Limites explicites (non satisfactions tracées)

- Le critère **(f)** est mesuré par un **proxy structurel statique, non facturé** : aucun `github_billed_minutes`
  n'est affirmé (UNKNOWN reporté dans `repro_composite_adoption_v1.json::unknowns`). C'est une mesure
  avant/après de **runs/jobs déclenchés / cost proxy**, pas une facturation GitHub.
- Le critère **(b)** est satisfait **partiellement** : la transition composite reste bloquée sur
  `population-pack-catalog.yml` / job `browser-smoke` (raison et pointeur de preuve `migratable: false`
  dans `repro_composite_adoption_v1.json`). Aucune autre factorisation n'est prouvée fail-closed, donc
  rien d'autre n'est migré. Cet écart est **justifié**, pas silencieux.

## 3. Traçabilité « Remaining N8N work » (10 items autoritatifs)

| # | Item « Remaining N8N work » | Chemin de preuve | Commande exécutée | Statut |
|---|---|---|---|---|
| 1 | Régénérer l'inventaire/DAG de tous les workflows actifs | `analysis/workflow_audit/workflows.json` (69), `analysis/workflow_audit/active_workflow_dag_v2.json` (54), `docs/ci-workflow-dag.md` | `python3 tools/audit_github_workflows.py --inventory analysis/workflow_audit/workflows.json` ; `python3 tools/audit_active_workflow_dag.py --check` | PASS |
| 2 | Prouver que les workflows historiques restent manual-only | `analysis/workflow_audit/historical_workflow_quarantine_v2.json` (15/15 `workflow_dispatch`, 0 trigger automatique) | `python3 tools/audit_historical_workflow_quarantine.py --check` | PASS |
| 3 | Vérifier l'adoption des composite actions REPRO et les derniers duplicats réels | `analysis/workflow_audit/repro_composite_adoption_v1.json` (16 consommateurs, 20/21 jobs, 1 exception) | `python3 tools/audit_repro_composite_factorization.py --check-adoption` | PASS |
| 4 | Mesurer avant/après : workflows déclenchés, jobs, static cost proxy | `analysis/workflow_audit/consolidation_decision_v1.json` (`totals.before`/`totals.after`, 14 scénarios) | `python3 tools/audit_active_workflow_dag.py --check` | PASS |
| 5 | Auditer triggers et concurrency | `analysis/workflow_audit/consolidation_decision_v1.json` (table `workflows[]` trigger + `concurrency` + `fail_closed_safe`) ; `docs/ci-workflow-dag.md` colonne « Fail-closed safe » | `python3 tests/ci/test_consolidation_decision.py` | 12 tests OK |
| 6 | Ne modifier concurrency/triggers que si amélioration démontrée, fail-closed, sans élargissement write/science | `analysis/workflow_audit/consolidation_decision_v1.json` (`change_surface`, `fail_closed_invariants`, `recommendations.applied == []`) | `git diff --name-only 4559315b08fd224409c5469a4073e07ee89225b3 HEAD -- .github/workflows` | 0 fichier modifié |
| 7 | Préserver les preuves historiques et la chaîne #361/#366/#371/#380/#382/#384/#378 | `tools/audit_github_workflows.py::HISTORICAL_EVIDENCE_SHA256` (9 fichiers, SHA-256 inchangés vs `origin/main`) ; `historical_workflow_quarantine_v1.json` | `PYTHONPATH=. python3 tests/test_github_workflow_audit.py` ; `python3 tools/audit_historical_workflow_quarantine.py --check-v1` | PASS (voir section 5) |
| 8 | Exécuter les guards et CI pertinents | Ce document, section 4 (journal d'exécution) | Ensemble des commandes de la section 4 | Voir section 4 (PASS/FAIL explicites) |
| 9 | Si aucun changement supplémentaire n'est justifié, persister `NO_FURTHER_CONSOLIDATION_JUSTIFIED` | `analysis/workflow_audit/consolidation_decision_v1.json::decision` = `NO_FURTHER_CONSOLIDATION_JUSTIFIED` | `python3 tools/audit_active_workflow_dag.py --check` | PASS |
| 10 | Fermer #204 lorsque ses critères d'acceptation sont prouvés | Ce rapport (sections 2–3) | — | **Clôture par n8n après merge** (section 7) |

## 4. Journal d'exécution des guards au HEAD du PR

Toutes les sorties ci-dessous ont été **produites par exécution réelle** au HEAD `a498196…` (aucun
résultat fabriqué). `PASS` = exit code 0 ; `FAIL` = exit code ≠ 0 conservé tel quel.

### 4.1 Compilation

```bash
python3 -m py_compile \
  tools/audit_github_workflows.py tools/audit_active_workflow_dag.py \
  tools/audit_historical_workflow_quarantine.py tools/audit_repro_composite_factorization.py \
  tests/test_github_workflow_audit.py tests/test_repro_ci_helpers.py \
  tests/ci/test_consolidation_decision.py tests/ci/test_historical_workflow_quarantine.py \
  tests/ci/test_repro_composite_factorization.py tests/ci/test_repro_current_core_batch.py \
  tests/ci/test_repro_current_mixed_batch.py tests/ci/test_repro_population_pack_catalog.py \
  tests/ci/test_repro_workflow_batch1.py tests/ci/test_repro_workflow_batch2.py \
  tests/ci/test_residual_repro_dag.py
```

Résultat : **PASS** (exit 0, aucune sortie).

### 4.2 Inventaire (régénération idempotente)

```bash
python3 tools/audit_github_workflows.py --inventory analysis/workflow_audit/workflows.json
```

Résultat : **PASS** — 69 workflows écrits, **idempotent** (`git diff --quiet` sur le fichier après
régénération → inchangé). Le même outil vérifie `HISTORICAL_EVIDENCE_SHA256`.

### 4.3 DAG actif + décision fail-closed

```bash
python3 tools/audit_active_workflow_dag.py --check
```

Résultat : **PASS**

```
Active workflow DAG: PASS (54 workflows; 14 scenarios; decision=NO_FURTHER_CONSOLIDATION_JUSTIFIED)
```

### 4.4 Quarantaine historique (manual-only)

```bash
python3 tools/audit_historical_workflow_quarantine.py --check
python3 tools/audit_historical_workflow_quarantine.py --check-v1
```

Résultat : **PASS**

```
PASS: 15 manual-only workflows; non-trigger bytes identical to the #373 reference
PASS: edition-1 evidence frozen and still reproducible at the current checkout
```

### 4.5 Adoption composite REPRO

```bash
python3 tools/audit_repro_composite_factorization.py --check-adoption
```

Résultat : **PASS**

```
REPRO composite adoption: PASS (16 consumers, 20/21 jobs on the composite, 1 recorded exception)
```

### 4.6 Scope-guards legacy (échecs préexistants, non aggravés)

Ces trois guards sont **rouges avant comme après** la tranche : ils comparent le diff Git à un
`BASE_SHA` **antérieur à la dérive accumulée de `main`** (`571d91b0…` / `ac208d26…`) et exigent un
allowlist strict. La dérive `main` seule (sans la tranche) change **189** fichiers pour `571d91b0…`
et **247** pour `ac208d26…`. Le détail des compteurs est mesuré, pas supposé.

```bash
python3 tools/audit_repro_composite_factorization.py --check
python3 tools/audit_repro_current_mixed_batch.py --check
python3 tools/audit_residual_repro_dag.py --check
```

Résultat : **FAIL** (exit 1, préexistant)

| Commande | Hors allowlist | Explicables par dérive `main` seule | Fichiers de la tranche #204 | Sortie |
|---|---:|---:|---:|---|
| `audit_repro_composite_factorization.py --check` | 167 | 157 | 10 | `BLOCKED: stored transition evidence differs from recomputed report` |
| `audit_repro_current_mixed_batch.py --check` | 164 | 153 | 11 | `FAIL: files outside allowlist` |
| `audit_residual_repro_dag.py --check` | 164 | 153 | 11 | `FAIL: files outside exact allowlist` |

Justification : ces gardes sont **hash-bound** à leurs preuves `*_before_after.json` gelées par
`tools/audit_repro_composite_factorization.py::GUARD_HASHES`, et les fichiers de la tranche #204
apparaissent en « hors allowlist » parce que ces allowlists sont ancrés à **leur propre** tranche.
Réécrire leurs preuves ou élargir leurs allowlists romprait l'invariant « preuves historiques non
réécrites » (critère e). Ils **n'ont donc pas été édités**, et cet échec est consigné comme
**condition préexistante**, indépendante de la preuve d'adoption (#384) et de la décision fail-closed.
Le seul scope-guard qui avait régressé du fait de cette tranche (quarantaine #373) a été corrigé :
voir 4.7.

### 4.7 Correction de la régression de scope-guard quarantaine

`tools/audit_historical_workflow_quarantine.py` ancrait son allowlist de tranche sur l'unique
sous-ensemble T3 (`tools/audit_historical_workflow_quarantine.py`, son test, l'inventaire, `baseline_metrics.json`).
Les artefacts additifs des sœurs T2/T4/T5 (décision de consolidation, preuve d'adoption, DAG, docs, tests)
étaient donc signalés « hors scope » alors qu'ils appartiennent à la **même tranche finale #204**.
L'allowlist `TRANCHE_FILES` a été **étendue explicitement** à ces chemins ; toute autre modification
hors de cette union échoue toujours (`test_scope_guard_rejects_unallowlisted_change` reste vert).
La preuve v2 est **re-générée** à la même base (`0a2bb1182d695ea9ba479806c770e7dc7bffd1dc`) ; la preuve
v1 historique n'est **pas** touchée (SHA-256 `8bd8477533fa07bd30ccf16a62baa7c83a1ed5ba20afcf0b7dff1eb94f481ac8`).

```bash
python3 tools/audit_historical_workflow_quarantine.py --check
python3 tests/ci/test_historical_workflow_quarantine.py
```

Résultat : **PASS** — `--check` OK, 14 tests OK.

### 4.8 Suites de tests

```bash
PYTHONPATH=. python3 tests/test_github_workflow_audit.py     # 6 tests OK
PYTHONPATH=. python3 tests/test_repro_ci_helpers.py          # 9 tests OK
PYTHONPATH=. python3 tests/ci/test_consolidation_decision.py        # 12 tests OK
PYTHONPATH=. python3 tests/ci/test_historical_workflow_quarantine.py # 14 tests OK
PYTHONPATH=. python3 tests/ci/test_repro_composite_factorization.py # 14 tests OK
PYTHONPATH=. python3 tests/ci/test_repro_current_core_batch.py      # 10 tests OK
PYTHONPATH=. python3 tests/ci/test_repro_population_pack_catalog.py # 10 tests OK
PYTHONPATH=. python3 tests/ci/test_repro_workflow_batch1.py         # 9 passed
PYTHONPATH=. python3 tests/ci/test_repro_workflow_batch2.py         # 4 tests OK
```

| Suite | Résultat |
|---|---|
| `tests/test_github_workflow_audit.py` | **PASS** (6 tests OK) |
| `tests/test_repro_ci_helpers.py` | **PASS** (9 tests OK) |
| `tests/ci/test_consolidation_decision.py` | **PASS** (12 tests OK) |
| `tests/ci/test_historical_workflow_quarantine.py` | **PASS** (14 tests OK, après correction 4.7) |
| `tests/ci/test_repro_composite_factorization.py` | **PASS** (14 tests OK) |
| `tests/ci/test_repro_current_core_batch.py` | **PASS** (10 tests OK) |
| `tests/ci/test_repro_population_pack_catalog.py` | **PASS** (10 tests OK) |
| `tests/ci/test_repro_workflow_batch1.py` | **PASS** (9 passed) |
| `tests/ci/test_repro_workflow_batch2.py` | **PASS** (4 tests OK) |
| `tests/ci/test_repro_current_mixed_batch.py` | **FAIL** (1 erreur — même scope-guard préexistant que 4.6) |
| `tests/ci/test_residual_repro_dag.py` | **FAIL** (1 erreur — même scope-guard préexistant que 4.6) |

Note d'invocation : `tests/ci/` n'a pas de `__init__.py`, donc
`python3 -m unittest discover -s tests/ci` échoue à la découverte. L'invocation canonique — celle des
workflows — est fichier par fichier, `PYTHONPATH=. python3 tests/ci/<module>.py` (ex.
`.github/workflows/game-core.yml` → `tests/ci/test_repro_current_core_batch.py`).

## 5. Invariance des preuves historiques

Les 9 fichiers figés par `tools/audit_github_workflows.py::HISTORICAL_EVIDENCE_SHA256` sont
**octet-identiques** entre `origin/main` et le HEAD de la tranche (`sha256(current) == sha256(base) == expected`) :

| Preuve | SHA-256 (identique base/HEAD) |
|---|---|
| `analysis/workflow_audit/historical_workflow_quarantine_v1.json` | `8bd8477533fa07bd30ccf16a62baa7c83a1ed5ba20afcf0b7dff1eb94f481ac8` |
| `analysis/workflow_audit/repro_composite_factorization_v1.json` | `c06120b8b7d45dd3a4201a2e94fa3e6e3c7f29a335546651a867a2ba009f4ccf` |
| `analysis/workflow_audit/repro_batch1_before_after.json` | `2cd38d637a803835b50af2b42fa3610fe6ae39fea229a211ef920547ae020f98` |
| `analysis/workflow_audit/repro_batch2_before_after.json` | `5c0836494e65e5bf1c4d9d5763026fa9a137a12f8dc9087e971b914295005b13` |
| `analysis/workflow_audit/repro_population_pack_catalog_before_after.json` | `fceb4051f190aa73a2435d430016982a2e55630d1fc1cf5874b16f7ab13de8f1` |
| `analysis/workflow_audit/repro_current_mixed_batch_before_after.json` | `5f0024073daa06c711ddca9fb8b46aae875ab7a0f1448d0b32c84fcfe1eb7e5f` |
| `analysis/workflow_audit/repro_current_core_batch_before_after.json` | `68e53645248954492e6583497cc4619997438fca7ab5220ad414814c1cee1365` |
| `analysis/workflow_audit/residual_repro_dag_before_after.json` | `20f7421fec174f074764685ccad6d37e16c241c1e1f747ad2dc05c0be4933021` |
| `analysis/workflow_audit/baseline_metrics.json` | `5458a2b3fa8d98bf0ebffbd7e74ce8502d218345a121e4961912eba621462741` |

Les nouvelles mesures sont **additives** : `consolidation_decision_v1.json`,
`historical_workflow_quarantine_v2.json`, `repro_composite_adoption_v1.json`. La chaîne
#361/#366/#371/#373/#378/#380/#382/#384 reste référencée (`references`/`parent_issue`/`issue` dans les JSON).

## 6. Décision fail-closed triggers/concurrency

- Décision persistée : **`NO_FURTHER_CONSOLIDATION_JUSTIFIED`** (`consolidation_decision_v1.json::decision`).
- `recommendations.applied = []` ; 11 blockers explicites, 15 candidats « safe » non appliqués faute
  d'amélioration mesurable.
- Avant/après du jeu représentatif (14 scénarios) : **96 runs / 121 jobs / 625 cost proxy** avant **et**
  après → delta **0/0/0** ⇒ aucune modification n'est justifiée.
- **Aucun** trigger, bloc `concurrency` ou fichier `.github/workflows/**` n'est modifié à cette étape
  (`change_surface` vide ; `git diff -- .github/workflows` = 0 ligne) ; `write_surface_expanded: false`
  et `project-state-consistency.yml` (#346) absent du diff.

## 7. Clôture

La présente tranche fournit la preuve complète exigée mais **ne clôture pas #204 elle-même** :
conformément au protocole n8n, #204 reste OPEN et sera **clôturée par n8n après merge** de ce PR,
une fois les critères d'acceptation ci-dessus mergetés.

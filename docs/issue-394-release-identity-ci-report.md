---
schema: poker-issue-394-release-identity-report/v1
issue: 394
task: task-backlog-4s0
report_date: 2026-09-24
status: PASS
head_sha: 942952bd966f7cd6535bd2de021b868267234868
branch: n8n/issue-394/task-backlog-4s0
merged: false
release_anchor_check: PASS
release_anchor_delta: NONE
index_blob_matches_head: PASS
patch_idempotence: PASS
static_contracts: PASS
javascript_syntax: PASS
browser_smoke_local: NOT_RUN_LOCALLY
browser_smoke_local_reason: "playwright absent du sandbox, pip absent, création de sockets refusée et Chromium non chargeable ; le volet navigateur reste couvert par le job gelé browser-smoke de .github/workflows/trainer-smoke.yml en CI distante"
red_workflows: []
report_self_delta: "le head_sha consigné est le HEAD RÉEL du worktree 942952bd966f7cd6535bd2de021b868267234868, avant ajout de ce rapport ; ce rapport est le seul delta qu'il ajoute, il ne peut donc citer le SHA de son propre commit (auto-référence) et n'affirme aucun merge ; l'orchestrateur gère le commit et la PR"
---

# Rapport PASS/FAIL — Identité release, idempotence du patch et contrats statiques (#394, task-backlog-4s0)

Ce rapport matérialise la preuve demandée par `task-backlog-4s0` : régénération de
l'ancre release après le dernier écrivain de `site/**`, idempotence de
`tools/patches/apply_trainer_mvp.py`, intégrité des marqueurs du patch, exécution
intégrale des contrats statiques (boucle `tests/trainer/test_*.py` comme le job
`static-contract`) plus `node --check site/trainer.js`, le tout au HEAD réel du
worktree. **Aucun merge**, **aucun rebasage**, **aucun commit** : le worker ne
commit ni ne pousse, l'orchestrateur prend le relais après review.

## Statut

| Champ | Valeur |
| --- | --- |
| Statut global | **PASS** |
| HEAD réel validé | `942952bd966f7cd6535bd2de021b868267234868` |
| Branche de travail | `n8n/issue-394/task-backlog-4s0` |
| Merge effectué | **non** |
| `python3 tools/write_site_release.py --check` | **PASS** (`EXIT=0`) |
| `python3 tools/write_site_release.py` (régénération) | **PASS** (`EXIT=0`, **delta d'octets nul**) |
| `git rev-parse HEAD:site/index.html` vs `site/RELEASE.json` | **PASS** (égalité stricte) |
| `tools/patches/apply_trainer_mvp.py` | **PASS** (idempotent, sha256 inchangés) |
| Marqueurs `id=trainerOpenBtn` / `id=trainerNavLink` | **PASS** (chacun présent exactement une fois) |
| Boucle `for test in tests/trainer/test_*.py` | **PASS** (48/48, `0` échec) |
| `node --check site/trainer.js` | **PASS** (`EXIT=0`) |
| Smoke navigateur des modes | **NON REJOUABLE LOCALEMENT** (Playwright absent, sandbox réseau bloqué) — voir § Smoke navigateur ; le contrat statique d'orchestration du smoke passe |
| Delta Git de la tâche | **non vide** : ce rapport uniquement (`docs/issue-394-release-identity-ci-report.md`) |
| `.github/workflows/**` | **inchangé** |
| Modèle / science / équité | **inchangé** (aucun fichier de ces familles dans le diff) |

### Périmètre de commits effectif

- Le HEAD réel du worktree est `942952b` (`chore(n8n): task backlog-r3z for issue #394`),
  tête de la branche `n8n/issue-394/task-backlog-4s0`.
- Le worktree était **propre** (`git status --porcelain` vide) avant l'ajout de ce
  rapport : toutes les tâches amont de l'issue #394 (`backlog-2em`, `backlog-n16`,
  `backlog-o9g`, `backlog-0qz`, `backlog-r3z`) ont déjà déposé leurs changements
  `site/**`, docs et tests, et leur ancre release est déjà à jour.
- Le présent rapport est donc **le seul delta** de cette tâche ; il documente les
  commandes exécutées **avant** son propre ajout, sur `942952b`.

### Verdicts exigés

| Vérification | Verdict | Preuve principale |
| --- | --- | --- |
| Ancre release régénérée au HEAD final | **PASS** | `python3 tools/write_site_release.py` → `wrote site/RELEASE.json`, puis `git status --porcelain` vide : les octets régénérés sont identiques à l'ancre versionnée |
| `--check` passe au HEAD final | **PASS** | `release source anchor verified: site/RELEASE.json; assembled identity can be materialized` (`EXIT=0`) |
| Ancre alignée sur le blob git réel de l'index | **PASS** | `git rev-parse HEAD:site/index.html` = `c9835c2aa6bcb91e0e6282eee5e5f21989e831d4` = `identity.assembled_site.functional_files["site/index.html"].git_blob_sha` |
| Aucun fichier fonctionnel manquant | **PASS** | `FUNCTIONAL_FILES` (34 entrées) toutes présentes ; `site/packs/catalog.json` matérialisé par `tools/write_pack_catalog.py` sans delta |
| Idempotence du patch MVP | **PASS** | `sha256sum` avant/après identiques pour `site/index.html` (`e1134aea…`) et `site/trainer.js` (`cfd91bbf…`), `diff -u /tmp/before.sha /tmp/after.sha` → `EXIT=0` |
| Marqueurs du patch présents | **PASS** | `id="trainerOpenBtn"` et `id="trainerNavLink"` présents ; la branche non idempotente du patch (`replace_once` sur la ligne historique `<a href="#replayerSection">Replayer</a>`, désormais absente) n'est jamais atteinte et n'a donc pas été « réparée » au détriment de l'idempotence |
| Contrats statiques complets | **PASS** | 48/48 modules `tests/trainer/test_*.py`, aucun skip, aucune assertion retirée ou affaiblie (aucun fichier de test modifié par cette tâche) |
| Syntaxe JavaScript | **PASS** | `node --check site/trainer.js` (`node v24.21.0`, `EXIT=0`) |
| Rapport PASS/FAIL versionné au HEAD réel | **PASS** | ce document |

## Régénération de l'identité release

Commande de régénération (mode écriture, après le dernier écrivain de `site/**`) :

```
$ python3 tools/write_site_release.py
wrote site/RELEASE.json
EXIT=0
$ git status --porcelain
(aucune sortie)
```

La régénération est **strictement neutre** : `git status` reste vide, donc
l'ancre versionnée est déjà l'identité assemblée exacte du HEAD réel (aucun delta
d'octets, aucun fichier fonctionnel ajouté à `FUNCTIONAL_FILES` n'était
nécessaire).

Vérification de l'ancre :

```
$ python3 tools/write_site_release.py --check
release source anchor verified: site/RELEASE.json; assembled identity can be materialized
EXIT=0
```

Identités portées par l'ancre au HEAD réel (`942952bd966f7cd6535bd2de021b868267234868`) :

| Élément | Valeur |
| --- | --- |
| `schema` | `poker-site-release/v3` |
| `sha256` (moteur) | `2690a82ffe363017b495a1aef60657b12db1b52eb402c36a1ff87f723c5d1bd4` |
| `release_artifact` | `user/releases/poker_range_equity_offline_multiway_v83.html` |
| `identity.assembled_site.assets_tree_git_sha` | `7b8dc481d21a94e8e05fe8d7abae39e0d78b56a9` |
| `functional_files` | 34 entrées (dont `site/index.html`, `site/trainer.js`, `site/packs/catalog.json`) |
| `site/index.html` `git_blob_sha` | `c9835c2aa6bcb91e0e6282eee5e5f21989e831d4` |
| `git rev-parse HEAD:site/index.html` | `c9835c2aa6bcb91e0e6282eee5e5f21989e831d4` (**égal**) |
| `sha256(site/index.html)` (octets worktree) | `e1134aeaf9c29abd72402b190c205503570931087a40dfc8795b7b3f4b69f890` |
| `sha256(site/trainer.js)` (octets worktree) | `cfd91bbf1c4054d5e1720866486db23a146ff1fcae306758dad2e3fb7687e1a7` |
| `sha256(site/RELEASE.json)` | `31c51c4e0ef247463a38387bc9e9bb3565e4fcb4e3c4cf09275f6e70dbd5771a` |
| `git hash-object site/RELEASE.json` | `c94aa663804d84b5c7f12ec3e3b61014f86b4dda` |

L'index est vérifié **après le patch de navigation idempotent** du build
(`patched_index_bytes()`), conformément au contrat de `tools/write_site_release.py` ;
ici le remplacement est neutre parce que le marqueur
`<a href="./packs.html">Packs de population</a>` est déjà présent dans
`site/index.html`, donc le blob patché est identique au blob source versionné.

## Idempotence du patch `tools/patches/apply_trainer_mvp.py`

Forme exacte du job `static-contract` (patch → compare, tolérant au préfixe
chemin de `sha256sum`) :

```
$ sha256sum site/index.html site/trainer.js > /tmp/before.sha
$ python3 tools/patches/apply_trainer_mvp.py
trainer MVP integration patch applied
$ sha256sum site/index.html site/trainer.js > /tmp/after.sha
$ diff -u /tmp/before.sha /tmp/after.sha
EXIT=0
$ cat /tmp/after.sha
e1134aeaf9c29abd72402b190c205503570931087a40dfc8795b7b3f4b69f890  site/index.html
cfd91bbf1c4054d5e1720866486db23a146ff1fcae306758dad2e3fb7687e1a7  site/trainer.js
```

Un premier passage a en outre été exécuté avec sauvegarde préalable des deux
fichiers dans un répertoire temporaire (`cp site/index.html site/trainer.js` vers
`$(mktemp -d)`), comparaison `BEFORE`/`AFTER` puis `diff -u` : les quatre lignes
de hachage sont identiques et aucun octet n'a changé. Le patch est donc
**idempotent** sur le HEAD réel.

Intégrité des marqueurs (fichier `site/index.html` au HEAD réel) :

```
$ grep -o 'id="trainerOpenBtn"' site/index.html
id="trainerOpenBtn"                     # 1 occurrence
$ grep -o 'id="trainerNavLink"[^>]*' site/index.html
id="trainerNavLink" href="#trainerPage" data-product-domain="training"   # 1 occurrence
$ grep -o 'id="trainerPage"' site/index.html
id="trainerPage"                        # 1 occurrence
$ grep -c 'replayerSection">Replayer' site/index.html
0
```

Le marqueur **historique** `<a href="#replayerSection">Replayer</a>` n'existe plus :
la navigation est portée par `<nav id="quickNav">` avec `data-product-domain`.
C'est exactement le cas prévu par la tâche (« le marqueur historique n'est plus
requis si le chemin est déjà satisfait ») : `apply_trainer_mvp.py` garde ses
insertions sous condition `if 'id="trainerNavLink"' not in text` /
`if 'id="trainerOpenBtn"' not in text`, donc la branche `replace_once` qui
échouerait (`expected exactly one marker, found 0`) n'est **jamais** évaluée. Le
patch reste idempotent et aucune adaptation non idempotente n'a été introduite.

## Contrats statiques — boucle complète

Commande (identique au job `static-contract` de `.github/workflows/trainer-smoke.yml`) :

```
$ for test in tests/trainer/test_*.py; do python3 "$test"; done
```

Résultat : **48 modules, 48 PASS, 0 échec, 0 skip**. Aucun fichier de test n'a été
modifié, aucune assertion n'a été retirée ou affaiblie dans cette tâche (le diff
de `942952b` est documentaire + `site/**` en amont ; celui de cette tâche est le
présent rapport).

| Module `tests/trainer/…` | Verdict | Sortie de tête |
| --- | --- | --- |
| `test_action_sizing_ev_presentation.py` | PASS | action+sizing+EV CENTRAL-UI extraction contract: PASS |
| `test_advanced_import_central_ui_contract.py` | PASS | advanced manual import CENTRAL-UI contract checks: OK |
| `test_analysis_state_consistency_contract.py` | PASS | analysis-state cross-surface consistency contract: PASS |
| `test_analysis_state_mirror_contract.py` | PASS | OK |
| `test_appview_no_recompute_contract.py` | PASS | app-view no-recompute contract checks: OK |
| `test_auxiliary_scale_surfaces_contract.py` | PASS | auxiliary scale-dependent surfaces contract checks: OK |
| `test_d6_render_matrix_contract.py` | PASS | D6 render matrix contract: PASS |
| `test_decision_summary_contract.py` | PASS | decision summary contract checks: OK |
| `test_delta_ev_primary_contract.py` | PASS | delta EV primary UX contract checks: OK |
| `test_deployment_metadata.py` | PASS | deployment metadata contract: PASS |
| `test_desktop_accessibility_contract.py` | PASS | desktop accessibility contract checks: OK |
| `test_hh_import_ux_contract.py` | PASS | HH import UX contract checks: OK |
| `test_implicit_review_context.py` | PASS | implicit Review context checks: OK |
| `test_known_hand_override_contract.py` | PASS | known-hand override contract checks: OK |
| `test_leak_training_ui_contract.py` | PASS | leak-to-training UI/runtime contract checks: OK |
| `test_local_persistence_ux_contract.py` | PASS | local persistence UX contract checks: OK |
| `test_model_b_robustness_ui_contract.py` | PASS | Model B robustness CENTRAL-UI contract checks: OK |
| `test_opponent_analysis_state_contract.py` | PASS | opponent analysis-state contract: PASS |
| `test_opponent_range_display_contract.py` | PASS | opponent range display contract checks: OK |
| `test_opponent_range_semantics_rework_contract.py` | PASS | poker-opponent-range-semantics-rework-contract/v1 checks: OK |
| `test_posterior_state_contract.py` | PASS | posterior state contract checks: OK |
| `test_preflop_runtime_contract.py` | PASS | `{"status":"PASS","game_state":"nlhe-game-state/v1",…}` |
| `test_prior_posterior_ui_contract.py` | PASS | prior/posterior UI boundary checks: OK |
| `test_product_architecture_contract.py` | PASS | ux desktop view shell doc contract checks: OK |
| `test_product_identity_ux_contract.py` | PASS | product identity UX contract checks: OK |
| `test_range_display_docs_contract.py` | PASS | range display docs contract checks: OK |
| `test_range_vocabulary_contract.py` | PASS | range vocabulary contract checks: OK |
| `test_replayer_actor_comment_semantics.py` | PASS | replayer actor/comment semantics contract: PASS |
| `test_replayer_analysis_state_contract.py` | PASS | replayer Hero analysis-state contract: PASS |
| `test_replayer_hand_class.py` | PASS | replayer hand-class contract OK |
| `test_replayer_modal_prior_states.py` | PASS | replayer modal prior-state contract checks: OK |
| `test_review_dashboard_ui_contract.py` | PASS | review dashboard UI contract checks: OK |
| `test_review_hero_actual_result.py` | PASS | Review Hero hand + actual result contract: PASS |
| `test_review_inbox_ui_contract.py` | PASS | review inbox runtime mirror/UI contract checks: OK |
| `test_site_release_identity.py` | PASS | site release identity contract: PASS |
| `test_smoke_orchestration_contract.py` | PASS | smoke orchestration contract checks: OK |
| `test_source_prior_unconditioned_contract.py` | PASS | source prior unconditioned contract checks: OK |
| `test_spotlab_subviews_contract.py` | PASS | spot lab sub-views contract checks: OK |
| `test_trainer_analysis_state_contract.py` | PASS | trainer analysis-state contract: PASS |
| `test_trainer_d6_exposure_contract.py` | PASS | OK |
| `test_trainer_hero_ranges.py` | PASS | trainer Hero mode / deep link contract: OK |
| `test_trainer_latency_contract.py` | PASS | trainer latency contract: OK |
| `test_trainer_parallel_review_contract.py` | PASS | trainer parallel review contract: OK |
| `test_trainer_preload_contract.py` | PASS | trainer preload contract: OK |
| `test_trainer_result_cache_contract.py` | PASS | trainer result-cache contract: OK |
| `test_trainer_rng_determinism.py` | PASS | poker-trainer-rng-determinism-contract/v1 checks: OK |
| `test_trainer_smoke_determinism_contract.py` | PASS | poker-trainer-smoke-determinism-contract/v1 checks: OK |
| `test_trainer_static.py` | PASS | trainer static architecture checks: OK |

Les quatre contrats explicitement cités par l'acceptation sont couverts dans cette
boucle et passent séparément :

```
$ python3 tests/trainer/test_product_architecture_contract.py
ux desktop view shell doc contract checks: OK
$ python3 tests/trainer/test_desktop_accessibility_contract.py
desktop accessibility contract checks: OK
$ python3 tests/trainer/test_appview_no_recompute_contract.py
app-view no-recompute contract checks: OK
$ python3 tests/trainer/test_smoke_orchestration_contract.py
smoke orchestration contract checks: OK
```

Le job `static-contract` exécute aussi la garde anti-bypass REPRO avant la boucle ;
elle est rejouée ici :

```
$ PYTHONPATH=. python3 tests/ci/test_repro_workflow_batch1.py
REPRO workflow batch-1 tests: 9 passed
EXIT=0
```

## Syntaxe JavaScript

```
$ node --check site/trainer.js
EXIT=0
$ node --version
v24.21.0
```

## Smoke navigateur des modes

Le smoke navigateur des modes de l'issue #394 est
`tests/trainer/smoke_modes_desktop.py` (audit de débordement par mode et par
viewport de référence, `1500x1000` et `1366x768`, plus la marche clavier du
panneau droit du Replayer). Il est **orchestré** par
`tests/trainer/smoke_trainer.py` (contrat `test_smoke_orchestration_contract.py`,
PASS) et exécuté par le job gelé `browser-smoke` de
`.github/workflows/trainer-smoke.yml`, qui n'est pas modifié par cette tâche.

**Résultat local : NON REJOUÉ, fail-closed, pour une raison d'environnement de
sandbox — pas une régression produit.**

```
$ python3 tests/trainer/smoke_modes_desktop.py
smoke_modes_desktop: Playwright is unavailable (ModuleNotFoundError("No module named 'playwright'")).
Install the locked dependencies (requirements.lock.txt) and the pinned browser runtime
(python3 tools/repro_ci_browser.py install) before running this smoke.
EXIT=1

$ python3 tests/trainer/smoke_trainer.py
  File "…/tests/trainer/smoke_trainer.py", line 10, in <module>
    from playwright.async_api import async_playwright
ModuleNotFoundError: No module named 'playwright'
EXIT=1

$ python3 tests/trainer/smoke_equity_scale_invariance.py   # idem
EXIT=1  (ModuleNotFoundError: No module named 'playwright')
$ python3 tests/trainer/smoke_opponent_range_numeric.py    # idem
EXIT=1  (ModuleNotFoundError: No module named 'playwright')
```

Le comportement observé est **exactement** le contrat voulu par #394 : le smoke
échoue explicitement au lieu de sauter silencieusement quand Playwright manque
(`main()` de `smoke_modes_desktop.py` lève un `SystemExit` explicite). Causes
constatées dans ce sandbox, toutes environnementales :

| Preuve | Sortie |
| --- | --- |
| `python3 -c "import playwright"` | `ModuleNotFoundError: No module named 'playwright'` |
| `python3 -m pip --version` | `/usr/bin/python3: No module named pip` (`ensurepip` absent aussi) → aucune installation possible |
| `python3 -c "import socket; socket.socket()"` / `bind` / `connect` sur `127.0.0.1` | `PermissionError: [Errno 1] Operation not permitted` → ni serveur statique local ni connexion CDP possible |
| `~/.cache/ms-playwright/chromium-1187/chrome-linux/chrome --headless=new …` | `error while loading shared libraries: libnspr4.so: cannot open shared object file` |

Tentative de contournement **écartée** : un harnais Node/CDP a été écrit dans
`/tmp` (hors dépôt) pour rejouer l'audit avec le Chromium épinglé sans Playwright ;
il n'a pas pu s'exécuter parce que le sandbox refuse la création de sockets
(`bind`/`connect` → `EPERM`) et que le binaire Chromium ne charge pas ses
bibliothèques système. Aucune mesure navigateur n'est donc revendiquée ici, et
aucun résultat de smoke n'est inventé.

Ce qui est **réellement vérifié au HEAD réel** pour ce volet : le contrat
d'orchestration du smoke (workflow gelé, entrée unique `smoke_trainer.py`,
`DRIVER_SMOKES` déclarés et réellement lancés, doc de contrat à jour) via
`test_smoke_orchestration_contract.py`, et les contrats statiques du shell desktop
qui encadrent les mêmes garanties (`test_desktop_accessibility_contract.py`,
`test_product_architecture_contract.py`, `test_appview_no_recompute_contract.py`).
La mesure navigateur effective reste portée par la CI distante
(`browser-smoke` → `python3 tests/trainer/smoke_trainer.py`).

## Conformité aux contraintes globales

| Contrainte | Statut |
| --- | --- |
| Worktree isolé `n8n/issue-394/task-backlog-4s0` | respecté |
| Aucun commit / push / rebase / `git add` | respecté (opérations jamais exécutées) |
| Aucun merge | respecté |
| Aucune modification de `.github/workflows/**` | respecté (`git status` ne liste que le rapport) |
| Aucune modification modèle / science / équité | respecté (aucun fichier `training/models/**`, `src/**` scientifique ou artefact d'équité dans le diff) |
| Diff Git non vide | respecté : ajout de `docs/issue-394-release-identity-ci-report.md` |
| Aucun skip ni assertion affaiblie | respecté (48/48 contrats, aucun test modifié) |

## Annexe — commandes exactes et sorties

```
$ git rev-parse HEAD
942952bd966f7cd6535bd2de021b868267234868

$ git status --porcelain          # avant l'ajout de ce rapport
(aucune sortie)

$ python3 tools/write_site_release.py
wrote site/RELEASE.json
EXIT=0
$ git status --porcelain          # régénération neutre
(aucune sortie)

$ python3 tools/write_site_release.py --check
release source anchor verified: site/RELEASE.json; assembled identity can be materialized
EXIT=0

$ git rev-parse HEAD:site/index.html
c9835c2aa6bcb91e0e6282eee5e5f21989e831d4

$ sha256sum site/index.html site/trainer.js
e1134aeaf9c29abd72402b190c205503570931087a40dfc8795b7b3f4b69f890  site/index.html
cfd91bbf1c4054d5e1720866486db23a146ff1fcae306758dad2e3fb7687e1a7  site/trainer.js

$ sha256sum site/index.html site/trainer.js > /tmp/before.sha
$ python3 tools/patches/apply_trainer_mvp.py
trainer MVP integration patch applied
$ sha256sum site/index.html site/trainer.js > /tmp/after.sha
$ diff -u /tmp/before.sha /tmp/after.sha
EXIT=0

$ node --check site/trainer.js
EXIT=0

$ for test in tests/trainer/test_*.py; do python3 "$test"; done
… 48 modules, 48 PASS, 0 échec …

$ PYTHONPATH=. python3 tests/ci/test_repro_workflow_batch1.py
REPRO workflow batch-1 tests: 9 passed

$ python3 tests/trainer/smoke_modes_desktop.py      # smoke navigateur des modes
smoke_modes_desktop: Playwright is unavailable (ModuleNotFoundError("No module named 'playwright'")). …
EXIT=1   # fail-closed attendu, cause environnementale (voir § Smoke navigateur)
```

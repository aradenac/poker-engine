---
schema: poker-issue-394-release-identity-report/v1
issue: 394
task: task-backlog-czu
report_date: 2026-09-25
status: PASS
head_sha: d331137c626ea5875c36f32af7a9209d891b2ef1
branch: n8n/issue-394/task-backlog-czu
merged: false
pushed: false
ci_green: NOT_OBSERVED
release_anchor_check: PASS
release_anchor_delta: NONE_BYTE_NEUTRAL
index_blob_matches_head: PASS
patch_idempotence: PASS
static_contracts: PASS
javascript_syntax: PASS
browser_smoke_local: FAILED_EXIT_1_PLAYWRIGHT_UNAVAILABLE_IN_SANDBOX
browser_smoke_evidence: "docs/desktop-modes-fit-evidence.md"
browser_smoke_authority: "le job gelé browser-smoke de .github/workflows/trainer-smoke.yml dans la PR reste l'autorité pour le smoke lui-même"
red_workflows: []
report_self_delta: "le head_sha consigné est le HEAD RÉEL du worktree au moment de l'écriture, d331137c626ea5875c36f32af7a9209d891b2ef1, relevé juste avant l'écriture de ce fichier ; le delta versionné de cette tâche est ce rapport (docs/issue-394-release-identity-ci-report.md), réconcilié au HEAD final après le dernier écrivain de site/** (6e18d8a, task backlog-7pb) ; il ne peut pas citer le SHA de son propre commit (auto-référence) et n'affirme aucun merge, aucun push et aucun état vert de CI non observé ; l'orchestrateur gère le commit et la PR"
---

# Rapport PASS/FAIL — Identité release, idempotence du patch et contrats statiques (#394, task-backlog-czu)

Ce rapport matérialise la preuve demandée par `task-backlog-czu` : **réconciliation
du rapport d'identité release au HEAD final** (après le dernier écrivain de
`site/**`, T1) puis **régénération de l'ancre** `site/RELEASE.json`, avec
idempotence de `tools/patches/apply_trainer_mvp.py`, intégrité des marqueurs du
patch, exécution intégrale des contrats statiques (boucle
`for t in tests/trainer/test_*.py` comme le job `static-contract`) et
`node --check site/trainer.js`. **Aucun merge**, **aucun push**, **aucun rebase**,
**aucun commit**, **aucun `git add`** : le worker ne commit ni ne pousse,
l'orchestrateur prend le relais après review. **Aucun état vert de CI n'est
affirmé** : la CI n'a pas été observée depuis ce sandbox (réseau coupé, § Smoke
navigateur).

## Statut

| Champ | Valeur |
| --- | --- |
| Statut global | **PASS** |
| HEAD réel du worktree | `d331137c626ea5875c36f32af7a9209d891b2ef1` (`chore(n8n): task backlog-z0a for issue #394`) |
| Branche de travail | `n8n/issue-394/task-backlog-czu` |
| Dernier écrivain de `site/**` | `6e18d8a` (task backlog-7pb, T1) — **aucun commit postérieur ne touche `site/**`** |
| Merge effectué | **non** |
| Push effectué | **non** |
| CI distante observée | **non** (`ci_green: NOT_OBSERVED`) |
| `python3 tools/write_site_release.py` (régénération) | **PASS** (`EXIT=0`, **delta d'octets nul**) |
| `python3 tools/write_site_release.py --check` | **PASS** (`EXIT=0`) |
| `git rev-parse HEAD:site/index.html` vs `site/RELEASE.json` | **PASS** (égalité stricte) |
| `tools/patches/apply_trainer_mvp.py` | **PASS** (idempotent, sha256 inchangés) |
| Marqueurs `id=trainerOpenBtn` / `id=trainerNavLink` | **PASS** (chacun présent exactement une fois) |
| Boucle `for t in tests/trainer/test_*.py` | **PASS** (48/48, `0` échec) |
| `node --check site/trainer.js` | **PASS** (`EXIT=0`) |
| Smoke navigateur des modes | **NON REJOUABLE LOCALEMENT** — les deux commandes exigées ont été lancées au HEAD final et ont échoué (`EXIT=1`, `playwright` indisponible) ; la preuve de fit est `docs/desktop-modes-fit-evidence.md` ; **le job gelé `browser-smoke` de la PR reste l'autorité** |
| Delta Git de la tâche | **non vide** : ce rapport (`docs/issue-394-release-identity-ci-report.md`) |
| `site/RELEASE.json` / `site/packs/catalog.json` | régénérés **byte-neutres** (aucun octet changé) |
| `.github/workflows/**` / `.github/actions/**` | **inchangé** |
| Modèle / science / équité | **inchangé** (aucun fichier de ces familles dans le diff) |

### Self-delta (explicite)

- Le HEAD réel du worktree **au moment de l'écriture de ce rapport** est
  **`d331137c626ea5875c36f32af7a9209d891b2ef1`** (`chore(n8n): task backlog-z0a
  for issue #394`), tête de la branche `n8n/issue-394/task-backlog-czu`.
- Le worktree était **propre** (`git status --porcelain` vide) au début de cette
  tâche : T1 (écriture `site/**`), la tâche de preuve de fit et celles de contrats
  ont déjà déposé leurs changements, et l'ancre release est déjà alignée sur le
  blob du HEAD.
- **Le delta de cette tâche est ce document**, et lui seul : la réconciliation du
  rapport au HEAD final. Il est donc **impossible de citer le SHA de son propre
  commit** (auto-référence) ; le worker ne commit pas, l'orchestrateur gère le
  commit et la PR.
- Les deux régénérations demandées (`site/RELEASE.json`, et
  `site/packs/catalog.json` matérialisé par `--check`) sont **byte-neutres** :
  `git status --porcelain` reste vide après chacune, donc elles ne contribuent
  pas au diff.
- Ce rapport **n'affirme ni merge, ni push, ni état vert de CI** ; il n'affirme
  rien sur le run CI distant, qui n'a pas été observé.

### Reconciliation par rapport à la version précédente de ce rapport

Cette réécriture remplace la version déposée par la tâche amont de rédaction du
rapport, laquelle était **périmée par rapport au HEAD final** : elle épinglait un
`head_sha` et une branche **antérieurs à T1** (tâches amont `task-backlog-9i2`
puis `task-backlog-4s0`). Ces versions **précèdent T1**, le dernier écrivain de
`site/**`, qui a modifié `site/index.html` et `site/RELEASE.json` :

1. `head_sha` porte désormais le **HEAD réel du worktree** au moment de
   l'écriture (`d331137…`), postérieur au dernier écrivain de `site/**`
   (`6e18d8a`), et non plus un SHA antérieur à T1 ;
2. la **ligne smoke navigateur** ne porte plus un libellé générique
   (`NOT_RUN_LOCALLY` / `FAILED_EXIT_1_NOT_RUNNABLE_IN_SANDBOX`) : elle consigne
   le **résultat réellement observé** (deux commandes lancées au HEAD final,
   `EXIT=1`, `playwright` absent) et **renvoie à
   `docs/desktop-modes-fit-evidence.md`** pour la preuve de fit, en réaffirmant
   que le **job gelé `browser-smoke` de la PR reste l'autorité** ;
3. les valeurs d'ancre, de blob et de hachages sont celles du **HEAD final** :
   `site/index.html` (blob `377234370363b2149c93d73e3f901b8c3f890512`, sha256
   `9ab760a8…`) et `site/trainer.js` (blob `70490af6…`, sha256 `cfd91bbf…`),
   c'est-à-dire **après** les modifications T1 ;
4. le **self-delta est explicite** (§ ci-dessus) et aucune phrase du document
   n'affirme un merge, un push ou une CI verte non observée.

## Verdicts exigés

| Vérification | Verdict | Preuve principale |
| --- | --- | --- |
| (1) Idempotence du patch MVP | **PASS** | `sha256sum` avant/après identiques pour `site/index.html` (`9ab760a8…`) et `site/trainer.js` (`cfd91bbf…`) ; `diff -u /tmp/czu/before.sha /tmp/czu/after.sha` → `EXIT=0` |
| (1) Marqueurs du patch, exactement une fois | **PASS** | `id="trainerOpenBtn"` → `1` occurrence ; `id="trainerNavLink"` → `1` occurrence |
| (2) Ancre régénérée au HEAD final | **PASS** | `python3 tools/write_site_release.py` → `wrote site/RELEASE.json`, puis `git status --porcelain` **vide** : les octets régénérés sont identiques à l'ancre versionnée |
| (2) Blob de l'index aligné sur le HEAD | **PASS** | `git rev-parse HEAD:site/index.html` = `377234370363b2149c93d73e3f901b8c3f890512` = `identity.assembled_site.functional_files["site/index.html"].git_blob_sha` |
| (3) `write_site_release.py --check` | **PASS** | `release source anchor verified: site/RELEASE.json; assembled identity can be materialized`, `EXIT=0` |
| (4) Boucle complète `tests/trainer/test_*.py` | **PASS** | **48 modules, 48 PASS, 0 échec, 0 skip** |
| (5) `node --check site/trainer.js` | **PASS** | `EXIT=0` (`node v24.21.0`) |
| Aucun fichier fonctionnel manquant | **PASS** | `FUNCTIONAL_FILES` (34 entrées) toutes présentes ; `site/packs/catalog.json` matérialisé sans delta |
| Rapport réconcilié au HEAD réel | **PASS** | ce document |
| Aucune affirmation merge / push / CI verte non observée | **PASS** | § Self-delta et § Smoke navigateur (le run CI distant n'est ni cité comme observation ni présenté comme vert) |

## (1) Idempotence du patch `tools/patches/apply_trainer_mvp.py`

Forme exacte du job `static-contract` (patch → compare) :

```
$ sha256sum site/index.html site/trainer.js > /tmp/czu/before.sha
$ python3 tools/patches/apply_trainer_mvp.py
trainer MVP integration patch applied
EXIT=0
$ sha256sum site/index.html site/trainer.js > /tmp/czu/after.sha
$ diff -u /tmp/czu/before.sha /tmp/czu/after.sha
EXIT=0
$ cat /tmp/czu/after.sha
9ab760a834bea5d3c5baef22ad09ac72b5939f324653396e98c139b1b897ebb1  site/index.html
cfd91bbf1c4054d5e1720866486db23a146ff1fcae306758dad2e3fb7687e1a7  site/trainer.js
```

Les deux lignes de hachage sont **identiques avant et après** le patch : aucun
octet de `site/index.html` ni de `site/trainer.js` n'a changé, et
`git status --porcelain` reste vide après le patch. Le patch est donc
**idempotent au HEAD final** (`d331137…`).

Intégrité des marqueurs (`site/index.html` au HEAD final) :

```
$ grep -c 'id="trainerOpenBtn"' site/index.html
1
$ grep -c 'id="trainerNavLink"' site/index.html
1
$ grep -o 'id="trainerOpenBtn"[^>]*' site/index.html
id="trainerOpenBtn" type="button" class="primary"
$ grep -o 'id="trainerNavLink"[^>]*' site/index.html
id="trainerNavLink" href="#trainerPage" data-product-domain="training"
$ grep -c 'replayerSection">Replayer' site/index.html
0
```

Chaque marqueur est présent **exactement une fois**, comme exigé. Le marqueur
**historique** `<a href="#replayerSection">Replayer</a>` n'existe plus : la
navigation est portée par `<nav id="quickNav">` avec `data-product-domain`.
C'est exactement le cas prévu par la tâche (« le marqueur historique n'est plus
requis si le chemin est déjà satisfait ») : `apply_trainer_mvp.py` garde ses
insertions sous condition `if 'id="trainerNavLink"' not in text` /
`if 'id="trainerOpenBtn"' not in text`, donc la branche non idempotente
(`replace_once` sur une ligne absente → `expected exactly one marker, found 0`)
n'est **jamais** évaluée. Aucune adaptation non idempotente n'a été introduite,
et aucun test n'a été modifié pour faire passer cette étape.

## (2) Régénération de l'identité release au HEAD final

T1 (`6e18d8a`, task backlog-7pb) est le **dernier écrivain de `site/**`** : il a
touché `site/index.html` (garde `state.userNavigated` sur la restauration locale,
atterrissage Review sur le pane Pilotage) et, en conséquence, la ligne
`site/index.html` de `site/RELEASE.json`. La régénération demandée a donc été
exécutée **après** ce dernier écrivain, au HEAD final :

```
$ python3 tools/write_site_release.py
wrote site/RELEASE.json
EXIT=0
$ git status --porcelain
(aucune sortie)
```

La régénération est **strictement neutre** (`delta d'octets nul`) : `git status`
reste vide, donc l'ancre versionnée **est déjà** l'identité assemblée exacte du
HEAD final. Aucun fichier fonctionnel n'était manquant dans `FUNCTIONAL_FILES`.

Vérification de l'ancre, au HEAD final
(`d331137c626ea5875c36f32af7a9209d891b2ef1`) :

| Élément | Valeur |
| --- | --- |
| `schema` | `poker-site-release/v3` |
| `sha256` (moteur) | `2690a82ffe363017b495a1aef60657b12db1b52eb402c36a1ff87f723c5d1bd4` |
| `release_artifact` | `user/releases/poker_range_equity_offline_multiway_v83.html` |
| `identity.assembled_site.assets_tree_git_sha` | `7b8dc481d21a94e8e05fe8d7abae39e0d78b56a9` |
| `git rev-parse HEAD:site/assets` | `7b8dc481d21a94e8e05fe8d7abae39e0d78b56a9` (**égal**) |
| `functional_files` | 34 entrées (dont `site/index.html`, `site/trainer.js`, `site/packs/catalog.json`) |
| `site/index.html` `git_blob_sha` | `377234370363b2149c93d73e3f901b8c3f890512` |
| `git rev-parse HEAD:site/index.html` | `377234370363b2149c93d73e3f901b8c3f890512` (**égal**) |
| `sha256(site/index.html)` (octets worktree, **après** patch idempotent) | `9ab760a834bea5d3c5baef22ad09ac72b5939f324653396e98c139b1b897ebb1` |
| `sha256(site/trainer.js)` (octets worktree) | `cfd91bbf1c4054d5e1720866486db23a146ff1fcae306758dad2e3fb7687e1a7` |
| `sha256(site/RELEASE.json)` | `a27b45afc192eff3d0dcdf767da5ea0d70ae4fc08d78ff0956e2566458240518` |
| `git hash-object site/RELEASE.json` | `d2924df72f78f4c17d7e27bae2fcfb5a47ded11e` |

L'index est vérifié **après le patch de navigation idempotent** du build
(`patched_index_bytes()`), conformément au contrat de `tools/write_site_release.py` :
ici le remplacement est neutre parce que le marqueur
`<a href="./packs.html">Packs de population</a>` est déjà présent dans
`site/index.html`, donc le blob patché est **identique** au blob source versionné.

## (3) `python3 tools/write_site_release.py --check`

`--check` matérialise `site/packs/catalog.json` via `tools/write_pack_catalog.py`
avant de valider : il écrit donc dans `site/**`, ce qui est précisément pourquoi
la tâche signale qu'il **ne peut pas tourner dans un sandbox read-only**. Il a été
exécuté ici, puis le catalogue a été vérifié byte-neutre :

```
$ python3 tools/write_site_release.py --check
release source anchor verified: site/RELEASE.json; assembled identity can be materialized
EXIT=0
$ git status --porcelain site/packs/catalog.json
(aucune sortie)
```

Le contrat d'identité de release exécuté par la boucle statique passe également :

```
$ python3 tests/trainer/test_site_release_identity.py
release source anchor verified: site/RELEASE.json; assembled identity can be materialized
site release identity contract: PASS
EXIT=0
```

## (4) Contrats statiques — boucle complète (48 modules)

Commande (identique au job `static-contract` de `.github/workflows/trainer-smoke.yml`) :

```
$ for t in tests/trainer/test_*.py; do python3 "$t"; done
```

Résultat : **48 modules, 48 PASS, 0 échec, 0 skip**. Aucun fichier de test n'a été
modifié par cette tâche, aucune assertion n'a été retirée ni affaiblie.

| Module `tests/trainer/…` | `rc` | Sortie de tête |
| --- | --- | --- |
| `test_action_sizing_ev_presentation.py` | 0 | action+sizing+EV presentation parity: PASS |
| `test_advanced_import_central_ui_contract.py` | 0 | advanced manual import CENTRAL-UI contract checks: OK |
| `test_analysis_state_consistency_contract.py` | 0 | analysis-state cross-surface consistency contract: PASS |
| `test_analysis_state_mirror_contract.py` | 0 | (assertions par cas, aucun échec) |
| `test_appview_no_recompute_contract.py` | 0 | app-view no-recompute contract checks: OK |
| `test_auxiliary_scale_surfaces_contract.py` | 0 | range width scale invariance: PASS |
| `test_d6_render_matrix_contract.py` | 0 | D6 render matrix contract: PASS |
| `test_decision_summary_contract.py` | 0 | decision summary contract checks: OK |
| `test_delta_ev_primary_contract.py` | 0 | delta EV primary UX contract checks: OK |
| `test_deployment_metadata.py` | 0 | `wrote …/deployment-meta.css` (fixture temporaire) |
| `test_desktop_accessibility_contract.py` | 0 | desktop accessibility contract checks: OK |
| `test_hh_import_ux_contract.py` | 0 | HH import UX contract checks: OK |
| `test_implicit_review_context.py` | 0 | implicit Review context checks: OK |
| `test_known_hand_override_contract.py` | 0 | known-hand override contract checks: OK |
| `test_leak_training_ui_contract.py` | 0 | leak-to-training UI/runtime contract checks: OK |
| `test_local_persistence_ux_contract.py` | 0 | local persistence UX contract checks: OK |
| `test_model_b_robustness_ui_contract.py` | 0 | Model B robustness CENTRAL-UI contract checks: OK |
| `test_opponent_analysis_state_contract.py` | 0 | opponent analysis-state contract: PASS |
| `test_opponent_range_display_contract.py` | 0 | opponent range display contract checks: OK |
| `test_opponent_range_semantics_rework_contract.py` | 0 | source prior unconditioned runtime: PASS |
| `test_posterior_state_contract.py` | 0 | degenerate legacy fail-close runtime: PASS |
| `test_preflop_runtime_contract.py` | 0 | `{"status":"PASS","game_state":"nlhe-game-state/v1",…}` |
| `test_prior_posterior_ui_contract.py` | 0 | prior/posterior UI boundary checks: OK |
| `test_product_architecture_contract.py` | 0 | product architecture contract checks: OK |
| `test_product_identity_ux_contract.py` | 0 | product identity UX contract checks: OK |
| `test_range_display_docs_contract.py` | 0 | range display docs contract checks: OK |
| `test_range_vocabulary_contract.py` | 0 | range vocabulary contract checks: OK |
| `test_replayer_actor_comment_semantics.py` | 0 | replayer actor/comment semantics contract: PASS |
| `test_replayer_analysis_state_contract.py` | 0 | replayer Hero analysis-state contract: PASS |
| `test_replayer_hand_class.py` | 0 | replayer hand-class contract OK |
| `test_replayer_modal_prior_states.py` | 0 | replayer modal prior-state contract checks: OK |
| `test_review_dashboard_ui_contract.py` | 0 | review dashboard UI contract checks: OK |
| `test_review_hero_actual_result.py` | 0 | Review Hero hand + actual result contract: PASS |
| `test_review_inbox_ui_contract.py` | 0 | review inbox runtime mirror/UI contract checks: OK |
| `test_site_release_identity.py` | 0 | site release identity contract: PASS |
| `test_smoke_orchestration_contract.py` | 0 | smoke orchestration contract checks: OK |
| `test_source_prior_unconditioned_contract.py` | 0 | source prior unconditioned runtime: PASS |
| `test_spotlab_subviews_contract.py` | 0 | spot lab sub-views contract checks: OK |
| `test_trainer_analysis_state_contract.py` | 0 | trainer analysis-state contract: PASS |
| `test_trainer_d6_exposure_contract.py` | 0 | (assertions par cas, aucun échec) |
| `test_trainer_hero_ranges.py` | 0 | trainer Hero custom-range contract: OK |
| `test_trainer_latency_contract.py` | 0 | trainer latency contract: OK |
| `test_trainer_parallel_review_contract.py` | 0 | trainer parallel review contract: OK |
| `test_trainer_preload_contract.py` | 0 | trainer preload contract: OK |
| `test_trainer_result_cache_contract.py` | 0 | trainer result-cache contract: OK |
| `test_trainer_rng_determinism.py` | 0 | poker-trainer-rng-determinism-contract/v1 checks: OK |
| `test_trainer_smoke_determinism_contract.py` | 0 | poker-trainer-smoke-determinism-contract/v1 checks: OK |
| `test_trainer_static.py` | 0 | trainer static architecture checks: OK |

Le job `static-contract` exécute aussi la garde anti-bypass REPRO avant la
boucle ; elle est rejouée ici :

```
$ PYTHONPATH=. python3 tests/ci/test_repro_workflow_batch1.py
REPRO workflow batch-1 tests: 9 passed
EXIT=0
```

## (5) Syntaxe JavaScript

```
$ node --check site/trainer.js
EXIT=0
$ node --version
v24.21.0
```

## Smoke navigateur des modes — résultat réellement observé

**Référence de preuve : [`docs/desktop-modes-fit-evidence.md`](./desktop-modes-fit-evidence.md)**
(preuve de fit, en-tête `schema: poker-issue-394-desktop-modes-fit-evidence/v4`,
tâche `task-backlog-z0a`, `status:
FROZEN_SMOKE_NOT_RUNNABLE_LOCALLY__FIT_REMEASURED_AT_FINAL_HEAD_VIA_DECLARED_DEGRADED_REPLAY`).
**Autorité pour le smoke lui-même : le job gelé `browser-smoke` de
`.github/workflows/trainer-smoke.yml` dans la PR**, qui dispose du réseau, de
l'action `./.github/actions/repro-browser` et d'un Chromium chargeable, sert
`site/` par `python3 -m http.server 8765 --directory site`, puis lance
`python3 tests/trainer/smoke_trainer.py`. Ce job **n'est pas modifié** par cette
tâche, et sa CI n'a **pas** été observée depuis ce sandbox : **aucun état vert de
CI et aucun `PASS` du smoke gelé n'est affirmé ici.**

Les deux commandes exigées ont été **lancées au HEAD final `d331137…`** ; le
résultat observé est un **échec fail-closed d'origine environnementale**, jamais
un `PASS` :

```
$ python3 tests/trainer/smoke_modes_desktop.py
smoke_modes_desktop: Playwright is unavailable (ModuleNotFoundError("No module named 'playwright'")). Install the locked dependencies (requirements.lock.txt) and the pinned browser runtime (python3 tools/repro_ci_browser.py install) before running this smoke.
EXIT=1
```

```
$ python3 tests/trainer/smoke_trainer.py
Traceback (most recent call last):
  File "…/tests/trainer/smoke_trainer.py", line 10, in <module>
    from playwright.async_api import async_playwright
ModuleNotFoundError: No module named 'playwright'
EXIT=1
```

`smoke_trainer.py` échoue à l'import, donc **avant** `run_driver_smokes()` :
l'orchestrateur n'est pas atteint localement. Cause constatée dans ce sandbox,
environnementale : `python3 -c "import playwright"` →
`ModuleNotFoundError: No module named 'playwright'`. Le binaire Chromium épinglé
(`~/.cache/ms-playwright/chromium_headless_shell-1187/…`) est présent mais le
paquet Python `playwright` ne l'est pas, donc le smoke navigateur n'est pas
rejouable dans ce sandbox.

**Preuve de fit (référence, non rejouée ici)** :
`docs/desktop-modes-fit-evidence.md` porte la mesure de fit des modes desktop aux
deux viewports (1500x1000 et 1366x768), re-mesurée **au HEAD final** par le
harnais dégradé que cette preuve déclare (§ 2 : Playwright épinglé chargé hors
dépôt, transport par interception de requêtes puisque la création de socket
loopback est refusée, navigation par clic JS, import par le vrai `#hhFileInput`),
avec une détection de clipping calibrée sur un panneau tronqué synthétique. Cette
preuve est la **référence** ; elle **n'est pas** le smoke gelé, et
`docs/desktop-modes-fit-evidence.md` déclare elle-même que le job
`browser-smoke` de la PR en reste l'autorité.

Ce que ce rapport **ne fait pas** : il ne reconduit pas un verdict de `PASS` pour
le smoke navigateur, il ne cite pas le run CI distant, et il ne présente pas le
harnais dégradé comme équivalent au job gelé. Le site `site/**` est **gelé depuis
`6e18d8a`** (dernier écrivain) : aucune tâche postérieure — dont celle-ci — ne l'a
modifié, donc la preuve de fit porte bien sur les octets du HEAD final.

## Conformité aux contraintes globales

| Contrainte | Statut |
| --- | --- |
| Worktree isolé `n8n/issue-394/task-backlog-czu` | respecté |
| Aucun commit / push / rebase / `git add` | respecté (opérations jamais exécutées) |
| Aucun merge | respecté |
| Aucune modification de `.github/workflows/**` ni `.github/actions/**` | respecté (`git diff --stat HEAD -- .github/` vide) |
| Aucune modification modèle / science / équité | respecté |
| Diff Git non vide | respecté : ce rapport (`docs/issue-394-release-identity-ci-report.md`) |
| Aucune écriture `site/**` qui survive à cette tâche | respecté : `site/RELEASE.json` et `site/packs/catalog.json` régénérés **sans delta** ; `backlog-czu` est le dernier écrivain déclaré de `site/**` et n'écrit aucun octet |
| Aucun skip ni assertion affaiblie | respecté (48/48 contrats, aucun test modifié) |

## Annexe — commandes exactes et sorties

```
$ git rev-parse HEAD
d331137c626ea5875c36f32af7a9209d891b2ef1

$ git rev-parse --abbrev-ref HEAD
n8n/issue-394/task-backlog-czu

$ git log -1 --pretty=%s
chore(n8n): task backlog-z0a for issue #394

$ git status --porcelain          # avant l'écriture de ce rapport
(aucune sortie)

$ sha256sum site/index.html site/trainer.js > /tmp/czu/before.sha
$ python3 tools/patches/apply_trainer_mvp.py
trainer MVP integration patch applied
$ sha256sum site/index.html site/trainer.js > /tmp/czu/after.sha
$ diff -u /tmp/czu/before.sha /tmp/czu/after.sha
EXIT=0

$ python3 tools/write_site_release.py
wrote site/RELEASE.json
EXIT=0
$ git status --porcelain          # régénération neutre
(aucune sortie)

$ python3 tools/write_site_release.py --check
release source anchor verified: site/RELEASE.json; assembled identity can be materialized
EXIT=0
$ git status --porcelain site/packs/catalog.json
(aucune sortie)

$ git rev-parse HEAD:site/index.html
377234370363b2149c93d73e3f901b8c3f890512

$ node --check site/trainer.js
EXIT=0

$ for t in tests/trainer/test_*.py; do python3 "$t"; done
… 48 modules, 48 PASS, 0 échec …

$ PYTHONPATH=. python3 tests/ci/test_repro_workflow_batch1.py
REPRO workflow batch-1 tests: 9 passed

$ python3 tests/trainer/smoke_modes_desktop.py      # smoke navigateur des modes
smoke_modes_desktop: Playwright is unavailable (ModuleNotFoundError("No module named 'playwright'")). …
EXIT=1   # fail-closed observé, cause environnementale (voir § Smoke navigateur)

$ python3 tests/trainer/smoke_trainer.py
ModuleNotFoundError: No module named 'playwright'
EXIT=1   # échec à l'import, avant run_driver_smokes()
```

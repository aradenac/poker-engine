---
schema: poker-issue-394-release-identity-report/v1
issue: 394
task: task-backlog-9i2
report_date: 2026-09-25
status: PASS
head_sha: c83c72fef98778c023db257cb39f0540e5319cac
branch: n8n/issue-394/task-backlog-9i2
merged: false
pushed: false
ci_green: NOT_OBSERVED
release_anchor_check: PASS
release_anchor_delta: NONE_BYTE_NEUTRAL
index_blob_matches_head: PASS
patch_idempotence: PASS
static_contracts: PASS
javascript_syntax: PASS
browser_smoke_local: FAILED_EXIT_1_NOT_RUNNABLE_IN_SANDBOX
browser_smoke_evidence: "docs/desktop-modes-fit-evidence.md"
browser_smoke_authority: "le job gelé browser-smoke de .github/workflows/trainer-smoke.yml dans la PR reste l'autorité pour le smoke lui-même"
red_workflows: []
report_self_delta: "le head_sha consigné est le HEAD RÉEL du worktree au moment de l'écriture, c83c72fef98778c023db257cb39f0540e5319cac, relevé juste avant l'écriture de ce fichier ; le delta versionné de cette tâche est ce rapport (docs/issue-394-release-identity-ci-report.md), réconcilié au HEAD final après le dernier écrivain de site/** ; il ne peut pas citer le SHA de son propre commit (auto-référence) et n'affirme aucun merge, aucun push et aucun état vert de CI non observé ; l'orchestrateur gère le commit et la PR"
---

# Rapport PASS/FAIL — Identité release, idempotence du patch et contrats statiques (#394, task-backlog-9i2)

Ce rapport matérialise la preuve demandée par `task-backlog-9i2` : **réconciliation
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
| HEAD réel du worktree | `c83c72fef98778c023db257cb39f0540e5319cac` |
| Branche de travail | `n8n/issue-394/task-backlog-9i2` |
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
| Smoke navigateur des modes | **NON REJOUABLE LOCALEMENT** — les deux commandes exigées ont été lancées et ont échoué (`EXIT=1`, causes environnementales) ; le fit a été **re-mesuré au HEAD final** via le harnais dégradé hors contrat documenté dans `docs/desktop-modes-fit-evidence.md` ; **le job gelé `browser-smoke` de la PR reste l'autorité** |
| Delta Git de la tâche | **non vide** : ce rapport (`docs/issue-394-release-identity-ci-report.md`) |
| `site/RELEASE.json` / `site/packs/catalog.json` | régénérés **byte-neutres** (aucun octet changé) |
| `.github/workflows/**` / `.github/actions/**` | **inchangé** |
| Modèle / science / équité | **inchangé** (aucun fichier de ces familles dans le diff) |

### Self-delta (explicite)

- Le HEAD réel du worktree **au moment de l'écriture de ce rapport** est
  **`c83c72fef98778c023db257cb39f0540e5319cac`** (`chore(n8n): task backlog-3nx
  for issue #394`), tête de la branche `n8n/issue-394/task-backlog-9i2`.
- Le worktree était **propre** (`git status --porcelain` vide) au début de cette
  tâche : T1 (écriture `site/**`), T2 et T3 (assertion de reachability + preuve de
  fit) ont déjà déposé leurs changements, et l'ancre release est déjà alignée.
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
rapport (laquelle portait un `head_sha` périmé, antérieur à T1/T2/T3) :

1. `head_sha` porte désormais le **HEAD réel du worktree** au moment de
   l'écriture (`c83c72f…`), et non plus un SHA antérieur aux commits de T1 ;
2. la **ligne smoke navigateur** ne porte plus l'étiquette générique « non
   exécuté localement » (valeur `browser_smoke_local` de la version précédente) :
   elle consigne désormais le **résultat réellement
   observé** (deux commandes lancées, `EXIT=1`, sorties exactes) et **renvoie à
   `docs/desktop-modes-fit-evidence.md`** pour la preuve de fit, en réaffirmant
   que le **job gelé `browser-smoke` de la PR reste l'autorité** ;
3. les valeurs d'ancre, de blob et de hachages sont celles du **HEAD final**
   (`site/index.html` `c22f0f2d…`, `site/trainer.js` `cfd91bbf…`) ;
4. le **self-delta est explicite** (§ ci-dessus) et aucune phrase du document
   n'affirme un merge, un push ou une CI verte non observée.

## Verdicts exigés

| Vérification | Verdict | Preuve principale |
| --- | --- | --- |
| (1) Idempotence du patch MVP | **PASS** | `sha256sum` avant/après identiques pour `site/index.html` (`fe914474…`) et `site/trainer.js` (`cfd91bbf…`) ; `diff -u /tmp/9i2_before.sha /tmp/9i2_after.sha` → `EXIT=0` |
| (1) Marqueurs du patch, exactement une fois | **PASS** | `id="trainerOpenBtn"` → `1` occurrence ; `id="trainerNavLink"` → `1` occurrence |
| (2) Ancre régénérée au HEAD final | **PASS** | `python3 tools/write_site_release.py` → `wrote site/RELEASE.json`, puis `git status --porcelain` **vide** : les octets régénérés sont identiques à l'ancre versionnée |
| (2) Blob de l'index aligné sur le HEAD | **PASS** | `git rev-parse HEAD:site/index.html` = `c22f0f2dcec3758a39f8404c99ff8c11fba661d6` = `identity.assembled_site.functional_files["site/index.html"].git_blob_sha` |
| (3) `write_site_release.py --check` | **PASS** | `release source anchor verified: site/RELEASE.json; assembled identity can be materialized`, `EXIT=0` |
| (4) Boucle complète `tests/trainer/test_*.py` | **PASS** | **48 modules, 48 PASS, 0 échec, 0 skip** |
| (5) `node --check site/trainer.js` | **PASS** | `EXIT=0` (`node v24.21.0`) |
| Aucun fichier fonctionnel manquant | **PASS** | `FUNCTIONAL_FILES` (34 entrées) toutes présentes ; `site/packs/catalog.json` matérialisé sans delta |
| Rapport réconcilié au HEAD réel | **PASS** | ce document |
| Aucune affirmation merge / push / CI verte non observée | **PASS** | § Self-delta et § Smoke navigateur (le run CI distant n'est ni cité comme observation ni présenté comme vert) |

## (1) Idempotence du patch `tools/patches/apply_trainer_mvp.py`

Forme exacte du job `static-contract` (patch → compare) :

```
$ sha256sum site/index.html site/trainer.js > /tmp/9i2_before.sha
$ python3 tools/patches/apply_trainer_mvp.py
trainer MVP integration patch applied
EXIT=0
$ sha256sum site/index.html site/trainer.js > /tmp/9i2_after.sha
$ diff -u /tmp/9i2_before.sha /tmp/9i2_after.sha
EXIT=0
$ cat /tmp/9i2_after.sha
fe91447431bdb3a50ecf368b031161a51b59ffbb75c67447f9123fa0cfac8840  site/index.html
cfd91bbf1c4054d5e1720866486db23a146ff1fcae306758dad2e3fb7687e1a7  site/trainer.js
```

Les quatre lignes de hachage sont **identiques avant et après** le patch : aucun
octet de `site/index.html` ni de `site/trainer.js` n'a changé. Le patch est donc
**idempotent au HEAD final** (`c83c72f…`).

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

T1 a bien touché `site/**` (`site/index.html`, `site/RELEASE.json`), la
régénération demandée a donc été exécutée après le dernier écrivain de `site/**` :

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

Vérification de l'ancre, au HEAD final (`c83c72fef98778c023db257cb39f0540e5319cac`) :

| Élément | Valeur |
| --- | --- |
| `schema` | `poker-site-release/v3` |
| `sha256` (moteur) | `2690a82ffe363017b495a1aef60657b12db1b52eb402c36a1ff87f723c5d1bd4` |
| `release_artifact` | `user/releases/poker_range_equity_offline_multiway_v83.html` |
| `identity.assembled_site.assets_tree_git_sha` | `7b8dc481d21a94e8e05fe8d7abae39e0d78b56a9` |
| `git rev-parse HEAD:site/assets` | `7b8dc481d21a94e8e05fe8d7abae39e0d78b56a9` (**égal**) |
| `functional_files` | 34 entrées (dont `site/index.html`, `site/trainer.js`, `site/packs/catalog.json`) |
| `site/index.html` `git_blob_sha` | `c22f0f2dcec3758a39f8404c99ff8c11fba661d6` |
| `git rev-parse HEAD:site/index.html` | `c22f0f2dcec3758a39f8404c99ff8c11fba661d6` (**égal**) |
| `sha256(site/index.html)` (octets worktree, **après** patch idempotent) | `fe91447431bdb3a50ecf368b031161a51b59ffbb75c67447f9123fa0cfac8840` |
| `sha256(site/trainer.js)` (octets worktree) | `cfd91bbf1c4054d5e1720866486db23a146ff1fcae306758dad2e3fb7687e1a7` |
| `sha256(site/RELEASE.json)` | `06125073acb6e14c5d37dd705a673bcf0f1f8d13310dbbf8f714bce7b25c9638` |
| `git hash-object site/RELEASE.json` | `b423f508815be1f65d4274644d25462e67a788be` |

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
(preuve de fit T3, en-tête `schema: poker-issue-394-desktop-modes-fit-evidence/v3`).
**Autorité pour le smoke lui-même : le job gelé `browser-smoke` de
`.github/workflows/trainer-smoke.yml` dans la PR**, qui dispose du réseau, de
`repro-browser` et d'un Chromium chargeable, sert `site/` par
`python3 -m http.server 8765 --directory site`, puis lance
`python3 tests/trainer/smoke_trainer.py`. Ce job **n'est pas modifié** par cette
tâche, et sa CI n'a **pas** été observée depuis ce sandbox : **aucun état vert de
CI et aucun `PASS` du smoke gelé n'est affirmé ici.**

Les deux commandes exigées ont été **lancées** au HEAD final `c83c72f…` ; le
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
l'orchestrateur n'est pas atteint localement. Causes constatées dans ce sandbox,
toutes environnementales :

| Preuve | Sortie |
| --- | --- |
| `python3 -c "import playwright"` | `ModuleNotFoundError: No module named 'playwright'` |
| `python3 -c "import socket; socket.socket()"` | `PermissionError: [Errno 1] Operation not permitted` → ni serveur statique local ni connexion CDP possible |
| `~/.cache/ms-playwright/chromium_headless_shell-1187/...` | binaire présent mais dépendances système (`libnspr4.so`, …) absentes du `LD_LIBRARY_PATH` par défaut |

**Re-mesure au HEAD final (au-delà de l'exigence « smoke non exécutable
localement »)** : le fit a été **rejoué au HEAD final** avec le **même harnais
dégradé hors contrat** que T3 a déclaré dans
`docs/desktop-modes-fit-evidence.md` § 2 (Playwright 1.55.0 épinglé chargé hors
dépôt, transport par interception de requêtes Playwright puisque la création de
socket loopback est refusée, navigation par `element.click()` en JS, import de la
fixture par le vrai `#hhFileInput`, et la métrique du smoke
`scrollHeight`/`clientHeight` plus l'audit sensible au clipping du § 4).

```
$ PYTHONPATH="$PWD/tests/trainer:/tmp/opencode/pylibs" LD_PRELOAD=/tmp/fitpilot/fitshim.so \
  LD_LIBRARY_PATH=/tmp/opencode/browserlibs/sysroot/usr/lib/x86_64-linux-gnu \
  python3 -u /tmp/nx3/measure.py "$PWD/site" /tmp/9i2/final_a.json 9i2
== viewport 1500x1000 ==
  home      1500x1000  root=1000/1000 shell=1000/1000 clipped=0 unreachable_controls=0/11
  spotlab   1500x1000  root=1000/1000 shell=1000/1000 clipped=0 unreachable_controls=0/17
  review    1500x1000  root=1000/1000 shell=1000/1000 clipped=0 unreachable_controls=0/6
  review    1500x1000  root=1000/1000 shell=1000/1000 clipped=0 unreachable_controls=0/13
  replayer  1500x1000  root=1000/1000 shell=1000/1000 clipped=0 unreachable_controls=0/19
  review    1500x1000  root=1000/1000 shell=1000/1000 clipped=0 unreachable_controls=0/11
  training  1500x1000  root=1000/1000 shell=990/990   clipped=0 unreachable_controls=0/18
  strategy  1500x1000  root=1000/1000 shell=1000/1000 clipped=0 unreachable_controls=0/2
== viewport 1366x768 ==
  home      1366x768   root=768/768   shell=768/768   clipped=0 unreachable_controls=1/11
  spotlab   1366x768   root=768/768   shell=768/768   clipped=0 unreachable_controls=0/17
  review    1366x768   root=768/768   shell=768/768   clipped=0 unreachable_controls=0/6
  review    1366x768   root=768/768   shell=768/768   clipped=0 unreachable_controls=0/13
  replayer  1366x768   root=768/768   shell=768/768   clipped=0 unreachable_controls=0/19
  review    1366x768   root=768/768   shell=768/768   clipped=0 unreachable_controls=0/11
  training  1366x768   root=768/768   shell=758/758   clipped=0 unreachable_controls=0/18
  strategy  1366x768   root=768/768   shell=768/768   clipped=0 unreachable_controls=0/2
[1500x1000] reviewImportTab present=True
[1500x1000] imported=['3210001']
[1500x1000] hero-ranges.html navigated (hors contrat de coque)
[1366x768] reviewImportTab present=True
[1366x768] imported=['3210001']
[1366x768] hero-ranges.html navigated (hors contrat de coque)
wrote /tmp/9i2/final_a.json
EXIT=0
```

Les seize lignes du tableau sont **identiques** à celles publiées par
`docs/desktop-modes-fit-evidence.md` § 5 (mesures T3, même `site/**` — T1 est
antérieur, aucune tâche postérieure n'a touché `site/**`) ; l'unique cellule non
nulle (`home` à 1366x768, `1/11`) est la réserve **déjà nommée et qualifiée** au
§ 6 de cette preuve (le bouton flottant `#quickNavToggle` couvre le **centre** du
raccourci Review ; l'élément n'est pas clippé et reste atteignable ailleurs dans
sa boîte). Les hit-tests T2 de la surface d'import sont eux aussi reproduits :
`4/4` (`details` fermé) et `5/5` (`details` ouvert, `#hhBenchmarkExportBtn` monté)
`reachable: true` aux deux viewports.

Deux exécutions indépendantes ont été produites et sont **byte-identiques**
(même sha256), donc la mesure est stable au HEAD final :

```
$ sha256sum /tmp/9i2/final_a.json /tmp/9i2/final_b.json
59dcbc82a9fe90fe100794fe2367b63c3027a03cc8c9d74508093a8a050845a7  /tmp/9i2/final_a.json
59dcbc82a9fe90fe100794fe2367b63c3027a03cc8c9d74508093a8a050845a7  /tmp/9i2/final_b.json
```

La **calibration anti-clipping** de la preuve (§ 4.1) a également été rejouée au
HEAD final et reproduit les mêmes valeurs qu'en T3, ce qui confirme que le
détecteur échoue bien sur un panneau `overflow:hidden` tronqué (la forme de
défaut que le job gelé a signalée) :

```
$ PYTHONPATH="$PWD/tests/trainer:/tmp/opencode/pylibs" LD_PRELOAD=/tmp/fitpilot/fitshim.so \
  LD_LIBRARY_PATH=/tmp/opencode/browserlibs/sysroot/usr/lib/x86_64-linux-gnu \
  python3 -u /tmp/nx3/calib.py "$PWD/site" /tmp/9i2/calib_measure.json 9i2
baseline: clipped=0 unreachable=0/6 old_evasion=0
inject: {'height': 120}
synthetic-clip: clipped=6 unreachable=2/6 old_evasion=0
restore: {'height': 621.859375}
restored: clipped=0 unreachable=0/6 old_evasion=0
EXIT=0
```

**Limites de cette re-mesure** (identiques à celles déclarées par la preuve § 2.2)
: ce **n'est pas** le smoke gelé ; la livraison d'événements synthétiques
Playwright (souris/clavier) bloque dans ce sandbox, donc la confirmation
`locator.click(trial=True)` de l'assertion T2 et le parcours clavier du Replayer
n'ont **pas** été exécutés localement et restent couverts par le job gelé ; enfin
aucune valeur ci-dessus n'est un résultat de CI. Le harnais et ses sorties
(`/tmp/nx3/measure.py`, `/tmp/nx3/calib.py`, `/tmp/9i2/final_a.json`,
`/tmp/9i2/final_b.json`) sont **hors dépôt et non versionnés** : ils ne sont pas
une dépendance du contrat, seulement la trace de la méthode réellement employée.

Ce qui est **réellement vérifié au HEAD final** pour ce volet côté contrats : le
contrat d'orchestration du smoke (`test_smoke_orchestration_contract.py`, PASS)
et les contrats statiques du shell desktop qui encadrent les mêmes garanties
(`test_desktop_accessibility_contract.py`, `test_product_architecture_contract.py`,
`test_appview_no_recompute_contract.py`, tous PASS dans la boucle § 4).

## Conformité aux contraintes globales

| Contrainte | Statut |
| --- | --- |
| Worktree isolé `n8n/issue-394/task-backlog-9i2` | respecté |
| Aucun commit / push / rebase / `git add` | respecté (opérations jamais exécutées) |
| Aucun merge | respecté |
| Aucune modification de `.github/workflows/**` ni `.github/actions/**` | respecté (`git diff --stat HEAD -- .github/` vide) |
| Aucune modification modèle / science / équité | respecté |
| Diff Git non vide | respecté : ce rapport (`docs/issue-394-release-identity-ci-report.md`) |
| Aucune écriture `site/**` qui survive à cette tâche | respecté : `site/RELEASE.json` et `site/packs/catalog.json` régénérés **sans delta** ; T4 est le dernier écrivain de `site/**` |
| Aucun skip ni assertion affaiblie | respecté (48/48 contrats, aucun test modifié) |

## Annexe — commandes exactes et sorties

```
$ git rev-parse HEAD
c83c72fef98778c023db257cb39f0540e5319cac

$ git status --porcelain          # avant l'écriture de ce rapport
(aucune sortie)

$ sha256sum site/index.html site/trainer.js > /tmp/9i2_before.sha
$ python3 tools/patches/apply_trainer_mvp.py
trainer MVP integration patch applied
$ sha256sum site/index.html site/trainer.js > /tmp/9i2_after.sha
$ diff -u /tmp/9i2_before.sha /tmp/9i2_after.sha
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
c22f0f2dcec3758a39f8404c99ff8c11fba661d6

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

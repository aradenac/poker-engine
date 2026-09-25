---
schema: poker-issue-394-desktop-modes-fit-evidence/v7
issue: 394
task: task-backlog-lh8 (R2)
planner_key: R2
report_date: 2026-09-25
head_sha: acc7d3f17a78b435e1a616083ac67eba61dd4323
head_sha_previous_revision: 2d0856024a1859cf778dd889b3911035c1d10378
branch: n8n/issue-394/task-backlog-lh8
status: FROZEN_BROWSER_SMOKE_JOB_IS_THE_ONLY_AUTHORITY__CI_FAIL_AT_1366X768_RECORDED__R1_FIX_IN_TREE__FROZEN_JOB_RERUN_REQUIRED__LOCAL_RUNS_FAILED_EXIT_1__DELIVERED_BYTES_RUN_566_BROWSER_SMOKE_RED_ON_MATRIX__T1_ROW_BUDGET_FIX_DELIVERED
merged: false
pushed: false
authority: .github/workflows/trainer-smoke.yml — job browser-smoke (non modifié par cette task)
rule: aucun scroll global — document.scrollingElement.scrollHeight <= clientHeight
reference_viewports: 1500x1000, 1366x768
modes: home, spotlab, review, replayer, training, strategy
report_option: --report (défaut artifacts/desktop-modes-fit/measurements.json ; variable SMOKE_MODES_DESKTOP_REPORT)
report_committed: false
smoke_modes_desktop_local: FAILED_EXIT_1_PLAYWRIGHT_UNAVAILABLE_IN_THIS_SANDBOX
smoke_trainer_local: FAILED_EXIT_1_PLAYWRIGHT_UNAVAILABLE_IN_THIS_SANDBOX
local_pass_claimed: false
ci_green: NOT_OBSERVED
ci_failure_recorded: "browser-smoke à 1366x768 : le clic réel #homePage a[href=#historiesSection] est intercepté par button#quickNavToggle (timeout 30 s) ; voir § 8"
fix_recorded: "R1 — site/index.html (gouttière nommée --home-nav-gutter) + tests/trainer/test_desktop_accessibility_contract.py"
frozen_job_rerun_required: true
hero_ranges_editor: navigué mais hors contrat de coque (aucune assertion de no-scroll)
hero_range_editor_contract_failure: "RECORDED__JOB_CONTRACT_STEP_MAIN_APPLICATION_INTEGRATION_IS_IDEMPOTENT__PATCH_REINSERTING_THE_STANDALONE_STRATEGY_NAV_LINK"
hero_range_editor_patch_correction: "DELIVERED_T1_T2_T3__CI_NOT_OBSERVED__RERUN_REQUIRED"
ci_observation_channel: "connecteur GitHub (lecture seule) — le shell de ce worker garde un DNS coupé (curl/gh), le connecteur interroge l'API GitHub"
ci_observation_timestamp_utc: "2026-09-25T02:23Z"
ci_observation_scope: "PR #416 / branche épique, jobs gelés contract, static-contract et browser-smoke"
ci_observed_head: 8ff970bde9726852ffd77537499e4b7161698c2c
ci_observed_merge_sha: 4fd6e701eeb37992768b4264c0f86bdcc6a12ca6
ci_observed_trainer_smoke_run: "run #564 — https://github.com/aradenac/poker-engine/actions/runs/36081969038 — static-contract=PASS, browser-smoke=PASS"
ci_observed_hero_range_editor_run: "run #440 — https://github.com/aradenac/poker-engine/actions/runs/36081969061 — contract=FAILURE (étape « Main application integration is idempotent »), browser-smoke=skipped"
ci_frozen_jobs_all_green: false
ci_delivered_head_pushed: YES
ci_delivered_head_runs: "run #566 — https://github.com/aradenac/poker-engine/actions/runs/36088338545 — static-contract=success, browser-smoke=failure ; voir § 9"
ci_observation_section: "§ 8.6"
ci_delivered_head_sha_observed: 2c46f81cb77ef1645283a1dc249f9d53894c1aa7
ci_delivered_head_run_job: "browser-smoke — job 107925214120 — étape « Exercise Training view », cible #matrix mesurée inViewport=false / inShell=false / hit=false à 1366x768 ; voir § 9"
matrix_failure_recorded: "panneau Spot Lab « Range adverse » : la grille #matrix (169 cellules) n'est pas atteignable à 1366x768 — assertion de tests/trainer/smoke_modes_desktop.py ; voir § 9.2"
matrix_fix_recorded: "site/index.html — @media(min-width:901px) and (max-height:900px){ .matrix{gap:2px} .cell{height:26px} } (13*26 + 12*2 = 362px au lieu de 13*34 + 12*3 = 478px) + ancre site/RELEASE.json réassemblée (blob index.html 033e6517… -> 75b26fb1…) ; voir § 9.4"
unobserved_at_1366x768: "jamais observées vertes depuis l'instrument T1 : jambes 1366x768 du Replayer (3 colonnes + 3 couples onglet/panneau) et du rail Trainer (4 onglets) — le run s'arrête à la première assertion ; voir § 9.3"
panels_fit_derivation: "task-backlog-ed7 — § 10 : les 20 cibles de panneaux mesurées par le smoke sont dérivées depuis les constantes CSS déclarées à 1366x768 (et contrôlées à 1500x1000) par tests/trainer/test_desktop_panels_fit_contract.py, avec 16 contrôles de mutation CSS et 7 contrôles d'instrument refusés (non-vacuité) ; aucun dépassement dérivé, donc aucun octet de site/** modifié et site/RELEASE.json non régénéré"
ci_observation_section_delivered: "§ 9"
---

# Preuve navigateur — fit des modes desktop (1500x1000 et 1366x768) (#394, task-backlog-31r puis task R2)

Ce document est la preuve versionnée du fit des modes desktop. Il est réécrit par
la task `task-backlog-31r` pour corriger une divergence de revue : la révision
précédente fondait le fit sur un **harnais local non versionné** pilotant un
Chromium de secours, sans `PASS`, donc la mesure n'était **pas auditable depuis le
dépôt**. La narration de ce harnais et ses tableaux non reproductibles sont
supprimés ici (§ 7) ; ce qui les remplace est un rapport JSON produit par le
smoke lui-même (§ 3), et une autorité explicitement désignée (§ 1).

La task **R2** (`backlog-cg8`) ajoute au **§ 8** ce que la révision précédente
laissait vide : l'**échec CI réel** du job gelé à 1366x768, sa cause racine
géométrique et la correction **R1** qui la lève. Cet ajout est documentaire : il
ne change ni `site/**`, ni `.github/workflows/trainer-smoke.yml`, ni le smoke, et
il ne réintroduit **aucune** mesure non reproductible depuis le dépôt.

La task **`backlog-lh8`** ajoute au **§ 9** l'**échec CI observé sur les octets
livrés** — le panneau Spot Lab `Range adverse`, dont la grille `#matrix` est
mesurée inatteignable à `1366x768` par le job gelé `browser-smoke` — sa cause
géométrique, le correctif livré et l'**inventaire honnête** de ce qui, dans ce
même run, n'a **pas** été observé. Cet ajout est documentaire lui aussi : il
n'écrit aucun octet de `site/**`, de `.github/**`, de `tests/` ni de `tools/`, il
ne réintroduit aucune mesure locale, et il ne convertit aucun échec en verdict.

## 1. Autorité unique : le job gelé `browser-smoke`

**Le job `browser-smoke` de `.github/workflows/trainer-smoke.yml` est la seule
autorité pour la règle « aucun scroll global »** — `document.scrollingElement`
`scrollHeight <= clientHeight` — aux deux viewports de référence **1500x1000** et
**1366x768**, pour les six modes (`home`, `spotlab`, `review`, `replayer`,
`training`, `strategy`). C'est ce job qui porte le **verdict** : lui seul dispose
du réseau, de l'action `./.github/actions/repro-browser` et d'un Chromium
chargeable.

Ce job n'est **pas modifié** par cette task : il reste gelé, il ne gagne aucun
step, et il exerce le smoke des modes par son unique entrée

```
$ python3 tests/trainer/smoke_trainer.py
```

après avoir servi `site/` par `python3 -m http.server 8765 --directory site`.
`smoke_trainer.py` orchestre `smoke_modes_desktop.py` via `run_driver_smokes()` et
`DRIVER_SMOKES` : le smoke des modes tourne donc **par défaut** à chaque
invocation de l'entrée gelée, sans step dédié.

## 2. Ce que l'autorité mesure

`tests/trainer/smoke_modes_desktop.py` pilote la vraie interface (aucun raccourci
en page quand un clic existe) et mesure, **par mode et par viewport de
référence**, que le document ne défile jamais globalement :
`document.scrollingElement.scrollHeight <= clientHeight` à **1500x1000** et
**1366x768**. Le mode qui déborde échoue explicitement avec ses valeurs mesurées,
donc l'audit ne peut pas être satisfait silencieusement par une coque tronquée.

- **les six modes** sont mesurés : `home`, `spotlab`, `review`, `replayer`,
  `training`, `strategy` (les parcours Accueil → Spot Lab sans main importée,
  Accueil → Review → Replayer → Review, Accueil → Training, Accueil → Stratégie
  Hero par le deep link `#strategyPage`, plus le contrôle clavier/focus du
  panneau droit du Replayer) ;
- **la surface d'import Review** est mesurée à main vide, aux deux viewports :
  chaque cible (`#reviewImportTab`, le label `Importer mes mains`, le résumé des
  options avancées, `#hhWatchBtn`, puis `#hhBenchmarkExportBtn` détails ouverts)
  est résolue par `document.elementFromPoint` au centre de sa boîte, puis
  confirmée par un hit-test Playwright `locator.click(trial=True)` — la règle
  exacte d'un vrai clic ;
- **le scénario de course Review** (carte cliquée pendant l'ouverture
  d'IndexedDB) est rejoué dans un contexte frais par viewport et son verdict est
  relu après le barrage `state.persistenceReady === true` ;
- **l'éditeur autonome `./hero-ranges.html`** est navigué mais **hors contrat de
  coque** : aucune assertion de no-scroll ne le concerne (§ 6).

Un run qui ne satisfait pas la règle **échoue** : le smoke ne saute jamais et ne
réessaie jamais.

## 3. Le rapport JSON : régénération

Le smoke **sérialise l'audit qu'il a déjà construit** dans un rapport JSON. Depuis
le dépôt :

```
$ python3 tests/trainer/smoke_modes_desktop.py --report artifacts/desktop-modes-fit/measurements.json
```

Le même chemin se règle sans toucher à la ligne de commande :

```
$ SMOKE_MODES_DESKTOP_REPORT=artifacts/desktop-modes-fit/measurements.json python3 tests/trainer/smoke_modes_desktop.py
```

Précédence : `--report` l'emporte sur la variable, qui l'emporte sur le défaut
`artifacts/desktop-modes-fit/measurements.json` (le défaut s'applique donc à
l'entrée sans argument). Le rapport contient :

| Section | Contenu |
| --- | --- |
| `records` | chaque mesure de mode : `mode`, `viewport`, `mounted`, `scrollHeight`, `clientHeight` |
| `import_hit_tests` | chaque hit-test de la surface d'import Review (`surface`, `viewport`, verdicts `visible` / `inViewport` / `inShell` / `hit` / `reachable`) |
| `editor_deep_links` | chaque mesure du deep link de l'éditeur (`step`, `url`, `query`, `controls`, `historyLength`) |
| `review_races` | le verdict mesuré de la course Review (`mounted`, `appView`, `userNavigated`, `persistenceReady`, panneaux) |
| `verdict` | verdict global, **dérivé** de ces mêmes enregistrements (`PASS` seulement si chaque enregistrement satisfait son propre contrat, `FAIL` sinon) |
| `head_sha`, `viewports`, `modes`, `schema` | provenance et périmètre du run |

Garanties, toutes mesurables :

1. le rapport est écrit **uniquement par un run réel qui a atteint la fin de
   `run()`** : toute assertion en échec, et tout échec antérieur (Playwright
   absent, socket refusé) laisse le dépôt sans rapport — aucune valeur n'est
   fabriquée, reprise d'un run précédent ou écrite en dur dans le code ;
2. la sérialisation est **déterministe** (clés triées, indentation fixe, ordre des
   enregistrements = ordre des mesures) : deux runs identiques produisent le même
   contenu ;
3. le fichier **n'est pas versionné** : aucun `artifacts/desktop-modes-fit/` n'est
   commité, le rapport n'existe qu'après un run réel.

## 4. Observation locale : les deux commandes échouent, aucun `PASS`

Les deux commandes exigées ont été lancées depuis ce worktree au HEAD
`8ed9ef07ed40beec1f2717109bcf6b29ceeb205d`. **Aucune ligne `PASS` n'est écrite
pour elles, ni pour le smoke gelé** : la cause est environnementale (le paquet
Python `playwright` n'est pas installé dans ce sandbox), donc le smoke n'est pas
rejouable ici et **aucun fit n'est revendiqué localement**.

```
$ git rev-parse HEAD
8ed9ef07ed40beec1f2717109bcf6b29ceeb205d
EXIT=0
```

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
l'orchestrateur n'est pas atteint localement et `smoke_modes_desktop.py` n'est
jamais déclenché depuis lui. Le smoke des modes, lui, échoue dans `main()`, sur sa
garde Playwright, **avant** toute mesure et avant l'écriture du rapport.

La conséquence est vérifiée sur la commande de régénération elle-même : elle est
acceptée, échoue de la même façon, et **ne laisse aucun rapport derrière** —

```
$ python3 tests/trainer/smoke_modes_desktop.py --report artifacts/desktop-modes-fit/measurements.json
smoke_modes_desktop: Playwright is unavailable (ModuleNotFoundError("No module named 'playwright'")). Install the locked dependencies (requirements.lock.txt) and the pinned browser runtime (python3 tools/repro_ci_browser.py install) before running this smoke.
EXIT=1
$ ls artifacts/desktop-modes-fit
ls: cannot access 'artifacts/desktop-modes-fit': No such file or directory
```

— ce qui est exactement la garantie du § 3 : un run qui n'aboutit pas ne produit
aucun chiffre.

## 5. Verdict

| Objet | Verdict | Base |
| --- | --- | --- |
| Règle « aucun scroll global » à `1500x1000` et `1366x768` | **non observée localement** ; l'autorité est le job gelé `browser-smoke` (§ 1) | ce sandbox n'a pas de runtime Playwright : les deux commandes du § 4 sont `EXIT=1` |
| Mesure reproductible depuis le dépôt | **acquise** | `tests/trainer/smoke_modes_desktop.py --report …` produit le JSON de l'audit (§ 3) |
| Fit des six modes | **non revendiqué ici** | aucun `PASS` local ; le rapport n'existe qu'après un run réel |
| CI du job gelé | **non observée** | réseau coupé dans ce sandbox ; aucun état vert de CI n'est affirmé |

Aucune affirmation « aucun débordement / aucun contenu inatteignable » n'est
écrite dans ce document : elle n'apparaît que dans la sortie d'un run réel du
smoke (ou dans son rapport JSON), jamais dans la prose.

## 6. `./hero-ranges.html` : navigué mais **hors contrat de coque**

Le parcours navigue réellement de l'Accueil vers l'éditeur autonome
`./hero-ranges.html` (activation du lien réel
`a.mode-card[data-app-view="strategy"]`) et mesure son deep link (les cinq
paramètres `population`, `position`, `spot`, `stack`, `hand` comparés aux vrais
contrôles, la réécriture en place après un clic réel sur `#heroGrid`, puis le
reload). Cette page reste **hors contrat de coque** : c'est un document autonome,
pas la coque desktop à hauteur fixe, donc aucune assertion
`scrollHeight <= clientHeight` ne la concerne et elle ne porte aucun verdict de
fit dans le périmètre de ce document.

## 7. Ce que ce document ne contient plus, et pourquoi

Les révisions antérieures portaient : la narration d'un harnais local **non
versionné** (Chromium de secours lancé par des moyens hors dépôt), ses commandes
et ses sorties, ses tableaux mode × viewport « stabilisés », et une réserve
numérique issue de ce harnais. Tout cela est **supprimé** :

- un chiffre qu'aucune commande versionnée ne peut reproduire n'est pas une
  preuve ; il est remplacé par le rapport JSON du smoke (§ 3), produit par le même
  code de mesure que celui que le job gelé exécute ;
- les tableaux non reproductibles ne sont **pas** reconduits, même en les
  qualifiant : ce document ne cite plus de mesure locale ;
- l'éditeur hors contrat de coque reste documenté (§ 6) parce que c'est un contrat
  de navigation du smoke, pas une mesure de fit.

Le smoke lui-même n'a **pas** été affaibli par cette task : l'ajout du rapport est
strictement additif (il sérialise l'audit existant), le message d'échec sans
Playwright et tous les marqueurs contractuels restent mot pour mot, et
`.github/workflows/trainer-smoke.yml` ne gagne aucun step.

## 8. Vérification

### 8.1 L'échec CI réel, et sa cause racine géométrique

Le job gelé `browser-smoke` a échoué **en CI**, de façon déterministe, au HEAD de
la **PR #416**, à **1366x768** : le clic réel du smoke

```
await page.click('#homePage a[href="#historiesSection"]')
```

— le raccourci Accueil « Review », `#homePage a[href="#historiesSection"]` — n'a
jamais atteint sa cible. Le centre de la boîte du lien recevait
`button#quickNavToggle`, la bascule du rail de navigation flottant : l'attente
d'actionnabilité de Playwright expirait donc sur son délai **par défaut de 30 s**.
Le smoke a échoué sur son propre clic réel, pas sur une mesure.

Cause racine, géométrique et recalculable depuis les déclarations CSS : à
1366x768 la colonne Home — centrée par `margin:auto` sur `.wrap`
(`max-width:1220px`) puis décalée de son `padding` — commençait à **x≈99**, donc
**à gauche du bord droit du toggle, x=142**. Ce bord est déclaré :
`--nav-rail-left:10px` + `--nav-rail-width:118px` = bord droit du rail à 128,
et la bascule `--nav-toggle-width:28px` déborde de `--nav-toggle-right:-14px`,
soit l'intervalle 86..142. Le centre du raccourci tombait dans l'intervalle
couvert par la bascule : l'interception n'était pas un aléa du run mais une
propriété de la mise en page à ce viewport.

Cette cause racine est aussi consignée, dans le dépôt, par la garde R1 elle-même
(`check_home_nav_separation()` de
`tests/trainer/test_desktop_accessibility_contract.py`), qui la recalcule depuis
les mêmes jetons CSS : la lecture de § 8.1 et celle de la garde ne peuvent pas
diverger.

### 8.2 La correction R1, et le clic réel conservé

La correction consignée ici est celle livrée par **R1** :

- **`site/index.html`** : la géométrie du rail devient une autorité unique et
  nommée (`--nav-rail-left`, `--nav-rail-width`, `--nav-toggle-width`,
  `--nav-toggle-right`, `--nav-rail-end`, `--home-nav-gutter`) et la colonne Home
  réserve cette gouttière par son propre `padding-left: var(--home-nav-gutter)` :
  la colonne interactive commence strictement à droite de `--nav-rail-end`.
  Aucun `z-index`, aucun `pointer-events` et aucun décalage négatif ne contourne
  le recouvrement — il est supprimé, pas masqué ;
- **`tests/trainer/test_desktop_accessibility_contract.py`** : la garde statique
  correspondante, sans navigateur, qui recalcule cette séparation Home/rail
  depuis ces mêmes déclarations (`var()` et `calc()` résolus) à `1500x1000` et
  `1366x768` et sur toute la plage où le rail reste vertical.

Le smoke, lui, **conserve son clic réel** : la correction ne remplace pas le clic
par un clic JS forcé (`dispatch_event`, `evaluate("… .click()")`), et n'ajoute ni
`force=True`, ni retry, ni skip sur ce raccourci. C'est exactement ce qui rend la
garde R1 vérifiable : si le recouvrement revenait, c'est le clic réel du job gelé
qui le signalerait, ici par ce timeout d'actionnabilité de 30 s.

### 8.3 Ce qui est observé, et l'autorité gelée

| Objet | État observé | Base |
| --- | --- | --- |
| `python3 tests/trainer/test_smoke_orchestration_contract.py` | **PASS** (`EXIT=0`) | exécuté dans ce worktree, au HEAD du front-matter |
| `for test in tests/trainer/test_*.py; do python3 "$test"; done` | **PASS** (`files=48 fails=0`) | idem |
| `python3 tests/trainer/smoke_modes_desktop.py` | **EXIT=1** — `Playwright is unavailable` : aucune mesure, aucun rapport | § 4 |
| `python3 tests/trainer/smoke_trainer.py` | **EXIT=1** — `ModuleNotFoundError: No module named 'playwright'` | § 4 |
| Job gelé `browser-smoke` **après** la correction | **non observé** — **relance exigée au nouveau HEAD, `PASS` attendu** | le job n'est observable qu'en CI ; aucun `PASS` n'est affirmé ici |

Deux points d'autorité, sans exception :

1. le job gelé `browser-smoke` de `.github/workflows/trainer-smoke.yml` reste la
   **seule autorité** pour la règle « aucun scroll global »
   (`document.scrollingElement.scrollHeight <= clientHeight`) aux deux viewports
   de référence **1500x1000** et **1366x768**, pour les six modes (`home`,
   `spotlab`, `review`, `replayer`, `training`, `strategy`) : c'est lui qui porte
   le **verdict** ;
2. son résultat **n'est pas observable depuis ce sandbox** : l'échec consigné en
   § 8.1 est l'échec CI réel, et la correction R1 reste à confirmer par une
   **relance du job gelé au nouveau HEAD**, qui doit y être `PASS`. Cette relance
   est une exigence de clôture, pas une observation : aucun `PASS` de CI n'est
   revendiqué dans ce document.

Le seul `PASS` consigné ici est celui des gardes statiques exécutées dans ce
worktree (§ 8.3, lignes 1 et 2). Le smoke lui-même ne revendique toujours aucun
fit depuis le dépôt (§ 5), et l'option de rapport `--report` (§ 3) reste la seule
façon de produire `artifacts/desktop-modes-fit/measurements.json` — par un run
réel, jamais par ce document.

### 8.4 La garde qui empêche ce constat de disparaître

`python3 tests/trainer/test_smoke_orchestration_contract.py` → `smoke
orchestration contract checks: OK`, `EXIT=0`. Cette garde vérifie notamment que
ce document cite les deux commandes
(`python3 tests/trainer/smoke_modes_desktop.py` et
`python3 tests/trainer/smoke_trainer.py`), `git rev-parse HEAD`, `1500x1000` et
`1366x768`, `scrollHeight` et `clientHeight`, les six modes, un verdict, que
`hero-ranges.html` est **hors contrat** de coque, qu'il cite l'option de rapport
`--report`, la variable `SMOKE_MODES_DESKTOP_REPORT` et le défaut
`artifacts/desktop-modes-fit/measurements.json`, que le job gelé `browser-smoke`
est la **seule autorité** (§ 8.3), que ce document **ne cite aucun chemin hors
dépôt**, qu'il nomme l'**interception** (`#quickNavToggle`) et le **clic réel
conservé** (`#homePage a[href="#historiesSection"]`, sans `dispatch_event`, sans
`force=True`, sans retry et sans skip), et que sa lecture reste factuelle :
l'échec y est un échec CI **observé**, nommé par son clic réel, sa cause et sa
correction — pas une requalification de l'échec en effet de bord inoffensif.

### 8.5 Le second échec CI réel : l'étape d'idempotence du job gelé `contract`

Le § 8.1 consigne l'échec du job gelé `browser-smoke`. Un **second** échec CI
réel, distinct, est consigné ici : le job gelé `contract` de `.github/workflows/hero-range-editor.yml` a échoué à son étape
« Main application integration is idempotent ». Cette étape encadre le patch de
navigation par deux empreintes du même fichier, puis compare ces empreintes :

```
$ sha256sum site/index.html                 # empreinte « avant »
$ python3 tools/patches/apply_hero_range_editor.py
$ sha256sum site/index.html                 # empreinte « après »
$ diff -u <empreinte avant> <empreinte après>
```

Le `diff` a retourné **1** : la révision alors versionnée du patch modifiait
bien `site/index.html`, donc le step échouait. Ce que la CI signale ici n'est
pas une mesure de fit, mais un patch qui n'était plus idempotent.

**Cause réelle, en markup.** Dans sa révision antérieure à la correction #394,
`patch_text()` de `tools/patches/apply_hero_range_editor.py` réinsérait à chaque
exécution l'entrée de rail autonome

```
  <a href="./hero-ranges.html" data-product-domain="strategy">Strategy</a>
```

juste après la ligne du rail
`<a id="trainerNavLink" href="#trainerPage" data-product-domain="training">Training</a>`
(l'entrée `#trainerNavLink` de `#quickNav`).
Depuis R1 (`site/index.html`, commit `8ed9ef0`, task `backlog-0q6`), `#quickNav`
ne porte plus ce lien : son entrée Strategy est une navigation **in-app**
(`href="#strategyPage"`, § 6). Le marqueur d'idempotence du patch — « l'entrée
est déjà là, ne rien écrire » — ne pouvait donc plus se déclencher : chaque run
ajoutait une **seconde** entrée Strategy au rail, changeait le `sha256` de
`site/index.html`, et faisait échouer le `diff`.

Mesuré sur une copie **byte-identique** de `site/index.html` (aucun octet de
`site/**` écrit par cette task), avec la révision antérieure du patch
(`git show 8ff970b:tools/patches/apply_hero_range_editor.py`) :

| Empreinte de `site/index.html` | Valeur |
| --- | --- |
| avant le patch (octets R1 livrés) | `4bcfbcf50af63b29d0b6dbf7007b1b7081b9e2e0e1363d280b39e3bb756b2a2b` |
| après le patch (révision antérieure) | `c5ac487a66360fa5b7cf05742aba79011ae631d5806d9ffa630ea3f1c8ccffa2` |
| `diff -u` des deux empreintes | `EXIT=1` (échec du step) |

**Correction livrée (#394).** Trois tâches, toutes internes au dépôt :

- **T1** — `tools/patches/apply_hero_range_editor.py` (commit `3ff4f45`, task
  `backlog-jiv`) : la réinsertion dans `#quickNav` est **supprimée**. Le patch ne
  garde qu'une insertion strictement conditionnée par le marqueur hors
  navigation `id="heroRangesOpenBtn"` de l'Accueil (`patch_text()` renvoie le
  texte inchangé dès que ce marqueur est présent) et n'ancre plus rien sur un
  identifiant de `#quickNav` ;
- **T2** — `tests/hero_ranges/test_hero_range_repository.mjs` (commit `9d5efcc`,
  task `backlog-y03`) : le contrat de dépôt de l'éditeur, étendu sur cette même
  surface ;
- **T3** — `tools/check_issue394_stale_claims.py` (commit `1e17f90`, task
  `backlog-3p7`) : la garde anti-claims échoue si le patch ré-ancre sur un
  identifiant de `#quickNav` ou s'il émet une entrée `data-product-domain`
  pointant vers `./hero-ranges.html`, donc la régression ne peut pas revenir
  silencieusement.

Sur la même copie byte-identique, la révision corrigée du patch laisse le
`sha256` **inchangé** et `diff -u` retourne `EXIT=0` : le step redevient
idempotent. C'est une mesure locale, reproductible depuis le dépôt, et elle
n'écrit aucun octet de `site/**`.

**Statut de non-observation.** Le job gelé `contract` et son job dépendant
`browser-smoke` ne sont pas observables depuis ce sandbox (réseau coupé) : aucun
`PASS` de CI n'est revendiqué ici, ni pour la correction du patch, ni pour le
fit. Ce document consigne l'échec CI **réel**, sa cause et la correction
livrée ; la relance des jobs gelés reste une exigence de clôture. Le job gelé
`browser-smoke` de `.github/workflows/trainer-smoke.yml` demeure la **seule
autorité** pour la règle « aucun scroll global » (`scrollHeight` /
`clientHeight` à `1500x1000` et `1366x768`, pour les six modes `home`,
`spotlab`, `review`, `replayer`, `training`, `strategy`) ; l'étape
d'idempotence de § 8.5 ne porte aucun verdict de fit, et aucun octet de
`.github/workflows/**` n'est modifié par cette task.

### 8.6 Observation CI réelle des jobs gelés au HEAD livré (task `backlog-g0t`)

Cette sous-section est **strictement additive** : elle consigne l'**état CI
réellement observé** des trois jobs gelés — `contract` de
`.github/workflows/hero-range-editor.yml`, `static-contract` et `browser-smoke`
de `.github/workflows/trainer-smoke.yml` — au HEAD **poussé** de la branche
épique / de la PR #416, tel qu'il a été relevé par le **connecteur GitHub** en
lecture seule. Aucune des lignes ci-dessous n'est déduite : chaque URL, chaque
conclusion et chaque extrait provient de la réponse de l'API (runs, jobs,
étapes) et du journal du job concerné.

#### 8.6.1 Le canal d'observation, le périmètre et l'instant

Le canal disponible est le **connecteur GitHub**, pas le shell : la résolution
DNS vers `api.github.com` reste coupée dans ce worker (§ 8.3), donc `curl` et
`gh` échouent toujours, mais le connecteur interroge l'API GitHub et rend les
runs, jobs et journaux. Ce qui est observé est le **HEAD poussé** de la branche
épique — `8ff970bde9726852ffd77537499e4b7161698c2c` (PR #416), que la CI
`pull_request` a extrait sous la forme du commit de fusion
`4fd6e701eeb37992768b4264c0f86bdcc6a12ca6` — et non le HEAD livré du worktree :

```
$ git rev-parse HEAD
2d0856024a1859cf778dd889b3911035c1d10378
$ git rev-parse --abbrev-ref HEAD
n8n/issue-394/task-backlog-g0t
```

Le workflow `Validate interactive trainer` ne se déclenche que sur une liste de
chemins parmi lesquels `tests/trainer/**` et `tools/patches/apply_trainer_mvp.py` ;
le workflow `Validate Hero range repository and editor` surveille de même
`tools/patches/apply_hero_range_editor.py`, `tests/hero_ranges/**` et
`site/index.html`. Les corrections T1/T2/T3 (§ 8.5) portent précisément sur ces
familles de chemins — elles sont **dans le worktree, pas dans la branche
épique** : il n'existe donc **aucun run** sur les octets livrés.

#### 8.6.2 L'état observé des jobs gelés, run par run

| Workflow (gelé) | Job | Run observé | Étapes du job | Conclusion |
| --- | --- | --- | --- | --- |
| `.github/workflows/trainer-smoke.yml` | `static-contract` | `#564` — [run `36081969038`](https://github.com/aradenac/poker-engine/actions/runs/36081969038) | toutes `success` (REPRO batch-1, JavaScript syntax, Release identity, All trainer regression contracts, Patch idempotence) | **`success`** — [job `107905680522`](https://github.com/aradenac/poker-engine/actions/runs/36081969038/job/107905680522) |
| `.github/workflows/trainer-smoke.yml` | `browser-smoke` | `#564` — [run `36081969038`](https://github.com/aradenac/poker-engine/actions/runs/36081969038) | `Exercise Training view` = `success`, `Exercise pathological engine regressions` = `success` | **`success`** — [job `107905811137`](https://github.com/aradenac/poker-engine/actions/runs/36081969038/job/107905811137) |
| `.github/workflows/hero-range-editor.yml` | `contract` | `#440` — [run `36081969061`](https://github.com/aradenac/poker-engine/actions/runs/36081969061) | étape 7 « Main application integration is idempotent » = **`failure`** ; `Release identity` = `skipped` | **`failure`** — [job `107905680401`](https://github.com/aradenac/poker-engine/actions/runs/36081969061/job/107905680401) |
| `.github/workflows/hero-range-editor.yml` | `browser-smoke` | `#440` — [run `36081969061`](https://github.com/aradenac/poker-engine/actions/runs/36081969061) | aucune (dépendance `needs: contract`) | **`skipped`** |

Le run `#564` de `trainer-smoke` est **vert** au HEAD poussé : ses deux jobs
gelés sont `success`, y compris l'étape `Exercise Training view` qui porte le
smoke des modes. Le run `#440` de `hero-range-editor` est **rouge** : son job
`contract` échoue sur l'étape d'idempotence, ce qui met `browser-smoke` en
`skipped`. Autrement dit, **les jobs gelés ne sont pas tous verts au HEAD de
code observé**.

#### 8.6.3 L'étape « Main application integration is idempotent » : extrait du journal, rouge

L'échec de `#440` n'est pas rapporté de mémoire : c'est le journal du job
`contract` qui le porte, et il reproduit exactement les deux empreintes
consignées au § 8.5 et dans `docs/issue-394-release-identity-ci-report.md` § 8 —

```
$ sha256sum site/index.html > …          # empreinte « avant » de l'étape
$ python3 tools/patches/apply_hero_range_editor.py
Hero range editor links integrated
$ sha256sum site/index.html > …          # empreinte « après » de l'étape
$ diff -u …
-4bcfbcf50af63b29d0b6dbf7007b1b7081b9e2e0e1363d280b39e3bb756b2a2b  site/index.html
+c5ac487a66360fa5b7cf05742aba79011ae631d5806d9ffa630ea3f1c8ccffa2  site/index.html
##[error]Process completed with exit code 1
```

— donc l'étape est **rouge au HEAD poussé** : `diff -u` sort en `1` parce que le
patch réinsérait l'entrée de rail autonome dans `#quickNav` (§ 8.5). Ce qui a
été corrigé (T1/T2/T3) n'est pas encore dans la branche épique, et aucune
relance n'a été demandée ni observée : l'étape n'est **pas** verte, et ce
document ne l'écrit nulle part. Seul le chemin des deux empreintes temporaires
de l'étape est élidé (`…`), pour que ce document ne cite aucun chemin hors du
dépôt ; les lignes de `sha256` et la sortie d'erreur, elles, sont reprises mot
pour mot du journal.

#### 8.6.4 Les extraits qui prouvent l'exécution réelle des jambes `1366x768`

Le job `browser-smoke` du run vert `#564` a imprimé, dans son journal, l'audit
**par mode et par viewport** que le smoke construit — l'extrait ci-dessous est
celui des lignes `1366x768` (les lignes `1500x1000` du même run sont identiques
en structure, avec `scrollHeight=1000 <= clientHeight=1000`) :

```
  mode=home      viewport=1366x768   scrollHeight=768 <= clientHeight=768
  mode=spotlab   viewport=1366x768   scrollHeight=768 <= clientHeight=768
  mode=review    viewport=1366x768   scrollHeight=768 <= clientHeight=768
  mode=review    viewport=1366x768   import surface[closed] reachability: #reviewImportTab=ok, label[for="hhFileInput"]=ok, .hh-import-advanced > summary=ok, #hhWatchBtn=ok
  mode=review    viewport=1366x768   import surface[advanced-open] reachability: #reviewImportTab=ok, label[for="hhFileInput"]=ok, .hh-import-advanced > summary=ok, #hhWatchBtn=ok, #hhBenchmarkExportBtn=ok
  mode=replayer  viewport=1366x768   scrollHeight=768 <= clientHeight=768
  mode=training  viewport=1366x768   scrollHeight=768 <= clientHeight=768
  mode=strategy  viewport=1366x768   scrollHeight=768 <= clientHeight=768
  mode=strategy-editor viewport=1366x768   deep link[arrivée]: query={'population': 'legacy_pokerstars_nlhe_100-200_play_6max_mixed_v1', 'position': 'BTN', 'spot': 'UNOPENED', 'stack': '100', 'hand': 'AA'} contrôles=[population:… position:BTN spot:UNOPENED stack:100] main active=['AA'] history.length=4
  mode=strategy-editor viewport=1366x768   deep link[réécriture]: query={… 'hand': 'KK'} contrôles=[…] main active=['KK'] history.length=4
  mode=strategy-editor viewport=1366x768   deep link[reload]: query={… 'hand': 'KK'} contrôles=[…] main active=['KK'] history.length=4
  mode=review    viewport=1366x768   course Review: persistenceReady=True mounted=review userNavigated=True #reviewDashboard=True #historiesSection masqué=True
desktop modes measurements written: artifacts/desktop-modes-fit/measurements.json
modes desktop smoke: PASS (2 viewports · home, spotlab, review, replayer, training, strategy · transitions + Replayer keyboard + measured Review import surface reachability: elementFromPoint hit-test + click trial + persistenceReady readiness barrier + Review race scenario + #strategyPage deep link of the embedded shell + editor deep link (query↔contrôles, réécriture en place, reload))
```

Ces lignes nomment, viewport par viewport, les jambes réellement parcourues à
`1366x768` : Spot Lab, Replayer, Training (rail Trainer), Stratégie Hero et
l'éditeur autonome du deep link, plus la surface d'import Review et la course
Review. Elles sont **mesurées**, pas commentées : chaque valeur est celle que le
smoke a sérialisée dans le rapport `artifacts/desktop-modes-fit/measurements.json`
de ce run, et la ligne finale est le `PASS` **du run**, pas une affirmation de ce
document.

#### 8.6.5 La couverture élargie à `1366x768` (Spot Lab, Replayer, rail Trainer)

Les panneaux que la revue humaine nommait comme jamais mesurés à `1366x768` sont
mesurés par l'**extension `#394 T1`** du smoke, avec le **même instrument** que
la surface d'import Review (`document.elementFromPoint` au centre de la boîte,
puis hit-test Playwright `locator.click(trial=True)`), chacun monté par un
**clic réel** sur son onglet, dans le parcours **par viewport** :

| Surface | Onglet mesuré | Cibles mesurées |
| --- | --- | --- |
| Spot Lab, panneau `Range adverse` | `#spotlabRangeTab` | `#rangeDisplaySection` et la grille `#matrix` (169 cellules) |
| Replayer, colonnes | — (montage du Replayer) | `.replayer-col-left`, `.replayer-col-center`, `#replayerContextPanel` |
| Replayer, onglets du panneau droit | `#replayerDecisionTab`, `#replayerRangesTab`, `#replayerDetailsTab` | `#replayerDecisionPanel`, `#replayerRangesPanel`, `#hhReplayDetail` |
| Rail Trainer, onglets | `#trainerCoachingTab`, `#trainerSessionTab`, `#trainerProfilesTab`, `#trainerTestTab` | `#trainerCoachPanel`, `#trainerSessionPanel`, `#trainerProfilesPanel`, `#trainerTestPanel` |

Ces mesures sont sérialisées dans le compartiment `panel_surfaces` du rapport
(un enregistrement par surface et par viewport), le verdict `reachable` est
composé comme celui de la surface d'import, et un **inventaire par viewport** est
imprimé depuis l'audit lui-même — vert ou rouge :

```
  inventaire panneaux viewport=1366x768 mesures=… cibles=… atteignables=…/… — spotlab-range=[…] · replayer-columns=[…] · replayer-tabs=[…] · trainer-rail=[…]
```

**Ce que cette preuve est, et ce qu'elle n'est pas encore.** L'inventaire de
panneaux est produit par les **octets de l'extension T1**, et ces octets ne sont
**pas poussés** : le run `#564` observé au § 8.6.2 est celui du HEAD poussé
`8ff970b`, qui est **antérieur** à l'extension. Ses journaux portent donc les
lignes citées au § 8.6.4 (audit de scroll, surface d'import, courses et deep
links) mais **pas** les lignes `panneau[…]` / `inventaire panneaux` ci-dessus.
La preuve d'exécution par viewport des **panneaux** à `1366x768` est donc
**attendue au rerun du job gelé sur les octets livrés** : elle n'est **pas**
revendiquée ici, et aucune ligne de ce document n'en affirme le résultat.

#### 8.6.6 Le constat : HEAD livré non poussé, jetons de garde inchangés

| Objet | État observé | Base |
| --- | --- | --- |
| `trainer-smoke` / `static-contract` au HEAD poussé `8ff970b` | **`success`** | run `#564`, § 8.6.2 |
| `trainer-smoke` / `browser-smoke` au HEAD poussé `8ff970b` | **`success`** | § 8.6.2 et § 8.6.4 |
| `hero-range-editor` / `contract` au HEAD poussé `8ff970b` | **`failure`** — étape d'idempotence | § 8.6.2 et § 8.6.3 |
| `hero-range-editor` / `browser-smoke` au HEAD poussé `8ff970b` | **`skipped`** | § 8.6.2 |
| Runs sur les octets **livrés** (worktree, `2d08560`, non poussé) | **aucun** | la branche épique est restée sur `8ff970b` |
| Jobs gelés tous verts **au HEAD de code livré** | **non** | le job `contract` est rouge au HEAD poussé, et les octets livrés n'ont pas de run |

Conséquences, écrites telles quelles :

1. `ci_green` reste **`NOT_OBSERVED`** : la condition d'un `OBSERVED` — les
   **trois** jobs gelés verts sur les octets du HEAD de code — n'est pas
   satisfaite, et aucune valeur n'est forcée ;
2. `frozen_job_rerun_required` reste **`true`** : le job gelé `browser-smoke`
   doit être relancé sur les octets livrés, d'autant que l'extension T1 du smoke
   touche `tests/trainer/**`, une famille de chemins que le workflow
   `trainer-smoke` surveille — donc la poussée des corrections redéclenche le
   workflow par construction ;
3. `contract_job_rerun_required` reste **`true`** : la correction du patch
   (`tools/patches/apply_hero_range_editor.py`) n'est pas dans la branche épique,
   donc l'étape d'idempotence est encore rouge en CI ;
4. aucun `PASS` n'est écrit pour un job gelé qui n'a pas été observé vert sur
   les octets livrés, et l'autorité de la règle « aucun scroll global » reste le
   job gelé `browser-smoke` de `.github/workflows/trainer-smoke.yml`, à
   `1500x1000` et `1366x768`, pour les six modes `home`, `spotlab`, `review`,
   `replayer`, `training`, `strategy`.

Cette sous-section ne modifie aucun octet de `site/**`, de
`.github/workflows/**` ni du smoke : elle n'ajoute que l'observation ci-dessus,
ses URLs et ses extraits.

### 8.7 Pré-vol hors navigateur des deux jobs gelés au HEAD livré `b3baf65` (task `backlog-3bh`)

Cette sous-section est **strictement additive** : elle consigne, tels qu'ils ont été
**réellement enregistrés** par la task `backlog-3bh` au **§ 10** de
`docs/issue-394-release-identity-ci-report.md`, le **pré-vol hors CI** du corps
**hors navigateur** des **deux jobs gelés** — l'étape d'idempotence du job
`contract` de `.github/workflows/hero-range-editor.yml`, et les étapes non
navigateur du job `static-contract` de `.github/workflows/trainer-smoke.yml`. Elle
ne produit **aucune mesure navigateur** et **aucun `PASS` de job gelé** : un
pré-vol local **n'est pas** un PASS d'acceptation, et aucune ligne ci-dessous ne
doit être lue comme tel.

#### 8.7.1 L'état de livraison observé localement : aucun run CI pour les octets livrés

| Élément | Valeur enregistrée par `backlog-3bh` (§ 10.1 du rapport) |
| --- | --- |
| HEAD du pré-vol | `b3baf65e8a263bad2cda8d06c734b55876b455e9` |
| Branche de ce worktree | `n8n/issue-394/task-backlog-3bh` |
| Commits d'avance sur le tip distant | **7** (`git rev-list --count 8ff970b..HEAD`) |
| Tip distant (dernier HEAD poussé) | `8ff970bde9726852ffd77537499e4b7161698c2c` — **tête de la PR #416** |
| Runs CI sur les octets livrés | **aucun** (`ci_delivered_head_runs: NONE`) |

Le tip distant `8ff970b` est la tête de la PR #416 : les corrections livrées ne sont
**pas** dans la branche épique, donc **aucun run CI n'existe pour les octets
livrés** — ni pour le pré-vol, ni pour la présente révision. C'est la raison du
§ 8.6 : seul un HEAD **poussé** peut alimenter les jobs gelés, et un pré-vol local,
quel que soit son verdict, ne les remplace pas.

#### 8.7.2 Les six commandes rejouées, hors CI, au HEAD `b3baf65`

Le pré-vol a exécuté **6** commandes — les étapes non-navigateur des deux jobs
gelés — et **chacune** est sortie `EXIT=0` ; les codes de sortie sont **observés**,
jamais extrapolés (§ 10.2 du rapport) :

| # | Commande (exacte) | Observation enregistrée | Code de sortie |
| --- | --- | --- | --- |
| 1 | `PYTHONPATH=. python3 tests/ci/test_repro_workflow_batch1.py` | `REPRO workflow batch-1 tests: 9 passed` | **0** |
| 2 | `node --check site/trainer.js` | aucune sortie (syntaxe OK) | **0** |
| 3 | `python3 tools/write_site_release.py --check` | `release source anchor verified: site/RELEASE.json; assembled identity can be materialized` | **0** |
| 4 | `for test in tests/trainer/test_*.py; do python3 "$test"; done` | **48 modules**, **0 échec**, `TOTAL_MODULES=48` (§ 10.8 du rapport) | **0** |
| 5 | étape « Patch idempotence » : `sha256sum site/index.html site/trainer.js` → `python3 tools/patches/apply_trainer_mvp.py` → comparaison | `sha256` avant = après pour les deux fichiers, `diff -u` vide (§ 10.3) | **0** |
| 6 | étape « Main application integration is idempotent » : `sha256sum site/index.html` → `python3 tools/patches/apply_hero_range_editor.py` → comparaison | `sha256` avant = après, `diff -u` vide (§ 10.4) | **0** |

L'étape 6 est **exactement** l'étape qui était **rouge** au HEAD poussé `8ff970b`
(§ 8.5, § 8.6.3, et § 8 du rapport) : le `diff -u` y retournait `1` parce que la
révision alors versionnée du patch réinsérait l'entrée de rail autonome dans
`#quickNav`. Rejouée au HEAD `b3baf65` sur une copie **byte-identique** des octets
servis — aucun octet de `site/**` écrit par le pré-vol, les octets d'origine
sauvegardés puis restaurés par copie, `git hash-object` égal aux blobs `HEAD` — la
révision corrigée du patch laisse le `sha256` **inchangé** et le `diff -u` retourne
**`EXIT=0`** : le marqueur de garde `id="heroRangesOpenBtn"` est présent exactement
une fois, donc `patch_text()` rend le texte inchangé, et les deux empreintes
encadrantes sont **égales** :

```
-4bcfbcf50af63b29d0b6dbf7007b1b7081b9e2e0e1363d280b39e3bb756b2a2b  site/index.html  # avant
+4bcfbcf50af63b29d0b6dbf7007b1b7081b9e2e0e1363d280b39e3bb756b2a2b  site/index.html  # après, identique
```

Le même pré-vol a exercé les modes `--index` / `--check` de ce patch : `--index`
sur une copie non patchée écrit **au plus une fois** puis devient inerte, `--check`
sur cette copie patchée sort `EXIT=0`, et `--check` sur une copie non patchée sort
`EXIT=1` (« hero range editor patch is not applied ») — le garde fail-closed
attendu.

#### 8.7.3 Ce qui reste non prouvé : la moitié navigateur, observable seulement par le job gelé `browser-smoke`

Les six commandes de § 8.7.2 sont **statiques** : aucune n'exécute un navigateur.
Restent donc **non prouvés** hors CI, et **non revendiqués** ici :

- l'**absence de défilement global** — `document.scrollingElement.scrollHeight <= clientHeight`
  — pour les **six modes** `home`, `spotlab`, `review`, `replayer`, `training`,
  `strategy`, **aux deux viewports de référence** `1500x1000` et `1366x768` ;
- l'**atteignabilité réelle** des panneaux **Spot Lab**, **Replayer** et **Trainer**
  (les hit-tests de panneaux que la revue humaine nommait comme jamais mesurés à
  `1366x768`, § 8.6.5) ;
- le **clic réel** du raccourci Accueil `#homePage a[href="#historiesSection"]`,
  **non intercepté** : `tests/trainer/smoke_modes_desktop.py` exécute
  `await page.click('#homePage a[href="#historiesSection"]')`, sans `force=True`,
  sans `dispatch_event`, sans retry et sans skip.

Le **seul** canal qui observe ces trois points est le job gelé `browser-smoke` de
`.github/workflows/trainer-smoke.yml`, exécuté sur un HEAD **poussé** (§ 1, § 8.6,
et § 10.5 du rapport). **Aucun `PASS` de ce job n'est écrit ici** : il n'a pas été
observé depuis ce worker, et le pré-vol hors navigateur ne couvre pas cette moitié
de l'acceptation.

#### 8.7.4 Le repli navigateur local est irréalisable sur cet hôte

Le pré-vol a **vérifié**, et non supposé, que le repli navigateur est
**irréalisable** ici (§ 10.6 du rapport) : le module Python `playwright` est
**absent** (`ModuleNotFoundError: No module named 'playwright'`), si bien que
`tests/trainer/smoke_modes_desktop.py` et `tests/trainer/smoke_trainer.py` sortent
`EXIT=1` — le second à l'import, donc **avant** `run_driver_smokes()` — et le
**Chromium pinné** (révision `1187`, version `140.0.7339.16`, cf.
`reproducibility/browser-identity.lock.json` et
`reproducibility/environment.lock.json`) est **présent mais ne démarre pas** : il
manque `libnspr4.so` et `libnss3.so`, absents de l'hôte, et le **réseau** (DNS) est
coupé, donc ces bibliothèques ne peuvent pas être installées ici. Aucun smoke
navigateur n'est exécutable localement.

#### 8.7.5 Jetons inchangés : le pré-vol ne bascule rien

Le pré-vol hors navigateur **ne remplace pas** un run CI poussé (§ 10.7 du
rapport). Donc, inchangés :

- `ci_green` reste **`NOT_OBSERVED`** ;
- `frozen_job_rerun_required` reste **`true`** : le job gelé `browser-smoke` doit
  tourner sur les octets livrés d'un HEAD **poussé** ;
- `contract_job_rerun_required` reste **`true`** : l'étape d'idempotence du job
  `contract` est rouge au HEAD poussé `8ff970b`, sa correction n'y est pas ;
- `red_workflows` **nomme** toujours le workflow réellement rouge observé,
  `.github/workflows/hero-range-editor.yml` (job `contract`, run `36081969061`,
  étape « Main application integration is idempotent »).

Aucune bascule n'est possible sans un run réel au HEAD livré : ce pré-vol ne mesure
que le périmètre **hors navigateur**, et le job gelé `browser-smoke` de
`.github/workflows/trainer-smoke.yml` demeure la **seule autorité** pour la règle
« aucun scroll global » (`scrollHeight` / `clientHeight` à `1500x1000` et
`1366x768`, pour les six modes `home`, `spotlab`, `review`, `replayer`, `training`,
`strategy`). Cette sous-section n'écrit **aucun octet** de `site/**`, de
`.github/**`, de `tests/` ni de `tools/` : elle n'ajoute que la lecture ci-dessus.

## 9. L'échec CI observé sur les octets livrés (`#matrix` à `1366x768`), sa cause et le correctif (task `backlog-lh8`)

Cette section est **strictement additive** : elle consigne, à la suite du § 8,
l'**échec CI réellement observé sur les octets livrés** — le panneau Spot Lab
`Range adverse`, dont la grille `#matrix` est mesurée inatteignable à `1366x768`
par le job gelé `browser-smoke` —, sa **cause géométrique**, le **correctif
livré** qui la lève, et l'**inventaire honnête** de ce que ce même run n'a **pas**
observé. Elle n'écrit aucun octet de `site/**`, de `.github/**`, de `tests/` ni de
`tools/` : elle n'ajoute que la lecture ci-dessous. Les jetons de garde du § 8
restent ceux du § 8 : `ci_green: NOT_OBSERVED`, `frozen_job_rerun_required: true`
et `contract_job_rerun_required: true` — aucun d'eux n'est basculé ici.

### 9.1 Le canal, l'instant, et le HEAD observé

Le canal reste le **connecteur GitHub** en lecture seule : la résolution DNS vers
`api.github.com` demeure coupée dans ce worker (§ 8.3), donc `curl` et `gh`
échouent toujours, mais le connecteur interroge l'API GitHub et rend les runs, les
jobs et leurs journaux. Le relevé de cette section est daté du
**2026-09-25T03:27Z**.

Ce qui est observé cette fois est le **HEAD poussé de la branche épique** de la
PR #416 — `2c46f81cb77ef1645283a1dc249f9d53894c1aa7` (`chore(n8n): task
backlog-imj for issue #394`) — et non le HEAD livré du worktree :

```
$ git rev-parse HEAD
acc7d3f17a78b435e1a616083ac67eba61dd4323
$ git rev-parse --abbrev-ref HEAD
n8n/issue-394/task-backlog-lh8
$ git merge-base --is-ancestor 2c46f81cb77ef1645283a1dc249f9d53894c1aa7 HEAD && echo ancestor
ancestor
```

Le SHA observé est donc un **ancêtre** de ce worktree : la branche épique, restée
sur `8ff970b` lors de l'observation du § 8.6, a été poussée depuis à `2c46f81`,
qui **porte les octets livrés** (extension T1 du smoke incluse, § 8.6.5). La CI
`pull_request` a extrait ces octets sous la forme du commit de fusion
`369bf056f5830dbec3ebe461763e989767b59eb2`, et c'est **ce** commit qu'elle a
exécuté. Le constat du § 8.6.6 (« runs sur les octets livrés : aucun ») valait
pour le HEAD de worktree `2d08560`, qui n'était pas poussé ; il est **remplacé ici
par l'observation ci-dessous**, pas reconduit.

### 9.2 L'échec observé : le job gelé `browser-smoke`, sur la cible `#matrix`

| Workflow (gelé) | Job | Run observé | Étapes du job | Conclusion |
| --- | --- | --- | --- | --- |
| `.github/workflows/trainer-smoke.yml` | `static-contract` | `#566` — [run `36088338545`](https://github.com/aradenac/poker-engine/actions/runs/36088338545) | toutes `success` (REPRO batch-1, JavaScript syntax, Release identity, All trainer regression contracts, Patch idempotence) | **`success`** — [job `107925080169`](https://github.com/aradenac/poker-engine/actions/runs/36088338545/job/107925080169) |
| `.github/workflows/trainer-smoke.yml` | `browser-smoke` | `#566` — [run `36088338545`](https://github.com/aradenac/poker-engine/actions/runs/36088338545) | `Exercise Training view` = **`failure`** ; `Exercise pathological engine regressions` = `skipped` | **`failure`** — [job `107925214120`](https://github.com/aradenac/poker-engine/actions/runs/36088338545/job/107925214120) |

L'échec n'est ni infrastructurel ni aléatoire : le job installe l'environnement
verrouillé (`PASS` du rapport d'environnement, `python` `3.11.9`), installe le
Chromium pinné, sert `site/`, puis échoue sur l'**assertion déterministe** de
`tests/trainer/smoke_modes_desktop.py` — la **première jauge de panneau** du
parcours `1366x768`, celle du panneau `Range adverse` du Spot Lab. La cible
mesurée est la grille `#matrix` (les 169 cellules), et le verdict mesuré la nomme
par ses champs individuels, jamais par un booléen :

| Cible mesurée | Viewport | `inViewport` | `inShell` | `hit` | `reachable` |
| --- | --- | --- | --- | --- | --- |
| `#matrix` (`SPOTLAB_RANGE_SURFACE_SELECTORS`) | `1366x768` | **`false`** | **`false`** | **`false`** | **`false`** |

Les deux autres cibles du **même** relevé de panneau — `#spotlabRangeTab` et
`#rangeDisplaySection` — sont, elles, mesurées atteignables : le panneau est bien
monté par un clic réel, c'est la grille qu'il contient qui est coupée. Les deux
lignes d'inventaire imprimées par le smoke (il les imprime pour un run vert comme
pour un run rouge, depuis l'audit qu'il a construit) le prouvent, mot pour mot :

```
  inventaire panneaux viewport=1500x1000 mesures=9 cibles=20 atteignables=20/20 — spotlab-range=[#spotlabRangeTab=ok, #rangeDisplaySection=ok, #matrix=ok] · replayer-columns=[.replayer-col-left=ok, .replayer-col-center=ok, #replayerContextPanel=ok] · replayer-decision=[#replayerDecisionTab=ok, #replayerDecisionPanel=ok] · replayer-ranges=[#replayerRangesTab=ok, #replayerRangesPanel=ok] · replayer-details=[#replayerDetailsTab=ok, #hhReplayDetail=ok] · trainer-coaching=[#trainerCoachingTab=ok, #trainerCoachPanel=ok] · trainer-session=[#trainerSessionTab=ok, #trainerSessionPanel=ok] · trainer-profiles=[#trainerProfilesTab=ok, #trainerProfilesPanel=ok] · trainer-test=[#trainerTestTab=ok, #trainerTestPanel=ok]
  inventaire panneaux viewport=1366x768 mesures=1 cibles=3 atteignables=2/3 — spotlab-range=[#spotlabRangeTab=ok, #rangeDisplaySection=ok, #matrix=MISS]
trainer smoke failed: Command '[…]' returned non-zero exit status 1.
##[error]Process completed with exit code 1.
```

Le chemin absolu que l'orchestrateur `smoke_trainer.py` imprime dans sa ligne
d'échec est élidé (`…`), pour que ce document ne cite aucun chemin hors du dépôt ;
la ligne d'erreur du runner, elle, est reprise telle quelle.

Un point compte pour la lecture de la règle : les mesures de défilement global
(`scrollHeight <= clientHeight`) passent **avant** la jauge de panneau dans le
parcours par viewport, et elles sont assertives. L'échec survient *après* celles
des modes déjà parcourus à `1366x768` (`home`, `spotlab`) : la règle « aucun
scroll global » **y était donc satisfaite**, et l'échec est exactement ce qu'elle
ne peut pas voir — un contenu **coupé à l'intérieur d'un panneau borné**, pas un
défilement du document.

### 9.3 Ce que ce run n'a pas observé : l'inventaire honnête

Le smoke **s'arrête à la première assertion en échec**, et cette assertion est la
**première** jauge de panneau du parcours `1366x768`. L'audit imprimé à cet
instant porte donc **un seul** relevé de panneau à `1366x768` (3 cibles) là où
`1500x1000` en porte **neuf** (20 cibles) : les deux lignes du § 9.2 sont la
preuve de ce qui a tourné et de ce qui n'a pas tourné. **Jamais observées vertes
depuis l'ajout de l'instrument T1**, à `1366x768` :

| Surface | Onglet | Cibles jamais observées à `1366x768` |
| --- | --- | --- |
| Replayer, colonnes | — (montage du Replayer) | `.replayer-col-left`, `.replayer-col-center`, `#replayerContextPanel` |
| Replayer, onglets du panneau droit | `#replayerDecisionTab`, `#replayerRangesTab`, `#replayerDetailsTab` | `#replayerDecisionPanel`, `#replayerRangesPanel`, `#hhReplayDetail` |
| Rail Trainer, onglets | `#trainerCoachingTab`, `#trainerSessionTab`, `#trainerProfilesTab`, `#trainerTestTab` | `#trainerCoachPanel`, `#trainerSessionPanel`, `#trainerProfilesPanel`, `#trainerTestPanel` |

Restent également **non parcourues** à `1366x768` dans ce run, parce qu'elles sont
en aval de l'assertion en échec dans le parcours par viewport : la surface
d'import Review et ses hit-tests, la course Review, le deep link `#strategyPage`
de la coque embarquée, et le deep link de l'éditeur autonome (arrivée, réécriture
en place, reload).

**Justification structurelle de cette réserve.** Les cibles listées ci-dessus sont
les **panneaux bornés eux-mêmes**, posés par flex/grid avec `min-height:0` et leur
propre `overflow:hidden` sous la coque `100dvh` — par exemple
`#replayerSection>#replayerContextPanel{display:flex;flex-direction:column;min-height:0;overflow:hidden}`,
`#replayerSection .replayer-col{min-height:0;display:flex;flex-direction:column;…}`,
`.trainer-side{…;min-height:0;overflow:hidden}` et
`.trainer-rail-panel{display:grid;gap:10px;flex:1 1 auto;min-height:0;align-content:start}`.
`#matrix`, lui, n'est **pas** borné par ces mécanismes : c'est une grille
d'hauteur incompressible (hauteur de rangée = hauteur de cellule) coupée par
`.matrixwrap{overflow:hidden;margin-top:12px}`. Le correctif du § 9.4 porte sur le
**budget de rangées de cette grille** ; il ne dit rien des panneaux déjà bornés
par flex/grid et `min-height:0`, et leur atteignabilité à `1366x768` reste donc un
risque **distinct**, non couvert par la levée ci-dessous.

### 9.4 La cause géométrique, et le correctif livré

La cause est déclarative, donc recalculable depuis les octets servis : la grille
`#matrix` a **13 rangées** de `.cell{height:34px}` séparées par **12 gouttières**
de `.matrix{gap:3px}`, soit

```
H = 13 * 34px + 12 * 3px = 478px
```

— une hauteur **incompressible** (une rangée ne peut pas être plus courte que la
cellule qu'elle peint), alors que le panneau `Range adverse` ne dispose à
`1366x768`, sous la coque `100dvh`, que d'un budget vertical inférieur. Le
`.matrixwrap{overflow:hidden;margin-top:12px}` qui borne la grille en **coupe**
donc le bas : la boîte existe, mais `#matrix` n'est ni dans le viewport, ni dans
la coque, et `document.elementFromPoint` au centre de sa boîte ne rend pas la
cible — les trois `false` du § 9.2.

Le correctif **livré** (commit `70dc732`, task `backlog-qyb`) ajoute au bloc
`<style>` de `site/index.html` la règle responsive :

```
  @media(min-width:901px) and (max-height:900px){
    .matrix{gap:2px}
    .cell{height:26px}
  }
```

soit `13 * 26px + 12 * 2px = 362px` : la grille repasse sous le budget du panneau
à `1366x768`. L'ancre de release est **réassemblée** dans le même commit
(`site/RELEASE.json`, blob de `site/index.html` `033e6517…` → `75b26fb1…`), donc
l'identité publiée suit les octets corrigés.

Ce que ce correctif **n'est pas** : il ne touche ni les 13 colonnes, ni les 169
cells, ni les valeurs non gatées (`.cell{height:34px}`, `.matrix{gap:3px}`, qui
restent celles du viewport de référence `1500x1000`) — la règle est gatée
`min-width:901px` **et** `max-height:900px`, donc elle ne change rien au viewport
de référence `1500x1000` ni au rendu des largeurs sous `901px`, et il ne
contourne rien : aucun `force=True`, aucun `dispatch_event`, aucun retry et aucun
skip n'est ajouté au smoke, qui garde son clic réel et ses jauges.

Ce correctif reste vérifiable **depuis le dépôt, sans navigateur** :
`tests/trainer/test_spotlab_range_fit_contract.py` recalcule les deux côtés de la
comparaison depuis les octets servis — `H` selon le verdict de la requête média
(largeur **et** hauteur) et le budget du panneau — et exige que la grille **non
gatée** (`478px`) soit **au-dessus** de ce budget, faute de quoi la garde échoue
au lieu de passer à vide. C'est la même famille de garde statique que
`tests/trainer/test_desktop_accessibility_contract.py` (§ 8.2), et elle ne
remplace pas un run du job gelé.

### 9.5 La condition de clôture

Le run observé ici est **rouge**, et il porte sur des octets **antérieurs** au
correctif du § 9.4 : il ne peut donc rien basculer.

1. `ci_green` reste **`NOT_OBSERVED`** — aucune valeur n'est forcée, et le run
   vert du job gelé sur les octets **corrigés** n'existe pas encore ;
2. `frozen_job_rerun_required` reste **`true`** : `browser-smoke` doit être
   relancé sur un HEAD **poussé** portant le correctif ;
3. `contract_job_rerun_required` reste **`true`** (la correction du patch
   d'idempotence du job `contract` n'est pas dans la branche épique, § 8.6.3) ;
4. **seul** un run **vert** des jobs gelés sur le nouveau SHA fera passer
   `ci_green` de `NOT_OBSERVED` à `OBSERVED`. Ni le pré-vol hors navigateur du
   § 8.7, ni les gardes statiques des § 9.4 et § 8.2, ni la lecture de ce
   document ne remplacent ce run : le job gelé `browser-smoke` de
   `.github/workflows/trainer-smoke.yml` demeure la **seule autorité** pour la
   règle « aucun scroll global » (`scrollHeight` / `clientHeight` à `1500x1000` et
   `1366x768`, pour les six modes `home`, `spotlab`, `review`, `replayer`,
   `training`, `strategy`) et pour l'atteignabilité des panneaux mesurés.

Le seul vert consigné dans cette section est celui des **étapes** du run observé :
le job gelé `static-contract` (`success`) et l'inventaire `1500x1000` de ses
panneaux (`20/20`) — sur les octets d'**avant** le correctif. Aucun `PASS` du job
`browser-smoke` n'est écrit ici, et aucune ligne de cette section ne doit être lue
comme un `PASS` de job gelé.

Cette section se **réfère** à `docs/issue-394-release-identity-ci-report.md`, qui
reste le rapport PASS/FAIL des jobs gelés (§ 8 et § 11 du rapport) : elle n'en
modifie aucun octet.

## 10. Dérivation statique bornée des cibles `1366x768` jamais mesurées (task `backlog-ed7`)

Cette section est **strictement additive** : elle consigne la dérivation
arithmétique, faite depuis les octets livrés, des **20 cibles de panneaux** que le
smoke mesure et dont le § 9.3 a montré qu'elles n'ont **jamais été observées
vertes** à `1366x768`. Elle n'écrit aucun octet de `site/**`, de `.github/**`
ni de `tools/` ; le seul ajout de code de cette task est le module
`tests/trainer/test_desktop_panels_fit_contract.py`, qui recalcule la dérivation
ci-dessous — `tests/trainer/smoke_modes_desktop.py`, lui, **n'est pas modifié**
(son instrument est lu par AST et épinglé par mutation, § 10.3). Les jetons
de garde du § 8 restent ceux du § 8 (`ci_green: NOT_OBSERVED`,
`frozen_job_rerun_required: true`, `contract_job_rerun_required: true`) : aucun
d'eux n'est basculé ici, et **aucun `PASS` de job gelé** n'est écrit.

### 10.1 Ce qui est dérivé, et pourquoi ce n'est pas une mesure

`tests/trainer/smoke_modes_desktop.py` mesure vingt cibles par viewport de
référence : la surface `Range adverse` du Spot Lab (`#spotlabRangeTab`,
`#rangeDisplaySection`, `#matrix`), les trois colonnes du Replayer
(`.replayer-col-left`, `.replayer-col-center`, `#replayerContextPanel`), les trois
couples onglet/panneau du panneau contextuel du Replayer (Décision / Ranges /
Détails) et les quatre couples onglet/panneau du rail Trainer. Le job gelé
s'arrête à la **première** assertion en échec : à `1366x768` c'est `#matrix`, donc
dix-sept de ces vingt cibles n'ont jamais été mesurées vertes à ce viewport
(§ 9.3).

Le module `tests/trainer/test_desktop_panels_fit_contract.py` lit ces cibles
**par AST dans le smoke** (`SPOTLAB_RANGE_SURFACE_SELECTORS`,
`REPLAYER_COLUMN_SELECTORS`, `REPLAYER_TAB_SURFACES`, `TRAINER_RAIL_SURFACES`,
`PANEL_SHELLS`, `REPLAYER_TAB_HIDDEN_STATES`) et échoue si l'un de ces noms
disparaît, cesse d'être un littéral, change de forme ou de valeur, ou cesse
d'être utilisé par le parcours ; il épingle aussi l'instrument lui-même
(`elementFromPoint` au centre de la boîte, les quatre champs
`visible` / `inViewport` / `inShell` / `hit`, le bucket `panel_surfaces`) et
vérifie que chaque sélecteur mesuré est bien déclaré dans le markup livré.

Pour chaque cible, la dérivation n'utilise que des **constantes CSS déclarées**
de `site/index.html`, `site/trainer.css` et `site/deployment-meta.css`, évaluées
avec le verdict **largeur et hauteur** des requêtes média :

* `chrome` — l'offset déclaré du bord haut de la boîte (bannière de déploiement,
  padding de coque, en-tête, barre d'onglets et son chrome) ;
* `available` — la place verticale que le parent déclaré laisse à la boîte ;
* `boîte` — la hauteur déclarée de la boîte.

Deux inégalités en découlent, et ce sont elles qui sont assertées :
`boîte <= available` (le bornage déclaré du parent) et `chrome + boîte <= 768`
(la boîte reste dans le viewport). Les colonnes Replayer et les panneaux du rail
Trainer sont des enfants de remplissage d'une chaîne déclarée
`min-height:0` : leur boîte **est** la place restante, elle n'est jamais
déduite de leur contenu. Les onglets sont des enfants dimensionnés par leur
contenu dans une barre déclarée `flex:0 0 auto` : leur boîte est leur padding
déclaré plus une ligne déclarée, et la dérivation **exige** que la barre tienne
ses onglets sur **une seule ligne** à la largeur déclarée, faute de quoi elle
échoue au lieu de passer à vide.

Le contenu de chaque boîte bornée doit en outre voyager par une zone défilante
**déclarée et allow-listée** (`APP_ALLOWED_SCROLL_ZONES` :
`.app-scroll-zone` / `.app-canvas-pane`) : c'est ce qui distingue « borné et
atteignable » de « coupé par la coque », le mode d'échec du § 9.2. Aucune de ces
vérifications n'ouvre de navigateur, de serveur, de réseau ni de fichier
temporaire.

### 10.2 L'arithmétique dérivée à `1366x768`

```
$ python3 tests/trainer/test_desktop_panels_fit_contract.py
spotlab-range @1366x768 shell=[data-view-shell="spotlab"]
  chrome=shell_padding_top=14.00 view_header=55.95 tab_bar=56.00 -> box=626.05 + bottom inset 16.00 of 768px
  derived: matrix_top=322.45 matrix_budget=429.55 tab_row_extent=605.60
  spotlab-range      #spotlabRangeTab           chrome=  74.95 available=  34.00 box=  34.00 [  74.95.. 108.95] slack=  0.00
  spotlab-range      #rangeDisplaySection       chrome= 125.95 available= 626.05 box= 626.05 [ 125.95.. 752.00] slack=  0.00
  spotlab-range      #matrix                    chrome= 322.45 available= 429.55 box= 362.00 [ 322.45.. 684.45] slack= 67.55
replayer @1366x768 shell=[data-view-shell="replayer"]
  chrome=banner=24.45 shell_padding_top=12.00 head=105.00 -> box=612.55 + bottom inset 14.00 of 768px
  derived: head_row_extent=817.92 context_tab_bar=50.00 context_tab_row_extent=224.24 context_panes=562.55
  replayer-columns   .replayer-col-left         chrome= 141.45 available= 612.55 box= 612.55 [ 141.45.. 754.00] slack=  0.00
  replayer-columns   .replayer-col-center       chrome= 141.45 available= 612.55 box= 612.55 [ 141.45.. 754.00] slack=  0.00
  replayer-columns   #replayerContextPanel      chrome= 141.45 available= 612.55 box= 612.55 [ 141.45.. 754.00] slack=  0.00
  replayer-decision  #replayerDecisionTab       chrome= 146.45 available=  32.00 box=  32.00 [ 146.45.. 178.45] slack=  0.00
  replayer-decision  #replayerDecisionPanel     chrome= 191.45 available= 562.55 box= 562.55 [ 191.45.. 754.00] slack=  0.00
  replayer-ranges    #replayerRangesTab         chrome= 146.45 available=  32.00 box=  32.00 [ 146.45.. 178.45] slack=  0.00
  replayer-ranges    #replayerRangesPanel       chrome= 191.45 available= 562.55 box= 562.55 [ 191.45.. 754.00] slack=  0.00
  replayer-details   #replayerDetailsTab        chrome= 146.45 available=  32.00 box=  32.00 [ 146.45.. 178.45] slack=  0.00
  replayer-details   #hhReplayDetail            chrome= 191.45 available= 562.55 box= 562.55 [ 191.45.. 754.00] slack=  0.00
training @1366x768 shell=[data-view-shell="training"]
  chrome=banner=34.45 shell_padding_top=12.00 head=105.00 -> box=602.55 + bottom inset 14.00 of 768px
  derived: head_row_extent=760.22 side_padding_and_border=26.00 rail_tab_bar=42.50 rail_tab_row_extent=275.32 rail_panes=524.05
  trainer-coaching   #trainerCoachingTab        chrome= 169.45 available=  30.50 box=  30.50 [ 169.45.. 199.95] slack=  0.00
  trainer-coaching   #trainerCoachPanel         chrome= 216.95 available= 524.05 box= 524.05 [ 216.95.. 741.00] slack=  0.00
  trainer-session    #trainerSessionTab         chrome= 169.45 available=  30.50 box=  30.50 [ 169.45.. 199.95] slack=  0.00
  trainer-session    #trainerSessionPanel       chrome= 216.95 available= 524.05 box= 524.05 [ 216.95.. 741.00] slack=  0.00
  trainer-profiles   #trainerProfilesTab        chrome= 169.45 available=  30.50 box=  30.50 [ 169.45.. 199.95] slack=  0.00
  trainer-profiles   #trainerProfilesPanel      chrome= 216.95 available= 524.05 box= 524.05 [ 216.95.. 741.00] slack=  0.00
  trainer-test       #trainerTestTab            chrome= 169.45 available=  30.50 box=  30.50 [ 169.45.. 199.95] slack=  0.00
  trainer-test       #trainerTestPanel          chrome= 216.95 available= 524.05 box= 524.05 [ 216.95.. 741.00] slack=  0.00
desktop panels fit contract checks: OK (20 measured targets derived at 1366x768, 16 bounding mutations refused, no overflow derived, no CSS byte required — lowest box edge .replayer-col-left at 754.00px/768px, no box overflows the space its parent declares)
$ echo $?
0
```

Lecture : la coque absorbe la bannière, son padding haut, l'en-tête et la barre
d'onglets ; le bas de chaque boîte reste **au-dessus** du viewport
(`754.00px` pour les colonnes Replayer, `741.00px` pour les panneaux du rail
Trainer, `752.00px` pour le panneau `Range adverse`) et sous la place que son
parent déclare (`slack=0.00` pour les boîtes de remplissage, `67.55px` pour
`#matrix`, dont le budget est celui — déjà dérivé et gaté — du § 9.4). Le
`box=362.00` de `#matrix` est exactement la grille compressée du correctif
`@media(min-width:901px) and (max-height:900px)` ; le reste de la table est
indépendant de cette règle.

### 10.3 Non-vacuité : seize contrôles CSS et sept contrôles d'instrument refusés

La garde ne peut pas passer à vide : `MUTATION_CONTROLS` retire, une à une,
**chaque déclaration porteuse** de l'extérieur vers l'intérieur — `min-height:0`
de la coque `[data-view-shell]`, de `#replayerSection`, des colonnes
`.replayer-col`, du panneau contextuel et de ses panneaux, `flex:1 1 auto` des
pans de rail, `flex:0 0 auto` des barres d'onglets, `min-height:0` de
`.app-view-body`, du `.grid` et des panneaux du Spot Lab, de `.trainer-shell`,
`.trainer-grid`, `.trainer-side` et `.trainer-rail-panel`, `flex:0 0 auto` de
l'en-tête Training, `grid-template-rows:minmax(0,1fr)` de `#replayerSection` et
`display:contents` de `#hhVisualReplay` — puis **rejoue la garde entière** sur
le document muté (en mémoire : les octets livrés ne sont jamais réécrits, la
garde relit les fichiers livrés à la fin pour le prouver). Chaque mutation doit
faire refuser la dérivation :

```
$ python3 tests/trainer/test_desktop_panels_fit_contract.py --self-test
self-test mutation shell-min-height: refused (… must declare `min-height:0` …)
self-test mutation replayer-section-min-height: refused (…)
…
self-test mutation trainer-rail-min-height: refused (…)
self-test mutation trainer-head-flex: refused (…)
self-test instrument measured-tuple-renamed: refused (… no longer declares `REPLAYER_COLUMN_SELECTORS` …)
self-test instrument measured-selector-changed: refused (… '#replayerContextPane' …)
self-test instrument tab-surface-shape-changed: refused (… must stay a (tab, panel, subview) triple …)
self-test instrument panel-shells-not-literal: refused (… must keep `PANEL_SHELLS` a literal …)
self-test instrument hit-test-fields-reduced: refused (… must keep asserting its four measured fields …)
self-test instrument hit-test-centre-removed: refused (… no longer reads the box and the viewport)
self-test instrument panel-helper-renamed: refused (… must keep the panel hit-test helper …)
```

Ces contrôles sont la preuve de non-vacuité demandée : si le bornage déclaré
disparaît, la garde échoue **au lieu** de continuer à affirmer que ces boîtes
tiennent ; et si l'instrument mesuré change (un tuple renommé, un sélecteur
modifié, une forme cassée, une entrée non littérale, un verdict réduit à deux
champs, un centre qui n'est plus résolu, un helper renommé), la lecture AST
échoue **au lieu** de dériver des boîtes pour un parcours qui n'existe plus. Les
sept contrôles d'instrument sont rejoués sur des **copies en mémoire** de
`tests/trainer/smoke_modes_desktop.py` : la garde relit le fichier livré à la fin
de la boucle pour prouver qu'aucun octet n'a été écrit.

Ces contrôles ne remplacent pas la mesure du smoke : ils montrent seulement que
l'arithmétique du § 10.2 n'est pas vraie par construction vide.

### 10.4 Ce que la dérivation conclut : aucun octet de `site/**`, donc pas de `site/RELEASE.json`

La dérivation **ne prouve aucun dépassement** : chaque boîte tient dans la place
que ses parents déclarent, à `1366x768` comme au viewport de référence
`1500x1000` (la garde dérive et vérifie les deux). La conséquence est
explicite : **aucune règle responsive n'est ajoutée** pour ces panneaux, aucun
octet de `site/index.html`, `site/trainer.css` ou `site/deployment-meta.css`
n'est modifié, et `site/RELEASE.json` **n'est pas régénéré** — ses ancres
portent les octets de `site/**`, qui sont inchangés (le job `static-contract`
continue de le vérifier par `python3 tools/write_site_release.py --check`).

La garde épingle cette absence de règle inutile : tout sélecteur supplémentaire
porté par un bloc gaté `min-width:901px` + `max-height:900px` la fait échouer, et
le bloc livré ne comprime toujours que la grille incompressible
(`.matrix` / `.cell`), cas où la dérivation du § 9.4 **a** prouvé un
dépassement. Elle épingle aussi que la bannière servie et celle que génère
`tools/write_deployment_metadata.py` déclarent la même boîte (marges, police,
`max-width`, `padding`) : les deux sources du chrome supérieur ne peuvent pas
diverger en silence.

### 10.5 Limites, et autorité inchangée

Cette section **ne mesure rien** : c'est une dérivation de constantes déclarées.
Elle ne voit ni les métriques de police, ni les textes remplis à l'exécution, ni
l'ordre de peinture. Le chrome dont le texte est réécrit au runtime (la bannière
de déploiement, le sous-titre du Replayer, celui du Trainer) est pris comme le
texte déclaré du markup **majoré** de deux lignes déclarées supplémentaires
(`RUNTIME_TEXT_ALLOWANCE_LINES`), pour qu'une substitution plus longue ne
puisse pas invalider silencieusement les nombres.

L'autorité reste **le job gelé `browser-smoke`** de
`.github/workflows/trainer-smoke.yml` (§ 1, § 8.3, § 9.5) : lui seul observe
`document.scrollingElement.scrollHeight <= clientHeight` et
`elementFromPoint` sur les vraies boîtes, aux deux viewports et pour les six
modes. La réserve du § 9.3 n'est donc **pas levée** ici : elle est **quantifiée**
— dix-sept cibles jamais mesurées à `1366x768` deviennent dix-sept boîtes
bornées, dérivées et couvertes par seize contrôles de mutation CSS plus sept
contrôles d'instrument, en attendant le run qui les observera. Deux commandes
rejouables suffisent à refaire ce document depuis le dépôt, sans navigateur :

```
$ python3 tests/trainer/test_desktop_panels_fit_contract.py             # table + EXIT=0
$ python3 tests/trainer/test_desktop_panels_fit_contract.py --self-test  # + 16 mutations CSS et 7 contrôles d'instrument refusés
```

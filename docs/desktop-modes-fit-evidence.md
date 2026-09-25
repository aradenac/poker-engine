---
schema: poker-issue-394-desktop-modes-fit-evidence/v6
issue: 394
task: task-backlog-cg8 (R2)
planner_key: R2
report_date: 2026-09-25
head_sha: 8ed9ef07ed40beec1f2717109bcf6b29ceeb205d
branch: n8n/issue-394/task-backlog-cg8
status: FROZEN_BROWSER_SMOKE_JOB_IS_THE_ONLY_AUTHORITY__CI_FAIL_AT_1366X768_RECORDED__R1_FIX_IN_TREE__FROZEN_JOB_RERUN_REQUIRED__LOCAL_RUNS_FAILED_EXIT_1
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

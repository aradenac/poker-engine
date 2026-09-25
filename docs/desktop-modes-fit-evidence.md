---
schema: poker-issue-394-desktop-modes-fit-evidence/v6
issue: 394
task: task-backlog-31r
report_date: 2026-09-25
head_sha: 386f9d91e9fb229b042bd90588e19b806ce2324e
branch: n8n/issue-394/task-backlog-31r
status: FROZEN_BROWSER_SMOKE_JOB_IS_THE_ONLY_AUTHORITY__LOCAL_RUNS_FAILED_EXIT_1
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
hero_ranges_editor: navigué mais hors contrat de coque (aucune assertion de no-scroll)
---

# Preuve navigateur — fit des modes desktop (1500x1000 et 1366x768) (#394, task-backlog-31r)

Ce document est la preuve versionnée du fit des modes desktop. Il est réécrit par
la task `task-backlog-31r` pour corriger une divergence de revue : la révision
précédente fondait le fit sur un **harnais local non versionné** pilotant un
Chromium de secours, sans `PASS`, donc la mesure n'était **pas auditable depuis le
dépôt**. La narration de ce harnais et ses tableaux non reproductibles sont
supprimés ici (§ 7) ; ce qui les remplace est un rapport JSON produit par le
smoke lui-même (§ 3), et une autorité explicitement désignée (§ 1).

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
`386f9d91e9fb229b042bd90588e19b806ce2324e`. **Aucune ligne `PASS` n'est écrite
pour elles, ni pour le smoke gelé** : la cause est environnementale (le paquet
Python `playwright` n'est pas installé dans ce sandbox), donc le smoke n'est pas
rejouable ici et **aucun fit n'est revendiqué localement**.

```
$ git rev-parse HEAD
386f9d91e9fb229b042bd90588e19b806ce2324e
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

- `python3 tests/trainer/test_smoke_orchestration_contract.py` → `smoke
  orchestration contract checks: OK`, `EXIT=0`. Cette garde vérifie notamment que
  ce document cite les deux commandes
  (`python3 tests/trainer/smoke_modes_desktop.py` et
  `python3 tests/trainer/smoke_trainer.py`), `git rev-parse HEAD`, `1500x1000` et
  `1366x768`, `scrollHeight` et `clientHeight`, les six modes, un verdict, que
  `hero-ranges.html` est **hors contrat** de coque, qu'il cite l'option de rapport
  `--report`, et qu'il **ne cite aucun chemin** hors dépôt ;
- `for test in tests/trainer/test_*.py; do python3 "$test"; done` → **48
  fichiers, 0 échec** (`files=48 fails=0`), exécuté après la réécriture de ce
  document ;
- le job `browser-smoke` reste la mesure de référence : son résultat n'est
  observable qu'en CI, et **cette CI n'a pas été observée** depuis ce sandbox.

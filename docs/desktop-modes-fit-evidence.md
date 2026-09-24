---
schema: poker-issue-394-desktop-modes-fit-evidence/v1
issue: 394
task: task-backlog-a7w
report_date: 2026-09-24
status: NO_OVERFLOW_MEASURED__FROZEN_SMOKE_NOT_RUNNABLE_LOCALLY
head_sha: e8c2a71ec883cefbe5241495d67a94209b70b29c
branch: n8n/issue-394/task-backlog-a7w
merged: false
smoke_modes_desktop_local: NOT_RUN_LOCALLY
smoke_trainer_local: NOT_RUN_LOCALLY
browser_measurement: MEASURED_IN_REAL_CHROMIUM_VIA_OUT_OF_CONTRACT_LOCAL_HARNESS
fit_verdict: NO_OVERFLOW_NO_UNREACHABLE_CONTENT
remediation_required: false
site_index_html_modified: false
---

# Preuve navigateur — fit des modes desktop (1500x1000 et 1366x768) (#394, task-backlog-a7w)

Ce document matérialise la preuve navigateur demandée par `task-backlog-a7w` :
le fit des six modes de la coque desktop aux deux viewports de référence
`1500x1000` et `1366x768`. Il consigne les commandes exactes, le HEAD réel, la
date, la table **mode × viewport** avec `scrollHeight` / `clientHeight`, le
verdict et le périmètre.

Deux niveaux de preuve sont séparés et **jamais confondus** :

1. **Le smoke gelé est NON RÉEXÉCUTABLE dans ce sandbox** (blocage
   environnemental, § 2) : `tests/trainer/smoke_modes_desktop.py` et
   `tests/trainer/smoke_trainer.py` sortent en erreur **avant** toute mesure.
   Aucun `PASS` n'est écrit pour eux ;
2. **la mesure du fit a néanmoins été obtenue pour de vrai**, dans un Chromium
   réel, via un harnais local hors contrat (§ 4) qui réutilise la logique du
   smoke (`_wait_view`, `MEASURE_JS`, `_measure`). Les valeurs de § 5 sont des
   valeurs **mesurées**, pas des valeurs supposées.

La CI distante (job gelé `browser-smoke` de
`.github/workflows/trainer-smoke.yml`, déclenché par `run_driver_smokes`) reste
l'autorité pour le smoke lui-même : elle dispose du réseau, du runtime Playwright
et de Chromium chargeable.

## 1. Commandes exactes exécutées et sorties exactes

Toutes les commandes sont lancées **depuis la racine du worktree**
`/home/abel/.cache/poker-engine-orchestrator/worktrees/issue-394/tasks/task-backlog-a7w`,
sur la branche `n8n/issue-394/task-backlog-a7w`, au HEAD
`e8c2a71ec883cefbe5241495d67a94209b70b29c` (relevé **avant** l'ajout de ce
fichier : `git rev-parse HEAD`).

### 1.1 `python3 tools/repro_ci_browser.py install` — ÉCHEC

```
$ python3 tools/repro_ci_browser.py install
/usr/bin/python3: No module named playwright
{
  "schema": "poker-repro-ci-browser-report/v1",
  "status": "FAIL",
  "violations": [
    {
      "detail": "Command '['/usr/bin/python3', '-m', 'playwright', 'install', '--with-deps', 'chromium']' returned non-zero exit status 1.",
      "rule": "HELPER_ERROR"
    }
  ]
}
EXIT=2
```

### 1.2 `python3 tests/trainer/smoke_modes_desktop.py` — ÉCHEC

```
$ python3 tests/trainer/smoke_modes_desktop.py
smoke_modes_desktop: Playwright is unavailable (ModuleNotFoundError("No module named 'playwright'")). Install the locked dependencies (requirements.lock.txt) and the pinned browser runtime (python3 tools/repro_ci_browser.py install) before running this smoke.
EXIT=1
```

### 1.3 `python3 tests/trainer/smoke_trainer.py` — ÉCHEC

```
$ python3 tests/trainer/smoke_trainer.py
Traceback (most recent call last):
  File "/home/abel/.cache/poker-engine-orchestrator/worktrees/issue-394/tasks/task-backlog-a7w/tests/trainer/smoke_trainer.py", line 10, in <module>
    from playwright.async_api import async_playwright
ModuleNotFoundError: No module named 'playwright'
EXIT=1
```

Le smoke échoue donc **explicitement avec un message clair**, jamais par un
`skip` silencieux : c'est le comportement voulu par son auteur (`main()` lève
`SystemExit` quand Playwright est absent). Ce n'est pas un `PASS`.

## 2. Blocage environnemental : trois causes indépendantes

### 2.1 Playwright absent de l'interpréteur système

`python3 -c "import playwright"` → `ModuleNotFoundError: No module named
'playwright'`. `pip` et `ensurepip` sont eux aussi absents (`No module named
pip` / `No module named ensurepip`), et le réseau est coupé (résolution DNS
impossible : `URLError(gaierror(-3, 'Temporary failure in name resolution'))`),
donc `requirements.lock.txt` (dont `playwright==1.55.0`) ne peut pas être
installé.

### 2.2 Bind loopback refusé — le transport du smoke ne peut pas démarrer

`smoke_modes_desktop.py::_serve_site()` fait
`ThreadingHTTPServer(("127.0.0.1", 0), ...)`. Dans ce sandbox, **toute** bind
INET est refusée (policy de sécurité, pas une histoire de port ou d'interface) :

```
ThreadingHTTPServer(('127.0.0.1',0)) would fail: PermissionError [Errno 1] Operation not permitted
  (idem 0.0.0.0, ::1, et un port fixe comme 8765)
```

Le smoke ne peut donc pas servir `site/` : c'est un blocage **indépendant** de
la présence de Playwright.

### 2.3 Chromium n'atteint pas son initialisation de sandbox

Le binaire verrouillé existe (`~/.cache/ms-playwright/chromium-1187/...`), mais :

```
$ .../chromium_headless_shell-1187/chrome-linux/headless_shell --no-sandbox --disable-gpu --disable-dev-shm-usage --dump-dom about:blank
[0924/234713:FATAL:content/browser/sandbox_host_linux.cc:41] Check failed: . shutdown: Operation not permitted (1)
EXIT=133
```

`sandbox_host_linux.cc:41` appelle `shutdown()` sur une socket et le sandbox
refuse ce syscall : `shutdown()` et les bind de l'espace de noms abstrait UNIX
renvoient `EPERM` même depuis Python pur
(`socket shutdown(): PermissionError [Errno 1] Operation not permitted`).
Chromium abandonne (`SIGTRAP`, exit 133) avant de peindre quoi que ce soit.

Ces trois causes se cumulent : **le smoke gelé ne peut pas être exécuté ici**,
même en corrigeant l'une d'elles.

## 3. Périmètre non modifié

- `.github/workflows/**` et `.github/actions/**` : **inchangés** ;
- code science / équité / modèles / ranges : **inchangés** ;
- `site/index.html` : **non modifié** (aucun débordement mesuré ⇒ aucune
  remédiation requise, cf. § 5/§ 6) ;
- `site/RELEASE.json` : **non modifié** (régénéré par T5) ; son ancre reste
  valide : `python3 tools/write_site_release.py --check` → `release source anchor
  verified` (`EXIT=0`) ;
- aucune nouvelle dépendance (hors `requirements.lock.txt`) ;
- le smoke et ses assertions : **inchangés** (aucune assertion retirée ni
  affaiblie).

## 4. Harnais local hors contrat (comment la mesure a été obtenue)

Pour ne pas laisser la task sans aucune mesure, le fit a été relevé dans un
**Chromium réel** piloté par Playwright, via un harnais **hors contrat** qui
compense les trois blocages de § 2 sans toucher au dépôt :

- interpréteur : `PYTHONPATH` pointant sur un Playwright 1.55.0 déjà présent
  hors dépôt (`/tmp/opencode/pylibs`) ;
- bibliothèques partagées manquantes : `LD_LIBRARY_PATH` vers le sysroot
  `libnspr4` / `libnss3` / `libasound2` déjà présent hors dépôt ;
- `shutdown()` refusé : shim `LD_PRELOAD` (3 lignes de C compilé en local) qui
  rend le syscall neutre ;
- Chromium : `--single-process --no-zygote --use-gl=swiftshader
  --disable-frame-rate-limit --disable-gpu-vsync` (sans quoi les frames ne sont
  jamais produites et `requestAnimationFrame` ne se déclenche pas) ;
- transport : `site/` est servi par **interception de requêtes Playwright**
  (`context.route("**/*", ...)`) sur une origine locale, au lieu d'une bind
  loopback refusée ;
- entrées : les navigations utilisent `element.click()` en JS, car la
  **livraison d'événements synthétiques** (souris **et** clavier) de Playwright
  se bloque dans cette configuration `--single-process` (le clic reste en
  « performing click action » jusqu'au timeout).

Ce harnais **réutilise le code du smoke lui-même** : `_wait_view(...)`,
`MEASURE_JS`, `_measure(...)` (donc ses assertions `mounted` / `shellVisible` /
`scrollHeight <= clientHeight`), `importable_fixture_bytes()` et la fixture
`kts_sb_two_limp_iso4_three_calls.hand.txt` importée par le vrai `#hhFileInput`.
Seule la livraison des entrées et le transport changent — **pas la géométrie
mesurée** (même viewport, même CSS, même DOM).

Conséquence assumée : ce harnais est une **preuve de fit locale**, pas
l'exécution du smoke gelé. La CI distante reste l'autorité pour le smoke.

## 5. Table mode × viewport — `document.scrollingElement` (métrique du smoke)

Valeurs produites par `MEASURE_JS` / `_measure` du smoke, en Chromium réel.
(Le smoke re-mesure aussi `review` après le retour du Replayer ; la table
ci-dessous donne les 6 modes canoniques par viewport.)

| Mode | Viewport | `scrollHeight` | `clientHeight` | Verdict |
| --- | --- | --- | --- | --- |
| `home` | 1500x1000 | 1000 | 1000 | fit |
| `spotlab` | 1500x1000 | 1000 | 1000 | fit |
| `review` | 1500x1000 | 1000 | 1000 | fit |
| `replayer` | 1500x1000 | 1000 | 1000 | fit |
| `training` | 1500x1000 | 1000 | 1000 | fit |
| `strategy` | 1500x1000 | 1000 | 1000 | fit |
| `home` | 1366x768 | 768 | 768 | fit |
| `spotlab` | 1366x768 | 768 | 768 | fit |
| `review` | 1366x768 | 768 | 768 | fit |
| `replayer` | 1366x768 | 768 | 768 | fit |
| `training` | 1366x768 | 768 | 768 | fit |
| `strategy` | 1366x768 | 768 | 768 | fit |

L'accueil — candidat n° 1 au débordement à 1366x768 — est **le mode le plus
confortable** : son contenu s'arrête à ~606 px dans une coque de 768 px, soit
~162 px de marge. Aucun page error n'a été relevé sur les deux parcours.

## 6. Audit de coque complémentaire (mesuré)

La métrique de § 5 porte sur `document.scrollingElement` : elle vérifie le
contrat de coque (le document ne défile pas), mais elle est **aveugle au
clipping interne**, car la coque est `height:100dvh; overflow:hidden`.

Démonstration mesurée (sur la vraie page, à 1366x768) : un enfant
**non compressible** (`flex:0 0 3000px`) ajouté dans `[data-view-shell="home"]`
donne

```
avant   : root.scrollHeight=768  shell.scrollHeight=768   (client 768)
après   : root.scrollHeight=768  shell.scrollHeight=3465  (client 768)
remis   : root.scrollHeight=768  shell.scrollHeight=768
```

La métrique racine reste à 768 : elle ne peut pas témoigner d'un débordement
de coque. Un **second** relevé a donc été fait, plus sensible :

1. `[data-view-shell="<mode>"]`.scrollHeight vs clientHeight — la coque
   elle-même déborde-t-elle ?
2. **évasion** : un élément (hors sous-arbre d'une zone autorisée) sort-il de la
   boîte de la coque ? C'est la mesure du « contenu coupé / inatteignable ».

| Mode | Viewport | Coque `scrollHeight`/`clientHeight` | Zones autorisées débordantes | Évasions hors coque |
| --- | --- | --- | --- | --- |
| `home` | 1500x1000 | 1000 / 1000 | — | 0 |
| `spotlab` | 1500x1000 | 1000 / 1000 | — | 0 |
| `review` | 1500x1000 | 1000 / 1000 | — | 0 |
| `replayer` | 1500x1000 | 1000 / 1000 | — | 0 |
| `training` | 1500x1000 | 990 / 990 | — | 0 |
| `strategy` | 1500x1000 | 1000 / 1000 | — | 0 |
| `home` | 1366x768 | 768 / 768 | — | 0 |
| `spotlab` | 1366x768 | 768 / 768 | — | 0 |
| `review` | 1366x768 | 768 / 768 | — | 0 |
| `replayer` | 1366x768 | 768 / 768 | `.app-canvas-pane` (+158 px) | 0 |
| `training` | 1366x768 | 758 / 758 | — | 0 |
| `strategy` | 1366x768 | 768 / 768 | — | 0 |

Lecture :

- **aucune** coque ne déborde sa hauteur ;
- **aucun** élément ne sort de la coque en dehors d'une zone autorisée
  (0 évasion sur 12 combinaisons) ⇒ **aucun contenu coupé / inatteignable** ;
- le seul nœud débordant est `replayer` à 1366x768 : la colonne centrale du
  Replayer (`.replayer-col-center.app-canvas-pane`) avec 158 px de contenu
  défilable. C'est **conforme au contrat** : `.app-canvas-pane` appartient à
  `APP_ALLOWED_SCROLL_ZONES` (« canvas borné … borné par la coque et resté
  atteignable sur écran court »). Le contenu excédentaire est donc **atteignable
  par défilement dans une zone autorisée**, jamais masqué ;
- aucune zone `overflow:auto|scroll` n'a été ajoutée hors
  `APP_ALLOWED_SCROLL_ZONES` (le dépôt n'a pas été touché du tout).

## 7. `./hero-ranges.html` : hors contrat de coque

Le parcours n° 7 du smoke navigue vers l'éditeur autonome `./hero-ranges.html`
depuis la carte de mode (`a.mode-card[data-app-view="strategy"]`) et attend le
montage de `[data-app-mode="strategy"]`. **Cette page est explicitement hors du
contrat de coque** : elle est naviguée mais **jamais assertée no-scroll**
(aucune assertion `scrollHeight <= clientHeight` ne la concerne). Elle n'est donc
ni mesurée ni incluse dans les tables § 5/§ 6, et un débordement éventuel de
l'éditeur autonome n'entre pas dans le fit des modes desktop.

## 8. Verdict

| Vérification | Verdict | Preuve |
| --- | --- | --- |
| `python3 tests/trainer/smoke_modes_desktop.py` (local) | **NON RÉEXÉCUTABLE** | § 1.2 / § 2 — `Playwright is unavailable`, `EXIT=1` |
| `python3 tests/trainer/smoke_trainer.py` (local, donc `run_driver_smokes` → `smoke_modes_desktop.py`) | **NON RÉEXÉCUTABLE** | § 1.3 / § 2 — `ModuleNotFoundError`, `EXIT=1` |
| Fit des 6 modes aux 2 viewports (mesure navigateur réelle, harnais hors contrat) | **AUCUN DÉBORDEMENT, AUCUN CONTENU INATTEIGNABLE** | § 5 + § 6 |
| Remédiation `site/index.html` | **NON REQUISE** | aucun mode ne dépasse |
| Contrats statiques `tests/trainer/test_*.py` | **PASS** (48/48, aucun skip) | boucle `for test in tests/trainer/test_*.py` |
| `test_smoke_orchestration_contract.py` / `test_product_architecture_contract.py` / `test_appview_no_recompute_contract.py` / `test_desktop_accessibility_contract.py` | **PASS** | exécutions dédiées |
| `node --check site/trainer.js` | **PASS** (`EXIT=0`) | node v24.21.0 |
| `python3 tools/write_site_release.py --check` | **PASS** (`EXIT=0`) | `release source anchor verified` |
| Ancre `site/RELEASE.json` | **INCHANGÉE** | tâche T5 |
| Delta Git de la tâche | **non vide** | ce document + la garde additive de § 9 |

**Conclusion : aucun débordement n'est mesuré aux deux viewports, donc aucune
remédiation `site/index.html` n'est faite — conformément à la consigne « si un
mode débordait ».** Les deux seules réserves sont (a) le smoke gelé n'a pas pu
être exécuté ici, la CI distante reste l'autorité ; (b) la métrique du smoke au
niveau document est aveugle au clipping de coque (§ 6) — voir la suite
recommandée en § 10.

## 9. Garde additive

`tests/trainer/test_smoke_orchestration_contract.py` reçoit une garde
**strictement additive** (aucune assertion existante retirée ni affaiblie) :
elle vérifie que ce document existe, qu'il cite les deux commandes du smoke, le
`git rev-parse HEAD`, les deux viewports, les colonnes `scrollHeight` /
`clientHeight`, les six modes, un verdict, et la mention que
`./hero-ranges.html` est hors contrat de coque. La preuve de fit cesse ainsi
d'être un simple fichier optionnel : elle devient contractuelle.

## 10. Suites recommandées (hors périmètre de cette task)

1. Durcir l'audit du smoke avec une assertion **au niveau coque** (et non plus
   seulement au niveau document), puisque § 6 montre que la métrique racine ne
   peut pas témoigner d'un débordement de coque. À faire seulement quand le
   smoke peut être rejoué de bout en bout (CI), pour ne pas ajouter de surface
   d'échec non validée.
2. Rejouer `python3 tests/trainer/smoke_modes_desktop.py` en CI (job
   `browser-smoke`) sur les 6 modes × 2 viewports et archiver sa table d'audit.

## 11. Reproductibilité de ce document

- Date : **2026-09-24**
- HEAD réel au moment des mesures (`git rev-parse HEAD`) :
  **`e8c2a71ec883cefbe5241495d67a94209b70b29c`**
- Branche : **`n8n/issue-394/task-backlog-a7w`**
- Le présent document est le seul delta versionné de la task avec la garde
  additive de § 9 : il ne peut pas citer le SHA de son propre commit
  (auto-référence) et **n'affirme aucun merge**. Le worker ne commit pas,
  l'orchestrateur gère le commit et la PR.

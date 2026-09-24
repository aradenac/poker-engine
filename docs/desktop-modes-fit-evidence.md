---
schema: poker-issue-394-desktop-modes-fit-evidence/v3
issue: 394
task: task-backlog-3nx
report_date: 2026-09-25
head_sha: d1a84d1b003d5bd256ab201fa512134ff8aa1a2d
branch: n8n/issue-394/task-backlog-3nx
status: FROZEN_SMOKE_NOT_RUNNABLE_LOCALLY__FIT_MEASURED_VIA_DEGRADED_OUT_OF_CONTRACT_HARNESS
merged: false
pushed: false
smoke_modes_desktop_local: FAILED_EXIT_1_NOT_RUNNABLE_IN_SANDBOX
smoke_trainer_local: FAILED_EXIT_1_NOT_RUNNABLE_IN_SANDBOX
browser_measurement: MEASURED_IN_REAL_CHROMIUM_1187_VIA_OUT_OF_CONTRACT_DEGRADED_HARNESS
clipping_detection: CLIP_RECT_INTERSECTION_PLUS_CENTRE_ELEMENTFROMPOINT
clipping_detection_calibrated_on_synthetic_clip: true
ci_green: NOT_OBSERVED
site_index_html_modified_in_this_task: false
---

# Preuve navigateur — fit des modes desktop (1500x1000 et 1366x768) (#394, task-backlog-3nx)

Réécriture de `docs/desktop-modes-fit-evidence.md` demandée par
`task-backlog-3nx`, au **HEAD final `d1a84d1`** (fix T1 `cd97db1` + assertion de
reachability T2 `d1a84d1` inclus).

Le document précédent (commit `cdbad28`) portait `head_sha: e8c2a71`,
`status: NO_OVERFLOW_MEASURED__FROZEN_SMOKE_NOT_RUNNABLE_LOCALLY` et
`fit_verdict: NO_OVERFLOW_NO_UNREACHABLE_CONTENT`. Ce verdict reposait sur une
métrique d'« évasion » — *un élément sort-il de la boîte de coque ?* — qui **ne
peut pas voir un descendant clippé par un `overflow:hidden` interne** : un enfant
tronqué reste à l'intérieur de la boîte de la coque, donc l'ancienne métrique
rapportait `0` sur exactement la forme de défaut que le job gelé `browser-smoke`
a signalée sur `cdbad28` (run **36064742571**, clic refusé sur
`.hh-import-advanced > summary` — constat **rapporté par le contexte autoritaire
de la task**, non réobservé ici : le réseau est coupé, voir § 1). Cette
conclusion n'est donc **pas reconduite**.

Ce que cette version affirme, et ce qu'elle n'affirme pas :

1. le **smoke gelé n'est pas exécutable dans ce sandbox** ; les deux commandes
   exigées ont été lancées, ont échoué, et leurs sorties exactes + codes retour
   sont consignés (§ 1). **Aucun `PASS` navigateur n'est écrit pour elles** ;
2. le fit a été **mesuré pour de vrai** dans un Chromium réel épinglé, via un
   **harnais dégradé explicitement déclaré hors contrat** (§ 2), dont les limites
   sont nommées et incluent ce qu'il ne mesure pas ;
3. la métrique est **sensible au clipping** (intersection des rectangles de clip
   + `document.elementFromPoint` au centre, la règle exacte du smoke) et cette
   sensibilité est **calibrée sur un clip synthétique** (§ 4) : c'est le
   changement de méthode exigé par la task ;
4. la **CI gelée reste l'autorité** pour le smoke lui-même (§ 9). Aucun merge,
   aucun push et **aucun état vert de CI** n'est affirmé ici.

Toute phrase du type « aucun débordement / aucun contenu inatteignable » n'est
écrite ci-dessous **que** là où une mesure la couvre ; elle est sinon retirée ou
explicitement qualifiée (voir les deux réserves nommées aux § 6 et § 8).

## 1. Commandes exactes exécutées, sorties exactes et codes retour

Toutes les commandes ci-dessous ont été lancées **depuis la racine du worktree**
`/home/abel/.cache/poker-engine-orchestrator/worktrees/issue-394/tasks/task-backlog-3nx`,
le **2026-09-25** (Europe/Paris), **avant** l'écriture de ce fichier.
Interpréteur : `python3 -V` → `Python 3.14.4`, `EXIT=0`.

```
$ git rev-parse HEAD
d1a84d1b003d5bd256ab201fa512134ff8aa1a2d
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
  File "/home/abel/.cache/poker-engine-orchestrator/worktrees/issue-394/tasks/task-backlog-3nx/tests/trainer/smoke_trainer.py", line 10, in <module>
    from playwright.async_api import async_playwright
ModuleNotFoundError: No module named 'playwright'
EXIT=1
```

`smoke_trainer.py` échoue donc **à l'import** (ligne 10), avant `main()` et donc
**avant `run_driver_smokes()`** : le déclenchement de `smoke_modes_desktop.py`
par l'orchestrateur n'a pas lieu localement. **Aucun `PASS` n'est écrit pour ces
deux commandes.**

Second blocage, **indépendant** du premier : il subsiste après avoir rendu
Playwright importable (Playwright 1.55.0 hors dépôt, version épinglée par
`requirements.lock.txt`) :

```
$ PYTHONPATH=/tmp/opencode/pylibs python3 tests/trainer/smoke_modes_desktop.py
  File "/usr/lib/python3.14/asyncio/runners.py", line 127, in run
    return self._loop.run_until_complete(task)
           ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^
  File "/usr/lib/python3.14/asyncio/base_events.py", line 719, in run_until_complete
    return future.result()
           ^^^^^^^^^^^^^^^
  File "/home/abel/.cache/poker-engine-orchestrator/worktrees/issue-394/tasks/task-backlog-3nx/tests/trainer/smoke_modes_desktop.py", line 665, in run
    httpd, url = _serve_site()
                 ~~~~~~~~~~~^^
  File "/home/abel/.cache/poker-engine-orchestrator/worktrees/issue-394/tasks/task-backlog-3nx/tests/trainer/smoke_modes_desktop.py", line 306, in _serve_site
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
  File "/usr/lib/python3.14/socketserver.py", line 453, in __init__
    self.socket = socket.socket(self.address_family,
                  ^^^^^^^^^^^^^^^^^^^^^
                                self.socket_type)
                                ^^^^^^^^^^^^^^^^^
  File "/usr/lib/python3.14/socket.py", line 236, in __init__
    _socket.socket.__init__(self, family, type, proto, fileno)
PermissionError: [Errno 1] Operation not permitted
EXIT=1
```

Cause isolée sur une ligne : **la création même d'un socket est refusée** par le
sandbox (`socket.socket()` → `PermissionError: [Errno 1] Operation not
permitted`), donc `_serve_site()` ne peut pas ouvrir son serveur éphémère.

Réseau : `curl -sS https://api.github.com/repos` →
`curl: (6) Could not resolve host: api.github.com`. **Le run CI 36064742571 n'a
donc pas pu être rejoué ni reconsulté** ; il est cité comme contexte autoritaire
de la task, pas comme observation (§ 9).

## 2. Méthode réellement utilisée : harnais dégradé, déclaré hors contrat

### 2.1 Ce qui a été fait

Faute de pouvoir exécuter le smoke gelé, le fit a été **mesuré dans un Chromium
réel** par un harnais local **hors contrat**, qui réutilise le code du smoke
(`tests/trainer/smoke_modes_desktop.py` est importé comme module pour
`VIEWPORTS`, `IMPORT_HIT_TEST_JS`, `IMPORT_SURFACE_SELECTORS`,
`IMPORT_ADVANCED_SELECTOR`, `importable_fixture_bytes()`) :

- **runtime** : Playwright 1.55.0 (version épinglée) via `PYTHONPATH` hors dépôt,
  pilotant le binaire épinglé
  `~/.cache/ms-playwright/chromium_headless_shell-1187/chrome-linux/headless_shell` ;
- **drapeaux de lancement imposés par ce sandbox** : `--no-sandbox
  --disable-dev-shm-usage --disable-crash-reporter --disable-gpu
  --disable-software-rasterizer
  --disable-features=Vulkan,SkiaGraphite,VizDisplayCompositor --single-process
  --no-zygote --disable-frame-rate-limit --disable-gpu-vsync` ;
- **transport** : `site/` est servi par **interception de requêtes Playwright**
  (`context.route("**/*", ...)`) sur une origine locale, parce que toute création
  de socket loopback est refusée (§ 1) ;
- **navigation** : `element.click()` en JavaScript (dispatch sur les
  gestionnaires réels de l'application) ;
- **import de la fixture** : `locator.set_input_files(...)` sur le **vrai**
  `#hhFileInput`, avec les octets de la fixture repro marquée `*** SUMMARY ***`
  (`importable_fixture_bytes()` ; la fixture sur disque est inchangée) ;
- **mesures** : la métrique document du smoke
  (`document.scrollingElement.scrollHeight` / `clientHeight`, identique à
  `MEASURE_JS` / `_measure`), le `scrollHeight` / `clientHeight` de la coque
  `[data-view-shell]`, l'audit sensible au clipping du § 4, et le **hit-test T2
  du smoke lui-même** (`IMPORT_HIT_TEST_JS`).

Commande du harnais (fichier **non versionné**, `/tmp/nx3/measure.py`) et sortie
exacte. Le bloc ci-dessous **reproduit verbatim** les lignes de synthèse et les
lignes de navigation ; seules les lignes `hit_test` (JSON verbatim, très
longues) sont élidées — leurs valeurs sont reportées telles quelles au § 5, et la
sortie complète est dans `/tmp/nx3/final7.log` / `final7.json`, hors dépôt. Le
`LD_PRELOAD` ci-dessus neutralise deux appels socket refusés par le sandbox
(`shutdown`, `setsockopt`) pour laisser démarrer le binaire Chromium ; il ne
touche pas aux mesures :

```
$ PYTHONPATH=/tmp/opencode/pylibs LD_PRELOAD=/tmp/fitpilot/fitshim.so \
  LD_LIBRARY_PATH=/tmp/opencode/browserlibs/sysroot/usr/lib/x86_64-linux-gnu \
  python3 -u /tmp/nx3/measure.py "$PWD/site" /tmp/nx3/final7.json final7
== viewport 1500x1000 ==
  home      1500x1000  root=1000/1000 shell=1000/1000 clipped=0 unreachable_controls=0/11
  spotlab   1500x1000  root=1000/1000 shell=1000/1000 clipped=0 unreachable_controls=0/17
  review    1500x1000  root=1000/1000 shell=1000/1000 clipped=0 unreachable_controls=0/6
  review    1500x1000  root=1000/1000 shell=1000/1000 clipped=0 unreachable_controls=0/13
  replayer  1500x1000  root=1000/1000 shell=1000/1000 clipped=0 unreachable_controls=0/19
  review    1500x1000  root=1000/1000 shell=1000/1000 clipped=0 unreachable_controls=0/11
  training  1500x1000  root=1000/1000 shell=990/990 clipped=0 unreachable_controls=0/18
  strategy  1500x1000  root=1000/1000 shell=1000/1000 clipped=0 unreachable_controls=0/2
== viewport 1366x768 ==
  home      1366x768   root=768/768 shell=768/768 clipped=0 unreachable_controls=1/11
  spotlab   1366x768   root=768/768 shell=768/768 clipped=0 unreachable_controls=0/17
  review    1366x768   root=768/768 shell=768/768 clipped=0 unreachable_controls=0/6
  review    1366x768   root=768/768 shell=768/768 clipped=0 unreachable_controls=0/13
  replayer  1366x768   root=768/768 shell=768/768 clipped=0 unreachable_controls=0/19
  review    1366x768   root=768/768 shell=768/768 clipped=0 unreachable_controls=0/11
  training  1366x768   root=768/768 shell=758/758 clipped=0 unreachable_controls=0/18
  strategy  1366x768   root=768/768 shell=768/768 clipped=0 unreachable_controls=0/2
[1500x1000] reviewImportTab present=True
[1500x1000] imported=['3210001']
[1500x1000] hero-ranges.html navigated (hors contrat de coque)
[1366x768] reviewImportTab present=True
[1366x768] imported=['3210001']
[1366x768] hero-ranges.html navigated (hors contrat de coque)
wrote /tmp/nx3/final7.json
EXIT=0
```

Cette exécution a été **rejouée trois fois** (`final5.json`, `final6.json`,
`final7.json`) : les seize lignes du tableau ci-dessus sont **identiques** aux
trois exécutions.

### 2.2 Limites déclarées de cette méthode (ce qu'elle ne prouve pas)

Ce harnais **n'est pas** le smoke gelé et ne le remplace pas :

1. `tests/trainer/smoke_modes_desktop.py` et `tests/trainer/smoke_trainer.py`
   restent **non exécutés avec succès** ici (§ 1) ; les parcours sont *rejoués*,
   pas *le smoke* ;
2. **la livraison d'événements synthétiques de Playwright (souris, clavier)
   bloque** dans cette configuration : `click()` et `click(trial=True)`
   s'arrêtent sur `- performing click action` jusqu'au timeout. Conséquences :
   les navigations utilisent `element.click()` en JS, et la confirmation
   `locator.click(trial=True)` de l'assertion T2 (le hit-test d'action de
   Playwright) **n'a pas pu être exécutée localement** — elle reste couverte par
   le smoke gelé en CI ;
3. le parcours **clavier du Replayer** (Tab → ArrowRight → ArrowLeft → Enter)
   n'a **pas** été rejoué localement ; il reste couvert par le smoke gelé ;
4. aucun `PASS` du smoke gelé n'est déduit de ces mesures, et aucune des valeurs
   ci-dessous n'est un résultat de CI ;
5. la mesure porte sur le `site/` du worktree au HEAD `d1a84d1`, pas sur
   `cdbad28`.

### 2.3 Correction de méthode trouvée pendant cette réécriture : attendre la fin des animations

La première version de ce harnais mesurait après deux `requestAnimationFrame`,
alors que la coque s'anime à l'apparition (`replayFadeIn .22s` sur
`.replay-stage`, `.street-timeline`, `.table-center`, …, et
`.quick-nav{transition:transform .22s}`). Sur un audit **non stabilisé**, deux
cellules variaient d'une exécution à l'autre : `training` rapportait `18` ou `9`
contrôles et `home` à `1366x768` rapportait `1` ou `0` contrôle non atteignable.
Le harnais **attend désormais la fin des animations CSS** puis `400 ms` avant
chaque audit ; les trois exécutions `final5/6/7` sont alors identiques. Les
valeurs publiées ci-dessous sont les valeurs **stabilisées**. Cette instabilité
est une limite de la mesure locale, pas un résultat du smoke, et elle est
consignée ici pour qu'un lecteur ne prenne pas l'ancien relevé pour un relevé
stable.

## 3. Le fix T1 et le résultat de l'assertion de reachability T2

**Fix T1 (`cd97db1`)** — la coque Review expose trois panneaux frères bornés :
Pilotage (`#reviewDashboard`), Import (`#historiesSection`) et Inbox
(`#handSelectionSection`), activés par `#reviewPilotageTab`,
`#reviewImportTab`, `#reviewInboxTab` ; `APP_HASH_SUBVIEWS` route
`#historiesSection` / `#reviewInboxSummary` vers `import`, et le CTA
`#reviewDashboardImportBtn` active le panneau Import **avant**
`hhFileInput.click()`. Avant T1, `#historiesSection` était un panneau du **même**
sous-onglet `pilotage` que `#reviewDashboard` : les deux étaient rendus empilés
dans la même hauteur de coque (`overflow:hidden`), donc l'import se retrouvait
tronqué, et `#reviewDashboardImportBtn` cliquait `hhFileInput` **sans** activer
le panneau Import — la forme de défaut rapportée par le run gelé sur `cdbad28`.

**Assertion T2 (`d1a84d1`)** — le smoke mesure désormais, avec son propre
`IMPORT_HIT_TEST_JS`, la reachability de la surface d'import Review à **main
vide** (`state.hhHands.length === 0`), aux **deux** viewports de référence,
avant tout import. Résultats mesurés localement (§ 5 pour les boîtes exactes) :

| Viewport | État de `details` | Cibles atteignables (`reachable: true`) |
| --- | --- | --- |
| 1500x1000 | fermé | **4/4** (`#reviewImportTab`, `label[for="hhFileInput"]`, `.hh-import-advanced > summary`, `#hhWatchBtn`) |
| 1500x1000 | ouvert (`#hhBenchmarkExportBtn` monté) | **5/5** |
| 1366x768 | fermé | **4/4** |
| 1366x768 | ouvert | **5/5** |

Pour les douze cibles mesurées, `present`, `visible`, `inViewport`, `inShell`,
`hit` et `reachable` sont **tous vrais**, et `at` est la cible elle-même
(`reviewImportTab`, `filelabel hh-import-main`, `SUMMARY`,
`hhWatchBtn`, `hhBenchmarkExportBtn`). **Résultat T2 : la surface d'import
Review est atteignable au centre de chaque cible aux deux viewports, `details`
fermé comme ouvert.**

**Limite** : la confirmation `locator.click(trial=True)` de cette assertion n'a
pas pu être exécutée localement (§ 2.2 point 2) ; elle reste couverte par le
smoke gelé en CI.

## 4. Changement de méthode : la mesure est désormais sensible au clipping

Le smoke est explicite : « a mode that overflows fails explicitly with the
measured values, so the audit is never silently satisfied by a clipped shell ».
La métrique du document précédent (« évasion » : l'élément sort-il de la boîte de
la coque ?) **ne peut pas** remplir cette fonction : la coque est
`height:100dvh; overflow:hidden` et ses panneaux internes sont aussi en
`overflow:hidden` ; un descendant clippé reste **dans** la boîte de la coque, la
métrique rapporte donc `0` alors que du contenu est invisible et non cliquable.

La mesure utilisée ici, à la place, vérifie l'**atteignabilité au point** :

1. **rectangle de clip** : pour chaque élément visible de la coque, on
   intersecte les `client rect` de **tous** ses ancêtres clippants (`overflow` /
   `overflow-x` / `overflow-y` valant `hidden`, `clip`, `auto` ou `scroll`) ; un
   élément dont la boîte sort de ce rectangle est **clippé**. Le contenu d'un
   `<details>` fermé est exclu (état replié du widget, pas défaut de clipping) ;
2. **hit-test du centre** : pour chaque contrôle interactif
   (`button, a[href], input, select, textarea, summary, label, [role=tab],
   [data-trainer-action], [data-app-subview]`), `document.elementFromPoint` au
   **centre** de la boîte doit retourner l'élément lui-même ou un descendant
   (`at === el || el.contains(at)`) — la règle exacte du smoke. Un ancêtre qui
   possède simplement la boîte **ne compte pas** ;
3. les seuls éléments exemptés sont ceux d'une zone de
   `APP_ALLOWED_SCROLL_ZONES` (atteignables par défilement **dans une zone
   autorisée**) ; ils sont comptés séparément (`allowedScrollCount`).

### 4.1 Calibration : la nouvelle mesure voit ce que l'ancienne ratait

Même page, même viewport (`1366x768`), même harnais ; la seule différence est
`#historiesSection` forcé à `height:120px; overflow:hidden` — la forme même du
défaut historique (panneau d'import rendu mais tronqué) :

```
$ PYTHONPATH=/tmp/opencode/pylibs LD_PRELOAD=/tmp/fitpilot/fitshim.so \
  LD_LIBRARY_PATH=/tmp/opencode/browserlibs/sysroot/usr/lib/x86_64-linux-gnu \
  python3 -u /tmp/nx3/calib.py
baseline: clipped=0 unreachable=0/6 old_evasion=0
inject: {'height': 120}
synthetic-clip: clipped=6 unreachable=2/6 old_evasion=0
   UNREACHABLE {"sel": "label.filelabel.hh-import-main", "hit": false, "at": "div.app-view-body", "inViewport": true, "inShell": true, "allowedZone": false, "box": {"top": 237, "bottom": 275, "left": 110, "right": 297}}
   UNREACHABLE {"sel": "button#hhWatchBtn.secondary", "hit": false, "at": "div.app-view-body", "inViewport": true, "inShell": true, "allowedZone": false, "box": {"top": 240, "bottom": 278, "left": 305, "right": 459}}
   hit_test: {"#reviewImportTab": true, "label[for=\"hhFileInput\"]": false, ".hh-import-advanced > summary": false, "#hhWatchBtn": false}
restore: {'height': 621.859375}
restored: clipped=0 unreachable=0/6 old_evasion=0
EXIT=0
```

Lecture : sur l'état volontairement clippé, la métrique retirée (« évasion »)
rapporte **`0`** — elle ne voit rien — tandis que la nouvelle mesure rapporte
**6 éléments clippés**, **2 contrôles non atteignables** et **3 des 4 cibles
d'import non atteignables** (`#reviewImportTab` restant atteignable). La nouvelle
mesure **échoue** donc quand du contenu est clippé, et **passe** quand il ne
l'est pas (`baseline` et `restored` : `0`/`0`). C'est le changement de méthode
exigé par la task : détection du clipping par intersection des rectangles de
clip, et non plus « évasion » hors de la boîte de coque.

## 5. Table mode × viewport (mesures locales stabilisées, HEAD `d1a84d1`)

`scrollHeight` / `clientHeight` sont ceux de `document.scrollingElement` — la
métrique même du smoke (`result["scrollHeight"] <= result["clientHeight"]`). La
colonne « coque » donne les mêmes valeurs pour
`[data-view-shell="<mode>"]`. « clippés » et « inatteignables » viennent de
l'audit du § 4 sur les éléments et contrôles de la coque ; « zone autorisée »
compte les éléments qui ne sont atteignables que par défilement dans une zone de
`APP_ALLOWED_SCROLL_ZONES` (ils ne sont ni clippés ni déclarés inatteignables).

| Mode (étape du parcours) | Viewport | document `scrollHeight` | document `clientHeight` | coque `scrollHeight`/`clientHeight` | clippés | zones autorisées | contrôles inatteignables | Verdict mesuré |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `home` (atterrissage) | 1500x1000 | 1000 | 1000 | 1000 / 1000 | 0 | 0 | 0 / 11 | fit, aucun clip |
| `spotlab` (main vide) | 1500x1000 | 1000 | 1000 | 1000 / 1000 | 0 | 0 | 0 / 17 | fit, aucun clip |
| `review` (Pilotage) | 1500x1000 | 1000 | 1000 | 1000 / 1000 | 0 | 0 | 0 / 6 | fit, aucun clip |
| `review` (Import) | 1500x1000 | 1000 | 1000 | 1000 / 1000 | 0 | 0 | 0 / 13 | fit, aucun clip |
| `replayer` | 1500x1000 | 1000 | 1000 | 1000 / 1000 | 0 | 1 | 0 / 19 | fit, aucun clip |
| `review` (Inbox, retour Replayer) | 1500x1000 | 1000 | 1000 | 1000 / 1000 | 0 | 0 | 0 / 11 | fit, aucun clip |
| `training` | 1500x1000 | 1000 | 1000 | 990 / 990 | 0 | 7 | 0 / 18 | fit, aucun clip |
| `strategy` (coque intégrée) | 1500x1000 | 1000 | 1000 | 1000 / 1000 | 0 | 0 | 0 / 2 | fit, aucun clip |
| `home` (atterrissage) | 1366x768 | 768 | 768 | 768 / 768 | 0 | 0 | **1 / 11 (voir § 6)** | aucun clip ; 1 hit-test central couvert — qualifié |
| `spotlab` (main vide) | 1366x768 | 768 | 768 | 768 / 768 | 0 | 0 | 0 / 17 | fit, aucun clip |
| `review` (Pilotage) | 1366x768 | 768 | 768 | 768 / 768 | 0 | 0 | 0 / 6 | fit, aucun clip |
| `review` (Import) | 1366x768 | 768 | 768 | 768 / 768 | 0 | 0 | 0 / 13 | fit, aucun clip |
| `replayer` | 1366x768 | 768 | 768 | 768 / 768 | 0 | 46 | 0 / 19 | fit, aucun clip |
| `review` (Inbox, retour Replayer) | 1366x768 | 768 | 768 | 768 / 768 | 0 | 0 | 0 / 11 | fit, aucun clip |
| `training` | 1366x768 | 768 | 768 | 758 / 758 | 0 | 11 | 0 / 18 | fit, aucun clip |
| `strategy` (coque intégrée) | 1366x768 | 768 | 768 | 768 / 768 | 0 | 0 | 0 / 2 | fit, aucun clip |

Notes de lecture :

- `review` apparaît trois fois : panneau **Pilotage** (atterrissage), panneau
  **Import** après le clic sur `#reviewImportTab` (T1, `details` fermé), puis
  coque après le retour `Replayer → Review` (**Inbox**) ;
- `training` a une coque de `990/990` (1500x1000) et `758/758` (1366x768) : la
  coque est **plus courte** que le document (`1000`, `768`) et ne déborde pas ;
- `replayer` (46 zones autorisées à 1366x768, 1 à 1500x1000) et `training` (11 et
  7) contiennent des éléments hors de la boîte **visibles uniquement dans une
  zone autorisée** `app-canvas-pane` / `app-scroll-zone` : ils sont atteignables
  par défilement **dans cette zone** et ne sont donc comptés ni comme clippés ni
  comme inatteignables ;
- la seule anomalie de hit-test mesurée est celle de `home` à 1366x768 ; elle est
  nommée et qualifiée au § 6.

### 5.1 Détail des cibles d'import T2 (valeurs mesurées)

| Viewport | État | Cible | `reachable` | `hit` | `inShell` | boîte top/bottom, left/right |
| --- | --- | --- | --- | --- | --- | --- |
| 1500x1000 | fermé | `#reviewImportTab` | true | true | true | 87/117, 251/323 |
| 1500x1000 | fermé | `label[for="hhFileInput"]` | true | true | true | 237/275, 177/364 |
| 1500x1000 | fermé | `.hh-import-advanced > summary` | true | true | true | 400/427, 178/1322 |
| 1500x1000 | fermé | `#hhWatchBtn` | true | true | true | 240/278, 372/526 |
| 1500x1000 | ouvert | `.hh-import-advanced > summary` | true | true | true | 400/428, 178/1322 |
| 1500x1000 | ouvert | `#hhBenchmarkExportBtn` | true | true | true | 459/497, 991/1243 |
| 1366x768 | fermé | `#reviewImportTab` | true | true | true | 87/117, 184/256 |
| 1366x768 | fermé | `label[for="hhFileInput"]` | true | true | true | 237/275, 110/297 |
| 1366x768 | fermé | `.hh-import-advanced > summary` | true | true | true | 400/427, 111/1255 |
| 1366x768 | fermé | `#hhWatchBtn` | true | true | true | 240/278, 305/459 |
| 1366x768 | ouvert | `.hh-import-advanced > summary` | true | true | true | 400/428, 111/1255 |
| 1366x768 | ouvert | `#hhBenchmarkExportBtn` | true | true | true | 459/497, 924/1176 |

La fixture repro a ensuite été importée par le vrai `#hhFileInput` aux deux
viewports (`imported=['3210001']`), puis la main a été ouverte depuis l'inbox
Review (`#hhHands .review-inbox-open`) et le `replayer` mesuré — ce qui couvre le
parcours T2 « avant import » *et* le parcours d'import qui suit.

## 6. Réserve mesurée n° 1 : `home` à 1366x768 — un contrôle flottant couvre le centre d'un raccourci

À **1366x768** uniquement, le hit-test central du smoke signale **1 contrôle non
atteignable sur 11** sur `home` : le raccourci Accueil **« Review »**
(`a.filelabel[href="#historiesSection"]`, boîte `top=337 bottom=375 left=97
right=173`) a son **centre** `(135, 356)` pris par le bouton flottant
`#quickNavToggle` (« Replier la navigation », boîte `top=355 bottom=413 left=113
right=141`), donc `elementFromPoint` renvoie `button#quickNavToggle` et
`hit=false`. Le relevé a été confirmé **après stabilisation** (attente de fin des
animations, puis re-mesure à `+100 ms`, `+400 ms`, `+1,4 s` et `+4,4 s` après le
montage) : ces quatre relevés donnent exactement les mêmes boîtes
(`337/375, 97/173` et `355/413, 113/141`) et le même `hit=false` sur le
centre — donc ce n'est pas un artefact d'animation. Seul le tout premier relevé,
**avant** que la mise en page ne se stabilise (`+0 ms`, raccourci à
`283/321`), donnait `hit=true` : c'est précisément le relevé non stabilisé qui
explique la cellule `0/11` observée une fois avec l'ancien harnais (§ 2.3).

Qualification (mesurée, pas supposée) :

- l'élément **n'est pas clippé** : sa boîte est entièrement dans le rectangle de
  clip de la coque (colonne « clippés » = 0) ;
- il reste **atteignable ailleurs dans sa boîte** : le hit-test au point
  `(135, 340)` (haut-centre) renvoie bien le raccourci Review lui-même ;
- c'est donc un **artefact de la règle « au centre »** (la règle du smoke, ici
  appliquée par le harnais) sur un recouvrement réel de deux contrôles, pas un
  « contenu inatteignable » ni un débordement de coque.

Ce point est **la seule raison** pour laquelle une mesure de contrôles
inatteignables est non nulle dans ce document ; il est conservé et qualifié
plutôt que retiré. En revanche, la ligne `home` du § 5 ne porte **aucune**
affirmation « aucun débordement » basée sur ce hit-test : elle porte sur
`scrollHeight = clientHeight = 768` et sur `clippés = 0`.

## 7. Verdict par mode

| Mode | Verdict local mesuré (harnais hors contrat, HEAD `d1a84d1`) | Base de mesure |
| --- | --- | --- |
| `home` | fit ; aucun élément clippé | `scrollHeight = clientHeight` aux 2 viewports, `clippés = 0` ; à 1366x768, 1 hit-test central couvert par un bouton flottant — **qualifié au § 6** |
| `spotlab` | fit ; aucun élément clippé | `scrollHeight = clientHeight`, `clippés = 0`, `0/17` contrôle inatteignable |
| `review` | fit ; aucun élément clippé ; surface d'import atteignable | `scrollHeight = clientHeight`, `clippés = 0`, T2 `4/4` et `5/5` `reachable` aux 2 viewports |
| `replayer` | fit ; aucun élément clippé | `scrollHeight = clientHeight`, `clippés = 0` ; 46 et 1 éléments en zone autorisée |
| `training` | fit ; aucun élément clippé | document `1000/1000` et `768/768`, coque `990/990` et `758/758`, `clippés = 0` |
| `strategy` | fit ; aucun élément clippé | `scrollHeight = clientHeight`, `clippés = 0`, `0/2` contrôle inatteignable |

Aucun de ces verdicts n'est un `PASS` du smoke gelé : ils portent sur les mesures
du harnais dégradé (§ 2) et restent bornés par ses limites déclarées (§ 2.2).
Une conclusion « aucun débordement / aucun contenu inatteignable » n'est écrite
**que** là où une mesure la couvre (colonnes `scrollHeight` / `clientHeight`,
compteur de clipping, hit-tests T2) ; partout ailleurs elle est absente ou
qualifiée.

## 8. Réserve n° 2 : `./hero-ranges.html` est naviguée mais **hors contrat de coque**

Le parcours navigue réellement depuis l'Accueil vers l'éditeur autonome
`./hero-ranges.html` (clic sur `a.mode-card[data-app-view="strategy"]`, puis
attente du montage de `[data-app-mode="strategy"]`), aux deux viewports. Cette
page est **hors contrat de coque** : c'est un document autonome, pas la coque
desktop fixe. Elle est donc **naviguée mais jamais assertée no-scroll** : aucune
assertion `scrollHeight <= clientHeight` ne la concerne, elle n'apparaît dans
aucune ligne du tableau du § 5, et elle ne porte aucun verdict de fit. Le harnais
confirme seulement qu'elle monte (`hero-ranges.html navigated (hors contrat de
coque)`).

## 9. Statut du smoke gelé et autorité CI

- `python3 tests/trainer/smoke_modes_desktop.py` : **exécutée localement, échec**
  (`EXIT=1`, `ModuleNotFoundError: No module named 'playwright'`), puis **échec
  indépendant** avec Playwright importable (`EXIT=1`, `PermissionError [Errno 1]`
  à la création du socket du serveur éphémère) — § 1 ;
- `python3 tests/trainer/smoke_trainer.py` (donc `run_driver_smokes()` →
  `smoke_modes_desktop.py`) : **exécutée localement, échec à l'import**
  (`EXIT=1`) ; l'orchestrateur n'a donc pas été atteint ;
- **le job gelé `browser-smoke` de `.github/workflows/trainer-smoke.yml` reste
  l'autorité** pour le smoke lui-même : il dispose du réseau, de
  `repro-browser` et d'un Chromium chargeable, et il sert `site/` par
  `python3 -m http.server 8765 --directory site` avant
  `run: python3 tests/trainer/smoke_trainer.py` ;
- l'échec du run **36064742571** sur le HEAD `cdbad28` (clic sur
  `.hh-import-advanced > summary` refusé comme non visible) est **rapporté par le
  contexte autoritaire de la task** ; il n'a **pas** été rejoué ni réobservé ici
  (réseau coupé, § 1) ;
- **aucun merge, aucun push et aucun état vert de CI n'est affirmé** dans ce
  document. La seule chose affirmée sur la CI est qu'elle n'a pas été observée.

## 10. Périmètre, contrats statiques et boucle de tests

- **périmètre** : ce document est le **seul** delta versionné de la task
  (`git status --porcelain` → ` M docs/desktop-modes-fit-evidence.md`). Aucun
  fichier `.github/workflows/**` ni `.github/actions/**` n'est modifié ; aucun
  code science / équité / modèles / ranges n'est touché ; `site/index.html`,
  `site/trainer.js` et `site/RELEASE.json` ne sont pas modifiés :
  `python3 tools/write_site_release.py --check` →
  `release source anchor verified: site/RELEASE.json; assembled identity can be
  materialized`, `EXIT=0` ; `node --check site/trainer.js` → `EXIT=0`.
- `python3 tests/trainer/test_smoke_orchestration_contract.py` → `smoke
  orchestration contract checks: OK`, `EXIT=0`. Cette garde vérifie notamment
  que ce document cite les **deux** commandes du smoke
  (`python3 tests/trainer/smoke_modes_desktop.py` et
  `python3 tests/trainer/smoke_trainer.py`), `git rev-parse HEAD`, `1500x1000` et
  `1366x768`, `scrollHeight` et `clientHeight`, les **six** modes
  (`home`, `spotlab`, `review`, `replayer`, `training`, `strategy`), un
  **verdict**, et que `./hero-ranges.html` est **hors contrat** de coque ;
- boucle complète `for test in tests/trainer/test_*.py; do python3 "$test"; done`
  → **48 fichiers, 0 échec**.

## 11. Reproductibilité de ce document

- Date des mesures : **2026-09-25** (Europe/Paris), avant écriture du fichier ;
- `git rev-parse HEAD` au moment des mesures :
  **`d1a84d1b003d5bd256ab201fa512134ff8aa1a2d`** (branche
  `n8n/issue-394/task-backlog-3nx`) ;
- le présent document ne peut pas citer le SHA de son propre commit
  (auto-référence) : le worker **ne commit pas**, l'orchestrateur gère le commit
  et la PR ; aucun merge et aucun push ne sont affirmés ;
- le harnais local (`/tmp/nx3/measure.py`, `/tmp/nx3/calib.py`,
  `/tmp/nx3/settle_probe.py`) et ses sorties (`/tmp/nx3/final5.json`,
  `final6.json`, `final7.json`) sont **hors dépôt et non versionnés** : ils ne
  sont pas une dépendance du contrat, seulement la trace de la méthode réellement
  utilisée, dont les limites sont déclarées au § 2.2 ;
- ce qui est reproductible sans ce harnais : les sorties et codes retour du § 1
  (deux commandes + `git rev-parse HEAD`), la garde de contrat et la boucle de
  tests du § 10.

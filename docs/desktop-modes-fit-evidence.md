---
schema: poker-issue-394-desktop-modes-fit-evidence/v4
issue: 394
task: task-backlog-z0a
report_date: 2026-09-25
head_sha: 43fa73bd17a50cbbab13f6b66d337f399dbaa02c
branch: n8n/issue-394/task-backlog-z0a
status: FROZEN_SMOKE_NOT_RUNNABLE_LOCALLY__FIT_REMEASURED_AT_FINAL_HEAD_VIA_DECLARED_DEGRADED_REPLAY
merged: false
pushed: false
smoke_modes_desktop_local: FAILED_EXIT_1_LOOPBACK_SOCKET_DENIED_BY_SANDBOX
smoke_trainer_local: FAILED_EXIT_1_PLAYWRIGHT_IMPORT_THEN_BROWSER_LAUNCH_THEN_NO_SERVER
browser_measurement: MEASURED_IN_REAL_CHROMIUM_1187_BY_DECLARED_DEGRADED_REPLAY
clipping_detection: CLIP_RECT_INTERSECTION_PLUS_CENTRE_ELEMENTFROMPOINT
clipping_detection_calibrated_on_synthetic_clip: true
import_surface_reachability: MEASURED_4OF4_CLOSED_AND_5OF5_OPEN_REACHABLE_AT_BOTH_VIEWPORTS
persistence_ready_race: MEASURED_GREEN_AT_BOTH_VIEWPORTS
ci_green: NOT_OBSERVED
site_index_html_modified_in_this_task: false
---

# Preuve navigateur — fit des modes desktop (1500x1000 et 1366x768) (#394, task-backlog-z0a)

Réécriture de `docs/desktop-modes-fit-evidence.md` demandée par `task-backlog-z0a`,
**réécrite et re-mesurée au HEAD réel du worktree `43fa73b`**, le 2026-09-25
(Europe/Paris).

Ce que ce document remplace, et pourquoi. La version précédente du fichier
(`task-backlog-3nx`, publiée à un HEAD interne `d1a84d1` depuis superseded) et la
version antérieure à celle-ci (`task-backlog-a7w`, HEAD interne `e8c2a71` depuis
superseded) portaient un verdict de fit obtenu par un harnais hors contrat dont la
métrique d'« évasion » — *un élément sort-il de la boîte de la coque ?* — **ne
peut pas voir un descendant clippé par un `overflow:hidden` interne** : un enfant
tronqué reste à l'intérieur de la boîte de la coque, la métrique rapportait donc
`0` sur exactement la forme de défaut que le job gelé `browser-smoke` a signalée
sur le HEAD `cdbad28` (clic refusé sur `.hh-import-advanced > summary`). Une telle
conclusion n'est **pas** reconduite ici sans mesure : elle est remplacée par une
mesure **sensible au clipping**, calibrée, et bornée par les limites déclarées au
§ 3.2.

Ce que ce document affirme, et ce qu'il n'affirme pas :

1. le **smoke gelé n'est pas exécutable dans ce sandbox** ; les deux commandes
   exigées ont été lancées et leurs sorties + codes retour exacts sont consignés
   au § 1. **Aucune ligne `PASS` n'est écrite pour elles, ni pour le smoke gelé** ;
2. le fit a été **mesuré pour de vrai** à `43fa73b`, dans un Chromium réel épinglé,
   par un **harnais dégradé explicitement déclaré hors contrat** (§ 3) qui
   **réutilise le code de mesure du smoke lui-même** (`MEASURE_JS`,
   `IMPORT_HIT_TEST_JS`, `RACE_PROBE_JS`, `REVIEW_SELECTED_SUBTABS_JS`,
   `importable_fixture_bytes`, le barrage `state.persistenceReady`) ;
3. la métrique d'atteignabilité est **sensible au clipping** (intersection des
   rectangles de clip de tous les ancêtres clippants + `document.elementFromPoint`
   au centre, la règle exacte du smoke) et cette sensibilité est **calibrée sur un
   clip synthétique** (§ 4) ;
4. le **job gelé `browser-smoke` de la PR reste l'autorité** pour le smoke
   lui-même (§ 11). **Aucun merge, aucun push et aucun état vert de CI n'est
   affirmé** : la CI n'a pas été observée depuis ce worktree.

Toute affirmation du type « aucun débordement / aucun contenu inatteignable »
n'apparaît ci-dessous **que** là où une mesure la couvre, ou elle est
explicitement qualifiée (réserves nommées aux § 8 et § 9).

## 1. Commandes exactes exécutées, sorties exactes et codes retour

Toutes les commandes de cette section ont été lancées **depuis la racine du
worktree**
`/home/abel/.cache/poker-engine-orchestrator/worktrees/issue-394/tasks/task-backlog-z0a`,
le **2026-09-25** (Europe/Paris), **avant** l'écriture de ce fichier.
Interpréteur : `python3 -V` → `Python 3.14.4`.

```
$ git rev-parse HEAD
43fa73bd17a50cbbab13f6b66d337f399dbaa02c
EXIT=0
```

### 1.1 `smoke_modes_desktop.py` — lancé, échec, `EXIT=1`

```
$ PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/tmp/pylibs python3 tests/trainer/smoke_modes_desktop.py
Traceback (most recent call last):
  File "/home/abel/.cache/poker-engine-orchestrator/worktrees/issue-394/tasks/task-backlog-z0a/tests/trainer/smoke_modes_desktop.py", line 892, in <module>
    main()
  File "/home/abel/.cache/poker-engine-orchestrator/worktrees/issue-394/tasks/task-backlog-z0a/tests/trainer/smoke_modes_desktop.py", line 888, in main
    asyncio.run(run())
  File "/usr/lib/python3.14/asyncio/runners.py", line 204, in run
    return runner.run(main)
  File "/usr/lib/python3.14/asyncio/runners.py", line 127, in run
    return self._loop.run_until_complete(task)
  File "/usr/lib/python3.14/asyncio/base_events.py", line 719, in run_until_complete
    return future.result()
  File "/home/abel/.cache/poker-engine-orchestrator/worktrees/issue-394/tasks/task-backlog-z0a/tests/trainer/smoke_modes_desktop.py", line 812, in run
    httpd, url = _serve_site()
  File "/home/abel/.cache/poker-engine-orchestrator/worktrees/issue-394/tasks/task-backlog-z0a/tests/trainer/smoke_modes_desktop.py", line 341, in _serve_site
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
  File "/usr/lib/python3.14/socketserver.py", line 453, in __init__
    self.socket = socket.socket(self.address_family,
  File "/usr/lib/python3.14/socket.py", line 236, in __init__
    _socket.socket.__init__(self, family, type, proto, fileno)
PermissionError: [Errno 1] Operation not permitted
EXIT=1
```

Cause isolée sur une ligne — **la création même d'un socket loopback est refusée**
par le sandbox, alors qu'un socket Unix passe. Sondes exactes et sortie verbatim
au § 1.3.

`_serve_site()` ne peut donc pas ouvrir son serveur éphémère : le smoke s'arrête
**avant** de lancer Chromium, et **avant** toute mesure. `EXIT=1` constaté, pas de
`PASS`.

### 1.2 `smoke_trainer.py` — lancé, échec, `EXIT=1`

Exactement la commande de la task, sans variable d'environnement :

```
$ python3 tests/trainer/smoke_trainer.py
Traceback (most recent call last):
  File "/home/abel/.cache/poker-engine-orchestrator/worktrees/issue-394/tasks/task-backlog-z0a/tests/trainer/smoke_trainer.py", line 10, in <module>
    from playwright.async_api import async_playwright
ModuleNotFoundError: No module named 'playwright'
EXIT=1
```

Le runtime Playwright épinglé existe localement (`/tmp/pylibs`, Playwright 1.55.0),
donc la commande a été relancée avec le même préfixe que le § 1.1 ; elle échoue
alors **un cran plus loin**, au lancement du navigateur. Les lignes ci-dessous
sont recopiées telles quelles, `...` marquant les élisions (trames intermédiaires,
longue sortie `Browser logs:` de Playwright, préfixe absolu des chemins) :

```
$ PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/tmp/pylibs python3 tests/trainer/smoke_trainer.py
trainer smoke failed: BrowserType.launch: Target page, context or browser has been closed
...
  File ".../tests/trainer/smoke_trainer.py", line 62, in main
    browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
...
  - [pid=16][err] /home/abel/.cache/ms-playwright/chromium_headless_shell-1187/chrome-linux/headless_shell:
    error while loading shared libraries: libnspr4.so: cannot open shared object file: No such file or directory
EXIT=1
```

En fournissant les bibliothèques du navigateur (hors dépôt) pour franchir cette
marche, l'échec se déplace encore, à la création de la page : les drapeaux de
lancement du smoke (`--no-sandbox --disable-dev-shm-usage`) ne permettent pas de
démarrer un processus de rendu dans ce noyau. Et même si une page était créée,
l'adresse `http://127.0.0.1:8765/index.html` — que le job CI sert par
`python3 -m http.server 8765 --directory site` — n'est servie par personne ici
(socket loopback refusé, § 1.1) :

```
$ PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/tmp/pylibs LD_PRELOAD=/tmp/fitpilot/fitshim.so \
  LD_LIBRARY_PATH=/tmp/opencode/browserlibs/sysroot/usr/lib/x86_64-linux-gnu \
  python3 tests/trainer/smoke_trainer.py
trainer smoke failed: Browser.new_page: Target page, context or browser has been closed
...
  File ".../tests/trainer/smoke_trainer.py", line 63, in main
    page = await browser.new_page(viewport={"width": 1500, "height": 1000})
playwright._impl._errors.TargetClosedError: Browser.new_page: Target page, context or browser has been closed
EXIT=1
```

`smoke_trainer.py` échoue donc dans `main()` (ligne 62/63) **avant
`run_driver_smokes()`** (ligne 1562) : l'orchestrateur n'est jamais atteint, et
`smoke_modes_desktop.py` n'est jamais déclenché depuis lui localement. **Aucun
`PASS` n'est écrit pour ces commandes.**

### 1.3 Second blocage, indépendant du premier : aucune saisie fiable

Le sandbox refuse aussi la **livraison d'événements synthétiques**. Chromium
démarre pourtant bien ici, avec les drapeaux que ce noyau exige (voir § 3.1) :

```
$ PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/tmp/pylibs LD_PRELOAD=/tmp/fitpilot/fitshim.so \
  LD_LIBRARY_PATH=/tmp/opencode/browserlibs/sysroot/usr/lib/x86_64-linux-gnu \
  python3 -u /tmp/z0a/limits.py "$PWD"
socket(AF_INET/SOCK_STREAM): PermissionError: [Errno 1] Operation not permitted
socket(AF_INET6/SOCK_STREAM): PermissionError: [Errno 1] Operation not permitted
socket(AF_UNIX/SOCK_STREAM): OK
playwright page.click('#b'): TimeoutError: Page.click: Timeout 8000ms exceeded.
   - attempting click action
   - waiting for element to be visible, enabled and stable
   - element is visible, enabled and stable
   - scrolling into view if needed
   - done scrolling
   - performing click action          <-- n'aboutit jamais, jusqu'au timeout
EXIT=0
```

La même limite est atteinte **en contournant Playwright**, directement par le
protocole de débogage, et pour la souris comme pour le clavier. Aucun de ces
événements n'atteint la page (`hits: []`) :

```
$ PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/tmp/pylibs LD_PRELOAD=/tmp/fitpilot/fitshim.so \
  LD_LIBRARY_PATH=/tmp/opencode/browserlibs/sysroot/usr/lib/x86_64-linux-gnu \
  python3 -u /tmp/z0a/cdp_probe.py
CDP input dispatch FAIL TimeoutError
hits: []
file chooser OK: JSHandle@<input id="f" type="file">
EXIT=0

$ PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/tmp/pylibs LD_PRELOAD=/tmp/fitpilot/fitshim.so \
  LD_LIBRARY_PATH=/tmp/opencode/browserlibs/sysroot/usr/lib/x86_64-linux-gnu \
  python3 -u /tmp/z0a/key_probe.py
playwright keyboard FAIL TimeoutError
CDP keyboard FAIL TimeoutError
EXIT=0
```

Note : la troisième ligne montre qu'une évaluation CDP avec `userGesture: true`
peut, elle, ouvrir un sélecteur de fichier — c'est ce qui rend
`set_input_files(...)` sur le vrai `#hhFileInput` praticable pour le harnais,
alors que le clic Playwright et le `click(trial=True)` du smoke, qui passent par
la livraison d'événements, ne le sont pas.

C'est la raison pour laquelle les étapes du smoke qui exigent un **clic réel**
(`page.click`, `page.mouse.click`, `locator.click(trial=True)`) et le **parcours
clavier du Replayer** (`Tab` / `ArrowRight` / `ArrowLeft` / `Enter`) ne sont pas
rejouables ici ; elles restent couvertes par le job gelé (§ 11) et sont déclarées
comme limites au § 3.2.

Réseau : le sandbox est également coupé (`CODEX_SANDBOX_NETWORK_DISABLED=1`),
donc le run CI du job gelé n'a **pas** pu être reconsulté ni rejoué depuis ce
worktree. Il est cité en § 11 comme contexte autoritaire, pas comme observation.

## 2. Ce qui marche malgré tout : le navigateur épinglé

Chromium réel épinglé démarre et rend la page :

```
$ PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/tmp/pylibs LD_PRELOAD=/tmp/fitpilot/fitshim.so \
  LD_LIBRARY_PATH=/tmp/opencode/browserlibs/sysroot/usr/lib/x86_64-linux-gnu \
  python3 -u /tmp/z0a/browser_alive.py
chromium executable: /home/abel/.cache/ms-playwright/chromium-1187/chrome-linux/chrome
text: hi
EXIT=0
```

Runtime : Playwright 1.55.0 (version épinglée par `requirements.lock.txt`) ; le
harnais lance explicitement
`~/.cache/ms-playwright/chromium_headless_shell-1187/chrome-linux/headless_shell`
(la ligne `chromium executable` ci-dessus est le chemin par défaut rapporté par
Playwright, pas le binaire utilisé par le harnais), avec les drapeaux et le
transport décrits au § 3.1.

## 3. Méthode réellement utilisée : rejeu dégradé, déclaré hors contrat

### 3.1 Ce qui a été fait

Faute de pouvoir exécuter le smoke (§ 1), les parcours ont été **rejoués** par un
harnais local **hors contrat** (`/tmp/z0a/harness.py`, **non versionné**) qui
**importe le module du smoke** et réutilise son code de mesure tel quel :

| Élément | Source |
| --- | --- |
| `scrollHeight` / `clientHeight` document + mode monté + coque visible | `smoke_modes_desktop.MEASURE_JS` (métrique et assertions de `_measure`) |
| atteignabilité de la surface d'import Review (T2) | `smoke_modes_desktop.IMPORT_HIT_TEST_JS` + `IMPORT_SURFACE_SELECTORS` + `IMPORT_ADVANCED_SELECTOR` |
| atterrissage Review | `smoke_modes_desktop.REVIEW_SELECTED_SUBTABS_JS` |
| scénario de course | `smoke_modes_desktop.RACE_PROBE_JS` + barrage `state.persistenceReady===true` (`READINESS_TIMEOUT_MS`) |
| import de la main repro | `smoke_modes_desktop.importable_fixture_bytes()` via le **vrai** `#hhFileInput` (`set_input_files`) |

Déviations imposées par le sandbox, toutes déclarées :

1. **transport** : `site/` est servi par **interception de requêtes Playwright**
   (`context.route("**/*", …)`, origine locale factice) parce que toute création
   de socket loopback est refusée (§ 1.1) ;
2. **drapeaux de lancement** : `--no-sandbox --disable-dev-shm-usage
   --disable-crash-reporter --disable-gpu --disable-software-rasterizer
   --disable-features=Vulkan,SkiaGraphite,VizDisplayCompositor --single-process
   --no-zygote --disable-frame-rate-limit --disable-gpu-vsync` (les drapeaux du
   smoke ne suffisent pas ici, § 1.2) ; bibliothèques du navigateur fournies par
   `LD_LIBRARY_PATH`, deux appels `shutdown`/`setsockopt` neutralisés par un
   `LD_PRELOAD` (`/tmp/fitpilot/fitshim.so`) — ce shim ne touche pas aux mesures ;
3. **actions** : chaque navigation passe par `element.click()` en JavaScript
   (donc par les gestionnaires réels de l'application) au lieu d'un clic souris
   Playwright, faute de saisie fiable (§ 1.3) ;
4. **mesures stabilisées** : l'audit attend la fin des animations CSS
   (`document.getAnimations()` sans `running`) puis 400 ms avant de mesurer.

Commande du harnais et sortie exacte (sortie complète : `/tmp/z0a/harness_run9.log`,
JSON : `/tmp/z0a/out9.json`, hors dépôt et non versionnés) :

```
$ PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/tmp/pylibs LD_PRELOAD=/tmp/fitpilot/fitshim.so \
  LD_LIBRARY_PATH=/tmp/opencode/browserlibs/sysroot/usr/lib/x86_64-linux-gnu \
  python3 -u /tmp/z0a/harness.py "$PWD" /tmp/z0a/out9.json
== viewport 1500x1000 ==
  mode=home      viewport=1500x1000  scrollHeight=1000 <= clientHeight=1000 shell=1000/1000 clipped=0 allowedZones=0 unreachable_controls=0/11
  mode=spotlab   viewport=1500x1000  scrollHeight=1000 <= clientHeight=1000 shell=1000/1000 clipped=0 allowedZones=0 unreachable_controls=0/17
[1500x1000] Review landing selected_subtabs=['pilotage']
  mode=review    viewport=1500x1000  scrollHeight=1000 <= clientHeight=1000 shell=1000/1000 clipped=0 allowedZones=0 unreachable_controls=0/5
  mode=review    viewport=1500x1000  scrollHeight=1000 <= clientHeight=1000 shell=1000/1000 clipped=0 allowedZones=0 unreachable_controls=0/6
[1500x1000] import surface[import-closed] reachability: #reviewImportTab=ok, label[for="hhFileInput"]=ok, .hh-import-advanced > summary=ok, #hhWatchBtn=ok
[1500x1000] import surface[import-advanced-open] reachability: #reviewImportTab=ok, label[for="hhFileInput"]=ok, .hh-import-advanced > summary=ok, #hhWatchBtn=ok, #hhBenchmarkExportBtn=ok
  mode=review    viewport=1500x1000  scrollHeight=1000 <= clientHeight=1000 shell=1000/1000 clipped=0 allowedZones=0 unreachable_controls=0/13
  mode=review    viewport=1500x1000  scrollHeight=1000 <= clientHeight=1000 shell=1000/1000 clipped=0 allowedZones=0 unreachable_controls=0/6
[1500x1000] imported=['3210001']
  mode=replayer  viewport=1500x1000  scrollHeight=1000 <= clientHeight=1000 shell=1000/1000 clipped=0 allowedZones=1 unreachable_controls=0/19
  mode=review    viewport=1500x1000  scrollHeight=1000 <= clientHeight=1000 shell=1000/1000 clipped=0 allowedZones=0 unreachable_controls=0/11
  mode=training  viewport=1500x1000  scrollHeight=1000 <= clientHeight=1000 shell=990/990 clipped=0 allowedZones=7 unreachable_controls=0/18
  mode=strategy  viewport=1500x1000  scrollHeight=1000 <= clientHeight=1000 shell=1000/1000 clipped=0 allowedZones=0 unreachable_controls=0/2
[1500x1000] hero-ranges.html navigated (hors contrat de coque)
  mode=review    viewport=1500x1000  course Review: persistenceReady=True mounted=review userNavigated=True #reviewDashboard=True #historiesSection masque=True
== viewport 1366x768 ==
  mode=home      viewport=1366x768   scrollHeight=768 <= clientHeight=768 shell=768/768 clipped=0 allowedZones=0 unreachable_controls=1/11
      UNREACHABLE: {"sel": "a.filelabel", "hit": false, "at": "button#quickNavToggle.quick-nav-toggle", "inViewport": true, "inShell": true, "allowedZone": false, "box": {"top": 337, "bottom": 375, "left": 97, "right": 173}, "point": {"x": 135, "y": 356}}
  mode=spotlab   viewport=1366x768   scrollHeight=768 <= clientHeight=768 shell=768/768 clipped=0 allowedZones=0 unreachable_controls=0/17
[1366x768] Review landing selected_subtabs=['pilotage']
  mode=review    viewport=1366x768   scrollHeight=768 <= clientHeight=768 shell=768/768 clipped=0 allowedZones=0 unreachable_controls=0/5
  mode=review    viewport=1366x768   scrollHeight=768 <= clientHeight=768 shell=768/768 clipped=0 allowedZones=0 unreachable_controls=0/6
[1366x768] import surface[import-closed] reachability: #reviewImportTab=ok, label[for="hhFileInput"]=ok, .hh-import-advanced > summary=ok, #hhWatchBtn=ok
[1366x768] import surface[import-advanced-open] reachability: #reviewImportTab=ok, label[for="hhFileInput"]=ok, .hh-import-advanced > summary=ok, #hhWatchBtn=ok, #hhBenchmarkExportBtn=ok
  mode=review    viewport=1366x768   scrollHeight=768 <= clientHeight=768 shell=768/768 clipped=0 allowedZones=0 unreachable_controls=0/13
  mode=review    viewport=1366x768   scrollHeight=768 <= clientHeight=768 shell=768/768 clipped=0 allowedZones=0 unreachable_controls=0/6
[1366x768] imported=['3210001']
  mode=replayer  viewport=1366x768   scrollHeight=768 <= clientHeight=768 shell=768/768 clipped=0 allowedZones=43 unreachable_controls=0/19
  mode=review    viewport=1366x768   scrollHeight=768 <= clientHeight=768 shell=768/768 clipped=0 allowedZones=0 unreachable_controls=0/11
  mode=training  viewport=1366x768   scrollHeight=768 <= clientHeight=768 shell=758/758 clipped=0 allowedZones=11 unreachable_controls=0/18
  mode=strategy  viewport=1366x768   scrollHeight=768 <= clientHeight=768 shell=768/768 clipped=0 allowedZones=0 unreachable_controls=0/2
[1366x768] hero-ranges.html navigated (hors contrat de coque)
  mode=review    viewport=1366x768   course Review: persistenceReady=True mounted=review userNavigated=True #reviewDashboard=True #historiesSection masque=True
wrote /tmp/z0a/out9.json
EXIT=0
```

Ce rejeu a été exécuté **neuf fois** au total : `out2.json` … `out5.json` avec le
parcours décrit ci-dessus privé de l'étape deep link (9 mesures de mode par
viewport), puis `out6.json` … `out9.json` avec le parcours complet (10 mesures de
mode par viewport). Sur les **quatre** exécutions complètes (6 à 9), les vingt
lignes de mesure et les **deux** lignes de course sont identiques, à **une
cellule près**, nommée ici plutôt que lissée : `training` à 1366x768 rend
`allowedZones=11` (runs 6, 7 et 9) puis `12` (run 8), le nombre d'éléments d'une
zone de défilement autorisée variant avec la fin du rendu du panneau. Sur les
neuf exécutions, cette même cellule de `training` à 1366x768 vaut `11` sept fois
et `12` deux fois, et le **nombre total de contrôles** de `training` à 1500x1000
vaut `18` huit fois et `17` une fois (run 2). Aucune de ces cellules ne change un
compteur de clipping, un compteur de contrôles inatteignables, ni un verdict.

### 3.2 Limites déclarées de cette méthode (ce qu'elle ne prouve pas)

1. **Ce n'est pas le smoke.** `tests/trainer/smoke_modes_desktop.py` et
   `tests/trainer/smoke_trainer.py` restent **non exécutés avec succès** ici
   (§ 1) ; les parcours sont *rejoués*, pas *le smoke* ;
2. **aucune saisie fiable** n'existe dans ce sandbox (§ 1.3). Ne sont donc pas
   rejouées localement : le clic Playwright `locator.click(trial=True)` de
   l'assertion T2 (hit-test d'action de Playwright), le clic réel de mesure sur
   `#hhWatchBtn`, le `expect_file_chooser` sur `label[for="hhFileInput"]`, le clic
   réel sur `#hhBenchmarkExportBtn`, et le parcours clavier du Replayer
   (`Tab` → `ArrowRight` → `ArrowLeft` → `Enter`). Ces étapes restent couvertes
   par le job gelé ;
3. **le déclenchement par l'orchestrateur** (`run_driver_smokes()` →
   `smoke_modes_desktop.py`) n'a pas eu lieu localement : `smoke_trainer.py`
   échoue avant (§ 1.2) ;
4. **aucun `PASS` du smoke gelé n'est déduit** de ces mesures, et aucune valeur
   ci-dessous n'est un résultat de CI ;
5. la mesure porte sur le `site/` de ce worktree au HEAD `43fa73b`.

## 4. Méthode de mesure : sensible au clipping, et calibrée

Le smoke est explicite : « a mode that overflows fails explicitly with the
measured values, so the audit is never silently satisfied by a clipped shell ».
La métrique retirée (« évasion » hors de la boîte de coque) **ne peut pas** tenir
ce rôle : la coque est bornée et ses panneaux internes sont en `overflow:hidden`,
donc un descendant tronqué reste **dans** la boîte de la coque et la métrique
rapporte `0`.

La mesure utilisée ici vérifie l'**atteignabilité au point**, règle du smoke :

1. **rectangle de clip** : pour chaque élément visible de la coque, on intersecte
   les `client rect` de **tous** ses ancêtres clippants (`overflow` / `overflow-x`
   / `overflow-y` valant `hidden`, `clip`, `auto` ou `scroll`) ; un élément dont la
   boîte sort de ce rectangle est **clippé**. Le contenu d'un `<details>` fermé est
   exclu (état replié du widget, pas défaut de clipping) ;
2. **hit-test du centre** : pour chaque contrôle interactif
   (`button, a[href], input, select, textarea, summary, label, [role=tab],
   [data-trainer-action], [data-app-subview]`), `document.elementFromPoint` au
   **centre** de la boîte doit retourner l'élément lui-même ou un descendant
   (`at === el || el.contains(at)`). Un ancêtre qui possède simplement la boîte ne
   compte pas — c'est ce qui fait échouer un contrôle clippé ;
3. les éléments d'une zone de `APP_ALLOWED_SCROLL_ZONES` (atteignables par
   défilement **dans une zone bornée autorisée**) sont comptés séparément
   (`allowedZones`) ; ils ne sont ni clippés ni déclarés inatteignables.

### 4.1 Calibration : la nouvelle mesure voit ce que l'ancienne ratait

Même page, même viewport (`1366x768`), même harnais. La seule différence :
`#historiesSection` (le panneau d'import Review) est forcé à
`height:120px; overflow:hidden` — la forme même du défaut historique.

```
$ PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/tmp/pylibs LD_PRELOAD=/tmp/fitpilot/fitshim.so \
  LD_LIBRARY_PATH=/tmp/opencode/browserlibs/sysroot/usr/lib/x86_64-linux-gnu \
  python3 -u /tmp/z0a/calib.py "$PWD"
baseline: new-metric clipped=0 unreachable=0/6 old-evasion=0 scrollHeight=768 clientHeight=768
inject: {'height': 120}
synthetic-clip: new-metric clipped=6 unreachable=2/6 old-evasion=0 scrollHeight=768 clientHeight=768
  smoke-metric mounted=review scrollHeight<=clientHeight: True
  CLIPPED {"sel": "div.hh-import-primary", ... "clip": {"top": 130, "bottom": 250}, "clipBy": "section#historiesSection.panel.wide.app-subview-panel", ...}
  CLIPPED {"sel": "label.filelabel.hh-import-main", "box": {"top": 237, "bottom": 275, "left": 110, "right": 297}, ...}
  CLIPPED {"sel": "button#hhWatchBtn.secondary", "box": {"top": 240, "bottom": 278, "left": 305, "right": 459}, ...}
  CLIPPED {"sel": "div#hhImportEffect.hh-import-effect", ...} {"sel": "div#hhFileMeta.hh-import-summary", ...} {"sel": "div#hhStatus.status", ...}
  UNREACHABLE {"sel": "label.filelabel.hh-import-main", "hit": false, "at": "div.app-view-body", "inViewport": true, "inShell": true, "allowedZone": false, "box": {"top": 237, "bottom": 275, "left": 110, "right": 297}, "point": {"x": 204, "y": 256}}
  UNREACHABLE {"sel": "button#hhWatchBtn.secondary", "hit": false, "at": "div.app-view-body", "inViewport": true, "inShell": true, "allowedZone": false, "box": {"top": 240, "bottom": 278, "left": 305, "right": 459}, "point": {"x": 382, "y": 259}}
  import hit_test reachable: {"#reviewImportTab": true, "label[for=\"hhFileInput\"]": false, ".hh-import-advanced > summary": false, "#hhWatchBtn": false}
restore: {'height': 622}
restored: new-metric clipped=0 unreachable=0/6 old-evasion=0 scrollHeight=768 clientHeight=768
EXIT=0
```

Lecture, en trois faits mesurés :

1. sur l'état volontairement clippé, la métrique **retirée** (« évasion »)
   rapporte `0` : elle ne voit rien, alors que **3 des 4** cibles d'import sont
   devenues non atteignables et que 6 éléments sont clippés ;
2. la métrique **globale du smoke** (`scrollHeight <= clientHeight`) reste
   verte sur cet état (`True`) : un panneau tronqué ne fait pas déborder le
   document. C'est précisément pourquoi l'assertion T2 d'atteignabilité existe,
   et pourquoi ce document ne s'appuie pas sur le seul `scrollHeight` ;
3. la nouvelle mesure **échoue** quand du contenu est clippé (6 clippés / 2
   contrôles inatteignables / 3 cibles d'import en échec) et **passe** quand il ne
   l'est pas (`baseline` et `restored` : `0`/`0`). C'est le changement de méthode
   exigé.

## 5. Table mode × viewport (mesures locales stabilisées, HEAD `43fa73b`)

`scrollHeight` / `clientHeight` sont ceux de `document.scrollingElement` — la
métrique même du smoke. La colonne « coque » donne les mêmes valeurs pour
`[data-view-shell="<mode>"]`. « clippés » / « inatteignables » viennent de l'audit
du § 4 ; « zones autorisées » compte les éléments hors de la boîte visibles
uniquement dans une zone de `APP_ALLOWED_SCROLL_ZONES` (atteignables par
défilement borné, donc ni clippés ni inatteignables).

| Mode (étape du parcours) | Viewport | document `scrollHeight` | document `clientHeight` | coque `scrollHeight`/`clientHeight` | clippés | zones autorisées | contrôles inatteignables | Verdict mesuré |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `home` (atterrissage) | 1500x1000 | 1000 | 1000 | 1000 / 1000 | 0 | 0 | 0 / 11 | fit, aucun clip |
| `spotlab` (main vide) | 1500x1000 | 1000 | 1000 | 1000 / 1000 | 0 | 0 | 0 / 17 | fit, aucun clip |
| `review` (Pilotage, atterrissage) | 1500x1000 | 1000 | 1000 | 1000 / 1000 | 0 | 0 | 0 / 5 | fit, aucun clip |
| `review` (Import) | 1500x1000 | 1000 | 1000 | 1000 / 1000 | 0 | 0 | 0 / 6 | fit, aucun clip |
| `review` (Import, détails ouverts) | 1500x1000 | 1000 | 1000 | 1000 / 1000 | 0 | 0 | 0 / 13 | fit, aucun clip |
| `review` (Import, deep link `#historiesSection`) | 1500x1000 | 1000 | 1000 | 1000 / 1000 | 0 | 0 | 0 / 6 | fit, aucun clip |
| `replayer` | 1500x1000 | 1000 | 1000 | 1000 / 1000 | 0 | 1 | 0 / 19 | fit, aucun clip |
| `review` (Inbox, retour Replayer) | 1500x1000 | 1000 | 1000 | 1000 / 1000 | 0 | 0 | 0 / 11 | fit, aucun clip |
| `training` | 1500x1000 | 1000 | 1000 | 990 / 990 | 0 | 7 | 0 / 18 | fit, aucun clip |
| `strategy` (coque intégrée) | 1500x1000 | 1000 | 1000 | 1000 / 1000 | 0 | 0 | 0 / 2 | fit, aucun clip |
| `home` (atterrissage) | 1366x768 | 768 | 768 | 768 / 768 | 0 | 0 | **1 / 11 (voir § 8)** | aucun clip ; 1 hit-test central couvert — qualifié |
| `spotlab` (main vide) | 1366x768 | 768 | 768 | 768 / 768 | 0 | 0 | 0 / 17 | fit, aucun clip |
| `review` (Pilotage, atterrissage) | 1366x768 | 768 | 768 | 768 / 768 | 0 | 0 | 0 / 5 | fit, aucun clip |
| `review` (Import) | 1366x768 | 768 | 768 | 768 / 768 | 0 | 0 | 0 / 6 | fit, aucun clip |
| `review` (Import, détails ouverts) | 1366x768 | 768 | 768 | 768 / 768 | 0 | 0 | 0 / 13 | fit, aucun clip |
| `review` (Import, deep link `#historiesSection`) | 1366x768 | 768 | 768 | 768 / 768 | 0 | 0 | 0 / 6 | fit, aucun clip |
| `replayer` | 1366x768 | 768 | 768 | 768 / 768 | 0 | 43 | 0 / 19 | fit, aucun clip |
| `review` (Inbox, retour Replayer) | 1366x768 | 768 | 768 | 768 / 768 | 0 | 0 | 0 / 11 | fit, aucun clip |
| `training` | 1366x768 | 768 | 768 | 758 / 758 | 0 | 11 | 0 / 18 | fit, aucun clip |
| `strategy` (coque intégrée) | 1366x768 | 768 | 768 | 768 / 768 | 0 | 0 | 0 / 2 | fit, aucun clip |

Notes de lecture :

- `review` apparaît cinq fois : panneau **Pilotage** (atterrissage), panneau
  **Import** après le clic sur `#reviewImportTab`, même panneau `details` ouvert,
  retour par le **deep link** `#historiesSection`, puis coque après le retour
  `Replayer → Review` (**Inbox**) ;
- l'atterrissage Review est mesuré : `selected_subtabs=['pilotage']` aux deux
  viewports, et l'assertion « un seul panneau monté » passe après chaque
  bascule ;
- `training` a une coque de `990/990` (1500x1000) et `758/758` (1366x768) : la
  coque est **plus courte** que le document (`1000`, `768`) et ne déborde pas ;
- `replayer` (43 zones autorisées à 1366x768, 1 à 1500x1000) et `training` (11 et
  7) contiennent des éléments hors de la boîte visibles uniquement dans une zone
  autorisée `app-canvas-pane` / `app-scroll-zone` ;
- après le deep link, la vérification « aucun défilement caché de coque »
  (`scrollTop <= 1` sur la coque Review, `.app-view-body` et
  `#historiesSection`) passe aux deux viewports ;
- la seule anomalie de hit-test mesurée est celle de `home` à 1366x768 ; elle est
  nommée et qualifiée au § 8. Aucune autre ligne n'a de contrôle inatteignable.

## 6. Assertion T2 — reachability de la surface d'import Review

Mesure à **main vide** (`state.hhHands.length === 0`), avant tout import, aux deux
viewports, `details` fermé puis ouvert, avec la règle du smoke
(`document.elementFromPoint` au centre ; `visible`, `inViewport`, `inShell`, `hit`
puis le verdict composite `reachable`).

| Viewport | État de `details` | Cibles atteignables (`reachable: true`) |
| --- | --- | --- |
| 1500x1000 | fermé | **4/4** (`#reviewImportTab`, `label[for="hhFileInput"]`, `.hh-import-advanced > summary`, `#hhWatchBtn`) |
| 1500x1000 | ouvert (`#hhBenchmarkExportBtn` monté) | **5/5** |
| 1366x768 | fermé | **4/4** |
| 1366x768 | ouvert | **5/5** |

Détail mesuré (boîtes `getBoundingClientRect`, `at` = élément réellement renvoyé
par `elementFromPoint` au centre) :

| Viewport | État | Cible | `reachable` | `hit` | `inShell` | boîte top/bottom, left/right | `at` |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1500x1000 | fermé | `#reviewImportTab` | true | true | true | 87/117, 251/323 | `reviewImportTab` |
| 1500x1000 | fermé | `label[for="hhFileInput"]` | true | true | true | 237/275, 177/364 | `filelabel hh-import-main` |
| 1500x1000 | fermé | `.hh-import-advanced > summary` | true | true | true | 400/427, 178/1322 | `SUMMARY` |
| 1500x1000 | fermé | `#hhWatchBtn` | true | true | true | 240/278, 372/526 | `hhWatchBtn` |
| 1500x1000 | ouvert | `.hh-import-advanced > summary` | true | true | true | 400/428, 178/1322 | `SUMMARY` |
| 1500x1000 | ouvert | `#hhBenchmarkExportBtn` | true | true | true | 459/497, 991/1243 | `hhBenchmarkExportBtn` |
| 1366x768 | fermé | `#reviewImportTab` | true | true | true | 87/117, 184/256 | `reviewImportTab` |
| 1366x768 | fermé | `label[for="hhFileInput"]` | true | true | true | 237/275, 110/297 | `filelabel hh-import-main` |
| 1366x768 | fermé | `.hh-import-advanced > summary` | true | true | true | 400/427, 111/1255 | `SUMMARY` |
| 1366x768 | fermé | `#hhWatchBtn` | true | true | true | 240/278, 305/459 | `hhWatchBtn` |
| 1366x768 | ouvert | `.hh-import-advanced > summary` | true | true | true | 400/428, 111/1255 | `SUMMARY` |
| 1366x768 | ouvert | `#hhBenchmarkExportBtn` | true | true | true | 459/497, 924/1176 | `hhBenchmarkExportBtn` |

Pour les douze cibles mesurées, `present`, `visible`, `inViewport`, `inShell`,
`hit` et `reachable` sont **tous vrais**, et `at` est la cible elle-même. La main
repro a ensuite été importée par le **vrai** `#hhFileInput`
(`imported=['3210001']` aux deux viewports), ouverte depuis l'inbox Review
(`#hhHands .review-inbox-open`), et le Replayer mesuré : le parcours T2 « avant
import » *et* le parcours d'import qui suit sont donc couverts.

**Limite** : la confirmation `locator.click(trial=True)` de cette assertion n'a
pas pu être exécutée localement (saisie indisponible, § 1.3 et § 3.2) ; elle reste
couverte par le smoke gelé.

## 7. Scénario de course `persistenceReady`

Le scénario du smoke (`run_review_race_viewport`) est rejoué dans un contexte
**frais** par viewport : la carte Review est activée pendant que la restauration
locale asynchrone ouvre encore IndexedDB, puis le barrage est franchi
(`state.persistenceReady===true`) et le verdict est relu depuis la page.

| Viewport | `persistenceReady` | `document.body.dataset.appView` | `state.userNavigated` | `#reviewDashboard` visible | `#historiesSection` masqué | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| 1500x1000 | true | review | true | true | true | la vue choisie pendant la course survit à la fin de la restauration |
| 1366x768 | true | review | true | true | true | idem |

Ligne brute du harnais, aux deux viewports :

```
  mode=review    viewport=1500x1000  course Review: persistenceReady=True mounted=review userNavigated=True #reviewDashboard=True #historiesSection masque=True
  mode=review    viewport=1366x768   course Review: persistenceReady=True mounted=review userNavigated=True #reviewDashboard=True #historiesSection masque=True
```

Sur les huit rejeux qui ont produit ces lignes (runs 2 à 9 — le run 1 a perdu son
navigateur avant l'étape de course, voir § 3.1), elles sont **identiques** aux
deux viewports. C'est une mesure du scénario rejoué, pas un `PASS` du smoke gelé
(§ 3.2).

## 8. Réserve mesurée : `home` à 1366x768 — un contrôle flottant couvre le centre d'un raccourci

À **1366x768** uniquement, le hit-test central signale **1 contrôle non
atteignable sur 11** sur `home` : le raccourci Accueil **« Review »**
(`a.filelabel[href="#historiesSection"]`, boîte `top=337 bottom=375 left=97
right=173`) a son **centre** `(135, 356)` pris par le bouton flottant
`#quickNavToggle` (« Replier la navigation », boîte `top=355 bottom=413 left=113
right=141`), donc `elementFromPoint` renvoie `button#quickNavToggle` et
`hit=false`. Le relevé est **stable** : mesuré après stabilisation des animations
(`animationsRunning=0`) puis re-mesuré à `+4 s`, les boîtes et le verdict sont
identiques.

```
$ PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/tmp/pylibs LD_PRELOAD=/tmp/fitpilot/fitshim.so \
  LD_LIBRARY_PATH=/tmp/opencode/browserlibs/sysroot/usr/lib/x86_64-linux-gnu \
  python3 -u /tmp/z0a/home_edge.py "$PWD"
1366x768 settled: {"reviewShortcut": {"top": 337, "bottom": 375, "left": 97, "right": 173}, "quickNavToggle": {"top": 355, "bottom": 413, "left": 113, "right": 141}, "quickNavCollapsed": false, "centre": {"x": 135, "y": 356}, "centreHit": "quickNavToggle", "centreIsShortcut": false, "topCentreHit": "filelabel", "topCentreIsShortcut": true, "animationsRunning": 0}
1366x768 t+4s   : {"reviewShortcut": {"top": 337, "bottom": 375, "left": 97, "right": 173}, "quickNavToggle": {"top": 355, "bottom": 413, "left": 113, "right": 141}, "quickNavCollapsed": false, "centre": {"x": 135, "y": 356}, "centreHit": "quickNavToggle", "centreIsShortcut": false, "topCentreHit": "filelabel", "topCentreIsShortcut": true, "animationsRunning": 0}
1500x1000 settled: {"reviewShortcut": {"top": 337, "bottom": 375, "left": 164, "right": 240}, "quickNavToggle": {"top": 471, "bottom": 529, "left": 113, "right": 141}, ..., "centreHit": "filelabel", "centreIsShortcut": true, "topCentreHit": "filelabel", "topCentreIsShortcut": true, "animationsRunning": 0}
1500x1000 t+4s   : ... idem ci-dessus ...
EXIT=0
```

Qualification (mesurée, pas supposée) :

- l'élément **n'est pas clippé** : sa boîte est entièrement dans le rectangle de
  clip de la coque (colonne « clippés » = 0) et `inShell=true` ;
- il reste **atteignable ailleurs dans sa boîte** : le hit-test au point
  `(135, 340)` (haut-centre) renvoie le raccourci lui-même
  (`topCentreIsShortcut: true`) ;
- à 1500x1000, le bouton flottant est plus bas (`471/529`) et le centre du
  raccourci est bien atteignable (`0/11`) ;
- c'est donc un **artefact de la règle « au centre »** (la règle du smoke, ici
  appliquée par le harnais) sur un recouvrement réel de deux contrôles, pas un
  « contenu inatteignable » ni un débordement de coque. Ce point est **la seule**
  raison pour laquelle un compteur de contrôles inatteignables est non nul dans ce
  document ; il est conservé et qualifié plutôt que retiré.

La ligne `home` du § 5 ne porte **aucune** affirmation « aucun débordement »
fondée sur ce hit-test : elle porte sur `scrollHeight = clientHeight = 768` et sur
`clippés = 0`.

## 9. `./hero-ranges.html` est naviguée mais **hors contrat de coque**

Le parcours navigue réellement depuis l'Accueil vers l'éditeur autonome
`./hero-ranges.html` (activation de `a.mode-card[data-app-view="strategy"]`, puis
attente du montage de `[data-app-mode="strategy"]`), aux deux viewports, et la
ligne brute du harnais le confirme :

```
[1500x1000] hero-ranges.html navigated (hors contrat de coque)
[1366x768] hero-ranges.html navigated (hors contrat de coque)
```

Cette page est **hors contrat de coque** : c'est un document autonome, pas la
coque desktop à hauteur fixe. Elle est donc **naviguée mais jamais assertée
no-scroll** : aucune assertion `scrollHeight <= clientHeight` ne la concerne, elle
n'apparaît dans aucune ligne du tableau du § 5, et elle ne porte aucun verdict de
fit. Le harnais confirme seulement qu'elle monte.

## 10. Verdict par mode

| Mode | Verdict local mesuré (rejeu hors contrat, HEAD `43fa73b`) | Base de mesure |
| --- | --- | --- |
| `home` | fit ; aucun élément clippé | `scrollHeight = clientHeight` aux 2 viewports, `clippés = 0` ; à 1366x768, 1 hit-test central couvert par un bouton flottant — **qualifié au § 8** |
| `spotlab` | fit ; aucun élément clippé | `scrollHeight = clientHeight`, `clippés = 0`, `0/17` contrôle inatteignable |
| `review` | fit ; aucun élément clippé ; surface d'import atteignable | `scrollHeight = clientHeight`, `clippés = 0` (5 étapes), T2 `4/4` puis `5/5` `reachable` aux 2 viewports |
| `replayer` | fit ; aucun élément clippé | `scrollHeight = clientHeight`, `clippés = 0` ; 43 et 1 éléments en zone autorisée |
| `training` | fit ; aucun élément clippé | document `1000/1000` et `768/768`, coque `990/990` et `758/758`, `clippés = 0` |
| `strategy` | fit ; aucun élément clippé | `scrollHeight = clientHeight`, `clippés = 0`, `0/2` contrôle inatteignable |

Aucun de ces verdicts n'est un `PASS` du smoke gelé : ils portent sur les mesures
du harnais dégradé (§ 3) et restent bornés par ses limites déclarées (§ 3.2). Une
conclusion « aucun débordement / aucun contenu inatteignable » n'est écrite **que**
là où une mesure la couvre (colonnes `scrollHeight` / `clientHeight`, compteur de
clipping, hit-tests T2) ; partout ailleurs elle est absente ou qualifiée.

## 11. Statut du smoke gelé et autorité CI

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/tmp/pylibs python3 tests/trainer/smoke_modes_desktop.py`
  : **exécutée localement, échec** — `EXIT=1`, `PermissionError: [Errno 1]
  Operation not permitted` à la création du socket du serveur éphémère (§ 1.1) ;
- `python3 tests/trainer/smoke_trainer.py` : **exécutée localement, échec** —
  `EXIT=1`, `ModuleNotFoundError: No module named 'playwright'` (§ 1.2) ; avec le
  préfixe d'environnement, échec au lancement du navigateur puis à la création de
  la page ; `run_driver_smokes()` n'est donc jamais atteint localement ;
- **le job gelé `browser-smoke` de `.github/workflows/trainer-smoke.yml` reste
  l'autorité** pour le smoke lui-même : il dispose du réseau, de `repro-browser` et
  d'un Chromium chargeable, et il sert `site/` par
  `python3 -m http.server 8765 --directory site` avant
  `run: python3 tests/trainer/smoke_trainer.py` ;
- l'échec du run signalé par le contexte autoritaire de la task sur le HEAD
  `cdbad28` (clic refusé sur `.hh-import-advanced > summary`) est **rapporté par ce
  contexte**, pas réobservé ici : le réseau est coupé (§ 1.3) et la CI n'a pas été
  interrogée depuis ce worktree ;
- **aucun merge, aucun push et aucun état vert de CI n'est affirmé** dans ce
  document. La seule chose affirmée sur la CI est qu'elle n'a **pas** été
  observée.

## 12. Périmètre, contrats statiques et boucle de tests

- **périmètre** : ce document est le **seul** delta versionné de la task
  (`git status --porcelain` → ` M docs/desktop-modes-fit-evidence.md`). Aucun
  fichier `.github/workflows/**` ni `.github/actions/**` n'est modifié ; aucun code
  science / équité / modèles / ranges n'est touché ; `site/index.html`,
  `site/trainer.js` et `site/RELEASE.json` ne sont pas modifiés :
  `python3 tools/write_site_release.py --check` →
  `release source anchor verified: site/RELEASE.json; assembled identity can be
  materialized`, `EXIT=0` ; `node --check site/trainer.js` → `EXIT=0` ;
- `python3 tests/trainer/test_smoke_orchestration_contract.py` → `smoke
  orchestration contract checks: OK`, `EXIT=0`. Cette garde vérifie notamment que
  ce document cite les **deux** commandes du smoke
  (`python3 tests/trainer/smoke_modes_desktop.py` et
  `python3 tests/trainer/smoke_trainer.py`), `git rev-parse HEAD`, `1500x1000` et
  `1366x768`, `scrollHeight` et `clientHeight`, les **six** modes (`home`,
  `spotlab`, `review`, `replayer`, `training`, `strategy`), un **verdict**, et que
  `./hero-ranges.html` est **hors contrat** de coque ;
- boucle complète `for test in tests/trainer/test_*.py; do python3 "$test"; done` :
  exécutée après l'écriture de ce fichier → **48 fichiers, 0 échec** (`files=48
  fails=0`) ; aucune sortie de test n'est recopiée ici, seule la boucle complète
  est revendiquée ;
- hors de ce périmètre, les contrôles git-bound du dépôt qui sont épinglés à un
  SHA de base historique échouent dans ce worktree **indépendamment de cette
  task** : `tests/ci/test_historical_workflow_quarantine.py`,
  `tests/ci/test_repro_current_mixed_batch.py` et
  `tests/ci/test_residual_repro_dag.py` comparent l'arbre courant à
  `ac208d26cbf3f16b498fd5333ad3b7c4fa58355b`, et **236** fichiers diffèrent déjà
  entre ce SHA et le HEAD `43fa73b` (mesuré : `git diff --name-only
  ac208d26cbf3f16b498fd5333ad3b7c4fa58355b HEAD | wc -l` → `236`), alors que leur
  liste blanche en attend une poignée. De même, `tests/test_repro_*.py` doivent
  être lancés avec `PYTHONPATH=.` comme le fait la CI
  (« REPRO batch-1 anti-bypass contract ») : avec ce réglage,
  `PYTHONPATH=. python3 tests/ci/test_repro_workflow_batch1.py` →
  `REPRO workflow batch-1 tests: 9 passed`, `EXIT=0`. Le delta de **cette** task
  reste d'un seul fichier (`git diff --name-only HEAD` →
  `docs/desktop-modes-fit-evidence.md`), et les 48 contrats trainer, dont la garde
  de contrat ci-dessus, sont verts.

## 13. Reproductibilité de ce document

- Date des mesures : **2026-09-25** (Europe/Paris), avant écriture du fichier ;
- `git rev-parse HEAD` au moment des mesures :
  **`43fa73bd17a50cbbab13f6b66d337f399dbaa02c`** (branche
  `n8n/issue-394/task-backlog-z0a`) ;
- le présent document ne peut pas citer le SHA de son propre commit
  (auto-référence) : le worker **ne commit pas, ne pousse pas et ne stage pas**,
  l'orchestrateur gère le commit et la PR ;
- le harnais local et ses sorties (`/tmp/z0a/harness.py`, `calib.py`,
  `home_edge.py`, `limits.py`, `cdp_probe.py`, `key_probe.py`, `browser_alive.py`,
  `out9.json`,
  `harness_run9.log`, `calib.json`, `home_edge.log`, `limits.log`) sont **hors
  dépôt et non versionnés** : ils ne sont
  pas une dépendance du contrat, seulement la trace de la méthode réellement
  utilisée, dont les limites sont déclarées au § 3.2 ;
- ce qui est reproductible sans ce harnais : les sorties et codes retour du § 1
  (les deux commandes, `git rev-parse HEAD`, les sondes socket / saisie), la garde
  de contrat et la boucle de tests du § 12.

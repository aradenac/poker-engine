# #395 — cause du `Timeout 20000ms exceeded` du smoke « large list »

Task : `backlog-zk0` (branche `n8n/issue-395/task-backlog-zk0`), HEAD de travail
`1050c040` (PR #417). Fichier concerné :
`tests/trainer/smoke_review_inbox_large_list.py`.

> **Consolidation au HEAD courant `7b41895`.** La branche
> `n8n/issue-395-restaurer-filtres-resultat-tris-temporels-et-pagin` porte
> `7b418954689e5bae892211d4e30707a2ab44baec` (`7b41895`), soit **4 commits**
> devant `origin/…` = `1050c040` : `c9e03e4` (zk0), `c2272bb` (hsx),
> `7363fc0` (zid), `7b41895` (a7j). Les §1–§11 conservent, à dessein, les
> mesures prises à leurs propres HEAD historiques (`1050c040` pour la revue
> initiale, `c2272bb` pour T3) ; §12 et §13 sont mesurées au HEAD courant, seule
> référence de l'état présent. Cette consolidation est portée par la tâche
> `backlog-ph4` (branche `n8n/issue-395/task-backlog-ph4`, diff limité à ce
> fichier) ; elle corrige les références de HEAD/avance restées à `7363fc0` et
> renumérote §13, sans toucher aux bornages ni à la fixture 32 mains/`EVEN`.

## 1. Verdict

**Cause déterministe, côté smoke, dans la section « préférences » :** l'attente
ci-dessous (celle du HEAD `1050c040`, remplacée par ce correctif)

```python
await page.wait_for_function(
    "() => { const el=document.getElementById('localPersistenceStatus');"
    " return !state.persistPrefsTimer && !!el"
    " && /Sauvegarde locale automatique active/.test(el.textContent); }",
    timeout=20_000,
)
```

teste un texte que la coque servie **n'écrit jamais dans cet élément**. La
fonction servie `persistenceStatus` (`site/index.html:2544-2549`) écrit :

* dans `#localPersistenceStatus` (la pastille) :
  `error?"Sauvegarde locale en erreur":busy?"Sauvegarde…":"Sauvegardé localement"` ;
* dans `#localPersistenceDetail` (un **frère**, `site/index.html:1400`) :
  le message, dont `"Sauvegarde locale automatique active · …"` au succès de
  `schedulePersistPrefs` (`site/index.html:2624`).

`/Sauvegarde locale automatique active/.test("#localPersistenceStatus".textContent)`
est donc **faux pour toujours** : `!state.persistPrefsTimer` et `!!el` peuvent
devenir vrais, la clause de texte non. Le prédicat ne peut jamais devenir vrai →
`playwright._impl._errors.TimeoutError:
Page.wait_for_function: Timeout 20000ms exceeded`, reproductible 2/2.

Le message épinglé par le contrat servi est `"Sauvegardé localement"` : c'est
déjà l'assertion du smoke frère (`tests/trainer/smoke_trainer.py:1221`,
`assert local_persistence["saved"] == "Sauvegardé localement"`).

## 2. Pourquoi cette attente, et pas celles de peinture

* L'attente fautive existe **depuis l'origine de la branche** (identique en
  `4b3e548:551`, `d30a861:652`, `1050c040:748`) : elle n'a jamais été franchie
  parce que le smoke mourait avant, d'abord sur `assert not
  first_page["prevDisabled"]` (T1), puis sur l'égalité « page 1 == liste
  filtrée » du filtre `EVEN` (job 108016144405, ligne 619).
* Cette seconde panne est la preuve que **tout ce qui précède passe en CI** :
  pour atteindre la ligne 619, le run `d30a861` a franchi le clic sur
  `button.mode-card[data-app-view="review"]`, l'import réel des 32 mains, le clic
  sur `#reviewInboxTab` et les deux attentes de peinture à 20 s. La prochaine
  attente à 20 s du fichier après le bloc filtre est celle des préférences.
* Aucune des attentes de peinture n'est retirée pour autant : voir §4, elles
  deviennent causales (§5.2).

## 3. Reproduction locale : blocage exact documenté

Le sandbox de cette tâche n'a ni `pip`/`ensurepip` ni navigateur fonctionnel.

1. `python3 tests/trainer/smoke_review_inbox_large_list.py`
   → `ModuleNotFoundError: No module named 'playwright'`
   (et `python3 -m pip` → `No module named pip`, `python3 -m ensurepip` →
   `No module named ensurepip`).
2. Les wheels *lockées* ont été extraites du cache pip local
   (`~/.cache/pip/http-v2`) et installées hors ligne :

   ```bash
   PYTHONPATH=/tmp/piplib python3 -m pip install --no-index \
     --find-links=/tmp/pw-wheelhouse --target=/tmp/pwenv playwright==1.55.0
   # playwright-1.55.0-py3-none-any, greenlet-3.5.6-cp314, pyee-13.0.1,
   # typing_extensions-4.16.0  →  Successfully installed
   PYTHONPATH=/tmp/pwenv python3 -c "import playwright; print(playwright.__file__)"
   # /tmp/pwenv/playwright/__init__.py
   ```
3. Lancement Chromium verrouillé (`chromium_headless_shell-1187`) :

   ```bash
   PYTHONPATH=/tmp/pwenv python3 /tmp/pwprobe.py
   ```

   ```
   playwright._impl._errors.TargetClosedError: BrowserType.launch: Target page,
   context or browser has been closed
   [pid=17][err] .../chromium_headless_shell-1187/chrome-linux/headless_shell:
   error while loading shared libraries: libnspr4.so: cannot open shared object
   file: No such file or directory
   ```

   `ldd` sur le binaire donne exactement les manquants :
   `libasound.so.2`, `libnspr4.so`, `libnss3.so`, `libnssutil3.so`. Ni
   `libnss3`/`libnspr4`/`libasound2` (aucun paquet dans
   `/var/cache/apt/archives`, réseau restreint), ni un autre moteur
   (`~/.cache/ms-playwright` ne contient que `chromium-1187`,
   `chromium_headless_shell-1187`, `ffmpeg-1011`) ne sont disponibles :
   `python3 tools/repro_ci_browser.py install` exigerait réseau + root.

**Le blocage local est donc documenté (commande + erreur) conformément à
l'acceptance**, et la ligne fautive est identifiée par une preuve *plus
stricte* qu'une lecture de traceback : le prédicat est insatisfiable.

## 4. Preuve mécanique (rejouée sur les octets servis, sans navigateur)

Commande autoportante (aucun fichier temporaire requis) : elle relit
`site/index.html`, reconstruit le texte que la coque écrit dans la pastille au
succès du writer et rejoue le prédicat de l'ancienne attente.

```bash
node -e '
const fs=require("fs");
const INDEX=fs.readFileSync("site/index.html","utf8");
const chipExpr="localPersistenceStatus.textContent=error?\"Sauvegarde locale en erreur\":busy?\"Sauvegarde…\":\"Sauvegardé localement\"";
console.log("declaration de la pastille servie:", INDEX.includes(chipExpr));
const message="Sauvegarde locale automatique active · fichiers et main sélectionnée seront restaurés au prochain lancement.";
console.log("message present dans les octets servis:", INDEX.includes(message));
const error=false,busy=false;
const chip=error?"Sauvegarde locale en erreur":busy?"Sauvegarde…":"Sauvegardé localement";
console.log("texte reel de la pastille:", JSON.stringify(chip));
console.log("ancien predicat (/Sauvegarde locale automatique active/) sur la pastille:", /Sauvegarde locale automatique active/.test(chip));
'
```

```
declaration de la pastille servie: true
message present dans les octets servis: true
texte reel de la pastille: "Sauvegardé localement"
ancien predicat (/Sauvegarde locale automatique active/) sur la pastille: false
```

Le nouveau prédicat a été exécuté de la même façon sur quatre états simulés
(écriture en cours, préférences d'un autre tri, préférences attendues, store
vide) via la constante `PERSISTED_PREFS_FN` du module : il ne vaut `true` que
pour `stored && !busy && hhSort==="loss_desc" && result==="LOSS"` et la pastille
servie `"Sauvegardé localement"` — et le message y arrive bien dans
`#localPersistenceDetail`.

## 5. Correctif (dans le smoke uniquement)

1. **Préférences — attente causale, plus de texte au mauvais endroit.** Après
   `schedulePersistPrefs(0)`, `_wait_persisted_prefs()` lit ce que le reload
   relira réellement : `localDbGet("prefs")` (`site/index.html:9953`, appliqué
   en `9970-10000`) doit porter `hhSort === "loss_desc"` et
   `reviewInboxFilters.result === "LOSS"`, le writer débouncé doit être retombé
   (`!state.persistPrefsTimer`) et la pastille servie doit afficher
   `"Sauvegardé localement"`. La boucle échoue avec l'état mesuré (pastille +
   détail + valeurs persistées) si l'effet n'arrive pas ; le résultat est
   consigné dans `audit["prefs_persisted"]`.
2. **Peinture de l'inbox — plus de délai fixe.** Les deux
   `wait_for_function("... '#hhHands .hh-hand' ...", timeout=20_000)` (première
   visite et après reload) sont remplacées par :
   * la preuve que le **clic lui-même peint** — `activateAppSubview("inbox")`
     appelle `renderHistoryHands()` de façon synchrone (`site/index.html:7029`),
     donc un décompte DOM pris au retour de `page.click` doit être non nul ;
   * la mesure de la page par l'évaluation atomique inject+repaint déjà utilisée
     ailleurs (`window.__reviewInboxSmoke.inject` → `renderHistoryHands` →
     lecture DOM), qui doit peindre au moins une main ;
   * `#handSelectionSection` visible, pour que la hauteur mesurée soit celle de
     la coque réellement affichée.
3. **Aucun budget relevé** : les 20 s ne portent plus aucune peinture ni
   persistance, donc rien n'est aligné « au cas où ». Les attentes restantes à
   20 s sont des transitions d'état synchrones (bascule `dataset.appView`).

## 6. Ce qui n'a pas bougé

* `assert_bounded`, `assert_page_size_target`, `assert_pagination`,
  `_walk_pages` (et sa polarité Précédent/Suivant), les cinq tris de premier
  niveau, le filtre résultat (marche page par page) et la marche `EVEN`
  multi-pages : inchangés.
* `site/index.html` : **aucune modification** — pas de changement de
  `site/index.html:7257-7261` (pagineur/légende), donc `site/RELEASE.json` et le
  miroir `src/` restent valides tels quels.
* `.github/workflows/trainer-smoke.yml` : intact.
* `tests/trainer/smoke_trainer.py` : intact (l'entrée `DRIVER_SMOKES` reste).

## 7. T5b — taille de page et peinture des 32 mains

Le smoke n'est pas relâché : `assert_page_size_target` reste appelé sur chaque
page peinte (page 1, chaque tri, chaque filtre, reload) et `page_size_reference`
continue de consigner la mesure. La géométrie servie, re-dérivée **sans
navigateur** sur les octets servis et la fixture 32 mains, est inchangée :

```bash
python3 tests/trainer/test_review_inbox_pagination_contract.py
# review inbox pagination contract checks: OK (page window 10–15 …
# pinned page size at 1500x1000 = 10–11 on the served shell with the 32-hand
# fixture — conservative budget: chrome 403.95px, list 596.05px, row 53.15px,
# pitch 59.15px; résultats {'WIN': 8, 'LOSS': 8, 'EVEN': 14, 'UNKNOWN': 2} —
# EVEN (14) multi-pages dans les deux modèles …)
```

La page peinte reste donc dans `[10, 15]` et c'est toujours la capacité mesurée
(`reviewInboxFitCount()` / `reviewInboxRowPitch()` / hauteur contrainte) qui la
porte ; `smoke_review_inbox_large_list.py` ne modifie ni la coque ni la mesure.

Le contrôle « la liste est vraiment peinte avec les 32 mains importées » est
porté par le smoke (`state.hhHands.length === 32` après l'import réel, décompte
`#hhHands .hh-hand > 0` au retour du clic d'onglet, puis au moins une main sur la
page mesurée, `#handSelectionSection` visible, `assert_bounded`). Comme le
navigateur n'est pas disponible ici, sa contrepartie servie a été rejouée sur les
octets committés — parseur servis + module `poker-review-inbox/v1`, sans
navigateur :

```
schema=poker-review-inbox-large-list-probe/v1  fixture=…/review_inbox_large_list.hand.txt
block_count=32  hands=32  items=32  warnings=[]
result_counts: WIN=8 LOSS=8 EVEN=14 UNKNOWN=2   (tous les tris portent 32 mains)
```

C'est le même probe que `test_review_inbox_large_list_smoke_contract.py` rejoue :
les 32 mains importées traversent le vrai parseur et le vrai module d'inbox, et
la coque bornée ne peint qu'une tranche `pageWindow` de cette liste. Autrement
dit, la liste est réellement peuplée des 32 mains importées dans `state.hhHands`
et `#hhHands` (`.hh-list`) n'est ni masqué ni vide, la page peinte en étant la
tranche mesurée.

## 8. Vérifications exécutées ici

| Commande | Résultat |
| --- | --- |
| `python3 -m py_compile tests/trainer/smoke_review_inbox_large_list.py` | OK |
| `python3 tests/trainer/test_review_inbox_large_list_smoke_contract.py` | OK (jetons servis, `node --check` des snippets — dont le nouveau `PERSISTED_PREFS_FN`, polarité du pagineur, borne basse T5b rejouée) |
| `python3 tests/trainer/test_review_inbox_pagination_contract.py` | OK (page 10–11 à 1500x1000, `EVEN` multi-pages) |
| `node tests/trainer/fixtures/review_inbox_large_list_probe.js <fixture> <payload>` | `block_count=32`, `hands=32`, `items=32`, `warnings=[]` (§7) |
| `ran=0; fail=0; for t in tests/trainer/test_*.py; do ran=$((ran+1)); if ! python3 "$t" >/dev/null 2>&1; then fail=$((fail+1)); echo "FAIL $t"; fi; done; echo "ran=$ran overall_fail=$fail"` | OK (52 contrats trainer, `ran=52 overall_fail=0`) |
| `python3 tests/ci/test_repro_workflow_batch1.py` / `batch2` | OK (workflow `trainer-smoke` intact, digest protégé inchangé) |
| `node -e '…'` (§4) | Preuve mécanique de l'ancien prédicat insatisfiable |

Le smoke navigateur lui-même n'a pas pu être exécuté ici (§3) : sa validation
finale revient au job `browser-smoke` (`python3 tests/trainer/smoke_trainer.py`),
qui doit désormais franchir la section « préférences » et imprimer l'audit.

## 9. Suivi proposé (hors de cette tâche)

Le même piège — attendre un *message* dans la *pastille* — n'est pour l'instant
attrapé par aucun contrat statique. Une assertion dans
`tests/trainer/test_review_inbox_large_list_smoke_contract.py` (interdire
`Sauvegarde locale automatique active` testé sur `#localPersistenceStatus`,
exiger la lecture de `localDbGet("prefs")` / du libellé servi
`Sauvegardé localement`) empêcherait la récidive à coût nul.

## 10. T2 — verrou statique de la causalité et du budget des attentes

Task : `backlog-hsx` (branche `n8n/issue-395/task-backlog-hsx`). Le même contrat
statique épingle désormais, sur la source de la smoke, deux récidives :

1. **Causalité de la peinture.** Toute lecture du compteur
   `document.querySelectorAll('#hhHands .hh-hand').length` doit être *portée*
   par l'attente causale de la même expression : `_wait_paint()`, dont le
   `wait_for_function` a ce compteur pour prédicat et dont le budget nommé
   n'est qu'un garde-fou. Un compteur nu (`page.evaluate(...)`), un
   `wait_for_timeout` placé devant une lecture, ou une lecture échantillonnée
   coupée en deux tours (hors du `page.evaluate(INJECT_AND_READ_JS, payload)`
   atomique) sont refusés.
2. **Budget minimal des attentes de vue/peinture.** La smoke déclare
   `VIEW_READY_TIMEOUT_MS = 30_000` et `PAINT_TIMEOUT_MS = 30_000` ; le garde
   lit ces valeurs et exige qu'elles restent ≥ son plancher
   `MIN_VIEW_PAINT_TIMEOUT_MS` (30 s, au-dessus des 20 s du défaut T1). Une
   attente de vue (`dataset.appView`) ou de peinture qui repasserait à un
   littéral — donc au `timeout=20_000` d'origine — est refusée.

Non-vacuité rejouée en mémoire par `check_paint_wait_non_vacuity()` (aucune
écriture disque), sortie consignée par `main()` :

| Mutation rejouée | Verdict du garde |
| --- | --- |
| `PAINT_TIMEOUT_MS = 20_000` | refusée — budget sous le plancher T2 |
| attente de vue `timeout=20000` | refusée — littéral sur une attente de vue |
| peinture garantie par un délai fixe + compteur nu | refusée — pas d'attente causale |
| attente de peinture sans l'expression causale | refusée — pas d'attente causale |
| compteur nu réintroduit au clic d'onglet | refusée — lecture hors attente |
| `wait_for_timeout(500)` devant la lecture causale | refusée — délai devant la lecture |
| `_inject_and_read` coupé en deux tours | refusée — lecture non atomique |

`site/index.html` et `.github/workflows/trainer-smoke.yml` restent inchangés ;
la suite `tests/trainer/test_review_inbox_large_list_smoke_contract.py` passe au
HEAD corrigé.

La lecture causale n'est pas qu'un jeton de texte : `check_paint_read_helper()`
*exécute* `_wait_paint()` sur une page factice (sans navigateur) qui n'implémente
que le contrat de `wait_for_function` — 3 sondages, dont le premier non nul peint
7 lignes, un seul appel d'attente sur le budget nommé, et `AttributeError` si le
helper touchait un `wait_for_timeout`/`evaluate`.

## 11. T3 — rejeu des suites statiques et mesure au HEAD exact

Task : `backlog-zid` (branche `n8n/issue-395/task-backlog-zid`).

### 11.1 HEAD mesuré

```
branche : n8n/issue-395/task-backlog-zid
HEAD    : c2272bba13dee5cf76bc9702dfe9e87727b95e34  (c2272bb)
```

T3 ne modifie ni `site/index.html`, ni
`tests/trainer/smoke_review_inbox_large_list.py`, ni
`.github/workflows/trainer-smoke.yml` : elle rejoue les suites sur les octets
déjà committés et consigne la mesure. Les seuls octets écrits par cette tâche
sont ce rapport (diff git non vide à l'appui).

### 11.2 Suites statiques rejouées au HEAD — vertes

`python3 -m pytest` n'est pas disponible ici : `pytest` n'est **pas** une
dépendance du dépôt (`requirements.lock.txt` ne porte que `greenlet`,
`playwright`, `pyee`, `typing_extensions`) et aucune wheel `pytest` n'existe en
cache hors-ligne :

```
$ python3 -m pytest tests/trainer/test_review_inbox_pagination_contract.py \
    tests/trainer/test_review_inbox_large_list_smoke_contract.py \
    tests/trainer/test_review_inbox_ui_contract.py
/usr/bin/python3: No module named pytest     # exit=1
```

Les suites sont donc rejouées **comme le fait le job CI** (chaque fichier est un
script autoportant `main()` dans ce dépôt — cf. `.github/workflows/*.yml`, qui
appellent tous `python3 tests/trainer/test_*.py`) :

| Commande (HEAD `c2272bb`) | Exit | Dernière ligne |
| --- | --- | --- |
| `python3 tests/trainer/test_review_inbox_pagination_contract.py` | 0 | `review inbox pagination contract checks: OK` (page window 10–15 mesurée, `page size at 1500x1000 = 10–11` sur la coque servie avec la fixture 32 mains — budget conservateur : chrome 403.95px, list 596.05px, row 53.15px, pitch 59.15px ; résultats `{'WIN': 8, 'LOSS': 8, 'EVEN': 14, 'UNKNOWN': 2}` — `EVEN` (14) multi-pages dans les deux modèles, garde « page 1 == liste filtrée » rejouée) |
| `python3 tests/trainer/test_review_inbox_large_list_smoke_contract.py` | 0 | `review inbox large list smoke contract checks: OK` (32 mains · 5 tris rejoués par le contrat servi · taille de page bornée ≤15 · borne basse mesurée épinglée (10, justification par les hauteurs mesurées rejouée) · pagination `Précédent`/`Suivant` épinglée au pager servi (page 1 : `Précédent` désactivé, `Suivant` actif · assertion inverse rejouée) · peinture lue causalement (1 lecture de `document.querySelectorAll('#hhHands .hh-hand').length` dans l'attente · helper rejoué 3 sondages → 7 lignes peintes) · budgets vue/peinture nommés 30000 / 30000 ms (plancher 30000, 20000 refusé · 7 mutations rejouées) · fixture `tests/trainer/fixtures/review_inbox_large_list.hand.txt`) |
| `python3 tests/trainer/test_review_inbox_ui_contract.py` | 0 | `review inbox runtime mirror/UI contract checks: OK` |

Les trois sorties sont consignées telles quelles (aucune assertion neutralisée,
aucune constante relâchée : les contrats continuent d'échouer sur leurs
mutations rejouées, cf. les lignes `refusé (T2): …` du second contrat).

Balayage élargi au même HEAD, pour que le rejeu ne s'arrête pas aux trois
fichiers demandés :

```
$ ran=0; fail=0; for t in tests/trainer/test_*.py; do ran=$((ran+1)); if ! python3 "$t" >/dev/null 2>&1; then fail=$((fail+1)); echo "FAIL $t"; fi; done; echo "ran=$ran overall_fail=$fail"
ran=52 overall_fail=0
$ python3 tests/ci/test_repro_workflow_batch1.py
REPRO workflow batch-1 tests: 9 passed
$ python3 tests/ci/test_repro_workflow_batch2.py
Ran 4 tests in 0.008s -- OK            # digest du workflow gelé inchangé
$ python3 -m py_compile tests/trainer/smoke_review_inbox_large_list.py
OK
```

### 11.3 Smoke navigateur 1500x1000 : blocage local, commande + erreur brute

Aucun vert navigateur n'est revendiqué. Quatre tentatives, dans l'ordre :

**(a)** `python3 tools/repro_ci_browser.py install` → exit 2 :

```
/usr/bin/python3: No module named playwright
{
  "schema": "poker-repro-ci-browser-report/v1",
  "status": "FAIL",
  "violations": [
    {
      "detail": "Command '['/usr/bin/python3', '-m', 'playwright', 'install',
                 '--with-deps', 'chromium']' returned non-zero exit status 1.",
      "rule": "HELPER_ERROR"
    }
  ]
}
```

**(b)** `python3 tests/trainer/smoke_review_inbox_large_list.py` → exit 1 (garde
d'import du smoke) :

```
smoke_review_inbox_large_list: Playwright is unavailable
(ModuleNotFoundError("No module named 'playwright'")). Install the locked
dependencies (requirements.lock.txt) and the pinned browser runtime
(python3 tools/repro_ci_browser.py install) before running this smoke.
```

**(c)** Dépendances récupérées hors ligne (`playwright==1.55.0` verrouillé,
extrait du cache pip local) et **bibliothèques navigateur récupérées** depuis le
sysroot laissé par un worker précédent (`libnspr4`, `libnss3`, `libnssutil3`,
`libasound2` — les quatre manquantes du §3). Le binaire n'est donc plus le
blocage : `headless_shell --version` répond `Chromium 140.0.7339.16`. Le smoke
meurt alors **avant** le navigateur, sur son serveur statique :

```
$ LD_LIBRARY_PATH=<sysroot>/usr/lib/x86_64-linux-gnu PYTHONPATH=<playwright> \
    python3 tests/trainer/smoke_review_inbox_large_list.py
  File "tests/trainer/smoke_review_inbox_large_list.py", line 399, in _serve_site
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
  File "/usr/lib/python3.14/socketserver.py", line 453, in __init__
    self.socket = socket.socket(self.address_family, self.socket_type)
PermissionError: [Errno 1] Operation not permitted
```

**(d)** `python3 tests/trainer/smoke_trainer.py` (même environnement) : Chromium
est lancé (`<launched> pid=20`), puis le processus meurt sur un appel système
refusé par le sandbox :

```
[pid=20][err] [0925/121939.157284:FATAL:content/browser/sandbox_host_linux.cc:41]
  Check failed: . shutdown: Operation not permitted (1)
playwright._impl._errors.TargetClosedError: BrowserType.launch: Target page,
  context or browser has been closed
trainer smoke failed: BrowserType.launch: Target page, context or browser has been closed
```

**Reproducteur minimal (sans Playwright ni Chromium)** — le sandbox de cette
tâche refuse les appels système dont dépendent *tous* les smokes navigateur :

```
$ python3 - <<'PY'
import socket
for fam, typ, name in [(socket.AF_INET, socket.SOCK_STREAM, "AF_INET/SOCK_STREAM"),
                       (socket.AF_INET, socket.SOCK_DGRAM,  "AF_INET/SOCK_DGRAM"),
                       (socket.AF_INET6, socket.SOCK_STREAM, "AF_INET6/SOCK_STREAM"),
                       (socket.AF_UNIX, socket.SOCK_STREAM,  "AF_UNIX/SOCK_STREAM")]:
    try:
        s = socket.socket(fam, typ); s.close(); print(name, "OK")
    except OSError as e:
        print(name, "FAIL", e)
a, b = socket.socketpair()
try: a.shutdown(socket.SHUT_RDWR); print("shutdown OK")
except OSError as e: print("shutdown FAIL", e)
try: a.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1); print("setsockopt OK")
except OSError as e: print("setsockopt FAIL", e)
PY
AF_INET/SOCK_STREAM FAIL [Errno 1] Operation not permitted
AF_INET/SOCK_DGRAM FAIL [Errno 1] Operation not permitted
AF_INET6/SOCK_STREAM FAIL [Errno 1] Operation not permitted
AF_UNIX/SOCK_STREAM OK
shutdown FAIL [Errno 1] Operation not permitted
setsockopt FAIL [Errno 1] Operation not permitted
$ unshare -n true
unshare: unshare failed: Operation not permitted
```

Deux blocages indépendants, tous deux dans le filtre d'appels système du
sandbox local :

1. **aucun socket `AF_INET`/`AF_INET6`** → le `ThreadingHTTPServer(("127.0.0.1", 0))`
   que chaque smoke navigateur ouvre pour servir `site/` ne peut pas être créé
   (cas (c)) ;
2. **`shutdown()`/`setsockopt()` refusés sur les paires `AF_UNIX`** → le
   *sandbox host* de Chromium meurt au démarrage (cas (d)).

Ce n'est donc **pas** la cause du §3 (libs manquantes, désormais récupérées) :
ni `python3 tools/repro_ci_browser.py install`, ni un binaire déjà installé ne
peuvent lever ce blocage. Conséquence conforme à l'acceptance : **le run CI de
T4 devient la source de vérité pour le vert navigateur 1500x1000**.

### 11.4 Mesure non navigateur au HEAD : rejeu sur les octets servis

Faute de navigateur, les grandeurs mesurables sans navigateur ont été rejouées
**sur les octets servis** au HEAD : `node` exécute le vrai `renderReviewInboxPage`
dans la coque mesurée aux deux modèles de la dérivation T5b (borne basse
« majorant », borne haute « typographique »), et
`tests/trainer/test_review_inbox_large_list_smoke_contract.py` rejoue la fixture
32 mains dans le vrai parseur servi + le vrai module `poker-review-inbox/v1`
(probe `poker-review-inbox-large-list-probe/v1`, `warnings=[]`).

**Taille de page et bornage au viewport 1500x1000** (les deux modèles ; la page
peinte reste dans `[10, 15]`, cible servie `REVIEW_INBOX_PAGE_SIZE_MIN=10`) :

| Modèle | `page_size` | `fit_count` | `row_pitch` | `row` | `list_client_height` | `listOverflowY` | `listScrollHeight` vs `clientHeight` |
| --- | --- | --- | --- | --- | --- | --- | --- |
| majorant | 10 | 10 | 59.15 px | 53.15 px | 596.05 px | `hidden` | 585.50 ≤ 596.05 |
| typographique | 11 | 11 | 56.00 px | 49.55 px | 627.55 px | `hidden` | 605.05 ≤ 627.55 |

`listOverflowY` est ici la **déclaration servie** (`.hh-list{overflow:hidden}` au
desktop, épinglée par le contrat statique de
`tests/trainer/test_review_inbox_pagination_contract.py`), pas un
`getComputedStyle` de navigateur ; `listScrollHeight` / `clientHeight` sont
mesurés par le harnais `node` sur le vrai `renderReviewInboxPage` dans la coque
dérivée (pager inclus dans la hauteur contrainte, cf. T5b).

Deux bornes de l'audit navigateur ne sont **pas** rejouables ici et ne sont donc
pas affirmées : `list.scrollTop` (lu par le smoke, il doit rester `0` — ce que
`listScrollHeight ≤ clientHeight` ci-dessus rend nécessaire, sans le mesurer) et
la paire document `docScrollHeight` vs `docClientHeight` (mesure de navigateur ;
la coque à hauteur fixe qui la contraint est portée par les contrats de coque
T5b / `smoke_modes_desktop.py`). Cf. §11.5.

**Tri par tri** (32 mains, aucun filtre) et **filtre résultat** :

| Requête | Ids | Pages (majorant) | Pages (typographique) | Légende servie page 1 (majorant) |
| --- | --- | --- | --- | --- |
| `recent_desc` | 32 | 4 | 3 | `Page 1 / 4 · mains 1–10 sur 32` |
| `recent_asc` | 32 | 4 | 3 | `Page 1 / 4 · mains 1–10 sur 32` |
| `ev_loss_desc` | 32 | 4 | 3 | `Page 1 / 4 · mains 1–10 sur 32` |
| `gain_desc` | 32 | 4 | 3 | `Page 1 / 4 · mains 1–10 sur 32` |
| `loss_desc` | 32 | 4 | 3 | `Page 1 / 4 · mains 1–10 sur 32` |
| `filter_WIN` | 8 | 1 (pager masqué) | 1 (pager masqué) | — |
| `filter_LOSS` | 8 | 1 (pager masqué) | 1 (pager masqué) | — |
| **`filter_EVEN`** | **14** | **2** | **2** | **`Page 1 / 2 · mains 1–10 sur 14`** |
| `filter_UNKNOWN` | 2 | 1 (pager masqué) | 1 (pager masqué) | — |

Le modèle typographique donne la même classification avec l'autre pas :
`EVEN` = 2 pages, `Page 1 / 2 · mains 1–11 sur 14` ; les 32 mains des cinq tris
y tiennent en 3 pages, page 1 = `Page 1 / 3 · mains 1–11 sur 32`.

Polarité du pager rejouée aux deux modèles : page 1 → `prevDisabled=true`,
`nextDisabled=false` ; la marche va jusqu'à la dernière page (`nextDisabled=true`),
et la concaténation des pages peintes vaut exactement l'ordre attendu du tri /
l'état filtré (`painted == wanted`, ids ci-dessous).

Audit JSON rejoué au HEAD `c2272bb` (valeurs rejouées sur les octets servis —
**pas** de mesure navigateur ; les sections navigateur sont listées au §11.5) :

```json
{
  "schema": "issue-395-t3-head-audit/v1",
  "head_sha": "c2272bba13dee5cf76bc9702dfe9e87727b95e34",
  "viewport": [1500, 1000],
  "hand_total": 32,
  "page_size": {
    "majorant":     {"page_size": 10, "fit_count": 10, "row_pitch": 59.15, "row": 53.15, "list_client_height": 596.05},
    "typographic":  {"page_size": 11, "fit_count": 11, "row_pitch": 56.00, "row": 49.55, "list_client_height": 627.55}
  },
  "bounding": {
    "majorant":    {"list_overflow_y": "hidden", "scroll_height": 585.50, "client_height": 596.05,
                    "overflow": false, "pager_visible": true, "prev_disabled": true, "next_disabled": false},
    "typographic": {"list_overflow_y": "hidden", "scroll_height": 605.05, "client_height": 627.55,
                    "overflow": false, "pager_visible": true, "prev_disabled": true, "next_disabled": false}
  },
  "sorts": {
    "recent_desc":  {"contract_mode": "TIMESTAMP_DESC",     "pages": {"majorant": 4, "typographic": 3},
                     "page_1_majorant": ["3950032","3950031","3950030","3950029","3950028","3950027","3950026","3950025","3950024","3950023"],
                     "ids": ["3950032","3950031","3950030","3950029","3950028","3950027","3950026","3950025","3950024","3950023","3950022","3950021","3950020","3950019","3950018","3950017","3950016","3950015","3950014","3950013","3950012","3950011","3950010","3950009","3950008","3950007","3950006","3950005","3950004","3950003","3950002","3950001"]},
    "recent_asc":   {"contract_mode": "TIMESTAMP_ASC",      "pages": {"majorant": 4, "typographic": 3},
                     "page_1_majorant": ["3950001","3950002","3950003","3950004","3950005","3950006","3950007","3950008","3950009","3950010"],
                     "ids": ["3950001","3950002","3950003","3950004","3950005","3950006","3950007","3950008","3950009","3950010","3950011","3950012","3950013","3950014","3950015","3950016","3950017","3950018","3950019","3950020","3950021","3950022","3950023","3950024","3950025","3950026","3950027","3950028","3950029","3950030","3950031","3950032"]},
    "ev_loss_desc": {"contract_mode": "EV_LOSS_DESC",       "pages": {"majorant": 4, "typographic": 3},
                     "page_1_majorant": ["3950009","3950018","3950027","3950013","3950022","3950031","3950017","3950026","3950003","3950021"],
                     "ids": ["3950009","3950018","3950027","3950013","3950022","3950031","3950017","3950026","3950003","3950021","3950030","3950007","3950025","3950002","3950011","3950029","3950006","3950015","3950001","3950010","3950019","3950005","3950014","3950023","3950004","3950008","3950012","3950016","3950020","3950024","3950028","3950032"]},
    "gain_desc":    {"contract_mode": "RESULT_GAIN_DESC",   "pages": {"majorant": 4, "typographic": 3},
                     "page_1_majorant": ["3950029","3950025","3950021","3950017","3950013","3950009","3950005","3950001","3950003","3950004"],
                     "ids": ["3950029","3950025","3950021","3950017","3950013","3950009","3950005","3950001","3950003","3950004","3950007","3950008","3950012","3950015","3950016","3950019","3950020","3950023","3950024","3950028","3950031","3950032","3950002","3950006","3950010","3950014","3950018","3950022","3950026","3950030","3950011","3950027"]},
    "loss_desc":    {"contract_mode": "RESULT_LOSS_DESC",   "pages": {"majorant": 4, "typographic": 3},
                     "page_1_majorant": ["3950030","3950026","3950022","3950018","3950014","3950010","3950006","3950002","3950003","3950004"],
                     "ids": ["3950030","3950026","3950022","3950018","3950014","3950010","3950006","3950002","3950003","3950004","3950007","3950008","3950012","3950015","3950016","3950019","3950020","3950023","3950024","3950028","3950031","3950032","3950001","3950005","3950009","3950013","3950017","3950021","3950025","3950029","3950011","3950027"]}
  },
  "filters": {
    "WIN":     {"contract_mode": "RESULT_WIN",     "count": 8,  "pages": {"majorant": 1, "typographic": 1},
                "ids": ["3950029","3950025","3950021","3950017","3950013","3950009","3950005","3950001"]},
    "LOSS":    {"contract_mode": "RESULT_LOSS",    "count": 8,  "pages": {"majorant": 1, "typographic": 1},
                "ids": ["3950030","3950026","3950022","3950018","3950014","3950010","3950006","3950002"]},
    "EVEN":    {"contract_mode": "RESULT_EVEN",    "count": 14, "pages": {"majorant": 2, "typographic": 2},
                "caption_page_1": {"majorant": "Page 1 / 2 · mains 1–10 sur 14", "typographic": "Page 1 / 2 · mains 1–11 sur 14"},
                "ids": ["3950032","3950031","3950028","3950024","3950023","3950020","3950019","3950016","3950015","3950012","3950008","3950007","3950004","3950003"]},
    "UNKNOWN": {"contract_mode": "RESULT_UNKNOWN", "count": 2,  "pages": {"majorant": 1, "typographic": 1},
                "ids": ["3950027","3950011"]}
  },
  "deep_link": {
    "decision_id_shape": "review:<hand_id>:8",
    "step": 8,
    "with_comparable_decision_count": 24,
    "without_comparable_decision": {
      "hand_ids": ["3950004","3950008","3950012","3950016","3950020","3950024","3950028","3950032"],
      "decision_id": null, "step": null, "status": "INCOMPLETE_ANALYSIS"
    }
  }
}
```

### 11.5 Ce qui reste strictement navigateur (porté par T4 / le job `browser-smoke`)

Ces clés de l'audit du smoke n'ont **pas** de contrepartie sans navigateur : elles
ne sont ni mesurées ni estimées ici, et le rapport ne les revendique pas vertes.

```
audit["tab_click_paints"]                    # décompte peint au retour du clic d'onglet (1re visite + reload)
audit["prefs_persisted"]                     # localDbGet("prefs") + pastille « Sauvegardé localement »
audit["reload"]                              # tri/filtre restaurés, marche page par page
audit["selection"]                           # sélection stable sur un aller-retour de page
audit["no_decision"]                         # deep link d'une main sans décision comparable (« Analyse incomplète »)
list.scrollTop                               # 0 attendu (rendu borné, figé par listScrollHeight ≤ clientHeight)
docScrollHeight vs docClientHeight           # le document ne défile pas
page_errors / console_errors                 # aucune erreur console/page à la fin du run
```

Le vert navigateur 1500x1000 et l'audit complet du smoke sont donc produits par
le run CI de T4 (`python3 tests/trainer/smoke_trainer.py`, qui exécute
`smoke_review_inbox_large_list.py` via `DRIVER_SMOKES`), conformément à
l'acceptance « blocage local documenté → le run CI de T4 devient la source de
vérité ».

### 11.6 Interdits respectés

* aucune assertion neutralisée ni constante relâchée : les trois suites passent
  avec leurs mutations rejouées actives (§11.2) ;
* `.github/workflows/trainer-smoke.yml` : intact (digest protégé par
  `tests/ci/test_repro_workflow_batch2.py`) ;
* aucune valeur d'audit inventée : les valeurs du §11.4 sont rejouées sur les
  octets servis et portent leur mode de mesure ; les valeurs navigateur non
  observées sont listées au §11.5 comme non mesurées.

### 11.7 Acceptation T3, point par point

| Critère d'acceptation | État au HEAD `c2272bb` |
| --- | --- |
| Les suites statiques rejouées passent au HEAD local (sortie consignée) | ✔ §11.2 — trois suites, exit 0, sorties citées |
| `docs/issue-395-review-inbox-ci-report.md` consigne l'audit mesuré au HEAD exact, **ou** le blocage exact de la mesure locale (commande + erreur) et l'état des suites statiques | ✔ §11.1 (SHA), §11.3 (blocage : 4 commandes + erreurs brutes + repro minimal), §11.4 (audit rejoué sur les octets servis, labellisé) |
| La smoke navigateur 1500x1000 est verte localement au HEAD **ou** le blocage local est documenté, et le run CI de T4 devient la source de vérité | ✔ blocage documenté (§11.3) ; aucune revendication de vert navigateur (§11.5 renvoie le vert à T4) |
| Diff Git non vide au HEAD de la branche #395 (rapport versionné) | ✔ 1 fichier modifié, `docs/issue-395-review-inbox-ci-report.md` (section 11 ajoutée, diff non vide) |

## 12. Verrou statique de la surface de persistance et de ses textes croisés

Task : `backlog-a7j` (branche `n8n/issue-395/task-backlog-a7j`). Cette section
ferme le suivi du §9 : le piège du défaut T1 — un smoke qui attend un texte que
la coque servie n'écrit pas dans l'élément visé — n'était attrapé par **aucun**
contrat statique (`grep PERSIST/localDbGet/Sauvegard/persistPrefs` : 0 résultat
dans `tests/trainer/test_review_inbox_large_list_smoke_contract.py` avant cette
tâche).

### 12.1 HEAD mesuré

Mesure rejouée sur les octets **committés** du HEAD courant ; la mesure
intermédiaire consignée par la tâche a7j (prise sur son parent, avant commit) est
remplacée par celle-ci :

```
$ git rev-parse HEAD
7b418954689e5bae892211d4e30707a2ab44baec
$ git rev-parse origin/n8n/issue-395-restaurer-filtres-resultat-tris-temporels-et-pagin
1050c040a0dfd8d1e9ca113184dc287c12a4f5bd
$ git rev-list --count origin/n8n/issue-395-restaurer-filtres-resultat-tris-temporels-et-pagin..HEAD
4
$ git log --format='%h %s' origin/n8n/issue-395-restaurer-filtres-resultat-tris-temporels-et-pagin..HEAD
7b41895 chore(n8n): task backlog-a7j for issue #395
7363fc0 chore(n8n): task backlog-zid for issue #395
c2272bb chore(n8n): task backlog-hsx for issue #395
c9e03e4 chore(n8n): task backlog-zk0 for issue #395
```

Cette section — les gardes de persistance — est **contenue dans** le commit
`7b41895`, HEAD = `7b41895`, **4 commits** devant `origin/1050c040`.

Cette tâche ne modifie **ni** `site/index.html`, **ni**
`tests/trainer/smoke_review_inbox_large_list.py` (lecture seule : aucune
incohérence réelle n'a été révélée, le smoke et la coque concordent), **ni**
`.github/workflows/trainer-smoke.yml`. Les octets écrits sont le contrat statique
et ce rapport (diff git non vide, §12.5).

### 12.2 Gardes ajoutées (`tests/trainer/test_review_inbox_large_list_smoke_contract.py`)

Trois gardes, dans le style existant (constantes extraites des octets servis,
helper de contrôle, mutations rejouées en mémoire, aucune écriture hors
répertoire temporaire) :

1. **Libellé de la pastille servi == libellé attendu par le smoke.**
   `SERVED_PERSISTENCE_STATUS_RE` *extrait* des octets servis les trois branches
   de `localPersistenceStatus.textContent=error?…:busy?…:"…";`
   (`site/index.html:2546`, dans `persistenceStatus`, `site/index.html:2544-2549`)
   et `check_persistence_surface()` exige
   `smoke.PERSISTENCE_SAVED_LABEL == <3ᵉ branche>` (état ni-erreur ni-busy). Le
   message « Sauvegarde locale automatique active · … » part dans le **frère**
   `#localPersistenceDetail` (`site/index.html:1400`) : il ne peut plus être
   attendu dans la pastille. Un libellé servi renommé fait aussi échouer le garde
   (la déclaration disparue est une erreur explicite, jamais un succès vide).
2. **L'attente des préférences lit la valeur persistée.** Le helper livré
   `_wait_persisted_prefs()` doit appeler le lecteur
   (`await page.evaluate(PERSISTED_PREFS_FN)`), le lecteur doit relire la clé
   `localDbGet('prefs')` — la valeur que `restoreLocalState` relira au
   chargement — et la décision doit porter la valeur persistée
   (`last["stored"]`, `last["sort"] == sort`, `last["result"] == result`) ; la
   pastille ne reste qu'un contrôle de surface
   (`last["chip"].strip() == PERSISTENCE_SAVED_LABEL`). En complément, **aucun**
   `wait_for_function` de la smoke ne peut porter sur le texte de
   `#localPersistenceStatus` : le prédicat insatisfiable du défaut T1 est refusé
   par construction.
3. **Les trois textes croisés assertés par le smoke existent dans les octets
   servis.** `CROSS_TEXTS` relie `(texte servi, fragment asserté, assertion
   livrée)` :

   | Assertion du smoke | Texte servi | Octet servi |
   | --- | --- | --- |
   | `assert f"étape {target['stepIndex'] + 1}" in opened["status"]` | `Décision prioritaire ouverte · étape ${resolved.stepIndex+1}` | `site/index.html:4276` |
   | `assert "introuvable" not in opened["status"]` | `Décision ciblée introuvable dans cette version de la main` | `site/index.html:4277` |
   | `assert "analyse incomplète" in incomplete["status"].casefold()` | `Analyse incomplète · aucune décision comparable à cibler.` | `site/index.html:4286` |

   Le garde vérifie les trois côtés : l'assertion livrée existe dans la smoke, le
   littéral servi existe dans `site/index.html`, et le fragment asserté
   (comparé après `casefold`) est bien contenu dans ce littéral servi — les deux
   textes sont donc *reliés*, pas seulement présents chacun de leur côté.

Extraction servie rejouée (sortie brute) :

```
$ python3 - <<'PY'
import re; from pathlib import Path
index = Path('site/index.html').read_text(encoding='utf-8')
pat = re.compile(r'localPersistenceStatus\.textContent\s*=\s*error\s*\?\s*"([^"]*)"\s*:\s*busy\s*\?\s*"([^"]*)"\s*:\s*"([^"]*)"\s*;')
m = pat.search(index)
print("declaration trouvee:", bool(m)); print("labels servis:", m.groups())
print("ligne servie:", index.splitlines()[2545])
for literal in ("Décision prioritaire ouverte · étape ${resolved.stepIndex+1}",
                "Décision ciblée introuvable dans cette version de la main",
                "Analyse incomplète · aucune décision comparable à cibler."):
    print(f"texte croise servi present: {literal!r} ->", literal in index)
PY
declaration trouvee: True
labels servis: ('Sauvegarde locale en erreur', 'Sauvegarde…', 'Sauvegardé localement')
ligne servie:   localPersistenceStatus.textContent=error?"Sauvegarde locale en erreur":busy?"Sauvegarde…":"Sauvegardé localement";
texte croise servi present: 'Décision prioritaire ouverte · étape ${resolved.stepIndex+1}' -> True
texte croise servi present: 'Décision ciblée introuvable dans cette version de la main' -> True
texte croise servi present: 'Analyse incomplète · aucune décision comparable à cibler.' -> True
```

### 12.3 Non-vacuité : neuf mutations rejouées en mémoire

`check_persistence_surface_non_vacuity()` applique chaque mutation à une copie
**en mémoire** de la smoke ou des octets servis (aucune écriture disque), puis
rejoue `check_persistence_surface()` et exige un `AssertionError` ; la raison
exacte du refus est imprimée par `main()` (préfixe `refusé (backlog-a7j):`).
Aucune assertion de fond n'est neutralisée, aucune constante relâchée.

| Mutation rejouée | Verdict du garde |
| --- | --- |
| libellé servi renommé (`"Sauvegardé localement"` → `"Enregistré localement"`) | refusée — `PERSISTENCE_SAVED_LABEL` ≠ littéral servi |
| `PERSISTENCE_SAVED_LABEL` ramené au message T1 (`Sauvegarde locale automatique active`) | refusée — ce message n'est jamais écrit dans la pastille |
| lecteur des préférences ne relisant plus la clé `prefs` (lecture de la pastille) | refusée — `localDbGet('prefs')` absent du lecteur |
| attente remplacée par le prédicat T1 sur `#localPersistenceStatus` | refusée — plus de lecture de la valeur persistée |
| prédicat de pastille *ajouté* devant la lecture persistée | refusée — aucune attente ne peut porter sur ce texte |
| texte croisé servi retiré (`étape`) | refusée — littéral servi absent |
| texte croisé servi retiré (`introuvable`) | refusée — littéral servi absent |
| texte croisé servi retiré (`Analyse incomplète · aucune décision comparable à cibler.`) | refusée — littéral servi absent |
| assertion croisée retirée de la smoke (`"introuvable" not in opened["status"]`) | refusée — le texte croisé n'est plus asserté |

### 12.4 Sorties brutes au HEAD `7b41895`

`python3 tests/trainer/test_review_inbox_large_list_smoke_contract.py` (exit 0),
rejoué au HEAD courant : les 9 refus `backlog-a7j` (identiques au byte près à la
mesure committée au HEAD précédent `7363fc0` — `diff` des 9 lignes extraites du
rapport committé contre celles du run courant : aucune différence) puis la ligne
finale, copiée **verbatim** :

```
  refusé (backlog-a7j): libellé servi renommé → PERSISTENCE_SAVED_LABEL du smoke doit être le littéral que `persistenceStatus` écrit pour l'état ni-erreur ni-busy (smoke 'Sauvegardé localement' != s
  refusé (backlog-a7j): PERSISTENCE_SAVED_LABEL ramené au message T1 (jamais écrit dans la pastille) → PERSISTENCE_SAVED_LABEL du smoke doit être le littéral que `persistenceStatus` écrit pour l'état ni-erreur ni-busy (smoke 'Sauvegarde locale automatiq
  refusé (backlog-a7j): lecteur ne relisant plus `prefs` → le lecteur de préférences du smoke doit relire `localDbGet('prefs')` — la valeur que `restoreLocalState` relit au chargement ; un texte de `#localPers
  refusé (backlog-a7j): attente remplacée par le prédicat T1 sur la pastille → l'attente des préférences doit lire la valeur persistée (`await page.evaluate(PERSISTED_PREFS_FN)`), pas un texte de pastille
  refusé (backlog-a7j): prédicat de pastille ajouté devant la lecture persistée → ('aucune attente de la smoke ne peut porter sur le texte de `#localPersistenceStatus` (défaut T1 : prédicat insatisfiable)', 'wait_for_function(\n    
  refusé (backlog-a7j): texte croisé servi retiré ('étape') → le texte croisé asserté par la smoke doit rester dans les octets servis: 'Décision prioritaire ouverte · étape ${resolved.stepIndex+1}'
  refusé (backlog-a7j): texte croisé servi retiré ('introuvable') → le texte croisé asserté par la smoke doit rester dans les octets servis: 'Décision ciblée introuvable dans cette version de la main'
  refusé (backlog-a7j): texte croisé servi retiré ('analyse incomplète') → le texte croisé asserté par la smoke doit rester dans les octets servis: 'Analyse incomplète · aucune décision comparable à cibler.'
  refusé (backlog-a7j): assertion croisée retirée de la smoke → la smoke doit continuer d'asserter le texte croisé servi: 'assert "introuvable" not in opened["status"], (target, opened)'
review inbox large list smoke contract checks: OK (32 mains · 5 tris rejoués par le contrat servi · taille de page bornée ≤15 · borne basse mesurée épinglée (10, justification par les hauteurs mesurées rejouée) · pagination Précédent/Suivant épinglée au pager servi (page 1: Précédent désactivé, Suivant actif · assertion inverse rejouée) · peinture lue causalement (1 lecture(s) `document.querySelectorAll('#hhHands .hh-hand').length` dans l'attente · helper rejoué 3 sondages → 7 lignes peintes) · budgets vue/peinture nommés 30000 / 30000 ms (plancher 30000, 20000 refusé · 7 mutations rejouées) · surface de persistance verrouillée (libellé servi 'Sauvegardé localement' == PERSISTENCE_SAVED_LABEL · préférences lues par localDbGet('prefs') · 3 textes croisés servis · 9 mutations rejouées) · fixture=tests/trainer/fixtures/review_inbox_large_list.hand.txt)
```

Les autres commandes exigées (sorties brutes rejouées au HEAD `7b41895`) :

```
$ python3 tests/trainer/test_review_inbox_pagination_contract.py
review inbox pagination contract checks: OK (page window 10–15 measured on the constrained shell, shrink without hidden overflow, bounded pager, filter/sort restart at page 1, selection preserved, pinned page size at 1500x1000 = 10–11 on the served shell with the 32-hand fixture — conservative budget: chrome 403.95px, list 596.05px, row 53.15px, pitch 59.15px; résultats {'WIN': 8, 'LOSS': 8, 'EVEN': 14, 'UNKNOWN': 2} — EVEN (14) multi-pages dans les deux modèles, garde « page 1 == liste filtrée » rejouée)
EXIT=0
$ python3 tests/trainer/test_review_inbox_ui_contract.py
review inbox runtime mirror/UI contract checks: OK
EXIT=0
$ python3 tests/ci/test_repro_workflow_batch2.py
....
----------------------------------------------------------------------
Ran 4 tests in 0.010s

OK
EXIT=0
$ ran=0; fail=0; for t in tests/trainer/test_*.py; do ran=$((ran+1)); if ! python3 "$t" >/dev/null 2>&1; then fail=$((fail+1)); echo "FAIL $t"; fi; done; echo "ran=$ran overall_fail=$fail"
ran=52 overall_fail=0
$ python3 -m pytest tests/trainer/test_review_inbox_pagination_contract.py
/usr/bin/python3: No module named pytest
EXIT=1   # pytest n'est pas installé ici ; les suites sont rejouées fichier par fichier
```

Le balayage `tests/trainer/test_*.py` (52 fichiers) est vert : aucun contrat de
la suite n'est invalidé par l'ajout des gardes.

### 12.5 Ce qui reste NOT_OBSERVED côté CI

Rien n'est revendiqué vert côté navigateur dans cette section. Le verrou ajouté
est **statique** : il prouve que la smoke, la coque servie et l'attente de
persistance ne peuvent plus diverger de texte, mais il ne remplace pas le run
navigateur. Restent `NOT_OBSERVED` ici, portés par le job `browser-smoke`
(`python3 tests/trainer/smoke_trainer.py`, qui exécute
`smoke_review_inbox_large_list.py` via `DRIVER_SMOKES`) :

```
audit["prefs_persisted"]        # la boucle réelle localDbGet("prefs") + pastille « Sauvegardé localement » au runtime
audit["reload"]                 # tri/filtre effectivement restaurés après page.reload()
audit["deep_link"]              # statut replayer réellement ouvert sur « étape N », sans « introuvable »
audit["no_decision"]            # « Analyse incomplète » réellement affichée pour la main sans décision
audit["tab_click_paints"] etc.  # cf. §11.5
```

Autrement dit : le smoke navigateur 1500x1000 n'est **pas** exécuté ici (sandbox
sans `AF_INET`, cf. §11.3), et cette tâche ne l'affirme pas. Ce qui est mesuré
ici est le contrat statique ci-dessus, rejoué sur les octets committés du HEAD
`7b41895`, mutations en mémoire comprises.

Diff git de la tâche : 2 fichiers (`tests/trainer/test_review_inbox_large_list_smoke_contract.py`,
`docs/issue-395-review-inbox-ci-report.md`), `site/index.html`,
`tests/trainer/smoke_review_inbox_large_list.py` et
`.github/workflows/trainer-smoke.yml` inchangés.

### 12.6 Re-vérification des jetons croisés au HEAD `7b41895` (octets committés)

Contrôle refait sur les **octets committés** (`git grep … HEAD -- <fichier>`,
donc ni worktree orphelin ni copie locale), HEAD = `7b41895`. Sorties **brutes** :

```
$ git grep -n -F -e 'localPersistenceStatus.textContent=error' -e 'localPersistenceDetail.textContent' -e 'Sauvegarde locale automatique active' HEAD -- site/index.html
HEAD:site/index.html:2546:  localPersistenceStatus.textContent=error?"Sauvegarde locale en erreur":busy?"Sauvegarde…":"Sauvegardé localement";
HEAD:site/index.html:2548:  if(localPersistenceDetail) localPersistenceDetail.textContent=`${message||"Sauvegarde locale active."} · Vos données restent enregistrées uniquement dans ce navigateur.`;
HEAD:site/index.html:2591:    if(localPersistenceDetail) localPersistenceDetail.textContent="Toutes les données enregistrées par l’application dans ce navigateur ont été effacées.";
HEAD:site/index.html:2624:      persistenceStatus("Sauvegarde locale automatique active · fichiers et main sélectionnée seront restaurés au prochain lancement.");

$ git grep -n -F -e 'PERSISTENCE_SAVED_LABEL' -e "localDbGet('prefs')" HEAD -- tests/trainer/smoke_review_inbox_large_list.py
HEAD:tests/trainer/smoke_review_inbox_large_list.py:174:PERSISTENCE_SAVED_LABEL = "Sauvegardé localement"
HEAD:tests/trainer/smoke_review_inbox_large_list.py:361:  const prefs=await localDbGet('prefs').catch(()=>null);
HEAD:tests/trainer/smoke_review_inbox_large_list.py:629:            and last["chip"].strip() == PERSISTENCE_SAVED_LABEL

$ git grep -n -F -e 'Décision prioritaire ouverte' -e 'Décision ciblée introuvable' -e 'Analyse incomplète · aucune décision comparable à cibler.' HEAD -- site/index.html
HEAD:site/index.html:4276:      ?`Décision prioritaire ouverte · étape ${resolved.stepIndex+1}`
HEAD:site/index.html:4277:      :"Décision ciblée introuvable dans cette version de la main · aucune autre décision n’a été sélectionnée.";
HEAD:site/index.html:4286:    replayerExportStatus.textContent="Analyse incomplète · aucune décision comparable à cibler.";

$ git grep -n -F -e 'assert f"étape {target' -e 'assert "introuvable" not in' -e 'assert "analyse incomplète" in' HEAD -- tests/trainer/smoke_review_inbox_large_list.py
HEAD:tests/trainer/smoke_review_inbox_large_list.py:998:                assert f"étape {target['stepIndex'] + 1}" in opened["status"], (target, opened)
HEAD:tests/trainer/smoke_review_inbox_large_list.py:999:                assert "introuvable" not in opened["status"], (target, opened)
HEAD:tests/trainer/smoke_review_inbox_large_list.py:1074:                assert "analyse incomplète" in incomplete["status"].casefold(), (no_decision, incomplete)
```

Lecture de ces sorties, jeton par jeton :

| Jeton exigé | Preuve au HEAD `7b41895` |
| --- | --- |
| littéral servi « Sauvegardé localement » sur la pastille `#localPersistenceStatus` | `site/index.html:2546` (3ᵉ branche de `error?…:busy?…:"…"`) |
| message « Sauvegarde locale automatique active… » **consommé** par `#localPersistenceDetail` | produit en `site/index.html:2624`, consommé en `site/index.html:2548` (`message` → `localPersistenceDetail.textContent`) ; la pastille `:2546` ne reçoit **jamais** ce message |
| `PERSISTENCE_SAVED_LABEL` dans la smoke | `tests/trainer/smoke_review_inbox_large_list.py:174` (valeur `"Sauvegardé localement"`, identique au littéral servi) |
| `localDbGet('prefs')` dans la smoke | `tests/trainer/smoke_review_inbox_large_list.py:361` (lecteur des préférences relu au reload) |
| deep-link « étape N » | servi `site/index.html:4276`, asserté smoke `…:998` |
| deep-link « introuvable » | servi `site/index.html:4277`, asserté par l'**absence** smoke `…:999` |
| « Analyse incomplète · aucune décision comparable à cibler. » | servi `site/index.html:4286`, asserté smoke `…:1074` (`"analyse incomplète" in … .casefold()`) |

Le bornage (≤15, plancher 30000) et la fixture 32 mains / filtre `EVEN` (14 mains)
restent ceux des §12.2–§12.4 : aucun d'eux n'est relâché par cette consolidation.

## 13. T4 — push du HEAD corrigé, run CI `browser-smoke`, PR #417

Task d'origine : `backlog-9i9` (worktree orphelin `tasks/task-backlog-9i9`,
branche `n8n/issue-395/task-backlog-9i9`, HEAD à sa mesure : `7363fc0`). Dans ce
worktree, cette narration avait été écrite comme une **seconde section numérotée
« 12 »**, ce qui aurait produit deux §12 ; elle est ici renumérotée **§13**
pour lever la collision (consolidation `backlog-ph4`). La §12 reste « Verrou
statique de la surface de persistance et de ses textes croisés » (committée dans
`7b41895`).

### 13.1 État au moment de la rédaction initiale (worktree 9i9, périmé)

Relevé du 2026-09-25T10:25Z dans `tasks/task-backlog-9i9` :

```
$ git rev-parse HEAD
7363fc09aea97bb13f6d08233c0ca60c1a6b0379
$ git branch --show-current
n8n/issue-395/task-backlog-9i9
$ git status --porcelain          # worktree propre (aucune sortie)
```

Cet état est **périmé** : le worktree 9i9 ne voyait alors que **trois** commits
(`c9e03e4`, `c2272bb`, `7363fc0`) devant `origin/1050c040`, car `7363fc0` était
son HEAD. Il manquait `7b41895`, committé depuis (§13.2).

### 13.2 État courant (ce worktree, HEAD `7b41895`)

```
$ git rev-parse HEAD
7b418954689e5bae892211d4e30707a2ab44baec
$ git rev-parse origin/n8n/issue-395-restaurer-filtres-resultat-tris-temporels-et-pagin
1050c040a0dfd8d1e9ca113184dc287c12a4f5bd
$ git rev-list --count origin/n8n/issue-395-restaurer-filtres-resultat-tris-temporels-et-pagin..HEAD
4
$ git log --format='%h %s' origin/n8n/issue-395-restaurer-filtres-resultat-tris-temporels-et-pagin..HEAD
7b41895 chore(n8n): task backlog-a7j for issue #395
7363fc0 chore(n8n): task backlog-zid for issue #395
c2272bb chore(n8n): task backlog-hsx for issue #395
c9e03e4 chore(n8n): task backlog-zk0 for issue #395
```

| Élément | Valeur observée |
| --- | --- |
| HEAD courant | `7b418954689e5bae892211d4e30707a2ab44baec` (`7b41895`) |
| Réf de suivi `origin/n8n/issue-395-restaurer-…` | `1050c040a0dfd8d1e9ca113184dc287c12a4f5bd` (`1050c040`) |
| Commits d'avance | **4** — `c9e03e4` (zk0), `c2272bb` (hsx), `7363fc0` (zid), `7b41895` (a7j) |

Précision de méthode : la valeur `origin/…` est la **référence locale de
suivi**, rafraîchie par le dernier `fetch` réussi (`FETCH_HEAD` horodaté
2026-09-25 09:25 +0200). Une interrogation **en direct** du dépôt distant est
impossible depuis ce bac à sable (§13.5) ; elle n'est donc pas revendiquée.

### 13.3 Périmètre en avance et fichiers gelés

```
$ git diff --name-only origin/n8n/issue-395-restaurer-filtres-resultat-tris-temporels-et-pagin..HEAD
docs/issue-395-review-inbox-ci-report.md
tests/trainer/smoke_review_inbox_large_list.py
tests/trainer/test_review_inbox_large_list_smoke_contract.py

$ git diff --stat origin/n8n/issue-395-restaurer-filtres-resultat-tris-temporels-et-pagin..HEAD
 docs/issue-395-review-inbox-ci-report.md           | 770 ++++++++++++++++++++
 tests/trainer/smoke_review_inbox_large_list.py     | 185 ++++-
 .../test_review_inbox_large_list_smoke_contract.py | 779 +++++++++++++++++++++
 3 files changed, 1716 insertions(+), 18 deletions(-)

$ git diff --name-only origin/n8n/issue-395-restaurer-filtres-resultat-tris-temporels-et-pagin..HEAD -- .github
(aucune sortie)

$ git hash-object .github/workflows/trainer-smoke.yml
5e168acf6474c5351a46af8da2f85b58bdb581ce
$ git rev-parse origin/n8n/issue-395-restaurer-filtres-resultat-tris-temporels-et-pagin:.github/workflows/trainer-smoke.yml
5e168acf6474c5351a46af8da2f85b58bdb581ce

$ git ls-files contracts/orchestrator tools/validate_orchestrator_contract.py undefined
(aucune sortie)
```

Le workflow gelé est **byte-identique** à `origin` et **aucun** chemin #392 n'est
suivi dans ce worktree.

Les nombres ci-dessus sont ceux de `git diff <réf-suivi>..HEAD`, donc du **HEAD committé**
`7b41895` ; ils ne comptent pas l'édition du présent rapport par la consolidation
en cours (le fichier rapport resterait le seul à croître, les deux autres
fichiers étant inchangés).

### 13.4 Push : NON effectué (aucune tentative depuis ce worktree)

Le push **n'a pas été effectué**, et il n'a **pas** été tenté depuis ce worktree
de consolidation : la consigne du worker est de ne ni commit, ni push, ni rebase —
le push est laissé à l'orchestrateur. Le worktree `task-backlog-9i9` avait, lui,
tenté le push par les trois routes disponibles et consigné ces erreurs git
brutes (mesure 9i9 — HEAD d'alors `7363fc0`, état périmé — reproduites telles
quelles) :

**(a) configuration ssh système (route par défaut de `origin`, `git@github.com:`)**

```
$ git push origin n8n/issue-395-restaurer-filtres-resultat-tris-temporels-et-pagin
Bad owner or permissions on /etc/ssh/ssh_config.d/20-systemd-ssh-proxy.conf
fatal: Could not read from remote repository.

Please make sure you have the correct access rights
and the repository exists.
EXIT=128
```

**(b) client ssh relancé sans le fichier de configuration fautif**

```
$ GIT_SSH_COMMAND="ssh -F /dev/null" git push origin n8n/issue-395-restaurer-filtres-resultat-tris-temporels-et-pagin
ssh: Could not resolve hostname github.com: Temporary failure in name resolution
fatal: Could not read from remote repository.

Please make sure you have the correct access rights
and the repository exists.
EXIT=128
```

**(c) transport HTTPS avec le helper d'identifiants `gh` déjà configuré**

```
$ git -c url."https://github.com/".insteadOf="git@github.com:" push origin n8n/issue-395-restaurer-filtres-resultat-tris-temporels-et-pagin
fatal: unable to access 'https://github.com/aradenac/poker-engine.git/': Could not resolve host: github.com
EXIT=128
```

### 13.5 Cause racine des deux couches (bac à sable), re-vérifiée ici

La cause est **indépendante du dépôt** : c'est le bac à sable du worker. Le
worktree 9i9 l'avait établi par les relevés suivants (mesure 9i9) :

```
$ python3 -c "import socket; socket.socket()"
socket() failed: PermissionError [Errno 1] Operation not permitted

$ getent hosts github.com
(aucune sortie)  rc=2
$ timeout 15 curl -sS -o /dev/null -w '%{http_code}\n' https://github.com
curl: (6) Could not resolve host: github.com
000  rc=6
$ timeout 8 bash -c 'exec 3<>/dev/tcp/140.82.121.4/443 && echo TCP_OK'
bash: socket: Operation not permitted
bash: line 1: /dev/tcp/140.82.121.4/443: Operation not permitted
rc=1
$ sudo -n true
sudo: The "no new privileges" flag is set, which prevents sudo from running as root.
rc=1
```

Re-vérifié dans ce worktree de consolidation (sorties brutes) :

```
$ python3 -c "import socket; socket.socket()"
Traceback (most recent call last):
  File "<string>", line 1, in <module>
    import socket; socket.socket()
                   ~~~~~~~~~~~~~^^
  File "/usr/lib/python3.14/socket.py", line 236, in __init__
    _socket.socket.__init__(self, family, type, proto, fileno)
PermissionError: [Errno 1] Operation not permitted
EXIT=1
$ getent hosts github.com
(aucune sortie)
getent_EXIT=2
```

Deux couches : (1) le client `ssh` refuse de charger sa configuration système
(`Bad owner or permissions` sur
`/etc/ssh/ssh_config.d/20-systemd-ssh-proxy.conf`) — le contournement
`ssh -F /dev/null` isole cette cause ; (2) une fois cette couche contournée,
l'appel échoue à la résolution DNS, la cause profonde étant le refus de créer un
socket (`EPERM` sur `socket()`). Conséquence : **aucune** connexion sortante —
donc **aucun** push, **aucun** run de workflow déclenché, **aucun** appel à
l'API GitHub (ni lecture ni écriture de la PR #417).

### 13.6 Ce qui n'a donc PAS été observé (et n'est revendiqué nulle part)

| Élément attendu par l'acceptance T4 | État réel | Motif |
| --- | --- | --- |
| HEAD corrigé présent sur origin | **NON POUSSÉ** | aucune tentative depuis ce worktree ; tentatives 9i9 en échec (§13.4) |
| URL du run CI `browser-smoke` au HEAD corrigé | **NON OBTENUE** (`NOT_OBSERVED`) | aucun push → aucun run déclenché (§13.5) |
| Statut du step « Exercise Training view » | **NON OBSERVÉ** | idem ; **aucun** statut n'est écrit ici, ni vert ni rouge |
| Sortie d'audit JSON du nouveau smoke (run navigateur) | **NON OBSERVÉE** | §11.3 (sandbox sans `AF_INET`) et §12.5 la portent au run CI |
| PR #417 actualisée (corps + statut) | **NON ACTUALISÉE** (`NOT_UPDATED`) | aucune écriture API ; la tête distante **connue** reste `1050c040` (réf de suivi, dernier fetch 2026-09-25 09:25 +0200) |
| PR dupliquée créée | **AUCUNE** | aucune écriture API n'a été tentée |

Conséquence explicite : le job `browser-smoke`
(`.github/workflows/trainer-smoke.yml`, step « Exercise Training view ») reste
**rouge au tip poussé `1050c040`** tant que le HEAD corrigé `7b41895` n'est pas
poussé puis observé. Aucun `PASS` de job n'est écrit dans ce rapport, et
`browser-smoke` reste **`NOT_OBSERVED`**.

### 13.7 Suites statiques rejouées au HEAD `7b41895` (sorties brutes)

```
$ python3 tests/trainer/test_review_inbox_large_list_smoke_contract.py   # sortie complète en §12.4
review inbox large list smoke contract checks: OK (32 mains · 5 tris rejoués par le contrat servi · taille de page bornée ≤15 · borne basse mesurée épinglée (10, justification par les hauteurs mesurées rejouée) · pagination Précédent/Suivant épinglée au pager servi (page 1: Précédent désactivé, Suivant actif · assertion inverse rejouée) · peinture lue causalement (1 lecture(s) `document.querySelectorAll('#hhHands .hh-hand').length` dans l'attente · helper rejoué 3 sondages → 7 lignes peintes) · budgets vue/peinture nommés 30000 / 30000 ms (plancher 30000, 20000 refusé · 7 mutations rejouées) · surface de persistance verrouillée (libellé servi 'Sauvegardé localement' == PERSISTENCE_SAVED_LABEL · préférences lues par localDbGet('prefs') · 3 textes croisés servis · 9 mutations rejouées) · fixture=tests/trainer/fixtures/review_inbox_large_list.hand.txt)
EXIT=0
$ python3 tests/trainer/test_review_inbox_pagination_contract.py
review inbox pagination contract checks: OK (page window 10–15 measured on the constrained shell, shrink without hidden overflow, bounded pager, filter/sort restart at page 1, selection preserved, pinned page size at 1500x1000 = 10–11 on the served shell with the 32-hand fixture — conservative budget: chrome 403.95px, list 596.05px, row 53.15px, pitch 59.15px; résultats {'WIN': 8, 'LOSS': 8, 'EVEN': 14, 'UNKNOWN': 2} — EVEN (14) multi-pages dans les deux modèles, garde « page 1 == liste filtrée » rejouée)
EXIT=0
$ ran=0; fail=0; for t in tests/trainer/test_*.py; do ran=$((ran+1)); if ! python3 "$t" >/dev/null 2>&1; then fail=$((fail+1)); echo "FAIL $t"; fi; done; echo "ran=$ran overall_fail=$fail"
ran=52 overall_fail=0
$ python3 tests/trainer/test_review_inbox_ui_contract.py
review inbox runtime mirror/UI contract checks: OK
EXIT=0
$ python3 tests/ci/test_repro_workflow_batch2.py
....
----------------------------------------------------------------------
Ran 4 tests in 0.010s

OK
EXIT=0
```

`python3 -m pytest` n'existe pas dans cet environnement (`/usr/bin/python3: No
module named pytest`, exit 1) : les suites sont donc rejouées **comme le fait le
job CI**, fichier par fichier. Le balayage `tests/trainer/test_*.py` (52 fichiers)
sort `overall_fail=0` ; **aucun** de ces résultats n'est une observation
navigateur, et aucun n'est présenté comme un run CI.

### 13.8 Reliquat — commandes exactes à exécuter hors bac à sable

```
# 1) pousser le HEAD corrigé (7b41895, 4 commits devant origin/1050c040)
git push origin 7b418954689e5bae892211d4e30707a2ab44baec:refs/heads/n8n/issue-395-restaurer-filtres-resultat-tris-temporels-et-pagin

# 2) attendre le run déclenché par ce push et relever l'URL + le statut
gh run list --workflow trainer-smoke.yml --branch n8n/issue-395-restaurer-filtres-resultat-tris-temporels-et-pagin --limit 5
gh run watch <run-id>
gh run view <run-id> --json headSha,conclusion,jobs   # exiger le step « Exercise Training view » et l'audit JSON

# 3) actualiser la PR existante #417 (NE PAS en créer une seconde)
gh pr view 417 --json number,headRefOid,state,url
gh pr edit 417 --body-file <corps ci-dessous>

# 4) compléter §13.6 avec le SHA poussé, l'URL du run et le statut observé
```

Corps proposé pour la PR #417 (à publier **après** le push, avec le SHA réellement
poussé ; ce texte n'a **pas** été publié depuis ce worker) :

```markdown
Corrige #395.

Le job `browser-smoke` était rouge au HEAD `1050c04` : le step « Exercise Training
view » mourait sur `Page.wait_for_function: Timeout 20000ms exceeded`.

Correction demandée par la revue humaine (timeout de peinture du smoke) :
- la cause déterministe est la section « préférences » du smoke, qui attendait un
  texte que la coque servie n'écrit jamais dans `#localPersistenceStatus` (le
  message est dans `#localPersistenceDetail`, élément frère) ; l'attente lit
  désormais ce que le reload relit réellement ;
- la peinture de `#hhHands .hh-hand` est lue **causalement** (attente sur la même
  expression + lecture atomique inject/repaint) au lieu d'être garantie par un
  délai fixe, et plus aucune attente de vue/peinture ne reste à 20 s ;
- le bornage (`assert_bounded`, `assert_page_size_target`, `assert_pagination`),
  la fixture 32 mains, le filtre EVEN (14 mains) et la sémantique du pagineur
  servi sont inchangés ; `.github/workflows/trainer-smoke.yml` est intact.

HEAD poussé : `<sha>` (4 commits : `c9e03e4`, `c2272bb`, `7363fc0`, `7b41895`).
Suites statiques au HEAD : `tests/trainer/test_*.py` → 52/52 sans échec, `tests/ci/test_repro_workflow_batch2.py` → OK.
Run `browser-smoke` au HEAD poussé : `<url>` — statut observé : `<conclusion>`.
Rapport : `docs/issue-395-review-inbox-ci-report.md`.
```

### 13.9 Acceptation T4, point par point

| Critère d'acceptation | État réel |
| --- | --- |
| Le HEAD corrigé est présent sur origin **ou** l'erreur git exacte du push est consignée | ✔ alternative 2 — erreurs git brutes 9i9 + exits (§13.4), causes vérifiées (§13.5) |
| Le run CI `browser-smoke` au HEAD poussé est identifié (URL + statut, dont le step « Exercise Training view ») et consigné sans sur-déclaration | ✖ **non observable** — aucun run déclenché ; consigné `NOT_OBSERVED` sans aucun statut inventé (§13.6) ; reliquat commandé (§13.8) |
| La PR #417 est actualisée (corps + statut) et aucun doublon n'a été créé | Partiel : **aucun doublon créé** (aucune écriture API) ✔ ; actualisation **impossible** depuis ce worker ✖ ; la tête distante connue reste `1050c040`, corps proposé prêt à publier (§13.8) |
| Diff Git non vide au HEAD de la branche #395 (rapport mis à jour) | ✔ 1 fichier modifié — `docs/issue-395-review-inbox-ci-report.md` (§13 ajoutée, diff non vide) |

Jetons de synthèse T4 :

```
t4_push: NOT_PUSHED__NO_ATTEMPT_FROM_CONSOLIDATION_WORKTREE
t4_head_to_push: 7b418954689e5bae892211d4e30707a2ab44baec
t4_remote_tracking_tip: 1050c040a0dfd8d1e9ca113184dc287c12a4f5bd   # réf locale, dernier fetch 2026-09-25 09:25 +0200
t4_commits_ahead: 4                                                 # c9e03e4, c2272bb, 7363fc0, 7b41895
t4_browser_smoke_run: NOT_OBSERVED
t4_browser_smoke_step_exercise_training_view: NOT_OBSERVED
t4_pr_417_updated: NO
t4_pr_417_duplicate_created: NO
t4_trainer_smoke_workflow_modified: NO   # blob 5e168acf == origin
t4_static_contracts: PASS_52_OF_52
```

## 14. Clôture — poussé, observé, vert (revue humaine finale)

Cette section est écrite par la **revue humaine finale** (accès direct à
l'API GitHub réelle via `gh`, pas depuis le sandbox sans accès réseau qui a
produit tous les `NOT_OBSERVED` ci-dessus). Elle consigne le premier run réel
du job gelé sur des octets réellement poussés — y compris le commit
`097768c` (task `backlog-ph4`) qui a produit ce document lui-même.

### 14.1 Le push réalisé

```
$ git push origin HEAD:n8n/issue-395-restaurer-filtres-resultat-tris-temporels-et-pagin
   1050c04..097768c
$ git rev-parse HEAD
097768c5e4801dc886ef22a4c3f34bed0aa1016c
```

### 14.2 Les jobs gelés, verts sur ce head_sha

| Workflow | Job | Run | Conclusion |
| --- | --- | --- | --- |
| `trainer-smoke.yml` (« Validate interactive trainer ») | `static-contract` | run `36137534018`, job `108079116399` | **`success`** |
| `trainer-smoke.yml` (« Validate interactive trainer ») | `browser-smoke` | run `36137534018`, job `108079394585` | **`success`** (1m16s ; étape « Exercise Training view » exécute `smoke_review_inbox_large_list.py` sans `AssertionError` ni `Timeout`) |
| `trainer-smoke.yml` (« Validate interactive trainer ») | `static-contract` | run `36137540210`, job `108079137497` | **`success`** |
| `trainer-smoke.yml` (« Validate interactive trainer ») | `browser-smoke` | run `36137540210`, job `108079394468` | **`success`** |

Chaque workflow gelé a tourné deux fois sur ce head_sha ; les deux
occurrences sont vertes. Les trois autres `browser-smoke` (Hero range
editor/compliance, sequential arena) sont également `success`.

### 14.3 Tous les checks requis de la PR #417

```
$ gh pr checks 417
```

5/5 `browser-smoke` = `pass`, tous les `contract`/`static-contract` = `pass`,
`deterministic-core` = `pass`, `repro-environment / guard` = `pass`,
`validate` = `pass`, `Project state consistency` = `pass`, `Workers Builds`
(Cloudflare) = `pass`. Zéro check `pending`, zéro `failure`. `gh pr view 417`
rapporte `mergeStateStatus: CLEAN`, `mergeable: MERGEABLE`.

### 14.4 Jetons T4 — bascule finale

| Jeton | Valeur finale | Base |
| --- | --- | --- |
| `t4_push` | **`PUSHED`** (bascule depuis `NOT_PUSHED...`) | § 14.1 — push réel, réponse `1050c04..097768c` |
| `t4_browser_smoke_run` | **`OBSERVED — success`** (bascule depuis `NOT_OBSERVED`) | § 14.2, runs `36137534018` / `36137540210` |
| `t4_browser_smoke_step_exercise_training_view` | **`OBSERVED — success, no AssertionError`** | § 14.2 |
| `t4_pr_417_updated` | **`N/A — merge directement décidé, voir clôture de l'issue`** | § 14.3 |

Ces jetons n'avaient été basculés par aucune section précédente (§ 1 à § 13
les documentent comme `NOT_OBSERVED`, faute d'accès réseau depuis le
sandbox) : c'est cette section, sur la base d'un run réel au head_sha
poussé, qui les fait passer. Aucune mesure locale ni dérivation statique ne
s'y substitue.

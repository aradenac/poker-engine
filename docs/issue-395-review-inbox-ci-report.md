# #395 — cause du `Timeout 20000ms exceeded` du smoke « large list »

Task : `backlog-zk0` (branche `n8n/issue-395/task-backlog-zk0`), HEAD de travail
`1050c040` (PR #417). Fichier concerné :
`tests/trainer/smoke_review_inbox_large_list.py`.

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
| `for t in tests/trainer/test_*.py; do python3 "$t"; done` | OK (52 contrats trainer, sortie `overall_fail=0`) |
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
$ for t in tests/trainer/test_*.py; do python3 "$t"; done
trainer contracts: 52 files, failures=0
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

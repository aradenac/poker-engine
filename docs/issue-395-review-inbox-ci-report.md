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

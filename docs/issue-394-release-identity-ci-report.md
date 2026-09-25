---
schema: poker-issue-394-release-identity-report/v1
issue: 394
task: task-backlog-hm5
report_date: 2026-09-25
status: PASS
head_sha: af95f63b27c01aa9d4f41e9eb1da27d7cc8e14b1
branch: n8n/issue-394/task-backlog-hm5
merged: false
pushed: false
ci_green: NOT_OBSERVED
release_anchor_check: PASS
release_anchor_delta: SITE_TRAINER_CSS_COMMENT_AND_ANCHOR_LINE_ONLY
index_blob_matches_head: PASS
stale_claims_guard: PASS
patch_idempotence: PASS
static_contracts: PASS
javascript_syntax: PASS
browser_smoke_local: FAILED_EXIT_1_PLAYWRIGHT_UNAVAILABLE_IN_SANDBOX
browser_smoke_evidence: "docs/desktop-modes-fit-evidence.md"
browser_smoke_authority: "le job gelé browser-smoke de .github/workflows/trainer-smoke.yml dans la PR reste l'autorité pour le smoke lui-même"
red_workflows: []
report_self_delta: "le head_sha consigné est le HEAD RÉEL du worktree au moment de l'écriture, af95f63b27c01aa9d4f41e9eb1da27d7cc8e14b1, relevé juste avant l'écriture de ce fichier ; cette task est le dernier écrivain de site/** (commentaire de portée dans site/trainer.css + ancre site/RELEASE.json régénérée), et le rapport est réécrit APRÈS ces écritures ; il ne peut pas citer le SHA de son propre commit (auto-référence) et n'affirme aucun merge, aucun push et aucun état vert de CI non observé ; l'orchestrateur gère le commit et la PR"
---

# Rapport PASS/FAIL — ancre release, boucle complète, garde anti-claims et rapport CI (#394, task-backlog-hm5)

Ce rapport matérialise la clôture demandée par `task-backlog-hm5` (T4) :
**garde anti-claims périmés**, **régénération et vérification de l'ancre de
release** après les écritures dans `site/**`, **boucle complète des contrats
statiques** (`for test in tests/trainer/test_*.py`, comme le job
`static-contract`), `node --check site/trainer.js`, **idempotence** de
`tools/patches/apply_trainer_mvp.py` avec unicité des marqueurs du patch, et
**réécriture de ce rapport au HEAD réel**.

**Aucun merge**, **aucun push**, **aucun rebase**, **aucun commit**, **aucun
`git add`** : le worker ne commit ni ne pousse, l'orchestrateur prend le relais
après review. **Aucun état vert de CI n'est affirmé** : la CI n'a pas été
observée depuis ce sandbox (réseau coupé, § Smoke navigateur).

## Statut

| Champ | Valeur |
| --- | --- |
| Statut global | **PASS** |
| HEAD réel du worktree | `af95f63b27c01aa9d4f41e9eb1da27d7cc8e14b1` |
| Sujet du HEAD | `chore(n8n): task backlog-31r for issue #394` |
| Branche de travail | `n8n/issue-394/task-backlog-hm5` |
| Dernier écrivain **commité** de `site/**` | `386f9d9` (task backlog-arq) |
| Dernier écrivain de `site/**` (cette task, non commité) | `site/trainer.css` (commentaire de portée) + `site/RELEASE.json` (ancre régénérée) |
| Merge effectué | **non** |
| Push effectué | **non** |
| CI distante observée | **non** (`ci_green: NOT_OBSERVED`) |
| Garde anti-claims périmés | **PASS** (`EXIT=0`, 1051 fichiers versionnés scannés, 3 claims, self-test non vacueux) |
| `python3 tools/write_site_release.py` (régénération) | **PASS** (`EXIT=0`) |
| `python3 tools/write_site_release.py --check` | **PASS** (`EXIT=0`) |
| `git rev-parse HEAD:site/index.html` vs `site/RELEASE.json` | **PASS** (égalité stricte) |
| `tools/patches/apply_trainer_mvp.py` | **PASS** (idempotent, sha256 inchangés) |
| Marqueurs `id=trainerOpenBtn` / `id=trainerNavLink` | **PASS** (chacun présent exactement une fois) |
| Boucle `for test in tests/trainer/test_*.py` | **PASS** (48/48, `0` échec) |
| `node --check site/trainer.js` | **PASS** (`EXIT=0`) |
| Smoke navigateur des modes | **NON REJOUABLE LOCALEMENT** — les deux commandes exigées ont été lancées au HEAD final et ont échoué (`EXIT=1`, `playwright` indisponible) ; la preuve de fit est `docs/desktop-modes-fit-evidence.md` ; **le job gelé `browser-smoke` de la PR reste l'autorité** |
| Delta Git de la tâche | **non vide** : ce rapport, le garde-fou, son branchement et l'ancre |
| `.github/workflows/**` / `.github/actions/**` | **inchangé** (`git diff --stat HEAD -- .github` vide) |
| Modèle / science / équité | **inchangé** (aucun fichier de ces familles dans le diff) |

### Self-delta (explicite)

- Le HEAD réel du worktree **au moment de l'écriture de ce rapport** est
  **`af95f63b27c01aa9d4f41e9eb1da27d7cc8e14b1`**
  (`chore(n8n): task backlog-31r for issue #394`), tête de la branche
  `n8n/issue-394/task-backlog-hm5`. Il a été relevé juste avant l'écriture de ce
  fichier (`git rev-parse HEAD`), et c'est **la valeur qui figure dans l'en-tête
  `head_sha` ci-dessus**.
- **Cette task est le dernier écrivain de `site/**`** : elle corrige un
  commentaire de portée devenu faux dans `site/trainer.css` (voir § 1) et
  **régénère** en conséquence `site/RELEASE.json`. Le rapport est donc rédigé
  **après** ces écritures, et toutes les valeurs d'ancre ci-dessous sont
  postérieures au dernier écrivain de `site/**`.
- **Le delta versionné de cette task** est : ce rapport, `site/trainer.css`,
  `site/RELEASE.json`, `tools/check_issue394_stale_claims.py` (nouveau garde-fou)
  et `tests/trainer/test_product_architecture_contract.py` (branchement du
  garde-fou dans la boucle gelée). La somme de contrôle de ce fichier ne peut pas
  être citée par lui-même (auto-référence) ; le worker ne commit pas,
  l'orchestrateur gère le commit et la PR.
- Ce rapport **n'affirme ni merge, ni push, ni état vert de CI** ; il n'affirme
  rien sur le run CI distant, qui n'a pas été observé.

## (1) Garde anti-claims périmés — `tools/check_issue394_stale_claims.py`

Le contrat statique
**`tools/check_issue394_stale_claims.py`** (`poker-issue-394-stale-claims-guard/v1`)
scanne **tous** les fichiers versionnés (liste `git ls-files`, extensions
textuelles, payloads > 1 Mio ignorés) et échoue sur le premier fichier qui
réaffirme l'un des trois claims rejetés en review :

| Claim (identifiant) | Affirmation périmée | Ce que le code dit à la place |
| --- | --- | --- |
| `nav-entry-points-to-standalone-editor` | l'entrée Strategy de `#quickNav` porterait le lien réel vers l'éditeur autonome `./hero-ranges.html` | `site/index.html` : l'entrée est `<a href="#strategyPage" data-product-domain="strategy">Strategy</a>` (navigation **in-app**) ; les liens réels `./hero-ranges.html` sont la carte de mode de l'Accueil, `#heroRangesOpenBtn` et `#strategyPageEditorLink` |
| `narrow-rendering-out-of-scope` | le rendu `<901px` serait non concerné par la règle de coque | `site/index.html` : seule la règle `100dvh` / pas de scroll global est **desktop only** ; le pattern sous-vue / onglet / panneau est **global** (règles de base hors media query, `activateAppSubview` sans garde de largeur) |
| `fit-measured-by-out-of-repo-harness` | la mesure de fit reposerait sur un outillage local non versionné, extérieur au dépôt | `tests/trainer/smoke_modes_desktop.py` porte la mesure **dans le dépôt**, son option `--report` matérialise le rapport JSON, le job gelé `browser-smoke` est la seule autorité de verdict, et `docs/desktop-modes-fit-evidence.md` ne cite aucun chemin hors du dépôt |

Chaque claim est portée par (a) des motifs **affirmatifs** — les formulations
rejetées elles-mêmes, normalisées en espaces — et (b) un **bloc structurel** qui
prouve que l'implémentation contredit encore le claim (entrée `#quickNav`,
portée du pattern sous-vue + `APP_ALLOWED_SCROLL_ZONES`, propriété in-repo de la
mesure de fit). Le garde-fou n'est donc pas vacueux : il échoue **aussi** si la
contradiction disparaît de l'implémentation.

Seul ce fichier de garde est exclu du scan : il porte nécessairement les
formulations rejetées comme entrées de détection. Tout le reste de ce que Git
versionne est scanné.

```
$ python3 tools/check_issue394_stale_claims.py
issue-394 stale claims guard: PASS (1051 versioned text files scanned, 3 claims)
EXIT=0
```

Preuve de non-vacuité (`--self-test`) : chaque détecteur est rejoué sur la
révision historique qui portait le claim, par `git show <rev>:<chemin>` :

```
$ python3 tools/check_issue394_stale_claims.py --self-test
self-test nav-entry-points-to-standalone-editor: 3 detector(s) matched a6cefc7:docs/ux-desktop-view-shell.md
self-test narrow-rendering-out-of-scope: 1 detector(s) matched dda6f60:site/index.html
self-test narrow-rendering-out-of-scope: 1 detector(s) matched c3da3fe:site/trainer.css
self-test fit-measured-by-out-of-repo-harness: 4 detector(s) matched c83c72f:docs/desktop-modes-fit-evidence.md
issue-394 stale claims guard: PASS (1051 versioned text files scanned, 3 claims)
EXIT=0
```

Le scan a d'ailleurs **trouvé** le claim `narrow-rendering-out-of-scope` encore
versionné dans `site/trainer.css` (commentaire de la coque Training) ; c'est
l'unique correction de code de cette task :

```diff
--- a/site/trainer.css
+++ b/site/trainer.css
-   <une ligne déclarant le rendu étroit non concerné par la règle, retirée>
+   Portée : la règle `100dvh` / pas de scroll global reste **desktop only**
+   (bloc `@media(min-width:901px)` ci-dessous). Le pattern sous-vue / onglet est
+   **global** : les sous-vues bornées du rail (`.app-subview-panel`, dont
+   `.app-subview-panel[hidden]{display:none!important}`) et
+   `activateAppSubview` vivent dans la coque de `index.html`, hors media query.
+   Le Training reste donc une vue à onglets sous 901px (un seul panneau visible
+   à la fois) tandis que `html`/`body` gardent leur flux documentaire normal. */
```

Le commentaire remplacé énonçait auparavant que le rendu étroit n'était pas
concerné par la règle de coque, ce que le pattern sous-vue global contredit ; la
ligne retirée n'est pas recopiée ici, précisément parce que la garde
`narrow-rendering-out-of-scope` interdit de la réintroduire dans un fichier
versionné.

Le garde-fou est **branché dans la boucle gelée** :
`tests/trainer/test_product_architecture_contract.py` (le consommateur statique
de `docs/ux-desktop-view-shell.md`) exécute
`python3 tools/check_issue394_stale_claims.py` et exige la ligne
`issue-394 stale claims guard: PASS`. Le nombre de modules de
`tests/trainer/test_*.py` reste **48** : la garde vit dans un module existant,
elle n'ajoute pas un 49ᵉ fichier.

## (2) Ancre release régénérée au HEAD final

`site/trainer.css` a été corrigé **avant** toute vérification d'identité ; l'ancre
a donc été régénérée et vérifiée **après** le dernier écrivain de `site/**` :

```
$ python3 tools/write_site_release.py
wrote site/RELEASE.json
EXIT=0
$ git diff --stat site/RELEASE.json
 site/RELEASE.json | 2 +-
EXIT=0
$ python3 tools/write_site_release.py --check
release source anchor verified: site/RELEASE.json; assembled identity can be materialized
EXIT=0
$ git status --porcelain site/packs/catalog.json
(aucune sortie)
```

La régénération est **exactement** le delta attendu : la ligne
`site/trainer.css` de `identity.assembled_site.functional_files`, dont le blob
Git passe de `8974c3ba62bf2aefeb077bc3d5be9d26e7c3e431` (HEAD) à
`c5998c79331d76ac0e2b2b7c7f8538421833cf66` (octets corrigés). Aucun autre octet
de l'ancre ne bouge, `engine_release` est **inchangée**, et le catalogue de packs
reste matérialisé sans delta.

Vérification de l'ancre, au HEAD final
(`af95f63b27c01aa9d4f41e9eb1da27d7cc8e14b1`) :

| Élément | Valeur |
| --- | --- |
| `schema` | `poker-site-release/v3` |
| `sha256` (moteur) | `2690a82ffe363017b495a1aef60657b12db1b52eb402c36a1ff87f723c5d1bd4` |
| `release_artifact` | `user/releases/poker_range_equity_offline_multiway_v83.html` |
| `identity.assembled_site.assets_tree_git_sha` | `7b8dc481d21a94e8e05fe8d7abae39e0d78b56a9` |
| `git rev-parse HEAD:site/assets` | `7b8dc481d21a94e8e05fe8d7abae39e0d78b56a9` (**égal**) |
| `functional_files` | 34 entrées (dont `site/index.html`, `site/trainer.js`, `site/trainer.css`, `site/packs/catalog.json`) |
| `site/index.html` `git_blob_sha` | `98b51799fe69e4d0e09fc88befeab12139a810b0` |
| `git rev-parse HEAD:site/index.html` | `98b51799fe69e4d0e09fc88befeab12139a810b0` (**égal**) |
| `site/packs/catalog.json` `git_blob_sha` | `9ce17debfd672614050104aa8e1ca8dd88e19fc2` = `git hash-object site/packs/catalog.json` (**égal**) |
| `sha256(site/index.html)` (octets worktree, **après** patch idempotent) | `37a966bb6a74bacfb31989b185748ede9217dd023801dfe8dd76327b6eadf608` |
| `sha256(site/trainer.js)` (octets worktree) | `cfd91bbf1c4054d5e1720866486db23a146ff1fcae306758dad2e3fb7687e1a7` |
| `sha256(site/trainer.css)` (octets worktree) | `c99880520f6ee385ac3228a7a2fd239151874a05680975f97700bba9b8d8c07d` |
| `sha256(site/RELEASE.json)` | `5bb8c6f968d9f784e01b137d74b6dcdd4a21763464cf8591d1687f0496a0efaf` |
| `git hash-object site/RELEASE.json` | `df45ddbc096207457fa4ad2f317a7991089cf43e` |

Le contrat d'identité dédié passe également :

```
$ python3 tests/trainer/test_site_release_identity.py
release source anchor verified: site/RELEASE.json; assembled identity can be materialized
site release identity contract: PASS
EXIT=0
```

L'index est vérifié **après le patch de navigation idempotent** du build
(`patched_index_bytes()`), conformément au contrat de
`tools/write_site_release.py` : ici le remplacement est neutre parce que le
marqueur `<a href="./packs.html">Packs de population</a>` est déjà présent dans
`site/index.html`, donc le blob patché est identique au blob source versionné.

## (3) Boucle complète des contrats statiques (48 modules)

Commande (identique au job `static-contract` de `.github/workflows/trainer-smoke.yml`) :

```
$ files=0; fails=0
$ for test in tests/trainer/test_*.py; do files=$((files+1)); python3 "$test" || fails=$((fails+1)); done
$ printf 'files=%s fails=%s\n' "$files" "$fails"
files=48 fails=0
EXIT=0
```

**48 modules, 48 PASS, 0 échec.** Aucun fichier de test n'a été supprimé ni
affaibli ; le seul ajout est l'appel à la garde anti-claims dans
`tests/trainer/test_product_architecture_contract.py`, dont la sortie est :

```
$ python3 tests/trainer/test_product_architecture_contract.py
issue-394 stale claims guard: PASS
product architecture contract checks: OK
ux desktop view shell doc contract checks: OK
EXIT=0
```

Le job `static-contract` exécute aussi la garde anti-bypass REPRO avant la
boucle ; elle est rejouée ici :

```
$ PYTHONPATH=. python3 tests/ci/test_repro_workflow_batch1.py
REPRO workflow batch-1 tests: 9 passed
EXIT=0
```

## (4) Syntaxe JavaScript

```
$ node --check site/trainer.js
EXIT=0
$ node --version
v24.21.0
```

## (5) Idempotence du patch `tools/patches/apply_trainer_mvp.py`

Forme exacte du job `static-contract` (patch → compare) :

```
$ sha256sum site/index.html site/trainer.js > /tmp/hm5/before.sha
$ python3 tools/patches/apply_trainer_mvp.py
trainer MVP integration patch applied
EXIT=0
$ sha256sum site/index.html site/trainer.js > /tmp/hm5/after.sha
$ diff -u /tmp/hm5/before.sha /tmp/hm5/after.sha
EXIT=0
$ cat /tmp/hm5/after.sha
37a966bb6a74bacfb31989b185748ede9217dd023801dfe8dd76327b6eadf608  site/index.html
cfd91bbf1c4054d5e1720866486db23a146ff1fcae306758dad2e3fb7687e1a7  site/trainer.js
```

Les deux lignes de hachage sont **identiques avant et après** le patch : aucun
octet de `site/index.html` ni de `site/trainer.js` n'a changé, et
`git status --porcelain` ne montre après le patch que les écritures déjà
attendues de cette task (`site/trainer.css`, `site/RELEASE.json`, le branchement
du garde-fou et le garde-fou lui-même).

Intégrité des marqueurs (`site/index.html` au HEAD final) :

```
$ grep -c 'id="trainerOpenBtn"' site/index.html
1
$ grep -c 'id="trainerNavLink"' site/index.html
1
```

Chaque marqueur est présent **exactement une fois**, comme exigé.
`apply_trainer_mvp.py` garde ses insertions sous condition
(`if 'id="trainerNavLink"' not in text` / `if 'id="trainerOpenBtn"' not in text`),
donc la branche non idempotente n'est jamais évaluée et aucune adaptation non
idempotente n'a été introduite. Aucun test n'a été modifié pour faire passer
cette étape.

## Smoke navigateur des modes — résultat réellement observé

**Référence de preuve : [`docs/desktop-modes-fit-evidence.md`](./desktop-modes-fit-evidence.md)**
(preuve de fit versionnée, autorité de verdict explicitement déléguée).
**Autorité pour le smoke lui-même : le job gelé `browser-smoke` de
`.github/workflows/trainer-smoke.yml` dans la PR**, qui dispose du réseau, de
l'action `./.github/actions/repro-browser` et d'un Chromium chargeable, sert
`site/` par `python3 -m http.server 8765 --directory site`, puis lance
`python3 tests/trainer/smoke_trainer.py`. Ce job **n'est pas modifié** par cette
task et sa CI n'a **pas** été observée depuis ce sandbox : **aucun état vert de
CI et aucun `PASS` du smoke gelé n'est affirmé ici.**

Les deux commandes exigées ont été **lancées au HEAD final `af95f63…`** ; le
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
l'orchestrateur n'est pas atteint localement, et le smoke navigateur n'est pas
rejouable dans ce sandbox. Le seul delta versionné de cette task dans
`site/**` est un **commentaire CSS** (portée de la coque Training) ; aucune règle
de style, aucun markup et aucun script n'ont changé, donc la preuve de fit
portée par `docs/desktop-modes-fit-evidence.md` reste la mesure de référence des
mêmes octets fonctionnels — et le job gelé `browser-smoke` reste l'autorité du
verdict.

## Conformité aux contraintes globales

| Contrainte | Statut |
| --- | --- |
| Worktree isolé `n8n/issue-394/task-backlog-hm5` | respecté |
| Aucun commit / push / rebase / `git add` | respecté (opérations jamais exécutées) |
| Aucun merge | respecté |
| Aucune modification de `.github/workflows/**` ni `.github/actions/**` | respecté (`git diff --stat HEAD -- .github` vide) |
| Aucune modification modèle / science / équité | respecté (aucun fichier de ces familles dans le diff) |
| Diff Git non vide | respecté : ce rapport, `tools/check_issue394_stale_claims.py`, `tests/trainer/test_product_architecture_contract.py`, `site/trainer.css`, `site/RELEASE.json` |
| Boucle `tests/trainer/test_*.py` toujours à 48 modules | respecté (la garde vit dans un module existant) |
| Ancre release cohérente avec les octets de `site/index.html` | respecté (`--check` `EXIT=0`, blob de l'index égal à `HEAD:site/index.html`) |
| `engine_release` inchangée | respecté (`sha256` moteur identique avant/après) |
| Rapport réconcilié au HEAD réel, après le dernier écrivain de `site/**` | respecté |
| Aucune affirmation merge / push / CI verte non observée | respecté (§ Self-delta et § Smoke navigateur) |
| Aucun skip ni assertion affaiblie | respecté (48/48 contrats, aucune assertion retirée) |

## Annexe — commandes exactes et sorties

```
$ git rev-parse HEAD
af95f63b27c01aa9d4f41e9eb1da27d7cc8e14b1

$ git rev-parse --abbrev-ref HEAD
n8n/issue-394/task-backlog-hm5

$ git log -1 --pretty=%s
chore(n8n): task backlog-31r for issue #394

$ git log -1 --oneline -- site
386f9d9 chore(n8n): task backlog-arq for issue #394

$ python3 tools/check_issue394_stale_claims.py --self-test
… issue-394 stale claims guard: PASS (1051 versioned text files scanned, 3 claims)
EXIT=0

$ python3 tools/write_site_release.py
wrote site/RELEASE.json
EXIT=0
$ python3 tools/write_site_release.py --check
release source anchor verified: site/RELEASE.json; assembled identity can be materialized
EXIT=0

$ sha256sum site/index.html site/trainer.js > /tmp/hm5/before.sha
$ python3 tools/patches/apply_trainer_mvp.py
trainer MVP integration patch applied
$ sha256sum site/index.html site/trainer.js > /tmp/hm5/after.sha
$ diff -u /tmp/hm5/before.sha /tmp/hm5/after.sha
EXIT=0

$ node --check site/trainer.js
EXIT=0

$ for test in tests/trainer/test_*.py; do python3 "$test"; done
files=48 fails=0

$ PYTHONPATH=. python3 tests/ci/test_repro_workflow_batch1.py
REPRO workflow batch-1 tests: 9 passed

$ python3 tests/trainer/smoke_modes_desktop.py      # smoke navigateur des modes
smoke_modes_desktop: Playwright is unavailable (ModuleNotFoundError("No module named 'playwright'")). …
EXIT=1   # fail-closed observé, cause environnementale (voir § Smoke navigateur)

$ python3 tests/trainer/smoke_trainer.py
ModuleNotFoundError: No module named 'playwright'
EXIT=1   # échec à l'import, avant run_driver_smokes()
```

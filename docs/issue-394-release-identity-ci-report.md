---
schema: poker-issue-394-release-identity-report/v1
issue: 394
task: task-backlog-kd4
planner_key: T4
report_date: 2026-09-25
status: PASS_STATIC_CONTRACTS__FROZEN_BROWSER_JOB_NOT_OBSERVABLE_FROM_THIS_WORKER
head_sha: 7e0280ff554caf7c9b3b94218d729f0283acc623
head_subject: "chore(n8n): task backlog-cg8 for issue #394"
branch: n8n/issue-394/task-backlog-kd4
merged: false
pushed: false
ci_green: NOT_OBSERVED
ci_authority: ".github/workflows/trainer-smoke.yml — workflow « Validate interactive trainer », jobs static-contract et browser-smoke (gelés, non modifiés par cette task)"
ci_required_before_ready: "« Validate interactive trainer » observé au HEAD de la PR avec static-contract = PASS et browser-smoke = PASS ; non observable depuis ce sandbox"
release_anchor_write: NO_DELTA_REGENERATION_IS_BYTE_IDENTICAL
release_anchor_check: PASS
release_anchor_delta: NONE
index_blob_matches_head: PASS
engine_release_unchanged: PASS
stale_claims_guard: PASS_4_CLAIMS
stale_claims_guard_positive_control: PASS_EXIT_1_ON_PROBE
last_site_writer: "8ed9ef0 — chore(n8n): task backlog-0q6 for issue #394 (R1)"
site_bytes_written_by_this_task: NONE
patch_idempotence: PASS
static_contracts: PASS_48_OF_48
javascript_syntax: PASS
browser_smoke_local: FAILED_EXIT_1_PLAYWRIGHT_UNAVAILABLE_IN_SANDBOX
browser_smoke_evidence: "docs/desktop-modes-fit-evidence.md"
browser_smoke_authority: "job gelé browser-smoke de .github/workflows/trainer-smoke.yml — seule autorité de la règle « aucun scroll global » à 1500x1000 et 1366x768 et du clic réel du raccourci Accueil"
red_workflows: []
report_self_delta: "le head_sha consigné est le HEAD RÉEL du worktree au moment de l'écriture, 7e0280ff554caf7c9b3b94218d729f0283acc623, relevé juste avant l'écriture de ce fichier (git rev-parse HEAD) ; cette task n'écrit AUCUN octet de site/** (la régénération de l'ancre est byte-identique, git diff vide), donc le rapport est postérieur au dernier écrivain commité de site/** (8ed9ef0, R1) ; il ne peut pas citer le SHA de son propre commit (auto-référence) et n'affirme aucun merge, aucun push et aucun état vert de CI non observé ; l'orchestrateur gère le commit et la PR"
---

# Rapport PASS/FAIL — ancre release, boucle complète, garde anti-claims et rapport CI (#394, task-backlog-kd4)

Ce rapport matérialise la clôture demandée par `task-backlog-kd4` (T4), **après**
la correction du recouvrement Home/rail livrée par **R1**
(`site/index.html`, task `backlog-0q6`, commit `8ed9ef0`) et le constat d'échec CI
livré par **R2** (`docs/desktop-modes-fit-evidence.md` § 8, task `backlog-cg8`,
commit `7e0280f`) :

1. **régénération et vérification** de l'ancre de release (`site/RELEASE.json`)
   au HEAD réel ;
2. **boucle complète** des contrats statiques (`for test in tests/trainer/test_*.py`,
   la commande exacte du job `static-contract`), `node --check site/trainer.js` et
   **idempotence** de `tools/patches/apply_trainer_mvp.py` ;
3. **garde anti-claims périmés** étendue au **quatrième** claim rejeté en review
   (la requalification de l'échec Home), en plus des trois claims déjà couverts ;
4. **réécriture de ce rapport au HEAD réel**, avec l'exigence CI explicitement
   portée et **aucun `PASS` inventé**.

**Aucun merge**, **aucun push**, **aucun rebase**, **aucun commit**, **aucun
`git add`** : le worker ne commit ni ne pousse, l'orchestrateur prend le relais
après review. **Aucun état vert de CI n'est affirmé** : la CI n'a pas été
observable depuis ce sandbox (§ 6 et § 7).

## Statut

| Champ | Valeur |
| --- | --- |
| Statut global | **PASS** des contrats statiques ; **CI non observée** ; **smoke navigateur non rejouable localement** |
| HEAD réel du worktree | `7e0280ff554caf7c9b3b94218d729f0283acc623` |
| Sujet du HEAD | `chore(n8n): task backlog-cg8 for issue #394` |
| Branche de travail | `n8n/issue-394/task-backlog-kd4` |
| Dernier écrivain **commité** de `site/**` | `8ed9ef0` (task `backlog-0q6`, R1) |
| Changement d'octets dans `site/**` par cette task | **aucun** (régénération byte-identique de l'ancre et du catalogue, `git diff` vide sur `site/**`) |
| Merge effectué | **non** |
| Push effectué | **non** |
| CI distante observée | **non** (`ci_green: NOT_OBSERVED`, § 7) |
| `python3 tools/write_site_release.py` (régénération) | **PASS** (`EXIT=0`, **delta Git vide**) |
| `python3 tools/write_site_release.py --check` | **PASS** (`EXIT=0`) |
| `git rev-parse HEAD:site/index.html` vs `site/RELEASE.json` | **PASS** (égalité stricte) |
| `engine_release` inchangée | **PASS** (`sha256` moteur identique au fichier moteur) |
| Garde anti-claims périmés (4 claims) | **PASS** (`EXIT=0`, 1051 fichiers versionnés scannés, 4 claims) |
| Garde — self-test de non-vacuité | **PASS** (détecteurs rejoués sur les révisions historiques) |
| Garde — contrôle positif | **PASS** (`EXIT=1` sur une sonde temporaire, sonde retirée, diff final inchangé) |
| `tools/patches/apply_trainer_mvp.py` | **PASS** (idempotent, `sha256` inchangés) |
| Marqueurs `id="trainerOpenBtn"` / `id="trainerNavLink"` | **PASS** (chacun présent exactement une fois) |
| Boucle `for test in tests/trainer/test_*.py` | **PASS** (`48/48`, `0` échec) |
| `node --check site/trainer.js` | **PASS** (`EXIT=0`, Node `v24.21.0`) |
| Anti-bypass REPRO (`tests/ci/test_repro_workflow_batch1.py`) | **PASS** (9 passed) |
| Smoke navigateur des modes | **NON REJOUABLE LOCALEMENT** — les deux commandes exigées ont été lancées au HEAD final et ont échoué (`EXIT=1`, `playwright` indisponible) ; **le job gelé `browser-smoke` reste l'autorité** |
| Workflow « Validate interactive trainer » | **NON OBSERVABLE** depuis ce sandbox (§ 7) — arrêt pour vérification humaine, aucun `PASS` affirmé |
| Delta Git de la task | **non vide** : ce rapport + la garde étendue + son branchement documentaire |
| `.github/workflows/**` / `.github/actions/**` | **inchangé** (`git diff --stat HEAD -- .github` vide) |
| Modèle / science / équité | **inchangé** (aucun fichier de ces familles dans le diff) |

### Self-delta (explicite)

- Le HEAD réel du worktree **au moment de l'écriture de ce rapport** est
  **`7e0280ff554caf7c9b3b94218d729f0283acc623`**
  (`chore(n8n): task backlog-cg8 for issue #394`), tête de la branche
  `n8n/issue-394/task-backlog-kd4`. Il a été relevé juste avant l'écriture de ce
  fichier (`git rev-parse HEAD`), et c'est **la valeur qui figure dans l'en-tête
  `head_sha` ci-dessus**.
- **Cette task ne change aucun octet fonctionnel** : `site/index.html`,
  `site/trainer.js`, `site/trainer.css` et `site/RELEASE.json` sont **inchangés**
  (§ 2 : la régénération de l'ancre — et du catalogue de packs qu'elle
  matérialise — reproduit les mêmes octets, le `git diff` correspondant est
  vide). Il n'y a donc **aucune modification `site/**` postérieure au HEAD
  commité**, et l'ancre vérifiée est celle du HEAD réel.
- **Le delta versionné de cette task** est : ce rapport,
  `tools/check_issue394_stale_claims.py` (garde étendue de 3 à 4 claims) et le
  commentaire d'en-tête de `tests/trainer/test_product_architecture_contract.py`
  (le module qui exécute la garde dans la boucle gelée). La somme de contrôle de
  ce fichier ne peut pas être citée par lui-même (auto-référence) ; le worker ne
  commit pas, l'orchestrateur gère le commit et la PR.
- Ce rapport **n'affirme ni merge, ni push, ni état vert de CI** ; il n'affirme
  rien sur le run CI distant, qui n'a pas été observable depuis ce sandbox.

## (1) Garde anti-claims périmés — quatrième claim rejeté en review

La garde statique **`tools/check_issue394_stale_claims.py`**
(`poker-issue-394-stale-claims-guard/v1`) scanne **tous** les fichiers versionnés
(`git ls-files`, extensions textuelles, payloads > 1 Mio ignorés) et échoue sur
le premier fichier qui réaffirme l'un des claims rejetés en review. Elle est
étendue ici du claim (iv) demandé par cette task ; les trois précédents restent
inchangés et continuent d'être vérifiés.

| Claim (identifiant) | Affirmation périmée | Ce que le dépôt dit à la place |
| --- | --- | --- |
| `nav-entry-points-to-standalone-editor` | l'entrée Strategy de `#quickNav` porterait le lien réel vers l'éditeur autonome `./hero-ranges.html` | `site/index.html` : l'entrée est `<a href="#strategyPage" data-product-domain="strategy">Strategy</a>` (navigation **in-app**) ; les liens réels `./hero-ranges.html` sont la carte de mode de l'Accueil, `#heroRangesOpenBtn` et `#strategyPageEditorLink` |
| `narrow-rendering-out-of-scope` | le rendu `<901px` serait non concerné par la règle de coque | `site/index.html` : seule la règle `100dvh` / pas de scroll global est **desktop only** ; le pattern sous-vue / onglet / panneau est **global** (règles de base hors media query, `activateAppSubview` sans garde de largeur) |
| `fit-measured-by-out-of-repo-harness` | la mesure de fit reposerait sur un outillage local non versionné, extérieur au dépôt | `tests/trainer/smoke_modes_desktop.py` porte la mesure **dans le dépôt**, son option `--report` matérialise le rapport JSON, le job gelé `browser-smoke` est la seule autorité de verdict, et `docs/desktop-modes-fit-evidence.md` ne cite aucun chemin hors du dépôt |
| `home-failure-requalified-as-artefact` **(nouveau)** | l'échec du job gelé à 1366x768 (clic réel du raccourci Accueil « Review ») aurait été un sous-produit bénin de la règle du **hit-test central**, donc sans correction nécessaire | `tests/trainer/smoke_modes_desktop.py` conserve ce **clic réel** (`#homePage a[href="#historiesSection"]`, ni `force=True`, ni `dispatch_event`, ni retry, ni skip) ; `docs/desktop-modes-fit-evidence.md` § 8 nomme l'**interception réelle** — le centre de la boîte du lien recevait `button#quickNavToggle`, timeout d'actionnabilité de **30 s** — et `site/index.html` supprime la cause par géométrie (`--home-nav-gutter`, `#homePage{padding-left:calc(24px + var(--home-nav-gutter))}`), sans masquer le recouvrement |

Chaque claim est portée par (a) des motifs **affirmatifs** — les formulations
rejetées elles-mêmes, normalisées en espaces — et (b) un **bloc structurel** qui
prouve que l'implémentation contredit encore le claim (entrée `#quickNav`,
portée du pattern sous-vue + `APP_ALLOWED_SCROLL_ZONES`, propriété in-repo de la
mesure de fit, clic réel du smoke + gouttière nommée de la colonne Home). Le
garde-fou n'est donc pas vacueux : il échoue **aussi** si la contradiction
disparaît de l'implémentation.

Comme en `backlog-hm5`, les formulations exactes rejetées ne sont **pas
recopiées dans ce rapport** : elles constituent l'entrée de détection de la
garde, et les reproduire ici ferait échouer le scan de ce document lui-même.

Seul ce fichier de garde est exclu du scan : il porte nécessairement les
formulations rejetées comme entrées de détection. Tout le reste de ce que Git
versionne est scanné, **ce rapport inclus**.

```
$ python3 tools/check_issue394_stale_claims.py
issue-394 stale claims guard: PASS (1051 versioned text files scanned, 4 claims)
EXIT=0
```

### Preuve de non-vacuité (`--self-test`)

Chaque détecteur est rejoué sur la révision historique qui portait le claim, par
`git show <rev>:<chemin>` :

```
$ python3 tools/check_issue394_stale_claims.py --self-test
self-test nav-entry-points-to-standalone-editor: 3 detector(s) matched a6cefc7:docs/ux-desktop-view-shell.md
self-test narrow-rendering-out-of-scope: 1 detector(s) matched dda6f60:site/index.html
self-test narrow-rendering-out-of-scope: 1 detector(s) matched c3da3fe:site/trainer.css
self-test fit-measured-by-out-of-repo-harness: 4 detector(s) matched c83c72f:docs/desktop-modes-fit-evidence.md
self-test home-failure-requalified-as-artefact: 3 detector(s) matched f105927:docs/desktop-modes-fit-evidence.md
self-test home-failure-requalified-as-artefact: 2 detector(s) matched d331137:docs/desktop-modes-fit-evidence.md
issue-394 stale claims guard: PASS (1051 versioned text files scanned, 4 claims)
EXIT=0
```

### Contrôle positif (sonde temporaire, retirée)

La garde a été **réellement** mise en échec pour vérifier que le nouveau claim
est bien détecté et pas seulement déclaré : une phrase portant le claim rejeté a
été ajoutée temporairement à un document versionné (`docs/shared-components.md`),
puis retirée.

```
$ python3 tools/check_issue394_stale_claims.py       # avec la sonde en place
stale claim re-affirmed: docs/shared-components.md: home-failure-requalified-as-artefact (3 détecteurs)
EXIT=1
$ python3 tools/check_issue394_stale_claims.py       # sonde retirée
issue-394 stale claims guard: PASS (1051 versioned text files scanned, 4 claims)
EXIT=0
```

Sortie condensée : la garde imprime une ligne par détecteur déclenché, **avec le
fragment rejeté** qu'il a reconnu ; ces fragments ne sont volontairement **pas**
recopiés ici, puisqu'ils feraient échouer la garde sur ce rapport (qui est lui
aussi scanné).

La sonde est absente du diff final : `git status --porcelain docs/shared-components.md`
ne retourne rien, et le document est **byte-identique à HEAD**
(`git hash-object docs/shared-components.md` = `git rev-parse HEAD:docs/shared-components.md`).

### Décision d'implémentation : pourquoi la garde étendue, sans 49ᵉ module

Le cahier des charges préférait un **nouveau** module
`tests/trainer/test_issue394_review_claims_contract.py`, *« de préférence, pour
ne pas rouvrir les fichiers de R1/R2 »*. La contrainte de clôture, elle, est
explicite et chiffrée deux fois : la boucle `tests/trainer/test_*.py` doit
rester **48 modules, 0 échec**. Ajouter un 49ᵉ module de test la ferait passer à
49 et contredirait cette acceptance (elle ferait aussi diverger le
`files=48 fails=0` consigné dans `docs/desktop-modes-fit-evidence.md`, fichier
R2).

La garde a donc été **étendue dans le module existant** issu de `backlog-hm5`
(`tools/check_issue394_stale_claims.py`, déjà branché dans la boucle par
`tests/trainer/test_product_architecture_contract.py`). Cela satisfait l'intention
du « pas de réouverture » : **aucun fichier de R1 ou de R2 n'est modifié**
(`git diff --name-only` : rapport, garde, et le seul commentaire d'en-tête du
module qui exécute la garde — ni `site/index.html`, ni
`tests/trainer/test_desktop_accessibility_contract.py`, ni
`tests/trainer/test_smoke_orchestration_contract.py`, ni
`docs/desktop-modes-fit-evidence.md`, ni `docs/ux-desktop-view-shell.md`), et la
boucle gelée reste à **48 modules**.

La garde est bien **exécutée par la boucle** :

```
$ python3 tests/trainer/test_product_architecture_contract.py
issue-394 stale claims guard: PASS
product architecture contract checks: OK
ux desktop view shell doc contract checks: OK
EXIT=0
```

## (2) Ancre release au HEAD réel

Le dernier écrivain **commité** de `site/**` est `8ed9ef0` (R1). Cette task
**régénère** l'ancre puis la vérifie ; la régénération s'avère
**byte-identique** :

```
$ python3 tools/write_site_release.py
wrote site/RELEASE.json
EXIT=0
$ git status --porcelain site/RELEASE.json site/packs/catalog.json
(aucune sortie — ancre et catalogue déjà exacts au HEAD réel)
$ git diff --stat
(aucune sortie pour site/**)
$ python3 tools/write_site_release.py --check
release source anchor verified: site/RELEASE.json; assembled identity can be materialized
EXIT=0
```

Autrement dit : l'ancre `site/RELEASE.json` **coïncide déjà** avec les octets de
`site/index.html` (et de ses 33 autres fichiers fonctionnels) au HEAD réel ; il
n'y a **aucun delta d'ancre** à committer, et `engine_release` reste
**inchangée**.

Vérifications d'identité au HEAD réel
(`7e0280ff554caf7c9b3b94218d729f0283acc623`) :

| Élément | Valeur |
| --- | --- |
| `schema` | `poker-site-release/v3` |
| `sha256` (moteur) | `2690a82ffe363017b495a1aef60657b12db1b52eb402c36a1ff87f723c5d1bd4` |
| `sha256(user/releases/poker_range_equity_offline_multiway_v83.html)` (octets worktree) | `2690a82ffe363017b495a1aef60657b12db1b52eb402c36a1ff87f723c5d1bd4` (**égal — moteur inchangé**) |
| `identity.assembled_site.assets_tree_git_sha` | `7b8dc481d21a94e8e05fe8d7abae39e0d78b56a9` |
| `git rev-parse HEAD:site/assets` | `7b8dc481d21a94e8e05fe8d7abae39e0d78b56a9` (**égal**) |
| `functional_files` | 34 entrées |
| `site/index.html` `git_blob_sha` (ancre) | `033e6517619c162f9033a226d2a5a8e05247401b` |
| `git rev-parse HEAD:site/index.html` | `033e6517619c162f9033a226d2a5a8e05247401b` (**égal**) |
| `site/trainer.js` `git_blob_sha` (ancre) | `70490af692872b663a74ad1d2b180cefe9446568` |
| `git rev-parse HEAD:site/trainer.js` | `70490af692872b663a74ad1d2b180cefe9446568` (**égal**) |
| `site/packs/catalog.json` `git_blob_sha` (ancre) | `9ce17debfd672614050104aa8e1ca8dd88e19fc2` |
| `git hash-object site/packs/catalog.json` | `9ce17debfd672614050104aa8e1ca8dd88e19fc2` (**égal**) |
| `sha256(site/index.html)` (octets worktree, **après** patch idempotent) | `4bcfbcf50af63b29d0b6dbf7007b1b7081b9e2e0e1363d280b39e3bb756b2a2b` |
| `sha256(site/trainer.js)` (octets worktree) | `cfd91bbf1c4054d5e1720866486db23a146ff1fcae306758dad2e3fb7687e1a7` |
| `sha256(site/RELEASE.json)` | `b084076f92a8b63b94b72847e14f12f6a66ce7a9a0cdbdd2d2781cf0548b787c` |
| `git hash-object site/RELEASE.json` | `881f4b0dcc2c81241fe8dde646667855aad436e1` |
| `publication_verification` | `UNVERIFIED_LIVE`, `tracked_by_issue: 45` (**la vérification live reste hors de cette task**) |

Le contrat d'identité dédié passe également :

```
$ python3 tests/trainer/test_site_release_identity.py
release source anchor verified: site/RELEASE.json; assembled identity can be materialized
site release identity contract: PASS
EXIT=0
```

L'index est vérifié **après le patch de navigation idempotent** du build
(`patched_index_bytes()`), conformément au contrat de
`tools/write_site_release.py` : le remplacement y est neutre puisque le marqueur
`<a href="./packs.html">Packs de population</a>` est déjà présent dans
`site/index.html`, donc le blob patché est identique au blob source versionné.

## (3) Boucle complète des contrats statiques (48 modules)

Commande identique au job `static-contract` de `.github/workflows/trainer-smoke.yml` :

```
$ files=0; fails=0
$ for test in tests/trainer/test_*.py; do files=$((files+1)); python3 "$test" || fails=$((fails+1)); done
$ printf 'files=%s fails=%s\n' "$files" "$fails"
files=48 fails=0
EXIT=0
```

**48 modules, 48 PASS, 0 échec**, exécutés au HEAD réel après l'extension de la
garde. Aucun fichier de test n'a été supprimé, renommé ni affaibli ; aucune
assertion n'a été retirée, et le nombre de modules de `tests/trainer/test_*.py`
reste **48** (§ 1, décision d'implémentation).

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
$ sha256sum site/index.html site/trainer.js > /tmp/before.sha
$ python3 tools/patches/apply_trainer_mvp.py
trainer MVP integration patch applied
EXIT=0
$ sha256sum site/index.html site/trainer.js > /tmp/after.sha
$ diff -u /tmp/before.sha /tmp/after.sha
EXIT=0
$ cat /tmp/after.sha
4bcfbcf50af63b29d0b6dbf7007b1b7081b9e2e0e1363d280b39e3bb756b2a2b  site/index.html
cfd91bbf1c4054d5e1720866486db23a146ff1fcae306758dad2e3fb7687e1a7  site/trainer.js
```

Les deux lignes de hachage sont **identiques avant et après** le patch : aucun
octet de `site/index.html` ni de `site/trainer.js` n'a changé, et
`git status --porcelain` ne montre après le patch que les écritures attendues de
cette task (rapport + garde + commentaire d'en-tête du module consommateur).

Intégrité des marqueurs (`site/index.html` au HEAD réel) :

```
$ grep -c 'id="trainerOpenBtn"' site/index.html
1
$ grep -c 'id="trainerNavLink"' site/index.html
1
```

Chaque marqueur est présent **exactement une fois**, comme exigé. Le patch garde
ses insertions sous condition (`if 'id="trainerNavLink"' not in text` /
`if 'id="trainerOpenBtn"' not in text`), donc la branche non idempotente n'est
jamais évaluée. Aucun test n'a été modifié pour faire passer cette étape.

## (6) Smoke navigateur — résultat réellement observé (non rejouable localement)

**Référence de preuve : [`docs/desktop-modes-fit-evidence.md`](./desktop-modes-fit-evidence.md)**
(preuve de fit versionnée, autorité de verdict explicitement déléguée).
**Autorité pour le smoke lui-même : le job gelé `browser-smoke` de
`.github/workflows/trainer-smoke.yml` dans la PR**, qui dispose du réseau, de
l'action `./.github/actions/repro-browser` et d'un Chromium chargeable, sert
`site/` par `python3 -m http.server 8765 --directory site`, puis lance
`python3 tests/trainer/smoke_trainer.py`. Ce job **n'est pas modifié** par cette
task et sa CI n'a **pas** été observée depuis ce sandbox : **aucun état vert de
CI et aucun `PASS` du smoke gelé n'est affirmé ici.**

Les deux commandes exigées ont été **lancées au HEAD final**
(`7e0280ff554caf7c9b3b94218d729f0283acc623`) ; le résultat observé est un
**échec fail-closed d'origine environnementale**, jamais un `PASS` :

```
$ python3 tests/trainer/smoke_modes_desktop.py
smoke_modes_desktop: Playwright is unavailable (ModuleNotFoundError("No module named 'playwright'")). Install the locked dependencies (requirements.lock.txt) and the pinned browser runtime (python3 tools/repro_ci_browser.py install) before running this smoke.
EXIT=1

$ python3 tests/trainer/smoke_trainer.py
Traceback (most recent call last):
  File "…/tests/trainer/smoke_trainer.py", line 10, in <module>
    from playwright.async_api import async_playwright
ModuleNotFoundError: No module named 'playwright'
EXIT=1
```

`smoke_trainer.py` échoue à l'import, donc **avant** `run_driver_smokes()` :
l'orchestrateur n'est pas atteint localement et le smoke navigateur n'est pas
rejouable dans ce sandbox. Cette task n'écrit **aucun** octet de `site/**`
(§ 2), donc les octets fonctionnels mesurés par la preuve de fit restent ceux du
HEAD réel — et le **job gelé `browser-smoke` reste l'unique autorité** pour la
règle « aucun scroll global » à **1500x1000** et **1366x768**, comme pour le
**clic réel** du raccourci Accueil.

## (7) Exigence CI : « Validate interactive trainer » — non observable ici

Condition exigée **avant** de considérer la PR prête :

- workflow **« Validate interactive trainer »** (`.github/workflows/trainer-smoke.yml`)
  **observé** au HEAD de la PR, avec **job `static-contract` = PASS** et
  **job `browser-smoke` = PASS** ;
- le job gelé `browser-smoke` est la **seule autorité** pour la règle « aucun
  scroll global » (`document.scrollingElement.scrollHeight <= clientHeight`) aux
  viewports de référence **1500x1000** et **1366x768** et pour le **clic réel**
  du raccourci Accueil ;
- le job `static-contract` est le consommateur autoritatif de cette boucle
  (48/48, `node --check`, `--check` de l'ancre, idempotence du patch).

**Cette exécution CI n'est pas observable depuis l'environnement de ce worker.**
Tentatives réelles, au HEAD final :

```
$ curl -sS https://api.github.com/rate_limit
curl: (6) Could not resolve host: api.github.com

$ gh run list --workflow trainer-smoke.yml --limit 5
error connecting to api.github.com
check your internet connection or https://githubstatus.com
```

Le réseau est coupé (DNS), aucun run n'a pu être lu et **aucun verdict de CI ne
peut être consigné**. Conformément à la consigne, ce constat est écrit
explicitement et la clôture **s'arrête pour vérification humaine** :

- **aucun `PASS` n'est inventé** pour `static-contract` ni pour `browser-smoke`
  au nouveau HEAD ;
- l'état `ci_green` de ce rapport reste **`NOT_OBSERVED`** ;
- la PR ne peut être déclarée prête qu'après observation, dans l'interface
  GitHub, du workflow « Validate interactive trainer » avec
  `static-contract = PASS` **et** `browser-smoke = PASS` au HEAD réel ; un
  `browser-smoke` rouge au nouveau HEAD invaliderait la clôture de #394.

Les seuls verdicts `PASS` de ce document sont ceux des commandes exécutées **dans
ce worktree** (§ 1 à § 5), plus l'échec fail-closed explicitement consigné du
smoke local (§ 6).

## Conformité aux contraintes globales

| Contrainte | Statut |
| --- | --- |
| Worktree isolé `n8n/issue-394/task-backlog-kd4` | respecté |
| Aucun commit / push / rebase / `git add` | respecté (opérations jamais exécutées) |
| Aucun merge | respecté |
| Aucune modification de `.github/workflows/**` ni `.github/actions/**` | respecté (`git diff --stat HEAD -- .github` vide) |
| Aucune modification modèle / science / équité | respecté (aucun fichier de ces familles dans le diff) |
| Aucun fichier de R1 (`site/index.html`, `tests/trainer/test_desktop_accessibility_contract.py`, `docs/ux-desktop-view-shell.md`) ni de R2 (`docs/desktop-modes-fit-evidence.md`, `tests/trainer/test_smoke_orchestration_contract.py`) modifié | respecté |
| Diff Git non vide, limité au rapport d'identité, à la garde et à son branchement | respecté : `docs/issue-394-release-identity-ci-report.md`, `tools/check_issue394_stale_claims.py`, `tests/trainer/test_product_architecture_contract.py` |
| Aucun octet de `site/**` écrit par cette task | respecté (régénération byte-identique, `git diff` vide sur `site/**`) |
| Boucle `tests/trainer/test_*.py` toujours à 48 modules | respecté (la garde est étendue dans le module existant) |
| Ancre release cohérente avec les octets de `site/index.html` au HEAD réel | respecté (`--check` `EXIT=0`, blob de l'index égal à `HEAD:site/index.html`) |
| `engine_release` inchangée | respecté (`sha256` moteur identique aux octets du fichier moteur) |
| Rapport réconcilié au HEAD réel, postérieur au dernier écrivain de `site/**` | respecté (`head_sha` relevé juste avant écriture, aucune écriture `site/**` par cette task) |
| Aucune affirmation merge / push / CI verte non observée | respecté (§ Self-delta, § 6, § 7) |
| Exigence CI portée explicitement, non-observation consignée, arrêt pour vérification humaine | respecté (§ 7) |
| Aucun skip ni assertion affaiblie | respecté (48/48 contrats, aucune assertion retirée) |

## Annexe — commandes exactes et sorties

```
$ git rev-parse HEAD
7e0280ff554caf7c9b3b94218d729f0283acc623

$ git rev-parse --abbrev-ref HEAD
n8n/issue-394/task-backlog-kd4

$ git log -1 --pretty=%s
chore(n8n): task backlog-cg8 for issue #394

$ git log -1 --oneline -- site
8ed9ef0 chore(n8n): task backlog-0q6 for issue #394

$ python3 tools/check_issue394_stale_claims.py
issue-394 stale claims guard: PASS (1051 versioned text files scanned, 4 claims)
EXIT=0

$ python3 tools/check_issue394_stale_claims.py --self-test
… 6 self-test lines, dont 3+2 pour home-failure-requalified-as-artefact
EXIT=0

$ python3 tools/write_site_release.py
wrote site/RELEASE.json
EXIT=0            # git status/diff : aucune sortie — régénération byte-identique
$ python3 tools/write_site_release.py --check
release source anchor verified: site/RELEASE.json; assembled identity can be materialized
EXIT=0

$ sha256sum site/index.html site/trainer.js > /tmp/before.sha
$ python3 tools/patches/apply_trainer_mvp.py
trainer MVP integration patch applied
$ sha256sum site/index.html site/trainer.js > /tmp/after.sha
$ diff -u /tmp/before.sha /tmp/after.sha
EXIT=0

$ node --check site/trainer.js
EXIT=0

$ for test in tests/trainer/test_*.py; do python3 "$test"; done
files=48 fails=0

$ python3 tests/trainer/test_product_architecture_contract.py
issue-394 stale claims guard: PASS
product architecture contract checks: OK
ux desktop view shell doc contract checks: OK
EXIT=0

$ python3 tests/trainer/test_site_release_identity.py
site release identity contract: PASS
EXIT=0

$ PYTHONPATH=. python3 tests/ci/test_repro_workflow_batch1.py
REPRO workflow batch-1 tests: 9 passed

$ python3 tests/trainer/smoke_modes_desktop.py      # smoke navigateur des modes
smoke_modes_desktop: Playwright is unavailable (ModuleNotFoundError("No module named 'playwright'")). …
EXIT=1   # fail-closed observé, cause environnementale (voir § 6)

$ python3 tests/trainer/smoke_trainer.py
ModuleNotFoundError: No module named 'playwright'
EXIT=1   # échec à l'import, avant run_driver_smokes() (voir § 6)

$ curl -sS https://api.github.com/rate_limit
curl: (6) Could not resolve host: api.github.com       # CI non observable (voir § 7)
```

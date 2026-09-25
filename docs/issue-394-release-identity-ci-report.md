---
schema: poker-issue-394-release-identity-report/v1
issue: 394
task: task-backlog-lzl
planner_key: T4
report_date: 2026-09-25
status: PASS_STATIC_CONTRACTS__CONTRACT_JOB_FAILURE_RECORDED__FROZEN_BROWSER_JOB_NOT_OBSERVABLE_FROM_THIS_WORKER
head_sha: 1e17f90f05811b3dba4e6c830180578f42c391e1
head_subject: "chore(n8n): task backlog-3p7 for issue #394"
branch: n8n/issue-394/task-backlog-lzl
merged: false
pushed: false
ci_green: NOT_OBSERVED
ci_observation_channel: "connecteur GitHub (lecture seule) — le shell de ce worker garde un DNS coupé (curl/gh), le connecteur interroge l'API GitHub"
ci_observation_timestamp_utc: "2026-09-25T02:23Z"
ci_observation_section: "§ 9 (et docs/desktop-modes-fit-evidence.md § 8.6)"
ci_observed_head: 8ff970bde9726852ffd77537499e4b7161698c2c
ci_observed_merge_sha: 4fd6e701eeb37992768b4264c0f86bdcc6a12ca6
ci_observed_trainer_smoke_run: "run #564 — https://github.com/aradenac/poker-engine/actions/runs/36081969038 — static-contract=PASS, browser-smoke=PASS"
ci_observed_hero_range_editor_run: "run #440 — https://github.com/aradenac/poker-engine/actions/runs/36081969061 — contract=FAILURE (étape « Main application integration is idempotent »), browser-smoke=skipped"
ci_frozen_jobs_all_green: false
ci_delivered_head_pushed: NO
ci_delivered_head_runs: NONE
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
patch_idempotence_hero_range_editor: "CORRECTED_T1_T2_T3 — tools/patches/apply_hero_range_editor.py idempotent depuis 3ff4f45"
contract_job_failure_recorded: "PASS — échec CI réel du job gelé contract de .github/workflows/hero-range-editor.yml, étape « Main application integration is idempotent », consigné au § 8"
contract_job_rerun_required: true
static_contracts: PASS_48_OF_48
javascript_syntax: PASS
browser_smoke_local: FAILED_EXIT_1_PLAYWRIGHT_UNAVAILABLE_IN_SANDBOX
browser_smoke_evidence: "docs/desktop-modes-fit-evidence.md"
browser_smoke_authority: "job gelé browser-smoke de .github/workflows/trainer-smoke.yml — seule autorité de la règle « aucun scroll global » à 1500x1000 et 1366x768 et du clic réel du raccourci Accueil"
red_workflows: [".github/workflows/hero-range-editor.yml — job contract rouge au HEAD poussé 8ff970b (run 36081969061, étape « Main application integration is idempotent »), correction T1/T2/T3 non poussée"]
report_self_delta: "révision task-backlog-lzl (T4) : le head_sha consigné est le HEAD RÉEL du worktree au moment de l'écriture, 1e17f90f05811b3dba4e6c830180578f42c391e1 (chore(n8n): task backlog-3p7 for issue #394), relevé juste avant l'écriture de ce fichier (git rev-parse HEAD) ; cette révision AJOUTE le § 8 (échec CI réel du job gelé contract de .github/workflows/hero-range-editor.yml à l'étape « Main application integration is idempotent », cause markup, correction T1/T2/T3) et deux sous-sections documentaires (§ 8.5 de docs/desktop-modes-fit-evidence.md, annotation additive de docs/hero-strategy-population-binding-ci-report.md) ; elle n'écrit AUCUN octet de site/** ni de .github/** (git status --porcelain vide sur ces familles), donc le rapport reste postérieur au dernier écrivain commité de site/** (8ed9ef0, R1) ; il ne peut pas citer le SHA de son propre commit (auto-référence) et n'affirme aucun merge, aucun push et aucun état vert de CI non observé ; l'orchestrateur gère le commit et la PR"
g0t_self_delta: "révision task-backlog-g0t (T3, observation CI) : AJOUTE le § 9 de ce rapport et le § 8.6 de docs/desktop-modes-fit-evidence.md, qui consignent l'observation CI RÉELLE des jobs gelés relevée par le connecteur GitHub le 2026-09-25T02:23Z au HEAD poussé 8ff970bde9726852ffd77537499e4b7161698c2c (runs 36081969038 et 36081969061, URLs de runs et de jobs, conclusions et extraits de journaux) ; les jetons ci_green (NOT_OBSERVED), contract_job_rerun_required (true) et frozen_job_rerun_required (true) restent INCHANGÉS parce que le job gelé contract est rouge au HEAD poussé et que les octets livrés (2d0856024a1859cf778dd889b3911035c1d10378, non poussé) n'ont aucun run ; red_workflows passe de [] au workflow réellement rouge observé ; cette révision n'écrit AUCUN octet de site/**, de .github/**, de tests/ ni d'outils (git status --porcelain limité aux deux documents de preuve)"
frozen_job_rerun_required: true
b3bh_preflight_head: b3baf65e8a263bad2cda8d06c734b55876b455e9
b3bh_preflight_branch: n8n/issue-394/task-backlog-3bh
b3bh_preflight_commits_ahead_of_remote_tip: 7
b3bh_preflight_remote_tip: 8ff970bde9726852ffd77537499e4b7161698c2c
b3bh_preflight_delivered_bytes_have_ci_run: NO
b3bh_preflight_frozen_commands_executed: 6
b3bh_preflight_frozen_commands_exit: "5 commandes de job + 1 étape d'idempotence rejouée sur une copie sous /tmp, toutes EXIT=0 en pré-vol local ; l'indisponibilité navigateur de cet hôte reste signalée séparément et n'est jamais convertie en PASS de job gelé"
b3bh_preflight_trainer_loop: "48 modules, 0 échec"
b3bh_preflight_patch_idempotence: "PASS byte-identique (apply_trainer_mvp.py et apply_hero_range_editor.py : sha256 avant = après, diff -u EXIT=0)"
b3bh_preflight_frozen_job_verdict: NOT_OBSERVED_FROM_THIS_WORKER
b3bh_preflight_browser_coverage: NOT_PROVEN_BY_THIS_WORKER
b3bh_preflight_browser_unavailable: "Module Python playwright absent ET Chromium pinné 1187 non démarrable (libnspr4/libnss3 absents) ET DNS coupé — repli navigateur local irréalisable sur cet hôte"
b3bh_self_delta: "révision task-backlog-3bh (pré-vol hors navigateur) : AJOUTE le § 10 de ce rapport, qui consigne l'exécution RÉELLE, commande par commande, des deux jobs gelés au HEAD du worktree b3baf65e8a263bad2cda8d06c734b55876b455e9 (7 commits d'avance sur le tip distant 8ff970b) — codes de sortie observés, jamais extrapolés — et l'indisponibilité navigateur de cet hôte ; elle AJOUTE la clé frozen_job_rerun_required: true et n'altère AUCUN jeton existant (ci_green: NOT_OBSERVED, contract_job_rerun_required: true et red_workflows restent inchangés) ; elle n'écrit AUCUN octet de site/**, de .github/**, de tests/ ni d'outils (les octets de site/index.html et site/trainer.js ont été sauvés avant les deux essais d'idempotence puis restaurés par copie, sha256 identiques aux blobs HEAD) ; l'orchestrateur gère le commit et la PR"
boq_preflight_head: eb1d117a7a1070b53bc034109c57ecae987501f5
boq_preflight_branch: n8n/issue-394/task-backlog-boq
boq_preflight_head_subject: "chore(n8n): task backlog-wix for issue #394"
boq_preflight_remote_tip: 8ff970bde9726852ffd77537499e4b7161698c2c
boq_preflight_bytes_under_control: "édition CSS de la coque Spot Lab : commit 70dc732 (task backlog-qyb) — règle responsive @media(min-width:901px) and (max-height:900px){.matrix{gap:2px}.cell{height:26px}} ajoutée au bloc <style> de site/index.html et ancre site/RELEASE.json réassemblée (blob index.html 033e6517… -> 75b26fb1…)"
boq_preflight_frozen_commands_executed: 6
boq_preflight_frozen_commands_exit: "5 commandes de job (a–e) + l'étape d'idempotence du second job gelé (f), toutes EXIT=0 observées localement, plus 3 étapes non-navigateur supplémentaires du job contract de hero-range-editor.yml (2x node --check, contrat de dépôt .mjs) également EXIT=0 ; aucun PASS de job gelé revendiqué depuis ce pré-vol"
boq_preflight_trainer_loop: "49 modules, 0 échec (les deux modules ajoutés depuis § 10, tests/trainer/test_smoke_orchestration_contract.py et tests/trainer/test_spotlab_range_fit_contract.py, inclus et EXIT=0)"
boq_preflight_patch_idempotence: "PASS byte-identique sur les octets édités (apply_trainer_mvp.py : sha256 site/index.html et site/trainer.js avant = après, diff -u EXIT=0)"
boq_preflight_hero_patch_idempotence: "PASS byte-identique sur les octets édités (apply_hero_range_editor.py : sha256 site/index.html avant = après, diff -u EXIT=0) — l'étape qui était rouge à 8ff970b"
boq_preflight_css_target_present_in_served_bytes: "PASS (statique) — la règle responsive est dans les octets du fichier servi site/index.html (ligne 121), l'ancre de release est recalculée depuis ces octets (write_site_release.py --check EXIT=0) et tests/trainer/test_spotlab_range_fit_contract.py recalcule la géométrie depuis ces mêmes octets"
boq_preflight_frozen_job_verdict: NOT_OBSERVED_FROM_THIS_WORKER
boq_preflight_browser_coverage: NOT_PROVEN_BY_THIS_WORKER
boq_preflight_browser_unavailable: "Module Python playwright absent ET Chromium pinné 1187 (chrome + headless_shell) non démarrable faute de libnspr4/libnss3 (chargement EXIT=127) ET réseau/DNS coupé (aucune installation possible) — repli navigateur local irréalisable sur cet hôte"
boq_self_delta: "révision task-backlog-boq (pré-vol hors navigateur sur les octets édités) : AJOUTE le § 11 de ce rapport, qui consigne l'exécution RÉELLE, commande par commande et sans rien pousser, des étapes non-navigateur des deux workflows gelés au HEAD du worktree eb1d117a7a1070b53bc034109c57ecae987501f5, qui porte l'édition CSS 70dc732 (task backlog-qyb) — codes de sortie observés, sha256 avant/après, jamais extrapolés — la preuve d'idempotence byte-identique des deux patches sur ces octets, la présence statique de la cible CSS dans les octets servis, et la moitié NON couverte (browser-smoke aux deux viewports, atteignabilité des panneaux, absence de défilement global, clic réel du raccourci Accueil) avec l'impossibilité locale du repli navigateur ; elle n'altère AUCUN jeton existant (ci_green: NOT_OBSERVED, contract_job_rerun_required: true, frozen_job_rerun_required: true et red_workflows restent inchangés) ; elle n'écrit AUCUN octet de site/**, de .github/**, de tests/ ni d'outils (les octets de site/index.html et site/trainer.js ont été sauvés avant les deux essais d'idempotence, puis vérifiés identiques aux blobs HEAD — aucune restauration n'a été nécessaire, les patches n'ayant rien écrit) ; l'orchestrateur gère le commit et la PR"
---

# Rapport PASS/FAIL — ancre release, boucle complète, garde anti-claims et rapport CI (#394, révisé par task-backlog-lzl)

Ce rapport matérialise la clôture demandée par `task-backlog-kd4` (T4), **révisée
par `task-backlog-lzl` (T4)** pour consigner l'**échec CI réel du job gelé
`contract`** de `.github/workflows/hero-range-editor.yml` et la correction du
patch d'idempotence qu'il a révélée (§ 8), **après** la correction du
recouvrement Home/rail livrée par **R1**
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
   portée et **aucun `PASS` inventé** ;
5. **échec CI réel du job gelé `contract`** (étape « Main application integration
   is idempotent »), sa cause markup et la correction livrée, avec les empreintes
   avant/après reproduites depuis le dépôt (§ 8) — sans aucun `PASS` de CI.

**Aucun merge**, **aucun push**, **aucun rebase**, **aucun commit**, **aucun
`git add`** : le worker ne commit ni ne pousse, l'orchestrateur prend le relais
après review. **Aucun état vert de CI n'est affirmé** : la CI n'a pas été
observable depuis ce sandbox (§ 6 et § 7).

## Statut

| Champ | Valeur |
| --- | --- |
| Statut global | **PASS** des contrats statiques ; **CI non observée** ; **smoke navigateur non rejouable localement** |
| HEAD réel du worktree | `1e17f90f05811b3dba4e6c830180578f42c391e1` (relevé juste avant l'écriture de cette révision) |
| Sujet du HEAD | `chore(n8n): task backlog-3p7 for issue #394` |
| Branche de travail | `n8n/issue-394/task-backlog-lzl` |
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
| `tools/patches/apply_hero_range_editor.py` (job gelé `contract`) | **PASS** locale, sur copie **byte-identique** au HEAD réel (idempotent, `sha256` inchangé, `diff -u` `EXIT=0`) — échec CI réel de l'étape et sa correction : § 8 |
| Job gelé `contract` de `.github/workflows/hero-range-editor.yml` (après correction) | **NON OBSERVABLE** depuis ce sandbox — relance exigée (§ 8) ; aucun `PASS` de CI affirmé |
| Marqueurs `id="trainerOpenBtn"` / `id="trainerNavLink"` | **PASS** (chacun présent exactement une fois) |
| Boucle `for test in tests/trainer/test_*.py` | **PASS** (`48/48`, `0` échec) |
| `node --check site/trainer.js` | **PASS** (`EXIT=0`, Node `v24.21.0`) |
| Anti-bypass REPRO (`tests/ci/test_repro_workflow_batch1.py`) | **PASS** (9 passed) |
| Smoke navigateur des modes | **NON REJOUABLE LOCALEMENT** — les deux commandes exigées ont été lancées au HEAD réel de cette révision et ont échoué (`EXIT=1`, `playwright` indisponible) ; **le job gelé `browser-smoke` reste l'autorité** |
| Workflow « Validate interactive trainer » | **NON OBSERVABLE** depuis ce sandbox (§ 7) — arrêt pour vérification humaine, aucun `PASS` affirmé |
| Delta Git de la task | **non vide** : ce rapport + la garde étendue + son branchement documentaire |
| Delta Git de cette révision | **non vide** : ce rapport (§ 8), `docs/desktop-modes-fit-evidence.md` (§ 8.5) et `docs/hero-strategy-population-binding-ci-report.md` (annotation additive) — aucun autre fichier |
| `.github/workflows/**` / `.github/actions/**` | **inchangé** (`git diff --stat HEAD -- .github` vide) |
| Modèle / science / équité | **inchangé** (aucun fichier de ces familles dans le diff) |

### Self-delta (explicite)

- Le HEAD réel du worktree **au moment de l'écriture de ce rapport** est
  **`1e17f90f05811b3dba4e6c830180578f42c391e1`**
  (`chore(n8n): task backlog-3p7 for issue #394`), tête de la branche
  `n8n/issue-394/task-backlog-lzl`. Il a été relevé juste avant l'écriture de ce
  fichier (`git rev-parse HEAD`), et c'est **la valeur qui figure dans l'en-tête
  `head_sha` ci-dessus**. La révision précédente de ce rapport était ancrée sur
  `7e0280ff554caf7c9b3b94218d729f0283acc623` (task `backlog-kd4`) ; elle est
  remplacée, jamais réécrite dans son contenu de preuve.
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
- **Le delta versionné de cette révision** (`task-backlog-lzl`, T4) est
  strictement documentaire : ce rapport (§ 8),
  `docs/desktop-modes-fit-evidence.md` (§ 8.5) et
  `docs/hero-strategy-population-binding-ci-report.md` (annotation additive
  marquant la ligne d'idempotence périmée). Aucun octet de `site/**`, de
  `.github/**`, de test ou d'outil n'est touché par cette révision.
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

Depuis **T3** (`backlog-3p7`, commit `1e17f90`), ce bloc structurel couvre en
outre la régression de l'échec `contract` consigné au § 8 : la garde exige que
`tools/patches/apply_hero_range_editor.py` n'ancre plus d'insertion sur un
identifiant de `#quickNav` et n'émette aucune entrée `data-product-domain`
pointant vers `./hero-ranges.html`. Ses deux contrôles de non-vacuité (entrée
in-app retirée, puis copie temporaire du patch mutée) ajoutent deux lignes au
`--self-test` ci-dessous ; le patch versionné lui-même reste byte-identique après
le contrôle.

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
self-test nav-entry-points-to-standalone-editor: fails without the in-app #strategyPage entry
self-test nav-entry-points-to-standalone-editor: fails on a mutated copy of the patch script
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
(`1e17f90f05811b3dba4e6c830180578f42c391e1`, identique à celui de la révision
`backlog-kd4` pour tout `site/**` : aucun octet fonctionnel n'a bougé depuis
`8ed9ef0`) :

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

Les deux commandes exigées ont été **lancées au HEAD de la révision
`backlog-kd4`** (`7e0280ff554caf7c9b3b94218d729f0283acc623`) **puis de nouveau
au HEAD réel de cette révision**
(`1e17f90f05811b3dba4e6c830180578f42c391e1`) : le résultat observé est le même
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
Tentatives réelles, au HEAD réel de cette révision :

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
ce worktree** (§ 1 à § 5 et § 8), plus l'échec fail-closed explicitement consigné
du smoke local (§ 6).

## (8) Échec CI réel du job gelé `contract` — idempotence du patch de l'éditeur

Ce document consigne, en plus de l'échec du job gelé `browser-smoke` relevé par
R2 (`docs/desktop-modes-fit-evidence.md` § 8.1), un **second échec CI réel** :
celui du job gelé `contract` de `.github/workflows/hero-range-editor.yml`, à son
étape « Main application integration is idempotent », dont la forme exacte est

```
$ sha256sum site/index.html > /tmp/index-before.sha
$ python3 tools/patches/apply_hero_range_editor.py
$ sha256sum site/index.html > /tmp/index-after.sha
$ diff -u /tmp/index-before.sha /tmp/index-after.sha
```

Le `diff` a retourné **1** : la révision alors versionnée de
`tools/patches/apply_hero_range_editor.py` modifiait `site/index.html` à chaque
exécution, donc le step échouait. Ce n'est pas le patch de § 5
(`apply_trainer_mvp.py`, resté idempotent) : c'est celui de l'éditeur autonome.

### Cause réelle, en markup

Le `patch_text()` d'alors réinsérait l'entrée de rail autonome

```
  <a href="./hero-ranges.html" data-product-domain="strategy">Strategy</a>
```

juste après la ligne du rail
`<a id="trainerNavLink" href="#trainerPage" data-product-domain="training">Training</a>`
(l'entrée `#trainerNavLink` de `#quickNav`).
Depuis R1 (`site/index.html`, commit `8ed9ef0`, task `backlog-0q6`), `#quickNav`
ne porte plus ce lien : son entrée Strategy est une navigation **in-app**
(`href="#strategyPage"`). Le garde d'idempotence du patch (« l'entrée est déjà
présente, ne rien écrire ») ne se déclenchait donc plus jamais : chaque run
ajoutait une **seconde** entrée Strategy au rail, changeait le `sha256` de
`site/index.html` et faisait échouer le `diff`.

Reproduction depuis le dépôt, sur une copie **byte-identique** de
`site/index.html` (aucun octet de `site/**` écrit par cette révision) :

```
$ mkdir -p /tmp/hero-editor-before/tools/patches /tmp/hero-editor-before/site
$ cp site/index.html /tmp/hero-editor-before/site/index.html
$ git show 8ff970b:tools/patches/apply_hero_range_editor.py \
    > /tmp/hero-editor-before/tools/patches/apply_hero_range_editor.py
$ sha256sum /tmp/hero-editor-before/site/index.html
4bcfbcf50af63b29d0b6dbf7007b1b7081b9e2e0e1363d280b39e3bb756b2a2b  /tmp/hero-editor-before/site/index.html
$ python3 /tmp/hero-editor-before/tools/patches/apply_hero_range_editor.py
Hero range editor links integrated
$ sha256sum /tmp/hero-editor-before/site/index.html
c5ac487a66360fa5b7cf05742aba79011ae631d5806d9ffa630ea3f1c8ccffa2  /tmp/hero-editor-before/site/index.html
$ diff -u <empreinte avant> <empreinte après>          # empreintes encadrant le patch
EXIT=1
```

| Empreinte de `site/index.html` | Valeur |
| --- | --- |
| avant le patch (octets R1 livrés) | `4bcfbcf50af63b29d0b6dbf7007b1b7081b9e2e0e1363d280b39e3bb756b2a2b` |
| après le patch (révision antérieure) | `c5ac487a66360fa5b7cf05742aba79011ae631d5806d9ffa630ea3f1c8ccffa2` |
| `diff -u` des deux empreintes | `EXIT=1` (échec du step) |

Sur la même copie byte-identique, la révision **corrigée** du patch laisse le
`sha256` **inchangé** et `diff -u` retourne `EXIT=0` — mesuré dans ce worktree au
HEAD réel du front-matter, jamais contre `site/index.html` lui-même.

### Correction livrée (#394, T1/T2/T3)

| Tâche | Livrable | Effet |
| --- | --- | --- |
| **T1** (`backlog-jiv`, commit `3ff4f45`) | `tools/patches/apply_hero_range_editor.py` | la réinsertion dans `#quickNav` est **supprimée** ; le patch ne garde qu'une insertion strictement conditionnée par le marqueur hors navigation `id="heroRangesOpenBtn"` de l'Accueil et n'ancre plus rien sur un identifiant de `#quickNav` |
| **T2** (`backlog-y03`, commit `9d5efcc`) | `tests/hero_ranges/test_hero_range_repository.mjs` | le contrat de dépôt de l'éditeur est étendu sur cette même surface |
| **T3** (`backlog-3p7`, commit `1e17f90`) | `tools/check_issue394_stale_claims.py` | la garde anti-claims échoue si le patch ré-ancre sur un identifiant de `#quickNav` ou s'il émet une entrée `data-product-domain` pointant vers `./hero-ranges.html` : la régression ne peut pas revenir silencieusement |

La ligne historique `apply_hero_range_editor.py` (idempotence `site/index.html`)
de `docs/hero-strategy-population-binding-ci-report.md` est **périmée /
superseded** : elle est annotée sur place (l'historique n'est pas réécrit) avec
renvoi vers cet échec #394 et sa correction. Le récit complet, viewport par
viewport, est consigné en **§ 8.5 de `docs/desktop-modes-fit-evidence.md`**.

### Statut de non-observation

Le job gelé `contract` **après correction** et son job dépendant `browser-smoke`
de `.github/workflows/hero-range-editor.yml` ne sont **pas observables** depuis ce
sandbox (réseau coupé, § 7) : **aucun `PASS` de CI n'est affirmé** ici, ni pour
la correction du patch, ni pour le fit. Ce qui est consigné est l'échec CI réel,
sa cause et la correction livrée ; leur relance au HEAD réel reste une exigence
de clôture. La **seule autorité** de la règle « aucun scroll global » reste le
job gelé `browser-smoke` de `.github/workflows/trainer-smoke.yml` ; l'étape
d'idempotence ci-dessus ne porte aucun verdict de fit. Cette révision n'écrit
**aucun octet** de `site/**` ni de `.github/**`.

## Conformité aux contraintes globales

| Contrainte | Statut |
| --- | --- |
| Worktree isolé `n8n/issue-394/task-backlog-lzl` | respecté |
| Aucun commit / push / rebase / `git add` | respecté (opérations jamais exécutées) |
| Aucun merge | respecté |
| Aucune modification de `.github/workflows/**` ni `.github/actions/**` | respecté (`git diff --stat HEAD -- .github` vide) |
| Aucune modification modèle / science / équité | respecté (aucun fichier de ces familles dans le diff) |
| Aucun fichier de R1 (`site/index.html`, `tests/trainer/test_desktop_accessibility_contract.py`, `docs/ux-desktop-view-shell.md`) ni de R2 (`docs/desktop-modes-fit-evidence.md`, `tests/trainer/test_smoke_orchestration_contract.py`) modifié | respecté |
| Diff Git non vide, limité au rapport d'identité, à la garde et à son branchement (révision `backlog-kd4`) | respecté : `docs/issue-394-release-identity-ci-report.md`, `tools/check_issue394_stale_claims.py`, `tests/trainer/test_product_architecture_contract.py` |
| Diff Git de cette révision documentaire, limité aux trois documents consignés | respecté : `docs/issue-394-release-identity-ci-report.md` (§ 8), `docs/desktop-modes-fit-evidence.md` (§ 8.5), `docs/hero-strategy-population-binding-ci-report.md` (annotation additive) |
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
1e17f90f05811b3dba4e6c830180578f42c391e1

$ git rev-parse --abbrev-ref HEAD
n8n/issue-394/task-backlog-lzl

$ git log -1 --pretty=%s
chore(n8n): task backlog-3p7 for issue #394

$ git log -1 --oneline -- site
8ed9ef0 chore(n8n): task backlog-0q6 for issue #394

$ python3 tools/check_issue394_stale_claims.py
issue-394 stale claims guard: PASS (1051 versioned text files scanned, 4 claims)
EXIT=0

$ python3 tools/check_issue394_stale_claims.py --self-test
… 8 self-test lines : 6 rejeux historiques (nav-entry, narrow ×2, fit, home ×2)
  + 2 contrôles de non-vacuité nav-entry-points-to-standalone-editor
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

$ sha256sum site/index.html          # empreinte « avant » commune aux deux essais (§ 8)
4bcfbcf50af63b29d0b6dbf7007b1b7081b9e2e0e1363d280b39e3bb756b2a2b  site/index.html

# (a) révision CORRIGÉE du patch, sur une copie byte-identique hors du dépôt
$ mkdir -p /tmp/hero-editor-fixed/tools/patches /tmp/hero-editor-fixed/site
$ cp site/index.html /tmp/hero-editor-fixed/site/index.html
$ cp tools/patches/apply_hero_range_editor.py /tmp/hero-editor-fixed/tools/patches/
$ python3 /tmp/hero-editor-fixed/tools/patches/apply_hero_range_editor.py
/tmp/hero-editor-fixed/site/index.html
$ sha256sum /tmp/hero-editor-fixed/site/index.html
4bcfbcf50af63b29d0b6dbf7007b1b7081b9e2e0e1363d280b39e3bb756b2a2b  /tmp/hero-editor-fixed/site/index.html
$ diff -u <empreinte avant> <empreinte après>
EXIT=0            # patch corrigé : idempotent, aucun octet écrit (§ 8)

# (b) révision ANTÉRIEURE du patch, sur la même copie byte-identique
$ mkdir -p /tmp/hero-editor-before/tools/patches /tmp/hero-editor-before/site
$ cp site/index.html /tmp/hero-editor-before/site/index.html
$ git show 8ff970b:tools/patches/apply_hero_range_editor.py \
    > /tmp/hero-editor-before/tools/patches/apply_hero_range_editor.py
$ python3 /tmp/hero-editor-before/tools/patches/apply_hero_range_editor.py
Hero range editor links integrated
$ sha256sum /tmp/hero-editor-before/site/index.html
c5ac487a66360fa5b7cf05742aba79011ae631d5806d9ffa630ea3f1c8ccffa2  /tmp/hero-editor-before/site/index.html
$ diff -u <empreinte avant> <empreinte après>
EXIT=1            # échec réel du step « Main application integration is idempotent » (§ 8)

$ git status --porcelain site/       # (aucune sortie : site/** jamais touché par ces essais)
$ sha256sum site/index.html
4bcfbcf50af63b29d0b6dbf7007b1b7081b9e2e0e1363d280b39e3bb756b2a2b  site/index.html

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

## (9) Observation CI réelle des jobs gelés au HEAD livré — connecteur GitHub

Le § 7 constate que le **shell** de ce worker n'a pas de réseau (DNS coupé) : il
reste vrai, `curl` et `gh` échouent toujours. Un **second canal** a cependant
permis de relever l'état CI **réel** des jobs gelés : le **connecteur GitHub**
(lecture seule), interroge l'API GitHub et rend les runs, les jobs, leurs étapes
et leurs journaux. L'observation ci-dessous a été faite le
**2026-09-25T02:23Z** ; le récit viewport par viewport et les extraits
d'exécution complets sont consignés en **§ 8.6 de
`docs/desktop-modes-fit-evidence.md`**.

### Ce qui a été observé, et à quel HEAD

| Élément | Valeur |
| --- | --- |
| HEAD observé (branche épique = tête de PR #416) | `8ff970bde9726852ffd77537499e4b7161698c2c` |
| Commit extrait par la CI `pull_request` | `4fd6e701eeb37992768b4264c0f86bdcc6a12ca6` (fusion de `8ff970b` dans `main`) |
| HEAD livré du worktree | `2d0856024a1859cf778dd889b3911035c1d10378` — **non poussé** |
| Runs CI sur les octets livrés | **aucun** : les corrections T1/T2/T3 (`tools/patches/apply_hero_range_editor.py`, `tests/hero_ranges/**`, `tests/trainer/**`) ne sont pas dans la branche épique |

| Workflow (gelé) | Job | Run | Conclusion |
| --- | --- | --- | --- |
| `.github/workflows/trainer-smoke.yml` | `static-contract` | [run `36081969038`](https://github.com/aradenac/poker-engine/actions/runs/36081969038) (`#564`) | **`success`** — [job `107905680522`](https://github.com/aradenac/poker-engine/actions/runs/36081969038/job/107905680522) |
| `.github/workflows/trainer-smoke.yml` | `browser-smoke` | [run `36081969038`](https://github.com/aradenac/poker-engine/actions/runs/36081969038) (`#564`) | **`success`** — [job `107905811137`](https://github.com/aradenac/poker-engine/actions/runs/36081969038/job/107905811137) |
| `.github/workflows/hero-range-editor.yml` | `contract` | [run `36081969061`](https://github.com/aradenac/poker-engine/actions/runs/36081969061) (`#440`) | **`failure`** à l'étape « Main application integration is idempotent » — [job `107905680401`](https://github.com/aradenac/poker-engine/actions/runs/36081969061/job/107905680401) |
| `.github/workflows/hero-range-editor.yml` | `browser-smoke` | [run `36081969061`](https://github.com/aradenac/poker-engine/actions/runs/36081969061) (`#440`) | **`skipped`** (`needs: contract`) |

### Les extraits du journal

L'étape d'idempotence est **rouge** au HEAD poussé, et le journal du job `contract`
porte les deux empreintes du § 8 — il n'y a là aucune déduction :

```
Hero range editor links integrated
--- /tmp/index-before.sha
+++ /tmp/index-after.sha
@@ -1 +1 @@
-4bcfbcf50af63b29d0b6dbf7007b1b7081b9e2e0e1363d280b39e3bb756b2a2b  site/index.html
+c5ac487a66360fa5b7cf05742aba79011ae631d5806d9ffa630ea3f1c8ccffa2  site/index.html
##[error]Process completed with exit code 1.
```

Le job `browser-smoke` du run vert `#564` porte, lui, l'audit par mode **et par
viewport** du smoke : les lignes `1366x768` de Spot Lab, Replayer, Training
(rail Trainer), Stratégie Hero et de l'éditeur autonome y figurent, avec la ligne
finale `modes desktop smoke: PASS (2 viewports · …)`. L'extrait complet est en
§ 8.6.4 de `docs/desktop-modes-fit-evidence.md`.

### Conséquence sur les jetons de ce rapport

La condition de bascule n'est **pas** remplie : les jobs gelés ne sont pas tous
verts, et les octets livrés n'ont pas encore de run. Donc :

- `ci_green` reste **`NOT_OBSERVED`** — aucune valeur n'est forcée ;
- `contract_job_rerun_required` reste **`true`** : l'étape d'idempotence du job
  gelé `contract` est rouge au HEAD poussé, sa correction n'y est pas ;
- `frozen_job_rerun_required` reste **`true`** : le job gelé `browser-smoke` de
  `.github/workflows/trainer-smoke.yml` doit être relancé sur les octets livrés
  (l'extension T1 du smoke touche `tests/trainer/**`, une famille de chemins que
  ce workflow surveille, donc la poussée des corrections le redéclenche par
  construction) ;
- `red_workflows` n'est plus vide : il nomme le workflow réellement rouge au HEAD
  poussé, `.github/workflows/hero-range-editor.yml`, avec son run et son étape —
  la valeur précédente (`[]`) ne correspondait plus à l'échec consigné au § 8.

Aucun `PASS` de job gelé n'est écrit ici pour un état non observé, et le job gelé
`browser-smoke` de `.github/workflows/trainer-smoke.yml` reste la **seule
autorité** de la règle « aucun scroll global » (`scrollHeight` / `clientHeight` à
`1500x1000` et `1366x768`, pour les six modes `home`, `spotlab`, `review`,
`replayer`, `training`, `strategy`). Cette section n'écrit **aucun octet** de
`site/**`, de `.github/**`, de test ou d'outil : elle est strictement additive.

## (10) Pré-vol hors navigateur des deux jobs gelés, au HEAD livré `b3baf65`

Cette section est **strictement additive** : elle consigne l'exécution **réelle**,
commande par commande, du corps **hors navigateur** des **deux jobs gelés** au
HEAD du worktree épique **`b3baf65e8a263bad2cda8d06c734b55876b455e9`**
(`chore(n8n): task backlog-g0t for issue #394`). Chaque code de sortie ci-dessous
est **observé**, jamais extrapolé ; aucun échec d'environnement n'est requalifié en
`PASS`.

### (10.1) À quel HEAD, et pourquoi aucun run CI n'existe pour les octets livrés

| Élément | Valeur observée |
| --- | --- |
| HEAD du pré-vol | `b3baf65e8a263bad2cda8d06c734b55876b455e9` |
| Sujet du HEAD | `chore(n8n): task backlog-g0t for issue #394` |
| Branche de ce worktree | `n8n/issue-394/task-backlog-3bh` |
| Commits d'avance sur le tip distant | **7** (`git rev-list --count 8ff970b..HEAD`) |
| Tip distant (dernier HEAD poussé) | `8ff970bde9726852ffd77537499e4b7161698c2c` |
| Runs CI sur les octets livrés | **aucun** (`ci_delivered_head_runs: NONE`, § 9) |
| `git status --porcelain` à l'ouverture | vide (worktree propre) |
| Environnement observé | Python `3.14.4`, Node `v24.21.0`, worktree inscriptible |

Le `head_sha` du front-matter (`1e17f90…`) est **inchangé** : il reste l'ancre de la
révision `lzl`, conservée telle quelle par cette édition additive. Le HEAD des
exécutions de ce § 10 est celui relevé ci-dessus, `b3baf65…`, **7 commits
d'avance** sur `8ff970b` — il n'y a donc **aucun run CI pour les octets livrés**.
La conséquence est directe : seule la relance des jobs gelés sur un HEAD **poussé**
peut observer l'acceptation ; ce pré-vol ne mesure que le périmètre hors navigateur.

### (10.2) Les six commandes, réellement exécutées au HEAD `b3baf65`

| # | Commande (exacte) | Observation | Code de sortie |
| --- | --- | --- | --- |
| 1 | `PYTHONPATH=. python3 tests/ci/test_repro_workflow_batch1.py` | `REPRO workflow batch-1 tests: 9 passed` | **0** |
| 2 | `node --check site/trainer.js` | aucune sortie (syntaxe OK) | **0** |
| 3 | `python3 tools/write_site_release.py --check` | `release source anchor verified: site/RELEASE.json; assembled identity can be materialized` | **0** |
| 4 | `for test in tests/trainer/test_*.py; do python3 "$test"; done` | **48 modules**, **0 échec** (§ 10.2.1) | **0** |
| 5 | étape « Patch idempotence » : `sha256sum site/index.html site/trainer.js` → `apply_trainer_mvp.py` → comparaison | `sha256` avant = après, `diff -u` vide (§ 10.3) | **0** |
| 6 | étape « Main application integration is idempotent » : `sha256sum site/index.html` → `apply_hero_range_editor.py` → comparaison | `sha256` avant = après, `diff -u` vide (§ 10.4) | **0** |

Les commandes 1–3 sont les trois premières étapes du job `static-contract` de
`.github/workflows/trainer-smoke.yml` ; la commande 1 est aussi la première étape
du job `contract` de `.github/workflows/hero-range-editor.yml`.

#### (10.2.1) Commande 4 — la boucle gelée « All trainer regression contracts »

```
$ for test in tests/trainer/test_*.py; do echo "=== $test"; python3 "$test"; echo "EXIT[$test]=$?"; done
…
TOTAL_MODULES=48
```

Les **48 modules** ont été exécutés et **chacun** est sorti avec `EXIT=0` : la
**liste exacte des échecs est vide**. Les 48 chemins sont recopiés en § 10.8.

**Aucun échec de type « no usable temporary directory » ni « filesystem
read-only » n'a été observé** : `TMPDIR` est inscriptible sur cet hôte et l'arbre de
travail l'est aussi (§ 10.7). De tels échecs, s'ils survenaient, seraient nommés
**environnementaux** et **jamais** convertis en `PASS` ; ici ils ne se produisent
pas, donc rien n'est requalifié.

### (10.3) Commande 5 — idempotence du patch Trainer MVP (octets sauvés, restaurés par copie)

```
$ cp site/index.html /tmp/b3bh/index.html.orig
$ cp site/trainer.js /tmp/b3bh/trainer.js.orig
$ sha256sum site/index.html site/trainer.js > /tmp/b3bh/before-trainer.sha
$ python3 tools/patches/apply_trainer_mvp.py
trainer MVP integration patch applied
$ sha256sum site/index.html site/trainer.js > /tmp/b3bh/after-trainer.sha
$ diff -u /tmp/b3bh/before-trainer.sha /tmp/b3bh/after-trainer.sha
EXIT=0
```

| Fichier | `sha256` avant | `sha256` après | Byte-identique |
| --- | --- | --- | --- |
| `site/index.html` | `4bcfbcf50af63b29d0b6dbf7007b1b7081b9e2e0e1363d280b39e3bb756b2a2b` | `4bcfbcf50af63b29d0b6dbf7007b1b7081b9e2e0e1363d280b39e3bb756b2a2b` | **oui** |
| `site/trainer.js` | `cfd91bbf1c4054d5e1720866486db23a146ff1fcae306758dad2e3fb7687e1a7` | `cfd91bbf1c4054d5e1720866486db23a146ff1fcae306758dad2e3fb7687e1a7` | **oui** |

Le patch imprime `trainer MVP integration patch applied` et **n'écrit aucun
octet** : les deux empreintes encadrantes sont **égales** et le `diff -u` — la
comparaison que la CI utilise — retourne **`EXIT=0`**.

### (10.4) Commande 6 — idempotence du patch Hero range editor (job `contract`)

C'est exactement l'étape **rouge** observée à `8ff970b` (§ 8 et § 9). Elle est ici
rejouée au HEAD `b3baf65` :

```
$ grep -c 'id="heroRangesOpenBtn"' site/index.html
1
$ sha256sum site/index.html > /tmp/b3bh/index-before.sha
$ python3 tools/patches/apply_hero_range_editor.py
/home/…/site/index.html
$ sha256sum site/index.html > /tmp/b3bh/index-after.sha
$ diff -u /tmp/b3bh/index-before.sha /tmp/b3bh/index-after.sha
EXIT=0
```

| Fichier | `sha256` avant | `sha256` après | Byte-identique |
| --- | --- | --- | --- |
| `site/index.html` | `4bcfbcf50af63b29d0b6dbf7007b1b7081b9e2e0e1363d280b39e3bb756b2a2b` | `4bcfbcf50af63b29d0b6dbf7007b1b7081b9e2e0e1363d280b39e3bb756b2a2b` | **oui** |

Le marqueur de garde `id="heroRangesOpenBtn"` est présent **exactement une fois**,
donc `patch_text()` retourne le texte inchangé : `sha256` avant = après et
`diff -u` `EXIT=0` — **plus l'échec de § 8**, dont la cause (la réinsertion dans
`#quickNav`) a été retirée en T1 (`3ff4f45`).

#### (10.4.1) Modes `--index` / `--check` du même patch

```
$ python3 tools/patches/apply_hero_range_editor.py --check         # index du dépôt (déjà patché)
/home/…/site/index.html
EXIT=0

# copie byte-identique SANS le marqueur, écrite sous /tmp (aucun octet du dépôt touché)
$ sha256sum /tmp/b3bh/index-mode/index-unpatched.html
63294b6809f20aebb8ad90cd2729471432a1c731ee373e54451c5dc5c17623f3  /tmp/b3bh/index-mode/index-unpatched.html
$ python3 tools/patches/apply_hero_range_editor.py --index /tmp/b3bh/index-mode/index-unpatched.html
/tmp/b3bh/index-mode/index-unpatched.html
EXIT=0            # 1er run : écrit une fois
$ sha256sum /tmp/b3bh/index-mode/index-unpatched.html
4bcfbcf50af63b29d0b6dbf7007b1b7081b9e2e0e1363d280b39e3bb756b2a2b  /tmp/b3bh/index-mode/index-unpatched.html
$ python3 tools/patches/apply_hero_range_editor.py --index /tmp/b3bh/index-mode/index-unpatched.html
EXIT=0            # 2e run : idempotent, sha256 inchangé
$ sha256sum /tmp/b3bh/index-mode/index-unpatched.html
4bcfbcf50af63b29d0b6dbf7007b1b7081b9e2e0e1363d280b39e3bb756b2a2b  (identique)
$ python3 tools/patches/apply_hero_range_editor.py --index /tmp/b3bh/index-mode/index-unpatched.html --check
EXIT=0            # --check sur une copie patchée : PASS
$ python3 tools/patches/apply_hero_range_editor.py --index /tmp/b3bh/index-mode/index-plain.html --check
hero range editor patch is not applied
EXIT=1            # --check sur une copie NON patchée : échec fail-closed attendu
```

La copie patchée (`4bcfbcf5…`) est **byte-identique** à `site/index.html` du
dépôt : la copie non patchée n'en différait que par la ligne Strategy de l'Accueil.
Le double `--index` montre que le patch écrit **au plus une fois** puis devient
inerte ; `--check` est un garde fail-closed qui échoue (`EXIT=1`) quand l'entrée
attendue manque.

### (10.5) Couverture NON prouvée : la moitié navigateur

Ce pré-vol **ne couvre pas** — et ne prétend pas couvrir — la moitié navigateur de
l'acceptation #394. Restent **non prouvés localement** :

- l'**absence de défilement global** (`document.scrollingElement.scrollHeight <=
  clientHeight`) pour les **six modes** `home`, `spotlab`, `review`, `replayer`,
  `training`, `strategy`, **aux deux viewports de référence** `1500x1000` et
  `1366x768` ;
- l'**atteignabilité réelle** des panneaux Spot Lab, Replayer et Trainer (les
  hit-tests de panneaux à `1366x768` nommés par la revue humaine) ;
- le **clic réel** du raccourci Accueil `#homePage a[href="#historiesSection"]`,
  **non intercepté** — `tests/trainer/smoke_modes_desktop.py` (≈ ligne 1141)
  exécute `await page.click('#homePage a[href="#historiesSection"]')`, sans
  `force=True`, sans `dispatch_event`, sans retry et sans skip.

Les commandes 1–6 ci-dessus sont **statiques** : aucune n'exécute un navigateur. Le
**seul** canal qui observe ces trois points est le job gelé `browser-smoke` de
`.github/workflows/trainer-smoke.yml` (§ 7 et § 9), plus le job `browser-smoke` de
`.github/workflows/hero-range-editor.yml` pour l'éditeur autonome. **Aucun `PASS`
de ces jobs n'est écrit ici** : ils n'ont pas été observés depuis ce worker.

### (10.6) Repli navigateur local : irréalisable sur cet hôte (constat observé)

Le repli navigateur demandé par la revue est **irréalisable sur cet hôte**, et les
trois raisons ont été **vérifiées** ici, pas supposées :

```
$ python3 -c "import playwright"
ModuleNotFoundError: No module named 'playwright'
$ python3 tests/trainer/smoke_modes_desktop.py
smoke_modes_desktop: Playwright is unavailable (ModuleNotFoundError("No module named 'playwright'")). …
EXIT=1
$ python3 tests/trainer/smoke_trainer.py
ModuleNotFoundError: No module named 'playwright'     # échec à l'import, avant run_driver_smokes()
EXIT=1
$ ~/.cache/ms-playwright/chromium-1187/chrome-linux/chrome --version
…/chrome: error while loading shared libraries: libnspr4.so: cannot open shared object file: No such file or directory
EXIT=127
$ ~/.cache/ms-playwright/chromium_headless_shell-1187/chrome-linux/headless_shell --version
…/headless_shell: error while loading shared libraries: libnspr4.so: cannot open shared object file: No such file or directory
EXIT=127
$ ldconfig -p | grep -Ei 'libnspr4|libnss3'
NO libnspr4/libnss3 in ldconfig cache
$ ls /usr/lib/x86_64-linux-gnu/libnspr4.so /usr/lib/x86_64-linux-gnu/libnss3.so
ls: cannot access '…/libnspr4.so': No such file or directory
ls: cannot access '…/libnss3.so': No such file or directory
$ timeout 8 curl -sS https://pypi.org/simple/
curl: (6) Could not resolve host: pypi.org            # DNS coupé, EXIT=6
```

Chromium **pinné** (révision `1187`, version `140.0.7339.16`, cf.
`reproducibility/browser-identity.lock.json` et
`reproducibility/environment.lock.json`) est **présent** dans le cache mais **ne
démarre pas** : il manque `libnspr4.so` (et `libnss3.so`), absents de l'hôte. Le
module Python `playwright` est lui aussi **absent**, et le **réseau** (DNS) est
coupé, donc ces bibliothèques **ne peuvent pas être installées ici**. Conclusion :
aucun smoke navigateur n'est exécutable localement, et **la seule autorité reste le
run des jobs gelés sur un HEAD poussé**.

### (10.7) Conséquence sur les jetons, et clôture

La condition de bascule de § 9 n'est pas remplie : le pré-vol local ne remplace pas
un run CI poussé. Donc :

- `ci_green` reste **`NOT_OBSERVED`** ;
- `frozen_job_rerun_required` reste **`true`** (désormais aussi porté comme clé de
  front-matter) : le job gelé `browser-smoke` doit tourner sur les octets livrés ;
- `contract_job_rerun_required` reste **`true`** : l'étape d'idempotence du job
  `contract` est rouge au HEAD poussé `8ff970b`, sa correction n'y est pas ;
- `red_workflows` **nomme** toujours le workflow rouge réellement observé,
  `.github/workflows/hero-range-editor.yml` (job `contract`, run `36081969061`,
  étape « Main application integration is idempotent »).

Après restauration par copie, l'arbre est rendu **intact** :

```
$ cp /tmp/b3bh/index.html.orig site/index.html && cp /tmp/b3bh/trainer.js.orig site/trainer.js
$ sha256sum site/index.html site/trainer.js
4bcfbcf50af63b29d0b6dbf7007b1b7081b9e2e0e1363d280b39e3bb756b2a2b  site/index.html
cfd91bbf1c4054d5e1720866486db23a146ff1fcae306758dad2e3fb7687e1a7  site/trainer.js
$ git hash-object site/index.html site/trainer.js
033e6517619c162f9033a226d2a5a8e05247401b   # == git rev-parse HEAD:site/index.html
70490af692872b663a74ad1d2b180cefe9446568   # == git rev-parse HEAD:site/trainer.js
$ git status --porcelain
 M docs/issue-394-release-identity-ci-report.md
$ python3 tools/write_site_release.py --check
release source anchor verified: site/RELEASE.json; assembled identity can be materialized
EXIT=0
```

`git status --porcelain` ne montre **que** le fichier de rapport modifié ; les
octets de `site/**` sont **identiques aux blobs HEAD** (aucun `git checkout`,
`reset` ni `stash` n'a été utilisé — la restauration s'est faite par copie) ; et
`python3 tools/write_site_release.py --check` sort **`0`**. Cette section n'écrit
**aucun octet** de `site/**` ni de `.github/**` : elle est strictement additive.

### (10.8) Annexe — les 48 modules de la boucle gelée (tous `EXIT=0`)

```
tests/trainer/test_action_sizing_ev_presentation.py                     EXIT=0
tests/trainer/test_advanced_import_central_ui_contract.py               EXIT=0
tests/trainer/test_analysis_state_consistency_contract.py               EXIT=0
tests/trainer/test_analysis_state_mirror_contract.py                    EXIT=0
tests/trainer/test_appview_no_recompute_contract.py                     EXIT=0
tests/trainer/test_auxiliary_scale_surfaces_contract.py                 EXIT=0
tests/trainer/test_d6_render_matrix_contract.py                         EXIT=0
tests/trainer/test_decision_summary_contract.py                         EXIT=0
tests/trainer/test_delta_ev_primary_contract.py                         EXIT=0
tests/trainer/test_deployment_metadata.py                               EXIT=0
tests/trainer/test_desktop_accessibility_contract.py                    EXIT=0
tests/trainer/test_hh_import_ux_contract.py                             EXIT=0
tests/trainer/test_implicit_review_context.py                           EXIT=0
tests/trainer/test_known_hand_override_contract.py                      EXIT=0
tests/trainer/test_leak_training_ui_contract.py                         EXIT=0
tests/trainer/test_local_persistence_ux_contract.py                     EXIT=0
tests/trainer/test_model_b_robustness_ui_contract.py                    EXIT=0
tests/trainer/test_opponent_analysis_state_contract.py                  EXIT=0
tests/trainer/test_opponent_range_display_contract.py                   EXIT=0
tests/trainer/test_opponent_range_semantics_rework_contract.py          EXIT=0
tests/trainer/test_posterior_state_contract.py                          EXIT=0
tests/trainer/test_preflop_runtime_contract.py                          EXIT=0
tests/trainer/test_prior_posterior_ui_contract.py                       EXIT=0
tests/trainer/test_product_architecture_contract.py                     EXIT=0
tests/trainer/test_product_identity_ux_contract.py                      EXIT=0
tests/trainer/test_range_display_docs_contract.py                       EXIT=0
tests/trainer/test_range_vocabulary_contract.py                         EXIT=0
tests/trainer/test_replayer_actor_comment_semantics.py                  EXIT=0
tests/trainer/test_replayer_analysis_state_contract.py                  EXIT=0
tests/trainer/test_replayer_hand_class.py                               EXIT=0
tests/trainer/test_replayer_modal_prior_states.py                       EXIT=0
tests/trainer/test_review_dashboard_ui_contract.py                      EXIT=0
tests/trainer/test_review_hero_actual_result.py                         EXIT=0
tests/trainer/test_review_inbox_ui_contract.py                          EXIT=0
tests/trainer/test_site_release_identity.py                             EXIT=0
tests/trainer/test_smoke_orchestration_contract.py                      EXIT=0
tests/trainer/test_source_prior_unconditioned_contract.py               EXIT=0
tests/trainer/test_spotlab_subviews_contract.py                         EXIT=0
tests/trainer/test_trainer_analysis_state_contract.py                   EXIT=0
tests/trainer/test_trainer_d6_exposure_contract.py                      EXIT=0
tests/trainer/test_trainer_hero_ranges.py                               EXIT=0
tests/trainer/test_trainer_latency_contract.py                          EXIT=0
tests/trainer/test_trainer_parallel_review_contract.py                  EXIT=0
tests/trainer/test_trainer_preload_contract.py                          EXIT=0
tests/trainer/test_trainer_result_cache_contract.py                     EXIT=0
tests/trainer/test_trainer_rng_determinism.py                           EXIT=0
tests/trainer/test_trainer_smoke_determinism_contract.py                EXIT=0
tests/trainer/test_trainer_static.py                                    EXIT=0
```

## (11) Pré-vol hors navigateur au HEAD édité `eb1d117` — l'édition CSS de la coque sous contrôle d'idempotence

Cette section est **strictement additive** : elle consigne l'exécution **réelle**,
commande par commande et **sans rien pousser**, des étapes **non-navigateur** des
**deux workflows gelés** au HEAD du worktree de cette task,
**`eb1d117a7a1070b53bc034109c57ecae987501f5`**
(`chore(n8n): task backlog-wix for issue #394`), qui porte l'**édition CSS**
`70dc732` (task `backlog-qyb`) : la règle responsive
`@media(min-width:901px) and (max-height:900px){ .matrix{gap:2px} .cell{height:26px} }`
ajoutée au bloc `<style>` de `site/index.html` (compression du budget vertical du
panneau « Range adverse » à 1366x768). C'est **cette édition** que le pré-vol met
sous contrôle d'idempotence : un patch qui ré-ancre une insertion dans un octet
modifié peut devenir non idempotent, et c'est exactement le mode d'échec qui avait
rendu l'étape `contract` rouge à `8ff970b` (§ 8).

Les deux workflows gelés concernés sont
`.github/workflows/trainer-smoke.yml` (job `static-contract`, plus son job
`browser-smoke` **non exécutable ici**) et
`.github/workflows/hero-range-editor.yml` (job `contract`). Cette section
**n'affirme aucun `PASS` de job gelé** : un pré-vol local n'est pas un run CI
distinct des octets livrés.

### (11.1) Octets sous contrôle au HEAD `eb1d117`

```
$ git rev-parse HEAD
eb1d117a7a1070b53bc034109c57ecae987501f5
$ sha256sum site/index.html site/trainer.js site/trainer.css site/RELEASE.json
3ebf502135a52171ce3d63644d4966ebe765d4ad178edc2bd162848e6af35b3e  site/index.html
cfd91bbf1c4054d5e1720866486db23a146ff1fcae306758dad2e3fb7687e1a7  site/trainer.js
c99880520f6ee385ac3228a7a2fd239151874a05680975f97700bba9b8d8c07d  site/trainer.css
cd938cea75c508931b310ec70d5895ff5cef2b49a73bcc90b0615f44b237dd1f  site/RELEASE.json
$ git hash-object site/index.html site/trainer.js
75b26fb163960b06df00372c1f8be5598a968750
70490af692872b663a74ad1d2b180cefe9446568
$ git rev-parse HEAD:site/index.html HEAD:site/trainer.js
75b26fb163960b06df00372c1f8be5598a968750
70490af692872b663a74ad1d2b180cefe9446568
```

| Objet | `sha256` | blob Git | Égalité blob HEAD |
| --- | --- | --- | --- |
| `site/index.html` | `3ebf5021…f35b3e` | `75b26fb1…968750` | **oui** |
| `site/trainer.js` | `cfd91bbf…7687e1a7` | `70490af6…46568` | **oui** |
| `site/trainer.css` | `c9988052…b8d8c07d` | — | inchangé |

L'ancre `site/RELEASE.json` porte bien l'empreinte blob des octets édités :

```
$ python3 -c "import json;d=json.load(open('site/RELEASE.json'));print(d['identity']['assembled_site']['functional_files']['site/index.html']['git_blob_sha'])"
75b26fb163960b06df00372c1f8be5598a968750
```

### (11.2) Les commandes gelées (a)–(e) du job `static-contract`

Chaque commande est celle du workflow gelé, rejouée telle quelle depuis la racine
du dépôt. **Aucune n'est extrapolée** : le code de sortie est celui rendu par le
shell.

```
$ PYTHONPATH=. python3 tests/ci/test_repro_workflow_batch1.py
REPRO workflow batch-1 tests: 9 passed
EXIT=0
```

```
$ node --version && node --check site/trainer.js
v24.21.0
EXIT=0
```

```
$ python3 tools/write_site_release.py --check
release source anchor verified: site/RELEASE.json; assembled identity can be materialized
EXIT=0
```

```
$ for test in tests/trainer/test_*.py ; do python3 "$test" ; done
… 49 modules …
MODULES=49 FAILS=0
```

La boucle compte désormais **49** modules (contre 48 en § 10) : les deux modules
ajoutés depuis — `tests/trainer/test_smoke_orchestration_contract.py` (task
`backlog-eit`, commit `57b86f2`) et
`tests/trainer/test_spotlab_range_fit_contract.py` (task `backlog-wix`, commit
`eb1d117`, le contrat qui recalcule la géométrie de la coque depuis les octets
livrés) — sont **inclus dans la boucle** et sortent `EXIT=0`. Le détail
module-par-module est en annexe (11.8).

| Commande | Sortie observée | `EXIT` |
| --- | --- | --- |
| (a) `PYTHONPATH=. python3 tests/ci/test_repro_workflow_batch1.py` | `REPRO workflow batch-1 tests: 9 passed` | `0` |
| (b) `node --check site/trainer.js` | `v24.21.0` — aucune sortie d'erreur | `0` |
| (c) `python3 tools/write_site_release.py --check` | ancre vérifiée, identité matérialisable | `0` |
| (d) `for test in tests/trainer/test_*.py ; do python3 "$test" ; done` | 49 modules, 0 échec | tous `0` |

### (11.3) Étape d'idempotence des patches (e) et (f)

**(e) `tools/patches/apply_trainer_mvp.py`** — l'étape « Patch idempotence » du
job `static-contract` :

```
$ sha256sum site/index.html site/trainer.js > /tmp/before.sha
$ python3 tools/patches/apply_trainer_mvp.py
trainer MVP integration patch applied
EXIT=0
$ sha256sum site/index.html site/trainer.js > /tmp/after.sha
$ diff -u /tmp/before.sha /tmp/after.sha
EXIT=0
```

**(f) `tools/patches/apply_hero_range_editor.py`** — l'étape « Main application
integration is idempotent » du job `contract` de
`.github/workflows/hero-range-editor.yml`, **celle qui était rouge à `8ff970b`**
(§ 8 et § 9) :

```
$ sha256sum site/index.html > /tmp/hero-before.sha
$ python3 tools/patches/apply_hero_range_editor.py
/home/…/site/index.html
EXIT=0
$ sha256sum site/index.html > /tmp/hero-after.sha
$ diff -u /tmp/hero-before.sha /tmp/hero-after.sha
EXIT=0
```

Le marqueur de garde `id="heroRangesOpenBtn"` est présent **exactement une fois**
et `id="trainerOpenBtn"` également, donc `patch_text()` retourne le texte
inchangé : **aucun octet n'est écrit**, les empreintes encadrantes sont égales et
le `diff -u` — la comparaison exacte du workflow — retourne `EXIT=0`.

### (11.4) Idempotence byte-identique sur les octets édités — synthèse

| Fichier | `sha256` avant | `sha256` après | Byte-identique |
| --- | --- | --- | --- |
| `site/index.html` (patch trainer MVP) | `3ebf5021…f35b3e` | `3ebf5021…f35b3e` | **oui** |
| `site/trainer.js` (patch trainer MVP) | `cfd91bbf…7687e1a7` | `cfd91bbf…7687e1a7` | **oui** |
| `site/index.html` (patch Hero range editor) | `3ebf5021…f35b3e` | `3ebf5021…f35b3e` | **oui** |

Les deux patches impriment leur message de succès et **n'écrivent aucun octet**
sur ces sources : l'édition CSS `70dc732` **n'a pas introduit de régression
d'idempotence**, et l'arbre n'a eu besoin d'**aucune** restauration.

**Étapes non-navigateur supplémentaires** du job `contract` de
`.github/workflows/hero-range-editor.yml` (pour mémoire, le workflow étant gelé et
susceptible d'être relancé) :

```
$ node --check site/hero-ranges.js
EXIT=0
$ node --check site/hero-ranges-app.js
EXIT=0
$ node tests/hero_ranges/test_hero_range_repository.mjs
Hero range repository contract: PASS (2 legacy ranges, 3 contexts, hero range editor patch idempotent)
EXIT=0
```

### (11.5) La cible CSS est bien dans les octets servis (statique)

`site/index.html` est l'asset exact que le serveur statique des jobs sert. La
règle responsive de l'édition CSS y est présente **une fois** :

```
$ grep -n 'min-width:901px) and (max-height:900px)' site/index.html
121:  @media(min-width:901px) and (max-height:900px){
```

Trois observations statiques, **sans navigateur**, corroborent que la cible est
bien dans les octets servis et non absente :

1. la règle est dans les **octets du fichier** `site/index.html`
   (`sha256 3ebf5021…f35b3e`), donc dans ce que le serveur statique sert ;
2. `python3 tools/write_site_release.py --check` **recalcule** l'identité depuis
   ces octets et sort `EXIT=0` (blob `75b26fb1…` = celui de
   `git rev-parse HEAD:site/index.html`) ;
3. `tests/trainer/test_spotlab_range_fit_contract.py` **recalcule** la géométrie
   de la coque depuis ces mêmes octets (13 rangées × hauteur de cellule + 12
   gouttières) et **échoue si la règle disparaît** ou si le budget de la coque
   est gonflé jusqu'à ne plus discriminer la grille non compressée.

Un contrôle **de transport** (fetch HTTP en boucle locale) a été **tenté** et
**bloqué** par le bac à sable de ce worker (`urlopen` →
`URLError [Errno 1] Operation not permitted` ; `curl` → `EXIT=7`), et non par le
dépôt : je le consigne **tel quel** et ne le présente pas comme une preuve
négative. La cible est prouvée présente dans les **octets du fichier servi** ; sa
présence **après transport HTTP** relève du job gelé et n'est pas revendiquée ici.

### (11.6) Moitié NON couverte : `browser-smoke` aux deux viewports

Ce pré-vol **ne couvre pas** — et ne prétend pas couvrir — la moitié navigateur
de l'acceptation #394. Restent **non observés localement** :

- l'**absence de défilement global** (`document.scrollingElement.scrollHeight <=
  clientHeight`) pour les **six modes** `home`, `spotlab`, `review`, `replayer`,
  `training`, `strategy`, **aux deux viewports de référence** `1500x1000` et
  `1366x768` ;
- l'**atteignabilité réelle** des panneaux Spot Lab, Replayer et Trainer (les
  hit-tests de panneaux à `1366x768` nommés par la revue humaine) ;
- le **clic réel** du raccourci Accueil `#homePage a[href="#historiesSection"]`,
  **non intercepté** — `tests/trainer/smoke_modes_desktop.py` exécute
  `await page.click('#homePage a[href="#historiesSection"]')`, sans `force=True`,
  sans `dispatch_event`, sans retry et sans skip.

Les commandes (a)–(f) et les étapes supplémentaires de (11.3) sont **statiques** :
aucune n'exécute un navigateur. Le **seul** canal qui observe ces trois points est
le job gelé `browser-smoke` de `.github/workflows/trainer-smoke.yml` (§ 7 et § 9),
plus le job `browser-smoke` de `.github/workflows/hero-range-editor.yml` pour
l'éditeur autonome. **Aucun `PASS` de ces jobs n'est écrit ici** : ils n'ont pas
été observés depuis ce worker.

### (11.7) Repli navigateur local : irréalisable sur cet hôte (constat observé)

Le repli navigateur est **irréalisable sur cet hôte**, et les raisons ont été
**vérifiées** ici, pas supposées :

```
$ python3 -c "import playwright"
ModuleNotFoundError: No module named 'playwright'
EXIT=1
$ python3 tests/trainer/smoke_modes_desktop.py
smoke_modes_desktop: Playwright is unavailable (ModuleNotFoundError("No module named 'playwright'")). …
EXIT=1
$ python3 tests/trainer/smoke_trainer.py
    from playwright.async_api import async_playwright
ModuleNotFoundError: No module named 'playwright'
EXIT=1
$ ~/.cache/ms-playwright/chromium-1187/chrome-linux/chrome --version
…/chrome: error while loading shared libraries: libnspr4.so: cannot open shared object file: No such file or directory
EXIT=127
$ ~/.cache/ms-playwright/chromium_headless_shell-1187/chrome-linux/headless_shell --version
…/headless_shell: error while loading shared libraries: libnspr4.so: cannot open shared object file: No such file or directory
EXIT=127
$ ldconfig -p | grep -Ei 'libnspr4|libnss3'
NO libnspr4/libnss3 in ldconfig cache
$ timeout 8 curl -sS https://pypi.org/simple/
curl: (6) Could not resolve host: pypi.org
EXIT=6
```

Chromium **pinné** (révision `1187`, `140.0.7339.16`, cf.
`reproducibility/browser-identity.lock.json`) est **présent** dans le cache mais
**ne démarre pas** : il manque `libnspr4.so` et `libnss3.so`, absents de l'hôte.
Le module Python `playwright` est **absent**, et le **réseau/DNS** est **coupé**
(`curl` `EXIT=6`), donc ces bibliothèques **ne peuvent pas être installées ici**.
Le bac à sable refuse en outre la boucle locale (`EXIT=7`), ce qui exclut même un
serveur statique de repli. Conclusion : aucun smoke navigateur n'est exécutable
localement, et **la seule autorité reste le run des jobs gelés sur un HEAD
poussé**.

### (11.8) Conséquence sur les jetons, arbre intact, et clôture

La condition de bascule de § 9 n'est **pas** remplie : ce pré-vol local ne
remplace pas un run CI poussé. Donc, **inchangés** :

- `ci_green` reste **`NOT_OBSERVED`** ;
- `frozen_job_rerun_required` reste **`true`** : le job gelé `browser-smoke` doit
  tourner sur les octets livrés ;
- `contract_job_rerun_required` reste **`true`** : l'étape d'idempotence du job
  `contract` est rouge au HEAD poussé `8ff970b`, sa correction n'y est pas — mais
  elle est **verte localement** sur les octets édités (11.4) ;
- `red_workflows` **nomme** toujours le workflow rouge réellement observé,
  `.github/workflows/hero-range-editor.yml` (job `contract`, run `36081969061`,
  étape « Main application integration is idempotent »).

Après les deux essais d'idempotence, l'arbre est **intact** (les patches
n'avaient rien écrit, aucune restauration n'a donc été nécessaire). Mesuré
**avant** l'écriture de ce rapport :

```
$ git status --porcelain
                 # vide — aucun fichier modifié par les patches
$ diff <(git hash-object site/index.html site/trainer.js) <(git rev-parse HEAD:site/index.html HEAD:site/trainer.js)
IDENTICAL        # EXIT=0
```

En **fin de cette task** (rapport écrit), l'unique entrée de `git status` est ce
rapport, et la vérification finale d'ancre sort `EXIT=0` :

```
$ git status --porcelain
 M docs/issue-394-release-identity-ci-report.md
$ python3 tools/write_site_release.py --check
release source anchor verified: site/RELEASE.json; assembled identity can be materialized
EXIT=0
$ python3 tools/check_issue394_stale_claims.py
issue-394 stale claims guard: PASS (1052 versioned text files scanned, 4 claims)
```

Cette section n'écrit **aucun octet** de `site/**`, de `.github/**`, de `tests/`
ni d'outils ; elle est strictement additive au rapport. Elle ne peut pas citer le
`sha256` de son propre blob (auto-référence) ; le worker ne commit ni ne pousse,
l'orchestrateur gère le commit et la PR.

#### (11.8.1) Annexe — les 49 modules de la boucle gelée (tous `EXIT=0`)

```
tests/trainer/test_action_sizing_ev_presentation.py                     EXIT=0
tests/trainer/test_advanced_import_central_ui_contract.py               EXIT=0
tests/trainer/test_analysis_state_consistency_contract.py               EXIT=0
tests/trainer/test_analysis_state_mirror_contract.py                    EXIT=0
tests/trainer/test_appview_no_recompute_contract.py                     EXIT=0
tests/trainer/test_auxiliary_scale_surfaces_contract.py                 EXIT=0
tests/trainer/test_d6_render_matrix_contract.py                         EXIT=0
tests/trainer/test_decision_summary_contract.py                         EXIT=0
tests/trainer/test_delta_ev_primary_contract.py                         EXIT=0
tests/trainer/test_deployment_metadata.py                               EXIT=0
tests/trainer/test_desktop_accessibility_contract.py                    EXIT=0
tests/trainer/test_hh_import_ux_contract.py                             EXIT=0
tests/trainer/test_implicit_review_context.py                           EXIT=0
tests/trainer/test_known_hand_override_contract.py                      EXIT=0
tests/trainer/test_leak_training_ui_contract.py                         EXIT=0
tests/trainer/test_local_persistence_ux_contract.py                     EXIT=0
tests/trainer/test_model_b_robustness_ui_contract.py                    EXIT=0
tests/trainer/test_opponent_analysis_state_contract.py                  EXIT=0
tests/trainer/test_opponent_range_display_contract.py                   EXIT=0
tests/trainer/test_opponent_range_semantics_rework_contract.py          EXIT=0
tests/trainer/test_posterior_state_contract.py                          EXIT=0
tests/trainer/test_preflop_runtime_contract.py                          EXIT=0
tests/trainer/test_prior_posterior_ui_contract.py                       EXIT=0
tests/trainer/test_product_architecture_contract.py                     EXIT=0
tests/trainer/test_product_identity_ux_contract.py                      EXIT=0
tests/trainer/test_range_display_docs_contract.py                       EXIT=0
tests/trainer/test_range_vocabulary_contract.py                         EXIT=0
tests/trainer/test_replayer_actor_comment_semantics.py                  EXIT=0
tests/trainer/test_replayer_analysis_state_contract.py                  EXIT=0
tests/trainer/test_replayer_hand_class.py                               EXIT=0
tests/trainer/test_replayer_modal_prior_states.py                       EXIT=0
tests/trainer/test_review_dashboard_ui_contract.py                      EXIT=0
tests/trainer/test_review_hero_actual_result.py                         EXIT=0
tests/trainer/test_review_inbox_ui_contract.py                          EXIT=0
tests/trainer/test_site_release_identity.py                             EXIT=0
tests/trainer/test_smoke_orchestration_contract.py                      EXIT=0   # nouveau depuis § 10
tests/trainer/test_source_prior_unconditioned_contract.py               EXIT=0
tests/trainer/test_spotlab_range_fit_contract.py                        EXIT=0   # nouveau depuis § 10
tests/trainer/test_spotlab_subviews_contract.py                         EXIT=0
tests/trainer/test_trainer_analysis_state_contract.py                   EXIT=0
tests/trainer/test_trainer_d6_exposure_contract.py                      EXIT=0
tests/trainer/test_trainer_hero_ranges.py                               EXIT=0
tests/trainer/test_trainer_latency_contract.py                          EXIT=0
tests/trainer/test_trainer_parallel_review_contract.py                  EXIT=0
tests/trainer/test_trainer_preload_contract.py                          EXIT=0
tests/trainer/test_trainer_result_cache_contract.py                     EXIT=0
tests/trainer/test_trainer_rng_determinism.py                           EXIT=0
tests/trainer/test_trainer_smoke_determinism_contract.py                EXIT=0
tests/trainer/test_trainer_static.py                                    EXIT=0
```

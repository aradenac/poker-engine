# Décision #421 — modèle de réponse adverse préflop généralisé

- Issue : #421 (parent #314, aval #367)
- Décision terminale : `RETAIN_REFERENCE_GENERALIZATION_INSUFFICIENT`
  (protocole `RETAIN_ACTIVE_REFERENCE`, 8/10 critères gelés)
- Candidat : `generalized-adverse-response-candidate-v1`
  (`regularized_multinomial_spline`, payload canonique
  `c3f3573f3e80b3f7889dc8b1fd6f1948daeea95effc5a41a5d707385c4eed7dc`, octets
  `ea93e8c35e2604debd943495474cdb9262d724efb4a5caefe3723b53f23a59e7`), **non
  admis**, non promu, non câblé à #367
- Gates en échec : `non_inferiority_vs_active_model_a_preflop_population`,
  `calibration_within_frozen_ceiling`
- `validation_consumed` = `true` (lecture unique gelée, `validation_reads` = 1) ;
  `test_consumed` = `false` ; `active_pointer_mutated` = `false` ;
  `issue367_authorized` = `false` ; `next_issue` = `367` (jamais lancé ici)

## Ce qui est décidé

Le lookup de cellules exactes de Model A est remplacé par une fonction apprise
`P(FOLD|CALL|RAISE|JAM | contexte public avant action, prix, stack, history,
sizing demandé)`, évaluée directement au contexte demandé (aucun nearest-price /
nearest-context / representative-price / legal-minimum, aucune imputation de main
cachée), avec masquage des actions illégales, canal de sizing conditionnel légal
et gate OOD/incertitude fail-closed. Le candidat est retenu comme référence
scientifique, pas comme modèle actif : le modèle admis pour #367 reste
`model-a-preflop-sizing-aware-candidate-v2`.

## Résultats one-shot (VALIDATION, 11538 décisions in-scope / 2324 mains)

- Couverture totale `1.0` (seuil gelé `>= 0.5`) ; LIMPER_VS_ISO `1.0` (364/364) ;
  LIMPER_VS_ISO_CALLERS `1.0` (370/370) ; abstention `0.0`.
- Log loss `1.2689828317` vs actif v5 `1.2677704885` vs baseline priors
  `1.33567312` ; delta apparié vs actif `+0.0012123432`, IC95%
  `[-0.0046920887, +0.0069549188]` → **non-infériorité vs actif NON satisfaite**.
  vs #352 v2 `+0.006683435` (IC95% `[+0.0009497274, +0.0122203446]`) ; vs
  architecture alternative `-0.0128461418` (IC95% `[-0.0194064333,
  -0.0086878096]`, marge `0.005`, PASS) ; vs priors `-0.0666902883` (PASS).
- Calibration : ECE candidat `0.0362278552` (plafond absolu `0.05` respecté),
  mais delta vs actif `0.0214846158` > plafond gelé `0.02` → **échec**.
- Strates : exacts fréquents 87.10 % (log loss 1.2958, ECE 0.0372), exacts rares
  10.57 % (1.0316, ECE 0.0536), exact absent mais in-domain 2.32 % (1.3427,
  ECE 0.0949), exact absent hors domaine 0 %. Les strates rares et non
  exactement vues sont répondues par la fonction apprise, pas par abstention :
  la couverture n'est pas un artefact de lookup.
- Gate OOD (calibré TRAIN/CV seulement, `validation_consumed=false`) : statuts
  `MODEL_SUPPORTED` / `MODEL_SUPPORTED_HIGH_UNCERTAINTY` / `MODEL_OOD_ABSTAIN`,
  parts out-of-fold 0.790417 / 0.20925 / 0.000333 ; extrapolation stack/prix/
  sizing et catégorie jamais vue ⇒ abstention ; contexte exact absent mais
  in-domain ⇒ haute incertitude, jamais abstenu par définition.
- Sizing conditionnel : 7/7 frontières #388/#419 résolues, 0 fail-closed,
  27627 sizings générés dont 0 illégal (plafond gelé `0.0`). Depuis `backlog-jj0`,
  une cible de raise hors fenêtre légale sur un contexte répondable est refusée
  en fail-closed (`ILLEGAL_SIZING_GENERATED`) au lieu d'être conditionnée sur un
  gain clampé sans signal, et chaque document déclare `sizing_window`.

## Preflight #367 (preuve, pas exécution)

`ISSUE367_PREFLIGHT.json` parcourt les 38 nœuds du scénario #321 et les 7
frontières de sizing via le runtime provider : 38 évaluations directes, 0
abstention explicite, aucun lookup voisin, `hero_ev_executed=false`,
`issue367_executed=false`. Consommation #367 `FORBIDDEN` (outcome de rétention) :
aucun run ISO EV, aucune extension de grille de support, aucun câblage provider.

## Artefacts persistés et content-addressed

Les dix artefacts exigés par le ticket sont persistés et adressés par contenu
dans `analysis/issue421_generalized_response/sha256/`, indexés par
`analysis/issue421_generalized_response/ARTIFACTS.json` (index non auto-adressé) :

| artefact | SHA256 octets |
| --- | --- |
| GENERALIZED_RESPONSE_MODEL_SPEC.json | `486ef55e14cdc1160faef7e53ac29631f1e13a9953b4f4996a8b3b052b185abf` |
| TRAIN_CV_REPORT.json | `43d9fffff98aeae1f51d0bdd78647a2dedbd58403a0591433d22840a5cf996ff` |
| CANDIDATE_MANIFEST.json | `06f8380ea898d41efc9f7dbe65968292fd1277fe750229e0059b4df5918f8fea` |
| FROZEN_VALIDATION_PROTOCOL.json | `ff91421b372dab869b8603fac04e7cb15b4b810f4c742c0fff4139786d97cdd5` |
| VALIDATION_RESULT.json | `6a8f02b6ea92d2906f9681684f572926601d6bab7bd78bb14bc8efd424f516c3` |
| OOD_CALIBRATION_REPORT.json | `a8f1b181f0d3ff3fd48dd3d58181a844760409f036e0b11f440ff7553dfc0b71` |
| RAISE_SIZING_MODEL_REPORT.json | `955b926a5d19efe4998abfeae416792f85284d167cfaf9306315cb639320e9f6` |
| ISSUE367_PREFLIGHT.json | `4b7c757f9f4bd8f2aac83d2ec1f4106dbb67a4ab5a5df31c30c02fbdac9cb7d1` |
| DECISION.json | `8783fbc871853821270ed5fe92cda22a8e69c229af557383894c883d507211ea` |
| SUMMARY.md | `0c0a2031e7e4649a75af866ab3e705db1204b51397443dce953817b2cc61a7ba` |

Les copies `sha256/<digest>.json|.md` sont régénérées avec ces digests et les
objets devenus orphelins (l'ancien `16d8b75d….json`, ainsi que les copies
obsolètes de la spec et du résumé) sont purgés : aucun digest n'est édité à la
main. Le dernier incrément (#421 `backlog-jj0`, fenêtre légale explicite) a
rejoué la même chaîne : le module runtime a changé, donc la préflight et les
dix artefacts ont été régénérés, et les anciens objets `sha256/4d392697….json`,
`68b014cd….json` et `4c73491a….md` ont été remplacés par les digests ci-dessus.
Le nouveau module runtime
(`tools/preflop/generalized_response_runtime.py`,
`af585fa50e04be4c848dc77db1bd28417eb536eee486aa0cfd5fcd4f95e6e361`) déclare la
fenêtre légale de la cible de raise et refuse en fail-closed
(`ILLEGAL_SIZING_GENERATED`) une cible hors fenêtre sur un contexte
autrement répondable ; la distribution in-window est inchangée, bit à bit
(`analysis/issue421_generalized_response/IN_WINDOW_PREDICTION_REFERENCE.json`).

## Provenance indépendante de l'environnement

Depuis le correctif de provenance du runtime, chaque chemin enregistré par la
preflight est un chemin POSIX relatif au dépôt, jamais un chemin absolu d'hôte :
`evidence_bindings.runtime_module_path` (`tools/preflop/generalized_response_runtime.py`,
`af585fa50e04be4c848dc77db1bd28417eb536eee486aa0cfd5fcd4f95e6e361`) et chaque
`registry_source` (`analysis/issue421_generalized_response/CANDIDATE_MANIFEST.json`)
sont désormais identiques sur tout hôte et dans tout worktree. Les artefacts
régénérés ne contiennent plus aucune occurrence de `/home/`, et
`evidence_bindings.runtime_module_sha256` est recalculé depuis le module gelé au
lieu d'être hérité d'une exécution précédente. La décision terminale reste
inchangée : `RETAIN_REFERENCE_GENERALIZATION_INSUFFICIENT`.

`GENERALIZED_RESPONSE_MODEL_SPEC.json` est la pièce que le ticket exigeait et
qu'aucune autre tâche n'émettait : une projection déterministe des preuves
gelées (identité, contrat d'entrée, représentation, estimateur, gate OOD, sizing,
calibration, validation one-shot, frontière), sans nouvel entraînement ni lecture
holdout. Son digest propre vit dans
`GENERALIZED_RESPONSE_MODEL_SPEC.sha256` et dans l'index, jamais dans son payload.

Tous les digests persistés sont recalculés depuis les octets persistés et
comparés aux valeurs déclarées : 5 sidecars `.sha256` et 36 références croisées
inter-artefacts (manifeste, protocole, résultat de validation, décision,
preflight), toutes concordantes
(`digest_verification.all_recomputed_digests_match_persisted = true`). Le cas
#352 (digest self-reporté non revérifié) ne se reproduit pas ; un écart est
fail-closed à la génération comme sous `--check`.

## Frontières

- `TEST_CONSUMED=false` : TEST refusé par le builder, le runtime et les
  self-scans ; 2449 mains TEST intactes.
- `ACTIVE_POINTER_MUTATED=false` : pointeurs actifs Model A
  (`training/models/preflop_population_model_v5.json`,
  `ff952055ca4ee051a3ac9607d513fdecac0a320a31f658ecfd8a11d8448975ca`) et Model B
  inchangés, registres inchangés, aucune promotion.
- `VALIDATION_CONSUMED=true` une seule fois, après gel du protocole ; aucun
  seuil, prior ou critère modifié après la lecture.
- Doc normative associée : `docs/generalized-opponent-response-model.md`.

Reproduce: `python3 tools/training/build_issue421_evidence_bundle.py` ;
verify: `python3 tools/training/build_issue421_evidence_bundle.py --check` ;
guard: `python3 tests/training/test_issue421_evidence_bundle.py`.

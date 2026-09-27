# Décision #423 — routeur de réponse préflop hybride

- Issue : #423 (parent #314, aval #367)
- Décision terminale : **`RETAIN_REFERENCE_HYBRID_INSUFFICIENT`**
  (4/5 critères gelés satisfaits ; l'unique critère en échec est
  `SPARSE_ECE_CEILING`)
- Issue de repli / d'admission : `ADMIT_HYBRID_ROUTER_FOR_ANALYSIS` (les deux
  seuls outcomes terminaux valides) — non atteint
- Bundle content-addressed : `analysis/issue423_hybrid_router/`
  (`HYBRID_ROUTER_SPEC.json`, `TRAIN_CV_ROUTER_REPORT.json`,
  `SPARSE_STRATA_COMPARISON.json`, `GENERALIZED_CALIBRATION_REPORT.json`,
  `ROUTER_MANIFEST.json`, `ISSUE367_PREFLIGHT.json`, `DECISION.json`,
  `SUMMARY.md`) ; `DECISION.json` octets
  `fdca3922726b0feee166aac31f585c6305e5687f0243581389e1dbe258862abd`, payload
  canonique `cf8a506d44033e477c3b4147c2a3b02395529715510642359b63a2b71d099e95`
- Doc normative associée : `docs/hybrid-response-router.md`

## Décision terminale

Le routeur hybride compose deux canaux de réponse adverse préflop (le modèle de
population **actif** à support exact fort et le canal **généralisé** appris de
#421) derrière un sélecteur fail-closed à trois sources
(`ACTIVE_STRONG_SUPPORT` / `GENERALIZED_SPARSE_IN_DOMAIN` / `OOD_ABSTAIN`). Sur
le score **TRAIN-only**, cross-fitté et groupé par main, il passe 4/5 critères
d'admission gelés et échoue `SPARSE_ECE_CEILING` :

- la référence Model A active est **retenue** ;
- #367 **garde son modèle actuellement admis** (`model-a-preflop-sizing-aware-candidate-v2`) ;
- aucun provider n'est câblé, aucune EV Hero n'est calculée, aucune promotion
  n'a lieu.

`decision_rationale` (extrait de `DECISION.json`) : « the hybrid router passes
4/5 frozen criteria but fails SPARSE_ECE_CEILING on the TRAIN-only cross-fitted
score; the active Model A reference is retained and #367 keeps its currently
admitted model ». Le critère gelé a été écrit **avant** le score terminal
(`ROUTER_CRITERIA_ORDER_GUARD`, `terminal_report_absent_at_freeze = true`,
`authored_before_terminal_score = true`) ; les valeurs numériques terminales
n'ont pas été persistées dans la spec (`terminal_numeric_values_persisted =
false`).

## Résultat par strate (TRAIN-only, cross-fitté, groupé par `hand_id`)

Surface : 94160 lignes sur 19016 mains, 5 folds (`derivation/CV_DERIVATION.json`,
octets `abbc09ec485fd59e9603455a82cd724afb3eaa0aec3c1f0245f530d249884ed2`).
VALIDATION et TEST sont refusés par le loader, le harnais, le gel des critères
et la préflight (`validation_consumed=false`, `test_consumed=false`).

Canaux du routeur : `ACTIVE_STRONG_SUPPORT=81185`,
`GENERALIZED_SPARSE_IN_DOMAIN=12966`, `OOD_ABSTAIN=9` ; couverture hybride
`0.999904`.

| canal | log loss (bits/décision) | ECE | couverture |
| --- | --- | --- | --- |
| `active_model_a` | 1.437454 | 0.17112 | 1.0 |
| `generalized_calibrated` | 1.215171 | 0.012032 | 1.0 |
| `hybrid_router` | 1.433096 | 0.166441 | 0.999904 |

Bootstrap apparié par main (hybride moins actif, négatif favorable au routeur) :
point `-0.004301`, IC95 `[-0.009648, +0.001598]`, quantile supérieur unilatéral
`0.000508` contre la marge gelée `0.001` → `GLOBAL_NON_INFERIORITY_MARGIN`
**PASS**.

**Strates gelées** (support fit-fold de la signature de contexte exacte :
`frequent_exact = support >= 20`, `rare_exact = 1 <= support < 20`,
`exact_absent_in_domain = support == 0` avec tous les labels mono-feature
observés, `exact_absent_out_of_domain = support == 0` avec au moins une valeur de
feature jamais vue) :

| strate | part | n | log loss hybride | ECE hybride | couverture hybride |
| --- | --- | --- | --- | --- | --- |
| `rare_exact` | 0.110737 | 10425 | 1.053151 | 0.024273 | 0.999808 |
| `exact_absent_in_domain` | 0.02705 | 2541 | 1.462743 | 0.040773 | 0.997644 |
| `frequent_exact` | 0.862213 | 81185 | 1.480957 | 0.194212 | 0.999988 |
| `exact_absent_out_of_domain` | 0.0 | 0 | n/a | n/a | 0.0 |

Support sparse poolé (`rare_exact`, `exact_absent_in_domain`) : 12966 décisions,
gain `0.167733` bits/décision (plancher `0.167` → `SPARSE_GAIN_FLOOR` **PASS**),
ECE sparse hybride `0.027507` contre la référence active `0.042629`, plafond
`0.02` → `SPARSE_ECE_CEILING` **FAIL** (le seul critère en échec). La strate
`exact_absent_out_of_domain` est vide sur la surface TRAIN naturelle (part
`0.0`) : l'abstention est exercée sur les sondes OOD synthétiques.

**Famille `LIMPER_VS_ISO`** (2614 mains, surface propre) : log loss hybride
`1.000974` vs actif `1.031822` vs généralisé `1.008978`.

## Marges et seuils gelés (`ROUTER_MANIFEST.json`, `HYBRID_ROUTER_SPEC.json`)

Bloc de critères canonique
`e9f1ebc48fe384c2bf28fcb8d3359c54d1faa318dda42a0a518d48bb1be037e2` ; manifeste
octets `c7c63cc89f76184d974b9764358311b0dc115e9167e8ab230e84e6389381fd99` ;
spec octets `15c14c4ad0acddc65e240673cf8d148e2cd40dfb3d6fc43170ab8c2bb814d075`.
Les constantes de pré-enregistrement sont gelées
(`terminal_evaluation_derived=false`) :
`NON_INFERIORITY_CONFIDENCE_LEVEL=0.95`,
`NON_INFERIORITY_UPPER_QUANTILE=0.95`, `NON_INFERIORITY_ALPHA=0.05`,
`BOOTSTRAP_SAMPLES=2000`, `BOOTSTRAP_SEED=423`,
`Z_ONE_SIDED_95=1.6448536269514722`, `MARGIN_MAX_BITS=0.0`,
`MARGIN_ANALYTIC_TOLERANCE_BITS=0.001`, `GAIN_FLOOR_BITS=0.0`,
`ECE_ABSOLUTE_CEILING=0.02`, `ECE_DELTA_CEILING=0.02`,
`FREQUENT_EXACT_MAX_DEGRADATION_BITS=0.0`, `MINIMUM_SPARSE_OBSERVATIONS=20`,
`FREQUENT_EXACT_MIN_SUPPORT=20`, `RARE_EXACT_MIN_SUPPORT=1`.

| critère gelé | comparateur | seuil | observé | résultat | justification |
| --- | --- | --- | --- | --- | --- |
| `GLOBAL_NON_INFERIORITY_MARGIN` | `<=` | `0.001` | `0.000508` | **PASS** | marge dimensionnée par la dispersion TRAIN mesurée ; `ceil_to_quantum(max(0.0, 0.000508), 0.001)` ; marges bootstrap `0.000508` et analytique `0.000338` concordantes à `0.00017 < 0.001` |
| `SPARSE_GAIN_FLOOR` | `>=` | `0.167` | `0.167733` | **PASS** | plancher = gain TRAIN déjà démontré arrondi **vers le bas** à la résolution `0.001` (`floor_to_quantum`) |
| `SPARSE_ECE_CEILING` | `<=` | `0.02` | `0.027507` (actif `0.042629`) | **FAIL** | plafond = `min(absolu 0.02, ECE actif + delta 0.02 = 0.062629)` ; terme liant `ECE_ABSOLUTE_CEILING` |
| `FREQUENT_EXACT_NON_DEGRADATION_BOUND` | `<=` | `0.0` | point `0.0`, quantile sup `0.0`, ci95 sup `0.0` | **PASS** | borne dérivée de la dispersion appariée de la strate, plafonnée à `FREQUENT_EXACT_MAX_DEGRADATION_BITS=0.0` |
| `OOD_ABSTENTION_CRITERION` | `==` | `1.0` | abstention `1.0`, couverture `0.0` (640/640) | **PASS** | `abstain(c) ssi hard_reasons(c) non vide` ; 160 sondes par type (`extrapolation_sizing`, `extrapolation_stack`, `missing_domain_axis`, `unseen_category`) |

## Bornes

- `TEST_CONSUMED=false` : TEST refusé par le loader, le harnais, le gel des
  critères et la préflight (`test_authorized=false`) ; splits refusés
  `['VALIDATION', 'TEST']` ; un split refusé est une erreur dure. Les 2449 mains
  TEST certifiées restent intactes.
- `VALIDATION_CONSUMED=false`, `validation_reopened=false` : le design, la
  calibration, les critères et le score terminal sont **TRAIN-only** ; le canal
  généralisé n'est jamais recalibré sur VALIDATION
  (`validation_recalibrated=false`, `validation_recalibration_refused=true`).
- **L'évidence #421 reste inchangée et n'est pas relue.** Le cycle #423 consomme
  le canal généralisé et la porte OOD gelés de #421 comme **historique
  descriptif** seulement ; il ne rouvre pas le split VALIDATION de #421 et ne
  re-fit/ne re-score jamais le candidat #421. Les artefacts #421 réutilisés sont
  liés par digest et laissés byte-identiques —
  `analysis/issue421_generalized_response/TRAIN_CV_REPORT.json`
  (`43d9fffff98aeae1f51d0bdd78647a2dedbd58403a0591433d22840a5cf996ff`) et
  `analysis/issue421_generalized_response/OOD_CALIBRATION_REPORT.json`
  (`a8f1b181f0d3ff3fd48dd3d58181a844760409f036e0b11f440ff7553dfc0b71`) — et le
  score TRAIN-only réutilise le dataset #421
  (`analysis/issue421_generalized_response/dataset/GENERALIZED_RESPONSE_DATASET.jsonl`,
  `4c18872fac5fc443e68e6f99feb0036509999f67f952c02e118671c7c72330a2`) sans lire
  aucune ligne holdout. La porte OOD réutilisée est
  `contracts/training/generalized-response-ood-gate.schema.json`
  (`99a6fe9c3eeb4b7f61db35f390115938799c8730d41fa0b8e62e4311023f0f1e`).
- `ACTIVE_POINTER_MUTATED=false` : pointeurs actifs Model A
  (`training/models/preflop_population_model_v5.json`,
  `ff952055ca4ee051a3ac9607d513fdecac0a320a31f658ecfd8a11d8448975ca`) et Model B
  (`training/models/postflop_population_model_v5.json`,
  `6d948f30f6c276ce41e70e83ac35275e30e7841e93e5b1da11782648c6b4d8ae`) inchangés,
  registres inchangés, aucune promotion (`automatic_promotion=FORBIDDEN`).
- `ISSUE367_EXECUTED=false` : la préflight
  (`ISSUE367_PREFLIGHT.json`,
  `8ab43718bc3132341667c89b48868b13587ebde5f959429e91123a237a251f0b`) parcourt les
  38 nœuds du scénario #321 et les 7 frontières de sizing (45 décisions visitées :
  43 évaluations directes, 2 abstentions explicites) via le provider runtime,
  mais `hero_ev_executed=false` et `issue367_executed=false`. L'issue terminale
  étant une rétention, l'admission #367 est `FORBIDDEN`
  (`ABSTAIN_BLOCKED_ADMISSION`) ; `next_issue=367` est enregistré `NOT_EXECUTED`
  et #367 garde son modèle actuellement admis. Aucune EV Hero, aucun rollout,
  aucune extension de grille de support.

## Séparation `ANALYSIS_ADMISSIBLE` vs `PRODUCT_ADMISSIBLE`

Le routeur ne décide que de l'**admissibilité d'analyse** : le booléen
`analysis_admissible` (`route_source != OOD_ABSTAIN` **et** probabilités légales
**et** `sizing_provenance` présent quand l'action sélectionnée est `RAISE`/`JAM`).
Il ne dit rien de la possibilité de montrer une décision à un utilisateur, de la
promouvoir, de la câbler dans un chemin produit ou d'agir dessus.

`PRODUCT_ADMISSIBLE` est **explicitement hors scope #423** et n'est jamais un
outcome terminal de cette décision (`boundaries.product_admissible=false`).
L'admissibilité produit est une question aval distincte, portée par d'autres
workstreams — la piste de sensibilité Model B (#315) et la couche de validation
temporelle prospective (#202) — et le routeur #423 ne la revendique pas et ne
s'y substitue pas.

## Intégrité des digests

Tous les digests persistés sont recalculés depuis les octets persistés (92
références croisées déclarées par les artefacts gelés + tous les sidecars
`.sha256`) et concordent
(`digest_verification.all_recomputed_digests_match_persisted=true`). Le cas #352
(digest self-reporté jamais revérifié) ne se reproduit pas ; un écart est
fail-closed à la génération comme sous `--check`. `ARTIFACTS.json` est un index,
pas un membre de l'ensemble adressé par contenu : il ne porte pas son propre
digest.

Reproduce : `python3 tools/training/build_issue423_evidence_bundle.py` ;
verify : `python3 tools/training/build_issue423_evidence_bundle.py --check` ;
guard : `python3 tests/training/test_issue423_evidence_bundle.py`.

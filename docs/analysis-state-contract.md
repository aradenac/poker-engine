# Contrat analysis-state `poker-analysis-state/v1`

Contrat canonique et versionné de l'état d'analyse partagé par Review
(Inbox/Dashboard), Replayer (Hero/adversaire) et Training. Le schéma de
référence est `contracts/analytics/analysis-state.schema.json` ; tout producteur
qui expose un état d'analyse vers l'utilisateur doit émettre un objet conforme à
ce schéma.

## Objet et portée

Le contrat remplace la notion floue de « couverture » par six états explicites
de premier niveau. Il sépare strictement les causes techniques et scientifiques
afin qu'une même étiquette utilisateur ne mélange plus :

- la possibilité de calculer ;
- l'existence d'un nœud / d'un contexte supporté ;
- le support statistique réel ;
- la comparabilité des EV ;
- l'admissibilité d'une recommandation ;
- la disponibilité d'une posterior de range ;
- une erreur de worker.

La version du contrat est portée par le champ `schema` (`poker-analysis-state/v1`)
et par l'`$id` du schéma. Toute évolution incompatible crée une nouvelle version
`poker-analysis-state/vN` ; les producteurs conservent la version qu'ils
émettent.

## États de premier niveau

Le champ `state` porte exactement l'un des six états suivants. Aucun autre état
de premier niveau n'est autorisé, et aucun libellé agrégé de type « couverture »
ne peut servir d'état.

| `state` | Signification utilisateur |
|---|---|
| `ANALYSE_DISPONIBLE` | Le calcul est terminé et la réponse demandée est exploitable. |
| `ANALYSE_PARTIELLE` | Une analyse existe mais une partie seulement est exploitable (comparabilité ou alternatives manquantes). |
| `CALCUL_EN_COURS` | Le calcul n'est pas terminé ; ce n'est pas une conclusion scientifique. |
| `DONNEES_INSUFFISANTES` | Le nœud existe mais le support statistique (observations / mains distinctes) est insuffisant. |
| `SPOT_NON_SUPPORTE` | Le modèle ne représente pas le contexte : nœud absent ou contexte hors domaine supporté. |
| `ERREUR_CALCUL` | Le worker a échoué ; l'erreur et sa rejouabilité vivent dans la dimension `error`. |

## Interdiction de « couverture » comme libellé principal

« couverture » n'est jamais un libellé principal utilisateur. Elle ne doit plus
apparaître dans un message de premier niveau, dans une colonne de statut ou dans
un filtre d'état. La couverture est une dimension de génération interne : elle
peut être conservée pour compatibilité, exposée dans la vue technique
secondaire, mais elle ne peut pas remplacer l'un des six états ci-dessus. Quand
une cause plus précise existe, aucun message générique du type « aucune analyse
disponible » ne doit être affiché : l'état de taxonomie et son `reason_codes`
doivent être émis à la place.

## Dimensions strictement séparées

Le schéma déclare les dimensions suivantes comme des champs obligatoires et
distincts. Aucune ne peut être déduite par défaut d'une autre ni fusionnée dans
le libellé principal.

- `state` — état utilisateur unique parmi les six ci-dessus.
- `reason_codes` — codes **machine-readable** stables (majuscules/underscores).
  Les codes détaillés ne sont affichés que dans la vue détails secondaire ; un
  code inconnu est préservé tel quel, jamais remplacé par un message générique.
- `computational_status` — `NOT_STARTED`, `PENDING`, `RUNNING`, `COMPLETE`,
  `FAILED`, `NOT_EVALUATED`. Distingue un calcul non terminé d'une conclusion
  scientifique ; `NOT_EVALUATED` est le statut fail-safe lorsque le producteur
  ne fournit pas la dimension.
- `model_support_status` — `SUPPORTED`, `NODE_ABSENT`, `CONTEXT_UNSUPPORTED`,
  `NOT_EVALUATED`. Distingue l'absence de nœud d'un contexte non supporté ;
  `NOT_EVALUATED` est le statut fail-safe par défaut.
- `statistical_support` — objet `{observations, distinct_hands}`. Le nombre de
  mains distinctes est séparé du nombre d'observations pour qu'une main répétée
  ne constitue pas un support. Les deux compteurs peuvent valoir `null` (ou le
  plancher fail-safe `0`) pour représenter un support inconnu / indisponible :
  ils ne sont jamais fabriqués à partir d'un autre compte (voir la règle
  d'agrégation Review Inbox ci-dessous).
- `ev_comparability` — objet `{comparable, reason}`. `comparable` n'est vrai que
  lorsque la ligne jouée et la recommandation sont évaluées sous la même
  référence admissible. Sans évidence de comparabilité, `comparable` vaut
  `false` et `reason` vaut `NOT_EVALUATED`.
- `recommendation_admissibility` — objet `{admissible, status, reason_codes}`.
  Seul `admissible` autorise l'exposition d'une recommandation ou d'une EV Hero.
  Sans évidence d'admissibilité, `admissible` vaut `false` et `status` vaut
  `NOT_EVALUATED`.
- `posterior_availability` — `conditioned`, `prior_uninformative`,
  `source_prior_unconditioned`, `degenerate`, `unavailable` (vocabulaire
  posterior de #391). Sans évidence de posterior, la valeur fail-safe est
  `unavailable` ; `conditioned` n'est jamais déduit de l'absence de blocker.
- `error` — objet `{type, retryable}`. `type` vaut `null` sans erreur ; une
  valeur non nulle marque une erreur de worker et `retryable` dit si la requête
  peut être rejouée.

## Fail-safe : dimensions non évaluées

Le mapper (`src/analytics/analysis-state.js`) est **fail-safe** : il ne défaut
jamais à `ANALYSE_DISPONIBLE` sur une entrée vide ou faible, et il ne fabrique
jamais une dimension positive faute d'évidence. Une dimension n'est promue
(`computational_status = COMPLETE`, `model_support_status = SUPPORTED`,
`ev_comparability.comparable = true`, `recommendation_admissibility.admissible =
true`, `posterior_availability = conditioned`) que si le producteur fournit une
**évidence positive explicite** pour cette dimension :

- `computational_status = COMPLETE` seulement sur un statut explicite ou une
  preuve terminale (code de raison, dimension évaluée, couverture `COVERED`) ;
- `model_support_status = SUPPORTED` seulement sur `model_support_status:
  SUPPORTED` ou une couverture `COVERED` explicite ;
- `ev_comparability.comparable = true` seulement sur une comparabilité
  explicitement évaluée et vraie ;
- `recommendation_admissibility.admissible = true` seulement sur une
  admissibilité explicitement évaluée et vraie ;
- `posterior_availability = conditioned` seulement sur une posterior
  explicitement conditionnée.

L'**absence de blocker n'est jamais une évidence** : une dimension manquante est
représentée explicitement par `NOT_EVALUATED` (statut/raison) ou `unavailable`
(posterior), jamais par une valeur optimiste. `ANALYSE_DISPONIBLE` n'est émis
que lorsqu'un signal positif explicite existe (code positif, couverture
`COVERED`, comparabilité ou admissibilité explicitement positives). Une entrée
vide retombe sur l'état sûr `DONNEES_INSUFFISANTES`, et le mapper reste
idempotent.

## Règle d'agrégation du support statistique (Review Inbox)

Le support statistique d'une main ne se déduit **jamais** du nombre de décisions
de review. Une main peut contenir plusieurs décisions comparables, chacune
adossée à un nœud de modèle distinct avec son propre `support.observations` ; ces
nœuds ne sont pas additifs. La couche canonique (`analysis_state`) applique donc
une règle d'agrégation hand-level conservatrice et déterministe, implémentée dans
`src/analytics/review-inbox.js` (`analysisStateFor`) :

- **décisions pertinentes** : décisions `support.covered === true` **et**
  `comparability.comparable === true`. Les décisions non supportées ou non
  comparables n'apportent aucun support modèle admissible et sont exclues ;
- **`observations`** : **minimum** des `event.support.observations` réels sur les
  décisions pertinentes. On ne somme jamais des nœuds hétérogènes et on
  n'utilise jamais le nombre de décisions comme proxy ;
- **support inconnu** : si aucune décision pertinente n'expose d'observations
  valides (entier >= 0), le support est **inconnu / indisponible**. Il est
  représenté par le plancher fail-safe `0` sous le contrat numérique actuel, et
  `null` reste autorisé par le schéma `review-inbox` pour cette sémantique ; un
  support positif n'est jamais fabriqué ;
- **`distinct_hands`** : `poker-leak-decision-event/v1` ne porte aucune preuve de
  mains distinctes. Le champ est donc explicitement indisponible (`0`/`null`) et
  n'est **jamais inventé à `1`**. Seule une preuve réelle ajoutée aux événements
  pourra l'alimenter.

Exemple normatif : une main à 2 décisions comparables adossées à 120 et 450
observations modèle donne `statistical_support.observations = 120` (minimum),
jamais `2` ni `570`.

## Les sept distinctions

Le contrat impose de distinguer explicitement les sept causes suivantes. Elles
ne doivent jamais être confondues ni regroupées sous un message unique.

1. **Calcul non terminé** — `state = CALCUL_EN_COURS`,
   `computational_status ∈ {NOT_STARTED, PENDING, RUNNING}`, codes
   `CALCULATION_PENDING`, `ANALYSIS_PENDING`, `UNFINISHED_DECISIONS`.
2. **Absence de node** — `state = SPOT_NON_SUPPORTE`,
   `model_support_status = NODE_ABSENT`, codes `NODE_ABSENT`,
   `EXACT_CONTEXT_ABSENT`, `SPOT_NON_COUVERT`, `UNCOVERED`.
3. **Support insuffisant** — `state = DONNEES_INSUFFISANTES`,
   `statistical_support` sous le seuil, codes `INSUFFICIENT_SUPPORT`,
   `LOW_SUPPORT`, `MISSING_HH_SOURCE`, `MISSING_REVIEW_SCORE`.
4. **Contexte non supporté** — `state = SPOT_NON_SUPPORTE`,
   `model_support_status = CONTEXT_UNSUPPORTED`, codes `CONTEXT_UNSUPPORTED`,
   `EXACT_CONTEXT_MISMATCH`, `ACTIVE_REFERENCE_SCOPE_UNSUPPORTED`,
   `POPULATION_MISMATCH`, `STRATEGY_MISMATCH`, `ARTIFACT_IDENTITY_MISMATCH`.
5. **Recommandation non admise** — `recommendation_admissibility.admissible =
   false`, codes `RECOMMENDATION_NOT_ADMISSIBLE`, `INVALID_GUIDANCE`,
   `NO_ADMISSIBLE_STRATEGY`, `PLAYED_ALTERNATIVE_NOT_EVALUATED`,
   `REVIEW_SCORE_INCOMPLETE`, `NO_DECISION_EVENTS`, `UNSUPPORTED_DECISIONS`.
6. **Erreur worker** — `state = ERREUR_CALCUL`, `error.type` non nul et
   `error.retryable` renseigné, codes `WORKER_ERROR`, `ANALYSIS_ERROR`.
7. **Analyse partielle** — `state = ANALYSE_PARTIELLE`, codes
   `PARTIAL_ANALYSIS`, `NON_COMPARABLE`, `NON_COMPARABLE_ALTERNATIVES`,
   `NON_COMPARABLE_DECISIONS`, `MISSING_COMPARABLE_EV`,
   `NO_COMPARABLE_REVIEW_DETAIL`, `ANALYSIS_MISSING`.

## Règle D5

D5 : les surfaces adverses exposent uniquement **l'action observée + le
support/likelihood + la range avant/après**. Aucune surface ne doit promettre
une « alternative EV optimale » ni une recommandation EV Hero pour l'adversaire.
La disponibilité de la range adverse est portée par `posterior_availability`, et
le support par `statistical_support` / `model_support_status`.

## Règle D6

D6 : les champs EV Hero (played/recommended/EV et champs associés) ne sont
exposés que si `recommendation_admissibility.admissible === true` **ET**
`ev_comparability.comparable === true`. Si l'une des deux conditions est fausse,
les champs EV Hero sont absents (ou `null`) et l'état utilisateur est dérivé de
la dimension bloquante (`ANALYSE_PARTIELLE`, `DONNEES_INSUFFISANTES`,
`SPOT_NON_SUPPORTE`, `CALCUL_EN_COURS` ou `ERREUR_CALCUL`).

## Reason codes

Les `reason_codes` sont machine-readable et stables. Le catalogue canonique est
déclaré dans `$defs.reason_code` du schéma. Les codes sont regroupés par les
sept distinctions ; ils peuvent être complétés par des codes historiques
(`coverage_state`, `FAIL_CLOSED_STATES`, codes Review/Inbox/Replayer) lors du
mapping. La règle de sûreté est : un code inconnu est conservé et l'état retombe
sur un état sûr, plutôt que d'être supprimé ou remplacé par un libellé
générique.

## Surfaces consommatrices

- **Review — Inbox** : filtre `analysis_state` explicite, reason codes en vue
  secondaire.
- **Review — Dashboard** : état dominant du périmètre dérivé de la même enum.
- **Replayer — Hero** : libellé de taxonomie en vue feed, D6 appliquée.
- **Replayer — adversaire** : D5 appliquée, jamais d'EV optimale promise.
- **Training** : libellés d'état issus de l'enum partagée, hors frontière
  flop-only documentée (#206).

Toutes ces surfaces doivent dériver leur état du même module et de la même enum
`poker-analysis-state/v1` ; le contrat inter-surfaces est vérifié par les tests.

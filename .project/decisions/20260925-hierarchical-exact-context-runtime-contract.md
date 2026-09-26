# Contrat runtime exact-context hiérarchique — doc normative — 2026-09-25

Decision owner: issue #419 (tâche `T12`). La référence normative est
`docs/hierarchical-exact-context-runtime-contract.md`. Ce document ne crée ni
modèle, ni fit, ni candidat, ni promotion, ni changement de provider : il fixe
la **sémantique** que les surfaces consommatrices doivent appliquer.

## Décision 1 — sémantique normative des trois statuts

Un statut unique, jamais de quatrième valeur ni de défaut implicite :

- `EXACT_EMPIRICAL_STRONG` — la clé fine demandée (`hierarchical_exact_key`,
  `L0_EXACT_KEY`) passe elle-même les deux seuils gelés (20 observations
  marginales et 20 mains distinctes) et l'estimation rapportée utilise
  `pooling.level == L0_EXACT_KEY` ;
- `EXACT_HIERARCHICAL_ESTIMATE` — la clé fine est sous le seuil mais un niveau
  parent déclaré le passe ; l'estimation est rétrécie vers ce parent, la
  provenance de pooling est rapportée, et ce n'est **jamais** une preuve de
  support exact ;
- `EXACT_UNRESOLVED` — aucun niveau ne passe, ou le sizing de raise de la
  branche est non résolu, ou la règle d'isolation serait violée : aucune action
  n'est émise, la branche et ses descendants restent non résolus.

Les seuils restent gelés à 20/20 et ne sont jamais abaissés pour clore l'arbre.

## Décision 2 — séparation stricte identité / pooling

L'identité et le support restent la clé fine `hierarchical_exact_key`
(`L0_EXACT_KEY`), en égalité de chaîne exacte. Le pooling est un mécanisme
**paramètres seulement** sur `L0..L4`, et seul `L0` peut être une source de
support. `SUPPORT_ISOLATION_NO_KEY_BORROWS_SUPPORT` est l'invariant normatif :
`support.source_key == requested_key`, sinon la réponse doit lever
`COARSE_KEY_SUPPORT_LAUNDERING` au lieu d'émettre. Une clé grossière peut
amorcer un prior, jamais certifier un support.

## Décision 3 — risque `RUNTIME_SUPPORT_CONTEXT_COARSE_MERGE`

Le risque est **contenu, pas résolu** : la clé runtime fusionne 38 clés fines en
30 clés grossières sur 8 groupes de collision, et le statut de la décision de
granularité reste `OPEN_FOR_367_SPEC_DOES_NOT_CHANGE_PROVIDER`. Conséquence
normative : un nœud dont le seul support qualifiant est à `L3` ne peut produire
qu'un `EXACT_HIERARCHICAL_ESTIMATE`, jamais un `EXACT_EMPIRICAL_STRONG`. La
cellule canonique BB face au SB `ISO@5` (45/45 à `L3`, 6/6 à `L0`) est une
estimation hiérarchique ; la cellule canonique CO après SB `ISO@5` / BB `FOLD`
(14/14 à `L3`, 4/4 à `L0`) reste `EXACT_UNRESOLVED`. Le risque ne se ferme que
si #367 expose les comptes par clé fine, ou résout à la clé fine.

## Décision 4 — conditions exactes de clôture de l'arbre #367

`required_tree_complete` est une conjonction : chaque nœud requis admet une
réponse exacte `EXACT_EMPIRICAL_STRONG` à `L0` (20/20), aucun frontier de sizing
de raise ne reste ouvert, l'énumération #388 est complète, aucune substitution
(nearest/representative/interpolated/legal-minimum/emprunt de support) n'est
appliquée, et aucun EV Hero n'est calculé. Au-delà, une consommation #367 exige
`ISSUE367_CONSUMES_ONLY_AN_ADMITTED_CANDIDATE` : verdict VALIDATION
`ADMIT_CANDIDATE` avec toutes les portes franchies, résultat content-addressed
avec `protocol_byte_sha256`, et nouvelle révision explicite du protocole #367
nommant le candidat. États courants : `required_tree_complete = false`
(0/38 admissibles, 31 `NO_ADMISSIBLE_POOLING_LEVEL`, 7
`RAISE_SIZING_UNRESOLVED_NO_NEAREST_PRICE`), 7/7 frontiers non résolus,
VALIDATION `RETAIN_ACTIVE_REFERENCE` (échecs `coverage_floor` et
`calibration_absolute`), décision terminale `UNRESOLVED_HIERARCHICAL_TREE_GAP`
(`BLOCKED_SCIENTIFIC`, `admitted = false`, `next_issue = 367`).

## Décision 5 — surfaces consommatrices et garde

`docs/model-a-posterior-runtime.md` et `docs/reviewer-preflop-iso-analysis.md`
renvoient au contrat : pas d'upgrade d'une estimation rétrécie en support exact,
pas d'EV ni de recommandation sur un nœud non résolu, niveau de pooling visible.
La conformité texte/artefacts est re-dérivée par
`tests/training/test_hierarchical_exact_context_contract_doc.py`. Le pointeur
Model A actif, les registres et le provider restent inchangés.

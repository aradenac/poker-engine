# Cause racine du rouge CI #421 — reproductibilité IEEE-754 du runtime gelé

- Issue : #421, tâche orchestrateur `backlog-8l8`
- Branche : `n8n/issue-421-construire-un-opponent-response-model-generalise-e`
  @ `0783c9d`
- Statut : **diagnostic de reproductibilité**. Décision scientifique sous-jacente
  **inchangée** (`RETAIN_REFERENCE_GENERALIZATION_INSUFFICIENT`) ; aucun
  artefact d'evidence, aucun digest et aucun module gelé n'est modifié.
- Verdict : le rouge CI **n'est pas** un défaut du modèle #421. C'est l'écart de
  sémantique de `sum()` entre l'interpréteur qui a figé les octets
  (CPython ≥ 3.12 : sommation compensée de Neumaier) et l'interpréteur du
  workflow (`.python-version` = `3.11.9` : sommation naïve gauche-droite).

## 1. Le rouge

Le workflow `.github/workflows/issue-421-generalized-response-model.yml`
sélectionne son interpréteur par `python-version-file: '.python-version'`
(ligne 150) → **`3.11.9`**. Trois assertions du job `contract` comparent des
octets/flottants figés et échouent sur un runner 3.11.9 :

| suite | test | assertion qui rougit |
| --- | --- | --- |
| `tests/preflop/test_generalized_response_sizing.py` | `InWindowReferenceTests.test_in_window_predictions_are_bit_for_bit_unchanged` | `json.dumps(recomputed, sort_keys=True) == json.dumps(persisted, sort_keys=True)`, **bit à bit**, sonde par sonde |
| `tests/simulation/test_issue421_preflight.py` | `Issue421Issue367PreflightTests.test_build_is_deterministic_and_reproducible` | `serialize(build()) == (OUTPUT_DIR / NAME).read_bytes()` |
| `tests/simulation/test_issue421_preflight.py` | `Issue421Issue367PreflightTests.test_persisted_preflight_is_content_addressed_and_check_passes` | `preflight_tool.check() == 0` (le sidecar ne se recompose plus) |

Les deux artefacts consommés sont figés et adressés par contenu :
`analysis/issue421_generalized_response/IN_WINDOW_PREDICTION_REFERENCE.json` et
`analysis/issue421_generalized_response/ISSUE367_PREFLIGHT.json` (+ leurs
`*.sha256` et leurs copies `sha256/<digest>.json`).

## 2. Mécanisme

`tools/preflop/generalized_response_model.py:554` `_normalize_legal()` masque les
actions illégales, normalise, puis **clôt exactement** la distribution :

```python
others = sum(probability[action] for action in legal[:-1])   # ligne 578
probability[legal[-1]] = max(0.0, 1.0 - others)              # ligne 579
```

et `predict()` publie `"probability_sum": sum(probabilities.values())`
(ligne 1394) ; le runtime publie `"probability_sum": float(sum(...))`
(`generalized_response_runtime.py:1090`).

Depuis **CPython 3.12**, `sum()` somme les flottants en **sommation compensée
de Neumaier** (changement documenté, `gh-100425`). Jusqu'à **3.11** — donc pour
`.python-version` = `3.11.9` — `sum()` accumule **naïvement, de gauche à
droite**. Sur les mêmes entrées, les deux sémantiques peuvent différer d'une
ULP : par exemple, pour le vecteur `others` de la sonde
`free_unopened_jam_effective_stack` (`0.5965385309561733 + 0.38381794802071395
+ 0.011200382019392878`), `sum()` compensé rend `0.99155686099628` et
l'accumulation naïve `0.9915568609962802`. La clôture
`probability[legal[-1]] = 1.0 - others` propage alors l'écart sur la dernière
action légale (`JAM`), et la division `raw / total` sur les autres.

Conséquence : les octets figés (issus d'un interpréteur compensé) et les octets
recalculés par CI (3.11.9, naïf) ne sont plus **bit à bit** identiques, alors que
la somme reste `1.0` et que `illegal_mass` reste `0.0` dans les deux cas — la
clôture garantit `sum == 1.0` exactement quelle que soit la sémantique. L'écart
n'est pas scientifique : il est de l'ordre de l'ULP, mais il suffit à faire
échouer des comparaisons volontairement exactes.

## 3. Vérification naive-sum (reproduite, résultat consigné tel quel)

On remplace `builtins.sum` par une accumulation naïve gauche-droite — la
sémantique de CPython ≤ 3.11 — puis on recalcule la préflight et les sondes
in-window et on compare aux octets figés. Commande de reproduction (depuis la
racine du dépôt, aucune dépendance supplémentaire) :

```bash
python3 - <<'PY'
import builtins
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))


def naive_sum(iterable, start=0):  # CPython <= 3.11 sum(): naive, left-to-right
    total = start
    for item in iterable:
        total = total + item
    return total


builtins.sum = naive_sum

spec = importlib.util.spec_from_file_location(
    "sizing", ROOT / "tests/preflop/test_generalized_response_sizing.py"
)
sizing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sizing)
from tools.simulation import issue421_issue367_preflight as preflight

reference = json.loads(sizing.REFERENCE_PATH.read_text(encoding="utf-8"))
fresh = sizing.in_window_reference_entries()
divergent = [
    entry["probe_id"]
    for entry, rebuilt in zip(reference["entries"], fresh)
    if json.dumps(rebuilt, sort_keys=True) != json.dumps(entry, sort_keys=True)
]
print("probes_total", len(reference["entries"]), "divergent", len(divergent), divergent)


def flatten(node, prefix=()):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from flatten(value, prefix + (str(key),))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from flatten(value, prefix + (str(index),))
    else:
        yield prefix, node


persisted = dict(
    flatten(json.loads((preflight.OUTPUT_DIR / preflight.NAME).read_text(encoding="utf-8")))
)
rebuilt = dict(flatten(preflight.build()[0]))
changed = [
    (key, persisted.get(key), rebuilt.get(key))
    for key in set(persisted) | set(rebuilt)
    if persisted.get(key) != rebuilt.get(key)
]
deltas = [
    abs(right - left)
    for _, left, right in changed
    if isinstance(left, (int, float))
    and isinstance(right, (int, float))
    and not isinstance(left, bool)
]
print(
    "leaves_total", len(persisted), "divergent", len(changed),
    "numeric", len(deltas), "max_abs_delta", max(deltas),
)
PY
```

Sortie brute obtenue (avec `sum` remplacé) :

```text
probes_total 9 divergent 5 ['free_unopened_jam_effective_stack', 'explicit_interval_jam_cap', 'vs_limpers_bb_raise_3bb', 'short_stack_raise_15bb', 'short_stack_jam_cap']
leaves_total 13845 divergent 77 numeric 44 max_abs_delta 2.220446049250313e-16
```

Mesures, telles que consignées :

- **5 sondes sur 9** divergent, exactement
  `free_unopened_jam_effective_stack`, `explicit_interval_jam_cap`,
  `vs_limpers_bb_raise_3bb`, `short_stack_raise_15bb`,
  `short_stack_jam_cap`.
- **77 feuilles sur 13845** de `ISSUE367_PREFLIGHT.json` divergent :
  **44 numériques** (probabilités d'action) et **33 digests**
  `decision_canonical_sha256` qui adressent ces probabilités. Elles se
  répartissent sur **13 des 38 nœuds** (`nodes/2, 3, 4, 5, 8, 12, 13, 16, 17,
  18, 24, 25, 28`) et **4 des 7 frontières** (`sizing_frontiers/0, 1, 3, 4`),
  plus `nearest_lookup_audit/probes/0/perturbed_distribution/JAM`.
- **`max |delta| = 2.220446049250313e-16`** — soit exactement `math.ulp(1.0)`,
  un écart d'une ULP sur la clôture `1.0 - others` (et la division
  `raw / total` pour les autres feuilles).

Contrôle négatif (même commande **sans** le remplacement de `sum`) : la même
comparaison donne **0 / 9** sonde divergente et **0 / 13845** feuille divergente.
L'interpréteur local (sommation compensée) reproduit donc les octets figés à
l'identique ; seul le remplacement naïf les casse.

Contrôle au niveau des suites : exécutées sous `sum` naïf, les deux fichiers de
test passent de **50 tests OK** à **7 échecs** — les 5 sous-tests
`test_in_window_predictions_are_bit_for_bit_unchanged` (une sonde chacun) et les
2 tests de préflight `test_build_is_deterministic_and_reproducible` /
`test_persisted_preflight_is_content_addressed_and_check_passes`. La cause est
bien l'unique bascule de `sum` : aucun autre écart n'apparaît.

## 4. Carte des contraintes gelées

Le correctif « évident » est bloqué par quatre familles de contraintes gelées,
qui rendent tout contournement coûteux et hors périmètre :

| contrainte | valeur gelée | épinglée dans |
| --- | --- | --- |
| module modèle `tools/preflop/generalized_response_model.py` | `sha256 92d7ac94aa03face11dbcd9a3b573d9ed790efb77b924a7ae5458fddcf94dbc3` | `CANDIDATE_MANIFEST.json` (`runtime_format/module_sha256`), `FROZEN_VALIDATION_PROTOCOL.json` (`code/inputs[2]`, rôle `CANDIDATE_MODEL_AND_RUNTIME`), `GENERALIZED_RESPONSE_MODEL_SPEC.json` (`model_identity/runtime_module_sha256`), `IN_WINDOW_PREDICTION_REFERENCE.json` (`model_module_sha256`) |
| module runtime `tools/preflop/generalized_response_runtime.py` | `sha256 af585fa50e04be4c848dc77db1bd28417eb536eee486aa0cfd5fcd4f95e6e361` | `ISSUE367_PREFLIGHT.json` (`evidence_bindings/runtime_module_sha256` + `model/provenance/runtime/module_sha256` sur chacun des 38 nœuds et 7 frontières) |
| interpréteur | `.python-version` = `3.11.9` | `.python-version` ; `reproducibility/environment.lock.json` (`python.version`) ; `reproducibility/container-base.lock.json` (tarball `Python-3.11.9.tar.xz`, `sha256 9b1e896523fc510691126c864406d9360a3d1e986acbda59cda57b5abda45b87`) ; `reproducibility/Dockerfile.science` (`ARG PYTHON_VERSION=3.11.9`) ; `requirements.lock.txt` |
| evidence adressée par contenu | `CANDIDATE_MANIFEST`, `FROZEN_VALIDATION_PROTOCOL`, `ISSUE367_PREFLIGHT`, `DECISION`, `VALIDATION_RESULT`, `GENERALIZED_RESPONSE_MODEL_SPEC` | sidecars `*.sha256`, copies `sha256/<digest>.…`, `ARTIFACTS.json`, `SUMMARY.md` |

Autrement dit, il n'existe aucune zone « libre » entre le modèle gelé, le
runtime gelé, l'interpréteur gelé et les octets d'evidence adressés par contenu :
toute action qui rendrait CI vert touche forcément l'une de ces quatre
contraintes.

## 5. Alternatives rejetées

1. **Re-pin de l'interpréteur** (passer `.python-version` à ≥ 3.12, ou épingler
   CI sur l'interpréteur qui a figé les octets). Rejeté : le pin `3.11.9` est une
   contrainte de reproductibilité **repo-wide** (#203) dupliquée dans
   `environment.lock.json`, `container-base.lock.json`, `Dockerfile.science` et
   `requirements.lock.txt` ; le changer modifie l'environnement hermétique
   entier et invalide les digests de la base conteneur pour corriger un seul
   artefact. Cela déplace le problème, ne le résout pas, et sort du périmètre
   #421.
2. **Édition de `tools/preflop/generalized_response_model.py`** (rendre la
   normalisation/la clôture indépendante de la sémantique de `sum`). Rejeté : le
   module est gelé à `92d7ac94…` ; toute édition déclenche
   `CANDIDATE_HASH_MISMATCH` (fail-closed), invalide la lecture one-shot
   VALIDATION et le futur `ISSUE367_PREFLIGHT.json`, et le périmètre de la tâche
   le déclare **lecture seule**.
3. **Simple re-run `--write-in-window-reference`** (régénérer la référence, la
   préflight et leurs digests sous 3.11.9). Rejeté : ce n'est pas un correctif
   mais une **ré-émission d'evidence** après la lecture one-shot VALIDATION ; elle
   réécrirait des octets figés, `ARTIFACTS.json`, `SUMMARY.md` et les sidecars,
   et ferait échouer la garde « aucun artefact modifié » du ticket. De plus elle
   ne ferait que **retourner** l'ambiguïté d'une ULP : l'artefact deviendrait
   irréproductible sur l'interpréteur compensé.

## 6. Frontière et suite

- Cette tâche est un **diagnostic** : la seule modification du diff est ce
  decision record. `IN_WINDOW_PREDICTION_REFERENCE.json`,
  `ISSUE367_PREFLIGHT.json`, les modules gelés, les digests et tous les autres
  artefacts d'evidence sont intacts.
- La décision terminale reste `RETAIN_REFERENCE_GENERALIZATION_INSUFFICIENT` ;
  aucun seuil, aucune métrique ni aucun gate n'est touché, et la lecture one-shot
  VALIDATION n'est pas rouverte.
- Recommandation hors périmètre (successeur) : rendre la clôture
  `_normalize_legal` **indépendante de l'interpréteur** (ordre/accumulation
  déterministes, p. ex. `math.fsum` ou une clôture qui ne dépend pas de la
  sémantique de `sum`), puis re-dériver une seule fois, dans un incrément revu,
  le module, la référence in-window, la préflight et leurs digests sous un
  interpréteur unique épinglé. Tant que ce successeur n'est pas livré, le rouge
  CI #421 est compris, borné (≤ 1 ULP) et **documenté ici**.

## 7. Ajout postérieur (`backlog-bvi`, T3) — octets de l'ancienne référence in-window

Les sections 1 à 6 sont le diagnostic `backlog-8l8` : à cette date, la seule
modification du diff était ce decision record. `backlog-bvi` (T3) exécute la
recommandation de §6 : il re-pinne la référence in-window sur la surface
canonique et la régénère avec son générateur officiel
(`python3 tests/preflop/test_generalized_response_sizing.py --write-in-window-reference`).
Le module gelé (`tools/preflop/generalized_response_model.py`, `92d7ac94…`),
l'identité de candidat (`c3f3573f…`, octets `ea93e8c3…`) et l'interpréteur ne
changent pas. Le module runtime reste `36591c2905bf61c186ad65832d9499151cf24a0e221c2ded7c3f15bd412f48e4` ;
c'est la valeur **recalculée** que porte désormais `CAPTURED_AT_RUNTIME_MODULE_SHA256`
(l'ancienne valeur était `e390a199…`, la surface runtime pré-canonique).

Seule la **représentation** change. La sonde du modèle de chaque entrée est
capturée à travers le même helper de canonicalisation que le runtime
(`runtime.canonical_prediction`, celui qu'applique
`GeneralizedResponseRuntime.resolve` à `self.predict(context)`), et non plus les
flottants bruts du module gelé : chaque probabilité enregistrée est donc
quantifiée sur la grille décimale fixe du runtime. Mesures sur les neuf sondes :

- écart maximal par probabilité, de la référence pré-canonique à la référence
  régénérée : `1.0758061108617767e-12` (sonde `short_stack_raise_15bb`, action
  `FOLD`) — au plus un pas de la grille à douze décimales, c'est-à-dire l'ordre
  de l'ULP ~ 1 en relatif sur un vecteur qui somme à `1.0` ;
- écart maximal des probabilités *runtime* de la référence remplacée (§7.2) à la
  référence régénérée : `0.0` — elles étaient déjà sur la grille ;
- la distribution ne bouge pas : l'action sélectionnée, les sizings sélectionnés
  et générés, le verdict `sizing_window`, `probability_sum == 1.0` et
  `illegal_mass == 0.0` sont identiques sonde par sonde, et l'ordre des
  probabilités est inchangé ; seules les représentations et les digests qui les
  adressent (`model_prediction_sha256`, `entries_sha256`) changent.

La garde conserve **exactement** l'égalité stricte déjà en place, sans aucune
tolérance ajoutée : `json.dumps(recomputed, sort_keys=True) ==
json.dumps(persisted, sort_keys=True)` sonde par sonde, plus la comparaison des
sha256 `runtime_prediction_sha256`, `model_prediction_sha256` et
`runtime_generated_sizings_sha256`. Aucun test n'est supprimé ni relâché ; deux
assertions sont ajoutées (identité de candidat, octets inclus, et la révision
runtime épinglée). La suite reste verte sur l'interpréteur local (CPython 3.14)
**et** sous l'émulation naïve-`sum` de 3.11 reproduite en §3 (29 tests).

Les octets de l'ancienne référence sont conservés ci-dessous comme preuve
historique. Deux états sont distingués, chacun avec la taille et le `sha256` de
ses octets **exacts** (fichier terminé par un saut de ligne) ; chacun est
reproduisible par `git show <commit>:<chemin>`.

### 7.1 Référence d'origine — surface pré-canonique (`@0783c9d`)

- chemin : `analysis/issue421_generalized_response/IN_WINDOW_PREDICTION_REFERENCE.json`
- `sha256` : `60bb723b2fcabe2aec1f264e47ccb4f7f57bd64a044ee545981364f2fd894f6b`
- taille : `13904` octets
- révision runtime épinglée : `e390a199857a00357969c51ec87af2b2f5e799384a3aa4858c0762a70411b538`
- `entries_sha256` : `bc34f4a36e0c4978cea57dee686f268d97040d05822f4b82bf69af58e495834a`

<!-- ANCIENNE_REFERENCE_0783C9D_DEBUT -->
```json
{
  "boundary": {
    "active_pointer_mutated": false,
    "issue367_executed": false,
    "test_consumed": false,
    "validation_split_reopened": false
  },
  "candidate_canonical_payload_sha256": "c3f3573f3e80b3f7889dc8b1fd6f1948daeea95effc5a41a5d707385c4eed7dc",
  "candidate_id": "generalized-adverse-response-candidate-v1",
  "captured_at_runtime_module_sha256": "e390a199857a00357969c51ec87af2b2f5e799384a3aa4858c0762a70411b538",
  "entries": [
    {
      "action": "RAISE",
      "actor_position": "LJ",
      "bounds_source": {
        "max": "effective_stack_bb_conservative",
        "min": "derived_conservative_floor"
      },
      "effective_stack_bb": 70.975,
      "family": "UNOPENED",
      "legal_window_bb": [
        2.0,
        70.975
      ],
      "model_prediction_sha256": "6baf3cc49d71fa47e92f78a835da311d35ffa4c5e82b0a8982ed3ded3c50d42d",
      "model_probabilities": {
        "CALL": 0.3495352733202476,
        "FOLD": 0.5432556229824147,
        "JAM": 0.0009611245756500075,
        "RAISE": 0.10624797912168772
      },
      "probe_id": "free_unopened_raise_floor",
      "runtime_generated_sizings_sha256": "1583e2dcafea72d58b0931af53787523089c70e1e42c3da4cb1870a278b0bcb1",
      "runtime_illegal_mass": 0.0,
      "runtime_inside_legal_window": true,
      "runtime_prediction_sha256": "0e03cbbe8b804955e2b8669491b47b01211afde06557a0f2b441129c1b102708",
      "runtime_probabilities": {
        "CALL": 0.3495352733202476,
        "FOLD": 0.5432556229824147,
        "JAM": 0.0009611245756500075,
        "RAISE": 0.10624797912168772
      },
      "runtime_probability_sum": 1.0,
      "runtime_selected_action": "RAISE",
      "runtime_selected_sizing_bb": 6.260645,
      "runtime_sizing_status": "RESOLVED",
      "runtime_status": "RESOLVED",
      "runtime_usable": true,
      "target_total_bb": 2.0
    },
    {
      "action": "RAISE",
      "actor_position": "LJ",
      "bounds_source": {
        "max": "effective_stack_bb_conservative",
        "min": "derived_conservative_floor"
      },
      "effective_stack_bb": 70.975,
      "family": "UNOPENED",
      "legal_window_bb": [
        2.0,
        70.975
      ],
      "model_prediction_sha256": "e37654eefd5fea55d3b514fe86c074914a8f28f06899aca59c948da3ece01cdb",
      "model_probabilities": {
        "CALL": 0.35836843928398743,
        "FOLD": 0.5569843291955411,
        "JAM": 0.0009854133199814763,
        "RAISE": 0.08366181820048998
      },
      "probe_id": "free_unopened_raise_default_relative",
      "runtime_generated_sizings_sha256": "1583e2dcafea72d58b0931af53787523089c70e1e42c3da4cb1870a278b0bcb1",
      "runtime_illegal_mass": 0.0,
      "runtime_inside_legal_window": true,
      "runtime_prediction_sha256": "16b571aa838bf69383f5d5569ac8860afb109fe2dbda60f19221296f84fe76c9",
      "runtime_probabilities": {
        "CALL": 0.35836843928398743,
        "FOLD": 0.5569843291955411,
        "JAM": 0.0009854133199814763,
        "RAISE": 0.08366181820048998
      },
      "runtime_probability_sum": 1.0,
      "runtime_selected_action": "RAISE",
      "runtime_selected_sizing_bb": 6.260645,
      "runtime_sizing_status": "RESOLVED",
      "runtime_status": "RESOLVED",
      "runtime_usable": true,
      "target_total_bb": 3.0
    },
    {
      "action": "JAM",
      "actor_position": "LJ",
      "bounds_source": {
        "max": "effective_stack_bb_conservative",
        "min": "derived_conservative_floor"
      },
      "effective_stack_bb": 70.975,
      "family": "UNOPENED",
      "legal_window_bb": [
        2.0,
        70.975
      ],
      "model_prediction_sha256": "c52a1c0256a7724d2eca3bffa85d388bffc7bed83ad775ab02861d8a16e9dd3c",
      "model_probabilities": {
        "CALL": 0.38381794802071395,
        "FOLD": 0.5965385309561733,
        "JAM": 0.008443139003719957,
        "RAISE": 0.011200382019392878
      },
      "probe_id": "free_unopened_jam_effective_stack",
      "runtime_generated_sizings_sha256": "02865385569048571d290ff376de2f6dd3e64f43a5adc94eb27aa37ee16b8aa7",
      "runtime_illegal_mass": 0.0,
      "runtime_inside_legal_window": true,
      "runtime_prediction_sha256": "6acab32594fea932748c707c9a630669b583996386fd66617a6414bc03b0e212",
      "runtime_probabilities": {
        "CALL": 0.38381794802071395,
        "FOLD": 0.5965385309561733,
        "JAM": 0.008443139003719957,
        "RAISE": 0.011200382019392878
      },
      "runtime_probability_sum": 1.0,
      "runtime_selected_action": "JAM",
      "runtime_selected_sizing_bb": 47.527076,
      "runtime_sizing_status": "RESOLVED",
      "runtime_status": "RESOLVED_HIGH_UNCERTAINTY",
      "runtime_usable": true,
      "target_total_bb": 70.975
    },
    {
      "action": "RAISE",
      "actor_position": "LJ",
      "bounds_source": {
        "max": "engine_max_raise_to",
        "min": "engine_interval"
      },
      "effective_stack_bb": 70.975,
      "family": "UNOPENED",
      "legal_window_bb": [
        9.0,
        60.0
      ],
      "model_prediction_sha256": "c793473c11154ebf0878c44cffc728414c95b0170300e9b486d779e68fb22a8b",
      "model_probabilities": {
        "CALL": 0.3866746020079299,
        "FOLD": 0.6009784071573037,
        "JAM": 0.0010632473776944762,
        "RAISE": 0.011283743457071956
      },
      "probe_id": "explicit_interval_raise_interior",
      "runtime_generated_sizings_sha256": "a21ea388f6212161ed74821ccfc1929eff69cab4dcca7d857914157603d66895",
      "runtime_illegal_mass": 0.0,
      "runtime_inside_legal_window": true,
      "runtime_prediction_sha256": "6c9455cdec6b5041f801d1772e3b7abd3865a434646fda1162cfbaddb016656b",
      "runtime_probabilities": {
        "CALL": 0.3866746020079299,
        "FOLD": 0.6009784071573037,
        "JAM": 0.0010632473776944762,
        "RAISE": 0.011283743457071956
      },
      "runtime_probability_sum": 1.0,
      "runtime_selected_action": "RAISE",
      "runtime_selected_sizing_bb": 28.401151,
      "runtime_sizing_status": "RESOLVED",
      "runtime_status": "RESOLVED",
      "runtime_usable": true,
      "target_total_bb": 12.0
    },
    {
      "action": "JAM",
      "actor_position": "LJ",
      "bounds_source": {
        "max": "engine_max_raise_to",
        "min": "engine_interval"
      },
      "effective_stack_bb": 70.975,
      "family": "UNOPENED",
      "legal_window_bb": [
        9.0,
        60.0
      ],
      "model_prediction_sha256": "6d0f2da557ce0d8951dd529d4cddd43dfcec173459fc96f71add38b8e5bc08e4",
      "model_probabilities": {
        "CALL": 0.38381794802071395,
        "FOLD": 0.5965385309561733,
        "JAM": 0.008443139003719957,
        "RAISE": 0.011200382019392878
      },
      "probe_id": "explicit_interval_jam_cap",
      "runtime_generated_sizings_sha256": "df4d62e567ba0bea35d205da7f6fc569ac14b0b864e1f1282e1f20a87027ffce",
      "runtime_illegal_mass": 0.0,
      "runtime_inside_legal_window": true,
      "runtime_prediction_sha256": "81862552cdb3c4641d9574c3c515a145f483255f1e4245e125caf29ad9c9d031",
      "runtime_probabilities": {
        "CALL": 0.38381794802071395,
        "FOLD": 0.5965385309561733,
        "JAM": 0.008443139003719957,
        "RAISE": 0.011200382019392878
      },
      "runtime_probability_sum": 1.0,
      "runtime_selected_action": "JAM",
      "runtime_selected_sizing_bb": 42.18677,
      "runtime_sizing_status": "RESOLVED",
      "runtime_status": "RESOLVED_HIGH_UNCERTAINTY",
      "runtime_usable": true,
      "target_total_bb": 60.0
    },
    {
      "action": "RAISE",
      "actor_position": "BB",
      "bounds_source": {
        "max": "effective_stack_bb_conservative",
        "min": "derived_conservative_floor"
      },
      "effective_stack_bb": 70.975,
      "family": "VS_LIMPERS",
      "legal_window_bb": [
        2.5,
        70.975
      ],
      "model_prediction_sha256": "24abbb8c9d7fc4593b9d4097702b6d5a419512dd87a3e3aa69ac7add595bab60",
      "model_probabilities": {
        "CALL": 0.38452007484377504,
        "FOLD": 0.41189529029966204,
        "JAM": 0.003886528164895875,
        "RAISE": 0.19969810669166707
      },
      "probe_id": "vs_limpers_bb_raise_3bb",
      "runtime_generated_sizings_sha256": "d3c4059a63ac2946e86e44cfb5bcc298aef76ac7ac92bc5f31d030de45c982a5",
      "runtime_illegal_mass": 0.0,
      "runtime_inside_legal_window": true,
      "runtime_prediction_sha256": "122aa8dba2f6109427c8df6771ac2e14943e8edf3ada94e075679ef904dfc0c6",
      "runtime_probabilities": {
        "CALL": 0.38452007484377504,
        "FOLD": 0.41189529029966204,
        "JAM": 0.003886528164895875,
        "RAISE": 0.19969810669166707
      },
      "runtime_probability_sum": 1.0,
      "runtime_selected_action": "RAISE",
      "runtime_selected_sizing_bb": 7.073598,
      "runtime_sizing_status": "RESOLVED",
      "runtime_status": "RESOLVED_HIGH_UNCERTAINTY",
      "runtime_usable": true,
      "target_total_bb": 3.0
    },
    {
      "action": "RAISE",
      "actor_position": "LJ",
      "bounds_source": {
        "max": "effective_stack_bb_conservative",
        "min": "derived_conservative_floor"
      },
      "effective_stack_bb": 20.0,
      "family": "UNOPENED",
      "legal_window_bb": [
        2.0,
        20.0
      ],
      "model_prediction_sha256": "0f4b65d1f2422e2d81c86e068d47af2e23697bac581840ae390db17182a553bf",
      "model_probabilities": {
        "CALL": 0.38279510101767034,
        "FOLD": 0.6006456813860758,
        "JAM": 0.005464283356628075,
        "RAISE": 0.011094934239625777
      },
      "probe_id": "short_stack_raise_15bb",
      "runtime_generated_sizings_sha256": "01a5ba640a64189fcb73690e3f96897a2c74182371e78f5f7f37838297690350",
      "runtime_illegal_mass": 0.0,
      "runtime_inside_legal_window": true,
      "runtime_prediction_sha256": "24e448252b48a374bbd1d3d0f35fb3be31dac648f93b867a838fb90d3a352423",
      "runtime_probabilities": {
        "CALL": 0.38279510101767034,
        "FOLD": 0.6006456813860758,
        "JAM": 0.005464283356628075,
        "RAISE": 0.011094934239625777
      },
      "runtime_probability_sum": 1.0,
      "runtime_selected_action": "RAISE",
      "runtime_selected_sizing_bb": 4.326613,
      "runtime_sizing_status": "RESOLVED",
      "runtime_status": "RESOLVED",
      "runtime_usable": true,
      "target_total_bb": 15.0
    },
    {
      "action": "JAM",
      "actor_position": "LJ",
      "bounds_source": {
        "max": "effective_stack_bb_conservative",
        "min": "derived_conservative_floor"
      },
      "effective_stack_bb": 20.0,
      "family": "UNOPENED",
      "legal_window_bb": [
        2.0,
        20.0
      ],
      "model_prediction_sha256": "71d527c3f278f12ab3d55b02e67f66758dc54acc9b9027cf405971c58c30515b",
      "model_probabilities": {
        "CALL": 0.379799829105396,
        "FOLD": 0.5959457854524506,
        "JAM": 0.01324626617170599,
        "RAISE": 0.0110081192704474
      },
      "probe_id": "short_stack_jam_cap",
      "runtime_generated_sizings_sha256": "fcdf8c814aaf13779cf38fe2bcf60a9b425220ce41575c237a1f50dcff20f077",
      "runtime_illegal_mass": 0.0,
      "runtime_inside_legal_window": true,
      "runtime_prediction_sha256": "640a143ff25b63d3fc3724367ec8684af2423577a723484a115ebc65d052b043",
      "runtime_probabilities": {
        "CALL": 0.379799829105396,
        "FOLD": 0.5959457854524506,
        "JAM": 0.01324626617170599,
        "RAISE": 0.0110081192704474
      },
      "runtime_probability_sum": 1.0,
      "runtime_selected_action": "JAM",
      "runtime_selected_sizing_bb": 14.87146,
      "runtime_sizing_status": "RESOLVED",
      "runtime_status": "RESOLVED",
      "runtime_usable": true,
      "target_total_bb": 20.0
    },
    {
      "action": "RAISE",
      "actor_position": "LJ",
      "bounds_source": {
        "max": "effective_stack_bb_conservative",
        "min": "derived_conservative_floor"
      },
      "effective_stack_bb": 150.0,
      "family": "UNOPENED",
      "legal_window_bb": [
        2.0,
        150.0
      ],
      "model_prediction_sha256": "96347e60136b1c1cefbd3126a9a623a8040126fdf51faf8b8029116a820b2597",
      "model_probabilities": {
        "CALL": 0.37763394911025583,
        "FOLD": 0.61020378886889,
        "JAM": 0.0009074412588571112,
        "RAISE": 0.01125482076199706
      },
      "probe_id": "deep_stack_raise_9bb",
      "runtime_generated_sizings_sha256": "160263e16ec7551573076f19587dbe11ae3520bf2f8cf6c83a0e122657123072",
      "runtime_illegal_mass": 0.0,
      "runtime_inside_legal_window": true,
      "runtime_prediction_sha256": "463c1b92a619db934efadb90792b1a57058b689bbb121aff253923673e6507ea",
      "runtime_probabilities": {
        "CALL": 0.37763394911025583,
        "FOLD": 0.61020378886889,
        "JAM": 0.0009074412588571112,
        "RAISE": 0.01125482076199706
      },
      "runtime_probability_sum": 1.0,
      "runtime_selected_action": "RAISE",
      "runtime_selected_sizing_bb": 19.167792,
      "runtime_sizing_status": "RESOLVED",
      "runtime_status": "RESOLVED",
      "runtime_usable": true,
      "target_total_bb": 9.0
    }
  ],
  "entries_sha256": "bc34f4a36e0c4978cea57dee686f268d97040d05822f4b82bf69af58e495834a",
  "issue": 421,
  "kind": "IN_WINDOW_PREDICTION_REFERENCE",
  "model_module_sha256": "92d7ac94aa03face11dbcd9a3b573d9ed790efb77b924a7ae5458fddcf94dbc3",
  "purpose": "Freeze the in-window RAISE/JAM response predictions so that the explicit legal-window declaration (and any later revision) is proved not to move the in-window distribution.",
  "regeneration": "python3 tests/preflop/test_generalized_response_sizing.py --write-in-window-reference",
  "rule": "an in-window query keeps the same action distribution and the same selected sizing as before the legal-window declaration was added; only the declared sizing_window verdict, never a probability, is new",
  "schema": "poker-generalized-response-in-window-reference/v1"
}
```
<!-- ANCIENNE_REFERENCE_0783C9D_FIN -->

### 7.2 Référence remplacée par ce re-pin — surface runtime canonique (`@fea622d`)

- chemin : `analysis/issue421_generalized_response/IN_WINDOW_PREDICTION_REFERENCE.json`
- `sha256` : `7737a0c4a5ce50a401828349a864588db3bde71f9d501e51b4bb7edc8aeddcfb`
- taille : `13978` octets
- révision runtime épinglée : `36591c2905bf61c186ad65832d9499151cf24a0e221c2ded7c3f15bd412f48e4`
- `entries_sha256` : `4af7100b42c2687151ea49740028e94c52c154afcb7a78ac29ece3d630c094bf`

<!-- ANCIENNE_REFERENCE_FEA622D_DEBUT -->
```json
{
  "boundary": {
    "active_pointer_mutated": false,
    "issue367_executed": false,
    "test_consumed": false,
    "validation_split_reopened": false
  },
  "candidate_canonical_payload_sha256": "c3f3573f3e80b3f7889dc8b1fd6f1948daeea95effc5a41a5d707385c4eed7dc",
  "candidate_id": "generalized-adverse-response-candidate-v1",
  "captured_at_runtime_module_sha256": "36591c2905bf61c186ad65832d9499151cf24a0e221c2ded7c3f15bd412f48e4",
  "entries": [
    {
      "action": "RAISE",
      "actor_position": "LJ",
      "bounds_source": {
        "max": "effective_stack_bb_conservative",
        "min": "derived_conservative_floor"
      },
      "effective_stack_bb": 70.975,
      "family": "UNOPENED",
      "legal_window_bb": [
        2.0,
        70.975
      ],
      "model_prediction_sha256": "6baf3cc49d71fa47e92f78a835da311d35ffa4c5e82b0a8982ed3ded3c50d42d",
      "model_probabilities": {
        "CALL": 0.3495352733202476,
        "FOLD": 0.5432556229824147,
        "JAM": 0.0009611245756500075,
        "RAISE": 0.10624797912168772
      },
      "probe_id": "free_unopened_raise_floor",
      "runtime_generated_sizings_sha256": "1583e2dcafea72d58b0931af53787523089c70e1e42c3da4cb1870a278b0bcb1",
      "runtime_illegal_mass": 0.0,
      "runtime_inside_legal_window": true,
      "runtime_prediction_sha256": "230a3d1312be80faaa2d2885f8bb56ac92264bdb553c89d82a99b70cbe18a3da",
      "runtime_probabilities": {
        "CALL": 0.34953527332,
        "FOLD": 0.543255622982,
        "JAM": 0.000961124576,
        "RAISE": 0.106247979122
      },
      "runtime_probability_sum": 1.0,
      "runtime_selected_action": "RAISE",
      "runtime_selected_sizing_bb": 6.260645,
      "runtime_sizing_status": "RESOLVED",
      "runtime_status": "RESOLVED",
      "runtime_usable": true,
      "target_total_bb": 2.0
    },
    {
      "action": "RAISE",
      "actor_position": "LJ",
      "bounds_source": {
        "max": "effective_stack_bb_conservative",
        "min": "derived_conservative_floor"
      },
      "effective_stack_bb": 70.975,
      "family": "UNOPENED",
      "legal_window_bb": [
        2.0,
        70.975
      ],
      "model_prediction_sha256": "e37654eefd5fea55d3b514fe86c074914a8f28f06899aca59c948da3ece01cdb",
      "model_probabilities": {
        "CALL": 0.35836843928398743,
        "FOLD": 0.5569843291955411,
        "JAM": 0.0009854133199814763,
        "RAISE": 0.08366181820048998
      },
      "probe_id": "free_unopened_raise_default_relative",
      "runtime_generated_sizings_sha256": "1583e2dcafea72d58b0931af53787523089c70e1e42c3da4cb1870a278b0bcb1",
      "runtime_illegal_mass": 0.0,
      "runtime_inside_legal_window": true,
      "runtime_prediction_sha256": "00ad87ec2e5edc717ff3dd1a4bf33e0e1e9d78f55048fcc19b18d45576fcd932",
      "runtime_probabilities": {
        "CALL": 0.358368439284,
        "FOLD": 0.556984329196,
        "JAM": 0.00098541332,
        "RAISE": 0.0836618182
      },
      "runtime_probability_sum": 1.0,
      "runtime_selected_action": "RAISE",
      "runtime_selected_sizing_bb": 6.260645,
      "runtime_sizing_status": "RESOLVED",
      "runtime_status": "RESOLVED",
      "runtime_usable": true,
      "target_total_bb": 3.0
    },
    {
      "action": "JAM",
      "actor_position": "LJ",
      "bounds_source": {
        "max": "effective_stack_bb_conservative",
        "min": "derived_conservative_floor"
      },
      "effective_stack_bb": 70.975,
      "family": "UNOPENED",
      "legal_window_bb": [
        2.0,
        70.975
      ],
      "model_prediction_sha256": "c52a1c0256a7724d2eca3bffa85d388bffc7bed83ad775ab02861d8a16e9dd3c",
      "model_probabilities": {
        "CALL": 0.38381794802071395,
        "FOLD": 0.5965385309561733,
        "JAM": 0.008443139003719957,
        "RAISE": 0.011200382019392878
      },
      "probe_id": "free_unopened_jam_effective_stack",
      "runtime_generated_sizings_sha256": "02865385569048571d290ff376de2f6dd3e64f43a5adc94eb27aa37ee16b8aa7",
      "runtime_illegal_mass": 0.0,
      "runtime_inside_legal_window": true,
      "runtime_prediction_sha256": "98b7fd841ead5f19a23ccb4080ec7cd337b7ad3b5d27091b907543098e326a2a",
      "runtime_probabilities": {
        "CALL": 0.383817948021,
        "FOLD": 0.5965385309560001,
        "JAM": 0.008443139004,
        "RAISE": 0.011200382019
      },
      "runtime_probability_sum": 1.0,
      "runtime_selected_action": "JAM",
      "runtime_selected_sizing_bb": 47.527076,
      "runtime_sizing_status": "RESOLVED",
      "runtime_status": "RESOLVED_HIGH_UNCERTAINTY",
      "runtime_usable": true,
      "target_total_bb": 70.975
    },
    {
      "action": "RAISE",
      "actor_position": "LJ",
      "bounds_source": {
        "max": "engine_max_raise_to",
        "min": "engine_interval"
      },
      "effective_stack_bb": 70.975,
      "family": "UNOPENED",
      "legal_window_bb": [
        9.0,
        60.0
      ],
      "model_prediction_sha256": "c793473c11154ebf0878c44cffc728414c95b0170300e9b486d779e68fb22a8b",
      "model_probabilities": {
        "CALL": 0.3866746020079299,
        "FOLD": 0.6009784071573037,
        "JAM": 0.0010632473776944762,
        "RAISE": 0.011283743457071956
      },
      "probe_id": "explicit_interval_raise_interior",
      "runtime_generated_sizings_sha256": "a21ea388f6212161ed74821ccfc1929eff69cab4dcca7d857914157603d66895",
      "runtime_illegal_mass": 0.0,
      "runtime_inside_legal_window": true,
      "runtime_prediction_sha256": "380baf5a702c18e24ef3050616034c4e413b12d697770a31f47a05df0c9c8b41",
      "runtime_probabilities": {
        "CALL": 0.386674602008,
        "FOLD": 0.600978407157,
        "JAM": 0.001063247378,
        "RAISE": 0.011283743457
      },
      "runtime_probability_sum": 1.0,
      "runtime_selected_action": "RAISE",
      "runtime_selected_sizing_bb": 28.401151,
      "runtime_sizing_status": "RESOLVED",
      "runtime_status": "RESOLVED",
      "runtime_usable": true,
      "target_total_bb": 12.0
    },
    {
      "action": "JAM",
      "actor_position": "LJ",
      "bounds_source": {
        "max": "engine_max_raise_to",
        "min": "engine_interval"
      },
      "effective_stack_bb": 70.975,
      "family": "UNOPENED",
      "legal_window_bb": [
        9.0,
        60.0
      ],
      "model_prediction_sha256": "6d0f2da557ce0d8951dd529d4cddd43dfcec173459fc96f71add38b8e5bc08e4",
      "model_probabilities": {
        "CALL": 0.38381794802071395,
        "FOLD": 0.5965385309561733,
        "JAM": 0.008443139003719957,
        "RAISE": 0.011200382019392878
      },
      "probe_id": "explicit_interval_jam_cap",
      "runtime_generated_sizings_sha256": "df4d62e567ba0bea35d205da7f6fc569ac14b0b864e1f1282e1f20a87027ffce",
      "runtime_illegal_mass": 0.0,
      "runtime_inside_legal_window": true,
      "runtime_prediction_sha256": "ba83729c813e8da5d9f512b854e61496bb29fdd5ba16ab3dd0f04cf4dca1a93c",
      "runtime_probabilities": {
        "CALL": 0.383817948021,
        "FOLD": 0.5965385309560001,
        "JAM": 0.008443139004,
        "RAISE": 0.011200382019
      },
      "runtime_probability_sum": 1.0,
      "runtime_selected_action": "JAM",
      "runtime_selected_sizing_bb": 42.18677,
      "runtime_sizing_status": "RESOLVED",
      "runtime_status": "RESOLVED_HIGH_UNCERTAINTY",
      "runtime_usable": true,
      "target_total_bb": 60.0
    },
    {
      "action": "RAISE",
      "actor_position": "BB",
      "bounds_source": {
        "max": "effective_stack_bb_conservative",
        "min": "derived_conservative_floor"
      },
      "effective_stack_bb": 70.975,
      "family": "VS_LIMPERS",
      "legal_window_bb": [
        2.5,
        70.975
      ],
      "model_prediction_sha256": "24abbb8c9d7fc4593b9d4097702b6d5a419512dd87a3e3aa69ac7add595bab60",
      "model_probabilities": {
        "CALL": 0.38452007484377504,
        "FOLD": 0.41189529029966204,
        "JAM": 0.003886528164895875,
        "RAISE": 0.19969810669166707
      },
      "probe_id": "vs_limpers_bb_raise_3bb",
      "runtime_generated_sizings_sha256": "d3c4059a63ac2946e86e44cfb5bcc298aef76ac7ac92bc5f31d030de45c982a5",
      "runtime_illegal_mass": 0.0,
      "runtime_inside_legal_window": true,
      "runtime_prediction_sha256": "f63c8ff610091f41e04cef55fcd421a61adf7e5e8c1ba4a80d30051275925e90",
      "runtime_probabilities": {
        "CALL": 0.384520074844,
        "FOLD": 0.41189529029899996,
        "JAM": 0.003886528165,
        "RAISE": 0.199698106692
      },
      "runtime_probability_sum": 1.0,
      "runtime_selected_action": "RAISE",
      "runtime_selected_sizing_bb": 7.073598,
      "runtime_sizing_status": "RESOLVED",
      "runtime_status": "RESOLVED_HIGH_UNCERTAINTY",
      "runtime_usable": true,
      "target_total_bb": 3.0
    },
    {
      "action": "RAISE",
      "actor_position": "LJ",
      "bounds_source": {
        "max": "effective_stack_bb_conservative",
        "min": "derived_conservative_floor"
      },
      "effective_stack_bb": 20.0,
      "family": "UNOPENED",
      "legal_window_bb": [
        2.0,
        20.0
      ],
      "model_prediction_sha256": "0f4b65d1f2422e2d81c86e068d47af2e23697bac581840ae390db17182a553bf",
      "model_probabilities": {
        "CALL": 0.38279510101767034,
        "FOLD": 0.6006456813860758,
        "JAM": 0.005464283356628075,
        "RAISE": 0.011094934239625777
      },
      "probe_id": "short_stack_raise_15bb",
      "runtime_generated_sizings_sha256": "01a5ba640a64189fcb73690e3f96897a2c74182371e78f5f7f37838297690350",
      "runtime_illegal_mass": 0.0,
      "runtime_inside_legal_window": true,
      "runtime_prediction_sha256": "775bf3648aa72f339959d3fad9d66377a4979975adc5a3d81e1fbe6fa6721752",
      "runtime_probabilities": {
        "CALL": 0.382795101018,
        "FOLD": 0.600645681385,
        "JAM": 0.005464283357,
        "RAISE": 0.01109493424
      },
      "runtime_probability_sum": 1.0,
      "runtime_selected_action": "RAISE",
      "runtime_selected_sizing_bb": 4.326613,
      "runtime_sizing_status": "RESOLVED",
      "runtime_status": "RESOLVED",
      "runtime_usable": true,
      "target_total_bb": 15.0
    },
    {
      "action": "JAM",
      "actor_position": "LJ",
      "bounds_source": {
        "max": "effective_stack_bb_conservative",
        "min": "derived_conservative_floor"
      },
      "effective_stack_bb": 20.0,
      "family": "UNOPENED",
      "legal_window_bb": [
        2.0,
        20.0
      ],
      "model_prediction_sha256": "71d527c3f278f12ab3d55b02e67f66758dc54acc9b9027cf405971c58c30515b",
      "model_probabilities": {
        "CALL": 0.379799829105396,
        "FOLD": 0.5959457854524506,
        "JAM": 0.01324626617170599,
        "RAISE": 0.0110081192704474
      },
      "probe_id": "short_stack_jam_cap",
      "runtime_generated_sizings_sha256": "fcdf8c814aaf13779cf38fe2bcf60a9b425220ce41575c237a1f50dcff20f077",
      "runtime_illegal_mass": 0.0,
      "runtime_inside_legal_window": true,
      "runtime_prediction_sha256": "a1df2a078484a12627a629894a6e2b57356b1f32126404bff923be104f66d282",
      "runtime_probabilities": {
        "CALL": 0.379799829105,
        "FOLD": 0.595945785453,
        "JAM": 0.013246266172,
        "RAISE": 0.01100811927
      },
      "runtime_probability_sum": 1.0,
      "runtime_selected_action": "JAM",
      "runtime_selected_sizing_bb": 14.87146,
      "runtime_sizing_status": "RESOLVED",
      "runtime_status": "RESOLVED",
      "runtime_usable": true,
      "target_total_bb": 20.0
    },
    {
      "action": "RAISE",
      "actor_position": "LJ",
      "bounds_source": {
        "max": "effective_stack_bb_conservative",
        "min": "derived_conservative_floor"
      },
      "effective_stack_bb": 150.0,
      "family": "UNOPENED",
      "legal_window_bb": [
        2.0,
        150.0
      ],
      "model_prediction_sha256": "96347e60136b1c1cefbd3126a9a623a8040126fdf51faf8b8029116a820b2597",
      "model_probabilities": {
        "CALL": 0.37763394911025583,
        "FOLD": 0.61020378886889,
        "JAM": 0.0009074412588571112,
        "RAISE": 0.01125482076199706
      },
      "probe_id": "deep_stack_raise_9bb",
      "runtime_generated_sizings_sha256": "160263e16ec7551573076f19587dbe11ae3520bf2f8cf6c83a0e122657123072",
      "runtime_illegal_mass": 0.0,
      "runtime_inside_legal_window": true,
      "runtime_prediction_sha256": "23ab0c724bfb888eade8c5ee9057335fe5a37505fd9d7415a8a46b6e49b07e49",
      "runtime_probabilities": {
        "CALL": 0.37763394911,
        "FOLD": 0.6102037888690001,
        "JAM": 0.000907441259,
        "RAISE": 0.011254820762
      },
      "runtime_probability_sum": 1.0,
      "runtime_selected_action": "RAISE",
      "runtime_selected_sizing_bb": 19.167792,
      "runtime_sizing_status": "RESOLVED",
      "runtime_status": "RESOLVED",
      "runtime_usable": true,
      "target_total_bb": 9.0
    }
  ],
  "entries_sha256": "4af7100b42c2687151ea49740028e94c52c154afcb7a78ac29ece3d630c094bf",
  "issue": 421,
  "kind": "IN_WINDOW_PREDICTION_REFERENCE",
  "model_module_sha256": "92d7ac94aa03face11dbcd9a3b573d9ed790efb77b924a7ae5458fddcf94dbc3",
  "purpose": "Freeze the in-window RAISE/JAM response predictions so that the explicit legal-window declaration, and every later runtime revision, is proved not to move the in-window action, the selected sizing or the declared window verdict.",
  "regeneration": "python3 tests/preflop/test_generalized_response_sizing.py --write-in-window-reference",
  "rule": "an in-window query keeps the same selected action, the same selected sizing and the same declared sizing_window verdict across runtime revisions; the legal-window declaration added no probability, and the interpreter-independent canonical surface only moved each emitted probability onto the runtime's fixed decimal grid, where probability_sum stays exactly 1.0 and illegal_mass exactly 0.0",
  "schema": "poker-generalized-response-in-window-reference/v1"
}
```
<!-- ANCIENNE_REFERENCE_FEA622D_FIN -->

### 7.3 Référence régénérée (`backlog-bvi`)

- chemin : `analysis/issue421_generalized_response/IN_WINDOW_PREDICTION_REFERENCE.json`
- `sha256` : `873e429b72bf81ab180b416811480bff04863aed10d699791d39524a952b8312`
- taille : `13969` octets
- révision runtime épinglée : `36591c2905bf61c186ad65832d9499151cf24a0e221c2ded7c3f15bd412f48e4`
- `entries_sha256` : `a48c280c9cd7607d06752fedb0fa264ec9b082fdf2529b8dfee594219937cb79`
- identité de candidat pinnée : `generalized-adverse-response-candidate-v1`,
  payload canonique `c3f3573f3e80b3f7889dc8b1fd6f1948daeea95effc5a41a5d707385c4eed7dc`,
  octets du candidat `ea93e8c35e2604debd943495474cdb9262d724efb4a5caefe3723b53f23a59e7`
- écrite par le générateur officiel
  (`--write-in-window-reference`), jamais éditée à la main ; les sections §7.1 et
  §7.2 restent l'unique copie des octets antérieurs.

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

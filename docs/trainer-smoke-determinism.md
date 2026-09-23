# Déterminisme du browser-smoke Trainer et reproductibilité par seed

Contrat de documentation pour le browser-smoke du Trainer (#409). Ce document
décrit le mécanisme de randomisation du Trainer, la seed smoke retenue, la
procédure de reproduction d'un échec local, et la frontière stricte avec les
surfaces Model A / Model B et le protocole scientifique.

## Pourquoi le smoke Trainer doit être déterministe

`tests/trainer/smoke_trainer.py` pilote un vrai navigateur (Playwright/Chromium)
contre `site/index.html` et joue une session Trainer scriptée. Sans seed
explicite, chaque main est distribuée depuis une source non contrôlée : les
cartes, les sièges, le rôle Hero (`PFA` / `CALLER`) et l'historique préflop
changent à chaque exécution. Un échec rouge devient alors non rejouable, la
non-régression est instable (flaky), et une régression réelle peut être masquée
par un simple retirage chanceux.

Le smoke doit donc vérifier deux choses séparément :

1. la session scriptée est une fonction pure de la seed injectée ;
2. la seed calibrée expose bien la décision Hero attendue (main vivante et non
   terminale), sans retirage silencieux ni retry qui masquerait la régression.

## Mécanisme RNG retenu

Le Trainer ne tire plus sa randomisation directement dans sa logique. Tous les
tirages passent par une **source unique et seedable** définie dans
`site/trainer.js`, entre les marqueurs explicites
`/* #409-RNG-BLOCK-START */` et `/* #409-RNG-BLOCK-END */` :

- `trainerRandom()` : seul point d'entrée utilisé par la logique Trainer
  (`trainerRandomInt`, `trainerShuffle`, `trainerWeightedChoice`, etc.) ;
- `trainerSetSeed(seed)` : installe une source déterministe dérivée de la seed
  (générateur Mulberry32 après normalisation) et renvoie la seed normalisée ;
- `trainerSetRandomSource(fn)` : injecte une source déterministe arbitraire
  (fonction attendue, sinon `TypeError`) et efface la seed courante ;
- `trainerResetRandomSource()` : restaure la source de production et efface la
  seed courante ;
- `trainerRandomSeed()` : renvoie la seed courante (`null` quand aucune seed
  explicite n'est active).

Ces quatre fonctions sont exposées sur `window` (`window.trainerSetSeed`,
`window.trainerSetRandomSource`, `window.trainerResetRandomSource`,
`window.trainerRandomSeed`) pour que le smoke et les repros navigateur puissent
les appeler sans patcher `Math.random`.

**Défaut prod = `Math.random`.** La source par défaut est
`trainerDefaultRandom = () => Math.random()`. C'est la seule occurrence de
`Math.random` du bundle : ni la logique Trainer ni un test n'écrase
`Math.random` global. `trainerResetRandomSource()` restaure exactement cette
source par défaut, donc une page de production non seedée garde le comportement
historique.

La normalisation de la seed est stable : un nombre fini est ramené en `uint32`
(`seed >>> 0`) ; toute autre valeur est hachée en FNV-1a. Deux appels
`trainerSetSeed(mêmeSeed)` produisent donc la même séquence, et une seed
différente produit une séquence différente.

Le contrat exécutable de ce mécanisme est
`tests/trainer/test_trainer_rng_determinism.py` (extraction verbatim du bloc
`#409-RNG-BLOCK-START` / `#409-RNG-BLOCK-END`, contrôle statique de l'unicité de
`Math.random`, `node --check`) et sa preuve runtime
`tests/trainer/trainer_rng_determinism.js`.

## Seed smoke retenue

La seed du browser-smoke est `TRAINER_SMOKE_SEED`, définie dans
`tests/trainer/smoke_trainer.py` :

    TRAINER_SMOKE_SEED = int(os.environ.get("TRAINER_SMOKE_SEED", "39"))

**Seed retenue : `39`.** Elle est injectée via
`window.trainerSetSeed(TRAINER_SMOKE_SEED)` **avant** l'ouverture du Trainer et
donc avant la distribution de la première main. Toute la session scriptée est
ensuite une fonction pure de cette seed.

Calibration : la main seedée doit exposer une décision Hero **vivante et non
terminale** (`trainerState.hand.awaitingHero === true` et `ended === false`).
La valeur `39` produit un spot canonique VS-RFI `CALLER` (Hero HJ face à une
open LJ), c'est-à-dire le spot couvert par la référence CALL/FOLD #108
conservée. Le smoke échoue explicitement (« recalibrate the seed ») si cette
propriété disparaît : aucun retry ni aucune régénération silencieuse ne peut
masquer la régression.

La seed est journalisée dans la sortie du smoke (`trainer smoke seed: <seed>`)
et dans le snapshot JSON (`trainer_seed`, `trainer_seed_env_override`,
`seeded_hand`, `scenario_probe`).

## Reproduire localement un échec

Un échec affiche la seed utilisée dans sa sortie :

    trainer smoke seed: 39

Pour rejouer exactement la même session, lancer le smoke avec cette seed :

    TRAINER_SMOKE_SEED=39 python3 tests/trainer/smoke_trainer.py

Forme générique :

    TRAINER_SMOKE_SEED=<seed> python3 tests/trainer/smoke_trainer.py

Utilité : bissecter une seed en échec (`TRAINER_SMOKE_SEED=123 ...`) ou
reproduire à l'identique un run CI rouge sans modifier le code. Le
`scenario_probe` du snapshot re-seede deux fois la même seed et vérifie que les
empreintes (sièges dealer/Hero, positions, cartes, rôle Hero, historique
préflop) sont identiques ; la seed voisine est rapportée mais jamais assertée,
de sorte que la calibration reste observable.

## Case terminale « Recommandation — » vs invariant Mode Test / Réponse masquée

Deux états visuels proches **ne doivent jamais être confondus** :

| État | Condition | Rendu attendu | Assertion smoke |
| --- | --- | --- | --- |
| Case terminale de fin de main | `trainerState.hand.ended === true` | label `Recommandation`, valeur `—`, classe `hidden-answer` | `terminal_recommendation` : `label == "Recommandation"`, `main == "—"`, `hidden-answer` présent, et **absence** de `Mode Test` / `Réponse masquée` |
| Invariant Mode Test / Training | décision Hero **vivante et non terminale** (`awaitingHero && !ended`), avant toute action Hero | Mode Test : label `Mode Test` + `Réponse masquée` ; mode Training : `Décidez d'abord` + `Réponse masquée` | assertion sur la décision vivante, puis contrôle des deux surfaces avant d'agir |

La case terminale est un **placeholder neutre** de main terminée : ce n'est pas
le message d'attente d'une décision. L'invariant Mode Test vérifie que les
réponses restent masquées tant que la main est en cours ; il est asserté
strictement sur une décision Hero vivante (`awaitingHero === true`,
`ended === false`), avant toute action, car changer de mode ne joue jamais la
main. Une assertion de l'un ne vaut donc jamais preuve de l'autre.

## Absence d'impact Model A / Model B / protocole scientifique

Ce changement est strictement limité au **déterminisme de la randomisation du
smoke Trainer** :

- aucune modification de Model A, de Model B, de leurs fits, évaluations ou
  artefacts scientifiques ;
- aucune modification de la sémantique equity, des ranges posterior, des
  populations, du budget de recherche ni de l'activation de candidat ;
- aucune modification des contrats #107 / #108 : la référence CALL/FOLD
  conservée reste la même ;
- la production garde la source par défaut `Math.random` : la seed n'existe que
  lorsque le smoke ou une repro l'injecte explicitement ;
- aucun changement de protocole scientifique, de métrique ou de conclusion
  validée.

Autrement dit, la reproductibilité par seed est un outil de test et de debug ;
elle ne change ni les résultats Model A / Model B, ni leur protocole
scientifique.

## Références

- `site/trainer.js` — bloc RNG `#409-RNG-BLOCK-START` / `#409-RNG-BLOCK-END`
  (`trainerRandom`, `trainerSetSeed`, `trainerSetRandomSource`,
  `trainerResetRandomSource`, `trainerRandomSeed`, défaut prod `Math.random`).
- `tests/trainer/smoke_trainer.py` — browser-smoke seedé, calibration,
  `scenario_probe`, case terminale et invariant Mode Test.
- `tests/trainer/test_trainer_rng_determinism.py` et
  `tests/trainer/trainer_rng_determinism.js` — contrat statique + runtime du RNG.
- `docs/reproducible-environment.md` — contrat d'environnement d'exécution.

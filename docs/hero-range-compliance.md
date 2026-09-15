# Contrôle de conformité aux ranges Hero

Ce document décrit le contrat livré par l'issue #98. Il contrôle si une décision préflop observée respecte la stratégie Hero sélectionnée. Il ne remplace pas la recommandation empirique du moteur et ne crée aucune EV préflop lorsqu'elle n'est pas disponible par un évaluateur validé.

## Entrée et absence de fuite future

Le contrôle consomme le contexte `poker-preflop-context/v1` construit **BEFORE_ACTION** par le contrat #96, la main privée de Hero et le dépôt `poker-hero-range-repository/v1` sélectionné. Il ne consomme ni board futur, ni cartes adverses révélées après la décision, ni résultat de la main.

La résolution utilise : population, taille de table, position de Hero, famille de spot et profondeur effective. Une profondeur ne peut réutiliser un contexte voisin que si l'écart absolu est au plus de 2 BB. Sinon le verdict est `UNCOVERED_DEPTH` et aucune conformité n'est inventée.

## Actions sémantiques

Les actions structurelles du replayer sont traduites vers le vocabulaire du dépôt Hero :

- `LIMP` devient `LIMP` ou `OVERLIMP` selon l'historique ;
- `RAISE` devient `OPEN`, `ISO`, `3BET` ou `4BET` selon le niveau et les limpers ;
- `JAM` devient `SHOVE` ;
- `CALL` face au dernier acte agressif `JAM` devient `CALL_SHOVE`, y compris lorsqu'un autre joueur a call le tapis entre-temps ;
- `FOLD` et `CHECK` restent inchangés.

Les familles de contexte distinguent notamment `UNOPENED`, `VS_LIMPERS`, `VS_RFI`, `VS_RFI_CALLERS`, `VS_ISO`, `VS_ISO_CALLERS`, `VS_3BET`, `VS_4BET`, `VS_5BET`, `VS_6BET_PLUS` et `VS_JAM`.

## Verdict d'action

Pour une main et un contexte couverts :

- `COMPLIANT` : l'action prescrite a une fréquence de 100 % ;
- `MIXED_ALLOWED` : l'action possède une fréquence strictement positive et inférieure à 100 % ;
- `OUT_OF_RANGE` : le contexte et la main sont définis mais l'action observée a une fréquence nulle.

Une action prescrite à 20 % est donc **autorisée sur l'occurrence observée**. Une occurrence isolée ne permet pas de conclure que Hero respecte une fréquence de 20 % sur le long terme. Le champ `frequency_calibration_status` reste `SAMPLE_REQUIRED` et le bilan agrégé ne prétend pas effectuer ce test statistique.

Les cas `NO_REPOSITORY`, `UNCOVERED_CONTEXT`, `UNCOVERED_DEPTH`, `UNCOVERED_HAND` et `UNKNOWN_ACTION` ne sont jamais convertis en fold implicite ou en verdict négatif.

## Sizing

Le sizing est un contrôle séparé du verdict d'action. Lorsqu'une action agressive autorisée possède une distribution de sizings, le replayer compare le `target_total_bb` réellement joué aux cibles prescrites. La tolérance est le maximum entre 0,05 BB et 2 % de la cible.

Les états sont : `MATCHED`, `OUT_OF_RANGE`, `UNCOVERED`, `UNKNOWN_OBSERVED_SIZE` et `NOT_APPLICABLE`. Un sizing non couvert ne transforme pas l'action en hors range.

## Couches et version

La couche `personal` prévaut sur `calculated` pour une main définie, sans effacer la couche calculée. Le résultat expose la couche, sa version et sa provenance.

`repository_token` est un identifiant déterministe du contenu décisionnel : schéma/version, valeurs par défaut et contextes/actions/sizings. Le document range-folder brut conservé comme provenance n'entre pas dans ce token ; une modification de stratégie, elle, le change. Cela permet de reproduire le verdict après rechargement tout en conservant la source historique sans perte.

## EV et recommandation moteur

Le résultat réserve `ev_deviation_bb`, mais #98 le laisse à `null` avec `ev_status = NOT_EVALUATED`. Le replayer présente explicitement deux concepts distincts :

1. conformité au plan Hero personnel/calculé ;
2. recommandation et EV du moteur lorsqu'elles existent et ont été validées pour ce contexte.

Une range personnelle n'est donc jamais présentée comme optimale par défaut.

## Interface

Le feed affiche le verdict de plan, la fréquence prescrite et un accès à la grille. Le détail de décision expose également le sizing attendu, la couche et le token de dépôt. Un bilan jusqu'à l'étape courante agrège autorisé, hors range et non couvert par position/spot sans lire les actions futures.

Le lien vers `hero-ranges.html` transporte `population`, `position`, `stack`, `spot` et `hand`, afin d'ouvrir directement le contexte et la classe concernés.

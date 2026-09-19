# Reviewer préflop — analyse d'iso-raise et évolution des ranges adverses

## Besoin utilisateur

Le reviewer doit permettre de comprendre une décision préflop dans son contexte réel, pas seulement afficher une recommandation abstraite.

Scénario de référence :

- Hero a **KTs en SB** ;
- deux joueurs ont limpé ;
- Hero relance à **4 BB** ;
- BB, CO et BTN suivent ;
- Hero se retrouve donc à quatre joueurs au flop.

Le reviewer doit pouvoir répondre aux questions suivantes :

1. **L'action choisie était-elle bonne ?**
   - fold ;
   - limp / overlimp ;
   - iso-raise ;
   - autre action légale éventuelle.

2. **Si raise est préférable, quel sizing ?**
   - 4 BB ;
   - plus petit ;
   - plus gros ;
   - avec l'EV propre à chaque montant réellement évalué.

3. **Quelles ranges adverses étaient estimées avant la décision Hero ?**
   - les limps précédents doivent déjà modifier les distributions adverses ;
   - les bloqueurs connus doivent être pris en compte ;
   - une grille 169 où toutes les mains restent à 100 % n'est pas une range postérieure exploitable.

4. **Comment les ranges adverses évoluent-elles après leurs réponses ?**
   - après le raise Hero, un fold, call, 3-bet ou jam apporte de l'information ;
   - après les calls de BB / CO / BTN, le reviewer doit afficher leurs nouvelles distributions conditionnelles ;
   - l'évolution doit être reconstruite uniquement à partir des informations disponibles à ce moment de la main.

5. **Le sizing Hero était-il adapté pour isoler ?**
   - quelle probabilité que tout le monde fold ?
   - quelle probabilité d'obtenir exactement un caller ?
   - quelle probabilité de jouer à 3 ou 4+ ?
   - quel risque de 3-bet / jam ?
   - quelles ranges continuent selon le sizing ?
   - quelle EV finale pour Hero ?

## Principe de décision

Le moteur ne doit **pas** choisir un sizing simplement parce qu'il réduit le nombre de callers.

Un gros iso peut effectivement produire moins de callers, tout en sélectionnant une range beaucoup plus forte. Optimiser uniquement « la probabilité d'être heads-up » peut donc conduire au comportement indésirable suivant :

> miser de plus en plus cher jusqu'à n'être payé que par une range très forte.

Le critère principal reste **l'EV de Hero**.

Pour chaque sizing candidat, le moteur doit exposer comme diagnostics explicatifs :

- EV Hero ;
- probabilité de fold de tous les adversaires ;
- probabilité de 1 caller ;
- probabilité de 2 callers ;
- probabilité de 3+ callers ;
- nombre moyen de callers ;
- probabilité de 3-bet / jam ;
- ranges postérieures des joueurs qui continuent ;
- support et incertitude du modèle.

Le reviewer peut alors expliquer pourquoi un sizing est recommandé sans transformer « isoler » en objectif artificiel.

## Architecture cible

### 1. Range adverse = distribution conditionnelle, pas grille booléenne

À chaque étape de la main, chaque adversaire possède une distribution sur ses combos / 169 classes.

Elle est mise à jour chronologiquement :

```
prior
  -> action publique du joueur
  -> posterior
  -> action publique suivante
  -> nouveau posterior
```

Exemples :

- CO limp -> range CO après limp ;
- BTN limp -> range BTN après limp ;
- Hero iso 4 BB ;
- BB call -> range BB conditionnée par ce call face à 4 BB ;
- CO call -> range CO conditionnée par limp puis call de l'iso ;
- BTN call -> range BTN conditionnée par limp puis call de l'iso.

Les cartes privées non révélées et les cartes futures ne doivent jamais intervenir.

### 2. Réponse préflop conditionnée par le prix exact

Une politique qui connaît seulement la séquence `LIMP -> RAISE -> CALL`, mais pas le prix réellement proposé, ne permet pas de comparer correctement 4 BB, 5 BB ou 7 BB.

Le modèle de réaction préflop doit donc intégrer des variables publiques liées au prix, au minimum :

- montant à payer ;
- taille du pot avant décision ;
- price-to-pot / pot odds ;
- target total du raise ;
- stack effectif / SPR préflop utile ;
- position ;
- séquence d'actions ;
- nombre de limpers / callers ;
- rôle du joueur dans la séquence ;
- support statistique.

Pour mettre à jour une range après l'action, il faut idéalement estimer :

```
P(action | hand_class, contexte, sizing)
```

et pas uniquement une fréquence marginale de call/fold.

### 3. Recherche Hero

À la décision Hero, l'analyse doit comparer les alternatives légales et une grille de sizings observés / pertinents :

```
fold
overlimp
iso 3.5 BB
iso 4 BB
iso 5 BB
iso 6 BB
...
```

Pour chaque candidat :

1. reconstruire les ranges adverses avant Hero ;
2. simuler leurs réponses conditionnelles au sizing ;
3. mettre à jour leurs ranges après chaque réponse ;
4. continuer la main multiway ;
5. calculer l'EV Hero ;
6. conserver l'incertitude et le support.

L'action recommandée est celle de meilleure EV selon le protocole applicable. Les sizings proches dans l'intervalle d'incertitude doivent être présentés comme tels plutôt que surinterprétés.

## Ce qui existe déjà

Le dépôt possède déjà plusieurs briques utiles :

- `poker-preflop-decision/v1` sait représenter **FOLD / LIMP / OVERLIMP / ISO / ...**, plusieurs sizings et une EV associée à chaque alternative ;
- #106 a livré la recherche action+sizing+EV avec continuation multiway ;
- `ModelAPreflopContinuationRollout` reconstruit les cartes adverses depuis des ranges conditionnées par l'historique public ;
- `ModelAContinuationPolicy._posterior_from_history()` met déjà à jour une distribution de combos à partir des actions antérieures ;
- `model_a_latent_ranges.py` possède une reconstruction exacte-combo fail-closed ;
- #197 a démontré, côté Model B, l'intérêt d'une réponse conditionnée au prix et d'un audit de support/incertitude ;
- #196 prévoit déjà explicitement la famille **VS_LIMPERS / overlimp / iso**.

## Gap actuel

### A. Range reviewer

La capacité de posterior existe dans le moteur/training mais n'est pas exposée comme un contrat runtime stable consommé par Review.

Conséquence visible : la grille peut se comporter comme une range de base/non conditionnée, voire afficher 100 % sur les 169 classes, au lieu de montrer la distribution après les actions de la main.

### B. Le sizing exact n'entre pas suffisamment dans le contexte préflop Model A

Le contexte préflop actuel de `ModelAContinuationPolicy` reconstruit notamment :

- position ;
- famille ;
- niveau de raise ;
- joueurs live/all-in ;
- séquence position + action.

Mais l'historique sémantique utilisé pour retrouver un node préflop ne conserve pas le **montant exact du raise**.

Ainsi, deux séquences identiques en actions mais avec des sizings différents peuvent partager la même politique de réaction.

C'est insuffisant pour répondre rigoureusement à :

> « 4 BB était-il le bon iso, ou 5/6 BB aurait-il réduit le multiway avec une meilleure EV ? »

### C. Le Model B response-to-price ne ferme pas ce gap

#197 fournit une excellente base méthodologique, mais son candidat response-to-price est indépendant et n'est pas une substitution automatique à Model A.

Il faut conserver l'indépendance A/B :

- **Model A** : environnement utilisé pour calculer la stratégie Hero ;
- **Model B** : environnement indépendant servant à éprouver la robustesse de cette stratégie.

### D. Explication produit manquante

Même lorsqu'une décision action+sizing+EV existe, Review doit encore exposer le compromis :

- EV ;
- isolation ;
- nombre de callers ;
- force/range des callers ;
- risque de re-raise.

Sans cela, une recommandation « raise 6 BB » serait difficile à interpréter.

## Résultat cible dans Review

Pour le scénario KTs SB après deux limpers, le détail préflop doit pouvoir ressembler conceptuellement à :

| Alternative | EV | Tous fold | 1 caller | 2+ callers | 3-bet/jam |
|---|---:|---:|---:|---:|---:|
| Fold | ... | — | — | — | — |
| Overlimp | ... | — | ... | ... | ... |
| Iso 4 BB | ... | ... | ... | ... | ... |
| Iso 5 BB | ... | ... | ... | ... | ... |
| Iso 6 BB | ... | ... | ... | ... | ... |

Puis, pour l'action réellement jouée :

- **Hero : KTs, SB**
- **Joué : ISO 4 BB**
- **Recommandé : action + sizing + EV**
- **ΔEV du choix réel**
- **BB après call : range postérieure**
- **CO après limp puis call : range postérieure**
- **BTN après limp puis call : range postérieure**

Les 169 cases représentent des probabilités/fréquences conditionnelles, avec support et provenance, pas un faux 100 % uniforme.

## Critères de réussite globaux

Le besoin est satisfait lorsque :

- Review reconstruit les ranges adverses étape par étape ;
- les actions observées modifient réellement ces ranges ;
- le sizing Hero modifie réellement les probabilités de réponse adverses lorsque les données le permettent ;
- fold / limp / iso et plusieurs sizings sont comparés avec EV ;
- le reviewer explique le compromis isolation / sélection de range / EV ;
- un cas multiway après iso est analysable sans information future ;
- les contextes sans support suffisant échouent explicitement plutôt que d'inventer une précision ;
- Model B reste indépendant pour la validation de robustesse.

# Use case — comprendre une décision préflop dans le Reviewer

## Situation

Je rejoue une main dans **Review**.

Je suis en **SB avec KTs**. Deux joueurs ont limpé avant moi. Je décide de **raise à 4 BB**.

Après mon raise :
- BB call ;
- CO call ;
- BTN call.

Je me retrouve donc à quatre joueurs au flop.

## Ce que j'attends du Reviewer

### 1. Comprendre si mon action était bonne

Je veux savoir si, avec KTs dans cette situation, j'aurais dû :

- fold ;
- limper / overlimper ;
- raise ;
- ou choisir une autre action disponible.

Je veux voir clairement l'action recommandée, celle que j'ai réellement jouée et la différence d'EV entre les deux.

### 2. Comprendre si mon sizing était bon

Si raise est une bonne décision, je veux savoir si **4 BB** était le bon montant.

Je veux pouvoir comparer 4 BB avec d'autres sizings raisonnables et voir l'EV associée à chacun.

Je veux notamment comprendre si un autre sizing aurait eu plus de chances :

- de faire folder tout le monde ;
- de m'isoler contre un seul joueur ;
- d'éviter un pot à 3 ou 4 joueurs ;
- sans pour autant miser tellement cher que seuls les jeux très forts continuent.

Le but n'est donc pas simplement de réduire le nombre de callers : je veux savoir quel choix est le plus rentable à long terme.

### 3. Voir les ranges adverses évoluer

Je veux pouvoir voir la range estimée de chaque adversaire évoluer au fil de ses actions.

Dans cet exemple :

- la range de CO doit déjà évoluer lorsqu'il limp ;
- la range de BTN doit déjà évoluer lorsqu'il limp ;
- après mon raise à 4 BB, la range de BB doit évoluer lorsqu'il call ;
- la range de CO doit encore évoluer lorsqu'il call mon raise après avoir limpé ;
- même chose pour BTN.

Je veux ainsi comprendre **avec quelles mains chaque joueur est estimé continuer à ce moment précis de la main**.

Une grille où les 169 mains restent toutes affichées à 100 % n'est pas utile pour ce besoin.

### 4. Comprendre pourquoi je me retrouve multiway

Après avoir été payé par trois joueurs, je veux que le Reviewer puisse m'aider à répondre à des questions simples :

- Mon raise était-il trop petit ?
- Un sizing légèrement supérieur aurait-il souvent réduit le nombre de callers ?
- À partir de quel sizing les joueurs qui continuent deviennent-ils beaucoup plus forts ?
- Le pot à quatre joueurs était-il malgré tout le résultat le plus rentable compte tenu de leurs tendances ?
- Quelle part du résultat vient de mon action, de mon sizing ou simplement des réactions adverses observées ?

### 5. Avoir des commentaires adaptés à l'acteur

Sous une action **Hero**, si le spot n'est pas encore couvert, je veux que le Reviewer me le dise clairement : par exemple **« Aucune recommandation EV validée pour ce contexte »**. Je ne veux pas qu'un message ambigu me laisse penser que toutes les alternatives ont été calculées si ce n'est pas le cas.

Sous une action **adverse**, je ne veux pas voir un commentaire du type **« Aucune alternative EV validée »**, car je ne cherche pas à optimiser la décision de l'adversaire comme celle de Hero. Je veux plutôt voir ce que son action apprend sur sa range, ou un message clair indiquant que cette analyse n'est pas disponible.

## Présentation souhaitée

Au niveau de ma décision, je veux retrouver rapidement :

- **Ma main :** KTs
- **Ma position :** SB
- **Situation :** deux limpers
- **Joué :** Raise 4 BB
- **Recommandé :** action + sizing
- **EV du choix joué**
- **EV du choix recommandé**
- **Différence d'EV**

Je veux également pouvoir consulter les principales alternatives, par exemple :

| Choix | EV | Risque de multiway |
|---|---:|---|
| Fold | … | — |
| Overlimp | … | … |
| Raise 4 BB | … | … |
| Raise 5 BB | … | … |
| Raise 6 BB | … | … |

Enfin, en avançant dans la main, je veux pouvoir ouvrir la range estimée de BB, CO ou BTN et voir comment elle a changé après chacune de leurs actions.

## Résultat attendu

Le Reviewer doit me permettre de répondre simplement à trois questions :

1. **Mon action était-elle bonne ?**
2. **Mon sizing était-il bon ?**
3. **Pourquoi les adversaires ont-ils continué, et avec quelles ranges sont-ils estimés l'avoir fait ?**

L'analyse doit m'aider à améliorer ma décision future, pas seulement à constater le résultat de la main.

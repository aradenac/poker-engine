**État des lieux et reprise priorisée — Poker Engine — 12 septembre 2026**

Audit de main **caaff599**, de la PR **#44 / 899015dd**, des branches actives, du backlog et des résultats CI. Les versions citées sont figées à ces commits.

**Diagnostic**

L’application et les données historiques sont largement conservées et utilisables. La boucle « nouvelles mains → modèles → validation indépendante → meilleure stratégie → publication » reste incomplète. La priorité est de rendre ses résultats reproductibles et ses mesures pertinentes avant une nouvelle promotion du moteur.

| Composant | État vérifié | Limite actuelle |
|---|---|---|
| Analyseur/replayer | Moteur promu v83 ; v84 expérimental | Pas de grand benchmark indépendant reproductible actuel conservé. |
| Trainer | Guided, Training, Test ; ranges Hero personnalisées ; corrections de verdict et performances fusionnées | Six sièges affichés, mais exercice heads-up postflop après un pot préflop préconstruit. Pas de préflop interactif complet ni de Hero BB sans range fournie. |
| Modèle A intégré | Préflop v5 et postflop v5 | Candidats additifs du 12 septembre rejetés ; reconstruction des candidats incomplète. |
| Modèle B externe | v2 promue, trois profils | Rafraîchissement candidat sur branche ; comparaison avec la v2 sur le même holdout encore attendue. |
| Corpus approuvé | 27 735 mains uniques 100/200 | L’union annoncée de 31 003 mains inclut un nouveau ZIP absent de main. |
| Ingestion du 12 septembre | Audit annoncé : 11 896 mains, dont 3 268 nouvelles | Source binaire et incrément exact à finaliser. |
| Simulateur | PR #44 ouverte ; tests de scénarios et smoke navigateur verts | Graine moteur, contrôle des essais et entrée CLI à corriger. |
| Publication | Ingestion GitHub Actions réussie sur main | Build Cloudflare en échec ; publication de la dernière version non vérifiée. |

Les sept fichiers de modèles A/B exposés au trainer ont les mêmes blobs Git que leurs modèles promus de référence. Les gros modèles et les deux archives historiques sont donc présents. Les tâches trainer #19, #21–#24, #30 et #31 sont déjà fusionnées. Sources : [statut](https://github.com/aradenac/poker-engine/blob/caaff599707006fab3daa0f39b90b67c37fdaac1/.project/STATUS.md), [registre](https://github.com/aradenac/poker-engine/blob/caaff599707006fab3daa0f39b90b67c37fdaac1/training/registry.json).

**Constats qui changent les priorités**

1. **Source du nouveau cycle manquante — #35.** Le ZIP attendu fait 2 509 906 octets, SHA-256 374f8dedf5eeeee26b2cd049b1729f80bd2877c6f7ccef806c580019c5f94fcb. Il faut conserver ses octets exacts puis reproduire les 3 268 nouveaux IDs : 2 606 TRAIN, 320 VALIDATION, 342 TEST. Les fragments de staging inspectés ne constituent pas l’archive. Le benchmark sur l’ancien corpus peut avancer indépendamment. [Ticket](https://github.com/aradenac/poker-engine/issues/35)

2. **Reproductibilité partielle de la PR #44 — #9.** Les cartes et profils sont déterministes, mais les workers Hero utilisent Math.random() sans graine fournie par l’oracle. Trois invocations isolées du même worker d’agression, sur une entrée identique à 2 500 essais, ont donné 5,292 ; 4,584 ; 4,788 BB. Cette variation Monte-Carlo est normale ; elle contredit une reproduction exacte des EV/choix. Il faut initialiser aussi l’aléatoire du moteur, par scénario, état et candidat. [Workers](https://github.com/aradenac/poker-engine/blob/caaff599707006fab3daa0f39b90b67c37fdaac1/site/index.html), [oracle](https://github.com/aradenac/poker-engine/blob/899015dd4d29ffcdb9130ddb10d74347b856a0c1/tools/simulation/sequential_postflop.py)

3. **Contrat CLI incomplet — #9.** Le remplacement de texte destiné à appliquer --trials cherche « snap.trials=2500 », absent du HTML actuel. La valeur annoncée dans les métadonnées ne prouve donc pas le budget réellement utilisé. L’appel direct du wrapper Python avec --help échoue sur « No module named 'tools' ». Il manque également un choix explicite du modèle B candidat sans modification du registre de production, et une vérification des empreintes lors de la réutilisation des scénarios. [Critères ajoutés](https://github.com/aradenac/poker-engine/issues/9)

4. **Réalisme de B insuffisant pour conclure seul sur les sizings — #46.** Les probabilités d’action utilisent profil, street, mode, position relative, type de pot et rôle préflop ; elles n’intègrent pas la force des cartes, le board, le prix relatif à payer ou le SPR. Le prix intervient seulement dans le masque de légalité de relance. Les cartes adverses servent au showdown, sans conditionner ces actions. Mon évaluation : optimiser uniquement contre ce comportement peut exploiter une simplification du simulateur. Le conditionnement et la sensibilité doivent être validés avec des données suffisantes. L’indépendance architecturale A/B n’élimine pas les biais communs d’un même corpus. [Runtime](https://github.com/aradenac/poker-engine/blob/899015dd4d29ffcdb9130ddb10d74347b856a0c1/tools/simulation/model_b_runtime.py), [chantier créé](https://github.com/aradenac/poker-engine/issues/46)

5. **Rejets du modèle A documentés, candidats non reconstructibles — #7.** VALIDATION préfère le poids nul pour les deux candidats du 12 septembre : retenir v5 est cohérent avec le protocole. Le faible gain sur TEST ne doit pas inverser cette sélection. Mais ce cycle ne contient sur main qu’un rapport avec des SHA de candidats locaux ; les anciens scripts d’extraction/overlay utilisent encore /mnt/data. #36/#37 restent clos pour leur décision de rejet, avec la dette de reconstruction suivie dans #7. La branche #38 ne conserve encore que le rapport de sélection et un workflow d’export de l’ancien modèle B, sans ses nouveaux artefacts complets ni comparaison appariée. [Rapport A](https://github.com/aradenac/poker-engine/blob/caaff599707006fab3daa0f39b90b67c37fdaac1/training/runs/20260912_population_increment_cycle/evaluation/model_a_incremental_selection.json), [état B](https://github.com/aradenac/poker-engine/issues/38)

6. **Couverture CI incomplète — #12.** Le workflow trainer appelle le test statique principal et le smoke, mais pas les cinq scripts dédiés aux ranges, au cache, au préchargement, à la latence et au parallélisme. La main pathologique et les audits du dossier regression n’ont pas de runner automatisé. La PR #44 compare deux générations de scénarios, pas deux rollouts complets. Les seuils de validation doivent être définis avant de sélectionner une nouvelle stratégie. [Workflow trainer](https://github.com/aradenac/poker-engine/blob/caaff599707006fab3daa0f39b90b67c37fdaac1/.github/workflows/trainer-smoke.yml), [workflow arène](https://github.com/aradenac/poker-engine/blob/899015dd4d29ffcdb9130ddb10d74347b856a0c1/.github/workflows/sequential-arena.yml)

7. **Déploiement à diagnostiquer — #45.** Le check Cloudflare échoue sur main caaff599 et sur la PR #44. Les logs fournisseur sont nécessaires pour identifier la cause. Cela ne démontre pas une panne du site précédemment publié. Il faut vérifier l’URL et le commit effectivement servi ; le champ published du manifeste n’est pas une preuve. Le manifeste devrait aussi distinguer le SHA de la release moteur et celui du site assemblé avec le trainer. [Ticket et liens des builds](https://github.com/aradenac/poker-engine/issues/45)

**Backlog classé**

P0 : blocage immédiat. P1 : fiabilité des preuves et prérequis de sélection. P2 : amélioration, promotion et automatisation. P3 : conservation historique. Ces rangs sont inscrits dans les tickets ; les epics #2/#43 restent des outils de coordination.

| Rang | Priorité | Ticket | Critère de sortie |
|---:|:---:|---|---|
| 1 | P0 | [#35 Source du 12 septembre](https://github.com/aradenac/poker-engine/issues/35) | ZIP exact, audit, IDs et splits vérifiés. |
| 2 | P0 | [#9 Simulateur / PR #44](https://github.com/aradenac/poker-engine/issues/9) | Graine moteur, essais effectifs, CLI et répétition complète vérifiés. |
| 3 | P0 | [#45 Cloudflare](https://github.com/aradenac/poker-engine/issues/45) | Déploiement réussi ; URL et build identifiés. |
| 4 | P1 | [#12 Contrat de validation](https://github.com/aradenac/poker-engine/issues/12) | Seuils préétablis ; régressions raccordées à la CI. |
| 5 | P1 | [#7 Reconstruction A](https://github.com/aradenac/poker-engine/issues/7) | Scripts, candidats rejetés et résultats reproductibles depuis GitHub. |
| 6 | P1 | [#10 Référence v83 + B v2](https://github.com/aradenac/poker-engine/issues/10) | Benchmark figé, périmètre explicite et incertitudes calculées. |
| 7 | P1 | [#38 Rafraîchissement B](https://github.com/aradenac/poker-engine/issues/38) | Candidat conservé, comparaison appariée, décision séparée. |
| 8 | P1 | [#46 Réalisme de B](https://github.com/aradenac/poker-engine/issues/46) | Sensibilité et réponses validées pour les sizings évalués. |
| 9 | P1 | [#39 Nouvelle référence](https://github.com/aradenac/poker-engine/issues/39) | Dérive de l’environnement isolée du changement de stratégie. |
| 10 | P2 | [#11 Évaluation des stratégies](https://github.com/aradenac/poker-engine/issues/11) | Capacité de comparaison, exécutée avec #40 pour ce cycle. |
| 11 | P2 | [#40 Candidat stratégique](https://github.com/aradenac/poker-engine/issues/40) | Sélection sur VALIDATION ; finaliste sur TEST ; gain et limites documentés. |
| 12 | P2 | [#41 Tous les contrôles](https://github.com/aradenac/poker-engine/issues/41) | Rapport PASS/FAIL par composant. |
| 13 | P2 | [#42 Clôture / promotion](https://github.com/aradenac/poker-engine/issues/42) | Décisions indépendantes, artefacts et rollback cohérents. |
| 14 | P2 | [#13 Automatisation](https://github.com/aradenac/poker-engine/issues/13) | Automatiser un cycle déjà validé, y compris son chemin de rejet. |
| 15 | P3 | [#1 Archives historiques](https://github.com/aradenac/poker-engine/issues/1) | Compléter la v78 historique, sans bloquer la reprise. |

Les capacités #7/#11/#12/#13 et les tâches du cycle #36–#42 se recouvrent : ne pas compter deux fois une même implémentation ou un même benchmark.

**Reprise recommandée**

Commencer #35 et les corrections de #9. Diagnostiquer #45 indépendamment. Spécifier les critères #12 dès maintenant. Dès #9 validé, lancer #10 sur le corpus approuvé, sans attendre le nouveau ZIP.

Ensuite, terminer la reconstruction A et la comparaison B. Pour les mesures, conserver une référence v83 + B v2 ; mesurer v83 avec l’environnement retenu après le rafraîchissement ; puis comparer le nouveau moteur à v83 avec cet environnement fixé. Appliquer les limites/contrôles #46 avant d’en tirer une décision de promotion.

Réserver des scénarios VALIDATION à l’exploration et un TEST au finaliste. Le simulateur propose actuellement TEST par défaut : réutiliser sans distinction ce même jeu pour choisir toutes les variantes consommerait le holdout. Les incertitudes doivent tenir compte des répétitions d’une même main.

L’utilité de l’arène est calculée à partir du flop : les dépenses préflop sont déjà engagées. Elle n’est donc pas un winrate global. Un regret indépendant nécessite l’évaluation des alternatives dans B ; un écart d’EV interne à A ne suffit pas.

| Lot | Effort indicatif |
|---|---|
| Source, corrections de l’arène, diagnostic du déploiement | Environ 1 à 3 jours, si ZIP et logs accessibles. |
| Reconstruction A, CI/critères, référence et comparaison B | Environ 3 à 6 jours, plus les calculs. |
| Validité de l’environnement B | Quelques jours à une semaine ou davantage selon la couverture des données ; principale incertitude. |
| Premier cycle stratégique complet puis automatisation | Environ 3 à 6 jours après prérequis, plus les benchmarks. |

Ce sont des ordres de grandeur d’effort de développement concentré, pas une promesse de durée d’exécution automatisée.

Les extensions du trainer — préflop interactif, vrais pots multiway, exercices ciblés, répétition des erreurs — viennent après la stabilisation du benchmark. La couverture multiway est pertinente pour la population visée, mais l’arène HU actuelle ne peut pas la valider. Extraire progressivement le moteur du HTML aidera les tests ; une refonte générale de l’interface n’est pas un prérequis.

**Vérifications effectuées**

Lecture de l’arbre main (173 entrées), des tickets/branches, des workflows et des chemins critiques de simulation/training. Six tests synthétiques d’ingestion réussis ; un test dépendant des archives complètes non matérialisées localement a été omis. Quatre contrats trainer de performances réussis ; syntaxe de trainer.js valide. Reproduction isolée de l’aléatoire non fixé, du paramètre --trials sans effet et de l’échec CLI.

Exécutions GitHub consultées : [trainer](https://github.com/aradenac/poker-engine/actions/runs/34702431581), [arène PR #44](https://github.com/aradenac/poker-engine/actions/runs/34708682390), [ingestion main](https://github.com/aradenac/poker-engine/actions/runs/34706735645). Leur succès ne couvre que leurs commits et périmètres respectifs.

Aucun entraînement complet, grand benchmark stratégique ou test du site public n’a été relancé pendant cet audit. Les métriques de modèles proviennent des rapports conservés, avec leurs limites de reconstruction précisées ci-dessus.

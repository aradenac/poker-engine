# Poker Engine

Dépôt persistant du moteur d'analyse et d'entraînement poker.

## Plan actif

Le plan produit et le graphe de dépendances sont pilotés par **l'issue #92 — Moteur NLHE 100/200 Zoom : préflop, ranges Hero et entraînement continu**. Les anciens tickets clos restent des acquis ; ils ne doivent pas être repris comme backlog actif parce qu'ils figurent encore dans un rapport historique.

## Besoins produit détaillés

- [Reviewer préflop : analyse d'iso-raise, sizing et évolution des ranges adverses](docs/reviewer-preflop-iso-analysis.md)

## Déploiement

- [Ouvrir l'application de production](https://poker-engine.arad-chatgpt-compositeur-repas.workers.dev/)
- [Consulter l'identité et les preuves de déploiement](site/PRODUCTION.md)
- [Console Cloudflare du service `poker-engine`](https://dash.cloudflare.com/335073663ad947e69fb7590bc22b5e73/workers/services/view/poker-engine/production)

L'identité du déploiement live courant est exposée par `/deployment-meta.css` sur l'URL de production. Elle est vérifiée indépendamment de `site/RELEASE.json`, qui décrit la release applicative promue.

## Identités à ne pas confondre

- **moteur recommandé** : release immuable sous `user/releases/` (actuellement v83) ;
- **application assemblée** : octets fonctionnels sous `site/`, identifiés par `site/RELEASE.json` ;
- **déploiement live** : révision réellement servie par Cloudflare, vérifiée et documentée dans `site/PRODUCTION.md`.

`tools/write_site_release.py --check` contrôle que l'identité de l'application correspond aux octets fonctionnels committés. `published=true` ou un build réussi ne constituent pas à eux seuls une preuve de production live.

## Organisation

- `user/` : fichiers directement utiles à l'utilisateur (releases, documentation, exports) ;
- `src/` : code source et composants du moteur ;
- `training/` : données, registres, résultats et modèles liés à l'apprentissage/calibration continue ;
- `tests/` : non-régressions, contrats et benchmarks ;
- `tools/` : scripts et utilitaires techniques ;
- `.project/` : état de travail persistant destiné aux outils/assistants (`STATUS`, `PLAN`, `HANDOFF`, conventions).

## Principe de reprise

Toute nouvelle session de travail doit commencer par :

1. lire l'issue GitHub #92 ;
2. lire `.project/STATUS.md` ;
3. lire `.project/PLAN.md` ;
4. lire `.project/HANDOFF.md` ;
5. lire `training/registry.json` ;
6. vérifier l'issue à traiter et ses dépendances avant toute modification.

Ces sources permettent de reprendre le chantier sans dépendre de l'historique d'une conversation.

## Entraînement continu

Les résultats d'entraînement/calibration sont append-only : chaque run conserve ses entrées, paramètres, métriques, preuves et décision. Une nouvelle exécution ne doit pas écraser l'historique et peut légitimement aboutir à `RETAIN_BASELINE` ou `NO_OP`. Une CI verte n'implique pas à elle seule la promotion d'un modèle ou d'une stratégie.

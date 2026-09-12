# Calibration population poker — release 2026-09-09

## Décision de release

- **Préflop v5 : ACCEPTÉ**.
- **Postflop : v5 conservé en production**. Le candidat v6 est rejeté par non-régression récente.
- **Aucune métrique de confiance EV ajoutée**.

## Nouveau lot

- 1 000 mains certaines nouvelles : 790 TRAIN / 100 VALIDATION / 110 TEST.
- Préflop : 4140 / 4185 décisions TRAIN appliquées sur nœud exact.
- Postflop : 4651 / 4696 décisions TRAIN compatibles avec un nœud v5 exact après correction de l'ordre de position postflop.

## Résultats principaux

| Jeu | Modèle | Log-loss base | Candidat | Δ relatif | Décision |
|---|---|---:|---:|---:|---|
| Nouveau VALIDATION | Préflop | 0.806419 | 0.805702 | -0.0889% | ACCEPT |
| Nouveau VALIDATION | Postflop candidat | 0.707518 | 0.707700 | +0.0257% | REJECT/BASE v5 |
| Nouveau TEST | Préflop | 0.825583 | 0.823863 | -0.2083% | ACCEPT |
| Nouveau TEST | Postflop candidat | 0.695457 | 0.695885 | +0.0616% | REJECT/BASE v5 |
| Ancien-overlap VALIDATION | Préflop | 0.843043 | 0.843003 | -0.0047% | ACCEPT |
| Ancien-overlap VALIDATION | Postflop candidat | 0.694125 | 0.693971 | -0.0222% | diagnostic |
| Ancien-overlap TEST | Préflop | 0.843441 | 0.843768 | +0.0388% | ACCEPT |
| Ancien-overlap TEST | Postflop candidat | 0.687889 | 0.687796 | -0.0135% | diagnostic |

### Ranges préflop révélées

Les policies 169 et les modèles revealed-policy v4 sont conservés à l’identique dans le modèle accepté. Leur log-loss connu est donc strictement inchangé sur les jeux de contrôle.

### Pourquoi postflop v6 est rejeté

Après correction du parseur, ~99 % des décisions postflop se raccordent exactement à la topologie v5. Malgré cela, toute pondération positive testée des nouvelles marges dégrade le nouveau VALIDATION et le nouveau TEST. Les coefficients continus et de composition n’ont pas été modifiés ; la bonne décision de non-régression est donc de conserver v5 et d’accumuler le nouveau lot dans l’overlay.

## Bootstrap TEST apparié par main

**Nouveau TEST**
- Préflop: Δ log-loss = -0.001720, IC95 bootstrap [-0.004940, +0.000244], P(amélioration)=92.5%.
- Postflop candidat: Δ log-loss = +0.000428, IC95 bootstrap [-0.000244, +0.001089], P(amélioration)=10.8%.

**Ancien TEST de chevauchement**
- Préflop: Δ log-loss = +0.000328, IC95 bootstrap [+0.000090, +0.000566], P(amélioration)=0.4%.
- Postflop candidat: Δ log-loss = -0.000093, IC95 bootstrap [-0.000409, +0.000207], P(amélioration)=72.0%.

## Artefacts de continuité

- `poker_population_increment_overlay_v2.json` : statistiques additives TRAIN corrigées, à fusionner avec les prochains lots.
- `poker_population_increment_decisions_v2.jsonl` : décisions normalisées, avec split déterministe intact.
- `RoiDePiqueNique_training2_delta_after_v4v5.zip` : les 1 000 mains nouvelles certaines.
- `build_incremental_decisions_v2.py` : extracteur corrigé (ordre postflop).

## Limite du contrôle historique

Le benchmark historique réexécuté ici utilise le sous-ensemble 100/200 de l’ancienne période qui est présent dans le nouveau ZIP et que le parseur courant récupère. Il ne remplace pas le TEST historique complet des 27 164 mains, dont les métriques de référence restent documentées dans les artefacts v4/v5.

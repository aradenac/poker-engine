# Production Cloudflare

URL publique de production :

- https://poker-engine.arad-chatgpt-compositeur-repas.workers.dev/

La révision effectivement servie est identifiable indépendamment de `site/RELEASE.json` via :

- `https://poker-engine.arad-chatgpt-compositeur-repas.workers.dev/deployment-meta.css`

Ce fichier est généré pendant le build Cloudflare et contient le commit Git, la branche, le build ID et l'horodatage de déploiement. Il constitue le pointeur opérationnel vers l'identité du déploiement courant ; `site/RELEASE.json` décrit pour sa part la release applicative promue.

## Vérification indépendante du 2026-09-14

Le déploiement suivant a été vérifié depuis un runner GitHub externe au build Cloudflare :

- commit Git : `5f8b836060ea016c359c8a859db9a7b35e0b2ed6`
- branche : `main`
- Cloudflare build ID : `fb09ab55-8b92-409a-9835-da3d432ae748`
- Cloudflare version ID : `56cd6e46-214a-4ee0-b99d-9815487ca765`
- URL de version : `https://56cd6e46-poker-engine.arad-chatgpt-compositeur-repas.workers.dev/`
- SHA-256 de la racine HTML servie : `c617fb2dc8e4109f58fdb34946acdfe5cd89b6868c61e61d9066e5c555d5bd32`
- `generated_at` exposé par `deployment-meta.css` : `2026-09-14T21:19:11Z`

La racine de production et la racine de l'URL de version étaient byte-for-byte identiques pour cette vérification. Les deux servaient HTTP 200 avec le titre `Poker Range Equity — Offline v83`.

### Smoke live

La vérification HTTP a confirmé l'accessibilité de `RELEASE.json` et de tous les fichiers sous `site/assets/trainer/` (Hero, Model A et Model B).

Le smoke Chromium sur la production a confirmé :

- chargement HTTP 200 sans erreur page ni console ;
- présence de l'analyseur, de l'équité, du trainer et des contrôles de street ;
- ouverture d'une main Trainer 6-max issue des ranges persistées ;
- passage en mode Guided ;
- recommandation réelle `BET · 125% pot · 8,13 BB`, avec coût interne `8.125 BB` et EV `6.7053189454776545 BB` ;
- exécution de l'action recommandée puis feedback reprenant exactement le même label, coût et EV ;
- perte EV `0 BB` et réutilisation de la recommandation (`reused=1`).

Preuves GitHub Actions :

- run `34898763579`, artifact `10369971577` — smoke HTTP + assets + navigateur + Guided ACTION/sizing/EV ;
- run `34898903114`, artifact `10368714812` — identité production/version, commit et build Cloudflare.

Ces enregistrements prouvent un déploiement précis. Pour connaître l'identité du déploiement courant après un commit ultérieur, consulter `deployment-meta.css` sur l'URL de production.

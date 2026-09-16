# Certified Zoom postflop response refit result

- Population: `pokerstars_nlhe_100-200_zoom_play_6max_v1`
- Candidate SHA-256 (uncompressed): `8cde4cf526feea5fa68f62afaa904a799d5faa3a53164c2f4dfb265ff5433733`
- Candidate archive SHA-256: `bfd2937c9e198414dff13d72535bbfbde17c7d44b7ae0cdb850667daf28233e7`
- Stage A decision: `PROMOTE_CANDIDATE_SCIENTIFICALLY`
- Production effect: none
- TEST consumed: no

The runtime-consumed public response coefficients improved VALIDATION log loss
from 0.681563 to 0.679343 across 13,066 identical rows. The paired-hand mean
delta is -0.003035 with a 95% interval of [-0.005192, -0.000628]. All six
street/mode response models changed. Model nodes, combo policy and hand-policy
prior remain frozen in this Stage A candidate.

`LATENT_AUDIT.json` records the admissible fail-closed Stage B support.
Issue #102 remains incomplete until the independently selected combo-policy
Stage B candidate is implemented and evaluated.

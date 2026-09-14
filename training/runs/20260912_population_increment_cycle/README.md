# 2026-09-12 NLHE 100-200 training cycle

This run is closed. The unified promotion gate passed as a process/integrity gate, but every trained strategy/model candidate was rejected or retained behind the existing production baseline.

## Final outcome

| Component | Decision | Production state |
|---|---|---|
| Model A preflop | `RETAIN_BASELINE` | `preflop_population_model_v5.json` |
| Model A postflop | `RETAIN_BASELINE` | `postflop_population_model_v5.json` |
| Independent Model B | `RETAIN_BASELINE` | `independent_model_b_v2` |
| Hero strategy | `RETAIN_BASELINE` | engine `v83` |

The production transition is therefore `NO_OP_RETAIN_ALL`: `training/registry.json`, promoted models, the v83 release, and `site/index.html` are unchanged by this cycle.

The strategy VALIDATION gate compared 96 base hands × 2 repetitions (192 paired scenarios) against the corrected response-conditioned Model B v3 evaluation environment. `cap_3` and `cap_4` both had positive mean deltas but confidence intervals crossed zero, so neither candidate was eligible. No finalist was frozen and protected strategy TEST was not consumed.

## Source state

- population: `NLHE 100-200`;
- source snapshot: `training/datasets/NLHE_100-200/snapshots/20260912/source/RoiDePiqueNique.zip`;
- 3,268 genuinely unseen 100/200 hands;
- deterministic split: 2,606 TRAIN / 320 VALIDATION / 342 TEST;
- resulting union: 31,003 unique 100/200 hands;
- selected-ID fingerprint: `9eb753baed592b48d697ad6d00652612de6153e5033448f41983bccc9e31be2b`.

## Authoritative closure artifacts

- cycle manifest: `manifest.json`;
- unified gate evidence: `training/gates/20260912_evidence.json`;
- unified gate report: `training/gates/20260912_report.json`;
- immutable final state: `FINAL_STATE.json`;
- final-state generator/verifier: `tools/finalize_training_cycle.py`;
- strategy decision: `training/runs/20260913_strategy_candidate_v84/decision.json`.

`FINAL_STATE.json` records exact SHA-256 identities for the dataset evidence, promoted Model A files, all promoted Model B v2 artifacts, engine v83, strategy evidence, gate report, rollback pointers, and the before/after registry Git blob. It is generated deterministically and CI verifies byte-for-byte regeneration.

## Reproduce the final state

From a clean checkout containing the final gate evidence:

```bash
python3 tools/evaluate_promotion_gates.py \
  --evidence training/gates/20260912_evidence.json \
  --contract training/PROMOTION_GATE_CONTRACT.json \
  --out /tmp/20260912_gate_report.json \
  --require-ready
cmp /tmp/20260912_gate_report.json training/gates/20260912_report.json

python3 tools/finalize_training_cycle.py \
  --gate-merge-commit 2b824196b08b3f0e6a345859250c12f0878c8c00 \
  --expected-registry-blob bbf2ea6f32f7ac8aea5dd92c4ed0f4839c6d7879 \
  --out training/runs/20260912_population_increment_cycle/FINAL_STATE.json \
  --check
```

Deployment/public URL verification is intentionally separate under #45: this cycle did not promote or modify any site/application artifact.

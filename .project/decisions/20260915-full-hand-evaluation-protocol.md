# Full-hand and preflop evaluation protocol — 2026-09-15

Decision owner: issue #99.  The machine-readable source of truth is `training/full_hand/FULL_HAND_EVALUATION_PROTOCOL_20260915.json`.

## Why this protocol exists

The historical strategy campaign is valid only for a heads-up postflop arena.  It cannot justify a preflop or multiway strategy change.  Before #101–#108 produce new fits or candidates, the target population, holdouts, budgets, metrics and decision rules are therefore frozen.

## Frozen population and holdouts

The target is `pokerstars_nlhe_100-200_zoom_play_6max_v1`, certified from 23,789 unique PokerStars hand IDs with fingerprint `4661c200fab5a24ce67a45f0801acd0238c701f55e8dbeeaf3e8299fa250119c`.

The certified split is 19,016 TRAIN / 2,324 VALIDATION / 2,449 TEST.  Promotion-oriented comparisons use all available unique VALIDATION hands and, for the single frozen finalist, all available unique TEST hands.  Repeated simulations are clustered by independent hand ID rather than treated as independent samples.

TEST cannot choose a candidate, select an alternative or trigger same-cycle retuning.  Its consumption is tracked in `training/full_hand/TEST_HOLDOUT_LEDGER.json`; once a generation has been inspected for a final scientific decision, a later retuned candidate needs a new temporal TEST generation.

## Thresholds and diagnostics

The strategy decision metric becomes net `bb_per_100_full_hands`, from blind posting through settlement, rather than conditional postflop utility.  VALIDATION selects a finalist only when the paired 95% confidence interval for candidate-minus-incumbent has lower bound >= 0.  TEST applies the same non-regression threshold to that frozen finalist.  Otherwise the result is `RETAIN_BASELINE`.

The Model B numerical guardrails are not re-invented: they are required to remain exactly aligned with `training/PROMOTION_GATE_CONTRACT.json`.  Model A keeps paired log-loss non-regression as its hard selection rule while calibration, support, coverage and backoff diagnostics become mandatory reporting.  Those diagnostics deliberately have no fabricated absolute threshold in this issue; a future threshold requires evidence and a new pre-result protocol version.

A Hero promotion must also report context breakdowns and sensitivity under the nominal Model B plus at least two predeclared plausible Model B variants.  This is a robustness requirement, not a claim that those variants identify the true population exactly.

## Budget rule

The full-hand protocol inherits the already frozen strategic benchmark defaults of two rollouts per base hand, 1,200 analyser trials per decision and master seed 20260912.  Reduced-budget runs are allowed only as `PILOT`/`DEBUG`; they are never promotion-eligible.

## Successor tickets

- #100/#105 provide the full-hand and multiway accounting/simulation needed to execute the strategy part of this protocol.
- #101/#102/#103/#104 produce the Model A/B candidates and environments whose metrics are defined here.
- #106/#107 produce the preflop Hero candidate.
- #108 executes the frozen strategy comparison and records PROMOTE/RETAIN evidence.

Changing these scientific rules after seeing candidate results is prohibited.  A semantic change requires a new immutable protocol file/version committed before the affected experiment.

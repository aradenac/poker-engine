# Continuous-cycle automation

This directory contains repository-native orchestration contracts for issue #13.

## Safety model

`tools/training/run_continuous_cycle.py` is the automation boundary. Version 1 is deliberately **validation-only**:

- stage commands are explicit argv arrays; no shell command string is evaluated;
- the contract declares all promoted/production paths that must remain unchanged;
- those paths are copied to a temporary rollback snapshot before the first stage;
- after every stage, production identities are compared with the snapshot;
- a failed stage, a missing output, an unexpected production write, or a non-ready promotion gate causes a non-zero result;
- if production changed, the runner restores the protected files/directories before returning;
- stages may have a declarative JSON `when` condition, used for protected holdout control;
- v1 rejects every `promotion_mode` except `disabled`.

A candidate build is therefore allowed to write only outside the protected production paths. A green candidate build is not promotion authorization.

## Reference cycle — Model A / unified gate

`reference_cycle_20260912.json` replays the repository-native parts of the closed `NLHE 100-200` cycle:

1. dataset increment and persisted-snapshot contracts;
2. deterministic 3,268-hand decision normalization;
3. Model A overlay construction;
4. preflop and postflop candidate rebuilds into `/tmp`;
5. unified promotion gate regeneration with `--require-ready`;
6. byte comparison of the regenerated gate with the immutable canonical gate report.

## Reference cycle — Model B / protected strategy selection

`reference_model_b_strategy_20260912.json` extends the validation-only chain without touching production:

1. rebuild TRAIN-only Model B player features from the approved three-archive `100/200` lineage;
2. rebuild the same K3 candidate in `/tmp`;
3. score candidate and incumbent on the identical enlarged VALIDATION/TEST holdout;
4. rerun the paired bootstrap promotion comparison and verify it against the immutable cycle evidence;
5. rerun the frozen Hero strategy VALIDATION gate;
6. execute the protected TEST confirmation stage **only** when `validation_selection.json.test_authorized == true`.

For the closed 2026-09-12 cycle, no strategy candidate cleared VALIDATION, so the TEST stage is recorded as `SKIPPED` and the protected holdout remains unconsumed.

The Model B summary contains the CLI feature-source path, so a safe `/tmp` rebuild cannot have the same full-file SHA as the historical candidate. Reference verification therefore ignores only `features.path` in that summary and still requires exact paired metrics/guardrails/decision plus exact hashes for profiles, preflop ranges, postflop actions and sizing artifacts.

The protected set includes `training/registry.json`, all promoted Model A files, promoted Model B v2 model files, `user/releases/`, and the complete assembled `site/` tree.

Atomic promotion remains a separate follow-up (#80). Promotion must never be inferred merely from successful training commands.

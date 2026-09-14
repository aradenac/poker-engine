# Continuous-cycle automation

This directory contains repository-native orchestration contracts for issue #13.

## Safety model

`tools/training/run_continuous_cycle.py` is the first automation boundary. Version 1 is deliberately **validation-only**:

- stage commands are explicit argv arrays; no shell command string is evaluated;
- the contract declares all promoted/production paths that must remain unchanged;
- those paths are copied to a temporary rollback snapshot before the first stage;
- after every stage, production identities are compared with the snapshot;
- a failed stage, a missing output, an unexpected production write, or a non-ready promotion gate causes a non-zero result;
- if production changed, the runner restores the protected files/directories before returning;
- v1 rejects every `promotion_mode` except `disabled`.

A candidate build is therefore allowed to write only outside the protected production paths. A green candidate build is not promotion authorization.

## Reference cycle

`reference_cycle_20260912.json` replays the repository-native parts of the closed `NLHE 100-200` cycle that are already reproducible:

1. dataset increment and persisted-snapshot contracts;
2. deterministic 3,268-hand decision normalization;
3. Model A overlay construction;
4. preflop and postflop candidate rebuilds into `/tmp`;
5. unified promotion gate regeneration with `--require-ready`;
6. byte comparison of the regenerated gate with the immutable canonical gate report.

The protected set includes `training/registry.json`, all promoted Model A files, promoted Model B v2 model files, `user/releases/`, and the complete assembled `site/` tree.

The next automation tranche may add candidate Model B / strategy stages and, only after an explicit atomic-promotion contract exists, a promotion mode. Promotion must never be inferred merely from successful training commands.

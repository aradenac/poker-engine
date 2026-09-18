# Continuous-cycle automation

This directory contains repository-native orchestration contracts for issue #13.

## Safety model

`tools/training/run_continuous_cycle.py` is the automation boundary:

- stage commands are explicit argv arrays; no shell command string is evaluated;
- the contract declares promoted/production paths protected by a complete rollback snapshot;
- after every training/evaluation stage, production identities are compared with that snapshot;
- a failed stage, missing output, unauthorized production write, or non-ready promotion gate returns non-zero;
- if production changed unexpectedly, the runner restores the protected files/directories before returning;
- stages may have a declarative JSON `when` condition, used for protected holdout control;
- a green candidate build is never promotion authorization by itself.

Two promotion modes exist:

- `disabled`: validation-only. Protected production must remain byte-identical throughout the cycle.
- `explicit`: requires `promotion_plan`, and the machine-readable gate must be `PASS` with `promotion_ready=true` even if the CLI did not request `--require-ready`.

## Explicit promotion transaction

An explicit plan has schema `poker-atomic-promotion/v1` and an ordered `operations` list. Each operation pins:

- an immutable candidate `source` outside every protected production path;
- a protected `destination`;
- the exact candidate `source_sha256`;
- the exact `destination_sha256_before`, or `null` when the destination is intentionally new.

Before the first production write, all operations and preconditions are checked and all candidate bytes are staged and re-hashed. The runner then replaces each destination atomically at file level. If `training/registry.json` is part of the plan it **must be the final operation**, so production pointers cannot lead the artifact transition.

The outer production snapshot makes the multi-file operation transactional: any failed replace, post-write hash mismatch, or unexpected changed protected path restores the entire pre-promotion state. Successful execution verifies that the changed protected-path set is exactly the set named by the plan.

`tests/training/test_continuous_cycle.py` exercises successful model+registry promotion, blocked gates, bad candidate hashes, invalid registry ordering, and an injected failure on the second production write to prove the first write is rolled back.

## GitHub Actions entrypoint

`.github/workflows/continuous-training-cycle.yml` is the repository-native entrypoint.

- branch/PR changes run the promotion/rollback safety contract only;
- `workflow_dispatch` accepts a **committed JSON contract under `training/automation/`** and executes it with `--require-ready`;
- arbitrary absolute paths, parent traversal, and configs outside `training/automation/` are refused;
- the machine-readable execution report is uploaded as a workflow artifact.

Thus a production-changing run requires both a reviewed committed explicit plan and an intentional workflow dispatch. Existing reference contracts remain `promotion_mode=disabled` because the 2026-09-12 cycle retained every incumbent.

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

## Reference cycle — user bundle

`reference_user_bundle_20260912.json` builds the coherent `NLHE 100-200` user bundle under `/tmp`, validates manifest/checksums/custom-range identity, and leaves production unchanged. The bundle itself is generated only from the accepted final training state.

The protected set includes `training/registry.json`, all promoted Model A files, promoted Model B v2 model files, `user/releases/`, and the complete assembled `site/` tree.


## Release handoff for no-publication outcomes

`tools/training/build_release_handoff.py` turns one immutable cycle decision into the
versioned #113 release-handoff evidence for `RETAIN`, `NO_OP` or `BLOCKED`.
It derives known terminal vocabulary when possible, hashes the snapshot,
decision, source commit and current production identities, asserts that no
deployment was attempted, and validates the generated document against
`RELEASE_HANDOFF_CONTRACT.json`.

Example for a zero-new-hands cycle:

```bash
python3 tools/training/build_release_handoff.py \
  --population-id pokerstars_nlhe_100-200_zoom_play_6max_v1 \
  --cycle-run-id <immutable-run-id> \
  --cycle-decision <run-dir>/gate.json \
  --snapshot <snapshot.zip> \
  --reason "No unseen hands in the admitted population; production remains unchanged." \
  --out <run-dir>/RELEASE_HANDOFF.json
python3 tools/validate_release_handoff.py --handoff <run-dir>/RELEASE_HANDOFF.json
```

The builder deliberately cannot produce a `PROMOTE` handoff. Promotion still
requires the separately governed content-addressed pack, atomic promotion plan,
Cloudflare production deployment and live verification/rollback evidence.

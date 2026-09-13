# Model B refresh-cycle contract

A current-cycle refresh must remain statistically independent from Model A and must be reproducible from persisted hand-history archives only.

For the 2026-09-12 enlarged lineage, the refresh uses the canonical historical 100/200 source archive, the persisted 2026-09-09 snapshot, and the exact unseen-hand increment under `training/datasets/NLHE_100-200/increments/20260912/source/selected_100_200.zip`.

The sequence is fixed:

1. Fit player features on TRAIN only.
2. Select profile count on VALIDATION only; TEST remains locked during structure selection.
3. Build the selected candidate from TRAIN only.
4. Evaluate the candidate and the currently promoted incumbent on the identical enlarged VALIDATION/TEST hand union with the same evaluator and smoothing parameters.
5. Make any promotion decision from the predeclared VALIDATION gate; inspect TEST only after that decision.
6. Persist the candidate, both holdout reports, hashes and the explicit promotion/rejection decision. Never overwrite the promoted incumbent merely because a newer candidate exists.

No Model A EV, policy, recommendation, calibration output, or engine decision is an allowed training input.

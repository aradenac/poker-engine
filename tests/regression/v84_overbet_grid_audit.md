# v84 overbet-grid audit

## Why v84 exists

In v83, bet/check spots tested 25%, 33%, 50%, 66%, 75%, 100%, 125% pot and then jumped directly to the effective all-in. That can make the all-in appear optimal simply because intermediate overbets were never evaluated.

v84 adds:

- fixed 150%, 200%, 300% pot candidates;
- adaptive candidates at 50% and 75% of the effective all-in whenever that effective all-in exceeds 300% pot;
- up to 14 sizing candidates instead of 9.

## Targeted audit of the 20 v83 effective-all-in recommendations

With v84:

- 17 remain `all-in effectif`;
- 2 become `300% pot`;
- 1 becomes `200% pot`.

Changed examples:

- `261781466304` flop: 200% pot becomes best; 300% and effective all-in are essentially tied behind it.
- `261784707982` flop: 300% pot becomes best; effective all-in is slightly lower.
- `261982346969` river: 300% pot becomes best; effective all-in is slightly lower.

For 16 of the 17 effective all-ins that remain best, the EV gap versus the second-best tested sizing exceeds `1.96 * combined Monte-Carlo SE + 0.05 BB`. Only `261784144670` is within Monte-Carlo noise.

## Interpretation

The high effective-all-in frequency is not primarily caused by a missing 150-300% grid. The population model genuinely predicts high fold rates at large call-price ratios, and many of these spots also have strong equity when called. Therefore a blanket all-in penalty would be unjustified.

The remaining question is the reliability of continuous response extrapolation far above a node's local P90. The raw TRAIN corpus does show high observed fold rates at high prices (roughly 70-80% in the 0.8-1.0 call-price region), so any tail regularization must be evidence-based rather than an arbitrary cap.

## Status

v83 remains the promoted behavioral baseline until the broader v84 regression is complete. v84 is an experimental sizing-grid improvement currently under validation.

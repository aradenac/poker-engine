# Regression suite

Permanent corpus for decisions that previously exposed engine defects or subtle behaviour.

Each regression case should preserve:

- hand/history identifier or a minimal reproducible scenario;
- relevant engine/model version;
- expected validity constraints;
- expected recommendation when the result is stable enough to assert it;
- expected ordering/invariants when exact EV is intentionally allowed to evolve;
- reason the case was added.

Important initial categories:

1. JAM recommended from tiny response samples.
2. Raise/JAM outside empirical sizing support.
3. Feed recommendation differing from action-detail argmax.
4. `sanityInvalid` sizing reappearing through a fallback.
5. Cases where call/check remains superior to aggression after calibration.
6. Ordinary decisions that must remain unchanged when pathological guardrails are tightened.

Prefer robust invariants over brittle exact-EV assertions when calibration is still evolving.

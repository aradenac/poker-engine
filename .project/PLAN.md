# Project Plan

## Phase 1 — Persist and stabilize current engine

- Import the current application baseline and useful historical artifacts.
- Apply and materialize the v79 correction set.
- Build a permanent regression corpus from hands that exposed recommendation bugs.
- Ensure all UI surfaces expose one consistent tuple: recommended action, recommended sizing, associated final EV.

## Phase 2 — Audit calibration

- Measure the influence of ordinary sizing calibration offsets (25%-125% pot).
- Compare raw EV, calibration delta and final EV across representative decisions.
- Detect systematic drift toward larger or smaller sizings.
- Replace fixed-BB offsets only if the benchmark demonstrates a structural bias.

## Phase 3 — Behaviour benchmark

Measure recommendation frequencies by context:

- fold / check / call / bet / raise / jam;
- sizing distribution;
- overbet and jam frequency;
- street;
- SPR;
- hand-strength/equity buckets;
- confidence/sample-size buckets.

Compare engine behaviour to observed population data as a diagnostic, not as a constraint forcing imitation.

## Phase 4 — Continuous learning

- Add new hand-history datasets without erasing old datasets.
- Run versioned calibration/training jobs.
- Record full provenance, parameters, metrics and output artifacts for every run.
- Evaluate candidate models against the permanent regression suite and holdout data.
- Promote a candidate only after explicit evaluation.
- Keep the previously promoted model available for rollback and comparison.

## Phase 5 — Productization

- Simplify the normal UI around the decision tuple: `ACTION — SIZING — EV`.
- Keep diagnostic/internal EV variants behind detailed/debug views.
- Produce user-facing releases independently from tool/debug artifacts.

## Working rule

Do not change calibration merely because a recommendation looks surprising. First establish whether the behaviour is caused by data scarcity, extrapolation, calibration, implementation inconsistency, or genuinely superior EV.

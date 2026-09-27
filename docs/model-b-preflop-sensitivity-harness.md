# Model B preflop sensitivity harness (#344)

## Purpose

This harness prepares the final #315 sensitivity step without consuming the still-unavailable real #314 output.

It reuses the persisted #340 Model B candidate and price-agnostic reference. It does not fit a model, read TRAIN/VALIDATION/TEST hands, change any active pointer, or make a Hero recommendation.

## Future #314 input

The future source remains `poker-preflop-decision/v1`. The adapter
`project_canonical_decision()` copies only:

- alternative id;
- Hero action;
- exact `target_total_bb`;
- exact `incremental_cost_bb`;
- decision/context identity.

Canonical EV, uncertainty, confidence, selected/recommended alternative, Model A data and recommendation fields are deliberately not copied into the Model B request.

The public context is supplied separately: Hero position/current contribution, pot before Hero acts, public preflop sequence, limper count, ordered responders, their public contribution/effective stack/profile, and the #340 response family to use before/after callers.

## Diagnostics

For ISO alternatives, the harness evaluates responders sequentially using the #340 response-to-price runtime. It exposes conditional FOLD/CALL/RAISE/JAM probabilities per responder, reach probability, support/backoff level, expected continuers, P(all fold), P(3bet or jam), caller-count partition, and pairwise sizing deltas.

RAISE/JAM ends the branch. #340 models the facing response only; this harness does not fabricate a response-to-3bet continuation model.

FOLD and OVERLIMP are preserved as canonical alternatives but reported `NOT_APPLICABLE` for Model B response-to-price.

There is no nearest-price lookup. Exact target sizing is kept in every ISO request; any empirical-bin or context backoff is the declared #340 hierarchy and is surfaced as non-identifiability.

## Synthetic preparation fixture

The persisted #344 example uses the existing #322 canonical synthetic decision with FOLD / OVERLIMP / ISO 4 / 5 / 6 BB and a separate public-context fixture. No value originates from real #314 output.

## Exact post-#314 execution

After #314 is CLOSED and its canonical artifact is persisted:

1. take the real `poker-preflop-decision/v1` artifact from #314;
2. construct the public response context from the same decision point, preserving exact action order, responder positions/contributions/stacks and public Model B profiles;
3. call `project_canonical_decision(real_decision, context=public_context)`;
4. verify the request contains no Model A/EV/recommendation features;
5. run `run_harness()` against the unchanged #340 candidate/reference identities;
6. persist the real sensitivity report separately from this synthetic #344 evidence;
7. only then evaluate the remaining sensitivity DoD of #315.

Do not reuse the synthetic #344 probabilities as evidence about real Hero strategy. #315 remains open until that later real sensitivity is completed.

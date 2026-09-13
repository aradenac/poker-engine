# v83 / response-conditioned Model B v3 strategic baseline

Issue #39 benchmark with Hero v83 and Model A frozen. The selected Model B candidate changes only postflop response/sizing and conditions FACING behavior on price-to-pot. Production pointers are unchanged.

The benchmark uses master seed 20260912, 32 base hands per split, 2 deterministic repetitions and 1200 analyser trials per decision. VALIDATION runs current/no_jam/cap_2/cap_3/cap_4; TEST runs current only. v2 and v3 consume identical cards, profiles, runouts and seeds after byte-identical profile/range dependency verification.

VALIDATION candidate-minus-v2 current-policy realized utility delta: -6.147035 BB, CI95 [-13.105774140625, -0.7307256250000073].

TEST candidate-minus-v2 current-policy realized utility delta: -3.481227 BB, CI95 [-9.784060292968748, 1.5205606054687464].

This is heads-up postflop environment evidence, not an overall cash-game win rate. It does not authorize Hero strategy or Model B production promotion. TEST is reserved confirmation evidence and must not be tuned against.

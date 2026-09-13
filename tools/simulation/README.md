# Sequential independent arena

Hero uses the selected analyser HTML and integrated Model A. Opponents use only independent Model B JSON. This harness is heads-up postflop; its utility starts at the flop and is not a session win rate.

## Run from a clean checkout

Install Python Playwright and Chromium:

```sh
python3 -m pip install playwright
python3 -m playwright install chromium
python3 -m tools.simulation.sequential_postflop --n 6 --seed 20260912 --trials 1200 --split VALIDATION --scenario-out artifacts/scenarios.json --out artifacts/arena.json
```

The compatibility entrypoint is also supported:
`python3 tools/sequential_postflop_population_sim_v4.py --help`.

Use `--engine`, `--preflop-model`, `--postflop-model` and `--model-b-dir` to select explicit artifacts. A Model B override does not edit the production registry. Reusing `--scenario-manifest` checks the selected Model B artifact hashes and uses the manifest's master seed. Generate a separate scenario manifest for a different environment.

## Reproducibility contract

The arena installs `oracle_runtime.js` into its browser only. It seeds main-thread and actual worker randomness with a stable decision/snapshot seed, using Mulberry32 and FNV-1a. Production HTML and model artifacts are not rewritten.

`--trials` must be at least 1200, the aggression worker's supported minimum. Every Monte-Carlo worker request receives the requested budget; returned trial counts are checked. Exact enumeration remains exact and is not counted as Monte-Carlo. Metadata records observed budgets, RNG contract, model/engine hashes, source-file hashes and checkout commit. Pin browser/Python versions as well when comparing across machines.

CI compares full result documents from fresh browser processes at 1200 trials, then checks an actual 2400-trial execution. A production-worker test checks seed sensitivity. Accounting fixtures cover short calls, short opening all-ins, refunds, minimum bets and attempts to raise an all-in opponent. Hero action records distinguish recommended cost from the legal executed cost.

These fixtures prove specific contracts, not strategic strength. Model B's marginal response probabilities and the HU scope still limit sizing conclusions (#46). Use VALIDATION for exploration; reserve TEST for the preselected final comparison (#10/#12). A smoke run must never justify engine or model promotion.

#!/usr/bin/env python3
"""Print one v83 review-detail payload to diagnose the analyser/oracle contract."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from tools.simulation.model_b_runtime import ModelBEnvironment
from tools.simulation.scenarios import build_scenario_manifest
from tools.simulation.sequential_postflop import AnalyzerOracle, action_line, default_paths, preflop_prefix

ROOT = Path(__file__).resolve().parents[2]


async def run(out: Path, trials: int) -> None:
    env = ModelBEnvironment.from_registry(ROOT)
    manifest = build_scenario_manifest(env=env, count=1, reps=1, master_seed=20260912, split="TEST", root=ROOT)
    scenario = manifest["scenarios"][0]
    hero = scenario["hero"]
    opponent = scenario["opponent"]
    history = [f"*** FLOP *** [{' '.join(scenario['flop'])}]"]
    if scenario["postflop_order"][0] != hero:
        history.append(f"{opponent}: checks")
    history.append(f"{hero}: checks")
    hh = preflop_prefix(scenario["raw_hand"]) + "\n" + "\n".join(history) + "\n"
    defaults = default_paths(ROOT)
    oracle = AnalyzerOracle(
        engine_html=defaults["engine"],
        preflop_model=defaults["preflop"],
        postflop_model=defaults["postflop"],
        trials=trials,
    )
    await oracle.start()
    try:
        detail = await oracle.decide(hh)
    finally:
        await oracle.close()
    out.write_text(json.dumps(detail, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(detail, indent=2, ensure_ascii=False), flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/oracle-detail.json")
    ap.add_argument("--trials", type=int, default=50)
    args = ap.parse_args()
    asyncio.run(run(Path(args.out), args.trials))


if __name__ == "__main__":
    main()

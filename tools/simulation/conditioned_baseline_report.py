#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.simulation.baseline_report import build_report


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--arena", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    arena = json.loads(Path(args.arena).read_text(encoding="utf-8"))
    report = build_report(arena)
    report["environment_variant"] = "independent_model_b_v3_response_conditioned_candidate"
    report["environment_limitations"] = [
        "Model B v3 candidate adds facing price-to-pot conditioning with explicit sparse-context backoff.",
        "The selected candidate does not add SPR or board-texture conditioning because richer variants were worse on VALIDATION.",
        "Revealed-card strength is not used for FACING response training because revealed samples omit folds by construction.",
        "The benchmark remains heads-up postflop only and does not validate preflop or multiway strategy.",
    ]
    report["promotion_status"] = {
        "model_b_candidate": "predictive_gate_passed",
        "production_effect": "NONE",
        "hero_strategy_promotion_authorized": False,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"sample": report["sample"], "variant": report["environment_variant"]}, indent=2))


if __name__ == "__main__":
    main()

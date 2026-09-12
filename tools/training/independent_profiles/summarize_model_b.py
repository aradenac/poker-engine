#!/usr/bin/env python3
"""Produce compact audit metrics from generated Model B JSON artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def without_values(row: dict) -> dict:
    return {k: v for k, v in row.items() if k != "values"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    root = args.model_dir
    summary = json.loads((root / "summary.json").read_text())
    profiles = json.loads((root / "profiles.json").read_text())
    ranges = json.loads((root / "preflop_ranges.json").read_text())
    actions = json.loads((root / "postflop_actions.json").read_text())
    sizing = json.loads((root / "sizing.json").read_text())

    global_sizing = sizing["levels"][-1]["data"].get("ALL", {})
    sizing_values = global_sizing.get("values", [])
    by_context = {}
    for key, row in sizing["levels"][2]["data"].items():
        by_context[key] = without_values(row)

    action_by_street_mode = actions["levels"][4]["data"]
    global_actions = actions["levels"][-1]["data"].get("ALL", {"n": 0, "counts": {}})
    global_ranges = ranges["levels"][-1]["data"].get("ALL", {"n": 0, "counts": {}})

    metrics = {
        "schema": "independent-opponent-model-b-metrics/v1",
        "model_schema": summary["schema"],
        "fit_split": summary["fit_split"],
        "profile_summary": [
            {
                "profile": p["profile"],
                "appearance_weight": p["appearance_weight"],
                "fit_players": p["fit_players"],
                "all_players": p["all_players"],
                "centroid": p["centroid"],
            }
            for p in profiles["profiles"]
        ],
        "preflop_known_hand_observations": global_ranges["n"],
        "postflop_action_observations": global_actions["n"],
        "postflop_global_actions": global_actions["counts"],
        "postflop_actions_by_street_mode": action_by_street_mode,
        "sizing": {
            "global": without_values(global_sizing),
            "max": max(sizing_values) if sizing_values else None,
            "over_20x_count": sum(1 for x in sizing_values if x > 20),
            "over_20x_fraction": (
                sum(1 for x in sizing_values if x > 20) / len(sizing_values) if sizing_values else 0.0
            ),
            "by_street_mode_action": by_context,
        },
        "parser_or_state_anomalies": {
            k: v for k, v in summary["counts"].items() if k.startswith("invalid_")
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

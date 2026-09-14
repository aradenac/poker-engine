#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARCHIVES = [
    "training/datasets/NLHE_100-200/source/NLHE 100-200.zip",
    "training/datasets/NLHE_100-200/snapshots/20260909/source/RoiDePiqueNique_training2.zip",
    "training/datasets/NLHE_100-200/increments/20260912/source/selected_100_200.zip",
]
INCUMBENT_FEATURES = "training/runs/20260912_independent_profiles_v2/features/player_features.json"
INCUMBENT_MODEL = "training/runs/20260912_independent_profiles_v2/model"


def run(argv: list[str]) -> None:
    subprocess.run(argv, cwd=ROOT, check=True)


def archive_args() -> list[str]:
    out: list[str] = []
    for path in ARCHIVES:
        out += ["--archive", path]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-dir", default="/tmp/poker-cycle-model-b")
    ap.add_argument("--code-commit", default="reference-cycle-20260912")
    args = ap.parse_args()
    work = Path(args.work_dir)
    features = work / "features/player_features.json"
    summary = work / "features/summary.json"
    model = work / "model"
    candidate_eval = work / "candidate_holdout.json"
    incumbent_eval = work / "incumbent_holdout.json"
    comparison = work / "paired_comparison.json"
    work.mkdir(parents=True, exist_ok=True)

    common = archive_args() + ["--stake", "100/200", "--exclude-player", "RoiDePiqueNique"]
    run(["python3", "tools/training/independent_profiles/build_player_features.py", *common,
         "--min-hands", "30", "--prior-strength", "40",
         "--output", str(features), "--summary", str(summary)])
    run(["python3", "-m", "tools.training.independent_profiles.build_model_b",
         "--features", str(features), *common, "--profiles", "3", "--output-dir", str(model)])
    run(["python3", "-m", "tools.training.independent_profiles.evaluate_model_b",
         "--features", str(features), "--model-dir", str(model), *common,
         "--action-alpha", "1", "--range-prior-strength", "50",
         "--output", str(candidate_eval), "--prediction-contract", str(model / "prediction_contract.json")])
    run(["python3", "-m", "tools.training.independent_profiles.evaluate_model_b",
         "--features", INCUMBENT_FEATURES, "--model-dir", INCUMBENT_MODEL, *common,
         "--action-alpha", "1", "--range-prior-strength", "50", "--output", str(incumbent_eval)])
    run(["python3", "tools/training/independent_profiles/compare_model_b_paired.py",
         "--incumbent-features", INCUMBENT_FEATURES,
         "--incumbent-model-dir", INCUMBENT_MODEL,
         "--incumbent-evaluation", str(incumbent_eval),
         "--candidate-features", str(features),
         "--candidate-model-dir", str(model),
         "--candidate-evaluation", str(candidate_eval),
         *common, "--bootstrap-samples", "5000", "--seed", "20260913",
         "--code-commit", args.code_commit, "--output", str(comparison)])
    run(["python3", "tools/training/verify_reference_cycle_artifacts.py",
         "--model-b-report", str(comparison),
         "--candidate-summary", str(model / "summary.json")])

    report = json.loads(comparison.read_text(encoding="utf-8"))
    print(json.dumps({
        "status": "PASS",
        "comparison": str(comparison),
        "decision": report["decision"],
        "dataset": report["dataset"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

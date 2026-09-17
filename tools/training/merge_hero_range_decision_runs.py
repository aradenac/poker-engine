#!/usr/bin/env python3
"""Merge deterministic #107 partial decision runs into one immutable 169 run.

Each shard must come from the same context, models, seed, sizing evidence and
selection contract. Only the per-shard budget/coverage may differ. Duplicate or
missing hand classes fail closed.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any, Sequence

from tools.training.generate_hero_range_decisions import HAND_CLASSES, SCHEMA, export_candidate


def _stable(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _identity(run: dict[str, Any]) -> dict[str, Any]:
    provenance = copy.deepcopy(run.get("provenance") or {})
    provenance.pop("budget", None)
    return {
        "schema": run.get("schema"),
        "status": run.get("status"),
        "promotion_authorized": run.get("promotion_authorized"),
        "population_id": run.get("population_id"),
        "context": run.get("context"),
        "context_id": run.get("context_id"),
        "version": run.get("version"),
        "provenance_without_budget": provenance,
    }


def merge_runs(runs: Sequence[dict[str, Any]], *, require_complete: bool = True) -> dict[str, Any]:
    if not runs:
        raise ValueError("at least one partial run is required")
    for index, run in enumerate(runs):
        if run.get("schema") != SCHEMA:
            raise ValueError(f"shard {index}: unsupported schema {run.get('schema')!r}")

    expected = _identity(runs[0])
    for index, run in enumerate(runs[1:], 1):
        if _stable(_identity(run)) != _stable(expected):
            raise ValueError(f"shard {index}: run identity/provenance mismatch")

    rows_by_hand: dict[str, dict[str, Any]] = {}
    unsupported: list[dict[str, Any]] = []
    requested = 0
    total_rollouts = 0
    samples: set[int] = set()
    for index, run in enumerate(runs):
        coverage = run.get("coverage") or {}
        requested += int(coverage.get("requested") or 0)
        unsupported.extend(copy.deepcopy(run.get("unsupported") or []))
        budget = (run.get("provenance") or {}).get("budget") or {}
        samples.add(int(budget.get("samples_per_nonfold_candidate") or 0))
        total_rollouts += int(budget.get("rollout_samples_consumed") or 0)
        for row in run.get("rows") or []:
            hand = str(row.get("hand_class") or "")
            if hand not in HAND_CLASSES:
                raise ValueError(f"shard {index}: unknown hand class {hand!r}")
            if hand in rows_by_hand:
                raise ValueError(f"duplicate hand class across shards: {hand}")
            rows_by_hand[hand] = copy.deepcopy(row)

    if samples == {0} or len(samples) != 1:
        raise ValueError(f"shards disagree on samples_per_nonfold_candidate: {sorted(samples)}")
    if requested != len(HAND_CLASSES):
        raise ValueError(f"shard request coverage must partition exactly 169 classes, got {requested}")

    missing = [hand for hand in HAND_CLASSES if hand not in rows_by_hand]
    if require_complete and (missing or unsupported):
        raise ValueError(
            f"incomplete 169 merge: missing={len(missing)} unsupported={len(unsupported)} "
            f"examples={missing[:8] or unsupported[:3]}"
        )

    merged = copy.deepcopy(runs[0])
    merged["rows"] = [rows_by_hand[hand] for hand in HAND_CLASSES if hand in rows_by_hand]
    merged["unsupported"] = unsupported
    merged["coverage"] = {
        "requested": len(HAND_CLASSES),
        "completed": len(merged["rows"]),
        "complete_169": len(merged["rows"]) == len(HAND_CLASSES) and not unsupported,
    }
    merged["provenance"]["budget"] = {
        "requested_hand_classes": len(HAND_CLASSES),
        "completed_hand_classes": len(merged["rows"]),
        "samples_per_nonfold_candidate": samples.pop(),
        "rollout_samples_consumed": total_rollouts,
        "execution": "deterministic hand-class shards merged without changing per-hand seeds",
    }
    return merged


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--rows-out", type=Path, required=True)
    parser.add_argument("--candidate-out", type=Path)
    parser.add_argument("--allow-partial", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    runs = [json.loads(path.read_text(encoding="utf-8")) for path in args.input]
    merged = merge_runs(runs, require_complete=not args.allow_partial)
    args.rows_out.parent.mkdir(parents=True, exist_ok=True)
    args.rows_out.write_text(json.dumps(merged, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.candidate_out:
        args.candidate_out.parent.mkdir(parents=True, exist_ok=True)
        export_candidate(merged, run_path=args.rows_out, output_path=args.candidate_out)
    print(json.dumps({
        "context_id": merged["context_id"],
        "coverage": merged["coverage"],
        "budget": merged["provenance"]["budget"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Merge deterministic #107 Hero decision shards into one 169-class run."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from tools.training.generate_hero_range_decisions import HAND_CLASSES

SCHEMA = "poker-hero-range-decision-run/v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_provenance(run: Mapping[str, Any]) -> dict[str, Any]:
    provenance = copy.deepcopy(run.get("provenance") or {})
    provenance.pop("budget", None)
    provenance.pop("shard", None)
    return provenance


def merge(paths: list[Path]) -> dict[str, Any]:
    if not paths:
        raise ValueError("at least one shard is required")
    loaded: list[tuple[Path, dict[str, Any]]] = []
    for path in paths:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("schema") != SCHEMA:
            raise ValueError(f"unexpected shard schema in {path}: {data.get('schema')!r}")
        loaded.append((Path(path), data))

    first = loaded[0][1]
    invariant_keys = (
        "schema", "status", "promotion_authorized", "population_id",
        "context", "context_id", "version",
    )
    stable = _stable_provenance(first)
    samples = int(((first.get("provenance") or {}).get("budget") or {}).get("samples_per_nonfold_candidate") or 0)
    if samples < 1:
        raise ValueError("invalid shard sample budget")

    seen_shards: set[int] = set()
    shard_count: int | None = None
    by_hand: dict[str, dict[str, Any]] = {}
    unsupported: list[dict[str, Any]] = []
    rollouts = 0
    requested = 0
    completed = 0
    input_manifest = []

    for path, run in loaded:
        for key in invariant_keys:
            if run.get(key) != first.get(key):
                raise ValueError(f"shard invariant mismatch for {key}: {path}")
        if _stable_provenance(run) != stable:
            raise ValueError(f"shard provenance mismatch: {path}")
        budget = (run.get("provenance") or {}).get("budget") or {}
        if int(budget.get("samples_per_nonfold_candidate") or 0) != samples:
            raise ValueError(f"shard sample budget mismatch: {path}")
        shard = (run.get("provenance") or {}).get("shard") or {}
        index = int(shard.get("index", -1))
        count = int(shard.get("count", -1))
        if shard.get("partition") != "canonical_hand_index_modulo_shard_count":
            raise ValueError(f"unexpected shard partition contract: {path}")
        if index < 0 or count < 1 or index >= count:
            raise ValueError(f"invalid shard metadata: {path}")
        if shard_count is None:
            shard_count = count
        elif count != shard_count:
            raise ValueError("shard count mismatch")
        if index in seen_shards:
            raise ValueError(f"duplicate shard index {index}")
        seen_shards.add(index)

        expected_hands = {
            hand for i, hand in enumerate(HAND_CLASSES) if i % count == index
        }
        actual_requested = int((run.get("coverage") or {}).get("requested") or 0)
        if actual_requested != len(expected_hands):
            raise ValueError(f"shard requested count mismatch for index {index}")
        row_hands = {str(row.get("hand_class") or "") for row in run.get("rows") or []}
        unsupported_hands = {str(row.get("hand_class") or "") for row in run.get("unsupported") or []}
        if row_hands | unsupported_hands != expected_hands:
            raise ValueError(f"shard hand partition mismatch for index {index}")
        if row_hands & unsupported_hands:
            raise ValueError(f"hand both completed and unsupported in shard {index}")

        for row in run.get("rows") or []:
            hand = str(row.get("hand_class") or "")
            if hand in by_hand:
                raise ValueError(f"duplicate hand class across shards: {hand}")
            by_hand[hand] = row
        unsupported.extend(run.get("unsupported") or [])
        requested += int(budget.get("requested_hand_classes") or 0)
        completed += int(budget.get("completed_hand_classes") or 0)
        rollouts += int(budget.get("rollout_samples_consumed") or 0)
        input_manifest.append({
            "shard_index": index,
            "path": path.name,
            "sha256": sha256_file(path),
            "requested": actual_requested,
            "completed": len(run.get("rows") or []),
        })

    assert shard_count is not None
    if seen_shards != set(range(shard_count)):
        missing = sorted(set(range(shard_count)) - seen_shards)
        raise ValueError(f"missing shard indices: {missing}")
    if requested != len(HAND_CLASSES):
        raise ValueError(f"merged requested classes {requested} != 169")
    all_accounted = set(by_hand) | {str(row.get("hand_class") or "") for row in unsupported}
    if all_accounted != set(HAND_CLASSES):
        missing = [hand for hand in HAND_CLASSES if hand not in all_accounted]
        raise ValueError(f"merged shards do not account for all 169 classes: {missing[:10]}")

    rows = [by_hand[hand] for hand in HAND_CLASSES if hand in by_hand]
    merged = copy.deepcopy(first)
    merged["rows"] = rows
    merged["unsupported"] = sorted(unsupported, key=lambda row: HAND_CLASSES.index(str(row.get("hand_class"))))
    merged["coverage"] = {
        "requested": len(HAND_CLASSES),
        "completed": len(rows),
        "complete_169": len(rows) == len(HAND_CLASSES) and not unsupported,
    }
    provenance = copy.deepcopy(first["provenance"])
    provenance.pop("shard", None)
    provenance["budget"] = {
        "requested_hand_classes": len(HAND_CLASSES),
        "completed_hand_classes": len(rows),
        "samples_per_nonfold_candidate": samples,
        "rollout_samples_consumed": rollouts,
        "shard_count": shard_count,
    }
    provenance["merge"] = {
        "contract": "CANONICAL_HAND_INDEX_MODULO_SHARD_COUNT_V1",
        "input_shards": sorted(input_manifest, key=lambda row: row["shard_index"]),
    }
    merged["provenance"] = provenance
    return merged


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--inputs", type=Path, nargs="+", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--require-complete", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    merged = merge(args.inputs)
    if args.require_complete and not merged["coverage"]["complete_169"]:
        print(json.dumps({"coverage": merged["coverage"], "unsupported": merged["unsupported"][:20]}, indent=2))
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(merged, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "context_id": merged["context_id"],
        "coverage": merged["coverage"],
        "budget": merged["provenance"]["budget"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

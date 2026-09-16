#!/usr/bin/env python3
"""Build the deterministic, label-independent decision budget for Model A Stage B.

The full certified Zoom corpus is first materialized by
``build_certified_population_decisions.py``.  This tool then selects complete
hands by a stable SHA-256 rank, stratified by runtime ``street_mode`` combo-policy
model.  TRAIN selection uses only public context/support. VALIDATION selection
uses the fact that a private hand was revealed (not its cards or action outcome)
so the Stage-B conditional-composition metric can be evaluated directly.

TEST rows are never emitted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

SCHEMA = "poker-model-a-stage-b-budget/v1"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_rows(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def stable_rank(hand_id: str, split: str, model_key: str) -> str:
    return hashlib.sha256(f"stage-b-v1|{split}|{model_key}|{hand_id}".encode()).hexdigest()


def model_key(row: dict) -> str:
    return f"{row.get('street')}_{row.get('mode')}"


def select_hand_ids(
    rows: list[dict],
    postflop_model: dict,
    *,
    train_hands_per_model: int,
    validation_revealed_hands_per_model: int,
) -> tuple[set[str], dict]:
    combo_models = postflop_model.get("combo_policy_models") or {}
    candidates: dict[tuple[str, str], set[str]] = defaultdict(set)
    observed_splits = defaultdict(set)

    for row in rows:
        split = str(row.get("split") or "")
        observed_splits[split].add(str(row.get("hand_id")))
        if split not in {"TRAIN", "VALIDATION"}:
            continue
        if row.get("is_hero") or row.get("street") not in {"flop", "turn", "river"}:
            continue
        key = model_key(row)
        spec = combo_models.get(key)
        if not spec or row.get("action") not in (spec.get("classes") or []):
            continue
        if split == "VALIDATION" and len(list(row.get("known_cards") or [])) != 2:
            continue
        candidates[(split, key)].add(str(row.get("hand_id")))

    selected: set[str] = set()
    strata = {}
    keys = sorted(combo_models)
    for split, budget in (
        ("TRAIN", train_hands_per_model),
        ("VALIDATION", validation_revealed_hands_per_model),
    ):
        for key in keys:
            ids = sorted(candidates.get((split, key), set()), key=lambda hid: stable_rank(hid, split, key))
            picked = ids[:max(0, int(budget))] if budget > 0 else ids
            selected.update(picked)
            strata[f"{split}|{key}"] = {
                "eligible_hands": len(ids),
                "budget": int(budget),
                "selected_hands": len(picked),
                "selection": "sha256_rank_stage-b-v1",
            }

    return selected, {
        "strata": strata,
        "source_hands_by_split": {k: len(v) for k, v in sorted(observed_splits.items())},
    }


def build(
    decisions_path: Path,
    postflop_model_path: Path,
    out_path: Path,
    summary_path: Path,
    *,
    train_hands_per_model: int = 120,
    validation_revealed_hands_per_model: int = 60,
) -> dict:
    rows = load_rows(decisions_path)
    model = json.loads(postflop_model_path.read_text(encoding="utf-8"))
    selected_ids, selection = select_hand_ids(
        rows,
        model,
        train_hands_per_model=train_hands_per_model,
        validation_revealed_hands_per_model=validation_revealed_hands_per_model,
    )

    selected_rows = [
        row for row in rows
        if str(row.get("hand_id")) in selected_ids and str(row.get("split")) in {"TRAIN", "VALIDATION"}
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        for row in selected_rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    hand_splits: dict[str, set[str]] = defaultdict(set)
    row_counts: dict[str, int] = defaultdict(int)
    for row in selected_rows:
        split = str(row.get("split"))
        hand_splits[split].add(str(row.get("hand_id")))
        row_counts[split] += 1
    if "TEST" in hand_splits or row_counts.get("TEST", 0):
        raise AssertionError("Stage-B budget must never contain TEST")

    summary = {
        "schema": SCHEMA,
        "selection_contract": {
            "train_hands_per_runtime_model": int(train_hands_per_model),
            "validation_revealed_hands_per_runtime_model": int(validation_revealed_hands_per_model),
            "test_consumed": False,
            "train_label_policy": "selection ignores action outcome and private cards; requires only supported runtime context",
            "validation_label_policy": "selection may require reveal availability but never reads private-card identity/value for ranking",
        },
        "selection": selection,
        "selected_unique_hands_by_split": {k: len(v) for k, v in sorted(hand_splits.items())},
        "selected_rows_by_split": dict(sorted(row_counts.items())),
        "provenance": {
            "decisions": str(decisions_path),
            "decisions_sha256": sha256_file(decisions_path),
            "postflop_model": str(postflop_model_path),
            "postflop_model_sha256": sha256_file(postflop_model_path),
            "tool": str(Path(__file__)),
            "tool_sha256": sha256_file(Path(__file__)),
            "output": str(out_path),
            "output_sha256": sha256_file(out_path),
        },
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--decisions", required=True, type=Path)
    p.add_argument("--postflop-model", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--summary", required=True, type=Path)
    p.add_argument("--train-hands-per-model", type=int, default=120)
    p.add_argument("--validation-revealed-hands-per-model", type=int, default=60)
    return p.parse_args()


def main() -> None:
    a = parse_args()
    build(
        a.decisions,
        a.postflop_model,
        a.out,
        a.summary,
        train_hands_per_model=a.train_hands_per_model,
        validation_revealed_hands_per_model=a.validation_revealed_hands_per_model,
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Audit the fail-closed Model A latent-range subset for postflop refit.

Only TRAIN and VALIDATION are read.  TEST is rejected at the selection layer.
The current exact subset consists of a player's first postflop decision, whose
range can be reconstructed from Model A preflop policy plus public blockers
without needing an earlier postflop IPF update.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
from pathlib import Path

from tools.training.model_a_latent_ranges import (
    LatentRangeError,
    UnsupportedPostflopHistory,
    posterior_audit,
    posterior_before_first_postflop_action,
    revealed_label_audit,
)

SCHEMA = "poker-model-a-latent-range-audit/v1"
ALLOWED_SPLITS = {"TRAIN", "VALIDATION"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_decisions(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def group_hands(rows: list[dict]) -> list[list[dict]]:
    # increment_decisions.py emits every hand contiguously and chronologically.
    groups: list[list[dict]] = []
    current_id = None
    current: list[dict] = []
    seen = set()
    for row in rows:
        hid = str(row.get("hand_id"))
        if hid != current_id:
            if current:
                groups.append(current)
                seen.add(current_id)
            if hid in seen:
                raise ValueError(f"non-contiguous decision rows for hand {hid}")
            current_id, current = hid, []
        current.append(row)
    if current:
        groups.append(current)
    return groups


def audit(preflop_model: dict, rows: list[dict]) -> dict:
    counts = collections.Counter()
    by_split = collections.defaultdict(collections.Counter)
    by_street = collections.defaultdict(collections.Counter)
    entropy = collections.defaultdict(list)
    effective_support = collections.defaultdict(list)
    revealed_nll = collections.defaultdict(list)
    revealed_prob = collections.defaultdict(list)

    for hand_rows in group_hands(rows):
        hand_split = str(hand_rows[0].get("split") or "")
        if hand_split not in ALLOWED_SPLITS:
            counts["test_or_other_rows_not_consumed"] += len(hand_rows)
            continue
        for idx, target in enumerate(hand_rows):
            if target.get("is_hero") or target.get("street") not in {"flop", "turn", "river"}:
                continue
            split = str(target.get("split"))
            street = str(target.get("street"))
            counts["population_postflop_targets"] += 1
            by_split[split]["targets"] += 1
            by_street[street]["targets"] += 1
            try:
                posterior = posterior_before_first_postflop_action(hand_rows, idx, preflop_model)
            except UnsupportedPostflopHistory:
                counts["excluded_prior_postflop_history"] += 1
                by_split[split]["excluded_prior_postflop_history"] += 1
                by_street[street]["excluded_prior_postflop_history"] += 1
                continue
            except LatentRangeError as exc:
                reason = str(exc)
                if "missing exact preflop" in reason:
                    key = "excluded_missing_exact_preflop_node"
                elif "no embedded policy169" in reason:
                    key = "excluded_missing_policy169"
                elif "no matched preflop" in reason:
                    key = "excluded_no_matched_preflop_action"
                else:
                    key = "excluded_other_latent_error"
                counts[key] += 1
                by_split[split][key] += 1
                by_street[street][key] += 1
                continue

            pa = posterior_audit(posterior)
            ra = revealed_label_audit(posterior, target.get("known_cards"))
            counts["admitted_exact_latent_targets"] += 1
            by_split[split]["admitted"] += 1
            by_street[street]["admitted"] += 1
            entropy[split].append(float(pa["entropy_nats"]))
            effective_support[split].append(float(pa["effective_combo_support"]))
            if ra["revealed"]:
                counts["admitted_revealed_targets"] += 1
                by_split[split]["revealed"] += 1
                p = float(ra["posterior_probability"] or 0.0)
                revealed_prob[split].append(p)
                revealed_nll[split].append(float(ra["negative_log_probability"]))
            else:
                counts["admitted_hidden_targets"] += 1
                by_split[split]["hidden"] += 1

    def stats(values: list[float]) -> dict:
        if not values:
            return {"n": 0, "mean": None, "min": None, "max": None}
        return {"n": len(values), "mean": sum(values) / len(values), "min": min(values), "max": max(values)}

    targets = counts["population_postflop_targets"]
    admitted = counts["admitted_exact_latent_targets"]
    return {
        "schema": SCHEMA,
        "selection": {"splits_consumed": ["TRAIN", "VALIDATION"], "test_consumed": False},
        "current_scope": "first postflop decision per population player only; later decisions fail closed until postflop IPF parity",
        "counts": dict(sorted(counts.items())),
        "coverage": {
            "admitted_fraction": admitted / targets if targets else 0.0,
            "by_split": {k: dict(sorted(v.items())) for k, v in sorted(by_split.items())},
            "by_street": {k: dict(sorted(v.items())) for k, v in sorted(by_street.items())},
        },
        "posterior_entropy_nats": {k: stats(v) for k, v in sorted(entropy.items())},
        "effective_combo_support": {k: stats(v) for k, v in sorted(effective_support.items())},
        "revealed_combo_probability": {k: stats(v) for k, v in sorted(revealed_prob.items())},
        "revealed_combo_negative_log_probability": {k: stats(v) for k, v in sorted(revealed_nll.items())},
        "gates": {
            "target_action_leakage": "PASS_BY_CONSTRUCTION",
            "future_cards": "PASS_BY_CONSTRUCTION_TARGET_BOARD_ONLY",
            "nearest_context_substitution": "DISABLED",
            "later_postflop_without_ipf": "FAIL_CLOSED",
        },
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--preflop-model", type=Path, required=True)
    p.add_argument("--decisions", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    model = json.loads(a.preflop_model.read_text(encoding="utf-8"))
    rows = load_decisions(a.decisions)
    result = audit(model, rows)
    result["provenance"] = {
        "preflop_model": str(a.preflop_model),
        "preflop_model_sha256": sha256_file(a.preflop_model),
        "decisions": str(a.decisions),
        "decisions_sha256": sha256_file(a.decisions),
        "tool": str(Path(__file__)),
        "tool_sha256": sha256_file(Path(__file__)),
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Merge deterministic #107 partial decision runs into one immutable 169 run.

Each shard must come from the same context, models, seed, sizing evidence and
selection contract. Only the per-shard budget/coverage may differ. Every one of
the 169 hand classes must be represented exactly once, either by a completed
decision row or by an explicit unsupported record. No silent hole is allowed.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from collections.abc import Mapping
from typing import Any, Sequence

from tools.training.generate_hero_range_decisions import HAND_CLASSES, SCHEMA, export_candidate


def _stable(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)



_CLOSURE_AUDIT_COUNTER_KEYS = {
    "decisions",
    "exact_model_a_decisions",
    "support_closure_decisions",
    "support_closure_rate",
    "support_closure_by_street",
    "support_closure_reasons",
}


def _closure_audit_identity(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return only the immutable contract portion of one closure audit."""
    audit = copy.deepcopy(dict(value or {}))
    for key in _CLOSURE_AUDIT_COUNTER_KEYS:
        audit.pop(key, None)
    return audit


def _merge_closure_audits(
    audits: Sequence[Mapping[str, Any]], *, label: str
) -> dict[str, Any]:
    """Aggregate shard-local closure counters while preserving contract identity."""
    if not audits:
        raise ValueError(f"{label}: at least one closure audit is required")
    expected = _closure_audit_identity(audits[0])
    decisions = exact = fallback = 0
    by_street: dict[str, int] = {}
    reasons: dict[str, int] = {}

    for index, audit_value in enumerate(audits):
        audit = dict(audit_value or {})
        if _stable(_closure_audit_identity(audit)) != _stable(expected):
            raise ValueError(f"shard {index}: {label} contract mismatch")

        shard_decisions = int(audit.get("decisions") or 0)
        shard_exact = int(audit.get("exact_model_a_decisions") or 0)
        shard_fallback = int(audit.get("support_closure_decisions") or 0)
        if min(shard_decisions, shard_exact, shard_fallback) < 0:
            raise ValueError(f"shard {index}: {label} has negative closure counters")
        if shard_exact + shard_fallback != shard_decisions:
            raise ValueError(f"shard {index}: {label} closure accounting is incomplete")
        expected_rate = None if shard_decisions == 0 else shard_fallback / shard_decisions
        observed_rate = audit.get("support_closure_rate")
        if expected_rate is None:
            if observed_rate is not None:
                raise ValueError(f"shard {index}: {label} zero-decision rate must be null")
        elif observed_rate is None or abs(float(observed_rate) - expected_rate) > 1e-12:
            raise ValueError(f"shard {index}: {label} closure rate mismatch")

        decisions += shard_decisions
        exact += shard_exact
        fallback += shard_fallback
        for street, count in dict(audit.get("support_closure_by_street") or {}).items():
            value = int(count)
            if value < 0:
                raise ValueError(f"shard {index}: {label} has negative street counter")
            by_street[str(street)] = by_street.get(str(street), 0) + value
        for reason, count in dict(audit.get("support_closure_reasons") or {}).items():
            value = int(count)
            if value < 0:
                raise ValueError(f"shard {index}: {label} has negative reason counter")
            reasons[str(reason)] = reasons.get(str(reason), 0) + value

    merged = copy.deepcopy(expected)
    merged.update(
        {
            "decisions": decisions,
            "exact_model_a_decisions": exact,
            "support_closure_decisions": fallback,
            "support_closure_rate": None if decisions == 0 else fallback / decisions,
            "support_closure_by_street": dict(sorted(by_street.items())),
            "support_closure_reasons": dict(sorted(reasons.items())),
        }
    )
    return merged


def _merge_continuation_support(runs: Sequence[dict[str, Any]]) -> dict[str, Any]:
    closures = [
        copy.deepcopy(((run.get("provenance") or {}).get("continuation_support") or {}))
        for run in runs
    ]
    merged = copy.deepcopy(closures[0])
    for key in ("opponent_future_actions", "hero_future_actions"):
        present = [key in closure for closure in closures]
        if any(present):
            if not all(present):
                raise ValueError(f"{key}: closure audit missing from one or more shards")
            merged[key] = _merge_closure_audits(
                [closure[key] for closure in closures],
                label=key,
            )
    return merged

def _identity(run: dict[str, Any]) -> dict[str, Any]:
    provenance = copy.deepcopy(run.get("provenance") or {})
    provenance.pop("budget", None)
    continuation = provenance.get("continuation_support")
    if isinstance(continuation, Mapping):
        normalized = copy.deepcopy(dict(continuation))
        for key in ("opponent_future_actions", "hero_future_actions"):
            if key in normalized:
                normalized[key] = _closure_audit_identity(normalized[key])
        provenance["continuation_support"] = normalized
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
    unsupported_by_hand: dict[str, dict[str, Any]] = {}
    requested = 0
    total_rollouts = 0
    samples: set[int] = set()
    for index, run in enumerate(runs):
        coverage = run.get("coverage") or {}
        shard_requested = int(coverage.get("requested") or 0)
        shard_rows = list(run.get("rows") or [])
        shard_unsupported = list(run.get("unsupported") or [])
        if shard_requested != len(shard_rows) + len(shard_unsupported):
            raise ValueError(
                f"shard {index}: requested={shard_requested} but "
                f"completed+unsupported={len(shard_rows) + len(shard_unsupported)}"
            )
        requested += shard_requested
        budget = (run.get("provenance") or {}).get("budget") or {}
        samples.add(int(budget.get("samples_per_nonfold_candidate") or 0))
        total_rollouts += int(budget.get("rollout_samples_consumed") or 0)

        for row in shard_rows:
            hand = str(row.get("hand_class") or "")
            if hand not in HAND_CLASSES:
                raise ValueError(f"shard {index}: unknown hand class {hand!r}")
            if hand in rows_by_hand or hand in unsupported_by_hand:
                raise ValueError(f"duplicate hand class across shards: {hand}")
            rows_by_hand[hand] = copy.deepcopy(row)

        for item in shard_unsupported:
            hand = str(item.get("hand_class") or "")
            reason = str(item.get("reason") or "").strip()
            if hand not in HAND_CLASSES:
                raise ValueError(f"shard {index}: unknown unsupported hand class {hand!r}")
            if not reason:
                raise ValueError(f"shard {index}: unsupported {hand} has no reason")
            if hand in rows_by_hand or hand in unsupported_by_hand:
                raise ValueError(f"duplicate hand class across shards: {hand}")
            unsupported_by_hand[hand] = {"hand_class": hand, "reason": reason}

    if samples == {0} or len(samples) != 1:
        raise ValueError(f"shards disagree on samples_per_nonfold_candidate: {sorted(samples)}")
    if requested != len(HAND_CLASSES):
        raise ValueError(f"shard request coverage must partition exactly 169 classes, got {requested}")

    accounted = set(rows_by_hand) | set(unsupported_by_hand)
    missing = [hand for hand in HAND_CLASSES if hand not in accounted]
    if missing:
        raise ValueError(f"169 merge has silent missing classes: {missing[:12]}")
    if len(accounted) != len(HAND_CLASSES):
        raise AssertionError("accounted Hero hand classes must total exactly 169")
    if require_complete and unsupported_by_hand:
        examples = [unsupported_by_hand[hand] for hand in HAND_CLASSES if hand in unsupported_by_hand][:3]
        raise ValueError(
            f"incomplete 169 merge: unsupported={len(unsupported_by_hand)} examples={examples}"
        )

    merged = copy.deepcopy(runs[0])
    merged["provenance"]["continuation_support"] = _merge_continuation_support(runs)
    merged["rows"] = [rows_by_hand[hand] for hand in HAND_CLASSES if hand in rows_by_hand]
    merged["unsupported"] = [
        unsupported_by_hand[hand] for hand in HAND_CLASSES if hand in unsupported_by_hand
    ]
    merged["coverage"] = {
        "requested": len(HAND_CLASSES),
        "completed": len(merged["rows"]),
        "unsupported": len(merged["unsupported"]),
        "accounted": len(merged["rows"]) + len(merged["unsupported"]),
        "complete_169": len(merged["rows"]) == len(HAND_CLASSES) and not merged["unsupported"],
    }
    merged["provenance"]["budget"] = {
        "requested_hand_classes": len(HAND_CLASSES),
        "completed_hand_classes": len(merged["rows"]),
        "unsupported_hand_classes": len(merged["unsupported"]),
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

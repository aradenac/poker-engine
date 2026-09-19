#!/usr/bin/env python3
"""Support-aware hierarchical Model B candidate for issue #286.

TRAIN-only artifact builder and deterministic read-only runtime.
No VALIDATION/TEST data is accepted by the builder and no production pointer is changed.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from typing import Any, Iterable, Mapping, Sequence

from tools.simulation.model_b_price_response import ACTIONS, HIERARCHY, price_bucket, spr_bucket

SCHEMA = "independent-opponent-model-b-support-aware-backoff/v1"
PREDICTION_SCHEMA = "model-b-support-aware-backoff-prediction/v1"


def _key(columns: Sequence[str], row: Mapping[str, Any]) -> str:
    return "ALL" if not columns else "|".join(str(row[name]) for name in columns)


def _context(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "profile": int(row["profile"]),
        "street": str(row["street"]).lower(),
        "relative_position": str(row["relative_position"]),
        "pot_type": str(row["pot_type"]),
        "sequence": str(row["sequence"]),
        "price_bucket": price_bucket(row.get("facing_price_to_pot")),
        "spr_bucket": spr_bucket(row.get("spr")),
    }


def _quantile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    vals = sorted(float(v) for v in values)
    if len(vals) == 1:
        return vals[0]
    pos = max(0.0, min(1.0, float(q))) * (len(vals) - 1)
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    if lo == hi:
        return vals[lo]
    w = pos - lo
    return vals[lo] * (1.0 - w) + vals[hi] * w


def artifact_sha256(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def build_artifact(
    observations: Iterable[Mapping[str, Any]],
    *,
    graph: Mapping[str, Any],
    alpha_per_action: float = 1.0,
    model_version: str = "model_b_support_aware_backoff_v1_candidate_20260919",
) -> dict[str, Any]:
    if graph.get("schema") != "model-b-support-aware-backoff-graph/v1":
        raise ValueError("unsupported backoff graph schema")
    if graph.get("source_split") != "TRAIN" or graph.get("frozen_before_validation") is not True:
        raise ValueError("backoff graph must be TRAIN-derived/frozen before VALIDATION")
    expected = [list(level) for level in HIERARCHY]
    actual = [list(row.get("dimensions") or []) for row in graph.get("levels") or []]
    if actual != expected:
        raise ValueError("backoff graph differs from declared #197 hierarchy")
    alpha = float(alpha_per_action)
    if not math.isfinite(alpha) or alpha <= 0:
        raise ValueError("alpha_per_action must be positive finite")

    action_counts = [defaultdict(Counter) for _ in HIERARCHY]
    hands = [defaultdict(set) for _ in HIERARCHY]
    sizing_values = [defaultdict(list) for _ in HIERARCHY]
    sizing_hands = [defaultdict(set) for _ in HIERARCHY]
    total = 0
    raise_total = 0

    for raw in observations:
        if str(raw.get("source_split", "TRAIN")) != "TRAIN":
            raise ValueError("builder accepts TRAIN observations only")
        hand_id = str(raw.get("hand_id") or "")
        if not hand_id:
            raise ValueError("TRAIN observation missing hand_id")
        ctx = _context(raw)
        action = str(raw.get("action") or "").upper()
        if action not in ACTIONS:
            raise ValueError(f"unsupported action: {action!r}")
        sizing = raw.get("raise_sizing_ratio")
        clean_sizing = None
        if sizing is not None:
            clean_sizing = float(sizing)
            if action != "RAISE" or not math.isfinite(clean_sizing) or clean_sizing <= 0:
                raise ValueError("invalid raise sizing")
            raise_total += 1
        total += 1
        for level_index, columns in enumerate(HIERARCHY):
            key = _key(columns, ctx)
            action_counts[level_index][key][action] += 1
            hands[level_index][key].add(hand_id)
            if clean_sizing is not None:
                sizing_values[level_index][key].append(clean_sizing)
                sizing_hands[level_index][key].add(hand_id)

    if not total:
        raise ValueError("no TRAIN observations")

    levels = []
    for idx, columns in enumerate(HIERARCHY):
        data = {}
        for key in sorted(action_counts[idx]):
            counts = action_counts[idx][key]
            values = sizing_values[idx].get(key, [])
            data[key] = {
                "source_split": "TRAIN",
                "observations": int(sum(counts.values())),
                "distinct_hands": len(hands[idx][key]),
                "action_counts": {a: int(counts.get(a, 0)) for a in ACTIONS},
                "raise_observations": len(values),
                "distinct_raise_hands": len(sizing_hands[idx].get(key, set())),
                "raise_sizing_ratios": [float(v) for v in values],
            }
        levels.append({"index": idx, "dimensions": list(columns), "data": data})

    return {
        "schema": SCHEMA,
        "model_version": model_version,
        "status": "CANDIDATE_NOT_PROMOTED",
        "fit_split": "TRAIN",
        "test_consumed": False,
        "production_effect": "NONE",
        "automatic_promotion": False,
        "alpha_per_action": alpha,
        "graph_identity": {
            "schema": graph["schema"],
            "version": graph["version"],
            "levels": actual,
        },
        "thresholds": {
            "action": dict(graph["action_support"]),
            "sizing": dict(graph["sizing_support"]),
        },
        "feature_contract": {
            "allowed_dimensions": list(HIERARCHY[0]),
            "forbidden_sources": ["model_a_ev", "model_a_policy", "model_a_recommendation"],
            "nearest_context_heuristic": False,
            "silent_pooling": False,
        },
        "training_counts": {
            "decisions": total,
            "raise_sizings": raise_total,
        },
        "levels": levels,
    }


def validate_artifact(document: Mapping[str, Any]) -> None:
    if document.get("schema") != SCHEMA:
        raise ValueError("unsupported support-aware artifact schema")
    if document.get("fit_split") != "TRAIN" or document.get("test_consumed") is not False:
        raise ValueError("support-aware candidate must be TRAIN-only and TEST-unconsumed")
    if document.get("status") != "CANDIDATE_NOT_PROMOTED":
        raise ValueError("candidate must remain unpromoted")
    if document.get("production_effect") != "NONE" or document.get("automatic_promotion") is not False:
        raise ValueError("candidate must have no production effect")
    contract = document.get("feature_contract") or {}
    if contract.get("nearest_context_heuristic") is not False or contract.get("silent_pooling") is not False:
        raise ValueError("undeclared context mixing is forbidden")
    if tuple(contract.get("allowed_dimensions") or ()) != tuple(HIERARCHY[0]):
        raise ValueError("feature dimensions differ from #197")
    levels = document.get("levels") or []
    if [tuple(x.get("dimensions") or ()) for x in levels] != list(HIERARCHY):
        raise ValueError("artifact hierarchy differs from frozen graph")


class SupportAwareBackoffModel:
    def __init__(self, document: Mapping[str, Any]) -> None:
        self.document = dict(document)
        validate_artifact(self.document)
        self.alpha = float(self.document["alpha_per_action"])
        self.action_threshold = dict(self.document["thresholds"]["action"])
        self.sizing_threshold = dict(self.document["thresholds"]["sizing"])
        self.identity = {
            "schema": SCHEMA,
            "model_version": str(self.document["model_version"]),
            "artifact_sha256": artifact_sha256(self.document),
            "production_effect": "NONE",
        }

    @staticmethod
    def _support(node: Mapping[str, Any]) -> dict[str, int]:
        return {
            "observations": int(node.get("observations", 0)),
            "distinct_hands": int(node.get("distinct_hands", 0)),
            "raise_observations": int(node.get("raise_observations", 0)),
            "distinct_raise_hands": int(node.get("distinct_raise_hands", 0)),
        }

    def _action_ok(self, node: Mapping[str, Any]) -> bool:
        s = self._support(node)
        return (
            s["observations"] >= int(self.action_threshold["min_observations"])
            and s["distinct_hands"] >= int(self.action_threshold["min_distinct_hands"])
        )

    def _sizing_ok(self, node: Mapping[str, Any]) -> bool:
        s = self._support(node)
        return (
            s["raise_observations"] >= int(self.sizing_threshold["min_raises"])
            and s["distinct_raise_hands"] >= int(self.sizing_threshold["min_distinct_hands"])
        )

    def _select(self, row: Mapping[str, Any], *, sizing: bool = False):
        ctx = _context(row)
        last = None
        failed = []
        for level in self.document["levels"]:
            dims = tuple(level["dimensions"])
            key = _key(dims, ctx)
            node = (level.get("data") or {}).get(key)
            if node is None:
                failed.append({"level": int(level["index"]), "reason": "NO_TRAIN_NODE"})
                continue
            last = (level, key, node)
            ok = self._sizing_ok(node) if sizing else self._action_ok(node)
            if ok:
                reason = "EXACT_CONTEXT_SUPPORTED" if int(level["index"]) == 0 else (
                    "BACKOFF_ACTION_SUPPORT" if not sizing else "BACKOFF_SIZING_SUPPORT"
                )
                return level, key, node, reason, failed
            support = self._support(node)
            failed.append({
                "level": int(level["index"]),
                "reason": "INSUFFICIENT_TRAIN_SUPPORT",
                "support": support,
            })
        if last is None:
            return None, None, None, "NO_DECLARED_LEVEL_AVAILABLE", failed
        level, key, node = last
        return level, key, node, "GLOBAL_FALLBACK_BELOW_THRESHOLD", failed

    @staticmethod
    def _sizing_summary(values: Sequence[float]) -> dict[str, Any]:
        clean = [float(v) for v in values if math.isfinite(float(v)) and float(v) > 0]
        return {
            "n": len(clean),
            "p10": _quantile(clean, 0.10),
            "median": _quantile(clean, 0.50),
            "p90": _quantile(clean, 0.90),
            "p99": _quantile(clean, 0.99),
        }

    def sizing_values(self, **row: Any) -> list[float]:
        _, _, node, _, _ = self._select(row, sizing=True)
        if node is None:
            return []
        return [float(v) for v in node.get("raise_sizing_ratios", []) if float(v) > 0]

    def predict(self, **row: Any) -> dict[str, Any]:
        ctx = _context(row)
        level, key, node, reason, failed = self._select(row, sizing=False)
        if node is None:
            raise KeyError(f"no declared TRAIN node for {ctx}")
        support = self._support(node)
        counts = {a: float((node.get("action_counts") or {}).get(a, 0)) for a in ACTIONS}
        posterior = {a: counts[a] + self.alpha for a in ACTIONS}
        denom = sum(posterior.values())
        probs = {a: posterior[a] / denom for a in ACTIONS}

        slevel, skey, snode, sreason, sfailed = self._select(row, sizing=True)
        values = [] if snode is None else [
            float(v) for v in snode.get("raise_sizing_ratios", []) if float(v) > 0
        ]
        spr = row.get("spr")
        price = row.get("facing_price_to_pot")
        jam = overbet = tail = 0
        for value in values:
            jam_like = spr is not None and float(spr) > 0 and value >= float(spr) * (1.0 - 1e-9)
            is_overbet = value > 1.0
            is_tail = jam_like or (price is not None and float(price) > 1.5) or value > 1.5
            jam += int(jam_like)
            overbet += int(is_overbet)
            tail += int(is_tail)
        nsize = len(values)
        tail_diag = {
            "sizing_support_n": nsize,
            "jam_like_conditional_on_raise": (jam / nsize) if nsize else None,
            "overbet_conditional_on_raise": (overbet / nsize) if nsize else None,
            "tail_conditional_on_raise": (tail / nsize) if nsize else None,
        }
        return {
            "schema": PREDICTION_SCHEMA,
            "identity": self.identity,
            "exact_context": ctx,
            "selected_level": {
                "index": int(level["index"]),
                "dimensions": list(level["dimensions"]),
                "key": key,
            },
            "effective_support": {**support, "source_split": "TRAIN"},
            "fallback_reason": reason,
            "failed_finer_levels": failed,
            "probabilities": probs,
            "sizing": self._sizing_summary(values),
            "sizing_selected_level": None if slevel is None else {
                "index": int(slevel["index"]),
                "dimensions": list(slevel["dimensions"]),
                "key": skey,
            },
            "sizing_effective_support": None if snode is None else {
                **self._support(snode), "source_split": "TRAIN"
            },
            "sizing_fallback_reason": sreason,
            "sizing_failed_finer_levels": sfailed,
            "tail_diagnostics": tail_diag,
            "production_effect": "NONE",
        }

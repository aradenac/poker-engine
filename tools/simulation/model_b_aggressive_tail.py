#!/usr/bin/env python3
"""Explicit support-aware aggressive-tail component for Model B (#298).

The component is additive and TRAIN-fitted. It delegates action probabilities
and conditional sizing distribution unchanged to the frozen #286 candidate,
while adding an explicit conditional-on-RAISE tail distribution.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from typing import Any, Iterable, Mapping, Sequence

from tools.simulation.model_b_price_response import HIERARCHY, price_bucket, spr_bucket
from tools.simulation.model_b_support_aware_backoff import (
    SupportAwareBackoffModel,
    artifact_sha256 as support_artifact_sha256,
)

SCHEMA = "independent-opponent-model-b-aggressive-tail/v1"
PREDICTION_SCHEMA = "model-b-aggressive-tail-prediction/v1"
TAIL_CLASSES = (
    "JAM_OVERBET",
    "JAM_NONOVERBET",
    "LARGE_OVERBET_NONJAM",
    "OVERBET_NONJAM",
    "OTHER_RAISE",
)


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


def _key(columns: Sequence[str], row: Mapping[str, Any]) -> str:
    return "ALL" if not columns else "|".join(str(row[name]) for name in columns)


def tail_class(row: Mapping[str, Any]) -> str | None:
    if str(row.get("action") or "").upper() != "RAISE":
        return None
    sizing = row.get("raise_sizing_ratio")
    if sizing is None:
        return None
    value = float(sizing)
    if not math.isfinite(value) or value <= 0:
        raise ValueError("raise_sizing_ratio must be positive finite")
    jam = bool(row.get("is_jam"))
    if jam:
        return "JAM_OVERBET" if value > 1.0 else "JAM_NONOVERBET"
    if value > 1.5:
        return "LARGE_OVERBET_NONJAM"
    if value > 1.0:
        return "OVERBET_NONJAM"
    return "OTHER_RAISE"


def artifact_sha256(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def build_artifact(
    observations: Iterable[Mapping[str, Any]],
    *,
    graph: Mapping[str, Any],
    base_action_artifact: Mapping[str, Any],
    alpha_per_tail_class: float = 0.5,
    model_version: str = "model_b_aggressive_tail_v1_candidate_20260919",
) -> dict[str, Any]:
    if graph.get("schema") != "model-b-aggressive-tail-backoff-graph/v1":
        raise ValueError("unsupported tail graph schema")
    if graph.get("source_split") != "TRAIN" or graph.get("frozen_before_validation") is not True:
        raise ValueError("tail graph must be TRAIN-derived/frozen before VALIDATION")
    expected = [list(level) for level in HIERARCHY]
    actual = [list(row.get("dimensions") or []) for row in graph.get("levels") or []]
    if actual != expected:
        raise ValueError("tail graph differs from declared #286 hierarchy")
    alpha = float(alpha_per_tail_class)
    if not math.isfinite(alpha) or alpha <= 0:
        raise ValueError("alpha_per_tail_class must be positive finite")

    base_sha = support_artifact_sha256(base_action_artifact)
    counts = [defaultdict(Counter) for _ in HIERARCHY]
    hands = [defaultdict(set) for _ in HIERARCHY]
    class_hands = [defaultdict(lambda: defaultdict(set)) for _ in HIERARCHY]
    raises = 0
    distinct_raise_hands: set[str] = set()

    for raw in observations:
        if str(raw.get("source_split", "TRAIN")) != "TRAIN":
            raise ValueError("builder accepts TRAIN observations only")
        klass = tail_class(raw)
        if klass is None:
            continue
        hand_id = str(raw.get("hand_id") or "")
        if not hand_id:
            raise ValueError("TRAIN raise observation missing hand_id")
        ctx = _context(raw)
        raises += 1
        distinct_raise_hands.add(hand_id)
        for level_index, columns in enumerate(HIERARCHY):
            key = _key(columns, ctx)
            counts[level_index][key][klass] += 1
            hands[level_index][key].add(hand_id)
            class_hands[level_index][key][klass].add(hand_id)

    if not raises:
        raise ValueError("no TRAIN raise observations")

    levels = []
    for idx, columns in enumerate(HIERARCHY):
        data = {}
        for key in sorted(counts[idx]):
            node_counts = counts[idx][key]
            data[key] = {
                "source_split": "TRAIN",
                "raise_observations": int(sum(node_counts.values())),
                "distinct_raise_hands": len(hands[idx][key]),
                "class_counts": {klass: int(node_counts.get(klass, 0)) for klass in TAIL_CLASSES},
                "class_distinct_hands": {
                    klass: len(class_hands[idx][key].get(klass, set()))
                    for klass in TAIL_CLASSES
                },
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
        "base_action_model": {
            "schema": base_action_artifact.get("schema"),
            "model_version": base_action_artifact.get("model_version"),
            "artifact_sha256": base_sha,
            "delegated_components": ["action_probabilities", "sizing_distribution"],
        },
        "alpha_per_tail_class": alpha,
        "tail_classes": list(TAIL_CLASSES),
        "thresholds": {"tail": dict(graph["tail_support"])},
        "graph_identity": {
            "schema": graph["schema"],
            "version": graph["version"],
            "levels": actual,
        },
        "feature_contract": {
            "allowed_dimensions": list(HIERARCHY[0]),
            "forbidden_sources": [
                "model_a_ev",
                "model_a_policy",
                "model_a_recommendation",
                "hero_strategy",
                "hero_ev",
            ],
            "nearest_context_heuristic": False,
            "silent_pooling": False,
        },
        "training_counts": {
            "raise_observations": raises,
            "distinct_raise_hands": len(distinct_raise_hands),
        },
        "levels": levels,
    }


def validate_artifact(document: Mapping[str, Any]) -> None:
    if document.get("schema") != SCHEMA:
        raise ValueError("unsupported aggressive-tail artifact schema")
    if document.get("fit_split") != "TRAIN" or document.get("test_consumed") is not False:
        raise ValueError("aggressive-tail candidate must be TRAIN-only and TEST-unconsumed")
    if document.get("status") != "CANDIDATE_NOT_PROMOTED":
        raise ValueError("candidate must remain unpromoted")
    if document.get("production_effect") != "NONE" or document.get("automatic_promotion") is not False:
        raise ValueError("candidate must have no production effect")
    if tuple(document.get("tail_classes") or ()) != TAIL_CLASSES:
        raise ValueError("tail class contract changed")
    contract = document.get("feature_contract") or {}
    if tuple(contract.get("allowed_dimensions") or ()) != tuple(HIERARCHY[0]):
        raise ValueError("feature dimensions differ from #286")
    if contract.get("nearest_context_heuristic") is not False or contract.get("silent_pooling") is not False:
        raise ValueError("undeclared context mixing is forbidden")
    levels = document.get("levels") or []
    if [tuple(x.get("dimensions") or ()) for x in levels] != list(HIERARCHY):
        raise ValueError("artifact hierarchy differs from frozen graph")
    threshold = (document.get("thresholds") or {}).get("tail") or {}
    if int(threshold.get("min_raises", 0)) <= 0 or int(threshold.get("min_distinct_hands", 0)) <= 0:
        raise ValueError("invalid tail support thresholds")
    alpha = float(document.get("alpha_per_tail_class", 0))
    if not math.isfinite(alpha) or alpha <= 0:
        raise ValueError("invalid tail prior")


class AggressiveTailModel:
    def __init__(self, document: Mapping[str, Any], base_action_artifact: Mapping[str, Any]) -> None:
        self.document = dict(document)
        validate_artifact(self.document)
        actual_base_sha = support_artifact_sha256(base_action_artifact)
        expected_base_sha = str(self.document["base_action_model"]["artifact_sha256"])
        if actual_base_sha != expected_base_sha:
            raise ValueError("base #286 artifact identity mismatch")
        self.base = SupportAwareBackoffModel(base_action_artifact)
        self.alpha = float(self.document["alpha_per_tail_class"])
        self.threshold = dict(self.document["thresholds"]["tail"])
        self.identity = {
            "schema": SCHEMA,
            "model_version": str(self.document["model_version"]),
            "artifact_sha256": artifact_sha256(self.document),
            "base_artifact_sha256": actual_base_sha,
            "production_effect": "NONE",
        }

    @staticmethod
    def _support(node: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "raise_observations": int(node.get("raise_observations", 0)),
            "distinct_raise_hands": int(node.get("distinct_raise_hands", 0)),
            "class_counts": dict(node.get("class_counts") or {}),
            "class_distinct_hands": dict(node.get("class_distinct_hands") or {}),
        }

    def _supported(self, node: Mapping[str, Any]) -> bool:
        s = self._support(node)
        return (
            s["raise_observations"] >= int(self.threshold["min_raises"])
            and s["distinct_raise_hands"] >= int(self.threshold["min_distinct_hands"])
        )

    def _select(self, row: Mapping[str, Any]):
        ctx = _context(row)
        last = None
        failed = []
        for level in self.document["levels"]:
            dims = tuple(level["dimensions"])
            key = _key(dims, ctx)
            node = (level.get("data") or {}).get(key)
            if node is None:
                failed.append({"level": int(level["index"]), "reason": "NO_TRAIN_TAIL_NODE"})
                continue
            last = (level, key, node)
            if self._supported(node):
                reason = (
                    "EXACT_TAIL_CONTEXT_SUPPORTED"
                    if int(level["index"]) == 0
                    else "BACKOFF_TAIL_SUPPORT"
                )
                return level, key, node, reason, failed
            failed.append({
                "level": int(level["index"]),
                "reason": "INSUFFICIENT_TRAIN_TAIL_SUPPORT",
                "support": self._support(node),
            })
        if last is None:
            return None, None, None, "NO_DECLARED_TAIL_LEVEL_AVAILABLE", failed
        level, key, node = last
        return level, key, node, "GLOBAL_TAIL_FALLBACK_BELOW_THRESHOLD", failed

    def tail_probabilities(self, **row: Any) -> dict[str, Any]:
        level, key, node, reason, failed = self._select(row)
        if node is None:
            raise KeyError("no declared TRAIN tail node")
        counts = {
            klass: float((node.get("class_counts") or {}).get(klass, 0))
            for klass in TAIL_CLASSES
        }
        posterior = {klass: counts[klass] + self.alpha for klass in TAIL_CLASSES}
        denom = sum(posterior.values())
        class_probs = {klass: posterior[klass] / denom for klass in TAIL_CLASSES}
        jam = class_probs["JAM_OVERBET"] + class_probs["JAM_NONOVERBET"]
        overbet = (
            class_probs["JAM_OVERBET"]
            + class_probs["LARGE_OVERBET_NONJAM"]
            + class_probs["OVERBET_NONJAM"]
        )
        price = row.get("facing_price_to_pot")
        high_price = price is not None and float(price) > 1.5
        aggressive_tail = 1.0 if high_price else (
            jam + class_probs["LARGE_OVERBET_NONJAM"]
        )
        return {
            "selected_level": {
                "index": int(level["index"]),
                "dimensions": list(level["dimensions"]),
                "key": key,
            },
            "effective_support": {**self._support(node), "source_split": "TRAIN"},
            "fallback_reason": reason,
            "failed_finer_levels": failed,
            "class_probabilities": class_probs,
            "jam_conditional_on_raise": jam,
            "overbet_conditional_on_raise": overbet,
            "aggressive_tail_conditional_on_raise": aggressive_tail,
            "high_price_tail_forced_by_metric_definition": high_price,
        }

    def sizing_values(self, **row: Any) -> list[float]:
        # #298 deliberately leaves the conditional sizing distribution unchanged.
        return self.base.sizing_values(**row)

    def predict(self, **row: Any) -> dict[str, Any]:
        base = self.base.predict(**row)
        tail = self.tail_probabilities(**row)
        return {
            **base,
            "schema": PREDICTION_SCHEMA,
            "identity": self.identity,
            "probabilities": dict(base["probabilities"]),
            "sizing": dict(base["sizing"]),
            "tail_component": tail,
            "production_effect": "NONE",
        }

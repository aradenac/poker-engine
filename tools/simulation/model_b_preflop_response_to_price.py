#!/usr/bin/env python3
"""Independent synthetic-only preflop response-to-price scaffold for #315 tranche 1."""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from typing import Any, Iterable, Mapping, Sequence

SCHEMA = "independent-opponent-model-b-preflop-response-to-price-scaffold/v1"
PREDICTION_SCHEMA = "model-b-preflop-response-to-price-prediction/v1"
ACTIONS = ("FOLD", "CALL", "RAISE", "JAM")
FAMILIES = ("ISO_OVER_LIMPERS", "VS_RFI")
FORBIDDEN_KEYS = {
    "model_a",
    "model_a_policy",
    "model_a_ev",
    "model_a_recommendation",
    "hero_ev",
    "hero_recommendation",
    "recommended_action",
    "recommended_sizing",
}
FULL_DIMENSIONS = (
    "profile",
    "family",
    "responder_position",
    "raiser_position",
    "sequence",
    "limper_count_bucket",
    "raise_size_bucket",
    "price_bucket",
    "effective_stack_bucket",
)
HIERARCHY = (
    FULL_DIMENSIONS,
    (
        "family","responder_position","raiser_position","sequence",
        "limper_count_bucket","raise_size_bucket","price_bucket","effective_stack_bucket",
    ),
    (
        "family","responder_position","sequence","limper_count_bucket",
        "raise_size_bucket","price_bucket","effective_stack_bucket",
    ),
    (
        "family","responder_position","limper_count_bucket",
        "raise_size_bucket","price_bucket","effective_stack_bucket",
    ),
    ("family","responder_position","limper_count_bucket","price_bucket","effective_stack_bucket"),
    ("family","responder_position","price_bucket","effective_stack_bucket"),
    ("family","price_bucket","effective_stack_bucket"),
    ("family","price_bucket"),
    ("family",),
)


def _finite_nonnegative(value: Any, *, name: str) -> float:
    x = float(value)
    if not math.isfinite(x) or x < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    return x


def _assert_independent(raw: Mapping[str, Any]) -> None:
    lowered = {str(k).lower() for k in raw}
    explicit = lowered.intersection(FORBIDDEN_KEYS)
    prefixed = {k for k in lowered if k.startswith("model_a")}
    if explicit or prefixed:
        raise ValueError(f"forbidden Model A/EV/recommendation features: {sorted(explicit | prefixed)}")


def limper_count_bucket(value: Any) -> str:
    n = int(value)
    if n < 0:
        raise ValueError("limper_count must be non-negative")
    return "L0" if n == 0 else "L1" if n == 1 else "L2" if n == 2 else "L3_PLUS"


def raise_size_bucket(value: Any) -> str:
    x = _finite_nonnegative(value, name="hero_raise_size_bb")
    if x <= 3.0:
        return "S00_3"
    if x <= 4.5:
        return "S3_4P5"
    if x <= 6.0:
        return "S4P5_6"
    if x <= 8.0:
        return "S6_8"
    return "S8_PLUS"


def price_bucket(value: Any) -> str:
    x = _finite_nonnegative(value, name="facing_price_to_pot")
    if x <= 0.25:
        return "P00_25"
    if x <= 0.50:
        return "P25_50"
    if x <= 0.75:
        return "P50_75"
    if x <= 1.00:
        return "P75_100"
    if x <= 1.50:
        return "P100_150"
    return "P150_PLUS"


def effective_stack_bucket(value: Any) -> str:
    x = _finite_nonnegative(value, name="effective_stack_bb")
    if x <= 20:
        return "E00_20"
    if x <= 40:
        return "E20_40"
    if x <= 80:
        return "E40_80"
    if x <= 150:
        return "E80_150"
    return "E150_PLUS"


def public_context(raw: Mapping[str, Any]) -> dict[str, Any]:
    _assert_independent(raw)
    required = (
        "profile","family","responder_position","raiser_position","sequence",
        "limper_count","hero_raise_size_bb","facing_price_to_pot","effective_stack_bb",
    )
    missing = [name for name in required if raw.get(name) is None]
    if missing:
        raise ValueError(f"missing public preflop response features: {missing}")
    family = str(raw["family"])
    if family not in FAMILIES:
        raise ValueError(f"unsupported preflop response family: {family!r}")
    return {
        "profile": str(raw["profile"]),
        "family": family,
        "responder_position": str(raw["responder_position"]),
        "raiser_position": str(raw["raiser_position"]),
        "sequence": str(raw["sequence"]),
        "limper_count_bucket": limper_count_bucket(raw["limper_count"]),
        "raise_size_bucket": raise_size_bucket(raw["hero_raise_size_bb"]),
        "price_bucket": price_bucket(raw["facing_price_to_pot"]),
        "effective_stack_bucket": effective_stack_bucket(raw["effective_stack_bb"]),
    }


def _key(columns: Sequence[str], context: Mapping[str, Any]) -> str:
    return "|".join(str(context[name]) for name in columns)


def artifact_sha256(document: Mapping[str, Any]) -> str:
    payload = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(payload).hexdigest()


def build_synthetic_artifact(
    observations: Iterable[Mapping[str, Any]],
    *,
    graph: Mapping[str, Any],
    alpha_per_action: float | None = None,
    model_version: str = "model_b_preflop_response_to_price_scaffold_v1",
) -> dict[str, Any]:
    if graph.get("schema") != "model-b-preflop-response-to-price-backoff-graph/v1":
        raise ValueError("unsupported preflop backoff graph schema")
    if graph.get("source_kind") != "SYNTHETIC_FIXTURE":
        raise ValueError("tranche 1 graph must be synthetic-only")
    expected = [list(level) for level in HIERARCHY]
    actual = [list(level.get("dimensions") or []) for level in graph.get("levels") or []]
    if actual != expected:
        raise ValueError("preflop backoff graph differs from frozen contract")
    if graph.get("no_cross_family_pooling") is not True:
        raise ValueError("cross-family pooling must remain forbidden")

    alpha = float(graph["alpha_per_action"] if alpha_per_action is None else alpha_per_action)
    if not math.isfinite(alpha) or alpha <= 0:
        raise ValueError("alpha_per_action must be positive finite")
    counts = [defaultdict(Counter) for _ in HIERARCHY]
    hands = [defaultdict(set) for _ in HIERARCHY]
    total = 0
    distinct_hands: set[str] = set()

    for raw in observations:
        _assert_independent(raw)
        if raw.get("source_kind") != "SYNTHETIC_FIXTURE":
            raise ValueError("tranche 1 builder accepts SYNTHETIC_FIXTURE only")
        if raw.get("dataset_split") is not None or raw.get("split") is not None:
            raise ValueError("TRAIN/VALIDATION/TEST dataset splits are forbidden in tranche 1")
        action = str(raw.get("action") or "").upper()
        if action not in ACTIONS:
            raise ValueError(f"unsupported preflop response action: {action!r}")
        hand_id = str(raw.get("hand_id") or "")
        if not hand_id:
            raise ValueError("synthetic observation missing hand_id")
        ctx = public_context(raw)
        total += 1
        distinct_hands.add(hand_id)
        for index, columns in enumerate(HIERARCHY):
            key = _key(columns, ctx)
            counts[index][key][action] += 1
            hands[index][key].add(hand_id)

    if not total:
        raise ValueError("at least one synthetic observation is required")

    levels = []
    for index, columns in enumerate(HIERARCHY):
        data = {}
        for key in sorted(counts[index]):
            c = counts[index][key]
            data[key] = {
                "source_kind": "SYNTHETIC_FIXTURE",
                "observations": int(sum(c.values())),
                "distinct_hands": len(hands[index][key]),
                "action_counts": {action: int(c.get(action, 0)) for action in ACTIONS},
            }
        levels.append({"index": index, "dimensions": list(columns), "data": data})

    return {
        "schema": SCHEMA,
        "model_version": model_version,
        "status": "SCAFFOLD_SYNTHETIC_ONLY",
        "fit_status": "NOT_FINAL_BEFORE_319",
        "source_kind": "SYNTHETIC_FIXTURE",
        "validation_consumed": False,
        "test_consumed": False,
        "performance_claim_allowed": False,
        "production_effect": "NONE",
        "automatic_promotion": False,
        "active_model_b_changed": False,
        "alpha_per_action": alpha,
        "thresholds": {
            "min_observations": int(graph["min_observations"]),
            "min_distinct_hands": int(graph["min_distinct_hands"]),
        },
        "feature_contract": {
            "allowed_dimensions": list(FULL_DIMENSIONS),
            "forbidden_features": sorted(FORBIDDEN_KEYS),
            "no_cross_family_pooling": True,
            "nearest_context_heuristic": False,
        },
        "synthetic_counts": {
            "observations": total,
            "distinct_hands": len(distinct_hands),
        },
        "levels": levels,
    }


def validate_artifact(document: Mapping[str, Any]) -> None:
    if document.get("schema") != SCHEMA:
        raise ValueError("unsupported preflop response scaffold schema")
    if document.get("status") != "SCAFFOLD_SYNTHETIC_ONLY":
        raise ValueError("tranche 1 candidate must remain scaffold-only")
    if document.get("fit_status") != "NOT_FINAL_BEFORE_319":
        raise ValueError("final fit is forbidden before #319")
    if document.get("source_kind") != "SYNTHETIC_FIXTURE":
        raise ValueError("tranche 1 artifact must be synthetic-only")
    if document.get("validation_consumed") is not False or document.get("test_consumed") is not False:
        raise ValueError("VALIDATION/TEST consumption is forbidden in tranche 1")
    if document.get("performance_claim_allowed") is not False:
        raise ValueError("performance claims are forbidden in tranche 1")
    if document.get("production_effect") != "NONE":
        raise ValueError("scaffold must have no production effect")
    if document.get("automatic_promotion") is not False or document.get("active_model_b_changed") is not False:
        raise ValueError("promotion/active pointer changes are forbidden")
    contract = document.get("feature_contract") or {}
    if tuple(contract.get("allowed_dimensions") or ()) != FULL_DIMENSIONS:
        raise ValueError("feature dimensions differ from frozen contract")
    if contract.get("no_cross_family_pooling") is not True:
        raise ValueError("cross-family pooling is forbidden")
    if contract.get("nearest_context_heuristic") is not False:
        raise ValueError("nearest-context heuristic is forbidden")
    levels = document.get("levels") or []
    if [tuple(level.get("dimensions") or ()) for level in levels] != list(HIERARCHY):
        raise ValueError("preflop response hierarchy changed")


class PreflopResponseToPriceModel:
    def __init__(self, document: Mapping[str, Any]) -> None:
        self.document = dict(document)
        validate_artifact(self.document)
        self.alpha = float(self.document["alpha_per_action"])
        self.min_observations = int(self.document["thresholds"]["min_observations"])
        self.min_distinct_hands = int(self.document["thresholds"]["min_distinct_hands"])
        self.identity = {
            "schema": SCHEMA,
            "model_version": self.document["model_version"],
            "artifact_sha256": artifact_sha256(self.document),
            "status": "SCAFFOLD_SYNTHETIC_ONLY",
            "production_effect": "NONE",
        }

    def _supported(self, node: Mapping[str, Any]) -> bool:
        return (
            int(node.get("observations", 0)) >= self.min_observations
            and int(node.get("distinct_hands", 0)) >= self.min_distinct_hands
        )

    def _select(self, raw: Mapping[str, Any]):
        ctx = public_context(raw)
        failed = []
        last = None
        for level in self.document["levels"]:
            columns = tuple(level["dimensions"])
            key = _key(columns, ctx)
            node = (level.get("data") or {}).get(key)
            if node is None:
                failed.append({"level": int(level["index"]), "reason": "NO_SYNTHETIC_NODE"})
                continue
            last = (level, key, node)
            if self._supported(node):
                reason = (
                    "EXACT_SYNTHETIC_CONTEXT_SUPPORTED"
                    if int(level["index"]) == 0
                    else "DECLARED_SYNTHETIC_BACKOFF"
                )
                return level, key, node, reason, failed
            failed.append({
                "level": int(level["index"]),
                "reason": "INSUFFICIENT_SYNTHETIC_SUPPORT",
                "support": {
                    "observations": int(node["observations"]),
                    "distinct_hands": int(node["distinct_hands"]),
                },
            })
        if last is None:
            raise KeyError(f"no synthetic node for preflop family {ctx['family']!r}")
        level, key, node = last
        return level, key, node, "FAMILY_FALLBACK_BELOW_SUPPORT", failed

    def predict(self, **raw: Any) -> dict[str, Any]:
        _assert_independent(raw)
        ctx = public_context(raw)
        level, key, node, reason, failed = self._select(raw)
        counts = {action: float((node.get("action_counts") or {}).get(action, 0)) for action in ACTIONS}
        posterior = {action: counts[action] + self.alpha for action in ACTIONS}
        total = sum(posterior.values())
        probabilities = {action: posterior[action] / total for action in ACTIONS}
        support = {
            "observations": int(node["observations"]),
            "distinct_hands": int(node["distinct_hands"]),
            "source_kind": "SYNTHETIC_FIXTURE",
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
            "effective_support": support,
            "fallback_reason": reason,
            "failed_finer_levels": failed,
            "probabilities": probabilities,
            "derived": {
                "continue_probability": 1.0 - probabilities["FOLD"],
                "passive_continue_probability": probabilities["CALL"],
                "aggressive_continue_probability": probabilities["RAISE"] + probabilities["JAM"],
            },
            "performance_claim": "NOT_ALLOWED_SYNTHETIC_SCAFFOLD",
            "production_effect": "NONE",
        }


# --- Issue #340 tranche 2A: empirical TRAIN fit + independent VALIDATION runtime ---

EMPIRICAL_SCHEMA = "independent-opponent-model-b-preflop-response-to-price-2a/v1"
EMPIRICAL_PREDICTION_SCHEMA = "model-b-preflop-response-to-price-2a-prediction/v1"
EMPIRICAL_FAMILIES = (
    "VS_LIMPERS",
    "LIMPER_VS_ISO",
    "LIMPER_VS_ISO_CALLERS",
    "VS_ISO",
    "VS_ISO_CALLERS",
    "VS_RFI",
    "VS_RFI_CALLERS",
    "OPENER_OR_ISO_VS_3BET",
    "CALLER_VS_SQUEEZE_OR_3BET",
    "COLD_VS_3BET",
)
EMPIRICAL_LEVELS = (
    ("profile","family","responder_position","raiser_position","sequence","limper_count","caller_count","target_exact","price_bin","stack_bin"),
    ("family","responder_position","raiser_position","sequence","limper_count","caller_count","target_exact","price_bin","stack_bin"),
    ("family","responder_position","raiser_position","limper_count","caller_count","target_exact","price_bin","stack_bin"),
    ("family","responder_position","limper_count","caller_count","target_exact","price_bin","stack_bin"),
    ("family","responder_position","limper_count","target_exact","price_bin"),
    ("family","responder_position","target_exact","price_bin"),
    ("family","target_exact","price_bin"),
    ("family","target_bin","price_bin"),
    ("family","target_bin"),
    ("family",),
)
REFERENCE_LEVELS = (
    ("profile","family","responder_position","raiser_position","sequence","limper_count","caller_count","stack_bin"),
    ("family","responder_position","raiser_position","sequence","limper_count","caller_count","stack_bin"),
    ("family","responder_position","raiser_position","limper_count","caller_count","stack_bin"),
    ("family","responder_position","limper_count","caller_count","stack_bin"),
    ("family","responder_position","limper_count","stack_bin"),
    ("family","responder_position","stack_bin"),
    ("family","responder_position"),
    ("family",),
)


def _declared_empirical_bin(value: Any, bins: Sequence[Mapping[str, Any]]) -> str:
    if value is None or not bins:
        return "MISSING"
    x = float(value)
    if not math.isfinite(x):
        return "MISSING"
    for row in bins:
        if x <= float(row["max_observed"]) + 1e-9:
            return str(row["bin_id"])
    return str(bins[-1]["bin_id"])


def _family_bins(all_bins: Mapping[str, Any], family: str) -> Mapping[str, Any]:
    bins = all_bins.get(family)
    if not isinstance(bins, Mapping):
        raise ValueError(f"#319 empirical bins missing for family {family!r}")
    return bins


def empirical_public_context(
    raw: Mapping[str, Any],
    *,
    bin_proposals: Mapping[str, Any],
) -> dict[str, Any]:
    _assert_independent(raw)
    required = (
        "profile","family","responder_position","raiser_position","sequence",
        "limper_count","caller_count","target_total_bb","facing_price_to_pot",
        "effective_stack_bb",
    )
    missing = [name for name in required if raw.get(name) is None]
    if missing:
        raise ValueError(f"missing empirical preflop response features: {missing}")
    family = str(raw["family"])
    if family not in EMPIRICAL_FAMILIES:
        raise ValueError(f"unsupported empirical preflop family: {family!r}")
    bins = _family_bins(bin_proposals, family)
    target = float(raw["target_total_bb"])
    if not math.isfinite(target) or target < 0:
        raise ValueError("target_total_bb must be finite and non-negative")
    return {
        "profile": str(raw["profile"]),
        "family": family,
        "responder_position": str(raw["responder_position"]),
        "raiser_position": str(raw["raiser_position"]),
        "sequence": str(raw["sequence"]),
        "limper_count": int(raw["limper_count"]),
        "caller_count": int(raw["caller_count"]),
        "target_exact": format(target, ".6g"),
        "target_bin": _declared_empirical_bin(target, bins.get("target_total_bb") or []),
        "price_bin": _declared_empirical_bin(
            raw["facing_price_to_pot"], bins.get("price_to_pot") or []
        ),
        "stack_bin": _declared_empirical_bin(
            raw["effective_stack_bb"], bins.get("effective_stack_bb") or []
        ),
    }


def build_train_artifact(
    observations: Iterable[Mapping[str, Any]],
    *,
    bin_proposals: Mapping[str, Any],
    source_report_hash: str,
    reference_mode: bool = False,
    min_observations: int = 20,
    min_distinct_hands: int = 15,
    alpha_per_action: float = 1.0,
    model_version: str = "model_b_preflop_response_to_price_2a_20260919",
) -> dict[str, Any]:
    if min_observations <= 0 or min_distinct_hands <= 0:
        raise ValueError("support thresholds must be positive")
    alpha = float(alpha_per_action)
    if not math.isfinite(alpha) or alpha <= 0:
        raise ValueError("alpha_per_action must be positive finite")
    levels_spec = REFERENCE_LEVELS if reference_mode else EMPIRICAL_LEVELS
    counts = [defaultdict(Counter) for _ in levels_spec]
    hands = [defaultdict(set) for _ in levels_spec]
    total = 0
    for raw in observations:
        _assert_independent(raw)
        if raw.get("source_split") != "TRAIN":
            raise ValueError("empirical Model B fit accepts TRAIN rows only")
        action = str(raw.get("action") or "").upper()
        if action not in ACTIONS:
            raise ValueError(f"unsupported empirical preflop response action: {action!r}")
        hand_id = str(raw.get("hand_id") or "")
        if not hand_id:
            raise ValueError("empirical observation missing hand_id")
        ctx = empirical_public_context(raw, bin_proposals=bin_proposals)
        total += 1
        for index, columns in enumerate(levels_spec):
            key = _key(columns, ctx)
            counts[index][key][action] += 1
            hands[index][key].add(hand_id)
    if not total:
        raise ValueError("at least one TRAIN observation is required")

    levels = []
    for index, columns in enumerate(levels_spec):
        data = {}
        for key in sorted(counts[index]):
            c = counts[index][key]
            n = int(sum(c.values()))
            h = len(hands[index][key])
            data[key] = {
                "observations": n,
                "distinct_hands": h,
                "action_counts": {action: int(c.get(action, 0)) for action in ACTIONS},
                "support_state": (
                    "SUPPORTED" if n >= min_observations and h >= min_distinct_hands
                    else "SPARSE"
                ),
            }
        levels.append({"index": index, "dimensions": list(columns), "data": data})

    return {
        "schema": EMPIRICAL_SCHEMA,
        "model_version": model_version + ("_price_agnostic_reference" if reference_mode else "_candidate"),
        "status": "CANDIDATE_NOT_PROMOTED",
        "fit_split": "TRAIN",
        "validation_consumed_for_fit": False,
        "test_consumed": False,
        "production_effect": "NONE",
        "automatic_promotion": False,
        "active_model_b_changed": False,
        "reference_mode": bool(reference_mode),
        "source_issue_319_report_hash": str(source_report_hash),
        "alpha_per_action": alpha,
        "thresholds": {
            "min_observations": int(min_observations),
            "min_distinct_hands": int(min_distinct_hands),
        },
        "feature_contract": {
            "public_only": True,
            "actions": list(ACTIONS),
            "price_aware": not reference_mode,
            "no_cross_family_pooling": True,
            "nearest_context_heuristic": False,
            "forbidden_features": sorted(FORBIDDEN_KEYS),
        },
        "training_counts": {"decisions": total},
        "bin_proposals": dict(bin_proposals),
        "levels": levels,
    }


def validate_train_artifact(document: Mapping[str, Any]) -> None:
    if document.get("schema") != EMPIRICAL_SCHEMA:
        raise ValueError("unsupported empirical preflop response schema")
    if document.get("fit_split") != "TRAIN":
        raise ValueError("empirical Model B must be fit on TRAIN")
    if document.get("validation_consumed_for_fit") is not False:
        raise ValueError("VALIDATION must not be consumed for fit")
    if document.get("test_consumed") is not False:
        raise ValueError("TEST consumption is forbidden")
    if document.get("production_effect") != "NONE":
        raise ValueError("candidate must have no production effect")
    if document.get("automatic_promotion") is not False:
        raise ValueError("automatic promotion is forbidden")
    if document.get("active_model_b_changed") is not False:
        raise ValueError("active Model B must remain unchanged")
    contract = document.get("feature_contract") or {}
    if contract.get("public_only") is not True:
        raise ValueError("only public features are permitted")
    if contract.get("no_cross_family_pooling") is not True:
        raise ValueError("cross-family pooling is forbidden")
    if contract.get("nearest_context_heuristic") is not False:
        raise ValueError("nearest-context heuristic is forbidden")
    expected = REFERENCE_LEVELS if document.get("reference_mode") else EMPIRICAL_LEVELS
    actual = [tuple(level.get("dimensions") or ()) for level in document.get("levels") or []]
    if actual != list(expected):
        raise ValueError("empirical hierarchy differs from frozen contract")


class EmpiricalPreflopResponseToPriceModel:
    def __init__(self, document: Mapping[str, Any]) -> None:
        self.document = dict(document)
        validate_train_artifact(self.document)
        self.alpha = float(self.document["alpha_per_action"])
        self.min_observations = int(self.document["thresholds"]["min_observations"])
        self.min_distinct_hands = int(self.document["thresholds"]["min_distinct_hands"])
        self.bin_proposals = self.document["bin_proposals"]
        self.identity = {
            "schema": EMPIRICAL_SCHEMA,
            "model_version": self.document["model_version"],
            "artifact_sha256": artifact_sha256(self.document),
            "reference_mode": bool(self.document["reference_mode"]),
            "production_effect": "NONE",
        }

    def _supported(self, node: Mapping[str, Any]) -> bool:
        return (
            int(node.get("observations", 0)) >= self.min_observations
            and int(node.get("distinct_hands", 0)) >= self.min_distinct_hands
        )

    def predict(self, **raw: Any) -> dict[str, Any]:
        _assert_independent(raw)
        ctx = empirical_public_context(raw, bin_proposals=self.bin_proposals)
        failed = []
        selected = None
        for level in self.document["levels"]:
            dims = tuple(level["dimensions"])
            key = _key(dims, ctx)
            node = (level.get("data") or {}).get(key)
            if node is None:
                failed.append({"level": int(level["index"]), "reason": "NO_TRAIN_NODE"})
                continue
            if self._supported(node):
                selected = (level, key, node)
                break
            failed.append({
                "level": int(level["index"]),
                "reason": "SPARSE_TRAIN_NODE",
                "support": {
                    "observations": int(node["observations"]),
                    "distinct_hands": int(node["distinct_hands"]),
                },
            })
        if selected is None:
            raise KeyError(f"no supported TRAIN node for family {ctx['family']!r}")
        level, key, node = selected
        counts = {
            action: float((node.get("action_counts") or {}).get(action, 0))
            for action in ACTIONS
        }
        posterior = {action: counts[action] + self.alpha for action in ACTIONS}
        total = sum(posterior.values())
        probabilities = {action: posterior[action] / total for action in ACTIONS}
        uncertainty = {}
        for action in ACTIONS:
            a = posterior[action]
            variance = a * (total - a) / (total * total * (total + 1.0))
            sd = math.sqrt(max(0.0, variance))
            mean = probabilities[action]
            uncertainty[action] = {
                "mean": mean,
                "approx_95": [max(0.0, mean - 1.96 * sd), min(1.0, mean + 1.96 * sd)],
            }
        index = int(level["index"])
        exact_supported = index == 0
        used_empirical_bin = (not self.document["reference_mode"]) and index >= 7 and index <= 8
        return {
            "schema": EMPIRICAL_PREDICTION_SCHEMA,
            "identity": self.identity,
            "exact_context": ctx,
            "selected_level": {
                "index": index,
                "dimensions": list(level["dimensions"]),
                "key": key,
            },
            "effective_support": {
                "observations": int(node["observations"]),
                "distinct_hands": int(node["distinct_hands"]),
                "source_split": "TRAIN",
            },
            "support_state": (
                "EXACT_SUPPORTED" if exact_supported
                else "DECLARED_EMPIRICAL_BIN_BACKOFF" if used_empirical_bin
                else "DECLARED_CONTEXT_BACKOFF"
            ),
            "failed_finer_levels": failed,
            "probabilities": probabilities,
            "uncertainty": uncertainty,
            "price_zone": {
                "target_exact": ctx["target_exact"],
                "target_bin": ctx["target_bin"],
                "price_bin": ctx["price_bin"],
                "stack_bin": ctx["stack_bin"],
            },
            "production_effect": "NONE",
        }

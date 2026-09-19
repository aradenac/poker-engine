from __future__ import annotations

import copy
import hashlib
import json
import math
import statistics
from dataclasses import dataclass
from typing import Any, Callable, Mapping

SCHEMA = "paired-adaptive-preflop-ev/v1"
PAIRING_CONTRACT = "DECISION_SAMPLE_COMMON_RANDOM_NUMBERS_V1"
LEGACY_SEED_CONTRACT = "BASE_SEED_CANDIDATE_ID_SAMPLE_INDEX_SHA256_PREFIX64"

WorldFactory = Callable[[Mapping[str, Any], str, int, int], Mapping[str, Any]]
PairedEvaluator = Callable[[Mapping[str, Any], str, Mapping[str, Any]], float]
LegacyEvaluator = Callable[[str, Mapping[str, Any], int, int], float]

_FORBIDDEN_PUBLIC_KEY_FRAGMENTS = (
    "opponent_hole",
    "villain_hole",
    "private_card",
    "private_cards",
    "future_board",
    "future_card",
    "future_cards",
    "runout",
    "showdown_cards",
)


class PairedSearchError(ValueError):
    """Raised when the preparatory paired/adaptive search contract is violated."""


@dataclass(frozen=True)
class AdaptiveBudget:
    initial_samples_per_alternative: int = 8
    max_samples_per_alternative: int = 64
    batch_size: int = 8
    max_total_rollouts: int | None = None
    confidence_z: float = 1.96
    elimination_margin_bb: float = 0.0

    def validate(self, non_exact_alternatives: int) -> None:
        for name, value in (
            ("initial_samples_per_alternative", self.initial_samples_per_alternative),
            ("max_samples_per_alternative", self.max_samples_per_alternative),
            ("batch_size", self.batch_size),
        ):
            if int(value) != value or value <= 0:
                raise PairedSearchError(f"{name} must be a positive integer")
        if self.initial_samples_per_alternative > self.max_samples_per_alternative:
            raise PairedSearchError("initial samples cannot exceed max samples")
        if not math.isfinite(float(self.confidence_z)) or self.confidence_z <= 0:
            raise PairedSearchError("confidence_z must be finite and positive")
        if not math.isfinite(float(self.elimination_margin_bb)) or self.elimination_margin_bb < 0:
            raise PairedSearchError("elimination_margin_bb must be finite and >= 0")
        if self.max_total_rollouts is not None:
            if int(self.max_total_rollouts) != self.max_total_rollouts or self.max_total_rollouts <= 0:
                raise PairedSearchError("max_total_rollouts must be a positive integer")
            required = self.initial_samples_per_alternative * non_exact_alternatives
            if self.max_total_rollouts < required:
                raise PairedSearchError(
                    "max_total_rollouts is smaller than the declared initial budget"
                )


def _round(value: float) -> float:
    return round(float(value), 9)


def _finite(value: Any, name: str) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise PairedSearchError(f"{name} must be finite")
    return value


def _seed64(payload: str) -> int:
    return int.from_bytes(hashlib.sha256(payload.encode("utf-8")).digest()[:8], "big")


def legacy_candidate_seed(base_seed: int | str, candidate_id: str, sample_index: int) -> int:
    """Exactly preserve the historical preflop_grid_evaluator seed namespace."""
    return _seed64(f"{base_seed}|{candidate_id}|{int(sample_index)}")


def common_world_seed(base_seed: int | str, decision_id: str, sample_index: int) -> int:
    """Candidate-independent CRN namespace: decision + sample only."""
    decision_id = str(decision_id).strip()
    if not decision_id:
        raise PairedSearchError("decision_id is required")
    return _seed64(f"{base_seed}|{decision_id}|{int(sample_index)}")


def _assert_public_context(value: Any, path: str = "public_context") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key).strip().lower()
            if any(fragment in key_text for fragment in _FORBIDDEN_PUBLIC_KEY_FRAGMENTS):
                raise PairedSearchError(
                    f"{path}.{key} is future/private information and cannot seed world materialization"
                )
            _assert_public_context(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _assert_public_context(child, f"{path}[{index}]")


def _world_fingerprint(world: Mapping[str, Any]) -> str:
    try:
        payload = json.dumps(
            world, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        )
    except (TypeError, ValueError) as exc:
        raise PairedSearchError("world_factory must return canonical JSON-compatible data") from exc
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _mean(values: list[float]) -> float:
    if not values:
        raise PairedSearchError("cannot summarize an unsampled alternative")
    return statistics.fmean(values)


def _se(values: list[float]) -> float:
    return 0.0 if len(values) < 2 else statistics.stdev(values) / math.sqrt(len(values))


def _paired_stats(left: list[float], right: list[float], z: float) -> dict[str, Any]:
    n = min(len(left), len(right))
    if n <= 0:
        return {
            "samples": 0,
            "delta_ev_bb": None,
            "variance_bb2": None,
            "standard_error_bb": None,
            "ci_lower_bb": None,
            "ci_upper_bb": None,
        }
    deltas = [left[i] - right[i] for i in range(n)]
    mean = statistics.fmean(deltas)
    variance = 0.0 if n < 2 else statistics.variance(deltas)
    se = 0.0 if n < 2 else math.sqrt(variance / n)
    return {
        "samples": n,
        "delta_ev_bb": _round(mean),
        "variance_bb2": _round(variance),
        "standard_error_bb": _round(se),
        "ci_lower_bb": _round(mean - z * se),
        "ci_upper_bb": _round(mean + z * se),
    }


def _leader(active: set[str], values: Mapping[str, list[float]]) -> str:
    # Explicit lexical tie break makes the result independent of mapping/set iteration order.
    return min(sorted(active), key=lambda cid: (-_mean(values[cid]), cid))


def _pairwise(values: Mapping[str, list[float]], z: float) -> dict[str, Any]:
    ids = sorted(values)
    result: dict[str, Any] = {}
    for i, left in enumerate(ids):
        for right in ids[i + 1 :]:
            result[f"{left}__minus__{right}"] = _paired_stats(values[left], values[right], z)
    return result


def _summary(
    *,
    mode: str,
    candidate_payloads: Mapping[str, Mapping[str, Any]],
    values: Mapping[str, list[float]],
    selected_id: str,
    exact_values: Mapping[str, float],
    eliminated_at: Mapping[str, int],
    rollout_budget: int,
    worlds: Mapping[int, str],
    config: Mapping[str, Any],
    confidence_z: float,
) -> dict[str, Any]:
    alternatives: dict[str, Any] = {}
    for cid in sorted(candidate_payloads):
        samples = values[cid]
        ev = _mean(samples)
        se = _se(samples)
        paired = _paired_stats(samples, values[selected_id], confidence_z)
        alternatives[cid] = {
            "ev_bb": _round(ev),
            "samples": len(samples),
            "rollouts": 0 if cid in exact_values else len(samples),
            "standard_error_bb": _round(se),
            "ci_lower_bb": _round(ev - confidence_z * se),
            "ci_upper_bb": _round(ev + confidence_z * se),
            "paired_delta_vs_selected": paired,
            "status": (
                "SELECTED"
                if cid == selected_id
                else "ELIMINATED"
                if cid in eliminated_at
                else "RETAINED_TO_BUDGET"
            ),
            "eliminated_after_samples": eliminated_at.get(cid),
        }
    return {
        "schema": SCHEMA,
        "mode": mode,
        "selected_id": selected_id,
        "alternatives": alternatives,
        "pairwise_deltas": _pairwise(values, confidence_z),
        "search": {
            **dict(config),
            "rollout_budget_used": rollout_budget,
            "worlds_materialized": len(worlds),
            "world_fingerprints_sha256": {str(k): worlds[k] for k in sorted(worlds)},
        },
    }


def run_fixed_historical(
    candidate_payloads: Mapping[str, Mapping[str, Any]],
    *,
    evaluator: LegacyEvaluator,
    base_seed: int | str,
    samples_per_alternative: int,
    exact_values: Mapping[str, float] | None = None,
    confidence_z: float = 1.96,
) -> dict[str, Any]:
    """Compatibility mode matching historical candidate-dependent seed construction."""
    if int(samples_per_alternative) != samples_per_alternative or samples_per_alternative <= 0:
        raise PairedSearchError("samples_per_alternative must be a positive integer")
    exact = {str(k): _finite(v, f"exact_values[{k}]") for k, v in dict(exact_values or {}).items()}
    if not candidate_payloads:
        raise PairedSearchError("at least one candidate is required")
    unknown = sorted(set(exact) - set(candidate_payloads))
    if unknown:
        raise PairedSearchError(f"exact_values contains unknown candidates: {unknown}")

    values: dict[str, list[float]] = {str(cid): [] for cid in candidate_payloads}
    rollout_budget = 0
    for cid, payload in candidate_payloads.items():  # preserve historical candidate order
        cid = str(cid)
        if cid in exact:
            values[cid] = [exact[cid]] * int(samples_per_alternative)
            continue
        for sample_index in range(int(samples_per_alternative)):
            seed = legacy_candidate_seed(base_seed, cid, sample_index)
            values[cid].append(
                _finite(evaluator(cid, payload, sample_index, seed), f"ev[{cid}][{sample_index}]")
            )
            rollout_budget += 1
    selected = min(values, key=lambda cid: (-_mean(values[cid]), list(values).index(cid)))
    return _summary(
        mode="fixed_historical",
        candidate_payloads=candidate_payloads,
        values=values,
        selected_id=selected,
        exact_values=exact,
        eliminated_at={},
        rollout_budget=rollout_budget,
        worlds={},
        config={
            "seed_contract": LEGACY_SEED_CONTRACT,
            "base_seed": str(base_seed),
            "samples_per_alternative": int(samples_per_alternative),
            "adaptive": False,
        },
        confidence_z=float(confidence_z),
    )


def run_paired_search(
    candidate_payloads: Mapping[str, Mapping[str, Any]],
    *,
    decision_id: str,
    public_context: Mapping[str, Any],
    world_factory: WorldFactory,
    evaluator: PairedEvaluator,
    base_seed: int | str,
    budget: AdaptiveBudget,
    exact_values: Mapping[str, float] | None = None,
    adaptive: bool = True,
) -> dict[str, Any]:
    """Evaluate alternatives on identical candidate-independent worlds.

    The world is materialized once per decision/sample and deep-copied before each
    alternative evaluation, preventing mutation by one alternative from contaminating
    another. World inputs are restricted to public-at-decision context.
    """
    if not candidate_payloads:
        raise PairedSearchError("at least one candidate is required")
    decision_id = str(decision_id).strip()
    if not decision_id:
        raise PairedSearchError("decision_id is required")
    _assert_public_context(public_context)

    exact = {str(k): _finite(v, f"exact_values[{k}]") for k, v in dict(exact_values or {}).items()}
    unknown = sorted(set(exact) - set(candidate_payloads))
    if unknown:
        raise PairedSearchError(f"exact_values contains unknown candidates: {unknown}")
    non_exact_count = len(candidate_payloads) - len(exact)
    budget.validate(non_exact_count)

    values: dict[str, list[float]] = {str(cid): [] for cid in candidate_payloads}
    active = set(values)
    eliminated_at: dict[str, int] = {}
    rollout_budget = 0
    world_fingerprints: dict[int, str] = {}
    next_sample = 0

    def evaluate_batch(sample_count: int) -> int:
        nonlocal next_sample, rollout_budget
        if sample_count <= 0:
            return 0
        active_non_exact = [cid for cid in sorted(active) if cid not in exact]
        if not active_non_exact:
            return 0
        if budget.max_total_rollouts is not None:
            remaining = int(budget.max_total_rollouts) - rollout_budget
            sample_count = min(sample_count, remaining // len(active_non_exact))
        if sample_count <= 0:
            return 0
        current_n = min(len(values[cid]) for cid in active_non_exact)
        sample_count = min(
            sample_count,
            int(budget.max_samples_per_alternative) - current_n,
        )
        if sample_count <= 0:
            return 0

        for _ in range(sample_count):
            sample_index = next_sample
            seed = common_world_seed(base_seed, decision_id, sample_index)
            world = dict(
                world_factory(copy.deepcopy(public_context), decision_id, sample_index, seed)
            )
            fingerprint = _world_fingerprint(world)
            world_fingerprints[sample_index] = fingerprint
            for cid in sorted(active):
                if cid in exact:
                    values[cid].append(exact[cid])
                    continue
                payload = candidate_payloads[cid]
                ev = evaluator(copy.deepcopy(world), cid, copy.deepcopy(payload))
                values[cid].append(_finite(ev, f"ev[{cid}][{sample_index}]"))
                rollout_budget += 1
            # Already eliminated alternatives deliberately receive no new value.
            next_sample += 1
        return sample_count

    initial = int(budget.initial_samples_per_alternative)
    if evaluate_batch(initial) != initial and non_exact_count:
        raise PairedSearchError("could not satisfy declared initial paired budget")

    if adaptive:
        while len(active) > 1:
            leader = _leader(active, values)
            removed: list[str] = []
            for cid in sorted(active):
                if cid == leader:
                    continue
                stats = _paired_stats(values[cid], values[leader], float(budget.confidence_z))
                upper = stats["ci_upper_bb"]
                if upper is not None and upper < -float(budget.elimination_margin_bb):
                    removed.append(cid)
            for cid in removed:
                active.remove(cid)
                eliminated_at[cid] = len(values[cid])
            if len(active) <= 1:
                break
            before = rollout_budget
            if evaluate_batch(int(budget.batch_size)) <= 0:
                break
            if rollout_budget == before:
                break
    else:
        remaining = int(budget.max_samples_per_alternative) - initial
        while remaining > 0:
            batch = min(int(budget.batch_size), remaining)
            if evaluate_batch(batch) <= 0:
                break
            remaining -= batch

    selected = _leader(active if adaptive else set(values), values)
    return _summary(
        mode="paired_adaptive" if adaptive else "paired_fixed",
        candidate_payloads=candidate_payloads,
        values=values,
        selected_id=selected,
        exact_values=exact,
        eliminated_at=eliminated_at,
        rollout_budget=rollout_budget,
        worlds=world_fingerprints,
        config={
            "pairing_contract": PAIRING_CONTRACT,
            "base_seed": str(base_seed),
            "decision_id": decision_id,
            "initial_samples_per_alternative": int(budget.initial_samples_per_alternative),
            "max_samples_per_alternative": int(budget.max_samples_per_alternative),
            "batch_size": int(budget.batch_size),
            "max_total_rollouts": budget.max_total_rollouts,
            "confidence_z": float(budget.confidence_z),
            "elimination_margin_bb": float(budget.elimination_margin_bb),
            "adaptive": bool(adaptive),
        },
        confidence_z=float(budget.confidence_z),
    )

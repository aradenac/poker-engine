#!/usr/bin/env python3
"""Build the #196 TRAIN-only future Hero preflop generation plan.

Consumes only the persisted TRAIN coverage audit from #251. This planner never
generates strategy, evaluates EV, recommends actions/sizings, consumes
VALIDATION/TEST, or selects a nearest context.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_AUDIT = ROOT / "analysis/hero_preflop_coverage_train.json"
DEFAULT_JSON = ROOT / "analysis/hero_preflop_generation_plan.json"
DEFAULT_MD = ROOT / "analysis/hero_preflop_generation_plan.md"

SCHEMA = "poker-hero-preflop-generation-plan/v1"
SOURCE_SCHEMA = "poker-hero-preflop-coverage-audit/v1"
FALLBACK_ID = "NO_NEAREST_CONTEXT__INCUMBENT_EXACT_OR_UNCOVERED_V1"
HAND_CLASSES_PER_CONTEXT = 169
MAX_CONTEXTS_PER_SHARD = 16
TARGET_GROUPS = (
    "VS_LIMPERS_ISO",
    "VS_RFI",
    "RFI_CALLERS_SQUEEZE",
    "VS_3BET",
    "VS_4BET_OR_JAM",
)
STATUS_BY_SUPPORT = {
    "VERY_HIGH": "READY_FOR_GENERATION",
    "HIGH": "READY_FOR_GENERATION",
    "MEDIUM": "LOW_SUPPORT",
    "LOW": "DEFERRED",
    "SPARSE": "UNCOVERED",
}
STATUS_ORDER = {
    "READY_FOR_GENERATION": 0,
    "LOW_SUPPORT": 1,
    "DEFERRED": 2,
    "UNCOVERED": 3,
}
REQUIRED_MATRIX_FIELDS = (
    "family",
    "actor_position",
    "opener_position",
    "last_aggressor_position",
    "callers_after_first_raise",
    "limpers_before_first_raise",
    "facing_jam",
    "observations",
    "distinct_hands",
    "frequency_of_population_preflop",
    "frequency_of_targeted",
    "support_tier",
    "effective_stack",
)


class GenerationPlanError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_audit(path: Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema") != SOURCE_SCHEMA:
        raise GenerationPlanError(f"unexpected audit schema: {data.get('schema')!r}")
    scope = data.get("scope") or {}
    expected = {
        "split_consumed": "TRAIN",
        "validation_consumed": False,
        "test_consumed": False,
        "strategy_generated": False,
        "ev_evaluated": False,
    }
    for key, value in expected.items():
        if scope.get(key) != value:
            raise GenerationPlanError(f"audit scope {key}={scope.get(key)!r}, expected {value!r}")
    matrix = data.get("matrix")
    if not isinstance(matrix, list) or not matrix:
        raise GenerationPlanError("audit matrix must be non-empty")
    for index, row in enumerate(matrix):
        missing = [key for key in REQUIRED_MATRIX_FIELDS if key not in row]
        if missing:
            raise GenerationPlanError(f"matrix[{index}] missing {missing}")
        if int(row["observations"]) <= 0 or int(row["distinct_hands"]) <= 0:
            raise GenerationPlanError("cannot plan an invented context without observations")
        if row.get("coverage_group") not in TARGET_GROUPS:
            raise GenerationPlanError(f"unsupported coverage group {row.get('coverage_group')!r}")
    return data


def _finite(value: Any) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise GenerationPlanError("stack boundary must be finite")
    return value


def _stack_buckets(audit: Mapping[str, Any]) -> list[dict[str, Any]]:
    observed = audit["effective_stack_targeted_population"]
    values = [
        _finite(observed["p10_bb"]),
        _finite(observed["p25_bb"]),
        _finite(observed["p50_bb"]),
        _finite(observed["p75_bb"]),
        _finite(observed["p90_bb"]),
    ]
    if values != sorted(values) or len(values) != len(set(values)):
        raise GenerationPlanError("stack quantile cuts must be strictly increasing")
    ids = (
        "B0_LE_P10",
        "B1_P10_P25",
        "B2_P25_P50",
        "B3_P50_P75",
        "B4_P75_P90",
        "B5_GT_P90",
    )
    edges = [None] + values + [None]
    return [
        {
            "id": bucket_id,
            "lower_exclusive_bb": edges[index],
            "upper_inclusive_bb": edges[index + 1],
            "basis": "global targeted TRAIN effective-stack quantiles from #251",
            "assignment": "whole exact audit cell classified by observed p50; no invented sub-cell counts",
        }
        for index, bucket_id in enumerate(ids)
    ]


def _bucket_id(median_bb: float, buckets: Sequence[Mapping[str, Any]]) -> str:
    median = _finite(median_bb)
    for bucket in buckets:
        lower = bucket["lower_exclusive_bb"]
        upper = bucket["upper_inclusive_bb"]
        if (lower is None or median > float(lower)) and (upper is None or median <= float(upper)):
            return str(bucket["id"])
    raise AssertionError("non-exhaustive stack buckets")


def _token(value: Any) -> str:
    if value is None:
        return "NONE"
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value).strip().upper().replace(" ", "_")


def _context_id(row: Mapping[str, Any], stack_bucket: str) -> str:
    return (
        "pfgen:v1:"
        f"family={_token(row['family'])}:"
        f"hero={_token(row['actor_position'])}:"
        f"opener={_token(row['opener_position'])}:"
        f"lastagg={_token(row['last_aggressor_position'])}:"
        f"callers={int(row['callers_after_first_raise'])}:"
        f"limpers={int(row['limpers_before_first_raise'])}:"
        f"jam={1 if row['facing_jam'] else 0}:"
        f"stack={stack_bucket}"
    )


def _source_key(row: Mapping[str, Any]) -> str:
    payload = {
        "family": row["family"],
        "actor_position": row["actor_position"],
        "opener_position": row["opener_position"],
        "last_aggressor_position": row["last_aggressor_position"],
        "callers_after_first_raise": int(row["callers_after_first_raise"]),
        "limpers_before_first_raise": int(row["limpers_before_first_raise"]),
        "facing_jam": bool(row["facing_jam"]),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _group_order(audit: Mapping[str, Any]) -> list[str]:
    dist = audit["coverage_group_distribution_population"]
    groups = [group for group in TARGET_GROUPS if group in dist]
    return sorted(groups, key=lambda group: (-int(dist[group]), group))


def _family_order(matrix: Sequence[Mapping[str, Any]], groups: Sequence[str]) -> dict[str, list[str]]:
    observations: dict[str, int] = defaultdict(int)
    families: dict[str, set[str]] = defaultdict(set)
    for row in matrix:
        family = str(row["family"])
        observations[family] += int(row["observations"])
        families[str(row["coverage_group"])].add(family)
    return {
        group: sorted(families[group], key=lambda family: (-observations[family], family))
        for group in groups
    }


def build_plan(audit: Mapping[str, Any], *, audit_sha256: str) -> dict[str, Any]:
    matrix = list(audit["matrix"])
    buckets = _stack_buckets(audit)
    groups = _group_order(audit)
    group_rank = {group: index for index, group in enumerate(groups)}
    families_by_group = _family_order(matrix, groups)
    family_rank = {
        (group, family): index
        for group, families in families_by_group.items()
        for index, family in enumerate(families)
    }

    contexts = []
    seen_source = set()
    seen_ids = set()
    for row in matrix:
        source_key = _source_key(row)
        if source_key in seen_source:
            raise GenerationPlanError(f"duplicate audit context: {source_key}")
        seen_source.add(source_key)
        tier = str(row["support_tier"])
        if tier not in STATUS_BY_SUPPORT:
            raise GenerationPlanError(f"unknown support tier {tier!r}")
        readiness = STATUS_BY_SUPPORT[tier]
        stack_bucket = _bucket_id(row["effective_stack"]["p50_bb"], buckets)
        context_id = _context_id(row, stack_bucket)
        if context_id in seen_ids:
            raise GenerationPlanError(f"duplicate context_id: {context_id}")
        seen_ids.add(context_id)
        contexts.append(
            {
                "context_id": context_id,
                "source_matrix_key": source_key,
                "source_priority_rank": int(row["priority_rank"]),
                "coverage_group": row["coverage_group"],
                "family": row["family"],
                "hero_position": row["actor_position"],
                "opener_position": row["opener_position"],
                "last_aggressor_position": row["last_aggressor_position"],
                "caller_count": int(row["callers_after_first_raise"]),
                "limper_count": int(row["limpers_before_first_raise"]),
                "jam_state": bool(row["facing_jam"]),
                "effective_stack_bucket": stack_bucket,
                "effective_stack_observed": dict(row["effective_stack"]),
                "train_observations": int(row["observations"]),
                "distinct_hands": int(row["distinct_hands"]),
                "frequency": {
                    "of_population_preflop": float(row["frequency_of_population_preflop"]),
                    "of_targeted": float(row["frequency_of_targeted"]),
                },
                "support_tier": tier,
                "readiness": readiness,
                "exact_generation_eligible": readiness == "READY_FOR_GENERATION",
                "future_artifact_status": "EXPERIMENTAL",
                "fallback_id": FALLBACK_ID,
                "nearest_context_allowed": False,
            }
        )

    def ordering(context: Mapping[str, Any]) -> tuple[Any, ...]:
        group = str(context["coverage_group"])
        family = str(context["family"])
        return (
            STATUS_ORDER[str(context["readiness"])],
            group_rank[group],
            family_rank[(group, family)],
            -int(context["train_observations"]),
            -int(context["distinct_hands"]),
            int(context["source_priority_rank"]),
            str(context["context_id"]),
        )

    contexts.sort(key=ordering)
    for priority, context in enumerate(contexts, 1):
        context["generation_priority"] = priority

    ready = [row for row in contexts if row["readiness"] == "READY_FOR_GENERATION"]
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in ready:
        grouped[(str(row["coverage_group"]), str(row["effective_stack_bucket"]))].append(row)

    shards = []
    shard_number = 1
    for group in groups:
        for bucket in [item["id"] for item in buckets]:
            rows = grouped.get((group, bucket), [])
            for offset in range(0, len(rows), MAX_CONTEXTS_PER_SHARD):
                chunk = rows[offset:offset + MAX_CONTEXTS_PER_SHARD]
                shards.append(
                    {
                        "shard_id": f"GEN-{shard_number:03d}-{group}-{bucket}",
                        "coverage_group": group,
                        "effective_stack_bucket": bucket,
                        "context_count": len(chunk),
                        "hand_class_cells": len(chunk) * HAND_CLASSES_PER_CONTEXT,
                        "context_ids": [row["context_id"] for row in chunk],
                    }
                )
                shard_number += 1

    status_counts = Counter(row["readiness"] for row in contexts)
    group_counts = {}
    for group in groups:
        rows = [row for row in contexts if row["coverage_group"] == group]
        group_counts[group] = {
            "contexts": len(rows),
            "train_observations": sum(row["train_observations"] for row in rows),
            "status_counts": dict(sorted(Counter(row["readiness"] for row in rows).items())),
            "families_by_observed_support": families_by_group[group],
        }

    observations = sum(int(row["observations"]) for row in matrix)
    expected = int(audit["accounting"]["targeted_population_preflop_decisions"])
    if observations != expected:
        raise GenerationPlanError(f"matrix observations {observations} != accounting {expected}")

    return {
        "schema": SCHEMA,
        "population_id": audit["population_id"],
        "scope": {
            "split_consumed": "TRAIN",
            "validation_consumed": False,
            "test_consumed": False,
            "strategy_generated": False,
            "ev_evaluated": False,
            "actions_recommended": False,
            "sizings_recommended": False,
            "purpose": "future generation planning only",
        },
        "source": {
            "path": "analysis/hero_preflop_coverage_train.json",
            "schema": audit["schema"],
            "sha256": audit_sha256,
            "targeted_train_observations": expected,
            "matrix_contexts": len(matrix),
        },
        "priority_contract": {
            "coverage_group_order": groups,
            "coverage_group_order_basis": "descending observed TRAIN targeted decisions; lexical tie-break",
            "families_by_group": families_by_group,
            "support_to_readiness": STATUS_BY_SUPPORT,
            "within_family_order": "readiness, TRAIN observations desc, distinct hands desc, source rank, context_id",
            "other_family_policy": "only observed audit families; only HIGH/VERY_HIGH exact contexts are READY_FOR_GENERATION",
        },
        "exact_context_contract": {
            "required_dimensions": [
                "family",
                "hero_position",
                "opener_position",
                "last_aggressor_position",
                "caller_count",
                "limper_count",
                "jam_state",
                "effective_stack_bucket",
            ],
            "lookup": "exact context_id only",
            "nearest_context_allowed": False,
            "rule": "NO SILENT NEAREST-CONTEXT",
        },
        "stack_bucket_contract": {
            "source_distribution": dict(audit["effective_stack_targeted_population"]),
            "buckets": buckets,
            "important_limitation": (
                "The #251 audit has stack quantiles per exact cell, not raw per-stack counts. "
                "Each observed cell is therefore assigned by p50 without inventing finer contexts."
            ),
        },
        "fallback_contract": {
            "id": FALLBACK_ID,
            "trigger": "exact generated artifact unavailable or context not READY_FOR_GENERATION",
            "behavior": "use separately declared incumbent exact-context policy if available; otherwise EXACT_UNAVAILABLE / UNCOVERED",
            "forbidden": [
                "nearest stack bucket",
                "nearest position",
                "nearest family",
                "nearest opener/last aggressor",
                "silent caller/limper-count backoff",
                "silent jam-state backoff",
            ],
            "nearest_context_allowed": False,
        },
        "dependencies": {
            "planning_merge": ["persisted TRAIN audit #251"],
            "future_generation": [
                "#108 explicitly released",
                "#198 paired/adaptive integration decision completed",
                "generator supports exact context contract",
            ],
            "future_validation": ["generation artifact frozen", "VALIDATION explicitly invoked after generation"],
        },
        "generation_order": [row["context_id"] for row in ready],
        "shard_plan": {
            "max_contexts_per_shard": MAX_CONTEXTS_PER_SHARD,
            "partition_key": ["coverage_group", "effective_stack_bucket"],
            "ordering": "generation_priority",
            "shards": shards,
        },
        "structural_compute_estimator": {
            "actual_rollouts_executed": 0,
            "hand_classes_per_context": HAND_CLASSES_PER_CONTEXT,
            "ready_contexts": len(ready),
            "ready_hand_class_cells": len(ready) * HAND_CLASSES_PER_CONTEXT,
            "planned_shards": len(shards),
            "rollout_formula_if_later_enabled": (
                "SUM_over_ready_hand_class_cells(alternatives_evaluated * samples_allocated); "
                "alternatives and samples remain unresolved until #108 release/#198 integration"
            ),
            "wall_clock_estimate": None,
        },
        "summary": {
            "contexts_total": len(contexts),
            "train_observations_total": observations,
            "status_counts": dict(sorted(status_counts.items())),
            "group_counts": group_counts,
        },
        "contexts": contexts,
    }


def render_markdown(plan: Mapping[str, Any]) -> str:
    summary = plan["summary"]
    lines = [
        "# Hero preflop future generation plan — TRAIN-only",
        "",
        "Planning artifact only: no strategy, EV rollout, action/sizing recommendation, VALIDATION or TEST.",
        "",
        "## Readiness",
        "",
        "| State | Contexts |",
        "|---|---:|",
    ]
    for state in ("READY_FOR_GENERATION", "LOW_SUPPORT", "DEFERRED", "UNCOVERED"):
        lines.append(f"| {state} | {summary['status_counts'].get(state, 0)} |")
    lines += [
        "",
        f"- Exact audit contexts: **{summary['contexts_total']:,}**",
        f"- Targeted TRAIN observations: **{summary['train_observations_total']:,}**",
        f"- READY hand-class cells: **{plan['structural_compute_estimator']['ready_hand_class_cells']:,}**",
        f"- Planned READY shards: **{plan['structural_compute_estimator']['planned_shards']}**",
        "",
        "## Observed generation order",
        "",
        "| Order | Group | TRAIN obs. | READY | LOW_SUPPORT | DEFERRED | UNCOVERED |",
        "|---:|---|---:|---:|---:|---:|---:|",
    ]
    for index, group in enumerate(plan["priority_contract"]["coverage_group_order"], 1):
        row = summary["group_counts"][group]
        counts = row["status_counts"]
        lines.append(
            f"| {index} | {group} | {row['train_observations']:,} | "
            f"{counts.get('READY_FOR_GENERATION', 0)} | {counts.get('LOW_SUPPORT', 0)} | "
            f"{counts.get('DEFERRED', 0)} | {counts.get('UNCOVERED', 0)} |"
        )
    lines += [
        "",
        "## Stack buckets",
        "",
        "Derived from #251 global targeted TRAIN quantiles. Whole audit cells are classified by their observed p50; no sub-cell counts are invented.",
        "",
        "| Bucket | Lower exclusive BB | Upper inclusive BB |",
        "|---|---:|---:|",
    ]
    for bucket in plan["stack_bucket_contract"]["buckets"]:
        lower = "—" if bucket["lower_exclusive_bb"] is None else str(bucket["lower_exclusive_bb"])
        upper = "—" if bucket["upper_inclusive_bb"] is None else str(bucket["upper_inclusive_bb"])
        lines.append(f"| {bucket['id']} | {lower} | {upper} |")
    lines += [
        "",
        "## Exact lookup / fallback",
        "",
        "- NO SILENT NEAREST-CONTEXT. Lookup is exact context_id only.",
        f"- Fallback identifier: {plan['fallback_contract']['id']}.",
        "- Missing exact artifact: declared incumbent exact-context policy if separately available; otherwise EXACT_UNAVAILABLE / UNCOVERED.",
        "- Nearest stack/position/family/aggressor/caller/limper/jam substitution is forbidden.",
        "",
        "## Boundary",
        "",
        "- Planning merge depends only on #251.",
        "- Actual generation waits for explicit #108 release and the #198 integration decision.",
        "- Actual rollouts executed: 0.",
        "- VALIDATION=false; TEST=false; strategy_generated=false; ev_evaluated=false.",
        "",
        "## Reproduction",
        "",
        "    python3 tools/training/plan_hero_preflop_generation.py --audit analysis/hero_preflop_coverage_train.json --output-json analysis/hero_preflop_generation_plan.json --output-md analysis/hero_preflop_generation_plan.md",
        "",
    ]
    return "\n".join(lines)


def generate(audit_path: Path) -> tuple[dict[str, Any], str]:
    audit_path = Path(audit_path)
    audit = _load_audit(audit_path)
    plan = build_plan(audit, audit_sha256=_sha256(audit_path))
    return plan, render_markdown(plan)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_MD)
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    plan, markdown = generate(args.audit)
    json_text = json.dumps(plan, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not args.output_json.is_file() or args.output_json.read_text(encoding="utf-8") != json_text:
            raise SystemExit(f"generation plan JSON is stale: {args.output_json}")
        if not args.output_md.is_file() or args.output_md.read_text(encoding="utf-8") != markdown:
            raise SystemExit(f"generation plan Markdown is stale: {args.output_md}")
        print("Hero preflop generation plan: up to date")
        return 0
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json_text, encoding="utf-8")
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text(markdown, encoding="utf-8")
    print(json.dumps({
        "contexts": plan["summary"]["contexts_total"],
        "status_counts": plan["summary"]["status_counts"],
        "ready_hand_class_cells": plan["structural_compute_estimator"]["ready_hand_class_cells"],
        "planned_shards": plan["structural_compute_estimator"]["planned_shards"],
        "actual_rollouts_executed": 0,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

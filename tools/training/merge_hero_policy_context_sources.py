#!/usr/bin/env python3
"""Merge immutable #107 PFC sources into one PFPC-bound Hero repository.

Each source remains an editor-compatible exact-PFC repository plus its
``poker-hero-range-pfc-binding/v1`` evidence.  This merger does not recompute or
blend decisions.  It combines contexts byte-semantically, derives the frozen
``poker-preflop-policy-context/v1`` identity from each canonical source state,
and emits an explicit PFPC -> source-PFC authorization map.

Two source PFCs may not collide on one PFPC in v1.  Choosing between multiple
representatives inside a bucket would be a scientific selection step and must
therefore be specified by a later version instead of silently resolved here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from tools.preflop.policy_context import (
    SCHEMA as POLICY_CONTEXT_SCHEMA,
    build_policy_context,
    contract_descriptor,
)
from tools.simulation.hero_preflop_overlay import POLICY_BINDING_SCHEMA

REPOSITORY_SCHEMA = "poker-hero-range-repository/v1"
SOURCE_BINDING_SCHEMA = "poker-hero-range-pfc-binding/v1"


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical_json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _source(
    repository_path: Path,
    binding_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    repository = load_json(repository_path)
    binding = load_json(binding_path)
    if repository.get("schema") != REPOSITORY_SCHEMA:
        raise ValueError(f"{repository_path}: expected {REPOSITORY_SCHEMA}")
    if binding.get("schema") != SOURCE_BINDING_SCHEMA:
        raise ValueError(f"{binding_path}: expected {SOURCE_BINDING_SCHEMA}")
    expected_sha = str((binding.get("artifact_sha256") or {}).get("hero_range_repository_pfc") or "")
    actual_sha = sha256_file(repository_path)
    if actual_sha != expected_sha:
        raise ValueError(f"{repository_path}: source repository SHA mismatch")
    pfc_id = str(binding.get("preflop_context_id") or "")
    canonical = dict(binding.get("canonical_preflop_context") or {})
    if str(canonical.get("context_id") or "") != pfc_id:
        raise ValueError(f"{binding_path}: canonical PFC identity mismatch")
    matching_nodes = [
        node
        for node in (repository.get("contexts") or {}).values()
        if str((node.get("context") or {}).get("preflop_context_id") or "") == pfc_id
    ]
    if len(matching_nodes) != 1:
        raise ValueError(f"{repository_path}: expected exactly one context for {pfc_id}")
    node = matching_nodes[0]
    hands = dict((((node.get("layers") or {}).get("calculated") or {}).get("hands") or {}))
    supported = int((binding.get("coverage") or {}).get("supported") or len(hands))
    if supported != len(hands):
        raise ValueError(f"{repository_path}: binding/repository supported-hand mismatch")
    policy_context = build_policy_context(canonical)
    evidence = {
        "repository_path": str(repository_path),
        "repository_sha256": actual_sha,
        "binding_path": str(binding_path),
        "binding_sha256": sha256_file(binding_path),
        "source_run_id": str(binding.get("run_id") or binding.get("source_run_id") or ""),
        "preflop_context_id": pfc_id,
        "policy_context": policy_context,
        "supported_hand_classes": len(hands),
        "unsupported_hand_classes": int((binding.get("coverage") or {}).get("unsupported") or 0),
        "context": dict(node.get("context") or {}),
        "node": node,
        "population_id": str(binding.get("population_id") or (node.get("context") or {}).get("population_id") or ""),
    }
    return repository, binding, evidence


def merge_sources(
    repository_paths: Sequence[Path],
    binding_paths: Sequence[Path],
    *,
    run_id: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if not repository_paths or len(repository_paths) != len(binding_paths):
        raise ValueError("equal non-empty --source-repository/--source-binding lists are required")
    sources = [_source(repo, binding) for repo, binding in zip(repository_paths, binding_paths)]
    populations = {evidence["population_id"] for _, _, evidence in sources}
    if len(populations) != 1 or not next(iter(populations)):
        raise ValueError(f"source populations must match exactly: {sorted(populations)}")
    population_id = next(iter(populations))

    first_repository = sources[0][0]
    merged = {
        "schema": REPOSITORY_SCHEMA,
        "version": int(first_repository.get("version") or 1),
        "source": {
            "format": "calculated-multi-context",
            "preserved_verbatim": False,
            "meta": {
                "run_id": str(run_id),
                "issue": 107,
                "selection": "NOT_PROMOTED_EXPERIMENTAL",
            },
            "range_folder": None,
        },
        "defaults": dict(first_repository.get("defaults") or {}),
        "contexts": {},
    }
    merged["defaults"]["population_id"] = population_id

    policy_bindings: dict[str, dict[str, Any]] = {}
    source_summary = []
    for repository, binding, evidence in sources:
        del repository
        node = evidence.pop("node")
        context = dict(node.get("context") or {})
        key = next(
            key
            for key, value in (sources[source_summary.__len__()][0].get("contexts") or {}).items()
            if value is node
        ) if False else None
        # Repository context keys are content-addressing helpers owned by the
        # editor schema. Recompute their unique source key without assuming
        # Python object identity after JSON decoding.
        matches = [
            source_key
            for source_key, source_node in (sources[len(source_summary)][0].get("contexts") or {}).items()
            if str((source_node.get("context") or {}).get("preflop_context_id") or "") == evidence["preflop_context_id"]
        ]
        if len(matches) != 1:
            raise AssertionError("source context lookup drifted")
        source_key = matches[0]
        if source_key in merged["contexts"]:
            raise ValueError(f"duplicate Hero repository context key {source_key}")
        merged["contexts"][source_key] = node

        policy_context = dict(evidence["policy_context"])
        policy_context_id = str(policy_context["policy_context_id"])
        if policy_context_id in policy_bindings:
            other = policy_bindings[policy_context_id]
            raise ValueError(
                f"PFPC collision {policy_context_id}: {other['preflop_context_id']} and {evidence['preflop_context_id']}"
            )
        policy_bindings[policy_context_id] = {
            "preflop_context_id": evidence["preflop_context_id"],
            "source_run_id": evidence["source_run_id"],
            "source_repository_sha256": evidence["repository_sha256"],
            "source_binding_sha256": evidence["binding_sha256"],
            "actor_position": policy_context["actor_position"],
            "family": policy_context["family"],
            "effective_stack_bucket": policy_context["effective_stack_bucket"],
            "supported_hand_classes": evidence["supported_hand_classes"],
            "unsupported_hand_classes": evidence["unsupported_hand_classes"],
        }
        source_summary.append({
            key: value
            for key, value in evidence.items()
            if key not in {"policy_context"}
        } | {"policy_context_id": policy_context_id})

    repository_bytes = canonical_json_bytes(merged)
    repository_sha = hashlib.sha256(repository_bytes).hexdigest()
    policy_binding = {
        "schema": POLICY_BINDING_SCHEMA,
        "issue": 107,
        "run_id": str(run_id),
        "status": "EXPERIMENTAL",
        "promotion_authorized": False,
        "population_id": population_id,
        "policy_context_schema": POLICY_CONTEXT_SCHEMA,
        "policy_context_contract": contract_descriptor(),
        "repository_sha256": repository_sha,
        "matching": "EXACT_PFPC_AND_169_HAND_CLASS_ONLY",
        "nearest_context_substitution": False,
        "bindings": dict(sorted(policy_bindings.items())),
        "selection_boundary": {
            "validation_consumed": False,
            "test_consumed": False,
        },
    }
    summary = {
        "schema": "poker-hero-policy-context-merge-result/v1",
        "issue": 107,
        "run_id": str(run_id),
        "population_id": population_id,
        "repository_sha256": repository_sha,
        "policy_contexts": len(policy_bindings),
        "repository_contexts": len(merged["contexts"]),
        "supported_hand_slots": sum(row["supported_hand_classes"] for row in policy_bindings.values()),
        "unsupported_hand_slots": sum(row["unsupported_hand_classes"] for row in policy_bindings.values()),
        "promotion_authorized": False,
        "validation_consumed": False,
        "test_consumed": False,
        "sources": source_summary,
    }
    return merged, policy_binding, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-repository", type=Path, action="append", required=True)
    parser.add_argument("--source-binding", type=Path, action="append", required=True)
    parser.add_argument("--repository-out", type=Path, required=True)
    parser.add_argument("--policy-binding-out", type=Path, required=True)
    parser.add_argument("--summary-out", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()

    repository, binding, summary = merge_sources(
        args.source_repository,
        args.source_binding,
        run_id=args.run_id,
    )
    args.repository_out.parent.mkdir(parents=True, exist_ok=True)
    repository_bytes = canonical_json_bytes(repository)
    args.repository_out.write_bytes(repository_bytes)
    if hashlib.sha256(repository_bytes).hexdigest() != binding["repository_sha256"]:
        raise AssertionError("merged repository serialization hash drifted")
    args.policy_binding_out.parent.mkdir(parents=True, exist_ok=True)
    args.policy_binding_out.write_bytes(canonical_json_bytes(binding))
    args.summary_out.parent.mkdir(parents=True, exist_ok=True)
    args.summary_out.write_bytes(canonical_json_bytes(summary))
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

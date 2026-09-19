#!/usr/bin/env python3
"""Fail-closed validator for future content-addressed Hero preflop generations.

Contract-only infrastructure for #196. It performs no rollout, EV calculation,
strategy selection, action recommendation, VALIDATION or TEST consumption.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

MANIFEST_SCHEMA = "poker-hero-preflop-generation-manifest/v1"
SHARD_SCHEMA = "poker-hero-preflop-strategy-shard/v1"
BINDING_SCHEMA = "poker-hero-preflop-generation-binding/v1"
PLAN_SCHEMA = "poker-hero-preflop-generation-plan/v1"
HAND_ORDER_ID = "poker-hand-class-169-matrix-row-major-v1"
RANKS = "AKQJT98765432"
FALLBACK_STATES = ["EXACT_GENERATED", "EXACT_INCUMBENT_FALLBACK", "EXACT_UNAVAILABLE"]
FORBIDDEN_SUBSTITUTIONS = {
    "NEAREST_STACK", "NEAREST_POSITION", "NEAREST_OPENER", "NEAREST_FAMILY",
    "CALLER_COUNT_BACKOFF", "LIMPER_COUNT_BACKOFF", "JAM_STATE_BACKOFF",
}


class ContractError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def fail(code: str, message: str) -> None:
    raise ContractError(code, message)


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        fail("INVALID_JSON", f"{path}: {exc}")
    if not isinstance(value, dict):
        fail("INVALID_JSON", f"{path}: root must be an object")
    return value


def canonical_json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_path(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def canonical_hand_classes() -> list[str]:
    out: list[str] = []
    for i, row in enumerate(RANKS):
        for j, col in enumerate(RANKS):
            if i == j:
                out.append(row + col)
            elif i < j:
                out.append(row + col + "s")
            else:
                out.append(col + row + "o")
    if len(out) != 169 or len(set(out)) != 169:
        raise AssertionError("canonical 169 hand-class grid is invalid")
    return out


CANONICAL_HAND_CLASSES = tuple(canonical_hand_classes())
CANONICAL_HAND_SET = set(CANONICAL_HAND_CLASSES)


def safe_artifact_path(root: Path, relative: str) -> Path:
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts:
        fail("UNSAFE_ARTIFACT_PATH", relative)
    root_resolved = root.resolve()
    path = (root / rel).resolve()
    if root_resolved not in path.parents and path != root_resolved:
        fail("UNSAFE_ARTIFACT_PATH", relative)
    if not path.is_file():
        fail("MISSING_ARTIFACT", relative)
    return path


def _exact_context_fields(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "family": row["family"],
        "hero_position": row["hero_position"],
        "opener_position": row["opener_position"],
        "last_aggressor_position": row["last_aggressor_position"],
        "caller_count": int(row["caller_count"]),
        "limper_count": int(row["limper_count"]),
        "jam_state": bool(row["jam_state"]),
        "stack_bucket": row["effective_stack_bucket"],
    }


def validate_fallback_contract(manifest: Mapping[str, Any]) -> None:
    fallback = manifest.get("fallback_contract") or {}
    if fallback.get("states") != FALLBACK_STATES:
        fail("FALLBACK_CONTRACT_INVALID", "fallback states/order changed")
    if fallback.get("resolution_order") != FALLBACK_STATES:
        fail("FALLBACK_CONTRACT_INVALID", "resolution order changed")
    if fallback.get("lookup") != "EXACT_CONTEXT_ONLY":
        fail("NEAREST_CONTEXT_FORBIDDEN", "lookup must be exact-context only")
    if fallback.get("nearest_context_allowed") is not False:
        fail("NEAREST_CONTEXT_FORBIDDEN", "nearest-context lookup is forbidden")
    forbidden = set(fallback.get("forbidden_substitutions") or [])
    if forbidden != FORBIDDEN_SUBSTITUTIONS:
        fail("FALLBACK_CONTRACT_INVALID", "forbidden substitution set is incomplete")


def resolve_fallback(
    binding: Mapping[str, Any],
    requested_context_id: str,
    *,
    incumbent_exact_context_ids: set[str] | None = None,
) -> str:
    generated = {str(row.get("context_id") or "") for row in binding.get("bindings") or []}
    if requested_context_id in generated:
        return "EXACT_GENERATED"
    if requested_context_id in (incumbent_exact_context_ids or set()):
        return "EXACT_INCUMBENT_FALLBACK"
    return "EXACT_UNAVAILABLE"


def enforce_immutability(
    manifest: Mapping[str, Any],
    manifest_sha256: str,
    registry: Mapping[str, str] | None,
) -> None:
    policy = manifest.get("immutability") or {}
    required = {
        "content_addressed": True,
        "hash_algorithm": "sha256",
        "in_place_modification_allowed": False,
        "correction_policy": "NEW_GENERATION_ID",
        "finalized_state": "FINALIZED",
    }
    for key, value in required.items():
        if policy.get(key) != value:
            fail("IMMUTABILITY_CONTRACT_INVALID", f"{key}={policy.get(key)!r}")
    if (manifest.get("completeness") or {}).get("state") != "FINALIZED":
        return
    generation_id = str(manifest.get("generation_id") or "")
    previous = (registry or {}).get(generation_id)
    if previous is not None and previous != manifest_sha256:
        fail(
            "IMMUTABLE_GENERATION_CHANGED",
            f"finalized generation {generation_id} changed from {previous} to {manifest_sha256}; use a new generation_id",
        )


def _verify_artifact_hashes(root: Path, manifest: Mapping[str, Any]) -> dict[str, tuple[Path, dict[str, Any]]]:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        fail("MANIFEST_INVALID", "artifacts must be a non-empty list")
    by_path: dict[str, tuple[Path, dict[str, Any]]] = {}
    for item in artifacts:
        if not isinstance(item, dict):
            fail("MANIFEST_INVALID", "artifact entry must be an object")
        rel = str(item.get("path") or "")
        if not rel or rel in by_path:
            fail("DUPLICATE_ARTIFACT", rel or "<empty>")
        path = safe_artifact_path(root, rel)
        actual = sha256_path(path)
        expected = str(item.get("sha256") or "")
        if actual != expected:
            fail("HASH_MISMATCH", f"{rel}: expected {expected}, got {actual}")
        by_path[rel] = (path, item)
    return by_path


def validate_generation(
    root: Path,
    plan_path: Path,
    *,
    allow_synthetic: bool = False,
    immutability_registry: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    root = Path(root)
    manifest_path = root / "manifest.json"
    manifest = load_json(manifest_path)
    plan = load_json(plan_path)

    if manifest.get("schema") != MANIFEST_SCHEMA:
        fail("MANIFEST_SCHEMA_MISMATCH", str(manifest.get("schema")))
    if plan.get("schema") != PLAN_SCHEMA:
        fail("PLAN_SCHEMA_MISMATCH", str(plan.get("schema")))
    if manifest.get("source_plan_sha256") != sha256_path(plan_path):
        fail("SOURCE_PLAN_HASH_MISMATCH", "manifest does not bind exact plan bytes")
    if manifest.get("source_train_audit_sha256") != (plan.get("source") or {}).get("sha256"):
        fail("SOURCE_AUDIT_HASH_MISMATCH", "manifest TRAIN audit hash differs from plan")
    if manifest.get("population_id") != plan.get("population_id"):
        fail("POPULATION_MISMATCH", "manifest population differs from source plan")

    projection = manifest.get("plan_projection") or {}
    structural = plan.get("structural_compute_estimator") or {}
    expected_projection = {
        "ready_context_count": len(plan.get("generation_order") or []),
        "expected_hand_classes_per_context": 169,
        "ready_cell_count": int(structural.get("ready_hand_class_cells") or 0),
        "planned_shard_count": int(structural.get("planned_shards") or 0),
    }
    if projection != expected_projection:
        fail("PLAN_PROJECTION_MISMATCH", f"expected {expected_projection}, got {projection}")
    if expected_projection != {
        "ready_context_count": 44,
        "expected_hand_classes_per_context": 169,
        "ready_cell_count": 7436,
        "planned_shard_count": 6,
    }:
        fail("CURRENT_PLAN_SCALE_MISMATCH", str(expected_projection))

    synthetic = manifest.get("synthetic_fixture") is True
    if synthetic and not allow_synthetic:
        fail("SYNTHETIC_FIXTURE_FORBIDDEN", "explicit allow_synthetic is required")
    scope = manifest.get("generation_scope")
    ready_ids = list(plan.get("generation_order") or [])
    ready_set = set(ready_ids)
    if scope == "FULL_READY_PLAN":
        expected_ids = ready_ids
        if synthetic:
            fail("MANIFEST_INVALID", "FULL_READY_PLAN cannot be marked synthetic")
        if int(manifest.get("shard_count") or 0) != expected_projection["planned_shard_count"]:
            fail("SHARD_COUNT_MISMATCH", "full generation must use current plan shard count")
    elif scope == "SYNTHETIC_FIXTURE_SUBSET":
        if not synthetic:
            fail("MANIFEST_INVALID", "synthetic subset must be marked synthetic_fixture")
        expected_ids = [str(x) for x in manifest.get("expected_context_ids") or []]
        if len(expected_ids) < 2 or len(expected_ids) != len(set(expected_ids)):
            fail("MANIFEST_INVALID", "synthetic fixture needs >=2 unique exact contexts")
        if not set(expected_ids).issubset(ready_set):
            fail("WRONG_CONTEXT_ID", "fixture context is not READY in source plan")
    elif scope == "AUTHORIZED_READY_SUBSET":
        if synthetic:
            fail("MANIFEST_INVALID", "authorized READY subset cannot be synthetic")
        expected_ids = [str(x) for x in manifest.get("expected_context_ids") or []]
        if not expected_ids or len(expected_ids) != len(set(expected_ids)):
            fail("MANIFEST_INVALID", "authorized READY subset needs unique exact contexts")
        if not set(expected_ids).issubset(ready_set):
            fail("WRONG_CONTEXT_ID", "authorized subset context is not READY in source plan")
        if expected_ids != [context_id for context_id in ready_ids if context_id in set(expected_ids)]:
            fail("CONTEXT_ORDER_MISMATCH", "authorized subset must preserve source-plan generation order")
    else:
        fail("MANIFEST_INVALID", f"unsupported generation_scope {scope!r}")

    if int(manifest.get("context_count") or 0) != len(expected_ids):
        fail("CONTEXT_COUNT_MISMATCH", "manifest context_count differs from expected scope")
    if int(manifest.get("expected_hand_classes_per_context") or 0) != 169:
        fail("HAND_CLASS_CONTRACT_MISMATCH", "expected 169 hand classes per context")
    if manifest.get("hand_class_order_id") != HAND_ORDER_ID:
        fail("HAND_CLASS_CONTRACT_MISMATCH", f"hand_class_order_id must be {HAND_ORDER_ID}")
    if manifest.get("expected_context_ids") != expected_ids:
        fail("CONTEXT_ORDER_MISMATCH", "expected_context_ids must exactly follow generation scope/order")

    validate_fallback_contract(manifest)
    artifacts = _verify_artifact_hashes(root, manifest)

    env = manifest.get("environment_identity") or {}
    params = manifest.get("generation_parameters") or {}
    for slot, role in ((env, "ENVIRONMENT_IDENTITY"), (params, "GENERATION_PARAMETERS")):
        path = str(slot.get("path") or "")
        if path not in artifacts or artifacts[path][1].get("role") != role:
            fail("CONTENT_SLOT_UNBOUND", f"{role} slot path not present in artifacts")
        if slot.get("sha256") != artifacts[path][1].get("sha256"):
            fail("CONTENT_SLOT_HASH_MISMATCH", role)

    binding_artifacts = [(p, pair) for p, pair in artifacts.items() if pair[1].get("role") == "BINDING"]
    if len(binding_artifacts) != 1:
        fail("BINDING_INCOMPLETE", f"expected one binding artifact, got {len(binding_artifacts)}")
    binding_path, (binding_file, _) = binding_artifacts[0]
    binding = load_json(binding_file)
    if binding.get("schema") != BINDING_SCHEMA:
        fail("BINDING_SCHEMA_MISMATCH", str(binding.get("schema")))

    for field in ("population_id", "generation_id", "candidate_id"):
        if binding.get(field) != manifest.get(field):
            code = "POPULATION_MISMATCH" if field == "population_id" else ("WRONG_GENERATION" if field == "generation_id" else "WRONG_CANDIDATE")
            fail(code, f"binding {field} mismatch")
    policy = binding.get("lookup_policy") or {}
    if policy.get("mode") != "EXACT_CONTEXT_ONLY" or policy.get("nearest_context_allowed") is not False:
        fail("NEAREST_CONTEXT_FORBIDDEN", "binding lookup policy must be exact-only")
    if policy.get("fallback_states") != FALLBACK_STATES:
        fail("FALLBACK_CONTRACT_INVALID", "binding fallback states mismatch")

    binding_rows = binding.get("bindings") or []
    binding_by_context: dict[str, dict[str, Any]] = {}
    for row in binding_rows:
        context_id = str(row.get("context_id") or "")
        if context_id in binding_by_context:
            fail("DUPLICATE_BINDING", context_id)
        binding_by_context[context_id] = row
        for field in ("population_id", "generation_id", "candidate_id"):
            if row.get(field) != manifest.get(field):
                code = "POPULATION_MISMATCH" if field == "population_id" else ("WRONG_GENERATION" if field == "generation_id" else "WRONG_CANDIDATE")
                fail(code, f"binding row {context_id} {field} mismatch")
    if set(binding_by_context) != set(expected_ids):
        fail("BINDING_INCOMPLETE", f"binding contexts differ from expected exact set")

    plan_by_id = {str(row["context_id"]): row for row in plan.get("contexts") or []}
    shard_artifacts = {p: pair for p, pair in artifacts.items() if pair[1].get("role") == "STRATEGY_SHARD"}
    if len(shard_artifacts) != int(manifest.get("shard_count") or 0):
        fail("SHARD_COUNT_MISMATCH", "manifest shard_count differs from artifact list")

    cells_by_context: dict[str, list[dict[str, Any]]] = {context_id: [] for context_id in expected_ids}
    seen_cell_keys: set[tuple[str, str]] = set()
    actual_cells = 0
    actual_shard_contexts: set[str] = set()
    for rel, (path, artifact_meta) in shard_artifacts.items():
        shard = load_json(path)
        if shard.get("schema") != SHARD_SCHEMA:
            fail("SHARD_SCHEMA_MISMATCH", rel)
        for field in ("population_id", "generation_id", "candidate_id"):
            if shard.get(field) != manifest.get(field):
                code = "POPULATION_MISMATCH" if field == "population_id" else ("WRONG_GENERATION" if field == "generation_id" else "WRONG_CANDIDATE")
                fail(code, f"{rel} {field} mismatch")
        if shard.get("shard_id") != artifact_meta.get("shard_id"):
            fail("SHARD_ID_MISMATCH", rel)
        cells = shard.get("cells")
        if not isinstance(cells, list):
            fail("SHARD_SCHEMA_MISMATCH", f"{rel} cells not list")
        if len(cells) != int(artifact_meta.get("cell_count") or -1):
            fail("INCOMPLETE_SHARD", f"{rel} declared {artifact_meta.get('cell_count')} cells, contains {len(cells)}")
        shard_context_ids = sorted({str(cell.get("context_id") or "") for cell in cells})
        declared_context_ids = sorted(str(x) for x in (artifact_meta.get("context_ids") or []))
        if shard_context_ids != declared_context_ids:
            fail("INCOMPLETE_SHARD", f"{rel} context set differs from manifest")
        actual_shard_contexts.update(shard_context_ids)

        for cell in cells:
            actual_cells += 1
            if cell.get("population_id") != manifest.get("population_id"):
                fail("POPULATION_MISMATCH", "cell population differs from manifest")
            if cell.get("generation_id") != manifest.get("generation_id"):
                fail("WRONG_GENERATION", "cell belongs to another generation")
            if cell.get("candidate_id") != manifest.get("candidate_id"):
                fail("WRONG_CANDIDATE", "cell belongs to another candidate")
            context_id = str(cell.get("context_id") or "")
            if context_id not in expected_ids:
                fail("WRONG_CONTEXT_ID", context_id)
            plan_context = plan_by_id.get(context_id)
            if plan_context is None or plan_context.get("readiness") != "READY_FOR_GENERATION":
                fail("WRONG_CONTEXT_ID", f"{context_id} not READY in plan")
            expected_context = _exact_context_fields(plan_context)
            for field, expected_value in expected_context.items():
                if cell.get(field) != expected_value:
                    code = "STACK_BUCKET_MISMATCH" if field == "stack_bucket" else "CONTEXT_MISMATCH"
                    fail(code, f"{context_id} {field}: expected {expected_value!r}, got {cell.get(field)!r}")
            hand = str(cell.get("hand_class") or "")
            if hand not in CANONICAL_HAND_SET:
                fail("INVALID_HAND_CLASS", hand)
            key = (context_id, hand)
            if key in seen_cell_keys:
                fail("DUPLICATE_HAND_CLASS", f"{context_id} {hand}")
            seen_cell_keys.add(key)
            support = cell.get("support") or {}
            if support != {
                "train_observations": int(plan_context["train_observations"]),
                "distinct_hands": int(plan_context["distinct_hands"]),
                "support_tier": plan_context["support_tier"],
                "source_plan_context_id": context_id,
            }:
                fail("SUPPORT_MISMATCH", f"{context_id} {hand}")
            provenance = cell.get("provenance") or {}
            if provenance.get("source_plan_sha256") != manifest.get("source_plan_sha256"):
                fail("PROVENANCE_MISMATCH", "cell source plan hash")
            if provenance.get("source_train_audit_sha256") != manifest.get("source_train_audit_sha256"):
                fail("PROVENANCE_MISMATCH", "cell source audit hash")
            for field in ("generator_version", "code_sha"):
                if provenance.get(field) != manifest.get(field):
                    fail("PROVENANCE_MISMATCH", field)
            if provenance.get("environment_identity_slot") != env.get("slot_id"):
                fail("PROVENANCE_MISMATCH", "environment identity slot")
            if provenance.get("generation_parameters_slot") != params.get("slot_id"):
                fail("PROVENANCE_MISMATCH", "generation parameters slot")
            if synthetic:
                if (cell.get("action") or {}).get("status") != "SYNTHETIC_PLACEHOLDER" or (cell.get("action") or {}).get("value") is not None:
                    fail("SYNTHETIC_FIXTURE_HAS_RECOMMENDATION", f"{context_id} {hand} action")
                sizing = cell.get("sizing") or {}
                if sizing.get("status") != "SYNTHETIC_PLACEHOLDER" or sizing.get("kind") != "SYNTHETIC_PLACEHOLDER" or sizing.get("value") is not None:
                    fail("SYNTHETIC_FIXTURE_HAS_RECOMMENDATION", f"{context_id} {hand} sizing")
                ev = cell.get("ev") or {}
                if ev.get("status") != "SYNTHETIC_PLACEHOLDER" or ev.get("estimate_bb") is not None:
                    fail("SYNTHETIC_FIXTURE_HAS_EV", f"{context_id} {hand}")
                rollout = cell.get("rollout") or {}
                if rollout.get("status") != "SYNTHETIC_PLACEHOLDER" or int(rollout.get("sample_count") or 0) != 0 or int(rollout.get("world_count") or 0) != 0:
                    fail("SYNTHETIC_FIXTURE_HAS_ROLLOUT", f"{context_id} {hand}")
            else:
                action = cell.get("action") or {}
                sizing = cell.get("sizing") or {}
                ev = cell.get("ev") or {}
                rollout = cell.get("rollout") or {}
                statuses = {
                    str(action.get("status") or ""),
                    str(sizing.get("status") or ""),
                    str(ev.get("status") or ""),
                    str(rollout.get("status") or ""),
                }
                if statuses == {"MEASURED"}:
                    if action.get("value") not in {"FOLD", "CHECK", "CALL", "BET", "RAISE", "SHOVE"}:
                        fail("PRODUCTION_CELL_NOT_MEASURED", f"{context_id} {hand} action")
                    if sizing.get("kind") == "SYNTHETIC_PLACEHOLDER":
                        fail("PRODUCTION_CELL_NOT_MEASURED", f"{context_id} {hand} sizing")
                    if not isinstance(ev.get("estimate_bb"), (int, float)):
                        fail("PRODUCTION_CELL_NOT_MEASURED", f"{context_id} {hand} EV")
                    if int(rollout.get("sample_count") or 0) < 1 or int(rollout.get("world_count") or 0) < 1:
                        fail("PRODUCTION_CELL_NOT_MEASURED", f"{context_id} {hand} rollout")
                elif statuses == {"EXACT_DETERMINISTIC"}:
                    uncertainty = ev.get("uncertainty") or {}
                    exact_ok = (
                        action.get("value") == "FOLD"
                        and sizing.get("kind") == "NONE"
                        and sizing.get("value") is None
                        and sizing.get("unit") is None
                        and ev.get("estimate_bb") == 0
                        and uncertainty == {
                            "method": "EXACT_DETERMINISTIC_ZERO",
                            "std_error_bb": 0,
                            "ci95_low_bb": 0,
                            "ci95_high_bb": 0,
                        }
                        and int(rollout.get("sample_count") or 0) >= 1
                        and int(rollout.get("world_count") or 0) == 0
                    )
                    if not exact_ok:
                        fail("EXACT_DETERMINISTIC_INVALID", f"{context_id} {hand}")
                else:
                    fail("PRODUCTION_CELL_STATUS_MISMATCH", f"{context_id} {hand}: {sorted(statuses)}")
            cells_by_context[context_id].append(cell)

    if actual_shard_contexts != set(expected_ids):
        fail("MISSING_CONTEXT", "shard context set differs from expected exact set")

    for context_id, cells in cells_by_context.items():
        present = {str(cell.get("hand_class") or "") for cell in cells}
        missing = CANONICAL_HAND_SET - present
        extra = present - CANONICAL_HAND_SET
        if missing:
            fail("MISSING_HAND_CLASS", f"{context_id}: {sorted(missing)[:5]} ({len(missing)} missing)")
        if extra:
            fail("INVALID_HAND_CLASS", f"{context_id}: {sorted(extra)[:5]}")
        if len(cells) != 169:
            fail("HAND_CLASS_COUNT_MISMATCH", f"{context_id}: {len(cells)}")
        bound = binding_by_context[context_id]
        artifact_path = str(bound.get("artifact_path") or "")
        if artifact_path not in shard_artifacts:
            fail("BINDING_INCOMPLETE", f"{context_id} path not a strategy shard")
        artifact_hash = shard_artifacts[artifact_path][1].get("sha256")
        if bound.get("artifact_sha256") != artifact_hash:
            fail("BINDING_HASH_MISMATCH", context_id)
        if bound.get("stack_bucket") != plan_by_id[context_id].get("effective_stack_bucket"):
            fail("STACK_BUCKET_MISMATCH", f"binding {context_id}")

    completeness = manifest.get("completeness") or {}
    expected_cells = len(expected_ids) * 169
    actual_context_count = len([cid for cid, cells in cells_by_context.items() if cells])
    expected_complete = {
        "expected_context_count": len(expected_ids),
        "actual_context_count": actual_context_count,
        "expected_cells": expected_cells,
        "actual_cells": actual_cells,
        "expected_shard_count": int(manifest.get("shard_count") or 0),
        "actual_shard_count": len(shard_artifacts),
    }
    for field, value in expected_complete.items():
        if completeness.get(field) != value:
            fail("COMPLETENESS_MISMATCH", f"{field}: expected {value}, got {completeness.get(field)}")
    if completeness.get("state") not in {"COMPLETE", "FINALIZED"}:
        fail("INCOMPLETE_GENERATION", str(completeness.get("state")))

    manifest_sha = sha256_path(manifest_path)
    enforce_immutability(manifest, manifest_sha, immutability_registry)
    return {
        "valid": True,
        "schema": MANIFEST_SCHEMA,
        "population_id": manifest["population_id"],
        "generation_id": manifest["generation_id"],
        "candidate_id": manifest["candidate_id"],
        "manifest_sha256": manifest_sha,
        "contexts": len(expected_ids),
        "hand_classes_per_context": 169,
        "cells": actual_cells,
        "shards": len(shard_artifacts),
        "fallback": FALLBACK_STATES,
        "nearest_context_allowed": False,
        "synthetic_fixture": synthetic,
        "scientific_effect": "NONE_CONTRACT_ONLY",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--allow-synthetic", action="store_true")
    parser.add_argument("--immutability-index", type=Path)
    args = parser.parse_args()
    registry = None
    if args.immutability_index is not None:
        registry = load_json(args.immutability_index).get("generations") or {}
    try:
        report = validate_generation(
            args.root,
            args.plan,
            allow_synthetic=args.allow_synthetic,
            immutability_registry=registry,
        )
    except ContractError as exc:
        print(json.dumps({"valid": False, "error": {"code": exc.code, "message": exc.message}}, indent=2, sort_keys=True))
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

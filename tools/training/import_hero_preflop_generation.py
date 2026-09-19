#!/usr/bin/env python3
"""Import a validated Hero preflop generation into poker-hero-range-repository/v1.

This is an integration contract for #196. Synthetic placeholders are preserved as
inactive calculated-layer metadata and can never become active recommendations.
The input repository is never mutated in place.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

from tools.training.validate_hero_preflop_generation import (
    BINDING_SCHEMA,
    CANONICAL_HAND_CLASSES,
    ContractError,
    FALLBACK_STATES,
    canonical_json_bytes,
    load_json,
    sha256_path,
    validate_generation,
)

IMPORT_SCHEMA = "poker-hero-preflop-repository-import/v1"
REPOSITORY_SCHEMA = "poker-hero-range-repository/v1"
EXACT_LOOKUP = "EXACT_CONTEXT_ONLY"
HAND_ORDER_ID = "poker-hand-class-169-matrix-row-major-v1"
REPLACEMENT_MODE = "REPLACE_CALCULATED_ATOMIC"
PLACEHOLDER_STATE = "SYNTHETIC_PLACEHOLDER_METADATA_ONLY"
ACTIVE_STATE = "ACTIVE_MEASURED"
SUPPORTED_FAMILIES = {
    "VS_LIMPERS": "VS_LIMPERS",
    "VS_ISO": "VS_RFI",
    "VS_RFI": "VS_RFI",
    "VS_RFI_CALLERS": "VS_RFI_CALLERS",
}
REPOSITORY_ACTION_BY_GENERATION_ACTION = {
    "FOLD": "FOLD",
    "CHECK": "CHECK",
    "CALL": "CALL",
    "SHOVE": "SHOVE",
}


def fail(code: str, message: str) -> None:
    raise ContractError(code, message)


def repository_preflop_context_id(context_id: str) -> str:
    digest = hashlib.sha256(context_id.encode("utf-8")).hexdigest()[:16]
    return f"PFC_{digest}"


def repository_context_key(context: Mapping[str, Any]) -> str:
    population = str(context["population_id"])
    table_size = int(context["table_size"])
    position = str(context["position"])
    stack = float(context["effective_stack_bb"])
    stack_text = str(int(stack)) if stack.is_integer() else str(round(stack, 3)).rstrip("0").rstrip(".")
    spot = str(context["spot"])
    pfc = str(context.get("preflop_context_id") or "")
    base = f"{population}|{table_size}|{position}|{stack_text}|{spot}"
    return f"{base}|{pfc}" if pfc else base


def _empty_layer(kind: str) -> dict[str, Any]:
    return {"kind": kind, "version": None, "provenance": None, "hands": {}}


def _validate_base_repository(repo: Mapping[str, Any], population_id: str) -> None:
    if not isinstance(repo, Mapping) or repo.get("schema") != REPOSITORY_SCHEMA:
        fail("BASE_REPOSITORY_SCHEMA_MISMATCH", str(repo.get("schema") if isinstance(repo, Mapping) else type(repo)))
    defaults = repo.get("defaults") or {}
    default_population = str(defaults.get("population_id") or "")
    if default_population and default_population != population_id:
        fail("POPULATION_MISMATCH", f"base repository population {default_population} != {population_id}")
    source = repo.get("source") or {}
    if source.get("preserved_verbatim") and source.get("range_folder") is None:
        fail("BASE_REPOSITORY_INVALID", "preserved imported source is missing range_folder")
    contexts = repo.get("contexts")
    if not isinstance(contexts, Mapping):
        fail("BASE_REPOSITORY_INVALID", "contexts must be an object")
    for key, node in contexts.items():
        if not isinstance(node, Mapping):
            fail("BASE_REPOSITORY_INVALID", f"context {key} is not an object")
        layers = node.get("layers") or {}
        for kind in ("personal", "calculated"):
            layer = layers.get(kind)
            if not isinstance(layer, Mapping) or layer.get("kind") != kind or not isinstance(layer.get("hands"), Mapping):
                fail("BASE_REPOSITORY_INVALID", f"context {key} has invalid {kind} layer")


def _load_generation_parts(root: Path, manifest: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    binding_meta = [item for item in manifest["artifacts"] if item["role"] == "BINDING"]
    if len(binding_meta) != 1:
        fail("BINDING_INCOMPLETE", f"expected one binding artifact, got {len(binding_meta)}")
    binding = load_json(root / binding_meta[0]["path"])
    if binding.get("schema") != BINDING_SCHEMA:
        fail("BINDING_SCHEMA_MISMATCH", str(binding.get("schema")))
    binding_by_context = {row["context_id"]: row for row in binding["bindings"]}

    cells_by_context: dict[str, list[dict[str, Any]]] = {context_id: [] for context_id in manifest["expected_context_ids"]}
    for artifact in manifest["artifacts"]:
        if artifact["role"] != "STRATEGY_SHARD":
            continue
        shard = load_json(root / artifact["path"])
        for cell in shard["cells"]:
            row = copy.deepcopy(cell)
            row["_source_shard_path"] = artifact["path"]
            row["_source_shard_sha256"] = artifact["sha256"]
            row["_source_shard_id"] = artifact["shard_id"]
            cells_by_context[cell["context_id"]].append(row)
    return binding, binding_by_context, cells_by_context


def _map_measured_strategy(cell: Mapping[str, Any]) -> dict[str, Any]:
    action = str((cell.get("action") or {}).get("value") or "")
    family = str(cell["family"])
    if action == "RAISE":
        if family == "VS_LIMPERS":
            mapped = "ISO"
        elif family in {"VS_ISO", "VS_RFI", "VS_RFI_CALLERS"}:
            mapped = "3BET"
        else:
            fail("UNSUPPORTED_ACTION_CONTEXT", f"RAISE in family {family}")
    elif action == "BET":
        fail("UNSUPPORTED_PREFLOP_ACTION", "BET cannot be projected into a preflop Hero repository")
    else:
        mapped = REPOSITORY_ACTION_BY_GENERATION_ACTION.get(action)
        if mapped is None:
            fail("UNSUPPORTED_PREFLOP_ACTION", action)

    sizing = cell.get("sizing") or {}
    sizings: dict[str, list[dict[str, Any]]] = {}
    if sizing.get("status") != "MEASURED":
        fail("PRODUCTION_CELL_NOT_MEASURED", f"{cell['context_id']} {cell['hand_class']} sizing")
    kind = sizing.get("kind")
    value = sizing.get("value")
    if kind == "FIXED_BB":
        if not isinstance(value, (int, float)) or float(value) <= 0:
            fail("UNREPRESENTABLE_SIZING", f"{cell['context_id']} {cell['hand_class']} FIXED_BB={value!r}")
        sizings[mapped] = [{"target_total_bb": float(value), "probability": 1.0}]
    elif kind in {"NONE", "ALL_IN"}:
        pass
    else:
        fail("UNREPRESENTABLE_SIZING", f"{cell['context_id']} {cell['hand_class']} kind={kind!r}")
    return {"actions": {mapped: 1.0}, "sizings": sizings, "notes": ""}


def _cell_metadata(cell: Mapping[str, Any], *, active: bool) -> dict[str, Any]:
    placeholder = (cell.get("action") or {}).get("status") == "SYNTHETIC_PLACEHOLDER"
    fallback_state = "EXACT_GENERATED" if active else "EXACT_UNAVAILABLE"
    return {
        "source_generation_id": cell["generation_id"],
        "candidate_id": cell["candidate_id"],
        "source_shard_id": cell["_source_shard_id"],
        "source_shard_path": cell["_source_shard_path"],
        "source_shard_sha256": cell["_source_shard_sha256"],
        "support": copy.deepcopy(cell["support"]),
        "artifact_state": "EXACT_GENERATED",
        "fallback_state": fallback_state,
        "active_recommendation": bool(active),
        "action_status": (cell.get("action") or {}).get("status"),
        "sizing_status": (cell.get("sizing") or {}).get("status"),
        "ev_status": (cell.get("ev") or {}).get("status"),
        "placeholder": placeholder,
    }


def _context_dimensions(plan_row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "context_id": plan_row["context_id"],
        "family": plan_row["family"],
        "hero_position": plan_row["hero_position"],
        "opener_position": plan_row["opener_position"],
        "last_aggressor_position": plan_row["last_aggressor_position"],
        "caller_count": int(plan_row["caller_count"]),
        "limper_count": int(plan_row["limper_count"]),
        "jam_state": bool(plan_row["jam_state"]),
        "stack_bucket": plan_row["effective_stack_bucket"],
    }


def _layer_version(manifest: Mapping[str, Any], manifest_sha256: str) -> str:
    return f"{manifest['generation_id']}::{manifest['candidate_id']}::{manifest_sha256[:16]}"


def import_generation(
    generation_root: Path,
    plan_path: Path,
    base_repository: Mapping[str, Any],
    *,
    allow_synthetic: bool = False,
    activate_measured: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    generation_root = Path(generation_root)
    plan_path = Path(plan_path)

    validation = validate_generation(
        generation_root,
        plan_path,
        allow_synthetic=allow_synthetic,
    )
    manifest = load_json(generation_root / "manifest.json")
    plan = load_json(plan_path)
    _validate_base_repository(base_repository, manifest["population_id"])

    if manifest.get("synthetic_fixture") and activate_measured:
        fail("PLACEHOLDER_ACTIVATION_FORBIDDEN", "synthetic generation cannot be activated")

    binding, binding_by_context, cells_by_context = _load_generation_parts(generation_root, manifest)
    binding_meta = next(item for item in manifest["artifacts"] if item["role"] == "BINDING")
    binding_sha256 = binding_meta["sha256"]
    manifest_sha256 = validation["manifest_sha256"]

    env_slot = manifest["environment_identity"]
    params_slot = manifest["generation_parameters"]
    environment_document = load_json(generation_root / env_slot["path"])
    parameter_document = load_json(generation_root / params_slot["path"])
    plan_by_id = {row["context_id"]: row for row in plan["contexts"]}

    # Build the complete replacement plan before cloning/changing the repository.
    prepared: list[dict[str, Any]] = []
    pfc_to_context: dict[str, str] = {}
    for context_id in manifest["expected_context_ids"]:
        plan_row = plan_by_id.get(context_id)
        if plan_row is None:
            fail("WRONG_CONTEXT_ID", context_id)
        family = plan_row["family"]
        if family not in SUPPORTED_FAMILIES:
            fail("UNSUPPORTED_REPOSITORY_FAMILY", family)
        p50 = (plan_row.get("effective_stack_observed") or {}).get("p50_bb")
        if not isinstance(p50, (int, float)) or float(p50) <= 0:
            fail("MISSING_STACK_REPRESENTATIVE", context_id)

        pfc_id = repository_preflop_context_id(context_id)
        previous = pfc_to_context.get(pfc_id)
        if previous is not None and previous != context_id:
            fail("PFC_ID_COLLISION", f"{previous} and {context_id} -> {pfc_id}")
        pfc_to_context[pfc_id] = context_id

        repo_context = {
            "population_id": manifest["population_id"],
            "table_size": 6,
            "position": plan_row["hero_position"],
            "effective_stack_bb": round(float(p50), 3),
            "spot": SUPPORTED_FAMILIES[family],
            "preflop_context_id": pfc_id,
        }
        repo_key = repository_context_key(repo_context)
        cells = cells_by_context[context_id]
        if len(cells) != 169:
            fail("HAND_CLASS_COUNT_MISMATCH", f"{context_id}: {len(cells)}")
        cells_by_hand = {cell["hand_class"]: cell for cell in cells}
        if list(sorted(cells_by_hand)) and set(cells_by_hand) != set(CANONICAL_HAND_CLASSES):
            fail("HAND_CLASS_SET_MISMATCH", context_id)

        binding_row = binding_by_context[context_id]
        active_hands: dict[str, Any] = {}
        metadata_by_hand: dict[str, Any] = {}
        for hand in CANONICAL_HAND_CLASSES:
            cell = cells_by_hand[hand]
            is_placeholder = (cell.get("action") or {}).get("status") == "SYNTHETIC_PLACEHOLDER"
            active = False
            if is_placeholder:
                if (cell.get("action") or {}).get("value") is not None:
                    fail("PLACEHOLDER_ACTIVATION_FORBIDDEN", f"{context_id} {hand} action")
            elif activate_measured:
                active_hands[hand] = _map_measured_strategy(cell)
                active = True
            metadata_by_hand[hand] = _cell_metadata(cell, active=active)

        activation_state = ACTIVE_STATE if active_hands else PLACEHOLDER_STATE
        provenance = {
            "schema": IMPORT_SCHEMA,
            "activation_state": activation_state,
            "replacement_mode": REPLACEMENT_MODE,
            "exact_lookup": EXACT_LOOKUP,
            "nearest_context_allowed": False,
            "fallback_states": FALLBACK_STATES,
            "population_id": manifest["population_id"],
            "generation_id": manifest["generation_id"],
            "candidate_id": manifest["candidate_id"],
            "manifest_sha256": manifest_sha256,
            "binding_sha256": binding_sha256,
            "source_plan_sha256": manifest["source_plan_sha256"],
            "source_train_audit_sha256": manifest["source_train_audit_sha256"],
            "generator_version": manifest["generator_version"],
            "code_sha": manifest["code_sha"],
            "environment_identity": {
                "slot_id": env_slot["slot_id"],
                "sha256": env_slot["sha256"],
                "document": environment_document,
            },
            "generation_parameters": {
                "slot_id": params_slot["slot_id"],
                "sha256": params_slot["sha256"],
                "document": parameter_document,
            },
            "exact_context": _context_dimensions(plan_row),
            "repository_projection": {
                "context_key": repo_key,
                "preflop_context_id": pfc_id,
                "spot": repo_context["spot"],
                "representative_effective_stack_bb": repo_context["effective_stack_bb"],
                "stack_representation": "SOURCE_PLAN_OBSERVED_P50_ONLY",
            },
            "source_shard": {
                "shard_id": binding_row["shard_id"],
                "path": binding_row["artifact_path"],
                "sha256": binding_row["artifact_sha256"],
            },
            "hand_class_order_id": HAND_ORDER_ID,
            "hand_class_count": 169,
            "active_hand_count": len(active_hands),
            "cells": metadata_by_hand,
        }
        prepared.append({
            "context_id": context_id,
            "repository_context": repo_context,
            "repository_key": repo_key,
            "layer": {
                "kind": "calculated",
                "version": _layer_version(manifest, manifest_sha256),
                "provenance": provenance,
                "hands": active_hands,
            },
        })

    # Immutable historical-generation guard. Same generation_id with different
    # content is never accepted; a correction must have a new generation_id.
    for node in (base_repository.get("contexts") or {}).values():
        provenance = ((node.get("layers") or {}).get("calculated") or {}).get("provenance")
        if not isinstance(provenance, Mapping) or provenance.get("schema") != IMPORT_SCHEMA:
            continue
        if provenance.get("generation_id") == manifest["generation_id"] and provenance.get("manifest_sha256") != manifest_sha256:
            fail("IMMUTABLE_GENERATION_CHANGED", "same generation_id is already present with a different manifest hash")

    # Atomic transformation: all validation/preparation above succeeds before the
    # deep-cloned output is modified. The caller's base object remains untouched.
    output = copy.deepcopy(base_repository)
    if not output.get("defaults"):
        output["defaults"] = {"population_id": manifest["population_id"], "table_size": 6, "effective_stack_bb": 100}
    elif not output["defaults"].get("population_id"):
        output["defaults"]["population_id"] = manifest["population_id"]

    replaced_generation_ids: set[str] = set()
    for node in output["contexts"].values():
        calculated = node["layers"]["calculated"]
        prov = calculated.get("provenance")
        if isinstance(prov, Mapping) and prov.get("schema") == IMPORT_SCHEMA and prov.get("generation_id"):
            replaced_generation_ids.add(str(prov["generation_id"]))
        node["layers"]["calculated"] = _empty_layer("calculated")

    for item in prepared:
        key = item["repository_key"]
        if key not in output["contexts"]:
            output["contexts"][key] = {
                "context": copy.deepcopy(item["repository_context"]),
                "layers": {
                    "personal": _empty_layer("personal"),
                    "calculated": _empty_layer("calculated"),
                },
            }
        else:
            existing_context = output["contexts"][key].get("context")
            if existing_context != item["repository_context"]:
                fail("REPOSITORY_CONTEXT_COLLISION", key)
        output["contexts"][key]["layers"]["calculated"] = copy.deepcopy(item["layer"])

    receipt = {
        "schema": IMPORT_SCHEMA,
        "repository_schema": REPOSITORY_SCHEMA,
        "population_id": manifest["population_id"],
        "generation_id": manifest["generation_id"],
        "candidate_id": manifest["candidate_id"],
        "manifest_sha256": manifest_sha256,
        "binding_sha256": binding_sha256,
        "source_plan_sha256": manifest["source_plan_sha256"],
        "source_train_audit_sha256": manifest["source_train_audit_sha256"],
        "environment_identity": copy.deepcopy(env_slot),
        "generation_parameters": copy.deepcopy(params_slot),
        "generator_version": manifest["generator_version"],
        "code_sha": manifest["code_sha"],
        "replacement_mode": REPLACEMENT_MODE,
        "exact_lookup": EXACT_LOOKUP,
        "nearest_context_allowed": False,
        "fallback_states": FALLBACK_STATES,
        "synthetic_fixture": bool(manifest.get("synthetic_fixture")),
        "activation_state": ACTIVE_STATE if activate_measured and not manifest.get("synthetic_fixture") else PLACEHOLDER_STATE,
        "context_count": len(prepared),
        "expected_hand_classes_per_context": 169,
        "active_hand_count": sum(len(item["layer"]["hands"]) for item in prepared),
        "replaced_generation_ids": sorted(replaced_generation_ids),
        "contexts": [
            {
                "context_id": item["context_id"],
                "repository_key": item["repository_key"],
                "preflop_context_id": item["repository_context"]["preflop_context_id"],
                "family": item["layer"]["provenance"]["exact_context"]["family"],
                "hero_position": item["layer"]["provenance"]["exact_context"]["hero_position"],
                "opener_position": item["layer"]["provenance"]["exact_context"]["opener_position"],
                "last_aggressor_position": item["layer"]["provenance"]["exact_context"]["last_aggressor_position"],
                "caller_count": item["layer"]["provenance"]["exact_context"]["caller_count"],
                "limper_count": item["layer"]["provenance"]["exact_context"]["limper_count"],
                "jam_state": item["layer"]["provenance"]["exact_context"]["jam_state"],
                "stack_bucket": item["layer"]["provenance"]["exact_context"]["stack_bucket"],
                "source_shard_sha256": item["layer"]["provenance"]["source_shard"]["sha256"],
                "hand_class_count": 169,
                "active_hand_count": len(item["layer"]["hands"]),
            }
            for item in prepared
        ],
        "repository_sha256": hashlib.sha256(canonical_json_bytes(output)).hexdigest(),
        "scientific_effect": "NONE_INTEGRATION_CONTRACT_ONLY" if manifest.get("synthetic_fixture") else "INTEGRATION_ONLY",
    }
    return output, receipt


def _atomic_write_json(path: Path, value: object) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(value)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generation-root", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--base-repository", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt-output", type=Path)
    parser.add_argument("--allow-synthetic", action="store_true")
    parser.add_argument("--activate-measured", action="store_true")
    args = parser.parse_args()

    try:
        base_repository = load_json(args.base_repository)
        repository, receipt = import_generation(
            args.generation_root,
            args.plan,
            base_repository,
            allow_synthetic=args.allow_synthetic,
            activate_measured=args.activate_measured,
        )
        _atomic_write_json(args.output, repository)
        if args.receipt_output is not None:
            _atomic_write_json(args.receipt_output, receipt)
    except ContractError as exc:
        print(json.dumps({"ok": False, "error": {"code": exc.code, "message": exc.message}}, indent=2, sort_keys=True))
        return 1

    print(json.dumps({
        "ok": True,
        "repository": str(args.output),
        "repository_sha256": receipt["repository_sha256"],
        "receipt": str(args.receipt_output) if args.receipt_output else None,
        "generation_id": receipt["generation_id"],
        "contexts": receipt["context_count"],
        "active_hands": receipt["active_hand_count"],
        "activation_state": receipt["activation_state"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

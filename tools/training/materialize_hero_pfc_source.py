#!/usr/bin/env python3
"""Persist one enriched #107 context as repository + reusable PFC binding.

The expensive EV run and its PFC enrichment are inputs. This step performs no
rollout and no scientific selection: it only extracts the editor-compatible
repository from the verified candidate and binds it to the exact canonical PFC
that produced the decisions. The output binding intentionally uses the existing
``poker-hero-range-pfc-binding/v1`` schema so old BTN evidence and newly
generated contexts can be merged by the same downstream tool.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

RUN_SCHEMA = "poker-hero-range-decision-run/v1"
CANDIDATE_SCHEMA = "poker-hero-calculated-range-candidate/v1"
REPOSITORY_SCHEMA = "poker-hero-range-repository/v1"
BINDING_SCHEMA = "poker-hero-range-pfc-binding/v1"
PFC_SCHEMA = "poker-preflop-context/v1"


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def materialize(
    run: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    run_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if run.get("schema") != RUN_SCHEMA:
        raise ValueError(f"expected {RUN_SCHEMA}")
    if candidate.get("schema") != CANDIDATE_SCHEMA:
        raise ValueError(f"expected {CANDIDATE_SCHEMA}")
    if candidate.get("promotion_authorized") is not False:
        raise ValueError("candidate must remain non-promoted")
    canonical = dict(run.get("canonical_preflop_context") or {})
    if canonical.get("schema") != PFC_SCHEMA:
        raise ValueError("enriched run is missing canonical preflop context")
    pfc_id = str(canonical.get("context_id") or "")
    if not pfc_id.startswith("PFC_"):
        raise ValueError("invalid canonical preflop context id")
    if str(run.get("context_id") or "") != pfc_id:
        raise ValueError("run context_id differs from canonical PFC id")

    repository = json.loads(json.dumps(candidate.get("repository") or {}))
    if repository.get("schema") != REPOSITORY_SCHEMA:
        raise ValueError("candidate repository schema mismatch")
    contexts = list((repository.get("contexts") or {}).values())
    if len(contexts) != 1:
        raise ValueError("one source materialization must contain exactly one Hero context")
    context = dict(contexts[0].get("context") or {})
    if str(context.get("preflop_context_id") or "") != pfc_id:
        raise ValueError("repository source context does not match enriched run PFC")
    if str(context.get("population_id") or "") != str(run.get("population_id") or ""):
        raise ValueError("repository/run population mismatch")

    repository_bytes = canonical_json_bytes(repository)
    repository_sha = sha256_bytes(repository_bytes)
    coverage = dict(run.get("coverage") or {})
    unsupported = list(run.get("unsupported") or [])
    completed = int(coverage.get("completed") or len(run.get("rows") or []))
    requested = int(coverage.get("requested") or (completed + len(unsupported)))
    binding = {
        "schema": BINDING_SCHEMA,
        "issue": 107,
        "run_id": str(run_id),
        "source_run_id": str(run.get("version") or run_id),
        "status": "EXPERIMENTAL",
        "promotion_authorized": False,
        "population_id": str(run.get("population_id") or ""),
        "preflop_context_id": pfc_id,
        "canonical_preflop_context": canonical,
        "legacy_context_id": str(run.get("legacy_context_id") or ""),
        "coverage": {
            "requested": requested,
            "supported": completed,
            "unsupported": len(unsupported),
            "accounted": completed + len(unsupported),
        },
        "artifact_sha256": {
            "hero_range_repository_pfc": repository_sha,
        },
        "identity_transform": dict((run.get("provenance") or {}).get("context_identity") or {}),
        "selection_boundary": {
            "candidate_status": "EXPERIMENTAL",
            "validation_consumed": False,
            "test_consumed": False,
        },
        "handoff": {
            "supported_policy": "SOURCE_PFC_FOR_EXPLICIT_PFPC_BINDING_ONLY",
            "nearest_context_substitution": False,
        },
    }
    if binding["coverage"]["accounted"] != requested:
        raise ValueError("source run does not account for every requested hand class")
    return repository, binding


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--repository-out", type=Path, required=True)
    parser.add_argument("--binding-out", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()

    repository, binding = materialize(
        load_json(args.run),
        load_json(args.candidate),
        run_id=args.run_id,
    )
    args.repository_out.parent.mkdir(parents=True, exist_ok=True)
    repository_bytes = canonical_json_bytes(repository)
    args.repository_out.write_bytes(repository_bytes)
    actual_sha = sha256_bytes(repository_bytes)
    expected_sha = binding["artifact_sha256"]["hero_range_repository_pfc"]
    if actual_sha != expected_sha:
        raise AssertionError("repository serialization hash drifted")
    args.binding_out.parent.mkdir(parents=True, exist_ok=True)
    args.binding_out.write_bytes(canonical_json_bytes(binding))
    print(json.dumps({
        "preflop_context_id": binding["preflop_context_id"],
        "coverage": binding["coverage"],
        "repository_sha256": actual_sha,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

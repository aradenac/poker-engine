#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.populations.registry import resolve_population
from tools.simulation.model_b_conditioned_runtime import ConditionedModelBEnvironment
from tools.simulation.model_b_runtime import ModelBEnvironment

DEPENDENCY_FILES = ("profiles.json", "preflop_ranges.json")


def dependency_fingerprints(fingerprints: dict[str, str]) -> dict[str, str]:
    return {name: str(fingerprints[name]) for name in DEPENDENCY_FILES}


def retarget_manifest(manifest: dict, source_env: ModelBEnvironment, target_env: ModelBEnvironment) -> dict:
    if manifest.get("schema") != "sequential-arena-scenario-manifest/v2":
        raise ValueError("unexpected scenario manifest schema")
    population_id = str(manifest.get("population_id") or "")
    if not population_id:
        raise ValueError("scenario manifest has no population_id")
    if source_env.population_id != population_id:
        raise ValueError(
            f"source Model B population mismatch: manifest={population_id} source={source_env.population_id!r}"
        )
    if target_env.population_id != population_id:
        raise ValueError(
            f"target Model B population mismatch: manifest={population_id} target={target_env.population_id!r}"
        )

    source_fp = source_env.artifact_fingerprints()
    target_fp = target_env.artifact_fingerprints()
    if (manifest.get("model_b") or {}).get("artifact_sha256") != source_fp:
        raise ValueError("source manifest does not match source Model B")
    source_deps = dependency_fingerprints(source_fp)
    target_deps = dependency_fingerprints(target_fp)
    if source_deps != target_deps:
        raise ValueError("scenario materialization dependencies differ")

    out = copy.deepcopy(manifest)
    out["model_b"] = {
        "alias": target_env.alias,
        "model_dir": target_env.model_dir.as_posix(),
        "artifact_sha256": target_fp,
    }
    out["scenario_materialization_provenance"] = {
        "retargeted": True,
        "population_id": population_id,
        "source_alias": source_env.alias,
        "target_alias": target_env.alias,
        "dependency_files": list(DEPENDENCY_FILES),
        "dependency_sha256": source_deps,
        "scenario_fingerprint_unchanged": True,
    }
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--population", required=True)
    p.add_argument("--manifest", required=True)
    p.add_argument("--source-model-dir", required=True)
    p.add_argument("--target-model-dir", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    resolve_population(ROOT, args.population)
    source = ModelBEnvironment(
        Path(args.source_model_dir), alias="independent_model_b_v2", population_id=args.population
    )
    target = ConditionedModelBEnvironment(
        Path(args.target_model_dir),
        alias="independent_model_b_v3_response_conditioned_candidate",
        population_id=args.population,
    )
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    if manifest.get("population_id") != args.population:
        raise ValueError(
            f"scenario manifest population mismatch: expected {args.population}, got {manifest.get('population_id')!r}"
        )
    out = retarget_manifest(manifest, source, target)
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(out["scenario_fingerprint_sha256"])


if __name__ == "__main__":
    main()

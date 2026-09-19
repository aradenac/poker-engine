#!/usr/bin/env python3
"""Reproduce and validate the #370 content-addressed pack-engine artifact.

This tool is read-only by default. It consumes #360 persisted evidence, verifies
that the certified source subset has not drifted, closes all runtime dependencies,
reconstructs the deterministic bundle byte-for-byte and validates its immutable
content address. It never publishes, activates or promotes anything.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / "training/runs/20260919_pack_engine_artifact"
BUILD_SPEC_PATH = RUN_DIR / "BUILD_SPEC.json"
SOURCE_PROOF_PATH = ROOT / "training/runs/20260919_pack_runtime_compatibility/SOURCE_PROVENANCE.json"
ENGINE_CANDIDATE_PATH = ROOT / "training/runs/20260919_pack_runtime_compatibility/ENGINE_CANDIDATE.json"
EXPECTED_SOURCE_PROOF_SHA = "aefbd8fd76b2fe3ff6c31d290075be6eaa2aec215bd76444ca4cb8f3d1be8ff2"
EXPECTED_ENGINE_CANDIDATE_SHA = "8a90aac3c659feeb7973515961938b742038b05c904a87a1ffab67203599c8f3"
EXPECTED_BLOCKER = "NO_FRESH_DISTRIBUTABLE_ENGINE_ARTIFACT"
TARGET = "pokerstars_nlhe_100-200_zoom_play_6max_v1"
REQUIRE_RE = re.compile(r"""require\(\s*(['"])([^'"]+)\1\s*\)""")

class EngineArtifactError(RuntimeError):
    pass

def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EngineArtifactError(f"cannot load {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise EngineArtifactError(f"expected JSON object: {path}")
    return value

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def git_blob(path: Path, *, root: Path = ROOT) -> str:
    return subprocess.check_output(
        ["git", "hash-object", str(path.relative_to(root))],
        cwd=root,
        text=True,
    ).strip()

def compact_sha256(value: Any) -> str:
    payload = json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()

def resolve_relative_require(source_path: str, request: str) -> str | None:
    if not request.startswith("."):
        return None
    base = PurePosixPath(source_path).parent
    return str(PurePosixPath(base, request))

def normalized_repo_rel(source_path: str, request: str) -> str:
    base = PurePosixPath(source_path).parent
    parts: list[str] = []
    for part in PurePosixPath(base, request).parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                raise EngineArtifactError(f"runtime dependency escapes repository: {source_path} -> {request}")
            parts.pop()
        else:
            parts.append(part)
    return "/".join(parts)

def validate_source_closure(*, root: Path = ROOT) -> dict[str, Any]:
    spec = _load(root / BUILD_SPEC_PATH.relative_to(ROOT))
    proof = _load(root / SOURCE_PROOF_PATH.relative_to(ROOT))
    candidate = _load(root / ENGINE_CANDIDATE_PATH.relative_to(ROOT))

    if sha256_file(root / SOURCE_PROOF_PATH.relative_to(ROOT)) != EXPECTED_SOURCE_PROOF_SHA:
        raise EngineArtifactError("#360 SOURCE_PROVENANCE.json hash drift")
    if sha256_file(root / ENGINE_CANDIDATE_PATH.relative_to(ROOT)) != EXPECTED_ENGINE_CANDIDATE_SHA:
        raise EngineArtifactError("#360 ENGINE_CANDIDATE.json hash drift")
    if proof.get("population_id") != TARGET or spec.get("target_population_id") != TARGET:
        raise EngineArtifactError("target population mismatch")
    if candidate.get("source_set_sha256") != spec.get("source_subset_sha256"):
        raise EngineArtifactError("source subset identity mismatch")
    if (candidate.get("blocker") or {}).get("code") != EXPECTED_BLOCKER:
        raise EngineArtifactError("#360 engine blocker changed")
    if (proof.get("generic_engine_core") or {}).get("status") != "POPULATION_AGNOSTIC_SOURCE_SUBSET_CONFIRMED":
        raise EngineArtifactError("#360 population-agnostic source proof missing")

    proof_rows = (proof.get("generic_engine_core") or {}).get("files") or []
    expected_rows = spec.get("source_files") or []
    proof_core = [
        {"path": r.get("path"), "git_blob_sha": r.get("git_blob_sha"), "sha256": r.get("sha256")}
        for r in proof_rows
    ]
    if proof_core != expected_rows:
        raise EngineArtifactError("build source rows differ from #360 proof")
    if compact_sha256(proof_core) != spec.get("source_subset_sha256"):
        raise EngineArtifactError("source subset aggregate SHA mismatch")

    closure_rows = list(expected_rows)
    runtime = spec.get("runtime_dependency_closure") or {}
    closure_rows.extend(runtime.get("additional_files") or [])
    closure_paths = {str(r.get("path")) for r in closure_rows}
    declared_external = set(runtime.get("external_dependencies") or [])
    forbidden = list((proof.get("generic_engine_core") or {}).get("forbidden_markers") or [])

    verified: list[dict[str, Any]] = []
    dependency_edges: list[dict[str, str]] = []
    for row in closure_rows:
        rel = str(row.get("path") or "")
        path = root / rel
        if not path.is_file():
            raise EngineArtifactError(f"runtime source missing: {rel}")
        actual_sha = sha256_file(path)
        if actual_sha != row.get("sha256"):
            raise EngineArtifactError(f"source SHA-256 drift: {rel}")
        actual_blob = git_blob(path, root=root)
        if actual_blob != row.get("git_blob_sha"):
            raise EngineArtifactError(f"source git-blob drift: {rel}")
        text = path.read_text(encoding="utf-8")
        hits = [marker for marker in forbidden if marker in text]
        if hits:
            raise EngineArtifactError(f"forbidden population/legacy marker in {rel}: {hits}")
        for match in REQUIRE_RE.finditer(text):
            request = match.group(2)
            if request.startswith("."):
                target = normalized_repo_rel(rel, request)
                dependency_edges.append({"source": rel, "request": request, "target": target})
                if target not in closure_paths:
                    raise EngineArtifactError(f"undeclared runtime dependency: {rel} -> {target}")
            elif request not in declared_external:
                raise EngineArtifactError(f"undeclared external runtime dependency: {rel} -> {request}")
        verified.append({"path": rel, "sha256": actual_sha, "git_blob_sha": actual_blob})

    return {
        "spec": spec,
        "proof": proof,
        "candidate": candidate,
        "verified_files": verified,
        "dependency_edges": dependency_edges,
    }

def render_bundle(*, root: Path = ROOT) -> str:
    checked = validate_source_closure(root=root)
    spec = checked["spec"]
    source_commit = str(spec["source_commit"])
    subset_sha = str(spec["source_subset_sha256"])
    rows = list((spec.get("runtime_dependency_closure") or {}).get("additional_files") or []) + list(spec.get("source_files") or [])
    globals_ = [
        "PokerLeakAnalyzer",
        "PokerNlheGameState",
        "PokerPreflopContract",
        "PokerPreflopDecision",
        "PokerPreflopSearch",
        "PokerPreflopGuidance",
        "PokerPreflopDecisionAdapter",
        "PokerHeroPreflopAlternatives",
        "PokerIsoSizingDiagnostics",
    ]
    out = (
        "/*! poker-pack-engine-runtime/v1\n"
        " * issue: #370\n"
        " * source-proof: #360\n"
        f" * source-commit: {source_commit}\n"
        f" * source-subset-sha256: {subset_sha}\n"
        " * legacy-mixed-bytes-reused: false\n"
        " * deterministic: true\n"
        " */\n"
        "(function(root){\n"
        "  'use strict';\n"
        "  (function(){\n"
        "    const module=undefined;\n"
        "    const require=undefined;\n"
    )
    for row in rows:
        rel = str(row["path"])
        text = (root / rel).read_text(encoding="utf-8")
        out += (
            f"\n/* BEGIN {rel} | blob {row['git_blob_sha']} | sha256 {row['sha256']} */\n"
            + text
            + f"\n/* END {rel} */\n"
        )
    out += (
        "  })();\n"
        "  const names=" + json.dumps(globals_, separators=(",", ":")) + ";\n"
        "  const modules={};\n"
        "  for(const name of names){\n"
        "    if(!root||!root[name])throw new Error('pack-engine module missing after materialization: '+name);\n"
        "    modules[name]=root[name];\n"
        "  }\n"
        "  const api=Object.freeze({\n"
        "    schema:'poker-pack-engine-artifact/v1',\n"
        "    artifact_class:'DISTRIBUTABLE_POPULATION_AGNOSTIC_ENGINE_CORE',\n"
        f"    build_identity:'source-set:{subset_sha}',\n"
        f"    source_commit:'{source_commit}',\n"
        f"    source_subset_sha256:'{subset_sha}',\n"
        "    population_agnostic:true,\n"
        "    legacy_mixed_bytes_reused:false,\n"
        "    runtime_dependency_closure:'SELF_CONTAINED',\n"
        "    modules:Object.freeze(modules)\n"
        "  });\n"
        "  root.PokerPackEngineArtifact=api;\n"
        "  if(typeof module==='object'&&module.exports)module.exports=api;\n"
        "})(typeof globalThis!=='undefined'?globalThis:this);\n"
    )
    return out

def validate_materialized_artifact(*, root: Path = ROOT) -> dict[str, Any]:
    checked = validate_source_closure(root=root)
    spec = checked["spec"]
    identity = spec.get("identity") or {}
    rel = str(identity.get("artifact_path") or "")
    expected_sha = str(identity.get("sha256") or "")
    artifact = root / rel
    if not artifact.is_file():
        raise EngineArtifactError(f"materialized artifact missing: {rel}")
    actual_sha = sha256_file(artifact)
    if actual_sha != expected_sha:
        raise EngineArtifactError(f"materialized artifact hash mismatch: {actual_sha} != {expected_sha}")
    if expected_sha not in artifact.name:
        raise EngineArtifactError("artifact path is not content-addressed by full SHA-256")
    rendered = render_bundle(root=root)
    if artifact.read_text(encoding="utf-8") != rendered:
        raise EngineArtifactError("materialized artifact is not byte-for-byte reproducible")
    if hashlib.sha256(rendered.encode("utf-8")).hexdigest() != expected_sha:
        raise EngineArtifactError("rendered artifact SHA-256 differs from declared identity")
    if "MIXED_ZOOM_REGULAR" in rendered or "legacy_pokerstars_nlhe_100-200_play_6max_mixed_v1" in rendered:
        raise EngineArtifactError("legacy lineage marker leaked into artifact")
    return {
        "artifact_path": rel,
        "artifact_sha256": actual_sha,
        "verified_source_files": len(checked["verified_files"]),
        "dependency_edges": checked["dependency_edges"],
        "runtime_dependency_closure": "SELF_CONTAINED",
        "population_agnostic": True,
        "legacy_relabelled": False,
    }

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="validate the committed materialized artifact")
    args = parser.parse_args()
    result = validate_materialized_artifact()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

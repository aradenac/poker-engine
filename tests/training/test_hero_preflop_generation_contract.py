#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import tempfile
from pathlib import Path


from tools.training.validate_hero_preflop_generation import (
    ContractError,
    canonical_json_bytes,
    enforce_immutability,
    resolve_fallback,
    sha256_path,
    validate_generation,
)

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "analysis/hero_preflop_generation_plan.json"
FIXTURE = ROOT / "tests/fixtures/hero_preflop_generation/valid"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def expect_code(root: Path, code: str) -> None:
    try:
        validate_generation(root, PLAN, allow_synthetic=True)
    except ContractError as exc:
        assert exc.code == code, (exc.code, exc.message)
    else:
        raise AssertionError(f"expected {code}")


def copy_fixture() -> tuple[tempfile.TemporaryDirectory, Path]:
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name) / "generation"
    shutil.copytree(FIXTURE, root)
    return tmp, root


def artifact(manifest: dict, role: str) -> dict:
    rows = [row for row in manifest["artifacts"] if row["role"] == role]
    assert len(rows) == 1
    return rows[0]


def rehash_binding(root: Path) -> None:
    manifest = load(root / "manifest.json")
    item = artifact(manifest, "BINDING")
    item["sha256"] = sha256_path(root / item["path"])
    write_json(root / "manifest.json", manifest)


def rehash_shard(root: Path, *, update_cell_count: bool = True, update_context_ids: bool = True) -> None:
    manifest = load(root / "manifest.json")
    shard_item = artifact(manifest, "STRATEGY_SHARD")
    shard = load(root / shard_item["path"])
    shard_hash = sha256_path(root / shard_item["path"])
    shard_item["sha256"] = shard_hash
    if update_cell_count:
        shard_item["cell_count"] = len(shard["cells"])
    if update_context_ids:
        shard_item["context_ids"] = sorted({cell["context_id"] for cell in shard["cells"]})
    binding = load(root / "binding.json")
    for row in binding["bindings"]:
        if row["artifact_path"] == shard_item["path"]:
            row["artifact_sha256"] = shard_hash
    write_json(root / "binding.json", binding)
    bind_item = artifact(manifest, "BINDING")
    bind_item["sha256"] = sha256_path(root / "binding.json")
    write_json(root / "manifest.json", manifest)


def test_valid_synthetic_artifact_is_complete_and_fail_closed() -> None:
    report = validate_generation(FIXTURE, PLAN, allow_synthetic=True)
    assert report["valid"] is True
    assert report["contexts"] == 2
    assert report["hand_classes_per_context"] == 169
    assert report["cells"] == 338
    assert report["shards"] == 1
    assert report["nearest_context_allowed"] is False
    assert report["scientific_effect"] == "NONE_CONTRACT_ONLY"


def test_synthetic_fixture_requires_explicit_opt_in() -> None:
    try:
        validate_generation(FIXTURE, PLAN)
    except ContractError as exc:
        assert exc.code == "SYNTHETIC_FIXTURE_FORBIDDEN"
    else:
        raise AssertionError("synthetic fixture must fail closed without opt-in")


def test_missing_class_detected_even_when_hashes_are_rebound() -> None:
    tmp, root = copy_fixture()
    try:
        shard = load(root / "shards/shard-001.json")
        shard["cells"].pop()
        write_json(root / "shards/shard-001.json", shard)
        rehash_shard(root)
        manifest = load(root / "manifest.json")
        manifest["completeness"]["actual_cells"] = len(shard["cells"])
        write_json(root / "manifest.json", manifest)
        expect_code(root, "MISSING_HAND_CLASS")
    finally:
        tmp.cleanup()


def test_duplicate_class_detected() -> None:
    tmp, root = copy_fixture()
    try:
        shard = load(root / "shards/shard-001.json")
        shard["cells"].append(copy.deepcopy(shard["cells"][0]))
        write_json(root / "shards/shard-001.json", shard)
        rehash_shard(root)
        manifest = load(root / "manifest.json")
        manifest["completeness"]["actual_cells"] = len(shard["cells"])
        write_json(root / "manifest.json", manifest)
        expect_code(root, "DUPLICATE_HAND_CLASS")
    finally:
        tmp.cleanup()


def test_context_dimension_mismatch_detected() -> None:
    tmp, root = copy_fixture()
    try:
        shard = load(root / "shards/shard-001.json")
        shard["cells"][0]["family"] = "SYNTHETIC_WRONG_FAMILY"
        write_json(root / "shards/shard-001.json", shard)
        rehash_shard(root)
        expect_code(root, "CONTEXT_MISMATCH")
    finally:
        tmp.cleanup()


def test_wrong_context_id_detected() -> None:
    tmp, root = copy_fixture()
    try:
        shard = load(root / "shards/shard-001.json")
        shard["cells"][0]["context_id"] = "pfgen:v1:DOES_NOT_EXIST"
        write_json(root / "shards/shard-001.json", shard)
        rehash_shard(root)
        expect_code(root, "WRONG_CONTEXT_ID")
    finally:
        tmp.cleanup()


def test_population_mismatch_detected() -> None:
    tmp, root = copy_fixture()
    try:
        shard = load(root / "shards/shard-001.json")
        shard["cells"][0]["population_id"] = "wrong_population"
        write_json(root / "shards/shard-001.json", shard)
        rehash_shard(root)
        expect_code(root, "POPULATION_MISMATCH")
    finally:
        tmp.cleanup()


def test_stack_bucket_mismatch_detected() -> None:
    tmp, root = copy_fixture()
    try:
        shard = load(root / "shards/shard-001.json")
        shard["cells"][0]["stack_bucket"] = "B0_LE_P10"
        write_json(root / "shards/shard-001.json", shard)
        rehash_shard(root)
        expect_code(root, "STACK_BUCKET_MISMATCH")
    finally:
        tmp.cleanup()


def test_hash_mismatch_detected_before_consumption() -> None:
    tmp, root = copy_fixture()
    try:
        path = root / "shards/shard-001.json"
        path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
        expect_code(root, "HASH_MISMATCH")
    finally:
        tmp.cleanup()


def test_incomplete_shard_detected() -> None:
    tmp, root = copy_fixture()
    try:
        shard = load(root / "shards/shard-001.json")
        shard["cells"].pop()
        write_json(root / "shards/shard-001.json", shard)
        rehash_shard(root, update_cell_count=False)
        expect_code(root, "INCOMPLETE_SHARD")
    finally:
        tmp.cleanup()


def test_wrong_generation_detected() -> None:
    tmp, root = copy_fixture()
    try:
        shard = load(root / "shards/shard-001.json")
        shard["generation_id"] = "SYNTHETIC_OTHER_GENERATION"
        write_json(root / "shards/shard-001.json", shard)
        rehash_shard(root)
        expect_code(root, "WRONG_GENERATION")
    finally:
        tmp.cleanup()


def test_incomplete_binding_detected() -> None:
    tmp, root = copy_fixture()
    try:
        binding = load(root / "binding.json")
        binding["bindings"].pop()
        write_json(root / "binding.json", binding)
        rehash_binding(root)
        expect_code(root, "BINDING_INCOMPLETE")
    finally:
        tmp.cleanup()


def test_nearest_context_is_never_selected() -> None:
    manifest = load(FIXTURE / "manifest.json")
    binding = load(FIXTURE / "binding.json")
    assert manifest["fallback_contract"]["nearest_context_allowed"] is False
    exact = binding["bindings"][0]["context_id"]
    assert resolve_fallback(binding, exact) == "EXACT_GENERATED"
    assert resolve_fallback(binding, exact + ":nearby") == "EXACT_UNAVAILABLE"
    assert resolve_fallback(binding, "INCUMBENT_EXACT", incumbent_exact_context_ids={"INCUMBENT_EXACT"}) == "EXACT_INCUMBENT_FALLBACK"


def test_manifest_and_hash_serialization_are_deterministic() -> None:
    manifest = load(FIXTURE / "manifest.json")
    reordered = dict(reversed(list(manifest.items())))
    assert canonical_json_bytes(manifest) == canonical_json_bytes(reordered)
    assert hashlib.sha256(canonical_json_bytes(manifest)).hexdigest() == hashlib.sha256(canonical_json_bytes(reordered)).hexdigest()


def test_finalized_generation_is_immutable_and_correction_requires_new_generation_id() -> None:
    manifest = load(FIXTURE / "manifest.json")
    manifest["completeness"]["state"] = "FINALIZED"
    manifest_sha = hashlib.sha256(canonical_json_bytes(manifest)).hexdigest()
    enforce_immutability(manifest, manifest_sha, {manifest["generation_id"]: manifest_sha})
    try:
        enforce_immutability(manifest, "0" * 64, {manifest["generation_id"]: manifest_sha})
    except ContractError as exc:
        assert exc.code == "IMMUTABLE_GENERATION_CHANGED"
    else:
        raise AssertionError("same finalized generation_id cannot change content")
    corrected = copy.deepcopy(manifest)
    corrected["generation_id"] = manifest["generation_id"] + "_CORRECTION_2"
    enforce_immutability(corrected, "0" * 64, {manifest["generation_id"]: manifest_sha})


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"hero preflop generation contract tests: {len(tests)} passed")

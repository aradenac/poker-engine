#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training.import_hero_preflop_generation import (
    IMPORT_SCHEMA,
    PLACEHOLDER_STATE,
    REPLACEMENT_MODE,
    import_generation,
    repository_preflop_context_id,
)
from tools.training.validate_hero_preflop_generation import (
    CANONICAL_HAND_CLASSES,
    ContractError,
    canonical_json_bytes,
    sha256_path,
)

PLAN = ROOT / "analysis/hero_preflop_generation_plan.json"
GENERATION = ROOT / "tests/fixtures/hero_preflop_generation/valid"
BASE = ROOT / "tests/fixtures/hero_preflop_repository_import/base_repository.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def canonical_sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def copy_generation() -> tuple[tempfile.TemporaryDirectory, Path]:
    temp = tempfile.TemporaryDirectory()
    root = Path(temp.name) / "generation"
    shutil.copytree(GENERATION, root)
    return temp, root


def manifest_artifact(manifest: dict, role: str) -> dict:
    rows = [row for row in manifest["artifacts"] if row["role"] == role]
    assert len(rows) == 1
    return rows[0]


def rehash_generation(root: Path) -> None:
    manifest = load(root / "manifest.json")
    shard_meta = manifest_artifact(manifest, "STRATEGY_SHARD")
    shard_path = root / shard_meta["path"]
    shard = load(shard_path)
    shard_meta["sha256"] = sha256_path(shard_path)
    shard_meta["cell_count"] = len(shard["cells"])
    shard_meta["context_ids"] = sorted({cell["context_id"] for cell in shard["cells"]})

    binding = load(root / "binding.json")
    for row in binding["bindings"]:
        if row["artifact_path"] == shard_meta["path"]:
            row["artifact_sha256"] = shard_meta["sha256"]
    write(root / "binding.json", binding)
    binding_meta = manifest_artifact(manifest, "BINDING")
    binding_meta["sha256"] = sha256_path(root / "binding.json")
    write(root / "manifest.json", manifest)


def expect_code(root: Path, code: str) -> None:
    base = load(BASE)
    before = canonical_sha(base)
    try:
        import_generation(root, PLAN, base, allow_synthetic=True)
    except ContractError as exc:
        assert exc.code == code, (exc.code, exc.message)
    else:
        raise AssertionError(f"expected {code}")
    assert canonical_sha(base) == before, "failed import must not mutate base repository"


def valid_import() -> tuple[dict, dict, dict]:
    base = load(BASE)
    before = copy.deepcopy(base)
    repository, receipt = import_generation(GENERATION, PLAN, base, allow_synthetic=True)
    assert base == before, "import must never mutate its input repository"
    return repository, receipt, base


def generated_layers(repository: dict) -> list[dict]:
    out = []
    for node in repository["contexts"].values():
        layer = node["layers"]["calculated"]
        if (layer.get("provenance") or {}).get("schema") == IMPORT_SCHEMA:
            out.append(layer)
    return out


def test_valid_synthetic_generation_maps_into_existing_repository_schema() -> None:
    repository, receipt, _ = valid_import()
    assert repository["schema"] == "poker-hero-range-repository/v1"
    assert receipt["schema"] == IMPORT_SCHEMA
    assert receipt["replacement_mode"] == REPLACEMENT_MODE
    assert receipt["exact_lookup"] == "EXACT_CONTEXT_ONLY"
    assert receipt["nearest_context_allowed"] is False
    assert receipt["context_count"] == 2
    assert receipt["expected_hand_classes_per_context"] == 169
    assert receipt["active_hand_count"] == 0
    assert receipt["activation_state"] == PLACEHOLDER_STATE
    assert receipt["repository_sha256"] == canonical_sha(repository)


def test_exact_169_mapping_and_placeholder_never_becomes_active() -> None:
    repository, receipt, _ = valid_import()
    layers = generated_layers(repository)
    assert len(layers) == 2
    for layer in layers:
        assert layer["hands"] == {}, "placeholder generation must not create active calculated recommendations"
        provenance = layer["provenance"]
        assert provenance["activation_state"] == PLACEHOLDER_STATE
        assert provenance["nearest_context_allowed"] is False
        assert provenance["exact_lookup"] == "EXACT_CONTEXT_ONLY"
        assert provenance["hand_class_count"] == 169
        assert list(provenance["cells"]) == list(CANONICAL_HAND_CLASSES)
        assert len(provenance["cells"]) == 169
        for hand, cell in provenance["cells"].items():
            assert hand in CANONICAL_HAND_CLASSES
            assert cell["artifact_state"] == "EXACT_GENERATED"
            assert cell["fallback_state"] == "EXACT_UNAVAILABLE"
            assert cell["active_recommendation"] is False
            assert cell["placeholder"] is True
            assert cell["action_status"] == "SYNTHETIC_PLACEHOLDER"
            assert cell["sizing_status"] == "SYNTHETIC_PLACEHOLDER"
            assert cell["ev_status"] == "SYNTHETIC_PLACEHOLDER"
    assert all(ctx["active_hand_count"] == 0 for ctx in receipt["contexts"])


def test_exact_context_identity_and_source_identity_are_preserved() -> None:
    repository, receipt, _ = valid_import()
    manifest = load(GENERATION / "manifest.json")
    binding = load(GENERATION / "binding.json")
    assert receipt["generation_id"] == manifest["generation_id"]
    assert receipt["candidate_id"] == manifest["candidate_id"]
    assert receipt["manifest_sha256"] == sha256_path(GENERATION / "manifest.json")
    assert receipt["binding_sha256"] == sha256_path(GENERATION / "binding.json")
    assert receipt["source_plan_sha256"] == manifest["source_plan_sha256"]
    assert receipt["environment_identity"] == manifest["environment_identity"]
    assert receipt["generation_parameters"] == manifest["generation_parameters"]
    binding_by_context = {row["context_id"]: row for row in binding["bindings"]}
    for row in receipt["contexts"]:
        assert row["preflop_context_id"] == repository_preflop_context_id(row["context_id"])
        assert row["source_shard_sha256"] == binding_by_context[row["context_id"]]["artifact_sha256"]
        node = repository["contexts"][row["repository_key"]]
        exact = node["layers"]["calculated"]["provenance"]["exact_context"]
        assert exact["context_id"] == row["context_id"]
        assert exact["family"] == row["family"]
        assert exact["hero_position"] == row["hero_position"]
        assert exact["opener_position"] == row["opener_position"]
        assert exact["last_aggressor_position"] == row["last_aggressor_position"]
        assert exact["caller_count"] == row["caller_count"]
        assert exact["limper_count"] == row["limper_count"]
        assert exact["jam_state"] == row["jam_state"]
        assert exact["stack_bucket"] == row["stack_bucket"]


def test_personal_layer_and_imported_source_are_preserved_and_calculated_is_replaced() -> None:
    repository, _, base = valid_import()
    assert repository["source"] == base["source"], "imported source must remain byte-semantically unchanged"
    original_key = next(iter(base["contexts"]))
    assert repository["contexts"][original_key]["layers"]["personal"] == base["contexts"][original_key]["layers"]["personal"]
    assert repository["contexts"][original_key]["layers"]["calculated"] == {
        "kind": "calculated", "version": None, "provenance": None, "hands": {}
    }, "old calculated layer must be replaced, never merged"
    assert base["contexts"][original_key]["layers"]["calculated"]["hands"]["AQs"]["actions"] == {"FOLD": 1}


def test_missing_hand_class_fails_atomically() -> None:
    temp, root = copy_generation()
    try:
        shard = load(root / "shards/shard-001.json")
        shard["cells"].pop()
        write(root / "shards/shard-001.json", shard)
        rehash_generation(root)
        manifest = load(root / "manifest.json")
        manifest["completeness"]["actual_cells"] -= 1
        write(root / "manifest.json", manifest)
        expect_code(root, "MISSING_HAND_CLASS")
    finally:
        temp.cleanup()


def test_duplicate_hand_class_fails_atomically() -> None:
    temp, root = copy_generation()
    try:
        shard = load(root / "shards/shard-001.json")
        shard["cells"].append(copy.deepcopy(shard["cells"][0]))
        write(root / "shards/shard-001.json", shard)
        rehash_generation(root)
        manifest = load(root / "manifest.json")
        manifest["completeness"]["actual_cells"] += 1
        write(root / "manifest.json", manifest)
        expect_code(root, "DUPLICATE_HAND_CLASS")
    finally:
        temp.cleanup()


def test_wrong_shard_hash_fails_atomically() -> None:
    temp, root = copy_generation()
    try:
        path = root / "shards/shard-001.json"
        path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
        expect_code(root, "HASH_MISMATCH")
    finally:
        temp.cleanup()


def test_wrong_binding_hash_fails_atomically() -> None:
    temp, root = copy_generation()
    try:
        path = root / "binding.json"
        path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
        expect_code(root, "HASH_MISMATCH")
    finally:
        temp.cleanup()


def test_generation_mismatch_fails_atomically() -> None:
    temp, root = copy_generation()
    try:
        shard = load(root / "shards/shard-001.json")
        shard["cells"][0]["generation_id"] = "OTHER_GENERATION"
        write(root / "shards/shard-001.json", shard)
        rehash_generation(root)
        expect_code(root, "WRONG_GENERATION")
    finally:
        temp.cleanup()


def test_population_mismatch_fails_atomically() -> None:
    temp, root = copy_generation()
    try:
        shard = load(root / "shards/shard-001.json")
        shard["cells"][0]["population_id"] = "other-population"
        write(root / "shards/shard-001.json", shard)
        rehash_generation(root)
        expect_code(root, "POPULATION_MISMATCH")
    finally:
        temp.cleanup()


def test_context_mismatch_fails_atomically() -> None:
    temp, root = copy_generation()
    try:
        shard = load(root / "shards/shard-001.json")
        shard["cells"][0]["family"] = "VS_RFI"
        write(root / "shards/shard-001.json", shard)
        rehash_generation(root)
        expect_code(root, "CONTEXT_MISMATCH")
    finally:
        temp.cleanup()


def test_synthetic_activation_is_explicitly_forbidden() -> None:
    base = load(BASE)
    try:
        import_generation(GENERATION, PLAN, base, allow_synthetic=True, activate_measured=True)
    except ContractError as exc:
        assert exc.code == "PLACEHOLDER_ACTIVATION_FORBIDDEN"
    else:
        raise AssertionError("synthetic placeholder fixture must never activate recommendations")


def test_no_nearest_context_substitution() -> None:
    repository, receipt, _ = valid_import()
    assert receipt["fallback_states"] == ["EXACT_GENERATED", "EXACT_INCUMBENT_FALLBACK", "EXACT_UNAVAILABLE"]
    assert receipt["nearest_context_allowed"] is False
    generated_pfc = {row["preflop_context_id"] for row in receipt["contexts"]}
    assert repository_preflop_context_id(receipt["contexts"][0]["context_id"] + ":nearby") not in generated_pfc
    for layer in generated_layers(repository):
        assert layer["provenance"]["nearest_context_allowed"] is False


def test_deterministic_repository_output_and_hash() -> None:
    first, receipt1, _ = valid_import()
    second, receipt2, _ = valid_import()
    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert receipt1["repository_sha256"] == receipt2["repository_sha256"] == canonical_sha(first)
    assert canonical_json_bytes(receipt1) == canonical_json_bytes(receipt2)


def test_round_trip_through_existing_hero_repository_module_is_stable() -> None:
    repository, receipt, _ = valid_import()
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "repository.json"
        write(path, repository)
        script = r"""
const fs=require('fs');
const H=require('./site/hero-ranges.js');
const input=JSON.parse(fs.readFileSync(process.argv[1],'utf8'));
const imported=H.importDocument(input);
H.validateRepository(imported);
const exported=H.exportDocument(imported);
process.stdout.write(JSON.stringify(exported));
"""
        result = subprocess.run(
            ["node", "-e", script, str(path)],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        roundtrip = json.loads(result.stdout)
    assert roundtrip == repository
    assert canonical_sha(roundtrip) == receipt["repository_sha256"]
    assert len(generated_layers(roundtrip)) == 2
    assert all(len(layer["provenance"]["cells"]) == 169 for layer in generated_layers(roundtrip))


def test_same_generation_id_cannot_be_mutated_in_place() -> None:
    repository, _, _ = valid_import()
    tampered = copy.deepcopy(repository)
    layer = generated_layers(tampered)[0]
    layer["provenance"]["manifest_sha256"] = "0" * 64
    try:
        import_generation(GENERATION, PLAN, tampered, allow_synthetic=True)
    except ContractError as exc:
        assert exc.code == "IMMUTABLE_GENERATION_CHANGED"
    else:
        raise AssertionError("same generation_id with different manifest hash must fail")


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
    print(f"Hero preflop generation -> repository adapter tests: {len(tests)} passed")

#!/usr/bin/env python3
"""Materialize one population-scoped baseline from its certification evidence.

A certified population must not point at a broader mixed-format source archive.
This tool reconstructs exactly the ADMISSIBLE hand-id set from the immutable
certification archives, writes a deterministic ZIP, verifies its fingerprint and
split counts, persists a content-addressed manifest, and can bind that exact
baseline into the population registry.

Existing baseline artifacts are immutable: an identical rebuild is a no-op and a
different rebuild is rejected instead of overwritten.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]

from tools.datasets.build_hand_history_increment import (  # noqa: E402
    read_archive,
    records_summary,
    sha256_file,
    write_selected_zip,
)
from tools.populations.registry import (  # noqa: E402
    DEFAULT_REGISTRY,
    load_registry,
    validate_registry,
)
from tools.training.independent_profiles.reveal_aware_ranges import certified_records  # noqa: E402

SCHEMA = "poker-certified-population-baseline/v1"


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _identity_value(value: Any) -> str:
    return str(value).strip().upper()


def _validate_identity(population: Mapping[str, Any], certification: Mapping[str, Any]) -> None:
    target = certification.get("target") or {}
    identity = population.get("identity") or {}
    pairs = {
        "platform": (identity.get("platform"), target.get("platform")),
        "variant": (identity.get("variant"), target.get("variant")),
        "game_kind": (identity.get("game_kind"), target.get("game_kind")),
        "stake": (identity.get("stake"), target.get("stake")),
        "format": (identity.get("format"), target.get("format")),
        "money": (identity.get("money"), target.get("money")),
        "max_seats": (identity.get("max_seats"), target.get("max_seats")),
    }
    drift = [
        f"{field}: registry={left!r}, certification={right!r}"
        for field, (left, right) in pairs.items()
        if _identity_value(left) != _identity_value(right)
    ]
    if drift:
        raise ValueError("population/certification identity mismatch: " + "; ".join(drift))


def _archive_paths(root: Path, certification: Mapping[str, Any]) -> list[Path]:
    rows = list(certification.get("archives") or [])
    if not rows:
        raise ValueError("certification contains no source archives")
    paths: list[Path] = []
    for row in rows:
        rel = str(row.get("path") or "")
        expected = str(row.get("sha256") or "")
        if not rel or len(expected) != 64:
            raise ValueError("certification archive identity is incomplete")
        path = root / rel
        if not path.is_file():
            raise ValueError(f"certification source archive missing: {rel}")
        actual = sha256_file(path)
        if actual != expected:
            raise ValueError(f"certification source archive drifted: {rel}: {actual} != {expected}")
        paths.append(path)
    return paths


def _admissible_contract(certification: Mapping[str, Any]) -> Mapping[str, Any]:
    status = certification.get("status") or {}
    admissible = status.get("ADMISSIBLE") or {}
    if not admissible:
        raise ValueError("certification has no ADMISSIBLE population")
    ambiguous = status.get("AMBIGUOUS") or {}
    if int(ambiguous.get("unique_hands") or 0) != 0:
        raise ValueError("certification contains ambiguous hands; baseline materialization fails closed")
    fingerprint = str(admissible.get("fingerprint_sha256") or "")
    if len(fingerprint) != 64:
        raise ValueError("ADMISSIBLE fingerprint is missing or invalid")
    return admissible


def _write_immutable_bytes(path: Path, data: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        current = path.read_bytes()
        if current != data:
            raise ValueError(f"refusing to replace non-identical immutable artifact: {path}")
        return "UNCHANGED"
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return "CREATED"


def _write_immutable_text(path: Path, text: str) -> str:
    return _write_immutable_bytes(path, text.encode("utf-8"))


def _build_zip_bytes(records: Sequence[Any]) -> bytes:
    with tempfile.TemporaryDirectory() as raw:
        path = Path(raw) / "population.zip"
        write_selected_zip(path, list(records))
        return path.read_bytes()


def _verify_materialized_zip(path: Path, *, expected_summary: Mapping[str, Any]) -> dict[str, Any]:
    records, archive_meta = read_archive(path)
    summary = records_summary(records)
    for field in ("unique_hands", "hand_ids_fingerprint_sha256", "split_counts"):
        if summary.get(field) != expected_summary.get(field):
            raise ValueError(
                f"materialized baseline verification failed for {field}: "
                f"{summary.get(field)!r} != {expected_summary.get(field)!r}"
            )
    return {"archive": archive_meta, "records": summary}


def _bind_registry(
    *,
    registry: Mapping[str, Any],
    registry_path: Path,
    population_id: str,
    baseline_path: str,
    manifest_path: str,
    baseline_sha256: str,
    hand_ids_sha256: str,
) -> str:
    updated = copy.deepcopy(dict(registry))
    population = updated["populations"][population_id]
    data = population["data"]
    bindings = {
        "baseline_archive": baseline_path,
        "baseline_manifest": manifest_path,
        "baseline_archive_sha256": baseline_sha256,
        "baseline_hand_ids_sha256": hand_ids_sha256,
    }
    for key, value in bindings.items():
        current = data.get(key)
        if current not in (None, value):
            raise ValueError(
                f"refusing to replace existing population baseline binding {key}: {current!r} != {value!r}"
            )
        data[key] = value
    validate_registry(updated)
    text = _canonical(updated)
    current_text = registry_path.read_text(encoding="utf-8")
    if current_text == text:
        return "UNCHANGED"
    tmp = registry_path.with_name(registry_path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, registry_path)
    return "UPDATED"


def materialize(
    *,
    root: Path,
    registry_path: Path,
    population_id: str,
    output_zip: Path | None = None,
    manifest_path: Path | None = None,
    bind_registry: bool = False,
) -> dict[str, Any]:
    root = Path(root).resolve()
    registry_full = registry_path if registry_path.is_absolute() else root / registry_path
    registry = load_registry(root, registry_path)
    population = registry["populations"].get(population_id)
    if not isinstance(population, dict):
        raise ValueError(f"unknown population_id {population_id!r}")
    data = population["data"]
    certification_rel = str(data.get("source_certification") or "")
    if not certification_rel:
        raise ValueError(f"population {population_id} has no source_certification")
    certification_path = root / certification_rel
    certification = json.loads(certification_path.read_text(encoding="utf-8"))
    if certification.get("schema") != "poker-population-certification/v1":
        raise ValueError(f"unsupported certification schema: {certification.get('schema')!r}")
    _validate_identity(population, certification)
    admissible = _admissible_contract(certification)
    archives = _archive_paths(root, certification)

    expected_registry_fingerprint = str(data.get("source_hand_ids_sha256") or "")
    expected_registry_count = int(data.get("source_unique_hands") or 0)
    if expected_registry_fingerprint != str(admissible["fingerprint_sha256"]):
        raise ValueError("population registry source fingerprint differs from certification")
    if expected_registry_count != int(admissible["unique_hands"]):
        raise ValueError("population registry source hand count differs from certification")

    stake = str(population["identity"]["stake"])
    records, provenance = certified_records(archives, {stake}, certification_path)
    summary = records_summary(list(records))
    expected_summary = {
        "unique_hands": int(admissible["unique_hands"]),
        "hand_ids_fingerprint_sha256": str(admissible["fingerprint_sha256"]),
        "split_counts": dict(admissible["split_counts"]),
    }
    for field, expected in expected_summary.items():
        if summary.get(field) != expected:
            raise ValueError(f"certified record reconstruction mismatch for {field}: {summary.get(field)!r} != {expected!r}")

    data_root = root / str(data["root"])
    output_zip = (output_zip if output_zip is not None else data_root / "baseline/certified_population.zip")
    manifest_path = (manifest_path if manifest_path is not None else data_root / "baseline/manifest.json")
    output_zip = output_zip if output_zip.is_absolute() else root / output_zip
    manifest_path = manifest_path if manifest_path.is_absolute() else root / manifest_path
    if not output_zip.resolve().is_relative_to(data_root.resolve()):
        raise ValueError("population baseline ZIP must remain under the population data root")
    if not manifest_path.resolve().is_relative_to(data_root.resolve()):
        raise ValueError("population baseline manifest must remain under the population data root")

    zip_bytes = _build_zip_bytes(records)
    zip_sha = _sha256_bytes(zip_bytes)
    zip_write = _write_immutable_bytes(output_zip, zip_bytes)
    verified = _verify_materialized_zip(output_zip, expected_summary=expected_summary)
    if sha256_file(output_zip) != zip_sha:
        raise AssertionError("persisted baseline ZIP differs from deterministic build")

    manifest = {
        "schema": SCHEMA,
        "population_id": population_id,
        "population_identity": copy.deepcopy(population["identity"]),
        "selection": {
            "contract": "EXACT_CERTIFICATION_ADMISSIBLE_HAND_SET",
            "deduplication_key": "PokerStars hand ID",
            "ambiguous_hands_admitted": 0,
            "stake": stake,
        },
        "certification": {
            "path": certification_rel,
            "sha256": sha256_file(certification_path),
            "population_fingerprint_sha256": str(admissible["fingerprint_sha256"]),
            "unique_hands": int(admissible["unique_hands"]),
            "split_counts": dict(admissible["split_counts"]),
        },
        "sources": provenance["source"],
        "baseline": {
            "path": _relative(root, output_zip),
            "sha256": zip_sha,
            "size_bytes": output_zip.stat().st_size,
            "hand_ids_fingerprint_sha256": summary["hand_ids_fingerprint_sha256"],
            "unique_hands": summary["unique_hands"],
            "split_counts": summary["split_counts"],
            "language_counts": summary["language_counts"],
            "stake_counts": summary["stake_counts"],
            "earliest_local_timestamp": summary["earliest_local_timestamp"],
            "latest_local_timestamp": summary["latest_local_timestamp"],
        },
        "verification": {
            "reparsed_archive_unique_hands": verified["records"]["unique_hands"],
            "reparsed_hand_ids_fingerprint_sha256": verified["records"]["hand_ids_fingerprint_sha256"],
            "reparsed_split_counts": verified["records"]["split_counts"],
            "deterministic_zip": True,
        },
    }
    manifest_text = _canonical(manifest)
    manifest_write = _write_immutable_text(manifest_path, manifest_text)

    registry_write = "NOT_REQUESTED"
    if bind_registry:
        registry_write = _bind_registry(
            registry=registry,
            registry_path=registry_full,
            population_id=population_id,
            baseline_path=_relative(root, output_zip),
            manifest_path=_relative(root, manifest_path),
            baseline_sha256=zip_sha,
            hand_ids_sha256=summary["hand_ids_fingerprint_sha256"],
        )

    return {
        "schema": "poker-certified-population-materialization-result/v1",
        "status": "PASS",
        "population_id": population_id,
        "baseline": manifest["baseline"],
        "certification": manifest["certification"],
        "writes": {
            "baseline_zip": zip_write,
            "manifest": manifest_write,
            "registry": registry_write,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--population", required=True)
    parser.add_argument("--output-zip", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--bind-registry", action="store_true")
    args = parser.parse_args()
    result = materialize(
        root=args.root,
        registry_path=args.registry,
        population_id=args.population,
        output_zip=args.output_zip,
        manifest_path=args.manifest,
        bind_registry=args.bind_registry,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Build a deterministic increment after explicit population admission.

The generic historical increment builder scopes by stake only. That is not a
sufficient scientific boundary for a population such as PokerStars NLHE 100/200
Zoom play-money 6-max: a regular table at the same blinds must never enter the
Zoom lineage merely because its hand id is new.

This wrapper resolves the requested population from the versioned registry,
classifies every candidate hand with the conservative population certifier,
blocks the whole snapshot if any target-defining property is ambiguous, filters
out explicit mismatches, and only then applies the existing exact-hand-id
increment contract. The selected ZIP therefore contains population-admissible
hands only while preserving the established split/idempotence semantics.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.datasets.build_hand_history_increment import (  # noqa: E402
    build_increment,
    read_archive as read_increment_archive,
    sha256_file,
    write_selected_zip,
)
from tools.datasets.certify_population import certify  # noqa: E402
from tools.populations.registry import DEFAULT_REGISTRY, resolve_population  # noqa: E402

SCHEMA = "poker-population-hand-history-increment/v1"


def target_from_population(population: dict[str, Any]) -> dict[str, Any]:
    identity = population["identity"]
    return {
        "platform": str(identity["platform"]).upper(),
        "variant": str(identity["variant"]).upper(),
        "game_kind": str(identity["game_kind"]).upper(),
        "stake": str(identity["stake"]),
        "format": str(identity["format"]).upper(),
        "money": str(identity["money"]).upper(),
        "max_seats": int(identity["max_seats"]),
    }


def _representatives(candidate: Path, admitted_ids: set[str]) -> list[Any]:
    records, _ = read_increment_archive(candidate)
    selected: dict[str, Any] = {}
    for record in records:
        if record.hand_id not in admitted_ids:
            continue
        current = selected.get(record.hand_id)
        if current is None or (getattr(current, "language", "") != "en" and record.language == "en"):
            selected[record.hand_id] = record
    missing = admitted_ids - set(selected)
    if missing:
        sample = sorted(missing, key=int)[:10]
        raise ValueError(f"certifier admitted hand ids that raw parser cannot materialize: {sample}")
    return [selected[hand_id] for hand_id in sorted(selected, key=int)]


def build_population_increment(
    *,
    root: Path,
    population_id: str,
    known_archives: list[Path],
    candidate: Path,
    registry_path: Path = DEFAULT_REGISTRY,
    manifest_path: Path | None = None,
    output_zip: Path | None = None,
) -> tuple[dict[str, Any], list[Any]]:
    root = root.resolve()
    population = resolve_population(root, population_id, registry_path)
    target = target_from_population(population)
    candidate = candidate if candidate.is_absolute() else root / candidate
    known = [path if path.is_absolute() else root / path for path in known_archives]
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    if not known or any(not path.is_file() for path in known):
        raise ValueError("at least one existing known population archive is required")

    admission = certify([candidate], target)
    ambiguous = admission["status"]["AMBIGUOUS"]
    if int(ambiguous["unique_hands"]) != 0:
        raise ValueError(
            "candidate snapshot has ambiguous population identity; refusing partial admission: "
            f"{ambiguous['unique_hands']} hands, reasons={ambiguous.get('reason_counts', {})}"
        )

    admitted = admission["status"]["ADMISSIBLE"]
    admitted_ids = set(str(value) for value in admitted.get("hand_ids", []))
    if not admitted_ids:
        records, _ = read_increment_archive(candidate)
        all_ids = {record.hand_id for record in records}
        excluded_ids = set(str(value) for value in admission["status"]["EXCLUDED"].get("hand_ids", []))
        ambiguous_ids = set(str(value) for value in ambiguous.get("hand_ids", []))
        admitted_ids = all_ids - excluded_ids - ambiguous_ids
    if len(admitted_ids) != int(admitted["unique_hands"]):
        raise ValueError("admitted hand-id reconstruction differs from population certification count")

    admitted_records = _representatives(candidate, admitted_ids)
    with tempfile.TemporaryDirectory(prefix="poker-population-admission-") as raw:
        filtered = Path(raw) / "admitted-candidate.zip"
        write_selected_zip(filtered, admitted_records)
        base_manifest, selected = build_increment(known, filtered, stakes=None)

    _, raw_candidate_meta = read_increment_archive(candidate)
    base_manifest["candidate_archive"] = raw_candidate_meta
    base_manifest["schema"] = SCHEMA
    base_manifest["population_id"] = population_id
    base_manifest["population_target"] = target
    base_manifest["selection_rule"] = (
        "candidate hand is ADMISSIBLE for exact population identity and hand ID "
        "is absent from the union of known archive hand IDs"
    )
    base_manifest["population_admission"] = {
        "classifier_schema": admission["schema"],
        "unknown_target_property": admission["classification_contract"]["unknown_target_property"],
        "candidate_raw_sha256": sha256_file(candidate),
        "candidate_unique_hand_ids": int(admission["unique_hand_ids"]),
        "admissible_unique_hands": int(admitted["unique_hands"]),
        "admissible_hand_ids_fingerprint_sha256": admitted["fingerprint_sha256"],
        "admissible_split_counts": admitted["split_counts"],
        "excluded_unique_hands": int(admission["status"]["EXCLUDED"]["unique_hands"]),
        "excluded_reason_counts": admission["status"]["EXCLUDED"].get("reason_counts", {}),
        "excluded_hand_ids_fingerprint_sha256": admission["status"]["EXCLUDED"]["fingerprint_sha256"],
        "ambiguous_unique_hands": 0,
        "ambiguous_hand_ids_fingerprint_sha256": ambiguous["fingerprint_sha256"],
        "duplicate_diagnostics": admission["duplicate_diagnostics"],
    }

    if output_zip is not None:
        output_zip = output_zip if output_zip.is_absolute() else root / output_zip
        write_selected_zip(output_zip, selected)
        base_manifest["output_zip"] = {
            "path": output_zip.relative_to(root).as_posix() if output_zip.is_relative_to(root) else str(output_zip),
            "sha256": sha256_file(output_zip),
            "size_bytes": output_zip.stat().st_size,
        }
    if manifest_path is not None:
        manifest_path = manifest_path if manifest_path.is_absolute() else root / manifest_path
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(base_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return base_manifest, selected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--population", required=True)
    parser.add_argument("--known", type=Path, action="append", required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-zip", type=Path, required=True)
    args = parser.parse_args()
    manifest, _ = build_population_increment(
        root=args.root,
        population_id=args.population,
        known_archives=args.known,
        candidate=args.candidate,
        registry_path=args.registry,
        manifest_path=args.manifest,
        output_zip=args.output_zip,
    )
    print(json.dumps({
        "population_id": manifest["population_id"],
        "population_admission": manifest["population_admission"],
        "selected_unique_hands": manifest["selected_unique_hands"],
        "split_counts": manifest["split_counts"],
        "chronological_new": manifest["chronological_new"],
        "historical_backfill": manifest["historical_backfill"],
        "undated_unseen": manifest["undated_unseen"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

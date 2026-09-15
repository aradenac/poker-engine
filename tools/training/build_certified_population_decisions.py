#!/usr/bin/env python3
"""Materialize normalized decisions for one certified poker population.

The population certification is authoritative for inclusion/exclusion. Source
archives are re-read from their immutable repo paths, deduplicated by exact
PokerStars hand ID, and filtered by the certification's explicit EXCLUDED IDs.
The resulting target fingerprint and deterministic split counts must match the
certification byte-for-byte contract before any decision row is emitted.

This builder intentionally reuses the historical normalized-decision parser so
Model A evaluation and training consume the same row/context semantics. It fails
closed if any certified target hand cannot be normalized.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.datasets.build_hand_history_increment import (  # noqa: E402
    fingerprint,
    read_archive,
    sha256_file,
    split_for,
)
from tools.training.increment_decisions import decision_rows, parse_hand  # noqa: E402

SCHEMA = "poker-certified-population-decisions/v1"
CERT_SCHEMA = "poker-population-certification/v1"


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object: {path}")
    return data


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build(
    certification_path: Path,
    out: Path,
    summary_path: Path,
    *,
    include_preflop_context_v1: bool = True,
) -> dict[str, Any]:
    certification = load_json(certification_path)
    if certification.get("schema") != CERT_SCHEMA:
        raise ValueError(f"unexpected certification schema: {certification.get('schema')!r}")

    status = certification.get("status") or {}
    admissible = status.get("ADMISSIBLE") or {}
    excluded = status.get("EXCLUDED") or {}
    ambiguous = status.get("AMBIGUOUS") or {}
    if int(ambiguous.get("unique_hands") or 0) != 0:
        raise ValueError("certified population contains AMBIGUOUS hands; refusing materialization")
    excluded_ids = {str(x) for x in (excluded.get("hand_ids") or [])}
    if len(excluded_ids) != int(excluded.get("unique_hands") or 0):
        raise ValueError("EXCLUDED hand ID list does not match certification count")

    records_by_id = {}
    archive_evidence = []
    duplicate_occurrences = 0
    for archive in certification.get("archives") or []:
        rel = str(archive.get("path") or "")
        if not rel:
            raise ValueError("certification archive path missing")
        path = ROOT / rel
        if not path.is_file():
            raise FileNotFoundError(path)
        actual_sha = sha256_file(path)
        expected_sha = str(archive.get("sha256") or "")
        if actual_sha != expected_sha:
            raise ValueError(f"archive SHA mismatch for {rel}: {actual_sha} != {expected_sha}")
        records, meta = read_archive(path)
        if int(meta.get("unique_hands") or 0) != int(archive.get("unique_hand_ids") or 0):
            raise ValueError(f"archive unique-hand count mismatch for {rel}")
        archive_evidence.append({"path": rel, "sha256": actual_sha, "unique_hands": meta["unique_hands"]})
        for record in records:
            if record.hand_id in records_by_id:
                duplicate_occurrences += 1
                # Certification already proves duplicate metadata/content compatibility.
                # Prefer an English occurrence because the historical normalized-row
                # parser is English and the certified Zoom corpus is expected to be
                # parseable without inventing language translations.
                current = records_by_id[record.hand_id]
                if getattr(current, "language", "") != "en" and record.language == "en":
                    records_by_id[record.hand_id] = record
            else:
                records_by_id[record.hand_id] = record

    all_ids = set(records_by_id)
    if len(all_ids) != int(certification.get("unique_hand_ids") or 0):
        raise ValueError("deduplicated union count differs from certification")
    all_fp = fingerprint(all_ids)
    if all_fp != certification.get("all_hand_ids_fingerprint_sha256"):
        raise ValueError("deduplicated union fingerprint differs from certification")

    target_ids = all_ids - excluded_ids
    expected_count = int(admissible.get("unique_hands") or 0)
    expected_fp = str(admissible.get("fingerprint_sha256") or "")
    if len(target_ids) != expected_count:
        raise ValueError(f"target count mismatch: {len(target_ids)} != {expected_count}")
    if fingerprint(target_ids) != expected_fp:
        raise ValueError("target hand-ID fingerprint differs from certification")

    split_counts = collections.Counter(split_for(hid) for hid in target_ids)
    expected_splits = admissible.get("split_counts") or {}
    for split in ("TRAIN", "VALIDATION", "TEST"):
        if split_counts[split] != int(expected_splits.get(split) or 0):
            raise ValueError(f"target {split} split mismatch: {split_counts[split]} != {expected_splits.get(split)}")

    stats = collections.Counter()
    known_population = collections.Counter()
    parse_errors = []
    rows = []
    for hid in sorted(target_ids, key=int):
        record = records_by_id[hid]
        hand = parse_hand(record.text, record.source_file)
        if not hand:
            parse_errors.append({
                "hand_id": hid,
                "language": record.language,
                "source_file": record.source_file,
            })
            continue
        if str(hand.get("id")) != hid:
            raise ValueError(f"normalized hand ID mismatch: {hand.get('id')} != {hid}")
        for row in decision_rows(hand, include_preflop_context_v1=include_preflop_context_v1):
            rows.append(row)
            who = "hero" if row.get("is_hero") else "population"
            stats[(row["split"], row["street"], who)] += 1
            if not row.get("is_hero") and row.get("known_hand_class"):
                known_population[(row["split"], row["street"], row["action"])] += 1

    if parse_errors:
        sample = parse_errors[:10]
        raise ValueError(
            f"{len(parse_errors)} certified target hands failed normalization; sample={sample}"
        )

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    summary = {
        "schema": SCHEMA,
        "population_id": "pokerstars_nlhe_100-200_zoom_play_6max_v1",
        "certification": {
            "path": certification_path.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(certification_path),
        },
        "archives": archive_evidence,
        "source_union_unique_hands": len(all_ids),
        "duplicate_archive_occurrences": duplicate_occurrences,
        "excluded_unique_hands": len(excluded_ids),
        "target_unique_hands": len(target_ids),
        "target_hand_ids_fingerprint_sha256": fingerprint(target_ids),
        "hands_by_split": {k: split_counts[k] for k in ("TRAIN", "VALIDATION", "TEST")},
        "rows_total": len(rows),
        "decision_counts": {"|".join(map(str, key)): value for key, value in sorted(stats.items())},
        "known_population_preflop": {
            "|".join(map(str, key)): value
            for key, value in sorted(known_population.items())
            if key[1] == "preflop"
        },
        "hero_training_policy": "rows are materialized for audit/evaluation but downstream population fitting must exclude is_hero=true",
        "preflop_context_contract": bool(include_preflop_context_v1),
        "output": out.relative_to(ROOT).as_posix() if out.is_relative_to(ROOT) else str(out),
        "output_sha256": sha256_file(out),
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--certification", type=Path, default=ROOT / "training/datasets/NLHE_100-200/population_certification.json")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--summary", type=Path, required=True)
    p.add_argument("--without-preflop-contract-v1", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    certification = args.certification if args.certification.is_absolute() else ROOT / args.certification
    out = args.out if args.out.is_absolute() else ROOT / args.out
    summary = args.summary if args.summary.is_absolute() else ROOT / args.summary
    result = build(
        certification,
        out,
        summary,
        include_preflop_context_v1=not args.without_preflop_contract_v1,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

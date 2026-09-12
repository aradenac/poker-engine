#!/usr/bin/env python3
"""Build an immutable hand-history increment by exact PokerStars hand ID.

The tool compares one candidate archive with one or more already-known archives,
selects only genuinely unseen hands, applies the stable population split contract,
and writes a reproducible JSON manifest. Optionally it can materialize a ZIP that
contains only selected hands while preserving the source file grouping.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

SPLIT_NAMESPACE = "poker-population-split-v1"

HEADER_RE = re.compile(
    r"(?m)^(?:"
    r"PokerStars(?: Zoom)? Hand #(\d+):[^\n]*"
    r"|Main PokerStars n[°º](\d+)\s*:[^\n]*"
    r")$"
)
EN_DATE_RE = re.compile(r" - (\d{4})/(\d{2})/(\d{2}) (\d{1,2}):(\d{2}):(\d{2})")
FR_DATE_RE = re.compile(r" - (\d{2})/(\d{2})/(\d{4}) (\d{1,2}):(\d{2}):(\d{2})")


@dataclass(frozen=True)
class HandRecord:
    hand_id: str
    source_file: str
    text: str
    timestamp: str | None
    language: str


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass
    return data.decode("utf-8", errors="replace")


def normalize_timestamp(header: str, language: str) -> str | None:
    if language == "en":
        m = EN_DATE_RE.search(header)
        if not m:
            return None
        year, month, day, hour, minute, second = map(int, m.groups())
    else:
        m = FR_DATE_RE.search(header)
        if not m:
            return None
        day, month, year, hour, minute, second = map(int, m.groups())
    return datetime(year, month, day, hour, minute, second).strftime("%Y-%m-%d %H:%M:%S")


def parse_hand_blocks(text: str, source_file: str) -> list[HandRecord]:
    matches = list(HEADER_RE.finditer(text))
    out: list[HandRecord] = []
    for i, match in enumerate(matches):
        hand_id = match.group(1) or match.group(2)
        language = "en" if match.group(1) else "fr"
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[start:end].strip("\r\n") + "\n"
        header = match.group(0)
        out.append(
            HandRecord(
                hand_id=hand_id,
                source_file=source_file,
                text=block,
                timestamp=normalize_timestamp(header, language),
                language=language,
            )
        )
    return out


def read_archive(path: Path) -> tuple[list[HandRecord], dict]:
    records: list[HandRecord] = []
    entries = 0
    with zipfile.ZipFile(path) as zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        entries = len(infos)
        for info in infos:
            text = decode_text(zf.read(info))
            records.extend(parse_hand_blocks(text, info.filename))

    counts = Counter(r.hand_id for r in records)
    return records, {
        "path": path.as_posix(),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
        "archive_entries": entries,
        "parsed_hands": len(records),
        "unique_hands": len(counts),
        "duplicate_hand_ids": sum(1 for n in counts.values() if n > 1),
        "duplicate_hand_occurrences": sum(n - 1 for n in counts.values() if n > 1),
    }


def split_for(hand_id: str, namespace: str = SPLIT_NAMESPACE) -> str:
    digest = hashlib.sha256(f"{namespace}:{hand_id}".encode()).digest()
    bucket = int.from_bytes(digest[:8], "big") % 10000
    if bucket < 8000:
        return "TRAIN"
    if bucket < 9000:
        return "VALIDATION"
    return "TEST"


def fingerprint(ids: Iterable[str]) -> str:
    ordered = sorted(set(ids))
    return hashlib.sha256("\n".join(ordered).encode()).hexdigest()


def build_increment(known_archives: list[Path], candidate: Path) -> tuple[dict, list[HandRecord]]:
    known_ids: set[str] = set()
    known_meta = []
    for archive in known_archives:
        records, meta = read_archive(archive)
        known_ids.update(r.hand_id for r in records)
        known_meta.append(meta)

    candidate_records, candidate_meta = read_archive(candidate)
    candidate_counts = Counter(r.hand_id for r in candidate_records)

    selected_by_id: dict[str, HandRecord] = {}
    for record in candidate_records:
        if record.hand_id not in known_ids and record.hand_id not in selected_by_id:
            selected_by_id[record.hand_id] = record

    selected = sorted(selected_by_id.values(), key=lambda r: int(r.hand_id))
    selected_ids = [r.hand_id for r in selected]
    split_counts = Counter(split_for(hid) for hid in selected_ids)
    language_counts = Counter(r.language for r in selected)
    timestamps = sorted(r.timestamp for r in selected if r.timestamp)

    manifest = {
        "schema": "poker-hand-history-increment/v1",
        "selection_rule": "candidate hand ID not present in union of known archive hand IDs",
        "split_contract": {
            "namespace": SPLIT_NAMESPACE,
            "algorithm": "SHA-256(namespace + ':' + hand_id); first 64 bits big-endian modulo 10000",
            "TRAIN": [0, 7999],
            "VALIDATION": [8000, 8999],
            "TEST": [9000, 9999],
        },
        "known_archives": known_meta,
        "known_unique_hand_ids": len(known_ids),
        "known_hand_ids_fingerprint_sha256": fingerprint(known_ids),
        "candidate_archive": candidate_meta,
        "candidate_hand_ids_fingerprint_sha256": fingerprint(candidate_counts),
        "selected_unique_hands": len(selected_ids),
        "selected_hand_ids_fingerprint_sha256": fingerprint(selected_ids),
        "selected_hand_ids": selected_ids,
        "split_counts": {
            "TRAIN": split_counts.get("TRAIN", 0),
            "VALIDATION": split_counts.get("VALIDATION", 0),
            "TEST": split_counts.get("TEST", 0),
        },
        "language_counts": dict(sorted(language_counts.items())),
        "earliest_local_timestamp": timestamps[0] if timestamps else None,
        "latest_local_timestamp": timestamps[-1] if timestamps else None,
        "candidate_duplicate_hand_ids": candidate_meta["duplicate_hand_ids"],
        "candidate_duplicate_hand_occurrences": candidate_meta["duplicate_hand_occurrences"],
    }
    return manifest, selected


def write_selected_zip(path: Path, selected: list[HandRecord]) -> None:
    grouped: dict[str, list[str]] = defaultdict(list)
    for record in selected:
        grouped[record.source_file].append(record.text)

    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for source_file in sorted(grouped):
            payload = "\n".join(grouped[source_file]).encode("utf-8")
            zf.writestr(source_file, payload)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--known", type=Path, action="append", required=True,
                        help="Previously known hand-history ZIP; may be repeated")
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-zip", type=Path)
    args = parser.parse_args()

    manifest, selected = build_increment(args.known, args.candidate)
    if args.output_zip:
        write_selected_zip(args.output_zip, selected)
        manifest["output_zip"] = {
            "path": args.output_zip.as_posix(),
            "sha256": sha256_file(args.output_zip),
            "size_bytes": args.output_zip.stat().st_size,
        }

    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "selected_unique_hands": manifest["selected_unique_hands"],
        "split_counts": manifest["split_counts"],
        "selected_hand_ids_fingerprint_sha256": manifest["selected_hand_ids_fingerprint_sha256"],
        "earliest_local_timestamp": manifest["earliest_local_timestamp"],
        "latest_local_timestamp": manifest["latest_local_timestamp"],
    }, indent=2))


if __name__ == "__main__":
    main()

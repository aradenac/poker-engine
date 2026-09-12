#!/usr/bin/env python3
import argparse
import hashlib
import json
import re
import zipfile
from collections import Counter
from pathlib import Path

HAND_RE = re.compile(r"^PokerStars(?: Zoom)? Hand #(\d+):", re.M)
DATE_RE = re.compile(r"^PokerStars(?: Zoom)? Hand #\d+:.*? - (\d{4}/\d{2}/\d{2} \d{1,2}:\d{2}:\d{2})", re.M)


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


def audit(archive: Path) -> dict:
    hand_ids = []
    timestamps = []
    per_file = []
    total_uncompressed = 0
    text_entries = 0

    with zipfile.ZipFile(archive) as zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        for info in infos:
            total_uncompressed += info.file_size
            try:
                data = zf.read(info)
            except RuntimeError:
                per_file.append({"path": info.filename, "error": "unreadable"})
                continue

            text = decode_text(data)
            ids = HAND_RE.findall(text)
            dates = DATE_RE.findall(text)
            if ids or info.filename.lower().endswith((".txt", ".log", ".hh")):
                text_entries += 1
            hand_ids.extend(ids)
            timestamps.extend(dates)
            per_file.append({
                "path": info.filename,
                "bytes": info.file_size,
                "hands": len(ids),
            })

    counts = Counter(hand_ids)
    unique_ids = sorted(counts)
    fingerprint = hashlib.sha256("\n".join(unique_ids).encode()).hexdigest()
    duplicate_occurrences = sum(v - 1 for v in counts.values() if v > 1)

    return {
        "schema": "poker-hand-history-archive-audit/v1",
        "archive": archive.as_posix(),
        "archive_size_bytes": archive.stat().st_size,
        "archive_sha256": sha256_file(archive),
        "archive_entries": len(per_file),
        "text_entries": text_entries,
        "total_uncompressed_bytes": total_uncompressed,
        "compression_ratio": (total_uncompressed / archive.stat().st_size) if archive.stat().st_size else None,
        "parsed_hands": len(hand_ids),
        "unique_hands": len(unique_ids),
        "duplicate_hand_ids": sum(1 for v in counts.values() if v > 1),
        "duplicate_hand_occurrences": duplicate_occurrences,
        "earliest_local_timestamp": min(timestamps) if timestamps else None,
        "latest_local_timestamp": max(timestamps) if timestamps else None,
        "fingerprint_sorted_hand_ids_sha256": fingerprint,
        "files": per_file,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = audit(args.archive)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in (
        "archive_sha256", "archive_entries", "parsed_hands", "unique_hands",
        "duplicate_hand_ids", "earliest_local_timestamp", "latest_local_timestamp",
        "fingerprint_sorted_hand_ids_sha256"
    )}, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
import argparse
import hashlib
import json
import re
import zipfile
from collections import Counter
from pathlib import Path

EN_HAND_RE = re.compile(r"^PokerStars(?: Zoom)? Hand #(\d+):", re.M)
FR_HAND_RE = re.compile(r"^Main PokerStars n[°º](\d+)\s*:", re.M)
EN_DATE_RE = re.compile(r"^PokerStars(?: Zoom)? Hand #\d+:.*? - (\d{4})/(\d{2})/(\d{2}) (\d{1,2}):(\d{2}):(\d{2})", re.M)
FR_DATE_RE = re.compile(r"^Main PokerStars n[°º]\d+\s*:.*? - (\d{2})/(\d{2})/(\d{4}) (\d{1,2}):(\d{2}):(\d{2})", re.M)


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


def first_nonempty_line(text: str):
    for line in text.replace("\r", "").splitlines():
        line = line.strip()
        if line:
            return line
    return None


def normalized_dates(text: str):
    out = []
    for y, m, d, hh, mm, ss in EN_DATE_RE.findall(text):
        out.append(f"{y}-{m}-{d} {int(hh):02d}:{mm}:{ss}")
    for d, m, y, hh, mm, ss in FR_DATE_RE.findall(text):
        out.append(f"{y}-{m}-{d} {int(hh):02d}:{mm}:{ss}")
    return out


def audit(archive: Path) -> dict:
    hand_ids = []
    timestamps = []
    per_file = []
    unmatched_header_samples = []
    language_counts = Counter()
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
            en_ids = EN_HAND_RE.findall(text)
            fr_ids = FR_HAND_RE.findall(text)
            ids = en_ids + fr_ids
            dates = normalized_dates(text)
            language_counts["en"] += len(en_ids)
            language_counts["fr"] += len(fr_ids)
            if ids or info.filename.lower().endswith((".txt", ".log", ".hh")):
                text_entries += 1
            if not ids and len(unmatched_header_samples) < 20:
                header = first_nonempty_line(text)
                if header:
                    unmatched_header_samples.append({"path": info.filename, "header": header})
            hand_ids.extend(ids)
            timestamps.extend(dates)
            per_file.append({
                "path": info.filename,
                "bytes": info.file_size,
                "hands": len(ids),
                "en_hands": len(en_ids),
                "fr_hands": len(fr_ids),
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
        "language_hand_counts": dict(sorted(language_counts.items())),
        "earliest_local_timestamp": min(timestamps) if timestamps else None,
        "latest_local_timestamp": max(timestamps) if timestamps else None,
        "fingerprint_sorted_hand_ids_sha256": fingerprint,
        "unmatched_header_samples": unmatched_header_samples,
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
        "duplicate_hand_ids", "language_hand_counts", "earliest_local_timestamp",
        "latest_local_timestamp", "fingerprint_sorted_hand_ids_sha256",
        "unmatched_header_samples"
    )}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

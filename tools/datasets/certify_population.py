#!/usr/bin/env python3
"""Certify a PokerStars hand-history population from immutable ZIP archives.

The certifier is intentionally conservative: an unknown target-defining property
is AMBIGUOUS, never silently admitted. Duplicate PokerStars hand IDs are merged
before population counts are produced. Conflicting duplicate metadata/content is
reported explicitly.

This tool does not mutate historical archives or training splits.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from tools.datasets.build_hand_history_increment import decode_text, sha256_file, split_for

SCHEMA = "poker-population-certification/v1"
TARGET_DEFAULTS = {
    "platform": "POKERSTARS",
    "variant": "NLHE",
    "game_kind": "CASH",
    "stake": "100/200",
    "format": "ZOOM",
    "money": "PLAY",
    "max_seats": 6,
}

HEADER_LINE_RE = re.compile(
    r"(?im)^(?:"
    r"PokerStars(?:\s+Zoom)?\s+Hand\s+#\d+:[^\n]*"
    r"|Main\s+(?:Zoom\s+)?PokerStars(?:\s+Zoom)?\s+n[°º]\d+\s*:[^\n]*"
    r")$"
)
EN_HEADER_RE = re.compile(
    r"^PokerStars(?P<zoom>\s+Zoom)?\s+Hand\s+#(?P<id>\d+):(?P<rest>.*)$", re.I
)
FR_HEADER_RE = re.compile(
    r"^Main\s+(?P<zoom_before>Zoom\s+)?PokerStars(?P<zoom_after>\s+Zoom)?\s+"
    r"n[°º](?P<id>\d+)\s*:(?P<rest>.*)$",
    re.I,
)
STAKE_RE = re.compile(
    r"\((?:[€$£]\s*)?(\d[\d.,]*)\s*/\s*(?:[€$£]\s*)?(\d[\d.,]*)"
    r"(?:\s+(?:EUR|USD|GBP|CAD|AUD|CHF|[A-Za-z]+))?\)",
    re.I,
)
TABLE_SIZE_RE = re.compile(r"\b(\d+)-max\b", re.I)
REAL_MONEY_RE = re.compile(r"(?:[€$£]|\b(?:EUR|USD|GBP|CAD|AUD|CHF)\b)", re.I)
PLAY_MONEY_RE = re.compile(r"\b(?:play\s*money|argent\s+fictif|jetons\s+fictifs?)\b", re.I)
TOURNAMENT_RE = re.compile(r"\b(?:tournament|tournoi)\b", re.I)
NLHE_RE = re.compile(r"Hold[’']?em\s+No\s+Limit", re.I)
RAKE_RE = re.compile(
    r"(?:\|\s*)?(?:Rake|Commission|Pr[ée]l[èe]vement)\s+([€$£]?\s*[\d.,]+)", re.I
)
CANDIDATE_UNPARSED_RE = re.compile(
    r"(?im)^(?:PokerStars[^\n]*(?:Hand\s+#\d+)|Main[^\n]*PokerStars[^\n]*n[°º]\d+)[^\n]*$"
)


def normalize_number(text: str) -> str | None:
    value = re.sub(r"[^0-9,.-]", "", text).replace(",", ".")
    if not value:
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return str(int(number)) if number.is_integer() else str(number)


def parse_stake(header: str) -> str | None:
    match = STAKE_RE.search(header)
    if not match:
        return None
    small = normalize_number(match.group(1))
    big = normalize_number(match.group(2))
    if small is None or big is None:
        return None
    try:
        if float(small) <= 0 or float(big) <= 0:
            return None
    except ValueError:
        return None
    return f"{small}/{big}"


def parse_currency(header: str, money: str) -> str | None:
    if money == "PLAY":
        return "PLAY_CHIPS"
    match = re.search(r"\b(EUR|USD|GBP|CAD|AUD|CHF)\b", header, re.I)
    if match:
        return match.group(1).upper()
    if "€" in header:
        return "EUR"
    if "£" in header:
        return "GBP"
    if "$" in header:
        return "USD_OR_DOLLAR_DENOMINATED"
    return None


def normalized_payload_hash(text: str) -> str:
    normalized = "\n".join(line.rstrip() for line in text.replace("\r", "").splitlines()).strip() + "\n"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class HandEvidence:
    hand_id: str
    archive: str
    source_file: str
    language: str
    platform: str
    variant: str
    game_kind: str
    stake: str | None
    format: str
    money: str
    currency: str | None
    max_seats: int | None
    rake: str | None
    payload_sha256: str
    header: str

    def population_signature(self) -> tuple:
        return (
            self.platform,
            self.variant,
            self.game_kind,
            self.stake,
            self.format,
            self.money,
            self.currency,
            self.max_seats,
        )


def parse_header(header: str) -> tuple[str, str, bool] | None:
    en = EN_HEADER_RE.match(header)
    if en:
        return en.group("id"), "en", bool(en.group("zoom"))
    fr = FR_HEADER_RE.match(header)
    if fr:
        return fr.group("id"), "fr", bool(fr.group("zoom_before") or fr.group("zoom_after"))
    return None


def classify_block(block: str, archive: Path, source_file: str) -> HandEvidence:
    header = block.replace("\r", "").splitlines()[0].strip()
    parsed = parse_header(header)
    if not parsed:
        raise ValueError(f"unsupported PokerStars header: {header}")
    hand_id, language, is_zoom = parsed

    source_context = f"{source_file}\n{header}"
    play_evidence = bool(PLAY_MONEY_RE.search(source_context))
    real_evidence = bool(REAL_MONEY_RE.search(header))
    if play_evidence and real_evidence:
        money = "CONFLICT"
    elif play_evidence:
        money = "PLAY"
    elif real_evidence:
        money = "REAL"
    else:
        money = "UNKNOWN"

    table_size = TABLE_SIZE_RE.search(block)
    rake = RAKE_RE.search(block)
    rake_value = normalize_number(rake.group(1)) if rake else None

    return HandEvidence(
        hand_id=hand_id,
        archive=archive.as_posix(),
        source_file=source_file,
        language=language,
        platform="POKERSTARS",
        variant="NLHE" if NLHE_RE.search(header) else "OTHER_OR_UNKNOWN",
        game_kind="TOURNAMENT" if TOURNAMENT_RE.search(header) else "CASH",
        stake=parse_stake(header),
        format="ZOOM" if is_zoom else "REGULAR",
        money=money,
        currency=parse_currency(header, money),
        max_seats=int(table_size.group(1)) if table_size else None,
        rake=rake_value,
        payload_sha256=normalized_payload_hash(block),
        header=header,
    )


def read_archive(archive: Path) -> tuple[list[HandEvidence], dict]:
    hands: list[HandEvidence] = []
    unmatched: list[dict] = []
    entries = 0
    with zipfile.ZipFile(archive) as zf:
        infos = [item for item in zf.infolist() if not item.is_dir()]
        entries = len(infos)
        for info in infos:
            text = decode_text(zf.read(info))
            matches = list(HEADER_LINE_RE.finditer(text))
            for index, match in enumerate(matches):
                start = match.start()
                end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
                block = text[start:end].strip("\r\n") + "\n"
                hands.append(classify_block(block, archive, info.filename))

            if len(unmatched) < 50:
                parsed_headers = {match.group(0).strip() for match in matches}
                for candidate in CANDIDATE_UNPARSED_RE.findall(text):
                    candidate = candidate.strip()
                    if candidate not in parsed_headers:
                        unmatched.append({"source_file": info.filename, "header": candidate})
                        if len(unmatched) >= 50:
                            break

    return hands, {
        "path": archive.as_posix(),
        "sha256": sha256_file(archive),
        "size_bytes": archive.stat().st_size,
        "archive_entries": entries,
        "parsed_hands": len(hands),
        "unique_hand_ids": len({hand.hand_id for hand in hands}),
        "unparsed_pokerstars_header_samples": unmatched,
    }


def fingerprint(ids: Iterable[str]) -> str:
    return hashlib.sha256("\n".join(sorted(set(ids))).encode("utf-8")).hexdigest()


def counter_dict(counter: Counter) -> dict:
    return {str(key): value for key, value in sorted(counter.items(), key=lambda item: str(item[0]))}


def expected_fields(target: dict) -> tuple[str, ...]:
    return ("platform", "variant", "game_kind", "stake", "format", "money", "max_seats")


def classify_against_target(hand: HandEvidence, target: dict) -> tuple[str, list[str]]:
    unknown = []
    mismatch = []
    values = asdict(hand)
    for field in expected_fields(target):
        actual = values[field]
        expected = target[field]
        if actual is None or actual in {"UNKNOWN", "OTHER_OR_UNKNOWN", "CONFLICT"}:
            unknown.append(f"{field}:{actual}")
        elif actual != expected:
            mismatch.append(f"{field}:{actual}!={expected}")
    if unknown:
        return "AMBIGUOUS", unknown + mismatch
    if mismatch:
        return "EXCLUDED", mismatch
    return "ADMISSIBLE", []


def certify(archives: list[Path], target: dict | None = None) -> dict:
    target = dict(TARGET_DEFAULTS if target is None else target)
    occurrences: list[HandEvidence] = []
    archive_reports = []
    for archive in archives:
        parsed, report = read_archive(archive)
        occurrences.extend(parsed)
        archive_reports.append(report)

    by_id: dict[str, list[HandEvidence]] = defaultdict(list)
    for hand in occurrences:
        by_id[hand.hand_id].append(hand)

    status_ids: dict[str, list[str]] = {"ADMISSIBLE": [], "EXCLUDED": [], "AMBIGUOUS": []}
    reason_counts: dict[str, Counter] = {
        "EXCLUDED": Counter(),
        "AMBIGUOUS": Counter(),
    }
    samples: dict[str, list[dict]] = {"EXCLUDED": [], "AMBIGUOUS": []}
    metadata_conflicts: list[str] = []
    content_conflicts: list[str] = []
    cross_language_variants: list[str] = []
    field_counts = {
        "platform": Counter(),
        "variant": Counter(),
        "game_kind": Counter(),
        "stake": Counter(),
        "format": Counter(),
        "money": Counter(),
        "currency": Counter(),
        "max_seats": Counter(),
        "language": Counter(),
    }
    rake = Counter()

    for hand_id in sorted(by_id, key=lambda value: int(value)):
        group = by_id[hand_id]
        signatures = {hand.population_signature() for hand in group}
        payloads = {hand.payload_sha256 for hand in group}
        languages = {hand.language for hand in group}

        if len(signatures) > 1:
            status = "AMBIGUOUS"
            reasons = ["duplicate_metadata_conflict"]
            metadata_conflicts.append(hand_id)
        elif len(payloads) > 1 and len(languages) == 1:
            status = "AMBIGUOUS"
            reasons = ["duplicate_content_conflict"]
            content_conflicts.append(hand_id)
        else:
            if len(payloads) > 1 and len(languages) > 1:
                cross_language_variants.append(hand_id)
            status, reasons = classify_against_target(group[0], target)

        status_ids[status].append(hand_id)
        if status != "ADMISSIBLE":
            for reason in reasons:
                reason_counts[status][reason] += 1
            if len(samples[status]) < 30:
                samples[status].append({
                    "hand_id": hand_id,
                    "reasons": reasons,
                    "source_file": group[0].source_file,
                    "header": group[0].header,
                })

        representative = group[0]
        for field in field_counts:
            field_counts[field][getattr(representative, field) or "UNKNOWN"] += 1
        rake[representative.rake if representative.rake is not None else "UNKNOWN"] += 1

    all_ids = sorted(by_id, key=lambda value: int(value))
    admissible = status_ids["ADMISSIBLE"]
    excluded = status_ids["EXCLUDED"]
    ambiguous = status_ids["AMBIGUOUS"]
    split_counts = Counter(split_for(hand_id) for hand_id in admissible)

    return {
        "schema": SCHEMA,
        "target": target,
        "classification_contract": {
            "unknown_target_property": "AMBIGUOUS_NEVER_ADMITTED",
            "deduplication_key": "PokerStars hand ID",
            "duplicate_metadata_conflict": "AMBIGUOUS",
            "same_language_payload_conflict": "AMBIGUOUS",
            "cross_language_payload_variant": "reported_not_automatically_conflicting_when_population_metadata_agrees",
            "money_evidence": "explicit Play Money/Argent fictif source/header markers versus real-currency header markers",
            "format_evidence": "Zoom token in PokerStars hand header; recognized non-Zoom header => REGULAR",
            "rake_evidence": "observed hand-history summary only; no external rake schedule inferred",
        },
        "archives": archive_reports,
        "archive_occurrences": len(occurrences),
        "unique_hand_ids": len(all_ids),
        "all_hand_ids_fingerprint_sha256": fingerprint(all_ids),
        "status": {
            "ADMISSIBLE": {
                "unique_hands": len(admissible),
                "fingerprint_sha256": fingerprint(admissible),
                "split_counts": {
                    "TRAIN": split_counts.get("TRAIN", 0),
                    "VALIDATION": split_counts.get("VALIDATION", 0),
                    "TEST": split_counts.get("TEST", 0),
                },
            },
            "EXCLUDED": {
                "unique_hands": len(excluded),
                "fingerprint_sha256": fingerprint(excluded),
                "reason_counts": counter_dict(reason_counts["EXCLUDED"]),
                "hand_ids": excluded,
                "samples": samples["EXCLUDED"],
            },
            "AMBIGUOUS": {
                "unique_hands": len(ambiguous),
                "fingerprint_sha256": fingerprint(ambiguous),
                "reason_counts": counter_dict(reason_counts["AMBIGUOUS"]),
                "hand_ids": ambiguous,
                "samples": samples["AMBIGUOUS"],
            },
        },
        "field_counts_unique_hands": {
            field: counter_dict(counts) for field, counts in field_counts.items()
        },
        "observed_rake_counts_unique_hands": counter_dict(rake),
        "duplicate_diagnostics": {
            "ids_with_multiple_occurrences": sum(1 for group in by_id.values() if len(group) > 1),
            "metadata_conflict_ids": metadata_conflicts,
            "same_language_content_conflict_ids": content_conflicts,
            "cross_language_payload_variant_ids": cross_language_variants,
        },
    }


def summary(report: dict) -> dict:
    return {
        "schema": report["schema"],
        "target": report["target"],
        "archive_occurrences": report["archive_occurrences"],
        "unique_hand_ids": report["unique_hand_ids"],
        "all_hand_ids_fingerprint_sha256": report["all_hand_ids_fingerprint_sha256"],
        "status_counts": {
            key: value["unique_hands"] for key, value in report["status"].items()
        },
        "admissible_split_counts": report["status"]["ADMISSIBLE"]["split_counts"],
        "excluded_reason_counts": report["status"]["EXCLUDED"]["reason_counts"],
        "ambiguous_reason_counts": report["status"]["AMBIGUOUS"]["reason_counts"],
        "field_counts_unique_hands": report["field_counts_unique_hands"],
        "duplicate_diagnostics": {
            key: (len(value) if isinstance(value, list) else value)
            for key, value in report["duplicate_diagnostics"].items()
        },
        "archives": report["archives"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target-stake", default="100/200")
    parser.add_argument("--target-format", choices=("ZOOM", "REGULAR"), default="ZOOM")
    parser.add_argument("--target-money", choices=("PLAY", "REAL"), default="PLAY")
    parser.add_argument("--target-max-seats", type=int, default=6)
    args = parser.parse_args()

    target = dict(TARGET_DEFAULTS)
    target.update({
        "stake": args.target_stake,
        "format": args.target_format,
        "money": args.target_money,
        "max_seats": args.target_max_seats,
    })
    report = certify(args.archive, target)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary(report), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Public-only generalized adverse-response preflop dataset (#421).

The dataset is a versioned, byte-reproducible stream of **adverse** (non-Hero)
preflop response rows.  Every row is projected onto the public information that
exists *immediately before* the observed voluntary action:

``family``, ``actor_position``, ``aggressor_position``, ``limper_count``,
``caller_count``, ``live_positions``, ``raise_level``, ``to_call_bb``,
``pot_before_bb``, ``pot_odds``, ``price_to_pot``, ``effective_stack_bb``,
``target_total_bb``, ``observed_sizing_bb``, ``action`` plus the ``hand_id`` /
``split`` identity keys.

Hole cards, showdown cards, board cards, opponent hand classes, raw action
history and any post-decision state are deliberately absent: the projection is
an explicit allowlist and the contract is ``additionalProperties: false``.

Certification is authoritative.  Records are loaded through the two existing,
already-audited loaders:

* ``tools.training.audit_hero_preflop_coverage.load_train_records`` for TRAIN,
* ``tools.training.fit_model_a_preflop_sizing.load_certified_split`` for
  VALIDATION.

``TEST`` is refused by this tool *and* by the reused loaders (fail-closed), so no
TEST hand can cross the parser boundary.  Splits are assigned per hand ID, so a
hand contributes to exactly one fold.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.datasets.build_hand_history_increment import fingerprint, sha256_file, split_for  # noqa: E402
from tools.training.audit_hero_preflop_coverage import (  # noqa: E402
    DEFAULT_CERTIFICATION,
    load_train_records,
)
from tools.training.fit_model_a_preflop_sizing import load_certified_split  # noqa: E402
from tools.training.increment_decisions import decision_rows, parse_hand  # noqa: E402

SCHEMA = "poker-generalized-response-dataset/v1"
CORPUS_SCHEMA = "poker-generalized-response-corpus-hashes/v1"
CERT_SCHEMA = "poker-population-certification/v1"

POPULATION_ID = "pokerstars_nlhe_100-200_zoom_play_6max_v1"
SPLITS = ("TRAIN", "VALIDATION")
FORBIDDEN_SPLITS = ("TEST",)
RESPONSE_ACTIONS = ("FOLD", "CALL", "RAISE", "JAM")
# A limp is a call of the current price before any raise; it is not its own
# response family.  CHECK is intentionally *not* a response family.
ACTION_EQUIVALENTS = {"LIMP": "CALL"}
NON_RESPONSE_ACTIONS = ("CHECK",)

OUTPUT_DIR = ROOT / "analysis/issue421_generalized_response/dataset"
DATASET_NAME = "GENERALIZED_RESPONSE_DATASET.jsonl"
MANIFEST_NAME = "GENERALIZED_RESPONSE_DATASET.json"
CORPUS_NAME = "CORPUS_HASHES.json"
SUMMARY_NAME = "SUMMARY.md"
INDEX_NAME = "ARTIFACTS.json"
CONTRACT_PATH = ROOT / "contracts/training/generalized-response-dataset.schema.json"

#: Exact, ordered allowlist of the public row projection.  Adding any other key
#: is a contract violation and fails closed.
ROW_FIELDS = (
    "hand_id",
    "split",
    "table_size",
    "family",
    "actor_position",
    "aggressor_position",
    "limper_count",
    "caller_count",
    "live_positions",
    "raise_level",
    "to_call_bb",
    "pot_before_bb",
    "pot_odds",
    "price_to_pot",
    "effective_stack_bb",
    "target_total_bb",
    "observed_sizing_bb",
    "action",
)

#: Tokens that must never appear as a row key.  ``hand_id`` legitimately
#: contains ``hand`` so the guard matches whole key names, not substrings.
FORBIDDEN_ROW_KEYS = frozenset(
    {
        "known_cards",
        "known_hand_class",
        "hand_class",
        "cards",
        "hole_cards",
        "hero_cards",
        "board",
        "boards",
        "history",
        "future_actions",
        "showdown",
        "is_hero",
        "player",
    }
)

LOADER_SOURCES = {
    "TRAIN": "tools/training/audit_hero_preflop_coverage.load_train_records",
    "VALIDATION": "tools/training/fit_model_a_preflop_sizing.load_certified_split",
}

#: Per-split counters, always present (even at zero) so the persisted accounting
#: matches the splitAccounting block of the contract.
SPLIT_COUNTERS = (
    "hands_parsed",
    "adverse_preflop_decisions",
    "response_rows",
    "hero_decisions_skipped",
    "non_preflop_decisions_skipped",
    "non_response_action_rows_skipped",
)


class TestSplitForbidden(ValueError):
    """Raised whenever a TEST split is requested from the fail-closed loader."""


class IllegalResponseAction(ValueError):
    """Raised when the observed action is outside the public legal space."""


def stable_hash(value: Any) -> str:
    """Byte-identical to the repo-wide ``stable_hash`` canonicalization."""
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(raw).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _round(value: Any, digits: int = 6) -> float | None:
    if value is None:
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x):
        return None
    rounded = round(x, digits)
    return 0.0 if rounded == 0 else rounded


def require_consumable_splits(splits: Sequence[str]) -> tuple[str, ...]:
    """Fail-closed split guard: only TRAIN/VALIDATION may ever be consumed."""
    requested = tuple(dict.fromkeys(str(s).strip().upper() for s in splits))
    if not requested:
        raise ValueError("at least one split must be requested")
    forbidden = [s for s in requested if s in FORBIDDEN_SPLITS]
    if forbidden:
        raise TestSplitForbidden(
            "TEST is forbidden: the generalized response dataset is limited to "
            f"{', '.join(SPLITS)} and fails closed on {', '.join(forbidden)}"
        )
    unknown = [s for s in requested if s not in SPLITS]
    if unknown:
        raise ValueError(f"unsupported split(s): {', '.join(unknown)}; allowed: {', '.join(SPLITS)}")
    return requested


def response_action(action: Any) -> str | None:
    """Normalize a parsed action into the response space, or ``None``."""
    value = str(action or "").strip().upper()
    value = ACTION_EQUIVALENTS.get(value, value)
    return value if value in RESPONSE_ACTIONS else None


def legal_response_actions(context: Mapping[str, Any]) -> list[str]:
    """Public legal action space projected onto ``FOLD/CALL/RAISE/JAM``."""
    out: list[str] = []
    for raw in context.get("legal_actions") or []:
        mapped = response_action(raw)
        if mapped is not None and mapped not in out:
            out.append(mapped)
    return out


def aggressor_position(history: Iterable[Mapping[str, Any]]) -> str | None:
    """Most recent raising/jamming position, i.e. the current aggressor."""
    latest: str | None = None
    for item in history or []:
        if str(item.get("action") or "").upper() in ("RAISE", "JAM"):
            latest = str(item.get("position") or "") or None
    return latest


def assert_public_row(row: Mapping[str, Any]) -> None:
    """Fail closed if a row leaks a private/future key or an undefined field."""
    keys = set(row)
    leaked = sorted(keys & FORBIDDEN_ROW_KEYS)
    if leaked:
        raise ValueError(f"private/future information leaked into response row: {leaked}")
    undeclared = sorted(keys - set(ROW_FIELDS))
    if undeclared:
        raise ValueError(f"undeclared response row fields: {undeclared}")
    missing = sorted(set(ROW_FIELDS) - keys)
    if missing:
        raise ValueError(f"missing response row fields: {missing}")
    if str(row.get("action")) not in RESPONSE_ACTIONS:
        raise ValueError(f"response row action outside {RESPONSE_ACTIONS}: {row.get('action')!r}")
    if str(row.get("split")) not in SPLITS:
        raise ValueError(f"response row split outside {SPLITS}: {row.get('split')!r}")
    for value in (row.get("to_call_bb"), row.get("pot_before_bb"), row.get("effective_stack_bb")):
        if value is None or not math.isfinite(float(value)):
            raise ValueError(f"non-finite public feature: {value!r}")


def project_response_row(row: Mapping[str, Any], *, split: str | None = None) -> dict[str, Any] | None:
    """Project one parsed decision row onto the public adverse-response contract.

    Returns ``None`` for rows that are not adverse preflop responses (Hero rows,
    non-preflop streets, free-check rows).  Raises ``IllegalResponseAction`` when
    the observed action falls outside the public legal action space.
    """
    if not isinstance(row, Mapping):
        raise TypeError("decision row must be a mapping")
    row_split = str(row.get("split") or "").upper()
    if split is not None and row_split != str(split).upper():
        raise AssertionError(f"non-{split} decision row crossed the response builder")
    if str(row.get("street") or "").upper() != "PREFLOP":
        return None
    if row.get("is_hero"):
        return None
    action = response_action(row.get("action"))
    if action is None:
        return None
    context = row.get("preflop_context_v1")
    if not isinstance(context, Mapping):
        raise ValueError(f"decision row {row.get('hand_id')!r} is missing preflop_context_v1")
    legal = legal_response_actions(context)
    if action not in legal:
        raise IllegalResponseAction(
            f"observed action {action} is not legal in public context "
            f"{context.get('context_id')!r} (legal: {legal})"
        )
    to_call = _round(context.get("to_call_bb"))
    pot_before = _round(context.get("pot_before_bb"))
    if to_call is None or pot_before is None:
        raise ValueError(
            f"decision row {row.get('hand_id')!r} has a non-finite public price "
            f"(to_call_bb={context.get('to_call_bb')!r}, pot_before_bb={context.get('pot_before_bb')!r})"
        )
    sizing = row.get("action_sizing_v1") or {}
    projected = {
        "hand_id": str(row.get("hand_id")),
        "split": row_split,
        "table_size": int(context.get("table_size") or 0),
        "family": str(row.get("family") or ""),
        "actor_position": str(context.get("actor_position") or row.get("actor_position") or ""),
        "aggressor_position": aggressor_position(row.get("history") or []),
        "limper_count": len(context.get("limper_positions") or []),
        "caller_count": len(context.get("caller_positions") or []),
        "live_positions": [str(p) for p in context.get("live_positions") or []],
        "raise_level": int(row.get("raise_level") or 0),
        "to_call_bb": to_call,
        "pot_before_bb": pot_before,
        "pot_odds": _round(to_call / (pot_before + to_call)) if (pot_before + to_call) > 0 else None,
        "price_to_pot": _round(to_call / pot_before) if pot_before > 0 else None,
        "effective_stack_bb": _round(context.get("effective_stack_bb")),
        "target_total_bb": _round(sizing.get("target_total_bb")) if action in ("RAISE", "JAM") else None,
        "observed_sizing_bb": _round(sizing.get("incremental_cost_bb")) if action in ("RAISE", "JAM") else None,
        "action": action,
    }
    assert_public_row(projected)
    return projected


def iter_response_rows(records: Sequence[Any], split: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Parse certified records of one split and emit the public response rows."""
    expected = str(split).upper()
    if expected in FORBIDDEN_SPLITS:
        raise TestSplitForbidden(f"refusing to parse {expected} records")
    rows: list[dict[str, Any]] = []
    counters: collections.Counter[str] = collections.Counter({name: 0 for name in SPLIT_COUNTERS})
    for record in records:
        hand_id = str(getattr(record, "hand_id"))
        actual = split_for(hand_id)
        if actual != expected:
            raise AssertionError(f"non-{expected} record crossed the loader boundary: {hand_id}")
        hand = parse_hand(record.text, record.source_file)
        if not hand:
            raise ValueError(f"{expected} hand failed normalization: {hand_id}")
        counters["hands_parsed"] += 1
        for row in decision_rows(hand, include_preflop_context_v1=True):
            if str(row.get("split") or "").upper() != expected:
                raise AssertionError("non-split decision row produced")
            if str(row.get("street") or "").upper() != "PREFLOP":
                counters["non_preflop_decisions_skipped"] += 1
                continue
            if row.get("is_hero"):
                counters["hero_decisions_skipped"] += 1
                continue
            counters["adverse_preflop_decisions"] += 1
            projected = project_response_row(row, split=expected)
            if projected is None:
                counters["non_response_action_rows_skipped"] += 1
                continue
            rows.append(projected)
    counters["response_rows"] = len(rows)
    return rows, dict(counters)


def load_certified_records(
    splits: Sequence[str] = SPLITS,
    certification: Path = DEFAULT_CERTIFICATION,
) -> tuple[dict[str, list[Any]], dict[str, Any]]:
    """Load certified records through the two existing loaders (fail-closed)."""
    requested = require_consumable_splits(splits)
    certification = Path(certification)
    certification_data = json.loads(certification.read_text(encoding="utf-8"))
    if certification_data.get("schema") != CERT_SCHEMA:
        raise ValueError(f"unexpected certification schema: {certification_data.get('schema')!r}")
    admissible = (certification_data.get("status") or {}).get("ADMISSIBLE") or {}
    split_counts = admissible.get("split_counts") or {}

    records: dict[str, list[Any]] = {}
    evidence: dict[str, Any] = {}
    for split in requested:
        if split == "TRAIN":
            loaded, provenance = load_train_records(certification)
        else:
            loaded, provenance = load_certified_split(split)
        hand_ids = [str(record.hand_id) for record in loaded]
        expected_count = int(split_counts.get(split) or 0)
        if len(hand_ids) != expected_count:
            raise ValueError(f"{split} loader returned {len(hand_ids)} hands, expected {expected_count}")
        records[split] = loaded
        evidence[split] = {
            "loader": LOADER_SOURCES[split],
            "hands": len(hand_ids),
            "hand_ids_fingerprint_sha256": fingerprint(hand_ids),
            "loader_provenance": provenance,
        }
    corpus = {
        "schema": CORPUS_SCHEMA,
        "population_id": POPULATION_ID,
        "certification": {
            "path": certification.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(certification),
            "certification_schema": CERT_SCHEMA,
        },
        "archives": [
            {"path": str(a.get("path") or ""), "sha256": str(a.get("sha256") or "")}
            for a in certification_data.get("archives") or []
        ],
        "population_fingerprint_sha256": str(admissible.get("fingerprint_sha256") or ""),
        "certified_hands": int(admissible.get("unique_hands") or 0),
        "certified_split_counts": {
            name: int(split_counts.get(name) or 0) for name in ("TRAIN", "VALIDATION", "TEST")
        },
        "consumed_splits": list(requested),
        "refused_splits": [name for name in FORBIDDEN_SPLITS],
        "test_hands_consumed": 0,
        "loader_evidence": evidence,
    }
    return records, corpus


def collect_rows(
    records: Mapping[str, Sequence[Any]],
    splits: Sequence[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Emit deterministically ordered rows and per-split accounting."""
    rows: list[dict[str, Any]] = []
    accounting: dict[str, Any] = {}
    hand_split: dict[str, str] = {}
    totals: collections.Counter[str] = collections.Counter()
    for split in splits:
        split_rows, counters = iter_response_rows(records[split], split)
        accounting[split] = {
            "hand_ids_fingerprint_sha256": fingerprint([str(r.hand_id) for r in records[split]]),
            **counters,
        }
        for row in split_rows:
            hand_id = row["hand_id"]
            seen = hand_split.setdefault(hand_id, split)
            if seen != split:
                raise AssertionError(f"hand {hand_id} contributes to two folds: {seen} and {split}")
            rows.append(row)
        totals.update(counters)
    ordered = sorted(rows, key=lambda r: (int(r["hand_id"]), r["split"]))
    accounting["total"] = {
        "hands_loaded": sum(len(records[s]) for s in splits),
        "hands_parsed": int(totals["hands_parsed"]),
        "adverse_preflop_decisions": int(totals["adverse_preflop_decisions"]),
        "response_rows": len(ordered),
        "hero_decisions_skipped": int(totals["hero_decisions_skipped"]),
        "non_preflop_decisions_skipped": int(totals["non_preflop_decisions_skipped"]),
        "non_response_action_rows_skipped": int(totals["non_response_action_rows_skipped"]),
        "distinct_hands": len(hand_split),
        "test_hands_consumed": 0,
    }
    for split in splits:
        if accounting[split]["hands_parsed"] != len(records[split]):
            raise AssertionError(f"{split} accounting mismatch")
    return ordered, accounting


def dataset_payload(rows: Sequence[Mapping[str, Any]]) -> bytes:
    """Canonical JSON Lines payload (one row per line, sorted keys)."""
    lines = [
        json.dumps(dict(row), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
        for row in rows
    ]
    return ("\n".join(lines) + "\n").encode() if lines else b""


def build(
    certification: Path = DEFAULT_CERTIFICATION,
    splits: Sequence[str] = SPLITS,
) -> dict[str, Any]:
    requested = require_consumable_splits(splits)
    records, corpus = load_certified_records(requested, certification)
    rows, accounting = collect_rows(records, requested)
    payload = dataset_payload(rows)
    rows_by_split = collections.Counter(str(r["split"]) for r in rows)
    corpus["response_rows_by_split"] = {split: int(rows_by_split.get(split, 0)) for split in requested}
    corpus["response_rows_total"] = len(rows)
    manifest = {
        "schema": SCHEMA,
        "population_id": POPULATION_ID,
        "builder": {
            "path": Path(__file__).resolve().relative_to(ROOT).as_posix(),
            "sha256": sha256_file(Path(__file__).resolve()),
        },
        "scope": {
            "consumed_splits": list(requested),
            "refused_splits": list(FORBIDDEN_SPLITS),
            "test_consumed": False,
            "state_timing": "BEFORE_ACTION",
            "player_role": "ADVERSE_NON_HERO",
            "response_actions": list(RESPONSE_ACTIONS),
            "excluded_actions": list(NON_RESPONSE_ACTIONS),
            "public_only": True,
            "hole_cards_consumed": False,
            "future_information_consumed": False,
            "purpose": "public-only generalized adverse preflop response dataset (issue #421)",
        },
        "contract": {
            "path": CONTRACT_PATH.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(CONTRACT_PATH),
        },
        "corpus": {
            "path": CORPUS_NAME,
            "sha256": sha256_bytes(canonical_bytes(corpus)),
            "population_fingerprint_sha256": corpus["population_fingerprint_sha256"],
            "certification_sha256": corpus["certification"]["sha256"],
        },
        "dataset": {
            "path": DATASET_NAME,
            "format": "application/x-ndjson",
            "sha256": sha256_bytes(payload),
            "bytes": len(payload),
            "rows": len(rows),
            "canonical_payload_sha256": sha256_bytes(payload),
            "field_order_independent": True,
        },
        "splits": {
            split: {
                "hands": accounting[split]["hands_parsed"],
                "hand_ids_fingerprint_sha256": accounting[split]["hand_ids_fingerprint_sha256"],
                "response_rows": accounting[split]["response_rows"],
            }
            for split in requested
        },
        "accounting": accounting,
        "row_contract": {
            "fields": list(ROW_FIELDS),
            "additional_properties": False,
            "forbidden_keys": sorted(FORBIDDEN_ROW_KEYS),
        },
    }
    return {
        "rows": rows,
        "payload": payload,
        "corpus": corpus,
        "manifest": manifest,
        "accounting": accounting,
    }


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()


def summary_text(result: Mapping[str, Any]) -> str:
    manifest = result["manifest"]
    corpus = result["corpus"]
    dataset = manifest["dataset"]
    total = manifest["accounting"]["total"]
    lines = [
        "# #421 — generalized public-only adverse-response preflop dataset",
        "",
        "Versioned, byte-reproducible dataset of **adverse (non-Hero)** preflop",
        f"responses over the action space `{'/'.join(RESPONSE_ACTIONS)}`, restricted to the",
        f"certified **{' + '.join(SPLITS)}** folds. `TEST` is refused by the loader (fail-closed).",
        "",
        "## Scope",
        "",
        f"- Certified admissible hands: **{corpus['certified_hands']:,}** "
        f"(TRAIN {corpus['certified_split_counts']['TRAIN']:,} + "
        f"VALIDATION {corpus['certified_split_counts']['VALIDATION']:,} + TEST "
        f"{corpus['certified_split_counts']['TEST']:,})",
        f"- Consumed folds: **{', '.join(corpus['consumed_splits'])}** — certified TEST hands "
        f"present but never consumed: **{corpus['certified_split_counts']['TEST']:,}**",
        f"- Hands parsed: **{total['hands_parsed']:,}** across "
        f"**{total['distinct_hands']:,}** hand IDs (one fold per hand ID)",
        f"- Adverse preflop decisions: **{total['adverse_preflop_decisions']:,}**",
        f"- Emitted response rows: **{total['response_rows']:,}**",
        f"- Hero decisions excluded: **{total['hero_decisions_skipped']:,}**",
        f"- Free-check (non-response) rows excluded: **{total['non_response_action_rows_skipped']:,}**",
        "",
        "Every emitted row carries only public information available immediately",
        "before the observed action; no hole card, board card, opponent hand class,",
        "raw history or future action enters the projection.",
        "",
        "Information boundary: `hand_id`, `split`, `table_size`, `family`,",
        "`actor_position`, `aggressor_position`, `limper_count`, `caller_count`,",
        "`live_positions`, `raise_level`, `to_call_bb`, `pot_before_bb`, `pot_odds`,",
        "`price_to_pot` and `effective_stack_bb` describe the public state immediately",
        "before the action; `action` plus `target_total_bb` / `observed_sizing_bb`",
        "describe the observed response itself.",
        "",
        "## Artifacts",
        "",
        f"- `{DATASET_NAME}` — {dataset['rows']:,} canonical JSON Lines rows, "
        f"{dataset['bytes']:,} bytes, SHA256 `{dataset['sha256']}`",
        f"- `{MANIFEST_NAME}` — scope, contract link, corpus/loader evidence and accounting",
        f"- `{CORPUS_NAME}` — certification and archive hashes plus per-split hand-ID fingerprints",
        f"- `{CONTRACT_PATH.relative_to(ROOT).as_posix()}` — row/manifest/corpus feature contract",
        "",
        "## Corpus hashes",
        "",
        f"- Certification: `{corpus['certification']['path']}` "
        f"SHA256 `{corpus['certification']['sha256']}`",
        f"- Population fingerprint: `{corpus['population_fingerprint_sha256']}`",
    ]
    for archive in corpus["archives"]:
        lines.append(f"- Archive `{archive['path']}` SHA256 `{archive['sha256']}`")
    lines += ["", "## Per-split identity", "", "| Split | Hands | Hand-ID fingerprint SHA256 | Response rows |", "|---|---:|---|---:|"]
    for split, block in manifest["splits"].items():
        lines.append(
            f"| {split} | {block['hands']:,} | `{block['hand_ids_fingerprint_sha256']}` | {block['response_rows']:,} |"
        )
    lines += [
        "",
        "## Reproduction",
        "",
        "```",
        "python3 tools/training/build_generalized_response_dataset.py",
        "python3 tools/training/build_generalized_response_dataset.py --verify",
        "```",
        "",
        "The builder re-verifies certification and archive SHA256 identities, filters",
        "to certified TRAIN/VALIDATION hand IDs before normalization, and writes",
        "canonical JSON Lines, so a regeneration is byte-identical.",
        "",
        "The guard suite `tests/training/test_build_generalized_response_dataset.py`",
        "verifies the contract, the fail-closed TEST refusal and the persisted hashes;",
        "set `POKER_GENERALIZED_RESPONSE_FULL_REGEN=1` to also re-parse the whole",
        "certified corpus and assert byte-identical regeneration.",
        "",
    ]
    return "\n".join(lines)


def persist(output: Path, result: Mapping[str, Any]) -> dict[str, Any]:
    """Content-addressed write of the dataset, corpus hashes, manifest, summary."""
    output.mkdir(parents=True, exist_ok=True)
    objects = output / "sha256"
    objects.mkdir(exist_ok=True)
    index: dict[str, Any] = {}
    referenced: set[str] = set()

    dataset_bytes = result["payload"]
    (output / DATASET_NAME).write_bytes(dataset_bytes)
    dataset_digest = sha256_bytes(dataset_bytes)
    # The dataset is the one large artifact of this bundle: it is addressed by
    # its byte SHA256 in the index below but deliberately not duplicated into
    # ``sha256/`` (a second copy would double a ~40 MB repository payload).
    index[DATASET_NAME] = {
        "sha256": dataset_digest,
        "bytes": len(dataset_bytes),
        "rows": result["manifest"]["dataset"]["rows"],
        "object": None,
        "content_addressed": False,
    }

    for name, value in ((CORPUS_NAME, result["corpus"]), (MANIFEST_NAME, result["manifest"])):
        data = canonical_bytes(value)
        digest = sha256_bytes(data)
        (output / name).write_bytes(data)
        (objects / (digest + ".json")).write_bytes(data)
        index[name] = {
            "sha256": digest,
            "canonical_payload_sha256": stable_hash(value),
            "object": "sha256/" + digest + ".json",
        }
        referenced.add(digest + ".json")

    data = summary_text(result).encode()
    digest = sha256_bytes(data)
    (output / SUMMARY_NAME).write_bytes(data)
    (objects / (digest + ".md")).write_bytes(data)
    index[SUMMARY_NAME] = {"sha256": digest, "object": "sha256/" + digest + ".md"}
    referenced.add(digest + ".md")

    (output / INDEX_NAME).write_text(json.dumps(index, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    for path in objects.iterdir():
        if path.is_file() and path.name not in referenced:
            path.unlink()
    return index


def verify_persisted(output: Path = OUTPUT_DIR) -> dict[str, Any]:
    """Rebuild in memory and compare byte-for-byte with the persisted dataset."""
    result = build()
    persisted = (output / DATASET_NAME).read_bytes()
    index = json.loads((output / INDEX_NAME).read_text(encoding="utf-8"))
    report = {
        "persisted_sha256": sha256_bytes(persisted),
        "regenerated_sha256": sha256_bytes(result["payload"]),
        "byte_identical": persisted == result["payload"],
    }
    if not report["byte_identical"]:
        raise ValueError(f"regeneration is not byte-identical: {report}")
    if index[DATASET_NAME]["sha256"] != report["persisted_sha256"]:
        raise ValueError("persisted dataset sha256 disagrees with the artifact index")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--certification", type=Path, default=DEFAULT_CERTIFICATION)
    parser.add_argument("--split", action="append", dest="splits",
                        help=f"split(s) to consume (default: {' and '.join(SPLITS)}); TEST is refused")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--print-json", action="store_true")
    parser.add_argument("--verify", action="store_true",
                        help="rebuild in memory and assert byte-identical regeneration")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    certification = args.certification if args.certification.is_absolute() else ROOT / args.certification
    output = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    splits = tuple(args.splits) if args.splits else SPLITS
    if args.verify:
        print(json.dumps(verify_persisted(output), sort_keys=True, indent=2))
        return 0
    result = build(certification=certification, splits=splits)
    index = persist(output, result)
    if args.print_json:
        print(canonical_bytes(result["manifest"]).decode())
        return 0
    print(json.dumps(
        {
            "output_dir": output.relative_to(ROOT).as_posix() if output.is_relative_to(ROOT) else str(output),
            "dataset": result["manifest"]["dataset"],
            "splits": result["manifest"]["splits"],
            "accounting": result["manifest"]["accounting"]["total"],
            "artifacts": sorted(index),
        },
        sort_keys=True,
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

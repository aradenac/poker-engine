#!/usr/bin/env python3
"""Build leakage-safe player behavioural features for independent opponent model B.

The builder consumes immutable raw hand-history archives, scopes them by stake,
deduplicates by PokerStars hand ID, and uses TRAIN hands only to fit player
behaviour. It intentionally does not import or reuse analyser population model A.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from tools.datasets.build_hand_history_increment import (  # noqa: E402
    HandRecord,
    parse_hand_blocks,
    sha256_file,
    split_for,
)
import zipfile  # noqa: E402

SCHEMA = "independent-profile-player-features/v1"
FEATURE_VERSION = "model-b-player-features-v1"

SEAT_RE = re.compile(r"^(?:Seat|Siège)\s+(\d+)\s*:\s*(.+?)\s+\([^)]*\)\s*$", re.I)
ACTOR_RE = re.compile(r"^(.+?)\s*:\s*(.+)$")

STREET_MARKERS = {
    "*** FLOP ***": "flop",
    "*** TURN ***": "turn",
    "*** TOURNANT ***": "turn",
    "*** RIVER ***": "river",
    "*** RIVIÈRE ***": "river",
    "*** RIVIERE ***": "river",
}

IGNORED_PREFIXES = (
    "posts ", "poste ", "shows ", "montre ", "mucks ", "jette ",
    "collected ", "a remporté ", "doesn't show", "ne montre pas",
)


def decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def classify_action(body: str) -> str | None:
    value = body.strip().lower()
    if value.startswith(("folds", "se couche")):
        return "fold"
    if value.startswith(("checks", "parole")):
        return "check"
    if value.startswith(("calls", "suit ", "suit")):
        return "call"
    if value.startswith(("bets", "mise ", "mise")):
        return "bet"
    if value.startswith(("raises", "relance ", "relance")):
        return "raise"
    return None


def extract_seated_players(text: str) -> list[str]:
    players: list[str] = []
    seen: set[str] = set()
    for raw in text.replace("\r", "").splitlines():
        if raw.startswith("***"):
            break
        m = SEAT_RE.match(raw.strip())
        if m:
            player = m.group(2).strip()
            if player not in seen:
                players.append(player)
                seen.add(player)
    return players


def merge_archives(paths: list[Path], stakes: set[str]) -> tuple[dict[str, HandRecord], dict]:
    by_id: dict[str, HandRecord] = {}
    sources: list[dict] = []
    duplicates = 0
    conflicting_payloads = 0
    english_preferred_replacements = 0

    for path in paths:
        parsed = 0
        scoped = 0
        with zipfile.ZipFile(path) as zf:
            infos = [i for i in zf.infolist() if not i.is_dir()]
            for info in infos:
                for record in parse_hand_blocks(decode_text(zf.read(info)), info.filename):
                    parsed += 1
                    if record.stake not in stakes:
                        continue
                    scoped += 1
                    existing = by_id.get(record.hand_id)
                    if existing is None:
                        by_id[record.hand_id] = record
                        continue
                    duplicates += 1
                    if hashlib.sha256(existing.text.encode()).digest() != hashlib.sha256(record.text.encode()).digest():
                        conflicting_payloads += 1
                    # Prefer an English rendering for the same hand ID when one is
                    # available; action semantics are unchanged and EN parsing is
                    # less ambiguous. Otherwise preserve first-source precedence.
                    if existing.language != "en" and record.language == "en":
                        by_id[record.hand_id] = record
                        english_preferred_replacements += 1
        sources.append({
            "path": path.as_posix(),
            "sha256": sha256_file(path),
            "parsed_hands": parsed,
            "scoped_hands": scoped,
        })

    split_counts = Counter(split_for(hid) for hid in by_id)
    return by_id, {
        "archives": sources,
        "scope": {"stakes": sorted(stakes)},
        "unique_scoped_hands": len(by_id),
        "split_counts": dict(sorted(split_counts.items())),
        "overlap_occurrences": duplicates,
        "overlap_payload_differences": conflicting_payloads,
        "english_preferred_replacements": english_preferred_replacements,
        "sorted_hand_ids_sha256": hashlib.sha256("\n".join(sorted(by_id)).encode()).hexdigest(),
    }


def new_counter() -> defaultdict[str, int]:
    return defaultdict(int)


def update_hand_features(
    record: HandRecord,
    features: dict[str, defaultdict[str, int]],
    exclude: set[str],
    parser_stats: Counter,
    unmatched_samples: dict[str, list[str]],
) -> None:
    players = extract_seated_players(record.text)
    player_set = set(players)
    if not players:
        parser_stats[f"{record.language}|hands_without_seats"] += 1
        return

    for player in players:
        if player not in exclude:
            features[player]["appearances"] += 1

    street = "preflop"
    prior_raise = False
    first_preflop_decision: set[str] = set()
    vpip: set[str] = set()
    pfr: set[str] = set()
    limp: set[str] = set()
    threebet_opp: set[str] = set()
    threebet: set[str] = set()
    post_price_open = False
    last_aggressor: str | None = None

    for raw in record.text.replace("\r", "").splitlines():
        line = raw.strip()
        for marker, next_street in STREET_MARKERS.items():
            if line.startswith(marker):
                street = next_street
                post_price_open = False
                last_aggressor = None
                break

        m = ACTOR_RE.match(line)
        if not m:
            continue
        actor = m.group(1).strip()
        body = m.group(2).strip()
        if actor not in player_set:
            continue
        low = body.lower()
        if low.startswith(IGNORED_PREFIXES):
            continue

        action = classify_action(body)
        if action is None:
            # Only audit actor-looking lines before SUMMARY; seat/summary lines do
            # not have an actor name equal to a seated player.
            parser_stats[f"{record.language}|unmatched_actor_lines"] += 1
            bucket = unmatched_samples.setdefault(record.language, [])
            if len(bucket) < 20 and body not in bucket:
                bucket.append(body)
            continue

        parser_stats[f"{record.language}|recognized_actions"] += 1
        if actor in exclude:
            # Hero is not used to fit opponent profiles, but its action must still
            # update betting state so following opponent responses are interpreted.
            pass

        if street == "preflop":
            if actor not in first_preflop_decision:
                first_preflop_decision.add(actor)
                if prior_raise and actor not in exclude:
                    threebet_opp.add(actor)
            if action in {"call", "bet", "raise"}:
                vpip.add(actor)
            if action in {"bet", "raise"}:
                pfr.add(actor)
            if action == "call" and not prior_raise:
                limp.add(actor)
            if action == "raise":
                if prior_raise:
                    threebet.add(actor)
                prior_raise = True
            continue

        if actor not in exclude:
            features[actor][f"post_{action}"] += 1
            features[actor]["post_decisions"] += 1
            if action in {"bet", "raise"}:
                features[actor]["post_aggressive_actions"] += 1

            if post_price_open and actor != last_aggressor and action in {"fold", "call", "raise"}:
                features[actor]["post_face_aggression_opportunities"] += 1
                features[actor][f"post_face_aggression_{action}"] += 1

        if action in {"bet", "raise"}:
            post_price_open = True
            last_aggressor = actor

    for player in players:
        if player in exclude:
            continue
        f = features[player]
        if player in vpip:
            f["vpip_hands"] += 1
        if player in pfr:
            f["pfr_hands"] += 1
        if player in limp:
            f["limp_hands"] += 1
        if player in threebet_opp:
            f["threebet_opportunities"] += 1
        if player in threebet:
            f["threebet_hands"] += 1


def rate(num: int, den: int) -> float | None:
    return num / den if den else None


def shrunk(num: int, den: int, global_rate: float, strength: float) -> float:
    return (num + strength * global_rate) / (den + strength)


def build_output(
    by_id: dict[str, HandRecord],
    provenance: dict,
    exclude: set[str],
    min_hands: int,
    prior_strength: float,
) -> dict:
    features: dict[str, defaultdict[str, int]] = defaultdict(new_counter)
    parser_stats: Counter = Counter()
    unmatched_samples: dict[str, list[str]] = {}

    train_records = [record for hid, record in by_id.items() if split_for(hid) == "TRAIN"]
    for record in train_records:
        update_hand_features(record, features, exclude, parser_stats, unmatched_samples)

    totals = Counter()
    for f in features.values():
        totals.update(f)

    global_rates = {
        "vpip": rate(totals["vpip_hands"], totals["appearances"]) or 0.0,
        "pfr": rate(totals["pfr_hands"], totals["appearances"]) or 0.0,
        "limp": rate(totals["limp_hands"], totals["appearances"]) or 0.0,
        "threebet": rate(totals["threebet_hands"], totals["threebet_opportunities"]) or 0.0,
        "post_aggression_frequency": rate(totals["post_aggressive_actions"], totals["post_decisions"]) or 0.0,
        "post_fold_facing_aggression": rate(
            totals["post_face_aggression_fold"], totals["post_face_aggression_opportunities"]
        ) or 0.0,
    }

    players = []
    for player in sorted(features):
        f = features[player]
        rates = {
            "vpip": rate(f["vpip_hands"], f["appearances"]),
            "pfr": rate(f["pfr_hands"], f["appearances"]),
            "limp": rate(f["limp_hands"], f["appearances"]),
            "threebet": rate(f["threebet_hands"], f["threebet_opportunities"]),
            "post_aggression_frequency": rate(f["post_aggressive_actions"], f["post_decisions"]),
            "post_fold_facing_aggression": rate(
                f["post_face_aggression_fold"], f["post_face_aggression_opportunities"]
            ),
        }
        shrunk_rates = {
            "vpip": shrunk(f["vpip_hands"], f["appearances"], global_rates["vpip"], prior_strength),
            "pfr": shrunk(f["pfr_hands"], f["appearances"], global_rates["pfr"], prior_strength),
            "limp": shrunk(f["limp_hands"], f["appearances"], global_rates["limp"], prior_strength),
            "threebet": shrunk(
                f["threebet_hands"], f["threebet_opportunities"], global_rates["threebet"], prior_strength
            ),
            "post_aggression_frequency": shrunk(
                f["post_aggressive_actions"], f["post_decisions"],
                global_rates["post_aggression_frequency"], prior_strength
            ),
            "post_fold_facing_aggression": shrunk(
                f["post_face_aggression_fold"], f["post_face_aggression_opportunities"],
                global_rates["post_fold_facing_aggression"], prior_strength
            ),
        }
        players.append({
            "player": player,
            "eligible_default": f["appearances"] >= min_hands,
            "counts": dict(sorted(f.items())),
            "rates": rates,
            "shrunk_rates": shrunk_rates,
        })

    language_counts = Counter(r.language for r in train_records)
    return {
        "schema": SCHEMA,
        "feature_version": FEATURE_VERSION,
        "independence_contract": "TRAIN hand histories only; no analyser/model-A predictions or policies are inputs",
        "provenance": provenance,
        "split_used_for_fit": "TRAIN",
        "train_unique_hands": len(train_records),
        "train_language_counts": dict(sorted(language_counts.items())),
        "excluded_players": sorted(exclude),
        "default_min_hands_for_profile_fit": min_hands,
        "shrinkage": {
            "method": "empirical global-rate pseudo-observations",
            "prior_strength": prior_strength,
            "global_rates": global_rates,
        },
        "parser_audit": {
            "counts": dict(sorted(parser_stats.items())),
            "unmatched_samples": unmatched_samples,
        },
        "players_total": len(players),
        "players_eligible_default": sum(1 for p in players if p["eligible_default"]),
        "players": players,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, action="append", required=True)
    parser.add_argument("--stake", action="append", default=["100/200"])
    parser.add_argument("--exclude-player", action="append", default=[])
    parser.add_argument("--min-hands", type=int, default=30)
    parser.add_argument("--prior-strength", type=float, default=40.0)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args()

    by_id, provenance = merge_archives(args.archive, set(args.stake))
    output = build_output(
        by_id,
        provenance,
        set(args.exclude_player),
        args.min_hands,
        args.prior_strength,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary = {
        "schema": output["schema"],
        "feature_version": output["feature_version"],
        "unique_scoped_hands": provenance["unique_scoped_hands"],
        "split_counts": provenance["split_counts"],
        "train_unique_hands": output["train_unique_hands"],
        "players_total": output["players_total"],
        "players_eligible_default": output["players_eligible_default"],
        "global_rates": output["shrinkage"]["global_rates"],
        "parser_audit": output["parser_audit"],
    }
    if args.summary:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

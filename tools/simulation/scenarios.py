#!/usr/bin/env python3
"""Deterministic scenario generation for one explicit poker population."""

from __future__ import annotations

import collections
import hashlib
import json
import re
from pathlib import Path
from typing import Iterable

from tools.datasets.build_hand_history_increment import split_for
from tools.populations.registry import namespace_path, resolve_population
from tools.training.independent_profiles.build_model_b import (
    amount,
    apply_event,
    parse_hand,
    postflop_order,
    preflop_summary,
)
from tools.training.independent_profiles.build_player_features import merge_archives
from tools.simulation.model_b_runtime import ModelBEnvironment, cid, ccode, hseed

ROOT = Path(__file__).resolve().parents[2]
SEAT_STACK_RE = re.compile(r"^(?:Seat|Siège|Siege|Place)\s+(\d+)\s*:\s*(.+?)\s+\(([^)]*)\)\s*$", re.I)
FLOP_RE = re.compile(r"\*\*\* FLOP \*\*\* \[([^]]+)\]", re.I)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def blind_from_stake(stake: str | None) -> float:
    if not stake or "/" not in stake:
        raise ValueError(f"cannot determine big blind from stake {stake!r}")
    raw = stake.split("/")[-1].strip()
    value = amount(raw)
    if value is None or value <= 0:
        raise ValueError(f"invalid big blind in stake {stake!r}")
    return float(value)


def flop_cards(raw: str) -> list[str]:
    match = FLOP_RE.search(raw)
    if not match:
        return []
    cards = match.group(1).split()
    return cards if len(cards) == 3 else []


def seat_stacks(raw: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for line in raw.replace("\r", "").splitlines():
        if line.startswith("***"):
            break
        match = SEAT_STACK_RE.match(line.strip())
        if not match:
            continue
        descriptor = match.group(3)
        nums = re.findall(r"\d[\d\s.,]*", descriptor)
        if not nums:
            continue
        value = amount(nums[0])
        if value is not None and value > 0:
            out[match.group(2).strip()] = float(value)
    return out


def preflop_contributions(hand: dict) -> tuple[dict[str, float], set[str], set[str], float]:
    paid: dict[str, float] = collections.defaultdict(float)
    active = set(hand["players"])
    allin: set[str] = set()
    pot = 0.0
    price = 0.0
    for event in hand["events"]["preflop"]:
        pot, price, _ = apply_event(event, paid, pot, price)
        if event["type"] == "fold":
            active.discard(event["player"])
        if event.get("allin"):
            allin.add(event["player"])
    return dict(paid), active, allin, pot


def _one_zip(source_dir: Path) -> Path | None:
    zips = sorted(source_dir.glob("*.zip"))
    if not zips:
        return None
    if len(zips) != 1:
        raise RuntimeError(f"expected at most one ZIP in {source_dir}, found {len(zips)}")
    return zips[0]


def dataset_from_population(
    population_id: str,
    root: Path = ROOT,
) -> tuple[list[Path], set[str], dict]:
    population = resolve_population(root, population_id)
    data = population["data"]
    baseline_raw = data.get("baseline_archive")
    if not baseline_raw:
        raise RuntimeError(f"population {population_id} has no materialized baseline archive")
    baseline = root / str(baseline_raw)
    if not baseline.is_file():
        raise RuntimeError(f"population baseline archive missing: {baseline}")

    archives = [baseline]
    snapshots_root = namespace_path(root, population, "snapshots")
    if snapshots_root.is_dir():
        candidates = []
        for directory in sorted(p for p in snapshots_root.iterdir() if p.is_dir()):
            archive = _one_zip(directory / "source")
            if archive is not None:
                candidates.append(archive)
        if candidates and candidates[-1] not in archives:
            archives.append(candidates[-1])

    stake = str(population["identity"]["stake"])
    return archives, {stake}, {
        "population_id": population_id,
        "population_status": population["status"],
        "dataset_id": data["dataset_id"],
        "identity": population["identity"],
        "cache_namespace": population["storage"]["cache_namespace"],
    }


def eligible_base_scenarios(
    *,
    population_id: str,
    root: Path = ROOT,
    hero: str = "RoiDePiqueNique",
    split: str = "TEST",
    stakes: set[str] | None = None,
    archives: Iterable[Path] | None = None,
) -> tuple[list[dict], dict]:
    population = resolve_population(root, population_id)
    if archives is None:
        archive_paths, default_stakes, dataset_meta = dataset_from_population(population_id, root)
    else:
        archive_paths = [Path(path) for path in archives]
        default_stakes = {str(population["identity"]["stake"])}
        dataset_meta = {
            "population_id": population_id,
            "population_status": population["status"],
            "dataset_id": "explicit_archives",
            "identity": population["identity"],
            "cache_namespace": population["storage"]["cache_namespace"],
        }
    stakes = set(stakes or default_stakes)
    records, provenance = merge_archives(archive_paths, stakes)
    out: list[dict] = []
    audit = collections.Counter()

    for hand_id in sorted(records):
        if split_for(hand_id) != split.upper():
            continue
        record = records[hand_id]
        hand = parse_hand(record)
        if hand is None:
            audit["unparsed"] += 1
            continue
        if hero not in hand["players"] or hero not in hand["known_cards"]:
            audit["hero_missing"] += 1
            continue
        flop = flop_cards(record.text)
        if len(flop) != 3:
            audit["no_flop"] += 1
            continue
        roles_pot = preflop_summary(hand)
        pot_type, roles = roles_pot[0], roles_pot[1]
        paid, active, allin, pot = preflop_contributions(hand)
        if len(active) != 2 or hero not in active:
            audit["not_heads_up_flop"] += 1
            continue
        if allin:
            audit["preflop_allin"] += 1
            continue
        opponent = next(player for player in active if player != hero)
        stacks = seat_stacks(record.text)
        if hero not in stacks or opponent not in stacks:
            audit["stack_missing"] += 1
            continue
        bb = blind_from_stake(record.stake)
        order = postflop_order(hand, active)
        if len(order) != 2:
            audit["bad_postflop_order"] += 1
            continue
        out.append({
            "population_id": population_id,
            "hand_id": str(hand_id),
            "source_file": record.source_file,
            "source_language": record.language,
            "stake": record.stake,
            "big_blind_chips": bb,
            "raw_hand": record.text,
            "raw_hand_sha256": sha256_text(record.text),
            "hero": hero,
            "opponent": opponent,
            "hero_cards": list(hand["known_cards"][hero]),
            "flop": flop,
            "positions": {hero: hand["positions"].get(hero, "NA"), opponent: hand["positions"].get(opponent, "NA")},
            "preflop_roles": {hero: roles.get(hero, "OTHER"), opponent: roles.get(opponent, "OTHER")},
            "pot_type": pot_type,
            "postflop_order": order,
            "stacks_bb": {hero: stacks[hero] / bb, opponent: stacks[opponent] / bb},
            "preflop_contributions_bb": {hero: paid.get(hero, 0.0) / bb, opponent: paid.get(opponent, 0.0) / bb},
            "flop_pot_bb": pot / bb,
        })
        audit["eligible"] += 1

    meta = {
        "schema": "sequential-arena-scenario-source/v2",
        "population_id": population_id,
        "dataset": dataset_meta,
        "dataset_provenance": provenance,
        "split": split.upper(),
        "hero": hero,
        "audit": dict(sorted(audit.items())),
        "eligible_hand_ids_sha256": hashlib.sha256("\n".join(item["hand_id"] for item in out).encode()).hexdigest(),
    }
    return out, meta


def deterministic_runout(hero_cards: list[str], flop: list[str], opponent_cards: list[str], *seed_parts: object) -> list[str]:
    blocked = {cid(card) for card in hero_cards + flop + opponent_cards}
    deck = [index for index in range(52) if index not in blocked]
    deck.sort(key=lambda card: hseed(*seed_parts, "runout-card", card))
    return [ccode(deck[0]), ccode(deck[1])]


def materialize_scenario(base: dict, env: ModelBEnvironment, *, master_seed: int, rep: int) -> dict:
    hand_id = base["hand_id"]
    opponent = base["opponent"]
    profile = env.sample_profile(master_seed, hand_id, rep, "profile")
    opponent_cards = env.sample_hole_cards(
        profile,
        base["positions"][opponent],
        base["pot_type"],
        base["preflop_roles"][opponent],
        base["hero_cards"],
        base["flop"],
        master_seed,
        hand_id,
        rep,
        "opponent-cards",
    )
    runout = deterministic_runout(
        base["hero_cards"], base["flop"], opponent_cards, master_seed, hand_id, rep
    )
    scenario_key = {
        "population_id": base["population_id"],
        "hand_id": hand_id,
        "rep": int(rep),
        "master_seed": int(master_seed),
        "profile": int(profile),
        "opponent_cards": opponent_cards,
        "runout": runout,
    }
    scenario_id = hashlib.sha256(json.dumps(scenario_key, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:24]
    return {
        **base,
        "scenario_id": scenario_id,
        "rep": int(rep),
        "master_seed": int(master_seed),
        "profile": int(profile),
        "opponent_cards": opponent_cards,
        "runout": runout,
        "environment_seed": hseed(master_seed, hand_id, rep, "environment"),
    }


def build_scenario_manifest(
    *,
    population_id: str,
    env: ModelBEnvironment,
    count: int,
    reps: int,
    master_seed: int,
    start: int = 0,
    split: str = "TEST",
    hero: str = "RoiDePiqueNique",
    root: Path = ROOT,
) -> dict:
    population = resolve_population(root, population_id)
    base, source_meta = eligible_base_scenarios(
        population_id=population_id,
        root=root,
        hero=hero,
        split=split,
    )
    ordered = sorted(base, key=lambda item: (hseed(master_seed, "base-hand", item["hand_id"]), item["hand_id"]))
    selected = ordered[start : start + count]
    scenarios = [materialize_scenario(hand, env, master_seed=master_seed, rep=rep) for hand in selected for rep in range(reps)]
    compact_fingerprint = [
        {
            "population_id": item["population_id"],
            "scenario_id": item["scenario_id"],
            "hand_id": item["hand_id"],
            "rep": item["rep"],
            "profile": item["profile"],
            "opponent_cards": item["opponent_cards"],
            "runout": item["runout"],
        }
        for item in scenarios
    ]
    return {
        "schema": "sequential-arena-scenario-manifest/v2",
        "population_id": population_id,
        "cache_namespace": population["storage"]["cache_namespace"],
        "master_seed": int(master_seed),
        "split": split.upper(),
        "hero": hero,
        "requested_hands": int(count),
        "reps": int(reps),
        "start": int(start),
        "eligible_hands": len(base),
        "source": source_meta,
        "model_b": {
            "alias": env.alias,
            "model_dir": env.model_dir.relative_to(root).as_posix() if env.model_dir.is_relative_to(root) else env.model_dir.as_posix(),
            "artifact_sha256": env.artifact_fingerprints(),
        },
        "scenario_fingerprint_sha256": hashlib.sha256(json.dumps(compact_fingerprint, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "scenarios": scenarios,
    }

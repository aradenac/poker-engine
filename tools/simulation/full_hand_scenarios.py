#!/usr/bin/env python3
"""Leakage-safe full-hand scenario generation for the multiway arena.

Unlike ``scenarios.py`` (the historical HU-postflop harness), this module samples
only table geometry from historical hands. Observed actions, hole cards, boards
and outcomes are never eligibility criteria and are never reused as simulated
cards. A fresh complete deal is generated before either policy is queried.
"""
from __future__ import annotations

import collections
import hashlib
import json
import random
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from tools.datasets.build_hand_history_increment import split_for
from tools.populations.registry import resolve_population
from tools.simulation.model_b_runtime import ccode, hseed, weighted_choice
from tools.simulation.scenarios import blind_from_stake, dataset_from_population, seat_stacks
from tools.training.independent_profiles.build_model_b import parse_hand
from tools.training.independent_profiles.build_player_features import merge_archives

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "full-hand-arena-scenario-manifest/v1"


def _sha256_json(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def eligible_table_templates(
    *,
    population_id: str,
    hero: str = "RoiDePiqueNique",
    split: str = "TEST",
    root: Path = ROOT,
    archives: Iterable[Path] | None = None,
) -> tuple[list[dict], dict]:
    """Return population-derived table geometries without conditioning on play.

    The only historical information retained is information known before the deal:
    seats, button, stake and starting stacks. In particular no requirement to see
    a flop, showdown, Hero cards or any action is allowed here.
    """
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

    records, provenance = merge_archives(archive_paths, set(default_stakes))
    split = split.upper()
    templates: list[dict] = []
    audit = collections.Counter()

    for hand_id in sorted(records):
        if split_for(hand_id) != split:
            continue
        record = records[hand_id]
        hand = parse_hand(record)
        if hand is None:
            audit["unparsed"] += 1
            continue
        seats = [name for _, name in sorted(hand["seats"])]
        if hero not in seats:
            audit["hero_missing"] += 1
            continue
        if not 2 <= len(seats) <= 6:
            audit["unsupported_player_count"] += 1
            continue
        button_seat = hand.get("button")
        by_number = dict(hand["seats"])
        button = by_number.get(button_seat)
        if button not in seats:
            audit["button_missing"] += 1
            continue
        stacks_chips = seat_stacks(record.text)
        if any(player not in stacks_chips or stacks_chips[player] <= 0 for player in seats):
            audit["stack_missing"] += 1
            continue
        try:
            bb_chips = blind_from_stake(record.stake)
        except ValueError:
            audit["blind_missing"] += 1
            continue

        templates.append({
            "population_id": population_id,
            "source_hand_id": str(hand_id),
            "source_file": record.source_file,
            "source_language": record.language,
            "stake": record.stake,
            "big_blind_chips": bb_chips,
            "hero": hero,
            "seats": seats,
            "button": button,
            "positions": {player: hand["positions"].get(player, "NA") for player in seats},
            "stacks_bb": {player: round(float(stacks_chips[player]) / bb_chips, 9) for player in seats},
        })
        audit["eligible"] += 1
        audit[f"players_{len(seats)}"] += 1

    return templates, {
        "schema": "full-hand-arena-table-source/v1",
        "population_id": population_id,
        "split": split,
        "hero": hero,
        "dataset": dataset_meta,
        "dataset_provenance": provenance,
        "audit": dict(sorted(audit.items())),
        "eligible_template_ids_sha256": hashlib.sha256(
            "\n".join(item["source_hand_id"] for item in templates).encode("utf-8")
        ).hexdigest(),
        "selection_contract": "predeal-table-geometry-only",
    }


def materialize_full_hand_scenario(
    template: Mapping,
    *,
    profile_ids: Sequence[int],
    profile_weights: Sequence[float],
    player_profiles: Mapping[str, int] | None,
    master_seed: int,
    rep: int,
) -> dict:
    """Freshly deal one complete hand for a selected table template."""
    seats = [str(player) for player in template["seats"]]
    hero = str(template["hero"])
    if hero not in seats:
        raise ValueError("hero must be seated")
    if len(profile_ids) != len(profile_weights) or not profile_ids:
        raise ValueError("profile_ids/profile_weights must be non-empty and aligned")

    source_hand_id = str(template["source_hand_id"])
    deck_seed = hseed(template["population_id"], master_seed, source_hand_id, rep, "deck")
    deck = [ccode(card_id) for card_id in range(52)]
    random.Random(deck_seed).shuffle(deck)

    hole_cards = {player: [] for player in seats}
    cursor = 0
    # Round-robin dealing mirrors table dealing while remaining exactly reproducible.
    for _ in range(2):
        for player in seats:
            hole_cards[player].append(deck[cursor])
            cursor += 1
    board = deck[cursor : cursor + 5]
    cursor += 5
    dealt = [card for player in seats for card in hole_cards[player]] + board
    if len(dealt) != len(set(dealt)):
        raise AssertionError("fresh deal contains duplicate cards")

    known_profiles = dict(player_profiles or {})
    profiles: dict[str, int | None] = {}
    for player in seats:
        if player == hero:
            profiles[player] = None
            continue
        if player in known_profiles and int(known_profiles[player]) in set(map(int, profile_ids)):
            profiles[player] = int(known_profiles[player])
        else:
            profiles[player] = int(weighted_choice(
                list(profile_ids), list(profile_weights),
                template["population_id"], master_seed, source_hand_id, rep, player, "profile",
            ))

    seeds = {
        "deck": int(deck_seed),
        "opponent_actions": int(hseed(template["population_id"], master_seed, source_hand_id, rep, "opponent-actions")),
        "hero_policy": int(hseed(template["population_id"], master_seed, source_hand_id, rep, "hero-policy")),
        "monte_carlo": int(hseed(template["population_id"], master_seed, source_hand_id, rep, "monte-carlo")),
    }
    identity = {
        "population_id": template["population_id"],
        "source_hand_id": source_hand_id,
        "rep": int(rep),
        "master_seed": int(master_seed),
        "seats": seats,
        "button": template["button"],
        "stacks_bb": template["stacks_bb"],
        "hole_cards": hole_cards,
        "board": board,
        "profiles": profiles,
        "component_seeds": seeds,
    }
    scenario_id = _sha256_json(identity)[:24]
    return {
        "schema": "full-hand-arena-scenario/v1",
        "scenario_id": scenario_id,
        "cluster_id": source_hand_id,
        "population_id": template["population_id"],
        "source_hand_id": source_hand_id,
        "source_file": template.get("source_file"),
        "stake": template.get("stake"),
        "big_blind_chips": float(template["big_blind_chips"]),
        "master_seed": int(master_seed),
        "rep": int(rep),
        "hero": hero,
        "seats": seats,
        "button": str(template["button"]),
        "positions": dict(template["positions"]),
        "stacks_bb": {player: float(template["stacks_bb"][player]) for player in seats},
        # Trusted environment state. It is never embedded in NoLimitHoldemState.
        "hole_cards": hole_cards,
        "board": board,
        "profiles": profiles,
        "component_seeds": seeds,
    }


def build_full_hand_scenario_manifest(
    *,
    population_id: str,
    env,
    count: int,
    reps: int,
    master_seed: int,
    start: int = 0,
    split: str = "TEST",
    hero: str = "RoiDePiqueNique",
    root: Path = ROOT,
) -> dict:
    """Build immutable full-hand scenarios from one explicit population."""
    if int(count) < 1 or int(reps) < 1 or int(start) < 0:
        raise ValueError("count/reps must be positive and start non-negative")
    population = resolve_population(root, population_id)
    if getattr(env, "population_id", None) != population_id:
        raise ValueError(
            f"Model B population mismatch: expected {population_id}, got {getattr(env, 'population_id', None)!r}"
        )
    templates, source = eligible_table_templates(
        population_id=population_id,
        hero=hero,
        split=split,
        root=root,
    )
    ordered = sorted(
        templates,
        key=lambda item: (hseed(population_id, master_seed, "table-template", item["source_hand_id"]), item["source_hand_id"]),
    )
    selected = ordered[int(start) : int(start) + int(count)]
    profiles_doc = getattr(env, "profiles", {})
    scenarios = [
        materialize_full_hand_scenario(
            template,
            profile_ids=list(env.profile_ids),
            profile_weights=list(env.profile_weights),
            player_profiles=profiles_doc.get("player_profile", {}),
            master_seed=int(master_seed),
            rep=rep,
        )
        for template in selected
        for rep in range(int(reps))
    ]
    fingerprint = _sha256_json([
        {
            "scenario_id": item["scenario_id"],
            "cluster_id": item["cluster_id"],
            "hole_cards": item["hole_cards"],
            "board": item["board"],
            "profiles": item["profiles"],
            "component_seeds": item["component_seeds"],
        }
        for item in scenarios
    ])
    return {
        "schema": SCHEMA,
        "population_id": population_id,
        "cache_namespace": population["storage"]["cache_namespace"],
        "split": split.upper(),
        "hero": hero,
        "master_seed": int(master_seed),
        "requested_hands": int(count),
        "selected_independent_templates": len(selected),
        "reps": int(reps),
        "start": int(start),
        "eligible_templates": len(templates),
        "source": source,
        "model_b": {
            "alias": getattr(env, "alias", "unknown"),
            "profile_ids": list(map(int, env.profile_ids)),
        },
        "randomness_contract": {
            "deck": "pre-sampled independently of all policies",
            "opponent_actions": "separate deterministic seed namespace",
            "hero_policy": "separate deterministic seed namespace",
            "monte_carlo": "separate deterministic seed namespace",
        },
        "scenario_fingerprint_sha256": fingerprint,
        "scenarios": scenarios,
    }

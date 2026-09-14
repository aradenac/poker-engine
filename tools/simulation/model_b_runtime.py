#!/usr/bin/env python3
"""Runtime for the promoted independent opponent Model B.

This module is deliberately independent from the analyser's integrated population
model A. It reads only the promoted Model B JSON artifacts and exposes the exact
prediction/sampling contract needed by the sequential strategy arena.
"""

from __future__ import annotations

import collections
import hashlib
import itertools
import json
import math
from pathlib import Path
from typing import Iterable, Sequence

ROOT = Path(__file__).resolve().parents[2]
RANKS = "23456789TJQKA"
SUITS = "shdc"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def hseed(*parts: object) -> int:
    payload = "|".join(map(str, parts)).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def u01(*parts: object) -> float:
    return (hseed(*parts) % ((1 << 53) - 1)) / float((1 << 53) - 1)


def weighted_choice(items: Sequence, weights: Sequence[float], *seed_parts: object):
    if len(items) != len(weights) or not items:
        raise ValueError("items/weights must be non-empty and have equal length")
    clean = [max(0.0, float(w)) if math.isfinite(float(w)) else 0.0 for w in weights]
    total = sum(clean)
    if total <= 0:
        raise ValueError("weights must contain positive mass")
    target = u01(*seed_parts) * total
    acc = 0.0
    for item, weight in zip(items, clean):
        acc += weight
        if target <= acc:
            return item
    return items[-1]


def cid(card: str) -> int:
    card = card.strip()
    if len(card) != 2 or card[0].upper() not in RANKS or card[1].lower() not in SUITS:
        raise ValueError(f"invalid card: {card!r}")
    return SUITS.index(card[1].lower()) * 13 + RANKS.index(card[0].upper())


def ccode(card_id: int) -> str:
    if not 0 <= int(card_id) < 52:
        raise ValueError(f"invalid card id: {card_id}")
    card_id = int(card_id)
    return RANKS[card_id % 13] + SUITS[card_id // 13]


def combo_class_ids(a: int, b: int) -> str:
    ra, rb = a % 13, b % 13
    sa, sb = a // 13, b // 13
    if ra == rb:
        return RANKS[ra] * 2
    if rb > ra:
        ra, rb, sa, sb = rb, ra, sb, sa
    return RANKS[ra] + RANKS[rb] + ("s" if sa == sb else "o")


def combo_class(cards: Iterable[str]) -> str:
    a, b = [cid(c) for c in cards]
    return combo_class_ids(a, b)


def legal_combos(hero: Sequence[str], board: Sequence[str]) -> list[tuple[int, int]]:
    blocked = {cid(c) for c in list(hero) + list(board)}
    return [
        (a, b)
        for a in range(52)
        if a not in blocked
        for b in range(a + 1, 52)
        if b not in blocked
    ]


def five(cards: Sequence[str]) -> tuple:
    if len(cards) != 5:
        raise ValueError("five() requires exactly five cards")
    ranks = sorted([RANKS.index(c[0].upper()) for c in cards], reverse=True)
    suits = [c[1].lower() for c in cards]
    counts = collections.Counter(ranks)
    rank_set = set(ranks)
    straight = -1
    if {12, 3, 2, 1, 0}.issubset(rank_set):
        straight = 3
    for hi in range(12, 3, -1):
        if all(r in rank_set for r in range(hi - 4, hi + 1)):
            straight = hi
            break
    flush = len(set(suits)) == 1
    if flush and straight >= 0:
        return (8, straight)
    quads = sorted([r for r, n in counts.items() if n == 4], reverse=True)
    if quads:
        return (7, quads[0], max(r for r in ranks if r != quads[0]))
    trips = sorted([r for r, n in counts.items() if n == 3], reverse=True)
    pairs_or_better = sorted([r for r, n in counts.items() if n >= 2], reverse=True)
    if trips and any(r != trips[0] for r in pairs_or_better):
        return (6, trips[0], max(r for r in pairs_or_better if r != trips[0]))
    if flush:
        return (5, *ranks[:5])
    if straight >= 0:
        return (4, straight)
    if trips:
        return (3, trips[0], *([r for r in ranks if r != trips[0]][:2]))
    pairs = sorted([r for r, n in counts.items() if n == 2], reverse=True)
    if len(pairs) >= 2:
        return (2, pairs[0], pairs[1], max(r for r in ranks if r not in pairs[:2]))
    if len(pairs) == 1:
        return (1, pairs[0], *([r for r in ranks if r != pairs[0]][:3]))
    return (0, *ranks[:5])


def best(cards: Sequence[str]) -> tuple:
    if len(cards) < 5:
        raise ValueError("best() requires at least five cards")
    return max(five(combo) for combo in itertools.combinations(cards, 5))


def rake_net(gross_bb: float) -> float:
    """Historical arena rake contract: 5.5% capped at 13.925 BB."""
    gross_bb = max(0.0, float(gross_bb))
    return gross_bb - min(13.925, 0.055 * gross_bb)


def key_for(cols: Sequence[str], row: dict) -> str:
    return "ALL" if not cols else "|".join(str(row.get(c, "NA")) for c in cols)


def select_node(levels: Sequence[dict], row: dict, min_observations: int) -> tuple[dict, int, str]:
    fallback = None
    fallback_index = len(levels) - 1
    fallback_key = "ALL"
    for i, level in enumerate(levels):
        key = key_for(level["cols"], row)
        node = level["data"].get(key)
        if i == len(levels) - 1:
            fallback = node
            fallback_index = i
            fallback_key = key
        if node and int(node.get("n", 0)) >= int(min_observations):
            return node, i, key
    if fallback is not None:
        return fallback, fallback_index, fallback_key
    raise KeyError(f"no hierarchy node for {row}")


class ModelBEnvironment:
    """Read-only promoted Model B runtime."""

    def __init__(self, model_dir: Path, alias: str = "independent_model_b_v2", population_id: str | None = None) -> None:
        self.model_dir = Path(model_dir)
        self.alias = alias
        self.population_id = population_id
        self.profiles = json.loads((self.model_dir / "profiles.json").read_text(encoding="utf-8"))
        self.ranges = json.loads((self.model_dir / "preflop_ranges.json").read_text(encoding="utf-8"))
        self.actions = json.loads((self.model_dir / "postflop_actions.json").read_text(encoding="utf-8"))
        self.sizing = json.loads((self.model_dir / "sizing.json").read_text(encoding="utf-8"))
        self.contract = json.loads((self.model_dir / "prediction_contract.json").read_text(encoding="utf-8"))
        self._validate()
        self.profile_rows = sorted(self.profiles["profiles"], key=lambda x: int(x["profile"]))
        self.profile_ids = [int(x["profile"]) for x in self.profile_rows]
        self.profile_weights = [float(x["appearance_weight"]) for x in self.profile_rows]
        self.default_profile = int(max(self.profile_rows, key=lambda x: float(x["appearance_weight"]))["profile"])

    @classmethod
    def from_population(cls, population_id: str, root: Path | None = None) -> "ModelBEnvironment":
        from tools.populations.registry import require_artifact_role, resolve_population

        root = Path(root or ROOT)
        population = resolve_population(root, population_id)
        model_dir = root / require_artifact_role(population, "model_b")
        alias = str(population["artifacts"].get("model_b_alias") or f"model_b:{population_id}")
        return cls(model_dir, alias=alias, population_id=population_id)

    @classmethod
    def from_registry(
        cls,
        root: Path | None = None,
        registry_path: Path | None = None,
        *,
        population_id: str | None = None,
    ) -> "ModelBEnvironment":
        if registry_path is not None:
            raise ValueError("legacy registry_path selection is disabled; use from_population(population_id, root)")
        if not population_id:
            raise ValueError("population_id is required; implicit training/registry.json Model B selection is disabled")
        return cls.from_population(population_id, root)

    def _validate(self) -> None:
        expected = {
            self.profiles.get("schema"): "independent-opponent-profiles/v2",
            self.ranges.get("schema"): "independent-preflop-ranges/v2",
            self.actions.get("schema"): "independent-postflop-actions/v2",
            self.sizing.get("schema"): "independent-postflop-sizing/v2",
            self.contract.get("schema"): "independent-opponent-model-b-prediction-contract/v1",
        }
        bad = [(got, want) for got, want in expected.items() if got != want]
        if bad:
            raise ValueError(f"unsupported Model B artifact schema(s): {bad}")
        if sum(int(v) for v in self.ranges["multiplicity"].values()) != 1326:
            raise ValueError("invalid 1326-combo multiplicity contract")

    def artifact_fingerprints(self) -> dict[str, str]:
        names = ["profiles.json", "preflop_ranges.json", "postflop_actions.json", "sizing.json", "prediction_contract.json"]
        return {name: sha256_file(self.model_dir / name) for name in names}

    def sample_profile(self, *seed_parts: object) -> int:
        return int(weighted_choice(self.profile_ids, self.profile_weights, *seed_parts))

    def class_probabilities(self, profile: int, position: str, pot_type: str, preflop_role: str) -> dict[str, float]:
        row = {
            "profile": int(profile),
            "position": position,
            "pot_type": pot_type,
            "preflop_role": preflop_role,
        }
        node, _, _ = select_node(self.ranges["levels"], row, int(self.ranges["backoff_min_observations"]))
        prior_strength = float(self.contract["preflop_range"]["prior_strength"])
        multiplicity = self.ranges["multiplicity"]
        counts = node.get("counts", {})
        n = float(node.get("n", sum(counts.values())))
        den = n + prior_strength
        return {
            hand: (float(counts.get(hand, 0)) + prior_strength * float(multiplicity[hand]) / 1326.0) / den
            for hand in self.ranges["notations"]
        }

    def range_combos(
        self,
        profile: int,
        position: str,
        pot_type: str,
        preflop_role: str,
        hero: Sequence[str],
        board: Sequence[str],
    ) -> tuple[list[tuple[int, int]], list[float]]:
        class_probs = self.class_probabilities(profile, position, pot_type, preflop_role)
        multiplicity = self.ranges["multiplicity"]
        combos = legal_combos(hero, board)
        weights = [
            class_probs[combo_class_ids(a, b)] / max(1, int(multiplicity[combo_class_ids(a, b)]))
            for a, b in combos
        ]
        total = sum(weights)
        if total <= 0:
            raise ValueError("range has no legal probability mass")
        return combos, [w / total for w in weights]

    def sample_hole_cards(
        self,
        profile: int,
        position: str,
        pot_type: str,
        preflop_role: str,
        hero: Sequence[str],
        board: Sequence[str],
        *seed_parts: object,
    ) -> list[str]:
        combos, weights = self.range_combos(profile, position, pot_type, preflop_role, hero, board)
        a, b = weighted_choice(combos, weights, *seed_parts)
        return [ccode(a), ccode(b)]

    def action_probabilities(
        self,
        *,
        profile: int,
        street: str,
        mode: str,
        relative_position: str,
        pot_type: str,
        preflop_role: str,
        can_raise: bool = True,
    ) -> dict[str, float]:
        mode = mode.upper()
        labels = list(self.actions["labels"][mode])
        row = {
            "profile": int(profile),
            "street": street.lower(),
            "mode": mode,
            "relative_position": relative_position,
            "pot_type": pot_type,
            "preflop_role": preflop_role,
        }
        node, _, _ = select_node(self.actions["levels"], row, int(self.actions["backoff_min_observations"]))
        counts = node.get("counts", {})
        alpha = float(self.contract["postflop_action"]["alpha_per_action"])
        # The ALL fallback can contain both FREE and FACING labels. Normalize only
        # the labels legal in the current mode, matching the evaluated contract.
        legal_n = sum(float(counts.get(label, 0)) for label in labels)
        den = legal_n + alpha * len(labels)
        probs = {label: (float(counts.get(label, 0)) + alpha) / den for label in labels}
        if mode == "FACING" and not can_raise and "RAISE" in probs:
            probs["CALL"] += probs["RAISE"]
            probs["RAISE"] = 0.0
        total = sum(probs.values())
        return {k: v / total for k, v in probs.items()}

    def sample_action(self, *, seed_parts: Sequence[object], **context) -> str:
        probs = self.action_probabilities(**context)
        return str(weighted_choice(list(probs), list(probs.values()), *seed_parts))

    def sizing_values(
        self,
        *,
        profile: int,
        street: str,
        mode: str,
        action: str,
        pot_type: str,
    ) -> list[float]:
        row = {
            "profile": int(profile),
            "street": street.lower(),
            "mode": mode.upper(),
            "action": action.upper(),
            "pot_type": pot_type,
        }
        node, _, _ = select_node(self.sizing["levels"], row, int(self.sizing["backoff_min_observations"]))
        values = [float(x) for x in node.get("values", []) if math.isfinite(float(x)) and float(x) > 0]
        if not values:
            raise ValueError(f"no empirical sizing values for {row}")
        return values

    def sample_sizing(self, *, seed_parts: Sequence[object], **context) -> float:
        values = self.sizing_values(**context)
        return float(values[hseed(*seed_parts) % len(values)])

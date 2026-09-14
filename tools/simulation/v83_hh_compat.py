#!/usr/bin/env python3
"""Serialization-only compatibility helpers for the frozen v83 PokerStars parser.

The strategy arena may source French PokerStars histories, while the frozen v83
parser accepts the English PokerStars header/action grammar. These helpers preserve
cards, seats, names, amounts and chronology and change only textual serialization.
"""
from __future__ import annotations

import re

from tools.simulation import sequential_postflop as arena


_FRENCH_HEADER_RE = re.compile(
    r"^Main\s+PokerStars\s+n[°º]\s*(\d+)\s*:\s*(.*?)\s+-\s+"
    r"(\d{2})/(\d{2})/(\d{4})\s+(\d{1,2}:\d{2}:\d{2})(.*)$",
    re.IGNORECASE,
)


def normalize_prefix_text_for_v83(prefix: str) -> str:
    """Normalize a preflop prefix already stripped of terminal/postflop lines."""
    lines = str(prefix or "").replace("\r", "").splitlines()
    if not lines:
        return ""

    m = _FRENCH_HEADER_RE.match(lines[0].strip())
    if m:
        hand_id, game, day, month, year, clock, tail = m.groups()
        lines[0] = f"PokerStars Hand #{hand_id}: {game.strip()} - {year}/{month}/{day} {clock}{tail}"

    # French PokerStars exports may use NBSP / narrow-NBSP before the action colon.
    # The frozen parser keys player names against Seat lines, so retaining that
    # invisible space makes an otherwise English action actor a different player.
    lines = [re.sub(r"[\u00a0\u202f]+:", ":", line) for line in lines]
    return "\n".join(lines).rstrip()


def action_line_for_v83(
    player: str,
    kind: str,
    cost_bb: float,
    street_paid: float,
    max_paid: float,
    remaining: float,
    bb_chips: float,
    _source_language: str = "en",
) -> str:
    """Always serialize synthetic actions in the English grammar consumed by v83."""
    return arena.action_line(player, kind, cost_bb, street_paid, max_paid, remaining, bb_chips)


def street_marker_for_v83(street: str, board: list[str], _source_language: str = "en") -> str:
    """Always serialize synthetic streets in the English grammar consumed by v83."""
    if street == "flop":
        return f"*** FLOP *** [{' '.join(board[:3])}]"
    if street == "turn":
        return f"*** TURN *** [{' '.join(board[:3])}] [{board[3]}]"
    if street == "river":
        return f"*** RIVER *** [{' '.join(board[:4])}] [{board[4]}]"
    raise ValueError(f"unsupported street {street!r}")

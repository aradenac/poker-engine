#!/usr/bin/env python3
"""Build independent opponent Model B v2 from TRAIN hand histories.

This model is deliberately separate from the analyser's integrated population/EV
model A. Inputs are only persisted PokerStars hand histories plus the TRAIN-only
player feature artifact produced by ``build_player_features.py``.

Outputs are transparent JSON tables:
- deterministic behavioural profiles and player assignments;
- profile-conditioned preflop hand-class evidence;
- profile/context-conditioned postflop action counts with hierarchical backoff;
- empirical postflop bet/raise sizing samples with hierarchical backoff.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

from tools.datasets.build_hand_history_increment import HandRecord, split_for
from tools.training.independent_profiles.build_player_features import merge_archives

MODEL_SCHEMA = "independent-opponent-model-b/v2"
PROFILE_SCHEMA = "independent-opponent-profiles/v2"
RANGE_SCHEMA = "independent-preflop-ranges/v2"
ACTION_SCHEMA = "independent-postflop-actions/v2"
SIZING_SCHEMA = "independent-postflop-sizing/v2"
RANKS_ASC = "23456789TJQKA"
RANKS_DESC = "AKQJT98765432"
FEATURE_KEYS = [
    "vpip",
    "pfr",
    "limp",
    "threebet",
    "post_aggression_frequency",
    "post_fold_facing_aggression",
]
SEAT_RE = re.compile(r"^(?:Seat|Siège|Siege|Place)\s+(\d+)\s*:\s*(.+?)\s+\([^)]*\)\s*$", re.I)
ACTOR_RE = re.compile(r"^(.+?)\s*:\s*(.+)$")
CARD_RE = re.compile(r"^[2-9TJQKA][shdc]$", re.I)

POSTFLOP_LEVELS = [
    ["profile", "street", "mode", "relative_position", "pot_type", "preflop_role"],
    ["profile", "street", "mode", "relative_position", "pot_type"],
    ["profile", "street", "mode", "relative_position"],
    ["profile", "street", "mode"],
    ["street", "mode"],
    [],
]
RANGE_LEVELS = [
    ["profile", "position", "pot_type", "preflop_role"],
    ["profile", "position", "preflop_role"],
    ["profile", "preflop_role"],
    ["profile"],
    [],
]
SIZING_LEVELS = [
    ["profile", "street", "mode", "action", "pot_type"],
    ["profile", "street", "mode", "action"],
    ["street", "mode", "action"],
    [],
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def amount(text: str) -> float | None:
    s = str(text).strip().replace("€", "").replace("$", "").replace("£", "").replace(" ", "")
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        s = parts[0] + "." + parts[1] if len(parts) == 2 and len(parts[1]) != 3 else s.replace(",", "")
    try:
        x = float(s)
    except ValueError:
        return None
    return x if math.isfinite(x) else None


def numeric_tokens(text: str) -> list[float]:
    raw = re.findall(r"(?<![#\w])(?:[€$£]?\s*)?\d[\d.,]*", text)
    out = []
    for token in raw:
        x = amount(token)
        if x is not None:
            out.append(x)
    return out


def combo_class(cards: Iterable[str]) -> str | None:
    cards = list(cards)
    if len(cards) != 2 or not all(CARD_RE.match(c) for c in cards):
        return None
    a, b = cards
    r1, s1 = a[0].upper(), a[1].lower()
    r2, s2 = b[0].upper(), b[1].lower()
    i1, i2 = RANKS_ASC.index(r1), RANKS_ASC.index(r2)
    if i1 == i2:
        return r1 + r2
    if i2 > i1:
        r1, r2, s1, s2 = r2, r1, s2, s1
    return r1 + r2 + ("s" if s1 == s2 else "o")


def hand_notations() -> tuple[list[str], dict[str, int]]:
    names: list[str] = []
    mult: dict[str, int] = {}
    for i, high in enumerate(RANKS_DESC):
        pair = high + high
        names.append(pair)
        mult[pair] = 6
        for low in RANKS_DESC[i + 1 :]:
            for suffix, n in (("s", 4), ("o", 12)):
                name = high + low + suffix
                names.append(name)
                mult[name] = n
    assert len(names) == 169
    return names, mult


def weighted_mean(values: list[float], weights: list[float]) -> float:
    den = sum(weights)
    return sum(v * w for v, w in zip(values, weights)) / den if den else 0.0


def squared_distance(a: list[float], b: list[float]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b))


def fit_profiles(feature_doc: dict, k: int, weight_cap: int = 200) -> dict:
    eligible = [p for p in feature_doc["players"] if p.get("eligible_default")]
    if len(eligible) < k:
        raise ValueError(f"need at least {k} eligible players, got {len(eligible)}")

    raw_vectors = [[float(p["shrunk_rates"][key]) for key in FEATURE_KEYS] for p in eligible]
    fit_weights = [float(min(max(int(p["counts"].get("appearances", 0)), 1), weight_cap)) for p in eligible]
    means = [weighted_mean([v[j] for v in raw_vectors], fit_weights) for j in range(len(FEATURE_KEYS))]
    stds = []
    for j, mean in enumerate(means):
        var = weighted_mean([(v[j] - mean) ** 2 for v in raw_vectors], fit_weights)
        stds.append(max(math.sqrt(var), 1e-9))
    points = [[(v[j] - means[j]) / stds[j] for j in range(len(FEATURE_KEYS))] for v in raw_vectors]

    # Deterministic farthest-point initialization: start with the player closest
    # to the population center, then repeatedly add the point farthest from its
    # nearest selected centroid. Player name is the deterministic tie breaker.
    names = [p["player"] for p in eligible]
    first = min(range(len(points)), key=lambda i: (squared_distance(points[i], [0.0] * len(FEATURE_KEYS)), names[i]))
    centroid_indices = [first]
    while len(centroid_indices) < k:
        candidates = [i for i in range(len(points)) if i not in centroid_indices]
        nxt = max(
            candidates,
            key=lambda i: (min(squared_distance(points[i], points[c]) for c in centroid_indices), names[i]),
        )
        centroid_indices.append(nxt)
    centroids = [points[i][:] for i in centroid_indices]

    assignments = [-1] * len(points)
    for _ in range(100):
        new_assignments = [
            min(range(k), key=lambda c: (squared_distance(point, centroids[c]), c)) for point in points
        ]
        new_centroids: list[list[float]] = []
        for c in range(k):
            members = [i for i, a in enumerate(new_assignments) if a == c]
            if not members:
                # Deterministic empty-cluster recovery: use the globally worst-fit point.
                idx = max(
                    range(len(points)),
                    key=lambda i: (min(squared_distance(points[i], x) for x in centroids), names[i]),
                )
                new_centroids.append(points[idx][:])
                continue
            ws = [fit_weights[i] for i in members]
            new_centroids.append([
                weighted_mean([points[i][j] for i in members], ws) for j in range(len(FEATURE_KEYS))
            ])
        delta = sum(squared_distance(a, b) for a, b in zip(centroids, new_centroids))
        centroids = new_centroids
        if new_assignments == assignments or delta < 1e-12:
            assignments = new_assignments
            break
        assignments = new_assignments

    # Canonical profile IDs are ordered from tighter to looser, then by PFR and
    # postflop aggression. This keeps IDs stable even if internal k-means labels move.
    raw_centroids = [
        {key: centroids[c][j] * stds[j] + means[j] for j, key in enumerate(FEATURE_KEYS)} for c in range(k)
    ]
    order = sorted(
        range(k),
        key=lambda c: (
            raw_centroids[c]["vpip"],
            raw_centroids[c]["pfr"],
            raw_centroids[c]["post_aggression_frequency"],
            raw_centroids[c]["threebet"],
        ),
    )
    canonical = {old: new for new, old in enumerate(order)}
    centroids_canon = [centroids[old] for old in order]
    raw_centroids_canon = [raw_centroids[old] for old in order]

    def assign_player(p: dict) -> int:
        vector = [
            (float(p["shrunk_rates"][key]) - means[j]) / stds[j] for j, key in enumerate(FEATURE_KEYS)
        ]
        return min(range(k), key=lambda c: (squared_distance(vector, centroids_canon[c]), c))

    player_profile = {p["player"]: assign_player(p) for p in feature_doc["players"]}
    eligible_assignment = {eligible[i]["player"]: canonical[assignments[i]] for i in range(len(eligible))}

    profile_rows = []
    total_appearances = sum(int(p["counts"].get("appearances", 0)) for p in feature_doc["players"])
    for profile_id in range(k):
        all_members = [p for p in feature_doc["players"] if player_profile[p["player"]] == profile_id]
        fit_members = [p for p in eligible if eligible_assignment[p["player"]] == profile_id]
        appearances = sum(int(p["counts"].get("appearances", 0)) for p in all_members)
        profile_rows.append({
            "profile": profile_id,
            "name": f"P{profile_id}",
            "centroid": raw_centroids_canon[profile_id],
            "fit_players": len(fit_members),
            "all_players": len(all_members),
            "appearances": appearances,
            "appearance_weight": appearances / total_appearances if total_appearances else 0.0,
        })

    return {
        "schema": PROFILE_SCHEMA,
        "algorithm": "deterministic weighted k-means with farthest-point initialization",
        "k": k,
        "feature_keys": FEATURE_KEYS,
        "standardization": {"mean": dict(zip(FEATURE_KEYS, means)), "std": dict(zip(FEATURE_KEYS, stds))},
        "fit_weight": f"min(TRAIN appearances, {weight_cap})",
        "fit_players": len(eligible),
        "profiles": profile_rows,
        "player_profile": player_profile,
    }


def assign_positions(seats: list[tuple[int, str]], button: int | None) -> dict[str, str]:
    if button is None or not seats:
        return {name: "NA" for _, name in seats}
    ordered_seats = sorted(seats)
    try:
        bi = next(i for i, (seat, _) in enumerate(ordered_seats) if seat == button)
    except StopIteration:
        return {name: "NA" for _, name in seats}
    rotated = [ordered_seats[(bi + i) % len(ordered_seats)] for i in range(len(ordered_seats))]
    templates = {
        2: ["SB_BTN", "BB"],
        3: ["BTN", "SB", "BB"],
        4: ["BTN", "SB", "BB", "CO"],
        5: ["BTN", "SB", "BB", "HJ", "CO"],
        6: ["BTN", "SB", "BB", "LJ", "HJ", "CO"],
    }
    template = templates.get(len(rotated), [])
    return {name: template[i] if i < len(template) else f"Seat{seat}" for i, (seat, name) in enumerate(rotated)}


def extract_cards(text: str, seats_by_number: dict[int, str]) -> dict[str, list[str]]:
    known: dict[str, list[str]] = {}
    patterns = [
        r"(?m)^Dealt to (.+?) \[([^\]]+)\]",
        r"(?m)^Distribu(?:é|e) à (.+?) \[([^\]]+)\]",
        r"(?m)^Distribue a (.+?) \[([^\]]+)\]",
        r"(?m)^(.+?): shows \[([^\]]+)\]",
        r"(?m)^(.+?): montre \[([^\]]+)\]",
    ]
    for pattern in patterns:
        for m in re.finditer(pattern, text, re.I):
            cards = m.group(2).split()
            if len(cards) == 2:
                known[m.group(1).strip()] = cards
    for raw in text.replace("\r", "").splitlines():
        m = re.match(r"^(?:Seat|Siège|Siege|Place)\s+(\d+)\s*:\s*.*?\[([^\]]+)\]", raw, re.I)
        if not m:
            continue
        seat = int(m.group(1))
        cards = m.group(2).split()
        if seat in seats_by_number and len(cards) == 2:
            known[seats_by_number[seat]] = cards
    return known


def parse_action_line(line: str, player_names: set[str]) -> dict | None:
    low = line.lower()
    # Uncalled-bet returns do not follow the usual "player: action" grammar.
    m = re.search(r"\(([^)]+)\).*?(?:returned to|rendue à|rendue a|retournée à|retournee a)\s+(.+)$", line, re.I)
    if m:
        x = amount(m.group(1))
        player = m.group(2).strip().rstrip(".")
        if x is not None and player in player_names:
            return {"player": player, "type": "return", "amount": x, "to": None, "allin": False}

    m = ACTOR_RE.match(line.strip())
    if not m:
        return None
    player, body = m.group(1).strip(), m.group(2).strip()
    if player not in player_names:
        return None
    value = body.lower()
    nums = numeric_tokens(body)
    allin = "all-in" in value or "all in" in value

    if value.startswith(("posts ", "poste ", "met ")) and nums:
        return {"player": player, "type": "post", "amount": nums[0], "to": None, "allin": allin}
    if value.startswith(("folds", "se couche", "passe")):
        return {"player": player, "type": "fold", "amount": 0.0, "to": None, "allin": allin}
    if value.startswith(("checks", "parole")):
        return {"player": player, "type": "check", "amount": 0.0, "to": None, "allin": allin}
    if value.startswith(("calls", "suit")) and nums:
        return {"player": player, "type": "call", "amount": nums[0], "to": None, "allin": allin}
    if value.startswith(("bets", "mise")) and nums:
        return {"player": player, "type": "bet", "amount": nums[0], "to": None, "allin": allin}
    if value.startswith(("raises", "relance")) and nums:
        to_amount = nums[-1] if len(nums) >= 2 else None
        return {"player": player, "type": "raise", "amount": nums[0], "to": to_amount, "allin": allin}
    return None


def parse_hand(record: HandRecord) -> dict | None:
    lines = record.text.replace("\r", "").splitlines()
    seats: list[tuple[int, str]] = []
    for raw in lines:
        if raw.startswith("***"):
            break
        m = SEAT_RE.match(raw.strip())
        if m:
            seats.append((int(m.group(1)), m.group(2).strip()))
    if not seats:
        return None
    seats_by_number = dict(seats)
    names = {name for _, name in seats}

    button = None
    button_patterns = [
        r"Seat #(\d+) is the button",
        r"(?:Siège|Siege|Place)\s*#?(\d+)\s+est le bouton",
    ]
    for pattern in button_patterns:
        m = re.search(pattern, record.text, re.I)
        if m:
            button = int(m.group(1))
            break
    positions = assign_positions(seats, button)
    known_cards = extract_cards(record.text, seats_by_number)

    events = {"preflop": [], "flop": [], "turn": [], "river": []}
    street = "preflop"
    for raw in lines:
        line = raw.strip()
        if line.startswith("*** FLOP ***"):
            street = "flop"
            continue
        if line.startswith(("*** TURN ***", "*** TOURNANT ***")):
            street = "turn"
            continue
        if line.startswith(("*** RIVER ***", "*** RIVIÈRE ***", "*** RIVIERE ***")):
            street = "river"
            continue
        if line.startswith(("*** SUMMARY ***", "*** RÉSUMÉ ***", "*** RESUME ***")):
            break
        event = parse_action_line(line, names)
        if event is not None:
            events[street].append(event)

    return {
        "hand_id": record.hand_id,
        "players": [name for _, name in sorted(seats)],
        "seats": seats,
        "button": button,
        "positions": positions,
        "known_cards": known_cards,
        "events": events,
    }


def preflop_summary(hand: dict) -> tuple[str, dict[str, str], set[str], set[str], float]:
    actions_by: dict[str, list[str]] = defaultdict(list)
    active = set(hand["players"])
    allin: set[str] = set()
    paid: dict[str, float] = defaultdict(float)
    price = 0.0
    pot = 0.0
    raises = 0
    last_aggressor: str | None = None

    for event in hand["events"]["preflop"]:
        player = event["player"]
        typ = event["type"]
        if typ == "return":
            x = min(event["amount"], paid[player])
            paid[player] -= x
            pot = max(0.0, pot - x)
            continue
        if typ == "post":
            paid[player] += event["amount"]
            price = max(price, paid[player])
            pot += event["amount"]
            if event["allin"]:
                allin.add(player)
            continue
        if typ == "fold":
            actions_by[player].append("FOLD")
            active.discard(player)
        elif typ == "check":
            actions_by[player].append("CHECK")
        elif typ == "call":
            label = "LIMP" if raises == 0 else "CALL"
            actions_by[player].append(label)
            paid[player] += event["amount"]
            pot += event["amount"]
        elif typ in {"bet", "raise"}:
            label = "RAISE"
            actions_by[player].append(label)
            if event.get("to") is not None:
                add = max(0.0, float(event["to"]) - paid[player])
                paid[player] += add
            else:
                add = event["amount"]
                paid[player] += add
            pot += add
            price = max(price, paid[player])
            raises += 1
            last_aggressor = player
        if event["allin"]:
            allin.add(player)

    pot_type = "LIMPED" if raises == 0 else "SRP" if raises == 1 else "3BP" if raises == 2 else "4BP_PLUS"
    roles: dict[str, str] = {}
    for player in hand["players"]:
        acts = actions_by[player]
        if player == last_aggressor:
            roles[player] = "PFA"
        elif "CALL" in acts:
            roles[player] = "CALLER"
        elif "LIMP" in acts:
            roles[player] = "LIMPER"
        elif "CHECK" in acts:
            roles[player] = "BB_CHECK"
        else:
            roles[player] = "OTHER"
    return pot_type, roles, active, allin, pot


def postflop_order(hand: dict, active: set[str]) -> list[str]:
    seats = sorted(hand["seats"])
    if not seats:
        return []
    button = hand["button"]
    if button is None:
        return [name for _, name in seats if name in active]
    max_seat = max(seat for seat, _ in seats)
    by_seat = dict(seats)
    out = []
    for offset in range(1, max_seat + 1):
        seat = ((button - 1 + offset) % max_seat) + 1
        player = by_seat.get(seat)
        if player in active:
            out.append(player)
    return out


def relative_position(hand: dict, actor: str, active: set[str], allin: set[str]) -> str:
    actionable = set(active) - set(allin)
    actionable.add(actor)
    order = postflop_order(hand, actionable)
    if actor not in order or len(order) <= 1:
        return "ONLY"
    i = order.index(actor)
    if i == 0:
        return "OOP"
    if i == len(order) - 1:
        return "IP"
    return "MIDDLE"


def key_for(cols: list[str], row: dict) -> str:
    return "ALL" if not cols else "|".join(str(row.get(c, "NA")) for c in cols)


def add_count(level_data: list[defaultdict[str, Counter]], levels: list[list[str]], row: dict, label: str) -> None:
    for i, cols in enumerate(levels):
        level_data[i][key_for(cols, row)][label] += 1


def apply_event(event: dict, paid: dict[str, float], pot: float, price: float) -> tuple[float, float, float]:
    player = event["player"]
    typ = event["type"]
    add = 0.0
    if typ == "return":
        x = min(event["amount"], paid[player])
        paid[player] -= x
        return max(0.0, pot - x), price, -x
    if typ in {"post", "call", "bet"}:
        add = float(event["amount"])
        paid[player] += add
    elif typ == "raise":
        if event.get("to") is not None:
            add = max(0.0, float(event["to"]) - paid[player])
        else:
            add = float(event["amount"])
        paid[player] += add
    pot += add
    price = max(price, paid[player])
    return pot, price, add


def quantile(sorted_values: list[float], q: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = q * (len(sorted_values) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return sorted_values[lo]
    frac = pos - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def serialize_count_levels(levels: list[list[str]], data: list[defaultdict[str, Counter]]) -> list[dict]:
    out = []
    for cols, mapping in zip(levels, data):
        level = {}
        for key in sorted(mapping):
            counts = dict(sorted(mapping[key].items()))
            level[key] = {"n": sum(counts.values()), "counts": counts}
        out.append({"cols": cols, "data": level})
    return out


def serialize_sizing_levels(levels: list[list[str]], data: list[defaultdict[str, list[float]]]) -> list[dict]:
    out = []
    for cols, mapping in zip(levels, data):
        level = {}
        for key in sorted(mapping):
            values = sorted(round(float(x), 6) for x in mapping[key] if math.isfinite(float(x)) and float(x) > 0)
            if not values:
                continue
            level[key] = {
                "n": len(values),
                "mean": sum(values) / len(values),
                "p10": quantile(values, 0.10),
                "p25": quantile(values, 0.25),
                "p50": quantile(values, 0.50),
                "p75": quantile(values, 0.75),
                "p90": quantile(values, 0.90),
                "p95": quantile(values, 0.95),
                "p99": quantile(values, 0.99),
                "values": values,
            }
        out.append({"cols": cols, "data": level})
    return out


def build_behavior_tables(
    records: list[HandRecord],
    player_profile: dict[str, int],
    excluded_players: set[str],
) -> tuple[dict, dict, dict, dict]:
    notations, multiplicity = hand_notations()
    range_data = [defaultdict(Counter) for _ in RANGE_LEVELS]
    action_data = [defaultdict(Counter) for _ in POSTFLOP_LEVELS]
    sizing_data = [defaultdict(list) for _ in SIZING_LEVELS]
    audit = Counter()

    for record in records:
        hand = parse_hand(record)
        if hand is None:
            audit["hands_unparsed"] += 1
            continue
        audit["hands_parsed"] += 1
        pot_type, roles, active, allin, pot = preflop_summary(hand)

        for player, cards in hand["known_cards"].items():
            if player in excluded_players or player not in player_profile or player not in active:
                continue
            hc = combo_class(cards)
            if hc is None:
                continue
            row = {
                "profile": player_profile[player],
                "position": hand["positions"].get(player, "NA"),
                "pot_type": pot_type,
                "preflop_role": roles.get(player, "OTHER"),
            }
            add_count(range_data, RANGE_LEVELS, row, hc)
            audit["known_preflop_hands"] += 1

        # Reconstruct preflop contribution state only to obtain the correct pot.
        pre_paid: dict[str, float] = defaultdict(float)
        pre_price = 0.0
        pot = 0.0
        pre_active = set(hand["players"])
        allin = set()
        for event in hand["events"]["preflop"]:
            pot, pre_price, _ = apply_event(event, pre_paid, pot, pre_price)
            if event["type"] == "fold":
                pre_active.discard(event["player"])
            if event["allin"]:
                allin.add(event["player"])
        active = pre_active

        for street in ("flop", "turn", "river"):
            paid: dict[str, float] = defaultdict(float)
            price = 0.0
            for event in hand["events"][street]:
                actor = event["player"]
                typ = event["type"]
                if typ == "return":
                    pot, price, _ = apply_event(event, paid, pot, price)
                    continue
                if typ == "post":
                    pot, price, _ = apply_event(event, paid, pot, price)
                    continue
                if typ not in {"fold", "check", "call", "bet", "raise"}:
                    continue

                to_call = max(0.0, price - paid[actor])
                mode = "FACING" if to_call > 1e-9 else "FREE"
                if typ == "check":
                    action = "CHECK"
                elif typ == "fold":
                    action = "FOLD"
                elif typ == "call":
                    action = "CALL"
                elif typ == "bet":
                    action = "BET"
                else:
                    action = "RAISE"

                pot_before = pot
                rel = relative_position(hand, actor, active, allin)
                row = {
                    "profile": player_profile.get(actor),
                    "street": street,
                    "mode": mode,
                    "relative_position": rel,
                    "pot_type": pot_type,
                    "preflop_role": roles.get(actor, "OTHER"),
                    "action": action,
                }

                if actor not in excluded_players and actor in player_profile:
                    valid = (mode == "FREE" and action in {"CHECK", "BET"}) or (
                        mode == "FACING" and action in {"FOLD", "CALL", "RAISE"}
                    )
                    if valid:
                        add_count(action_data, POSTFLOP_LEVELS, row, action)
                        audit["postflop_decisions"] += 1
                    else:
                        audit[f"invalid_{mode.lower()}_{action.lower()}"] += 1

                pot, price, added = apply_event(event, paid, pot, price)
                if (
                    actor not in excluded_players
                    and actor in player_profile
                    and action in {"BET", "RAISE"}
                    and pot_before > 0
                    and added > 0
                ):
                    ratio = added / pot_before
                    if math.isfinite(ratio) and ratio > 0:
                        for i, cols in enumerate(SIZING_LEVELS):
                            sizing_data[i][key_for(cols, row)].append(ratio)
                        audit["sizing_observations"] += 1
                        if ratio > 20:
                            audit["sizing_over_20x_pot"] += 1
                if typ == "fold":
                    active.discard(actor)
                    allin.discard(actor)
                if event["allin"]:
                    allin.add(actor)

    range_levels = serialize_count_levels(RANGE_LEVELS, range_data)
    action_levels = serialize_count_levels(POSTFLOP_LEVELS, action_data)
    sizing_levels = serialize_sizing_levels(SIZING_LEVELS, sizing_data)
    ranges = {
        "schema": RANGE_SCHEMA,
        "notations": notations,
        "multiplicity": multiplicity,
        "backoff_min_observations": 20,
        "levels": range_levels,
    }
    actions = {
        "schema": ACTION_SCHEMA,
        "labels": {"FREE": ["CHECK", "BET"], "FACING": ["FOLD", "CALL", "RAISE"]},
        "backoff_min_observations": 30,
        "levels": action_levels,
    }
    sizings = {
        "schema": SIZING_SCHEMA,
        "semantics": "incremental action cost / pot immediately before action",
        "backoff_min_observations": 12,
        "levels": sizing_levels,
    }
    return ranges, actions, sizings, dict(sorted(audit.items()))


def build_model(
    feature_path: Path,
    archives: list[Path],
    stakes: set[str],
    excluded_players: set[str],
    k: int,
) -> tuple[dict, dict, dict, dict, dict]:
    feature_doc = json.loads(feature_path.read_text(encoding="utf-8"))
    if feature_doc.get("split_used_for_fit") != "TRAIN":
        raise ValueError("player feature artifact must be TRAIN-only")
    profiles = fit_profiles(feature_doc, k)
    by_id, provenance = merge_archives(archives, stakes)
    train_records = [record for hid, record in by_id.items() if split_for(hid) == "TRAIN"]
    ranges, actions, sizings, audit = build_behavior_tables(
        train_records, profiles["player_profile"], excluded_players
    )
    summary = {
        "schema": MODEL_SCHEMA,
        "model_version": "independent_model_b_v2_candidate",
        "independence_contract": "hand histories and TRAIN player features only; no analyser/model-A predictions, EVs, policies, or recommendations are inputs",
        "fit_split": "TRAIN",
        "features": {
            "path": feature_path.as_posix(),
            "sha256": sha256_file(feature_path),
            "schema": feature_doc.get("schema"),
            "feature_version": feature_doc.get("feature_version"),
        },
        "dataset": provenance,
        "parameters": {
            "profiles": k,
            "profile_weight_cap": 200,
            "range_backoff_min_observations": ranges["backoff_min_observations"],
            "postflop_backoff_min_observations": actions["backoff_min_observations"],
            "sizing_backoff_min_observations": sizings["backoff_min_observations"],
            "random_seed": None,
        },
        "counts": {
            "train_unique_hands": len(train_records),
            "profile_fit_players": profiles["fit_players"],
            "all_profiled_players": len(profiles["player_profile"]),
            **audit,
        },
        "profile_weights": {str(p["profile"]): p["appearance_weight"] for p in profiles["profiles"]},
        "promotion_status": "candidate_not_promoted",
    }
    return summary, profiles, ranges, actions, sizings


def write_outputs(output_dir: Path, outputs: tuple[dict, dict, dict, dict, dict]) -> None:
    summary, profiles, ranges, actions, sizings = outputs
    output_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "summary.json": summary,
        "profiles.json": profiles,
        "preflop_ranges.json": ranges,
        "postflop_actions.json": actions,
        "sizing.json": sizings,
    }
    for name, value in files.items():
        (output_dir / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--archive", type=Path, action="append", required=True)
    parser.add_argument("--stake", action="append", default=["100/200"])
    parser.add_argument("--exclude-player", action="append", default=[])
    parser.add_argument("--profiles", type=int, default=6)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    outputs = build_model(
        args.features,
        args.archive,
        set(args.stake),
        set(args.exclude_player),
        args.profiles,
    )
    write_outputs(args.output_dir, outputs)
    print(json.dumps(outputs[0], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

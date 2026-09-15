from __future__ import annotations

import math
import re

from tools.simulation.full_hand_core import HoldemState, STREETS

_SEAT_LINE_RE = re.compile(
    r"^(?:Seat|Siège|Siege|Place)\s+(\d+)\s*:\s*(.+?)\s+\(([^)]*)\)\s*$",
    re.IGNORECASE,
)
_BUTTON_RE = re.compile(
    r"(?:Seat|Siège|Siege|Place)\s*#?(\d+)\s+(?:is\s+the\s+button|est\s+(?:le|au)\s+bouton)",
    re.IGNORECASE,
)
_ACTOR_LINE_RE = re.compile(r"^(.+?)\s*:\s*(.+)$")
_CARD_RE = re.compile(r"^[2-9TJQKA][shdc]$", re.IGNORECASE)


def _amount(text: str) -> float | None:
    value = str(text).strip().replace("€", "").replace("$", "").replace("£", "")
    value = re.sub(r"[\s\u00a0\u202f]+", "", value)
    value = value.rstrip(".;:")
    if not value:
        return None
    if "," in value and "." in value:
        # PokerStars' English exports use comma thousands separators in this case.
        value = value.replace(",", "")
    elif "," in value:
        parts = value.split(",")
        value = parts[0] + "." + parts[1] if len(parts) == 2 and len(parts[1]) != 3 else value.replace(",", "")
    try:
        result = float(value)
    except ValueError:
        return None
    return result if math.isfinite(result) else None


def _numeric_tokens(text: str) -> list[float]:
    raw = re.findall(r"(?<![#\w])(?:[€$£]?\s*)?\d[\d\s\u00a0\u202f.,]*", str(text))
    out: list[float] = []
    for token in raw:
        value = _amount(token)
        if value is not None:
            out.append(value)
    return out


def _header_blinds(text: str) -> tuple[float, float] | None:
    first_lines = "\n".join(str(text).replace("\r", "").splitlines()[:3])
    for group in re.findall(r"\(([^()]*/[^()]*)\)", first_lines):
        parts = group.split("/", 1)
        if len(parts) != 2:
            continue
        left = _numeric_tokens(parts[0])
        right = _numeric_tokens(parts[1])
        if left and right and 0 < left[-1] <= right[0]:
            return left[-1], right[0]
    return None


def _cards_from_marker(line: str) -> list[str]:
    cards: list[str] = []
    for group in re.findall(r"\[([^\]]+)\]", line):
        cards.extend(group.split())
    return cards


def _parse_hh_action(line: str, players: set[str], bb_chips: float) -> dict | None:
    normalized = re.sub(r"[\u00a0\u202f]+:", ":", line.strip())
    match = _ACTOR_LINE_RE.match(normalized)
    if not match:
        return None
    player, body = match.group(1).strip(), match.group(2).strip()
    if player not in players:
        return None
    low = body.lower()
    nums = _numeric_tokens(body)
    all_in = "all-in" in low or "all in" in low or "tapis" in low

    # Forced blinds are already posted by HoldemState.new_hand().
    if low.startswith(("posts ", "poste ", "met ")) and (
        "blind" in low or "blinde" in low
    ):
        return {"kind": "blind", "player": player, "body": low, "amount_chips": nums[0] if nums else None}
    if low.startswith(("folds", "se couche", "passe")):
        return {"kind": "action", "player": player, "action": "FOLD"}
    if low.startswith(("checks", "parole")):
        return {"kind": "action", "player": player, "action": "CHECK"}
    if low.startswith(("calls", "suit")):
        event = {"kind": "action", "player": player, "action": "CALL"}
        if nums:
            event["observed_paid_bb"] = nums[0] / bb_chips
        return event
    if low.startswith(("bets", "mise")):
        if not nums:
            raise ValueError(f"cannot parse bet amount: {line!r}")
        target = nums[0] / bb_chips
        if all_in:
            return {
                "kind": "action",
                "player": player,
                "action": "ALL_IN",
                "observed_to_bb": target,
            }
        return {"kind": "action", "player": player, "action": "BET", "to_bb": target, "observed_to_bb": target}
    if low.startswith(("raises", "relance")):
        if not nums:
            raise ValueError(f"cannot parse raise amount: {line!r}")
        if len(nums) < 2:
            raise ValueError(f"raise-to amount missing: {line!r}")
        target = nums[-1] / bb_chips
        if all_in:
            return {
                "kind": "action",
                "player": player,
                "action": "ALL_IN",
                "observed_to_bb": target,
            }
        return {
            "kind": "action",
            "player": player,
            "action": "RAISE",
            "to_bb": target,
            "observed_to_bb": target,
        }
    return None


def state_from_pokerstars_prefix(text: str) -> HoldemState:
    """Reconstruct a policy-free state from an EN/FR PokerStars HH prefix.

    The caller supplies only text available before the decision being evaluated.
    Consequently this helper cannot consume a future street, future action or
    unrevealed card.  English and French action serializations are normalized to
    the same core actions before replay.

    The supported scope is the project's cash-game NLHE population: one small
    blind, one big blind and no ante/dead-blind accounting.  Unsupported forced
    bets fail closed rather than silently corrupting the pot.
    """
    lines = str(text or "").replace("\r", "").splitlines()
    seats: list[tuple[int, str, float]] = []
    for raw in lines:
        match = _SEAT_LINE_RE.match(raw.strip())
        if not match:
            continue
        seat, player, stack_text = int(match.group(1)), match.group(2).strip(), match.group(3)
        numbers = _numeric_tokens(stack_text)
        if not numbers:
            raise ValueError(f"missing stack in seat line: {raw!r}")
        seats.append((seat, player, numbers[0]))
    if len(seats) < 2:
        raise ValueError("HH prefix contains fewer than two seats")
    if len({name for _, name, _ in seats}) != len(seats):
        raise ValueError("duplicate player name in seat list")

    button_match = _BUTTON_RE.search("\n".join(lines))
    if not button_match:
        raise ValueError("HH prefix has no supported button marker")
    button_seat = int(button_match.group(1))
    player_by_seat = {seat: name for seat, name, _ in seats}
    if button_seat not in player_by_seat:
        raise ValueError("button seat is not occupied")
    button = player_by_seat[button_seat]

    players = {name for _, name, _ in seats}
    observed_sb: tuple[str, float] | None = None
    observed_bb: tuple[str, float] | None = None
    for raw in lines:
        event = _parse_hh_action(raw, players, 1.0)
        if not event or event.get("kind") != "blind":
            continue
        body = str(event["body"])
        amount_chips = event.get("amount_chips")
        if amount_chips is None:
            raise ValueError(f"blind amount missing: {raw!r}")
        if "small blind" in body or "petite blind" in body or "petite blinde" in body:
            observed_sb = (str(event["player"]), float(amount_chips))
        elif "big blind" in body or "grosse blind" in body or "grosse blinde" in body:
            observed_bb = (str(event["player"]), float(amount_chips))
    if observed_sb is None or observed_bb is None:
        raise ValueError("HH prefix must contain small- and big-blind posts")

    header = _header_blinds(text)
    if header is None:
        nominal_sb_chips, nominal_bb_chips = observed_sb[1], observed_bb[1]
    else:
        nominal_sb_chips, nominal_bb_chips = header
    if nominal_bb_chips <= 0:
        raise ValueError("invalid big blind")

    known_cards: dict[str, tuple[str, str]] = {}
    for raw in lines:
        for pattern in (
            r"^Dealt to (.+?) \[([^\]]+)\]$",
            r"^Distribu(?:é|e|ées|es) à (.+?) \[([^\]]+)\]$",
            r"^Distribue(?:e|es)? a (.+?) \[([^\]]+)\]$",
        ):
            match = re.match(pattern, raw.strip(), re.IGNORECASE)
            if match and match.group(1).strip() in players:
                cards = tuple(match.group(2).split())
                if len(cards) == 2 and all(_CARD_RE.match(c) for c in cards):
                    known_cards[match.group(1).strip()] = (cards[0], cards[1])
                break

    sorted_seats = sorted(seats, key=lambda row: row[0])
    seat_order = [name for _, name, _ in sorted_seats]
    stacks_bb = {name: stack / nominal_bb_chips for _, name, stack in sorted_seats}
    state = HoldemState.new_hand(
        stacks_bb=stacks_bb,
        seat_order=seat_order,
        button=button,
        small_blind_bb=nominal_sb_chips / nominal_bb_chips,
        big_blind_bb=1.0,
        hole_cards=known_cards,
    )
    if state.small_blind_player != observed_sb[0] or state.big_blind_player != observed_bb[0]:
        raise ValueError("observed blinds conflict with button/seat order")
    expected_sb = min(nominal_sb_chips, stacks_bb[observed_sb[0]] * nominal_bb_chips)
    expected_bb = min(nominal_bb_chips, stacks_bb[observed_bb[0]] * nominal_bb_chips)
    if abs(observed_sb[1] - expected_sb) > 1e-7 or abs(observed_bb[1] - expected_bb) > 1e-7:
        raise ValueError("observed blind amount conflicts with stack/blind structure")

    street = "preflop"
    for raw in lines:
        line = raw.strip()
        upper = line.upper()
        next_street: str | None = None
        if upper.startswith("*** FLOP ***"):
            next_street = "flop"
        elif upper.startswith(("*** TURN ***", "*** TOURNANT ***")):
            next_street = "turn"
        elif upper.startswith(("*** RIVER ***", "*** RIVIÈRE ***", "*** RIVIERE ***")):
            next_street = "river"
        elif upper.startswith(("*** SUMMARY ***", "*** RÉSUMÉ ***", "*** RESUME ***")):
            break
        if next_street is not None:
            cards = _cards_from_marker(line)
            expected = {"flop": 3, "turn": 4, "river": 5}[next_street]
            if len(cards) != expected or not all(_CARD_RE.match(card) for card in cards):
                raise ValueError(f"malformed {next_street} marker: {line!r}")
            if STREETS.index(next_street) != STREETS.index(street) + 1:
                raise ValueError("non-sequential street marker")
            state.advance_street(board_cards=cards)
            street = next_street
            continue

        event = _parse_hh_action(line, players, nominal_bb_chips)
        if not event or event.get("kind") == "blind":
            continue
        if event.get("kind") != "action":
            continue
        player = str(event["player"])
        state.apply_action(player, str(event["action"]), to_bb=event.get("to_bb"))
        action_record = state.action_log[-1]
        observed_paid = event.get("observed_paid_bb")
        if observed_paid is not None and abs(float(action_record["paid_bb"]) - float(observed_paid)) > 1e-7:
            raise ValueError(f"observed call amount conflicts with reconstructed state for {player}")
        observed_to = event.get("observed_to_bb")
        if observed_to is not None and abs(state.players[player].street_contribution_bb - float(observed_to)) > 1e-7:
            raise ValueError(f"observed wager target conflicts with reconstructed state for {player}")

    state.validate_invariants()
    return state

from __future__ import annotations

import re
from typing import Any

from tools.simulation.game_core import NoLimitHoldemState, RuleError

_AMOUNT_RE = r"([€$£]?\s*[\d.,]+)"


def amount(text: str) -> float:
    s = str(text).strip().replace(" ", "").replace("€", "").replace("$", "").replace("£", "")
    if "," in s and "." in s:
        s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        s = parts[0] + "." + parts[1] if len(parts) == 2 and len(parts[1]) != 3 else s.replace(",", "")
    return float(s)


def _cards_from_marker(line: str) -> list[list[str]]:
    return [x.split() for x in re.findall(r"\[([^\]]+)\]", line)]


def _action_line(line: str) -> dict[str, Any] | None:
    patterns = [
        ("fold", r"^(.+?)\s*:\s*(?:folds|se couche)\.?\s*$"),
        ("check", r"^(.+?)\s*:\s*(?:checks|parole|checke)\.?\s*$"),
        ("call", rf"^(.+?)\s*:\s*(?:calls|suit)\.?\s*{_AMOUNT_RE}(?:\s+(?:and is|et est)\s+all-in)?\.?\s*$"),
        ("bet", rf"^(.+?)\s*:\s*(?:bets|mise)\.?\s*{_AMOUNT_RE}(?:\s+(?:and is|et est)\s+all-in)?\.?\s*$"),
        (
            "raise",
            rf"^(.+?)\s*:\s*(?:raises|relance)\.?\s*{_AMOUNT_RE}\s+(?:to|à)\s+{_AMOUNT_RE}"
            rf"(?:\s+(?:and is|et est)\s+all-in)?\.?\s*$",
        ),
    ]
    for kind, pattern in patterns:
        m = re.match(pattern, line, flags=re.IGNORECASE)
        if not m:
            continue
        row: dict[str, Any] = {"player": m.group(1).strip(), "type": kind}
        if kind in ("call", "bet"):
            row["amount"] = amount(m.group(2))
        elif kind == "raise":
            row["increment"] = amount(m.group(2))
            row["target"] = amount(m.group(3))
        return row
    m = re.match(
        rf"^(?:Uncalled bet|Mise non suivie)\s*\({_AMOUNT_RE}\)\s*(?:returned to|retournée à)\s+(.+?)\.?\s*$",
        line,
        flags=re.IGNORECASE,
    )
    if m:
        return {"player": m.group(2).strip(), "type": "return", "amount": amount(m.group(1))}
    return None


def replay_public_hand(raw: str) -> dict[str, Any]:
    """Replay one EN/FR PokerStars public action stream into the shared game core.

    Decision snapshots are captured immediately before each voluntary action and
    contain only public state plus board cards already revealed at that point.
    """
    text = str(raw or "").replace("\r", "").replace("\ufeff", "")
    lines = [line.rstrip() for line in text.splitlines()]
    seats = []
    for line in lines:
        m = re.match(
            rf"^(?:Seat|Siège)\s+(\d+)\s*:\s*(.+?)\s+\({_AMOUNT_RE}\s+(?:in chips|en jetons)\)\s*$",
            line,
            flags=re.IGNORECASE,
        )
        if m:
            seats.append({"seat": int(m.group(1)), "name": m.group(2).strip(), "chips": amount(m.group(3))})
    if len(seats) < 2:
        raise ValueError("hand history contains fewer than two seats")
    seats.sort(key=lambda x: x["seat"])

    button_seat = None
    for line in lines:
        m = re.search(
            r"(?:Seat|Siège)\s+#?(\d+)\s+(?:is\s+(?:the\s+)?button|est\s+(?:au\s+)?bouton)",
            line,
            flags=re.IGNORECASE,
        )
        if m:
            button_seat = int(m.group(1))
            break
    if button_seat is None:
        raise ValueError("button seat not found")
    by_seat = {x["seat"]: x for x in seats}
    if button_seat not in by_seat:
        raise ValueError("button seat is not occupied")
    button = by_seat[button_seat]["name"]

    posts: list[dict[str, Any]] = []
    for line in lines:
        m = re.match(
            rf"^(.+?)\s*:\s*(?:posts\s+small\s+blind|met\s+la\s+petite\s+blind)\.?\s*{_AMOUNT_RE}"
            rf"(?:\s+(?:and is|et est)\s+all-in)?\.?\s*$",
            line,
            flags=re.IGNORECASE,
        )
        if m:
            posts.append({"kind": "SB", "player": m.group(1).strip(), "amount": amount(m.group(2))})
            continue
        m = re.match(
            rf"^(.+?)\s*:\s*(?:posts\s+big\s+blind|met\s+la\s+grosse\s+blind)\.?\s*{_AMOUNT_RE}"
            rf"(?:\s+(?:and is|et est)\s+all-in)?\.?\s*$",
            line,
            flags=re.IGNORECASE,
        )
        if m:
            posts.append({"kind": "BB", "player": m.group(1).strip(), "amount": amount(m.group(2))})
    sb_posts = [x for x in posts if x["kind"] == "SB"]
    bb_posts = [x for x in posts if x["kind"] == "BB"]
    if not sb_posts or not bb_posts:
        raise ValueError("small/big blind posts not found")
    sb_post, bb_post = sb_posts[0], bb_posts[0]
    bb_chips = float(bb_post["amount"])

    amount_token = r"[€$£]?\s*[\d.,]+"
    for candidate in lines[:3]:
        for group in re.findall(r"\(([^()]*)\)", candidate):
            blind_match = re.search(rf"({amount_token})\s*/\s*({amount_token})", group)
            if blind_match:
                nominal = amount(blind_match.group(2))
                if nominal > 0:
                    bb_chips = nominal
                    break
        else:
            continue
        break
    if bb_chips <= 0:
        raise ValueError("big blind must be positive")

    state = NoLimitHoldemState(
        seats=[x["name"] for x in seats],
        button=button,
        stacks_bb={x["name"]: x["chips"] / bb_chips for x in seats},
        small_blind_bb=sb_post["amount"] / bb_chips,
        big_blind_bb=1.0,
    )
    if state.small_blind_player != sb_post["player"] or state.big_blind_player != bb_post["player"]:
        raise ValueError("blind posts disagree with seat/button order")
    for post, player in ((sb_post, state.small_blind_player), (bb_post, state.big_blind_player)):
        observed = post["amount"] / bb_chips
        actual = state.street_committed_bb[player]
        if abs(observed - actual) > 1e-6:
            raise ValueError(f"blind amount disagrees with starting stack for {player}")

    trace: list[dict[str, Any]] = []
    current_street = "preflop"
    for line in lines:
        upper = line.upper()
        if upper.startswith("*** FLOP ***"):
            groups = _cards_from_marker(line)
            if not groups or len(groups[0]) != 3:
                raise ValueError("invalid flop marker")
            state.advance_street(groups[0])
            current_street = "flop"
            continue
        if upper.startswith("*** TURN ***"):
            groups = _cards_from_marker(line)
            if not groups:
                raise ValueError("invalid turn marker")
            new_cards = groups[-1]
            if len(new_cards) != 1:
                raise ValueError("turn marker must reveal one new card")
            state.advance_street(new_cards)
            current_street = "turn"
            continue
        if upper.startswith("*** RIVER ***"):
            groups = _cards_from_marker(line)
            if not groups:
                raise ValueError("invalid river marker")
            new_cards = groups[-1]
            if len(new_cards) != 1:
                raise ValueError("river marker must reveal one new card")
            state.advance_street(new_cards)
            current_street = "river"
            continue
        if upper.startswith("*** SHOW DOWN ***") or upper.startswith("*** ABATTAGE ***") or upper.startswith("*** SUMMARY ***"):
            break

        action = _action_line(line)
        if action is None:
            continue
        if action["type"] == "return":
            before = dict(state.refunds_bb)
            after = state.refund_uncalled()
            actual = after.get(action["player"], 0.0) - before.get(action["player"], 0.0)
            if abs(actual - action["amount"] / bb_chips) > 1e-6:
                raise RuleError("uncalled-return amount disagrees with game state")
            continue

        player = action["player"]
        if player not in state.seats:
            continue
        snap = state.to_snapshot(include_log=False)
        trace.append({
            "street": current_street,
            "player": player,
            "action": action["type"],
            "state_before": snap,
            "legal_before": state.legal_view(player),
        })
        kind = action["type"]
        if kind == "fold":
            state.apply_action(player, "FOLD")
        elif kind == "check":
            state.apply_action(player, "CHECK")
        elif kind == "call":
            expected = state.legal_view(player)["to_call_bb"]
            observed = action["amount"] / bb_chips
            if abs(expected - observed) > 1e-6:
                raise RuleError(f"call amount mismatch for {player}: expected {expected}, got {observed}")
            state.apply_action(player, "CALL")
        elif kind == "bet":
            target = state.street_committed_bb[player] + action["amount"] / bb_chips
            state.apply_action(player, "RAISE", target_total_bb=target)
        elif kind == "raise":
            target = action["target"] / bb_chips
            observed_increment = action["increment"] / bb_chips
            expected_increment = target - state.current_bet_bb
            if abs(expected_increment - observed_increment) > 1e-6:
                raise RuleError(
                    f"raise increment mismatch for {player}: expected {expected_increment}, got {observed_increment}"
                )
            state.apply_action(player, "RAISE", target_total_bb=target)
    return {
        "language": "fr" if re.search(r"\b(?:Siège|Partie|Distribuées|se couche|suit|mise|relance)\b", text, re.I) else "en",
        "big_blind_chips": bb_chips,
        "trace": trace,
        "final_state": state.to_snapshot(include_log=False),
    }

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Callable, Iterable, Mapping, Sequence
import copy

EPS = 1e-9
STREETS = ("preflop", "flop", "turn", "river")


class IllegalAction(ValueError):
    """Raised when an action violates no-limit hold'em betting rules."""


@dataclass
class PlayerState:
    name: str
    seat: int
    starting_stack_bb: float
    stack_bb: float
    total_contribution_bb: float = 0.0
    street_contribution_bb: float = 0.0
    folded: bool = False
    all_in: bool = False
    acted_this_round: bool = False
    last_action_bet_level_bb: float | None = None


@dataclass(frozen=True)
class Pot:
    amount_bb: float
    eligible: tuple[str, ...]
    contributors: tuple[str, ...]


@dataclass
class Settlement:
    gross_pot_bb: float
    contested_pot_bb: float
    rake_bb: float
    refunds_bb: dict[str, float]
    payouts_bb: dict[str, float]
    pots: list[Pot]
    net_by_player_bb: dict[str, float]


@dataclass
class HoldemState:
    """Policy-free NLHE betting/accounting state.

    The engine owns chips, legal actions and street progression only. Policies may
    query :meth:`player_view` and call :meth:`apply_action`; hidden cards and
    future runout are never included in a player view before they are public.
    """

    players: dict[str, PlayerState]
    seat_order: list[str]
    button: str
    small_blind_bb: float
    big_blind_bb: float
    small_blind_player: str
    big_blind_player: str
    street: str = "preflop"
    current_bet_bb: float = 0.0
    last_full_raise_bb: float = 0.0
    needs_action: set[str] = field(default_factory=set)
    next_actor: str | None = None
    action_no: int = 0
    board_runout: tuple[str, ...] = ()
    hole_cards: dict[str, tuple[str, str]] = field(default_factory=dict)
    revealed_board_count: int = 0
    terminal_reason: str | None = None
    action_log: list[dict] = field(default_factory=list)

    @classmethod
    def new_hand(
        cls,
        *,
        stacks_bb: Mapping[str, float],
        seat_order: Sequence[str],
        button: str,
        small_blind_bb: float = 0.5,
        big_blind_bb: float = 1.0,
        hole_cards: Mapping[str, Sequence[str]] | None = None,
        board_runout: Sequence[str] | None = None,
    ) -> "HoldemState":
        names = list(seat_order)
        if len(names) < 2 or len(set(names)) != len(names):
            raise ValueError("seat_order must contain at least two unique players")
        if set(names) != set(stacks_bb):
            raise ValueError("stacks_bb keys must exactly match seat_order")
        if button not in stacks_bb:
            raise ValueError("button must be seated")
        if big_blind_bb <= 0 or small_blind_bb < 0 or small_blind_bb > big_blind_bb:
            raise ValueError("invalid blind structure")
        players = {
            name: PlayerState(
                name=name,
                seat=i,
                starting_stack_bb=float(stacks_bb[name]),
                stack_bb=float(stacks_bb[name]),
            )
            for i, name in enumerate(names)
        }
        if any(p.starting_stack_bb < 0 for p in players.values()):
            raise ValueError("negative stack")
        state = cls(
            players=players,
            seat_order=names,
            button=button,
            small_blind_bb=float(small_blind_bb),
            big_blind_bb=float(big_blind_bb),
            small_blind_player="",
            big_blind_player="",
            last_full_raise_bb=float(big_blind_bb),
            hole_cards={k: tuple(v) for k, v in (hole_cards or {}).items()},
            board_runout=tuple(board_runout or ()),
        )
        if state.hole_cards and set(state.hole_cards) - set(names):
            raise ValueError("hole cards include an unknown player")
        if any(len(cards) != 2 for cards in state.hole_cards.values()):
            raise ValueError("each hole-card entry must contain exactly two cards")
        if len(state.board_runout) > 5:
            raise ValueError("board_runout cannot contain more than five cards")
        state._post_blinds_and_start()
        state.validate_invariants()
        return state

    def _next_name(self, name: str, *, candidates: Iterable[str] | None = None) -> str | None:
        allowed = set(candidates) if candidates is not None else set(self.seat_order)
        start = self.seat_order.index(name)
        for offset in range(1, len(self.seat_order) + 1):
            candidate = self.seat_order[(start + offset) % len(self.seat_order)]
            if candidate in allowed:
                return candidate
        return None

    def _post(self, name: str, amount_bb: float, kind: str) -> None:
        p = self.players[name]
        paid = min(max(0.0, amount_bb), p.stack_bb)
        p.stack_bb -= paid
        p.total_contribution_bb += paid
        p.street_contribution_bb += paid
        p.all_in = p.stack_bb <= EPS
        self.action_log.append({
            "action_no": self.action_no,
            "street": "preflop",
            "player": name,
            "action": kind,
            "paid_bb": paid,
        })
        self.action_no += 1

    def _post_blinds_and_start(self) -> None:
        if len(self.seat_order) == 2:
            sb = self.button
            bb = self._next_name(sb)
            first = sb
        else:
            sb = self._next_name(self.button)
            bb = self._next_name(sb)
            first = self._next_name(bb)
        assert sb is not None and bb is not None and first is not None
        self.small_blind_player, self.big_blind_player = sb, bb
        self._post(sb, self.small_blind_bb, "POST_SB")
        self._post(bb, self.big_blind_bb, "POST_BB")
        # A short all-in big blind does not reduce the nominal preflop bring-in.
        # Players who can act still face the full big blind.
        self.current_bet_bb = self.big_blind_bb
        self.last_full_raise_bb = self.big_blind_bb
        self.needs_action = {name for name, p in self.players.items() if not p.folded and not p.all_in}
        self.next_actor = self._first_from(first, self.needs_action)
        self._auto_finish_if_no_betting_possible()

    def _first_from(self, preferred: str, candidates: Iterable[str]) -> str | None:
        allowed = set(candidates)
        if preferred in allowed:
            return preferred
        return self._next_name(preferred, candidates=allowed)

    def active_players(self) -> list[str]:
        return [name for name in self.seat_order if not self.players[name].folded]

    def live_non_allin(self) -> list[str]:
        return [name for name in self.active_players() if not self.players[name].all_in]

    def to_call_bb(self, player: str) -> float:
        p = self.players[player]
        return max(0.0, self.current_bet_bb - p.street_contribution_bb)

    def incremental_cost_to_bb(self, player: str, target_street_total_bb: float) -> float:
        """Cost from the current decision point; prior contributions are sunk."""
        return max(0.0, float(target_street_total_bb) - self.players[player].street_contribution_bb)

    def _raise_reopened_for(self, player: str) -> bool:
        p = self.players[player]
        if p.last_action_bet_level_bb is None:
            return True
        return self.current_bet_bb - p.last_action_bet_level_bb >= self.last_full_raise_bb - EPS

    def legal_actions(self, player: str | None = None) -> dict:
        player = player or self.next_actor
        if player is None or player not in self.needs_action:
            return {"player": player, "actions": []}
        p = self.players[player]
        to_call = self.to_call_bb(player)
        max_target = p.street_contribution_bb + p.stack_bb
        actions = ["FOLD", "CALL"] if to_call > EPS else ["CHECK"]
        can_increase = max_target > self.current_bet_bb + EPS
        can_raise = can_increase and self._raise_reopened_for(player) and self._opponent_can_contest(player)
        min_to = None
        if can_raise:
            if self.current_bet_bb <= EPS:
                min_to = min(max_target, self.big_blind_bb)
                actions.append("BET")
            else:
                # An incomplete opening all-in may be completed to one full bet;
                # it does not require a full raise on top of the short wager.
                min_to = (
                    self.big_blind_bb
                    if self.current_bet_bb < self.big_blind_bb - EPS
                    else self.current_bet_bb + self.last_full_raise_bb
                )
                actions.append("RAISE")
            if max_target < float(min_to) - EPS:
                min_to = max_target  # short all-in is the only legal aggression
        allin_is_call = to_call > EPS and max_target <= self.current_bet_bb + EPS
        allin_is_raise = max_target > self.current_bet_bb + EPS and can_raise
        if p.stack_bb > EPS and (allin_is_call or allin_is_raise):
            actions.append("ALL_IN")
        return {
            "player": player,
            "street": self.street,
            "to_call_bb": min(to_call, p.stack_bb),
            "current_bet_bb": self.current_bet_bb,
            "min_raise_to_bb": min_to,
            "max_to_bb": max_target,
            "raise_reopened": self._raise_reopened_for(player),
            "actions": actions,
        }

    def _opponent_can_contest(self, player: str) -> bool:
        return any(
            name != player and not p.folded and p.stack_bb > EPS
            for name, p in self.players.items()
        )

    def apply_action(self, player: str, action: str, *, to_bb: float | None = None) -> None:
        if self.terminal_reason:
            raise IllegalAction("hand is already terminal")
        if player != self.next_actor or player not in self.needs_action:
            raise IllegalAction(f"{player} is not the next actor")
        action = action.upper().replace("-", "_")
        p = self.players[player]
        to_call = self.to_call_bb(player)
        old_current = self.current_bet_bb
        old_paid = p.street_contribution_bb
        max_target = old_paid + p.stack_bb
        aggressive = False
        full_raise = False

        if action == "FOLD":
            if to_call <= EPS:
                raise IllegalAction("cannot fold when checking is available")
            p.folded = True
            self.needs_action.discard(player)
            paid = 0.0
        elif action == "CHECK":
            if to_call > EPS:
                raise IllegalAction("illegal check facing a bet")
            self.needs_action.discard(player)
            paid = 0.0
        elif action == "CALL":
            if to_call <= EPS:
                raise IllegalAction("nothing to call")
            paid = min(to_call, p.stack_bb)
            self._pay(p, paid)
            self.needs_action.discard(player)
        elif action in {"BET", "RAISE", "ALL_IN"}:
            if action == "BET" and old_current > EPS:
                raise IllegalAction("BET is only legal when no wager is open")
            if action == "RAISE" and old_current <= EPS:
                raise IllegalAction("RAISE requires an open wager")
            if action == "ALL_IN":
                target = max_target
                if target <= old_current + EPS:
                    # all-in call (or all-in check with zero stack cannot occur)
                    if to_call <= EPS:
                        raise IllegalAction("all-in does not increase the wager")
                    paid = min(to_call, p.stack_bb)
                    self._pay(p, paid)
                    self.needs_action.discard(player)
                    action = "CALL"
                else:
                    aggressive = True
            else:
                if to_bb is None:
                    raise IllegalAction(f"{action} requires to_bb")
                target = float(to_bb)
                if target > max_target + EPS:
                    raise IllegalAction("target exceeds stack")
                if target <= old_current + EPS:
                    raise IllegalAction("aggression must increase the current bet")
                aggressive = True

            if aggressive:
                if not self._opponent_can_contest(player):
                    raise IllegalAction("cannot bet into an uncontestable pot")
                if not self._raise_reopened_for(player):
                    raise IllegalAction("betting has not been reopened for this player")
                target = max_target if action == "ALL_IN" else float(to_bb)
                opening = old_current <= EPS
                if opening:
                    min_target = self.big_blind_bb
                elif old_current < self.big_blind_bb - EPS:
                    min_target = self.big_blind_bb
                else:
                    min_target = old_current + self.last_full_raise_bb
                is_allin = target >= max_target - EPS
                if target < min_target - EPS and not is_allin:
                    raise IllegalAction(f"minimum {'bet' if opening else 'raise'} is to {min_target:g} BB")
                paid = target - old_paid
                self._pay(p, paid)
                increase = target - old_current
                full_raise = increase >= self.last_full_raise_bb - EPS
                self.current_bet_bb = target
                if full_raise:
                    self.last_full_raise_bb = increase
                self.needs_action = {
                    name for name, q in self.players.items()
                    if name != player and not q.folded and not q.all_in
                }
        else:
            raise IllegalAction(f"unknown action {action!r}")

        p.acted_this_round = True
        p.last_action_bet_level_bb = self.current_bet_bb
        if p.stack_bb <= EPS:
            p.all_in = True
            self.needs_action.discard(player)
        self.action_log.append({
            "action_no": self.action_no,
            "street": self.street,
            "player": player,
            "action": action,
            "paid_bb": paid,
            "street_to_bb": p.street_contribution_bb,
            "to_call_before_bb": to_call,
            "current_bet_before_bb": old_current,
            "current_bet_after_bb": self.current_bet_bb,
            "full_raise": full_raise,
            "all_in": p.all_in,
        })
        self.action_no += 1
        self._after_action(player)
        self.validate_invariants()

    def _pay(self, p: PlayerState, amount_bb: float) -> None:
        if amount_bb < -EPS or amount_bb > p.stack_bb + EPS:
            raise IllegalAction("invalid chip payment")
        amount_bb = min(max(0.0, amount_bb), p.stack_bb)
        p.stack_bb -= amount_bb
        p.street_contribution_bb += amount_bb
        p.total_contribution_bb += amount_bb
        if p.stack_bb <= EPS:
            p.stack_bb = 0.0
            p.all_in = True

    def _after_action(self, actor: str) -> None:
        live = self.active_players()
        if len(live) == 1:
            self.terminal_reason = "uncontested"
            self.next_actor = None
            self.needs_action.clear()
            return

        self.needs_action = {
            name for name in self.needs_action
            if not self.players[name].folded and not self.players[name].all_in
        }
        self._auto_finish_if_no_betting_possible()
        if self.terminal_reason or not self.needs_action:
            self.next_actor = None
            return
        self.next_actor = self._next_name(actor, candidates=self.needs_action)

    def _auto_finish_if_no_betting_possible(self) -> None:
        if len(self.active_players()) <= 1:
            return
        actors = self.live_non_allin()
        if len(actors) == 0:
            self.needs_action.clear()
            return
        if len(actors) == 1:
            only = actors[0]
            # If the sole player with chips still owes an all-in wager, they must
            # call or fold. Otherwise no further betting can create a contested pot.
            if self.to_call_bb(only) <= EPS:
                self.needs_action.clear()
            else:
                self.needs_action = {only}
                self.next_actor = only

    def validate_invariants(self) -> None:
        total_start = 0.0
        total_accounted = 0.0
        for p in self.players.values():
            if p.stack_bb < -EPS or p.total_contribution_bb < -EPS or p.street_contribution_bb < -EPS:
                raise RuntimeError("negative chip accounting")
            if p.street_contribution_bb > p.total_contribution_bb + EPS:
                raise RuntimeError("street contribution exceeds total contribution")
            if abs((p.stack_bb + p.total_contribution_bb) - p.starting_stack_bb) > 1e-7:
                raise RuntimeError(f"chip conservation failure for {p.name}")
            if p.all_in and p.stack_bb > EPS:
                raise RuntimeError(f"all-in player {p.name} still has chips")
            total_start += p.starting_stack_bb
            total_accounted += p.stack_bb + p.total_contribution_bb
        if abs(total_start - total_accounted) > 1e-7:
            raise RuntimeError("global chip conservation failure")
        highest_paid = max((p.street_contribution_bb for p in self.players.values()), default=0.0)
        if self.current_bet_bb + EPS < highest_paid:
            raise RuntimeError("current bet below a player's street contribution")

    def betting_round_complete(self) -> bool:
        return not self.terminal_reason and not self.needs_action

    def advance_street(self, *, board_cards: Sequence[str] | None = None) -> None:
        if self.terminal_reason:
            raise IllegalAction("hand is terminal")
        if self.needs_action:
            raise IllegalAction("betting round is not complete")
        idx = STREETS.index(self.street)
        if idx == len(STREETS) - 1:
            self.terminal_reason = "showdown"
            self.next_actor = None
            return
        self.street = STREETS[idx + 1]
        required = {"flop": 3, "turn": 4, "river": 5}[self.street]
        if board_cards is not None:
            public = tuple(board_cards)
            if len(public) != required:
                raise ValueError(f"{self.street} requires {required} public board cards")
            overlap = min(len(self.board_runout), required)
            if self.board_runout[:overlap] != public[:overlap]:
                raise ValueError("observed board conflicts with stored runout")
            if len(self.board_runout) < required:
                self.board_runout = public
        self.revealed_board_count = required
        for p in self.players.values():
            p.street_contribution_bb = 0.0
            p.acted_this_round = False
            p.last_action_bet_level_bb = None
        self.current_bet_bb = 0.0
        self.last_full_raise_bb = self.big_blind_bb
        self.needs_action = {name for name in self.active_players() if not self.players[name].all_in}
        first = self._next_name(self.button, candidates=self.needs_action) if self.needs_action else None
        self.next_actor = first
        self._auto_finish_if_no_betting_possible()
        self.validate_invariants()

    def runout_to_showdown(self) -> None:
        """Advance through actionless streets once all live players are all-in."""
        while not self.terminal_reason and not self.needs_action:
            if self.street == "river":
                self.terminal_reason = "showdown"
                break
            self.advance_street()

    def player_view(self, observer: str) -> dict:
        if observer not in self.players:
            raise ValueError("unknown observer")
        return {
            "street": self.street,
            "board": list(self.board_runout[: self.revealed_board_count]),
            "hero": observer,
            "hero_cards": list(self.hole_cards.get(observer, ())),
            "players": {
                name: {
                    "stack_bb": p.stack_bb,
                    "street_contribution_bb": p.street_contribution_bb,
                    "total_contribution_bb": p.total_contribution_bb,
                    "folded": p.folded,
                    "all_in": p.all_in,
                }
                for name, p in self.players.items()
            },
            "current_bet_bb": self.current_bet_bb,
            "to_call_bb": self.to_call_bb(observer),
            "next_actor": self.next_actor,
            "legal": self.legal_actions(observer) if observer == self.next_actor else {"actions": []},
        }

    def decision_snapshot(self, observer: str) -> dict:
        """Redacted deterministic snapshot safe to pass to a decision policy."""
        return self.player_view(observer)

    def checkpoint(self) -> dict:
        """Full deterministic internal state for trusted stop/resume."""
        return {
            "schema": "nlhe-full-hand-state/v1",
            "players": {name: asdict(p) for name, p in self.players.items()},
            "seat_order": list(self.seat_order),
            "button": self.button,
            "small_blind_bb": self.small_blind_bb,
            "big_blind_bb": self.big_blind_bb,
            "small_blind_player": self.small_blind_player,
            "big_blind_player": self.big_blind_player,
            "street": self.street,
            "current_bet_bb": self.current_bet_bb,
            "last_full_raise_bb": self.last_full_raise_bb,
            "needs_action": sorted(self.needs_action),
            "next_actor": self.next_actor,
            "action_no": self.action_no,
            "board_runout": list(self.board_runout),
            "hole_cards": {k: list(v) for k, v in self.hole_cards.items()},
            "revealed_board_count": self.revealed_board_count,
            "terminal_reason": self.terminal_reason,
            "action_log": copy.deepcopy(self.action_log),
        }

    @classmethod
    def from_checkpoint(cls, data: Mapping) -> "HoldemState":
        if data.get("schema") != "nlhe-full-hand-state/v1":
            raise ValueError("unsupported checkpoint schema")
        state = cls(
            players={name: PlayerState(**payload) for name, payload in data["players"].items()},
            seat_order=list(data["seat_order"]),
            button=str(data["button"]),
            small_blind_bb=float(data["small_blind_bb"]),
            big_blind_bb=float(data["big_blind_bb"]),
            small_blind_player=str(data["small_blind_player"]),
            big_blind_player=str(data["big_blind_player"]),
            street=str(data["street"]),
            current_bet_bb=float(data["current_bet_bb"]),
            last_full_raise_bb=float(data["last_full_raise_bb"]),
            needs_action=set(data["needs_action"]),
            next_actor=data["next_actor"],
            action_no=int(data["action_no"]),
            board_runout=tuple(data.get("board_runout", ())),
            hole_cards={k: tuple(v) for k, v in data.get("hole_cards", {}).items()},
            revealed_board_count=int(data.get("revealed_board_count", 0)),
            terminal_reason=data.get("terminal_reason"),
            action_log=copy.deepcopy(list(data.get("action_log", []))),
        )
        state.validate_invariants()
        return state

    def _contribution_levels(self) -> list[float]:
        return sorted({
            round(p.total_contribution_bb, 12)
            for p in self.players.values()
            if p.total_contribution_bb > EPS
        })

    def build_pots(self) -> tuple[list[Pot], dict[str, float]]:
        levels = self._contribution_levels()
        pots: list[Pot] = []
        refunds = {name: 0.0 for name in self.players}
        previous = 0.0
        for level in levels:
            contributors = [name for name, p in self.players.items() if p.total_contribution_bb >= level - EPS]
            amount = (level - previous) * len(contributors)
            previous = level
            if amount <= EPS:
                continue
            if len(contributors) == 1:
                refunds[contributors[0]] += amount
                continue
            eligible = [name for name in contributors if not self.players[name].folded]
            if not eligible:
                raise RuntimeError("pot has no eligible player")
            pots.append(Pot(amount_bb=amount, eligible=tuple(eligible), contributors=tuple(contributors)))
        return pots, {k: v for k, v in refunds.items() if v > EPS}

    def settle(
        self,
        ranks: Mapping[str, object],
        *,
        rake_net: Callable[[float], float] | None = None,
    ) -> Settlement:
        """Settle all pots using comparable ranks (higher is better).

        `rake_net(total_contested)` returns the post-rake contested pot. Applying
        rake once avoids side-pot cap multiplication; the net amount is allocated
        proportionally across pots before winner splitting.
        """
        pots, refunds = self.build_pots()
        contested = sum(p.amount_bb for p in pots)
        gross = sum(p.total_contribution_bb for p in self.players.values())
        net_contested = contested if rake_net is None else float(rake_net(contested))
        if net_contested < -EPS or net_contested > contested + EPS:
            raise ValueError("rake_net returned an invalid amount")
        scale = (net_contested / contested) if contested > EPS else 1.0
        payouts = {name: 0.0 for name in self.players}
        for pot in pots:
            if len(pot.eligible) == 1:
                winners = [pot.eligible[0]]
            else:
                missing = [name for name in pot.eligible if name not in ranks]
                if missing:
                    raise ValueError(f"missing rank for eligible player(s): {missing}")
                best_rank = max(ranks[name] for name in pot.eligible)
                winners = [name for name in pot.eligible if ranks[name] == best_rank]
            share = pot.amount_bb * scale / len(winners)
            for name in winners:
                payouts[name] += share
        net_by_player = {
            name: payouts[name] + refunds.get(name, 0.0) - p.total_contribution_bb
            for name, p in self.players.items()
        }
        rake = contested - net_contested
        lhs = sum(payouts.values()) + sum(refunds.values()) + rake
        if abs(lhs - gross) > 1e-7:
            raise RuntimeError(f"chip conservation failure: {lhs} != {gross}")
        return Settlement(
            gross_pot_bb=gross,
            contested_pot_bb=contested,
            rake_bb=rake,
            refunds_bb=refunds,
            payouts_bb={k: v for k, v in payouts.items() if v > EPS},
            pots=pots,
            net_by_player_bb=net_by_player,
        )


def replay_normalized_actions(state: HoldemState, actions: Sequence[Mapping]) -> HoldemState:
    """Replay a language-neutral HH action stream up to the supplied prefix.

    HH parsers may normalize English/French text into the same records. This
    function intentionally consumes only prior actions, so a caller can build the
    exact state before each historical decision without future information.
    """
    for item in actions:
        street = str(item.get("street", state.street)).lower()
        while STREETS.index(state.street) < STREETS.index(street):
            if state.needs_action:
                raise IllegalAction("cannot advance across an incomplete betting round")
            state.advance_street()
        state.apply_action(str(item["player"]), str(item["action"]), to_bb=item.get("to_bb"))
    return state

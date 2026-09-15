from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

EPS = 1e-9
STREETS = ("preflop", "flop", "turn", "river")
SNAPSHOT_SCHEMA = "nlhe-game-state/v1"


class RuleError(ValueError):
    """Raised when an action violates the no-limit hold'em betting rules."""


@dataclass(frozen=True)
class PotLayer:
    amount_bb: float
    cap_bb: float
    contributors: tuple[str, ...]
    eligible: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "amount_bb": _r(self.amount_bb),
            "cap_bb": _r(self.cap_bb),
            "contributors": list(self.contributors),
            "eligible": list(self.eligible),
        }


@dataclass(frozen=True)
class Settlement:
    terminal: str
    gross_pot_bb: float
    net_pot_bb: float
    rake_bb: float
    refunds_bb: dict[str, float]
    payouts_bb: dict[str, float]
    net_results_bb: dict[str, float]
    pots: tuple[PotLayer, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "terminal": self.terminal,
            "gross_pot_bb": _r(self.gross_pot_bb),
            "net_pot_bb": _r(self.net_pot_bb),
            "rake_bb": _r(self.rake_bb),
            "refunds_bb": {k: _r(v) for k, v in self.refunds_bb.items()},
            "payouts_bb": {k: _r(v) for k, v in self.payouts_bb.items()},
            "net_results_bb": {k: _r(v) for k, v in self.net_results_bb.items()},
            "pots": [x.as_dict() for x in self.pots],
        }


def _r(value: float) -> float:
    return round(float(value), 9)


def _nonnegative(value: float, name: str) -> float:
    x = float(value)
    if x < -EPS:
        raise ValueError(f"{name} must be non-negative")
    return max(0.0, x)


class NoLimitHoldemState:
    """Policy-free NLHE betting/accounting state.

    The core stores only public state. Hole cards never enter the object; showdown
    ranks are supplied only when settling a completed hand.
    """

    def __init__(
        self,
        *,
        seats: Sequence[str],
        button: str,
        stacks_bb: Mapping[str, float],
        small_blind_bb: float = 0.5,
        big_blind_bb: float = 1.0,
    ) -> None:
        if len(seats) < 2:
            raise ValueError("at least two seats are required")
        if len(set(seats)) != len(seats):
            raise ValueError("seat names must be unique")
        if button not in seats:
            raise ValueError("button must be seated")
        if set(stacks_bb) != set(seats):
            raise ValueError("stacks_bb must cover exactly the seated players")
        self.seats = tuple(seats)
        self.button = button
        self.small_blind_bb = _nonnegative(small_blind_bb, "small_blind_bb")
        self.big_blind_bb = _nonnegative(big_blind_bb, "big_blind_bb")
        if self.big_blind_bb <= EPS:
            raise ValueError("big blind must be positive")
        if self.small_blind_bb > self.big_blind_bb + EPS:
            raise ValueError("small blind cannot exceed big blind")

        self.starting_stacks_bb = {p: _nonnegative(stacks_bb[p], f"stack[{p}]") for p in self.seats}
        self.stacks_bb = dict(self.starting_stacks_bb)
        self.total_committed_bb = {p: 0.0 for p in self.seats}
        self.street_committed_bb = {p: 0.0 for p in self.seats}
        self.folded = {p: False for p in self.seats}
        self.all_in = {p: False for p in self.seats}
        self.street = "preflop"
        self.board: list[str] = []
        self.current_bet_bb = 0.0
        self.last_full_raise_bb = self.big_blind_bb
        self.full_bet_established = False
        self.acted_since_full_raise: set[str] = set()
        self.pending: list[str] = []
        self.action_log: list[dict[str, Any]] = []
        self.refunds_bb = {p: 0.0 for p in self.seats}
        self.settlement: Settlement | None = None

        if len(self.seats) == 2:
            self.small_blind_player = self.button
            self.big_blind_player = self._next_seat(self.button)
        else:
            self.small_blind_player = self._next_seat(self.button)
            self.big_blind_player = self._next_seat(self.small_blind_player)

        self._post_forced(self.small_blind_player, self.small_blind_bb)
        self._post_forced(self.big_blind_player, self.big_blind_bb)
        # A short all-in blind does not reduce the nominal preflop bring-in.
        # Contributions remain actual chips, while the live price stays one BB.
        self.current_bet_bb = self.big_blind_bb
        self.full_bet_established = True
        self.last_full_raise_bb = self.big_blind_bb
        self.pending = self._ordered_from(self._next_seat(self.big_blind_player), actionable_only=True)
        self._auto_close_dry_action()

    @property
    def pot_bb(self) -> float:
        return _r(sum(self.total_committed_bb.values()))

    @property
    def live_players(self) -> list[str]:
        return [p for p in self.seats if not self.folded[p]]

    @property
    def betting_complete(self) -> bool:
        return not self.pending

    @property
    def next_actor(self) -> str | None:
        return self.pending[0] if self.pending else None

    def legal_view(self, player: str | None = None) -> dict[str, Any]:
        player = player or self.next_actor
        if player is None:
            raise RuleError("no player is pending")
        if player not in self.seats:
            raise KeyError(player)
        if self.folded[player] or self.all_in[player]:
            raise RuleError("folded/all-in player cannot act")
        if self.pending and player != self.pending[0]:
            raise RuleError(f"{player} is not next to act")

        paid = self.street_committed_bb[player]
        remaining = self.stacks_bb[player]
        to_call_full = max(0.0, self.current_bet_bb - paid)
        call_cost = min(to_call_full, remaining)
        max_to = paid + remaining
        opponents_can_respond = any(
            q != player and not self.folded[q] and not self.all_in[q] and self.stacks_bb[q] > EPS
            for q in self.seats
        )
        # A single short all-in does not reopen action, but several short all-ins
        # can cumulatively do so once the actor faces at least one full raise more
        # than the price at which they last acted (their current contribution).
        raise_reopened = (
            player not in self.acted_since_full_raise
            or to_call_full + EPS >= self.last_full_raise_bb
        )
        can_increase = max_to > self.current_bet_bb + EPS
        can_raise = raise_reopened and can_increase and opponents_can_respond
        min_raise_to = None
        if can_raise:
            if not self.full_bet_established:
                min_raise_to = self.big_blind_bb
            else:
                min_raise_to = self.current_bet_bb + self.last_full_raise_bb

        legal = []
        if to_call_full > EPS:
            legal.extend(["FOLD", "CALL"])
        else:
            legal.append("CHECK")
        if can_raise:
            legal.append("RAISE")

        return {
            "street": self.street,
            "actor": player,
            "pot_before_bb": self.pot_bb,
            "actor_sunk_total_bb": _r(self.total_committed_bb[player]),
            "actor_street_contribution_bb": _r(paid),
            "actor_remaining_bb": _r(remaining),
            "current_price_bb": _r(self.current_bet_bb),
            "to_call_bb": _r(call_cost),
            "full_to_call_bb": _r(to_call_full),
            "free_check": to_call_full <= EPS,
            "legal_actions": legal,
            "raise_reopened": raise_reopened,
            "min_raise_to_bb": None if min_raise_to is None else _r(min_raise_to),
            "max_raise_to_bb": _r(max_to),
            "remaining_to_act": list(self.pending[1:]) if self.pending and player == self.pending[0] else [],
        }

    def apply_action(self, player: str, action: str, *, target_total_bb: float | None = None) -> dict[str, Any]:
        if self.settlement is not None:
            raise RuleError("hand is already settled")
        view = self.legal_view(player)
        action = str(action).upper()
        if action not in view["legal_actions"]:
            raise RuleError(f"{action} is not legal for {player}: {view['legal_actions']}")

        before = self.to_snapshot(include_log=False)

        if action == "FOLD":
            self.folded[player] = True
            self.acted_since_full_raise.add(player)
            self._consume_pending(player)
        elif action == "CHECK":
            self.acted_since_full_raise.add(player)
            self._consume_pending(player)
        elif action == "CALL":
            self._commit(player, view["to_call_bb"])
            self.acted_since_full_raise.add(player)
            self._consume_pending(player)
        else:
            if target_total_bb is None:
                raise RuleError("RAISE requires target_total_bb")
            target = float(target_total_bb)
            max_to = float(view["max_raise_to_bb"])
            if target > max_to + EPS:
                raise RuleError("raise target exceeds actor stack")
            if target <= self.current_bet_bb + EPS:
                raise RuleError("raise target must increase the current price")
            if target < self.street_committed_bb[player] - EPS:
                raise RuleError("raise target cannot reduce contribution")

            min_to = view["min_raise_to_bb"]
            is_all_in = abs(target - max_to) <= EPS
            if min_to is not None and target + EPS < float(min_to) and not is_all_in:
                raise RuleError(f"raise target below minimum {min_to}")

            old_price = self.current_bet_bb
            incremental = target - self.street_committed_bb[player]
            self._commit(player, incremental)
            new_price = self.street_committed_bb[player]
            raise_inc = new_price - old_price

            if not self.full_bet_established:
                full_raise = new_price + EPS >= self.big_blind_bb
                if full_raise:
                    self.full_bet_established = True
                    self.last_full_raise_bb = new_price
            else:
                full_raise = raise_inc + EPS >= self.last_full_raise_bb
                if full_raise:
                    self.last_full_raise_bb = raise_inc

            self.current_bet_bb = max(self.current_bet_bb, new_price)
            if full_raise:
                self.acted_since_full_raise = {player}
            else:
                self.acted_since_full_raise.add(player)
            self.pending = self._ordered_from(self._next_seat(player), actionable_only=True, exclude={player})
            self._auto_close_dry_action()

        self._auto_close_dry_action()
        record = {
            "index": len(self.action_log),
            "street": self.street,
            "player": player,
            "action": action,
            "target_total_bb": None if target_total_bb is None else _r(float(target_total_bb)),
            "incremental_cost_bb": _r(self.total_committed_bb[player] - before["total_committed_bb"][player]),
            "state_before": self._decision_digest(before, player),
            "state_after": self._decision_digest(self.to_snapshot(include_log=False), self.next_actor),
        }
        self.action_log.append(record)
        return record

    def advance_street(self, board_cards: Sequence[str]) -> None:
        if self.settlement is not None:
            raise RuleError("hand is already settled")
        if not self.betting_complete:
            raise RuleError("cannot advance while betting is pending")
        if len(self.live_players) <= 1:
            raise RuleError("hand ended by folds; settle it instead")
        i = STREETS.index(self.street)
        if i >= len(STREETS) - 1:
            raise RuleError("river is the final street")
        expected = 3 if self.street == "preflop" else 1
        if len(board_cards) != expected:
            raise ValueError(f"advancing from {self.street} requires {expected} board card(s)")
        cards = [str(c) for c in board_cards]
        if len(set(self.board + cards)) != len(self.board) + len(cards):
            raise ValueError("duplicate board card")
        self.board.extend(cards)
        self.street = STREETS[i + 1]
        self.street_committed_bb = {p: 0.0 for p in self.seats}
        self.current_bet_bb = 0.0
        self.last_full_raise_bb = self.big_blind_bb
        self.full_bet_established = False
        self.acted_since_full_raise = set()
        first = self._next_seat(self.button)
        self.pending = self._ordered_from(first, actionable_only=True)
        self._auto_close_dry_action()

    def refund_uncalled(self) -> dict[str, float]:
        if self.settlement is not None:
            return dict(self.refunds_bb)
        ranked = sorted(((v, p) for p, v in self.total_committed_bb.items()), reverse=True)
        if not ranked or ranked[0][0] <= EPS:
            return dict(self.refunds_bb)
        top, player = ranked[0]
        second = ranked[1][0] if len(ranked) > 1 else 0.0
        tied_top = sum(1 for value, _ in ranked if abs(value - top) <= EPS)
        if tied_top == 1 and top > second + EPS:
            amount = top - second
            self.total_committed_bb[player] -= amount
            street_refund = min(amount, self.street_committed_bb[player])
            self.street_committed_bb[player] -= street_refund
            self.stacks_bb[player] += amount
            self.refunds_bb[player] += amount
            self.current_bet_bb = max(self.street_committed_bb.values(), default=0.0)
        return {p: _r(v) for p, v in self.refunds_bb.items()}

    def pot_layers(self) -> tuple[PotLayer, ...]:
        contributions = {p: _r(v) for p, v in self.total_committed_bb.items() if v > EPS}
        levels = sorted(set(contributions.values()))
        prev = 0.0
        out: list[PotLayer] = []
        for cap in levels:
            contributors = tuple(p for p in self.seats if self.total_committed_bb[p] + EPS >= cap)
            amount = (cap - prev) * len(contributors)
            eligible = tuple(p for p in contributors if not self.folded[p])
            if amount > EPS:
                if not eligible:
                    raise RuleError("pot layer has no eligible player; uncalled chips were not normalized")
                out.append(PotLayer(_r(amount), _r(cap), contributors, eligible))
            prev = cap
        return tuple(out)

    def settle_by_fold(self, *, net_pot_fn: Callable[[float], float] | None = None) -> Settlement:
        live = self.live_players
        if len(live) != 1:
            raise RuleError("fold settlement requires exactly one live player")
        winner = live[0]
        self.refund_uncalled()
        pots = self.pot_layers()
        gross = sum(x.amount_bb for x in pots)
        net = self._net_pot(gross, net_pot_fn)
        payouts = {p: 0.0 for p in self.seats}
        payouts[winner] = net
        return self._finalize("fold", gross, net, payouts, pots)

    def settle_showdown(
        self,
        ranks: Mapping[str, Any],
        *,
        net_pot_fn: Callable[[float], float] | None = None,
    ) -> Settlement:
        if not self.betting_complete:
            raise RuleError("cannot settle showdown while betting is pending")
        if self.street != "river":
            raise RuleError("showdown settlement requires the public runout through river")
        live = self.live_players
        if len(live) < 2:
            raise RuleError("showdown requires at least two live players")
        missing = [p for p in live if p not in ranks]
        if missing:
            raise ValueError(f"missing showdown rank(s): {missing}")
        self.refund_uncalled()
        pots = self.pot_layers()
        gross = sum(x.amount_bb for x in pots)
        net = self._net_pot(gross, net_pot_fn)
        scale = 0.0 if gross <= EPS else net / gross
        payouts = {p: 0.0 for p in self.seats}
        for pot in pots:
            best_rank = max(ranks[p] for p in pot.eligible)
            winners = [p for p in pot.eligible if ranks[p] == best_rank]
            share = pot.amount_bb * scale / len(winners)
            for p in winners:
                payouts[p] += share
        return self._finalize("showdown", gross, net, payouts, pots)

    def to_snapshot(self, *, include_log: bool = True) -> dict[str, Any]:
        data = {
            "schema": SNAPSHOT_SCHEMA,
            "seats": list(self.seats),
            "button": self.button,
            "small_blind_player": self.small_blind_player,
            "big_blind_player": self.big_blind_player,
            "small_blind_bb": _r(self.small_blind_bb),
            "big_blind_bb": _r(self.big_blind_bb),
            "starting_stacks_bb": {p: _r(v) for p, v in self.starting_stacks_bb.items()},
            "stacks_bb": {p: _r(v) for p, v in self.stacks_bb.items()},
            "total_committed_bb": {p: _r(v) for p, v in self.total_committed_bb.items()},
            "street_committed_bb": {p: _r(v) for p, v in self.street_committed_bb.items()},
            "folded": dict(self.folded),
            "all_in": dict(self.all_in),
            "street": self.street,
            "board": list(self.board),
            "current_bet_bb": _r(self.current_bet_bb),
            "last_full_raise_bb": _r(self.last_full_raise_bb),
            "full_bet_established": bool(self.full_bet_established),
            "acted_since_full_raise": [p for p in self.seats if p in self.acted_since_full_raise],
            "pending": list(self.pending),
            "refunds_bb": {p: _r(v) for p, v in self.refunds_bb.items()},
        }
        if include_log:
            data["action_log"] = list(self.action_log)
        return data

    @classmethod
    def from_snapshot(cls, snapshot: Mapping[str, Any]) -> "NoLimitHoldemState":
        if snapshot.get("schema") != SNAPSHOT_SCHEMA:
            raise ValueError("unsupported snapshot schema")
        self = cls.__new__(cls)
        self.seats = tuple(snapshot["seats"])
        self.button = str(snapshot["button"])
        self.small_blind_player = str(snapshot["small_blind_player"])
        self.big_blind_player = str(snapshot["big_blind_player"])
        self.small_blind_bb = float(snapshot["small_blind_bb"])
        self.big_blind_bb = float(snapshot["big_blind_bb"])
        self.starting_stacks_bb = {p: float(v) for p, v in snapshot["starting_stacks_bb"].items()}
        self.stacks_bb = {p: float(v) for p, v in snapshot["stacks_bb"].items()}
        self.total_committed_bb = {p: float(v) for p, v in snapshot["total_committed_bb"].items()}
        self.street_committed_bb = {p: float(v) for p, v in snapshot["street_committed_bb"].items()}
        self.folded = {p: bool(v) for p, v in snapshot["folded"].items()}
        self.all_in = {p: bool(v) for p, v in snapshot["all_in"].items()}
        self.street = str(snapshot["street"])
        self.board = list(snapshot.get("board") or [])
        self.current_bet_bb = float(snapshot["current_bet_bb"])
        self.last_full_raise_bb = float(snapshot["last_full_raise_bb"])
        self.full_bet_established = bool(snapshot["full_bet_established"])
        self.acted_since_full_raise = set(snapshot.get("acted_since_full_raise") or [])
        self.pending = list(snapshot.get("pending") or [])
        self.refunds_bb = {p: float(v) for p, v in snapshot["refunds_bb"].items()}
        self.action_log = list(snapshot.get("action_log") or [])
        self.settlement = None
        self._validate_public_state()
        return self

    def _next_seat(self, player: str) -> str:
        i = self.seats.index(player)
        return self.seats[(i + 1) % len(self.seats)]

    def _ordered_from(
        self,
        first: str,
        *,
        actionable_only: bool = False,
        exclude: set[str] | None = None,
    ) -> list[str]:
        exclude = exclude or set()
        i = self.seats.index(first)
        ordered = list(self.seats[i:]) + list(self.seats[:i])
        if actionable_only:
            ordered = [
                p for p in ordered
                if p not in exclude and not self.folded[p] and not self.all_in[p] and self.stacks_bb[p] > EPS
            ]
        return ordered

    def _post_forced(self, player: str, amount: float) -> None:
        self._commit(player, min(amount, self.stacks_bb[player]))

    def _commit(self, player: str, amount: float) -> None:
        amount = _nonnegative(amount, "commit amount")
        if amount > self.stacks_bb[player] + EPS:
            raise RuleError("cannot commit more than remaining stack")
        amount = min(amount, self.stacks_bb[player])
        self.stacks_bb[player] -= amount
        self.total_committed_bb[player] += amount
        self.street_committed_bb[player] += amount
        if self.stacks_bb[player] <= EPS:
            self.stacks_bb[player] = 0.0
            self.all_in[player] = True

    def _consume_pending(self, player: str) -> None:
        if not self.pending or self.pending[0] != player:
            raise RuleError("pending action order mismatch")
        self.pending.pop(0)

    def _auto_close_dry_action(self) -> None:
        self.pending = [p for p in self.pending if not self.folded[p] and not self.all_in[p]]
        live = self.live_players
        if len(live) <= 1:
            self.pending = []
            return
        actionable = [p for p in live if not self.all_in[p] and self.stacks_bb[p] > EPS]
        if len(actionable) == 1:
            p = actionable[0]
            if max(0.0, self.current_bet_bb - self.street_committed_bb[p]) <= EPS:
                self.pending = []
            elif p not in self.pending:
                self.pending = [p]
        elif not actionable:
            self.pending = []

    def _net_pot(self, gross: float, net_pot_fn: Callable[[float], float] | None) -> float:
        if net_pot_fn is None:
            return gross
        net = float(net_pot_fn(gross))
        if net < -EPS or net > gross + EPS:
            raise ValueError("net_pot_fn must return a value between zero and gross pot")
        return max(0.0, min(gross, net))

    def _finalize(
        self,
        terminal: str,
        gross: float,
        net: float,
        payouts: dict[str, float],
        pots: tuple[PotLayer, ...],
    ) -> Settlement:
        if self.settlement is not None:
            raise RuleError("hand is already settled")
        for p, amount in payouts.items():
            self.stacks_bb[p] += amount
        rake = gross - net
        net_results = {p: self.stacks_bb[p] - self.starting_stacks_bb[p] for p in self.seats}
        conserved = sum(self.stacks_bb.values()) + rake
        initial = sum(self.starting_stacks_bb.values())
        if abs(conserved - initial) > 1e-6:
            raise AssertionError(f"chip conservation failed: {conserved} != {initial}")
        settlement = Settlement(
            terminal=terminal,
            gross_pot_bb=_r(gross),
            net_pot_bb=_r(net),
            rake_bb=_r(rake),
            refunds_bb={p: _r(v) for p, v in self.refunds_bb.items()},
            payouts_bb={p: _r(v) for p, v in payouts.items()},
            net_results_bb={p: _r(v) for p, v in net_results.items()},
            pots=pots,
        )
        self.settlement = settlement
        return settlement

    @staticmethod
    def _decision_digest(snapshot: Mapping[str, Any], actor: str | None) -> dict[str, Any]:
        return {
            "street": snapshot["street"],
            "actor": actor,
            "pot_bb": _r(sum(snapshot["total_committed_bb"].values())),
            "board": list(snapshot["board"]),
            "current_bet_bb": snapshot["current_bet_bb"],
            "pending": list(snapshot["pending"]),
        }

    def _validate_public_state(self) -> None:
        if set(self.seats) != set(self.stacks_bb):
            raise ValueError("snapshot player maps do not match seats")
        if self.street not in STREETS:
            raise ValueError("invalid street")
        expected_board = {"preflop": 0, "flop": 3, "turn": 4, "river": 5}[self.street]
        if len(self.board) != expected_board:
            raise ValueError(f"invalid public board length for {self.street}")
        if len(set(self.board)) != len(self.board):
            raise ValueError("duplicate public board card in snapshot")
        if any(p not in self.seats for p in self.pending):
            raise ValueError("pending contains unknown player")
        for p in self.seats:
            if self.stacks_bb[p] < -EPS or self.total_committed_bb[p] < -EPS:
                raise ValueError("negative stack/contribution in snapshot")
            if abs(self.starting_stacks_bb[p] - (self.stacks_bb[p] + self.total_committed_bb[p])) > 1e-6:
                raise ValueError(f"snapshot chip balance mismatch for {p}")

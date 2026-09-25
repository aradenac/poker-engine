#!/usr/bin/env python3
"""Deterministic builder for the #395 T7 Review-inbox large-list fixture.

The fixture is a *PokerStars hand-history export* of 32 hands, i.e. the real
input format the application imports through `#hhFileInput`. It is generated
instead of hand-written so that the expected values the browser smoke asserts
(timestamp, Hero position, real result, net in BB, EV loss, deep-link step
index) stay a pure function of one readable table.

Construction rules — every hand is a 6-max hand whose Hero owns **exactly one**
analyzable decision, or none at all:

* ``WIN`` / ``LOSS`` / ``SPLIT`` — Hero (big blind) shoves all-in preflop and is
  called, the board runs out to the river and the showdown settles the pot. The
  only analyzable Hero step is the shove, at step index 6 (step 0 is the deal,
  steps 1-5 are the preflop folds/posts of the other seats).
* ``FOLD`` — Hero (cutoff) folds preflop without ever posting a blind. The hand
  carries no analyzable Hero step, settles at exactly 0 BB (``EVEN``) and has no
  deep link.
* ``UNKNOWN`` — same body as a ``WIN``, but the header carries **no stake pair**
  (`(50/100)`), so the real settlement is genuinely unavailable: the inbox must
  keep the hand out of ``WIN``/``LOSS`` and carry it after the settled hands in
  both real-result sorts.

Stacks are a function of the hand index, so the net of each settled hand is a
distinct, authored number, and the EV loss of each hand owning a decision is a
distinct permutation value. The four requested orders (temporal, gain, loss, EV
loss) are therefore pairwise different: a sort that stopped sorting fails the
smoke instead of passing by accident.

Run it to (re)generate the committed fixture::

    python3 tests/trainer/fixtures/review_inbox_large_list_builder.py

`tests/trainer/test_review_inbox_large_list_smoke_contract.py` re-runs this
builder in memory and fails if the committed bytes drift from it.

The fixture lives under `tests/trainer/` on purpose: the frozen
`.github/workflows/trainer-smoke.yml` triggers on `tests/trainer/**` (it does not
watch `tests/fixtures/**`), so editing this builder, the fixture or its probe
re-runs the trainer-smoke CI — including the browser smoke that consumes them.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "tests/trainer/fixtures/review_inbox_large_list.hand.txt"

HAND_TOTAL = 32
BLIND_SB = 50
BLIND_BB = 100
DATE = "2026/09/01"
TABLE = "Review Inbox Large List"
BOARD = "2c 7d Qh 9s 3d"
BOARD_REVEALS = (("*** FLOP *** [2c 7d Qh]", "2c 7d Qh"),
                 ("*** TURN *** [2c 7d Qh] [9s]", "9s"),
                 ("*** RIVER *** [2c 7d Qh 9s] [3d]", "3d"))
# Hands whose header carries no stake pair: their real settlement is UNKNOWN.
UNKNOWN_HANDS = (11, 27)
# Step index of the single analyzable Hero decision (the shove), identical in
# the served replay (`makeReplaySteps`) and in the review adapter
# (`parseStoredHand`): 0 = deal, 1 = SB post, 2 = Hero posts the big blind,
# 3 = LJ folds, 4 = HJ raises, 5 = CO folds, 6 = BTN folds, 7 = SB folds,
# 8 = Hero shoves. The smoke asserts that identity per hand.
DECISION_STEP_INDEX = 8


def variant(index: int) -> str:
    """Authored variant of hand ``index`` (1..32)."""
    if index in UNKNOWN_HANDS:
        return "UNKNOWN"
    if index % 4 == 0:
        return "FOLD"
    return {1: "WIN", 2: "LOSS", 3: "SPLIT"}[index % 4]


def hand_id(index: int) -> str:
    return str(3950000 + index)


def clock(index: int) -> tuple[str, str]:
    """Wall clock of hand ``index``: one minute apart, from 10:00:00 CET."""
    total = index - 1
    return f"{10 + total // 60:02d}", f"{total % 60:02d}"


def timestamp(index: int) -> str:
    hour, minute = clock(index)
    return f"2026-09-01T{hour}:{minute}:00Z"


def effective_stack(index: int, kind: str) -> int:
    return (4000 if kind == "WIN" else 2000) + 100 * index


def net_bb(index: int, kind: str) -> float | None:
    """Real Hero settlement in BB, as the served parser computes it."""
    if kind == "WIN":
        return (2 * effective_stack(index, kind) + BLIND_SB - effective_stack(index, kind)) / BLIND_BB
    if kind == "LOSS":
        return -effective_stack(index, kind) / BLIND_BB
    if kind in ("SPLIT", "FOLD"):
        return 0.0
    return None


def result_state(index: int, kind: str) -> str:
    if kind == "UNKNOWN":
        return "UNKNOWN"
    if kind == "WIN":
        return "WIN"
    if kind == "LOSS":
        return "LOSS"
    return "EVEN"


def ev_loss_bb(index: int, kind: str) -> float:
    """Authored EV loss (BB) of the hand's single review decision.

    `index * 7 % 32` is a permutation of 0..31 over the 32 hand indices (7 and
    32 are coprime), so every hand owning a decision carries a distinct EV loss
    and the descending order is uncorrelated with the temporal, gain and loss
    orders.
    """
    if kind == "FOLD":
        return 0.0
    return round(((index * 7) % HAND_TOTAL + 1) * 2.5, 2)


def position(index: int, kind: str) -> str:
    return "CO" if kind == "FOLD" else "BB"


def _header(index: int, kind: str) -> str:
    hour, minute = clock(index)
    stakes = "" if kind == "UNKNOWN" else f" ({BLIND_SB}/{BLIND_BB})"
    return (
        f"PokerStars Hand #{hand_id(index)}: Hold'em No Limit{stakes} - "
        f"{DATE} {hour}:{minute}:00 CET"
    )


def _table(stacks: int, hero_seat: int = 3) -> list[str]:
    """Seat block: position labels of a 6-max table buttoned on seat 1.

    `hero_seat` carries the Hero name instead of its position label, so the
    played hands (Hero on seat 3, big blind) and the folded hands (Hero on seat
    6, cutoff) share the same seat/position mapping — the one the served
    `assignPokerPositions` computes.
    """
    labels = {1: "BTN", 2: "SB", 3: "BB", 4: "LJ", 5: "HJ", 6: "CO"}
    return [
        f"Table '{TABLE}' 6-max Seat #1 is the button",
        *[
            f"Seat {seat}: {'Hero' if seat == hero_seat else labels[seat]} ({stacks} in chips)"
            for seat in range(1, 7)
        ],
    ]


def _played_block(index: int, kind: str) -> list[str]:
    stacks = effective_stack(index, kind)
    pot = 2 * stacks + BLIND_SB
    lines = [
        _header(index, kind),
        *_table(stacks),
        f"SB: posts small blind {BLIND_SB}",
        f"Hero: posts big blind {BLIND_BB}",
        "*** HOLE CARDS ***",
        "Dealt to Hero [As Kd]",
        "LJ: folds",
        "HJ: raises 200 to 300",
        "CO: folds",
        "BTN: folds",
        "SB: folds",
        f"Hero: raises {stacks - BLIND_BB} to {stacks} and is all-in",
        f"HJ: calls {stacks - 300} and is all-in",
    ]
    for reveal, cards in BOARD_REVEALS:
        lines.append(reveal)
    lines.extend([
        "*** SHOW DOWN ***",
        "Hero: shows [As Kd] (high card Ace)",
        "HJ: shows [8h 8c] (a pair of Eights)",
    ])
    if kind in ("WIN", "UNKNOWN"):
        lines.append(f"Hero collected {pot} from pot")
        hero_seat = f"Seat 3: Hero (big blind) showed [As Kd] and won ({pot}) with high card Ace"
        rival_seat = "Seat 5: HJ showed [8h 8c] and lost with a pair of Eights"
    elif kind == "LOSS":
        lines.append(f"HJ collected {pot} from pot")
        hero_seat = "Seat 3: Hero (big blind) showed [As Kd] and lost with high card Ace"
        rival_seat = f"Seat 5: HJ showed [8h 8c] and won ({pot}) with a pair of Eights"
    else:
        lines.append(f"Hero collected {stacks} from pot")
        lines.append(f"HJ collected {stacks + BLIND_SB} from pot")
        hero_seat = f"Seat 3: Hero (big blind) showed [As Kd] and won ({stacks}) with high card Ace"
        rival_seat = (
            f"Seat 5: HJ showed [8h 8c] and won ({stacks + BLIND_SB}) with a pair of Eights"
        )
    lines.extend([
        "*** SUMMARY ***",
        f"Total pot {pot} | Rake 0",
        f"Board [{BOARD}]",
        "Seat 1: BTN (button) folded before Flop (didn't bet)",
        "Seat 2: SB (small blind) folded before Flop",
        hero_seat,
        "Seat 4: LJ folded before Flop (didn't bet)",
        rival_seat,
        "Seat 6: CO folded before Flop (didn't bet)",
    ])
    return lines


def _folded_block(index: int) -> list[str]:
    stacks = effective_stack(index, "FOLD")
    return [
        _header(index, "FOLD"),
        *_table(stacks, hero_seat=6),
        f"SB: posts small blind {BLIND_SB}",
        f"BB: posts big blind {BLIND_BB}",
        "*** HOLE CARDS ***",
        "Dealt to Hero [7h 2c]",
        "LJ: folds",
        "HJ: folds",
        "Hero: folds",
        "BTN: folds",
        "SB: folds",
        "*** SUMMARY ***",
        f"Total pot {BLIND_BB + BLIND_SB} | Rake 0",
        "Seat 1: BTN (button) folded before Flop (didn't bet)",
        "Seat 2: SB (small blind) folded before Flop",
        f"Seat 3: BB (big blind) collected ({BLIND_BB + BLIND_SB})",
        "Seat 4: LJ folded before Flop (didn't bet)",
        "Seat 5: HJ folded before Flop (didn't bet)",
        "Seat 6: Hero (cutoff) folded before Flop (didn't bet)",
    ]


def hand_specs() -> list[dict]:
    """The authored table: one row per hand, in import order."""
    specs = []
    for index in range(1, HAND_TOTAL + 1):
        kind = variant(index)
        specs.append({
            "hand_id": hand_id(index),
            "index": index,
            "variant": kind,
            "timestamp": timestamp(index),
            "position": position(index, kind),
            "result": result_state(index, kind),
            "net_bb": net_bb(index, kind),
            "ev_loss_bb": ev_loss_bb(index, kind),
            "decision_step_index": None if kind == "FOLD" else DECISION_STEP_INDEX,
        })
    return specs


def build_fixture() -> str:
    """The exact bytes of the committed PokerStars export."""
    blocks = []
    for index in range(1, HAND_TOTAL + 1):
        kind = variant(index)
        blocks.append(_folded_block(index) if kind == "FOLD" else _played_block(index, kind))
    return "\n\n".join("\n".join(block) for block in blocks) + "\n"


def main() -> None:
    text = build_fixture()
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(text, encoding="utf-8")
    print(f"{FIXTURE.relative_to(ROOT)}: {HAND_TOTAL} hands, "
          f"{len(text.encode('utf-8'))} bytes, sha256 {hashlib.sha256(text.encode('utf-8')).hexdigest()}")


if __name__ == "__main__":
    main()

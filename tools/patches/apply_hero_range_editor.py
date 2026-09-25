#!/usr/bin/env python3
"""Expose the standalone Hero range editor from the main static application.

The Strategy view is an in-app surface: its ``#quickNav`` entry carries the
``#strategyPage`` anchor (see the ``backlog-0q6`` work), so this patch must never
reintroduce a standalone ``./hero-ranges.html`` navigation link. The editor
keeps its real links outside the navigation — the Accueil mode card
(``[data-hero-ranges-entry]``), ``#heroRangesOpenBtn`` and
``#strategyPageEditorLink``. Only the guarded ``#heroRangesOpenBtn`` insertion
remains, and it is strictly idempotent: a second run over an already patched
file performs no write.
"""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INDEX = ROOT / "site/index.html"

TRAINER_OPEN_BUTTON = (
    '    <button id="trainerOpenBtn" type="button" class="primary">Training</button>\n'
)
HERO_RANGES_OPEN_BUTTON = (
    '    <a id="heroRangesOpenBtn" href="./hero-ranges.html" class="filelabel" '
    'style="width:auto;text-decoration:none">Strategy</a>\n'
)
HERO_RANGES_OPEN_BUTTON_MARKER = 'id="heroRangesOpenBtn"'


def patch_text(text: str) -> str:
    """Return ``text`` with the Accueil Strategy button present exactly once."""
    if HERO_RANGES_OPEN_BUTTON_MARKER in text:
        return text
    count = text.count(TRAINER_OPEN_BUTTON)
    if count != 1:
        raise SystemExit(
            "main Strategy link: expected one trainerOpenBtn marker, "
            f"found {count}"
        )
    return text.replace(
        TRAINER_OPEN_BUTTON,
        TRAINER_OPEN_BUTTON + HERO_RANGES_OPEN_BUTTON,
        1,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    before = args.index.read_text(encoding="utf-8")
    after = patch_text(before)
    if args.check:
        if before != after:
            raise SystemExit("hero range editor patch is not applied")
    elif after != before:
        args.index.write_text(after, encoding="utf-8")
    print(args.index)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

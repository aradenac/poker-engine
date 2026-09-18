#!/usr/bin/env python3
"""Add the population-pack manager link to the static analyser navigation."""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INDEX = ROOT / "site/index.html"
SOURCE = '<a href="./hero-ranges.html">Stratégie Hero</a>'
LEGACY_SOURCE = '<a href="./hero-ranges.html">Ranges Hero</a>'


def patch_text(text: str) -> str:
    if '<a href="./packs.html">Packs de population</a>' in text:
        return text
    for source in (SOURCE, LEGACY_SOURCE):
        if source in text:
            target = source + '\n      <a href="./packs.html">Packs de population</a>'
            return text.replace(source, target, 1)
    raise ValueError("hero-ranges navigation anchor not found")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    before = args.index.read_text(encoding="utf-8")
    after = patch_text(before)
    if args.check:
        if before != after:
            raise SystemExit("pack manager navigation patch is not applied")
    else:
        args.index.write_text(after, encoding="utf-8")
    print(args.index)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

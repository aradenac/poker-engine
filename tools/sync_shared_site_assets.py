#!/usr/bin/env python3
"""Keep static browser artifacts byte-identical to canonical shared sources."""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ((ROOT / "src/preflop/contract.js", ROOT / "site/preflop-contract.js"),)


def sync(*, check: bool) -> int:
    drift = []
    for source, target in ASSETS:
        expected = source.read_bytes()
        actual = target.read_bytes() if target.exists() else None
        if actual == expected:
            continue
        if check:
            drift.append(f"{target.relative_to(ROOT)} != {source.relative_to(ROOT)}")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(expected)
    if drift:
        for item in drift:
            print(item)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail instead of writing when a generated asset drifted")
    args = parser.parse_args()
    return sync(check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())

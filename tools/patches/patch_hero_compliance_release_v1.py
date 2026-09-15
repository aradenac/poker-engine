#!/usr/bin/env python3
"""Keep Hero compliance assets inside the assembled-site release identity."""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "tools" / "write_site_release.py"
ANCHOR = '    ROOT / "site" / "hero-ranges.css",\n'
INSERT = (
    '    ROOT / "site" / "hero-compliance.js",\n'
    '    ROOT / "site" / "hero-compliance-replayer.js",\n'
)
MARKER = 'ROOT / "site" / "hero-compliance.js"'


def apply(*, check: bool = False) -> bool:
    text = TARGET.read_text(encoding="utf-8")
    present = MARKER in text
    if check:
        if not present:
            raise SystemExit("Hero compliance assets are missing from FUNCTIONAL_FILES")
        return False
    if present:
        return False
    if ANCHOR not in text:
        raise SystemExit("Hero range release anchor not found")
    text = text.replace(ANCHOR, ANCHOR + INSERT, 1)
    TARGET.write_text(text, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    changed = apply(check=args.check)
    print("Hero compliance release coverage:", "updated" if changed else "current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

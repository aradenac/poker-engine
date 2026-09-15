#!/usr/bin/env python3
"""Synchronize source-owned shared modules into runnable static artifacts.

The historical application is still served directly from ``site/``.  Shared
modules extracted under ``src/`` remain the edit source; this tool makes the
copy into ``site/`` explicit and checkable without introducing a bundler.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULES = (
    (Path("src/preflop/contract.js"), Path("site/preflop-contract.js")),
    (Path("src/preflop/decision.js"), Path("site/preflop-decision.js")),
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sync(*, check: bool) -> int:
    failures = 0
    for source_rel, target_rel in MODULES:
        source = ROOT / source_rel
        target = ROOT / target_rel
        source_bytes = source.read_bytes()
        target_bytes = target.read_bytes() if target.exists() else None

        if target_bytes == source_bytes:
            print(f"OK {target_rel} == {source_rel} sha256={digest(source_bytes)}")
            continue

        if check:
            actual = "missing" if target_bytes is None else digest(target_bytes)
            print(
                f"DRIFT {target_rel}: expected sha256={digest(source_bytes)} "
                f"from {source_rel}, actual={actual}"
            )
            failures += 1
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source_bytes)
        print(f"SYNC {source_rel} -> {target_rel} sha256={digest(source_bytes)}")

    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="fail if a generated copy differs")
    mode.add_argument("--write", action="store_true", help="refresh generated copies from src/")
    args = parser.parse_args()
    return sync(check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())

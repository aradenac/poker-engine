#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest.get("schema") != "poker-hand-history-increment/v3":
        raise SystemExit("unexpected increment manifest schema")
    n = int(manifest.get("selected_unique_hands") or 0)
    result = {
        "schema": "poker-continuous-increment-status/v1",
        "selected_unique_hands": n,
        "has_new_hands": n > 0,
        "outcome": "CANDIDATE_BUILD_REQUIRED" if n > 0 else "NO_OP_NO_NEW_HANDS",
        "split_counts": manifest.get("split_counts") or {},
        "selected_hand_ids_fingerprint_sha256": manifest.get("selected_hand_ids_fingerprint_sha256"),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

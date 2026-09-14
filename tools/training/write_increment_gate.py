#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description="Write the first machine gate for a newly planned continuous cycle.")
    ap.add_argument("--cycle", required=True)
    ap.add_argument("--increment-status", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    status = json.loads(args.increment_status.read_text(encoding="utf-8"))
    if status.get("schema") != "poker-continuous-increment-status/v1":
        raise SystemExit("unexpected increment status schema")
    has_new = status.get("has_new_hands") is True
    report = {
        "schema": "poker-promotion-gate-report/v1",
        "cycle": args.cycle,
        "status": "BLOCKED" if has_new else "PASS",
        "promotion_ready": False if has_new else True,
        "phase": "increment_planning",
        "outcome": "CANDIDATE_PIPELINE_REQUIRED" if has_new else "NO_OP_NO_NEW_HANDS",
        "selected_unique_hands": int(status.get("selected_unique_hands") or 0),
        "selected_hand_ids_fingerprint_sha256": status.get("selected_hand_ids_fingerprint_sha256"),
        "reason": (
            "new unseen hands are materialized; model/strategy evaluation gates must run before any promotion"
            if has_new else
            "snapshot contains no unseen hands in scope; no model or production transition is required"
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

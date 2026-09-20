#!/usr/bin/env python3

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    subprocess.run(
        [sys.executable, "tools/write_site_release.py", "--check"],
        cwd=ROOT,
        check=True,
    )

    release = json.loads((ROOT / "site" / "RELEASE.json").read_text(encoding="utf-8"))
    assert release["schema"] == "poker-site-release/v3"
    assert release["identity"]["engine_release"]["artifact"].startswith("user/releases/")

    assembled = release["identity"]["assembled_site"]
    assert set(assembled["functional_files"]) == {
        "site/index.html",
        "site/compute-scheduler.js",
        "site/analytics/leak-analyzer.js",
        "site/analytics/review-score-adapter.js",
        "site/analytics/review-inbox.js",
        "site/analytics/leak-training-target.js",
        "site/analytics/review-dashboard.js",
        "site/analytics/model-b-robustness.js",
        "site/training/leak-scenario-selector.js",
        "site/preflop-contract.js",
        "site/preflop-decision.js",
        "site/preflop-guidance.js",
        "site/training/preflop-decision-adapter.js",
        "site/training/nlhe-game-state.js",
        "site/training/preflop-runtime.js",
        "site/hero-ranges.html",
        "site/hero-ranges.js",
        "site/hero-ranges-app.js",
        "site/hero-ranges.css",
        "site/hero-compliance.js",
        "site/hero-compliance-replayer.js",
        "site/trainer.css",
        "site/trainer.js",
        "site/action-sizing-ev.js",
        "site/packs.html",
        "site/packs.css",
        "site/packs-app.js",
        "site/pack-identity.js",
        "site/population-packs.js",
        "site/population-pack-sw.js",
        "site/packs/catalog.json",
    }
    assert assembled["assets_tree_git_sha"]
    assert release["publication_verification"]["status"] == "UNVERIFIED_LIVE"
    assert release["publication_verification"]["tracked_by_issue"] == 45
    assert "assembled_from_commit" not in assembled

    print("site release identity contract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

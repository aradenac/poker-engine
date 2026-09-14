from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_site_release_identity_matches_functional_bytes() -> None:
    subprocess.run(
        [sys.executable, "tools/write_site_release.py", "--check"],
        cwd=ROOT,
        check=True,
    )


def test_release_identity_separates_engine_app_and_live_publication() -> None:
    release = json.loads((ROOT / "site" / "RELEASE.json").read_text(encoding="utf-8"))

    assert release["schema"] == "poker-site-release/v3"
    assert release["identity"]["engine_release"]["artifact"].startswith("user/releases/")

    assembled = release["identity"]["assembled_site"]
    assert set(assembled["functional_files"]) == {
        "site/index.html",
        "site/trainer.css",
        "site/trainer.js",
    }
    assert assembled["assets_tree_git_sha"]
    assert release["publication_verification"]["status"] == "UNVERIFIED_LIVE"
    assert release["publication_verification"]["tracked_by_issue"] == 45
    assert "assembled_from_commit" not in assembled

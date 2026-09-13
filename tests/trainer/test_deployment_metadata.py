#!/usr/bin/env python3

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "write_deployment_metadata.py"


def main() -> int:
    commit = "0123456789abcdef0123456789abcdef01234567"
    env = os.environ.copy()
    env.update(
        {
            "WORKERS_CI_COMMIT_SHA": commit,
            "WORKERS_CI_BRANCH": "main",
            "WORKERS_CI_BUILD_UUID": "build-123",
            "DEPLOYMENT_BUILD_TIME": "2026-09-13T10:25:30Z",
        }
    )
    with tempfile.TemporaryDirectory() as td:
        output = Path(td) / "deployment-meta.css"
        subprocess.run(
            ["python3", str(SCRIPT), "--output", str(output)],
            cwd=ROOT,
            env=env,
            check=True,
        )
        text = output.read_text(encoding="utf-8")

    assert "poker-deployment-meta/v1" in text
    assert f"commit: {commit}" in text
    assert "branch: main" in text
    assert "build_id: build-123" in text
    assert "generated_at: 2026-09-13T10:25:30Z" in text
    assert "déploiement 2026-09-13 10:25 UTC · main · commit 0123456789ab" in text
    print("deployment metadata contract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

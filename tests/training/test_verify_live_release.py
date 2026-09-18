#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.training.verify_live_release import (  # noqa: E402
    functional_assets,
    git_blob_sha_bytes,
    join_url,
    parse_deployment_metadata,
)


def test_git_blob_identity_matches_git_object_contract() -> None:
    payload = b"abc\n"
    expected = hashlib.sha1(f"blob {len(payload)}\0".encode("ascii") + payload).hexdigest()
    assert git_blob_sha_bytes(payload) == expected


def test_deployment_metadata_requires_commit_and_build() -> None:
    css = """/* poker-deployment-meta/v1
commit: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
branch: main
build_id: build-123
generated_at: 2026-09-18T20:00:00Z
*/
"""
    fields = parse_deployment_metadata(css)
    assert fields["commit"] == "a" * 40
    assert fields["build_id"] == "build-123"

    try:
        parse_deployment_metadata("commit: short\nbuild_id: x\n")
    except ValueError as exc:
        assert "commit" in str(exc)
    else:
        raise AssertionError("invalid deployment commit must fail")


def test_functional_assets_strip_site_prefix_and_require_blob_ids() -> None:
    release = {
        "identity": {
            "assembled_site": {
                "functional_files": {
                    "site/index.html": {"git_blob_sha": "1" * 40},
                    "site/trainer.js": {"git_blob_sha": "2" * 40},
                }
            }
        }
    }
    assert functional_assets(release) == {
        "index.html": "1" * 40,
        "trainer.js": "2" * 40,
    }

    broken = {
        "identity": {
            "assembled_site": {
                "functional_files": {
                    "site/index.html": {"git_blob_sha": "bad"},
                }
            }
        }
    }
    try:
        functional_assets(broken)
    except ValueError as exc:
        assert "invalid git blob" in str(exc)
    else:
        raise AssertionError("invalid release asset identity must fail")


def test_join_url_keeps_canonical_origin() -> None:
    assert join_url("https://poker-engine.example.test", "RELEASE.json") == (
        "https://poker-engine.example.test/RELEASE.json"
    )
    assert join_url("https://poker-engine.example.test/", "site/trainer.js") == (
        "https://poker-engine.example.test/site/trainer.js"
    )


def main() -> None:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
    print(f"live release verifier tests: {len(tests)} passed")


if __name__ == "__main__":
    main()

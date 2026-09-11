#!/usr/bin/env python3
"""Download one staged artifact into the repository after strict verification.

The staging service is transport only. GitHub remains the durable source of truth.
A manifest provides the expected URL, repository target path, byte size and SHA-256.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tempfile
import urllib.parse
import urllib.request

SCHEMA = "poker-engine-artifact-ingest/v1"
ALLOWED_HOSTS = {
    "dropbox.com",
    "www.dropbox.com",
    "dl.dropboxusercontent.com",
}
FORBIDDEN_PREFIXES = (
    ".git/",
    ".github/workflows/",
    "artifacts/inbox/",
)


def fail(message: str) -> None:
    raise SystemExit(f"artifact ingest: {message}")


def validate_target(raw: str) -> Path:
    if not raw or raw.startswith("/") or "\\" in raw:
        fail("target_path must be a relative POSIX repository path")
    posix = PurePosixPath(raw)
    if any(part in ("", ".", "..") for part in posix.parts):
        fail("target_path contains an unsafe path component")
    normalized = posix.as_posix()
    if normalized.startswith(FORBIDDEN_PREFIXES):
        fail(f"target_path is forbidden: {normalized}")
    return Path(*posix.parts)


def validate_url(raw: str) -> str:
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme != "https":
        fail("source_url must use HTTPS")
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        fail(f"source host is not allow-listed: {host}")
    return raw


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, output: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "poker-engine-artifact-ingest/1"})
    with urllib.request.urlopen(req, timeout=120) as response, output.open("wb") as dst:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            dst.write(chunk)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest", type=Path)
    args = ap.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest.get("schema") != SCHEMA:
        fail(f"unsupported schema: {manifest.get('schema')!r}")

    url = validate_url(str(manifest.get("source_url", "")))
    target = validate_target(str(manifest.get("target_path", "")))
    expected_sha = str(manifest.get("sha256", "")).lower()
    expected_size = manifest.get("size_bytes")
    if len(expected_sha) != 64 or any(c not in "0123456789abcdef" for c in expected_sha):
        fail("sha256 must contain exactly 64 lowercase hexadecimal characters")
    if not isinstance(expected_size, int) or expected_size < 0:
        fail("size_bytes must be a non-negative integer")

    target.parent.mkdir(parents=True, exist_ok=True)

    # Idempotence: a previously imported exact file is already complete.
    if target.exists():
        size = target.stat().st_size
        digest = sha256_file(target)
        if size == expected_size and digest == expected_sha:
            print(f"already verified: {target}")
            return
        fail(f"target already exists with different content: {target}")

    fd, temp_name = tempfile.mkstemp(prefix="artifact-ingest-", dir=str(target.parent))
    os.close(fd)
    temp = Path(temp_name)
    try:
        download(url, temp)
        actual_size = temp.stat().st_size
        actual_sha = sha256_file(temp)
        if actual_size != expected_size:
            fail(f"size mismatch: expected {expected_size}, got {actual_size}")
        if actual_sha != expected_sha:
            fail(f"SHA-256 mismatch: expected {expected_sha}, got {actual_sha}")
        os.replace(temp, target)
        print(f"verified import: {target} ({actual_size} bytes, sha256={actual_sha})")
    finally:
        if temp.exists():
            temp.unlink()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Import one staged artifact into the repository after strict verification.

Supported transports:
- v1: HTTPS download from an allow-listed transient host.
- v2: repository chunks stored under artifacts/staging/, optionally base64+gzip.

GitHub remains the durable source of truth. Every artifact is verified against
its expected byte size and SHA-256 before it is moved to its canonical path.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import tempfile
import urllib.parse
import urllib.request

SCHEMA_V1 = "poker-engine-artifact-ingest/v1"
SCHEMA_V2 = "poker-engine-artifact-ingest/v2"
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
STAGING_PREFIX = "artifacts/staging/"
RECEIPTS_DIR = Path("artifacts/receipts")


def fail(message: str) -> None:
    raise SystemExit(f"artifact ingest: {message}")


def safe_repo_path(raw: str, *, allow_inbox: bool = False) -> Path:
    if not raw or raw.startswith("/") or "\\" in raw:
        fail("repository path must be a relative POSIX path")
    posix = PurePosixPath(raw)
    if any(part in ("", ".", "..") for part in posix.parts):
        fail("repository path contains an unsafe path component")
    normalized = posix.as_posix()
    forbidden = FORBIDDEN_PREFIXES if not allow_inbox else (".git/", ".github/workflows/")
    if normalized.startswith(forbidden):
        fail(f"repository path is forbidden: {normalized}")
    return Path(*posix.parts)


def validate_target(raw: str) -> Path:
    return safe_repo_path(raw)


def validate_part(raw: str) -> Path:
    p = safe_repo_path(raw)
    normalized = PurePosixPath(raw).as_posix()
    if not normalized.startswith(STAGING_PREFIX):
        fail(f"chunk must live under {STAGING_PREFIX}: {normalized}")
    return p


def validate_url(raw: str) -> str:
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme != "https":
        fail("source_url must use HTTPS")
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        fail(f"source host is not allow-listed: {host}")
    return raw


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, output: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "poker-engine-artifact-ingest/2"})
    with urllib.request.urlopen(req, timeout=120) as response, output.open("wb") as dst:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            dst.write(chunk)


def materialize_from_chunks(transport: dict, output: Path) -> list[Path]:
    parts_raw = transport.get("parts")
    if not isinstance(parts_raw, list) or not parts_raw:
        fail("repo_chunks transport requires a non-empty parts list")
    parts = [validate_part(str(x)) for x in parts_raw]
    for p in parts:
        if not p.is_file():
            fail(f"missing chunk: {p}")

    encoding = str(transport.get("encoding", "base64"))
    encoded = "".join(p.read_text(encoding="ascii") for p in parts)
    try:
        payload = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        fail(f"invalid base64 chunk stream: {exc}")

    if encoding == "base64":
        data = payload
    elif encoding == "base64+gzip":
        try:
            data = gzip.decompress(payload)
        except Exception as exc:
            fail(f"gzip decompression failed: {exc}")
    else:
        fail(f"unsupported repo_chunks encoding: {encoding!r}")

    output.write_bytes(data)
    return parts


def write_receipt(manifest_path: Path, manifest: dict, *, target: Path, digest: str, size: int, transport_type: str) -> None:
    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
    receipt = {
        "schema": "poker-engine-artifact-receipt/v1",
        "manifest": manifest_path.name,
        "target_path": target.as_posix(),
        "sha256": digest,
        "size_bytes": size,
        "transport": transport_type,
        "imported_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    out = RECEIPTS_DIR / manifest_path.name
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest", type=Path)
    args = ap.parse_args()

    manifest_path = args.manifest
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema = manifest.get("schema")
    if schema not in {SCHEMA_V1, SCHEMA_V2}:
        fail(f"unsupported schema: {schema!r}")

    target = validate_target(str(manifest.get("target_path", "")))
    expected_sha = str(manifest.get("sha256", "")).lower()
    expected_size = manifest.get("size_bytes")
    if len(expected_sha) != 64 or any(c not in "0123456789abcdef" for c in expected_sha):
        fail("sha256 must contain exactly 64 lowercase hexadecimal characters")
    if not isinstance(expected_size, int) or expected_size < 0:
        fail("size_bytes must be a non-negative integer")

    transport_type = "url"
    chunk_parts: list[Path] = []
    target.parent.mkdir(parents=True, exist_ok=True)

    # Idempotence: a previously imported exact file is already complete. We still
    # clean staging and create a receipt so retried manifests converge cleanly.
    if target.exists():
        size = target.stat().st_size
        digest = sha256_file(target)
        if size != expected_size or digest != expected_sha:
            fail(f"target already exists with different content: {target}")
        if schema == SCHEMA_V2:
            transport = manifest.get("transport") or {}
            if transport.get("type") != "repo_chunks":
                fail("v2 manifest transport.type must be repo_chunks")
            chunk_parts = [validate_part(str(x)) for x in transport.get("parts", [])]
            transport_type = "repo_chunks"
        for p in chunk_parts:
            if p.exists():
                p.unlink()
        write_receipt(manifest_path, manifest, target=target, digest=digest, size=size, transport_type=transport_type)
        manifest_path.unlink()
        print(f"already verified: {target}")
        return

    fd, temp_name = tempfile.mkstemp(prefix="artifact-ingest-", dir=str(target.parent))
    os.close(fd)
    temp = Path(temp_name)
    try:
        if schema == SCHEMA_V1:
            url = validate_url(str(manifest.get("source_url", "")))
            download(url, temp)
        else:
            transport = manifest.get("transport") or {}
            if transport.get("type") != "repo_chunks":
                fail("v2 manifest transport.type must be repo_chunks")
            transport_type = "repo_chunks"
            chunk_parts = materialize_from_chunks(transport, temp)

        actual_size = temp.stat().st_size
        actual_sha = sha256_file(temp)
        if actual_size != expected_size:
            fail(f"size mismatch: expected {expected_size}, got {actual_size}")
        if actual_sha != expected_sha:
            fail(f"SHA-256 mismatch: expected {expected_sha}, got {actual_sha}")

        os.replace(temp, target)
        for p in chunk_parts:
            p.unlink()
        write_receipt(manifest_path, manifest, target=target, digest=actual_sha, size=actual_size, transport_type=transport_type)
        manifest_path.unlink()
        print(f"verified import: {target} ({actual_size} bytes, sha256={actual_sha})")
    finally:
        if temp.exists():
            temp.unlink()


if __name__ == "__main__":
    main()

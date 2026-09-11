#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


def die(msg: str) -> None:
    raise SystemExit(f"artifact dispatch: {msg}")


def safe_path(raw: str) -> Path:
    p = PurePosixPath(raw)
    if not raw or raw.startswith('/') or '\\' in raw or any(x in ('', '.', '..') for x in p.parts):
        die(f"unsafe path: {raw!r}")
    if raw.startswith('.git/') or raw.startswith('.github/workflows/'):
        die(f"forbidden path: {raw}")
    return Path(*p.parts)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def ingest_text_chunks(manifest_path: Path, manifest: dict) -> None:
    target = safe_path(str(manifest['target_path']))
    aliases = [safe_path(str(x)) for x in manifest.get('aliases', [])]
    parts = [safe_path(str(x)) for x in manifest['transport']['parts']]
    for p in parts:
        if not p.is_file() or not p.as_posix().startswith('artifacts/staging/'):
            die(f"missing or invalid staging part: {p}")

    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('wb') as out:
        for p in parts:
            out.write(p.read_bytes())

    expected_size = int(manifest['size_bytes'])
    expected_sha = str(manifest['sha256']).lower()
    actual_size = target.stat().st_size
    actual_sha = sha256(target)
    if actual_size != expected_size or actual_sha != expected_sha:
        target.unlink(missing_ok=True)
        die(f"verification failed: size={actual_size}/{expected_size} sha={actual_sha}/{expected_sha}")

    for alias in aliases:
        alias.parent.mkdir(parents=True, exist_ok=True)
        alias.write_bytes(target.read_bytes())
        if sha256(alias) != expected_sha:
            die(f"alias verification failed: {alias}")

    receipt_dir = Path('artifacts/receipts')
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt = {
        'schema': 'poker-engine-artifact-receipt/v1',
        'manifest': manifest_path.name,
        'target_path': target.as_posix(),
        'aliases': [x.as_posix() for x in aliases],
        'sha256': actual_sha,
        'size_bytes': actual_size,
        'transport': 'raw_text_chunks',
        'imported_at_utc': datetime.now(timezone.utc).isoformat(),
    }
    (receipt_dir / manifest_path.name).write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    for p in parts:
        p.unlink()
    manifest_path.unlink()
    print(f"verified raw-text import: {target} ({actual_size} bytes, sha256={actual_sha})")


def main() -> None:
    if len(sys.argv) != 2:
        die('usage: ingest_dispatch.py MANIFEST')
    manifest_path = Path(sys.argv[1])
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('schema') == 'poker-engine-artifact-ingest/text-v1':
        transport = manifest.get('transport') or {}
        if transport.get('type') != 'raw_text_chunks':
            die('text-v1 requires transport.type=raw_text_chunks')
        ingest_text_chunks(manifest_path, manifest)
        return
    subprocess.run([sys.executable, 'tools/ingest_artifact.py', str(manifest_path)], check=True)


if __name__ == '__main__':
    main()

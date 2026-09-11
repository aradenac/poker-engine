#!/usr/bin/env python3
from pathlib import Path
import hashlib, json, shutil

ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / 'artifacts/staging/v83'
EXPECTED_SIZE = 420553
EXPECTED_SHA256 = '2690a82ffe363017b495a1aef60657b12db1b52eb402c36a1ff87f723c5d1bd4'
TARGETS = [
    ROOT / 'user/releases/poker_range_equity_offline_multiway_v83.html',
    ROOT / 'site/index.html',
]
parts = sorted(STAGE.glob('plain_part*.txt'))
if len(parts) != 28:
    raise SystemExit(f'expected 28 parts, found {len(parts)}')
data = b''.join(p.read_bytes() for p in parts)
sha = hashlib.sha256(data).hexdigest()
if len(data) != EXPECTED_SIZE or sha != EXPECTED_SHA256:
    raise SystemExit(f'v83 verification failed: size={len(data)} sha256={sha}')
for target in TARGETS:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
receipt = {
    'artifact': 'poker_range_equity_offline_multiway_v83.html',
    'size_bytes': len(data),
    'sha256': sha,
    'targets': [str(p.relative_to(ROOT)) for p in TARGETS],
}
receipt_path = ROOT / 'artifacts/receipts/v83-release.json'
receipt_path.parent.mkdir(parents=True, exist_ok=True)
receipt_path.write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
for p in STAGE.iterdir():
    if p.is_file():
        p.unlink()
print(json.dumps(receipt))

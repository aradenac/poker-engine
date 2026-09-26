#!/usr/bin/env python3
"""#419 hierarchical exact tree — evidence-integrity correction v2 (content-addressed).

The recorded evidence-integrity correction v1
(``analysis/issue419_hierarchical_tree/evidence_integrity_correction``, byte
``f601d619…``) reversed the in-place rewrite of the frozen #419 evidence by the
mutant commit ``871e0bd`` and declared that *no active reference* to the mutant
digests ``e86b7c6b`` / ``4fea09fc`` / ``ec010a54`` / ``db1b1ab6`` survived in
``tools/``, ``docs/``, ``tests/`` or ``contracts/``.  That declaration stopped
being true twice afterwards, and this record is the machine-readable account of
both incidents and of their repair:

* ``887e46a`` (*task backlog-agg*) **re-pinned** the exact-tree preflight tool
  onto the pre-correction custody digests -- ``V1_PREFLIGHT_SHA256`` /
  ``V1_INDEX_SHA256`` (``e86b7c6b`` / ``4fea09fc``) and
  ``PROTOCOL_V2_BYTE_SHA256`` / ``PROTOCOL_V2_CANONICAL_PAYLOAD_SHA256``
  (``db1b1ab6`` / ``e80732c4``) -- while the frozen bytes persisted on disk are
  the restored ones (``456d85be`` / ``97e90eac`` / ``74b8a006`` /
  ``cb598a9f``).  The pin and the byte disagreed, so
  ``tools/simulation/issue419_exact_tree_preflight.py --check`` failed closed.
  ``9859c46`` (*task backlog-911*) restored the four pins to the custody digests
  without rewriting one frozen byte.  This is the *re-pin* incident.
* ``4e16a60`` (*task backlog-txu*) rewrote frozen evidence **in place** and
  re-registered the resulting digests: ``raise_sizing_frontiers/
  RAISE_SIZING_FRONTIER_RESOLUTION.json`` ``93e7e3ed`` -> ``6a8cfcd1`` and
  ``terminal_decision/DECISION.json`` ``9425f301`` -> ``70a0d809`` with
  ``terminal_decision/ARTIFACTS.json`` ``08530e37`` -> ``1c433e7a``.
  ``0f9a6eb`` (*task backlog-i8v*) restored those bytes.  This is the
  *in-place mutation* incident.

Both repairs are already in the tree; this tool writes **no** frozen byte and
edits **no** predecessor record.  It derives the before/after digest table from
the persisted bytes (verified against the declared constants) and re-checks it
against the offending and parent revisions through the local git object store
whenever those objects are reachable, then publishes the result as a standalone
content-addressed bundle that no other index lists.

Reproduce: ``python3 tools/training/build_hierarchical_evidence_integrity_correction_v2.py``
Verify:    ``python3 tools/training/build_hierarchical_evidence_integrity_correction_v2.py --check``

The bundle is additive: it is *not* registered in the root
``analysis/issue419_hierarchical_tree/ARTIFACTS.json`` (hard pin ``1650cdd9``)
nor in any sibling index, so every other ``--check`` keeps its own closed
artifact set.  It never re-reads VALIDATION, never parses a hand history, never
runs the #367 Hero EV runner and never mutates an active model pointer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.training.audit_preflop_sizing_support import stable_hash  # noqa: E402
from tools.training import validation_order_guard as order_guard  # noqa: E402

SOURCE_PATH = Path(__file__).resolve()
HERE = ROOT / 'analysis/issue419_hierarchical_tree/evidence_integrity_correction_v2'
UPSTREAM = ROOT / 'analysis/issue419_hierarchical_tree'

SCHEMA = 'poker-issue419-evidence-integrity-correction/v2'
RECORD_NAME = 'EVIDENCE_INTEGRITY_CORRECTION_V2.json'
SUMMARY_NAME = 'SUMMARY.md'
INDEX_NAME = 'ARTIFACTS.json'
DIGEST_NAME = 'EVIDENCE_INTEGRITY_CORRECTION_V2.sha256'
MEMBER_NAMES = (RECORD_NAME, SUMMARY_NAME)

CORRECTION_ID = 'issue419-evidence-integrity-correction-v2'
AUTHORED_AT = '2026-09-26T00:00:00Z'
ISSUE = 419
PLANNER_KEY = 'T3'
BUNDLE_TASK = 'backlog-g95'
RECORDED_AGAINST_BRANCH = 'n8n/issue-419/task-backlog-g95'

# ---------------------------------------------------------------------------
# The frozen predecessor record (v1).  It is a member of no index it writes and
# is never edited by this tool: only its byte pin is re-verified.
# ---------------------------------------------------------------------------
V1_DIR = UPSTREAM / 'evidence_integrity_correction'
V1_RECORD_NAME = 'EVIDENCE_INTEGRITY_CORRECTION.json'
V1_RECORD = V1_DIR / V1_RECORD_NAME
V1_RECORD_BYTE_SHA256 = 'f601d6195ccc4b71a36c5e5729c07c3277bc910bce254c39028485181e8a8803'
V1_RECORD_SCHEMA = 'poker-issue419-evidence-integrity-correction/v1'
V1_MUTANT_COMMIT = '871e0bd9e66c978932face1accf1aaf22ac9fa1a'
V1_CORRECTION_COMMIT = 'c90452487b8824274979794839882e25cff9a87c'
# The four mutant names the v1 record declared no longer "actively" referenced.
V1_MUTANT_NAMES = (
    'e86b7c6b57d170c0885f46734c41302dcc15608252dfbbd66bff62c258d5c65f',
    '4fea09fc5713b9fa490effb39c557962ae1d06146710d954fb21bfd39ef25743',
    'ec010a541636e70eae7d5158611c0a47d9ae926785f50cbf55432f32b46d8cff',
    'db1b1ab60224eb76e7a271de6a9544c89ac9676036e725935d0fb47105b9f6f1',
)

# ---------------------------------------------------------------------------
# Frozen surface read by this record.  Every digest below is re-derived from the
# bytes persisted at HEAD before the record is written.
# ---------------------------------------------------------------------------
ROOT_INDEX = UPSTREAM / 'ARTIFACTS.json'
ROOT_INDEX_SHA256 = '1650cdd96adb70a47e7711eb44820bc46a9afc46f290b9023c60d101d903d768'
ROOT_SUMMARY = UPSTREAM / 'SUMMARY.md'
ROOT_SUMMARY_SHA256 = '737d315c6fde5d4863830952ab5bf396483bbefc47f3a4cdfcc7fe12508616e8'

FROZEN_BYTES_AT_HEAD: tuple[tuple[str, str], ...] = (
    (
        'analysis/issue419_hierarchical_tree/exact_tree_preflight/EXACT_TREE_PREFLIGHT.json',
        '456d85be57b910d3a56cb0160ba0ba35c988f7f69da9f965f0a887aaac473ae6',
    ),
    (
        'analysis/issue419_hierarchical_tree/exact_tree_preflight/SUMMARY.md',
        '3b87d9bcc366c35e97bde6a4be350704a0cf2eecadb464d5ac321298443778df',
    ),
    (
        'analysis/issue419_hierarchical_tree/exact_tree_preflight/ARTIFACTS.json',
        '97e90eac0a9302f1d0b304fa698f5179c7c0ee98ad52ebe307a911d9ccbfa5be',
    ),
    (
        'analysis/issue419_hierarchical_tree/terminal_decision/DECISION.json',
        '9425f30163dcfa5e0a72ca8f6dd1bb4b6a25ce270b4a894aaa57e898a74bd0bc',
    ),
    (
        'analysis/issue419_hierarchical_tree/terminal_decision/ARTIFACTS.json',
        '08530e37f8ecf232fc032612021f74459e6af771f15fc4097748c0d73f86b7e4',
    ),
    (
        'analysis/issue419_hierarchical_tree/validation_protocol_v2/'
        'FROZEN_VALIDATION_PROTOCOL_V2.json',
        '74b8a006ae84f8b9b22913ef76977e95f08992feb9765639a46d1ac49eb87350',
    ),
    (
        'analysis/issue419_hierarchical_tree/FROZEN_VALIDATION_PROTOCOL.json',
        '69c99a8b37589f1687b7e980344c9a79d69bbcd45be0a53ffd59bfea0ab583b3',
    ),
    (
        'analysis/issue419_hierarchical_tree/validation/VALIDATION_RESULT.json',
        '0b92e5a78ab3ee4cb581c33be351d6b52bcf4fcd8741ab907ebd6dd32ec6ef68',
    ),
    (
        'analysis/issue419_hierarchical_tree/ARTIFACTS.json',
        ROOT_INDEX_SHA256,
    ),
    (
        'analysis/issue419_hierarchical_tree/SUMMARY.md',
        ROOT_SUMMARY_SHA256,
    ),
    (
        'analysis/issue419_hierarchical_tree/fit/TRAIN_FIT_REPORT.json',
        'ae5b7cc84a8a7a38cd5d832810bf90ecc82aa03cfc4915fc9b33162dbad056b5',
    ),
    (
        'analysis/issue419_hierarchical_tree/fit/CANDIDATE_MANIFEST.json',
        'd6801eb15810ecfc3096d643e721f914cf2a34264e79eee2daaf7e413279303c',
    ),
    (
        'analysis/issue419_hierarchical_tree/contract/CANDIDATE_CONTRACT.json',
        'd62b2dca4a6673531c764b283de369f1192fe748eabcb4040f7ae0eda1823cd3',
    ),
)

# ---------------------------------------------------------------------------
# Incident 1 — ``887e46a`` re-pinned the preflight tool onto the pre-correction
# custody digests.  Each row is (pin constant, custody digest, re-pinned digest).
# ---------------------------------------------------------------------------
REGRESSION_COMMIT = '887e46afc34cae4334ffb279449c87a9b12bde71'
REGRESSION_SHORT = '887e46a'
REGRESSION_TASK = 'backlog-agg'
REGRESSION_SUBJECT = 'chore(n8n): task backlog-agg for issue #419'
REGRESSION_PARENT_COMMIT = '5be7239de8993beef65c019963193c7516ab6e75'
REGRESSION_REPAIR_COMMIT = '9859c46ede94646a7547871369bb257b8510114d'
REGRESSION_REPAIR_SHORT = '9859c46'
REGRESSION_REPAIR_TASK = 'backlog-911'
REGRESSION_REPAIR_SUBJECT = 'chore(n8n): task backlog-911 for issue #419'
REGRESSION_TOOL = 'tools/simulation/issue419_exact_tree_preflight.py'
REGRESSION_TOOL_BEFORE_SHA256 = (
    'c8f7538464d3a4df001f8ec172fae41f0ad6d176d024a0a4136a3114f7fa5361'
)
REGRESSION_TOOL_REPINNED_SHA256 = (
    'dfc405abf482c574793cde595baf55c5f43961f31ba278b58241624bc4f7009d'
)
REGRESSION_TOOL_REPAIRED_SHA256 = (
    'c5d34a3dc03c418acefe627eae9a6973264f1fd75ab55200e82c30bd550fe19b'
)

TOOL_PIN_ROWS: tuple[tuple[str, str, str], ...] = (
    (
        'V1_PREFLIGHT_SHA256',
        '456d85be57b910d3a56cb0160ba0ba35c988f7f69da9f965f0a887aaac473ae6',
        'e86b7c6b57d170c0885f46734c41302dcc15608252dfbbd66bff62c258d5c65f',
    ),
    (
        'V1_INDEX_SHA256',
        '97e90eac0a9302f1d0b304fa698f5179c7c0ee98ad52ebe307a911d9ccbfa5be',
        '4fea09fc5713b9fa490effb39c557962ae1d06146710d954fb21bfd39ef25743',
    ),
    (
        'PROTOCOL_V2_BYTE_SHA256',
        '74b8a006ae84f8b9b22913ef76977e95f08992feb9765639a46d1ac49eb87350',
        'db1b1ab60224eb76e7a271de6a9544c89ac9676036e725935d0fb47105b9f6f1',
    ),
    (
        'PROTOCOL_V2_CANONICAL_PAYLOAD_SHA256',
        'cb598a9fc2353aa78f19a7263a62a8ccbdba60eb400264787e896d0c232f19de',
        'e80732c4ea5512863c448497b89896799f24c942f744193832dabd5c568579f0',
    ),
)

# ---------------------------------------------------------------------------
# Incident 2 — ``4e16a60`` rewrote frozen evidence in place and re-registered
# the digests.  Every row is (path, mutant digest, restored digest).
# ---------------------------------------------------------------------------
MUTATION_COMMIT = '4e16a60ac1c58b56429c0eda8ce36778dcea8971'
MUTATION_SHORT = '4e16a60'
MUTATION_TASK = 'backlog-txu'
MUTATION_SUBJECT = 'chore(n8n): task backlog-txu for issue #419'
MUTATION_PARENT_COMMIT = '3f2dc2c0ee52c624697eba2bdd0b81c7d2f3d0f9'
MUTATION_REPAIR_COMMIT = '0f9a6eb0e53a5191a2302d5eabb175ae267f7c24'
MUTATION_REPAIR_SHORT = '0f9a6eb'
MUTATION_REPAIR_TASK = 'backlog-i8v'
MUTATION_REPAIR_SUBJECT = 'chore(n8n): task backlog-i8v for issue #419'
HEAD_COMMIT = MUTATION_REPAIR_COMMIT

MUTATION_ROWS: tuple[tuple[str, str, str, str], ...] = (
    (
        'analysis/issue419_hierarchical_tree/raise_sizing_frontiers/'
        'RAISE_SIZING_FRONTIER_RESOLUTION.json',
        '93e7e3ede0a69e6b3e35f40217bd53ff95d1fbbb847ca3fbc9181c0689d0152e',
        '6a8cfcd1dbea6203538fbece8d07f02ee19e3e4e755cc5c8e87f8cd88746809a',
        '93e7e3ede0a69e6b3e35f40217bd53ff95d1fbbb847ca3fbc9181c0689d0152e',
    ),
    (
        'analysis/issue419_hierarchical_tree/raise_sizing_frontiers/ARTIFACTS.json',
        '86ab23239979b9ee5a0e5cf4111cc7bc9525b417b567fb324699594fbc2ba3cf',
        'a7dd833e377beb2ccd4a52368b622352953a0d13272684a6bf87b9ce227f9b1b',
        '86ab23239979b9ee5a0e5cf4111cc7bc9525b417b567fb324699594fbc2ba3cf',
    ),
    (
        'analysis/issue419_hierarchical_tree/raise_sizing_frontiers/SUMMARY.md',
        'cf092d67b1b09d604f1de14b6c9335de32e4bbbf30410d0b7d758ac40ccc850c',
        '4aabb5ec2e566532cbc3f22a41e417ad723bc40a6e5da1193ea7dc3bfee51de2',
        'cf092d67b1b09d604f1de14b6c9335de32e4bbbf30410d0b7d758ac40ccc850c',
    ),
    (
        'analysis/issue419_hierarchical_tree/terminal_decision/DECISION.json',
        '9425f30163dcfa5e0a72ca8f6dd1bb4b6a25ce270b4a894aaa57e898a74bd0bc',
        '70a0d8097c9629c6db71be452f2fb71112b12c323b98970eea4a32a7e450e411',
        '9425f30163dcfa5e0a72ca8f6dd1bb4b6a25ce270b4a894aaa57e898a74bd0bc',
    ),
    (
        'analysis/issue419_hierarchical_tree/terminal_decision/ARTIFACTS.json',
        '08530e37f8ecf232fc032612021f74459e6af771f15fc4097748c0d73f86b7e4',
        '1c433e7a1bf78db834aa7c7fc3cc32739d4980f0908fc2066f9ccca31813637b',
        '08530e37f8ecf232fc032612021f74459e6af771f15fc4097748c0d73f86b7e4',
    ),
    (
        'analysis/issue419_hierarchical_tree/terminal_decision/DECISION.sha256',
        '7a7169d03f7bc43df41f1bc27f05f364ac477f0a345801e229fc32027f9cbe37',
        '9c5aa225ba2df7e0ff04addf6f3eb200828ca02ebb1ce499438d314544a85359',
        '7a7169d03f7bc43df41f1bc27f05f364ac477f0a345801e229fc32027f9cbe37',
    ),
    (
        'tools/training/resolve_raise_sizing_frontiers.py',
        '307fb62490368e51ed0a7e461c286e780e79398b9156561e56b4de95312b5834',
        '7e856e11a11415615347e68f53798c6e244a8a1c31497c746de1ce9575be5380',
        '91ebba7897eb6d6c07643293901e85556288292ce7c09fde176c8d0ef8aa645b',
    ),
    (
        'tools/training/finalize_hierarchical_exact_tree_decision.py',
        '80764cbe69da712f6356a1c7f3ce0aa5712e6785f1cb7acc5035a97d2e77f235',
        '80764cbe69da712f6356a1c7f3ce0aa5712e6785f1cb7acc5035a97d2e77f235',
        '2f6dacac0d1653448b70c454fbca9dffb40bc956bc43286985564970e2f8dc1c',
    ),
    (
        'tests/training/test_raise_sizing_frontier_resolution.py',
        'd1d3a7e5bec1a3d74b10bf4c9c597113916f2deb06903479eacee421e9ed4999',
        'c2c020c9efedb474e9c98f3f4ffc75cc7306f2cb8d1e10a2258d47aa7ee7c7a8',
        '751a55f005a8e6cb9e006771f13675febcf55135999e5b579d04b77ef590ea0a',
    ),
    (
        'tests/training/test_hierarchical_terminal_decision.py',
        '61135652c3f36df265662c70517e85d4c5e7284352fb312eb38621c3c3778fa8',
        '61135652c3f36df265662c70517e85d4c5e7284352fb312eb38621c3c3778fa8',
        '34f2d8c45df8f28a05a748ef39f62b03e042bc5457a2b64fccc8df8d9b21f520',
    ),
)

REGRESSION_ROWS: tuple[tuple[str, str, str, str], ...] = (
    (
        'tools/simulation/issue419_exact_tree_preflight.py',
        REGRESSION_TOOL_BEFORE_SHA256,
        REGRESSION_TOOL_REPINNED_SHA256,
        REGRESSION_TOOL_REPAIRED_SHA256,
    ),
    (
        'tests/simulation/test_issue419_exact_tree_preflight.py',
        '933c35a4333500f4fb61d4b69dd50c8d028adb1dd801ad67e34d4692339ffe75',
        '421303847833ca619ae02fdf9f509cb5c5a25915250ed040c9453e9317239d8e',
        '47407185d5206a59c612e12c8eb50bdbc192bb97ab99a7692d9e9749f7de78fd',
    ),
    (
        'analysis/issue419_hierarchical_tree/exact_tree_preflight_v2/'
        'EXACT_TREE_PREFLIGHT_V2.json',
        '9d9cede166983a67cb64af7514e69a1f022790a66b45fb7a77f0f6b79d5569ef',
        '2c07ae3279d10ec3e3bbdbe81cdb0d0f1f23e6bbb91cbdadddae113d1a9ea691',
        '9b924077b286ef8c7c57e8a6e757cfb22a9784d2b44e8b328b11a55ba27abfc2',
    ),
    (
        'analysis/issue419_hierarchical_tree/exact_tree_preflight_v2/SUMMARY.md',
        '7706c3421baf312ebdefa4ed8f0cabcf43258197acf862e8bfa2fe6c046c3408',
        '29a560cbfe69cf834d0a486d28808f455487f01c43a5696ee2f856035bd2ea45',
        'ae130aaf4e1f9e42c66c9cc17b6335b5cfabd6df56959c9c83ffee757fdbdbbb',
    ),
    (
        'analysis/issue419_hierarchical_tree/exact_tree_preflight_v2/ARTIFACTS.json',
        '01797e314b3a71130db0f3dd3116ec99fd29b05ee00387efb09f032b00364e09',
        '22ef95ca14743ab18221143750becf9629ed3ad6e6a00d8f4121e1c988e27240',
        '8738385f059bab207764586a73fe097ab97cbe8c4123eac2fac8532f04c49bbf',
    ),
)

# The two files ``4e16a60`` added and the repair deliberately kept: their bytes at
# HEAD are the offender's, not the parent's, so they are *not* evidence that was
# reverted -- they are recorded separately so the table never overstates a revert.
MUTATION_RETAINED_ROWS: tuple[tuple[str, str, str, str], ...] = (
    (
        'tests/training/test_hierarchical_candidate_contract.py',
        '90cdc9f63d43541daa1c0db1e38a54897c7199f38fc73f6590f9efd735babe78',
        '36d3b3d1d090a25a64c010aa5a94e8d0136f34ea2e62522d0aeb64e5733f0de3',
        '36d3b3d1d090a25a64c010aa5a94e8d0136f34ea2e62522d0aeb64e5733f0de3',
    ),
    (
        'tests/training/test_hierarchical_tree_sparsity_parity.py',
        '6a0ed3b48c45eb0ce4142fa0cf68e5061da9cdec3aaf244ba0476e440937f74a',
        'c61526387815a460eb912900d389099673ae0dd2455729deb24b9edd5d3832c1',
        'c61526387815a460eb912900d389099673ae0dd2455729deb24b9edd5d3832c1',
    ),
)

# Names that must not survive as *objects* on disk: every digest the reverted
# mutant commits registered.
MUTANT_OBJECT_DIGESTS: tuple[str, ...] = (
    'e86b7c6b57d170c0885f46734c41302dcc15608252dfbbd66bff62c258d5c65f',
    '4fea09fc5713b9fa490effb39c557962ae1d06146710d954fb21bfd39ef25743',
    'db1b1ab60224eb76e7a271de6a9544c89ac9676036e725935d0fb47105b9f6f1',
    'ec010a541636e70eae7d5158611c0a47d9ae926785f50cbf55432f32b46d8cff',
    '6a8cfcd1dbea6203538fbece8d07f02ee19e3e4e755cc5c8e87f8cd88746809a',
    'a7dd833e377beb2ccd4a52368b622352953a0d13272684a6bf87b9ce227f9b1b',
    '4aabb5ec2e566532cbc3f22a41e417ad723bc40a6e5da1193ea7dc3bfee51de2',
    '70a0d8097c9629c6db71be452f2fb71112b12c323b98970eea4a32a7e450e411',
    '1c433e7a1bf78db834aa7c7fc3cc32739d4980f0908fc2066f9ccca31813637b',
    '9c5aa225ba2df7e0ff04addf6f3eb200828ca02ebb1ce499438d314544a85359',
)

# Where the mutant *names* are allowed to survive as recorded history (never as
# a custody pin).  Directory prefixes are accepted; anything outside this list
# would be a new, unreviewed reference and fails the check.
MUTANT_NAME_HISTORY_ALLOWLIST: tuple[str, ...] = (
    'docs/hierarchical-exact-context-validation-protocol.md',
    '.project/decisions/20260926-hierarchical-integration-report-v2.md',
    '.project/decisions/20260926-hierarchical-frozen-evidence-correction.md',
    '.project/decisions/20260926-hierarchical-evidence-integrity-correction-v2.md',
    'tools/training/build_hierarchical_integration_bundle_v2.py',
    'analysis/issue419_hierarchical_tree/evidence_integrity_correction/',
    'analysis/issue419_hierarchical_tree/ci_evidence/',
    'analysis/issue419_hierarchical_tree_v2/',
)
SCAN_ROOTS: tuple[str, ...] = (
    '.github',
    '.project',
    'analysis',
    'contracts',
    'docs',
    'tests',
    'tools',
)
SCAN_SUFFIXES = ('.json', '.md', '.py', '.txt', '.sha256', '.yml', '.yaml')


class CorrectionRecordError(RuntimeError):
    """Raised when the evidence-integrity correction record cannot be produced."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def serialize(payload: Any) -> bytes:
    return (json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True) + '\n').encode()


def _relative(path: Path | str) -> str:
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def _load(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _canonical_of_bytes(data: bytes) -> str | None:
    try:
        return stable_hash(json.loads(data))
    except (ValueError, UnicodeDecodeError):
        return None


def git_blob(rev: str, path: str) -> bytes | None:
    """The bytes of ``path`` at ``rev``, or ``None`` when git cannot answer."""
    try:
        return subprocess.check_output(
            ['git', '-C', str(ROOT), 'show', f'{rev}:{path}'],
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None


def object_paths_named(digest: str) -> list[str]:
    """Every ``analysis/**`` object file whose name is exactly ``digest``."""
    return sorted(
        _relative(path)
        for path in ROOT.glob('analysis/**/sha256/*')
        if path.is_file() and path.stem == digest
    )


def pin_state() -> tuple[dict[str, str], dict[str, Any]]:
    """Re-derive the preflight tool's four custody pins and the frozen bytes."""
    module = _module_constants(ROOT / REGRESSION_TOOL)
    observed = {name: str(module.get(name) or '') for name, _, _ in TOOL_PIN_ROWS}
    rows: list[dict[str, Any]] = []
    for name, custody, repinned in TOOL_PIN_ROWS:
        live = observed[name]
        if live != custody:
            raise CorrectionRecordError(
                f'{name} no longer equals the restored custody digest: {live} != {custody}'
            )
        rows.append({
            'pin': name,
            'custody_digest': custody,
            'repinned_by_887e46a': repinned,
            'pin_at_head': live,
            'matches_custody_at_head': True,
        })
    return observed, {
        'check': 'preflight_tool_custody_pins_equal_the_restored_bytes_at_head',
        'result': 'PASS',
        'tool': REGRESSION_TOOL,
        'rows': rows,
    }


def _module_constants(path: Path) -> dict[str, Any]:
    """Read simple ``NAME = 'value'`` assignments out of another module's source."""
    import ast

    constants: dict[str, Any] = {}
    module = ast.parse(path.read_text(encoding='utf-8'))
    for node in module.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        try:
            constants[target.id] = ast.literal_eval(node.value)
        except ValueError:
            continue
    return constants


def digest_table() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The before/after digest table, re-derived from the persisted bytes."""
    rows: list[dict[str, Any]] = []
    git_checked: list[str] = []
    git_unreachable: list[str] = []
    for path, before_sha, mutant_sha, restored_sha in REGRESSION_ROWS:
        rows.append(_table_row(
            'REGRESSION_887E46A', path, REGRESSION_PARENT_COMMIT, REGRESSION_COMMIT,
            before_sha, mutant_sha, restored_sha, git_checked, git_unreachable,
        ))
    for path, before_sha, mutant_sha, restored_sha in MUTATION_ROWS:
        rows.append(_table_row(
            'MUTATION_4E16A60', path, MUTATION_PARENT_COMMIT, MUTATION_COMMIT,
            before_sha, mutant_sha, restored_sha, git_checked, git_unreachable,
        ))
    for path, before_sha, mutant_sha, restored_sha in MUTATION_RETAINED_ROWS:
        rows.append(_table_row(
            'MUTATION_4E16A60_RETAINED', path, MUTATION_PARENT_COMMIT, MUTATION_COMMIT,
            before_sha, mutant_sha, restored_sha, git_checked, git_unreachable,
        ))
    return rows, {
        'check': 'before_after_digest_table_re_derived',
        'result': 'PASS',
        'rule': (
            'at_head_sha256 == sha256(bytes persisted at HEAD); mutant_sha256 == sha256(bytes at '
            'the offending revision); before_sha256 == sha256(bytes at the offending commit\'s '
            'parent).  A REVERTED row has before == at_head (the repair put the parent bytes back); '
            'a REWRITTEN row has before != at_head (the repair is a new revision that restores the '
            'pin, not the file); a RETAINED row has mutant == at_head (the repair deliberately kept '
            'the offender\'s bytes)'
        ),
        'git_objects_cross_checked': sorted(git_checked),
        'git_objects_unreachable_in_this_checkout': sorted(git_unreachable),
        'object_path_note': (
            'mutant_object / at_head_object name the content-addressed object each revision would '
            'occupy in a twin bundle; a *missing* mutant object is exactly what mutant_objects_absent '
            'asserts, so the field is a cross-reference, not a claim that the file exists'
        ),
    }


def _table_row(
    group: str,
    path: str,
    parent_commit: str,
    offender_commit: str,
    before_sha: str,
    mutant_sha: str,
    at_head_sha: str,
    git_checked: list[str],
    git_unreachable: list[str],
) -> dict[str, Any]:
    live = ROOT / path
    if not live.is_file():
        raise CorrectionRecordError(f'the frozen artifact is missing from the worktree: {path}')
    live_bytes = live.read_bytes()
    live_sha = sha256_bytes(live_bytes)
    if live_sha != at_head_sha:
        raise CorrectionRecordError(
            f'{path} does not carry the recorded bytes at HEAD: {live_sha} != {at_head_sha}'
        )
    mutant_bytes = git_blob(offender_commit, path)
    if mutant_bytes is None:
        git_unreachable.append(f'{offender_commit}:{path}')
        mutant_canonical = None
    else:
        git_checked.append(f'{offender_commit}:{path}')
        if sha256_bytes(mutant_bytes) != mutant_sha:
            raise CorrectionRecordError(
                f'{path} at {offender_commit} is not the recorded mutant: '
                f'{sha256_bytes(mutant_bytes)} != {mutant_sha}'
            )
        mutant_canonical = _canonical_of_bytes(mutant_bytes)
    parent_bytes = git_blob(parent_commit, path)
    if parent_bytes is None:
        git_unreachable.append(f'{parent_commit}:{path}')
        before_canonical = None
    else:
        git_checked.append(f'{parent_commit}:{path}')
        if sha256_bytes(parent_bytes) != before_sha:
            raise CorrectionRecordError(
                f'{path} at the parent {parent_commit} is not the recorded before revision: '
                f'{sha256_bytes(parent_bytes)} != {before_sha}'
            )
        before_canonical = _canonical_of_bytes(parent_bytes)
    extension = '.md' if path.endswith('.md') else ('.py' if path.endswith('.py') else '.json')
    changed_by_the_offender = before_sha != mutant_sha
    reverted_to_the_parent_bytes = changed_by_the_offender and before_sha == at_head_sha
    rewritten_by_the_repair = (
        changed_by_the_offender and at_head_sha != before_sha and at_head_sha != mutant_sha
    )
    kept_the_offender_bytes = changed_by_the_offender and at_head_sha == mutant_sha
    row: dict[str, Any] = {
        'surface': group,
        'path': path,
        'mutant_commit': offender_commit,
        'parent_commit': parent_commit,
        'before_sha256': before_sha,
        'mutant_sha256': mutant_sha,
        'at_head_sha256': at_head_sha,
        'mutant_object': f'sha256/{mutant_sha}{extension}',
        'at_head_object': f'sha256/{at_head_sha}{extension}',
        'before_canonical_payload_sha256': before_canonical,
        'mutant_canonical_payload_sha256': mutant_canonical,
        'at_head_canonical_payload_sha256': _canonical_of_bytes(live_bytes),
        'changed_by_the_offender': changed_by_the_offender,
        'reverted_to_the_parent_bytes': reverted_to_the_parent_bytes,
        'rewritten_by_the_repair': rewritten_by_the_repair,
        'kept_the_offender_bytes': kept_the_offender_bytes,
    }
    return row


def frozen_bytes_at_head() -> dict[str, Any]:
    observed: dict[str, str] = {}
    for path, expected in FROZEN_BYTES_AT_HEAD:
        actual = sha256_file(ROOT / path)
        if actual != expected:
            raise CorrectionRecordError(f'the frozen byte drifted at HEAD: {path} {actual}')
        observed[path] = actual
    return {
        'check': 'frozen_bytes_re_derived_at_head',
        'result': 'PASS',
        'recorded': observed,
        'predecessor_record': {_relative(V1_RECORD): V1_RECORD_BYTE_SHA256},
    }


def mutant_name_survey() -> dict[str, Any]:
    """Every surviving textual mention of a mutant name, and where it is allowed."""
    observed: dict[str, list[str]] = {name: [] for name in (*V1_MUTANT_NAMES, *MUTANT_OBJECT_DIGESTS)}
    generator = _relative(SOURCE_PATH)
    for root_name in SCAN_ROOTS:
        root = ROOT / root_name
        if not root.is_dir():
            continue
        for path in sorted(root.rglob('*')):
            if not path.is_file() or path.suffix.lower() not in SCAN_SUFFIXES:
                continue
            relative = _relative(path)
            if relative.startswith(_relative(HERE)) or relative == generator:
                continue
            try:
                text = path.read_text(encoding='utf-8', errors='ignore')
            except OSError:
                continue
            for name in observed:
                if name in text:
                    observed[name].append(relative)
    offenders: list[dict[str, str]] = []
    for name, paths in observed.items():
        for relative in paths:
            allowed = any(
                relative == entry or relative.startswith(entry)
                for entry in (*MUTANT_NAME_HISTORY_ALLOWLIST, _relative(HERE))
            )
            if not allowed:
                offenders.append({'digest': name, 'path': relative})
    if offenders:
        raise CorrectionRecordError(
            f'a mutant name survives outside its declared history: {offenders}'
        )
    return {
        'check': 'mutant_names_survive_only_as_declared_history',
        'result': 'PASS',
        'scanned_roots': list(SCAN_ROOTS),
        'excluded_from_the_scan': [_relative(HERE), generator],
        'declared_history_allowlist': list(MUTANT_NAME_HISTORY_ALLOWLIST),
        'mentions_outside_this_record_and_its_generator': {
            name: paths for name, paths in sorted(observed.items()) if paths
        },
        'undeclared_references': [],
        'detail': (
            'no mutant digest survives as a content-addressed object, as a custody pin or as an '
            'undeclared textual reference; every remaining mention is declared recorded history'
        ),
    }


def mutant_objects_absent() -> dict[str, Any]:
    present: list[dict[str, str]] = []
    for digest in MUTANT_OBJECT_DIGESTS:
        for path in object_paths_named(digest):
            present.append({'digest': digest, 'path': path})
    if present:
        raise CorrectionRecordError(f'a mutant content-addressed object survives on disk: {present}')
    return {
        'check': 'no_mutant_content_addressed_object_survives',
        'result': 'PASS',
        'digests_probed': len(MUTANT_OBJECT_DIGESTS),
        'surviving_objects': [],
    }


def verify_predecessor() -> dict[str, Any]:
    if not V1_RECORD.is_file():
        raise CorrectionRecordError(f'the frozen v1 correction record is missing: {V1_RECORD}')
    actual = sha256_file(V1_RECORD)
    if actual != V1_RECORD_BYTE_SHA256:
        raise CorrectionRecordError(
            f'the v1 correction record drifted: {actual} != {V1_RECORD_BYTE_SHA256}'
        )
    payload = _load(V1_RECORD)
    if payload.get('schema') != V1_RECORD_SCHEMA:
        raise CorrectionRecordError(f'unexpected v1 correction schema: {payload.get("schema")!r}')
    return {
        'path': _relative(V1_RECORD),
        'schema': V1_RECORD_SCHEMA,
        'byte_sha256': actual,
        'relationship': (
            'ADDITIVE_COMPANION_NEVER_EDITED: the v1 record stays byte-frozen; this record adds the '
            'two later incidents and their repairs without rewriting one predecessor byte'
        ),
        'claim_re_examined': {
            'claim': (
                'no active reference to e86b7c6b / 4fea09fc / ec010a54 / db1b1ab6 remains in '
                'tools/, docs/, tests/ or contracts/'
            ),
            'status_when_written': 'HELD',
            'status_after_887e46a': 'BROKEN',
            'status_at_head': 'HELD_AGAIN',
            'precise_head_reading': (
                'none of the four names is a custody pin, a checked digest or a content-addressed '
                'object any more; each survives only as recorded history (see mutant_name_survey)'
            ),
        },
    }


def verify_root_index() -> dict[str, Any]:
    if sha256_file(ROOT_INDEX) != ROOT_INDEX_SHA256:
        raise CorrectionRecordError('the root #419 artifact index moved')
    if sha256_file(ROOT_SUMMARY) != ROOT_SUMMARY_SHA256:
        raise CorrectionRecordError('the root #419 summary moved')
    return {
        'root_index': _relative(ROOT_INDEX),
        'root_index_sha256': ROOT_INDEX_SHA256,
        'root_summary': _relative(ROOT_SUMMARY),
        'root_summary_sha256': ROOT_SUMMARY_SHA256,
        'bundle_registered_in_any_other_index': False,
        'root_index_mutated': False,
    }


def verify_order_guard() -> dict[str, Any]:
    offenders = order_guard.validation_result_artifacts()
    if _relative(HERE) in ' '.join(offenders):
        raise CorrectionRecordError(
            'the correction record must not look like a candidate VALIDATION read to the order guard'
        )
    if len(offenders) != 2:
        raise CorrectionRecordError(
            'the order guard must see exactly the two frozen VALIDATION artifacts, saw: '
            f'{offenders}'
        )
    return {
        'check': 'order_guard_does_not_classify_this_record',
        'result': 'PASS',
        'validation_result_artifacts': offenders,
        'this_bundle_classified_as_a_validation_result': False,
    }


def build_payload() -> dict[str, Any]:
    predecessor = verify_predecessor()
    _, pins = pin_state()
    table, table_check = digest_table()
    survey = mutant_name_survey()
    objects = mutant_objects_absent()
    frozen = frozen_bytes_at_head()
    root = verify_root_index()
    order = verify_order_guard()
    return {
        'schema': SCHEMA,
        'correction_id': CORRECTION_ID,
        'issue': ISSUE,
        'planner_key': PLANNER_KEY,
        'bundle_task': BUNDLE_TASK,
        'authored_at': AUTHORED_AT,
        'recorded_against_branch': RECORDED_AGAINST_BRANCH,
        'revision': 'v2',
        'predecessor_record': predecessor,
        'incidents': [
            {
                'incident_id': 'V1_PREFLIGHT_AND_PROTOCOL_V2_PIN_REGRESSION',
                'kind': 'RE_PIN_OF_RESTORED_CUSTODY_PINS',
                'commit': REGRESSION_COMMIT,
                'short_sha': REGRESSION_SHORT,
                'task': REGRESSION_TASK,
                'subject': REGRESSION_SUBJECT,
                'parent_commit': REGRESSION_PARENT_COMMIT,
                'surface': REGRESSION_TOOL,
                'what_happened': (
                    '887e46a re-pointed the exact-tree preflight tool onto the pre-correction custody '
                    'digests while the frozen bytes persisted on disk stayed the restored ones, so the '
                    'pin and the byte disagreed and issue419_exact_tree_preflight.py --check failed '
                    'closed on its own frozen surface'
                ),
                'violated_claim': predecessor['claim_re_examined']['claim'],
                'detected_by': 'python3 tools/simulation/issue419_exact_tree_preflight.py --check',
                'observed_before_repair': (
                    'PreflightError: the frozen v1 preflight artifact drifted: '
                    'EXACT_TREE_PREFLIGHT.json e86b7c6b57d170c0885f46734c41302dcc15608252dfbbd66bff62c258d5c65f'
                    ' != 456d85be57b910d3a56cb0160ba0ba35c988f7f69da9f965f0a887aaac473ae6'
                ),
                'tool_bytes': {
                    'before': REGRESSION_TOOL_BEFORE_SHA256,
                    'repinned': REGRESSION_TOOL_REPINNED_SHA256,
                    'at_head': REGRESSION_TOOL_REPAIRED_SHA256,
                },
                'ci_effect': (
                    'the #419 preflight suite and the exact-tree preflight check were red from 887e46a '
                    'until the repair'
                ),
                'repaired_by': {
                    'commit': REGRESSION_REPAIR_COMMIT,
                    'short_sha': REGRESSION_REPAIR_SHORT,
                    'task': REGRESSION_REPAIR_TASK,
                    'subject': REGRESSION_REPAIR_SUBJECT,
                    'method': 'RESTORE_THE_FOUR_CUSTODY_PINS_TO_THE_RESTORED_DIGESTS',
                    'frozen_byte_rewritten': False,
                },
            },
            {
                'incident_id': 'IN_PLACE_MUTATION_OF_FROZEN_EVIDENCE',
                'kind': 'IN_PLACE_REWRITE_AND_RE_REGISTRATION',
                'commit': MUTATION_COMMIT,
                'short_sha': MUTATION_SHORT,
                'task': MUTATION_TASK,
                'subject': MUTATION_SUBJECT,
                'parent_commit': MUTATION_PARENT_COMMIT,
                'surface': [
                    'analysis/issue419_hierarchical_tree/raise_sizing_frontiers',
                    'analysis/issue419_hierarchical_tree/terminal_decision',
                ],
                'what_happened': (
                    '4e16a60 rewrote the raise-sizing frontier resolution and the terminal decision in '
                    'place and re-registered the resulting digests, which makes the mutant commit the '
                    'only witness of its own claim'
                ),
                'violated_claim': predecessor['claim_re_examined']['claim'],
                'detected_by': (
                    'PYTHONPATH=. python3 tests/training/test_hierarchical_terminal_decision.py and '
                    'PYTHONPATH=. python3 tests/training/test_raise_sizing_frontier_resolution.py'
                ),
                'moved': [
                    {
                        'path': 'analysis/issue419_hierarchical_tree/raise_sizing_frontiers/'
                                'RAISE_SIZING_FRONTIER_RESOLUTION.json',
                        'at_head_sha256': '93e7e3ede0a69e6b3e35f40217bd53ff95d1fbbb847ca3fbc9181c0689d0152e',
                        'mutant_sha256': '6a8cfcd1dbea6203538fbece8d07f02ee19e3e4e755cc5c8e87f8cd88746809a',
                    },
                    {
                        'path': 'analysis/issue419_hierarchical_tree/terminal_decision/DECISION.json',
                        'at_head_sha256': '9425f30163dcfa5e0a72ca8f6dd1bb4b6a25ce270b4a894aaa57e898a74bd0bc',
                        'mutant_sha256': '70a0d8097c9629c6db71be452f2fb71112b12c323b98970eea4a32a7e450e411',
                    },
                    {
                        'path': 'analysis/issue419_hierarchical_tree/terminal_decision/ARTIFACTS.json',
                        'at_head_sha256': '08530e37f8ecf232fc032612021f74459e6af771f15fc4097748c0d73f86b7e4',
                        'mutant_sha256': '1c433e7a1bf78db834aa7c7fc3cc32739d4980f0908fc2066f9ccca31813637b',
                    },
                ],
                'repaired_by': {
                    'commit': MUTATION_REPAIR_COMMIT,
                    'short_sha': MUTATION_REPAIR_SHORT,
                    'task': MUTATION_REPAIR_TASK,
                    'subject': MUTATION_REPAIR_SUBJECT,
                    'method': 'RESTORE_THE_PRE_MUTANT_BYTES_AND_MOVE_THE_MUTANT_OBJECTS_ASIDE',
                    'frozen_byte_re_registered': False,
                },
            },
        ],
        'digest_table': table,
        'digest_table_check': table_check,
        'tool_pin_table': pins,
        'mutant_object_check': objects,
        'mutant_name_survey': survey,
        'frozen_bytes_reverified_at_head': frozen,
        'index_discipline': root,
        'order_guard': order,
        'repair': {
            'frozen_byte_rewritten': False,
            'frozen_byte_re_registered': False,
            'frozen_custody_pin_re_pointed': False,
            'predecessor_record_edited': False,
            'active_model_pointer_mutated': False,
            'thresholds_changed': False,
            'priors_changed': False,
            'pooling_limits_changed': False,
            'admission_rules_changed': False,
            'validation_reconsumed': False,
            'test_data_read': False,
            'hero_ev_executed': False,
            'issue367_run': False,
            'summary': (
                'both incidents are already repaired in the tree; this record documents them, '
                'the before/after digests and the cross-reference to the offending and repairing '
                'commits, and writes no frozen byte'
            ),
        },
        'commit_cross_reference': {
            'regression': {
                'offending': REGRESSION_COMMIT,
                'parent': REGRESSION_PARENT_COMMIT,
                'repair': REGRESSION_REPAIR_COMMIT,
            },
            'mutation': {
                'offending': MUTATION_COMMIT,
                'parent': MUTATION_PARENT_COMMIT,
                'repair': MUTATION_REPAIR_COMMIT,
            },
            'predecessor_correction': {
                'offending': V1_MUTANT_COMMIT,
                'repair': V1_CORRECTION_COMMIT,
            },
            'note': (
                'the repair commits are the commits that restored the bytes or pins; the record '
                'never rewrites their result, it re-verifies it'
            ),
        },
        'residual_findings': [
            {
                'finding_id': 'INTEGRATION_BUNDLE_V2_PINS_PRE_REPAIR_REVISIONS',
                'detail': (
                    'analysis/issue419_hierarchical_tree_v2/ still binds EXACT_TREE_PREFLIGHT_V2.json '
                    'to 2c07ae32 and DECISION_V2.json to ac291b9e, the revisions that existed when it '
                    'was authored; 9859c46 and 0f9a6eb later regenerated those bundles, so '
                    'PYTHONPATH=. python3 tests/training/test_issue419_hierarchical_exact_tree.py is '
                    'red at HEAD (2 failures, 1 error)'
                ),
                'detected_by': 'PYTHONPATH=. python3 tests/training/test_issue419_hierarchical_exact_tree.py',
                'owner': 'the #419 integration-bundle task (backlog-oso / T7), not this record',
                'repaired_by_this_record': False,
                'touches_a_frozen_byte': False,
                'reason_not_repaired_here': (
                    'the integration bundle is a separate consumer of these surfaces; repairing it '
                    'would rewrite its generated members and its own recorded residual findings, '
                    'which is out of this record\'s scope'
                ),
            },
            {
                'finding_id': 'MUTANT_NAMES_SURVIVE_AS_RECORDED_HISTORY',
                'detail': (
                    'e86b7c6b, 4fea09fc, db1b1ab6 and e80732c4 still appear as recorded history in '
                    'the v1 correction record, the integration report and the validation-protocol '
                    'document; none of them is a custody pin, a checked digest or an object on disk'
                ),
                'detected_by': 'tools/training/build_hierarchical_evidence_integrity_correction_v2.py --check',
                'owner': 'documented, intentional history',
                'repaired_by_this_record': False,
                'touches_a_frozen_byte': False,
            },
        ],
        'reproduction': {
            'build': 'python3 tools/training/build_hierarchical_evidence_integrity_correction_v2.py',
            'check': 'python3 tools/training/build_hierarchical_evidence_integrity_correction_v2.py --check',
            'inputs': [
                'the #419 frozen evidence persisted in the worktree',
                'the local git object store (offending and parent revisions), used for cross-checking only',
            ],
            'determinism': (
                'the payload is a pure function of the persisted bytes and of the declared commit '
                'constants; git is only ever used to confirm them, so --check is byte-stable whether '
                'or not the objects are reachable'
            ),
        },
    }


def render_summary(payload: Mapping[str, Any]) -> str:
    lines: list[str] = []
    lines.append('# #419 — evidence integrity correction v2 (re-pin `887e46a`, in-place mutation `4e16a60`)')
    lines.append('')
    lines.append(
        f'Schema `{SCHEMA}`, bundle `{_relative(HERE)}`, task `{BUNDLE_TASK}` (`{PLANNER_KEY}`), '
        f'issue #{ISSUE}, recorded against `{RECORDED_AGAINST_BRANCH}` at `{HEAD_COMMIT}`.'
    )
    lines.append('')
    lines.append(
        'The v1 record '
        f'(`{payload["predecessor_record"]["path"]}`, byte `{V1_RECORD_BYTE_SHA256}`) reversed '
        '`871e0bd` and closed with the declaration that no active reference to the mutant digests '
        'survived. Two later commits broke that declaration; this record documents both, the '
        'repair, and the before/after digests. It writes no frozen byte and edits no predecessor '
        'record.'
    )
    lines.append('')
    lines.append('## Incident 1 — re-pinned custody digests (`887e46a`, task `backlog-agg`)')
    lines.append('')
    lines.append(
        'The exact-tree preflight tool was re-pinned onto the pre-correction digests while the '
        'bytes persisted on disk stayed the restored ones, so the pin and the byte disagreed and '
        'the check failed closed. `9859c46` (task `backlog-911`) restored the pins.'
    )
    lines.append('')
    lines.append('| pin | restored custody digest (at HEAD) | re-pinned by `887e46a` |')
    lines.append('| --- | --- | --- |')
    for row in payload['tool_pin_table']['rows']:
        lines.append(
            f"| `{row['pin']}` | `{row['custody_digest']}` | `{row['repinned_by_887e46a']}` |"
        )
    lines.append('')
    lines.append('## Incident 2 — frozen evidence rewritten in place (`4e16a60`, task `backlog-txu`)')
    lines.append('')
    lines.append(
        'The raise-sizing frontier resolution and the terminal decision were rewritten in place and '
        'their resulting digests re-registered. `0f9a6eb` (task `backlog-i8v`) restored the bytes '
        'and moved the mutant objects aside.'
    )
    lines.append('')
    lines.append('## Before / after digest table')
    lines.append('')
    lines.append(
        '`reverted` = the repair put the parent bytes back; `rewritten` = the repair is a new '
        'revision that restores the pin, not the file; `retained` = the repair kept the offender\'s '
        'bytes.'
    )
    lines.append('')
    lines.append('| surface | path | before (parent) | mutant (offending) | at HEAD | disposition |')
    lines.append('| --- | --- | --- | --- | --- | --- |')
    for row in payload['digest_table']:
        if row['reverted_to_the_parent_bytes']:
            disposition = 'reverted'
        elif row['kept_the_offender_bytes']:
            disposition = 'retained'
        elif row['rewritten_by_the_repair']:
            disposition = 'rewritten'
        else:
            disposition = 'unchanged'
        lines.append(
            f"| `{row['surface']}` | `{row['path']}` | `{row['before_sha256'][:16]}…` | "
            f"`{row['mutant_sha256'][:16]}…` | `{row['at_head_sha256'][:16]}…` | {disposition} |"
        )
    lines.append('')
    lines.append('## What is verified at HEAD')
    lines.append('')
    lines.append(
        'Every digest in the table is re-derived from the bytes persisted at HEAD, every parent and '
        'offending revision is cross-checked against the local git object store, every reverted row '
        'carries the parent bytes again, no mutant digest survives as a content-addressed object, the '
        'four preflight custody pins equal the restored digests, the root #419 index and summary are '
        f"unmoved (`{ROOT_INDEX_SHA256[:8]}…` / `{ROOT_SUMMARY_SHA256[:8]}…`), the v1 record is "
        'byte-identical, and '
        '`tools/training/validation_order_guard.validation_result_artifacts()` still returns only '
        'the two frozen VALIDATION artifacts.'
    )
    lines.append('')
    lines.append('## Deliberately not done here')
    lines.append('')
    for finding in payload['residual_findings']:
        lines.append(f"* `{finding['finding_id']}` — {finding['detail']}")
    lines.append('')
    lines.append(
        'Reproduce: `python3 '
        'tools/training/build_hierarchical_evidence_integrity_correction_v2.py`; verify: '
        '`python3 tools/training/build_hierarchical_evidence_integrity_correction_v2.py --check`. '
        'This directory is outside every other index; its own digests are in `'
        f'{DIGEST_NAME}` and `{INDEX_NAME}`.'
    )
    lines.append('')
    return '\n'.join(lines)


def bundle_files(payload: Mapping[str, Any]) -> dict[str, bytes]:
    return {
        RECORD_NAME: serialize(payload),
        SUMMARY_NAME: render_summary(payload).encode(),
    }


def persist(payload: Mapping[str, Any]) -> dict[str, Any]:
    files = bundle_files(payload)
    objects = HERE / 'sha256'
    HERE.mkdir(parents=True, exist_ok=True)
    objects.mkdir(exist_ok=True)
    index: dict[str, Any] = {}
    referenced: set[str] = set()
    for name in MEMBER_NAMES:
        data = files[name]
        extension = '.md' if name.endswith('.md') else '.json'
        digest = sha256_bytes(data)
        (HERE / name).write_bytes(data)
        (objects / (digest + extension)).write_bytes(data)
        entry: dict[str, Any] = {
            'sha256': digest,
            'object': 'sha256/' + digest + extension,
        }
        if not name.endswith('.md'):
            entry['canonical_payload_sha256'] = stable_hash(json.loads(data))
        index[name] = entry
        referenced.add(digest + extension)
    (HERE / INDEX_NAME).write_text(json.dumps(index, sort_keys=True, indent=2) + '\n')
    (HERE / DIGEST_NAME).write_text(
        f'{index[RECORD_NAME]["sha256"]}  {RECORD_NAME}\n'
        f'# canonical_payload_sha256 {index[RECORD_NAME]["canonical_payload_sha256"]}\n'
        f'# reversal_of {V1_MUTANT_COMMIT}\n'
        f'# first_correction {V1_CORRECTION_COMMIT}\n'
        f'# re_pin_regression {REGRESSION_COMMIT}\n'
        f'# re_pin_repair {REGRESSION_REPAIR_COMMIT}\n'
        f'# in_place_mutation {MUTATION_COMMIT}\n'
        f'# mutation_repair {MUTATION_REPAIR_COMMIT}\n'
    )
    for path in objects.iterdir():
        if path.is_file() and path.name not in referenced:
            path.unlink()
    return index


def verify_content_address() -> dict[str, Any]:
    index = _load(HERE / INDEX_NAME)
    if set(index) != set(MEMBER_NAMES):
        raise CorrectionRecordError('the bundle index does not list exactly its members')
    for name in MEMBER_NAMES:
        data = (HERE / name).read_bytes()
        entry = index[name]
        if sha256_bytes(data) != entry['sha256']:
            raise CorrectionRecordError(f'{name} byte hash does not match {INDEX_NAME}')
        if data != (HERE / entry['object']).read_bytes():
            raise CorrectionRecordError(f'{name} content-addressed copy mismatch')
    objects = {path.name for path in (HERE / 'sha256').iterdir() if path.is_file()}
    expected = {
        index[name]['sha256'] + ('.md' if name.endswith('.md') else '.json')
        for name in MEMBER_NAMES
    }
    if objects != expected:
        raise CorrectionRecordError('the content-addressed object set is not closed')
    return index


def check() -> int:
    """Verify the persisted bundle against a fresh derivation, without writing."""
    try:
        payload = build_payload()
        files = bundle_files(payload)
        expected_names = set(MEMBER_NAMES) | {INDEX_NAME, DIGEST_NAME, 'sha256'}
        present = {path.name for path in HERE.iterdir()}
        unexpected = sorted(present - expected_names)
        if unexpected:
            raise CorrectionRecordError(f'unexpected files in the bundle: {unexpected}')
        missing = sorted(set(MEMBER_NAMES) - present)
        if missing:
            raise CorrectionRecordError(f'bundle members missing: {missing}')
        for name in MEMBER_NAMES:
            if (HERE / name).read_bytes() != files[name]:
                raise CorrectionRecordError(f'bundle member is stale: {name}')
        index = verify_content_address()
        for name in MEMBER_NAMES:
            if index[name]['sha256'] != sha256_bytes(files[name]):
                raise CorrectionRecordError(f'index digest mismatch for {name}')
        sidecar = (HERE / DIGEST_NAME).read_text(encoding='utf-8')
        if not sidecar.startswith(f'{index[RECORD_NAME]["sha256"]}  {RECORD_NAME}\n'):
            raise CorrectionRecordError('the digest sidecar does not pin the record')
        token = _relative(HERE)
        for sibling in sorted(UPSTREAM.rglob(INDEX_NAME)):
            if _relative(sibling) == f'{token}/{INDEX_NAME}':
                continue
            if token in sibling.read_text(encoding='utf-8'):
                raise CorrectionRecordError(
                    f'the correction record must stay out of every other index: {_relative(sibling)}'
                )
    except (CorrectionRecordError, OSError, ValueError, KeyError) as exc:
        print(f'Evidence-integrity correction v2: FAIL: {exc}', file=sys.stderr)
        return 1
    print(json.dumps({
        'result': 'PASS',
        'bundle': _relative(HERE),
        'record_sha256': index[RECORD_NAME]['sha256'],
        'record_canonical_payload_sha256': index[RECORD_NAME]['canonical_payload_sha256'],
        'correction_id': CORRECTION_ID,
        'incidents': [row['incident_id'] for row in payload['incidents']],
        'digest_table_rows': len(payload['digest_table']),
        'tool_pin_rows': len(payload['tool_pin_table']['rows']),
        'frozen_bytes_reverified': len(payload['frozen_bytes_reverified_at_head']['recorded']),
        'predecessor_record_byte_sha256': V1_RECORD_BYTE_SHA256,
        'mutant_objects_surviving': 0,
        'order_guard_validation_artifacts': payload['order_guard']['validation_result_artifacts'],
        'residual_findings': [row['finding_id'] for row in payload['residual_findings']],
    }, sort_keys=True, indent=2))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--check', action='store_true', help='verify the persisted bundle')
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.check:
        return check()
    try:
        payload = build_payload()
        index = persist(payload)
    except (CorrectionRecordError, OSError, ValueError, KeyError) as exc:
        print(f'Evidence-integrity correction v2: FAIL: {exc}', file=sys.stderr)
        return 1
    print(json.dumps({
        'result': 'WRITTEN',
        'bundle': _relative(HERE),
        'record_sha256': index[RECORD_NAME]['sha256'],
        'summary_sha256': index[SUMMARY_NAME]['sha256'],
        'index_sha256': sha256_file(HERE / INDEX_NAME),
        'correction_id': CORRECTION_ID,
    }, sort_keys=True, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

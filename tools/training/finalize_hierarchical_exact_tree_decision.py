#!/usr/bin/env python3
"""#419: terminal decision **v2** -- TRAIN-only preflight v2 + digest-pinned v1 VALIDATION.

This tool is the *only* place where #419 reaches a terminal verdict, and it now
reaches it as two distinct content-addressed revisions:

* the **v1** terminal decision (``analysis/issue419_hierarchical_tree/
  terminal_decision/DECISION.json``, byte SHA256
  ``9425f30163dcfa5e0a72ca8f6dd1bb4b6a25ce270b4a894aaa57e898a74bd0bc``) is a
  frozen, superseded surface.  It embedded ``source_files_sha256`` of the v1 tool
  itself, so a byte-identical re-derivation stopped being possible the moment
  this file was rewritten into the v2 revision: the v1 tool digest recorded in
  those bytes no longer exists on disk.  The v1 bytes are therefore **byte-pinned
  and re-verified on every build and every ``--check``**, never rewritten, and
  ``--revision v1`` is refused outright;
* the **v2** terminal decision (this tool's only output,
  ``analysis/issue419_hierarchical_tree/terminal_decision_v2/``) is composed of
  exactly two constituents:

  1. the **TRAIN-only** exact-tree preflight v2
     (``exact_tree_preflight_v2/EXACT_TREE_PREFLIGHT_V2.json``) -- the authority
     on ``required_tree_complete`` and on the admissibility of the 38 required
     nodes, itself TRAIN-only (``validation_consumed=false``,
     ``test_consumed=false``, ``hero_ev_executed=false``);
  2. the **already-consumed v1 VALIDATION result bytes**, referenced **by
     digest** (``validation/VALIDATION_RESULT.json``, byte SHA256
     ``0b92e5a78ab3ee4cb581c33be351d6b52bcf4fcd8741ab907ebd6dd32ec6ef68``,
     the digest the frozen protocol v2 custody table pins as
     ``holdout_boundary.validation_result_sha256`` and the digest the preflight
     v2 already attests its calibration gate from).

The v2 decision therefore opens **no holdout**: no hand history is parsed, no
VALIDATION decision row is read, no metric is recomputed and no threshold is
re-selected.  Every value the decision consumes from VALIDATION is a *published*
row of the digest-referenced artifact.  The tool proves that statically (AST
self-scan: no holdout loader symbol, no validation/holdout module) and at runtime
(a ``pathlib`` hand-history/dataset tripwire that fails the build if any such
file is opened), and records the proof in ``no_new_holdout_read``.

The terminal verdict is unchanged and never forced.  Admission still requires
``required_tree_complete=true`` from the preflight **v2**, no nearest-*/borrowed
substitution and a VALIDATION outcome of ``ADMIT_CANDIDATE`` with every frozen
gate passing; none of that holds, so the decision stays
``UNRESOLVED_HIERARCHICAL_TREE_GAP`` with precise blockers:

* ``NO_ADMISSIBLE_POOLING_LEVEL`` -- 31 of the 38 required nodes close on that
  unresolved reason (all 38 stay ``EXACT_UNRESOLVED``, 0 admissible);
* ``UNRESOLVED_RAISE_SIZING_FRONTIER`` -- the 7 raise-sizing frontiers stay
  unresolved and are explicitly ``independent_of_the_response_model=true``;
* ``REFUSED_CALIBRATION`` -- the frozen layer-B calibration gate, attested from
  the digest-referenced v1 VALIDATION bytes, refuses (pooled ECE 0.1352 > 0.05,
  0 of 40 reliability bins meet the minimum support) and the published
  ``calibration_absolute`` validation gate fails;
* ``REFUSED_COVERAGE_FLOOR`` -- the published VALIDATION coverage floor fails
  (9 identifiable decisions / 9 distinct hands against the frozen 200 / 100).

"Forcing" an admission is impossible by construction: the decision code and the
blocker list are pure functions of the preflight v2, the digest-referenced v1
VALIDATION rows and the frozen raise-sizing resolution, and #367 is never run
(``hero_ev_executed=false``, ``issue367_run=false``, ``next_issue=367``).

Output bundle (``analysis/issue419_hierarchical_tree/terminal_decision_v2/``):

* ``DECISION_V2.json`` -- terminal decision v2, blockers, evidence bindings
* ``SUMMARY.md`` -- human-readable terminal summary
* ``N8N_TASK_RESULT.txt`` -- the exact n8n output block
* ``ARTIFACTS.json`` -- content-addressed index (its own three generated files
  plus every bound upstream artifact, each by byte and canonical payload digest)

Every upstream bundle is a frozen input.  The root ``ARTIFACTS.json``/
``SUMMARY.md``, the T2 spec, the T6 protocol, the T1 sparsity baseline, the
active Model A reference and both v1 bundles (terminal decision, preflight) are
re-verified byte-for-byte before and after the build and are never rewritten.
No VALIDATION/TEST hand is parsed, no threshold is relaxed, and no active
registry, model pointer, reference model or frozen protocol byte is mutated.
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import hashlib
import json
import pathlib
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.datasets.build_hand_history_increment import sha256_file  # noqa: E402
from tools.preflop import model_a_sizing_hierarchical as H  # noqa: E402
from tools.simulation import issue419_exact_tree_preflight as preflight_tool  # noqa: E402
from tools.training import audit_hierarchical_tree_sparsity as baseline_tool  # noqa: E402
from tools.training import audit_model_a_exact_tree as legacy  # noqa: E402
from tools.training import fit_model_a_preflop_sizing_hierarchical as fit_tool  # noqa: E402
from tools.training import resolve_raise_sizing_frontiers as frontier_tool  # noqa: E402
from tools.training import write_hierarchical_model_spec as spec_tool  # noqa: E402
from tools.training.audit_preflop_sizing_support import stable_hash  # noqa: E402

HERE = ROOT / 'analysis/issue419_hierarchical_tree'

# ---------------------------------------------------------------------------
# The frozen v1 terminal-decision bundle.  These names are shared with the #419
# tests and the frozen protocol custody table, so they keep naming the v1 bytes:
# they are re-verified, never rewritten, by this v2 tool.
# ---------------------------------------------------------------------------
BUNDLE = HERE / 'terminal_decision'
SCHEMA = 'poker-hierarchical-exact-tree-terminal-decision/v1'
DECISION_NAME = 'DECISION.json'
SUMMARY_NAME = 'SUMMARY.md'
INDEX_NAME = 'ARTIFACTS.json'
N8N_NAME = 'N8N_TASK_RESULT.txt'
DIGEST_NAME = 'DECISION.sha256'
DIGEST_PATH = BUNDLE / DIGEST_NAME
DECISION_RECORD = ROOT / '.project/decisions/20260925-hierarchical-exact-tree-terminal-decision.md'

# Pinned bytes of the frozen v1 decision bundle: the superseded revision is
# immutable evidence and must hash back to these digests on every run.
V1_DECISION_SHA256 = '9425f30163dcfa5e0a72ca8f6dd1bb4b6a25ce270b4a894aaa57e898a74bd0bc'
V1_DECISION_CANONICAL_SHA256 = (
    '9b6aec99feeeb9c49424172f31a2d4657d8cf67cab2b80d2bbf66ecd22c261f5'
)
V1_SUMMARY_SHA256 = 'bb9c1b6f15695bb94b287a940ffd0e542ba575c586725fcea4dad4ecc235ed8f'
V1_INDEX_SHA256 = '08530e37f8ecf232fc032612021f74459e6af771f15fc4097748c0d73f86b7e4'
V1_N8N_SHA256 = '4fd1ab14ef254dd2ac250f5ab0ead1c54c5d0fe2e289921e326954d0c1d28333'
V1_DECISION_RECORD_SHA256 = (
    '25373ffa4a96d21837d5185e827a158a82455650dcdb213054e6299f439426ec'
)

# Explicit supersession declaration.  ``DECISION.json`` records
# ``source_files_sha256`` of the tool that produced it, so its byte-identical
# regeneration stopped being possible the moment that tool became this v2
# revision: the recorded v1 tool digest below no longer exists anywhere on disk.
# v1 is therefore kept strictly byte-identical and only ever re-verified against
# the digests recorded here; it is never rewritten and never re-derived.  The v2
# bundle in ``terminal_decision_v2/`` supersedes it and is the only revision this
# tool writes.
V1_SUPERSESSION = {
    'declaration': (
        'SUPERSEDED_BY_V2_BYTE_PINNED_NOT_REGENERATED: the v1 terminal decision is frozen, '
        'superseded evidence. Its source_files_sha256 records the superseded v1 tool, which no '
        'longer exists on disk, so a byte-identical re-derivation is impossible by construction; '
        'the bundle is byte-pinned to the digests recorded for it instead and is never rewritten.'
    ),
    'superseded_revision': 'v1',
    'superseding_revision': 'v2',
    'superseding_bundle': 'analysis/issue419_hierarchical_tree/terminal_decision_v2',
    'regeneration_possible': False,
    'regeneration_reason': (
        'the v1 DECISION.json embeds source_files_sha256 of the superseded v1 tool, so replaying '
        'the v1 revision cannot reproduce these bytes'
    ),
    'v1_records_decision_tool_sha256': (
        'e5ac5f429b1627c2356097b3d4841c5f9009694503bba00c2d2e6a511c021402'
    ),
}

# ---------------------------------------------------------------------------
# The v2 bundle this tool produces.
# ---------------------------------------------------------------------------
V2_BUNDLE = HERE / 'terminal_decision_v2'
V2_SCHEMA = 'poker-hierarchical-exact-tree-terminal-decision/v2'
V2_NAME = 'DECISION_V2.json'
V2_SUMMARY_NAME = 'SUMMARY.md'
V2_INDEX_NAME = 'ARTIFACTS.json'
V2_N8N_NAME = 'N8N_TASK_RESULT.txt'
V2_DIGEST_NAME = 'DECISION_V2.sha256'
V2_DIGEST_PATH = V2_BUNDLE / V2_DIGEST_NAME
V2_DECISION_RECORD = (
    ROOT / '.project/decisions/20260926-hierarchical-exact-tree-terminal-decision-v2.md'
)

ISSUE = 419
PARENT_ISSUE = 314
SCENARIO_ISSUE = 321
SOURCE_ISSUE = 388
NEXT_ISSUE = 367

DECISION_ADMIT = 'ADMIT_HIERARCHICAL_EXACT_TREE_CANDIDATE'
DECISION_UNRESOLVED = 'UNRESOLVED_HIERARCHICAL_TREE_GAP'
STATUS_READY = 'READY_FOR_INTEGRATION'
STATUS_BLOCKED = 'BLOCKED_SCIENTIFIC'
STATUS_NEEDS_FIXES = 'NEEDS_FIXES'

# The v1 blocker code is kept exported: the #419 suites still assert the frozen
# v1 decision's blocker list against it.
BLOCK_REQUIRED_TREE_INCOMPLETE = 'REQUIRED_TREE_INCOMPLETE'
BLOCK_UNRESOLVED_RAISE_SIZING = 'UNRESOLVED_RAISE_SIZING_FRONTIER'
BLOCK_VALIDATION_GATES = 'VALIDATION_GATES_FAILED'
BLOCK_EVIDENCE_INTEGRITY = 'EVIDENCE_INTEGRITY'

# v2 blocker codes: one per unmet admission condition, named after the frozen
# reason code that produced it.
BLOCK_NO_ADMISSIBLE_POOLING_LEVEL = 'NO_ADMISSIBLE_POOLING_LEVEL'
BLOCK_REFUSED_CALIBRATION = 'REFUSED_CALIBRATION'
BLOCK_REFUSED_COVERAGE_FLOOR = 'REFUSED_COVERAGE_FLOOR'
BLOCK_REFUSED_VALIDATION_GATES = 'REFUSED_VALIDATION_GATES'

POOLING_LEVEL_REASON_CODE = 'NO_ADMISSIBLE_POOLING_LEVEL'
RAISE_SIZING_REASON_CODE = 'RAISE_SIZING_UNRESOLVED_NO_NEAREST_PRICE'
LAYER_B_CALIBRATION_GATE_ID = 'CALIBRATION'
CALIBRATION_ABSOLUTE_GATE_ID = 'calibration_absolute'
CALIBRATION_DELTA_VS_ACTIVE_GATE_ID = 'calibration_delta_vs_active'
COVERAGE_FLOOR_GATE_ID = 'coverage_floor'
CALIBRATION_EVIDENCE_SOURCE = (
    'FROZEN_V1_VALIDATION_RESULT_BYTES_REFERENCED_BY_DIGEST_NO_NEW_HOLDOUT_READ'
)

# ---------------------------------------------------------------------------
# Frozen upstream identities.  Every value is re-verified from the persisted
# bytes; none of these files may be rewritten by this tool.
# ---------------------------------------------------------------------------
ROOT_SUMMARY_SHA256 = '737d315c6fde5d4863830952ab5bf396483bbefc47f3a4cdfcc7fe12508616e8'
ROOT_ARTIFACTS_SHA256 = '1650cdd96adb70a47e7711eb44820bc46a9afc46f290b9023c60d101d903d768'
SPEC_BYTE_SHA256 = '5be122e54e9ee07313a7efa0e0a6dbf4e195eceacf78287a9ac5a448964d105c'
BASELINE_BYTE_SHA256 = 'ef3995daaf5bc48a09f0785d574f7494754ad3904b87ecd2aa089b5be1b24a36'
PROTOCOL_V1_BYTE_SHA256 = preflight_tool.PROTOCOL_BYTE_SHA256
REFERENCE_BYTE_SHA256 = 'ff952055ca4ee051a3ac9607d513fdecac0a320a31f658ecfd8a11d8448975ca'
ISSUE352_CANDIDATE_SHA256 = '9115165c3141d16152946dd1ee7a049f219fef1a1d79c0e1c7b1249c45326f19'

# The TRAIN-only exact-tree preflight v2: the authority on required_tree_complete.
PREFLIGHT_V2_OUTPUT = preflight_tool.V2_OUTPUT
PREFLIGHT_V2_PATH = PREFLIGHT_V2_OUTPUT / preflight_tool.V2_NAME
PREFLIGHT_V2_SCHEMA = preflight_tool.V2_SCHEMA
PREFLIGHT_V2_BYTE_SHA256 = (
    '9b924077b286ef8c7c57e8a6e757cfb22a9784d2b44e8b328b11a55ba27abfc2'
)
PREFLIGHT_V2_CANONICAL_SHA256 = (
    'd88d1dba290f9a86033db7a875f8013b813472c24390c8a2736a09b7670b3a5b'
)

# The frozen v1 raise-sizing frontier bundle: superseded evidence, pinned and
# re-verified byte-for-byte, never a write target.  The blocker semantics this
# v2 decision consumes live in the v2 bundle (``raise_sizing_frontiers_v2``),
# which is the only frontier revision this tool binds for values; the v1 bytes
# are carried as custody so a silent in-place regeneration cannot go unnoticed.
V1_FRONTIER_RESOLUTION_SHA256 = (
    '93e7e3ede0a69e6b3e35f40217bd53ff95d1fbbb847ca3fbc9181c0689d0152e'
)
V1_FRONTIER_SUMMARY_SHA256 = (
    'cf092d67b1b09d604f1de14b6c9335de32e4bbbf30410d0b7d758ac40ccc850c'
)
V1_FRONTIER_INDEX_SHA256 = (
    '86ab23239979b9ee5a0e5cf4111cc7bc9525b417b567fb324699594fbc2ba3cf'
)
V1_FRONTIER_SCHEMA = frontier_tool.V1_SCHEMA

# The already-consumed v1 VALIDATION result, referenced by digest only.  The
# digest below is the one the frozen protocol v2 custody table pins as
# ``holdout_boundary.validation_result_sha256``.
V1_VALIDATION_RESULT_PATH = HERE / 'validation' / 'VALIDATION_RESULT.json'
V1_VALIDATION_RESULT_NAME = 'VALIDATION_RESULT.json'
V1_VALIDATION_RESULT_SHA256 = (
    '0b92e5a78ab3ee4cb581c33be351d6b52bcf4fcd8741ab907ebd6dd32ec6ef68'
)
V1_VALIDATION_RESULT_CANONICAL_SHA256 = (
    'b05012719388ec803481adaebe281e70982654f55153a81679f51555e9124ba6'
)
V1_VALIDATION_RESULT_SCHEMA = 'poker-hierarchical-validation-result/v1'
VALIDATION_SPLIT = 'VALIDATION'
VALIDATION_REFERENCE_POINTERS = (
    '/outcome',
    '/gate/failing_gates',
    f'/gate/gates[{COVERAGE_FLOOR_GATE_ID}]',
    f'/gate/gates[{CALIBRATION_ABSOLUTE_GATE_ID}]',
    f'/gate/gates[{CALIBRATION_DELTA_VS_ACTIVE_GATE_ID}]',
    '/coverage',
)

PROTOCOL_V2_PATH = HERE / 'validation_protocol_v2' / 'FROZEN_VALIDATION_PROTOCOL_V2.json'
PROTOCOL_V2_BUNDLE = HERE / 'validation_protocol_v2'
PROTOCOL_V2_NAME = 'FROZEN_VALIDATION_PROTOCOL_V2.json'
PROTOCOL_V1_PATH = HERE / 'FROZEN_VALIDATION_PROTOCOL.json'
PROTOCOL_V1_NAME = 'FROZEN_VALIDATION_PROTOCOL.json'
PROTOCOL_V1_DIGEST_PATH = HERE / 'FROZEN_VALIDATION_PROTOCOL.sha256'
PROTOCOL_V1_BUNDLE = HERE / 'validation_protocol'

ARTIFACT_SOURCES: tuple[tuple[str, Path, Path], ...] = (
    # the two v2 constituents: the TRAIN-only preflight v2 and the digest-
    # referenced v1 VALIDATION result bytes
    (preflight_tool.V2_NAME, PREFLIGHT_V2_PATH, PREFLIGHT_V2_OUTPUT),
    (V1_VALIDATION_RESULT_NAME, V1_VALIDATION_RESULT_PATH, V1_VALIDATION_RESULT_PATH.parent),
    # the frozen v1 decision bytes: pinned, never rewritten
    (DECISION_NAME, BUNDLE / DECISION_NAME, BUNDLE),
    # frozen upstream identities the v2 decision binds
    (spec_tool.SPEC_NAME, spec_tool.SPEC_PATH, spec_tool.BUNDLE),
    (fit_tool.REPORT_NAME, fit_tool.OUTPUT / fit_tool.REPORT_NAME, fit_tool.OUTPUT),
    (fit_tool.MANIFEST_NAME, fit_tool.OUTPUT / fit_tool.MANIFEST_NAME, fit_tool.OUTPUT),
    (PROTOCOL_V1_NAME, PROTOCOL_V1_PATH, PROTOCOL_V1_BUNDLE),
    (baseline_tool.BASELINE_NAME, HERE / baseline_tool.BASELINE_NAME, HERE),
    (frontier_tool.ARTIFACT_NAME, frontier_tool.OUTPUT / frontier_tool.ARTIFACT_NAME,
     frontier_tool.OUTPUT),
    # lineage: the superseded v1 exact-tree preflight is bound but never trusted
    (preflight_tool.NAME, preflight_tool.OUTPUT / preflight_tool.NAME, preflight_tool.OUTPUT),
)
REQUIRED_NAMES = tuple(name for name, _s, _o in ARTIFACT_SOURCES) + (
    V2_NAME,
    V2_SUMMARY_NAME,
)

# The #367 real ISO EV runner must never be imported or executed by this tool.
ISSUE367_RUNNER_SYMBOLS = (
    'run_issue367_real_iso_ev',
    'issue367_real_iso_ev',
    'hero_ev',
    'hero_recommendation',
)

# A holdout loader is any symbol that would parse a VALIDATION/TEST hand, read a
# validation decision row, or open a hand-history/dataset archive.  The v2
# decision consumes none of them: the only holdout-adjacent file it opens is the
# *published* VALIDATION result artifact, which it references by digest.
HOLDOUT_LOADER_SYMBOLS = (
    'load_validation_records',
    'validation_records',
    'validation_hand_ids',
    'VALIDATION_HANDS',
    'validation_decision_rows',
    'build_validation_decisions',
    'load_validation_decisions',
    'load_holdout',
    'holdout_records',
    'load_test_records',
    'TEST_HANDS',
    'test_hand_ids',
    'test_decisions_read',
)
HOLDOUT_FORBIDDEN_MODULE_PREFIXES = (
    'tools.training.validate_hierarchical_validation',
    'tools.training.validate_full_hand_protocol',
    'tools.training.select_preflop_strategy_validation',
    'tools.training.validate_hero_pfpc_evidence',
)

DATASET_ROOT = ROOT / 'training' / 'datasets'
HAND_HISTORY_SUFFIXES = frozenset({'jsonl', 'zip', 'snapshots'})

PROTECTED_PATHS: tuple[Path, ...] = (
    ROOT / 'training/registry.json',
    ROOT / 'training/populations/registry.json',
    ROOT / 'training/models/preflop_population_model_v5.json',
    HERE / INDEX_NAME,
    HERE / SUMMARY_NAME,
    HERE / baseline_tool.BASELINE_NAME,
    spec_tool.SPEC_PATH,
    spec_tool.DIGEST_PATH,
    PROTOCOL_V1_PATH,
    PROTOCOL_V1_DIGEST_PATH,
    PROTOCOL_V2_PATH,
    fit_tool.OUTPUT / fit_tool.CANDIDATE_NAME,
    fit_tool.OUTPUT / fit_tool.REPORT_NAME,
    fit_tool.OUTPUT / fit_tool.MANIFEST_NAME,
    V1_VALIDATION_RESULT_PATH,
    PREFLIGHT_V2_PATH,
    preflight_tool.OUTPUT / preflight_tool.NAME,
    # the v2 frontier bundle (the values source) and the frozen v1 frontier
    # bytes (custody only: pinned, re-verified, never rewritten)
    frontier_tool.OUTPUT / frontier_tool.ARTIFACT_NAME,
    frontier_tool.OUTPUT / 'SUMMARY.md',
    frontier_tool.OUTPUT / 'ARTIFACTS.json',
    frontier_tool.V1_OUTPUT / frontier_tool.V1_ARTIFACT_NAME,
    frontier_tool.V1_OUTPUT / 'SUMMARY.md',
    frontier_tool.V1_OUTPUT / 'ARTIFACTS.json',
    legacy.REFERENCE,
    BUNDLE / DECISION_NAME,
    BUNDLE / SUMMARY_NAME,
    BUNDLE / INDEX_NAME,
    BUNDLE / N8N_NAME,
    DIGEST_PATH,
    DECISION_RECORD,
)

SOURCE_PATH = Path(__file__).resolve()


class TerminalDecisionError(RuntimeError):
    """Raised when the consolidated evidence is inconsistent or inadmissible."""


def serialize(payload: Any) -> bytes:
    return (json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def _load(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _relative(path: Path | str) -> str:
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def _is_hand_history_path(raw: str | Path) -> bool:
    path = Path(raw)
    if path.suffix.lstrip('.').lower() in HAND_HISTORY_SUFFIXES:
        return True
    try:
        return path.resolve().is_relative_to(DATASET_ROOT)
    except (OSError, ValueError):  # pragma: no cover - defensive
        return False


@contextlib.contextmanager
def hand_history_tripwire():
    """Fail the build if a hand-history archive, JSONL or dataset file is opened."""
    opened: list[str] = []
    original_open = pathlib.Path.open

    def guarded_open(self, *args, **kwargs):
        if _is_hand_history_path(str(self)):
            raise TerminalDecisionError(f'hand-history/dataset file opened by the decision: {self}')
        opened.append(_relative(self))
        return original_open(self, *args, **kwargs)

    pathlib.Path.open = guarded_open
    try:
        yield opened
    finally:
        pathlib.Path.open = original_open


def verify_content_address(bundle: Path, index_name: str = INDEX_NAME) -> dict[str, Any]:
    """Verify a persisted content-addressed bundle before trusting any byte."""
    index = _load(bundle / index_name)
    for name, entry in index.items():
        data = (bundle / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise TerminalDecisionError(f'content-addressed byte hash mismatch: {bundle.name}/{name}')
        if data != (bundle / entry['object']).read_bytes():
            raise TerminalDecisionError(f'content-addressed copy mismatch: {bundle.name}/{name}')
    return index


def verify_no_holdout_access(source: str | None = None) -> dict[str, Any]:
    """Static proof that this command reads no holdout and no hand history."""
    text = SOURCE_PATH.read_text(encoding='utf-8') if source is None else source
    module = ast.parse(text)
    used: set[str] = set()
    imported: list[str] = []
    for node in ast.walk(module):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            used.add(node.attr)
        elif isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
            used.update(alias.name.split('.')[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or '')
            imported.extend(alias.name for alias in node.names)
            used.update(alias.name for alias in node.names)
    hits = sorted(used & set(HOLDOUT_LOADER_SYMBOLS))
    if hits:
        raise TerminalDecisionError(f'holdout loader symbol used by the decision: {hits}')
    bad_imports = sorted(
        name for name in imported
        if any(name == prefix or name.startswith(prefix + '.')
               for prefix in HOLDOUT_FORBIDDEN_MODULE_PREFIXES)
    )
    if bad_imports:
        raise TerminalDecisionError(f'holdout loader module imported by the decision: {bad_imports}')
    return {
        'check': 'self_source_scan_for_holdout_loaders',
        'result': 'PASS',
        'forbidden_symbols': list(HOLDOUT_LOADER_SYMBOLS),
        'forbidden_module_prefixes': list(HOLDOUT_FORBIDDEN_MODULE_PREFIXES),
        'hits': [],
        'holdout_looking_imports': [],
        'detail': (
            'AST scan: the v2 decision consumes no VALIDATION/TEST loader, imports no '
            'validation/holdout module and parses no hand history; the only holdout-adjacent '
            'file it opens is the published VALIDATION result artifact, referenced by digest'
        ),
    }


def verify_no_issue367_runner(source: str | None = None) -> dict[str, Any]:
    """AST tripwire: the decision tool never imports or executes the #367 Hero EV runner."""
    text = SOURCE_PATH.read_text() if source is None else source
    module = ast.parse(text)
    used: set[str] = set()
    imported: list[str] = []
    for node in ast.walk(module):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            used.add(node.attr)
        elif isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or '')
            imported.extend(alias.name for alias in node.names)
    names = {name.rsplit('.', 1)[-1] for name in imported} | used
    hits = sorted(name for name in names if name in ISSUE367_RUNNER_SYMBOLS)
    if hits:
        raise TerminalDecisionError(f'#367 Hero EV symbols referenced by the decision tool: {hits}')
    bad_imports = sorted(name for name in imported if 'issue367' in name.lower())
    if bad_imports:
        raise TerminalDecisionError(f'#367 runner imported by the decision tool: {bad_imports}')
    return {
        'check': 'self_source_scan_for_issue367_runner',
        'result': 'PASS',
        'forbidden_symbols': list(ISSUE367_RUNNER_SYMBOLS),
        'hits': [],
        'detail': 'AST scan: the #367 real ISO EV runner is neither imported nor executed here',
    }


def verify_frozen_v1_decision() -> dict[str, Any]:
    """Re-derive the frozen v1 decision digests; the v1 bundle is never rewritten."""
    expected = {
        DECISION_NAME: V1_DECISION_SHA256,
        SUMMARY_NAME: V1_SUMMARY_SHA256,
        INDEX_NAME: V1_INDEX_SHA256,
        N8N_NAME: V1_N8N_SHA256,
    }
    digests: dict[str, str] = {}
    for name, pinned in expected.items():
        path = BUNDLE / name
        if not path.is_file():
            raise TerminalDecisionError(f'the frozen v1 decision artifact is missing: {path}')
        actual = sha256_file(path)
        if actual != pinned:
            raise TerminalDecisionError(
                f'the frozen v1 decision artifact drifted: {name} {actual} != {pinned}'
            )
        digests[name] = actual
    sidecar = DIGEST_PATH.read_text(encoding='utf-8')
    expected_sidecar = (
        f'{V1_DECISION_SHA256}  {DECISION_NAME}\n'
        f'# canonical_payload_sha256 {V1_DECISION_CANONICAL_SHA256}\n'
    )
    if sidecar != expected_sidecar:
        raise TerminalDecisionError('the frozen v1 decision digest sidecar drifted')
    digests[DIGEST_NAME] = sha256_file(DIGEST_PATH)
    if not DECISION_RECORD.is_file():
        raise TerminalDecisionError('the frozen v1 decision record is missing')
    record_sha = sha256_file(DECISION_RECORD)
    if record_sha != V1_DECISION_RECORD_SHA256:
        raise TerminalDecisionError('the frozen v1 decision record drifted')
    digests['.project/decisions/20260925-hierarchical-exact-tree-terminal-decision.md'] = record_sha

    v1_payload = _load(BUNDLE / DECISION_NAME)
    if v1_payload.get('schema') != SCHEMA:
        raise TerminalDecisionError('the frozen v1 decision schema drifted')
    if stable_hash(v1_payload) != V1_DECISION_CANONICAL_SHA256:
        raise TerminalDecisionError('the frozen v1 decision canonical payload drifted')
    recorded_tool = str(
        v1_payload['source_files_sha256'][
            'tools/training/finalize_hierarchical_exact_tree_decision.py'
        ]
    )
    if recorded_tool != V1_SUPERSESSION['v1_records_decision_tool_sha256']:
        raise TerminalDecisionError(
            'the v1 supersession declaration drifted from the frozen v1 tool digest: '
            f"{recorded_tool} != {V1_SUPERSESSION['v1_records_decision_tool_sha256']}"
        )
    live_tool = sha256_file(SOURCE_PATH)
    regeneration_possible = bool(recorded_tool == live_tool)
    if regeneration_possible is not V1_SUPERSESSION['regeneration_possible']:
        raise TerminalDecisionError(
            'the v1 supersession declaration is stale: the frozen v1 bundle could now be '
            're-derived byte-identically and must be re-examined'
        )
    return {
        'check': 'frozen_v1_decision_bytes_re_derived',
        'result': 'PASS',
        'bundle': _relative(BUNDLE),
        'artifacts': digests,
        'never_rewritten': True,
        'revision': 'v1',
        'superseded_by': str(V2_BUNDLE.relative_to(ROOT)) + '/' + V2_NAME,
        'supersession': dict(V1_SUPERSESSION),
        'v1_code_bindings': {
            'recorded_decision_tool_sha256': recorded_tool,
            'live_decision_tool_sha256': live_tool,
            'decision_tool_unchanged_since_v1': recorded_tool == live_tool,
        },
        'canonical_payload_sha256': str(
            _load(BUNDLE / INDEX_NAME)[DECISION_NAME]['canonical_payload_sha256']
        ),
        'reason': (
            'the v1 terminal decision is pinned as an immutable v1 surface by the frozen v1 '
            'protocol custody table and by the #419 suites; this tool re-verifies those bytes and '
            'writes only the v2 bundle'
        ),
    }


def load_frozen_v2_preflight() -> dict[str, Any]:
    """Verify and load the TRAIN-only exact-tree preflight v2."""
    index = verify_content_address(PREFLIGHT_V2_OUTPUT)
    payload_bytes = PREFLIGHT_V2_PATH.read_bytes()
    actual = hashlib.sha256(payload_bytes).hexdigest()
    if actual != PREFLIGHT_V2_BYTE_SHA256:
        raise TerminalDecisionError(f'the frozen preflight v2 bytes moved: {actual}')
    if index[preflight_tool.V2_NAME]['sha256'] != PREFLIGHT_V2_BYTE_SHA256:
        raise TerminalDecisionError('the preflight v2 index disagrees with the pinned bytes')
    preflight = json.loads(payload_bytes)
    if preflight.get('schema') != PREFLIGHT_V2_SCHEMA:
        raise TerminalDecisionError('unexpected preflight v2 schema')
    if stable_hash(preflight) != PREFLIGHT_V2_CANONICAL_SHA256:
        raise TerminalDecisionError('the frozen preflight v2 canonical payload hash drifted')
    boundary = preflight['boundary']
    if boundary['split_consumed'] != 'TRAIN':
        raise TerminalDecisionError('the preflight v2 must stay TRAIN-only')
    if boundary['validation_consumed'] is not False:
        raise TerminalDecisionError('the preflight v2 must not consume VALIDATION')
    if boundary['test_consumed'] is not False:
        raise TerminalDecisionError('the preflight v2 must not consume TEST')
    if boundary['test_authorized'] is not False:
        raise TerminalDecisionError('the preflight v2 must not authorize TEST')
    if boundary['hero_ev_executed'] is not False:
        raise TerminalDecisionError('the preflight v2 must not execute Hero EV')
    if boundary['active_model_pointer_mutated'] is not False:
        raise TerminalDecisionError('the preflight v2 must not mutate the active pointer')
    if boundary['hand_histories_parsed'] != 0:
        raise TerminalDecisionError('the preflight v2 must not parse hand histories')
    if boundary['holdout_access_scan']['result'] != 'PASS':
        raise TerminalDecisionError('the preflight v2 holdout scan must pass')
    audit = preflight['nearest_substitution_audit']
    if audit['substitutions_applied'] != 0:
        raise TerminalDecisionError('a nearest-* substitution was applied: admission is impossible')
    if audit['support_source_equals_requested_key_for_every_node'] is not True:
        raise TerminalDecisionError('the preflight v2 must keep support == requested key')
    if preflight['provider']['candidate_canonical_payload_sha256'] != (
        preflight_tool.CANDIDATE_CANONICAL_SHA256
    ):
        raise TerminalDecisionError('the preflight v2 candidate digest drifted')
    if preflight['required_tree']['required_tree_sha256'] != (
        baseline_tool.ISSUE388_REQUIRED_TREE_SHA256
    ):
        raise TerminalDecisionError('the preflight v2 required-tree digest drifted')
    if preflight['evidence_bindings']['protocol_byte_sha256'] != PROTOCOL_V1_BYTE_SHA256:
        raise TerminalDecisionError('the preflight v2 protocol byte digest mismatch')
    return {
        'index': index,
        'byte_sha256': actual,
        'canonical_payload_sha256': PREFLIGHT_V2_CANONICAL_SHA256,
        # The preflight v2 records the protocol v2 digest it was built against.
        # It is carried verbatim as the preflight's own at-freeze binding; the
        # authority for the protocol-v2 custody chain used below is the frozen
        # protocol v2 bundle itself (``load_frozen_protocol_v2_custody``).
        'records_protocol_v2_byte_sha256': str(
            preflight['evidence_bindings']['protocol_v2_byte_sha256']
        ),
        'preflight': preflight,
    }


def load_frozen_protocol_v2_custody() -> dict[str, Any]:
    """Verify the frozen protocol v2 and its custody pin of the consumed VALIDATION bytes."""
    payload_bytes = PROTOCOL_V2_PATH.read_bytes()
    actual = hashlib.sha256(payload_bytes).hexdigest()
    index = _load(PROTOCOL_V2_BUNDLE / 'ARTIFACTS.json')
    entry = index[PROTOCOL_V2_NAME]
    if str(entry['sha256']) != actual:
        raise TerminalDecisionError('the protocol v2 content-addressed index disagrees with its bytes')
    if (PROTOCOL_V2_BUNDLE / str(entry['object'])).read_bytes() != payload_bytes:
        raise TerminalDecisionError('the protocol v2 content-addressed object disagrees with its bytes')
    protocol = json.loads(payload_bytes)
    if protocol['v1_provenance']['byte_sha256'] != PROTOCOL_V1_BYTE_SHA256:
        raise TerminalDecisionError('the frozen protocol v2 does not reference the frozen v1 bytes')
    holdout = protocol['holdout_boundary']
    if holdout['validation_result_sha256'] != V1_VALIDATION_RESULT_SHA256:
        raise TerminalDecisionError(
            'the frozen protocol v2 does not pin the consumed v1 VALIDATION result digest'
        )
    if protocol['v1_custody']['validation_history_sha256'] != V1_VALIDATION_RESULT_SHA256:
        raise TerminalDecisionError(
            'the frozen protocol v2 custody table does not pin the consumed VALIDATION history'
        )
    if holdout['validation_consumed_by_this_revision'] is not False:
        raise TerminalDecisionError('the frozen protocol v2 revision must not consume VALIDATION')
    if holdout['holdout_reopened_by_this_revision'] is not False:
        raise TerminalDecisionError('the frozen protocol v2 revision must not re-open the holdout')
    if holdout['test_consumed'] is not False:
        raise TerminalDecisionError('the frozen protocol v2 must leave TEST unconsumed')
    return {
        'byte_sha256': actual,
        'canonical_payload_sha256': str(entry['canonical_payload_sha256']),
        'validation_result_custody_pin': str(holdout['validation_result_sha256']),
        'validation_outcome': str(holdout['validation_outcome']),
        'protocol': protocol,
    }


def load_v1_validation_reference(
    preflight: Mapping[str, Any], custody: Mapping[str, Any]
) -> dict[str, Any]:
    """Re-derive the v1 VALIDATION digest and read only its *published* rows.

    Nothing about the holdout is re-opened here: the persisted bytes are the
    published, already-consumed VALIDATION result.  The digest is re-derived --
    never taken on trust -- and every value the decision consumes is a row of
    that artifact, cross-checked against the calibration attestation the frozen
    preflight v2 recorded from the very same digest.
    """
    payload_bytes = V1_VALIDATION_RESULT_PATH.read_bytes()
    actual = hashlib.sha256(payload_bytes).hexdigest()
    if actual != V1_VALIDATION_RESULT_SHA256:
        raise TerminalDecisionError(f'the consumed v1 VALIDATION result drifted: {actual}')
    if custody['validation_result_custody_pin'] != actual:
        raise TerminalDecisionError('the frozen protocol v2 custody pin disagrees with the bytes')
    payload = json.loads(payload_bytes)
    if stable_hash(payload) != V1_VALIDATION_RESULT_CANONICAL_SHA256:
        raise TerminalDecisionError('the consumed v1 VALIDATION canonical payload drifted')
    if payload.get('schema') != V1_VALIDATION_RESULT_SCHEMA:
        raise TerminalDecisionError('unexpected v1 VALIDATION result schema')
    if payload.get('split') != VALIDATION_SPLIT:
        raise TerminalDecisionError('the referenced artifact is not the VALIDATION split result')
    if payload.get('test_consumed') is not False:
        raise TerminalDecisionError('the referenced VALIDATION result must leave TEST unconsumed')
    if payload.get('hero_ev_consumed') is not False:
        raise TerminalDecisionError('the referenced VALIDATION result must leave Hero EV unconsumed')
    if payload.get('protocol_byte_sha256') != PROTOCOL_V1_BYTE_SHA256:
        raise TerminalDecisionError('the referenced VALIDATION result used another protocol')
    candidate = payload['candidate']
    provider = preflight['provider']
    for name, value in (
        ('candidate_id', provider['candidate_id']),
        ('canonical_payload_sha256', provider['candidate_canonical_payload_sha256']),
        ('byte_sha256', provider['candidate_byte_sha256']),
        ('candidate_instance_id', provider['candidate_instance_id']),
        ('identity_granularity', provider['identity_granularity']),
    ):
        if str(candidate[name]) != str(value):
            raise TerminalDecisionError(
                f'the referenced VALIDATION result is about another candidate: {name}'
            )

    gate = payload['gate']
    rows = {str(row['gate']): row for row in gate['gates']}
    failing = sorted(name for name, row in rows.items() if row.get('pass') is not True)
    if failing != sorted(str(name) for name in gate['failing_gates']):
        raise TerminalDecisionError('the published failing gates disagree with their own rows')
    if failing and gate.get('all_gates_pass') is not False:
        raise TerminalDecisionError('a published gate fails but all_gates_pass is not false')
    if not failing and gate.get('all_gates_pass') is not True:
        raise TerminalDecisionError('no published gate fails but all_gates_pass is not true')
    coverage_row = rows.get(COVERAGE_FLOOR_GATE_ID)
    calibration_row = rows.get(CALIBRATION_ABSOLUTE_GATE_ID)
    delta_row = rows.get(CALIBRATION_DELTA_VS_ACTIVE_GATE_ID)
    if not coverage_row or not calibration_row or not delta_row:
        raise TerminalDecisionError('the referenced VALIDATION result lost its frozen gate rows')

    # Cross-check the calibration rows against the attestation the frozen
    # preflight v2 recorded from the very same digest.  A drifting reference
    # artifact fails closed instead of silently passing.
    attestation = preflight['admissibility_protocol']['calibration_gate']['evidence']['attestation']
    if attestation['source_byte_sha256'] != actual:
        raise TerminalDecisionError('the preflight v2 calibration attestation names another digest')
    if attestation['protocol_v2_custody_pin'] != actual:
        raise TerminalDecisionError('the preflight v2 calibration custody pin disagrees')
    if attestation['source_artifact'] != _relative(V1_VALIDATION_RESULT_PATH):
        raise TerminalDecisionError('the preflight v2 calibration attestation names another file')
    measured = attestation['measured']
    if abs(float(measured['pooled_ece']) - float(calibration_row['measured']['ece'])) > 1e-12:
        raise TerminalDecisionError('the attested pooled ECE disagrees with the published row')
    if abs(
        float(measured['active_reference_ece'])
        - float(delta_row['measured']['active_ece'])
    ) > 1e-12:
        raise TerminalDecisionError('the attested active-reference ECE disagrees with its row')
    if int(measured['bins_meeting_minimum_support']) != int(
        calibration_row['measured']['bins_meeting_minimum_support']
    ):
        raise TerminalDecisionError('the attested calibration bin support disagrees with its row')
    if str(payload['outcome']) != custody['validation_outcome']:
        raise TerminalDecisionError('the referenced VALIDATION outcome disagrees with the custody')

    return {
        'path': _relative(V1_VALIDATION_RESULT_PATH),
        'byte_sha256': actual,
        'canonical_payload_sha256': V1_VALIDATION_RESULT_CANONICAL_SHA256,
        'schema': V1_VALIDATION_RESULT_SCHEMA,
        'split': VALIDATION_SPLIT,
        'source': CALIBRATION_EVIDENCE_SOURCE,
        'referenced_by_digest': True,
        'digest_re_derived_from_persisted_bytes': True,
        'protocol_v2_custody_pin': custody['validation_result_custody_pin'],
        'pointers_read': list(VALIDATION_REFERENCE_POINTERS),
        'holdout_reopened_by_this_decision': False,
        'validation_consumed_by_this_decision': False,
        'validation_split_re_evaluated': False,
        'validation_decision_rows_read': 0,
        'metrics_recomputed': 0,
        'thresholds_re_selected': False,
        'hand_histories_parsed': 0,
        'outcome': str(payload['outcome']),
        'reason': str(payload['reason']),
        'all_gates_pass': gate.get('all_gates_pass') is True,
        'failing_gates': failing,
        'gates': {
            name: {
                'pass': bool(row.get('pass')),
                'rule': row.get('rule'),
                'measured': dict(row.get('measured') or {}),
            }
            for name, row in rows.items()
        },
        'coverage': dict(payload['coverage']),
        'production_effect': payload['production_effect'],
        'test_consumed': False,
        'hero_ev_consumed': False,
    }


def verify_v1_raise_sizing_frontier() -> dict[str, Any]:
    """Re-derive the frozen v1 raise-sizing frontier digests; v1 is never rewritten."""
    expected = {
        frontier_tool.V1_ARTIFACT_NAME: V1_FRONTIER_RESOLUTION_SHA256,
        'SUMMARY.md': V1_FRONTIER_SUMMARY_SHA256,
        'ARTIFACTS.json': V1_FRONTIER_INDEX_SHA256,
    }
    digests: dict[str, str] = {}
    for name, pinned in expected.items():
        path = frontier_tool.V1_OUTPUT / name
        if not path.is_file():
            raise TerminalDecisionError(f'the frozen v1 raise-sizing artifact is missing: {path}')
        actual = sha256_file(path)
        if actual != pinned:
            raise TerminalDecisionError(
                f'the frozen v1 raise-sizing artifact drifted: {name} {actual} != {pinned}'
            )
        digests[name] = actual
    payload = _load(frontier_tool.V1_OUTPUT / frontier_tool.V1_ARTIFACT_NAME)
    if payload.get('schema') != V1_FRONTIER_SCHEMA:
        raise TerminalDecisionError('the frozen v1 raise-sizing schema drifted')
    if stable_hash(payload) != frontier_tool.V1_RESOLUTION_CANONICAL_SHA256:
        raise TerminalDecisionError('the frozen v1 raise-sizing canonical payload drifted')
    if 'blocker' in payload.get('frontiers', [{}])[0]:
        raise TerminalDecisionError(
            'the frozen v1 raise-sizing bundle must not carry the v2 blocker semantics'
        )
    return {
        'check': 'frozen_v1_raise_sizing_frontier_bytes_re_derived',
        'result': 'PASS',
        'bundle': _relative(frontier_tool.V1_OUTPUT),
        'schema': V1_FRONTIER_SCHEMA,
        'artifacts': digests,
        'canonical_payload_sha256': frontier_tool.V1_RESOLUTION_CANONICAL_SHA256,
        'never_rewritten': True,
        'superseded_by': (
            _relative(frontier_tool.OUTPUT) + '/' + frontier_tool.ARTIFACT_NAME
        ),
    }


def load_raise_sizing_frontiers(preflight: Mapping[str, Any]) -> dict[str, Any]:
    """Load the versioned **v2** TRAIN-only raise-sizing resolution; fail closed on drift."""
    path = frontier_tool.OUTPUT / frontier_tool.ARTIFACT_NAME
    frontier = _load(path)
    if frontier.get('schema') != frontier_tool.SCHEMA:
        raise TerminalDecisionError('the raise-sizing resolution is not the v2 revision')
    if frontier.get('revision') != 'v2':
        raise TerminalDecisionError('the raise-sizing resolution must declare revision v2')
    v1_custody = verify_v1_raise_sizing_frontier()
    if str(frontier['supersedes_v1']['artifacts'][frontier_tool.V1_ARTIFACT_NAME]) != (
        V1_FRONTIER_RESOLUTION_SHA256
    ):
        raise TerminalDecisionError('the v2 resolution records another v1 frontier custody')
    if frontier['unresolved_count'] != baseline_tool.ISSUE388_UNRESOLVED_FRONTIERS:
        raise TerminalDecisionError('raise-sizing frontier count mismatch')
    if frontier['blocker_persisted'] is not True:
        raise TerminalDecisionError('the unresolved raise-sizing frontier blocker must be persisted')
    if frontier['split_consumed'] != 'TRAIN' or frontier['validation_consumed'] is not False:
        raise TerminalDecisionError('the raise-sizing resolution must stay TRAIN-only')
    if frontier['unresolved_count'] != preflight['required_tree']['unresolved_sizing_frontier_count']:
        raise TerminalDecisionError('the raise-sizing count disagrees with the preflight v2')
    if frontier['unresolved_count'] != preflight['sizing_frontiers_queried']:
        raise TerminalDecisionError('the raise-sizing count disagrees with the walked frontiers')
    # The re-hosted v2 semantics: every frontier is an independent sizing blocker
    # with no admissible target and no substitution, and it forces the required
    # tree open.
    if frontier.get('blocker_reason_code') != RAISE_SIZING_REASON_CODE:
        raise TerminalDecisionError('the v2 frontier blocker reason code drifted')
    if frontier.get('independent_of_the_response_model') is not True:
        raise TerminalDecisionError('the v2 frontier must stay independent of the response model')
    effect = frontier.get('required_tree_complete_effect')
    if not isinstance(effect, Mapping):
        raise TerminalDecisionError('the v2 frontier lost its required_tree_complete effect')
    if effect.get('effect') != frontier_tool.REQUIRED_TREE_COMPLETE_EFFECT:
        raise TerminalDecisionError('the required_tree_complete effect drifted')
    if effect.get('blocker_reason_code') != RAISE_SIZING_REASON_CODE:
        raise TerminalDecisionError('the required_tree_complete effect names another blocker')
    if effect.get('independent_of_the_response_model') is not True:
        raise TerminalDecisionError('the required_tree_complete effect must stay model-independent')
    if effect.get('blocks_required_tree_complete') is not True:
        raise TerminalDecisionError('the unresolved frontier must block required_tree_complete')
    if effect.get('required_tree_complete') is not False:
        raise TerminalDecisionError('an unresolved frontier cannot leave the required tree complete')
    if frontier.get('required_tree_complete') is not False:
        raise TerminalDecisionError('the v2 frontier resolution must stay incomplete')
    if any(frontier['blockers'][0].get(flag) for flag in (
        'representative_price_substituted', 'nearest_price_substituted',
        'nearest_context_substituted', 'legal_minimum_fallback_substituted',
    )):
        raise TerminalDecisionError('a frontier replaced a price with a substitution')
    for item in frontier['frontiers']:
        blocker = item.get('blocker') or {}
        if blocker.get('reason_code') != RAISE_SIZING_REASON_CODE:
            raise TerminalDecisionError('a frontier is missing the v2 sizing blocker')
        if blocker.get('independent_of_the_response_model') is not True:
            raise TerminalDecisionError('a frontier blocker is response-model dependent')
        if blocker.get('exactly_supported_target_bb') is not None:
            raise TerminalDecisionError('a frontier blocker leaked an exact target')
        if blocker.get('admitted_target_bb') is not None:
            raise TerminalDecisionError('a frontier blocker leaked an admitted target')
        if any(blocker.get(flag) for flag in (
            'representative_price_substituted', 'nearest_price_substituted',
            'nearest_context_substituted', 'legal_minimum_fallback_substituted',
        )):
            raise TerminalDecisionError('a frontier blocker substituted a price')
    frontier = dict(frontier)
    frontier['_v1_custody'] = v1_custody
    frontier['_v2_byte_sha256'] = sha256_file(path)
    return frontier


def _deepcopy_json(value: Any) -> Any:
    return json.loads(json.dumps(value))


def tree_blocker(preflight: Mapping[str, Any], binding: Mapping[str, Any]) -> dict[str, Any]:
    admissibility = preflight['admissibility']
    reason_counts = _deepcopy_json(admissibility['unresolved_reason_counts'])
    pooling_nodes = int(reason_counts.get(POOLING_LEVEL_REASON_CODE, 0))
    return {
        'class': 'SCIENTIFIC_DATA',
        'code': BLOCK_NO_ADMISSIBLE_POOLING_LEVEL,
        'reason_code': POOLING_LEVEL_REASON_CODE,
        'rule': admissibility['rule'],
        'detail': (
            'the required #388/#419 response tree is not complete: 0 of the required nodes carry '
            'an admissible exact answer at hierarchical_exact_key / L0_EXACT_KEY and every node '
            'stays EXACT_UNRESOLVED. The dominant unresolved reason is '
            f'{POOLING_LEVEL_REASON_CODE} ({pooling_nodes} of '
            f"{preflight['required_tree']['required_node_count']} nodes); a fail-closed node is "
            'never repaired by lowering a frozen threshold'
        ),
        'required_nodes': preflight['required_tree']['required_node_count'],
        'admissible_exact_nodes': admissibility['admissible_exact_nodes'],
        'blocked_nodes': admissibility['blocked_nodes'],
        'nodes_with_no_admissible_pooling_level': pooling_nodes,
        'status_counts': _deepcopy_json(admissibility['status_counts']),
        'unresolved_reason_counts': reason_counts,
        'admissibility_class_counts': _deepcopy_json(admissibility['admissibility_class_counts']),
        'failed_admissibility_conditions': sorted(
            name for name, condition in admissibility['conditions'].items()
            if not condition['satisfied']
        ),
        'required_tree_complete': preflight['required_tree_complete'] is True,
        'required_tree_complete_reason_codes': list(
            preflight['required_tree_complete_reason_codes']
        ),
        'evidence': {
            'source': _relative(PREFLIGHT_V2_PATH),
            'sha256': binding['sha256'],
            'canonical_payload_sha256': binding['canonical_payload_sha256'],
            'scope': 'TRAIN_ONLY_PREFLIGHT_V2',
        },
    }


def sizing_blocker(
    preflight: Mapping[str, Any], frontier: Mapping[str, Any], binding: Mapping[str, Any]
) -> dict[str, Any]:
    effect = frontier['required_tree_complete_effect']
    return {
        'class': 'SCIENTIFIC_STRUCTURAL',
        'code': BLOCK_UNRESOLVED_RAISE_SIZING,
        'reason_code': RAISE_SIZING_REASON_CODE,
        'frontier_schema': str(frontier['schema']),
        'frontier_revision': str(frontier['revision']),
        'detail': (
            'raise-sizing frontiers stay unresolved: no exactly supported raise target exists at '
            'the frozen #367 structural node and no representative price may substitute it. The '
            'frontier is structural -- a property of the required tree, not of the response '
            'model -- so it is flagged independent_of_the_response_model=true and changing the '
            'response model cannot close it'
        ),
        'frontiers_total': frontier['frontiers_total'],
        'unresolved_count': frontier['unresolved_count'],
        'resolved_count': frontier['resolved_count'],
        'unresolved_node_ids': list(frontier['unresolved_node_ids']),
        'independent_of_the_response_model': True,
        'blocker_persisted': frontier['blocker_persisted'] is True,
        'required_tree_complete': frontier['required_tree_complete'] is True,
        'required_tree_complete_effect': _deepcopy_json(effect),
        'preflight_sizing_frontiers_queried': preflight['sizing_frontiers_queried'],
        'evidence': {
            'preflight': {
                'source': _relative(PREFLIGHT_V2_PATH),
                'sha256': binding['sha256'],
                'canonical_payload_sha256': binding['canonical_payload_sha256'],
            },
            'frontier_resolution': {
                'source': _relative(frontier_tool.OUTPUT / frontier_tool.ARTIFACT_NAME),
                'sha256': sha256_file(frontier_tool.OUTPUT / frontier_tool.ARTIFACT_NAME),
                'schema': str(frontier['schema']),
                'revision': str(frontier['revision']),
            },
            'superseded_v1_frontier_custody': {
                'source': _relative(
                    frontier_tool.V1_OUTPUT / frontier_tool.V1_ARTIFACT_NAME
                ),
                'sha256': V1_FRONTIER_RESOLUTION_SHA256,
            },
        },
    }


def calibration_blocker(
    preflight: Mapping[str, Any], validation: Mapping[str, Any], binding: Mapping[str, Any]
) -> dict[str, Any]:
    gate = preflight['admissibility_protocol']['calibration_gate']
    attestation = gate['evidence']['attestation']
    measured = attestation['measured']
    thresholds = gate['thresholds']
    published = validation['gates'][CALIBRATION_ABSOLUTE_GATE_ID]['measured']
    return {
        'class': 'SCIENTIFIC_EVIDENCE',
        'code': BLOCK_REFUSED_CALIBRATION,
        'layer_b_gate_id': LAYER_B_CALIBRATION_GATE_ID,
        'reason_code': BLOCK_REFUSED_CALIBRATION,
        'detail': (
            'the frozen layer-B calibration gate is refused from the digest-referenced v1 '
            f"VALIDATION bytes: pooled ECE {measured['pooled_ece']:.6g} > maximum_absolute_ece "
            f"{thresholds['maximum_absolute_ece']:g} and "
            f"{measured['bins_meeting_minimum_support']} of "
            f"{measured['reliability_bins_required']} reliability bins meet the minimum support "
            '(minimum_bin_support_for_a_calibration_claim='
            f"{thresholds['minimum_bin_support_for_a_calibration_claim']}). No threshold was "
            're-selected and no metric was recomputed: the verdict is read from the published, '
            'already-consumed VALIDATION result'
        ),
        'gate_evaluated': gate['evaluated'] is True,
        'gate_passed': gate['passed'] is True,
        'thresholds': _deepcopy_json(thresholds),
        'measured': {
            'pooled_ece': measured['pooled_ece'],
            'maximum_absolute_ece': thresholds['maximum_absolute_ece'],
            'bins_meeting_minimum_support': measured['bins_meeting_minimum_support'],
            'reliability_bins_required': measured['reliability_bins_required'],
            'bins_per_action_class': measured['bins_per_action_class'],
            'active_reference_ece': measured['active_reference_ece'],
            'ece_delta_vs_active': measured['ece_delta_vs_active'],
            'maximum_ece_delta_vs_active': thresholds['maximum_ece_delta_vs_active'],
            'claim_supportable_in_the_result': measured['claim_supportable_in_the_result'],
        },
        'recorded_gate_verdicts': _deepcopy_json(attestation['recorded_gate_verdicts']),
        'validation_gate': {
            'gate': CALIBRATION_ABSOLUTE_GATE_ID,
            'pass': bool(validation['gates'][CALIBRATION_ABSOLUTE_GATE_ID]['pass']),
            'rule': validation['gates'][CALIBRATION_ABSOLUTE_GATE_ID]['rule'],
            'published_measured': _deepcopy_json(published),
        },
        'evidence': {
            'source': validation['source'],
            'source_artifact': _relative(V1_VALIDATION_RESULT_PATH),
            'source_byte_sha256': validation['byte_sha256'],
            'canonical_payload_sha256': validation['canonical_payload_sha256'],
            'referenced_by_digest': True,
            'digest_re_derived_from_persisted_bytes': True,
            'protocol_v2_custody_pin': attestation['protocol_v2_custody_pin'],
            'pointers_read': list(attestation['pointers_read']),
            'holdout_reopened_by_this_decision': False,
            'validation_consumed_by_this_decision': False,
            'validation_decision_rows_read': 0,
            'metrics_recomputed': 0,
            'thresholds_re_selected': False,
            'preflight_evidence_sha256': binding['sha256'],
        },
    }


def coverage_blocker(
    validation: Mapping[str, Any], extra_failing_gates: Sequence[str]
) -> dict[str, Any]:
    row = validation['gates'][COVERAGE_FLOOR_GATE_ID]
    measured = row['measured']
    return {
        'class': 'SCIENTIFIC_EVIDENCE',
        'code': BLOCK_REFUSED_COVERAGE_FLOOR,
        'reason_code': BLOCK_REFUSED_COVERAGE_FLOOR,
        'detail': (
            'the published VALIDATION coverage floor fails: '
            f"{measured['identifiable_decisions']} identifiable decisions and "
            f"{measured['identifiable_hands']} distinct hands against the frozen "
            f"required_decisions={measured['required_decisions']} / "
            f"required_hands={measured['required_hands']}; a claim below the identifiable-support "
            'floor is never treated as supportable'
        ),
        'failing_gate': COVERAGE_FLOOR_GATE_ID,
        'rule': row['rule'],
        'measured': _deepcopy_json(measured),
        'coverage': _deepcopy_json(validation['coverage']),
        'production_effect': validation['production_effect'],
        'validation_outcome': validation['outcome'],
        'other_failing_gates': list(extra_failing_gates),
        'evidence': {
            'source': validation['source'],
            'source_artifact': validation['path'],
            'source_byte_sha256': validation['byte_sha256'],
            'canonical_payload_sha256': validation['canonical_payload_sha256'],
            'referenced_by_digest': True,
            'digest_re_derived_from_persisted_bytes': True,
            'pointers_read': list(VALIDATION_REFERENCE_POINTERS),
            'holdout_reopened_by_this_decision': False,
            'validation_consumed_by_this_decision': False,
            'validation_decision_rows_read': 0,
            'metrics_recomputed': 0,
        },
    }


def validation_gates_blocker(
    validation: Mapping[str, Any], failing_gates: Sequence[str]
) -> dict[str, Any]:
    return {
        'class': 'SCIENTIFIC_EVIDENCE',
        'code': BLOCK_REFUSED_VALIDATION_GATES,
        'detail': (
            'additional frozen VALIDATION gates fail on the digest-referenced v1 result: '
            + ', '.join(failing_gates)
        ),
        'failing_gates': list(failing_gates),
        'outcome': validation['outcome'],
        'all_gates_pass': validation['all_gates_pass'],
        'evidence': {
            'source': validation['source'],
            'source_artifact': validation['path'],
            'source_byte_sha256': validation['byte_sha256'],
            'referenced_by_digest': True,
        },
    }


def choose_decision(
    preflight: Mapping[str, Any],
    validation: Mapping[str, Any],
    frontier: Mapping[str, Any],
    bindings: Mapping[str, Any],
) -> tuple[str, str, list[dict[str, Any]]]:
    """Apply the frozen admission rule; never force an admission."""
    required_tree_complete = preflight['required_tree_complete'] is True
    substitutions = preflight['nearest_substitution_audit']['substitutions_applied']
    outcome = validation['outcome']
    all_gates_pass = validation['all_gates_pass'] is True
    admissible = (
        required_tree_complete
        and substitutions == 0
        and outcome == 'ADMIT_CANDIDATE'
        and all_gates_pass
    )
    if admissible:
        return DECISION_ADMIT, STATUS_READY, []

    blockers: list[dict[str, Any]] = []
    if not required_tree_complete:
        blockers.append(tree_blocker(preflight, bindings[preflight_tool.V2_NAME]))
    if frontier['unresolved_count']:
        blockers.append(sizing_blocker(preflight, frontier, bindings[preflight_tool.V2_NAME]))

    calibration = preflight['admissibility_protocol']['calibration_gate']
    calibration_refused = (
        calibration['evaluated'] is not True
        or calibration['passed'] is not True
        or validation['gates'][CALIBRATION_ABSOLUTE_GATE_ID]['pass'] is not True
    )
    if calibration_refused:
        blockers.append(calibration_blocker(preflight, validation, bindings[preflight_tool.V2_NAME]))

    other_failing = [
        name for name in validation['failing_gates'] if name != CALIBRATION_ABSOLUTE_GATE_ID
    ]
    if COVERAGE_FLOOR_GATE_ID in other_failing:
        others = [name for name in other_failing if name != COVERAGE_FLOOR_GATE_ID]
        blockers.append(coverage_blocker(validation, others))
        other_failing = others
    if other_failing:
        blockers.append(validation_gates_blocker(validation, other_failing))

    if substitutions:
        blockers.append({
            'class': 'EVIDENCE_INTEGRITY',
            'code': BLOCK_EVIDENCE_INTEGRITY,
            'detail': 'a forbidden nearest-*/borrowed substitution was applied',
            'substitutions_applied': substitutions,
        })

    status = STATUS_NEEDS_FIXES if any(
        blocker['class'] == 'EVIDENCE_INTEGRITY' for blocker in blockers
    ) else STATUS_BLOCKED
    return DECISION_UNRESOLVED, status, blockers


def build_n8n_block(decision: Mapping[str, Any]) -> dict[str, Any]:
    """The exact n8n output block handed back to the orchestrator."""
    return {
        'type': 'N8N_TASK_RESULT',
        'issue': ISSUE,
        'decision': decision['decision'],
        'status': decision['status'],
        'admitted': decision['admitted'],
        'candidate_id': decision['candidate_id'],
        'candidate_sha256': decision['candidate_sha256'],
        'required_tree_complete': decision['required_tree_complete'],
        'required_tree_sha256': decision['required_tree_sha256'],
        'blockers': [blocker['code'] for blocker in decision['blockers']],
        'primary_blocker': decision['primary_blocker'],
        'validation_outcome': decision['validation_outcome'],
        'validation_reference_sha256': decision['validation_reference']['byte_sha256'],
        'validation_consumed': decision['validation_consumed'],
        'test_consumed': decision['test_consumed'],
        'active_pointer_mutated': decision['active_pointer_mutated'],
        'hero_ev_executed': decision['hero_ev_executed'],
        'issue367_run': decision['issue367_run'],
        'next_issue': decision['next_issue'],
    }


def render_n8n_block(block: Mapping[str, Any]) -> str:
    """Deterministic ``key: value`` rendering of the exact n8n block.

    Keys are rendered in sorted order so that a block read back from
    ``DECISION_V2.json`` (whose keys are serialized sorted) renders
    byte-identically to the freshly built block.
    """
    lines = ['N8N_TASK_RESULT']
    for key in sorted(block):
        if key == 'type':
            continue
        value = block[key]
        if isinstance(value, bool):
            rendered = 'true' if value else 'false'
        elif value is None:
            rendered = 'null'
        elif isinstance(value, list):
            rendered = ','.join(str(item) for item in value)
        else:
            rendered = str(value)
        lines.append(f'{key}: {rendered}')
    return '\n'.join(lines) + '\n'


def object_extension(name: str) -> str:
    """Content-addressed object extension for a bundle artifact."""
    return '.md' if name.endswith('.md') else ('.txt' if name.endswith('.txt') else '.json')


def bound_artifact(name: str, source: Path, object_dir: Path) -> dict[str, Any]:
    data = source.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    object_path = object_dir / 'sha256' / (digest + object_extension(name))
    if not object_path.exists() or object_path.read_bytes() != data:
        raise TerminalDecisionError(
            f'{name} has no matching content-addressed object at {object_path.relative_to(ROOT)}'
        )
    entry: dict[str, Any] = {
        'path': str(source.relative_to(ROOT)),
        'sha256': digest,
        'object': str(object_path.relative_to(ROOT)),
        'bundle': str(object_dir.relative_to(ROOT)) if object_dir != HERE else '.',
    }
    if name.endswith('.json'):
        entry['canonical_payload_sha256'] = stable_hash(json.loads(data))
    return entry


def build() -> tuple[dict[str, Any], str]:
    """Build the terminal decision v2 and its human-readable summary."""
    holdout_scan = verify_no_holdout_access()
    verify_no_issue367_runner()
    protected_before = {str(p.relative_to(ROOT)): sha256_file(p) for p in PROTECTED_PATHS}

    with hand_history_tripwire() as opened:
        verify_content_address(HERE)
        verify_content_address(PREFLIGHT_V2_OUTPUT)
        verify_content_address(frontier_tool.OUTPUT)
        verify_content_address(frontier_tool.V1_OUTPUT)
        v2_preflight = load_frozen_v2_preflight()
        custody = load_frozen_protocol_v2_custody()
        v1_custody = verify_frozen_v1_decision()
        preflight = v2_preflight['preflight']
        validation = load_v1_validation_reference(preflight, custody)
        frontier = load_raise_sizing_frontiers(preflight)
        fit_index = verify_content_address(fit_tool.OUTPUT)
        model_spec_index = verify_content_address(spec_tool.BUNDLE)

        if sha256_file(HERE / INDEX_NAME) != ROOT_ARTIFACTS_SHA256:
            raise TerminalDecisionError(
                'the root ARTIFACTS.json is a frozen input and must not change'
            )
        if sha256_file(HERE / SUMMARY_NAME) != ROOT_SUMMARY_SHA256:
            raise TerminalDecisionError(
                'the root SUMMARY.md is a frozen input and must not change'
            )
        if sha256_file(spec_tool.SPEC_PATH) != SPEC_BYTE_SHA256:
            raise TerminalDecisionError('the frozen T2 spec bytes moved')
        if sha256_file(PROTOCOL_V1_PATH) != PROTOCOL_V1_BYTE_SHA256:
            raise TerminalDecisionError('the frozen T6 protocol bytes moved')
        if sha256_file(HERE / baseline_tool.BASELINE_NAME) != BASELINE_BYTE_SHA256:
            raise TerminalDecisionError('the T1 sparsity baseline bytes moved')
        if sha256_file(legacy.REFERENCE) != REFERENCE_BYTE_SHA256:
            raise TerminalDecisionError('the active Model A reference moved')
        spec = _load(spec_tool.SPEC_PATH)
        if spec.get('schema') != H.HIERARCHY_SPEC_SCHEMA:
            raise TerminalDecisionError('the T2 spec must be the unadmitted hierarchical spec')
        if spec.get('status') != 'SPEC_ONLY_NOT_ADMITTED':
            raise TerminalDecisionError('the T2 spec must stay unadmitted')
        fit_report = _load(fit_tool.OUTPUT / fit_tool.REPORT_NAME)
        manifest = _load(fit_tool.OUTPUT / fit_tool.MANIFEST_NAME)
        baseline = _load(HERE / baseline_tool.BASELINE_NAME)
        if preflight['provider']['candidate_canonical_payload_sha256'] != (
            preflight_tool.CANDIDATE_CANONICAL_SHA256
        ):
            raise TerminalDecisionError('candidate canonical payload digest moved')
        if preflight_tool.CANDIDATE_CANONICAL_SHA256 == ISSUE352_CANDIDATE_SHA256:
            raise TerminalDecisionError('the hierarchical candidate must stay distinct from #352 v2')
        for name, artifact in (
            (spec_tool.SPEC_NAME, spec),
            (fit_tool.REPORT_NAME, fit_report),
            (fit_tool.MANIFEST_NAME, manifest),
            (preflight_tool.V2_NAME, preflight),
        ):
            if artifact.get('test_consumed') is True:
                raise TerminalDecisionError(f'{name} declares test_consumed=true')
            if artifact.get('validation_consumed') is True:
                raise TerminalDecisionError(f'{name} must stay TRAIN-only')
        if fit_index[fit_tool.CANDIDATE_NAME]['canonical_payload_sha256'] != (
            preflight_tool.CANDIDATE_CANONICAL_SHA256
        ):
            raise TerminalDecisionError('candidate bytes are not the ones pinned by the fit index')
        if model_spec_index[spec_tool.SPEC_NAME]['canonical_payload_sha256'] != stable_hash(spec):
            raise TerminalDecisionError('the model-spec index disagrees with the spec bytes')
        if baseline.get('schema') != baseline_tool.SCHEMA:
            raise TerminalDecisionError('unexpected T1 sparsity baseline schema')

        bindings: dict[str, Any] = {}
        for name, source, object_dir in ARTIFACT_SOURCES:
            bindings[name] = bound_artifact(name, source, object_dir)

        decision_code, status, blockers = choose_decision(
            preflight, validation, frontier, bindings
        )
        primary_blocker = blockers[0]['code'] if blockers else None

    hand_history_opens = sorted(path for path in opened if _is_hand_history_path(path))
    if hand_history_opens:
        raise TerminalDecisionError(f'hand-history opens recorded: {hand_history_opens}')

    protected_after = {str(p.relative_to(ROOT)): sha256_file(p) for p in PROTECTED_PATHS}
    if protected_before != protected_after:
        raise TerminalDecisionError('a protected input was mutated while the decision was built')

    v1_decision = _load(BUNDLE / DECISION_NAME)
    rule = v1_decision['decision_rule']
    provider = preflight['provider']
    candidate = {
        'candidate_id': H.CANDIDATE_ID,
        'candidate_sha256': provider['candidate_canonical_payload_sha256'],
        'candidate_instance_id': provider['candidate_instance_id'],
        'candidate_byte_sha256': provider['candidate_byte_sha256'],
        'identity_granularity': provider['identity_granularity'],
        'distinct_from_issue_352': True,
        'issue_352_candidate_id': 'model-a-preflop-sizing-aware-candidate-v2',
        'issue_352_candidate_sha256': ISSUE352_CANDIDATE_SHA256,
        'admitted': decision_code == DECISION_ADMIT,
        'candidate_status_at_freeze': H.CANDIDATE_STATUS,
    }
    admissibility = preflight['admissibility']
    calibration_gate = preflight['admissibility_protocol']['calibration_gate']

    decision: dict[str, Any] = {
        'schema': V2_SCHEMA,
        'supersedes_schema': SCHEMA,
        'issue': ISSUE,
        'parent_issue': PARENT_ISSUE,
        'scenario_issue': SCENARIO_ISSUE,
        'source_issue': SOURCE_ISSUE,
        'kind': 'TERMINAL_HIERARCHICAL_EXACT_TREE_DECISION',
        'revision': 'v2',
        'bundle_dir': str(V2_BUNDLE.relative_to(ROOT)),
        'decision': decision_code,
        'status': status,
        'admitted': decision_code == DECISION_ADMIT,
        'candidate_id': candidate['candidate_id'],
        'candidate_sha256': candidate['candidate_sha256'],
        'candidate_instance_id': candidate['candidate_instance_id'],
        'candidate': candidate,
        'required_tree_complete': preflight['required_tree_complete'] is True,
        'required_tree_sha256': preflight['required_tree']['required_tree_sha256'],
        'required_tree_byte_sha256': preflight['required_tree']['required_tree_byte_sha256'],
        'required_tree_node_count': preflight['required_tree']['required_node_count'],
        'required_tree_complete_reason_codes': list(
            preflight['required_tree_complete_reason_codes']
        ),
        'admissible_exact_node_count': admissibility['admissible_exact_nodes'],
        'admissibility_class_counts': _deepcopy_json(
            admissibility['admissibility_class_counts']
        ),
        'exact_unresolved_node_count': admissibility['status_counts'].get('EXACT_UNRESOLVED', 0),
        'unresolved_reason_counts': _deepcopy_json(admissibility['unresolved_reason_counts']),
        'nodes_with_no_admissible_pooling_level': int(
            admissibility['unresolved_reason_counts'].get(POOLING_LEVEL_REASON_CODE, 0)
        ),
        'identity_granularity': provider['identity_granularity'],
        'support_isolation_rule': provider['support_isolation_rule'],
        'sizing_frontiers': {
            'frontiers_total': frontier['frontiers_total'],
            'unresolved_count': frontier['unresolved_count'],
            'resolved_count': frontier['resolved_count'],
            'schema': str(frontier['schema']),
            'revision': str(frontier['revision']),
            'independent_of_the_response_model': True,
            'blocker_reason_code': RAISE_SIZING_REASON_CODE,
            'required_tree_complete_effect': str(
                frontier['required_tree_complete_effect']['effect']
            ),
            'unresolved_node_ids': list(frontier['unresolved_node_ids']),
            'preflight_sizing_frontiers_queried': preflight['sizing_frontiers_queried'],
        },
        'unresolved_raise_sizing_frontier_count': frontier['unresolved_count'],
        'validation_reference': validation,
        'validation_outcome': validation['outcome'],
        'validation_failing_gates': list(validation['failing_gates']),
        'calibration_gate': {
            'gate_id': LAYER_B_CALIBRATION_GATE_ID,
            'evaluated': calibration_gate['evaluated'] is True,
            'passed': calibration_gate['passed'] is True,
            'reason_code': BLOCK_REFUSED_CALIBRATION,
            'source': calibration_gate['evidence']['source'],
            'source_artifact': _relative(V1_VALIDATION_RESULT_PATH),
            'source_byte_sha256': validation['byte_sha256'],
            'canonical_payload_sha256': validation['canonical_payload_sha256'],
            'digest_re_derived_from_persisted_bytes': True,
            'protocol_v2_custody_pin': validation['protocol_v2_custody_pin'],
            'no_new_holdout_read': True,
        },
        'protocol_custody': {
            'protocol_v1_byte_sha256': PROTOCOL_V1_BYTE_SHA256,
            'protocol_v2_byte_sha256': custody['byte_sha256'],
            'protocol_v2_canonical_payload_sha256': custody['canonical_payload_sha256'],
            'protocol_v2_revision_of': PROTOCOL_V1_BYTE_SHA256,
            'validation_result_custody_pin': custody['validation_result_custody_pin'],
            'preflight_v2_records_protocol_v2_byte_sha256': v2_preflight[
                'records_protocol_v2_byte_sha256'
            ],
            'digest_re_derived_from_persisted_bytes': True,
        },
        'no_new_holdout_read': {
            'check': holdout_scan['check'],
            'result': holdout_scan['result'],
            'holdout_reopened_by_this_decision': False,
            'validation_split_re_evaluated': False,
            'validation_decision_rows_read': 0,
            'metrics_recomputed': 0,
            'thresholds_re_selected': False,
            'hand_histories_parsed': 0,
            'dataset_archives_opened': False,
            'validation_result_referenced_by_digest': True,
            'digest_re_derived_from_persisted_bytes': True,
            'values_source': CALIBRATION_EVIDENCE_SOURCE,
            'opened_input_count': len(set(opened)),
            'opened_inputs': sorted(set(opened)),
            'static_scan': holdout_scan,
        },
        'holdout_boundary': {
            'validation_consumed': True,
            'validation_consumed_once_through_the_frozen_protocol': True,
            'validation_consumed_by_this_decision': False,
            'test_consumed': False,
            'test_authorized': False,
            'model_b_consumed': False,
            'hero_ev_consumed': False,
            'split_consumed_by_the_preflight_v2': 'TRAIN',
        },
        'validation_consumed': True,
        'test_consumed': False,
        'test_authorized': False,
        'active_pointer_mutated': False,
        'hero_ev_executed': False,
        'hero_recommendation': None,
        'issue367_run': False,
        'issue367_authorized': preflight['boundary']['issue367_authorization'][
            'authorized_at_freeze'
        ] is True,
        'next_issue': NEXT_ISSUE,
        'primary_blocker': primary_blocker,
        'blockers': blockers,
        'decision_rule': {
            'rule_id': rule['rule_id'],
            'question': rule['question'],
            'authorized_when': list(rule['authorized_when']),
            'consequence_when_forbidden': rule['consequence_when_forbidden'],
            'admission_requires': [
                'required_tree_complete=true from the exact-tree preflight v2',
                'no nearest-price / nearest-context / borrowed-support substitution applied',
                'VALIDATION outcome=ADMIT_CANDIDATE with every frozen gate passing',
            ],
            'observed': {
                'required_tree_complete': preflight['required_tree_complete'] is True,
                'substitutions_applied': preflight['nearest_substitution_audit'][
                    'substitutions_applied'
                ],
                'validation_outcome': validation['outcome'],
                'validation_all_gates_pass': validation['all_gates_pass'],
                'unresolved_raise_sizing_frontiers': frontier['unresolved_count'],
                'calibration_gate_passed': calibration_gate['passed'] is True,
            },
            'inherited_from_v1_decision': {
                'path': _relative(BUNDLE / DECISION_NAME),
                'sha256': V1_DECISION_SHA256,
                'canonical_payload_sha256': V1_DECISION_CANONICAL_SHA256,
            },
        },
        'carried_risks': [
            {
                'risk_id': 'RUNTIME_SUPPORT_CONTEXT_COARSE_MERGE',
                'detail': (
                    'the provider runtime key merges distinct public contexts; the exact identity '
                    'granularity stays the fine hierarchical_exact_key'
                ),
                'runtime_keys_merging_exact_states': preflight['required_tree'].get(
                    'runtime_keys_merging_exact_states'
                ),
                'handled_by': 'T2 HIERARCHICAL_MODEL_SPEC.granularity_decision',
                'not_a_substitution': True,
            },
        ],
        'composition': {
            'preflight_v2': {
                'path': _relative(PREFLIGHT_V2_PATH),
                'sha256': PREFLIGHT_V2_BYTE_SHA256,
                'canonical_payload_sha256': PREFLIGHT_V2_CANONICAL_SHA256,
                'scope': 'TRAIN_ONLY',
            },
            'validation_evidence_referenced_by_digest': {
                'path': _relative(V1_VALIDATION_RESULT_PATH),
                'sha256': V1_VALIDATION_RESULT_SHA256,
                'canonical_payload_sha256': V1_VALIDATION_RESULT_CANONICAL_SHA256,
                'scope': 'CONSUMED_VALIDATION_HISTORY_NEVER_RE_READ',
            },
            'no_second_holdout_read': True,
            'no_metric_recomputed': True,
        },
        'required_artifacts': {
            name: {
                'path': bindings[name]['path'],
                'sha256': bindings[name]['sha256'],
                'canonical_payload_sha256': bindings[name].get('canonical_payload_sha256'),
            }
            for name in REQUIRED_NAMES
            if name in bindings
        },
        'evidence_bindings': bindings,
        'verified_bundles': sorted({
            _relative(HERE),
            _relative(PREFLIGHT_V2_OUTPUT),
            _relative(fit_tool.OUTPUT),
            _relative(spec_tool.BUNDLE),
            _relative(PROTOCOL_V1_BUNDLE),
            _relative(V1_VALIDATION_RESULT_PATH.parent),
            _relative(frontier_tool.OUTPUT),
            _relative(frontier_tool.V1_OUTPUT),
            _relative(BUNDLE),
        }),
        'frozen_inputs_untouched': {
            'root_artifacts_sha256': ROOT_ARTIFACTS_SHA256,
            'root_summary_sha256': ROOT_SUMMARY_SHA256,
            'hierarchical_model_spec_sha256': SPEC_BYTE_SHA256,
            'frozen_validation_protocol_sha256': PROTOCOL_V1_BYTE_SHA256,
            'frozen_validation_protocol_v2_sha256': custody['byte_sha256'],
            'frozen_validation_protocol_v2_canonical_payload_sha256': custody[
                'canonical_payload_sha256'
            ],
            'hierarchical_tree_sparsity_baseline_sha256': BASELINE_BYTE_SHA256,
            'active_reference_sha256': REFERENCE_BYTE_SHA256,
            'v1_validation_result_sha256': V1_VALIDATION_RESULT_SHA256,
            'v1_decision_sha256': V1_DECISION_SHA256,
            'v1_terminal_decision_bundle_index_sha256': V1_INDEX_SHA256,
            'v1_raise_sizing_frontier_sha256': V1_FRONTIER_RESOLUTION_SHA256,
            'v1_raise_sizing_frontier_bundle_index_sha256': V1_FRONTIER_INDEX_SHA256,
            'v2_raise_sizing_frontier_sha256': str(frontier['_v2_byte_sha256']),
            'exact_tree_preflight_v2_sha256': PREFLIGHT_V2_BYTE_SHA256,
        },
        'frozen_v1_decision': v1_custody,
        'frozen_v1_raise_sizing_frontier': frontier['_v1_custody'],
        'raise_sizing_frontier_revision': {
            'schema': str(frontier['schema']),
            'revision': str(frontier['revision']),
            'supersedes_schema': str(frontier['supersedes_schema']),
            'values_source': (
                _relative(frontier_tool.OUTPUT) + '/' + frontier_tool.ARTIFACT_NAME
            ),
            'v1_custody_only_never_rewritten': (
                _relative(frontier_tool.V1_OUTPUT) + '/' + frontier_tool.V1_ARTIFACT_NAME
            ),
        },
        'protected_files_before_after_sha256': {
            'before': protected_before,
            'after': protected_after,
            'unchanged': True,
        },
        'source_files_sha256': {
            str(SOURCE_PATH.relative_to(ROOT)): sha256_file(SOURCE_PATH),
        },
        'reproduction': {
            'build': (
                'python3 tools/training/finalize_hierarchical_exact_tree_decision.py '
                '--revision v2'
            ),
            'check': 'python3 tools/training/finalize_hierarchical_exact_tree_decision.py --check',
            'v1_is_refused': True,
        },
        'not_an_admission_by_default': (
            'UNRESOLVED_HIERARCHICAL_TREE_GAP is a valid terminal outcome; admission is never '
            'forced and #367 is never run by this tool'
        ),
    }
    for name in (V2_NAME, V2_SUMMARY_NAME):
        decision['required_artifacts'][name] = {
            'path': str((V2_BUNDLE / name).relative_to(ROOT)),
            'sha256_location': str((V2_BUNDLE / V2_INDEX_NAME).relative_to(ROOT)),
            'note': (
                'self-referential: this artifact digest is recorded by the bundle index, not '
                'inside itself'
            ),
        }
    decision['n8n_task_result'] = build_n8n_block(decision)
    return decision, summary_text(decision)


def persist(decision: dict[str, Any]) -> dict[str, Any]:
    """Write the terminal v2 bundle: the generated files, their objects and the index."""
    generated = {
        V2_NAME: serialize(decision),
        V2_SUMMARY_NAME: summary_text(decision).encode(),
        V2_N8N_NAME: render_n8n_block(decision['n8n_task_result']).encode(),
    }

    V2_BUNDLE.mkdir(parents=True, exist_ok=True)
    objects = V2_BUNDLE / 'sha256'
    objects.mkdir(exist_ok=True)
    index: dict[str, Any] = {}
    referenced: set[str] = set()
    for name, data in generated.items():
        extension = object_extension(name)
        digest = hashlib.sha256(data).hexdigest()
        (V2_BUNDLE / name).write_bytes(data)
        (objects / (digest + extension)).write_bytes(data)
        entry: dict[str, Any] = {
            'path': str((V2_BUNDLE / name).relative_to(ROOT)),
            'sha256': digest,
            'object': str((objects / (digest + extension)).relative_to(ROOT)),
        }
        if extension == '.json':
            entry['canonical_payload_sha256'] = stable_hash(json.loads(data))
        index[name] = entry
        referenced.add(digest + extension)

    for name, source, object_dir in ARTIFACT_SOURCES:
        index[name] = bound_artifact(name, source, object_dir)

    for name in REQUIRED_NAMES:
        if name not in index:
            raise TerminalDecisionError(f'required artifact {name} missing from the index')
        if 'sha256' not in index[name]:
            raise TerminalDecisionError(f'required artifact {name} carries no sha256')

    (V2_BUNDLE / V2_INDEX_NAME).write_text(json.dumps(index, sort_keys=True, indent=2) + '\n')
    (V2_DIGEST_PATH).write_text(
        f"{index[V2_NAME]['sha256']}  {V2_NAME}\n"
        f"# canonical_payload_sha256 {index[V2_NAME].get('canonical_payload_sha256')}\n"
    )
    for path in objects.iterdir():
        if path.is_file() and path.name not in referenced:
            path.unlink()
    return index


def summary_text(decision: Mapping[str, Any]) -> str:
    blockers = decision['blockers']
    lines = [
        '# #419 — terminal decision v2: hierarchical exact-tree candidate',
        '',
        f"**{decision['decision']}** — status `{decision['status']}`, admitted: "
        f"`{'true' if decision['admitted'] else 'false'}`.",
        '',
        f"Candidate `{decision['candidate_id']}` (canonical payload "
        f"`{decision['candidate_sha256']}`) is the frozen TRAIN-fit hierarchical Model-A candidate. "
        'It is **not** admitted and it is **not** wired into #367: admission requires a complete '
        'exact tree *and* an `ADMIT_CANDIDATE` VALIDATION result, and neither holds.',
        '',
        'This v2 decision is composed of exactly two constituents: the TRAIN-only exact-tree '
        f"preflight v2 (`{_relative(PREFLIGHT_V2_PATH)}`, byte SHA256 "
        f"`{PREFLIGHT_V2_BYTE_SHA256}`) and the **already-consumed** v1 VALIDATION result bytes, "
        f"referenced **by digest** (`{_relative(V1_VALIDATION_RESULT_PATH)}`, byte SHA256 "
        f"`{V1_VALIDATION_RESULT_SHA256}`). No holdout is re-opened: no hand history is parsed, no "
        'validation decision row is read, no metric is recomputed and no threshold is re-selected.',
        '',
        f"preflight v2: `required_tree_complete={str(decision['required_tree_complete']).lower()}` "
        f"— {decision['admissible_exact_node_count']} of {decision['required_tree_node_count']} "
        'required nodes carry an admissible exact answer at `hierarchical_exact_key` / '
        f"`L0_EXACT_KEY`, so all {decision['exact_unresolved_node_count']} required nodes stay "
        f"`EXACT_UNRESOLVED` ({decision['nodes_with_no_admissible_pooling_level']} of them on "
        f"`{POOLING_LEVEL_REASON_CODE}` and {decision['unresolved_raise_sizing_frontier_count']} on "
        f"`{RAISE_SIZING_REASON_CODE}`). T5 left "
        f"{decision['unresolved_raise_sizing_frontier_count']} raise-sizing frontiers unresolved, "
        'explicitly `independent_of_the_response_model=true`; the re-hosted resolution is the '
        f"versioned **v2** bundle (`{decision['raise_sizing_frontier_revision']['values_source']}`, "
        f"schema `{decision['raise_sizing_frontier_revision']['schema']}`) whose unresolved "
        "frontiers force the `BLOCKS_REQUIRED_TREE_COMPLETE` effect. The superseded v1 frontier "
        f"bytes (`{decision['raise_sizing_frontier_revision']['v1_custody_only_never_rewritten']}`, "
        f"byte SHA256 `{V1_FRONTIER_RESOLUTION_SHA256}`) are pinned, re-verified and never "
        'rewritten. T7 VALIDATION returned '
        f"`{decision['validation_outcome']}` with failing frozen gates "
        f"{decision['validation_failing_gates']}.",
        '',
        '## Blockers',
        '',
    ]
    for blocker in blockers:
        lines.append(f"* `{blocker['code']}` ({blocker['class']}) — {blocker['detail']}")
    lines += [
        '',
        '## Holdout and pointer discipline',
        '',
        'VALIDATION was consumed once, through the frozen T6 protocol, by the original T7 '
        'evaluation (`validation_consumed=true`). This v2 decision does **not** consume it again: '
        'the v1 VALIDATION result is referenced by digest, its digest is re-derived from the '
        'persisted bytes, and every value it contributes is a *published* row of that artifact '
        '(`no_new_holdout_read`). TEST stays unconsumed and unauthorized (`test_consumed=false`). No '
        'threshold, prior, pooling limit or comparator was changed after the read. The active Model '
        'A pointer (`training/models/preflop_population_model_v5.json`), the registries, the '
        'reference model, the root `ARTIFACTS.json`/`SUMMARY.md` and the frozen protocol bytes are '
        'unchanged (`active_pointer_mutated=false`). The #367 Hero EV runner was neither imported '
        'nor executed (`hero_ev_executed=false`, `issue367_run=false`).',
        '',
        '## Frozen v1 revision',
        '',
        'The v1 terminal decision '
        f"(`{_relative(BUNDLE / DECISION_NAME)}`, byte SHA256 `{V1_DECISION_SHA256}`, canonical "
        f"payload `{V1_DECISION_CANONICAL_SHA256}`) remains **byte-identical**: it is re-verified "
        'byte-for-byte on every build and every `--check`, and it is never rewritten. Its '
        '`source_files_sha256` records the superseded v1 tool, which no longer exists on disk, so a '
        'byte-identical re-derivation is impossible by construction and `--revision v1` is refused.',
        '',
        '## Bundle',
        '',
        f"This terminal bundle (`{_relative(V2_BUNDLE)}/`) carries the decision, this summary, the "
        'n8n block and one content-addressed index. `ARTIFACTS.json` binds every required artifact '
        'by byte SHA256, canonical payload SHA256 and content-addressed object: '
        + ', '.join(f'`{name}`' for name in REQUIRED_NAMES) + '. The upstream bundles stay in place '
        'and are never rewritten (`frozen_inputs_untouched`).',
        '',
        'Reproduce: `python3 tools/training/finalize_hierarchical_exact_tree_decision.py '
        '--revision v2`; verify: '
        '`python3 tools/training/finalize_hierarchical_exact_tree_decision.py --check`.',
        '',
        '## n8n output',
        '',
        '```text',
        render_n8n_block(decision['n8n_task_result']).rstrip('\n'),
        '```',
        '',
    ]
    return '\n'.join(lines)


def decision_record_text(decision: Mapping[str, Any]) -> str:
    blockers = ', '.join(f"`{blocker['code']}`" for blocker in decision['blockers'])
    return '\n'.join([
        '# Décision terminale #419 v2 — arbre exact hiérarchique',
        '',
        f"- Décision : `{decision['decision']}`",
        f"- Statut : `{decision['status']}` (admission forcée : non)",
        f"- Candidat : `{decision['candidate_id']}` (`{decision['candidate_sha256']}`), non admis",
        f"- `required_tree_complete` = `{str(decision['required_tree_complete']).lower()}` "
        f"({decision['admissible_exact_node_count']}/{decision['required_tree_node_count']} nœuds "
        'admissibles, tous les autres `EXACT_UNRESOLVED`)',
        f"- Blockers : {blockers}",
        f"- Composition : préflight v2 TRAIN-only (`{_relative(PREFLIGHT_V2_PATH)}`) + octets v1 de "
        f"`{_relative(V1_VALIDATION_RESULT_PATH)}` référencés par digest "
        f"(`{V1_VALIDATION_RESULT_SHA256}`) — aucune seconde lecture du holdout, aucun recalcul de "
        'métrique',
        f"- `validation_consumed` = `true` (une seule lecture, via le protocole gelé T6), "
        '`test_consumed` = `false`, `active_pointer_mutated` = `false`',
        f"- `next_issue` = `{decision['next_issue']}` ; #367 n\u2019est jamais lancé par #419",
        '',
        'La DECISION v1 (`analysis/issue419_hierarchical_tree/terminal_decision/DECISION.json`, '
        f'`{V1_DECISION_SHA256}`) reste byte-identique : elle est revérifiée octet par octet et '
        'jamais réécrite ; `--revision v1` est refusé. Le candidat hiérarchique reste distinct de '
        '#352 v2 et n\u2019est pas câblé au provider #367. Aucun seuil, prior ou limite de pooling '
        'n\u2019a été modifié après la lecture VALIDATION, et les entrées gelées (spec T2, protocole '
        'T6, baseline T1, `ARTIFACTS.json`/`SUMMARY.md` racine, pointer actif) sont inchangées.',
        '',
        'Bundle content-adressé : `analysis/issue419_hierarchical_tree/terminal_decision_v2/` '
        '(`DECISION_V2.json`, `SUMMARY.md`, `N8N_TASK_RESULT.txt`, `ARTIFACTS.json`).',
        '',
        'Reproduce: `python3 tools/training/finalize_hierarchical_exact_tree_decision.py '
        '--revision v2`; verify: '
        '`python3 tools/training/finalize_hierarchical_exact_tree_decision.py --check`.',
        '',
    ])


def check() -> int:
    decision, summary = build()
    problems: list[str] = []
    expected = {
        V2_NAME: serialize(decision),
        V2_SUMMARY_NAME: summary.encode(),
        V2_N8N_NAME: render_n8n_block(decision['n8n_task_result']).encode(),
    }
    for name, data in expected.items():
        path = V2_BUNDLE / name
        if not path.exists():
            problems.append(f'{name} is missing')
        elif path.read_bytes() != data:
            problems.append(f'{name} differs from a fresh terminal decision v2')
    index_path = V2_BUNDLE / V2_INDEX_NAME
    if index_path.exists():
        index = _load(index_path)
        for name, entry in index.items():
            path = ROOT / entry['path']
            obj = ROOT / entry['object']
            if not path.exists():
                problems.append(f'{name} is missing at {path}')
                continue
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != entry['sha256']:
                problems.append(f'{name} byte hash does not match {V2_INDEX_NAME}')
            if not obj.exists() or data != obj.read_bytes():
                problems.append(f'{name} content-addressed copy mismatch')
        own_dir = (V2_BUNDLE / 'sha256').relative_to(ROOT)
        own_objects = {
            Path(entry['object']).name for entry in index.values()
            if Path(entry['object']).parent == own_dir
        }
        if {p.name for p in (V2_BUNDLE / 'sha256').iterdir()} != own_objects:
            problems.append(f'{V2_INDEX_NAME} objects and sha256/ directory disagree')
        for name in REQUIRED_NAMES:
            if name not in index:
                problems.append(f'required artifact {name} is absent from {V2_INDEX_NAME}')
            elif 'sha256' not in index[name]:
                problems.append(f'required artifact {name} has no sha256 in {V2_INDEX_NAME}')
    else:
        problems.append(f'{V2_INDEX_NAME} is missing')
    if [b['code'] for b in decision['blockers']] != [
        b['code'] for b in _load(V2_BUNDLE / V2_NAME)['blockers']
    ]:
        problems.append('persisted blockers differ from a fresh decision')
    # the frozen v1 revision must still hash back to its pinned bytes
    verify_frozen_v1_decision()
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1
    index = _load(V2_BUNDLE / V2_INDEX_NAME)
    print(json.dumps({
        'schema': V2_SCHEMA,
        'check': 'PASS',
        'bundle': _relative(V2_BUNDLE),
        'artifact_sha256': index[V2_NAME]['sha256'],
        'required_artifacts': list(REQUIRED_NAMES),
        'decision': decision['decision'],
        'status': decision['status'],
        'blockers': [blocker['code'] for blocker in decision['blockers']],
        'validation_reference_sha256': decision['validation_reference']['byte_sha256'],
        'v1_decision_sha256': V1_DECISION_SHA256,
        'next_issue': decision['next_issue'],
    }, indent=2))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--revision',
        choices=('v1', 'v2'),
        default='v2',
        help=(
            'decision revision to write.  ``v2`` (default) rewrites the content-addressed v2 '
            'bundle under analysis/issue419_hierarchical_tree/terminal_decision_v2/.  ``v1`` is '
            'refused: the superseded v1 bundle is byte-pinned, re-verified and never rewritten'
        ),
    )
    parser.add_argument(
        '--check',
        action='store_true',
        help='verify the persisted v2 bundle instead of rewriting it',
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.revision == 'v1':
        print(
            'REFUSED_REVISION_V1: the superseded v1 terminal decision '
            f'({_relative(BUNDLE)}) is byte-pinned, re-verified and never rewritten; write the v2 '
            'revision instead (--revision v2)',
            file=sys.stderr,
        )
        return 2
    if args.check:
        return check()
    decision, _summary = build()
    index = persist(decision)
    V2_DECISION_RECORD.parent.mkdir(parents=True, exist_ok=True)
    V2_DECISION_RECORD.write_text(decision_record_text(decision))
    print(render_n8n_block(decision['n8n_task_result']).rstrip('\n'))
    print(json.dumps({
        'schema': V2_SCHEMA,
        'bundle': _relative(V2_BUNDLE),
        'decision': decision['decision'],
        'status': decision['status'],
        'admitted': decision['admitted'],
        'candidate_id': decision['candidate_id'],
        'candidate_sha256': decision['candidate_sha256'],
        'required_tree_complete': decision['required_tree_complete'],
        'blockers': [blocker['code'] for blocker in decision['blockers']],
        'primary_blocker': decision['primary_blocker'],
        'validation_outcome': decision['validation_outcome'],
        'validation_reference_sha256': decision['validation_reference']['byte_sha256'],
        'v1_decision_sha256': V1_DECISION_SHA256,
        'next_issue': decision['next_issue'],
        'validation_consumed': decision['validation_consumed'],
        'validation_consumed_by_this_decision': False,
        'test_consumed': decision['test_consumed'],
        'active_pointer_mutated': decision['active_pointer_mutated'],
        'artifact_sha256': index[V2_NAME]['sha256'],
        'required_artifacts': list(REQUIRED_NAMES),
    }, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

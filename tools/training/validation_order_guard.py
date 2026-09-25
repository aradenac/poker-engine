#!/usr/bin/env python3
"""#419 VALIDATION order guard for the hierarchical exact-context Model A candidate.

The frozen VALIDATION protocol of the hierarchical candidate must be written,
content-addressed and timestamped **before** any VALIDATION decision is read for
that candidate.  This module owns that ordering rule so the protocol writer, the
protocol checker and the future evaluation command share a single
implementation:

* :func:`assert_validation_not_yet_consumed` fails closed when a VALIDATION
  result that references the hierarchical candidate already exists, so the
  freeze cannot be authored *after* the holdout was peeked at;
* :func:`assert_protocol_frozen_before_validation` fails closed when the
  persisted protocol is missing, is not frozen, or was mutated after the freeze
  (its bytes no longer match the pinned digest);
* :func:`verify_no_holdout_access` is the AST self-scan that keeps the protocol
  generator free of holdout loaders.

Scope is deliberately narrow: only the *hierarchical* candidate counts.  The
#352 exact-price comparator already consumed the VALIDATION split under its own
frozen protocol; that precedent is recorded by the writer, never treated as a
violation of this candidate's ordering rule, and never re-read here.
"""
from __future__ import annotations

import ast
import contextlib
import hashlib
import json
import pathlib
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATH = Path(__file__).resolve()

CANDIDATE_ID = 'model-a-preflop-sizing-hierarchical-candidate-v1'
CANDIDATE_INSTANCE_ID = 'model-a-preflop-sizing-hierarchical-train-fit-419-v1'
# canonical payload (stable JSON) and byte digests of the frozen TRAIN fit
CANDIDATE_CANONICAL_SHA256 = '637302885b8119e6b0246d827462c36eb707c6e234d0b652483c956f03360999'
CANDIDATE_BYTE_SHA256 = 'c78ae3c434d5f41e50567a131bdfb2b89982243379818709abeb0e5ec2385534'
CANDIDATE_REFERENCE_TOKENS = (CANDIDATE_ID, CANDIDATE_INSTANCE_ID, CANDIDATE_CANONICAL_SHA256)

PROTOCOL_SCHEMA = 'poker-hierarchical-frozen-validation-protocol/v1'
RESULT_SCHEMA = 'poker-hierarchical-validation-result/v1'
FROZEN_STATUS = 'FROZEN_BEFORE_VALIDATION'
# The guard module itself is named with the word "validation"; a generator that
# imports it is not importing a holdout split loader.
ENFORCEMENT_MODULE_NAME = 'validation_order_guard'

# Result locations this candidate would ever write to.  A file appearing at any
# of these paths means the holdout was already read and the freeze must abort.
RESULT_DIRECTORY = 'analysis/issue419_hierarchical_tree/validation'
RESULT_FILENAMES = ('VALIDATION_RESULT.json', 'FROZEN_VALIDATION_RESULT.json')
DECLARED_RESULT_LOCATIONS = tuple(f'{RESULT_DIRECTORY}/{name}' for name in RESULT_FILENAMES)
# Path literals this module legitimately declares because it is the enforcement
# point.  It is the only file allowed to name them; the generator is not.
DECLARED_RESULT_LITERALS = frozenset(
    (RESULT_DIRECTORY, *RESULT_FILENAMES, *DECLARED_RESULT_LOCATIONS)
)

# A failure to look like a protocol and a success at looking like a result is
# what turns a scanned JSON file into a candidate VALIDATION read.
RESULT_MARKERS = ('outcome', 'evidence_sha256', 'gate', 'metrics', 'decisions')
VALIDATION_READ_MARKERS = (
    ('split_consumed', 'VALIDATION'),
    ('selection_split', 'VALIDATION'),
    ('phase', 'VALIDATION'),
)

# Symbols that would indicate a holdout (VALIDATION/TEST) read.  The generator
# must not contain any of them; the check runs at build time and in tests.
HOLDOUT_LOADER_SYMBOLS = (
    'load_validation_records',
    'validation_records',
    'validation_hand_ids',
    'VALIDATION_HANDS',
    'load_holdout',
    'holdout_records',
    'build_validation_decisions',
    'load_test_records',
    'TEST_HANDS',
    'test_hand_ids',
)
HOLDOUT_PATH_MARKERS = ('validation', 'holdout', 'test')
# A literal that names a hand-history source is a boundary risk whatever it is
# called: no generator may point at a certified dataset archive, a decision
# JSONL or a fixture snapshot bundle.  Dataset-tree *metadata* files (the
# population certification JSON) are declared inputs, not hand histories.
HOLDOUT_DATA_EXTENSIONS = ('.jsonl', '.zip', '.snapshots')
DATASET_PATH_MARKER = 'training/datasets/'


class ValidationOrderError(RuntimeError):
    """Raised when the VALIDATION ordering contract would be violated."""


class HoldoutAccessError(ValidationOrderError):
    """Raised when a generator would cross the TRAIN boundary."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()
    return hashlib.sha256(raw).hexdigest()


def verify_no_holdout_access(
    source: str | Path | None = None,
    *,
    is_enforcement_point: bool = False,
    allow_literals: Iterable[str] = (),
) -> dict[str, Any]:
    """Static, reproducible proof that a generator cannot read a holdout split.

    The scan is AST-based on purpose: it looks for identifiers actually used
    (calls, attribute access, imports) and for holdout-looking data paths, not
    for the words themselves, so declarative constants stay readable.

    ``is_enforcement_point`` is only true for this guard module itself, which has
    to name the holdout result paths it polices.  Every generator is scanned with
    the default ``False`` and may not declare a holdout data path at all.

    ``allow_literals`` exists for a generator that must name its *own* output
    artifact (whose filename legitimately contains the word ``validation``).
    Every exempted literal is recorded in the returned evidence so the exemption
    is visible rather than silent; no exemption can name a holdout data source.
    """
    if source is None:
        text = SOURCE_PATH.read_text()
    elif isinstance(source, Path):
        text = source.read_text()
    else:
        text = source
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
    hits = sorted(used & set(HOLDOUT_LOADER_SYMBOLS))
    if hits:
        raise HoldoutAccessError(f'holdout loader symbol used in generator: {hits}')
    bad_imports = sorted(
        name for name in imported
        if any(marker in name.lower() for marker in ('validation', 'holdout'))
        and name.split('.')[-1] != ENFORCEMENT_MODULE_NAME
    )
    if bad_imports:
        raise HoldoutAccessError(f'holdout-looking import in generator: {bad_imports}')
    exempt_literals = set(allow_literals)
    if is_enforcement_point:
        exempt_literals |= set(DECLARED_RESULT_LITERALS)
        exempt_literals |= set(HOLDOUT_DATA_EXTENSIONS) | {DATASET_PATH_MARKER}
    bad_literals = sorted(
        node.value for node in ast.walk(module)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and node.value not in exempt_literals
        and _is_holdout_data_literal(node.value)
    )
    if bad_literals:
        raise HoldoutAccessError(f'holdout-looking data path literal: {bad_literals}')
    return {
        'check': 'self_source_scan_for_holdout_loaders',
        'result': 'PASS',
        'forbidden_symbols': list(HOLDOUT_LOADER_SYMBOLS),
        'hits': [],
        'holdout_looking_imports': [],
        'holdout_looking_data_path_literals': [],
        'exempt_result_path_literals': sorted(exempt_literals),
        'detail': (
            'AST scan: the generator uses none of the forbidden holdout loader symbols, imports no '
            'validation/holdout module and declares no hand-history archive, decision JSONL or fixture '
            'snapshot path'
        ),
        'forbidden_data_path_shapes': [DATASET_PATH_MARKER, *HOLDOUT_DATA_EXTENSIONS],
    }


def verify_guard_is_holdout_free() -> dict[str, Any]:
    """Self-scan of this enforcement module (declared result paths are exempt)."""
    return verify_no_holdout_access(SOURCE_PATH.read_text(), is_enforcement_point=True)


def is_dataset_open(raw: str | Path) -> bool:
    """True when a path is a certified dataset archive or a hand-history file."""
    normalized = str(raw).replace('\\', '/').lower()
    return DATASET_PATH_MARKER in normalized or normalized.endswith(HOLDOUT_DATA_EXTENSIONS)


@contextlib.contextmanager
def dataset_access_tripwire():
    """Record every filesystem open performed while the protocol is built.

    The build may open content-addressed evidence artifacts only.  Opening
    anything under the certified dataset tree, a decision JSONL or a fixture
    snapshot bundle is a boundary break and fails the build; the observed list is
    recorded as evidence.
    """
    opened: list[str] = []
    original_open = pathlib.Path.open

    def guarded_open(self, *args, **kwargs):
        if is_dataset_open(str(self)):
            raise HoldoutAccessError(f'dataset/holdout file opened during protocol build: {self}')
        opened.append(str(self))
        return original_open(self, *args, **kwargs)

    pathlib.Path.open = guarded_open
    try:
        yield opened
    finally:
        pathlib.Path.open = original_open


def relative_open_set(paths: Iterable[str], root: Path | str = ROOT) -> list[str]:
    root = Path(root).resolve()
    resolved = set()
    for raw in paths:
        path = pathlib.Path(raw)
        try:
            resolved.add(str(path.resolve().relative_to(root)))
        except ValueError:
            resolved.add(str(path))
    return sorted(resolved)


def assert_train_only_artifact(name: str, payload: Mapping[str, Any]) -> None:
    """Tripwire: any consumed TRAIN artifact declaring a holdout split aborts."""
    for field in ('validation_consumed', 'test_consumed'):
        if payload.get(field) is True:
            raise HoldoutAccessError(f'{name} declares {field}=true')
    split = payload.get('split_consumed')
    if split not in (None, 'TRAIN'):
        raise HoldoutAccessError(f'{name} declares split_consumed={split!r}')


def _is_holdout_data_literal(value: str) -> bool:
    normalized = value.replace('\\', '/').lower()
    if normalized.endswith(HOLDOUT_DATA_EXTENSIONS):
        return True
    return DATASET_PATH_MARKER in normalized and not normalized.endswith('.json')


def _looks_like_protocol(relative_path: str, payload: Mapping[str, Any]) -> bool:
    if 'protocol' in Path(relative_path).name.lower():
        return True
    if 'protocol' in str(payload.get('schema') or '').lower():
        return True
    kind = str(payload.get('kind') or '')
    if 'PROTOCOL' in kind:
        return True
    return False


def _looks_like_result(payload: Mapping[str, Any]) -> bool:
    return any(marker in payload for marker in RESULT_MARKERS)


def _declares_a_validation_read(payload: Mapping[str, Any]) -> bool:
    if payload.get('validation_consumed') is True:
        return True
    return any(str(payload.get(field) or '') == value
               for field, value in VALIDATION_READ_MARKERS)


def _references_the_candidate(
    payload: Mapping[str, Any],
    tokens: Sequence[str],
) -> bool:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    return any(token in blob for token in tokens)


def validation_result_artifacts(
    root: Path | str = ROOT,
    *,
    candidate_tokens: Sequence[str] = CANDIDATE_REFERENCE_TOKENS,
    declared_locations: Iterable[str] = DECLARED_RESULT_LOCATIONS,
    scan: bool = True,
) -> list[str]:
    """Return every persisted artifact that proves this candidate's holdout was read.

    Two independent detectors run: the explicit declared output locations of the
    future evaluation command, and a content scan of ``analysis/**/*.json`` for
    result-shaped payloads that both declare a VALIDATION read and reference this
    candidate.  Protocol artifacts and other candidates (notably the #352
    exact-price comparator) are excluded by construction.
    """
    root = Path(root)
    hits: list[str] = []
    for relative in declared_locations:
        if (root / relative).is_file():
            hits.append(relative)
    if scan:
        analysis = root / 'analysis'
        if analysis.is_dir():
            for path in sorted(analysis.rglob('*.json')):
                relative = str(path.relative_to(root))
                if relative in hits:
                    continue
                try:
                    payload = json.loads(path.read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    continue
                if not isinstance(payload, dict):
                    continue
                if _looks_like_protocol(relative, payload):
                    continue
                if not _looks_like_result(payload):
                    continue
                if not _declares_a_validation_read(payload):
                    continue
                if not _references_the_candidate(payload, candidate_tokens):
                    continue
                hits.append(relative)
    return sorted(set(hits))


def assert_validation_not_yet_consumed(
    root: Path | str = ROOT,
    *,
    candidate_tokens: Sequence[str] = CANDIDATE_REFERENCE_TOKENS,
    declared_locations: Iterable[str] = DECLARED_RESULT_LOCATIONS,
    scan: bool = True,
) -> dict[str, Any]:
    """Order guard: the freeze aborts if a candidate VALIDATION read already exists."""
    hits = validation_result_artifacts(
        root,
        candidate_tokens=candidate_tokens,
        declared_locations=declared_locations,
        scan=scan,
    )
    declared = [str(rel) for rel in declared_locations]
    if hits:
        raise ValidationOrderError(
            'VALIDATION was already read for the hierarchical candidate; the frozen protocol '
            f'must be authored before any evaluation, offenders: {hits}'
        )
    return {
        'guard_id': 'VALIDATION_ORDER_GUARD',
        'check': 'no_candidate_validation_result_exists_before_freeze',
        'result': 'PASS',
        'declared_result_locations': declared,
        'declared_result_locations_present': [],
        'scanned_tree': 'analysis/**/*.json',
        'excluded_from_scan': (
            'protocol artifacts (schema/kind mentions protocol, or a *protocol* filename) and every '
            'result that does not reference the hierarchical candidate — including the #352 '
            'exact-price comparator, which consumed VALIDATION under its own frozen protocol'
        ),
        'candidate_reference_tokens': list(candidate_tokens),
        'violations': [],
    }


def assert_protocol_frozen_before_validation(
    protocol_path: Path | str,
    *,
    expected_byte_sha256: str | None = None,
    root: Path | str = ROOT,
    candidate_tokens: Sequence[str] = CANDIDATE_REFERENCE_TOKENS,
) -> dict[str, Any]:
    """Evaluation-side guard: fail closed unless the protocol is frozen and unmoved.

    The evaluation command must call this *before* it opens a single VALIDATION
    hand: it re-verifies the persisted protocol bytes against the pinned digest
    and re-runs the ordering guard, so thresholds, comparators and pooling limits
    cannot be edited after the freeze to fit the observed holdout score.
    """
    protocol_path = Path(protocol_path)
    if not protocol_path.is_file():
        raise ValidationOrderError(
            f'no frozen VALIDATION protocol at {protocol_path}; VALIDATION is forbidden'
        )
    payload = json.loads(protocol_path.read_text(encoding='utf-8'))
    if payload.get('schema') != PROTOCOL_SCHEMA:
        raise ValidationOrderError(f'unexpected frozen protocol schema: {payload.get("schema")!r}')
    if payload.get('status') != FROZEN_STATUS:
        raise ValidationOrderError(
            f'protocol must be {FROZEN_STATUS} before evaluation, got {payload.get("status")!r}'
        )
    actual = sha256_file(protocol_path)
    pinned = expected_byte_sha256 or str(payload.get('protocol_byte_sha256') or '') or None
    if pinned and actual != pinned:
        raise ValidationOrderError(
            'frozen VALIDATION protocol was mutated after the freeze: '
            f'{actual} != {pinned}'
        )
    guard = assert_validation_not_yet_consumed(root, candidate_tokens=candidate_tokens)
    frozen_at = payload.get('frozen_at')
    if not frozen_at:
        raise ValidationOrderError('frozen protocol carries no frozen_at timestamp')
    return {
        'guard_id': 'VALIDATION_ORDER_GUARD',
        'result': 'PASS',
        'protocol_byte_sha256': actual,
        'protocol_canonical_payload_sha256': canonical_sha256(payload),
        'frozen_at': frozen_at,
        'order_guard': guard,
    }


__all__ = [
    'CANDIDATE_BYTE_SHA256',
    'CANDIDATE_CANONICAL_SHA256',
    'CANDIDATE_ID',
    'CANDIDATE_INSTANCE_ID',
    'CANDIDATE_REFERENCE_TOKENS',
    'DECLARED_RESULT_LITERALS',
    'DECLARED_RESULT_LOCATIONS',
    'FROZEN_STATUS',
    'HoldoutAccessError',
    'PROTOCOL_SCHEMA',
    'RESULT_DIRECTORY',
    'RESULT_FILENAMES',
    'RESULT_SCHEMA',
    'ROOT',
    'ValidationOrderError',
    'assert_protocol_frozen_before_validation',
    'assert_train_only_artifact',
    'assert_validation_not_yet_consumed',
    'canonical_sha256',
    'dataset_access_tripwire',
    'is_dataset_open',
    'relative_open_set',
    'sha256_file',
    'validation_result_artifacts',
    'verify_guard_is_holdout_free',
    'verify_no_holdout_access',
]
